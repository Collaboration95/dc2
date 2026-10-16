"""Real session hooks, concurrency model and CLI behind a fake transport; no AWS calls."""

import io
import json
import time
from types import SimpleNamespace

import pytest
from v1_support import MAPPING_IDS, outputs

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1 import operations
from scripts.aws.v1.hooks import (
    ATTEMPT_STATES,
    AttemptCounts,
    OwnerHooks,
    file_reader,
    refuse_ambient_credentials,
    sql_reader,
)
from scripts.aws.v1.operations import PlanTransport, config_from_outputs
from scripts.aws.v1.session import Session
from scripts.aws.v1.session_cli import main


class Cloud(PlanTransport):
    """PlanTransport plus failure injection and a configurable account limit."""

    def __init__(self, *, account_limit=1000, **kwargs):
        super().__init__(**kwargs)
        self.fail, self.account_limit = set(), account_limit

    def call(self, service, operation, payload, *, deadline):
        if operation in self.fail:
            self.calls.append({"service": service, "operation": operation, "payload": payload})
            raise OperationError("injected transport failure")
        if operation == "get-account-settings":
            self.calls.append({"service": service, "operation": operation, "payload": payload})
            return {"AccountLimit": {"ConcurrentExecutions": self.account_limit}}
        return super().call(service, operation, payload, deadline=deadline)

    def operations(self):
        return [c["operation"] for c in self.calls]


