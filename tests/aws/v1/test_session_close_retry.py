"""#225: a close retries its own failed steps, and says which step failed and why.

r1018b: two CD teardowns failed `td-session-close` with only "Partial close; retry from retained
journal". The unresolved step was the launcher's SQL flag the first time (Aurora had just paused
and the Lambda that flips the flag waits on the database) and a repair-rule disable the second.
"""

import json
import time

import pytest
from v1_support import outputs

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1 import operations
from scripts.aws.v1.hooks import ATTEMPT_STATES, AttemptCounts, LauncherHooks, OwnerHooks
from scripts.aws.v1.operations import PlanTransport, config_from_outputs
from scripts.aws.v1.session import Session

LAUNCHER = operations.LAUNCHER


class Clock:
    """A virtual clock that the injected sleep advances, so a retry costs no real time."""

    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class SlowDatabase(PlanTransport):
    """A stack whose database is still resuming: the first calls of an operation fail."""

    def __init__(self, failures, launcher_failures=0):
        super().__init__()
        self.failures, self.launcher_failures = dict(failures), launcher_failures

    def call(self, service, operation, payload, *, deadline):
        if self.failures.get(operation):
            self.failures[operation] -= 1
            self.calls.append({"service": service, "operation": operation, "payload": payload})
            raise OperationError("injected: the database is resuming")
        event = payload.get("Payload") if isinstance(payload, dict) else None
        if operation == "invoke" and isinstance(event, dict) and event.get(
                "dc2_operation") == "launcher" and self.launcher_failures:
            self.launcher_failures -= 1
            self.calls.append({"service": service, "operation": operation, "payload": payload})
            # What a Lambda that timed out on the paused database answers.
            return {"StatusCode": 200, "FunctionError": "Unhandled",
                    "Payload": {"errorType": "ConnectionTimeout", "errorMessage": "secret-host"}}
        return super().call(service, operation, payload, deadline=deadline)


def build(tmp_path, cloud, *, retry=240):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    all_outputs = outputs() | {
        f"{LAUNCHER}FunctionName": "fn-launcher", f"{LAUNCHER}RuleName": "rule-launcher"}
    config, hooks, _ = config_from_outputs(all_outputs, station="s", environment="e2e")
    journal = Journal(directory / "session.json", station="s", environment="e2e")
    journal.initialize(verified_empty=True, exclusive_station=True)
    clock = Clock()
    session = Session(config, cloud, journal, clock=clock, sleep=clock.sleep)
    session.close_retry_seconds = retry
    owner = OwnerHooks(cloud, **hooks, sleep=lambda s: None)
    return session, journal, clock, LauncherHooks(owner, sleep=lambda s: None)


def zero_counts():
    return AttemptCounts(lambda _d: dict.fromkeys(ATTEMPT_STATES, 0))


def close(session, launcher):
    reader = zero_counts()
    return session.close(drain=reader.drain, outcomes=reader.outcomes,
                         deadline=time.monotonic() + 600, launcher=launcher)


def test_a_close_waits_out_a_database_that_is_still_resuming(tmp_path):
    # The launcher's flag step fails twice (a Lambda that timed out on the paused database) and
    # a repair-rule disable fails once; the close retries both and ends closed.
    cloud = SlowDatabase({"disable-rule": 1}, launcher_failures=2)
    session, journal, clock, launcher = build(tmp_path, cloud)
    result = close(session, launcher)
    assert result["session"] == "closed"
    assert len(clock.slept) == 3 and set(clock.slept) == {10}
    saved = json.loads(journal.path.read_text())
    assert saved["session"] == "closed" and saved["session_failures"] == []
    assert set(cloud.rules.values()) == {"DISABLED"}


def test_a_step_that_keeps_failing_ends_the_close_with_its_name_and_reason(tmp_path):
    cloud = SlowDatabase({"disable-rule": 99})
    session, journal, clock, launcher = build(tmp_path, cloud, retry=60)
    with pytest.raises(OperationError) as caught:
        close(session, launcher)
    message = str(caught.value)
    assert message.startswith("Partial close; retry from retained journal.")
    assert "disable:rule-" in message and "injected: the database is resuming" in message
    # The first failing step (the launcher's rule) spends the shared 60 s: one try per 10 s plus
    # the first; the later steps then get their single try.
    assert "launcher:rule: OperationError: injected: the database is resuming (tries: 7)" in message
    saved = json.loads(journal.path.read_text())
    assert saved["session"] == "closing" and saved["session_failures"]
    assert all("injected" in v for v in saved["session_errors"].values())
    assert sum(clock.slept) == 60


def test_the_retry_budget_is_shared_so_many_failing_steps_cannot_outlast_the_deadline(tmp_path):
    cloud = SlowDatabase({"disable-rule": 99, "update-event-source-mapping": 99})
    session, _, clock, launcher = build(tmp_path, cloud, retry=60)
    with pytest.raises(OperationError):
        close(session, launcher)
    assert sum(clock.slept) <= 60


def test_the_launcher_failure_names_the_error_type_and_never_the_lambda_message(tmp_path):
    cloud = SlowDatabase({}, launcher_failures=99)
    session, _, _, launcher = build(tmp_path, cloud, retry=0)
    with pytest.raises(OperationError) as caught:
        close(session, launcher)
    message = str(caught.value)
    assert "launcher:flag" in message and "error type ConnectionTimeout" in message
    assert "secret-host" not in message


def test_a_library_close_does_not_retry_unless_asked(tmp_path):
    cloud = SlowDatabase({"disable-rule": 1})
    session, _, clock, launcher = build(tmp_path, cloud, retry=0)
    with pytest.raises(OperationError, match="Partial close"):
        close(session, launcher)
    assert clock.slept == []
