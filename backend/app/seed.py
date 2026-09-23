from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import password_hasher
from app.config import get_settings
from app.db import get_engine
from app.models import User, Workspace


def seed() -> None:
    settings = get_settings()
    if len(settings.demo_password) < 12:
        raise SystemExit("Set DEMO_PASSWORD to at least 12 characters before seeding")
    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == settings.demo_email.lower()))
        if user:
            print("Demo account already exists; existing credentials preserved.")
            return
        user = User(
            email=settings.demo_email.lower(),
            name="Demo developer",
            password_hash=password_hasher.hash(settings.demo_password),
        )
        db.add(user)
        db.flush()
        db.add(Workspace(name="Demo workspace", owner_user_id=user.id))
        db.commit()
    print("Demo account and workspace created.")


if __name__ == "__main__":
    seed()
