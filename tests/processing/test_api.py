from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from processing.config import Settings, get_settings
from processing.database import get_session
from processing.main import create_app


@pytest.fixture
def application():
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        postgres_dsn="postgresql://unused@unreachable/processing_db",
        service_token="test-processing-secret",
    )
    return application


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic wrong", "Bearer"])
@pytest.mark.parametrize("route", ["submit", "get", "batch"])
async def test_rejects_credentials_before_database(application, submission, authorization, route):
    def forbidden_database_access():
        pytest.fail("unauthenticated request reached the database dependency")

    application.dependency_overrides[get_session] = forbidden_database_access
    headers = {"X-Owner-Id": submission["owner_id"]}
    if authorization is not None:
        headers["Authorization"] = authorization
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        if route == "submit":
            response = await client.post("/internal/v1/jobs", json=submission, headers=headers)
        elif route == "get":
            response = await client.get(f"/internal/v1/jobs/{uuid4()}", headers=headers)
        else:
            response = await client.get(
                "/internal/v1/jobs",
                params={"asset_ids": submission["asset_id"]},
                headers=headers,
            )
    assert response.status_code == 401
    assert response.json() == {"error": "Missing or invalid service credentials"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert not hasattr(application.state, "engine")


async def test_unconfigured_token_fails_closed_without_database(application, submission):
    application.dependency_overrides[get_settings] = lambda: Settings(
        postgres_dsn="postgresql://unused@unreachable/processing_db",
        service_token="",
    )

    def forbidden_database_access():
        pytest.fail("unconfigured auth reached the database dependency")

    application.dependency_overrides[get_session] = forbidden_database_access
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/v1/jobs",
            json=submission,
            headers={"X-Owner-Id": submission["owner_id"], "Authorization": "Bearer anything"},
        )
    assert response.status_code == 503
    assert "not configured" in response.json()["error"]


@pytest.mark.parametrize("owner_header", [None, "invalid-uuid"])
async def test_requires_valid_owner_header(application, submission, owner_header):
    application.dependency_overrides[get_session] = lambda: AsyncMock()
    headers = {"Authorization": "Bearer test-processing-secret"}
    if owner_header is not None:
        headers["X-Owner-Id"] = owner_header
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/internal/v1/jobs", json=submission, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["header", "X-Owner-Id"]


@pytest.mark.parametrize("asset_ids", [None, "", "invalid", ",".join([str(uuid4())] * 201)])
async def test_batch_requires_bounded_uuid_list(application, submission, asset_ids):
    application.dependency_overrides[get_session] = lambda: AsyncMock()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(
            "/internal/v1/jobs",
            params={} if asset_ids is None else {"asset_ids": asset_ids},
            headers={
                "Authorization": "Bearer test-processing-secret",
                "X-Owner-Id": submission["owner_id"],
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:2] == ["query", "asset_ids"]


@pytest.mark.parametrize("failure", [None, OperationalError("SELECT 1", {}, Exception("secret"))])
async def test_health_probes_db_and_does_not_expose_driver_errors(application, failure):
    session = AsyncMock()
    session.execute.side_effect = failure
    application.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    session.execute.assert_awaited_once()
    assert str(session.execute.call_args.args[0]) == "SELECT 1"
    if failure is None:
        assert response.status_code == 200
        assert response.json()["worker_dispatch_connected"] is False
        assert response.json()["stage"] == "intake-only"
    else:
        assert response.status_code == 503
        assert response.json() == {"error": "Processing database unavailable"}


async def test_session_dependency_owns_and_closes_only_processing_pool(application):
    # Build the real session but execute no SQL. This proves the pool lifecycle
    # without requiring a live server or touching MM's engine.
    @application.get("/test-session")
    async def session_probe():
        return {"ok": True}

    from starlette.requests import Request

    request = Request({"type": "http", "app": application})
    settings = application.dependency_overrides[get_settings]()
    async with application.router.lifespan_context(application):
        async for session in get_session(request, settings):
            assert session.bind.url.database == "processing_db"
        engine = application.state.engine
        async for session in get_session(request, settings):
            assert session.bind is engine
    assert application.state.engine is None
