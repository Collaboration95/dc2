"""Operator DLQ helper: identities only, bounded peeks, original-queue redrive."""

import json
import os
import sys
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from delivery import dlq
from tests.v1.test_delivery import message


def record(body, number, receives=5):
    return {
        "MessageId": f"sqs-{number}",
        "ReceiptHandle": f"receipt-{number}",
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


LOOPBACK = "http://127.0.0.1:5999"
DLQ_ARN = "arn:aws:sqs:ap-southeast-1:123456789012:work-dlq"
SOURCE_ARN = "arn:aws:sqs:ap-southeast-1:123456789012:work"
SOURCE_URL = "http://127.0.0.1:5999/123456789012/work"


def moto_refusal():
    # Moto 5.2.4 answers an unimplemented action with a bare HTTP 500.
    return ClientError(
        {"Error": {"Code": "500", "Message": ""}, "ResponseMetadata": {"HTTPStatusCode": 500}},
        "StartMessageMoveTask",
    )


def fake_client(*messages, source_queues=(SOURCE_URL,), allow_policy=None):
    client = Mock()
    client.get_queue_url.return_value = {"QueueUrl": "dlq-url"}
    client.get_queue_attributes.return_value = {
        "Attributes": {"RedriveAllowPolicy": allow_policy} if allow_policy else {}
    }
    client.list_dead_letter_source_queues.return_value = {"queueUrls": list(source_queues)}
    client.receive_message.side_effect = [{"Messages": [item]} for item in messages] + [{}]
    return client


def test_manual_redrive_moves_valid_envelopes_and_never_touches_invalid_ones():
    good, bad = message("work"), "not json"
    client = fake_client(record(good, 1), record(bad, 2))
    naps = []
    result = dlq.manual_redrive(client, DLQ_ARN, per_second=4, sleep=naps.append)
    assert result == {"mode": "manual", "moved": 1, "left_invalid": 1, "source": SOURCE_URL}
    sent = client.send_message.call_args_list
    # Only the valid body is re-sent, verbatim, and only it is deleted from the DLQ.
    assert [call.kwargs["MessageBody"] for call in sent] == [json.dumps(good)]
    assert [call.kwargs["ReceiptHandle"] for call in client.delete_message.call_args_list] == [
        "receipt-1"
    ]
    # The invalid message is released again so the next inspector still sees it.
    assert client.change_message_visibility.call_args.kwargs["VisibilityTimeout"] == 0
    assert naps == [0.25]


def test_manual_redrive_releases_held_invalid_messages_even_when_a_send_fails():
    client = fake_client(
        {**record("not json", 1), "ReceiptHandle": "bad"},
        {**record(message("work"), 2), "ReceiptHandle": "good"},
    )
    client.send_message.side_effect = RuntimeError("source queue unreachable")
    with pytest.raises(RuntimeError):
        dlq.manual_redrive(client, DLQ_ARN, sleep=lambda _: None)
    client.delete_message.assert_not_called()
    assert client.change_message_visibility.call_args.kwargs["ReceiptHandle"] == "bad"


def test_manual_redrive_stops_when_the_same_message_is_delivered_twice():
    repeated = record(message("work"), 1)
    client = fake_client(repeated, repeated)
    result = dlq.manual_redrive(client, DLQ_ARN, sleep=lambda _: None)
    assert result["moved"] == 1 and client.send_message.call_count == 1


def test_source_queue_comes_from_the_allow_policy_before_the_source_listing():
    policy = json.dumps({"redrivePermission": "byQueue", "sourceQueueArns": [SOURCE_ARN]})
    client = fake_client(allow_policy=policy)
    client.get_queue_url.side_effect = [{"QueueUrl": "dlq-url"}, {"QueueUrl": SOURCE_URL}]
    assert dlq.resolve_source_queue(client, DLQ_ARN) == SOURCE_URL
    client.list_dead_letter_source_queues.assert_not_called()


def test_source_queue_falls_back_to_the_listing_when_the_emulator_lacks_the_allow_policy():
    client = fake_client()
    client.get_queue_attributes.side_effect = ClientError(
        {"Error": {"Code": "InvalidAttributeName", "Message": "Unknown Attribute"}},
        "GetQueueAttributes",
    )
    assert dlq.resolve_source_queue(client, DLQ_ARN) == SOURCE_URL


def test_source_queue_is_never_guessed_when_a_dlq_has_several_sources():
    client = fake_client(source_queues=("a", "b"))
    with pytest.raises(ValueError, match="--source-queue-url"):
        dlq.resolve_source_queue(client, DLQ_ARN)


def test_explicit_source_queue_must_name_this_dlq_as_its_dead_letter_queue():
    client = Mock()
    client.get_queue_attributes.return_value = {
        "Attributes": {"RedrivePolicy": json.dumps({"deadLetterTargetArn": "arn:other"})}
    }
    with pytest.raises(ValueError, match="dead-letter"):
        dlq.resolve_source_queue(client, DLQ_ARN, SOURCE_URL)
    client.get_queue_attributes.return_value = {
        "Attributes": {"RedrivePolicy": json.dumps({"deadLetterTargetArn": DLQ_ARN})}
    }
    assert dlq.resolve_source_queue(client, DLQ_ARN, SOURCE_URL) == SOURCE_URL


def test_loopback_emulator_without_move_tasks_falls_back_to_the_manual_loop():
    client = fake_client(record(message("work"), 1))
    client.start_message_move_task.side_effect = moto_refusal()
    result = dlq.redrive_with_fallback(client, DLQ_ARN, endpoint_url=LOOPBACK, per_second=500)
    assert result["mode"] == "manual" and result["moved"] == 1


def test_loopback_emulator_that_supports_move_tasks_keeps_the_native_path():
    client = Mock()
    client.start_message_move_task.return_value = {"TaskHandle": "task-9"}
    assert dlq.redrive_with_fallback(client, DLQ_ARN, endpoint_url=LOOPBACK) == {
        "task_handle": "task-9"
    }
    client.receive_message.assert_not_called()


def test_a_failing_real_aws_move_task_is_never_replaced_by_the_manual_loop():
    for endpoint in (None, "https://sqs.ap-southeast-1.amazonaws.com"):
        client = Mock()
        client.start_message_move_task.side_effect = moto_refusal()
        with pytest.raises(ClientError):
            dlq.redrive_with_fallback(client, DLQ_ARN, endpoint_url=endpoint)
        client.receive_message.assert_not_called()
        client.send_message.assert_not_called()


def test_a_loopback_failure_that_is_not_unimplemented_is_not_swallowed():
    client = Mock()
    client.start_message_move_task.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "no"}, "ResponseMetadata": {}},
        "StartMessageMoveTask",
    )
    with pytest.raises(ClientError):
        dlq.redrive_with_fallback(client, DLQ_ARN, endpoint_url=LOOPBACK)


