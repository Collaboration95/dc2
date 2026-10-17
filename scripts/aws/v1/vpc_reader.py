"""Read an owner's schema revision (or attempt counts) from inside the VPC, with no station.

Aurora is private and V1 has no bastion, so an operator laptop cannot open the database. The
cross-database harness (#63) already solved this by running a finite Fargate task in the VPC and
reading its result from CloudWatch Logs; this follows that pattern for the release code (#65)
and the session-close drain proof.

One read = one finite task: the owner's own deployed migration task definition with a command
override that runs `vpc_probe.py`. That task definition already carries the owner's migration
role (task secret reference), the RDS CA bundle and the network path, so the operator needs no
credential and no override carries a secret. The probe verifies TLS inside the task and prints
one tagged JSON line; this module parses it.

Every wait is bounded (Fargate start, Aurora resume, log delivery) and a task is never left
running: a timeout or error stops it first. Failures name an exception class, never a driver
message, because a driver message can echo the DSN.
"""

import base64
import json
import re
import time
import uuid
import zlib
from pathlib import Path

from scripts.aws.transport import OperationError, remaining
from scripts.aws.v1.hooks import validated_counts

SOURCE = "in-vpc-task"
PROBE = Path(__file__).with_name("vpc_probe.py")
MARKER = "DC2-VPC-READ"
CONTAINER = "migration"  # the migration task definitions' only container
# ECS caps the whole overrides block at 8192 characters.
MAX_SCRIPT = 6000
# The packed script has its base64 padding stripped: the transport refuses any string that holds
# "=" next to a credential-looking word, and padding makes that depend on the script's bytes.
WRAPPER = (
    "import base64,os,zlib;s=os.environ['DC2_SCRIPT'];"
    "exec(zlib.decompress(base64.b64decode(s+'='*(-len(s)%4))),{'__name__':'__main__'})"
)
ERROR_CLASS = re.compile(r"[A-Za-z0-9_.]{1,80}")


def ship():
    """The probe as an environment value plus the command that runs it."""
    packed = base64.b64encode(zlib.compress(PROBE.read_bytes(), 9)).decode().rstrip("=")
    if len(packed) > MAX_SCRIPT:
        raise OperationError("The in-VPC probe is too large for an ECS command override")
    return packed, ["python", "-c", WRAPPER]


def tagged(lines):
    """Payloads of the result lines; a malformed one is skipped, not trusted."""
    found = []
    for line in lines:
        if line.startswith(MARKER + " "):
            try:
                value = json.loads(line[len(MARKER) + 1 :])
            except ValueError:
                continue
            if isinstance(value, dict):
                found.append(value)
    return found


