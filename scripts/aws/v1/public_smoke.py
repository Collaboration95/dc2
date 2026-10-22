"""Release smoke through the public Gateway contracts (login, health, jobs, reserve).

Everything goes through the Gateway base URL exactly as a browser would, so a candidate
that only passes direct Lambda invocation (authorizer, cookie, route or CORS breakage)
still fails here. Side effects are limited to one upload reservation per Media release,
which is never finalized and expires on its own; Processing checks are read-only.

The HTTP transport and clock are injected. Credentials come from a private file and are
never logged, journaled or echoed in a failure: only check names and status codes are.
"""

import hashlib
import json
import stat
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from scripts.aws.transport import OperationError

MAX_BODY = 1_000_000
# An auto-paused Aurora cluster needs time to resume, and the first database-backed call meets it:
# Media gives up on its connection after about ten seconds and answers 503 (the gateway may answer
# 502/504). Only these statuses and a transport failure count as "the database is still waking".
DATABASE_WAKING = frozenset({502, 503, 504})
# Pauses between login attempts for a caller that expects to meet a paused database (the deploy).
DATABASE_WAKE_BACKOFF = (5, 10, 15)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # A redirect from the Gateway is a contract failure, not something to follow.


def urllib_http(method, url, headers, body, timeout):
    """(status, {lowercase header: [values]}, body bytes); no redirects, bounded size."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, _headers(response.headers), response.read(MAX_BODY)
    except urllib.error.HTTPError as error:
        return error.code, _headers(error.headers), error.read(MAX_BODY)


def _headers(message):
    result = {}
    for key in message.keys():
        result[key.lower()] = message.get_all(key) or []
    return result


def load_credentials(path):
    """Private 0600 JSON {"email","password"}: a pre-registered smoke user."""
    target = Path(path)
    try:
        if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) & 0o077:
            raise OperationError("Smoke credentials file must be private")
        data = json.loads(target.read_text())
    except (OSError, ValueError):
        raise OperationError("Smoke credentials unreadable") from None
    if not isinstance(data, dict) or data.keys() != {"email", "password"}:
        raise OperationError("Smoke credentials need exactly email and password")
    if not all(isinstance(v, str) and v for v in data.values()):
        raise OperationError("Smoke credentials need exactly email and password")
    return data


def validate_base_url(url):
    parts = urlsplit(url)
    local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        parts.scheme not in {"https", "http"}
        or (parts.scheme == "http" and not local)
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise OperationError("Base URL must be an https Gateway origin without credentials")
    return f"{parts.scheme}://{parts.netloc}"


class PublicSmoke:
    """Callable with the release hook shape public_smoke(owner, versions, worker, *, deadline)."""

    def __init__(
        self,
        base_url,
        credentials,
        *,
        http=urllib_http,
        clock=time.monotonic,
        reserve=True,
        sleep=time.sleep,
        wake_backoff=(),
    ):
        """`wake_backoff` is the pauses between login attempts while the database may be waking.

        Empty (the default, for a release smoke that runs after its migration has used the
        database) means a single attempt."""
        self.base = validate_base_url(base_url)
        self.credentials, self.http, self.clock, self.reserve = credentials, http, clock, reserve
        self.sleep, self.wake_backoff = sleep, tuple(wake_backoff)
        self.checks, self.failures, self.receipt = {}, [], {}
        self.cookie, self.login_attempts, self.processing_attempts = None, [], []

    # -- plumbing -----------------------------------------------------------------
    def _request(self, method, path, deadline, body=None, cookie=None):
        budget = deadline - self.clock()
        if budget <= 0:
            raise OperationError("A live finite deadline is required")
        headers = {"accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        if cookie:
            headers["cookie"] = cookie
        return self.http(method, self.base + path, headers, data, min(15, budget))

    @staticmethod
    def _json(body):
        try:
            return json.loads(body or b"null")
        except ValueError:
            return None

    def _check(self, name, action):
        try:
            outcome = action()
        except OperationError:
            raise
        except Exception:
            outcome = "error"  # network/JSON surprises fail the check without leaking detail
        self.checks[name] = "PASS" if outcome is True else "FAIL"
        if outcome is not True:
            self.failures.append(f"{name}:{outcome}")
        return outcome is True

    # -- contracts ----------------------------------------------------------------
    def _health(self, service, deadline):
        status, _, body = self._request("GET", f"/api/{service}/health", deadline)
        data = self._json(body)
        if status != 200:
            return status
        ok = isinstance(data, dict) and (data.get("status"), data.get("service")) == ("ok", service)
        if service == "processing":
            ok = ok and data.get("schema_version") == 1
        return True if ok else "contract"

    def _anonymous_denied(self, deadline):
        status, _, _ = self._request("GET", "/api/media/jobs", deadline)
        return True if status in {401, 403} else status

    def _waking(self, path, deadline, log, method="GET", body=None, cookie=None):
        """One request, repeated while a paused database is waking.

        Each service has its own Aurora cluster (AD-29) that pauses independently, so the first
        call needing each database (Media login, Processing's job batch) may meet a waking one.
        Only a 502/503/504 or a transport failure is retried, with the configured pauses and only
        while the deadline leaves room for the pause and another request; any other status ends
        the check at once, and a 503 that outlasts the pauses is still the failure. Every
        attempt's status is appended to `log` for the receipt."""
        attempts = len(self.wake_backoff) + 1
        for attempt in range(attempts):
            try:
                reply = self._request(method, path, deadline, body=body, cookie=cookie)
            except OperationError:
                raise
            except Exception:
                reply = ("error", {}, b"")  # a transport failure; no detail is kept
            status = reply[0]
            log.append(status)
            if status not in DATABASE_WAKING and status != "error":
                break
            last = attempt == attempts - 1
            if last or deadline - self.clock() <= self.wake_backoff[attempt] + 1:
                break
            self.sleep(self.wake_backoff[attempt])
        return reply

    def _login_attempts(self, deadline):
        return self._waking(
            "/api/media/auth/login", deadline, self.login_attempts, "POST", self.credentials
        )

    def _login(self, deadline):
        status, headers, body = self._login_attempts(deadline)
        if status != 200:
            return status
        cookies = headers.get("set-cookie", [])
        if not cookies:
            return "no-cookie"
        flags = " ".join(cookies).lower()
        if "httponly" not in flags or "secure" not in flags or "samesite=strict" not in flags:
            return "cookie-flags"
        self.cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
        data = self._json(body)
        return True if isinstance(data, dict) and "id" in data else "contract"

    def _jobs(self, deadline):
        status, _, body = self._request("GET", "/api/media/jobs", deadline, cookie=self.cookie)
        if status != 200:
            return status
        return True if isinstance(self._json(body), list) else "contract"

    def _processing_batch(self, deadline):
        # A random asset id this user cannot own: success is an authorized empty result.
        path = f"/api/processing/jobs?asset_ids={uuid.uuid4()}"
        status, _, body = self._waking(path, deadline, self.processing_attempts, cookie=self.cookie)
        if status != 200:
            return status
        return True if self._json(body) == [] else "contract"

    def _reserve(self, deadline):
        request = {
            "request_id": str(uuid.uuid4()),
            "filename": "release-smoke.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
            "sha256": hashlib.sha256(b"dc2-v1-release-smoke").hexdigest(),
        }
        status, _, body = self._request(
            "POST", "/api/media/uploads/reservations", deadline, body=request, cookie=self.cookie
        )
        if status != 201:
            return status
        data = self._json(body)
        upload = data.get("upload") if isinstance(data, dict) else None
        ok = (
            isinstance(upload, dict)
            and isinstance(upload.get("url"), str)
            and isinstance(upload.get("fields"), dict)
            and data.get("expires_at")
            and data.get("finalize_url")
        )
        # The reservation is deliberately never finalized: it expires and is reclaimed.
        return True if ok else "contract"

    def __call__(self, owner, versions, worker_definition, *, deadline):
        self.checks, self.failures, self.cookie = {}, [], None
        self.login_attempts, self.processing_attempts = [], []
        self._check("media-health", lambda: self._health("media", deadline))
        self._check("processing-health", lambda: self._health("processing", deadline))
        self._check("anonymous-denied", lambda: self._anonymous_denied(deadline))
        if self._check("login", lambda: self._login(deadline)):
            self._check("media-jobs", lambda: self._jobs(deadline))
            self._check("processing-jobs", lambda: self._processing_batch(deadline))
            if owner == "media" and self.reserve:
                self._check("upload-reserve", lambda: self._reserve(deadline))
        self.receipt = {
            "owner": owner,
            "versions": dict(versions),
            "checks": dict(self.checks),
            "failures": list(self.failures),
            # One status per login try ("error" for a transport failure): [503, 200] shows that
            # the database was still waking on the first try. Statuses only, never a body.
            "login_attempts": list(self.login_attempts),
            "processing_attempts": list(self.processing_attempts),
        }
        return not self.failures