@pytest.fixture
def rig(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    config, hooks, _ = config_from_outputs(outputs(), station="s", environment="e2e")
    journal = Journal(directory / "session.json", station="s", environment="e2e")
    journal.initialize(verified_empty=True, exclusive_station=True)
    # The template reserves nothing: an account limit of 10 forbids any reservation.
    cloud = Cloud(account_limit=10)
    session = Session(config, cloud, journal)
    owner = OwnerHooks(cloud, **hooks, sleep=lambda s: None)
    return session, cloud, journal, owner, config


def deadline():
    return time.monotonic() + 30


def counts(**values):
    return AttemptCounts(lambda _d: {**dict.fromkeys(ATTEMPT_STATES, 0), **values})


def state(journal):
    return json.loads(journal.path.read_text())


CONCURRENCY_CALLS = {
    "put-function-concurrency",
    "delete-function-concurrency",
    "get-function-concurrency",
    "get-account-settings",
}


def test_account_limit_ten_opens_without_touching_lambda_concurrency_at_all(rig):
    session, cloud, journal, owner, config = rig
    result = session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    assert result["worker_starts"] == 0
    assert not CONCURRENCY_CALLS & set(cloud.operations())
    assert set(cloud.mappings.values()) == {"Enabled"}
    assert set(cloud.rules.values()) == {"ENABLED"}
    assert cloud.stage == {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5}


def test_close_disables_every_wake_source_and_the_edge_without_reservations(rig):
    session, cloud, journal, owner, config = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    reader = counts(succeeded=3)
    result = session.close(drain=reader.drain, outcomes=reader.outcomes, deadline=deadline())
    assert result["database_pause"] == "NOT_OBSERVED"
    # Close never depends on put-function-concurrency: mappings, rules and the edge close it.
    assert not CONCURRENCY_CALLS & set(cloud.operations())
    assert set(cloud.mappings.values()) == {"Disabled"}
    assert set(cloud.rules.values()) == {"DISABLED"}
    assert cloud.stage == {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    assert state(journal)["close_outcomes"]["succeeded"] == 3


def invocations(cloud, function):
    return [
        i
        for i, c in enumerate(cloud.calls)
        if c["operation"] == "invoke" and c["payload"]["FunctionName"] == function
    ]


def test_each_owner_is_probed_with_the_direct_readiness_event_before_intake_serves(rig):
    session, cloud, journal, owner, config = rig
    session.open(
        ready=owner.ready,
        repair=owner.repair,
        intake_ready=owner.intake_ready,
        deadline=deadline(),
    )
    probes = [c for c in cloud.calls if c["operation"] == "invoke"]
    assert {"dc2_operation": "ready"} in [c["payload"]["Payload"] for c in probes]
    first_processing = invocations(cloud, "fn-ProcessingApi")[0]
    first_media = invocations(cloud, "fn-MediaApi")[0]
    edge_open = max(i for i, c in enumerate(cloud.calls) if c["operation"] == "update-stage")
    # Both owners are proven ready before the public edge opens.
    assert first_processing < first_media < edge_open


def test_failed_intake_probe_requiesces_intake_and_leaves_the_edge_closed(rig):
    _, cloud, journal, owner, config = rig
    config["zero_reservation"] = "required"
    session = Session(config, cloud, journal)
    real = cloud.call

    def call(service, operation, payload, *, deadline):
        if operation == "invoke" and payload["FunctionName"] == "fn-MediaApi":
            return {"StatusCode": 200, "FunctionError": False,
                    "Payload": {"service": "media", "ready": False}}
        return real(service, operation, payload, deadline=deadline)

    cloud.call = call
    with pytest.raises(OperationError):
        session.open(
            ready=owner.ready,
            repair=owner.repair,
            intake_ready=lambda **k: owner.intake_ready(
                deadline=time.monotonic() + 0.05
            ),
            deadline=deadline(),
        )
    assert cloud.functions["fn-MediaApi"] == 0 and cloud.functions["fn-MediaAuthorizer"] == 0
    assert cloud.stage == {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    assert state(journal)["session"] == "opening" and state(journal)["paused"]


def test_window_serves_only_the_public_api_and_never_enables_background_work(rig):
    session, cloud, journal, owner, config = rig
    result = session.open(
        ready=owner.ready, repair=owner.repair, intake_ready=owner.intake_ready,
        deadline=deadline(), window=True,
    )
    assert result["session"] == "window"
    assert set(cloud.mappings.values()) <= {"Disabled"}
    assert set(cloud.rules.values()) <= {"DISABLED"}
    assert state(journal)["paused"] is True
    assert session.status(deadline=deadline())["drift"] == []
    with pytest.raises(OperationError, match="Open unpaused"):
        session.batch(count=1, deadline=deadline())
    # A window may coexist with a release intent; a full open may not.
    with journal.locked() as saved:
        saved["pending_release"] = {"v1_request": {}}
        journal.save(saved)
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline(), window=True)
    with pytest.raises(OperationError, match="release intent"):
        session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())


def test_positive_reservation_is_refused_before_any_change_under_a_small_account_limit(rig):
    _, cloud, journal, _, config = rig
    config["functions"]["fn-ProcessingApi"] = 2
    session = Session(config, cloud, journal)
    with pytest.raises(OperationError, match="cannot hold"):
        session.open(ready=lambda **k: True, repair=lambda **k: True, deadline=deadline())
    assert cloud.operations() == ["get-account-settings"]
    assert state(journal)["session"] == "closed"


def test_positive_reservation_is_applied_when_the_account_keeps_the_unreserved_pool(rig):
    _, cloud, journal, _, config = rig
    config["functions"]["fn-ProcessingApi"] = 2
    cloud.account_limit = 1000
    Session(config, cloud, journal).open(
        ready=lambda **k: True, repair=lambda **k: True, deadline=deadline()
    )
    assert cloud.functions["fn-ProcessingApi"] == 2


def test_refused_zero_reservation_fails_close_unless_gateway_gate_makes_it_best_effort(rig):
    _, cloud, journal, owner, config = rig
    config["zero_reservation"] = "required"
    session = Session(config, cloud, journal)
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    cloud.fail.add("put-function-concurrency")
    reader = counts()
    with pytest.raises(OperationError, match="Partial close"):
        session.close(drain=reader.drain, outcomes=reader.outcomes, deadline=deadline())
    assert set(cloud.mappings.values()) == {"Disabled"}  # wake sources still disabled
    config["zero_reservation"] = "best-effort"
    relaxed = Session(config, cloud, journal)
    result = relaxed.close(drain=reader.drain, outcomes=reader.outcomes, deadline=deadline())
    assert any(w.startswith("zero-reservation-refused") for w in result["warnings"])
    assert cloud.stage["ThrottlingRateLimit"] == 0


def test_best_effort_without_an_edge_gate_is_rejected(rig):
    _, cloud, journal, _, config = rig
    config["zero_reservation"] = "off"
    del config["gateway"]
    with pytest.raises(OperationError, match="edge throttle gate"):
        Session(config, cloud, journal)


def test_partial_close_is_journaled_resumable_and_never_claims_database_pause(rig):
    session, cloud, journal, owner, _ = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    stuck = counts(processing=1)
    stuck.sleep = lambda s: None
    with pytest.raises(OperationError, match="Partial close"):
        session.close(
            drain=lambda **k: stuck.drain(deadline=time.monotonic() + 0.01),
            outcomes=stuck.outcomes,
            deadline=deadline(),
        )
    saved = state(journal)
    assert saved["session"] == "closing"
    assert "drain" in saved["session_failures"]
    assert "database_pause" not in json.dumps(saved)
    assert set(cloud.mappings.values()) == {"Disabled"}
    reader = counts(failed=1)
    result = session.close(drain=reader.drain, outcomes=reader.outcomes, deadline=deadline())
    assert result["session"] == "closed" and state(journal)["session_failures"] == []


def test_status_reports_drift_after_a_stack_update_reapplies_closed_defaults(rig):
    session, cloud, journal, owner, _ = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    assert session.status(deadline=deadline())["drift"] == []
    cloud.mappings[MAPPING_IDS["MediaResults"]] = "Disabled"
    cloud.stage = {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    report = session.status(deadline=deadline())
    assert report["journal_session"] == "open"
    assert any(d.startswith("mapping:") for d in report["drift"])
    assert "edge-throttle" in report["drift"]
    assert report["database_pause"] == "NOT_OBSERVED"


def test_readiness_polls_through_an_aurora_resume_and_gives_up_at_the_deadline(rig):
    _, cloud, _, owner, _ = rig
    attempts = []
    real = cloud.call

    def call(service, operation, payload, *, deadline):
        if operation == "invoke":
            attempts.append(1)
            if len(attempts) < 3:
                raise OperationError("resuming")
        return real(service, operation, payload, deadline=deadline)

    cloud.call = call
    assert owner.ready(deadline=deadline()) is True and len(attempts) == 3
    cloud.call = lambda *a, **k: (_ for _ in ()).throw(OperationError("down"))
    assert owner.ready(deadline=time.monotonic() + 0.05) is False


@pytest.mark.parametrize(
    "reply",
    [
        {"service": "processing", "ready": False, "error": "database unavailable"},
        {"service": "media", "ready": True},  # right shape from the wrong owner
        {"ready": True},
        None,
    ],
)
def test_readiness_requires_the_named_owner_to_report_ready(rig, reply):
    _, cloud, _, owner, _ = rig
    cloud.call = lambda *a, **k: {"StatusCode": 200, "FunctionError": False, "Payload": reply}
    assert owner.ready(deadline=time.monotonic() + 0.05) is False


def test_repair_requires_clean_function_results_and_retries_deadline_reached_rounds(rig):
    _, cloud, _, owner, _ = rig
    replies = iter([{"deadline_reached": True}, {}, {}, {}])

    def call(service, operation, payload, *, deadline):
        return {"StatusCode": 200, "FunctionError": False, "Payload": next(replies)}

    cloud.call = call
    assert owner.repair(deadline=deadline()) is True
    cloud.call = lambda *a, **k: {"StatusCode": 200, "FunctionError": True, "Payload": {}}
    assert owner.repair(deadline=deadline()) is False
    late = {"StatusCode": 200, "FunctionError": False, "Payload": {"deadline_reached": True}}
    cloud.call = lambda *a, **k: late
    assert owner.repair(deadline=deadline()) is False


def test_drain_waits_for_inflight_attempts_and_outcomes_reject_unresolved_work():
    sequence = iter([2, 1, 0])
    reader = AttemptCounts(
        lambda _d: {**dict.fromkeys(ATTEMPT_STATES, 0), "processing": next(sequence)},
        sleep=lambda s: None,
    )
    assert reader.drain(deadline=deadline()) is True
    busy = AttemptCounts(lambda _d: {"processing": 1})
    with pytest.raises(OperationError, match="In-flight"):
        busy.outcomes(deadline=deadline())


def test_sql_reader_is_read_only_closes_the_connection_and_hides_driver_errors(
    tmp_path, monkeypatch
):
    dsn = tmp_path / "dsn"
    dsn.write_text("postgresql://user:hunter2@db/processing_db")
    dsn.chmod(0o600)
    ca = tmp_path / "ca.pem"
    ca.write_text("")
    closed, queries = [], []

    class Connection:
        async def fetch(self, sql):
            queries.append(sql)
            return [("succeeded", 2), ("queued", 1)]

        async def close(self):
            closed.append(True)

    async def connect(dsn, **kwargs):
        return Connection()

    monkeypatch.setattr("ssl.create_default_context", lambda **kw: object())
    counts_ = sql_reader(dsn, ca, connect=connect)(time.monotonic() + 5)
    assert counts_["succeeded"] == 2 and counts_["processing"] == 0
    assert closed == [True] and queries[0].upper().startswith("SELECT")

    async def broken(dsn, **kwargs):
        raise RuntimeError("password hunter2 rejected")

    with pytest.raises(OperationError) as caught:
        sql_reader(dsn, ca, connect=broken)(time.monotonic() + 5)
    assert "hunter2" not in str(caught.value)
    dsn.chmod(0o644)
    with pytest.raises(OperationError, match="private"):
        sql_reader(dsn, ca)(time.monotonic() + 5)


def test_counts_file_must_be_private_and_valid(tmp_path):
    path = tmp_path / "counts.json"
    path.write_text(json.dumps({"succeeded": 1, "queued": 0}))
    path.chmod(0o600)
    assert file_reader(path)(None)["succeeded"] == 1
    path.write_text(json.dumps({"succeeded": -1}))
    with pytest.raises(OperationError):
        file_reader(path)(None)
    path.chmod(0o644)
    with pytest.raises(OperationError, match="private"):
        file_reader(path)(None)


def test_ambient_aws_credentials_and_endpoints_are_refused():
    refuse_ambient_credentials({"PATH": "/bin"})
    for key in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_ENDPOINT_URL_LAMBDA"):
        with pytest.raises(OperationError):
            refuse_ambient_credentials({key: "x"})


def operator_files(tmp_path):
    directory = tmp_path / "ops"
    directory.mkdir(mode=0o700)
    (directory / "outputs.json").write_text(json.dumps(outputs()))
    config = {
        "operator_station": "s",
        "environment_id": "e2e",
        "journal": str(directory / "session.json"),
        "outputs_file": str(directory / "outputs.json"),
    }
    (directory / "config.json").write_text(json.dumps(config))
    return directory / "config.json"


def run(*argv, tmp_path=None, **kwargs):
    out = io.StringIO()
    code = main(list(argv), stdout=out, **kwargs)
    return code, json.loads(out.getvalue())


SCOPE = ("--profile", "operator", "--region", "ap-southeast-1", "--account", "123456789012")


@pytest.mark.parametrize(
    "scope",
    [
        ("--region", "ap-southeast-1", "--account", "123456789012"),
        ("--profile", "operator", "--account", "123456789012"),
        ("--profile", "default", "--region", "ap-southeast-1", "--account", "123456789012"),
        ("--profile", "operator", "--region", "us-east-1", "--account", "123456789012"),
        ("--profile", "operator", "--region", "ap-southeast-1", "--account", "12"),
    ],
)
def test_cli_requires_explicit_profile_region_and_account(scope, tmp_path):
    with pytest.raises(SystemExit):
        main(["status", "--config", str(operator_files(tmp_path)), *scope], environ={})


@pytest.mark.parametrize("action", ["open", "close", "batch", "status", "init"])
def test_dry_run_prints_planned_calls_without_building_a_live_transport(action, tmp_path):
    config = operator_files(tmp_path)

    def forbidden(scope):
        raise AssertionError("dry-run must not build a live transport")

    code, out = run(
        action, "--config", str(config), *SCOPE, "--dry-run", transport_factory=forbidden
    )
    assert code == 0 and out["scope"]["mode"] == "dry-run"
    assert not (config.parent / "session.json").exists()  # the real journal is untouched
    if action != "init":
        assert out["planned_calls"]
        assert {c["service"] for c in out["planned_calls"]} <= {
            "lambda", "events", "apigatewayv2", "ecs"
        }


def test_dry_run_open_plans_edge_and_probes_without_lambda_concurrency_calls(tmp_path):
    code, out = run("open", "--config", str(operator_files(tmp_path)), *SCOPE, "--dry-run")
    ops = [c["operation"] for c in out["planned_calls"]]
    assert "invoke" in ops and "update-stage" in ops
    assert not CONCURRENCY_CALLS & set(ops)
    probes = [c["payload"]["Payload"] for c in out["planned_calls"] if c["operation"] == "invoke"]
    assert {"dc2_operation": "ready"} in probes
    assert out["result"]["worker_starts"] == 0 and "simulated" in out


def test_live_run_uses_the_injected_transport_and_persists_the_journal(tmp_path):
    config = operator_files(tmp_path)
    cloud = Cloud(account_limit=10)
    seen = []

    def factory(scope):
        seen.append(scope)
        return cloud

    assert run("init", "--config", str(config), *SCOPE, "--confirm-empty",
               "--confirm-exclusive", transport_factory=factory)[0] == 0
    code, out = run("open", "--config", str(config), *SCOPE, transport_factory=factory)
    assert code == 0 and out["scope"]["mode"] == "live"
    assert seen[0] == {"profile": "operator", "region": "ap-southeast-1", "account": "123456789012"}
    code, out = run("status", "--config", str(config), *SCOPE, transport_factory=factory)
    assert out["result"]["journal_session"] == "open" and out["result"]["drift"] == []
    # Close needs an outcome source; refusing is safer than guessing counts.
    code, out = run("close", "--config", str(config), *SCOPE, transport_factory=factory)
    assert code == 1 and "SQL or operator counts" in out["error"]


def test_init_refuses_to_replace_without_explicit_confirmation(tmp_path):
    config = operator_files(tmp_path)
    code, out = run("init", "--config", str(config), *SCOPE, transport_factory=lambda s: Cloud())
    assert code == 1 and out["ok"] is False


def test_live_transport_checks_identity_and_refuses_a_different_account(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

    class Boto:
        class Session:
            def __init__(self, profile_name, region_name):
                self.profile = profile_name

            def client(self, service, config=None):
                if service == "sts":
                    return SimpleNamespace(get_caller_identity=lambda: {"Account": "999999999999"})
                raise AssertionError("no service client before identity verification")

    with pytest.raises(OperationError, match="different account"):
        operations.live_transport(
            {"profile": "operator", "region": "ap-southeast-1", "account": "123456789012"},
            boto3_module=Boto,
        )


def test_outputs_translation_rejects_unknown_handlers_and_missing_values():
    with pytest.raises(OperationError, match="Unknown handler"):
        config_from_outputs(outputs(), station="s", environment="e", reservations={"Nope": 1})
    broken = outputs()
    del broken["HttpApiId"]
    with pytest.raises(OperationError, match="missing"):
        config_from_outputs(broken, station="s", environment="e")
    listed = [{"OutputKey": k, "OutputValue": v} for k, v in outputs().items()]
    config, hooks, urls = config_from_outputs(listed, station="s", environment="e")
    assert config["gateway"]["open"] == operations.DEFAULT_EDGE_OPEN
    assert set(config["owner_functions"]) == {"media", "processing"}
    assert urls["gateway"].startswith("https://")
