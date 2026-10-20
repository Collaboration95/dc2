"""Opt-in unattended encoder starts (V2 experiment, issue #68). V1 never imports this.

V1 starts finite Fargate encoders only when an operator runs a batch. This module lets a
scheduled Lambda do the same thing unattended, with the same three-executor cap, and
without ever starting a task that has no work to claim.

Safety rests on SQL, not on the Lambda or on ECS:

* A launch slot is a ``launch_reservations`` row committed BEFORE RunTask is called. The
  row carries the ECS ``clientToken``/``startedBy``, so a lost response, a killed Lambda or
  a second invocation can be resolved by token, never by guessing.
* The cap counts every live worker task ECS reports (whoever started it) plus every
  reservation that no live task explains yet. An ambiguous launch therefore keeps its slot.
* ``launcher_control`` is a single row. Reserving takes it FOR UPDATE (concurrent ticks
  queue up and each sees the previous tick's reservations); every send holds it FOR SHARE
  across the RunTask call. Disabling takes it FOR UPDATE, so it waits for in-flight sends
  and no launch can begin after it returns. That is the close interlock.
* Demand is the smaller of queued attempts in SQL and visible SQS messages, minus workers
  that are still unclaimed (a finite worker takes one attempt), so an idle worker is never
  added to and an exited one is not replaced without new backlog.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from processing import lifecycle
from processing.launcher_models import OPEN_STATES, LauncherControl, LaunchReservation
from processing.messaging_models import AttemptTask, JobMessaging
from processing.models import Attempt, Job
from processing.recovery_v1 import stopped_task_names

# The V1 three-executor bound. A configuration can lower it, never raise it.
HARD_CAP = 3
DESCRIBE_BATCH = 100
LIST_PAGES = 10


class RunTaskRefused(Exception):
    """ECS answered and nothing was started (4xx or an empty ``tasks`` with failures)."""


@dataclass(frozen=True)
class LauncherConfig:
    cluster: str
    task_definition: str
    subnets: tuple[str, ...]
    security_groups: tuple[str, ...]
    lifetime_seconds: int = 1800
    cap: int = HARD_CAP
    assign_public_ip: str = "ENABLED"
    container: str = "worker"
    module: str = "processing.v1_worker"
    max_empty_polls: int = 2
    # An unexplained reservation is replayed (same token, same payload) after this long, which
    # is longer than any RunTask call the adapter allows, and released after the second period.
    replay_after_seconds: float = 15
    release_after_seconds: float = 120
    # A worker that stops without claiming anything pauses launches briefly; several in a row
    # stop them until the next explicit enable, so a stuck queue cannot bill forever.
    idle_cooldown_seconds: float = 120
    idle_trip: int = 3
    # Do not start a worker that the session would stop almost at once.
    min_useful_seconds: float = 120
    # V2-live (#237): the persistent environment has no session end. The flag, the cap, the
    # reservations and the idle breaker still apply; only the end-of-session gate does not.
    always_on: bool = False

    @property
    def family(self):
        return family(self.task_definition)

    @property
    def slots(self):
        return max(0, min(self.cap, HARD_CAP))


def family(reference):
    return reference.rsplit("/", 1)[-1].split(":")[0]


def started_by_for(token):
    # ECS limits startedBy to 36 characters; "v1-u" marks an unattended start.
    return ("v1-u" + token)[:36]


def run_payload(config, token, deadline_epoch):
    name = started_by_for(token)
    return {
        "cluster": config.cluster,
        "taskDefinition": config.task_definition,
        "launchType": "FARGATE",
        "count": 1,
        "clientToken": token,
        "startedBy": name,
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": list(config.subnets),
                "securityGroups": list(config.security_groups),
                "assignPublicIp": config.assign_public_ip,
            }
        },
        "overrides": {
            "containerOverrides": [
                {
                    "name": config.container,
                    "command": [
                        "python",
                        "-m",
                        config.module,
                        "--deadline-epoch",
                        str(int(deadline_epoch)),
                        "--name",
                        name,
                        "--max-empty-polls",
                        str(config.max_empty_polls),
                    ],
                }
            ]
        },
    }


@dataclass
class Observation:
    """What ECS reports for this cluster's worker family, plus identities it forgot."""

    workers: dict
    missing: set


