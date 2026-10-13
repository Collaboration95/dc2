"""Real Media PostgreSQL persistence with a controlled HTTP Processing peer.

RUN_MEDIA_TESTS=1 requires a separately migrated MEDIA_POSTGRES_DSN. Tests use
real independent SQL sessions and delete only their UUID users/assets/objects.
These tests do not establish full Processing/FFmpeg/browser integration.
"""

import asyncio
import hashlib
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from media.config import Settings, get_settings
from media.main import create_app
from media.models import Asset, CleanupIntent, RequestKey, RetryIntent, StagedObject, User, now
from media.recovery import reconcile
from media.services.processing_client import ProcessingClient
from media.services.security import issue_token
from media.services.storage import get_storage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MEDIA_TESTS") != "1",
        reason="set RUN_MEDIA_TESTS=1 for real Media PostgreSQL",
    ),
]
VIDEO = b"\x00\x00\x00\x18ftypisom" + b"content" * 10


class Objects:
    def __init__(self):
        self.sources = {}
        self.outputs = {}
        self.deleted = []
        self.delete_fails = False
        self.put_fails = False
        self.copy_fails = False

    async def put_source(self, key, stream, size, media_type):
        if self.put_fails:
            raise OSError("controlled storage failure")
        self.sources[key] = stream.read()
        assert len(self.sources[key]) == size

    async def delete_source(self, key):
        if self.delete_fails:
            raise OSError("controlled storage failure")
        self.deleted.append(key)
        self.sources.pop(key, None)

    async def source_grant(self, key):
        return f"http://minio:9000/test-source/{key}?signed=test", now() + timedelta(minutes=15)

    async def sign_output(self, key, *, inline=False):
        return f"https://localhost:4443/test-output/{key}?signed=test"

    async def read_playlist(self, key):
        return self.outputs[key]

    async def copy_output_source(self, output, key):
        if self.copy_fails:
            raise OSError("controlled copy failure")
        data = self.outputs[output.object_key]
        self.sources[key] = data
        return len(data), hashlib.sha256(data).hexdigest()


class Boundary:
    def __init__(self):
        self.jobs = {}
        self.submissions = []
        self.cancellations = []
        self.retries = []
        self.cancelled = set()
        self.down = False
        self.lost_submit_ack = False
        self.lost_cancel_ack = False
        self.lost_retry_ack = False
        self.missing = False
        self.batch_requests = []

    def handle(self, request):
        import json

        assert request.headers["authorization"] == "Bearer controlled-forward"
        owner = request.headers["x-owner-id"]
        path = request.url.path
        if self.down:
            raise httpx.ConnectError("controlled outage", request=request)
        if request.method == "DELETE":
            asset_id = path.split("/")[-2]
            self.cancellations.append((owner, asset_id))
            self.cancelled.add(asset_id)
            if self.lost_cancel_ack:
                raise httpx.ReadTimeout("controlled lost acknowledgement", request=request)
            return httpx.Response(204)
        if request.method == "POST" and path == "/internal/v1/jobs":
            body = json.loads(request.content)
            self.submissions.append(body)
            asset_id = body["asset_id"]
            if asset_id in self.cancelled:
                return httpx.Response(410)
            existing = self.jobs.get(asset_id)
            if existing is None:
                stamp = datetime.now(UTC).isoformat()
                existing = {
                    "asset_id": asset_id,
                    "owner_id": owner,
                    "job_id": str(uuid4()),
                    "source": body["source"],
                    "status": "queued",
                    "outputs": [],
                    "current_attempt": {
                        "attempt_id": str(uuid4()),
                        "number": 1,
                        "state": "queued",
                        "queued_at": stamp,
                    },
                    "created_at": stamp,
                    "updated_at": stamp,
                }
                self.jobs[asset_id] = existing
            if self.lost_submit_ack:
                raise httpx.ReadTimeout("controlled lost acknowledgement", request=request)
            return httpx.Response(200, json=existing)
        if request.method == "POST" and path.endswith("/retry"):
            job_id = path.split("/")[-2]
            body = json.loads(request.content)
            job = next(j for j in self.jobs.values() if j["job_id"] == job_id)
            identity = (owner, job_id, body["retry_request_id"])
            if identity not in self.retries:
                if job["status"] != "failed":
                    return httpx.Response(409)
                self.retries.append(identity)
                job["status"] = "queued"
                job["outputs"] = []
                job["current_attempt"].update(
                    number=job["current_attempt"]["number"] + 1,
                    attempt_id=str(uuid4()),
                    state="queued",
                )
            if self.lost_retry_ack:
                raise httpx.ReadTimeout("controlled lost acknowledgement", request=request)
            return httpx.Response(202, json=job)
        if request.method == "GET" and path == "/internal/v1/jobs":
            ids = request.url.params["asset_ids"].split(",")
            self.batch_requests.append((owner, ids))
            return httpx.Response(
                200,
                json=[]
                if self.missing
                else [
                    j
                    for i, j in self.jobs.items()
                    if i in ids and j["owner_id"] == owner and i not in self.cancelled
                ],
            )
        job_id = path.split("/")[-1]
        job = next(
            (
                j
                for j in self.jobs.values()
                if j["job_id"] == job_id
                and j["owner_id"] == owner
                and j["asset_id"] not in self.cancelled
            ),
            None,
        )
        return httpx.Response(404 if job is None or self.missing else 200, json=job or {})


