"""Public health is database-free; readiness is an IAM-gated direct invocation only."""

from unittest.mock import AsyncMock

import pytest

from contracts.gateway import GatewayAdapter, is_readiness_probe
from media import database as media_database
from media import lambda_handler as media_lambda
from media.config import Settings as MediaSettings
from media.main import create_v1_app
from processing import config as processing_config
from processing import database as processing_database
from processing import lambda_handler as processing_lambda
from processing.config import Settings as ProcessingSettings
from processing.v1_api import create_app
from runtime_support import lambda_db


def gateway_event(service, path):
    return {
        "version": "2.0",
        "rawPath": f"/api/{service}{path}",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {"http": {"method": "GET"}},
    }


@pytest.mark.parametrize(
    "service,app",
    [("media", create_v1_app()), ("processing", create_app())],
)
async def test_public_health_is_served_without_any_database_work(service, app, monkeypatch):
    app.dependency_overrides[processing_config.get_settings] = lambda: ProcessingSettings(
        postgres_dsn="postgresql://runtime@unused/processing_db"
    )
    forbidden = AsyncMock(side_effect=AssertionError("health reached the database"))
    monkeypatch.setattr(media_database, "invocation_session", forbidden)
    monkeypatch.setattr(media_database, "create_async_engine", forbidden)
    monkeypatch.setattr(processing_database, "create_async_engine", forbidden)
    result = await GatewayAdapter(app, service=service).invoke(gateway_event(service, "/health"))
    assert result["statusCode"] == 200
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "service,app",
    [("media", create_v1_app()), ("processing", create_app())],
)
async def test_gateway_cannot_reach_a_readiness_route(service, app):
    # The proxy route would carry /ready to the Lambda; the application must not serve it.
    for path in ("/ready", "/ready/"):
        event = gateway_event(service, path)
        event["requestContext"]["authorizer"] = {
            "lambda": {
                "schema_version": 1,
                "integration": "dc2-gateway-v1",
                "owner_id": "00000000-0000-4000-8000-000000000001",
                "role": "publisher",
            }
        }
        result = await GatewayAdapter(app, service=service).invoke(event)
        assert result["statusCode"] in (404, 405)


@pytest.mark.parametrize(
    "event,expected",
    [
        ({"dc2_operation": "ready"}, True),
        ({"dc2_operation": "ready", "version": "2.0"}, False),
        ({"dc2_operation": "ready", "requestContext": {}}, False),
        ({"dc2_operation": "other"}, False),
        ({}, False),
        ("ready", False),
    ],
)
def test_only_a_bare_direct_invocation_is_a_readiness_probe(event, expected):
    assert is_readiness_probe(event) is expected


def test_readiness_probe_is_dispatched_only_by_the_adapter_that_has_one():
    called = AsyncMock(return_value={"ready": True})
    with_probe = GatewayAdapter(create_app(), service="processing", readiness=called)
    assert with_probe({"dc2_operation": "ready"}) == {"ready": True}
    without_probe = GatewayAdapter(create_app(), service="processing")
    # Without a hook it is just a malformed event: refused, never treated as a request.
    assert without_probe({"dc2_operation": "ready"})["statusCode"] == 401


def test_both_deployed_handlers_expose_a_readiness_hook():
    assert media_lambda.handler.readiness is not None
    assert processing_lambda.handler.readiness is not None


class Connection:
    def __init__(self, failure):
        self.failure = failure
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        if self.failure:
            raise self.failure


async def test_processing_readiness_checks_the_database_and_hides_driver_text(monkeypatch):
    settings = ProcessingSettings(
        postgres_dsn="postgresql://runtime@unused/processing_db", database_tls=False
    )
    for failure, expected in ((None, True), (OSError("password=secret"), False)):
        lambda_db.reset()  # a cold environment per case; the warm reuse has its own tests
        connection = Connection(failure)
        engine = AsyncMock()
        engine.connect = lambda c=connection: Context(c)
        monkeypatch.setattr(processing_database, "create_async_engine", lambda *a, e=engine, **k: e)
        result = await processing_database.database_ready(settings)
        assert result["ready"] is expected
        assert "secret" not in str(result)
        assert connection.statements == ["SELECT 1"]
        # A healthy engine stays warm; a failed readiness probe retires it.
        assert engine.dispose.await_count == (0 if expected else 1)


class Context:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *exc):
        return False


async def test_media_readiness_checks_the_database_and_hides_driver_text(monkeypatch):
    settings = MediaSettings(postgres_dsn="postgresql://runtime@unused/media_db")
    for failure, expected in ((None, True), (OSError("password=secret"), False)):
        connection = Connection(failure)

        def session(_settings, c=connection):
            return Context(c)

        monkeypatch.setattr(media_database, "invocation_session", session)
        result = await media_database.database_ready(settings)
        assert result["ready"] is expected
        assert "secret" not in str(result)
        assert connection.statements == ["SELECT 1"]
