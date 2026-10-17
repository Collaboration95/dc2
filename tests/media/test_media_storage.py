import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from minio import Minio
from minio.credentials import StaticProvider

from media.errors import MediaError
from media.services.storage import Storage, get_storage


@pytest.fixture
def store(settings):
    storage = Storage(settings)
    storage.internal = MagicMock()
    return storage


async def test_minio_capabilities_use_correct_internal_and_public_hosts(store, settings):
    # Real local signing with explicit region requires no MinIO network call.
    store.provider = StaticProvider("test-access", "test-secret")
    store.internal = Minio(
        settings.minio_endpoint,
        secure=False,
        access_key="test-access",
        secret_key="test-secret",
        region=settings.minio_region,
    )
    internal, expiry = await store.source_grant("sources/owned/input.mp4")
    assert internal.startswith("http://minio:9000/owned-source/sources/owned/input.mp4?")
    assert expiry.tzinfo is not None
    public = await store.sign_output("outputs/attempt/output.mp4", inline=True)
    assert public.startswith("https://localhost:4443/owned-output/outputs/attempt/output.mp4?")
    assert "response-content-disposition=inline" in public


async def test_source_put_and_delete_are_scoped_and_output_read_releases_connection(store):
    stream = BytesIO(b"abc")
    await store.put_source("source-key", stream, 3, "video/mp4")
    store.internal.put_object.assert_called_once_with(
        "owned-source", "source-key", stream, 3, content_type="video/mp4"
    )
    store.internal.list_objects.return_value = []
    store.internal.remove_objects.return_value = []
    await store.delete_source("source-key")
    store.internal.list_objects.assert_called_once_with(
        "owned-source", prefix="source-key", recursive=True, include_version=True
    )
    store.internal.remove_object.assert_not_called()
    response = store.internal.get_object.return_value
    response.read.return_value = b"#EXTM3U\nv0/index.m3u8\n"
    assert await store.read_playlist("output/hls/master.m3u8") == response.read.return_value
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
    response.read.return_value = b"x" * (1024 * 1024 + 1)
    with pytest.raises(MediaError):
        await store.read_playlist("output/hls/master.m3u8")
    assert response.close.call_count == 2


@pytest.mark.parametrize("failure", ["none", "size", "digest", "empty", "overrun"])
async def test_independent_copy_verifies_digest_size_and_limits_before_put(
    store, monkeypatch, failure
):
    content = b"output-video"
    output = SimpleNamespace(
        object_key="parent/output.mp4",
        media_type="video/mp4",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    if failure == "size":
        output.size_bytes += 1
    if failure == "digest":
        output.sha256 = "a" * 64
    if failure == "empty":
        content = b""
    if failure == "overrun":
        output.size_bytes = 1
    response = store.internal.get_object.return_value
    response.read.side_effect = [content, b""]
    if failure == "none":
        assert await store.copy_output_source(output, "child/source") == (
            len(content),
            output.sha256,
        )
        assert store.internal.put_object.call_args.args[:2] == ("owned-source", "child/source")
    else:
        with pytest.raises(MediaError):
            await store.copy_output_source(output, "child/source")
        store.internal.put_object.assert_not_called()
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


def test_storage_pool_is_app_local(settings):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert get_storage(request, settings) is get_storage(request, settings)


def version(name, version_id, *, marker=False):
    return SimpleNamespace(object_name=name, version_id=version_id, is_delete_marker=marker)


def record_removals(store):
    seen = []

    def remove(bucket, deletes):
        # The SDK consumes the generator lazily; it carries the filter under test.
        seen.extend((bucket, d.name, d.version_id) for d in deletes)
        return []

    store.internal.remove_objects.side_effect = remove
    return seen


async def test_source_delete_removes_every_version_and_marker_of_only_that_key(store):
    store.internal.list_objects.return_value = [
        version("source-key", "v2"),
        version("source-key", "marker", marker=True),
        version("source-key", "v1"),
        version("source-key-sibling", "other"),
    ]
    seen = record_removals(store)
    await store.delete_source("source-key")
    assert seen == [("owned-source", "source-key", v) for v in ("v2", "marker", "v1")]


async def test_source_delete_reports_a_refused_version_so_the_intent_is_kept(store):
    store.internal.list_objects.return_value = [version("source-key", "v1")]
    store.internal.remove_objects.return_value = [SimpleNamespace(code="AccessDenied")]
    with pytest.raises(MediaError) as error:
        await store.delete_source("source-key")
    assert error.value.status_code == 503


async def test_source_delete_can_preserve_the_pinned_version(store):
    store.internal.list_objects.return_value = [version("k", "keep"), version("k", "drop")]
    seen = record_removals(store)
    await store.remove_source_versions("owned-source", "k", preserve_version="keep")
    assert seen == [("owned-source", "k", "drop")]
