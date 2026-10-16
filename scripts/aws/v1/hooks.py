"""Real owner hooks for session open/close, behind the OperatorTransport abstraction.

Nothing here opens a socket itself except the optional SQL reader, and that only runs
from an operator station that can reach the private database. All Lambda/ECS access
goes through an injected transport, so every hook is testable with a fake. Results are
counts and booleans only: response bodies, DSNs and cookies are never returned or kept.
"""

import asyncio
import json
import os
import ssl
import stat
import time
from pathlib import Path

from scripts.aws.transport import OperationError, remaining

ATTEMPT_STATES = ("queued", "processing", "succeeded", "failed", "abandoned", "cancelled")
OUTCOME_STATES = ("queued", "succeeded", "failed", "abandoned", "cancelled")
# Read-only: attempt states are the authoritative terminal/fenced outcome record.
COUNT_SQL = "SELECT state, count(*) FROM attempts GROUP BY state"


class OwnerHooks:
    """ready/repair hooks for Session.open using alias invocations only."""

    def __init__(
        self,
        transport,
        *,
        processing_api,
        media_api,
        repairs,
        qualifier="live",
        clock=time.monotonic,
        sleep=time.sleep,
        poll_seconds=5,
        repair_rounds=3,
    ):
        if not processing_api or not media_api or not repairs:
            raise OperationError("Readiness functions and repair functions are required")
        self.transport, self.qualifier = transport, qualifier
        self.processing_api, self.media_api = processing_api, media_api
        self.repairs = list(repairs)
        self.clock, self.sleep = clock, sleep
        self.poll_seconds, self.repair_rounds = poll_seconds, repair_rounds

    def _invoke(self, function, event, deadline):
        return self.transport.call(
            "lambda",
            "invoke",
            {
                "FunctionName": function,
                "Qualifier": self.qualifier,
                "InvocationType": "RequestResponse",
                "Payload": event,
            },
            deadline=deadline,
        )

    def _probe(self, function, service, deadline):
        """Direct-invoke readiness: Gateway cannot construct this event, IAM gates it."""
        result = self._invoke(function, {"dc2_operation": "ready"}, deadline)
        reply = result.get("Payload")
        return (
            not result.get("FunctionError")
            and result.get("StatusCode") == 200
            and isinstance(reply, dict)
            and reply.get("service") == service
            and reply.get("ready") is True
        )

    def _poll(self, function, service, deadline):
        """Poll while Aurora resumes. Cold resume can outlast a single Lambda timeout."""
        while True:
            try:
                remaining(deadline, self.clock)
                if self._probe(function, service, deadline):
                    return True
            except OperationError:
                pass  # transient SDK/Lambda failure while resuming; the deadline bounds us
            try:
                self.sleep(min(self.poll_seconds, remaining(deadline, self.clock)))
            except OperationError:
                return False

    def ready(self, *, deadline):
        """Processing's owned database (runs while Media intake is still quiesced)."""
        return self._poll(self.processing_api, "processing", deadline)

    def intake_ready(self, *, deadline):
        """Media's owned database, probed once its intake function is restored."""
        return self._poll(self.media_api, "media", deadline)

    def repair(self, *, deadline):
        """Run every owner's bounded repair tick; a clean round means no deadline hit."""
        for _ in range(self.repair_rounds):
            clean = True
            for function in self.repairs:
                result = self._invoke(function, {}, deadline)
                reply = result.get("Payload")
                if (
                    result.get("FunctionError")
                    or result.get("StatusCode") != 200
                    or not isinstance(reply, dict)
                ):
                    return False
                if reply.get("deadline_reached"):
                    clean = False
            if clean:
                return True
        return False


def validated_counts(raw):
    if (
        not isinstance(raw, dict)
        or raw.keys() - set(ATTEMPT_STATES)
        or any(type(v) is not int or v < 0 for v in raw.values())
    ):
        raise OperationError("Safe SQL attempt counts required")
    return {state: raw.get(state, 0) for state in ATTEMPT_STATES}


def file_reader(path):
    """Operator-supplied private counts (for stations that cannot reach the private DB)."""

    def read(_deadline):
        target = Path(path)
        try:
            if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) & 0o077:
                raise OperationError("Counts file must be a private regular file")
            return validated_counts(json.loads(target.read_text()))
        except (OSError, ValueError):
            raise OperationError("Counts file unreadable") from None

    return read


