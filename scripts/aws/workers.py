"""Manual finite batches, conservative paginated inventory, and warm drain."""

import time
import uuid

from scripts.aws.transport import OperationError, config_value

NONTERMINAL = {
    "PROVISIONING",
    "PENDING",
    "ACTIVATING",
    "RUNNING",
    "DEACTIVATING",
    "STOPPING",
    "DEPROVISIONING",
}
TERMINAL_OUTCOMES = {"succeeded", "failed", "cancelled", "abandoned"}


def family(reference):
    return reference.rsplit("/", 1)[-1].split(":")[0]


def describe_tasks(config, transport, arns, *, deadline):
    found = {}
    arns = list(dict.fromkeys(arns))
    for offset in range(0, len(arns), 100):
        selected = arns[offset : offset + 100]
        result = transport.call(
            "ecs",
            "describe-tasks",
            {"cluster": config_value(config, "cluster"), "tasks": selected},
            deadline=deadline,
        )
        if result.get("failures"):
            raise OperationError("Task inventory contains unresolved identities")
        for task in result.get("tasks", []):
            if task.get("lastStatus") not in NONTERMINAL | {"STOPPED"}:
                raise OperationError("Unknown task state")
            found[task["taskArn"]] = task
        if not set(selected) <= found.keys():
            raise OperationError("Task missing from describe; absence is not STOPPED")
    return found


def inventory(config, transport, *, deadline, known=()):
    """Dedicated environment cluster: include every family and every deployment.

    desiredStatus STOPPED includes STOPPING; RUNNING alone cannot prove closure.
    Describe acknowledged requests independently of eventually-consistent lists.
    """
    arns = set(known)
    for desired in ("RUNNING", "STOPPED"):
        token = None
        seen = set()
        while True:
            payload = {"cluster": config_value(config, "cluster"), "desiredStatus": desired}
            if token:
                payload["nextToken"] = token
            result = transport.call("ecs", "list-tasks", payload, deadline=deadline)
            arns.update(result.get("taskArns", []))
            token = result.get("nextToken")
            if not token:
                break
            if token in seen:
                raise OperationError("Repeated inventory pagination token")
            seen.add(token)
    return describe_tasks(config, transport, sorted(arns), deadline=deadline)


def worker_inventory(config, transport, state, *, deadline):
    launches = state["launches"]
    known = [r["task"] for r in launches.values() if r.get("task")]
    tasks = inventory(config, transport, deadline=deadline, known=known)
    worker_family = family(config_value(config, "task_definitions")["worker"])
    workers = {
        arn: task
        for arn, task in tasks.items()
        if family(task["taskDefinitionArn"]) == worker_family
    }
    for record in launches.values():
        arn = record.get("task")
        if arn and tasks[arn]["lastStatus"] == "STOPPED":
            record["status"] = "stopped"
    occupied = {arn for arn, task in workers.items() if task["lastStatus"] != "STOPPED"}
    # A listed task associated with a request consumes its slot only once.
    unresolved = sum(
        1 for r in launches.values() if r["status"] != "stopped" and r.get("task") not in occupied
    )
    return workers, len(occupied) + unresolved


def _launch_response(journal, state, record, response):
    tasks = response.get("tasks", [])
    if len(tasks) != 1 or response.get("failures"):
        record["status"] = "uncertain"
        journal.save(state)
        raise OperationError("Partial or failed launch remains reserved")
    task = tasks[0]
    if not task.get("taskArn"):
        raise OperationError("Launch missing task identity; reservation retained")
    record.update(task=task["taskArn"], status="acknowledged")
    journal.save(state)
    return task["taskArn"]


def start(
    config,
    transport,
    journal,
    *,
    count,
    deadline,
    prewarm=False,
    clock=time.time,
    token_factory=lambda: uuid.uuid4().hex,
):
    """All callers (operator/smoke/release) must use this designated journal."""
    journal.check_context(config)
    with journal.locked() as state:
        return _start_locked(
            config,
            transport,
            journal,
            state,
            count=count,
            deadline=deadline,
            prewarm=prewarm,
            clock=clock,
            token_factory=token_factory,
        )


