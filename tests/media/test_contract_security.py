import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from pydantic import ValidationError

from media.config import Settings
from media.errors import PeerError
from media.schemas.edit import EditRequest
from media.schemas.public import Credentials
from media.services.media_type import sniff_video_type
from media.services.processing_client import ProcessingClient
from media.services.security import hash_password, issue_token, read_token, verify_password


@pytest.mark.parametrize(
    "payload",
    [
        {"operations": []},
        {"operations": [{"operation": "clip", "params": {"start": -1, "end": 3}}]},
        {"operations": [{"operation": "clip", "params": {"start": 3, "end": 3}}]},
        {"operations": [{"operation": "crop", "params": {"x": 0, "y": 0, "w": True, "h": 5}}]},
        {"operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}] * 2},
        {
            "operations": [
                {"operation": op, "params": {"height": 360}} for op in ["upscale", "downscale"]
            ]
        },
        {"operations": [{"operation": "convert", "params": {"format": "exe"}}]},
        {"operations": [{"operation": "clip", "params": {"start": 0, "end": float("inf")}}]},
    ],
)
def test_invalid_edits_fail_before_acceptance(payload):
    with pytest.raises(ValidationError):
        EditRequest.model_validate(payload)


def test_edit_order_is_not_canonicalized():
    operations = [
        {"operation": "crop", "params": {"x": 0, "y": 0, "w": 12, "h": 12}},
        {"operation": "clip", "params": {"start": 0, "end": 3}},
    ]
    request = EditRequest(operations=operations)
    assert request.stored_operations() == operations
    assert request.operation("crop").params.w == 12 and request.operation("convert") is None


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"", ""),
        (b"\x1aE\xdf\xa3" + b"webm" + b" " * 10, "video/webm"),
        (b"\x1aE\xdf\xa3" + b"matroska" + b" " * 10, "video/x-matroska"),
        (b"\x1aE\xdf\xa3" + b"unknown" + b" " * 10, ""),
        (b"RIFFxxxxAVI ", "video/x-msvideo"),
        (b"xxxxftypqt  ", "video/quicktime"),
        (b"xxxxmoovxxxx", "video/quicktime"),
        (b"\x00\x00\x01\xba" + b" " * 12, "video/mpeg"),
        (bytes([0x47]) + b" " * 187 + bytes([0x47]) + b" " * 187 + bytes([0x47]), "video/mpeg"),
        (b"this is no video", ""),
        (b"xxxxftypisom", "video/mp4"),
    ],
)
def test_sniffing_reuses_inherited_container_rules(head, expected):
    assert sniff_video_type(head) == (expected or None)


def test_settings_reject_other_databases_and_missing_jwt(settings):
    assert Settings(postgres_dsn="postgres://localhost/media_db").postgres_dsn.startswith(
        "postgresql+asyncpg:"
    )
    assert Settings(postgres_dsn=settings.postgres_dsn, migration_dsn=None).migration_dsn is None
    with pytest.raises(ValidationError):
        Settings(postgres_dsn="sqlite:///not-a-live-media-db")
    with pytest.raises(RuntimeError):
        issue_token(uuid4(), Settings(postgres_dsn=settings.postgres_dsn, jwt_secret=""))
    with pytest.raises(ValidationError):
        Credentials(email="a@example.com", password="é" * 40)


def test_cookie_token_tampering_expiry_and_password_byte_limit(settings):
    user_id = uuid4()
    token = issue_token(user_id, settings)
    assert read_token(token, settings) == user_id
    for candidate in [
        "malformed",
        token + "tamper",
        jwt.encode(
            {"sub": str(user_id), "iat": 0, "exp": 1},
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        ),
    ]:
        with pytest.raises(ValueError):
            read_token(candidate, settings)
    with pytest.raises(ValueError):
        hash_password("é" * 40)
    assert not verify_password("password", "invalid-hash")


async def test_password_hashing_can_run_without_blocking_event_loop():
    from starlette.concurrency import run_in_threadpool

    entered = asyncio.Event()

    async def work():
        entered.set()
        return await run_in_threadpool(hash_password, "a-real-test-password")

    task = asyncio.create_task(work())
    await entered.wait()
    await asyncio.sleep(0)
    assert not task.done()
    hashed = await task
    assert await run_in_threadpool(verify_password, "a-real-test-password", hashed)
    assert not await run_in_threadpool(verify_password, "wrong-password", hashed)


