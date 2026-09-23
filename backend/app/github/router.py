import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, current_identity, mutation_identity, token_digest
from app.config import get_settings
from app.db import get_db
from app.github.client import GitHubClient
from app.models import GitHubGrant, OAuthState, Repository

router = APIRouter(prefix="/api/v1/github", tags=["github"])


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
    mode: Literal["public", "app"] = "app"
    installation_id: int | None = Field(default=None, ge=1)


def owned_repository(
    db: Session, workspace_id: uuid.UUID, repository_id: uuid.UUID | None = None
) -> Repository:
    query = select(Repository).where(Repository.workspace_id == workspace_id)
    if repository_id:
        query = query.where(Repository.id == repository_id)
    repo = db.scalar(query)
    if not repo:
        raise HTTPException(404, "No repository connected")
    return repo


def repository_output(repo: Repository) -> dict[str, Any]:
    return {
        "id": str(repo.id),
        "full_name": repo.full_name,
        "default_branch": repo.default_branch,
        "status": repo.status,
        "auth_mode": repo.auth_mode,
        "installation_id": repo.installation_id,
        "last_checked_at": repo.last_checked_at,
    }


@router.get("/connection")
def connection(
    identity: Identity = Depends(current_identity), db: Session = Depends(get_db)
) -> dict[str, Any]:
    settings = get_settings()
    repo = db.scalar(select(Repository).where(Repository.workspace_id == identity.workspace.id))
    grant = db.get(GitHubGrant, identity.workspace.id)
    ids = (
        grant.installation_ids
        if grant and grant.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
        else []
    )
    return {
        "repository": repository_output(repo) if repo else None,
        "app_configured": bool(settings.github_client_id and settings.github_app_id),
        "install_url": f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        if settings.github_app_slug
        else None,
        "authorized_installations": ids,
    }


@router.get("/authorize")
def authorize(
    identity: Identity = Depends(current_identity), db: Session = Depends(get_db)
) -> RedirectResponse:
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(409, "Configure GitHub App OAuth credentials first")
    state = secrets.token_urlsafe(32)
    db.add(
        OAuthState(
            token_hash=token_digest(state),
            workspace_id=identity.workspace.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    db.commit()
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": settings.app_origin + "/api/v1/github/callback",
            "state": state,
        }
    )
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        "github_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=600,
        path="/api/v1/github",
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    code: str = Query(max_length=300),
    state: str = Query(max_length=200),
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    saved = db.get(OAuthState, token_digest(state))
    if (
        not saved
        or saved.workspace_id != identity.workspace.id
        or saved.expires_at.replace(tzinfo=UTC) < datetime.now(UTC)
        or not secrets.compare_digest(request.cookies.get("github_state", ""), state)
    ):
        raise HTTPException(403, "Invalid or expired GitHub authorization state")
    db.delete(saved)
    db.commit()
    settings = get_settings()
    with httpx.Client(timeout=15) as client:
        response = client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": settings.app_origin + "/api/v1/github/callback",
            },
        )
        token = response.json().get("access_token")
        if not token:
            raise HTTPException(403, "GitHub authorization failed")
        # User-to-installation membership is verified with GitHub, never trusted from callback JSON.
        installations = client.get(
            "https://api.github.com/user/installations",
            params={"per_page": 100},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        if installations.status_code != 200:
            raise HTTPException(403, "Could not verify your GitHub installations")
        ids = [item["id"] for item in installations.json().get("installations", [])]
    grant = db.get(GitHubGrant, identity.workspace.id)
    if not grant:
        grant = GitHubGrant(workspace_id=identity.workspace.id)
        db.add(grant)
    grant.installation_ids = ids
    grant.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()
    result = RedirectResponse(settings.app_origin + "/settings", status_code=303)
    result.delete_cookie("github_state", path="/api/v1/github")
    return result


@router.post("/connect")
def connect(
    data: ConnectionInput,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    existing = db.scalar(select(Repository).where(Repository.workspace_id == identity.workspace.id))
    if existing and existing.full_name.lower() != data.full_name.lower():
        raise HTTPException(
            409, "This workspace already has a repository. One repository is supported."
        )
    if data.mode == "app":
        grant = db.get(GitHubGrant, identity.workspace.id)
        if (
            not grant
            or grant.expires_at.replace(tzinfo=UTC) < datetime.now(UTC)
            or data.installation_id not in grant.installation_ids
        ):
            raise HTTPException(403, "Authorize this GitHub installation before connecting it")
    repo = Repository(
        workspace_id=identity.workspace.id,
        full_name=data.full_name,
        installation_id=data.installation_id if data.mode == "app" else None,
        github_id=0,
        default_branch="",
        auth_mode=data.mode,
    )
    client = GitHubClient(repo)
    try:
        metadata = client.get(client.prefix, fresh=True)
    finally:
        client.close()
    if data.mode == "public" and metadata.get("private"):
        raise HTTPException(403, "Public mode only supports public repositories")
    target = existing or repo
    target.full_name = metadata["full_name"]
    target.github_id = metadata["id"]
    target.default_branch = metadata["default_branch"]
    target.installation_id = repo.installation_id
    target.auth_mode = data.mode
    target.status = "connected"
    target.last_checked_at = datetime.now(UTC)
    db.add(target)
    db.commit()
    return repository_output(target)


@router.get("/refs")
def refs(
    identity: Identity = Depends(current_identity), db: Session = Depends(get_db)
) -> dict[str, Any]:
    repo = owned_repository(db, identity.workspace.id)
    client = GitHubClient(repo)
    try:
        branches, complete_b = client.pages(client.prefix + "/branches", max_pages=1)
        tags, complete_t = client.pages(client.prefix + "/tags", max_pages=1)
        return {
            "refs": [
                {"name": item["name"], "kind": kind, "sha": item["commit"]["sha"]}
                for kind, items in [("branch", branches), ("tag", tags)]
                for item in items
            ],
            "complete": complete_b and complete_t,
        }
    finally:
        client.close()
