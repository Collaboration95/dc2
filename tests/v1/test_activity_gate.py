"""V2-live (AD-27): idle minute ticks skip SQL so Aurora can pause; nothing pending is missed."""

import time

import pytest

from runtime_support import activity
from runtime_support.activity import MARGIN_SECONDS, MAX_QUIET_SECONDS, Activity

TOUCHED, QUIET = "/dc2/dc2-live/activity/x/touched", "/dc2/dc2-live/activity/x/quiet"


class Ssm:
    def __init__(self, touched="0", quiet="0"):
        self.values = {TOUCHED: touched, QUIET: quiet}
        self.puts, self.fail = [], False

    def get_parameter(self, Name):
        if self.fail:
            raise TimeoutError("ssm unreachable")
        return {"Parameter": {"Value": self.values[Name]}}

    def put_parameter(self, Name, Value, Type, Overwrite):
        if self.fail:
            raise TimeoutError("ssm unreachable")
        assert Type == "String" and Overwrite is True
        self.puts.append((Name, Value))
        self.values[Name] = Value


@pytest.fixture(autouse=True)
def fresh_touch_cache(monkeypatch):
    monkeypatch.setattr(activity, "_last_touch", {})


def gate(ssm, now=10_000.0):
    return Activity(TOUCHED, QUIET, client=ssm, clock=lambda: now)


def test_a_domain_is_quiet_only_after_a_check_that_postdates_its_last_write_by_the_margin():
    checked = 9_000
    assert gate(Ssm(str(checked - MARGIN_SECONDS - 1), f"{checked} 20000")).quiet()
    # A write that a check could have missed (within the margin) keeps the ticks on SQL.
    assert not gate(Ssm(str(checked - MARGIN_SECONDS + 1), f"{checked} 20000")).quiet()
    # Something scheduled (a lease, a retry, an outbox replay) is due: SQL again.
    assert not gate(Ssm("0", f"{checked} 10000")).quiet()


def test_every_tick_sweeps_sql_once_the_last_check_is_half_an_hour_old():
    # The bound on a lost touch: the quiet value ages out whatever it promised.
    assert gate(Ssm("0", "9000 99999"), now=9_000 + MAX_QUIET_SECONDS - 1).quiet()
    assert not gate(Ssm("0", "9000 99999"), now=9_000 + MAX_QUIET_SECONDS).quiet()
    assert MAX_QUIET_SECONDS == 30 * 60


MALFORMED = [
    ("0", "inf inf"), ("0", "nan 20000"), ("-inf", "9000 20000"), ("nan", "9000 20000"),
    ("0", "10500 20000"),  # checked in the future
    ("0", "9000000 9999999999999"),  # milliseconds: a check far in the future
]


@pytest.mark.parametrize(("touched", "quiet"), MALFORMED)
def test_non_finite_or_out_of_range_markers_are_never_quiet(touched, quiet):
    assert not gate(Ssm(touched, quiet)).quiet()


@pytest.mark.parametrize("owner", ["processing", "media"])
@pytest.mark.parametrize(("touched", "quiet"), [("0", "inf inf"), ("0", "99999999999999 inf")])
async def test_a_malformed_marker_sends_each_repair_tick_to_sql(
        monkeypatch, quiet_markers, owner, touched, quiet):
    import importlib

    handlers = importlib.import_module(f"{owner}.handlers")
    deny_database(monkeypatch, handlers)
    quiet_markers.values.update({TOUCHED: touched, QUIET: quiet})
    with pytest.raises(NoDatabase):
        await handlers.invoke({}, None, "repair")


@pytest.mark.parametrize(("touched", "quiet"), [("0", "inf inf"), ("0", "99999999999999 inf")])
async def test_a_malformed_marker_sends_the_launcher_tick_to_sql(quiet_markers, touched, quiet):
    from processing import launcher_aws

    quiet_markers.values.update({TOUCHED: touched, QUIET: quiet})
    with pytest.raises(KeyError):  # past the gate: config_from_environ, unset in this test
        await launcher_aws.run({"source": "aws.events"}, None)


@pytest.mark.parametrize("quiet", ["0", "", "not numbers", "1 2 3"])
def test_any_doubt_about_the_markers_means_run_sql(quiet):
    assert not gate(Ssm("0", quiet)).quiet()
    unreachable = Ssm("0", "9000 20000")
    unreachable.fail = True
    assert not gate(unreachable).quiet()


