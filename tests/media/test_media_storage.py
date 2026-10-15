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
    await store.delete_source("source-key")
    store.internal.remove_object.assert_called_once_with("owned-source", "source-key")
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
