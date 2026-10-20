"""Lambda entrypoint failures that carry no connection details.

Driver errors embed the DSN host and port (and sometimes more). Lambda copies an escaping
exception's message and traceback into the invocation response and logs, so entrypoints
convert them here. The invocation still fails, which keeps SQS/EventBridge retry semantics.
"""

import functools
import json
import logging
import re
from uuid import UUID

logger = logging.getLogger("dc2.handler")

_EVENT_TEXT = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_ERROR_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_EVENT_FIELDS = {
    "event",
    "operation",
    "outcome",
    "error_class",
    "sqlstate",
    "correlation_id",
    "request_id",
    "task_id",
    "job_id",
    "attempt_id",
    "http_status",
}


def _safe_event_value(name: str, value):
    if value is None:
        return None
    if name in {"job_id", "attempt_id"}:
        try:
            return str(value if isinstance(value, UUID) else UUID(value))
        except (AttributeError, TypeError, ValueError):
            return None
    if name in {"request_id", "correlation_id", "task_id"}:
        if isinstance(value, str) and _SAFE_ID.fullmatch(value):
            return value
        return None
    if name == "error_class":
        if isinstance(value, str) and _ERROR_CLASS.fullmatch(value):
            return value
        return "unknown"
    if name == "sqlstate":
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{5}", value):
            return value
        return None
    if name == "http_status":
        return value if type(value) is int and 100 <= value <= 599 else None
    if name in {"event", "operation", "outcome"}:
        if isinstance(value, str) and _EVENT_TEXT.fullmatch(value):
            return value
        return "unknown"
    return None


def log_safe_event(event_logger, **fields) -> None:
    """Write a bounded structured event from a fixed set of non-payload fields."""
    safe = {
        name: _safe_event_value(name, value)
        for name, value in fields.items()
        if name in _EVENT_FIELDS
    }
    try:
        event_logger.error(json.dumps(safe, separators=(",", ":"), sort_keys=True))
    except Exception:
        # Diagnostics must never change the handler, retry or acknowledgement outcome.
        pass


class SanitizedHandlerError(RuntimeError):
    """Safe to surface: names the operation and exception class only."""


def sanitized_entrypoint(operation: str):
    def decorate(handler):
        @functools.wraps(handler)
        def wrapper(event, context=None):
            try:
                return handler(event, context)
            except Exception as error:
                failure = type(error).__name__
                sqlstate = getattr(error, "sqlstate", None) or getattr(
                    getattr(error, "orig", None), "sqlstate", None
                )
                correlation = getattr(context, "aws_request_id", None) or "unknown"
            # Raised outside the except block so no __context__ links back to the original
            # exception, whose text a traceback formatter would otherwise print.
            log_safe_event(
                logger,
                event="handler_failed",
                operation=operation,
                error_class=failure,
                sqlstate=sqlstate,
                correlation_id=str(correlation),
            )
            raise SanitizedHandlerError(f"{operation} failed ({failure})")

        return wrapper

    return decorate
