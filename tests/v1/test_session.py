"""Failure-oriented offline control-plane contracts; no AWS credentials/network."""

import json
import time

import pytest

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1.session import Session


class Fake:
    def __init__(self):
        self.calls, self.functions, self.mappings, self.rules, self.tasks = [], {}, {}, {}, {}
        self.fail = None

    def call(self, service, operation, payload, *, deadline):
        assert deadline > time.monotonic()
        self.calls.append((service, operation, payload))
        if operation == self.fail:
            raise RuntimeError("injected transport failure")
        if operation == "put-function-concurrency":
            self.functions[payload["FunctionName"]] = payload["ReservedConcurrentExecutions"]
        if operation == "get-function-concurrency":
            return {"ReservedConcurrentExecutions": self.functions[payload["FunctionName"]]}
        if operation == "update-event-source-mapping":
            self.mappings[payload["UUID"]] = "Enabled" if payload["Enabled"] else "Disabled"
        if operation == "get-event-source-mapping":
            return {"State": self.mappings[payload["UUID"]]}
        if operation in {"enable-rule", "disable-rule"}:
            self.rules[payload["Name"]] = "ENABLED" if operation == "enable-rule" else "DISABLED"
        if operation == "describe-rule":
            return {"State": self.rules[payload["Name"]]}
        if operation == "list-tasks":
            return {"taskArns": list(self.tasks)}
        if operation == "describe-tasks":
            return {"tasks": [self.tasks[a] for a in payload["tasks"]]}
        if operation == "run-task":
            arn = "task/" + payload["clientToken"]
            self.tasks[arn] = {
                "taskArn": arn,
                "taskDefinitionArn": "worker:1",
                "lastStatus": "RUNNING",
            }
            return {"tasks": [self.tasks[arn]]}
        return {}


@pytest.fixture
def rig(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    journal = Journal(directory / "session.json", station="test", environment="v1-local")
    journal.initialize(verified_empty=True, exclusive_station=True)
    config = {
        "operator_station": "test",
        "environment_id": "v1-local",
        "functions": {"media": 2, "processing": 2, "authorizer": 1},
        "intake_functions": ["media"],
        "mappings": ["commands", "results"],
        "schedules": ["media-repair", "processing-repair"],
        "cluster": "local",
        "task_definitions": {"worker": "worker:1"},
        "network": {
            "subnets": ["subnet-local"],
            "security_groups": ["sg-local"],
            "assign_public_ip": "ENABLED",
        },
        "session_end_epoch": time.time() + 600,
        "worker_lifetime_seconds": 60,
    }
    fake = Fake()
    return Session(config, fake, journal), fake, journal


def yes(**kwargs):
    return True


def state(journal):
    return json.loads(journal.path.read_text())


def test_open_close_retains_queued_work_and_never_launches(rig):
    session, fake, journal = rig
    assert session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)["worker_starts"] == 0
    assert fake.functions == {"media": 2, "processing": 2, "authorizer": 1}
    result = session.close(
        drain=yes,
        outcomes=lambda **kw: {"queued": 4, "succeeded": 1},
        deadline=time.monotonic() + 5,
    )
    assert result["queued_work"] == "retained"
    assert result["database_pause"] == "NOT_OBSERVED"
    assert set(fake.functions.values()) == {0}
    assert set(fake.mappings.values()) == {"Disabled"}
    assert set(fake.rules.values()) == {"DISABLED"}
    assert state(journal)["close_outcomes"]["queued"] == 4
    assert all(
        operation not in {"purge-queue", "run-task", "stop-db-cluster"}
        for _, operation, _ in fake.calls
    )
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    assert state(journal)["session"] == "open"