class VpcReader:
    """schema_revision(owner, deadline=...) and attempt counts, over finite in-VPC tasks."""

    source = SOURCE

    def __init__(
        self,
        config,
        transport,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        resume_seconds=150,
        start_seconds=180,
        poll_seconds=3,
        log_seconds=30,
    ):
        self.config, self.transport = config, transport
        self.clock, self.sleep = clock, sleep
        self.resume_seconds, self.start_seconds = resume_seconds, start_seconds
        self.poll_seconds, self.log_seconds = poll_seconds, log_seconds
        self.definitions = dict(config.get("migration_definitions") or {})
        self.reads, self.pending, self.streams = [], {}, {}

    # -- public hooks ------------------------------------------------------------------------
    def __call__(self, owner, *, deadline):
        return self.schema(owner, deadline=deadline)

    def schema(self, owner, *, deadline):
        result = self.collect(owner, "schema", deadline)
        revision = result.get("revision")
        if result.get("heads") != 1 or not isinstance(revision, str):
            raise OperationError("Exactly one Alembic head is required")
        return revision

    def attempt_counts(self, deadline):
        """Processing's attempt-state counts: the drain proof's reader (positional deadline)."""
        return validated_counts(self.collect("processing", "attempts", deadline).get("counts"))

    def prefetch(self, owners, *, deadline):
        """Start the schema reads of several owners at once; each is collected by schema().

        Fargate start dominates a read, so two owners read one after the other would double the
        clocked release. Only reads whose freshness does not matter between launch and collect
        (the release's opening snapshots) are started ahead.
        """
        for owner in owners:
            if (owner, "schema") not in self.pending:
                self.pending[(owner, "schema")] = self.launch(owner, "schema", deadline)

    def abandon(self):
        """Stop anything still running (a failed release must leave no task behind)."""
        for key in list(self.pending):
            self.stop(self.pending.pop(key)["arn"])

    def receipt(self):
        return {"schema_revision_source": SOURCE, "reads": list(self.reads)}

    # -- one finite task ---------------------------------------------------------------------
    def collect(self, owner, mode, deadline):
        entry = self.pending.pop((owner, mode), None) or self.launch(owner, mode, deadline)
        task = None
        try:
            task = self.wait(entry, deadline)
            result = self.result(entry, deadline)
        except BaseException:
            if task is None:  # a task seen STOPPED needs no stop request
                self.stop(entry["arn"])
            raise
        if not result or not result.get("ok"):
            raise OperationError("In-VPC read failed: " + self.failure(task, result))
        if result.get("mode") != mode or result.get("owner") != owner:
            raise OperationError("In-VPC read answered for a different owner or mode")
        tls = result.get("tls") or {}
        if tls.get("verified") is not True:
            raise OperationError("Database TLS was not verified inside the task")
        self.reads.append({
            "owner": owner, "mode": mode, "seconds": round(self.clock() - entry["started"], 1),
            "connect_attempts": result.get("connect_attempts"),
            "tls_protocol": tls.get("protocol"), "tls_verified": True,
        })
        return result

    def launch(self, owner, mode, deadline):
        definition = self.definitions.get(owner)
        network = (self.config.get("task_networks") or {}).get(owner + "_migration")
        if not definition or not network:
            raise OperationError(
                "No migration task definition is known for this owner; the stack outputs "
                "lack its MigrationTaskDefinitionArn, so the schema cannot be read in the VPC")
        packed, command = ship()
        token = uuid.uuid4().hex
        reply = self.transport.call(
            "ecs",
            "run-task",
            {
                "cluster": self.config["cluster"],
                "taskDefinition": definition,
                "launchType": "FARGATE",
                "count": 1,
                "clientToken": token,
                "startedBy": "dc2-vpc-read-" + token[:12],
                "networkConfiguration": {
                    "awsvpcConfiguration": {
                        "subnets": network["subnets"],
                        "securityGroups": network["security_groups"],
                        "assignPublicIp": network["assign_public_ip"],
                    }
                },
                "overrides": {"containerOverrides": [{
                    "name": CONTAINER,
                    "command": command,
                    "environment": [
                        {"name": "DC2_SCRIPT", "value": packed},
                        {"name": "DC2_OWNER", "value": owner},
                        {"name": "DC2_MODE", "value": mode},
                        {"name": "DC2_RESUME_SECONDS", "value": str(self.resume_seconds)},
                    ],
                }]},
            },
            deadline=deadline,
        )
        tasks = reply.get("tasks", [])
        if reply.get("failures") or len(tasks) != 1:
            raise OperationError("The in-VPC read task could not be launched (capacity or quota)")
        return {"arn": tasks[0]["taskArn"], "definition": definition, "started": self.clock()}

    def wait(self, entry, deadline):
        """Poll to STOPPED, bounded by Fargate start plus an Aurora resume plus slack."""
        give_up = entry["started"] + self.start_seconds + self.resume_seconds + 30
        while True:
            reply = self.transport.call(
                "ecs", "describe-tasks",
                {"cluster": self.config["cluster"], "tasks": [entry["arn"]]}, deadline=deadline)
            if reply.get("failures") or len(reply.get("tasks", [])) != 1:
                raise OperationError("In-VPC read task inventory unresolved")
            task = reply["tasks"][0]
            if task.get("taskDefinitionArn") != entry["definition"]:
                raise OperationError("In-VPC read ran a different task definition")
            if task.get("lastStatus") == "STOPPED":
                return task
            if self.clock() >= give_up:
                raise OperationError("In-VPC read task did not finish in time")
            self.sleep(min(self.poll_seconds, remaining(deadline, self.clock)))

    def result(self, entry, deadline):
        """The probe's tagged line. Logs trail the stop by a few seconds, so wait for them."""
        group, stream = self.stream(entry)
        end = self.clock() + self.log_seconds
        while True:
            try:
                found = tagged(self.lines(group, stream, deadline))
            except OperationError:
                found = []  # the log stream may not exist yet
            if found:
                return found[-1]
            if self.clock() >= end:
                return None
            self.sleep(min(2, remaining(deadline, self.clock)))

    def stream(self, entry):
        definition = entry["definition"]
        if definition not in self.streams:
            described = self.transport.call(
                "ecs", "describe-task-definition", {"taskDefinition": definition},
                deadline=self.clock() + 60)
            for container in described["taskDefinition"]["containerDefinitions"]:
                if container["name"] == CONTAINER:
                    options = container["logConfiguration"]["options"]
                    self.streams[definition] = (options["awslogs-group"],
                                                options["awslogs-stream-prefix"])
                    break
            else:
                raise OperationError("The migration task definition has no logging container")
        group, prefix = self.streams[definition]
        return group, f"{prefix}/{CONTAINER}/{entry['arn'].rsplit('/', 1)[-1]}"

    def lines(self, group, stream, deadline):
        lines, token = [], None
        for _ in range(20):
            request = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
            if token:
                request["nextToken"] = token
            reply = self.transport.call("logs", "get-log-events", request, deadline=deadline)
            lines += [event["message"] for event in reply.get("events", [])]
            following = reply.get("nextForwardToken")
            if not following or following == token:
                break
            token = following
        return lines

    def failure(self, task, result):
        """Why a read failed, from an exception class or the ECS stop code: never a message."""
        error = (result or {}).get("error")
        if isinstance(error, str) and ERROR_CLASS.fullmatch(error):
            return error
        codes = [c.get("exitCode") for c in task.get("containers", [])]
        return f"no result line (exit {codes}, {task.get('stopCode') or 'unknown stop code'})"

    def stop(self, arn):
        try:
            self.transport.call(
                "ecs", "stop-task",
                {"cluster": self.config["cluster"], "task": arn, "reason": "dc2 in-VPC read"},
                deadline=self.clock() + 30)
        except Exception:  # best effort: the caller is already failing with its own error
            pass
