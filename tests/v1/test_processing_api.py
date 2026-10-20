import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from contracts.gateway import GatewayAdapter
from contracts.v1 import Actor
from processing import v1_api
from processing.config import Settings, get_settings
from processing.database import get_v1_session
from processing.errors import ProcessingError


def event(path, *, owner=None, method="GET", role="publisher", body=None):
    data = {
        "version": "2.0",
        "rawPath": "/api/processing" + path,
        "rawQueryString": "",
        "headers": {"x-owner-id": str(uuid4()), "x-role": "admin"},
        "requestContext": {"http": {"method": method}},
        "body": body,
    }
    if owner:
        data["requestContext"]["authorizer"] = {"lambda": Actor(str(owner), role).to_context()}
    return data


@pytest.fixture
def app():
    app = v1_api.create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        postgres_dsn="postgresql://runtime@unused/processing_db", database_tls=False
    )
    return app


@pytest.fixture
def pair():
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        asset_id=uuid4(),
        owner_id=uuid4(),
        status="failed",
        outputs=[],
        error="Encoding failed",
        created_at=now,
        updated_at=now,
    )
    attempt = SimpleNamespace(
        id=uuid4(),
        attempt_number=1,
        state="failed",
        queued_at=now,
        started_at=now,
        finished_at=now,
        error="Encoding failed",
    )
    return job, attempt


def fake_session(app, pair):
    session = AsyncMock()
    row = Mock()
    row.one_or_none.return_value = pair
    session.execute.return_value = row
    app.dependency_overrides[get_v1_session] = lambda: session
    return session


async def test_verified_owner_filters_database_query_and_public_identity(app, pair):
    session = fake_session(app, pair)
    result = await GatewayAdapter(app, service="processing").invoke(
        event(f"/jobs/{pair[0].id}", owner=pair[0].owner_id)
    )
    assert result["statusCode"] == 200
    assert result["headers"]["cache-control"] == "private, no-store"
    data = json.loads(result["body"])
    assert data["processing_job_id"] == str(pair[0].id)
    assert data["asset_id"] == str(pair[0].asset_id)
    assert "source" not in data
    query = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert pair[0].owner_id in query.params.values()
    assert pair[0].id in query.params.values()
    assert "jobs.owner_id =" in str(query) and "submission_guards.owner_id =" in str(query)


async def test_verified_owner_list_is_private_no_store(app, pair):
    session = AsyncMock()
    session.execute.return_value = [pair]
    app.dependency_overrides[get_v1_session] = lambda: session
    request = event("/jobs", owner=pair[0].owner_id)
    request["rawQueryString"] = f"asset_ids={pair[0].asset_id}"

    result = await GatewayAdapter(app, service="processing").invoke(request)

    assert result["statusCode"] == 200
    assert result["headers"]["cache-control"] == "private, no-store"
    assert json.loads(result["body"])[0]["processing_job_id"] == str(pair[0].id)


async def test_wrong_owner_is_not_found(app, pair):
    session = fake_session(app, None)
    result = await GatewayAdapter(app, service="processing").invoke(
        event(f"/jobs/{pair[0].id}", owner=uuid4())
    )
    assert result["statusCode"] == 404
    assert "Job not found" in result["body"]
    session.execute.assert_awaited_once()


async def test_direct_asgi_and_forged_header_never_reach_sql(app):
    def forbidden():
        pytest.fail("untrusted request reached SQL")

    app.dependency_overrides[get_v1_session] = forbidden
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        result = await client.get(
            f"/jobs/{uuid4()}",
            headers={
                "X-Owner-Id": str(uuid4()),
                "X-Role": "publisher",
                "Authorization": "Bearer forged",
            },
        )
    assert result.status_code == 401
    result = await GatewayAdapter(app, service="processing").invoke(event(f"/jobs/{uuid4()}"))
    assert result["statusCode"] == 401


@pytest.mark.parametrize("path", ["/jobs", "/internal/v1/jobs"])
async def test_public_source_creation_has_no_route_and_no_database(app, path):
    def forbidden():
        pytest.fail("public source creation reached SQL")

    app.dependency_overrides[get_v1_session] = forbidden
    result = await GatewayAdapter(app, service="processing").invoke(
        event(path, owner=uuid4(), method="POST", body=json.dumps({"source": {"key": "forged"}}))
    )
    assert result["statusCode"] in (404, 405)


async def test_viewer_cannot_mutate_before_database(app):
    def forbidden():
        pytest.fail("viewer mutation reached SQL")

    app.dependency_overrides[get_v1_session] = forbidden
    result = await GatewayAdapter(app, service="processing").invoke(
        event(
            f"/jobs/{uuid4()}/retry",
            owner=uuid4(),
            method="POST",
            role="viewer",
            body=json.dumps({"retry_request_id": str(uuid4())}),
        )
    )
    assert result["statusCode"] == 403


