"""Shared plumbing for the V1 cloud-proof harnesses (#63-#67).

Rules every harness inherits from here, so they hold even for a harness written in a hurry:

* A receipt is private (mode 0600, atomic write) and carries two views of each step: `private`
  (identifiers, hosts, task ARNs: useful to the operator, never committed) and `public` (numbers,
  verdicts, hashes). Only `public` reaches the committed summary, and it is screened for URLs,
  ARNs, account ids, addresses and token-looking strings before it is stored.
* A step that already passed is skipped on a rerun, so a rerun after a crash or a closed laptop
  neither repeats a billable action nor rewrites an old verdict. Side-effecting steps record their
  intent (request ids, task ARNs) first, so a rerun resumes the same job or task instead of
  starting another.
* Nothing that ran against the simulated account can be a PASS. A simulated receipt's overall
  status is SIMULATED whatever its steps say, and the summary writer refuses it.
* A step that needs an open session window refuses to start while the session journal says
  closed, and again when the Gateway throttle shows the edge shut.
"""

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from scripts.aws.transport import OperationError, safe_record
from scripts.aws.v1.public_smoke import validate_base_url

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT_RUN"
SIMULATED = "SIMULATED"
LEAK = re.compile(
    r"https?://|arn:aws|\b[0-9]{12}\b|[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|AKIA|ASIA|"
    r"x-amz|set-cookie|session=",
    re.I,
)
HEX = re.compile(r"[0-9a-f]{8,64}")
TOKENISH = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")


class ProofError(OperationError):
    """Safe-to-print failure of a harness precondition."""


class SessionRefused(ProofError):
    """The session is not in the state a step needs. It stops the whole command."""


def stamp(value=None):
    value = value if value is not None else time.time()
    return dt.datetime.fromtimestamp(value, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text):
    when = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def seconds_between(start, end):
    if not start or not end:
        return None
    return round((parse_time(end) - parse_time(start)).total_seconds(), 3)


