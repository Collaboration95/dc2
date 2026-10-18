"""Opt-in unattended launcher against real PostgreSQL with fake ECS and SQS (V2, #68).

Set V1_TEST_PROCESSING_DSN to an admin asyncpg DSN, as for test_messaging_sql.py. Each test
owns an ephemeral SQL schema. ECS and SQS are in-process fakes: they prove the launcher's
decisions and its SQL reservations, not ECS idempotency or IAM, which stay cloud evidence.
"""

import asyncio
import os
import time
from datetime import timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from processing import launcher, launcher_models, messaging
from processing.database import Base
from processing.launcher import LauncherConfig, RunTaskRefused
from processing.messaging import handle_command
from processing.models import Attempt, Job
from tests.v1.test_delivery import message
from tests.v1.test_messaging_sql import SETTINGS

pytestmark = pytest.mark.integration

ACCOUNT = "arn:aws:ecs:ap-southeast-1:123456789012"
DEFINITION = f"{ACCOUNT}:task-definition/env-worker:3"


class Crash(BaseException):
    """A killed Lambda: unlike Exception it must not be caught by the launcher."""


class FakeEcs:
    """Just enough ECS: tasks by token (idempotent RunTask), list/describe, failure injection."""

    def __init__(self):
        self.tasks, self.calls, self.run_calls = {}, [], []
        self.lose_response = 0  # next N RunTask calls create the task, then time out
        self.drop_request = 0  # next N RunTask calls never arrive, then time out
        self.crash = 0  # next N RunTask calls kill the caller before ECS sees them
        self.refuse = False
        self.hidden = set()  # tokens ECS has but list/describe do not show yet
        self.list_fails = False
        self.gate = None
        self.started = asyncio.Event()  # set when the first RunTask call is in flight
        self.barrier = None  # releases N concurrent ticks into their reservation step together

    def _task(self, payload):
        token = payload["clientToken"]
        if token not in self.tasks:
            arn = f"{ACCOUNT}:task/cluster/{token}"
            self.tasks[token] = {
                "taskArn": arn,
                "taskDefinitionArn": payload["taskDefinition"],
                "lastStatus": "RUNNING",
                "desiredStatus": "RUNNING",
                "startedBy": payload["startedBy"],
            }
        return self.tasks[token]

    def by_arn(self):
        return {
            t["taskArn"]: t for token, t in self.tasks.items() if token not in self.hidden
        }

    async def list_tasks(self, desired):
        self.calls.append("list")
        # Network latency is what lets concurrent ticks reach the reservation step together;
        # without it they happen to run one after another and hide a missing lock.
        await asyncio.sleep(0.02)
        if self.barrier is not None and desired == "RUNNING":
            await self.barrier.wait()
        if self.list_fails:
            raise TimeoutError("ECS unavailable")
        return [
            arn for arn, t in self.by_arn().items() if (t["desiredStatus"] == "RUNNING") == (
                desired == "RUNNING"
            )
        ]

    async def describe_tasks(self, arns):
        self.calls.append("describe")
        known = self.by_arn()
        return {
            "tasks": [known[a] for a in arns if a in known],
            "failures": [{"arn": a, "reason": "MISSING"} for a in arns if a not in known],
        }

    async def run_task(self, payload):
        self.run_calls.append(payload)
        self.started.set()
        await asyncio.sleep(0.01)  # a real call yields, which is when other ticks interleave
        if self.gate is not None:
            await self.gate.wait()
        if self.crash:
            self.crash -= 1
            raise Crash
        if self.refuse:
            raise RunTaskRefused("AccessDeniedException")
        if self.drop_request:
            self.drop_request -= 1
            raise TimeoutError("request never arrived")
        task = self._task(payload)
        if self.lose_response:
            self.lose_response -= 1
            raise TimeoutError("response lost after the task started")
        return {"tasks": [task], "failures": []}

    def stop(self, task):
        task["lastStatus"], task["desiredStatus"] = "STOPPED", "STOPPED"

    def live(self):
        return [t for t in self.tasks.values() if t["lastStatus"] != "STOPPED"]


class Depth:
    def __init__(self, count=100):
        self.count = count

    async def visible(self):
        return self.count


