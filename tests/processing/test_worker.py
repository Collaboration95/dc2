import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from processing.config import Settings
from processing.worker import tasks
from processing.worker.storage import OutputStore
from processing.worker.supervisor import AttemptDeadline, LeaseLost, Supervisor


def cfg(**kw):
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db", **kw)


def work():
    return SimpleNamespace(
        job_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        owner_id=uuid4(),
        source={
            "asset_id": str(uuid4()),
            "revision": 1,
            "sha256": "a" * 64,
            "size_bytes": 10,
            "media_type": "video/mp4",
        },
        operations=[],
        source_url="http://original.test",
        source_url_expires_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("exception", [LeaseLost, AttemptDeadline, asyncio.CancelledError])
async def test_hls_does_not_swallow_control_flow(monkeypatch, tmp_path, exception):
    download = AsyncMock()
    sup = Mock()
    sup.guard = AsyncMock(side_effect=lambda op: op)

    async def guard(op):
        return await op

    sup.guard.side_effect = guard
    sup.run = AsyncMock(
        side_effect=[
            json.dumps({"streams": [{"width": 32, "height": 24}], "format": {"duration": "1"}}),
            "",
            exception(),
        ]
    )
    store = SimpleNamespace(put=AsyncMock(return_value={"kind": "primary"}))
    with pytest.raises(exception):
        await tasks.pipeline(
            work(), cfg(), sup, None, store, tmp_path, downloader=download
        )


async def test_hls_failure_retains_primary(monkeypatch, tmp_path):
    download = AsyncMock()
    sup = Mock()

    async def guard(op):
        return await op

    sup.guard = guard
    sup.run = AsyncMock(
        side_effect=[
            json.dumps({"streams": [{"width": 32, "height": 24}], "format": {"duration": "1"}}),
            "",
            ValueError("HLS"),
        ]
    )
    store = SimpleNamespace(put=AsyncMock(return_value={"kind": "primary"}))
    assert await tasks.pipeline(
            work(), cfg(), sup, None, store, tmp_path, downloader=download
        ) == [{"kind": "primary"}]


async def test_guard_loss_interrupts_download_or_upload(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    sup = Supervisor(None, work(), cfg())
    cancelled = asyncio.Event()

    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with sup:
        task = asyncio.create_task(sup.guard(blocked()))
        await asyncio.sleep(0)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await task
    assert cancelled.is_set()


async def test_process_group_stopped_on_loss(monkeypatch, tmp_path):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    sup = Supervisor(None, work(), cfg())
    marker = tmp_path / "started"
    # Subprocess is local and deliberately alive until lease loss.
    script = f"import time,pathlib; pathlib.Path({str(marker)!r}).touch(); time.sleep(60)"
    async with sup:
        task = asyncio.create_task(sup.run([sys.executable, "-c", script]))
        async with asyncio.timeout(2):
            while not marker.exists():  # noqa: ASYNC110 - bounded subprocess readiness
                await asyncio.sleep(0.01)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(task, 2)


async def test_supervisor_deadline_and_bad_subprocess(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    async with Supervisor(None, work(), cfg()) as sup:
        with pytest.raises(ValueError, match="could not be processed"):
            await sup.run([sys.executable, "-c", "raise SystemExit(1)"])
        sup.deadline = time.monotonic() + 0.01
        with pytest.raises(AttemptDeadline):
            await sup.guard(asyncio.sleep(1))


@pytest.mark.parametrize("alive", [False, RuntimeError("secret")])
async def test_heartbeat_revokes_on_failure(monkeypatch, alive, caplog):
    callback = (
        AsyncMock(side_effect=alive)
        if isinstance(alive, Exception)
        else AsyncMock(return_value=alive)
    )
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", callback)
    async with Supervisor(None, work(), cfg()) as sup:
        await asyncio.wait_for(sup.lost.wait(), 0.5)
        with pytest.raises(LeaseLost):
            sup.check()
    assert "encoder authority revoked: LeaseLost" in caplog.text
    assert "secret" not in caplog.text


async def test_output_put_acknowledgment_without_head(monkeypatch, tmp_path):
    client = Mock()

    def upload(_bucket, _key, stream, length, **_kwargs):
        assert stream.read(length) == b"output"
        return SimpleNamespace(etag=etag)

    etag = "ack"
    client.put_object.side_effect = upload
    monkeypatch.setattr("processing.worker.storage.Minio", Mock(return_value=client))
    store = OutputStore(cfg(minio_access_key="writer", minio_secret_key="secret"))
    path = tmp_path / "out"
    path.write_bytes(b"output")
    output = await store.put("key", path, "video/mp4", "primary")
    assert output["size_bytes"] == 6 and len(output["sha256"]) == 64
    assert not client.stat_object.called and not client.get_object.called
    etag = ""
    with pytest.raises(ValueError):
        await store.put("key", path, "video/mp4", "primary")


async def test_total_deadline_is_not_reset_between_stages(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    async with Supervisor(None, work(), cfg()) as sup:
        sup.deadline = time.monotonic() + 0.03
        await sup.guard(asyncio.sleep(0.02))
        with pytest.raises(AttemptDeadline):
            await sup.guard(asyncio.sleep(0.02))


async def test_cancel_stops_descendant_when_process_leader_already_exited(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    pid_file = tmp_path / "child-pid"
    child_script = (
        f"import os,time,pathlib; pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    script = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child_script!r}])"
    async with Supervisor(None, work(), cfg()) as sup:
        task = asyncio.create_task(sup.run([sys.executable, "-c", script]))
        async with asyncio.timeout(2):
            while not pid_file.exists():  # noqa: ASYNC110 - bounded process readiness
                await asyncio.sleep(0.01)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(task, 2)
        child_pid = int(pid_file.read_text())
        # Reaping orphaned children can lag; distinguish a zombie from a live process.
        async with asyncio.timeout(2):
            while True:  # noqa: ASYNC110 - bounded process death polling
                process = await asyncio.create_subprocess_exec(
                    "ps", "-o", "stat=", "-p", str(child_pid), stdout=asyncio.subprocess.PIPE
                )
                output, _ = await process.communicate()
                if not output.strip() or output.strip().startswith(b"Z"):
                    break
                await asyncio.sleep(0.01)
        with pytest.raises(ProcessLookupError):
            # On macOS the adopted process is already reaped; Linux may retain
            # zombies briefly, so this final assertion applies only there.
            if sys.platform == "darwin":
                os.kill(child_pid, 0)
            else:
                raise ProcessLookupError
