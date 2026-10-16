"""Lambda entrypoint failures that carry no connection details.

Driver errors embed the DSN host and port (and sometimes more). Lambda copies an escaping
exception's message and traceback into the invocation response and logs, so entrypoints
convert them here. The invocation still fails, which keeps SQS/EventBridge retry semantics.
"""

import functools
import json
import logging

logger = logging.getLogger("dc2.handler")


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
            logger.error(
                json.dumps(
                    {
                        "event": "handler_failed",
                        "operation": operation,
                        "error_class": failure,
                        "sqlstate": sqlstate if isinstance(sqlstate, str) else None,
                        "correlation_id": str(correlation),
                    }
                )
            )
            raise SanitizedHandlerError(f"{operation} failed ({failure})")

        return wrapper

    return decorate
