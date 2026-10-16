"""Warm-latency generator. Standard library only: it runs inside the worker image on Fargate.

The harness ships this file as a `python -c` command (see proof/tasks.py). It registers one
throwaway `user` account through the public endpoint, so no credential travels in the task
overrides (which CloudTrail records) and nothing is read from the project's own accounts.

Fifty virtual users read the status route once a second for 180 seconds after a five-second
warmup; four other read routes get a shorter warm pass; then twenty logins run at once. Every
request is one sample and every failure stays in the denominator: there are no retries and no
failure is dropped. The task prints the raw samples (compressed, chunked below the CloudWatch
event limit) with their sha256, then one summary line.
"""

import base64
import hashlib
import http.client
import json
import math
import os
import secrets
import ssl
import sys
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

RESULT, SAMPLES = "DC2-RESULT", "DC2-SAMPLES"
STATUS_ROUTE = "/api/media/jobs"
OTHER_ROUTES = (
    "/api/media/health", "/api/processing/health", "/api/media/auth/me",
    "/api/processing/jobs?asset_ids={random}",
)
CHUNK = 120_000  # compressed bytes per log event; CloudWatch's limit is 256 KB


def percentile(values, fraction):
    """Nearest rank, the rule scripts.aws.latency uses for its p90."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(len(ordered) * fraction)) - 1] if ordered else None


def describe(rows):
    ms = [r["elapsed_ms"] for r in rows]
    bad = sum(1 for r in rows if r["status_code"] != 200 or r["error"])
    return {
        "count": len(rows), "errors": bad,
        "p50_ms": percentile(ms, 0.50), "p90_ms": percentile(ms, 0.90),
        "p95_ms": percentile(ms, 0.95), "p99_ms": percentile(ms, 0.99),
        "max_ms": max(ms) if ms else None,
    }


class Requester:
    """One persistent TLS connection per virtual user, reopened after any failure."""

    def __init__(self, base):
        parts = urlsplit(base)
        self.host, self.port = parts.hostname, parts.port or 443
        self.pool = {}  # a user is one task per round, so one thread at a time touches its entry
        self.context = ssl.create_default_context()

    def connection(self, user):
        if user not in self.pool:
            self.pool[user] = http.client.HTTPSConnection(
                self.host, self.port, timeout=10, context=self.context)
        return self.pool, self.pool[user]

    def __call__(self, user, method, path, cookie=None, body=None):
        """(status, elapsed_ms, set-cookie list, body bytes). Errors give status None."""
        pool, conn = self.connection(user)
        headers = {"accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        if cookie:
            headers["cookie"] = cookie
        before = time.perf_counter()
        try:
            conn.request(method, path, body=data, headers=headers)
            reply = conn.getresponse()
            payload = reply.read()
            status, cookies = reply.status, reply.msg.get_all("set-cookie") or []
        except Exception:
            pool.pop(user, None)
            conn.close()
            return None, (time.perf_counter() - before) * 1000, [], b""
        return status, (time.perf_counter() - before) * 1000, cookies, payload


def window_rounds(request, clock, sleep, pool, *, users, seconds, route, cookie, phase, rows,
                  label, not_before=None):
    """Whole rounds of one request per user, one round a second, until the window is spent.

    `end - start` may differ from `seconds` by a few float ulps; the eligibility test allows
    for that (`latency.WINDOW_EPSILON`), so the start needs no snapping. A window that must
    follow another waits for it and never starts before it ended.
    """
    if not_before is not None and clock() < not_before:
        sleep(not_before - clock())
    start = max(clock(), not_before or 0.0)
    end = start + seconds
    while clock() + 1 <= end:
        began = clock()
        done = list(pool.map(lambda u: (u, request(u, "GET", route, cookie)), range(users)))
        for user, (status, elapsed, _, _) in done:
            rows.append({"route": label, "phase": phase, "user": user, "started_at": began,
                         "elapsed_ms": elapsed, "ended_at": began + elapsed / 1000,
                         "status_code": status, "error": None if status else "request_failed"})
        pause = 1 - (clock() - began)
        if pause > 0:
            sleep(pause)
    return start, end


def run(config, request, clock, sleep, emit):
    rows, users = [], config["users"]
    email = f"latency-{secrets.token_hex(6)}@example.com"
    password = secrets.token_urlsafe(18)
    credentials = {"email": email, "password": password}
    status, _, _, _ = request(0, "POST", "/api/media/auth/register", None, credentials)
    if status != 201:
        emit(RESULT, {"ok": False, "stage": "register", "status": status})
        return 1
    status, _, cookies, _ = request(0, "POST", "/api/media/auth/login", None, credentials)
    if status != 200 or not cookies:
        emit(RESULT, {"ok": False, "stage": "login", "status": status})
        return 1
    cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
    pool = ThreadPoolExecutor(max_workers=max(users, config["logins"]))
    warm_start, warm_end = window_rounds(
        request, clock, sleep, pool, users=users, seconds=config["warmup"], route=STATUS_ROUTE,
        cookie=cookie, phase="warmup", rows=rows, label="status")
    s_start, s_end = window_rounds(
        request, clock, sleep, pool, users=users, seconds=config["seconds"], route=STATUS_ROUTE,
        cookie=cookie, phase="timed", rows=rows, label="status", not_before=warm_end)
    for route in OTHER_ROUTES:
        path = route.format(random=uuid.uuid4())
        window_rounds(request, clock, sleep, pool, users=10, seconds=config["other_seconds"],
                      route=path, cookie=cookie, phase="timed", rows=rows,
                      label=route.split("?")[0])
    began = clock()
    logins = list(pool.map(
        lambda u: (u, request(u, "POST", "/api/media/auth/login", None, credentials)),
        range(config["logins"])))
    for user, (code, elapsed, _, _) in logins:
        rows.append({"route": "login", "phase": "timed", "user": user, "started_at": began,
                     "elapsed_ms": elapsed, "ended_at": began + elapsed / 1000,
                     "status_code": code, "error": None if code else "request_failed"})
    l_end = max(r["ended_at"] for r in rows if r["route"] == "login")
    pool.shutdown()
    text = "".join(
        f"{r['route']},{r['phase']},{r['user']},{r['started_at']:.10f},{r['ended_at']:.10f},"
        f"{r['elapsed_ms']:.3f},{r['status_code'] or 0},{r['error'] or ''}\n" for r in rows)
    packed = base64.b64encode(zlib.compress(text.encode(), 9)).decode()
    chunks = [packed[i:i + CHUNK] for i in range(0, len(packed), CHUNK)] or [""]
    for index, chunk in enumerate(chunks):
        print(f"{SAMPLES} {index} {len(chunks)} {chunk}", flush=True)
    timed = [r for r in rows if r["phase"] == "timed"]
    emit(RESULT, {
        "ok": True, "samples_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "samples_length": len(text), "chunks": len(chunks), "users": users,
        "routes": {label: describe([r for r in timed if r["route"] == label])
                   for label in sorted({r["route"] for r in timed})},
        "windows": {
            "status": {"started_at": s_start, "ended_at": s_end, "warmup_started_at": warm_start,
                       "warmup_ended_at": warm_end, "booked_deadline": s_end + 600},
            "login": {"started_at": began, "ended_at": l_end, "warmup_started_at": began,
                      "warmup_ended_at": began, "booked_deadline": l_end + 600},
        },
        "python": sys.version.split()[0], "cpus": os.cpu_count(),
    })
    return 0


def emit(marker, payload):
    print(f"{marker} {json.dumps(payload, sort_keys=True)}", flush=True)


def main():
    base = os.environ["DC2_BASE_URL"]
    config = {"users": int(os.environ.get("DC2_USERS", "50")),
              "seconds": int(os.environ.get("DC2_SECONDS", "180")),
              "warmup": int(os.environ.get("DC2_WARMUP", "5")),
              "other_seconds": int(os.environ.get("DC2_OTHER_SECONDS", "20")),
              "logins": int(os.environ.get("DC2_LOGINS", "20"))}
    return run(config, Requester(base), time.monotonic, time.sleep, emit)


if __name__ == "__main__":
    raise SystemExit(main())
