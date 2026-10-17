"""Exercise the exported handler, keeping legacy routes outside the V1 boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from contracts.v1 import Actor
from media.api import deps, v1_hls, v1_jobs
from media.config import get_settings
from media.database import get_session
from media.lambda_handler import handler
from media.main import create_app
from media.services.processing_client import get_processing_client as get_peer
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
    import media.main as entry

    default = {route.path for route in domain_routes(entry.app)}
    assert "/upload" not in default and not any("internal" in path for path in default)
    assert "/uploads/reservations" in default
    legacy = {route.path for route in domain_routes(entry.legacy_app)}
    assert "/upload" in legacy and any("internal" in path for path in legacy)
    assert entry.legacy_app is entry.legacy_app
    with pytest.raises(AttributeError):
        _ = entry.no_such_app


async def test_exported_handler_reads_owned_projection_without_peer(settings, user, monkeypatch):
    app = handler.app
    session = SimpleNamespace()

    async def auth_sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=user))

    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(deps, "get_session", auth_sessions)
    monkeypatch.setattr(v1_jobs, "list_assets", listing)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: SimpleNamespace()

    def forbidden_peer():
        raise AssertionError("V1 invoked the HTTP peer")

    app.dependency_overrides[get_peer] = forbidden_peer
    try:
        result = await handler.invoke(event("/jobs", user, settings))
        assert result["statusCode"] == 200
        assert json.loads(result["body"]) == []
        listing.assert_awaited_once_with(session, user.id, 50, 0)
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
