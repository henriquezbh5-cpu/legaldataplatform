"""Lambda that consumes the ingest SQS queue and kicks off Prefect flows.

Uses the Prefect REST API to create a flow run rather than importing the
flow directly — this keeps the Lambda deployment package tiny.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3
import httpx

PREFECT_API_URL = os.environ["PREFECT_API_URL"]
PREFECT_DEPLOYMENT_ID = os.environ["PREFECT_DEPLOYMENT_ID"]
PREFECT_API_KEY = os.environ.get("PREFECT_API_KEY")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    sqs = boto3.client("sqs")
    processed: list[str] = []
    failed: list[dict[str, str]] = []

    for record in event.get("Records", []):
        receipt = record["receiptHandle"]
        try:
            payload = json.loads(record["body"])
            _trigger_prefect_flow(payload)
            processed.append(record["messageId"])
        except Exception as e:  # noqa: BLE001
            failed.append({"itemIdentifier": record["messageId"], "reason": str(e)})

    # Partial batch response — SQS only re-sends failed items
    return {"batchItemFailures": failed, "processed": len(processed)}


def _trigger_prefect_flow(payload: dict[str, Any]) -> None:
    headers = {"Content-Type": "application/json"}
    if PREFECT_API_KEY:
        headers["Authorization"] = f"Bearer {PREFECT_API_KEY}"

    body = {
        "parameters": {
            "bucket": payload["bucket"],
            "key": payload["key"],
        },
        "name": f"s3-triggered-{payload['bucket']}-{payload['key'][:20]}",
    }
    response = httpx.post(
        f"{PREFECT_API_URL}/deployments/{PREFECT_DEPLOYMENT_ID}/create_flow_run",
        json=body,
        headers=headers,
        timeout=15.0,
    )
    response.raise_for_status()
