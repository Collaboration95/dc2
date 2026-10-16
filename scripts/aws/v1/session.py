"""Booked V1 sessions and finite batches through an injected, bounded adapter.

There is no SDK, credential discovery or live transport in this module. The old
AWS2 transport remains unchanged. One private Journal is the designated operator
station; it is not a distributed lock. Every launcher must share that station.
"""

import time
import uuid

from scripts.aws.transport import OperationError, remaining, safe_record
from scripts.aws.workers import worker_inventory


class Session:
    def __init__(self, config, transport, journal, *, clock=time.monotonic, sleep=time.sleep):
        self.config, self.transport, self.journal = config, transport, journal
        self.clock, self.sleep = clock, sleep
        journal.check_context(config)
        functions = config.get("functions", {})
        if not functions or any(type(n) is not int or not 1 <= n <= 20 for n in functions.values()):
            raise OperationError("Explicit bounded function concurrency (1..20) required")
        if not set(config.get("intake_functions", [])) <= functions.keys():
            raise OperationError("Intake function must belong to this session")
        if not config.get("intake_functions"):
            raise OperationError("Explicit intake function required")

    def call(self, service, operation, payload, deadline):
        remaining(deadline, self.clock)
        return self.transport.call(service, operation, payload, deadline=deadline)

    def _step(self, state, name, action):
        # Retry idempotent control settings after lost acknowledgements. Persist
        # intent first; never mark a partially opened/closed session successful.
        state["session_step"] = name
        self.journal.save(state)
        action()
        state.setdefault("session_completed", []).append(name)
        self.journal.save(state)

    def _concurrency(self, name, value, deadline):
        self.call(
            "lambda",
            "put-function-concurrency",
            {
                "FunctionName": name,
                "ReservedConcurrentExecutions": value,
            },
            deadline,
        )
        result = self.call("lambda", "get-function-concurrency", {"FunctionName": name}, deadline)
        if result.get("ReservedConcurrentExecutions") != value:
            raise OperationError("Function concurrency was not confirmed")

    def _mapping(self, identity, enabled, deadline):
        self.call(
            "lambda",
            "update-event-source-mapping",
            {
                "UUID": identity,
                "Enabled": enabled,
            },
            deadline,
        )
        expected = "Enabled" if enabled else "Disabled"
        while True:
            result = self.call("lambda", "get-event-source-mapping", {"UUID": identity}, deadline)
            if result.get("State") == expected:
                return
            if result.get("State") not in {"Creating", "Enabling", "Disabling", "Updating"}:
                raise OperationError("Unexpected mapping state")
            self.sleep(min(0.2, remaining(deadline, self.clock)))

    def _schedule(self, name, enabled, deadline):
        self.call("events", "enable-rule" if enabled else "disable-rule", {"Name": name}, deadline)
        result = self.call("events", "describe-rule", {"Name": name}, deadline)
        if result.get("State") != ("ENABLED" if enabled else "DISABLED"):
            raise OperationError("Repair schedule state was not confirmed")

    def open(self, *, ready, repair, deadline):
        """Open only after owning SQL readiness and bounded recovery succeed.

        ready/repair are deadline-aware owner hooks. They must close their SQL
        connections. No worker starts implicitly, including when queues are full.
        """
        with self.journal.locked() as state:
            if state.get("pending_release") or state.get("session") not in {"closed", "opening"}:
                raise OperationError("Closed session without release intent required")
            state.update(session="opening", paused=True, session_completed=[])
            self.journal.save(state)
            # Quiesce intake first even on a retry after partial failure.
            for name in self.config["intake_functions"]:
                self._step(
                    state, "quiesce:" + name, lambda n=name: self._concurrency(n, 0, deadline)
                )
            for name, value in self.config["functions"].items():
                if name not in self.config["intake_functions"]:
                    self._step(
                        state,
                        "restore:" + name,
                        lambda n=name, v=value: self._concurrency(n, v, deadline),
                    )
            self._step(state, "sql-ready", lambda: self._require(ready(deadline=deadline)))
            self._step(state, "repair", lambda: self._require(repair(deadline=deadline)))
            for identity in self.config.get("mappings", []):
                self._step(
                    state, "enable:" + identity, lambda i=identity: self._mapping(i, True, deadline)
                )
            for name in self.config.get("schedules", []):
                self._step(
                    state, "enable:" + name, lambda n=name: self._schedule(n, True, deadline)
                )
            for name in self.config["intake_functions"]:
                self._step(
                    state,
                    "restore:" + name,
                    lambda n=name: self._concurrency(n, self.config["functions"][n], deadline),
                )
            state.update(session="open", paused=False, session_step="complete")
            self.journal.save(state)
            return {"session": "open", "worker_starts": 0}

    @staticmethod
    def _require(result):
        if result is not True:
            raise OperationError("Owner readiness/repair hook did not confirm success")

    def close(self, *, drain, outcomes, deadline):
        """Retain queued messages/data. Disable every wake source even if drain fails.

        drain must observe ECS STOPPED and owning SQL terminal/fenced outcomes;
        a forced stop alone is not a successful drain. Unresolved reservations
        prevent a successful close. No purge, DB stop/delete or object deletion.
        """
        with self.journal.locked() as state:
            state.update(session="closing", paused=True, session_completed=[])
            self.journal.save(state)
            failed = []

            def attempt(name, action):
                try:
                    self._step(state, name, action)
                except Exception:
                    failed.append(name)
                    state["session_failures"] = list(failed)
                    self.journal.save(state)

            for name in self.config["intake_functions"]:
                attempt("quiesce:" + name, lambda n=name: self._concurrency(n, 0, deadline))
            if not failed:
                attempt("drain", lambda: self._require(drain(deadline=deadline)))
                attempt("outcomes", lambda: self._outcomes(state, outcomes, deadline))
                attempt("inventory", lambda: self._empty(state, deadline))
            for identity in self.config.get("mappings", []):
                attempt("disable:" + identity, lambda i=identity: self._mapping(i, False, deadline))
            for name in self.config.get("schedules", []):
                attempt("disable:" + name, lambda n=name: self._schedule(n, False, deadline))
            for name in self.config["functions"]:
                attempt("zero:" + name, lambda n=name: self._concurrency(n, 0, deadline))
            state["session_failures"] = failed
            if failed:
                self.journal.save(state)
                raise OperationError("Partial close; retry from retained journal")
            state.update(session="closed", session_step="complete")
            self.journal.save(state)
            return {
                "session": "closed",
                "queued_work": "retained",
                "database_pause": "NOT_OBSERVED",
                "billing": "PENDING; storage, maintenance and requests may still incur charges",
            }

    def _outcomes(self, state, hook, deadline):
        counts = hook(deadline=deadline)
        if (
            not isinstance(counts, dict)
            or not counts
            or any(
                k not in {"queued", "succeeded", "failed", "cancelled", "abandoned"}
                or type(v) is not int
                or v < 0
                for k, v in counts.items()
            )
        ):
            raise OperationError("Safe SQL outcome counts required")
        state["close_outcomes"] = counts
        self.journal.save(state)

    def _empty(self, state, deadline):
        _, occupied = worker_inventory(self.config, self.transport, state, deadline=deadline)
        self.journal.save(state)
        if occupied:
            raise OperationError("Workers or ambiguous reservations remain")

    def batch(self, *, count, deadline, epoch=time.time, token_factory=lambda: uuid.uuid4().hex):
        """Reserve before RunTask, count ambiguity, one finite SQS worker/task."""
        with self.journal.locked() as state:
            if (
                state.get("session") != "open"
                or state.get("paused")
                or state.get("pending_release")
            ):
                raise OperationError("Open unpaused session required")
            maximum = self.config.get("max_worker_tasks", 3)
            if type(count) is not int or type(maximum) is not int or not 1 <= count <= maximum <= 3:
                raise OperationError("Batch/cap must be 1..3")
            _, occupied = worker_inventory(self.config, self.transport, state, deadline=deadline)
            self.journal.save(state)
            if occupied + count > maximum:
                raise OperationError("Worker/reservation cap reached")
            now = epoch()
            lifetime = self.config["worker_lifetime_seconds"]
            end = self.config["session_end_epoch"]
            if type(lifetime) is not int or not 1 <= lifetime <= 3600 or end <= now:
                raise OperationError("Finite live worker/session deadline required")
            stop_at = min(now + lifetime, end)
            tasks = []
            for _ in range(count):
                token = token_factory()
                if not isinstance(token, str) or not token or token in state["launches"]:
                    raise OperationError("Unique launch token required")
                payload = {
                    "cluster": self.config["cluster"],
                    "taskDefinition": self.config["task_definitions"]["worker"],
                    "launchType": "FARGATE",
                    "count": 1,
                    "clientToken": token,
                    "startedBy": ("v1-" + token)[:36],
                    "networkConfiguration": {
                        "awsvpcConfiguration": {
                            "subnets": self.config["network"]["subnets"],
                            "securityGroups": self.config["network"]["security_groups"],
                            "assignPublicIp": self.config["network"]["assign_public_ip"],
                        }
                    },
                    "overrides": {
                        "containerOverrides": [
                            {
                                "name": "worker",
                                "command": [
                                    "python",
                                    "-m",
                                    self.config.get("worker_module", "processing.v1_worker"),
                                    "--deadline-epoch",
                                    str(stop_at),
                                    "--name",
                                    ("v1-" + token)[:36],
                                    "--max-empty-polls",
                                    "2",
                                ],
                            }
                        ]
                    },
                }
                safe_record(payload)
                record = {
                    "status": "reserved",
                    "payload": payload,
                    "created": now,
                    "replay_before": stop_at,
                }
                state["launches"][token] = record
                self.journal.save(state)
                try:
                    response = self.call("ecs", "run-task", payload, deadline)
                    launched = response.get("tasks", [])
                    if (
                        response.get("failures")
                        or len(launched) != 1
                        or not launched[0].get("taskArn")
                    ):
                        raise OperationError("Uncertain launch")
                    record.update(status="acknowledged", task=launched[0]["taskArn"])
                    tasks.append(record["task"])
                except Exception:
                    record["status"] = "uncertain"
                    self.journal.save(state)
                    raise OperationError("Launch uncertain; reserved slot retained") from None
                self.journal.save(state)
            return tasks

    def replay(self, token, *, deadline, epoch=time.time):
        """Explicit retry of identical RunTask intent within its finite lifetime.

        Never free a lost-response slot by time alone. Expired tokens need ECS
        inventory/operator disposition; do not issue a new token to evade the cap.
        """
        with self.journal.locked() as state:
            if (
                state.get("session") != "open"
                or state.get("paused")
                or state.get("pending_release")
            ):
                raise OperationError("Open unpaused session required")
            record = state["launches"].get(token)
            if not record or record["status"] == "stopped" or epoch() >= record["replay_before"]:
                raise OperationError("Unknown/stopped/expired launch token requires disposition")
            try:
                response = self.call("ecs", "run-task", record["payload"], deadline)
                launched = response.get("tasks", [])
                if response.get("failures") or len(launched) != 1 or not launched[0].get("taskArn"):
                    raise OperationError("Uncertain launch")
                record.update(status="acknowledged", task=launched[0]["taskArn"])
            except Exception:
                record["status"] = "uncertain"
                self.journal.save(state)
                raise OperationError("Replay uncertain; reserved slot retained") from None
            self.journal.save(state)
            return record["task"]