def config(**overrides):
    values = {
        "cluster": f"{ACCOUNT}:cluster/cluster",
        "task_definition": DEFINITION,
        "subnets": ("subnet-a",),
        "security_groups": ("sg-worker",),
        "lifetime_seconds": 600,
        # Tests rewind nothing: a long replay horizon means "do not replay yet", zero means
        # "the creating invocation is long dead".
        "replay_after_seconds": 3600,
        "release_after_seconds": 7200,
        "idle_cooldown_seconds": 0,
    }
    return LauncherConfig(**(values | overrides))


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_PROCESSING_DSN")
    if not dsn:
        pytest.skip("V1_TEST_PROCESSING_DSN (admin asyncpg DSN) not provided")
    assert launcher_models.LaunchReservation.__tablename__ in Base.metadata.tables
    schema = "v2_launcher_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        dsn, connect_args={"server_settings": {"search_path": schema}}, pool_size=10
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def submit(factory, count):
    for _ in range(count):
        await handle_command(factory, message())


async def enable(factory, minutes=60):
    return await launcher.set_enabled(factory, True, session_end_epoch=time.time() + 60 * minutes)


async def rows(factory):
    async with factory() as session:
        return (
            await session.scalars(
                select(launcher_models.LaunchReservation).order_by(
                    launcher_models.LaunchReservation.reserved_at
                )
            )
        ).all()


async def claim_one(factory, task):
    """The real claim path: binds the first queued attempt to this task's startedBy name."""
    async with factory() as session:
        job_id, attempt_id = (
            await session.execute(
                select(Job.id, Attempt.id)
                .join(Attempt, Job.current_attempt_id == Attempt.id)
                .where(Job.status == "queued", Attempt.state == "queued")
                .order_by(Attempt.queued_at)
                .limit(1)
            )
        ).one()
    assert await messaging.claim(
        factory, job_id, attempt_id, SETTINGS, task_name=task["startedBy"]
    )


async def tick(factory, ecs, depth, **overrides):
    return await launcher.tick(factory, ecs, depth, config(**overrides))


async def test_no_backlog_means_no_launch_and_not_one_aws_call(factory):
    ecs = FakeEcs()
    await enable(factory)
    result = await tick(factory, ecs, Depth(50))
    assert result["launched"] == 0 and result["outcome"] == "idle"
    assert ecs.calls == [] and ecs.run_calls == []


async def test_an_empty_queue_blocks_a_launch_even_when_sql_shows_backlog(factory):
    ecs = FakeEcs()
    await submit(factory, 2)
    await enable(factory)
    result = await tick(factory, ecs, Depth(0))
    assert result["launched"] == 0 and ecs.run_calls == []
    # An unreadable queue is no demand either.

    class Broken:
        async def visible(self):
            raise TimeoutError("SQS unavailable")

    assert (await tick(factory, ecs, Broken()))["launched"] == 0 and ecs.run_calls == []


async def test_a_backlog_of_ten_launches_at_most_three_and_later_ticks_add_none(factory):
    ecs = FakeEcs()
    await submit(factory, 10)
    await enable(factory)
    first = await tick(factory, ecs, Depth())
    assert first["launched"] == 3 and len(ecs.live()) == 3
    for _ in range(3):
        later = await tick(factory, ecs, Depth())
        assert later["launched"] == 0 and later["occupied"] == 3
    assert len(ecs.run_calls) == 3
    assert {call["clientToken"] for call in ecs.run_calls} == set(ecs.tasks)


