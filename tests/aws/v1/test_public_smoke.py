"""Gateway-contract release smoke against a fake Gateway; no network, no AWS."""

import json
import time

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1.public_smoke import PublicSmoke, load_credentials, validate_base_url

SECURE_COOKIE = "access_token=jwt-value; HttpOnly; Secure; SameSite=Strict; Path=/"
CREDENTIALS = {"email": "smoke@example.invalid", "password": "correct horse battery"}


class Gateway:
    """Behaves like the deployed contracts; each flag breaks exactly one of them."""

    def __init__(self, **faults):
        self.faults, self.requests = faults, []

    def __call__(self, method, url, headers, body, timeout):
        path = url.split("//", 1)[1].split("/", 1)[1]
        path = "/" + path
        self.requests.append((method, path, headers.get("cookie"), body))
        json_ = lambda status, data, cookies=(): (  # noqa: E731
            status,
            {"set-cookie": list(cookies)},
            json.dumps(data).encode(),
        )
        if path == "/api/media/health":
            return json_(200, {"status": "ok", "service": "media"})
        if path == "/api/processing/health":
            version = self.faults.get("schema", 1)
            return json_(200, {"status": "ok", "service": "processing", "schema_version": version})
        if path == "/api/media/auth/login":
            replies = self.faults.get("login_replies")  # statuses in order; the last one repeats
            status = (replies.pop(0) if len(replies) > 1 else replies[0]) if replies else 200
            if status != 200:
                return json_(status, {"error": "unavailable"})
            if self.faults.get("login"):
                return json_(401, {"error": "invalid email or password"})
            cookie = self.faults.get("cookie", SECURE_COOKIE)
            return json_(200, {"id": "u", "email": "e", "role": "user"}, [cookie] if cookie else [])
        authed = headers.get("cookie") == "access_token=jwt-value"
        if path == "/api/media/jobs":
            if not authed:
                return json_(200 if self.faults.get("open_authorizer") else 401, [])
            return json_(200, [])
        if path.startswith("/api/processing/jobs?asset_ids="):
            return json_(200, [{"id": "leak"}] if self.faults.get("leak") else [])
        if path == "/api/media/uploads/reservations":
            data = {
                "reservation_id": "r",
                "asset_id": "a",
                "expires_at": "2026-10-16T00:15:00Z",
                "upload": {"url": "https://bucket", "fields": {}},
                "finalize_url": "/uploads/reservations/r/finalize",
            }
            return json_(self.faults.get("reserve", 201), data)
        return json_(404, {})


def smoke(gateway, **kwargs):
    return PublicSmoke("https://gw.example.invalid", dict(CREDENTIALS), http=gateway, **kwargs)


def run(check, owner="media"):
    return check(owner, {"fn": "2"}, None, deadline=time.monotonic() + 30)


def test_media_release_exercises_every_public_contract_and_one_expiring_reservation():
    gateway = Gateway()
    check = smoke(gateway)
    assert run(check) is True
    assert set(check.checks.values()) == {"PASS"}
    paths = [(m, p) for m, p, *_ in gateway.requests]
    assert ("POST", "/api/media/uploads/reservations") in paths
    assert sum(p == "/api/media/uploads/reservations" for _, p in paths) == 1
    assert not any("finalize" in p for _, p in paths)  # never finalized: it simply expires
    authed = [c for m, p, c, b in gateway.requests if p == "/api/media/jobs" and c]
    assert authed == ["access_token=jwt-value"]


def test_processing_release_is_read_only():
    gateway = Gateway()
    assert run(smoke(gateway), "processing") is True
    assert not any(m == "POST" and "reservations" in p for m, p, *_ in gateway.requests)


def test_reservation_can_be_skipped_for_a_side_effect_free_run():
    gateway = Gateway()
    assert run(smoke(gateway, reserve=False)) is True
    assert not any("reservations" in p for _, p, *_ in gateway.requests)


@pytest.mark.parametrize(
    "fault,failed",
    [
        ({"open_authorizer": True}, "anonymous-denied"),
        ({"schema": 2}, "processing-health"),
        ({"cookie": "access_token=jwt-value; Path=/"}, "login"),
        ({"cookie": None}, "login"),
        ({"leak": True}, "processing-jobs"),
        ({"reserve": 500}, "upload-reserve"),
    ],
)
def test_each_broken_contract_fails_the_candidate_by_name(fault, failed):
    check = smoke(Gateway(**fault))
    assert run(check) is False
    assert check.checks[failed] == "FAIL"
    assert [f.split(":")[0] for f in check.failures] == [failed]


def test_failed_login_skips_authenticated_checks_and_never_records_the_credentials():
    check = smoke(Gateway(login=True))
    assert run(check) is False
    assert "media-jobs" not in check.checks
    assert CREDENTIALS["password"] not in json.dumps(check.receipt)


WAKE = (5, 10, 15)


def waking(gateway, sleeps, **kwargs):
    """A smoke for a database that may be paused: three pauses, recorded instead of slept."""
    return smoke(gateway, sleep=sleeps.append, wake_backoff=WAKE, **kwargs)


