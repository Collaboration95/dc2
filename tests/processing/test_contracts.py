"""Frozen Processing HTTP contract, including replay and cancel-first operations."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from _processing_doubles import pair
from pydantic import ValidationError

from legacy.processing_rq import service as legacy_service
from legacy.processing_rq.config import LegacySettings as Settings
from legacy.processing_rq.config import get_settings
from legacy.processing_rq.main import create_app
from legacy.processing_rq.schemas import SourceAccess, SubmitJob
from processing import lifecycle, service
from processing.database import get_session
from processing.schemas import RetryJob

CONTRACTS = Path(__file__).resolve().parents[2] / "project-roadmap/design/05-contracts"


def test_all_frozen_operation_ids_and_retry_shape():
    designed = json.loads((CONTRACTS / "processing.openapi.json").read_text())
    live = create_app().openapi()
    for path, verbs in designed["paths"].items():
        for method, operation in verbs.items():
            assert (
                live["paths"]["/internal/v1" + path][method]["operationId"]
                == operation["operationId"]
            )
    expected = designed["components"]["schemas"]["RetryRequest"]
    assert set(RetryJob.model_fields) == set(expected["properties"])
    with pytest.raises(ValidationError):
        RetryJob.model_validate({"retry_request_id": str(uuid4()), "extra": 1})


def test_normal_upload_wire_omission_and_full_source_grant(submission):
    assert SubmitJob.model_validate(submission).operations == []
    with pytest.raises(ValidationError):
        SubmitJob.model_validate({**submission, "operations": []})
    grant = SourceAccess.model_validate(
        {
            "source": submission["source"],
            "source_url": "http://internal-source.test/private",
            "expires_at": submission["source_url_expires_at"],
        }
    )
    assert grant.source.asset_id == SubmitJob.model_validate(submission).asset_id
    with pytest.raises(ValidationError):
        SourceAccess.model_validate(
            {
                "source_url": "http://internal-source.test/private",
                "expires_at": submission["source_url_expires_at"],
            }
        )


async def test_http_retry_submit_batch_single_cancel_shapes(monkeypatch, submission):
    app = create_app()
    session = AsyncMock()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: Settings(
        postgres_dsn="postgresql://unused@unused/db", service_token="test-forward"
    )
    job, attempt, _, _ = pair("queued")
    response = service.job_response(job, attempt)
    submit = AsyncMock(return_value=(response, True))
    monkeypatch.setattr(legacy_service, "submit_job", submit)
    monkeypatch.setattr(legacy_service, "get_job", AsyncMock(return_value=response))
    monkeypatch.setattr(legacy_service, "list_jobs", AsyncMock(return_value=[response]))
    monkeypatch.setattr(lifecycle, "retry_job", AsyncMock(return_value=response))
    monkeypatch.setattr(lifecycle, "cancel_asset", AsyncMock())
    publish = AsyncMock()
    monkeypatch.setattr("legacy.processing_rq.main.publish", publish)
    headers = {"Authorization": "Bearer test-forward", "X-Owner-Id": submission["owner_id"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        assert (await client.post("/internal/v1/jobs", json=submission)).status_code == 201
        submit.return_value = (response, False)
        assert (await client.post("/internal/v1/jobs", json=submission)).status_code == 200
        read = await client.get(f"/internal/v1/jobs/{job.id}")
        assert read.json() == response.model_dump(mode="json", exclude_none=True)
        listed = await client.get("/internal/v1/jobs", params={"asset_ids": str(job.asset_id)})
        assert listed.json() == [read.json()]
        retry = await client.post(
            f"/internal/v1/jobs/{job.id}/retry", json={"retry_request_id": str(uuid4())}
        )
        assert retry.status_code == 202 and retry.json() == read.json()
        cancelled = await client.delete(f"/internal/v1/assets/{job.asset_id}/job")
        assert cancelled.status_code == 204 and cancelled.content == b""
    assert publish.await_count == 3


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "POST",
            "/internal/v1/jobs/" + str(uuid4()) + "/retry",
            {"retry_request_id": str(uuid4())},
        ),
        ("DELETE", "/internal/v1/assets/" + str(uuid4()) + "/job", None),
    ],
)
async def test_retry_cancel_auth_precedes_persistence(method, path, body):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        postgres_dsn="postgresql://unused@unused/db", service_token="test-forward"
    )

    def forbidden():
        pytest.fail("Missing forward service auth reached persistence")

    app.dependency_overrides[get_session] = forbidden
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        reply = await client.request(method, path, json=body, headers={"X-Owner-Id": str(uuid4())})
    assert reply.status_code == 401
