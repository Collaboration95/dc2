"""V2-live (#235, #236): one persistent environment that every deploy updates in place.

Everything runs against the offline simulation from test_deploy.py; no AWS, Docker or network.
"""

import hashlib
import json

import pytest
from test_deploy import ACCOUNT, Rig, no_disk_sync  # noqa: F401  (an autouse fixture)

from scripts.aws.journal import Journal
from scripts.aws.v1 import deploy
from scripts.aws.v1.definitions import WORK_PUBLISHERS, template
from scripts.aws.v1.deploy import PERSISTENT_STEPS, DeployError, Settings

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def live(tmp_path):
    return Rig(tmp_path, run_id="live", persistent=True)


def change_sets(rig, since=0):
    return [p for _, o, p in rig.sim.calls[since:] if o == "create-change-set"]


def executed(rig, since=0):
    return [p for _, o, p in rig.sim.calls[since:] if o == "execute-change-set"]


def applied_changes(rig):
    return rig.journal.view()["steps"]["applications"]["detail"].get("changes", [])


def test_the_environment_name_is_the_stack_and_implies_the_launcher(tmp_path):
    settings = Settings(profile="dc2-agent", region="ap-southeast-1", account=ACCOUNT,
                        run_id="live", state_dir=tmp_path, persistent=True)
    assert settings.env == "dc2-live" and settings.bootstrap_stack == "dc2-live-bootstrap"
    assert settings.unattended_launch is True
    assert Settings(profile="dc2-agent", region="ap-southeast-1", account=ACCOUNT,
                    run_id="r1", state_dir=tmp_path).env == "dc2-v1-r1"


def test_the_first_deploy_creates_the_environment_open_and_marks_it_established(live):
    live.deploy()
    meta = live.journal.view()
    assert list(deploy.ordered_steps(meta)) == list(PERSISTENT_STEPS)
    assert meta["established"] is True and meta["session_opened"] is True
    assert live.session.actions == ["init", "open"]
    parameters = {p["ParameterKey"]: p["ParameterValue"] for p in change_sets(live)[-1][
        "Parameters"]}
    assert parameters["AlwaysOn"] == "true" and parameters["UnattendedLaunch"] == "true"
    assert (parameters["StageRateLimit"], parameters["StageBurstLimit"]) == ("20", "50")
    assert parameters["MonthlyBudgetUsd"] == "20"
    # `session open` and `status` read the same open throttle the template deploys.
    config = json.loads((live.s.state_dir / "operator-config.json").read_text())
    assert config["edge_open"] == {"rate": 20, "burst": 50}


def test_a_second_deploy_reruns_every_step_as_an_in_place_update_and_recreates_nothing(live):
    live.deploy()
    first = len(live.sim.calls)
    live.deploy()
    meta = live.journal.view()
    assert [s for s in meta["steps"].values() if s["status"] != "done"] == []
    assert len(meta["invocations"]) == 1  # the first deploy's step log, archived
    assert {c["ChangeSetType"] for c in change_sets(live, first)} <= {"UPDATE"}
    assert not [c for c in live.sim.calls[first:] if c[1] in {"delete-stack", "put-parameter"}]
    assert meta["steps"]["foundation"]["detail"]["skipped"]
    assert meta["steps"]["db-bootstrap"]["detail"]["skipped"]
    assert meta["steps"]["migrations"]["detail"]["skipped"]
    assert meta["steps"]["images"]["detail"]["pushed"] is False
    # Unchanged bytes: nothing to execute, and the session is not opened a second time.
    assert executed(live, first) == []
    assert live.session.actions == ["init", "open"]


def test_a_template_change_reaches_the_stack_as_an_update_of_only_that_resource(live):
    live.deploy()
    first = len(live.sim.calls)
    live.s.stage_rate_limit = 30
    live.deploy()
    assert [c["ChangeSetType"] for c in change_sets(live, first)][-1] == "UPDATE"
    assert len(executed(live, first)) == 1
    assert applied_changes(live) == [{"Action": "Modify", "LogicalResourceId": "HttpStage",
                                      "ResourceType": "AWS::ApiGatewayV2::Stage",
                                      "Replacement": "False"}]


def test_the_cost_guard_reports_but_never_blocks_an_update(live):
    live.deploy()
    live.sim.mtd = 500.0  # far above --budget-usd
    live.deploy()
    checks = live.journal.view()["steps"]["preflight"]["detail"]["checks"]
    guard = next(c for c in checks if c["check"] == "cost-guard")
    assert guard["status"] == "info" and "exceeds" in guard["detail"]


