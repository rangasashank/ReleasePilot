import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.analyses.router import router as analyses_router
from app.auth import (
    COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    Identity,
    current_identity,
    mutation_identity,
    password_hasher,
    require_origin,
    token_digest,
)
from app.config import get_settings
from app.db import get_db
from app.documents.router import router as documents_router
from app.errors import IntegrationError
from app.github.router import router as github_router
from app.jobs.router import router as jobs_router
from app.models import LoginAttempt, Service, User, UserSession
from app.schemas import LoginInput, MeOutput, ServiceInput, ServiceOutput, SetupOutput
from app.services import (
    ServiceConflict,
    ServiceNotFound,
    create_service,
    get_service,
    list_services,
)
from app.webhooks.router import router as webhooks_router

app = FastAPI(title="ReleasePilot API", version="0.1.0")
app.include_router(analyses_router)
app.include_router(github_router)
app.include_router(documents_router)
app.include_router(jobs_router)
app.include_router(webhooks_router)
logger = logging.getLogger("releasepilot")


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request.state.request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        # Do not log exception payloads: database errors may include sensitive parameters.
        logger.error("unhandled_request request_id=%s", request.state.request_id)
        response = error_response(request, 500, "INTERNAL_ERROR", "Something went wrong")
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "request_id": request.state.request_id},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}
    return error_response(
        request, exc.status_code, codes.get(exc.status_code, "REQUEST_ERROR"), str(exc.detail)
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, "VALIDATION_ERROR", "Check the submitted fields")


@app.exception_handler(ServiceConflict)
async def service_conflict(request: Request, exc: ServiceConflict) -> JSONResponse:
    return error_response(request, 409, "CONFLICT", str(exc))


@app.exception_handler(ServiceNotFound)
async def service_not_found(request: Request, exc: ServiceNotFound) -> JSONResponse:
    return error_response(request, 404, "NOT_FOUND", str(exc))


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> Response:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready"})


@app.post("/api/v1/auth/demo/login", status_code=204)
def login(
    data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)
) -> None:
    require_origin(request)
    key = token_digest(data.email.strip().lower())
    attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key).with_for_update())
    now = datetime.now(UTC)
    if attempt and attempt.window_start.replace(tzinfo=UTC) < now - timedelta(minutes=10):
        attempt.count, attempt.window_start = 0, now
    if attempt and attempt.count >= 10:
        raise HTTPException(429, "Too many login attempts; try again in ten minutes")
    if not attempt:
        attempt = LoginAttempt(key=key, count=0)
        db.add(attempt)
    attempt.count += 1
    db.commit()
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    valid = password_hasher.verify(
        data.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if not user or not valid:
        raise HTTPException(401, "Incorrect email or password")
    attempt.count = 0
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=token_digest(raw_token),
            user_id=user.id,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
    )


@app.get("/api/v1/me", response_model=MeOutput)
def me(identity: Identity = Depends(current_identity)) -> MeOutput:
    return MeOutput(
        user_id=identity.user.id,
        name=identity.user.name,
        email=identity.user.email,
        workspace_id=identity.workspace.id,
        workspace_name=identity.workspace.name,
        csrf_token=identity.session.csrf_token,
    )


@app.post("/api/v1/auth/logout", status_code=204)
def logout(
    response: Response,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> None:
    db.delete(identity.session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@app.get("/api/v1/setup/status", response_model=SetupOutput)
def setup(
    identity: Identity = Depends(current_identity), db: Session = Depends(get_db)
) -> SetupOutput:
    count = (
        db.scalar(
            select(func.count())
            .select_from(Service)
            .where(Service.workspace_id == identity.workspace.id)
        )
        or 0
    )
    return SetupOutput(service_count=count)


@app.get("/api/v1/services", response_model=list[ServiceOutput])
def services(
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[Service]:
    return list_services(db, identity.workspace.id, limit, offset)


@app.post("/api/v1/services", response_model=ServiceOutput, status_code=201)
def add_service(
    data: ServiceInput,
    identity: Identity = Depends(mutation_identity),
    db: Session = Depends(get_db),
) -> Service:
    return create_service(db, identity.workspace.id, data)


@app.get("/api/v1/services/{service_id}", response_model=ServiceOutput)
def service_detail(
    service_id: uuid.UUID,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> Service:
    return get_service(db, identity.workspace.id, service_id)


@app.exception_handler(IntegrationError)
async def integration_error(request: Request, exc: IntegrationError) -> JSONResponse:
    response = error_response(request, 503 if exc.retry_after else 422, exc.code, str(exc))
    if exc.retry_after:
        response.headers["Retry-After"] = str(exc.retry_after)
    return response
