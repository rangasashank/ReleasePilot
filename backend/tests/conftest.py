import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import password_hasher
from app.db import get_db
from app.main import app
from app.models import Base, User, Workspace


@pytest.fixture
def db() -> Generator[Session]:
    # TEST_DATABASE_URL must identify a disposable database: tables are recreated per test.
    url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    kwargs = (
        {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if url == "sqlite://"
        else {}
    )
    if url != "sqlite://" and not (make_url(url).database or "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must point to a disposable *_test database")
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for index in (1, 2):
            user = User(
                email=f"user{index}@example.com",
                name=f"User {index}",
                password_hash=password_hasher.hash("test-password-long"),
            )
            session.add(user)
            session.flush()
            session.add(Workspace(name=f"Workspace {index}", owner_user_id=user.id))
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db: Session) -> Generator[TestClient]:
    def override_db() -> Generator[Session]:
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def sign_in(client: TestClient, index: int = 1) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/demo/login",
        headers={"Origin": "http://localhost:3000"},
        json={"email": f"user{index}@example.com", "password": "test-password-long"},
    )
    assert response.status_code == 204
    return {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": client.get("/api/v1/me").json()["csrf_token"],
    }


@pytest.fixture(autouse=True)
def no_live_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "openai_api_key", SecretStr(""))
    monkeypatch.setattr(
        get_settings(), "internal_secret", SecretStr("test-internal-secret-at-least-32-characters")
    )