def test_a_release_smoke_does_not_retry_unless_asked_to():
    # After its migration the database is awake, so a 503 there is a real failure at once.
    gateway = Gateway(login_replies=[503, 200])
    check = smoke(gateway, sleep=lambda _s: pytest.fail("must not pause"))
    assert run(check) is False
    assert check.failures == ["login:503"] and check.receipt["login_attempts"] == [503]
    assert sum(p == "/api/media/auth/login" for _, p, *_ in gateway.requests) == 1


def test_a_database_that_is_still_waking_is_waited_for_and_the_attempts_are_recorded():
    sleeps = []
    gateway = Gateway(login_replies=[503, 504, 200])
    check = waking(gateway, sleeps)
    assert run(check) is True
    assert set(check.checks.values()) == {"PASS"}
    assert sleeps == [5, 10]
    assert check.receipt["login_attempts"] == [503, 504, 200]
    # The first calls that need no database are made once; only the login is repeated.
    paths = [p for _, p, *_ in gateway.requests]
    assert paths.count("/api/media/health") == 1 and paths.count("/api/media/auth/login") == 3
    # A later run starts its record afresh.
    assert run(check) is True and check.receipt["login_attempts"] == [200]


def test_a_transport_failure_while_the_database_wakes_is_retried_without_leaking_detail():
    sleeps, seen = [], []
    gateway = Gateway()

    def flaky(method, url, headers, body, timeout):
        if url.endswith("/auth/login") and not seen:
            seen.append(url)
            raise TimeoutError("secret-host.internal timed out")
        return gateway(method, url, headers, body, timeout)

    check = smoke(flaky, sleep=sleeps.append, wake_backoff=WAKE)
    assert run(check) is True
    assert check.receipt["login_attempts"] == ["error", 200] and sleeps == [5]
    assert "secret-host" not in json.dumps(check.receipt)


def test_a_503_that_outlasts_the_pauses_is_still_a_failed_login():
    sleeps = []
    check = waking(Gateway(login_replies=[503]), sleeps)
    assert run(check) is False
    assert check.failures == ["login:503"]
    assert sleeps == [5, 10, 15] and check.receipt["login_attempts"] == [503] * 4
    assert "media-jobs" not in check.checks  # nothing authenticated runs without a session


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 429, 500])
def test_any_other_login_status_fails_at_once_even_when_waiting_is_allowed(status):
    sleeps = []
    check = waking(Gateway(login_replies=[status, 200]), sleeps)
    assert run(check) is False
    assert check.failures == [f"login:{status}"]
    assert sleeps == [] and check.receipt["login_attempts"] == [status]


def test_a_wake_retry_never_runs_past_the_deadline():
    sleeps = []
    now = [100.0]
    check = waking(Gateway(login_replies=[503]), sleeps, clock=lambda: now[0])
    # Three seconds left: not enough for the five-second pause plus another request.
    assert check("media", {}, None, deadline=103.0) is False
    assert sleeps == [] and check.receipt["login_attempts"] == [503]
    assert check.failures == ["login:503"]
    # Room for the first pause only (the clock does not move while sleeping in this test).
    sleeps.clear()
    now[0] = 100.0
    assert check("media", {}, None, deadline=100.0 + 5 + 1 + 0.5) is False
    assert sleeps == [5] and check.receipt["login_attempts"] == [503, 503]


def test_transport_errors_fail_the_check_without_leaking_detail():
    def broken(*args):
        raise ConnectionError("secret-host.internal refused")

    check = smoke(broken)
    assert run(check) is False
    assert "secret-host" not in json.dumps(check.receipt)


def test_expired_deadline_is_a_hard_error_not_a_pass():
    with pytest.raises(OperationError):
        smoke(Gateway())("media", {}, None, deadline=time.monotonic() - 1)


@pytest.mark.parametrize(
    "url",
    [
        "http://gw.example.invalid",
        "https://user:pw@gw.example.invalid",
        "https://gw.example.invalid/prod",
        "https://gw.example.invalid?x=1",
        "ftp://gw.example.invalid",
    ],
)
def test_base_url_must_be_a_plain_https_origin(url):
    with pytest.raises(OperationError):
        validate_base_url(url)
    assert validate_base_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_credentials_file_must_be_private_exact_and_string_valued(tmp_path):
    path = tmp_path / "creds.json"
    path.write_text(json.dumps(CREDENTIALS))
    path.chmod(0o600)
    assert load_credentials(path) == CREDENTIALS
    path.write_text(json.dumps({**CREDENTIALS, "extra": "x"}))
    with pytest.raises(OperationError):
        load_credentials(path)
    path.chmod(0o644)
    with pytest.raises(OperationError, match="private"):
        load_credentials(path)


def test_urllib_transport_refuses_redirects_and_returns_every_cookie():
    from email.message import Message

    from scripts.aws.v1 import public_smoke

    headers = Message()
    headers["Set-Cookie"] = "a=1"
    headers["Set-Cookie"] = "b=2"
    assert public_smoke._headers(headers)["set-cookie"] == ["a=1", "b=2"]
    assert public_smoke._NoRedirect().redirect_request() is None