def test_source_queue_override_is_refused_without_a_loopback_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        dlq.redrive_with_fallback(Mock(), DLQ_ARN, source_queue_url=SOURCE_URL)
    with pytest.raises(SystemExit):
        dlq.main(["redrive", "--dlq-arn", DLQ_ARN, "--source-queue-url", SOURCE_URL])


def test_status_explains_the_emulator_boundary_instead_of_crashing():
    client = Mock()
    client.list_message_move_tasks.side_effect = moto_refusal()
    assert dlq.status_with_fallback(client, DLQ_ARN, endpoint_url=LOOPBACK)["mode"] == "manual"
    with pytest.raises(ClientError):
        dlq.status_with_fallback(client, DLQ_ARN)


def test_cli_refuses_a_non_loopback_emulator_endpoint():
    with pytest.raises(ValueError, match="loopback"):
        dlq.build_client("https://sqs.example.test")
    with pytest.raises(SystemExit):
        dlq.main(["inspect", "--limit", "5"])
    with pytest.raises(SystemExit):
        dlq.main(["redrive"])


class FakeBoto3:
    """boto3 stand-in: STS answers with `account`; the SQS client is only built if allowed."""

    def __init__(self, account):
        self.account, self.profiles, self.clients = account, [], []
        self.sqs = Mock()
        self.Session = self.make_session

    def make_session(self, profile_name=None, region_name=None):
        self.profiles.append((profile_name, region_name))
        owner = self

        class Session:
            def client(self, name, config=None):
                owner.clients.append(name)
                if name == "sts":
                    return Mock(get_caller_identity=Mock(return_value={"Account": owner.account}))
                return owner.sqs

        return Session()


SCOPE_ARGS = ["--profile", "dc2-project2-mfa", "--region", "ap-southeast-1"]


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN",
                 "DC2_AWS_ACCOUNT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def no_client(monkeypatch):
    """Any attempt to build an AWS client fails the test: usage errors must come first."""
    def forbidden(*_a, **_k):
        raise AssertionError("an AWS client was built")

    monkeypatch.setattr(dlq, "build_client", forbidden)
    monkeypatch.setattr(dlq, "build_verified_client", forbidden)


