"""Thin async wrapper around aioboto3 S3 client.

Centralizing S3 access here lets us:
- Swap the endpoint between MinIO (dev) and AWS (prod) via config
- Apply consistent server-side encryption
- Add tracing / metrics in one place
- Mock the client cleanly for unit tests (via moto)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import aioboto3

from src.config import get_settings


@asynccontextmanager
async def s3_client() -> Any:
    """Yield a boto3 S3 client honoring MinIO endpoint when set."""
    settings = get_settings()
    session = aioboto3.Session(
        aws_access_key_id=settings.aws.access_key_id,
        aws_secret_access_key=settings.aws.secret_access_key,
        region_name=settings.aws.region,
    )

    client_kwargs: dict[str, Any] = {"service_name": "s3"}
    if settings.aws.s3_endpoint:
        client_kwargs["endpoint_url"] = settings.aws.s3_endpoint

    async with session.client(**client_kwargs) as client:
        yield client


async def put_object(
    bucket: str,
    key: str,
    body: bytes,
    content_type: str = "application/octet-stream",
    sse: str | None = "AES256",
) -> dict[str, Any]:
    """Upload an object with server-side encryption."""
    async with s3_client() as s3:
        kwargs: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if sse:
            kwargs["ServerSideEncryption"] = sse
        return await s3.put_object(**kwargs)


async def list_keys(bucket: str, prefix: str = "") -> list[str]:
    """List all object keys under a prefix (paginated)."""
    keys: list[str] = []
    async with s3_client() as s3:
        paginator = s3.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                keys.append(item["Key"])
    return keys


async def object_exists(bucket: str, key: str) -> bool:
    """Return True if the object exists."""
    async with s3_client() as s3:
        try:
            await s3.head_object(Bucket=bucket, Key=key)
            return True
        except s3.exceptions.ClientError:
            return False


async def delete_prefix(bucket: str, prefix: str) -> int:
    """Delete all objects under a prefix. Returns count deleted."""
    keys = await list_keys(bucket, prefix)
    if not keys:
        return 0
    async with s3_client() as s3:
        # S3 DeleteObjects supports up to 1000 keys per request
        deleted = 0
        for i in range(0, len(keys), 1000):
            chunk = keys[i : i + 1000]
            await s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in chunk]},
            )
            deleted += len(chunk)
        return deleted