def test_a_write_is_recorded_before_it_happens_at_most_once_a_minute_and_never_blocks():
    ssm = Ssm()
    gate(ssm, now=1_000).touch()
    gate(ssm, now=1_030).touch()
    gate(ssm, now=1_061).touch()
    assert ssm.puts == [(TOUCHED, "1000"), (TOUCHED, "1061")]
    ssm.fail = True
    activity._last_touch.clear()
    gate(ssm, now=2_000).touch()  # never fails the request; the 30 min sweep covers it
    assert ssm.puts[-1] == (TOUCHED, "1061")


def test_a_pass_records_quiet_only_when_nothing_is_due_now_and_never_for_long():
    ssm = Ssm()
    gate(ssm).record(9_000, 0.0)  # work due now: nothing written, the next tick runs SQL
    gate(ssm).record(9_000, 8_999.0)
    assert ssm.puts == []
    gate(ssm).record(9_000, 9_500.0)
    gate(ssm).record(9_000, None)
    assert ssm.puts == [(QUIET, "9000 9500"), (QUIET, f"9000 {9_000 + MAX_QUIET_SECONDS}")]
    ssm.fail = True
    gate(ssm).record(9_000, None)  # a failed write only costs SQL


def test_the_gate_exists_only_where_the_stack_deployed_its_markers():
    assert Activity.from_environ("MEDIA", {}) is None
    built = Activity.from_environ("MEDIA", {"MEDIA_ACTIVITY_TOUCHED_PARAMETER": TOUCHED,
                                            "MEDIA_ACTIVITY_QUIET_PARAMETER": QUIET})
    assert (built.touched, built.quiet_name) == (TOUCHED, QUIET)


# ---- the ticks themselves -------------------------------------------------------------
class NoDatabase(Exception):
    """Raised by anything that would read settings or open a connection."""


def deny_database(monkeypatch, module):
    def refuse(*_args, **_kwargs):
        raise NoDatabase

    monkeypatch.setattr(module, "get_settings", refuse)
    monkeypatch.setattr("runtime_support.lambda_db.shared_engine", refuse)


@pytest.fixture
def quiet_markers(monkeypatch):
    ssm = Ssm("0", f"{int(time.time())} 99999999999")  # checked just now, nothing due
    monkeypatch.setattr(activity, "_ssm_client", lambda: ssm)
    for prefix in ("MEDIA", "PROCESSING"):
        monkeypatch.setenv(f"{prefix}_ACTIVITY_TOUCHED_PARAMETER", TOUCHED)
        monkeypatch.setenv(f"{prefix}_ACTIVITY_QUIET_PARAMETER", QUIET)
    return ssm


@pytest.mark.parametrize("owner", ["processing", "media"])
async def test_an_idle_repair_tick_opens_no_database_connection(monkeypatch, quiet_markers, owner):
    import importlib

    handlers = importlib.import_module(f"{owner}.handlers")
    deny_database(monkeypatch, handlers)
    assert await handlers.invoke({}, None, "repair") == {"skipped": "idle"}
    # With something due the same tick goes to SQL (here: refused by the stub).
    quiet_markers.values[QUIET] = "0"
    with pytest.raises(NoDatabase):
        await handlers.invoke({}, None, "repair")


@pytest.mark.parametrize(("owner", "mode"), [("processing", "command"), ("media", "result")])
async def test_a_consumer_records_its_write_before_touching_sql(
        monkeypatch, quiet_markers, owner, mode):
    import importlib

    handlers = importlib.import_module(f"{owner}.handlers")
    deny_database(monkeypatch, handlers)
    with pytest.raises(NoDatabase):
        await handlers.invoke({"Records": []}, None, mode)
    assert [name for name, _ in quiet_markers.puts] == [TOUCHED]


async def test_an_idle_launcher_tick_opens_no_connection_but_a_wake_still_does(quiet_markers):
    from processing import launcher_aws

    result = await launcher_aws.run({"source": "aws.events"}, None)
    assert result == {"service": "processing-launcher", "action": "tick", "outcome": "idle",
                      "skipped": "quiet"}
    # A wake (after a work send) and every control event bypass the gate.
    with pytest.raises(KeyError):  # reaches config_from_environ, which this test left unset
        await launcher_aws.run({"dc2_operation": "launcher", "action": "wake"}, None)


async def test_a_mutating_media_request_is_recorded_and_a_read_is_not(quiet_markers):
    from httpx import ASGITransport, AsyncClient

    from media.main import create_v1_app

    async with AsyncClient(transport=ASGITransport(app=create_v1_app()),
                           base_url="http://media") as client:
        await client.get("/health")
        assert quiet_markers.puts == []
        await client.post("/auth/logout")
    assert [name for name, _ in quiet_markers.puts] == [TOUCHED]


