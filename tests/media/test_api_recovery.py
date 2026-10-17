from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError

from legacy.media_peer import hls, jobs, lifecycle
from legacy.media_peer import uploads as multipart
from legacy.media_peer.app import create_app
from legacy.media_peer.processing_client import get_processing_client
from media.api import auth, deps
from media.config import get_settings
from media.database import get_session
from media.errors import MediaError
from media.models import StagedObject, now
from media.schemas.public import PublicJob
from media.services.security import issue_token
from media.services.storage import get_storage


@pytest.fixture
def application(session, user, settings, peer, storage):
    app = create_app()

    async def database():
        yield session

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[deps.current_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_processing_client] = lambda: peer
    app.dependency_overrides[get_storage] = lambda: storage
    return app


async def test_public_upload_retry_edit_list_and_read_routes(
    application, monkeypatch, asset, user, job, storage
):
    uploaded = AsyncMock(return_value=asset)
    monkeypatch.setattr(multipart.intake, "upload", uploaded)
    monkeypatch.setattr(lifecycle, "dispatch", AsyncMock())
    monkeypatch.setattr(lifecycle, "reserve_retry", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(lifecycle, "dispatch_retry", AsyncMock(return_value=asset.id))
    monkeypatch.setattr(lifecycle, "edit", AsyncMock(return_value=asset))
    monkeypatch.setattr(jobs, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(jobs, "list_assets", AsyncMock(return_value=[asset]))
    monkeypatch.setattr(lifecycle, "live_job", AsyncMock(return_value=job))
    result = PublicJob(
        id=asset.id, filename=asset.filename, status="queued", submission_status="submitted"
    )
    monkeypatch.setattr(lifecycle, "projection", AsyncMock(return_value=result))
    monkeypatch.setattr(lifecycle, "project_page", AsyncMock(return_value=[result]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://unit.test"
    ) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        assert (
            await client.post("/upload", files={"file": ("x.mp4", b"video", "video/mp4")})
        ).status_code == 202
        uploaded.assert_awaited_once()
        assert (
            await client.post(
                "/upload",
                files={"file": ("x.mp4", b"video", "video/mp4")},
                headers={"Idempotency-Key": "invalid"},
            )
        ).status_code == 422
        assert (await client.post(f"/jobs/{asset.id}/retry")).status_code == 202
        assert (
            await client.post(
                f"/jobs/{asset.id}/edit",
                json={"operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}]},
            )
        ).status_code == 202
        assert (await client.get("/jobs")).json()[0]["id"] == str(asset.id)
        assert (await client.get(f"/jobs/{asset.id}")).json()["id"] == str(asset.id)
        assert (await client.get("/jobs?limit=201")).status_code == 422
        asset.submission_state = "pending"
        assert (await client.get(f"/jobs/{asset.id}")).status_code == 200


async def test_delete_tombstone_durable_response_and_operator_routes(
    application, monkeypatch, user, asset, session
):
    monkeypatch.setattr(lifecycle, "tombstone", AsyncMock(return_value=asset))
    monkeypatch.setattr(lifecycle, "cleanup", AsyncMock(side_effect=OSError()))
    monkeypatch.setattr(jobs, "list_assets", AsyncMock(return_value=[]))
    monkeypatch.setattr(lifecycle, "project_page", AsyncMock(return_value=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://unit.test"
    ) as client:
        assert (await client.delete(f"/jobs/{asset.id}")).status_code == 204
        session.rollback.assert_awaited_once()
        assert (await client.get("/admin/jobs")).status_code == 403
        assert (await client.delete(f"/admin/jobs/{asset.id}")).status_code == 403
        user.role = "operator"
        assert (await client.get("/admin/jobs")).json() == []
        assert (await client.delete(f"/admin/jobs/{asset.id}")).status_code == 204
        assert lifecycle.tombstone.call_args.args[-1] is None


async def test_auth_routes_use_async_hash_and_current_cookie(
    application, session, user, settings, monkeypatch
):
    session.scalar.return_value = user
    monkeypatch.setattr(auth, "hash_password", lambda password: "hashed")
    verified_hashes = []

    def verify(password, hashed):
        verified_hashes.append(hashed)
        return password == "strong-password"

    monkeypatch.setattr(auth, "verify_password", verify)
    from sqlalchemy.exc import IntegrityError

    async def flush():
        added = session.add.call_args.args[0]
        added.id = uuid4()
        added.role = "user"

    session.flush.side_effect = flush
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://unit.test"
    ) as client:
        body = {"email": "unit@example.com", "password": "strong-password"}
        registered = await client.post("/auth/register", json=body)
        assert registered.status_code == 201 and "Secure" in registered.headers["set-cookie"]
        session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
        conflict = await client.post("/auth/register", json=body)
        assert conflict.status_code == 409 and conflict.content == b""
        assert (await client.post("/auth/login", json=body)).status_code == 200
        assert (
            await client.post("/auth/login", json={**body, "password": "wrong-password"})
        ).status_code == 401
        session.scalar.return_value = None
        assert (await client.post("/auth/login", json=body)).status_code == 401
        assert verified_hashes == [user.password_hash, user.password_hash, auth.DUMMY_HASH]
        assert (await client.get("/auth/me")).json()["id"] == str(user.id)
        assert (await client.post("/auth/logout")).status_code == 204


async def test_real_auth_dependency_separate_session_no_autobegin(
    session, user, settings, monkeypatch
):
    session.get.return_value = user

    @asynccontextmanager
    async def unused():
        yield

    async def separate(request, settings):
        yield session

    monkeypatch.setattr(deps, "get_session", separate)
    token = issue_token(user.id, settings)
    request = Request({"type": "http", "headers": [(b"cookie", f"access_token={token}".encode())]})
    assert await deps.current_user(request, settings) is user
    session.get.return_value = None
    with pytest.raises(MediaError):
        await deps.current_user(request, settings)
    with pytest.raises(MediaError):
        await deps.current_user(Request({"type": "http", "headers": []}), settings)
    assert session.begin.call_count == 0


async def test_source_internal_auth_and_grant_contract(
    application, session, asset, storage, settings, pinned_version
):
    session.scalar.return_value = asset
    pinned_version.return_value = "accepted-version"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://unit.test"
    ) as client:
        path = f"/internal/v1/assets/{asset.id}/source-access"
        assert (await client.post(path, json={"revision": 1})).status_code == 401
        headers = {"Authorization": "Bearer reverse-unit", "X-Owner-Id": str(asset.owner_id)}
        assert (
            await client.post(
                path, json={"revision": 1}, headers={"Authorization": "Bearer reverse-unit"}
            )
        ).status_code == 401
        grant = await client.post(path, json={"revision": 1}, headers=headers)
        assert grant.status_code == 200 and grant.json()["source"]["sha256"] == asset.source_sha256
        # The legacy signed URL must name the pinned version, never "whatever is newest".
        storage.source_grant.assert_awaited_with(asset.source_key, "accepted-version")
        assert (await client.post(path, json={"revision": 2}, headers=headers)).status_code == 409
        storage.source_grant.side_effect = OSError()
        assert (await client.post(path, json={"revision": 1}, headers=headers)).status_code == 503


async def test_hls_route_ownership_paths_playlist_and_segments(
    application, session, asset, job, storage, monkeypatch
):
    from legacy.media_peer.schemas import Output

    session.scalar.return_value = asset
    monkeypatch.setattr(hls, "live_job", AsyncMock(return_value=job))
    job.status = "done"
    job.outputs = [
        Output(
            kind="hls_manifest",
            object_key="job/attempt/hls/master.m3u8",
            media_type="application/vnd.apple.mpegurl",
        )
    ]
    storage.read_playlist.return_value = b"#EXTM3U\nv0/index.m3u8\n"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://unit.test"
    ) as client:
        prefix = f"/jobs/{asset.id}/hls/"
        playlist = await client.get(prefix + "master.m3u8")
        assert (
            playlist.status_code == 200 and playlist.headers["cache-control"] == "private, no-store"
        )
        assert (await client.get(prefix + "v0/seg00001.ts")).status_code == 307
        assert storage.sign_output.call_args.kwargs == {"inline": True}
        assert (await client.get(prefix + "v0/%2e%2e/master.m3u8")).status_code == 404
        storage.read_playlist.side_effect = OSError()
        assert (await client.get(prefix + "missing.m3u8")).status_code == 404
        job.status = "processing"
        assert (await client.get(prefix + "master.m3u8")).status_code == 404
        asset.submission_state = "pending"
        assert (await client.get(prefix + "master.m3u8")).status_code == 404


async def test_safe_database_error_and_application_resource_cleanup(settings, application, session):
    session.scalar.side_effect = SQLAlchemyError("private DSN not returned")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="https://unit.test",
    ) as client:
        error = await client.post(
            "/auth/login", json={"email": "unit@example.com", "password": "strong-password"}
        )
    assert error.status_code == 503 and "private DSN" not in error.text
    application.state.engine = SimpleNamespace(dispose=AsyncMock())
    application.state.http_client = SimpleNamespace(aclose=AsyncMock())
    engine, http = application.state.engine, application.state.http_client
    async with application.router.lifespan_context(application):
        pass
    engine.dispose.assert_awaited_once()
    http.aclose.assert_awaited_once()


async def test_application_local_peer_client_pool(settings):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    a = get_processing_client(request, settings)
    b = get_processing_client(request, settings)
    assert a.client is b.client
    assert a.client.timeout.read == settings.processing_timeout_seconds
    await a.client.aclose()


async def test_database_dependency_allocates_app_local_pool_without_connecting(settings):
    app = create_app()
    request = SimpleNamespace(app=app)
    generator = get_session(request, settings)
    session = await anext(generator)
    assert app.state.engine is not None and not session.in_transaction()
    await generator.aclose()
    await app.state.engine.dispose()


@pytest.mark.parametrize("uncertain", [False, True])
async def test_reconcile_due_intents_and_orphan_grace(
    session, settings, peer, storage, monkeypatch, uncertain
):
    from legacy.media_peer import recovery

    ids = [uuid4() for _ in range(3)]
    stamp = now() - timedelta(hours=2)
    old_stage = StagedObject(key="orphan", created_at=stamp, write_uncertain=uncertain)
    session.scalars.side_effect = [[ids[0]], [ids[1]], [ids[2]], [old_stage]]

    @asynccontextmanager
    async def factory():
        yield session

    for name in ["dispatch", "dispatch_retry", "cleanup"]:
        monkeypatch.setattr(lifecycle, name, AsyncMock())
    counts = await recovery.reconcile(factory, peer, storage, settings)
    assert counts == {"submission": 1, "retry": 1, "cleanup": 1, "orphan": 1}
    storage.delete_source.assert_awaited_once_with("orphan")
    if uncertain:
        assert old_stage.created_at > stamp
        session.execute.assert_not_awaited()
    else:
        session.execute.assert_awaited_once()
    from sqlalchemy.dialects.postgresql import dialect

    query = str(session.scalars.call_args.args[0].compile(dialect=dialect()))
    assert "SKIP LOCKED" in query and "NOT (EXISTS" in query and "created_at <" in query


@pytest.mark.parametrize("error", [MediaError(410, "deleted"), OSError()])
async def test_reconcile_intent_error_is_bounded_and_orphan_failure_retained(
    session, settings, peer, storage, monkeypatch, error
):
    from legacy.media_peer import recovery

    session.scalars.side_effect = [[uuid4()], [], [], [StagedObject(key="retained")]]

    @asynccontextmanager
    async def factory():
        yield session

    monkeypatch.setattr(lifecycle, "dispatch", AsyncMock(side_effect=error))
    storage.delete_source.side_effect = OSError()
    counts = await recovery.reconcile(factory, peer, storage, settings)
    assert counts["submission"] == 1 and counts["orphan"] == 0
    session.execute.assert_not_awaited()


async def test_recovery_once_is_explicit_and_resources_close(monkeypatch, settings):
    from legacy.media_peer import recovery

    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(recovery, "get_settings", lambda: settings)
    monkeypatch.setattr(recovery, "create_async_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(recovery, "async_sessionmaker", lambda *a, **kw: None)
    monkeypatch.setattr(recovery, "Storage", lambda *a: None)
    monkeypatch.setattr(recovery, "reconcile", AsyncMock(return_value={}))
    await recovery.run(once=True)
    engine.dispose.assert_awaited_once()
    recovery.reconcile.side_effect = OSError("private exception omitted")
    with pytest.raises(RuntimeError, match="Media reconciliation failed"):
        await recovery.run(once=True)