@pytest_asyncio.fixture
async def lane():
    assert os.getenv("MEDIA_POSTGRES_DSN"), "MEDIA_POSTGRES_DSN is required"
    settings = Settings(
        postgres_dsn=os.environ["MEDIA_POSTGRES_DSN"],
        jwt_secret="integration-signing-secret-32bytes-long",
        processing_service_token="controlled-forward",
        source_service_token="controlled-reverse",
    )
    engine = create_async_engine(settings.postgres_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT asset_id FROM cleanup_intents LIMIT 0"))
    users = [
        User(
            id=uuid4(),
            email=f"media-{uuid4().hex}@example.com",
            password_hash="unusable",
            role="user",
        )
        for _ in range(2)
    ]
    async with factory() as session:
        session.add_all(users)
        await session.commit()
    objects, boundary = Objects(), Boundary()
    peer_http = httpx.AsyncClient(
        base_url="http://processing.test", transport=httpx.MockTransport(boundary.handle)
    )
    peer = ProcessingClient(peer_http, "controlled-forward")
    app = create_app()
    app.state.engine = engine
    app.state.http_client = peer_http
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage] = lambda: objects
    clients = [
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://media.test")
        for u in users
    ]
    for client, user in zip(clients, users, strict=True):
        client.cookies.set(
            "access_token", issue_token(user.id, settings), domain="media.test", path="/"
        )
    try:
        yield SimpleNamespace(
            app=app,
            factory=factory,
            settings=settings,
            objects=objects,
            boundary=boundary,
            peer=peer,
            clients=clients,
            users=users,
        )
    finally:
        for client in clients:
            await client.aclose()
        await peer_http.aclose()
        ids = [u.id for u in users]
        async with factory() as session:
            asset_ids = select(Asset.id).where(Asset.owner_id.in_(ids))
            for model in (CleanupIntent, RetryIntent, RequestKey):
                await session.execute(delete(model).where(model.asset_id.in_(asset_ids)))
            await session.execute(delete(Asset).where(Asset.owner_id.in_(ids)))
            await session.execute(delete(User).where(User.id.in_(ids)))
            for key in objects.sources.keys() | set(objects.deleted):
                await session.execute(delete(StagedObject).where(StagedObject.key == key))
            await session.commit()
        await engine.dispose()


async def upload(lane, key=None, index=0, data=VIDEO, filename="lesson.mp4"):
    response = await lane.clients[index].post(
        "/upload",
        files={"file": (filename, data, "video/mp4")},
        headers={"Idempotency-Key": str(key)} if key else {},
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


async def row(lane, asset_id):
    async with lane.factory() as session:
        return await session.get(Asset, UUID(asset_id))


async def due(lane):
    async with lane.factory() as session:
        owned = select(Asset.id).where(Asset.owner_id.in_([u.id for u in lane.users]))
        for model, column in (
            (Asset, Asset.next_submit_at),
            (CleanupIntent, CleanupIntent.next_try_at),
            (RetryIntent, RetryIntent.next_try_at),
        ):
            await session.execute(
                update(model)
                .where(
                    Asset.owner_id.in_([u.id for u in lane.users])
                    if model is Asset
                    else model.asset_id.in_(owned)
                )
                .values({column: now() - timedelta(seconds=1)})
            )
        await session.commit()


async def done(lane, asset_id, media_type="video/mp4"):
    job = lane.boundary.jobs[asset_id]
    primary = f"outputs/{job['job_id']}/{job['current_attempt']['attempt_id']}/output.mp4"
    hls = f"outputs/{job['job_id']}/{job['current_attempt']['attempt_id']}/hls/master.m3u8"
    job.update(
        status="done",
        outputs=[
            {
                "kind": "primary",
                "object_key": primary,
                "media_type": media_type,
                "size_bytes": len(VIDEO),
                "sha256": hashlib.sha256(VIDEO).hexdigest(),
            },
            {
                "kind": "hls_manifest",
                "object_key": hls,
                "media_type": "application/vnd.apple.mpegurl",
            },
        ],
    )
    job["current_attempt"]["state"] = "succeeded"
    lane.objects.outputs[primary] = VIDEO
    lane.objects.outputs[hls] = b"#EXTM3U\nv0/index.m3u8\n"
    lane.objects.outputs[hls.rsplit("/", 1)[0] + "/v0/index.m3u8"] = b"#EXTM3U\nseg00001.ts\n"
    return job


async def test_pending_restart_and_normal_payload_omits_operations(lane):
    lane.boundary.down = True
    asset_id = await upload(lane)
    asset = await row(lane, asset_id)
    assert asset.operations == [] and asset.processing_job_id is None
    status = await lane.clients[0].get(f"/jobs/{asset_id}")
    assert status.json() == {
        "id": asset_id,
        "filename": "lesson.mp4",
        "status": "queued",
        "submission_status": "pending",
    }
    # Replace application/pool and repair through independently constructed SQL sessions.
    fresh = create_app()
    fresh.dependency_overrides.update(lane.app.dependency_overrides)
    lane.boundary.down = False
    await due(lane)
    counts = await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert counts["submission"] >= 1
    assert "operations" not in lane.boundary.submissions[-1]
    asset = await row(lane, asset_id)
    assert asset.submission_state == "submitted"
    assert asset.source_sha256 == hashlib.sha256(VIDEO).hexdigest()
    async with fresh.router.lifespan_context(fresh):
        fresh.state.http_client = lane.app.state.http_client
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fresh),
            base_url="https://media.test",
            cookies=lane.clients[0].cookies,
        ) as client:
            response = await client.get(f"/jobs/{asset_id}")
            assert response.status_code == 200 and response.json()["status"] == "queued"
        fresh.state.http_client = None


