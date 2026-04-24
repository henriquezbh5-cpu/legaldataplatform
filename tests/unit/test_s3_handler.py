"""Unit tests for the S3 handler against a mocked S3 (moto)."""

from __future__ import annotations

import pytest
from moto import mock_aws

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_S3_ENDPOINT", raising=False)


async def test_put_and_list_object():
    """Moto's @mock_aws decorator is sync-only, so we use it as a
    context manager to keep the async function native for pytest-asyncio."""
    import boto3

    with mock_aws():
        from src.aws.s3 import list_keys, put_object

        # Clear any cached settings so the in-test env vars take effect
        from src.config import get_settings

        get_settings.cache_clear()

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

        await put_object("test-bucket", "prefix/file.txt", b"hello", sse=None)
        keys = await list_keys("test-bucket", prefix="prefix/")
        assert keys == ["prefix/file.txt"]


async def test_object_exists_returns_false_for_missing():
    import boto3

    with mock_aws():
        from src.aws.s3 import object_exists
        from src.config import get_settings

        get_settings.cache_clear()

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket2")
        assert await object_exists("test-bucket2", "nope.txt") is False