def test_open_failure_keeps_launches_paused_and_intake_zero(rig):
    session, fake, journal = rig
    with pytest.raises(OperationError):
        session.open(ready=lambda **kw: False, repair=yes, deadline=time.monotonic() + 5)
    assert fake.functions["media"] == 0
    assert state(journal)["session"] == "opening"
    assert state(journal)["paused"]
    with pytest.raises(OperationError):
        session.batch(count=1, deadline=time.monotonic() + 5)


def test_failed_drain_still_disables_wake_sources_and_is_retryable(rig):
    session, fake, journal = rig
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    with pytest.raises(OperationError, match="Partial close"):
        session.close(
            drain=lambda **kw: False,
            outcomes=lambda **kw: {"queued": 1},
            deadline=time.monotonic() + 5,
        )
    assert state(journal)["session"] == "closing"
    assert state(journal)["session_failures"] == ["drain"]
    assert set(fake.functions.values()) == {0}
    assert set(fake.rules.values()) == {"DISABLED"}
    session.close(drain=yes, outcomes=lambda **kw: {"queued": 1}, deadline=time.monotonic() + 5)
    assert state(journal)["session"] == "closed"


def test_lost_launch_response_reserves_slot_across_restart(rig):
    session, fake, journal = rig
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    fake.fail = "run-task"
    with pytest.raises(OperationError, match="reserved slot"):
        session.batch(count=1, deadline=time.monotonic() + 5, token_factory=lambda: "lost")
    assert state(journal)["launches"]["lost"]["status"] == "uncertain"
    fake.fail = None
    restarted = Session(session.config, fake, journal)
    with pytest.raises(OperationError, match="cap reached"):
        restarted.batch(count=3, deadline=time.monotonic() + 5)
    assert len(state(journal)["launches"]) == 1
    with pytest.raises(OperationError, match="Partial close"):
        restarted.close(
            drain=yes, outcomes=lambda **kw: {"queued": 1}, deadline=time.monotonic() + 5
        )
    assert state(journal)["session"] == "closing"


def test_finite_batch_cap_and_stopped_inventory_releases_slot(rig):
    session, fake, journal = rig
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    tasks = session.batch(count=3, deadline=time.monotonic() + 5)
    assert len(tasks) == 3
    payload = state(journal)["launches"].values().__iter__().__next__()["payload"]
    command = payload["overrides"]["containerOverrides"][0]["command"]
    assert "processing.worker.sqs" in command and "--name" in command
    assert "--burst" not in command
    with pytest.raises(OperationError, match="cap reached"):
        session.batch(count=1, deadline=time.monotonic() + 5)
    fake.tasks[tasks[0]]["lastStatus"] = "STOPPED"
    assert len(session.batch(count=1, deadline=time.monotonic() + 5)) == 1


def test_concurrent_station_and_release_interlocks(rig):
    session, fake, journal = rig
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    with journal.locked() as current:
        with pytest.raises(OperationError, match="busy"):
            session.batch(count=1, deadline=time.monotonic() + 5)
        current["pending_release"] = {"owner": "media"}
        journal.save(current)
    with pytest.raises(OperationError, match="Open unpaused"):
        session.batch(count=1, deadline=time.monotonic() + 5)
    assert not fake.tasks


def test_explicit_replay_keeps_identical_payload_and_token(rig):
    session, fake, journal = rig
    session.open(ready=yes, repair=yes, deadline=time.monotonic() + 5)
    fake.fail = "run-task"
    with pytest.raises(OperationError):
        session.batch(count=1, deadline=time.monotonic() + 5, token_factory=lambda: "lost")
    original = state(journal)["launches"]["lost"]["payload"]
    session.config["task_definitions"]["worker"] = "worker:2"
    fake.fail = None
    assert session.replay("lost", deadline=time.monotonic() + 5) == "task/lost"
    assert fake.calls[-1][2] == original
    assert len(state(journal)["launches"]) == 1
    with pytest.raises(OperationError, match="expired"):
        session.replay("lost", deadline=time.monotonic() + 5, epoch=lambda: time.time() + 9999)