async def test_concurrent_replay_one_asset_cleanup_only_losers(lane):
    key = uuid4()
    barrier = asyncio.Barrier(8)

    async def request():
        await barrier.wait()
        return await upload(lane, key)

    ids = await asyncio.gather(*(request() for _ in range(8)))
    assert len(set(ids)) == 1
    async with lane.factory() as session:
        assets = list(
            await session.scalars(select(Asset).where(Asset.owner_id == lane.users[0].id))
        )
    assert len(assets) == 1 and len(lane.boundary.jobs) == 1
    assert set(lane.objects.sources) == {assets[0].source_key}
    assert assets[0].source_key not in lane.objects.deleted


async def test_replay_conflict_owner_operation_and_deleted_key(lane):
    key = uuid4()
    asset_id = await upload(lane, key)
    conflict = await lane.clients[0].post(
        "/upload",
        files={"file": ("lesson.mp4", VIDEO + b"x", "video/mp4")},
        headers={"Idempotency-Key": str(key)},
    )
    assert conflict.status_code == 409
    other_id = await upload(lane, key, index=1)
    assert other_id != asset_id
    assert (await lane.clients[1].get(f"/jobs/{asset_id}")).status_code == 404
    assert (await lane.clients[1].delete(f"/jobs/{asset_id}")).status_code == 404
    assert (await lane.clients[0].delete(f"/jobs/{asset_id}")).status_code == 204
    replay = await lane.clients[0].post(
        "/upload",
        files={"file": ("lesson.mp4", VIDEO, "video/mp4")},
        headers={"Idempotency-Key": str(key)},
    )
    assert replay.status_code == 410