def test_the_first_deploy_of_an_environment_is_still_held_to_the_cost_guard(live):
    live.sim.mtd = 500.0
    with pytest.raises(DeployError, match="cost-guard"):
        live.deploy()


@pytest.mark.parametrize("logical", ["Distribution", "DatabaseCluster", "DatabaseInstance",
                                     "SourceBucket", "OutputBucket", "FrontendBucket"])
def test_replacing_stateful_data_fails_the_update_unless_explicitly_allowed(
        live, monkeypatch, logical):
    live.deploy()
    original = deploy.render_template

    def touched(database):
        built = original(database)
        built["Resources"][logical]["Properties"]["Tags"] = [{"Key": "touch", "Value": "1"}]
        return built

    monkeypatch.setattr(deploy, "render_template", touched)
    live.sim.replacing = {logical}
    with pytest.raises(DeployError, match=f"may replace stateful {logical}"):
        live.deploy()
    live.s.allow_replacement = True
    live.deploy()
    assert applied_changes(live)[0]["Replacement"] == "True"


def test_only_owners_whose_build_changed_are_reported_for_release(live, tmp_path):
    live.deploy()
    running = live.journal.view()["images"]
    images = tmp_path / "next.json"
    images.write_text(json.dumps({
        "media": {"source": "m:2", "local_id": running["media"]["local_id"]},
        "processing": {"source": "p:2", "local_id": "sha256:" + "f" * 64},
        "worker": {"source": "w:2", "local_id": running["worker"]["local_id"]},
    }))
    live.s.images_file = images
    live.deploy()
    detail = live.journal.view()["steps"]["images"]["detail"]
    assert detail == {"pushed": False, "changed_owners": ["processing"]}


def test_the_kill_switch_survives_routine_deploys(live):
    live.deploy()
    journal = Journal(live.s.state_dir / "session" / "journal.json", station=live.s.station,
                      environment=live.s.env)
    journal.initialize(verified_empty=True, exclusive_station=True)  # closed, as after close
    live.deploy()
    steps = live.journal.view()["steps"]
    assert steps["session-open"]["detail"]["kill_switch"] == "on"
    assert steps["public-smoke"]["detail"]["checks"].startswith("skipped")
    assert live.session.actions == ["init", "open"]


def release_dir(tmp_path, owner, digests):
    directory = tmp_path / "release"
    directory.mkdir()
    bundle = {kind: {"manifest_digest": digest, "config_id": f"sha256:{kind}-id"}
              for kind, digest in digests.items()}
    (directory / "bundle-good.json").write_text(json.dumps(bundle))
    (directory / "plan.json").write_text(json.dumps(
        {"owner": owner, "good": {"bundle": "bundle-good.json"}}))
    return directory


def test_an_adopted_release_becomes_what_the_stack_renders_for_that_owner_only(live, tmp_path):
    live.deploy()
    before = live.journal.view()["images"]
    digests = {"api": "sha256:" + "a" * 64, "worker": "sha256:" + "b" * 64}
    adopted = deploy.adopt_release(live.journal, "processing",
                                   release_dir(tmp_path, "processing", digests), "g9x1")
    images = live.journal.view()["images"]
    assert adopted == {"processing": digests["api"], "worker": digests["worker"]}
    assert images["processing"]["tag"] == "g9x1-processing"
    assert images["worker"]["uri"].endswith("@" + digests["worker"])
    assert images["media"] == before["media"]
    live.deploy(stop_after="applications")
    modified = {c["LogicalResourceId"] for c in applied_changes(live)}
    # A new published version is what moves each Processing alias; Media is untouched.
    assert {"ProcessingApiVersion", "ProcessingLauncherVersion", "WorkerTaskDefinition"} <= modified
    assert not [name for name in modified if name.startswith("Media")]


def test_adopting_refuses_a_plan_for_another_owner(live, tmp_path):
    live.deploy()
    with pytest.raises(DeployError, match="not media"):
        deploy.adopt_release(live.journal, "media",
                             release_dir(tmp_path, "processing", {"api": "sha256:" + "a" * 64}),
                             "g9x1")


def test_the_cli_targets_an_environment_or_a_run_but_never_both(capsys):
    with pytest.raises(SystemExit):
        deploy.main(["deploy", "--profile", "p", "--region", "ap-southeast-1", "--account",
                     ACCOUNT, "--run-id", "r1", "--environment", "live", "--dry-run"])
    assert "not allowed with" in capsys.readouterr().err


