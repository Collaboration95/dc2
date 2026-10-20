"""Only opt-in local emulator fixtures. Never infer an AWS account endpoint."""

import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest


@pytest.fixture
def sqs_local():
    endpoint = os.environ.get("V1_TEST_SQS_ENDPOINT")
    if not endpoint:
        pytest.skip("Lead C's explicit local SQS emulator endpoint not provided")
    parsed = urlsplit(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Messaging tests require a loopback-only emulator endpoint")
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "sqs",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="local-test",
        aws_secret_access_key="local-test",
        config=Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 1}),
    )
    prefix = "b-msg-" + uuid4().hex
    urls, all_urls = {}, []
    try:
        for lane in ("processing-commands", "processing-work", "media-results"):
            dlq = client.create_queue(
                QueueName=f"{prefix}-{lane}-dlq", Attributes={"MessageRetentionPeriod": "1209600"}
            )["QueueUrl"]
            all_urls.append(dlq)
            arn = client.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])[
                "Attributes"
            ]["QueueArn"]
            queue = client.create_queue(
                QueueName=f"{prefix}-{lane}",
                Attributes={
                    "MessageRetentionPeriod": "604800",
                    "VisibilityTimeout": "1",
                    "RedrivePolicy": json.dumps({"deadLetterTargetArn": arn, "maxReceiveCount": 2}),
                },
            )["QueueUrl"]
            all_urls.append(queue)
            urls[lane], urls[lane + "-dlq"] = queue, dlq
        yield client, urls
    finally:
        for url in reversed(all_urls):
            client.delete_queue(QueueUrl=url)
        client.close()
