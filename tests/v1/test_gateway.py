import base64
import json
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response

from contracts.gateway import GatewayAdapter
from contracts.v1 import Actor


def event(path="/api/processing/echo", method="POST", actor=True):
    result = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "x=a%2Bb&x=c",
        "headers": {"x-owner-id": "forged", "x-role": "admin"},
        "cookies": ["session=abc", "other=two"],
        "body": "hello",
        "requestContext": {"http": {"method": method}},
    }
    if actor:
        result["requestContext"]["authorizer"] = {
            "lambda": Actor(str(uuid4()), "publisher").to_context()
        }
    return result


@pytest.fixture
def app():
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request, response: Response):
        response.set_cookie("session", "one", secure=True, httponly=True, samesite="strict")
        response.set_cookie("other", "two")
        return {
            "body": (await request.body()).decode(),
            "query": request.url.query,
            "owner": request.state.actor.owner_id,
            "headers": dict(request.headers),
        }

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


async def test_preserves_payload_query_cookies_and_trusted_actor(app):
    payload = event()
    payload.update(body=base64.b64encode(b"binary body").decode(), isBase64Encoded=True)
    result = await GatewayAdapter(app, service="processing").invoke(payload)
    assert result["statusCode"] == 200
    data = json.loads(result["body"])
    assert data["body"] == "binary body"
    assert data["query"] == payload["rawQueryString"]
    assert data["owner"] == payload["requestContext"]["authorizer"]["lambda"]["owner_id"]
    assert "x-owner-id" not in data["headers"] and "x-role" not in data["headers"]
    assert data["headers"]["cookie"] == "session=abc; other=two"
    assert len(result["cookies"]) == 2
    assert "HttpOnly" in result["cookies"][0] and "SameSite=strict" in result["cookies"][0]


async def test_missing_actor_rejected_and_health_exempt(app):
    adapter = GatewayAdapter(app, service="processing")
    assert (await adapter.invoke(event(actor=False)))["statusCode"] == 401
    assert (await adapter.invoke(event("/api/processing/health", "GET", False)))[
        "statusCode"
    ] == 200


async def test_strips_only_own_prefix_once(app):
    adapter = GatewayAdapter(app, service="processing")
    for path in ("/api/media/echo", "/api/processingx/echo", "/api/processing/api/processing/echo"):
        assert (await adapter.invoke(event(path)))["statusCode"] == 404


async def test_no_sensitive_exception_in_response(app):
    @app.post("/fail")
    async def fail():
        raise RuntimeError("private-dsn-password")

    result = await GatewayAdapter(app, service="processing").invoke(event("/api/processing/fail"))
    assert result["statusCode"] == 500
    assert "private" not in result["body"]


async def test_bad_base64_is_bounded_error(app):
    value = event() | {"body": "???", "isBase64Encoded": True}
    assert (await GatewayAdapter(app, service="processing").invoke(value))["statusCode"] == 400