async def test_processing_http_boundary_matches_authored_contract(job, settings):
    captured = []

    def handle(request):
        captured.append(request)
        body = job.model_dump(mode="json")
        return httpx.Response(
            200,
            json=[body]
            if request.method == "GET" and request.url.path == "/internal/v1/jobs"
            else body,
        )

    async with httpx.AsyncClient(
        base_url="http://processing.test", transport=httpx.MockTransport(handle)
    ) as http:
        peer = ProcessingClient(http, "forward-unit")
        payload = {
            "asset_id": str(job.asset_id),
            "owner_id": str(job.owner_id),
            "source": job.source.model_dump(mode="json"),
            "source_url": "http://minio:9000/source/test",
            "source_url_expires_at": (job.created_at + timedelta(hours=1)).isoformat(),
        }
        assert (await peer.submit(job.owner_id, payload)).job_id == job.job_id
        await peer.read(job.owner_id, job.job_id)
        assert len(await peer.batch(job.owner_id, [job.asset_id])) == 1
        assert await peer.batch(job.owner_id, []) == []
        await peer.retry(job.owner_id, job.job_id, uuid4())
        await peer.cancel(job.owner_id, job.asset_id)
    assert all(
        r.headers["Authorization"] == "Bearer forward-unit"
        and r.headers["X-Owner-Id"] == str(job.owner_id)
        for r in captured
    )
    assert "operations" not in json.loads(captured[0].content)
    from starlette.concurrency import run_in_threadpool

    schema = json.loads(
        await run_in_threadpool(
            Path("project-roadmap/design/05-contracts/processing.openapi.json").read_text
        )
    )
    submit = schema["components"]["schemas"]["SubmitJob"]
    assert set(payload) <= set(submit["properties"])
    assert set(submit["required"]) <= set(payload)
    assert "operations" not in submit["required"]
    assert submit["properties"]["operations"]["minItems"] == 1


@pytest.mark.parametrize("code", [401, 404, 409, 410, 500])
async def test_processing_safe_errors_never_expose_peer_body(job, code):
    async with httpx.AsyncClient(
        base_url="http://peer.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(code, text="sensitive peer content")
        ),
    ) as client:
        with pytest.raises(PeerError) as error:
            await ProcessingClient(client, "token").read(job.owner_id, job.job_id)
    assert error.value.status_code == (code if code in (404, 409, 410) else 503)
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "malformation", ["json", "owner", "job-id", "source", "duplicate-batch", "foreign-batch"]
)
async def test_processing_rejects_malformed_or_mismatched_responses(job, malformation):
    body = job.model_dump(mode="json")
    if malformation == "owner":
        body["owner_id"] = str(uuid4())
    if malformation == "job-id":
        body["job_id"] = str(uuid4())
    if malformation == "source":
        body["source"]["sha256"] = "b" * 64
    if malformation == "foreign-batch":
        body["asset_id"] = str(uuid4())
    response_body = [body, body] if malformation == "duplicate-batch" else [body]

    def handle(request):
        if malformation == "json":
            return httpx.Response(200, text="not json")
        return httpx.Response(200, json=response_body if "batch" in malformation else body)

    async with httpx.AsyncClient(
        base_url="http://peer.test", transport=httpx.MockTransport(handle)
    ) as http:
        peer = ProcessingClient(http, "token")
        with pytest.raises(PeerError):
            if "batch" in malformation:
                await peer.batch(job.owner_id, [job.asset_id])
            elif malformation == "source":
                await peer.submit(
                    job.owner_id,
                    {"asset_id": str(job.asset_id), "source": job.source.model_dump(mode="json")},
                )
            else:
                await peer.read(job.owner_id, job.job_id)


async def test_processing_timeout_and_unconfigured_token(job):
    def handle(request):
        raise httpx.ReadTimeout("private URL omitted", request=request)

    async with httpx.AsyncClient(
        base_url="http://peer.test", transport=httpx.MockTransport(handle)
    ) as http:
        for candidate in ["", "token"]:
            with pytest.raises(PeerError):
                await ProcessingClient(http, candidate).read(job.owner_id, job.job_id)
