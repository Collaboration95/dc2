"""Opt-in Moto SQS redelivery/redrive checks; no real-AWS guarantees claimed."""

import pytest

from delivery.sqs import SQS, decode
from tests.v1.test_delivery import message

pytestmark = pytest.mark.integration


async def test_emulator_lost_delete_redelivery_stable_content(sqs_local):
    client, urls = sqs_local
    sender = SQS(urls, producer="media", client=client)
    consumer = SQS(urls, consumer="processing-control", client=client)
    body = message()
    await sender.send("processing-commands", body)
    first = (await consumer.receive("processing-commands", wait_seconds=0))[0]
    assert decode(first, "processing-commands") == body
    # Simulate commit followed by a lost delete response: next consumer dedupes
    # the stable application message ID, never the replaceable receipt handle.
    await consumer.visibility("processing-commands", first["ReceiptHandle"], 0)
    second = (await consumer.receive("processing-commands", wait_seconds=0))[0]
    assert decode(second, "processing-commands") == body
    assert second["ReceiptHandle"] != first["ReceiptHandle"]
    await consumer.delete("processing-commands", second["ReceiptHandle"])
    assert not await consumer.receive("processing-commands", wait_seconds=0)


async def test_emulator_poison_redrives_to_matching_dlq(sqs_local):
    client, urls = sqs_local
    consumer = SQS(urls, consumer="processing-control", client=client)
    client.send_message(QueueUrl=urls["processing-commands"], MessageBody="poison-json")
    for _ in range(4):
        records = await consumer.receive("processing-commands", wait_seconds=0)
        for record in records:
            with pytest.raises(ValueError):
                decode(record, "processing-commands")
            await consumer.visibility("processing-commands", record["ReceiptHandle"], 0)
    dlq = client.receive_message(QueueUrl=urls["processing-commands-dlq"], WaitTimeSeconds=0)
    assert [record["Body"] for record in dlq.get("Messages", [])] == ["poison-json"]
    assert not client.receive_message(QueueUrl=urls["processing-work-dlq"], WaitTimeSeconds=0).get(
        "Messages"
    )


async def test_native_output_cleanup_removes_versions_and_late_writes_only_in_attempt(sqs_local):
    from types import SimpleNamespace
    from uuid import uuid4

    import boto3

    from processing.recovery_v1 import NativeCleanupStore

    sqs, _ = sqs_local
    client = boto3.client(
        "s3",
        endpoint_url=sqs.meta.endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="local-test",
        aws_secret_access_key="local-test",
    )
    bucket = "b-cleanup-" + uuid4().hex
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    prefix = f"jobs/{uuid4()}/attempts/{uuid4()}/"
    outside = f"jobs/{uuid4()}/attempts/{uuid4()}/primary.mp4"
    try:
        for payload in (b"first", b"second"):
            client.put_object(Bucket=bucket, Key=prefix + "primary.mp4", Body=payload)
        client.delete_object(Bucket=bucket, Key=prefix + "primary.mp4")
        client.put_object(Bucket=bucket, Key=outside, Body=b"healthy-output")
        store = NativeCleanupStore(SimpleNamespace(minio_output_bucket=bucket), client=client)
        await store.delete_prefix(prefix)
        remaining = client.list_object_versions(Bucket=bucket)
        assert [obj["Key"] for obj in remaining.get("Versions", [])] == [outside]
        assert not remaining.get("DeleteMarkers")
        client.put_object(Bucket=bucket, Key=prefix + "late.mp4", Body=b"late-upload")
        await store.delete_prefix(prefix)
        assert not client.list_object_versions(Bucket=bucket, Prefix=prefix).get("Versions")
        assert client.get_object(Bucket=bucket, Key=outside)["Body"].read() == b"healthy-output"
    finally:
        remaining = client.list_object_versions(Bucket=bucket)
        versions = remaining.get("Versions", []) + remaining.get("DeleteMarkers", [])
        if versions:
            client.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [
                        {"Key": item["Key"], "VersionId": item["VersionId"]} for item in versions
                    ]
                },
            )
        client.delete_bucket(Bucket=bucket)
        client.close()
