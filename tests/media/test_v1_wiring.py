"""Exercise the exported handler, keeping legacy routes outside the V1 boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.routing import APIRoute

from contracts.v1 import Actor
from legacy.media_peer.app import create_app
from legacy.media_peer.processing_client import get_processing_client as get_peer
from media.api import deps, v1_hls, v1_jobs
from media.config import get_settings
from media.database import get_session
from media.lambda_handler import handler
from media.projections import ProjectedJob
from media.services.security import issue_token
from media.services.storage import get_storage


def event(path, user, settings, *, method="GET"):
    return {
        "version": "2.0",
        "rawPath": "/api/media" + path,
        "rawQueryString": "",
        "headers": {"x-owner-id": str(uuid4())},
        "cookies": ["access_token=" + issue_token(user.id, settings)],
        "requestContext": {
            "http": {"method": method},
            "authorizer": {"lambda": Actor(str(user.id), "publisher").to_context()},
        },
    }


def dependencies(dependant):
    for child in dependant.dependencies:
        yield child.call
        yield from dependencies(child)


def domain_routes(router):
    # FastAPI can retain lazy included routers instead of flattening app.routes.
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from domain_routes(route.original_router)


def test_handler_has_only_v1_domain_routes_and_no_peer_dependencies():
    routes = list(domain_routes(handler.app))
    by_path = {route.path: route for route in routes}
    assert by_path["/jobs"].endpoint is v1_jobs.listing
    assert by_path["/jobs/{job_id}/hls/{path:path}"].endpoint is v1_hls.part
    assert "/uploads/reservations" in by_path
    assert "/uploads/reservations/{reservation_id}/finalize" in by_path
    assert "/upload" not in by_path
    assert not any("internal" in route.path for route in routes)
    assert not any(get_peer in set(dependencies(route.dependant)) for route in routes)
    legacy_paths = {route.path for route in domain_routes(create_app())}
    assert "/upload" in legacy_paths
    assert any("internal" in path for path in legacy_paths)


def test_default_media_app_is_v1_and_legacy_peer_app_is_explicit():
    import legacy.media_peer.app as legacy_entry
    import media.main as entry

    default = {route.path for route in domain_routes(entry.app)}
    assert "/upload" not in default and not any("internal" in path for path in default)
    assert "/uploads/reservations" in default
    legacy = {route.path for route in domain_routes(legacy_entry.app)}
    assert "/upload" in legacy and any("internal" in path for path in legacy)
    # The V1 module carries no way to build the peer-calling app.
    assert not hasattr(entry, "legacy_app") and not hasattr(entry, "create_app")


async def test_exported_handler_reads_owned_projection_without_peer(
    settings, user, asset, monkeypatch
):
    app = handler.app
    projection = ProjectedJob(
        job_id=asset.processing_job_id,
        status="done",
        outputs=[
            {"kind": "primary", "object_key": "jobs/attempt/output.mp4", "media_type": "video/mp4"}
        ],
    )
    session = SimpleNamespace(get=AsyncMock(return_value=projection))
    signed_url = "https://storage.example/output.mp4?X-Amz-Signature=fixture"
    storage = SimpleNamespace(sign_output=AsyncMock(return_value=signed_url))

    async def auth_sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=user))

    listing = AsyncMock(return_value=[(asset, projection)])
    owned_asset = AsyncMock(return_value=asset)
    monkeypatch.setattr(deps, "get_session", auth_sessions)
    monkeypatch.setattr(v1_jobs, "get_asset", owned_asset)
    monkeypatch.setattr(v1_jobs, "list_asset_pages", listing)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage

    def forbidden_peer():
        raise AssertionError("V1 invoked the HTTP peer")

    app.dependency_overrides[get_peer] = forbidden_peer
    try:
        identity = await handler.invoke(event("/auth/me", user, settings))
        assert identity["statusCode"] == 200
        assert json.loads(identity["body"])["id"] == str(user.id)
        assert identity["headers"]["cache-control"] == "private, no-store"

        result = await handler.invoke(event("/jobs", user, settings))
        assert result["statusCode"] == 200
        assert result["headers"]["cache-control"] == "private, no-store"
        rows = json.loads(result["body"])
        assert rows[0]["status"] == "done" and rows[0]["output_url"] == signed_url
        listing.assert_awaited_once_with(session, user.id, 50, 0)

        detail = await handler.invoke(event(f"/jobs/{asset.id}", user, settings))
        assert detail["statusCode"] == 200
        assert detail["headers"]["cache-control"] == "private, no-store"
        data = json.loads(detail["body"])
        assert data["status"] == "done" and data["output_url"] == signed_url
        owned_asset.assert_awaited_once_with(session, asset.id, user.id)
        listing.return_value = []
        empty = await handler.invoke(event("/jobs", user, settings))
        assert empty["statusCode"] == 200 and json.loads(empty["body"]) == []
        assert empty["headers"]["cache-control"] == "private, no-store"
        assert storage.sign_output.await_count == 2

        health = await handler.invoke(event("/health", user, settings))
        assert health["statusCode"] == 200
        assert "cache-control" not in health["headers"]
        for path in ("/upload", "/internal/v1/assets/" + str(uuid4()) + "/source-access"):
            assert (await handler.invoke(event(path, user, settings, method="POST")))[
                "statusCode"
            ] == 404
    finally:
        app.dependency_overrides.clear()


def test_processing_gateway_identity_never_reads_media_sql(monkeypatch):
    from fastapi import Request

    from processing.auth import gateway_actor

    def forbidden(*args, **kwargs):
        raise AssertionError("Processing tried to access Media SQL")

    monkeypatch.setattr(deps, "get_session", forbidden)
    actor = Actor(str(uuid4()), "publisher")
    request = Request({"type": "http", "state": {"gateway_v1": True, "actor": actor}})
    assert gateway_actor(request) is actor


async def test_exported_hls_handler_reads_owned_projection(settings, user, asset, monkeypatch):
    app = handler.app
    session = SimpleNamespace()
    storage = SimpleNamespace(read_playlist=AsyncMock(return_value="#EXTM3U\nsegment.ts\n"))
    owned_asset = AsyncMock(return_value=asset)
    projection = AsyncMock(
        return_value=SimpleNamespace(
            status="done",
            outputs=[SimpleNamespace(kind="hls_manifest", object_key="owned/master.m3u8")],
        )
    )
    monkeypatch.setattr(v1_hls, "get_asset", owned_asset)
    monkeypatch.setattr(v1_hls, "read_job", projection)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        result = await handler.invoke(event(f"/jobs/{asset.id}/hls/master.m3u8", user, settings))
        assert result["statusCode"] == 200
        assert result["body"] == "#EXTM3U\nsegment.ts\n"
        owned_asset.assert_awaited_once_with(session, asset.id, user.id, lock=True)
        projection.assert_awaited_once_with(session, asset)
        storage.read_playlist.assert_awaited_once_with("owned/master.m3u8")
    finally:
        app.dependency_overrides.clear()
