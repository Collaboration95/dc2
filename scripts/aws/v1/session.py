"""Booked V1 sessions and finite batches through an injected, bounded adapter.

There is no SDK, credential discovery or live transport in this module. The old
AWS2 transport remains unchanged. One private Journal is the designated operator
station; it is not a distributed lock. Every launcher must share that station.

Concurrency model: the template reserves nothing (the account limit of 10 forbids any
reservation) and is closed through disabled mappings/rules and a zero Gateway throttle,
so the default zero_reservation policy "off" never calls the Lambda concurrency APIs.
Older configurations may keep "required"/"best-effort" zero reservations. A function
configured with an int is reserved at that value, which Lambda only allows
while the account keeps MINIMUM_UNRESERVED executions free (checked before any change);
one configured with None is unreserved while open, the only option under a small
account limit. Close always writes 0, which Lambda permits whatever the account limit.
The optional Gateway stage throttle is a second, independent intake gate.
"""

import time
import uuid

from scripts.aws.transport import OperationError, remaining, safe_record
from scripts.aws.workers import worker_inventory

MINIMUM_UNRESERVED = 100
ZERO_POLICIES = {"required", "best-effort", "off"}


def _bounded(value):
    return value is None or (type(value) is int and 1 <= value <= 20)


NO_RETRY = {"drain", "outcomes", "inventory"}
# Sized for an Aurora resume (30 to 60 s) plus one 70 s Lambda invocation that timed out
# waiting for it.
CLOSE_RETRY_SECONDS = 240


def _reason(error):
    """What a failed step says, without anything a payload could carry: the curated message of
    an OperationError, otherwise the exception's type alone."""
    if isinstance(error, OperationError):
        return f"OperationError: {str(error)[:200]}"
    return type(error).__name__