def percentile(values, fraction):
    """Nearest-rank percentile; the same rule scripts.aws.latency uses for p90."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * fraction // 1))  # ceil without importing math
    return ordered[int(rank) - 1]


def check_public(value, where="public"):
    """Refuse anything in the committed view that could identify a resource or carry a secret."""
    if isinstance(value, dict):
        for key, item in value.items():
            check_public(key, where)
            check_public(item, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_public(item, where)
    elif isinstance(value, str):
        if LEAK.search(value) or (TOKENISH.fullmatch(value) and not HEX.fullmatch(value)):
            raise ProofError(f"The public view of a step would leak an identifier at {where}")
    elif value is not None and not isinstance(value, (int, float, bool)):
        raise ProofError(f"Non-JSON value in the public view at {where}")


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".proof-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


class Proof:
    """One issue's receipt for one run id: ordered steps, resumable intents, an overall verdict."""

    def __init__(self, issue, *, directory, run_id, simulated, scope, required=(), guard=None,
                 wall=time.time, fresh=None):
        self.issue, self.run_id, self.simulated = issue, run_id, simulated
        self.required, self.guard, self.wall = tuple(required), guard, wall
        # `fresh` is None (PASS and NOT_RUN stay final), True (every step) or a set of step names
        # whose old receipt entry is archived, once per process, before the step runs again.
        self.fresh, self.archived = fresh, set()
        self.ran = []  # steps whose action ran in this process (not skipped as already passed)
        self.path = Path(directory) / f"evidence-{issue}-{run_id}.json"
        self.doc = {"issue": f"#{issue}", "run_id": run_id, "scope": scope, "steps": {},
                    "intents": {}, "mode": SIMULATED.lower() if simulated else "live"}
        if self.path.exists():
            try:
                self.doc = json.loads(self.path.read_text())
            except ValueError:
                raise ProofError("Existing receipt is unreadable; move it aside") from None
            if (self.doc.get("mode") == "live") == simulated:
                raise ProofError("A receipt from the other mode exists for this run id")

    # ---- persistence ------------------------------------------------------------------
    def save(self):
        self.doc["updated_at"] = stamp(self.wall())
        safe_record(self.doc)
        private_write(self.path, json.dumps(self.doc, indent=2, sort_keys=True) + "\n")

    def intent(self, name):
        """Mutable record for a side-effecting step; call save() after writing to it."""
        return self.doc["intents"].setdefault(name, {})

    def wants_fresh(self, name):
        return name not in self.archived and (
            self.fresh is True or (bool(self.fresh) and name in self.fresh))

    def archive(self, name):
        """Move a step's entry and intent to `attempts` so the step reruns and mints a new intent.

        `attempts` is private history: the summary and counts read `steps` only, so an archived
        attempt can never reach (or fail the screen of) a committed file.
        """
        self.archived.add(name)
        step = self.doc["steps"].pop(name, None)
        intent = self.doc["intents"].pop(name, None)
        if step is None and intent is None:
            return
        history = self.doc.setdefault("attempts", {}).setdefault(name, [])
        history.append({"attempt": len(history) + 1, "step": step, "intent": intent,
                        "archived_at": stamp(self.wall())})
        self.save()

    def checkpoint(self, kind):
        """Re-assert the session while a long step waits: a closed window must stop the step."""
        if self.guard and kind:
            self.guard(kind)

    # ---- steps ----------------------------------------------------------------------------
    def done(self, name):
        return self.doc["steps"].get(name, {}).get("status") in {PASS, NOT_RUN}

    def step(self, name, action, *, session="active", rerun=False):
        """Run `action(intent)` once. It returns {"status","public","private"} or raises.

        `session` names the window the step needs (open | window | active | closed | None); the
        guard raises before anything is recorded, so a refused step leaves the receipt untouched.
        """
        known = self.doc["steps"].get(name)
        fresh = self.wants_fresh(name)
        if known and known["status"] in {PASS, NOT_RUN} and not rerun and not fresh:
            return known
        self.checkpoint(session)
        if fresh:  # after the guard: a refused step leaves the receipt untouched
            self.archive(name)
        self.ran.append(name)
        started = self.wall()
        try:
            result = action(self.intent(name))
            status = result.get("status", PASS)
            public, private = result.get("public", {}), result.get("private", {})
        except SessionRefused:
            raise  # a guard refusal from inside a long step must stop the command
        except OperationError as error:
            status, public, private = FAIL, {"error": str(error)}, {}
        except Exception as error:  # a harness bug or a surprise: record the class, never text
            status, public, private = FAIL, {"error": type(error).__name__}, {}
        if status not in {PASS, FAIL, NOT_RUN}:
            raise ProofError(f"Step {name} returned an unknown status")
        try:
            check_public(public)
        except ProofError:
            status, public = FAIL, {"error": "the step's public view was withheld by the screen"}
        self.doc["steps"][name] = {
            "status": status, "started_at": stamp(started), "ended_at": stamp(self.wall()),
            "seconds": round(self.wall() - started, 3), "public": public, "private": private,
        }
        self.save()
        return self.doc["steps"][name]

    def failed_now(self):
        return [n for n in self.ran if self.doc["steps"].get(n, {}).get("status") == FAIL]

    def overall(self):
        if self.simulated:
            return SIMULATED
        steps = self.doc["steps"]
        statuses = [steps[n]["status"] for n in self.required if n in steps]
        if FAIL in statuses or any(s["status"] == FAIL for s in steps.values()):
            return FAIL
        if any(name not in steps for name in self.required):
            return "INCOMPLETE"
        if NOT_RUN in statuses or any(s["status"] == NOT_RUN for s in steps.values()):
            return "PARTIAL"
        return PASS

    def report(self):
        """What a command prints: statuses and public numbers only."""
        return {
            "issue": self.doc["issue"], "run_id": self.run_id, "mode": self.doc["mode"],
            "overall": self.overall(),
            "steps": {n: {"status": s["status"], "seconds": s["seconds"], **s["public"]}
                      for n, s in self.doc["steps"].items()},
            "receipt": str(self.path),
        }