@pytest.mark.parametrize("extra", [
    [],
    ["--profile", "dc2-project2-mfa"],
    ["--region", "ap-southeast-1"],
    ["--profile", "default", "--region", "ap-southeast-1"],
    ["--profile", "dc2-project2-mfa", "--region", "us-east-1"],
    ["--profile", "dc2-project2-mfa", "--region", "ap-southeast-1", "--account", "123"],
])
def test_real_aws_commands_need_an_explicit_profile_region_and_account_before_any_client(
        no_client, clean_env, extra):
    with pytest.raises(SystemExit):
        dlq.main(["status", "--dlq-arn", DLQ_ARN, *extra])


def test_a_non_loopback_endpoint_is_a_usage_error_not_a_fallback_to_default_credentials(
        no_client, clean_env):
    with pytest.raises(SystemExit):
        dlq.main(["status", "--dlq-arn", DLQ_ARN, "--endpoint-url", "https://sqs.example.test",
                  *SCOPE_ARGS])


def test_the_sts_account_is_verified_before_any_sqs_client_exists(
        monkeypatch, clean_env, capsys):
    fake = FakeBoto3("999999999999")
    monkeypatch.setitem(sys.modules, "boto3", fake)
    with pytest.raises(SystemExit, match="different account"):
        dlq.main(["status", "--dlq-arn", DLQ_ARN, *SCOPE_ARGS])
    assert fake.profiles == [("dc2-project2-mfa", "ap-southeast-1")]
    assert fake.clients == ["sts"]  # the SQS client was never created
    fake.sqs.list_message_move_tasks.assert_not_called()


def test_the_expected_project_account_is_the_default_check_and_account_overrides_it(
        monkeypatch, clean_env, capsys):
    fake = FakeBoto3(dlq.EXPECTED_ACCOUNT)
    fake.sqs.list_message_move_tasks.return_value = {"Results": []}
    monkeypatch.setitem(sys.modules, "boto3", fake)
    dlq.main(["status", "--dlq-arn", DLQ_ARN, *SCOPE_ARGS])
    assert fake.clients == ["sts", "sqs"]
    fake.sqs.list_message_move_tasks.assert_called_once()
    other = FakeBoto3("123456789012")
    other.sqs.list_message_move_tasks.return_value = {"Results": []}
    monkeypatch.setitem(sys.modules, "boto3", other)
    dlq.main(["status", "--dlq-arn", DLQ_ARN, *SCOPE_ARGS, "--account", "123456789012"])
    assert other.clients == ["sts", "sqs"]


def test_inherited_aws_credentials_are_refused_for_real_aws(monkeypatch, clean_env):
    monkeypatch.setenv("AWS_PROFILE", "default")
    with pytest.raises(SystemExit, match="Unset inherited"):
        dlq.main(["status", "--dlq-arn", DLQ_ARN, *SCOPE_ARGS])


def test_a_loopback_emulator_keeps_working_without_a_profile_and_rejects_one(monkeypatch):
    client = Mock()
    client.list_message_move_tasks.return_value = {"Results": []}
    built = []
    monkeypatch.setattr(dlq, "build_client", lambda endpoint: built.append(endpoint) or client)
    dlq.main(["status", "--dlq-arn", DLQ_ARN, "--endpoint-url", LOOPBACK])
    assert built == [LOOPBACK]
    with pytest.raises(SystemExit):
        dlq.main(["status", "--dlq-arn", DLQ_ARN, "--endpoint-url", LOOPBACK, *SCOPE_ARGS])


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


@pytest.mark.integration
async def test_emulator_redrive_returns_a_quarantined_envelope_and_keeps_the_invalid_one(
    sqs_local,
):
    client, urls = sqs_local
    work, dlq_url = urls["processing-work"], urls["processing-work-dlq"]
    body = message("work")
    client.send_message(QueueUrl=work, MessageBody=json.dumps(body))
    client.send_message(QueueUrl=work, MessageBody="not json")
    for _ in range(3):
        # maxReceiveCount is 2: the third receive moves both messages to the DLQ.
        client.receive_message(
            QueueUrl=work, MaxNumberOfMessages=10, VisibilityTimeout=0, WaitTimeSeconds=0
        )
    arn = client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    assert sorted(item["valid"] for item in dlq.inspect(client, dlq_url)) == [False, True]

    # The real emulator refuses StartMessageMoveTask, so this exercises the fallback.
    result = dlq.redrive_with_fallback(
        client, arn, endpoint_url=os.environ["V1_TEST_SQS_ENDPOINT"], per_second=500
    )
    assert result == {"mode": "manual", "moved": 1, "left_invalid": 1, "source": work}

    redriven = client.receive_message(QueueUrl=work, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    assert [json.loads(item["Body"])["message_id"] for item in redriven["Messages"]] == [
        body["message_id"]
    ]
    left = dlq.inspect(client, dlq_url)
    assert [item["valid"] for item in left] == [False]