async def test_retry_delegates_transactional_outbox_with_owner_and_idempotency(
    app, pair, monkeypatch
):
    retry = AsyncMock(return_value={"status": "queued", "job_id": str(pair[0].id)})
    monkeypatch.setattr(v1_api, "retry_owned", retry)
    fake_session(app, pair)
    request_id = uuid4()
    data = event(
        f"/jobs/{pair[0].id}/retry",
        owner=pair[0].owner_id,
        method="POST",
        body=json.dumps({"retry_request_id": str(request_id)}),
    )
    data["headers"]["content-type"] = "application/json"
    result = await GatewayAdapter(app, service="processing").invoke(data)
    assert result["statusCode"] == 202
    assert retry.await_args.args[1:] == (pair[0].owner_id, pair[0].id, request_id)


async def test_cancel_uses_existing_job_uuid(app, pair, monkeypatch):
    cancel = AsyncMock()
    monkeypatch.setattr(v1_api, "cancel_owned", cancel)
    fake_session(app, pair)
    result = await GatewayAdapter(app, service="processing").invoke(
        event(f"/jobs/{pair[0].id}", owner=pair[0].owner_id, method="DELETE")
    )
    assert result["statusCode"] == 204
    assert cancel.await_args.args[1:] == (pair[0].owner_id, pair[0].id)


async def test_bad_body_does_not_reflect_input(app):
    fake_session(app, None)
    data = event(
        f"/jobs/{uuid4()}/retry",
        owner=uuid4(),
        method="POST",
        body='{"retry_request_id":"private-secret-value"}',
    )
    data["headers"]["content-type"] = "application/json"
    result = await GatewayAdapter(app, service="processing").invoke(data)
    assert result["statusCode"] == 422
    assert "private-secret-value" not in result["body"]


async def test_db_failure_returns_safe_service_error(app):
    session = fake_session(app, None)
    session.execute.side_effect = OperationalError("SQL password", {}, Exception("private-secret"))
    result = await GatewayAdapter(app, service="processing").invoke(
        event(f"/jobs/{uuid4()}", owner=uuid4())
    )
    assert result["statusCode"] == 503
    assert json.loads(result["body"]) == {"error": "Processing database unavailable"}


async def test_public_health_never_opens_a_database_session(app):
    """A health probe must not wake a paused Aurora cluster."""

    def forbidden():
        raise AssertionError("health opened a database session")

    app.dependency_overrides[get_v1_session] = forbidden
    result = await GatewayAdapter(app, service="processing").invoke(event("/health"))
    assert result["statusCode"] == 200
    assert "cache-control" not in result["headers"]
    assert json.loads(result["body"])["service"] == "processing"


async def test_malformed_actor_denied(app):
    value = event(f"/jobs/{uuid4()}", owner=uuid4())
    value["requestContext"]["authorizer"]["lambda"]["role"] = "operator"
    result = await GatewayAdapter(app, service="processing").invoke(value)
    assert result["statusCode"] == 401


@pytest.mark.parametrize("value", ["bad", "", ",".join(str(uuid4()) for _ in range(201))])
async def test_batch_input_bounded(app, value):
    fake_session(app, None)
    data = event("/jobs", owner=uuid4()) | {"rawQueryString": "asset_ids=" + value}
    result = await GatewayAdapter(app, service="processing").invoke(data)
    assert result["statusCode"] == 422


async def test_cancel_reads_owned_job_then_closes_read_transaction(monkeypatch, pair):
    import sys
    from types import ModuleType

    messaging = ModuleType("processing.messaging")
    messaging.cancel_asset = AsyncMock()
    monkeypatch.setitem(sys.modules, "processing.messaging", messaging)
    session = AsyncMock()
    monkeypatch.setattr(v1_api, "owned_pair", AsyncMock(return_value=pair))
    await v1_api.cancel_owned(session, pair[0].owner_id, pair[0].id)
    session.rollback.assert_awaited_once()
    messaging.cancel_asset.assert_awaited_once_with(session, pair[0].owner_id, pair[0].asset_id)


async def test_retry_passes_domain_conflict_without_changing_identity(monkeypatch):
    import sys
    from types import ModuleType

    messaging = ModuleType("processing.messaging")
    messaging.retry_job = AsyncMock(
        side_effect=ProcessingError(409, "Only failed jobs can be retried")
    )
    monkeypatch.setitem(sys.modules, "processing.messaging", messaging)
    with pytest.raises(ProcessingError) as exc:
        await v1_api.retry_owned(AsyncMock(), uuid4(), uuid4(), uuid4())
    assert exc.value.status_code == 409
