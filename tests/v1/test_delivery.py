"""Fake SQS protocol checks; these are not AWS policy/delivery evidence."""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from contracts.v1 import ContractError
from delivery.envelope import document
from delivery.runtime import deadline_for
from delivery.sqs import SQS, consume_batch


def message(kind="submit"):
    owner, asset = str(uuid4()), str(uuid4())
    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "kind": kind,
        "owner_id": owner,
        "asset_id": asset,
        "job_id": str(uuid4()) if kind in {"work", "result"} else None,
        "attempt_id": str(uuid4()) if kind in {"work", "result"} else None,
        "state_version": 0,
        "source": {
            "bucket": "sources",
            "key": f"sources/{owner}/{asset}/source",
            "version_id": "immutable-v1",
            "sha256": "a" * 64,
            "size_bytes": 123,
            "content_type": "video/mp4",
        },
        "payload": {},
    }


class Client:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(("send", kwargs))
        return {"MessageId": "sqs-id"}

    def receive_message(self, **kwargs):
        self.calls.append(("receive", kwargs))
        return {"Messages": [{"Body": "{}", "ReceiptHandle": "receipt"}]}

    def change_message_visibility(self, **kwargs):
        self.calls.append(("visibility", kwargs))

    def delete_message(self, **kwargs):
        self.calls.append(("delete", kwargs))


@pytest.mark.parametrize(
    "producer,queue,kind",
    [
        ("media", "processing-work", "work"),
        ("media", "media-results", "result"),
        ("processing", "processing-commands", "submit"),
        ("media", "processing-commands", "work"),
        (None, "processing-commands", "submit"),
    ],
)
async def test_lane_rejection_precedes_network(producer, queue, kind):
    client = Client()
    queue_client = SQS({queue: "local-queue"}, producer=producer, client=client)
    with pytest.raises(ValueError):
        await queue_client.send(queue, message(kind))
    assert not client.calls


async def test_poll_visibility_delete_and_payload():
    client = Client()
    queue = SQS(
        {"processing-work": "local-queue"}, producer="processing", consumer="encoder", client=client
    )
    body = message("work")
    await queue.send("processing-work", body)
    assert json.loads(client.calls[-1][1]["MessageBody"]) == body
    await queue.receive("processing-work")
    assert client.calls[-1][1]["WaitTimeSeconds"] == 20
    assert client.calls[-1][1]["MaxNumberOfMessages"] == 1
    await queue.visibility("processing-work", "receipt", 30)
    assert client.calls[-1][1]["VisibilityTimeout"] == 30
    await queue.delete("processing-work", "receipt")
    assert client.calls[-1][1]["ReceiptHandle"] == "receipt"
    with pytest.raises(ValueError):
        await queue.receive("processing-work", wait_seconds=21)
    with pytest.raises(ValueError):
        await queue.visibility("processing-work", "receipt", 43201)


async def test_partial_batch_poison_and_handler_rollback(caplog):
    good, failed = message(), message()
    private = "postgresql://app:secret@database.internal/media?token=private"
    handler = AsyncMock(side_effect=[None, RuntimeError(private)])
    event = {
        "Records": [
            {"messageId": "good", "body": json.dumps(good)},
            {"messageId": "poison", "body": "invalid json"},
            {"messageId": "failed", "body": json.dumps(failed)},
            {"messageId": "wrong-lane", "body": json.dumps(message("work"))},
        ]
    }
    result = await consume_batch(event, "processing-commands", handler)
    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": "poison"},
            {"itemIdentifier": "failed"},
            {"itemIdentifier": "wrong-lane"},
        ]
    }
    assert handler.await_count == 2
    record = next(
        item for item in caplog.records if json.loads(item.message).get("request_id") == "failed"
    )
    logged = json.loads(record.message)
    assert private not in caplog.text
    assert logged == {
        "attempt_id": failed["attempt_id"],
        "error_class": "RuntimeError",
        "event": "record_failed",
        "job_id": failed["job_id"],
        "operation": "sqs_consume",
        "outcome": "retry",
        "request_id": "failed",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"state_version": -1},
        {"payload": {"source_url": "hidden"}},
        {"payload": {"nested": {"value": "https://private-source"}}},
        {
            "source": {
                "bucket": "sources",
                "key": "owned",
                "version_id": "null",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "content_type": "video/mp4",
            }
        },
    ],
)
def test_contract_rejects_unsafe_envelopes(change):
    body = message()
    body.update(change)
    with pytest.raises(ContractError):
        document(body)


def test_deadline_reserves_lambda_shutdown_time():
    import time
    from types import SimpleNamespace

    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 3000)
    remaining = deadline_for(context) - time.monotonic()
    assert 1.9 <= remaining <= 2
