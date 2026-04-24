"""Lambda handler triggered by S3 ObjectCreated events.

Flow:
    1. S3 PUT triggers an event
    2. Lambda enqueues an ingestion message to SQS
    3. An ECS task or scheduled Prefect job drains SQS and runs the pipeline

Decoupling the trigger from the pipeline keeps Lambda light (under 15min
timeout) and lets us batch-process without Lambda concurrency issues.

Entrypoint:
    handler(event, context)

Expected event shape: standard S3 Event Notification.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3

SQS_QUEUE_URL = os.environ.get("INGEST_QUEUE_URL", "")
MAX_BATCH = 10  # SQS SendMessageBatch limit


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    sqs = boto3.client("sqs")
    messages: list[dict[str, Any]] = []

    for record in event.get("Records", []):
        s3 = record.get("s3", {})
        bucket = s3.get("bucket", {}).get("name")
        key = s3.get("object", {}).get("key")
        size = s3.get("object", {}).get("size", 0)

        if not (bucket and key):
            continue

        messages.append({
            "Id": f"{bucket}-{len(messages)}",
            "MessageBody": json.dumps({
                "bucket": bucket,
                "key": key,
                "size": size,
                "event_name": record.get("eventName"),
                "event_time": record.get("eventTime"),
            }),
            "MessageAttributes": {
                "bucket": {"DataType": "String", "StringValue": bucket},
                "source": {"DataType": "String", "StringValue": "s3-event"},
            },
        })

    sent = 0
    for i in range(0, len(messages), MAX_BATCH):
        chunk = messages[i : i + MAX_BATCH]
        response = sqs.send_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=chunk)
        sent += len(response.get("Successful", []))
        if response.get("Failed"):
            print(f"SQS send failures: {response['Failed']}")

    return {"statusCode": 200, "messagesSent": sent, "totalRecords": len(event.get("Records", []))}
