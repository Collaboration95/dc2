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