async def test_launch_requests_are_finite_named_by_token_and_end_before_the_session(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    session_end = time.time() + 300
    await launcher.set_enabled(factory, True, session_end_epoch=session_end)
    await tick(factory, ecs, Depth())
    (payload,) = ecs.run_calls
    assert payload["startedBy"] == launcher.started_by_for(payload["clientToken"])
    assert len(payload["startedBy"]) <= 36 and payload["count"] == 1
    command = payload["overrides"]["containerOverrides"][0]["command"]
    assert command[command.index("--name") + 1] == payload["startedBy"]
    # lifetime_seconds is 600 but the session ends first: the task must end with it.
    assert int(command[command.index("--deadline-epoch") + 1]) <= int(session_end)
    assert payload["launchType"] == "FARGATE" and "assignPublicIp" in str(payload)


async def test_concurrent_triggers_never_exceed_the_cap(factory):
    ecs = FakeEcs()
    ecs.barrier = asyncio.Barrier(6)
    await submit(factory, 10)
    await enable(factory)
    results = await asyncio.gather(*(tick(factory, ecs, Depth()) for _ in range(6)))
    assert sum(r["launched"] for r in results) == 3
    assert len(ecs.run_calls) == 3 == len(ecs.live())
    assert len({call["clientToken"] for call in ecs.run_calls}) == 3
    assert len([r for r in await rows(factory) if r.status in launcher.OPEN_STATES]) == 3


async def test_always_on_concurrent_wakes_never_exceed_the_cap_without_a_session_end(factory):
    # V2-live (#237): every work publisher wakes the launcher, so wakes arrive together. The
    # SQL reservation, not the session, is what holds the cap.
    ecs = FakeEcs()
    ecs.barrier = asyncio.Barrier(8)
    await submit(factory, 10)
    async with factory() as session, session.begin():
        await session.execute(
            insert(launcher_models.LauncherControl).values(id=1, enabled=True)
        )  # enabled with no session end, as nothing on the persistent environment sets one
    results = await asyncio.gather(
        *(tick(factory, ecs, Depth(), always_on=True) for _ in range(8))
    )
    assert sum(r["launched"] for r in results) == 3
    assert len(ecs.run_calls) == 3 == len(ecs.live())
    held = [r for r in await rows(factory) if r.status in launcher.OPEN_STATES]
    assert len(held) == 3
    # Finite all the same: each task ends after its lifetime.
    assert all(
        (r.deadline_at - r.reserved_at).total_seconds() == config().lifetime_seconds
        for r in held
    )


async def test_always_on_launches_nothing_for_an_empty_queue_or_while_switched_off(factory):
    ecs = FakeEcs()
    async with factory() as session, session.begin():
        await session.execute(
            insert(launcher_models.LauncherControl).values(id=1, enabled=True)
        )
    assert (await tick(factory, ecs, Depth(), always_on=True))["outcome"] == "idle"
    await submit(factory, 2)
    assert (await tick(factory, ecs, Depth(0), always_on=True))["launched"] == 0
    await launcher.set_enabled(factory, False)  # the kill switch
    result = await tick(factory, ecs, Depth(), always_on=True)
    assert result["launched"] == 0 and ecs.run_calls == []


async def test_concurrent_triggers_with_a_lost_response_still_respect_the_cap(factory):
    ecs = FakeEcs()
    ecs.lose_response = 3
    ecs.barrier = asyncio.Barrier(4)
    await submit(factory, 10)
    await enable(factory)
    await asyncio.gather(*(tick(factory, ecs, Depth()) for _ in range(4)))
    # The first lost response stops that tick's loop, and the other ticks find the slots
    # already taken: three ambiguous slots, never a fourth, and no more than three sends.
    assert len(ecs.run_calls) <= 3
    held = await rows(factory)
    assert len(held) == 3 and {r.status for r in held} == {"reserved"}


async def test_a_lost_runtask_response_is_resolved_by_token_without_a_second_launch(factory):
    ecs = FakeEcs()
    ecs.lose_response = 1
    await submit(factory, 1)
    await enable(factory)
    lost = await tick(factory, ecs, Depth())
    assert lost["ambiguous"] == 1 and lost["launched"] == 0
    (row,) = await rows(factory)
    assert row.status == "reserved" and row.last_error == "TimeoutError"
    # More backlog than slots: the ambiguous launch still holds its slot, so only two more.
    await submit(factory, 5)
    again = await tick(factory, ecs, Depth())
    assert again["launched"] == 2 and again["occupied"] == 3
    assert len(ecs.run_calls) == 3, "the lost launch was found by startedBy, not re-sent"
    assert sorted(r.status for r in await rows(factory)) == ["launched"] * 3
    assert {r.token for r in await rows(factory)} == set(ecs.tasks)


async def test_a_dropped_request_is_replayed_with_the_identical_token_and_payload(factory):
    ecs = FakeEcs()
    ecs.drop_request = 1
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth())
    assert ecs.tasks == {}
    result = await tick(factory, ecs, Depth(), replay_after_seconds=0)
    assert result["replayed"] == 1 and result["launched"] == 1
    assert ecs.run_calls[0] == ecs.run_calls[1]
    assert len(ecs.live()) == 1


