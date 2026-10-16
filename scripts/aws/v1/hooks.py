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


def gateway_event(method, path, body=None):
    """Minimal HTTP API payload-v2 event for an unauthenticated public route."""
    payload = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": method}},
        "isBase64Encoded": False,
    }
    if body is not None:
        payload["body"] = json.dumps(body)
    return payload


class OwnerHooks:
    """ready/repair hooks for Session.open using alias invocations only."""

    def __init__(
        self,
        transport,
        *,
        processing_api,
        repairs,
        qualifier="live",
        clock=time.monotonic,
        sleep=time.sleep,
        poll_seconds=5,
        repair_rounds=3,
    ):
        if not processing_api or not repairs:
            raise OperationError("Readiness function and repair functions are required")
        self.transport, self.qualifier = transport, qualifier
        self.processing_api, self.repairs = processing_api, list(repairs)
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

    def _healthy(self, deadline):
        result = self._invoke(
            self.processing_api, gateway_event("GET", "/api/processing/health"), deadline
        )
        if result.get("FunctionError") or result.get("StatusCode") != 200:
            return False
        reply = result.get("Payload") or {}
        if reply.get("statusCode") != 200:
            return False
        try:
            body = json.loads(reply.get("body") or "{}")
        except ValueError:
            return False
        # Processing health runs SELECT 1, so success proves cluster wake, TLS and creds.
        return body.get("status") == "ok" and body.get("service") == "processing"

    def ready(self, *, deadline):
        """Poll while Aurora resumes. Cold resume can outlast a single Lambda timeout."""
        while True:
            try:
                remaining(deadline, self.clock)
                if self._healthy(deadline):
                    return True
            except OperationError:
                pass  # transient SDK/Lambda failure while resuming; the deadline bounds us
            try:
                self.sleep(min(self.poll_seconds, remaining(deadline, self.clock)))
            except OperationError:
                return False

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
