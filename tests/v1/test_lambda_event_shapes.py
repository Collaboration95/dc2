"""Feed AWS-documented event shapes into the real Lambda entrypoints.

The unit tests elsewhere call internal functions with convenient dicts. These tests start
from what SQS, EventBridge and ECS actually deliver and assert the routing (which domain
function runs, with what) and the partial-batch response format. Only I/O is replaced:
the database engine, the SQS client and the domain functions that need a database.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from media import handlers as media_handlers
from media.config import get_settings as media_settings
from processing import handlers as processing_handlers
from processing.config import get_settings as processing_settings
from processing.recovery_v1 import stopped_task_names
from tests.v1.test_delivery import message

REGION, ACCOUNT = "ap-southeast-1", "123456789012"


@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    for key in ("MEDIA_POSTGRES_SSL_CA", "PROCESSING_DATABASE_CA_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MEDIA_POSTGRES_DSN", "postgresql://media_runtime:pw@db/media")
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", "postgresql://processing_runtime:pw@db/p")
    monkeypatch.setenv("AWS_REGION", REGION)
    for name, lane in (
        ("PROCESSING_COMMANDS_QUEUE_URL", "commands"),
        ("PROCESSING_WORK_QUEUE_URL", "work"),
        ("MEDIA_RESULTS_QUEUE_URL", "results"),
    ):
        monkeypatch.setenv(name, f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{lane}")
    for module in (media_handlers, processing_handlers):
        engine = SimpleNamespace(dispose=AsyncMock())
        monkeypatch.setattr(module, "create_async_engine", lambda *a, _e=engine, **k: _e)
        monkeypatch.setattr(module, "async_sessionmaker", lambda *a, **k: object())
        monkeypatch.setattr(module, "SQS", lambda *a, **k: SimpleNamespace(client=None))
    monkeypatch.setattr("media.database.engine_options", lambda *a, **k: {})
    media_settings.cache_clear()
    processing_settings.cache_clear()
    yield
    media_settings.cache_clear()
    processing_settings.cache_clear()


def sqs_record(body, *, message_id=None, receive_count="1", producer="media", queue="commands"):
    """One record exactly as an SQS event source mapping delivers it."""
    text = body if isinstance(body, str) else json.dumps(body)
    return {
        "messageId": message_id or str(uuid4()),
        "receiptHandle": "AQEB" + uuid4().hex,
        "body": text,
        "attributes": {
            "ApproximateReceiveCount": receive_count,
            "SentTimestamp": "1760590000000",
            "SenderId": "AROAEXAMPLE:media",
            "ApproximateFirstReceiveTimestamp": "1760590000050",
        },
        "messageAttributes": {
            "producer": {
                "stringValue": producer,
                "stringListValues": [],
                "binaryListValues": [],
                "dataType": "String",
            }
        },
        "md5OfBody": "e4e68fb7bd0e697a0ae8f1bb342846b3",
        "eventSource": "aws:sqs",
        "eventSourceARN": f"arn:aws:sqs:{REGION}:{ACCOUNT}:{queue}",
        "awsRegion": REGION,
    }


def scheduled_event(rule):
    return {
        "version": "0",
        "id": str(uuid4()),
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "account": ACCOUNT,
        "time": "2026-10-16T01:02:03Z",
        "region": REGION,
        "resources": [f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{rule}"],
        "detail": {},
    }


def ecs_event(started_by="v1-0123456789abcdef", status="STOPPED"):
    task = uuid4().hex
    return {
        "version": "0",
        "id": str(uuid4()),
        "detail-type": "ECS Task State Change",
        "source": "aws.ecs",
        "account": ACCOUNT,
        "time": "2026-10-16T01:02:03Z",
        "region": REGION,
        "resources": [f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/v1/{task}"],
        "detail": {
            "clusterArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/v1",
            "taskArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/v1/{task}",
            "taskDefinitionArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/worker:3",
            "startedBy": started_by,
            "lastStatus": status,
            "desiredStatus": "STOPPED",
            "launchType": "FARGATE",
            "stopCode": "EssentialContainerExited",
            "stoppedReason": "Essential container in task exited",
            "containers": [{"name": "worker", "lastStatus": "STOPPED", "exitCode": 1}],
            "version": 5,
        },
    }


def object_created_event(key):
    return {
        "version": "0",
        "id": str(uuid4()),
        "detail-type": "Object Created",
        "source": "aws.s3",
        "account": ACCOUNT,
        "time": "2026-10-16T01:02:03Z",
        "region": REGION,
        "resources": ["arn:aws:s3:::outputs-bucket"],
        "detail": {
            "version": "0",
            "bucket": {"name": "outputs-bucket"},
            "object": {
                "key": key,
                "size": 5368,
                "etag": "b1946ac92492d2347c6235b4d2611184",
                "version-id": "IYV3p45BT0ac8hjHg1houSdS1a.Mro8e",
                "sequencer": "00617F08299329D189",
            },
            "request-id": "N4N7GDK58NMKJ12R",
            "requester": "123456789012",
            "source-ip-address": "1.2.3.4",
            "reason": "PutObject",
        },
    }


# --- SQS batches -----------------------------------------------------------------------


def test_processing_commands_batch_reports_exactly_the_failed_message_ids(monkeypatch):
    handled = AsyncMock(return_value=True)
    monkeypatch.setattr("processing.messaging.handle_command", handled)
    monkeypatch.setattr(processing_handlers, "publish_outbox", AsyncMock(return_value=0))
    good, wrong_lane, malformed = message("submit"), message("result"), "not json {"
    records = [
        sqs_record(good, message_id="m-good", receive_count="1"),
        sqs_record(wrong_lane, message_id="m-lane", receive_count="2"),
        sqs_record(malformed, message_id="m-bad", receive_count="5"),
    ]

    result = processing_handlers.command_handler({"Records": records}, None)

    assert result == {
        "batchItemFailures": [{"itemIdentifier": "m-lane"}, {"itemIdentifier": "m-bad"}]
    }
    assert handled.await_count == 1
    assert handled.await_args.args[1]["message_id"] == good["message_id"]
    processing_handlers.publish_outbox.assert_awaited_once()


@pytest.mark.parametrize("receive_count", ["1", "9", "1000"])
def test_the_receive_count_never_changes_how_a_record_is_routed(monkeypatch, receive_count):
    monkeypatch.setattr("processing.messaging.handle_command", AsyncMock(return_value=True))
    monkeypatch.setattr(processing_handlers, "publish_outbox", AsyncMock(return_value=0))
    record = sqs_record(message("submit"), receive_count=receive_count)
    assert processing_handlers.command_handler({"Records": [record]}, None) == {
        "batchItemFailures": []
    }


def test_a_command_handler_failure_is_a_batch_failure_not_an_invocation_error(monkeypatch):
    monkeypatch.setattr(
        "processing.messaging.handle_command", AsyncMock(side_effect=RuntimeError("db down"))
    )
    monkeypatch.setattr(processing_handlers, "publish_outbox", AsyncMock(return_value=0))
    record = sqs_record(message("cancel"), message_id="m-1")
    assert processing_handlers.command_handler({"Records": [record]}, None) == {
        "batchItemFailures": [{"itemIdentifier": "m-1"}]
    }


def test_an_empty_batch_is_a_successful_empty_response(monkeypatch):
    monkeypatch.setattr(processing_handlers, "publish_outbox", AsyncMock(return_value=0))
    assert processing_handlers.command_handler({"Records": []}, None) == {"batchItemFailures": []}


def test_media_results_batch_applies_results_and_fails_other_lanes(monkeypatch):
    applied = AsyncMock()
    monkeypatch.setattr(media_handlers, "consume_result", applied)
    monkeypatch.setattr(media_handlers, "async_sessionmaker", lambda *a, **k: _Context)
    result_body = message("result")
    records = [
        sqs_record(result_body, message_id="r-ok", producer="processing", queue="results"),
        sqs_record(message("submit"), message_id="r-lane", producer="media", queue="results"),
    ]

    result = media_handlers.result_handler({"Records": records}, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "r-lane"}]}
    assert applied.await_count == 1
    assert applied.await_args.args[1]["message_id"] == result_body["message_id"]


class _Context:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


# --- EventBridge: schedule, ECS, S3 ------------------------------------------------------


def stub_repair(monkeypatch, module):
    stubs = SimpleNamespace(
        terminal_event=AsyncMock(return_value=1),
        run_once=AsyncMock(
            return_value={"expired": 0, "repaired": 0, "published": 0, "cleaned": 0}
        ),
    )
    monkeypatch.setattr(module, "terminal_event", stubs.terminal_event)
    monkeypatch.setattr(module, "run_once", stubs.run_once)
    return stubs


def test_the_processing_schedule_runs_the_repair_pass_and_never_an_ecs_stop(monkeypatch):
    stubs = stub_repair(monkeypatch, processing_handlers)
    result = processing_handlers.repair_handler(scheduled_event("processing-repair"), None)
    assert result == {"expired": 0, "repaired": 0, "published": 0, "cleaned": 0}
    stubs.run_once.assert_awaited_once()
    stubs.terminal_event.assert_not_awaited()


def test_the_media_schedule_publishes_commands_then_cleans(monkeypatch):
    published = AsyncMock(return_value=2)
    cleaned = AsyncMock(return_value={"cleanup": 1, "uploads": 3})
    monkeypatch.setattr(media_handlers, "publish_commands", published)
    monkeypatch.setattr("media.recovery_v1.run_once", cleaned)
    monkeypatch.setattr("media.services.storage.Storage", lambda settings: object())
    result = media_handlers.repair_handler(scheduled_event("media-repair"), None)
    assert result == {"published": 2, "cleanup": 1, "uploads": 3}
    published.assert_awaited_once()
    cleaned.assert_awaited_once()


def test_an_ecs_task_state_change_is_routed_to_the_stop_handler_then_the_repair_pass(monkeypatch):
    stubs = stub_repair(monkeypatch, processing_handlers)
    event = ecs_event()
    result = processing_handlers.ecs_handler(event, None)
    stubs.terminal_event.assert_awaited_once()
    assert stubs.terminal_event.await_args.args[1] is event
    stubs.run_once.assert_awaited_once()
    assert result["stopped"] == 1


def test_an_object_created_notification_never_hands_its_key_to_the_cleanup(monkeypatch):
    stubs = stub_repair(monkeypatch, processing_handlers)
    key = "jobs/00000000-0000-0000-0000-000000000000/attempts/x/../../../elsewhere"
    result = processing_handlers.s3_handler(object_created_event(key), None)
    stubs.terminal_event.assert_not_awaited()
    stubs.run_once.assert_awaited_once()
    assert key not in repr(stubs.run_once.await_args)
    assert "stopped" not in result


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "DEPROVISIONING"])
def test_only_a_stopped_ecs_event_names_a_worker_task(status):
    assert stopped_task_names(ecs_event(status=status)) == set()


def test_a_stopped_ecs_event_names_the_started_by_task_arn_and_task_id():
    event = ecs_event("v1-0123456789abcdef")
    arn = event["detail"]["taskArn"]
    assert stopped_task_names(event) == {"v1-0123456789abcdef", arn, arn.rsplit("/", 1)[-1]}


@pytest.mark.parametrize("event", [{}, {"detail": None}, {"detail": []}, "STOPPED", None])
def test_malformed_ecs_events_name_no_task(event):
    assert stopped_task_names(event) == set()


def test_an_ecs_event_without_started_by_still_matches_by_task_arn():
    event = ecs_event()
    del event["detail"]["startedBy"]
    assert len(stopped_task_names(event)) == 2


# --- readiness is a direct invocation, not an event -------------------------------------


def refusal():
    return DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate="28P01"))


@pytest.mark.parametrize("service", ["media", "processing"])
def test_the_ready_invocation_reports_unavailable_and_forgets_a_refused_dsn(
    monkeypatch, service
):
    from contextlib import asynccontextmanager

    if service == "media":
        from media import database as database_module
        from media.config import get_settings
        from media.lambda_handler import handler

        @asynccontextmanager
        async def refused(_settings):
            raise refusal()
            yield

        monkeypatch.setattr(database_module, "invocation_session", refused)
    else:
        from processing import database as database_module
        from processing.config import get_settings
        from processing.lambda_handler import handler

        class Refusing:
            async def __aenter__(self):
                raise refusal()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(
            database_module, "create_async_engine", lambda *a, **k: SimpleNamespace(
                connect=Refusing, dispose=AsyncMock()
            )
        )
    first = get_settings()
    assert get_settings() is first
    result = handler({"dc2_operation": "ready"}, None)
    assert result == {"service": service, "ready": False, "error": "database unavailable"}
    assert get_settings() is not first