def sql_reader(dsn_file, ca_file, *, connect=None):
    """Read-only attempt counts over verified TLS. The DSN file stays private (0600)."""

    def read(deadline):
        target = Path(dsn_file)
        try:
            if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) & 0o077:
                raise OperationError("DSN file must be a private regular file")
            dsn = target.read_text().strip()
        except OSError:
            raise OperationError("DSN file unreadable") from None
        context = ssl.create_default_context(cafile=str(ca_file))

        async def query():
            opener = connect
            if opener is None:
                import asyncpg

                opener = asyncpg.connect
            connection = await opener(dsn, ssl=context, timeout=10, command_timeout=10)
            try:
                rows = await connection.fetch(COUNT_SQL)
            finally:
                await connection.close()
            return {row[0]: row[1] for row in rows}

        try:
            counts = asyncio.run(asyncio.wait_for(query(), timeout=remaining(deadline)))
        except OperationError:
            raise
        except Exception:
            # Driver messages can echo DSN fragments.
            raise OperationError("Processing SQL attempt counts unavailable") from None
        return validated_counts(counts)

    return read


class AttemptCounts:
    """drain/outcomes hooks over a counts reader (SQL or operator-supplied file)."""

    def __init__(self, reader, *, clock=time.monotonic, sleep=time.sleep, poll_seconds=5):
        self.reader, self.clock, self.sleep, self.poll_seconds = reader, clock, sleep, poll_seconds

    def drain(self, *, deadline):
        """True once no attempt is processing. Repair stays enabled, so leases expire."""
        while True:
            if self.reader(deadline)["processing"] == 0:
                return True
            try:
                self.sleep(min(self.poll_seconds, remaining(deadline, self.clock)))
            except OperationError:
                return False

    def outcomes(self, *, deadline):
        counts = self.reader(deadline)
        if counts["processing"]:
            raise OperationError("In-flight attempts remain; outcomes are not terminal")
        return {state: counts[state] for state in OUTCOME_STATES}


def refuse_ambient_credentials(environ=None):
    """The CLI uses one explicit profile; inherited credentials could target another."""
    environ = os.environ if environ is None else environ
    ambient = [
        key
        for key in environ
        if key in {"AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"}
        or key.startswith("AWS_ENDPOINT_URL")
    ]
    if ambient:
        raise OperationError("Unset inherited AWS_* credential/profile/endpoint variables")


def owner_quiescence(config, transport):
    """quiescent(owner): consumers and rules off and no ECS task outside STOPPED.

    Intake may be open (a release window); only background work must be silent. Pure
    control-plane reads, so it is safe to call inside a release's journal lock.
    """
    from scripts.aws.workers import inventory

    def quiescent(owner, *, deadline):
        consumers = config["owner_consumers"][owner]
        for identity in consumers["mappings"]:
            state = transport.call(
                "lambda", "get-event-source-mapping", {"UUID": identity}, deadline=deadline
            ).get("State")
            if state != "Disabled":
                return False
        for name in consumers["schedules"]:
            state = transport.call(
                "events", "describe-rule", {"Name": name}, deadline=deadline
            ).get("State")
            if state != "DISABLED":
                return False
        if owner == "processing":
            tasks = inventory(config, transport, deadline=deadline)
            return all(t["lastStatus"] == "STOPPED" for t in tasks.values())
        return True

    return quiescent


def schema_reader(dsn_files, ca_file, *, connect=None):
    """schema_revision(owner): the owning database's Alembic head, read-only over TLS."""

    def read(owner, *, deadline):
        if owner not in dsn_files:
            raise OperationError("No schema DSN file configured for this owner")
        target = Path(dsn_files[owner])
        try:
            if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) & 0o077:
                raise OperationError("DSN file must be a private regular file")
            dsn = target.read_text().strip()
        except OSError:
            raise OperationError("DSN file unreadable") from None
        context = ssl.create_default_context(cafile=str(ca_file))

        async def query():
            opener = connect
            if opener is None:
                import asyncpg

                opener = asyncpg.connect
            connection = await opener(dsn, ssl=context, timeout=10, command_timeout=10)
            try:
                return await connection.fetch("SELECT version_num FROM alembic_version")
            finally:
                await connection.close()

        try:
            rows = asyncio.run(asyncio.wait_for(query(), timeout=remaining(deadline)))
        except OperationError:
            raise
        except Exception:
            raise OperationError("Owning schema revision unavailable") from None
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            raise OperationError("Exactly one Alembic head is required")
        return rows[0][0]

    return read


def compatibility_from_evidence(path):
    """compatibility(...): an operator attestation bound to the exact source and revision.

    Whether the prior image tolerates the additive target schema is established by the
    owner's compatibility tests, not guessable at release time. The evidence file ties
    that result to this bundle's source_sha, so stale evidence cannot approve a new build.
    """

    def check(owner, prior, bundle, target_revision, *, deadline):
        try:
            evidence = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            raise OperationError("Compatibility evidence unreadable") from None
        return (
            isinstance(evidence, dict)
            and evidence.get("owner") == owner
            and evidence.get("source_sha") == bundle["api"]["source_sha"]
            and evidence.get("target_revision") == target_revision
            and evidence.get("additive_only") is True
            and evidence.get("current_image_compatible") is True
            and evidence.get("prior_image_compatible") is True
        )

    return check