def _start_locked(
    config,
    transport,
    journal,
    state,
    *,
    count,
    deadline,
    prewarm=False,
    clock=time.time,
    token_factory=lambda: uuid.uuid4().hex,
    definition=None,
    end_epoch=None,
):
    """Private primitive: caller MUST already hold the station journal lock."""
    journal.check_context(config)
    pending = state.get("pending_release")
    release_launch = (
        pending
        and pending["owner"] == "processing"
        and definition is not None
        and definition
        in {pending["candidate_definitions"]["worker"], pending["prior_definitions"]["worker"]}
    )
    if (state.get("paused") or pending) and not release_launch:
        raise OperationError("Launches paused")
    maximum = config_value(config, "max_worker_tasks", 3)
    if not 1 <= count <= maximum <= 3:
        raise OperationError("Batch/cap must be 1..3")
    _, occupied = worker_inventory(config, transport, state, deadline=deadline)
    journal.save(state)
    if occupied + count > maximum:
        raise OperationError("Worker task/reservation cap reached")
    lifetime = config_value(config, "worker_lifetime_seconds")
    session_end = config_value(config, "session_end_epoch")
    if session_end is None:
        from datetime import datetime

        session_end = datetime.fromisoformat(
            config_value(config, "session_end_utc").replace("Z", "+00:00")
        ).timestamp()
    now = clock()
    if not isinstance(lifetime, int) or not 1 <= lifetime <= 3600 or session_end <= now:
        raise OperationError("Finite approved worker/session deadline required")
    task_end = min(now + lifetime, session_end, end_epoch or session_end)
    tasks = []
    for _ in range(count):
        token = token_factory()
        rq_name = "aws-" + token
        command = [
            "python",
            "-m",
            "processing.worker",
            "--cloud-deadline",
            str(task_end),
            "--name",
            rq_name,
        ]
        if not prewarm:
            command.append("--burst")
        payload = {
            "cluster": config_value(config, "cluster"),
            "taskDefinition": definition
            or state.get("worker_definition")
            or config_value(config, "task_definitions")["worker"],
            "launchType": "FARGATE",
            "count": 1,
            "clientToken": token,
            "startedBy": rq_name[:36],
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": config_value(config, "network")["subnets"],
                    "securityGroups": config_value(config, "network")["security_groups"],
                    "assignPublicIp": config_value(config, "network")["assign_public_ip"],
                }
            },
            "overrides": {"containerOverrides": [{"name": "worker", "command": command}]},
        }
        record = {
            "payload": payload,
            "rq_name": rq_name,
            "status": "reserved",
            "created": now,
            "replay_before": min(now + 3600, task_end),
        }
        if token in state["launches"]:
            raise OperationError("Launch token already exists")
        state["launches"][token] = record
        journal.save(state)  # Intent/reservation precedes RunTask, including lost response.
        try:
            response = transport.call("ecs", "run-task", payload, deadline=deadline)
        except Exception:
            record["status"] = "uncertain"
            journal.save(state)
            raise OperationError("RunTask response uncertain; reservation retained") from None
        tasks.append(_launch_response(journal, state, record, response))
    return tasks


def replay(config, transport, journal, token, *, deadline, clock=time.time):
    journal.check_context(config)
    with journal.locked() as state:
        record = state["launches"][token]
        if (
            state.get("paused")
            or record["status"] == "stopped"
            or clock() >= record["replay_before"]
        ):
            raise OperationError("Paused/expired token cannot be replayed; reconcile explicitly")
        # Never rebuild from changed config: ECS idempotency requires identical payload.
        return _launch_response(
            journal,
            state,
            record,
            transport.call("ecs", "run-task", record["payload"], deadline=deadline),
        )