def test_a_dry_run_rehearses_the_environment_end_to_end(capsys):
    code = deploy.main(["rehearse", "--profile", "p", "--region", "ap-southeast-1",
                        "--account", ACCOUNT, "--environment", "live"])
    out = capsys.readouterr().out
    assert code == 0, out
    result = json.loads(out[: out.index("\n}\n") + 2])
    assert list(result["steps"])[: len(PERSISTENT_STEPS)] == list(PERSISTENT_STEPS)


# ---- the always-on template (#236) -----------------------------------------------------
RESOURCES = template()["Resources"]


def test_always_on_opens_every_gate_the_session_api_used_to_open():
    stage = RESOURCES["HttpStage"]["Properties"]["DefaultRouteSettings"]["Fn::If"]
    assert stage[1] == {"ThrottlingBurstLimit": {"Ref": "StageBurstLimit"},
                        "ThrottlingRateLimit": {"Ref": "StageRateLimit"}}
    for name in ("MediaRepairRule", "ProcessingRepairRule", "ProcessingEcsEventsRule",
                 "ProcessingS3EventsRule", "ProcessingLauncherRule"):
        assert RESOURCES[name]["Properties"]["State"]["Fn::If"][1] == "ENABLED"
    for name in ("ProcessingCommandsMapping", "MediaResultsMapping"):
        assert RESOURCES[name]["Properties"]["Enabled"]["Fn::If"][1] is True
    launcher = RESOURCES["ProcessingLauncher"]["Properties"]["Environment"]["Variables"]
    assert launcher["PROCESSING_LAUNCHER_ALWAYS_ON"]["Fn::If"][:2] == ["AlwaysOpen", "true"]


def test_the_budget_alerts_at_half_four_fifths_and_all_of_the_monthly_amount():
    budget = RESOURCES["MonthlyBudget"]
    assert budget["Condition"] == "AlwaysOpen"
    assert budget["Properties"]["Budget"]["BudgetLimit"] == {
        "Amount": {"Ref": "MonthlyBudgetUsd"}, "Unit": "USD"}
    notes = budget["Properties"]["NotificationsWithSubscribers"]
    assert [n["Notification"]["Threshold"] for n in notes] == [50, 80, 100]
    assert all(n["Subscribers"] == [{"SubscriptionType": "SNS",
                                     "Address": {"Ref": "BudgetAlertTopic"}}] for n in notes)
    # An email subscription exists only when an address is configured.
    assert RESOURCES["BudgetAlertSubscription"]["Condition"] == "BudgetEmail"


def test_only_the_work_publishers_may_wake_the_launcher_and_only_through_its_alias():
    invokers = RESOURCES["ProcessingLauncherInvokers"]
    assert invokers["Condition"] == "Unattended"
    assert invokers["Properties"]["Roles"] == [{"Ref": f"{n}Role"} for n in WORK_PUBLISHERS]
    (statement,) = invokers["Properties"]["PolicyDocument"]["Statement"]
    assert statement["Action"] == ["lambda:InvokeFunction"]
    assert statement["Resource"] == [{"Ref": "ProcessingLauncherAlias"}]
    granted = [name for name, r in RESOURCES.items() if r["Type"] in {
        "AWS::IAM::Policy", "AWS::IAM::Role"} and "lambda:InvokeFunction" in json.dumps(r)]
    assert granted == ["ProcessingLauncherInvokers"]
    for name in WORK_PUBLISHERS:
        variables = RESOURCES[name]["Properties"]["Environment"]["Variables"]
        assert variables["PROCESSING_LAUNCHER_FUNCTION"]["Fn::If"][:2] == [
            "Unattended", {"Ref": "ProcessingLauncherAlias"}]


def test_a_function_definition_change_publishes_a_new_version_for_its_alias():
    def digest(properties):
        return hashlib.sha256(json.dumps(properties, sort_keys=True).encode()).hexdigest()[:12]

    version = RESOURCES["ProcessingApiVersion"]
    assert version["DeletionPolicy"] == version["UpdateReplacePolicy"] == "Retain"
    description = version["Properties"]["Description"]["Fn::Sub"]
    properties = RESOURCES["ProcessingApi"]["Properties"]
    # The image and the definition both name the version, so either change replaces it.
    assert "${ProcessingImageUri}" in description and digest(properties) in description
    assert digest({**properties, "MemorySize": 4096}) not in description
