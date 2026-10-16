"""Operator DLQ helper: identities only, bounded peeks, original-queue redrive."""

import json
from unittest.mock import Mock

import pytest

from delivery import dlq
from tests.v1.test_delivery import message


def record(body, number, receives=5):
    return {
        "MessageId": f"sqs-{number}",
        "Body": body if isinstance(body, str) else json.dumps(body),
        "Attributes": {"ApproximateReceiveCount": str(receives)},
    }


def test_inspect_summarizes_identities_and_never_echoes_bodies_or_sources():
    result = message("result")
    result["payload"] = {"status": "failed", "attempt_number": 2, "error": "secret detail"}
    client = Mock()
    client.receive_message.side_effect = [
        {"Messages": [record(result, 1), record("not json", 2)]},
        {},
    ]
    summaries = dlq.inspect(client, "dlq-url")
    assert summaries[0] == {
        "sqs_message_id": "sqs-1",
        "receive_count": 5,
        "valid": True,
        "kind": "result",
        "message_id": result["message_id"],
        "owner_id": result["owner_id"],
        "asset_id": result["asset_id"],
        "job_id": result["job_id"],
        "attempt_id": result["attempt_id"],
        "state_version": 0,
        "status": "failed",
    }
    assert summaries[1] == {"sqs_message_id": "sqs-2", "receive_count": 5, "valid": False}
    flattened = json.dumps(summaries)
    assert "secret detail" not in flattened and result["source"]["key"] not in flattened
    call = client.receive_message.call_args_list[0].kwargs
    # A peek must not hide the message from the next inspector or the redrive.
    assert call["VisibilityTimeout"] == 0 and call["WaitTimeSeconds"] == 0


def test_inspect_is_bounded_and_dedupes_repeated_receipts():
    client = Mock()
    batch = {"Messages": [record(message("work"), n) for n in range(10)]}
    client.receive_message.return_value = batch
    assert len(dlq.inspect(client, "dlq-url", limit=10)) == 10
    assert client.receive_message.call_count == 1
    client.receive_message.reset_mock()
    # The same messages returned again are not counted twice; calls stay bounded.
    assert len(dlq.inspect(client, "dlq-url", limit=50)) == 10
    assert client.receive_message.call_count == 5


def test_redrive_returns_messages_to_their_source_queue_at_a_bounded_rate():
    client = Mock()
    client.start_message_move_task.return_value = {"TaskHandle": "task-1"}
    assert dlq.redrive(client, "arn:dlq", per_second=3) == "task-1"
    assert client.start_message_move_task.call_args.kwargs == {
        "SourceArn": "arn:dlq",
        "MaxNumberOfMessagesPerSecond": 3,
    }
    for rate in (0, 501):
        with pytest.raises(ValueError):
            dlq.redrive(client, "arn:dlq", per_second=rate)


def test_cli_refuses_a_non_loopback_emulator_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        dlq.build_client("https://sqs.example.test")
    with pytest.raises(SystemExit):
        dlq.main(["inspect", "--limit", "5"])
    with pytest.raises(SystemExit):
        dlq.main(["redrive"])


@pytest.mark.integration
async def test_quarantined_message_in_emulator_dlq_is_inspectable(sqs_local):
    client, urls = sqs_local
    body = message("work")
    client.send_message(QueueUrl=urls["processing-work"], MessageBody=json.dumps(body))
    for _ in range(3):
        # maxReceiveCount is 2: the third receive moves it to the DLQ.
        client.receive_message(
            QueueUrl=urls["processing-work"], VisibilityTimeout=0, WaitTimeSeconds=0
        )
    summaries = dlq.inspect(client, urls["processing-work-dlq"])
    assert [item["message_id"] for item in summaries] == [body["message_id"]]