class Session:
    # How long a close may spend retrying its failed steps, in total, and how often. Off by
    # default so a library caller or a test sees a failure at once; the CLI turns it on
    # (CLOSE_RETRY_SECONDS) because a live close can meet a database that is still resuming.
    close_retry_seconds = 0
    close_retry_interval = 10

    def __init__(self, config, transport, journal, *, clock=time.monotonic, sleep=time.sleep):
        self.config, self.transport, self.journal = config, transport, journal
        self.clock, self.sleep = clock, sleep
        journal.check_context(config)
        functions = config.get("functions", {})
        if not functions or not all(_bounded(n) for n in functions.values()):
            raise OperationError("Explicit bounded function concurrency (1..20 or None) required")
        policy = config.get("zero_reservation", "required")
        if policy not in ZERO_POLICIES:
            raise OperationError("Unknown zero-reservation policy")
        gateway = config.get("gateway")
        if gateway is not None:
            limits = gateway.get("open", {}) if isinstance(gateway, dict) else {}
            if (
                not isinstance(gateway, dict)
                or not gateway.get("api_id")
                or not gateway.get("stage")
                or not all(type(limits.get(k)) is int and limits[k] > 0 for k in ("rate", "burst"))
            ):
                raise OperationError("Edge gate needs api_id, stage and positive open limits")
        if policy != "required" and gateway is None:
            raise OperationError("Without zero reservations the edge throttle gate is needed")
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
        """value None removes the reservation; the observed state must match either way."""
        if value is None and self.config.get("zero_reservation") == "off":
            return  # No reservation exists to remove; the account limit forbids creating one.
        if value is None:
            self.call("lambda", "delete-function-concurrency", {"FunctionName": name}, deadline)
        else:
            self.call(
                "lambda",
                "put-function-concurrency",
                {"FunctionName": name, "ReservedConcurrentExecutions": value},
                deadline,
            )
        result = self.call("lambda", "get-function-concurrency", {"FunctionName": name}, deadline)
        if result.get("ReservedConcurrentExecutions") != value:
            raise OperationError("Function concurrency was not confirmed")

    def _zero(self, name, deadline, warnings):
        """Quiesce one function; best-effort records a refusal, off never calls Lambda."""
        policy = self.config.get("zero_reservation", "required")
        if policy == "off":
            return
        try:
            self._concurrency(name, 0, deadline)
        except OperationError:
            if self.config.get("zero_reservation", "required") != "best-effort":
                raise
            warnings.append("zero-reservation-refused:" + name)

    def _edge(self, opened, deadline):
        gate = self.config.get("gateway")
        if gate is None:
            return
        limits = gate["open"] if opened else {"rate": 0, "burst": 0}
        settings = {"ThrottlingBurstLimit": limits["burst"], "ThrottlingRateLimit": limits["rate"]}
        target = {"ApiId": gate["api_id"], "StageName": gate["stage"]}
        self.call(
            "apigatewayv2", "update-stage", {**target, "DefaultRouteSettings": settings}, deadline
        )
        observed = self.call("apigatewayv2", "get-stage", target, deadline)
        if any(observed.get("DefaultRouteSettings", {}).get(k) != v for k, v in settings.items()):
            raise OperationError("Edge throttle was not confirmed")

    def _preflight_quota(self, deadline):
        """Refuse positive reservations the account cannot honour before changing anything."""
        positive = sum(v for v in self.config["functions"].values() if v)
        if not positive:
            return
        settings = self.call("lambda", "get-account-settings", {}, deadline)
        total = settings.get("AccountLimit", {}).get("ConcurrentExecutions")
        if type(total) is not int or total - positive < MINIMUM_UNRESERVED:
            raise OperationError(
                "Account concurrency cannot hold the configured reservations; configure "
                "functions as None (unreserved) or raise the account quota"
            )

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

    def _launcher_on(self, launcher, session_end_epoch, deadline):
        """SQL flag first, then the rule: a tick can never find the rule on and the flag off."""
        self._require(launcher.enable(session_end_epoch=session_end_epoch, deadline=deadline))
        self._schedule(self.config["launcher"]["rule"], True, deadline)

    def open(
        self,
        *,
        ready,
        repair,
        deadline,
        window=False,
        intake_ready=None,
        launcher=None,
        launcher_session_end=None,
    ):
        """Open only after owning SQL readiness and bounded recovery succeed.

        ready/repair are deadline-aware owner hooks. They must close their SQL
        connections. No worker starts implicitly, including when queues are full.

        window=True opens only the public API functions and Gateway so a release can be
        smoke-tested through the real contracts while every queue consumer, repair rule
        and worker stays disabled (the owner must remain quiescent). It may run with a
        pending release, which a full open refuses; `close` ends it like any session.

        intake_ready probes the intake-side owner (Media) after its function is restored
        but before the edge opens, because a quiesced function cannot be invoked. A
        failure re-quiesces intake so a half-open session never serves the public API.

        launcher (hooks with enable/disable/settle) opts this session into unattended
        encoder starts (#68). It needs a stack deployed with UnattendedLaunch=true and a
        launcher_session_end epoch, after which the launcher starts nothing even if the
        operator forgets to close. Absent, V1's operator-batch behaviour is unchanged.
        """
        with self.journal.locked() as state:
            allowed = {"closed", "opening", "window"} if window else {"closed", "opening"}
            if state.get("session") not in allowed or (
                state.get("pending_release") and not window
            ):
                raise OperationError("Closed session without release intent required")
            if launcher is not None and (
                window or not self.config.get("launcher") or not launcher_session_end
            ):
                raise OperationError(
                    "Unattended launch needs a full open, an UnattendedLaunch stack and an end"
                )
            self._preflight_quota(deadline)
            restored = set(self.config.get("window_functions", [])) if window else None
            if window and not restored >= set(self.config["intake_functions"]):
                raise OperationError("Window needs the intake and readiness API functions")
            warnings = []
            state.update(session="opening", paused=True, unattended=False, session_completed=[])
            self.journal.save(state)
            # Quiesce intake first even on a retry after partial failure.
            for name in self.config["intake_functions"]:
                self._step(
                    state, "quiesce:" + name, lambda n=name: self._zero(n, deadline, warnings)
                )
            if self.config.get("gateway"):
                self._step(state, "edge:close", lambda: self._edge(False, deadline))
            for name, value in self.config["functions"].items():
                if name not in self.config["intake_functions"] and (
                    restored is None or name in restored
                ):
                    self._step(
                        state,
                        "restore:" + name,
                        lambda n=name, v=value: self._concurrency(n, v, deadline),
                    )
            self._step(state, "sql-ready", lambda: self._require(ready(deadline=deadline)))
            if not window:
                self._step(state, "repair", lambda: self._require(repair(deadline=deadline)))
                for identity in self.config.get("mappings", []):
                    self._step(
                        state,
                        "enable:" + identity,
                        lambda i=identity: self._mapping(i, True, deadline),
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
            if intake_ready is not None:
                try:
                    self._step(
                        state,
                        "intake-ready",
                        lambda: self._require(intake_ready(deadline=deadline)),
                    )
                except Exception:
                    # Never leave intake serving after a failed probe, even without an edge gate.
                    for name in self.config["intake_functions"]:
                        try:
                            self._zero(name, deadline, [])
                        except OperationError:
                            pass
                    raise
            if self.config.get("gateway"):
                self._step(state, "edge:open", lambda: self._edge(True, deadline))
            if launcher is not None:
                self._step(
                    state,
                    "launcher:enable",
                    lambda: self._launcher_on(launcher, launcher_session_end, deadline),
                )
            # A window never unpauses launches: batches need a full open session.
            state.update(
                session="window" if window else "open",
                unattended=launcher is not None,
                paused=window,
                session_step="complete",
                session_warnings=warnings,
            )
            self.journal.save(state)
            return {
                "session": state["session"],
                "worker_starts": 0,
                "warnings": warnings,
            }

    def status(self, *, deadline):
        """Read-only reconciliation of the journal against the live control plane.

        A stack update can re-apply the template's closed defaults underneath an open
        session; this is how the operator finds out. Nothing is changed here.
        """
        functions = {}
        for name in self.config["functions"]:
            payload = {"FunctionName": name}
            result = self.call("lambda", "get-function-concurrency", payload, deadline)
            functions[name] = result.get("ReservedConcurrentExecutions", "unreserved")
        mappings = {
            i: self.call("lambda", "get-event-source-mapping", {"UUID": i}, deadline).get("State")
            for i in self.config.get("mappings", [])
        }
        rules = {
            n: self.call("events", "describe-rule", {"Name": n}, deadline).get("State")
            for n in self.config.get("schedules", [])
        }
        launcher_rule = None
        if self.config.get("launcher"):
            launcher_rule = self.call(
                "events", "describe-rule", {"Name": self.config["launcher"]["rule"]}, deadline
            ).get("State")
        edge = None
        gate = self.config.get("gateway")
        if gate:
            target = {"ApiId": gate["api_id"], "StageName": gate["stage"]}
            edge = self.call("apigatewayv2", "get-stage", target, deadline).get(
                "DefaultRouteSettings", {}
            )
        with self.journal.locked() as state:
            recorded = state.get("session")
            failures = list(state.get("session_failures", []))
            unattended = bool(state.get("unattended"))
        drift = []
        if recorded in {"open", "window", "closed"}:
            opened = recorded == "open"
            api = recorded != "closed"  # open and window both serve the public API
            live = set(self.config.get("window_functions", [])) if recorded == "window" else None
            for name, value in functions.items():
                serving = api and (live is None or name in live)
                want = self.config["functions"][name] if serving else 0
                if self.config.get("zero_reservation") == "off" and want in {None, 0}:
                    want = None  # Reservations are not used at all in this mode.
                want = "unreserved" if want is None else want
                if value != want:
                    drift.append(f"function:{name}={value}")
            for identity, value in mappings.items():
                if value != ("Enabled" if opened else "Disabled"):
                    drift.append(f"mapping:{identity}={value}")
            for name, value in rules.items():
                if value != ("ENABLED" if opened else "DISABLED"):
                    drift.append(f"rule:{name}={value}")
            if self.config.get("launcher"):
                want = "ENABLED" if opened and unattended else "DISABLED"
                if launcher_rule != want:
                    drift.append(f"launcher-rule:{launcher_rule}")
            if gate:
                limits = gate["open"] if api else {"rate": 0, "burst": 0}
                if (edge.get("ThrottlingRateLimit"), edge.get("ThrottlingBurstLimit")) != (
                    limits["rate"],
                    limits["burst"],
                ):
                    drift.append("edge-throttle")
        return {
            "journal_session": recorded,
            "unresolved_steps": failures,
            "observed": {
                "functions": functions,
                "mappings": mappings,
                "schedules": rules,
                "launcher_rule": launcher_rule,
                "edge_throttle": edge,
            },
            "drift": drift,
            # Aurora capacity is never inferred from control-plane state.
            "database_pause": "NOT_OBSERVED",
        }

    @staticmethod
    def _require(result):
        if result is not True:
            raise OperationError("Owner readiness/repair hook did not confirm success")

    def close(self, *, drain, outcomes, deadline, launcher=None):
        """Retain queued messages/data. Disable every wake source even if drain fails.

        An unattended launcher is switched off before anything else: its rule, then its SQL
        flag (which returns only once no send is in flight). From then on nothing can start a
        worker, so the drain below waits on a shrinking set. Its ambiguous reservations are
        settled before the inventory check.

        drain must observe ECS STOPPED and owning SQL terminal/fenced outcomes;
        a forced stop alone is not a successful drain. Unresolved reservations
        prevent a successful close. No purge, DB stop/delete or object deletion.
        """
        with self.journal.locked() as state:
            state.update(session="closing", paused=True, session_completed=[])
            self.journal.save(state)
            failed, warnings = [], []

            errors = {}
            # One budget for the whole close, so several failing steps cannot add up to more
            # than the action's own deadline.
            retry_until = self.clock() + self.close_retry_seconds

            def attempt(name, action):
                # Every close step is an idempotent control setting, so a failed one is tried
                # again for a bounded time before the close gives up on it. The launcher flag
                # and the readiness hooks reach Aurora through a Lambda, and a database that
                # paused after the last use needs a minute or more to resume (r1018b: two CD
                # teardowns failed their close on exactly such a step). The drain checks are
                # not retried: they wait on running encoders, which a retry cannot change.
                tries = 0
                while True:
                    tries += 1
                    try:
                        self._step(state, name, action)
                        return
                    except Exception as error:
                        reason = _reason(error)
                        if name in NO_RETRY or (
                            self.clock() + self.close_retry_interval > retry_until
                        ):
                            break
                    self.sleep(self.close_retry_interval)
                failed.append(name)
                errors[name] = f"{reason} (tries: {tries})"
                state["session_failures"] = list(failed)
                state["session_errors"] = dict(errors)
                self.journal.save(state)

            if self.config.get("launcher"):
                rule = self.config["launcher"]["rule"]
                attempt("launcher:rule", lambda: self._schedule(rule, False, deadline))
                if launcher is not None:
                    attempt(
                        "launcher:flag", lambda: self._require(launcher.disable(deadline=deadline))
                    )
            for name in self.config["intake_functions"]:
                attempt("quiesce:" + name, lambda n=name: self._zero(n, deadline, warnings))
            if self.config.get("gateway"):
                attempt("edge:close", lambda: self._edge(False, deadline))
            if not failed:
                attempt("drain", lambda: self._require(drain(deadline=deadline)))
                attempt("outcomes", lambda: self._outcomes(state, outcomes, deadline))
                if self.config.get("launcher") and launcher is not None:
                    attempt(
                        "launcher:settle", lambda: self._require(launcher.settle(deadline=deadline))
                    )
                attempt("inventory", lambda: self._empty(state, deadline))
            for identity in self.config.get("mappings", []):
                attempt("disable:" + identity, lambda i=identity: self._mapping(i, False, deadline))
            for name in self.config.get("schedules", []):
                attempt("disable:" + name, lambda n=name: self._schedule(n, False, deadline))
            for name in self.config["functions"]:
                attempt("zero:" + name, lambda n=name: self._zero(n, deadline, warnings))
            state["session_failures"] = failed
            state["session_warnings"] = warnings
            if failed:
                self.journal.save(state)
                # Name each unresolved step and why: the CD log keeps nothing else of the close.
                detail = "; ".join(f"{name}: {errors.get(name, 'not run')}" for name in failed)
                raise OperationError(f"Partial close; retry from retained journal. {detail}")
            state.update(session="closed", unattended=False, session_step="complete")
            self.journal.save(state)
            return {
                "session": "closed",
                "warnings": warnings,
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
            if state.get("unattended"):
                # Two launchers sharing the cap would race each other's inventory reads.
                raise OperationError("Unattended launcher owns worker starts this session")
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


if __name__ == "__main__":
    # Imported lazily: the CLI module imports Session from here.
    from scripts.aws.v1.session_cli import main

    raise SystemExit(main())
