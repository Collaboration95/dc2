import pytest
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.workers import drain, inventory, replay, start, worker_inventory


def launch(config, fake, journal, clock, count=1, **kwargs):
    return start(config, fake, journal, count=count, deadline=1000, clock=clock, **kwargs)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_batch_and_fourth_cap(config, fake, journal, clock, count):
    launched = launch(config, fake, journal, clock, count)
    assert len(launched) == count
    with journal.locked() as state:
        assert worker_inventory(config, fake, state, deadline=1000)[1] == count
        for record in state["launches"].values():
            assert "--burst" in record["payload"]["overrides"]["containerOverrides"][0]["command"]
            assert (
                record["rq_name"]
                in record["payload"]["overrides"]["containerOverrides"][0]["command"]
            )
    with pytest.raises(OperationError, match="cap"):
        launch(config, fake, journal, clock, 4 - count)


def test_inventory_all_pages_mixed_digest_and_stopping(config, fake, journal, clock):
    fake.add_task("worker:1", status="PENDING")
    fake.add_task("worker:2", status="PROVISIONING")
    fake.add_task("worker:1", status="STOPPING")
    with pytest.raises(OperationError, match="cap"):
        launch(config, fake, journal, clock)
    assert any(c[2].get("nextToken") for c in fake.calls if c[1] == "list-tasks")


def test_lost_response_replays_identical_payload_after_restart(config, fake, journal, clock):
    fake.lost = True
    with pytest.raises(OperationError, match="reservation retained"):
        launch(config, fake, journal, clock)
    with journal.locked() as state:
        token, record = next(iter(state["launches"].items()))
        assert record["status"] == "uncertain"
    restarted = Journal(journal.path, station="station-a", environment="demo")
    config["task_definitions"]["worker"] = "worker:2"
    replay(config, fake, restarted, token, deadline=1000, clock=clock)
    requests = [c[2] for c in fake.calls if c[1] == "run-task"]
    assert requests[0] == requests[1]
    assert len(fake.tokens) == 1


def test_reservation_precedes_run_and_stale_list_never_releases(config, fake, journal, clock):
    original = fake.call

    def call(service, op, payload, **kw):
        if op == "run-task":
            import json

            saved = json.loads(journal.path.read_text())
            assert payload["clientToken"] in saved["launches"]
        return original(service, op, payload, **kw)

    fake.call = call
    fake.lost = True
    with pytest.raises(OperationError, match="reservation retained"):
        launch(config, fake, journal, clock)
    fake.stale_list = True
    with journal.locked() as state:
        assert worker_inventory(config, fake, state, deadline=1000)[1] == 1
    with pytest.raises(OperationError, match="cap"):
        launch(config, fake, journal, clock, 3)


def test_partial_failure_and_expired_token_fail_closed(config, fake, journal, clock):
    fake.partial = True
    with pytest.raises(OperationError, match="Partial"):
        launch(config, fake, journal, clock)
    with journal.locked() as state:
        token = next(iter(state["launches"]))
        assert (
            worker_inventory(config, fake, state, deadline=1000)[1] == 2
        )  # unknown + visible task
    clock.now = 2000
    with pytest.raises(OperationError, match="expired"):
        replay(config, fake, journal, token, deadline=3000, clock=clock)


def test_prewarm_is_explicit_finite_and_no_attempt_retry(config, fake, journal, clock):
    launch(config, fake, journal, clock, prewarm=True)
    request = next(c[2] for c in fake.calls if c[1] == "run-task")
    command = request["overrides"]["containerOverrides"][0]["command"]
    assert "--burst" not in command
    assert "--cloud-deadline" in command
    assert not any("retry" in str(c) for c in fake.calls)
    with journal.locked() as state:
        state["paused"] = True
        journal.save(state)
    with pytest.raises(OperationError, match="paused"):
        launch(config, fake, journal, clock)


def test_acknowledged_but_missing_describe_is_not_free_slot(config, fake, journal, clock):
    arn = launch(config, fake, journal, clock)[0]
    del fake.tasks[arn]
    with journal.locked() as state:
        with pytest.raises(OperationError, match="missing"):
            worker_inventory(config, fake, state, deadline=1000)


