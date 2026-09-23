import uuid
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.documents.storage import get_object, put_object
from app.jobs.queue import SQSQueue
from app.jobs.state import enqueue
from app.jobs.worker import dispatch_outbox
from app.models import OutboxEvent, Workspace


@mock_aws
def test_s3_round_trip_and_sqs_outbox(db: Session) -> None:
    settings = get_settings()
    s3 = boto3.client("s3", region_name="us-west-2")
    s3.create_bucket(
        Bucket="releasepilot-documents",
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
    )
    sqs = boto3.client("sqs", region_name="us-west-2")
    url = sqs.create_queue(QueueName="analysis")["QueueUrl"]
    workspace = db.scalar(select(Workspace))
    assert workspace
    job = enqueue(db, workspace.id, "index", str(uuid.uuid4()), {})
    db.commit()
    with (
        patch.object(settings, "object_backend", "s3"),
        patch.object(settings, "sqs_queue_url", url),
        patch("app.jobs.worker.get_engine", return_value=db.get_bind()),
    ):
        put_object("workspace/runbook.md", b"# Rollback\nRestore image")
        assert get_object("workspace/runbook.md") == b"# Rollback\nRestore image"
        with patch.object(SQSQueue, "send", side_effect=RuntimeError("network down")):
            with pytest.raises(RuntimeError):
                dispatch_outbox()
        db.expire_all()
        event = db.scalar(select(OutboxEvent))
        assert event and event.published_at is None
        dispatch_outbox()
        db.expire_all()
        assert event.published_at is not None
        message = SQSQueue().receive()[0]
        assert str(job.id) in message["Body"]
        SQSQueue().delete(message["ReceiptHandle"])
        assert (
            sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])[
                "Attributes"
            ]["ApproximateNumberOfMessages"]
            == "0"
        )