async def observe(ecs, config, known_arns=()):
    """Every worker task ECS knows, started by anyone. A failure aborts the tick (fail closed)."""
    arns = set(known_arns)
    for desired in ("RUNNING", "STOPPED"):
        # STOPPED here includes STOPPING, which still holds Fargate vCPU quota.
        arns.update(await ecs.list_tasks(desired))
    workers, missing = {}, set()
    ordered = sorted(arns)
    for offset in range(0, len(ordered), DESCRIBE_BATCH):
        batch = ordered[offset : offset + DESCRIBE_BATCH]
        reply = await ecs.describe_tasks(batch)
        for failure in reply.get("failures", []):
            if failure.get("reason") != "MISSING":
                raise RuntimeError("Task inventory contains an unresolved identity")
            missing.add(failure.get("arn"))
        for task in reply.get("tasks", []):
            if family(task["taskDefinitionArn"]) == config.family:
                workers[task["taskArn"]] = task
    return Observation(workers, missing)


def task_names(task):
    # The same names terminal_event binds, so one definition of "which worker is this".
    return stopped_task_names({"detail": {**task, "lastStatus": "STOPPED"}})


async def queued_backlog(session):
    """Attempts a worker could claim right now (the same set repair re-sends work for)."""
    return await session.scalar(
        select(func.count())
        .select_from(Job)
        .join(Attempt, Job.current_attempt_id == Attempt.id)
        .join(JobMessaging, JobMessaging.job_id == Job.id)
        .where(Job.deleted_at.is_(None), Job.status == "queued", Attempt.state == "queued")
    )


async def _claimed(session, task):
    names = task_names(task)
    if not names:
        return False
    found = await session.scalar(
        select(AttemptTask.attempt_id).where(AttemptTask.task_name.in_(names)).limit(1)
    )
    return found is not None


async def _reconcile(session, rows, obs, now):
    """Explain open reservations from ECS. Mutates rows; no network."""
    by_started = {t.get("startedBy"): t for t in obs.workers.values() if t.get("startedBy")}
    for row in rows:
        task = obs.workers.get(row.task_arn) if row.task_arn else None
        task = task or by_started.get(row.started_by)
        if task is not None:
            row.task_arn = task["taskArn"]
            if row.status == "reserved":
                row.status, row.launched_at = "launched", row.launched_at or now
            if task.get("lastStatus") == "STOPPED":
                row.status, row.settled_at = "stopped", now
                row.claimed = await _claimed(session, task)
        elif row.status == "launched" and row.task_arn in obs.missing and now >= row.deadline_at:
            # ECS forgot the task and its finite deadline has passed: it can only be gone.
            row.status, row.settled_at, row.claimed = "stopped", now, False


async def _idle_exits(session, control, limit):
    """Trailing run of workers that stopped without claiming, newest first."""
    query = (
        select(LaunchReservation.claimed, LaunchReservation.settled_at)
        .where(LaunchReservation.status == "stopped")
        .order_by(LaunchReservation.settled_at.desc())
        .limit(limit)
    )
    if control.enabled_at is not None:
        query = query.where(LaunchReservation.reserved_at >= control.enabled_at)
    run, newest = 0, None
    for claimed, settled in (await session.execute(query)).all():
        if claimed is not False:
            break
        run, newest = run + 1, newest or settled
    return run, newest


def _session_ended(control, now, config, margin=0.0):
    if config is not None and config.always_on:
        return False
    return control.session_end_at is None or (
        now + timedelta(seconds=margin) >= control.session_end_at
    )


def _gate(control, now, config, idle_run, idle_newest):
    if control is None or not control.enabled:
        return "disabled"
    if _session_ended(control, now, config, config.min_useful_seconds):
        return "session-ended"
    if idle_run >= config.idle_trip:
        return "idle-breaker"
    if idle_run and now < idle_newest + timedelta(seconds=config.idle_cooldown_seconds):
        return "idle-cooldown"
    return None


