"""SQS transports IDs only; PostgreSQL is the durable job authority."""

import json
from typing import Protocol

from app.config import get_settings
from app.documents.storage import aws_client


class JobQueue(Protocol):
    def send(self, job_id: str) -> None: ...


class SQSQueue:
    def send(self, job_id: str) -> None:
        aws_client("sqs").send_message(
            QueueUrl=get_settings().sqs_queue_url, MessageBody=json.dumps({"job_id": job_id})
        )

    def receive(self) -> list[dict[str, str]]:
        response = aws_client("sqs").receive_message(
            QueueUrl=get_settings().sqs_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5,
            VisibilityTimeout=120,
        )
        return list(response.get("Messages", []))

    def renew(self, receipt: str) -> None:
        aws_client("sqs").change_message_visibility(
            QueueUrl=get_settings().sqs_queue_url, ReceiptHandle=receipt, VisibilityTimeout=120
        )

    def delete(self, receipt: str) -> None:
        aws_client("sqs").delete_message(
            QueueUrl=get_settings().sqs_queue_url, ReceiptHandle=receipt
        )
