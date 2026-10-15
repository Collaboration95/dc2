"""Offline Lambda boundary checks; no cloud or PostgreSQL acceptance claim."""

import base64
import json
import ssl
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from contracts.v1 import Actor
from fastapi import Request

from media import authorizer, database
from media.api import deps
from media.config import get_settings
from media.errors import MediaError
from media.lambda_handler import handler
from media.main import create_app
from media.services.security import issue_token
from media.storage_credentials import LambdaProvider, credential_provider


def event(path="/auth/me", *, owner=None, token=None, method="GET"):
    value = {
        "version": "2.0",
        "rawPath": "/api/media" + path,
        "rawQueryString": "",
        "requestContext": {"http": {"method": method}},
        "headers": {"x-owner-id": str(uuid4()), "x-role": "operator"},
        "cookies": [f"access_token={token}"] if token else [],
    }
    if owner:
        value["requestContext"]["authorizer"] = {
            "lambda": Actor(str(owner), "publisher").to_context()
        }
    return value


@pytest.fixture
def api(settings, monkeypatch, user):
    from contracts.gateway import GatewayAdapter

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    async def sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=user))

    monkeypatch.setattr(deps, "get_session", sessions)
    return GatewayAdapter(app, service="media")


async def test_media_event_preserves_cookie_and_ignores_forged_owner(api, settings, user):
    result = await api.invoke(event(owner=user.id, token=issue_token(user.id, settings)))
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["id"] == str(user.id)


@pytest.mark.parametrize("failure", ["missing", "forged-marker", "other-owner", "role", "jwt"])
async def test_media_refuses_invalid_current_identity(api, settings, user, failure):
    request = event(owner=user.id, token=issue_token(user.id, settings))
    actor = request["requestContext"]["authorizer"]["lambda"]
    if failure == "missing":
        del request["requestContext"]["authorizer"]
    elif failure == "forged-marker":
        actor["integration"] = "public-header"
    elif failure == "other-owner":
        actor["owner_id"] = str(uuid4())
    elif failure == "role":
        actor["role"] = "viewer"
    else:
        request["cookies"] = ["access_token=forged"]
    result = await api.invoke(request)
    assert result["statusCode"] == 401


async def test_media_removed_user_is_denied(api, settings, user, monkeypatch):
    async def sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=None))

    monkeypatch.setattr(deps, "get_session", sessions)
    assert (await api.invoke(event(owner=user.id, token=issue_token(user.id, settings))))[
        "statusCode"
    ] == 401


async def test_lambda_mode_refuses_plain_http(settings):
    request = Request({"type": "http", "headers": []})
    with pytest.raises(MediaError, match="trusted gateway"):
        await deps.current_user(request, settings.model_copy(update={"runtime_mode": "lambda"}))


async def test_auth_public_base64_body_and_cookie_flags(settings, monkeypatch):
    from contracts.gateway import GatewayAdapter

    from media.api import auth

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    @asynccontextmanager
    async def begin():
        yield

    session = SimpleNamespace(begin=begin, scalar=AsyncMock(return_value=None))

    async def sessions():
        yield session

    app.dependency_overrides[database.get_session] = sessions
    monkeypatch.setattr(auth, "verify_password", lambda *args: False)
    request = event("/auth/login", method="POST")
    request["headers"]["content-type"] = "application/json"
    request["body"] = base64.b64encode(
        b'{"email":"absent@example.com","password":"valid-password"}'
    ).decode()
    request["isBase64Encoded"] = True
    adapter = GatewayAdapter(app, service="media")
    assert (await adapter.invoke(request))["statusCode"] == 401
    response = await adapter.invoke(event("/auth/logout", method="POST"))
    assert response["statusCode"] == 204
    assert all(
        flag in response["cookies"][0]
        for flag in ["Secure", "HttpOnly", "SameSite=strict", "Path=/"]
    )
    assert (await handler.invoke(event("/health")))["statusCode"] == 200
    request["rawPath"] = "/api/processing/auth/login"
    assert (await adapter.invoke(request))["statusCode"] == 404
    request["rawPath"] = "/api/media/api/media/auth/login"
    assert (await adapter.invoke(request))["statusCode"] != 200