async def _reserve(factory, config, obs, visible, *, launching):
    """One serialized pass: reconcile, decide, and commit new reservations."""
    async with factory() as session, session.begin():
        await session.execute(insert(LauncherControl).values(id=1).on_conflict_do_nothing())
        control = await session.scalar(
            select(LauncherControl).where(LauncherControl.id == 1).with_for_update()
        )
        now = await lifecycle.db_now(session)
        rows = (
            await session.scalars(
                select(LaunchReservation)
                .where(LaunchReservation.status.in_(OPEN_STATES))
                .order_by(LaunchReservation.reserved_at)
                .with_for_update()
            )
        ).all()
        await _reconcile(session, rows, obs, now)
        backlog = await queued_backlog(session)
        idle_run, idle_newest = await _idle_exits(session, control, config.idle_trip)
        reason = _gate(control, now, config, idle_run, idle_newest)
        if not launching:
            reason = reason or "settle-only"
        demand = min(backlog, visible) if visible is not None else 0
        live = {a: t for a, t in obs.workers.items() if t.get("lastStatus") != "STOPPED"}

        def unexplained():
            return [
                r
                for r in rows
                if r.status in OPEN_STATES and not (r.task_arn and r.task_arn in live)
            ]

        resend, released = [], 0
        for row in unexplained():
            if row.status != "reserved":
                continue
            age = (now - row.reserved_at).total_seconds()
            if (
                reason is None
                and demand > 0
                and now < row.deadline_at
                and age >= config.replay_after_seconds
            ):
                resend.append(row.token)
            elif age >= config.release_after_seconds or now >= row.deadline_at:
                # Past any in-flight call and absent from ECS: it never started. A task that
                # surfaces later is still counted through the live inventory.
                row.status, row.settled_at = "released", now
                row.last_error = row.last_error or "unconfirmed"
                released += 1
        pending = unexplained()
        occupied = len(live) + len(pending)
        # A task that already holds an attempt cannot take another, so only unclaimed
        # workers (and slots still starting) offset demand.
        names = {arn: task_names(task) for arn, task in live.items()}
        wanted = set().union(*names.values()) if names else set()
        bound_names = set()
        if wanted:
            bound_names = set(
                await session.scalars(
                    select(AttemptTask.task_name).where(AttemptTask.task_name.in_(wanted))
                )
            )
        bound = sum(1 for found in names.values() if found & bound_names)
        idle = occupied - bound
        count = 0
        if reason is None:
            count = max(0, min(demand - idle, config.slots - occupied))
        created = []
        for _ in range(count):
            token = uuid4().hex
            deadline = now + timedelta(seconds=config.lifetime_seconds)
            if not config.always_on:
                deadline = min(deadline, control.session_end_at)
            session.add(
                LaunchReservation(
                    token=token,
                    started_by=started_by_for(token),
                    status="reserved",
                    payload=run_payload(config, token, deadline.timestamp()),
                    deadline_at=deadline,
                    reserved_at=now,
                )
            )
            created.append(token)
        return {
            "tokens": resend + created,
            "replayed": len(resend),
            "reserved": len(created),
            "released": released,
            "backlog": backlog,
            "visible": visible,
            "occupied": occupied + len(created),
            "idle_workers": idle,
            "ambiguous": sum(1 for r in pending if r.status == "reserved") + len(created),
            "reason": reason,
        }


