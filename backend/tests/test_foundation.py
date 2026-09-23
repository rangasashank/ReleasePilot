from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, token_digest
from app.models import UserSession
from tests.conftest import sign_in


def test_health_and_unauthenticated_access(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    for path in ("/me", "/services", "/setup/status"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHENTICATED"
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_login_cookie_is_opaque_and_logout_revokes_session(client: TestClient, db: Session) -> None:
    headers = sign_in(client)
    raw_token = client.cookies[COOKIE_NAME]
    assert db.get(UserSession, raw_token) is None
    assert db.get(UserSession, token_digest(raw_token)) is not None
    response = client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    client.cookies.set(COOKIE_NAME, raw_token)
    assert client.get("/api/v1/me").status_code == 401


def test_login_rejects_bad_credentials_and_cross_origin(client: TestClient) -> None:
    data = {"email": "user1@example.com", "password": "wrong"}
    assert client.post("/api/v1/auth/demo/login", json=data).status_code == 403
    response = client.post(
        "/api/v1/auth/demo/login", json=data, headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 401
    assert "password" not in response.json()


def test_create_persist_and_scope_service(client: TestClient, db: Session) -> None:
    headers = sign_in(client)
    response = client.post(
        "/api/v1/services",
        headers=headers,
        json={"name": "Checkout API", "description": "Payments"},
    )
    assert response.status_code == 201
    service_id = response.json()["id"]
    db.expire_all()
    assert client.get("/api/v1/services").json()[0]["name"] == "Checkout API"
    assert client.get("/api/v1/setup/status").json()["service_count"] == 1
    assert (
        client.post("/api/v1/services", headers=headers, json={"name": "Checkout API"}).status_code
        == 409
    )
    sign_in(client, 2)
    assert client.get("/api/v1/services").json() == []
    assert client.get(f"/api/v1/services/{service_id}").status_code == 404
    assert client.get("/api/v1/setup/status").json()["service_count"] == 0


def test_mutations_require_csrf_and_reject_workspace_injection(client: TestClient) -> None:
    headers = sign_in(client)
    assert client.post("/api/v1/services", json={"name": "API"}).status_code == 403
    assert (
        client.post(
            "/api/v1/services", headers={**headers, "X-CSRF-Token": "bad"}, json={"name": "API"}
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/services",
        headers=headers,
        json={"name": "API", "workspace_id": "attacker-selected"},
    )
    assert response.status_code == 422
    assert client.post("/api/v1/services", headers=headers, json={"name": "   "}).status_code == 422


def test_expired_session_rejected(client: TestClient, db: Session) -> None:
    sign_in(client)
    session = db.scalar(select(UserSession))
    assert session
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_cookie_flags(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/demo/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": "user1@example.com", "password": "test-password-long"},
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=" in cookie


def test_pagination_validation(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/api/v1/services?limit=10000").status_code == 422
    assert client.get("/api/v1/services?offset=-1").status_code == 422
