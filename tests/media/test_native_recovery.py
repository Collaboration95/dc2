"""Native repair orchestration; SQL locking and fencing remain integration concerns."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from media import recovery_v1 as recovery

PHASES = ("cleanup_tombstones", "cleanup_expired_uploads", "cleanup_staged_objects")


@pytest.fixture
def repair(monkeypatch):
    phases = [AsyncMock(return_value=count) for count in (2, 3, 5)]
    calls = Mock()
    for name, phase in zip(PHASES, phases, strict=True):
        monkeypatch.setattr(recovery, name, phase)
        calls.attach_mock(phase, name)
    clock = Mock(return_value=0)
    # Replace the module reference, so asyncio keeps its real monotonic clock.
    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=clock))
    return SimpleNamespace(
        factory=Mock(),
        storage=AsyncMock(),
        settings=SimpleNamespace(
            recovery_batch_size=25, minio_source_bucket="owned-source", orphan_grace_seconds=3600
        ),
        phases=phases,
        calls=calls,
        clock=clock,
    )


@pytest.mark.parametrize("completed", [0, 1, 2])
async def test_deadline_stops_remaining_cleanup(repair, completed):
    # Equality is expired too; each completed phase consumes the remaining budget.
    repair.clock.side_effect = [0] * completed + [10] * (3 - completed)
    result = await recovery.run_once(repair.factory, repair.settings, repair.storage, deadline=10)

    assert result == dict(
        zip(
            ("cleanup", "uploads", "staged"),
            [2, 3, 5][:completed] + [0] * (3 - completed),
            strict=True,
        )
    )
    for index, phase in enumerate(repair.phases):
        assert phase.await_count == (1 if index < completed else 0)
    repair.storage.assert_not_called()


@pytest.mark.parametrize("failed_phase", [0, 1])
async def test_phase_failure_prevents_later_destructive_cleanup(repair, failed_phase):
    error = RuntimeError("cleanup unavailable")
    repair.phases[failed_phase].side_effect = error

    with pytest.raises(RuntimeError) as raised:
        await recovery.run_once(repair.factory, repair.settings, repair.storage)

    assert raised.value is error
    for index, phase in enumerate(repair.phases):
        assert phase.await_count == (1 if index <= failed_phase else 0)


@pytest.mark.parametrize("batch, limit", [(1, 1), (25, 25), (100, 100), (500, 100)])
@pytest.mark.parametrize("deadline", [None, 10])
async def test_bounded_ordered_phases_return_actual_counters(repair, batch, limit, deadline):
    repair.settings.recovery_batch_size = batch
    result = await recovery.run_once(
        repair.factory, repair.settings, repair.storage, deadline=deadline
    )

    assert result == {"cleanup": 2, "uploads": 3, "staged": 5}
    assert repair.calls.mock_calls == [
        call.cleanup_tombstones(repair.factory, repair.storage, limit=limit, deadline=deadline),
        call.cleanup_expired_uploads(
            repair.factory, repair.storage, limit=limit, deadline=deadline
        ),
        call.cleanup_staged_objects(
            repair.factory,
            repair.storage,
            "owned-source",
            grace_seconds=3600,
            limit=limit,
            deadline=deadline,
        ),
    ]