async def _send(factory, ecs, token, config=None):
    """Send one reservation while holding the control row FOR SHARE.

    Disable takes the same row FOR UPDATE, so it cannot return while a send is in flight,
    and a send that starts afterwards sees the flag off and releases its own slot.
    """
    async with factory() as session, session.begin():
        control = await session.scalar(
            select(LauncherControl).where(LauncherControl.id == 1).with_for_update(read=True)
        )
        row = await session.scalar(
            select(LaunchReservation).where(LaunchReservation.token == token).with_for_update()
        )
        now = await lifecycle.db_now(session)
        if row is None or row.status != "reserved":
            return "skipped"
        if control is None or not control.enabled or _session_ended(control, now, config):
            row.status, row.settled_at, row.last_error = "released", now, "closed"
            return "closed"
        row.sent_at = now
        try:
            reply = await ecs.run_task(row.payload)
        except RunTaskRefused as error:
            row.status, row.settled_at, row.last_error = "released", now, str(error)[:120]
            return "refused"
        except Exception as error:
            # Lost response or timeout: the task may exist. The slot stays reserved and a
            # later pass resolves it by startedBy or by replaying the same token.
            row.last_error = type(error).__name__[:120]
            return "ambiguous"
        tasks = reply.get("tasks") or []
        if len(tasks) == 1 and tasks[0].get("taskArn"):
            row.status, row.task_arn, row.launched_at = "launched", tasks[0]["taskArn"], now
            return "launched"
        if not tasks and reply.get("failures"):
            reason = str(reply["failures"][0].get("reason", "failure"))[:60]
            row.status, row.settled_at, row.last_error = "released", now, "RunTask:" + reason
            return "refused"
        row.last_error = "UnexpectedReply"
        return "ambiguous"


async def tick(factory, ecs, queue, config, *, launching=True):
    """One launcher pass. ``launching=False`` only reconciles (used by close to settle)."""
    async with factory() as session:
        control = await session.get(LauncherControl, 1)
        open_rows = (
            await session.execute(
                select(LaunchReservation.task_arn).where(LaunchReservation.status.in_(OPEN_STATES))
            )
        ).all()
        backlog = await queued_backlog(session)
    enabled = control is not None and control.enabled
    if not open_rows and not (launching and enabled and backlog):
        # Nothing to reconcile and nothing to start: no ECS or SQS call at all.
        return {"outcome": "idle", "launched": 0, "backlog": backlog, "ambiguous": 0}
    obs = await observe(ecs, config, [arn for (arn,) in open_rows if arn])
    visible = None
    if launching and enabled and backlog:
        try:
            visible = await queue.visible()
        except Exception:
            visible = None  # An unreadable queue means no demand: fail closed.
    plan = await _reserve(factory, config, obs, visible, launching=launching)
    results = {"launched": 0, "refused": 0, "unconfirmed": 0, "closed": 0, "skipped": 0}
    for token in plan.pop("tokens"):
        outcome = await _send(factory, ecs, token, config)
        results["unconfirmed" if outcome == "ambiguous" else outcome] += 1
        if outcome in {"refused", "ambiguous"}:
            break  # ECS is unhealthy or refusing; the next tick reconciles by token.
    return {"outcome": "ran", **plan, **results}


async def settle(factory, ecs, config):
    """Reconcile ambiguous reservations without reserving or sending anything.

    Close calls this after disabling the launcher, until ``ambiguous`` reaches zero.
    """
    return await tick(factory, ecs, None, config, launching=False)


async def set_enabled(factory, enabled, *, session_end_epoch=None):
    """Flip the launcher flag. Returns once no send is in flight and none can start."""
    async with factory() as session, session.begin():
        await session.execute(insert(LauncherControl).values(id=1).on_conflict_do_nothing())
        control = await session.scalar(
            select(LauncherControl).where(LauncherControl.id == 1).with_for_update()
        )
        now = await lifecycle.db_now(session)
        if enabled:
            end = (
                None
                if session_end_epoch is None
                else datetime.fromtimestamp(session_end_epoch, UTC)
            )
            if end is None or end <= now:
                raise ValueError("A future session end is required to enable the launcher")
            control.enabled, control.enabled_at, control.session_end_at = True, now, end
        else:
            control.enabled = False
        control.updated_at = now
        return await _status(session, control)


async def _status(session, control):
    counts = dict(
        (
            await session.execute(
                select(LaunchReservation.status, func.count()).group_by(LaunchReservation.status)
            )
        ).all()
    )
    return {
        "enabled": bool(control and control.enabled),
        "session_end_at": control.session_end_at.isoformat()
        if control and control.session_end_at
        else None,
        "ambiguous": counts.get("reserved", 0),
        "launched": counts.get("launched", 0),
        "reservations": counts,
    }


async def status(factory):
    async with factory() as session:
        return await _status(session, await session.get(LauncherControl, 1))
