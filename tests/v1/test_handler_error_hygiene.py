"""Lambda entrypoints must not return driver text (DSN host and port) in their failure."""

import json
import logging
import traceback

import pytest
from sqlalchemy.exc import OperationalError

from media import handlers as media_handlers
from processing import handlers as processing_handlers
from runtime_support.errors import SanitizedHandlerError, log_safe_event

HOST = "db-cluster.internal.example.com"
LEAKY = (
    f'connection to server at "{HOST}" (10.1.2.3), port 5432 failed: '
    "postgresql+asyncpg://app:s3cret@" + HOST + ":5432/media"
)
ENTRYPOINTS = [
    (media_handlers, "result_handler", "media.result"),
    (media_handlers, "repair_handler", "media.repair"),
    (processing_handlers, "command_handler", "processing.command"),
    (processing_handlers, "repair_handler", "processing.repair"),
    (processing_handlers, "ecs_handler", "processing.ecs"),
    (processing_handlers, "s3_handler", "processing.s3"),
]


class Context:
    aws_request_id = "req-123"


@pytest.mark.parametrize("module,name,operation", ENTRYPOINTS)
def test_a_database_failure_leaves_the_handler_without_host_port_or_dsn(
    module, name, operation, monkeypatch, caplog
):
    async def leak(*_):
        raise OperationalError("SELECT 1", {}, OSError(LEAKY))

    monkeypatch.setattr(module, "invoke", leak)
    with caplog.at_level(logging.ERROR, logger="dc2.handler"):
        with pytest.raises(SanitizedHandlerError) as caught:
            getattr(module, name)({}, Context())

    shown = "".join(traceback.format_exception(caught.value))
    for text in (str(caught.value), shown, caplog.text):
        for secret in (HOST, "5432", "s3cret", "postgresql", "10.1.2.3"):
            assert secret not in text
    assert str(caught.value) == f"{operation} failed (OperationalError)"
    entry = json.loads(caplog.records[-1].getMessage())
    assert entry == {
        "event": "handler_failed",
        "operation": operation,
        "error_class": "OperationalError",
        "sqlstate": None,
        "correlation_id": "req-123",
    }


def test_a_handler_that_succeeds_returns_its_result_unchanged(monkeypatch):
    async def ok(*_):
        return {"batchItemFailures": [{"itemIdentifier": "m-1"}]}

    monkeypatch.setattr(media_handlers, "invoke", ok)
    assert media_handlers.result_handler({}, None) == {
        "batchItemFailures": [{"itemIdentifier": "m-1"}]
    }


def test_a_missing_context_is_logged_with_an_unknown_correlation_id(monkeypatch, caplog):
    async def boom(*_):
        raise RuntimeError(LEAKY)

    monkeypatch.setattr(processing_handlers, "invoke", boom)
    with caplog.at_level(logging.ERROR, logger="dc2.handler"):
        with pytest.raises(SanitizedHandlerError):
            processing_handlers.s3_handler({}, None)
    assert json.loads(caplog.records[-1].getMessage())["correlation_id"] == "unknown"


def test_safe_events_drop_payload_fields_and_unsafe_identifiers(caplog):
    private = "https://user:secret@example.test/path?jwt=private"
    with caplog.at_level(logging.ERROR, logger="dc2.handler"):
        log_safe_event(
            logging.getLogger("dc2.handler"),
            event="record_failed",
            operation="sqs_consume",
            outcome="retry",
            error_class="RuntimeError",
            request_id=private,
            job_id="not-a-uuid",
            attempt_id="eyJhbGciOi.token.value",
            sqlstate=private,
            payload=private,
        )

    entry = json.loads(caplog.records[-1].getMessage())
    assert entry == {
        "attempt_id": None,
        "error_class": "RuntimeError",
        "event": "record_failed",
        "job_id": None,
        "operation": "sqs_consume",
        "outcome": "retry",
        "request_id": None,
        "sqlstate": None,
    }
    assert private not in caplog.text


def test_safe_event_logging_failure_does_not_escape():
    class BrokenLogger:
        def error(self, _message):
            raise OSError("logging backend unavailable")

    log_safe_event(BrokenLogger(), event="record_failed", operation="sqs_consume", outcome="retry")