def test_drain_collects_current_last_racing_claims(config, fake, journal, clock):
    arn = launch(config, fake, journal, clock)[0]
    sent = []
    observations = 0

    def observe(task, name):
        nonlocal observations
        observations += 1
        if observations >= 3:
            fake.tasks[arn]["lastStatus"] = "STOPPED"
        return {
            "fresh": True,
            "claims_stopped": observations >= 3,
            "claims": ["current", "last"] if observations == 1 else ["racing"],
            "outcomes": {"current": "succeeded", "last": "failed", "racing": "abandoned"},
        }

    def warm(task, name):
        sent.append((task, name))
        return True

    with journal.locked() as state:
        receipt = drain(
            config,
            fake,
            journal,
            state,
            observe=observe,
            warm_shutdown=warm,
            deadline=1000,
            clock=clock,
            sleep=clock.sleep,
        )
        record = next(iter(state["launches"].values()))
        assert record["claims"] == ["current", "last", "racing"]
        assert receipt["status"] == "complete"
    assert len(sent) == 1
    assert not any(c[1] == "stop-task" for c in fake.calls)


def test_lost_warm_ack_never_second_signal(config, fake, journal, clock):
    arn = launch(config, fake, journal, clock)[0]
    sent = []

    def warm(task, name):
        sent.append(task)
        return False

    def observed(task, name):
        fake.tasks[arn]["lastStatus"] = "STOPPED"
        return {
            "fresh": True,
            "claims_stopped": True,
            "claims": ["claim"],
            "outcomes": {"claim": "succeeded"},
        }

    with journal.locked() as state:
        # First observation sets STOPPED but inventory already identified it running.
        with pytest.raises(OperationError, match="acknowledged"):
            drain(
                config,
                fake,
                journal,
                state,
                observe=observed,
                warm_shutdown=warm,
                deadline=1000,
                clock=clock,
                sleep=clock.sleep,
            )
    assert len(sent) == 1


def test_timeout_is_forced_interruption_not_success(config, fake, journal, clock):
    launch(config, fake, journal, clock)

    def observed(*a):
        return {"fresh": True, "claims_stopped": False, "claims": ["claim"], "outcomes": {}}

    with journal.locked() as state:
        with pytest.raises(OperationError, match="not successful"):
            drain(
                config,
                fake,
                journal,
                state,
                observe=observed,
                warm_shutdown=lambda *a: True,
                deadline=1000,
                clock=clock,
                sleep=clock.sleep,
            )
        assert next(iter(state["launches"].values()))["drain"] == "interrupted"
    assert clock.now == 400
    assert any(c[1] == "stop-task" for c in fake.calls)


def test_unknown_or_stale_worker_registration(config, fake, journal, clock):
    fake.add_task("worker:1")
    with journal.locked() as state:
        with pytest.raises(OperationError, match="Uncorrelated"):
            drain(
                config,
                fake,
                journal,
                state,
                observe=lambda *a: {},
                warm_shutdown=lambda *a: True,
                deadline=1000,
                clock=clock,
                sleep=clock.sleep,
            )
    fake.tasks = {a: t for a, t in fake.tasks.items() if t["taskDefinitionArn"] != "worker:1"}
    launch(config, fake, journal, clock)
    with journal.locked() as state:
        with pytest.raises(OperationError, match="Stale"):
            drain(
                config,
                fake,
                journal,
                state,
                observe=lambda *a: {"fresh": False},
                warm_shutdown=lambda *a: True,
                deadline=1000,
                clock=clock,
                sleep=clock.sleep,
            )


def test_repeated_pagination_token_refused(config, fake):
    fake.call = lambda *a, **k: {"taskArns": [], "nextToken": "repeat"}
    with pytest.raises(OperationError, match="pagination"):
        inventory(config, fake, deadline=1000)


def test_mismatched_designated_station_refuses_launch(config, fake, journal, clock):
    config["operator_station"] = "station-b"
    with pytest.raises(OperationError, match="station"):
        launch(config, fake, journal, clock)
    assert not fake.calls
