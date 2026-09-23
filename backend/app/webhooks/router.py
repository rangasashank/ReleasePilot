import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, get_engine
from app.github.client import GitHubClient, invalidate
from app.jobs.state import enqueue, locked_job
from app.models import Analysis, ReleaseCandidate, Repository, WebhookDelivery

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/github", status_code=202)
async def receive(request: Request, db: Session = Depends(get_db)) -> dict[str, bool]:
    secret = get_settings().github_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(503, "Webhook secret is not configured")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1_000_000:
            raise HTTPException(413, "Webhook too large")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, request.headers.get("x-hub-signature-256", "")):
        raise HTTPException(401, "Invalid webhook signature")
    delivery_id = request.headers.get("x-github-delivery", "")
    event = request.headers.get("x-github-event", "")
    if not delivery_id or len(delivery_id) > 100 or len(event) > 80:
        raise HTTPException(422, "Invalid delivery metadata")
    try:
        payload: dict[str, Any] = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid webhook payload") from None
    repo_id = (payload.get("repository") or {}).get("id")
    install_id = (payload.get("installation") or {}).get("id")
    repos = db.scalars(
        select(Repository).where(Repository.github_id == repo_id)
        if repo_id
        else select(Repository).where(
            Repository.installation_id == install_id, Repository.installation_id.is_not(None)
        )
    ).all()
    # Store routing metadata only; payload bodies are unnecessary.
    delivery = WebhookDelivery(
        delivery_id=delivery_id,
        event_type=event,
        payload={"repository_id": repo_id, "installation_id": install_id},
        state="RECEIVED" if repos else "IGNORED",
    )
    db.add(delivery)
    try:
        db.flush()
        for repo in repos:
            enqueue(
                db,
                repo.workspace_id,
                "webhook",
                f"webhook:{delivery_id}:{repo.id}",
                {"delivery_id": delivery_id, "repository_id": str(repo.id)},
            )
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"accepted": True}


def process_delivery(job_id: uuid.UUID, owner: str) -> None:
    with Session(get_engine()) as db:
        job = locked_job(db, job_id, owner)
        repo = db.get(Repository, uuid.UUID(str(job.payload["repository_id"])))
        assert repo and repo.workspace_id == job.workspace_id
        delivery = db.get(WebhookDelivery, str(job.payload["delivery_id"]))
        assert delivery
        invalidate(repo)
        # Fresh provider state, not the delivery's possibly older snapshot, drives connection state.
        db.commit()
        checked_at = datetime.now(UTC)
        client = GitHubClient(repo)
        try:
            client.get(f"/repos/{repo.full_name}", fresh=True)
            connected = True
        except Exception as exc:
            from app.errors import IntegrationError

            if isinstance(exc, IntegrationError) and exc.code in (
                "GITHUB_PERMISSION",
                "GITHUB_AUTH",
                "GITHUB_NOT_FOUND",
                "GITHUB_UNAUTHORIZED",
            ):
                connected = False
            else:
                raise
        finally:
            client.close()
        locked_job(db, job_id, owner)
        repo = db.scalar(
            select(Repository)
            .where(Repository.id == repo.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert repo
        if checked_at >= repo.last_checked_at.replace(tzinfo=UTC):
            repo.status = "connected" if connected else "disconnected"
            repo.last_checked_at = checked_at
        analyses = db.scalars(
            select(Analysis)
            .join(ReleaseCandidate)
            .where(
                ReleaseCandidate.repository_id == repo.id,
                Analysis.workspace_id == repo.workspace_id,
            )
        )
        for analysis in analyses:
            analysis.stale = (
                True  # One-way annotation; never mutate captured facts or a completed decision.
            )
        delivery.state = "PROCESSED"
        job.state, job.stage, job.lease_owner, job.lease_expires_at = (
            "COMPLETED",
            "INVALIDATED",
            None,
            None,
        )
        db.commit()
