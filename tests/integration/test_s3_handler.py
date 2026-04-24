"""Integration tests against a mocked S3 (moto)."""
from __future__ import annotations

import os

import pytest
from moto import mock_aws

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_S3_ENDPOINT", raising=False)


@mock_aws
async def test_put_and_list_object():
    from src.aws.s3 import list_keys, put_object, s3_client

    # Create bucket via sync boto for test setup
    import boto3
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket")

    await put_object("test-bucket", "prefix/file.txt", b"hello", sse=None)
    keys = await list_keys("test-bucket", prefix="prefix/")
    assert keys == ["prefix/file.txt"]


@mock_aws
async def test_object_exists_returns_false_for_missing():
    from src.aws.s3 import object_exists
    import boto3
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="test-bucket2")
    assert await object_exists("test-bucket2", "nope.txt") is False