async def test_deleted_derived_asset_edit_key_replay_is_410_without_recreation(lane):
    parent_id = await upload(lane)
    await done(lane, parent_id)
    key = uuid4()
    path = f"/jobs/{parent_id}/edit"
    body = {"operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}]}
    headers = {"Idempotency-Key": str(key)}
    accepted = await lane.clients[0].post(path, json=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    child_id = accepted.json()["job_id"]
    child = await row(lane, child_id)
    parent = await row(lane, parent_id)
    assert child.source_asset_id == parent.id and child.source_key != parent.source_key
    assert (await lane.clients[0].delete(f"/jobs/{child_id}")).status_code == 204
    assert (await lane.clients[0].get(f"/jobs/{child_id}")).status_code == 404
    assert (await lane.clients[0].get(f"/jobs/{parent_id}")).status_code == 200
    assert child.source_key not in lane.objects.sources
    assert set(lane.objects.sources) == {parent.source_key}
    async with lane.factory() as session:
        retained = await session.get(RequestKey, (lane.users[0].id, "edit", key))
        assert retained.asset_id == UUID(child_id)
        digest = retained.request_hash
        assert (await session.get(Asset, UUID(child_id))).deleted_at is not None

    sources, outputs = deepcopy(lane.objects.sources), deepcopy(lane.objects.outputs)
    deleted = list(lane.objects.deleted)
    submissions, jobs = deepcopy(lane.boundary.submissions), deepcopy(lane.boundary.jobs)
    cancellations = list(lane.boundary.cancellations)
    for _ in range(2):
        replay = await lane.clients[0].post(path, json=body, headers=headers)
        assert replay.status_code == 410, replay.text
    assert lane.objects.sources == sources and lane.objects.outputs == outputs
    assert lane.objects.deleted == deleted
    assert lane.boundary.submissions == submissions and lane.boundary.jobs == jobs
    assert lane.boundary.cancellations == cancellations
    async with lane.factory() as session:
        assets = list(await session.scalars(select(Asset).where(Asset.owner_id == parent.owner_id)))
        assert {a.id for a in assets} == {parent.id, child.id}
        assert next(a for a in assets if a.id == child.id).deleted_at is not None
        assert next(a for a in assets if a.id == parent.id).deleted_at is None
        retained = await session.get(RequestKey, (lane.users[0].id, "edit", key))
        assert retained.asset_id == child.id and retained.request_hash == digest
        assert not list(
            await session.scalars(
                select(StagedObject).where(
                    StagedObject.key.startswith(f"sources/{parent.owner_id}/")
                )
            )
        )


@pytest.mark.parametrize("mode", ["down", "missing"])
async def test_live_status_outage_is_503_single_and_batch(lane, mode):
    asset_id = await upload(lane)
    setattr(lane.boundary, mode, True)
    for path in [f"/jobs/{asset_id}", "/jobs"]:
        response = await lane.clients[0].get(path)
        assert response.status_code == 503
        assert "output_url" not in response.text


async def test_batch_filters_owner_and_operator_groups_actual_owners(lane):
    a = await upload(lane)
    b = await upload(lane, index=1)
    assert [x["id"] for x in (await lane.clients[0].get("/jobs")).json()] == [a]
    assert lane.boundary.batch_requests[-1] == (str(lane.users[0].id), [a])
    assert (await lane.clients[0].get("/admin/jobs")).status_code == 403
    async with lane.factory() as session:
        await session.execute(
            update(User).where(User.id == lane.users[0].id).values(role="operator")
        )
        await session.commit()
    page = await lane.clients[0].get("/admin/jobs")
    assert {x["id"] for x in page.json()} == {a, b}
    assert (str(lane.users[1].id), [b]) in lane.boundary.batch_requests
    assert (await lane.clients[0].delete(f"/admin/jobs/{b}")).status_code == 204
    assert lane.boundary.cancellations[-1] == (str(lane.users[1].id), b)


async def test_reverse_grant_owner_revision_direction_and_tombstone(lane):
    asset_id = await upload(lane)
    path = f"/internal/v1/assets/{asset_id}/source-access"
    headers = {"Authorization": "Bearer controlled-reverse", "X-Owner-Id": str(lane.users[0].id)}
    grant = await lane.clients[0].post(path, json={"revision": 1}, headers=headers)
    assert grant.status_code == 200
    source = grant.json()["source"]
    assert source == {
        "asset_id": asset_id,
        "revision": 1,
        "sha256": hashlib.sha256(VIDEO).hexdigest(),
        "size_bytes": len(VIDEO),
        "media_type": "video/mp4",
    }
    assert grant.json()["source_url"].startswith("http://minio:9000/")
    assert (
        await lane.clients[0].post(path, json={"revision": 2}, headers=headers)
    ).status_code == 409
    assert (
        await lane.clients[0].post(
            path, json={"revision": 1}, headers={**headers, "X-Owner-Id": str(lane.users[1].id)}
        )
    ).status_code == 404
    assert (
        await lane.clients[0].post(
            path,
            json={"revision": 1},
            headers={**headers, "Authorization": "Bearer controlled-forward"},
        )
    ).status_code == 401
    await lane.clients[0].delete(f"/jobs/{asset_id}")
    assert (
        await lane.clients[0].post(path, json={"revision": 1}, headers=headers)
    ).status_code == 404


@pytest.mark.parametrize("use_key", [True, False])
async def test_retry_lost_ack_stable_request_no_source_upload(lane, use_key):
    asset_id = await upload(lane)
    job = lane.boundary.jobs[asset_id]
    job["status"] = "failed"
    job["current_attempt"].update(state="failed", error="controlled failure")
    failed = (await lane.clients[0].get(f"/jobs/{asset_id}")).json()
    assert failed["status"] == "failed" and failed["error"] == "controlled failure"
    sources = deepcopy(lane.objects.sources)
    headers = {"Idempotency-Key": str(uuid4())} if use_key else {}
    lane.boundary.lost_retry_ack = True
    response = await lane.clients[0].post(f"/jobs/{asset_id}/retry", headers=headers)
    assert response.status_code == 503
    async with lane.factory() as session:
        intent = await session.scalar(
            select(RetryIntent).where(RetryIntent.asset_id == UUID(asset_id))
        )
    assert intent.confirmed_at is None
    lane.boundary.lost_retry_ack = False
    response = await lane.clients[0].post(f"/jobs/{asset_id}/retry", headers=headers)
    assert response.status_code == 202 and response.json()["job_id"] == asset_id
    assert len(lane.boundary.retries) == 1 and job["current_attempt"]["number"] == 2
    assert sources == lane.objects.sources
    if use_key:
        assert (
            await lane.clients[0].post(f"/jobs/{asset_id}/retry", headers=headers)
        ).status_code == 202
    assert (await lane.clients[0].post(f"/jobs/{asset_id}/retry")).status_code == 409


async def test_retry_reconciles_uncertain_ack_after_restart(lane):
    asset_id = await upload(lane)
    lane.boundary.jobs[asset_id]["status"] = "failed"
    lane.boundary.lost_retry_ack = True
    assert (await lane.clients[0].post(f"/jobs/{asset_id}/retry")).status_code == 503
    lane.boundary.lost_retry_ack = False
    await due(lane)
    await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    async with lane.factory() as session:
        intent = await session.scalar(
            select(RetryIntent).where(RetryIntent.asset_id == UUID(asset_id))
        )
    assert intent.confirmed_at and len(lane.boundary.retries) == 1


async def test_edit_pending_operations_independent_source_and_parent_delete(lane):
    asset_id = await upload(lane)
    await done(lane, asset_id)
    key = uuid4()
    operations = [
        {"operation": "clip", "params": {"start": 0, "end": 3}},
        {"operation": "convert", "params": {"format": "mkv"}},
    ]
    lane.boundary.down = True
    # Editing needs a live completed source, so source-status outage rejects before copy.
    assert (
        await lane.clients[0].post(
            f"/jobs/{asset_id}/edit",
            json={"operations": operations},
            headers={"Idempotency-Key": str(key)},
        )
    ).status_code == 503
    lane.boundary.down = False
    lane.boundary.lost_submit_ack = True
    child_response = await lane.clients[0].post(
        f"/jobs/{asset_id}/edit",
        json={"operations": operations},
        headers={"Idempotency-Key": str(key)},
    )
    assert child_response.status_code == 202, child_response.text
    child_id = child_response.json()["job_id"]
    child = await row(lane, child_id)
    assert child.operations == operations and child.source_asset_id == UUID(asset_id)
    assert child.submission_state == "pending" and child.filename.endswith("-edited.mkv")
    assert child.source_key != (await row(lane, asset_id)).source_key
    await lane.clients[0].delete(f"/jobs/{asset_id}")
    assert child.source_key in lane.objects.sources
    replay = await lane.clients[0].post(
        f"/jobs/{asset_id}/edit",
        json={"operations": operations},
        headers={"Idempotency-Key": str(key)},
    )
    assert replay.status_code == 202 and replay.json()["job_id"] == child_id
    lane.boundary.lost_submit_ack = False
    await due(lane)
    await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert (await row(lane, child_id)).submission_state == "submitted"
    assert lane.boundary.submissions[-1]["operations"] == operations
    assert len(lane.boundary.jobs) == 2


async def test_edit_changed_order_conflicts_and_copy_failure_no_acceptance(lane):
    asset_id = await upload(lane)
    await done(lane, asset_id)
    operations = [
        {"operation": "clip", "params": {"start": 0, "end": 3}},
        {"operation": "crop", "params": {"x": 0, "y": 0, "w": 10, "h": 10}},
    ]
    key = uuid4()
    lane.objects.copy_fails = True
    response = await lane.clients[0].post(
        f"/jobs/{asset_id}/edit",
        json={"operations": operations},
        headers={"Idempotency-Key": str(key)},
    )
    assert response.status_code == 503 and len(lane.objects.sources) == 1
    lane.objects.copy_fails = False
    child = await lane.clients[0].post(
        f"/jobs/{asset_id}/edit",
        json={"operations": operations},
        headers={"Idempotency-Key": str(key)},
    )
    assert child.status_code == 202
    conflict = await lane.clients[0].post(
        f"/jobs/{asset_id}/edit",
        json={"operations": operations[::-1]},
        headers={"Idempotency-Key": str(key)},
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize("lost_submit", [True, False])
async def test_delete_uncertain_submit_cancel_lost_ack_source_waits(lane, lost_submit):
    lane.boundary.lost_submit_ack = lost_submit
    asset_id = await upload(lane)
    source_key = (await row(lane, asset_id)).source_key
    lane.boundary.lost_cancel_ack = True
    assert (await lane.clients[0].delete(f"/jobs/{asset_id}")).status_code == 204
    assert (await lane.clients[0].get(f"/jobs/{asset_id}")).status_code == 404
    assert source_key in lane.objects.sources
    assert lane.boundary.cancellations[-1][1] == asset_id
    async with lane.factory() as session:
        cleanup = await session.get(CleanupIntent, UUID(asset_id))
    assert cleanup.processing_deleted_at is None and cleanup.source_deleted_at is None
    lane.boundary.lost_cancel_ack = False
    await due(lane)
    await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert source_key not in lane.objects.sources
    assert (await lane.clients[0].delete(f"/jobs/{asset_id}")).status_code == 204
    assert asset_id in lane.boundary.cancelled


async def test_cancel_first_pending_then_late_dispatch_does_not_resurrect(lane):
    lane.boundary.down = True
    asset_id = await upload(lane)
    assert (await row(lane, asset_id)).processing_job_id is None
    await lane.clients[0].delete(f"/jobs/{asset_id}")
    lane.boundary.down = False
    await due(lane)
    await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert asset_id in lane.boundary.cancelled and asset_id not in lane.boundary.jobs
    assert (await lane.clients[0].get(f"/jobs/{asset_id}")).status_code == 404


async def test_cleanup_storage_retry_after_cancel_ack(lane):
    asset_id = await upload(lane)
    source = (await row(lane, asset_id)).source_key
    lane.objects.delete_fails = True
    await lane.clients[0].delete(f"/jobs/{asset_id}")
    async with lane.factory() as session:
        intent = await session.get(CleanupIntent, UUID(asset_id))
    assert intent.processing_deleted_at and not intent.source_deleted_at
    assert source in lane.objects.sources
    lane.objects.delete_fails = False
    await due(lane)
    await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert len(lane.boundary.cancellations) == 1 and source not in lane.objects.sources


@pytest.mark.parametrize("media_type", ["video/mp4", "video/x-matroska", "audio/mpeg"])
async def test_primary_hls_owner_checked_playlist_bodies_segment_signing(lane, media_type):
    asset_id = await upload(lane)
    await done(lane, asset_id, media_type)
    public = (await lane.clients[0].get(f"/jobs/{asset_id}")).json()
    assert public["id"] == asset_id and "localhost:4443/test-output/" in public["output_url"]
    assert public["hls_url"] == f"/api/jobs/{asset_id}/hls/master.m3u8"
    path = f"/jobs/{asset_id}/hls/"
    master = await lane.clients[0].get(path + "master.m3u8")
    assert master.status_code == 200 and master.content == b"#EXTM3U\nv0/index.m3u8\n"
    assert master.headers["cache-control"] == "private, no-store"
    rendition = await lane.clients[0].get(path + "v0/index.m3u8")
    assert rendition.status_code == 200 and b"seg00001.ts" in rendition.content
    segment = await lane.clients[0].get(path + "v0/seg00001.ts")
    assert segment.status_code == 307 and "test-output/" in segment.headers["location"]
    assert (await lane.clients[1].get(path + "master.m3u8")).status_code == 404
    assert (await lane.clients[0].get(path + "v0/%2e%2e/master.m3u8")).status_code == 404
    assert (await lane.clients[0].get(path + "missing.m3u8")).status_code == 404


async def test_storage_failure_preserves_no_asset_or_request_key(lane):
    lane.objects.put_fails = True
    key = uuid4()
    response = await lane.clients[0].post(
        "/upload",
        files={"file": ("x.mp4", VIDEO, "video/mp4")},
        headers={"Idempotency-Key": str(key)},
    )
    assert response.status_code == 503
    async with lane.factory() as session:
        assert await session.scalar(select(Asset).where(Asset.owner_id == lane.users[0].id)) is None
        assert await session.get(RequestKey, (lane.users[0].id, "upload", key)) is None


async def test_auth_cookie_transaction_and_current_role(lane):
    email = f"media-{uuid4().hex}@example.com"
    credentials = {"email": email, "password": "strong-test-password"}
    client = lane.clients[0]
    registered = await client.post("/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    user_id = UUID(registered.json()["id"])
    lane.users.append(User(id=user_id))
    assert (
        "Secure" in registered.headers["set-cookie"]
        and "HttpOnly" in registered.headers["set-cookie"]
    )
    assert "SameSite=strict" in registered.headers["set-cookie"]
    assert (await client.post("/auth/register", json=credentials)).status_code == 409
    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.get("/auth/me")).status_code == 401
    assert (
        await client.post("/auth/login", json={**credentials, "password": "incorrect-password"})
    ).status_code == 401
    assert (await client.post("/auth/login", json=credentials)).status_code == 200
    assert (await client.get("/auth/me")).json()["id"] == str(user_id)
    # Real auth SELECT followed by explicit domain begin must not autobegin-conflict.
    asset_id = await upload(lane)
    assert (await row(lane, asset_id)).owner_id == user_id


async def test_media_runtime_ddl_and_opposite_database_denied(lane):
    async with lane.factory() as session:
        with pytest.raises(SQLAlchemyError):
            await session.execute(text("CREATE TABLE media_should_not_exist (id int)"))
        await session.rollback()
        assert await session.scalar(text("SELECT current_database()")) == "media_db"

    other = create_async_engine(
        make_url(lane.settings.postgres_dsn).set(database="processing_db"), poolclass=NullPool
    )
    try:
        with pytest.raises(SQLAlchemyError):
            async with other.connect():
                pass
    finally:
        await other.dispose()


@pytest.mark.parametrize("operation", ["upload", "edit"])
async def test_inflight_stage_reservation_skips_orphan_cleanup_until_adoption(
    lane, monkeypatch, operation
):
    from media.services import intake

    if operation == "edit":
        parent_id = await upload(lane)
        await done(lane, parent_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original_stage, original_put = intake.stage, lane.objects.put_source
    original_copy = lane.objects.copy_output_source
    own_keys = []

    async def old_stage(session, key):
        await original_stage(session, key)
        own_keys.append(key)
        # Age the reservation so SKIP LOCKED, not grace alone, protects this write.
        async with session.begin():
            await session.execute(
                update(StagedObject)
                .where(StagedObject.key == key)
                .values(created_at=now() - timedelta(hours=2))
            )

    async def slow_put(*args):
        await original_put(*args)
        entered.set()
        await release.wait()

    async def slow_copy(*args):
        result = await original_copy(*args)
        entered.set()
        await release.wait()
        return result

    async def request():
        if operation == "upload":
            return await upload(lane)
        response = await lane.clients[0].post(
            f"/jobs/{parent_id}/edit",
            json={"operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}]},
        )
        assert response.status_code == 202
        return response.json()["job_id"]

    monkeypatch.setattr(intake, "stage", old_stage)
    from media.services import lifecycle

    monkeypatch.setattr(lifecycle, "stage", old_stage)
    lane.objects.put_source = slow_put
    lane.objects.copy_output_source = slow_copy
    uploading = asyncio.create_task(request())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with lane.factory() as session:
            assert await session.get(StagedObject, own_keys[0]) is not None
            assert (
                await session.scalar(select(Asset).where(Asset.source_key == own_keys[0])) is None
            )
        counts = await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
        assert counts["orphan"] == 0 and own_keys[0] not in lane.objects.deleted
    finally:
        release.set()
    asset_id = await asyncio.wait_for(uploading, 5)
    assert (await row(lane, asset_id)).source_key == own_keys[0]
    async with lane.factory() as session:
        assert await session.get(StagedObject, own_keys[0]) is None


async def test_orphan_cleanup_removes_only_old_unadopted_source(lane):
    asset_id = await upload(lane)
    asset = await row(lane, asset_id)
    fresh, orphan = (
        f"sources/{lane.users[0].id}/{uuid4()}/fresh",
        f"sources/{lane.users[0].id}/{uuid4()}/orphan",
    )
    lane.objects.sources.update({fresh: b"fresh", orphan: b"orphan"})
    async with lane.factory() as session:
        # Even a stray ledger row for an adopted source cannot delete it.
        session.add_all(
            [
                StagedObject(key=asset.source_key, created_at=now() - timedelta(hours=2)),
                StagedObject(key=fresh, created_at=now()),
                StagedObject(
                    key=orphan, created_at=now() - timedelta(hours=2), write_uncertain=False
                ),
            ]
        )
        await session.commit()
    counts = await reconcile(lane.factory, lane.peer, lane.objects, lane.settings)
    assert counts["orphan"] == 1
    assert orphan not in lane.objects.sources and fresh in lane.objects.sources
    assert asset.source_key in lane.objects.sources
    async with lane.factory() as session:
        assert await session.get(StagedObject, orphan) is None
        assert await session.get(StagedObject, fresh) is not None


async def test_concurrent_retry_key_has_one_durable_uuid_and_cross_asset_conflicts(lane):
    asset_id, other_id = await upload(lane), await upload(lane)
    for i in [asset_id, other_id]:
        lane.boundary.jobs[i]["status"] = "failed"
    key = uuid4()
    responses = await asyncio.gather(
        *(
            lane.clients[0].post(f"/jobs/{asset_id}/retry", headers={"Idempotency-Key": str(key)})
            for _ in range(6)
        )
    )
    assert [r.status_code for r in responses] == [202] * 6
    assert len(lane.boundary.retries) == 1
    async with lane.factory() as session:
        intents = list(
            await session.scalars(select(RetryIntent).where(RetryIntent.asset_id == UUID(asset_id)))
        )
    assert len(intents) == 1 and intents[0].confirmed_at
    conflict = await lane.clients[0].post(
        f"/jobs/{other_id}/retry", headers={"Idempotency-Key": str(key)}
    )
    assert conflict.status_code == 409
    assert lane.boundary.jobs[other_id]["status"] == "failed"


async def test_full_100mib_file_allowed_but_file_over_limit_rejected(lane):
    maximum = 100 * 1024 * 1024
    data = VIDEO + b"\x00" * (maximum - len(VIDEO))
    response = await lane.clients[0].post(
        "/upload", files={"file": ("limit.mp4", data, "video/mp4")}
    )
    assert response.status_code == 202, response.text
    asset = await row(lane, response.json()["job_id"])
    assert asset.source_size_bytes == maximum
    too_large = await lane.clients[0].post(
        "/upload", files={"file": ("over.mp4", data + b"x", "video/mp4")}
    )
    assert too_large.status_code == 413
    assert len(lane.objects.sources) == 1


async def test_cancel_waits_for_inflight_submit_then_tombstone_wins(lane):
    entered, release = asyncio.Event(), asyncio.Event()
    own_asset = []

    async def handle(request):
        import json

        if request.method == "POST" and request.url.path == "/internal/v1/jobs":
            own_asset.append(json.loads(request.content)["asset_id"])
            entered.set()
            await release.wait()
        return lane.boundary.handle(request)

    lane.app.state.http_client = httpx.AsyncClient(
        base_url="http://processing.test", transport=httpx.MockTransport(handle)
    )
    uploading = asyncio.create_task(upload(lane))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        deleting = asyncio.create_task(lane.clients[0].delete(f"/jobs/{own_asset[0]}"))
        # Local asset lock prevents cancellation overtaking its in-flight dispatch.
        assert (await row(lane, own_asset[0])).submission_state == "pending"
        release.set()
        await asyncio.wait_for(uploading, 5)
        assert (await asyncio.wait_for(deleting, 5)).status_code == 204
        assert own_asset[0] in lane.boundary.cancelled
        assert (await lane.clients[0].get(f"/jobs/{own_asset[0]}")).status_code == 404
        assert not lane.objects.sources
    finally:
        release.set()
        await lane.app.state.http_client.aclose()


async def test_playback_grant_serializes_before_tombstone_and_later_reads_are_denied(lane):
    asset_id = await upload(lane)
    await done(lane, asset_id)
    entered, release = asyncio.Event(), asyncio.Event()
    signs = []
    original_sign = lane.objects.sign_output

    async def slow_sign(key, *, inline=False):
        entered.set()
        await release.wait()
        signs.append(key)
        return await original_sign(key, inline=inline)

    lane.objects.sign_output = slow_sign
    reading = asyncio.create_task(lane.clients[0].get(f"/jobs/{asset_id}"))
    deleting = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        deleting = asyncio.create_task(lane.clients[0].delete(f"/jobs/{asset_id}"))
        # Acquire a competing lock without waiting. PostgreSQL refuses it while
        # playback holds the source Asset guard, rather than tombstoning early.
        async with lane.factory() as session:
            assert (
                await session.scalar(
                    select(Asset)
                    .where(Asset.id == UUID(asset_id))
                    .with_for_update(skip_locked=True)
                )
                is None
            )
        release.set()
        assert (await asyncio.wait_for(reading, 5)).status_code == 200
        assert (await asyncio.wait_for(deleting, 5)).status_code == 204
        assert len(signs) == 1
        assert (await lane.clients[0].get(f"/jobs/{asset_id}")).status_code == 404
        assert len(signs) == 1
    finally:
        release.set()
        await asyncio.gather(
            reading, *([deleting] if deleting is not None else []), return_exceptions=True
        )


async def test_lost_database_commit_ack_does_not_discard_adopted_source(lane, monkeypatch):
    from contextlib import asynccontextmanager

    from media.services import intake

    asset_id, key = uuid4(), uuid4()
    source_key = f"sources/{lane.users[0].id}/{asset_id}/committed.mp4"
    lane.objects.sources[source_key] = VIDEO
    asset = Asset(
        id=asset_id,
        owner_id=lane.users[0].id,
        filename="committed.mp4",
        source_key=source_key,
        source_revision=1,
        source_sha256=hashlib.sha256(VIDEO).hexdigest(),
        source_size_bytes=len(VIDEO),
        source_media_type="video/mp4",
        operations=[],
    )
    async with lane.factory() as session:
        await intake.stage(session, source_key)
        real_begin, calls = session.begin, []

        @asynccontextmanager
        async def lost_commit_ack():
            async with real_begin():
                yield
            raise OSError("controlled commit acknowledgement loss")

        def begin():
            calls.append(1)
            return lost_commit_ack() if len(calls) == 1 else real_begin()

        monkeypatch.setattr(session, "begin", begin)
        with pytest.raises(OSError):
            await intake.accept(session, lane.objects, asset, "upload", key, "a" * 64)
    committed = await row(lane, str(asset_id))
    assert committed.source_key == source_key
    assert lane.objects.sources[source_key] == VIDEO and source_key not in lane.objects.deleted
    async with lane.factory() as session:
        assert await session.get(StagedObject, source_key) is None
        assert (
            await session.get(RequestKey, (lane.users[0].id, "upload", key))
        ).asset_id == asset_id


@pytest.mark.parametrize("operation", ["upload", "edit"])
@pytest.mark.parametrize("finish_after", ["response", "first-cleanup", "parent-delete"])
async def test_uncertain_source_write_retains_cleanup_after_late_put(lane, operation, finish_after):
    parent_id = await upload(lane)
    await done(lane, parent_id)
    operations = [{"operation": "clip", "params": {"start": 0, "end": 3}}]
    # Protect a healthy adopted upload and edit, including the edit after parent deletion.
    healthy = await lane.clients[0].post(f"/jobs/{parent_id}/edit", json={"operations": operations})
    assert healthy.status_code == 202
    healthy_id = healthy.json()["job_id"]
    healthy_asset = await row(lane, healthy_id)
    parent_asset = await row(lane, parent_id)
    async with lane.factory() as session:
        session.add_all(
            StagedObject(key=a.source_key, created_at=now() - timedelta(hours=2))
            for a in [parent_asset, healthy_asset]
        )
        await session.commit()

    release, completed = asyncio.Event(), asyncio.Event()
    pending, writers = {}, []

    async def remote_put(key, data):
        await release.wait()
        lane.objects.sources[key] = data
        completed.set()

    async def uncertain_put(key, stream, size, media_type):
        pending[key] = stream.read()
        assert len(pending[key]) == size
        writers.append(asyncio.create_task(remote_put(key, pending[key])))
        raise TimeoutError("remote PUT remains in flight")

    async def uncertain_copy(output, key):
        pending[key] = lane.objects.outputs[output.object_key]
        writers.append(asyncio.create_task(remote_put(key, pending[key])))
        raise TimeoutError("remote copy PUT remains in flight")

    lane.objects.put_source = uncertain_put
    lane.objects.copy_output_source = uncertain_copy
    request_key = uuid4()
    headers = {"Idempotency-Key": str(request_key)}
    fresh_engine = create_async_engine(lane.settings.postgres_dsn, poolclass=NullPool)
    fresh_factory = async_sessionmaker(fresh_engine, expire_on_commit=False)

    async def age(key):
        async with fresh_factory() as session:
            await session.execute(
                update(StagedObject)
                .where(StagedObject.key == key)
                .values(created_at=now() - timedelta(hours=2))
            )
            await session.commit()

    async def verify_ledger(key):
        async with fresh_factory() as session:
            staged = await session.get(StagedObject, key)
            assert staged is not None and staged.write_uncertain
            assert staged.created_at > now() - timedelta(seconds=lane.settings.orphan_grace_seconds)
            assert await session.scalar(select(Asset.id).where(Asset.source_key == key)) is None
            assert await session.get(RequestKey, (lane.users[0].id, operation, request_key)) is None

    try:
        if operation == "upload":
            response = await lane.clients[0].post(
                "/upload", files={"file": ("late.mp4", VIDEO, "video/mp4")}, headers=headers
            )
        else:
            response = await lane.clients[0].post(
                f"/jobs/{parent_id}/edit", json={"operations": operations}, headers=headers
            )
        assert response.status_code == 503
        (key,) = pending
        assert lane.objects.deleted.count(key) == 1 and key not in lane.objects.sources
        await verify_ledger(key)
        assert (await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 0

        if finish_after != "response":
            await age(key)
            counts = await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings)
            assert counts["orphan"] == 1 and lane.objects.deleted.count(key) == 2
            await verify_ledger(key)
        if finish_after == "parent-delete":
            assert (await lane.clients[0].delete(f"/jobs/{parent_id}")).status_code == 204
            assert parent_asset.source_key not in lane.objects.sources
        # Complete only after HTTP failure, optionally after recovery and parent deletion.
        release.set()
        await asyncio.wait_for(completed.wait(), 5)
        assert lane.objects.sources[key] == VIDEO
        assert (await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 0
        assert key in lane.objects.sources
        await age(key)
        assert (await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 1
        assert key not in lane.objects.sources
        await verify_ledger(key)

        # Even another late completion after cleanup remains discoverable.
        lane.objects.sources[key] = pending[key]
        await age(key)
        assert (await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 1
        assert key not in lane.objects.sources
        await verify_ledger(key)
        assert (await reconcile(fresh_factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 0
        assert healthy_asset.source_key in lane.objects.sources
        assert healthy_asset.source_key not in lane.objects.deleted
        if finish_after != "parent-delete":
            assert parent_asset.source_key in lane.objects.sources
            assert parent_asset.source_key not in lane.objects.deleted

        # A replacement application/pool still serves the healthy adopted child.
        fresh_app = create_app()
        fresh_app.state.engine = fresh_engine
        fresh_app.state.http_client = lane.app.state.http_client
        fresh_app.dependency_overrides.update(lane.app.dependency_overrides)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fresh_app),
            base_url="https://media.test",
            cookies=lane.clients[0].cookies,
        ) as client:
            assert (await client.get(f"/jobs/{healthy_id}")).status_code == 200
    finally:
        release.set()
        await asyncio.gather(*writers)
        await fresh_engine.dispose()


@pytest.mark.parametrize("operation", ["upload", "edit"])
async def test_completed_stage_cleanup_before_adoption_cannot_accept_missing_source(
    lane, monkeypatch, operation
):
    from media.services import intake, lifecycle

    if operation == "edit":
        parent_id = await upload(lane)
        await done(lane, parent_id)
    original_accept = intake.accept
    keys = []

    async def delayed_accept(session, storage, asset, *args):
        keys.append(asset.source_key)
        async with lane.factory() as independent:
            stage = await independent.get(StagedObject, asset.source_key)
            assert stage is not None and not stage.write_uncertain
            stage.created_at = now() - timedelta(hours=2)
            await independent.commit()
        assert (await reconcile(lane.factory, lane.peer, lane.objects, lane.settings))[
            "orphan"
        ] == 1
        return await original_accept(session, storage, asset, *args)

    monkeypatch.setattr(intake, "accept", delayed_accept)
    monkeypatch.setattr(lifecycle, "accept", delayed_accept)
    key = uuid4()
    if operation == "upload":
        response = await lane.clients[0].post(
            "/upload",
            files={"file": ("expired.mp4", VIDEO, "video/mp4")},
            headers={"Idempotency-Key": str(key)},
        )
    else:
        response = await lane.clients[0].post(
            f"/jobs/{parent_id}/edit",
            json={"operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}]},
            headers={"Idempotency-Key": str(key)},
        )
    assert response.status_code == 503
    (source,) = keys
    assert source not in lane.objects.sources
    async with lane.factory() as session:
        assert await session.get(StagedObject, source) is None
        assert await session.scalar(select(Asset.id).where(Asset.source_key == source)) is None
        assert await session.get(RequestKey, (lane.users[0].id, operation, key)) is None
