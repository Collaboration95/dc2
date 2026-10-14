"""Experimental evidence must reject lost/duplicate output and unsafe drain."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts.evidence.common import EvidenceError
from scripts.experiments.followups import ExperimentDocker, queued_age, window_metrics


def job(asset="a", attempt="t", state="succeeded"):
    return dict(
        asset_id=asset,
        job_id="j" + asset,
        attempt_id=attempt,
        state=state,
        queued_at="2026-10-14T00:00:00+00:00",
        started_at="2026-10-14T00:00:10+00:00",
        finished_at="2026-10-14T00:00:20+00:00",
        has_primary=True,
        has_hls=True,
        has_error=False,
    )


@pytest.mark.parametrize(
    "bad",
    [[], [job(state="failed")], [dict(job(), has_hls=False)], [dict(job(), has_primary=False)]],
)
def test_window_requires_every_complete_success(bad):
    with pytest.raises(EvidenceError):
        window_metrics(bad, [dict(asset_id="a", seconds=2)], 30)


def test_duplicate_attempt_cannot_be_counted_as_two_outputs():
    with pytest.raises(EvidenceError, match="Duplicate"):
        window_metrics(
            [job(), job("b")], [dict(asset_id="a", seconds=2), dict(asset_id="b", seconds=60)], 30
        )


def test_queued_age_excludes_active_and_finished_jobs():
    jobs = [job(), job("b", "t2", "processing"), job("c", "t3", "queued")]
    assert queued_age(jobs, 1791936030) == 30
    assert queued_age(jobs[:2], 1791936030) == 0


@pytest.mark.asyncio
async def test_warm_drain_waits_beyond_old_sixty_second_grace(monkeypatch):
    docker = object.__new__(ExperimentDocker)
    docker.artifacts = MagicMock()
    docker.command = MagicMock(return_value='[{"State":{"ExitCode":0,"OOMKilled":false}}]')
    docker.worker_states = MagicMock(
        side_effect=[
            [dict(running=True, paused=False, id="owned")],
            [dict(running=True)],
            [dict(running=False)],
        ]
    )
    clock = iter([0, 61, 62])
    monkeypatch.setattr(
        "scripts.experiments.followups.time", SimpleNamespace(monotonic=lambda: next(clock, 62))
    )

    async def immediate(_seconds):
        return None

    monkeypatch.setattr("scripts.experiments.followups.asyncio.sleep", immediate)
    assert await docker.drain(["owned"]) == 62
    assert docker.command.call_args_list[0].args == ("kill", "--signal", "SIGTERM", "owned")
    assert all(
        "stop" not in call.args and "SIGKILL" not in call.args
        for call in docker.command.call_args_list
    )


@pytest.mark.asyncio
async def test_warm_drain_timeout_preserves_worker_for_recovery(monkeypatch):
    docker = object.__new__(ExperimentDocker)
    docker.artifacts = MagicMock()
    docker.command = MagicMock()
    docker.worker_states = MagicMock(return_value=[dict(running=True, paused=False, id="owned")])
    clock = iter([0, 301])
    monkeypatch.setattr(
        "scripts.experiments.followups.time", SimpleNamespace(monotonic=lambda: next(clock, 301))
    )
    with pytest.raises(EvidenceError, match="300s"):
        await docker.drain(["owned"])
    assert docker.command.call_count == 1


@pytest.mark.asyncio
async def test_drain_rejects_abnormal_exit_and_paused_worker():
    docker = object.__new__(ExperimentDocker)
    docker.artifacts = MagicMock()
    docker.command = MagicMock(return_value='[{"State":{"ExitCode":137,"OOMKilled":false}}]')
    docker.worker_states = MagicMock(
        side_effect=[[dict(running=True, paused=False, id="owned")], [dict(running=False)]]
    )
    with pytest.raises(EvidenceError, match="abnormally"):
        await docker.drain(["owned"])
    docker.worker_states = MagicMock(return_value=[dict(running=True, paused=True, id="owned")])
    docker.command.reset_mock()
    with pytest.raises(EvidenceError, match="unpaused"):
        await docker.drain(["owned"])
    docker.command.assert_not_called()
