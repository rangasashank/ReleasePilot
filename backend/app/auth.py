import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession, Workspace

password_hasher = PasswordHash.recommended()
# Equalize password verification work for unknown accounts.
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))
COOKIE_NAME = "releasepilot_session"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_origin(request: Request) -> None:
    if request.headers.get("origin") != get_settings().app_origin:
        raise HTTPException(403, "Untrusted request origin")


@dataclass
class Identity:
    user: User
    workspace: Workspace
    session: UserSession


def current_identity(request: Request, db: Session = Depends(get_db)) -> Identity:
    token = request.cookies.get(COOKIE_NAME)
    session = db.get(UserSession, token_digest(token)) if token else None
    if session is None:
        raise HTTPException(401, "Sign in to continue")
    expiry = session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry <= datetime.now(UTC):
        raise HTTPException(401, "Your session expired. Sign in again")
    user = db.get(User, session.user_id)
    workspace = db.scalar(select(Workspace).where(Workspace.owner_user_id == session.user_id))
    if user is None or workspace is None:
        raise HTTPException(401, "Account unavailable")
    return Identity(user, workspace, session)


def mutation_identity(request: Request, identity: Identity = Depends(current_identity)) -> Identity:
    require_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(supplied, identity.session.csrf_token):
        raise HTTPException(403, "Invalid CSRF token. Refresh and try again")
    return identity