async def test_a_replay_of_a_launch_ecs_has_not_listed_yet_does_not_double_launch(factory):
    ecs = FakeEcs()
    ecs.lose_response = 1
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth())
    ecs.hidden = set(ecs.tasks)  # eventual consistency: started, not yet listed
    await tick(factory, ecs, Depth(), replay_after_seconds=0)
    assert len(ecs.run_calls) == 2 and ecs.run_calls[0] == ecs.run_calls[1]
    assert len(ecs.tasks) == 1, "ECS idempotency on the stored token returned the original task"


async def test_restart_mid_launch_resumes_the_reserved_slots_by_token(factory):
    ecs = FakeEcs()
    ecs.crash = 1
    await submit(factory, 10)
    await enable(factory)
    with pytest.raises(Crash):
        await tick(factory, ecs, Depth())
    reserved = await rows(factory)
    assert len(reserved) == 3 and {r.status for r in reserved} == {"reserved"}
    assert all(r.sent_at is None for r in reserved), "the killed send rolled back"
    # A restarted Lambda must not mint three more slots on top of the stranded three.
    waiting = await tick(factory, ecs, Depth())
    assert waiting["reserved"] == 0 and waiting["occupied"] == 3 and len(ecs.run_calls) == 1
    resumed = await tick(factory, ecs, Depth(), replay_after_seconds=0)
    assert resumed["replayed"] == 3 and resumed["reserved"] == 0
    assert len(ecs.live()) == 3
    assert {call["clientToken"] for call in ecs.run_calls} == {r.token for r in reserved}