def stage_throttle(aws, gate):
    """The Gateway stage's live default-route throttle, as `session status` reads it
    ({"ThrottlingRateLimit", "ThrottlingBurstLimit"}; empty when the stage reports none)."""
    stage = aws.call("apigatewayv2", "get-stage",
                     {"ApiId": gate["api_id"], "StageName": gate["stage"]},
                     deadline=time.monotonic() + 30)
    return stage.get("DefaultRouteSettings", {})


class SessionGuard:
    """Refuses a step when the session journal (and the live Gateway throttle) disagree."""

    NEEDS = {"open": {"open"}, "window": {"window"}, "active": {"open", "window"},
             "closed": {"closed"}}

    def __init__(self, journal, aws, config):
        self.journal, self.aws, self.config = journal, aws, config

    def __call__(self, kind):
        if kind not in self.NEEDS:
            raise ProofError("Unknown session requirement")
        with self.journal.locked() as state:
            session, paused = state.get("session"), state.get("paused")
        if session not in self.NEEDS[kind] or (kind == "open" and paused):
            raise SessionRefused(
                f"Session is {session}; this step needs {kind}. Run "
                f"`python -m scripts.aws.v1.session {'window' if kind == 'window' else 'open'} "
                "--config ...` first (a closed session means a closed window)")
        gate = self.config.get("gateway")
        if gate and kind != "closed":
            limits = stage_throttle(self.aws, gate)
            if not limits.get("ThrottlingRateLimit"):
                raise SessionRefused(
                    f"Session is {session} but the Gateway throttle is 0: the edge is shut, "
                    "so this step needs an open session window")


# ---- HTTP ----------------------------------------------------------------------------------
class Reply:
    def __init__(self, status, headers, body, ms):
        self.status, self.headers, self.body, self.ms = status, headers, body, ms

    def first(self, name, default=""):
        return (self.headers.get(name.lower()) or [default])[0]

    def json(self):
        try:
            return json.loads(self.body or b"null")
        except ValueError:
            return None


class Api:
    """The public API through one origin, as a browser uses it: JSON, one in-memory cookie, no
    redirects followed. The cookie never leaves this object and is never written or printed."""

    def __init__(self, base, http, clock=time.monotonic):
        self.base, self.http, self.clock = validate_base_url(base), http, clock
        self.cookie = None

    def request(self, method, path, *, body=None, headers=None, auth=True, timeout=20, raw=None):
        sent = {"accept": "application/json", **(headers or {})}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            sent["content-type"] = "application/json"
        if auth and self.cookie:
            sent["cookie"] = self.cookie
        before = self.clock()
        status, reply_headers, payload = self.http(method, self.base + path, sent, data, timeout)
        return Reply(status, reply_headers, payload, round((self.clock() - before) * 1000, 1))

    def login(self, credentials):
        reply = self.request("POST", "/api/media/auth/login", body=credentials, auth=False)
        cookies = reply.headers.get("set-cookie", [])
        if reply.status == 200 and cookies:
            self.cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
        return reply, [c.split(";", 1)[1].lower() if ";" in c else "" for c in cookies]


def direct(http, method, url, headers, body, *, timeout=60, clock=time.monotonic):
    """A request that deliberately carries no cookie (storage, queues): url is absolute."""
    if any(k.lower() == "cookie" for k in headers):
        raise ProofError("A direct storage or queue request must not carry the session")
    before = clock()
    status, reply_headers, payload = http(method, url, headers, body, timeout)
    return Reply(status, reply_headers, payload, round((clock() - before) * 1000, 1))


def multipart(fields, filename, data, content_type):
    """(content-type header, body) for an S3 presigned POST: every field first, file last."""
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            .encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def host_of(url):
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or ""
