"""Finite Fargate tasks for the harnesses: launch once, watch, always stop, read the result.

Two harnesses run code inside the VPC: the cross-database denial probe (#63) and the latency
generator (#66). Both ship a small standard-library script to the existing worker image as a
`python -c` command, so no new image is built or pushed. The script prints one tagged JSON
line; the harness reads it back from the task's CloudWatch log stream.

A task is never left running: a timeout, an error or a closed session window stops it first,
and the task's launch token is recorded before RunTask so a rerun resumes rather than doubles.
"""

import base64
import json
import uuid
import zlib
from pathlib import Path

from scripts.aws.v1.proof.core import ProofError, parse_time, seconds_between

# ECS caps the whole overrides block at 8192 characters; leave room for env and the wrapper.
MAX_SCRIPT = 6000
WRAPPER = ("import base64,os,zlib;exec(zlib.decompress(base64.b64decode(os.environ['DC2_SCRIPT'])),"
           "{'__name__':'__main__'})")
POLL_SECONDS = 10


def ship(path):
    """The script as an environment value plus the command that runs it."""
    source = Path(path).read_bytes()
    packed = base64.b64encode(zlib.compress(source, 9)).decode()
    if len(packed) > MAX_SCRIPT:
        raise ProofError("The container script is too large for an ECS command override")
    return packed, ["python", "-c", WRAPPER]


def network(config):
    net = config["network"]
    return {"awsvpcConfiguration": {
        "subnets": net["subnets"], "securityGroups": net["security_groups"],
        "assignPublicIp": net["assign_public_ip"]}}


def describe(ctx, arn):
    reply = ctx.aws.call("ecs", "describe-tasks",
                         {"cluster": ctx.config["cluster"], "tasks": [arn]},
                         deadline=ctx.deadline(60))
    if reply.get("failures") or len(reply.get("tasks", [])) != 1:
        raise ProofError("The task could not be described; absence is not STOPPED")
    return reply["tasks"][0]


def stop(ctx, arn, reason):
    try:
        ctx.aws.call("ecs", "stop-task",
                     {"cluster": ctx.config["cluster"], "task": arn, "reason": reason[:200]},
                     deadline=ctx.deadline(60))
    except Exception:  # best effort: the caller is already failing and re-raises its own error
        pass


def timings(task):
    """Pull-to-stop is what Fargate bills; keep every stamp ECS reports, as ISO strings."""
    keys = ("createdAt", "pullStartedAt", "pullStoppedAt", "startedAt", "stoppedAt")
    seen = {k: str(task[k]) for k in keys if task.get(k)}
    billed = seconds_between(seen.get("pullStartedAt") or seen.get("createdAt"),
                             seen.get("stoppedAt"))
    return {**seen, "billed_seconds": billed}


def summary(task):
    return {
        "cpu": task.get("cpu"), "memory": task.get("memory"),
        "stop_code": task.get("stopCode"),
        "stopped_reason": (task.get("stoppedReason") or "")[:120],
        "exit_codes": [c.get("exitCode") for c in task.get("containers", [])],
        "image_digests": sorted({c.get("imageDigest", "") for c in task.get("containers", [])}),
        "task_definition": task.get("taskDefinitionArn"), **timings(task),
    }


def run(ctx, intent, save, *, label, definition, overrides, timeout, session="active",
        checkpoint=None):
    """Launch one finite task (once per intent), wait for STOPPED, return its description.

    `intent` is the step's persisted dict and `save` writes it, so the token and task ARN
    survive a crash. `checkpoint(kind)` re-asserts the session each poll.
    """
    if not intent.get("token"):
        intent["token"] = uuid.uuid4().hex
        save()
    arn = intent.get("task")
    if not arn:
        reply = ctx.aws.call("ecs", "run-task", {
            "cluster": ctx.config["cluster"], "taskDefinition": definition,
            "launchType": "FARGATE", "count": 1, "clientToken": intent["token"],
            "startedBy": f"dc2-proof-{label}"[:36], "networkConfiguration": network(ctx.config),
            "overrides": overrides}, deadline=ctx.deadline(60))
        tasks = reply.get("tasks", [])
        if reply.get("failures") or len(tasks) != 1:
            raise ProofError(f"The {label} task could not be launched (capacity or quota)")
        arn = intent["task"] = tasks[0]["taskArn"]
        save()
    end = ctx.clock() + timeout
    try:
        while True:
            task = describe(ctx, arn)
            if task.get("lastStatus") == "STOPPED":
                return task
            if ctx.clock() >= end:
                raise ProofError(f"The {label} task did not finish within {timeout} seconds")
            if checkpoint:
                checkpoint(session)
            ctx.sleep(POLL_SECONDS)
    except BaseException:
        stop(ctx, arn, f"dc2 proof {label} aborted")
        raise


def log_stream(definition_reply, container, arn):
    """Group and stream the awslogs driver wrote for this task."""
    for entry in definition_reply["taskDefinition"]["containerDefinitions"]:
        if entry["name"] == container:
            options = entry["logConfiguration"]["options"]
            return options["awslogs-group"], f"{options['awslogs-stream-prefix']}/{container}/" + \
                arn.rsplit("/", 1)[-1]
    raise ProofError("The task definition has no such container for logs")


def read_lines(ctx, group, stream):
    """Every message in the stream, in order (bounded: a finite task writes little)."""
    lines, token = [], None
    for _ in range(50):
        request = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
        if token:
            request["nextToken"] = token
        reply = ctx.aws.call("logs", "get-log-events", request, deadline=ctx.deadline(60))
        lines += [e["message"] for e in reply.get("events", [])]
        following = reply.get("nextForwardToken")
        if not following or following == token:
            break
        token = following
    return lines


def tagged(lines, marker):
    """Payloads of the lines that start with `marker `; malformed ones are skipped."""
    found = []
    for line in lines:
        if line.startswith(marker + " "):
            try:
                found.append(json.loads(line[len(marker) + 1:]))
            except ValueError:
                continue
    return found


def result(ctx, definition, container, arn, marker, *, wait=30):
    """The one tagged JSON line the task printed. Logs trail the stop by a few seconds."""
    reply = ctx.aws.call("ecs", "describe-task-definition", {"taskDefinition": definition},
                         deadline=ctx.deadline(60))
    group, stream = log_stream(reply, container, arn)
    end = ctx.clock() + wait
    while True:
        found = tagged(read_lines(ctx, group, stream), marker)
        if found or ctx.clock() >= end:
            return found[-1] if found else None
        ctx.sleep(5)


def peak_overlap(tasks):
    """Most tasks alive at once, from each task's own pull-start/stop stamps (not polling)."""
    edges = []
    for task in tasks:
        start = task.get("pullStartedAt") or task.get("createdAt")
        end = task.get("stoppedAt")
        if start and end:
            edges += [(parse_time(start), 1), (parse_time(end), -1)]
    live = peak = 0
    for _, delta in sorted(edges, key=lambda e: (e[0], e[1])):  # a stop frees before a start
        live += delta
        peak = max(peak, live)
    return peak


def wait_until(ctx, check, *, timeout, interval, checkpoint=None, session="active"):
    """Poll check() -> (done, value); bounded by the harness clock, session re-asserted."""
    end = ctx.clock() + timeout
    while True:
        done, value = check()
        if done:
            return value
        if ctx.clock() >= end:
            raise ProofError("Timed out waiting for the expected state")
        if checkpoint:
            checkpoint(session)
        ctx.sleep(interval)

