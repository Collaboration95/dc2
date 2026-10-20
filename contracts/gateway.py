"""Small HTTP API payload-v2 to ASGI adapter with trusted actor propagation.

Lambda resource policies must restrict invocation to the configured Gateway. The
integration marker is a schema fence, not a secret or substitute for that policy.
No identity is accepted from HTTP headers. Lifespan is deliberately not cached;
SQL dependencies must release invocation-scoped connections in finally blocks.
"""

import asyncio
import base64
import binascii
import json
import logging
from urllib.parse import unquote

from contracts.v1 import Actor, ContractError
from runtime_support import lambda_db
from runtime_support.errors import log_safe_event

PREFIXES = {"media": "/api/media", "processing": "/api/processing"}
logger = logging.getLogger("dc2.gateway")


def error_response(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"error": message}),
        "isBase64Encoded": False,
    }


def actor_from_event(event: dict) -> Actor:
    try:
        return Actor.from_context(event["requestContext"]["authorizer"]["lambda"])
    except (KeyError, TypeError) as exc:
        raise ContractError("Missing trusted actor") from exc


def is_public_route(service: str, method: str, path: str) -> bool:
    return (method == "GET" and path == "/health") or (
        service == "media"
        and method == "POST"
        and path in ("/auth/register", "/auth/login", "/auth/logout")
    )


async def invoke_asgi(app, event: dict, *, service: str, request_id=None) -> dict:
    try:
        if event.get("version") != "2.0":
            raise ContractError("HTTP API payload v2 required")
        prefix = PREFIXES[service]
        raw_path = event["rawPath"]
        if not isinstance(raw_path, str) or not raw_path.startswith(prefix + "/"):
            return error_response(404, "Route not found")
        path = unquote(raw_path[len(prefix) :])
        method = event["requestContext"]["http"]["method"].upper()
        actor = None if is_public_route(service, method, path) else actor_from_event(event)
        headers = []
        for name, value in event.get("headers", {}).items():
            if name.lower() not in ("x-owner-id", "x-role", "cookie"):
                headers.append((name.lower().encode("latin1"), value.encode("latin1")))
        cookies = event.get("cookies", [])
        if cookies:
            if not isinstance(cookies, list) or not all(isinstance(c, str) for c in cookies):
                raise ContractError("Invalid cookies")
            headers.append((b"cookie", "; ".join(cookies).encode("latin1")))
        body = event.get("body") or ""
        body = (
            base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode()
        )
        query = event.get("rawQueryString", "").encode("ascii")
    except ContractError:
        return error_response(401, "Missing or invalid trusted context")
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError, binascii.Error):
        return error_response(400, "Malformed gateway request")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": raw_path[len(prefix) :].encode(),
        "root_path": "",
        "query_string": query,
        "headers": headers,
        "server": ("gateway", 443),
        "client": None,
        "state": {"actor": actor, "gateway_v1": True},
    }
    messages = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Keep the peer connected while Starlette finishes streaming responses.
        await asyncio.Future()

    async def send(message):
        messages.append(message)

    try:
        await app(scope, receive, send)
    except Exception as error:
        log_safe_event(
            logger,
            event="request_failed",
            operation="gateway_asgi",
            outcome="http_500",
            error_class=type(error).__name__,
            request_id=request_id,
            http_status=500,
        )
        return error_response(500, "Internal service error")
    starts = [m for m in messages if m["type"] == "http.response.start"]
    if len(starts) != 1:
        log_safe_event(
            logger,
            event="response_failed",
            operation="gateway_asgi",
            outcome="invalid_response",
            request_id=request_id,
            http_status=500,
        )
        return error_response(500, "Invalid service response")
    status = starts[0]["status"]
    if isinstance(status, int) and not isinstance(status, bool) and status >= 500:
        log_safe_event(
            logger,
            event="response_status",
            operation="gateway_http",
            outcome="application_error",
            request_id=request_id,
            http_status=status,
        )
    output_headers = {}
    output_cookies = []
    for name, value in starts[0].get("headers", []):
        name, value = name.decode("latin1"), value.decode("latin1")
        if name.lower() == "set-cookie":
            output_cookies.append(value)
        else:
            output_headers[name] = value
    data = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    try:
        output_body, encoded = data.decode("utf-8"), False
    except UnicodeDecodeError:
        output_body, encoded = base64.b64encode(data).decode("ascii"), True
    result = {
        "statusCode": starts[0]["status"],
        "headers": output_headers,
        "body": output_body,
        "isBase64Encoded": encoded,
    }
    if output_cookies:
        result["cookies"] = output_cookies
    return result


def is_readiness_probe(event: dict) -> bool:
    """A direct operator invocation, which API Gateway can never construct.

    Gateway always builds a payload-v2 event with `version` and `requestContext`, and it
    cannot add top-level keys from request data. IAM `lambda:InvokeFunction` therefore
    gates this path, so it needs no public route and no shared secret.
    """
    return (
        isinstance(event, dict)
        and event.get("dc2_operation") == "ready"
        and "version" not in event
        and "requestContext" not in event
    )


class GatewayAdapter:
    def __init__(self, app, *, service: str, readiness=None):
        if service not in PREFIXES:
            raise ValueError("Unknown domain service")
        self.app, self.service, self.readiness = app, service, readiness

    async def invoke(self, event: dict, *, request_id=None) -> dict:
        return await invoke_asgi(self.app, event, service=self.service, request_id=request_id)

    def __call__(self, event: dict, context=None) -> dict:
        if self.readiness is not None and is_readiness_probe(event):
            return lambda_db.run(self.readiness())
        request_id = getattr(context, "aws_request_id", None)
        return lambda_db.run(self.invoke(event, request_id=request_id))