def drain(
    config,
    transport,
    journal,
    state,
    *,
    observe,
    warm_shutdown,
    deadline,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Observe hooks read SQL outcomes + fresh RQ claims, never infer from Redis absence.

    observe(task,rq_name) -> fresh, claims_stopped, claims(list of current/last/racing
    IDs), outcomes(dict ID->terminal status). warm_shutdown -> acknowledged bool.
    No repeat signal after an uncertain acknowledgement. Caller holds station lock.
    """
    journal.check_context(config)
    workers, _ = worker_inventory(config, transport, state, deadline=deadline)
    records = {r.get("task"): r for r in state["launches"].values() if r.get("task")}
    end = min(deadline - 10, clock() + 300)
    for arn, task in workers.items():
        record = records.get(arn)
        if task["lastStatus"] == "STOPPED":
            if record and (
                record.get("drain") == "interrupted"
                or record.get("warm_sent")
                and record.get("drain") != "complete"
            ):
                raise OperationError(
                    "Previous interrupted/unacknowledged drain needs operator disposition"
                )
            continue
        if not record:
            raise OperationError("Uncorrelated worker cannot be safely drained")
        observed = observe(arn, record["rq_name"])
        if not observed.get("fresh"):
            raise OperationError("Stale worker registration blocks drain")
        claims = set(record.get("claims", [])) | set(observed["claims"])
        record["claims"] = sorted(claims)
        if not record.get("warm_sent"):
            record["warm_sent"] = True
            record["warm_ack"] = False
            journal.save(state)  # Lost ack must never result in a cold second signal.
            record["warm_ack"] = warm_shutdown(arn, record["rq_name"]) is True
            journal.save(state)
        while clock() < end:
            observed = observe(arn, record["rq_name"])
            claims.update(observed.get("claims", []))
            record["claims"] = sorted(claims)
            journal.save(state)
            current = describe_tasks(config, transport, [arn], deadline=deadline)[arn]
            complete = (
                observed.get("fresh")
                and observed.get("claims_stopped")
                and all(observed.get("outcomes", {}).get(i) in TERMINAL_OUTCOMES for i in claims)
            )
            if current["lastStatus"] == "STOPPED":
                if not complete or not record["warm_ack"]:
                    raise OperationError("Stopped task lacks acknowledged drain/terminal outcomes")
                record["status"] = "stopped"
                record["drain"] = "complete"
                journal.save(state)
                break
            sleep(min(1, max(0, end - clock())))
        else:
            record["drain"] = "interrupted"
            journal.save(state)
            # State/recovery stays alive; SQL recovery will record actual abandoned work.
            transport.call(
                "ecs",
                "stop-task",
                {
                    "cluster": config_value(config, "cluster"),
                    "task": arn,
                    "reason": "bounded-drain-timeout",
                },
                deadline=deadline,
            )
            force_end = min(deadline, clock() + 120)
            while clock() < force_end:
                current = describe_tasks(config, transport, [arn], deadline=force_end)[arn]
                if current["lastStatus"] == "STOPPED":
                    record["forced_task_stopped"] = True
                    journal.save(state)
                    break
                sleep(min(1, max(0, force_end - clock())))
            raise OperationError("Warm drain timed out; forced stop is not successful drain")
    return {"status": "complete", "tasks": sorted(workers)}


def resume_launches(config, transport, journal, *, deadline):
    """Explicit operator action after a successful release/restore, never auto-resume."""
    journal.check_context(config)
    with journal.locked() as state:
        if state.get("session") != "open" or state.get("pending_release"):
            raise OperationError("Open session without pending owner intent required")
        worker_inventory(config, transport, state, deadline=deadline)
        if any(
            r["status"] in {"reserved", "uncertain"}
            or r.get("warm_sent")
            and r.get("drain") != "complete"
            for r in state["launches"].values()
        ):
            raise OperationError("Unresolved launch/drain requires disposition")
        state["paused"] = False
        journal.save(state)
