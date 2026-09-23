import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.errors import LeaseLost
from app.models import Job, OutboxEvent


def enqueue(
    db: Session,
    workspace_id: uuid.UUID,
    kind: str,
    key: str,
    payload: dict[str, Any],
    analysis_id: uuid.UUID | None = None,
) -> Job:
    job = Job(
        workspace_id=workspace_id,
        kind=kind,
        operation_key=key,
        payload=payload,
        analysis_id=analysis_id,
    )
    db.add(job)
    db.flush()
    db.add(OutboxEvent(job_id=job.id))
    return job


def claim(db: Session, job_id: uuid.UUID) -> str | None:
    owner = uuid.uuid4().hex
    now = datetime.now(UTC)
    result = db.execute(
        update(Job)
        .execution_options(synchronize_session="fetch")
        .where(
            Job.id == job_id,
            Job.next_attempt_at <= now,
            Job.state.in_(["READY", "WAITING", "RUNNING"]),
            or_(Job.lease_expires_at.is_(None), Job.lease_expires_at < now),
        )
        .values(
            state="RUNNING",
            lease_owner=owner,
            lease_expires_at=now + timedelta(seconds=120),
            attempts=Job.attempts + 1,
        )
    )
    db.commit()
    return owner if result.rowcount else None  # type: ignore[attr-defined]


def locked_job(db: Session, job_id: uuid.UUID, owner: str) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job or job.lease_owner != owner or job.state != "RUNNING":
        raise LeaseLost()
    if not job.lease_expires_at or job.lease_expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise LeaseLost()
    return job


def checkpoint(
    db: Session, job_id: uuid.UUID, owner: str, name: str, value: dict[str, Any]
) -> None:
    job = locked_job(db, job_id, owner)
    job.checkpoints = {**job.checkpoints, name: value}
    job.stage = name
    db.commit()