async def test_an_idle_worker_is_counted_as_capacity_and_never_respawned(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    assert (await tick(factory, ecs, Depth()))["launched"] == 1
    for _ in range(3):
        idle = await tick(factory, ecs, Depth())
        assert idle["launched"] == 0 and idle["idle_workers"] == 1
    # Three queued attempts and one unclaimed worker: add two, not three.
    await submit(factory, 2)
    assert (await tick(factory, ecs, Depth()))["launched"] == 2
    assert len(ecs.run_calls) == 3


async def test_a_worker_that_holds_an_attempt_does_not_offset_new_backlog(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth())
    (task,) = ecs.live()
    await claim_one(factory, task)
    await submit(factory, 1)
    result = await tick(factory, ecs, Depth())
    assert result["launched"] == 1 and result["idle_workers"] == 0
    assert [r.claimed for r in await rows(factory)] == [None, None]


async def test_three_idle_exits_in_a_row_stop_launches_until_the_operator_reenables(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    for round_ in range(3):
        assert (await tick(factory, ecs, Depth()))["launched"] == 1, round_
        ecs.stop(ecs.live()[0])  # exits after its empty polls without claiming anything
    blocked = await tick(factory, ecs, Depth())
    assert blocked["reason"] == "idle-breaker" and blocked["launched"] == 0
    assert [r.claimed for r in await rows(factory)] == [False, False, False]
    count = len(ecs.run_calls)
    again = await tick(factory, ecs, Depth())
    assert again["launched"] == 0 and len(ecs.run_calls) == count
    # An explicit enable is the operator saying "try again".
    await enable(factory)
    assert (await tick(factory, ecs, Depth()))["launched"] == 1
    assert len(ecs.run_calls) == count + 1


async def test_one_idle_exit_waits_out_the_cooldown_before_replacing_the_worker(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth(), idle_cooldown_seconds=600)
    ecs.stop(ecs.live()[0])
    paused = await tick(factory, ecs, Depth(), idle_cooldown_seconds=600)
    assert paused["reason"] == "idle-cooldown" and paused["launched"] == 0
    resumed = await tick(factory, ecs, Depth(), idle_cooldown_seconds=0)
    assert resumed["launched"] == 1


async def test_a_worker_that_finished_real_work_is_replaced_when_new_backlog_arrives(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth(), idle_cooldown_seconds=600)
    await claim_one(factory, ecs.live()[0])
    ecs.stop(ecs.live()[0])
    await submit(factory, 1)
    result = await tick(factory, ecs, Depth(), idle_cooldown_seconds=600)
    assert result["launched"] == 1
    assert [r.claimed for r in await rows(factory) if r.status == "stopped"] == [True]


async def test_workers_started_by_anyone_count_against_the_cap(factory):
    ecs = FakeEcs()
    for name in ("operator-batch-1", "operator-batch-2"):
        ecs._task({"clientToken": name, "startedBy": name, "taskDefinition": DEFINITION})
    await submit(factory, 10)
    await enable(factory)
    for task in ecs.live():
        await claim_one(factory, task)
    await submit(factory, 5)
    result = await tick(factory, ecs, Depth())
    assert result["occupied"] == 3 and result["launched"] == 1


async def test_other_task_families_do_not_consume_worker_slots(factory):
    ecs = FakeEcs()
    ecs._task(
        {
            "clientToken": "migration",
            "startedBy": "migration",
            "taskDefinition": f"{ACCOUNT}:task-definition/env-processingmigration:1",
        }
    )
    await submit(factory, 3)
    await enable(factory)
    assert (await tick(factory, ecs, Depth()))["launched"] == 3


async def test_disabling_stops_every_launch_including_a_slot_already_reserved(factory):
    ecs = FakeEcs()
    ecs.crash = 1
    await submit(factory, 5)
    await enable(factory)
    with pytest.raises(Crash):
        await tick(factory, ecs, Depth())
    await launcher.set_enabled(factory, False)
    calls = len(ecs.run_calls)
    # The stranded reservations are not replayed once the launcher is off ...
    closed = await tick(factory, ecs, Depth(), replay_after_seconds=0, release_after_seconds=0)
    assert closed["reason"] == "disabled" and closed["launched"] == 0
    assert len(ecs.run_calls) == calls
    # ... and settle reports nothing ambiguous remaining, so close may proceed.
    assert (await launcher.settle(factory, ecs, config(release_after_seconds=0)))["ambiguous"] == 0
    assert {r.status for r in await rows(factory)} == {"released"}


async def test_a_send_that_starts_after_disable_releases_its_slot_without_calling_ecs(factory):
    ecs = FakeEcs()
    ecs.crash = 1
    await submit(factory, 1)
    await enable(factory)
    with pytest.raises(Crash):
        await tick(factory, ecs, Depth())
    (row,) = await rows(factory)
    await launcher.set_enabled(factory, False)
    calls = len(ecs.run_calls)
    assert await launcher._send(factory, ecs, row.token) == "closed"
    assert len(ecs.run_calls) == calls
    assert (await rows(factory))[0].status == "released"


async def test_disable_waits_for_an_in_flight_send_so_nothing_launches_after_it_returns(factory):
    ecs = FakeEcs()
    ecs.gate = asyncio.Event()
    await submit(factory, 3)
    await enable(factory)
    running = asyncio.create_task(tick(factory, ecs, Depth()))
    await ecs.started.wait()
    closing = asyncio.create_task(launcher.set_enabled(factory, False))
    await asyncio.sleep(0.3)
    assert not closing.done(), "disable must queue behind the send holding the control row"
    ecs.gate.set()
    outcome = await running
    assert (await closing)["enabled"] is False
    calls = len(ecs.run_calls)
    # The in-flight send finished and was recorded; the loop's later sends were refused.
    assert outcome["launched"] == 1 and outcome["closed"] == 2
    assert len(ecs.run_calls) == calls == 1
    after = await tick(factory, ecs, Depth())
    assert after["launched"] == 0 and len(ecs.run_calls) == 1


async def test_enabling_requires_a_future_session_end_and_launches_stop_near_it(factory):
    with pytest.raises(ValueError):
        await launcher.set_enabled(factory, True, session_end_epoch=None)
    with pytest.raises(ValueError):
        await launcher.set_enabled(factory, True, session_end_epoch=time.time() - 1)
    ecs = FakeEcs()
    await submit(factory, 1)
    await launcher.set_enabled(factory, True, session_end_epoch=time.time() + 60)
    result = await tick(factory, ecs, Depth(), min_useful_seconds=120)
    assert result["reason"] == "session-ended" and ecs.run_calls == []


async def test_a_refusal_from_ecs_releases_the_slot_and_is_not_retried_in_the_same_tick(factory):
    ecs = FakeEcs()
    ecs.refuse = True
    await submit(factory, 3)
    await enable(factory)
    result = await tick(factory, ecs, Depth())
    assert result["refused"] == 1 and len(ecs.run_calls) == 1
    states = sorted(r.status for r in await rows(factory))
    assert states.count("released") == 1 and states.count("reserved") == 2
    ecs.refuse = False
    later = await tick(factory, ecs, Depth(), replay_after_seconds=0)
    assert len(ecs.live()) == 3 and later["occupied"] == 3


async def test_an_unreadable_inventory_fails_closed_before_any_reservation(factory):
    ecs = FakeEcs()
    ecs.list_fails = True
    await submit(factory, 3)
    await enable(factory)
    with pytest.raises(TimeoutError):
        await tick(factory, ecs, Depth())
    assert ecs.run_calls == [] and await rows(factory) == []


async def test_a_reservation_that_ecs_never_confirms_is_released_after_the_horizon(factory):
    ecs = FakeEcs()
    ecs.drop_request = 1
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth(), release_after_seconds=0, replay_after_seconds=3600)
    await launcher.set_enabled(factory, False)
    result = await launcher.settle(factory, ecs, config(release_after_seconds=0))
    assert result["ambiguous"] == 0
    assert [r.status for r in await rows(factory)] == ["released"]


async def test_a_forgotten_task_past_its_deadline_settles_as_stopped(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth())
    ecs.tasks.clear()  # ECS stopped remembering it
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE launch_reservations SET deadline_at = now() - interval '1 second'")
        )
    await launcher.settle(factory, ecs, config())
    (row,) = await rows(factory)
    assert row.status == "stopped" and row.claimed is False


