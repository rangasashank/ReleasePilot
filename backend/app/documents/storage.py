from pathlib import Path
from typing import Any

import boto3

from app.config import get_settings


def aws_client(service: str) -> Any:
    settings = get_settings()
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs.update(
            endpoint_url=settings.aws_endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    return boto3.client(service, **kwargs)


def put_object(key: str, content: bytes) -> None:
    settings = get_settings()
    if settings.object_backend == "s3":
        aws_client("s3").put_object(
            Bucket=settings.s3_bucket, Key=key, Body=content, ServerSideEncryption="AES256"
        )
    else:
        path = Path(settings.local_object_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def get_object(key: str) -> bytes:
    settings = get_settings()
    if settings.object_backend == "s3":
        return bytes(aws_client("s3").get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read())
    return (Path(settings.local_object_dir) / key).read_bytes()
