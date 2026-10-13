"""Output I/O bounds through the real MinIO reader, with network calls replaced."""

import asyncio
import builtins
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from minio import Minio

from processing.worker.storage import OutputStore


class CountedFile:
    def __init__(self, handle, counts):
        self.handle, self.counts = handle, counts

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.handle.__exit__(*args)

    def read(self, size=-1):
        data = self.handle.read(size)
        self.counts["read_bytes"] += len(data)
        return data

    def readinto(self, buffer):
        size = self.handle.readinto(buffer)
        self.counts["read_bytes"] += size
        return size


def count_file_io(monkeypatch, path):
    counts = {"read_bytes": 0, "opens": 0, "offloads": 0}
    open_file, open_path, offload = builtins.open, Path.open, asyncio.to_thread

    def wrap(handle):
        counts["opens"] += 1
        return CountedFile(handle, counts)

    def file_open(name, *args, **kwargs):
        handle = open_file(name, *args, **kwargs)
        return wrap(handle) if str(name) == str(path) else handle

    def path_open(self, *args, **kwargs):
        handle = open_path(self, *args, **kwargs)
        return wrap(handle) if self == path else handle

    async def to_thread(*args, **kwargs):
        counts["offloads"] += 1
        return await offload(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", file_open)
    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    return counts


def output_store(client):
    store = OutputStore.__new__(OutputStore)
    store.bucket, store.client = "outputs", client
    return store


@pytest.mark.parametrize("size", [64, 262144, 5 * 1024 * 1024 + 17])
async def test_sdk_upload_reads_output_once_with_matching_digest(monkeypatch, tmp_path, size):
    path = tmp_path / "output"
    content = b"x" * size
    path.write_bytes(content)
    counts = count_file_io(monkeypatch, path)
    uploaded = hashlib.sha256()
    part_sizes = []
    client = Minio("unused.test", region="us-east-1")

    def record(_bucket, _key, data, *_args):
        uploaded.update(data)
        part_sizes.append(len(data))
        return SimpleNamespace(etag="ack")

    client._put_object = Mock(side_effect=record)
    client._create_multipart_upload = Mock(return_value="upload-id")
    client._upload_part = Mock(side_effect=lambda *args: record(*args).etag)
    client._complete_multipart_upload = Mock(
        return_value=SimpleNamespace(
            bucket_name="outputs", object_name="key", version_id=None, etag="ack",
            http_headers={}, location=None,
        )
    )
    client.stat_object = Mock(side_effect=AssertionError("HEAD is forbidden"))
    client.get_object = Mock(side_effect=AssertionError("GET is forbidden"))
    client.put_object = Mock(wraps=client.put_object)
    output = await output_store(client).put("key", path, "video/mp4", "primary")
    assert output == {
        "kind": "primary", "object_key": "key", "media_type": "video/mp4",
        "size_bytes": size, "sha256": hashlib.sha256(content).hexdigest(),
    }
    assert output["sha256"] == uploaded.hexdigest()
    assert counts == {"read_bytes": size, "opens": 1, "offloads": 1}
    assert part_sizes == ([size] if size <= 5 * 1024 * 1024 else [5 * 1024 * 1024, 17])
    assert client.put_object.call_args.kwargs["num_parallel_uploads"] == 1
    client.stat_object.assert_not_called()
    client.get_object.assert_not_called()


@pytest.mark.parametrize("problem", ["empty", "unread", "partial", "grown", "no_etag", "error"])
async def test_output_metadata_requires_complete_acknowledged_upload(tmp_path, problem):
    path = tmp_path / "output"
    path.write_bytes(b"" if problem == "empty" else b"output")

    def upload(_bucket, _key, stream, length, **_kwargs):
        if problem == "error":
            raise OSError("upload failed")
        if problem != "unread":
            stream.read(length - 1 if problem == "partial" else length)
        if problem == "grown":
            with path.open("ab") as handle:
                handle.write(b"extra")
        return SimpleNamespace(etag="" if problem == "no_etag" else "ack")

    client = SimpleNamespace(put_object=Mock(side_effect=upload))
    with pytest.raises(OSError if problem == "error" else ValueError):
        await output_store(client).put("key", path, "video/mp4", "primary")
    if problem == "empty":
        client.put_object.assert_not_called()


async def test_sdk_rejects_truncated_output_before_acknowledgement(tmp_path):
    path = tmp_path / "output"
    path.write_bytes(b"output")
    client = Minio("unused.test", region="us-east-1")
    real_put = client.put_object

    def truncate_then_upload(*args, **kwargs):
        path.write_bytes(b"o")
        return real_put(*args, **kwargs)

    client.put_object = truncate_then_upload
    client._put_object = Mock(side_effect=AssertionError("truncated data must not be uploaded"))
    with pytest.raises(OSError, match="not enough data"):
        await output_store(client).put("key", path, "video/mp4", "primary")
    client._put_object.assert_not_called()


@pytest.mark.parametrize("failure", ["part", "completion"])
async def test_failed_multipart_aborts_and_fresh_retry_has_accurate_digest(tmp_path, failure):
    path = tmp_path / "output"
    content = b"x" * (5 * 1024 * 1024 + 17)
    path.write_bytes(content)
    client = Minio("unused.test", region="us-east-1")
    client._create_multipart_upload = Mock(return_value="upload-id")
    client._abort_multipart_upload = Mock()
    client._upload_part = Mock(
        side_effect=["part-1", OSError("part failed")] if failure == "part" else None,
        return_value="ack",
    )
    completed = SimpleNamespace(
        bucket_name="outputs", object_name="key", version_id=None, etag="ack",
        http_headers={}, location=None,
    )
    client._complete_multipart_upload = Mock(
        side_effect=OSError("completion failed") if failure == "completion" else None,
        return_value=completed,
    )
    store = output_store(client)
    with pytest.raises(OSError):
        await store.put("failed/key", path, "video/mp4", "primary")
    client._abort_multipart_upload.assert_called_once_with("outputs", "failed/key", "upload-id")
    client._upload_part.side_effect = None
    client._complete_multipart_upload.side_effect = None
    output = await store.put("retry/key", path, "video/mp4", "primary")
    assert output["object_key"] == "retry/key"
    assert output["size_bytes"] == len(content)
    assert output["sha256"] == hashlib.sha256(content).hexdigest()


async def test_cancelled_upload_returns_no_metadata_while_thread_finishes(tmp_path):
    path = tmp_path / "output"
    path.write_bytes(b"output")
    started, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    handles = []

    def upload(_bucket, _key, stream, length, **_kwargs):
        handles.append(stream.handle)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(2)
        assert stream.read(length) == b"output"
        return SimpleNamespace(etag="ack")

    class SignaledStore(OutputStore):
        def _put(self, *args):
            try:
                return super()._put(*args)
            finally:
                loop.call_soon_threadsafe(finished.set)

    client = SimpleNamespace(put_object=upload)
    store = SignaledStore.__new__(SignaledStore)
    store.bucket, store.client = "outputs", client
    task = asyncio.create_task(store.put("key", path, "video/mp4", "primary"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
    assert handles[0].closed