# ---- #244: the public Processing API is a marker writer --------------------------------
def processing_event(method, path, body=None, owner=None):
    from uuid import uuid4

    from contracts.v1 import Actor

    actor = Actor(str(owner or uuid4()), "publisher")
    return {
        "version": "2.0", "rawPath": "/api/processing" + path, "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": method},
                           "authorizer": {"lambda": actor.to_context()}},
        "body": body,
    }


@pytest.mark.parametrize(("method", "path", "body", "status"), [
    ("POST", "/jobs/{id}/retry", '{"retry_request_id": "%s"}', 202),
    ("DELETE", "/jobs/{id}", None, 204),
])
async def test_a_direct_processing_mutation_touches_before_it_commits_and_repair_then_runs_sql(
        monkeypatch, quiet_markers, method, path, body, status):
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from contracts.gateway import GatewayAdapter
    from processing import handlers, v1_api
    from processing.database import get_v1_session

    order = []

    async def mutation(*_args):
        order.append(("mutation", [name for name, _ in quiet_markers.puts]))

    monkeypatch.setattr(v1_api, "retry_owned" if method == "POST" else "cancel_owned",
                        AsyncMock(side_effect=mutation))
    deny_database(monkeypatch, handlers)
    assert await handlers.invoke({}, None, "repair") == {"skipped": "idle"}  # quiet start
    event = processing_event(method, path.format(id=uuid4()), body % uuid4() if body else None)
    app = v1_api.create_app()
    app.dependency_overrides[get_v1_session] = lambda: None  # the mutation is stubbed
    response = await GatewayAdapter(app, service="processing").invoke(event)
    assert response["statusCode"] == status
    assert order == [("mutation", [TOUCHED])]  # the marker was written before the mutation ran
    with pytest.raises(NoDatabase):  # the very next repair tick no longer trusts the old quiet
        await handlers.invoke({}, None, "repair")


async def test_processing_reads_and_health_write_no_marker(quiet_markers):
    from contracts.gateway import GatewayAdapter
    from processing import v1_api

    app = v1_api.create_app()
    for path in ("/health", "/jobs"):
        await GatewayAdapter(app, service="processing").invoke(processing_event("GET", path))
    assert quiet_markers.puts == []


# ---- #256: a lost marker write is bounded by the sweep, not by the next tick -----------
@pytest.fixture
def clocked(monkeypatch, quiet_markers):
    """Repair ticks read a controllable clock; the quiet snapshot is 600 s old at the start."""
    now = [100_000.0]
    build = Activity.from_environ.__func__
    monkeypatch.setattr(Activity, "from_environ", classmethod(
        lambda cls, prefix, environ=None, **kw: build(
            cls, prefix, environ, clock=lambda: now[0], **kw)))
    quiet_markers.values[QUIET] = f"{int(now[0]) - 600} 99999999999"
    return now


async def test_a_lost_touch_leaves_early_ticks_skipping_until_the_snapshot_ages_out(
        monkeypatch, quiet_markers, clocked):
    # Local, simulated clock and fake SSM: this is not AWS timing evidence (see AD-27).
    from processing import handlers

    deny_database(monkeypatch, handlers)
    checked = clocked[0] - 600
    # A correctly wired writer's put fails; the request and its SQL commit proceed regardless.
    quiet_markers.fail = True
    Activity.from_environ("PROCESSING").touch()
    quiet_markers.fail = False  # SSM recovers and serves the old, still valid quiet snapshot
    assert quiet_markers.puts == []
    for offset in (60, 120, 600):
        clocked[0] = 100_000.0 + offset
        assert await handlers.invoke({}, None, "repair") == {"skipped": "idle"}
    # A failed put is not cached as a touch, so the next request can still record activity.
    clocked[0] = 100_000.0 + 601
    Activity.from_environ("PROCESSING").touch()
    assert [name for name, _ in quiet_markers.puts] == [TOUCHED]
    # Suppose no later request ever arrives: the unconditional sweep is the only discovery.
    quiet_markers.values[TOUCHED] = "0"
    clocked[0] = checked + MAX_QUIET_SECONDS - 1
    assert await handlers.invoke({}, None, "repair") == {"skipped": "idle"}
    clocked[0] = checked + MAX_QUIET_SECONDS
    with pytest.raises(NoDatabase):
        await handlers.invoke({}, None, "repair")