@pytest.mark.parametrize("current_role", ["user", "operator", "removed", "invalid"])
async def test_authorizer_reads_current_owned_role(settings, user, monkeypatch, current_role):
    user.role = current_role

    @asynccontextmanager
    async def session(config):
        yield SimpleNamespace(
            get=AsyncMock(return_value=None if current_role == "removed" else user)
        )

    monkeypatch.setattr(authorizer, "invocation_session", session)
    monkeypatch.setattr(authorizer, "get_settings", lambda: settings)
    result = await authorizer.authorize(event(token=issue_token(user.id, settings)))
    assert result["isAuthorized"] == (current_role in {"user", "operator"})
    if result["isAuthorized"]:
        assert Actor.from_context(result["context"]) == Actor(str(user.id), "publisher")


async def test_authorizer_does_not_reuse_positive_decisions(settings, user, monkeypatch):
    lookup = AsyncMock(side_effect=[user, None])

    @asynccontextmanager
    async def session(config):
        yield SimpleNamespace(get=lookup)

    monkeypatch.setattr(authorizer, "invocation_session", session)
    monkeypatch.setattr(authorizer, "get_settings", lambda: settings)
    request = event(token=issue_token(user.id, settings))
    assert (await authorizer.authorize(request))["isAuthorized"]
    assert not (await authorizer.authorize(request))["isAuthorized"]
    assert lookup.await_count == 2
    request["cookies"] *= 2
    assert not (await authorizer.authorize(request))["isAuthorized"]


@pytest.mark.parametrize("fail", [False, True])
async def test_invocation_sql_closes_session_and_disposes_engine(settings, monkeypatch, fail):
    events = []
    engine = SimpleNamespace(dispose=AsyncMock(side_effect=lambda: events.append("dispose")))

    @asynccontextmanager
    async def session():
        try:
            yield "session"
        finally:
            events.append("close")

    monkeypatch.setattr(database, "create_async_engine", lambda *a, **k: engine)
    monkeypatch.setattr(database, "engine_options", lambda *a, **k: {})
    monkeypatch.setattr(database, "async_sessionmaker", lambda *a, **k: session)
    try:
        async with database.invocation_session(settings) as opened:
            assert opened == "session"
            if fail:
                raise RuntimeError("route failed")
    except RuntimeError:
        assert fail
    assert events == ["close", "dispose"]


def test_lambda_sql_requires_verified_tls_and_null_pool(settings, monkeypatch):
    from sqlalchemy.pool import NullPool

    with pytest.raises(ValueError, match="trusted PostgreSQL CA"):
        database.engine_options(
            settings.model_copy(update={"postgres_ssl_ca": None}), invocation=True
        )
    context = ssl.create_default_context()
    seen = []
    monkeypatch.setattr(
        database.ssl, "create_default_context", lambda **k: seen.append(k) or context
    )
    options = database.engine_options(
        settings.model_copy(update={"postgres_ssl_ca": "rds-ca.pem"}), invocation=True
    )
    assert options["poolclass"] is NullPool
    assert seen == [{"cafile": "rds-ca.pem"}]
    assert options["connect_args"]["ssl"].check_hostname
    assert options["connect_args"]["ssl"].verify_mode == ssl.CERT_REQUIRED


def test_lambda_credentials_rotate_without_profile_or_metadata(settings, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "unit-media")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "dummy-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token-one")
    monkeypatch.delenv("AWS_CREDENTIAL_EXPIRATION", raising=False)
    provider = credential_provider(
        settings.model_copy(update={"storage_credential_mode": "lambda"})
    )
    assert isinstance(provider, LambdaProvider)
    assert provider.retrieve().session_token == "token-one"
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token-two")
    assert provider.retrieve().session_token == "token-two"
    monkeypatch.delenv("AWS_SESSION_TOKEN")
    monkeypatch.setenv("AWS_PROFILE", "must-never-be-read")
    with pytest.raises(ValueError, match="Lambda storage credentials unavailable"):
        provider.retrieve()
    with pytest.raises(ValueError, match="overrides"):
        credential_provider(
            settings.model_copy(
                update={"storage_credential_mode": "lambda", "minio_access_key": "dummy"}
            )
        )
