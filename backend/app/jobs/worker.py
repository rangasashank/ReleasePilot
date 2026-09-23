"""At-least-once dispatcher with a transactional outbox and fenced publication."""

import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.documents.storage import aws_client
from app.errors import IntegrationError, LeaseLost
from app.jobs.pipeline import index_document, run_analysis
from app.jobs.queue import SQSQueue
from app.jobs.state import claim, locked_job
from app.models import Analysis, Document, Job, OutboxEvent

logger = logging.getLogger("releasepilot.worker")


def heartbeat(
    job_id: uuid.UUID, owner: str, stop: threading.Event, receipt: str | None = None
) -> None:
    while not stop.wait(30):
        with Session(get_engine()) as db:
            db.execute(
                update(Job)
                .where(
                    Job.id == job_id,
                    Job.lease_owner == owner,
                    Job.state == "RUNNING",
                    Job.lease_expires_at > datetime.now(UTC),
                )
                .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=120))
            )
            db.commit()
        if receipt:
            try:
                SQSQueue().renew(receipt)
            except Exception:
                logger.warning("queue_visibility_renewal_failed job_id=%s", job_id)


def process(job_id: uuid.UUID, receipt: str | None = None) -> bool:
    with Session(get_engine()) as db:
        owner = claim(db, job_id)
        if not owner:
            job = db.get(Job, job_id)
            return not job or job.state in ("COMPLETED", "FAILED")
        job = db.get(Job, job_id)
        assert job
        kind = job.kind
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job_id, owner, stop, receipt), daemon=True)
    thread.start()
    try:
        if kind == "analysis":
            run_analysis(job_id, owner)
        elif kind == "index":
            index_document(job_id, owner)
        elif kind == "webhook":
            from app.webhooks.router import process_delivery

            process_delivery(job_id, owner)
        else:
            raise IntegrationError("UNKNOWN_JOB", "Unknown job kind")
    except LeaseLost:
        return False
    except Exception as exc:
        with Session(get_engine()) as db:
            try:
                job = locked_job(db, job_id, owner)
            except LeaseLost:
                return False
            retryable = not isinstance(exc, IntegrationError) or exc.retry_after is not None
            failed = job.attempts >= get_settings().max_job_attempts or not retryable
            delay = exc.retry_after if isinstance(exc, IntegrationError) else None
            job.state = "FAILED" if failed else "WAITING"
            job.last_error_code = exc.code if isinstance(exc, IntegrationError) else "WORKER_ERROR"
            job.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=delay or min(300, 2**job.attempts)
            )
            job.lease_owner, job.lease_expires_at = None, None
            if job.analysis_id:
                analysis = db.get(Analysis, job.analysis_id)
                assert analysis
                analysis.state = job.state
            if kind == "index" and failed:
                doc = db.get(Document, uuid.UUID(str(job.payload["document_id"])))
                if doc:
                    doc.status, doc.error_code = "FAILED", job.last_error_code
            if not failed or get_settings().sqs_dlq_url:
                db.add(
                    OutboxEvent(
                        job_id=job_id, due_at=datetime.now(UTC) if failed else job.next_attempt_at
                    )
                )
            db.commit()
            logger.warning(
                "job_failed job_id=%s code=%s terminal=%s", job_id, job.last_error_code, failed
            )
    finally:
        stop.set()
        thread.join(timeout=2)
    return True


def dispatch_outbox() -> None:
    with Session(get_engine()) as db:
        events = db.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None), OutboxEvent.due_at <= datetime.now(UTC))
            .with_for_update(skip_locked=True)
            .limit(20)
        ).all()
        for event in events:
            job = db.get(Job, event.job_id)
            if job and job.state == "FAILED" and get_settings().sqs_dlq_url:
                aws_client("sqs").send_message(
                    QueueUrl=get_settings().sqs_dlq_url,
                    MessageBody=json.dumps({"job_id": str(event.job_id)}),
                )
            else:
                SQSQueue().send(str(event.job_id))
            event.published_at = datetime.now(UTC)
        db.commit()  # Crash after send is safe: duplicate messages are fenced by claim().


def due_jobs() -> list[uuid.UUID]:
    with Session(get_engine()) as db:
        return list(
            db.scalars(
                select(Job.id)
                .where(
                    Job.state.in_(["READY", "WAITING", "RUNNING"]),
                    Job.next_attempt_at <= datetime.now(UTC),
                    or_(Job.lease_expires_at.is_(None), Job.lease_expires_at < datetime.now(UTC)),
                )
                .order_by(Job.next_attempt_at)
                .limit(20)
            )
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    last_reconcile = 0.0
    while True:
        try:
            if get_settings().queue_backend == "sqs":
                dispatch_outbox()
                for message in SQSQueue().receive():
                    try:
                        job_id = uuid.UUID(json.loads(message["Body"])["job_id"])
                    except (ValueError, KeyError, TypeError):
                        SQSQueue().delete(message["ReceiptHandle"])
                        continue
                    if process(job_id, message["ReceiptHandle"]):
                        SQSQueue().delete(message["ReceiptHandle"])
                # Repair lost queue messages and workers killed after visibility expiry.
                if time.monotonic() - last_reconcile > 60:
                    for job_id in due_jobs():
                        SQSQueue().send(str(job_id))
                    last_reconcile = time.monotonic()
            else:
                for job_id in due_jobs():
                    process(job_id)
                time.sleep(1)
        except Exception:
            logger.warning("worker_dependency_unavailable")
            time.sleep(5)


if __name__ == "__main__":
    main()