async def test_the_status_and_idle_fast_paths_report_counts_only(factory):
    assert (await launcher.status(factory))["enabled"] is False
    await enable(factory)
    summary = await launcher.status(factory)
    assert summary["enabled"] is True and summary["ambiguous"] == 0
    assert set(summary) == {"enabled", "session_end_at", "ambiguous", "launched", "reservations"}
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job)) == 0


async def test_reservation_timestamps_use_the_database_clock(factory):
    ecs = FakeEcs()
    await submit(factory, 1)
    await enable(factory)
    await tick(factory, ecs, Depth())
    (row,) = await rows(factory)
    async with factory() as session:
        now = await session.scalar(select(func.clock_timestamp()))
    assert timedelta(0) <= now - row.reserved_at < timedelta(seconds=30)
    assert row.sent_at is not None and row.deadline_at > row.reserved_at


# ---- V2-live (AD-27): when the minute ticks next need SQL ------------------------------
async def test_idle_processing_has_nothing_due_and_open_work_is_due_now(factory):
    from processing.recovery_v1 import next_due

    assert await next_due(factory) is None
    await submit(factory, 1)
    assert await next_due(factory) == 0.0  # a queued attempt: dispatch and launches


async def test_once_no_attempt_is_open_the_earliest_scheduled_row_is_the_next_due_time(factory):
    from sqlalchemy import update

    from processing.messaging_models import ProcessingOutbox
    from processing.recovery_v1 import next_due

    await submit(factory, 1)
    async with factory() as session, session.begin():
        await session.execute(update(Attempt).values(state="cancelled"))
        await session.execute(
            update(ProcessingOutbox).values(next_try_at=func.now() + timedelta(days=6))
        )
    due = await next_due(factory)
    # The outbox's scheduled replay, six days out: the ticks may skip SQL until then.
    assert time.time() + 5 * 86400 < due < time.time() + 7 * 86400
    # An open launch reservation is work now, whatever else is scheduled.
    async with factory() as session, session.begin():
        session.add(launcher_models.LaunchReservation(
            token="t" * 32, started_by="v1-ut", status="reserved", payload={},
            deadline_at=func.now() + timedelta(minutes=5)))
    assert await next_due(factory) == 0.0


async def test_an_online_release_caps_launches_and_switches_the_worker_through_sql(factory):
    # V2-live: the release leaves Fargate room for its own tasks, then the launcher starts the
    # released worker; clearing both returns the stack's own cap and worker.
    ecs = FakeEcs()
    await submit(factory, 10)
    await enable(factory)
    released = DEFINITION.replace(":3", ":9")
    await launcher.set_release_controls(factory, cap_limit=2, worker_definition=released)
    first = await tick(factory, ecs, Depth())
    assert first["launched"] == 2
    assert {call["taskDefinition"] for call in ecs.run_calls} == {released}
    await launcher.set_release_controls(factory, cap_limit=None, worker_definition=None)
    later = await tick(factory, ecs, Depth())
    assert later["launched"] == 1 and ecs.run_calls[-1]["taskDefinition"] == DEFINITION
    with pytest.raises(ValueError):
        await launcher.set_release_controls(factory, cap_limit=4)
