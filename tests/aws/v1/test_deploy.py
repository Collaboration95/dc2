"""The deploy/teardown pipeline against the offline simulation; no AWS, Docker or network."""

import datetime as dt
import io
import json
import os
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1 import deploy, deploy_sim
from scripts.aws.v1.deploy import (
    DEPLOY_STEPS,
    TEARDOWN_STEPS,
    AwaitingExecute,
    AwsError,
    CliTransport,
    DeployError,
    DeployJournal,
    Pipeline,
    Settings,
)

ACCOUNT = "123456789012"
ARGS = ["--profile", "dc2-project2", "--region", "ap-southeast-1", "--account", ACCOUNT]
TODAY = dt.date(2026, 10, 16)


class FakeGateway:
    """Just enough of the public API for the seed and PublicSmoke checks."""

    def __init__(self, *, login=200, register=201):
        self.login, self.register, self.requests = login, register, []

    def __call__(self, method, url, headers, body, timeout):
        path = url.split(".amazonaws.com", 1)[1]
        self.requests.append((method, path))
        cookie = {"set-cookie": ["session=x; HttpOnly; Secure; SameSite=Strict"]}
        if path == "/api/media/auth/register":
            return self.register, {}, b"{}"
        if path == "/api/media/health":
            return 200, {}, b'{"status":"ok","service":"media"}'
        if path == "/api/processing/health":
            return 200, {}, b'{"status":"ok","service":"processing","schema_version":1}'
        if path == "/api/media/auth/login":
            return self.login, cookie, b'{"id":1}'
        if path == "/api/media/jobs":
            return (200, {}, b"[]") if headers.get("cookie") else (401, {}, b"{}")
        if path.startswith("/api/processing/jobs"):
            return 200, {}, b"[]"
        if path == "/api/media/uploads/reservations":
            reply = {"upload": {"url": "https://s3", "fields": {}}, "expires_at": "x",
                     "finalize_url": "y"}
            return 201, {}, json.dumps(reply).encode()
        return 404, {}, b"{}"


class FakeSession:
    """Stands in for session_cli.main; records each action and answers like a closed API."""

    def __init__(self):
        self.actions = []

    def __call__(self, argv, *, environ=None, stdout=None, **_):
        self.actions.append(argv[0])
        result = {"session": "closed", "database_pause": "NOT_OBSERVED"}
        print(json.dumps({"ok": True, "result": result}), file=stdout)
        return 0


def settings_for(tmp_path, **overrides):
    state = tmp_path / "state"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    images = tmp_path / "images.json"
    images.write_text(json.dumps({o: f"local-{o}:1" for o in ("media", "processing", "worker")}))
    values = dict(
        profile="dc2-project2", region="ap-southeast-1", account=ACCOUNT, run_id="t1",
        state_dir=state, execute=True, images_file=images, seed_email="smoke@example.com",
        assume_empty_counts=True, forecast_usd=0.0)
    values.update(overrides)
    return Settings(**values)


class Rig:
    def __init__(self, tmp_path, *, gateway=None, **overrides):
        self.s = settings_for(tmp_path, **overrides)
        self.sim = deploy_sim.SimulatedAws(self.s)
        self.docker = deploy_sim.SimulatedDocker(self.sim)
        self.gateway = gateway or FakeGateway()
        self.session = FakeSession()
        self.journal = DeployJournal(
            self.s.state_dir / "deploy-journal.json", station=self.s.station,
            environment=self.s.env)
        if not self.journal.exists():
            self.journal.create({
                "run_id": self.s.run_id, "env": self.s.env, "account": ACCOUNT,
                "region": self.s.region, "created_at": "t", "steps": {}, "resources": {},
                "outputs": {}, "images": {}, "events": []})

    def pipeline(self):
        return Pipeline(
            self.s, self.sim, self.journal, docker=self.docker, http=self.gateway,
            session_main=self.session, clock=iter_clock(), sleep=lambda _s: None,
            stderr=io.StringIO(), today=lambda: TODAY)

    def deploy(self, **kwargs):
        pipeline = self.pipeline()
        pipeline.deploy(**kwargs)
        return pipeline

    def teardown(self):
        pipeline = self.pipeline()
        pipeline.teardown()
        return pipeline

    def mutating(self, *, since=0):
        return [(s, o, p) for s, o, p in self.sim.calls[since:] if deploy.is_mutating(o)]

    def ops(self, name):
        return [c for c in self.sim.calls if c[1] == name]

    def steps(self):
        return deploy.ordered_steps(self.journal.view())


def iter_clock():
    ticks = iter(range(0, 10_000_000, 1))
    return lambda: next(ticks)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ---- scope and transport ----------------------
@pytest.mark.parametrize("override", [
    {"profile": "default"}, {"profile": "bad profile"}, {"region": "us-east-1"},
    {"account": "1234"}, {"run_id": "UPPER"}, {"run_id": "x" * 17}, {"budget_usd": 0},
])
def test_settings_refuse_default_profile_foreign_region_and_malformed_scope(tmp_path, override):
    with pytest.raises(DeployError):
        settings_for(tmp_path, **override)


def test_the_cli_requires_every_scope_flag_and_never_defaults_the_profile(capsys):
    with pytest.raises(SystemExit):
        deploy.main(["deploy", "--region", "ap-southeast-1", "--account", ACCOUNT,
                     "--run-id", "t1", "--dry-run"])
    assert "--profile" in capsys.readouterr().err


def test_live_transport_refuses_inherited_aws_credentials():
    with pytest.raises(OperationError):
        CliTransport({"profile": "p", "region": "ap-southeast-1", "account": ACCOUNT},
                     environ={"AWS_PROFILE": "other"})


class RecordingRunner:
    def __init__(self, stdout="{}", returncode=0, stderr=""):
        self.calls, self.stdout, self.returncode, self.stderr = [], stdout, returncode, stderr

    def __call__(self, argv, **kwargs):
        index = argv.index("--cli-input-json") if "--cli-input-json" in argv else None
        path = Path(argv[index + 1].removeprefix("file://")) if index else None
        self.calls.append({
            "argv": argv, "env": kwargs["env"],
            "file_mode": stat.S_IMODE(path.stat().st_mode) if path else None,
            "dir_mode": stat.S_IMODE(path.parent.stat().st_mode) if path else None,
            "body": json.loads(path.read_text()) if path else None, "path": path})
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def transport(runner, **kwargs):
    scope = {"profile": "dc2-project2", "region": "ap-southeast-1", "account": ACCOUNT}
    return CliTransport(scope, runner=runner, environ={}, **kwargs)


def test_live_call_sends_the_request_through_a_private_file_and_removes_it():
    runner = RecordingRunner('{"Version": 1}')
    result = transport(runner).call("ssm", "put-parameter", {
        "Name": "/dc2/x/a", "Value": "hunter2-very-secret", "Type": "SecureString"})
    call = runner.calls[0]
    assert result == {"Version": 1}
    assert "hunter2-very-secret" not in " ".join(call["argv"])
    assert call["body"]["Value"] == "hunter2-very-secret"
    assert (call["file_mode"], call["dir_mode"]) == (0o600, 0o700)
    assert not call["path"].exists()
    assert call["argv"][1:5] == ["--profile", "dc2-project2", "--region", "ap-southeast-1"]


def test_live_call_never_inherits_the_callers_aws_environment(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
    runner = RecordingRunner()
    CliTransport({"profile": "p", "region": "ap-southeast-1", "account": ACCOUNT},
                 runner=runner, environ={}).call("sts", "get-caller-identity", {})
    assert not [k for k in runner.calls[0]["env"] if k == "AWS_SECRET_ACCESS_KEY"]
    assert runner.calls[0]["env"]["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"


def test_a_cli_failure_surfaces_only_the_error_code_not_the_message():
    runner = RecordingRunner(returncode=254, stderr=(
        "\nAn error occurred (ValidationError) when calling the DescribeStacks operation: "
        "Stack with id x does not exist (secret-ish detail)"))
    with pytest.raises(AwsError) as caught:
        transport(runner).call("cloudformation", "describe-stacks", {"StackName": "x"})
    assert caught.value.code == "ValidationError"
    assert "secret-ish" not in str(caught.value)


@pytest.mark.parametrize("service,operation", [
    ("s3api", "put-bucket-policy"), ("ec2", "run-instances"), ("iam", "create-user"),
    ("rds", "delete-db-snapshot"), ("lambda", "put-function-concurrency"),
])
def test_calls_outside_the_allowlist_are_refused_before_any_process_starts(service, operation):
    runner = RecordingRunner()
    with pytest.raises(DeployError):
        transport(runner).call(service, operation, {})
    assert runner.calls == []


def test_ecs_calls_reuse_the_shared_argument_contract():
    with pytest.raises(OperationError):
        transport(RecordingRunner()).call("ecs", "run-task", {"cluster": "c", "count": 5})


def test_a_streaming_body_travels_as_a_path_argument_not_in_the_request_json():
    runner = RecordingRunner()
    transport(runner).call("s3api", "put-object", {"Bucket": "b", "Key": "k", "Body": "/tmp/x"})
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("--body") + 1] == "/tmp/x"
    assert "Body" not in runner.calls[0]["body"]


def test_plans_redact_parameter_values_but_keep_tags_and_elide_template_bodies():
    scope = {"profile": "p", "region": "ap-southeast-1", "account": ACCOUNT}
    shown = deploy.display_command(scope, "ssm", "put-parameter", {
        "Name": "/n", "Value": "s3cr3t", "Type": "SecureString",
        "Tags": [{"Key": "owner-run", "Value": "t1"}]})
    assert "s3cr3t" not in shown and '"Value":"<redacted>"' in shown and '"Value":"t1"' in shown
    body = "x" * 5000
    shown = deploy.display_command(scope, "cloudformation", "create-change-set",
                                   {"StackName": "s", "TemplateBody": body})
    assert body not in shown and "5000 bytes sha256:" in shown


def test_tag_keys_cannot_collide_with_template_tags_which_iam_compares_case_insensitively():
    from scripts.aws.v1.definitions import template

    keys = set()
    for document in (template(), json.loads(deploy.BOOTSTRAP_TEMPLATE.read_text())):
        for resource in document["Resources"].values():
            tags = resource.get("Properties", {}).get("Tags", [])
            if isinstance(tags, list):
                keys |= {t["Key"].lower() for t in tags if isinstance(t, dict) and "Key" in t}
    assert {deploy.PROJECT_KEY.lower(), deploy.RUN_KEY.lower()}.isdisjoint(keys)


# ---- preflight ----------------------
def preflight_blockers(rig):
    with pytest.raises(DeployError) as caught:
        rig.pipeline().preflight()
    return str(caught.value)


def test_preflight_passes_on_the_observed_account_shape_and_records_the_legacy_stack(rig):
    report = rig.pipeline().preflight()
    checks = {c["check"]: c for c in report["checks"]}
    assert checks["identity"]["simulated"] is True
    assert checks["lambda-concurrency"]["unreserved"] == 10
    assert checks["fargate-vcpu"]["quota"] == 6
    assert checks["aurora-engine"]["version"] == "16.8" and checks["aurora-engine"]["min_acu"] == 0
    assert checks["legacy-bootstrap-stack"]["decision"] == "not reused, not touched"
    assert checks["legacy-bootstrap-stack"]["stack_status"] == "ROLLBACK_COMPLETE"
    assert rig.mutating() == []


def test_preflight_stops_when_sts_names_a_different_account(rig):
    rig.sim.s = type("Other", (), {"account": "999999999999", "budget_name": "x"})()
    with pytest.raises(DeployError, match="STS account differs"):
        rig.pipeline().preflight()


def test_preflight_blocks_an_iam_user_without_an_mfa_device(rig):
    rig.sim.mfa = False
    assert "mfa" in preflight_blockers(rig)


def test_preflight_blocks_an_aurora_version_that_is_not_orderable_or_cannot_pause(rig):
    rig.sim.engine_available = False
    assert "aurora-engine" in preflight_blockers(rig)


def test_preflight_blocks_when_the_budget_is_missing_or_below_the_guard(rig):
    rig.sim.budget_name = "someone-elses-budget"
    assert "budget" in preflight_blockers(rig)
    rig.sim.budget_name = rig.s.budget_name
    rig.sim.budget_limit = 10.0
    assert "budget" in preflight_blockers(rig)


def test_preflight_blocks_fewer_than_two_fargate_vcpus_but_only_warns_below_six(tmp_path):
    rig = Rig(tmp_path)
    rig.sim.fargate_vcpus = 4.0
    checks = {c["check"]: c["status"] for c in rig.pipeline().preflight()["checks"]}
    assert checks["fargate-vcpu"] == "warn"
    rig.sim.fargate_vcpus = 1.0
    assert "fargate-vcpu" in preflight_blockers(rig)


def test_preflight_blocks_a_stack_with_the_run_name_that_this_run_does_not_own(rig):
    rig.sim.stacks[rig.s.env] = {"status": "CREATE_COMPLETE", "tags": {}, "resources": [],
                                 "outputs": {}, "changesets": {}, "id": "someone-elses"}
    assert "name-collisions" in preflight_blockers(rig)


def test_preflight_blocks_leftover_parameters_and_log_groups_that_are_not_tagged_for_this_run(rig):
    rig.sim.params[f"/dc2/{rig.s.env}/jwt_secret"] = {}
    rig.sim.groups[f"/dc2/{rig.s.env}/MediaApi"] = {}
    assert "name-collisions" in preflight_blockers(rig)


def test_preflight_accepts_resources_this_run_already_created_so_a_resume_works(rig):
    rig.sim.params[f"/dc2/{rig.s.env}/jwt_secret"] = {
        deploy.PROJECT_KEY: deploy.PROJECT_VALUE, deploy.RUN_KEY: rig.s.run_id}
    rig.pipeline().preflight()


def test_preflight_blocks_an_artifacts_bucket_name_owned_by_another_account(rig):
    def forbidden(payload):
        raise AwsError("s3api", "head-bucket", "403")

    rig.sim.s3api_head_bucket = forbidden
    assert "name-collisions" in preflight_blockers(rig)


def test_preflight_blocks_a_run_that_could_not_prove_a_drain_before_spending(tmp_path):
    rig = Rig(tmp_path, assume_empty_counts=False)
    assert "close-proof" in preflight_blockers(rig)


def test_preflight_validates_the_images_file_when_one_is_given(rig):
    rig.s.images_file.write_text('{"media": "m"}')
    assert "images-input" in preflight_blockers(rig)


def test_preflight_makes_no_mutating_call_of_any_kind(rig):
    rig.pipeline().preflight()
    assert rig.mutating() == []


# ---- cost guard ----------------------
def test_planned_cost_is_the_database_ceiling_plus_finite_tasks_and_a_months_retention():
    three_hours = deploy.planned_cost(3)
    assert 1.8 < three_hours < 2.2
    assert deploy.planned_cost(6) - three_hours == pytest.approx(3 * 2 * deploy.ACU_HOUR, abs=0.01)


def test_cost_guard_refuses_when_month_to_date_forecast_and_plan_exceed_the_budget(rig):
    rig.sim.mtd, rig.s.forecast_usd = 25.0, 4.0
    with pytest.raises(DeployError, match="exceeds --budget-usd"):
        rig.pipeline().cost_guard()


def test_cost_guard_passes_with_headroom_and_reports_every_component(rig):
    rig.sim.mtd, rig.s.forecast_usd = 5.0, 3.0
    report = rig.pipeline().cost_guard()
    assert report["month_to_date_usd"] == 5.0 and report["forecast_source"] == "operator-supplied"
    assert report["total_usd"] == pytest.approx(8.0 + report["planned_deploy_usd"])


def test_cost_guard_uses_the_cost_explorer_forecast_when_none_is_supplied(rig):
    rig.s.forecast_usd, rig.sim.forecast = None, 2.5
    assert rig.pipeline().cost_guard()["forecast_usd"] == 2.5


def test_cost_guard_fails_closed_when_there_is_no_forecast(rig):
    rig.s.forecast_usd, rig.sim.forecast = None, None
    with pytest.raises(DeployError, match="fail closed"):
        rig.pipeline().cost_guard()


def test_the_budget_flag_is_the_threshold(rig):
    rig.s.budget_usd, rig.s.forecast_usd = 1.0, 0.0
    with pytest.raises(DeployError):
        rig.pipeline().cost_guard()


def test_cost_is_checked_again_before_every_change_set_is_executed(rig):
    pipeline = rig.pipeline()
    pipeline.step = "bootstrap-stack"
    rig.sim.mtd = 29.99
    rig.s.forecast_usd = 0.0
    with pytest.raises(DeployError, match="Cost guard"):
        pipeline.step_bootstrap_stack()
    assert rig.ops("execute-change-set") == []


# ---- bootstrap stack ----------------------
def test_a_fresh_bootstrap_stack_is_created_and_the_rolled_back_one_is_not_touched(rig):
    pipeline = rig.pipeline()
    pipeline.step = "bootstrap-stack"
    result = pipeline.step_bootstrap_stack()
    assert result["decision"] == "created" and result["stack"] == f"{rig.s.env}-bootstrap"
    touched = {p.get("StackName") for _, _, p in rig.sim.calls if "StackName" in p}
    assert deploy.LEGACY_BOOTSTRAP_STACK not in touched
    request = rig.ops("create-change-set")[0][2]
    allowed = json.loads(request["TemplateBody"])["Parameters"]["Namespace"]["AllowedValues"]
    assert allowed == [rig.s.env]
    assert {t["Key"]: t["Value"] for t in request["Tags"]} == {
        "deploy-project": "dc2-v1", "owner-run": "t1"}


def test_adopting_a_bootstrap_stack_requires_it_to_be_healthy_and_exposes_a_bucket(rig):
    pipeline = rig.pipeline()
    pipeline.step = "bootstrap-stack"
    rig.s.adopt_bootstrap = deploy.LEGACY_BOOTSTRAP_STACK
    with pytest.raises(DeployError, match="not adoptable"):
        pipeline.step_bootstrap_stack()


def adopt(rig):
    rig.sim.stacks["shared-staging"] = {
        "status": "CREATE_COMPLETE", "tags": {}, "resources": [], "id": "s", "changesets": {},
        "outputs": {"ArtifactsBucket": "shared-artifacts"}}
    rig.sim.buckets["shared-artifacts"] = {"tags": {}, "versions": [], "markers": [], "uploads": []}
    rig.s.adopt_bootstrap = "shared-staging"


def test_an_adopted_bootstrap_stack_is_used_for_staging_and_survives_teardown(rig):
    adopt(rig)
    rig.deploy()
    assert any(b == "shared-artifacts" for b in [p.get("Bucket") for _, _, p in rig.sim.calls])
    rig.s.confirm_run_id = "t1"
    rig.teardown()
    assert "shared-staging" in rig.sim.stacks
    assert rig.sim.stacks["shared-staging"]["status"] == "CREATE_COMPLETE"
    assert "shared-artifacts" in rig.sim.buckets
    assert rig.sim.buckets["shared-artifacts"]["versions"] == []  # only its own templates removed
    receipt = rig.journal.view()
    assert any(s["id"] == "shared-staging" for s in receipt["ownership"]["skipped"])


# ---- change sets ----------------------
def test_without_execute_a_change_set_is_described_and_the_pipeline_stops(tmp_path):
    rig = Rig(tmp_path, execute=False)
    with pytest.raises(AwaitingExecute, match="--execute"):
        rig.deploy()
    assert rig.steps()["bootstrap-stack"] == "awaiting-execute"
    assert rig.ops("execute-change-set") == []
    assert len(rig.ops("create-change-set")) == 1


def test_a_later_execute_run_reuses_the_described_change_set_and_continues(tmp_path):
    rig = Rig(tmp_path, execute=False)
    with pytest.raises(AwaitingExecute):
        rig.deploy()
    rig.s.execute = True
    rig.deploy()
    assert len([c for c in rig.ops("create-change-set")
                if c[2]["StackName"].endswith("bootstrap")]) == 1
    assert set(rig.steps().values()) == {"done"}


def change(action, logical="Thing", kind="AWS::S3::Bucket", replacement="False"):
    return {"ResourceChange": {"Action": action, "LogicalResourceId": logical,
                               "ResourceType": kind, "Replacement": replacement}}


def test_an_initial_change_set_may_only_add_resources():
    with pytest.raises(DeployError, match="only Add"):
        deploy.review_changes([change("Modify")], "CREATE")


def test_an_update_may_not_remove_anything():
    with pytest.raises(DeployError, match="removes"):
        deploy.review_changes([change("Remove")], "UPDATE")


def test_an_update_may_not_replace_stateful_resources_unless_explicitly_allowed():
    risky = [change("Modify", "Database", "AWS::RDS::DBCluster", "True")]
    with pytest.raises(DeployError, match="stateful"):
        deploy.review_changes(risky, "UPDATE")
    assert deploy.review_changes(risky, "UPDATE", allow_replacement=True)
    assert deploy.review_changes([change("Modify", "Role", "AWS::IAM::Role", "True")], "UPDATE")


def test_an_empty_change_set_is_an_error_not_a_silent_success():
    with pytest.raises(DeployError, match="no changes"):
        deploy.review_changes([], "UPDATE")


def test_oversize_templates_are_staged_in_the_private_bucket_and_tagged(rig):
    rig.deploy(stop_after="foundation")
    upload = rig.ops("put-object")[0][2]
    assert upload["Bucket"] == rig.journal.view()["resources"]["staging_bucket"]
    assert upload["ServerSideEncryption"] == "AES256"
    assert "owner-run=t1" in upload["Tagging"]
    request = [c for c in rig.ops("create-change-set") if c[2]["StackName"] == rig.s.env][0][2]
    assert request["TemplateURL"].endswith(".json") and "TemplateBody" not in request


def test_a_failed_stack_creation_reports_the_failing_resource_not_a_traceback(rig):
    rig.sim.fail[("stack-complete", rig.s.env)] = "Resource creation cancelled"
    with pytest.raises(DeployError, match="ROLLBACK_COMPLETE.*Resource creation cancelled"):
        rig.deploy()
    assert rig.steps()["foundation"] == "failed"


def test_a_failed_stack_is_still_known_to_teardown_with_its_retained_resources(rig):
    original = rig.sim.complete_stack

    def partial(name, change_set, failure=None):
        original(name, change_set, None)  # resources exist, then the stack rolls back
        if name == rig.s.env:
            rig.sim.stacks[name]["status"] = "ROLLBACK_COMPLETE"

    rig.sim.complete_stack = partial
    with pytest.raises(DeployError, match="ROLLBACK_COMPLETE"):
        rig.deploy()
    recorded = rig.journal.view()["resources"]
    assert rig.s.env in recorded["stacks"] and len(recorded["buckets"]) == 4
    rig.s.confirm_run_id = "t1"
    rig.teardown()
    assert rig.sim.stacks[rig.s.env]["status"] == "DELETE_COMPLETE"
    assert not [b for b in rig.sim.buckets if b.startswith(rig.s.env)]


def test_foundation_creates_closed_infrastructure_and_records_what_it_made(rig):
    rig.deploy(stop_after="foundation")
    resources = rig.journal.view()["resources"]
    assert len(resources["buckets"]) == 4 and len(resources["repositories"]) == 3
    assert len(resources["db_clusters"]) == 1 and len(resources["db_instances"]) == 1
    request = [c for c in rig.ops("create-change-set") if c[2]["StackName"] == rig.s.env][0][2]
    parameters = {p["ParameterKey"]: p["ParameterValue"] for p in request["Parameters"]}
    assert parameters["DeployApplications"] == "false"


# ---- images ----------------------
def test_images_are_pushed_once_and_the_stack_receives_digest_pinned_references(rig):
    rig.deploy(stop_after="applications")
    images = rig.journal.view()["images"]
    assert set(images) == {"media", "processing", "worker"}
    assert all(i["uri"].endswith("@" + i["digest"]) and i["digest"].startswith("sha256:")
               for i in images.values())
    pushes = [c for c in rig.docker.commands if c[0] == "push"]
    assert len(pushes) == 3
    update = [c for c in rig.ops("create-change-set") if c[2]["ChangeSetType"] == "UPDATE"][0][2]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in update["Parameters"]}
    assert params["MediaImageUri"] == images["media"]["uri"]
    assert params["DeployApplications"] == "true"
    assert params["SourceCorsOrigin"].startswith("https://d")  # the generated frontend origin


def test_the_registry_login_uses_a_private_docker_config_via_stdin(tmp_path):
    seen = []

    class Spy(deploy_sim.SimulatedDocker):
        def __call__(self, argv, *, stdin=None):
            seen.append((argv[0], stdin))
            return super().__call__(argv, stdin=stdin)

    rig = Rig(tmp_path)
    rig.docker = Spy(rig.sim)
    rig.deploy(stop_after="images")
    assert ("login", "simulated-registry-password") in seen
    assert "simulated-registry-password" not in json.dumps(rig.journal.view())


def test_a_rerun_never_pushes_an_image_twice(rig):
    rig.deploy(stop_after="images")
    rig.journal.mutate(lambda d: d["steps"].pop("images"))
    rig.deploy(stop_after="images")
    assert len([c for c in rig.docker.commands if c[0] == "push"]) == 3


def test_only_linux_amd64_images_are_accepted(rig):
    class Arm(deploy_sim.SimulatedDocker):
        def __call__(self, argv, *, stdin=None):
            if argv[:2] == ["image", "inspect"]:
                return "linux/arm64 sha256:abc\n"
            return super().__call__(argv, stdin=stdin)

    rig.docker = Arm(rig.sim)
    with pytest.raises(DeployError, match="linux/amd64"):
        rig.deploy()


def test_a_resume_refuses_a_local_image_that_changed_after_it_was_pushed(rig):
    rig.deploy(stop_after="images")
    rig.journal.mutate(lambda d: d["steps"].pop("images"))

    class Rebuilt(deploy_sim.SimulatedDocker):
        def __call__(self, argv, *, stdin=None):
            if argv[:2] == ["image", "inspect"]:
                return "linux/amd64 sha256:rebuilt\n"
            return super().__call__(argv, stdin=stdin)

    rig.docker = Rebuilt(rig.sim)
    with pytest.raises(DeployError, match="changed since it was pushed"):
        rig.deploy(stop_after="images")


def test_a_registry_digest_that_differs_from_the_expected_one_is_refused(rig):
    rig.s.images_file.write_text(json.dumps({
        "media": {"source": "m:1", "expected_digest": "sha256:" + "0" * 64},
        "processing": "p:1", "worker": "w:1"}))
    with pytest.raises(DeployError, match="expected_digest"):
        rig.deploy()
    assert rig.steps()["images"] == "failed"


def evidence(status="LOCAL_ARTIFACT_PASS", **overrides):
    images = {o: {"tag": f"dc2-v1-{o}:local-abc", "config_id": f"sha256:{o}"}
              for o in ("media", "processing", "worker")}
    images.update(overrides)
    return {"schema_version": 2, "status": status, "images": images}


def test_the_build_scripts_evidence_file_is_accepted_directly(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence()))
    loaded = deploy.load_images(path)
    assert loaded["media"] == {"source": "dc2-v1-media:local-abc", "local_id": "sha256:media"}


def test_failing_build_evidence_is_refused(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence("LOCAL_ARTIFACT_FAIL")))
    with pytest.raises(DeployError, match="did not pass"):
        deploy.load_images(path)
    path.write_text(json.dumps(evidence(media={"tag": "x"})))
    with pytest.raises(DeployError, match="lacks image tags"):
        deploy.load_images(path)


def test_an_image_that_is_not_the_verified_build_is_refused(rig):
    rig.s.images_file.write_text(json.dumps(evidence()))
    with pytest.raises(DeployError, match="not the one the build evidence verified"):
        rig.deploy()
    assert rig.steps()["images"] == "failed"


@pytest.mark.parametrize("content,message", [
    ("not json", "unreadable"), ('{"media": "m"}', "exactly media"),
    ('{"media":"m","processing":"p","worker":"w x"}', "plain image reference"),
    ('{"media":"m","processing":"p","worker":{"source":"w","expected_digest":"sha256:short"}}',
     "sha256"),
    ('{"media":"m","processing":"p","worker":{"source":"w","extra":1}}', "needs 'source'"),
])
def test_images_input_is_validated(tmp_path, content, message):
    path = tmp_path / "i.json"
    path.write_text(content)
    with pytest.raises(DeployError, match=message):
        deploy.load_images(path)


# ---- database bootstrap ----------------------
def test_database_bootstrap_keeps_credentials_in_ssm_only_and_removes_the_temporary_input(rig):
    rig.deploy(stop_after="db-bootstrap")
    prefix = f"/dc2/{rig.s.env}/"
    assert sorted(rig.sim.params) == sorted(prefix + n for n in (
        "media_runtime_dsn", "media_migration_dsn", "processing_runtime_dsn",
        "processing_migration_dsn", "jwt_secret"))
    assert prefix + "bootstrap-input" not in rig.sim.params
    dsn = rig.sim.param_values[prefix + "media_runtime_dsn"]
    assert dsn.startswith("postgresql://media_runtime:") and dsn.endswith("/media_db")
    runtime_pw = dsn.split(":")[2].split("@")[0]
    state_text = (rig.s.state_dir / "deploy-journal.json").read_text()
    assert runtime_pw not in state_text and "postgresql://" not in state_text
    assert "simulated-master-password" not in state_text
    expected = {"deploy-project": "dc2-v1", "owner-run": "t1"}
    assert all(tags == expected for tags in rig.sim.params.values())


def test_the_four_database_roles_get_distinct_passwords_in_their_own_dsn(rig):
    rig.deploy(stop_after="db-bootstrap")
    prefix = f"/dc2/{rig.s.env}/"
    passwords = {k: rig.sim.param_values[prefix + k].split(":")[2].split("@")[0]
                 for k in ("media_runtime_dsn", "media_migration_dsn", "processing_runtime_dsn",
                           "processing_migration_dsn")}
    assert len(set(passwords.values())) == 4 and all(len(p) >= 24 for p in passwords.values())


def test_secrets_never_appear_in_the_printed_plan(rig):
    pipeline = rig.deploy(stop_after="db-bootstrap")
    text = json.dumps(pipeline.plan)
    assert "simulated-master-password" not in text
    prefix = f"/dc2/{rig.s.env}/"
    assert rig.sim.param_values[prefix + "jwt_secret"] not in text


def test_a_failed_bootstrap_task_still_removes_the_temporary_input_and_a_rerun_relaunches(rig):
    rig.sim.task_exit["bootstrap"] = 1
    with pytest.raises(DeployError, match="bootstrap task failed"):
        rig.deploy()
    assert f"/dc2/{rig.s.env}/bootstrap-input" not in rig.sim.params
    rig.sim.task_exit.clear()
    rig.deploy(stop_after="db-bootstrap")
    assert len(rig.ops("run-task")) == 2
    assert rig.steps()["db-bootstrap"] == "done"


def test_a_rerun_keeps_the_signing_key_stable(rig):
    rig.deploy(stop_after="db-bootstrap")
    key = f"/dc2/{rig.s.env}/jwt_secret"
    before = rig.sim.param_values[key]
    rig.journal.mutate(lambda d: d["steps"].pop("db-bootstrap"))
    rig.deploy(stop_after="db-bootstrap")
    assert rig.sim.param_values[key] == before


def test_an_existing_parameter_owned_by_someone_else_is_never_overwritten(rig):
    rig.sim.params[f"/dc2/{rig.s.env}/media_runtime_dsn"] = {}
    with pytest.raises(DeployError, match="not owned by this run"):
        rig.pipeline().put_parameter(f"/dc2/{rig.s.env}/media_runtime_dsn", "value")
    assert rig.sim.param_values == {}


# ---- migrations ----------------------
def test_each_owner_migrates_once_through_the_shared_module_in_order(rig):
    rig.deploy(stop_after="migrations")
    tasks = [p["taskDefinition"] for _, _, p in rig.ops("run-task")]
    assert [t.split("/")[-1].split(":")[0].rsplit("-", 1)[-1] for t in tasks] == [
        "bootstrap", "mediamigration", "processingmigration"]
    detail = rig.journal.view()["steps"]["migrations"]["detail"]
    assert detail["owners_done"] == ["media", "processing"]
    assert detail["schema_check"] == "task-exit-code-only"
    assert detail["media_revision"].startswith("media_") and detail["processing_revision"]
    assert rig.journal.view()["steps"]["migrations"]["status"] == "done"


def test_a_failed_migration_does_not_repeat_the_owner_that_finished(rig):
    rig.sim.task_exit["processingmigration"] = 1
    with pytest.raises(OperationError):
        rig.deploy()
    detail = rig.journal.view()["steps"]["migrations"]["detail"]
    assert detail["owners_done"] == ["media"]
    rig.sim.task_exit.clear()
    rig.deploy(stop_after="migrations")
    runs = [p["taskDefinition"].split("/")[-1] for _, _, p in rig.ops("run-task")]
    assert sum("mediamigration" in r for r in runs) == 1
    assert sum("processingmigration" in r for r in runs) == 2  # the failed one is not replayed


def test_the_migration_journal_lock_is_never_taken_twice(rig):
    pipeline = rig.deploy(stop_after="migrations")
    events = rig.journal.view()["events"]
    assert any(e["call"] == "ecs.run-task" and e["step"] == "migrations" for e in events)
    assert pipeline.deferred == []


def test_schema_revision_is_read_from_sql_only_when_the_station_can_reach_it(rig, tmp_path):
    sql = tmp_path / "sql.json"
    sql.write_text(json.dumps({
        "ca_file": "/ca.pem", "media_dsn_file": "/m", "processing_dsn_file": "/p"}))
    rig.s.sql_config = sql
    hook, label = rig.pipeline().schema_reader({"media": "m", "processing": "p"})
    assert label == "alembic_version-over-verified-tls" and callable(hook)
    rig.s.sql_config = None
    hook, label = rig.pipeline().schema_reader({"media": "m", "processing": "p"})
    assert label == "task-exit-code-only" and hook("media", deadline=1) == "m"


def test_sql_config_rejects_unknown_fields(rig, tmp_path):
    path = tmp_path / "sql.json"
    path.write_text('{"password": "x"}')
    rig.s.sql_config = path
    with pytest.raises(DeployError, match="unsupported"):
        rig.pipeline().sql_settings()


# ---- seed, smoke and session ----------------------
def test_session_init_refuses_when_the_window_could_not_be_closed(tmp_path):
    rig = Rig(tmp_path, assume_empty_counts=False)
    pipeline = rig.pipeline()
    pipeline.step = "session-init"
    with pytest.raises(DeployError, match="could not be closed"):
        pipeline.step_session_init()
    assert rig.session.actions == []


def test_the_operator_config_for_the_session_cli_is_private_and_nonsecret(rig):
    rig.deploy(stop_after="migrations")
    path = rig.pipeline().write_ops_config()
    data = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert set(data) == {"operator_station", "environment_id", "journal", "outputs_file",
                         "counts_file"}
    assert stat.S_IMODE(Path(data["counts_file"]).stat().st_mode) == 0o600


def test_seed_registers_through_the_public_endpoint_and_keeps_the_password_private(rig):
    rig.deploy(stop_after="seed")
    path = rig.s.state_dir / "smoke-credentials.json"
    creds = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert creds["email"] == "smoke@example.com" and len(creds["password"]) >= 24
    assert ("POST", "/api/media/auth/register") in rig.gateway.requests
    assert creds["password"] not in (rig.s.state_dir / "deploy-journal.json").read_text()
    assert rig.journal.view()["steps"]["seed"]["detail"]["role"] == "user"


def test_seed_treats_an_existing_account_as_success_and_other_statuses_as_failure(tmp_path):
    rig = Rig(tmp_path, gateway=FakeGateway(register=409))
    rig.deploy(stop_after="seed")
    assert rig.journal.view()["steps"]["seed"]["detail"]["registered"] == "already-exists"
    rig = Rig(tmp_path / "other", gateway=FakeGateway(register=500))
    with pytest.raises(DeployError, match="HTTP 500"):
        rig.deploy(stop_after="seed")


def test_seed_needs_an_address(tmp_path):
    rig = Rig(tmp_path, seed_email=None)
    with pytest.raises(DeployError, match="--seed-email"):
        rig.deploy()


def test_the_smoke_runs_every_public_check_through_the_gateway(rig):
    rig.deploy()
    detail = rig.journal.view()["steps"]["public-smoke"]["detail"]["checks"]
    assert set(detail.values()) == {"PASS"}
    assert {"media-health", "processing-health", "anonymous-denied", "login",
            "upload-reserve"} <= set(detail)


def test_a_failing_smoke_fails_the_run_and_still_closes_the_session_window(tmp_path):
    rig = Rig(tmp_path, gateway=FakeGateway(login=401))
    with pytest.raises(DeployError, match="PublicSmoke failed.*login"):
        rig.deploy()
    assert rig.session.actions == ["init", "window", "close"]
    assert rig.steps()["public-smoke"] == "failed"
    assert "session-window" not in rig.steps()  # a rerun must reopen it
    rig.gateway.login = 200
    rig.deploy()
    assert rig.session.actions == ["init", "window", "close", "window", "close"]
    assert set(rig.steps().values()) == {"done"}


def test_the_window_is_used_not_a_full_open_so_no_consumer_or_worker_starts(rig):
    rig.deploy()
    assert rig.session.actions == ["init", "window", "close"]


# ---- the whole path ----------------------
def test_a_full_deploy_runs_the_steps_in_order_and_journals_each(rig):
    pipeline = rig.deploy()
    assert list(rig.steps()) == list(DEPLOY_STEPS)
    assert set(rig.steps().values()) == {"done"}
    seen = []
    for entry in pipeline.plan:
        if entry["mutating"] and (not seen or seen[-1] != entry["step"]):
            seen.append(entry["step"])
    assert seen == [s for s in DEPLOY_STEPS if s in seen]


def test_every_pipeline_created_resource_carries_the_project_and_run_tags(rig):
    rig.deploy()
    expected = {"deploy-project": "dc2-v1", "owner-run": "t1"}
    stacks = [rig.s.env, rig.s.bootstrap_stack]
    assert all(rig.sim.stacks[s]["tags"] == expected for s in stacks)
    for table in (rig.sim.buckets, rig.sim.repos, rig.sim.clusters, rig.sim.instances):
        assert all(item["tags"] == expected for item in table.values())
    assert all(tags == expected for tags in rig.sim.groups.values())
    assert all(tags == expected for tags in rig.sim.params.values())


def test_a_second_run_of_a_finished_deploy_makes_no_mutating_calls(rig):
    rig.deploy()
    before = len(rig.sim.calls)
    rig.deploy()
    assert rig.mutating(since=before) == []


def test_a_rerun_resumes_at_the_failed_step_without_repeating_finished_ones(rig):
    rig.sim.fail[("ecr", "get-authorization-token")] = [AwsError("ecr", "x", "ThrottlingException")]
    with pytest.raises(AwsError):
        rig.deploy()
    assert rig.steps()["foundation"] == "done" and rig.steps()["images"] == "failed"
    creates = len(rig.ops("create-change-set"))
    rig.deploy()
    assert len(rig.ops("create-change-set")) == creates + 1  # only the applications update
    assert set(rig.steps().values()) == {"done"}


def test_a_crash_after_execute_but_before_journaling_does_not_execute_twice(rig):
    rig.deploy(stop_after="bootstrap-stack")
    rig.journal.mutate(lambda d: d["steps"].pop("bootstrap-stack"))
    rig.deploy(stop_after="bootstrap-stack")
    assert len([c for c in rig.ops("execute-change-set")
                if c[2]["StackName"].endswith("bootstrap")]) == 1


def test_only_one_process_may_run_a_given_run_at_a_time(rig):
    with rig.journal.run_lock():
        with pytest.raises(DeployError, match="Another deploy"):
            with rig.journal.run_lock():
                pass


def test_failure_text_that_trips_the_secret_screen_is_withheld_not_fatal(rig):
    def leaky(payload):
        raise DeployError("connect to postgresql://u:p@h/db failed")

    rig.sim.sts_get_caller_identity = leaky
    with pytest.raises(DeployError):
        rig.deploy()
    assert "withheld" in rig.journal.view()["steps"]["preflight"]["detail"]["error"]


def test_the_journal_contains_names_and_hashes_but_no_credentials(rig):
    rig.deploy()
    text = (rig.s.state_dir / "deploy-journal.json").read_text()
    for forbidden in ("postgresql://", "simulated-master-password", "password\":",
                      "simulated-registry-password"):
        assert forbidden not in text
    assert all(p not in text for p in rig.sim.param_values.values())


# ---- teardown ----------------------
@pytest.fixture
def deployed(tmp_path):
    rig = Rig(tmp_path)
    rig.deploy()
    return rig


def test_teardown_without_execute_inventories_and_deletes_nothing(deployed):
    deployed.s.execute = False
    before = len(deployed.sim.calls)
    with pytest.raises(AwaitingExecute, match="nothing deleted"):
        deployed.teardown()
    assert deployed.mutating(since=before) == []
    assert "td-inventory" in deployed.steps()


def test_teardown_execute_needs_the_run_id_repeated(deployed):
    deployed.s.confirm_run_id = "something-else"
    with pytest.raises(DeployError, match="--confirm-run-id"):
        deployed.teardown()


def first_index(rig, operation, **match):
    for index, (_, op, payload) in enumerate(rig.sim.calls):
        if op == operation and all(payload.get(k) == v for k, v in match.items()):
            return index
    raise AssertionError(f"{operation} {match} never called")


def test_teardown_deletes_in_dependency_order(deployed):
    deployed.s.confirm_run_id = "t1"
    start = len(deployed.sim.calls)
    deployed.teardown()
    sim = deployed.sim
    order = [
        first_index(deployed, "delete-objects"), first_index(deployed, "batch-delete-image"),
        first_index(deployed, "delete-db-instance"), first_index(deployed, "delete-db-cluster"),
        first_index(deployed, "delete-parameter", Name=f"/dc2/{deployed.s.env}/media_runtime_dsn"),
        first_index(deployed, "delete-stack", StackName=deployed.s.env),
        first_index(deployed, "delete-stack", StackName=deployed.s.bootstrap_stack),
        first_index(deployed, "delete-bucket"), first_index(deployed, "delete-repository"),
    ]
    assert order == sorted(order) and min(order) >= 0
    assert not sim.buckets and not sim.repos and not sim.clusters and not sim.instances
    assert not sim.params and not sim.groups
    assert start > 0


def test_teardown_removes_every_version_and_delete_marker_before_deleting_a_bucket(deployed):
    deployed.s.confirm_run_id = "t1"
    seeded = {name: (len(b["versions"]), len(b["markers"]))
              for name, b in deployed.sim.buckets.items()}
    assert any(v and m for v, m in seeded.values())
    deployed.teardown()
    removed = [o["VersionId"] for _, op, p in deployed.sim.calls if op == "delete-objects"
               for o in p["Delete"]["Objects"]]
    assert "dm1" in removed and "v1" in removed and "v2" in removed
    assert deployed.sim.buckets == {}


def test_teardown_takes_a_final_snapshot_by_default_and_tags_it(deployed):
    deployed.s.confirm_run_id = "t1"
    deployed.teardown()
    request = deployed.ops("delete-db-cluster")[0][2]
    assert request["SkipFinalSnapshot"] is False
    assert request["FinalDBSnapshotIdentifier"] == f"{deployed.s.env}-final"
    assert deployed.sim.snapshots[f"{deployed.s.env}-final"]["tags"] == {
        "deploy-project": "dc2-v1", "owner-run": "t1"}
    assert deployed.ops("modify-db-cluster")[0][2]["DeletionProtection"] is False


def test_skipping_the_final_snapshot_is_explicit_and_leaves_a_clean_receipt(tmp_path):
    rig = Rig(tmp_path, skip_final_snapshot=True, confirm_run_id="t1")
    rig.deploy()
    pipeline = rig.teardown()
    request = rig.ops("delete-db-cluster")[0][2]
    assert request == {"DBClusterIdentifier": request["DBClusterIdentifier"],
                       "SkipFinalSnapshot": True}
    assert rig.sim.snapshots == {}
    assert pipeline.receipt["status"] == "CLEAN" and pipeline.receipt["resources_remaining"] == []
    assert pipeline.receipt["final_snapshot"] == "skipped by operator"


def test_the_receipt_lists_the_snapshot_as_remaining_by_default(deployed):
    deployed.s.confirm_run_id = "t1"
    receipt = deployed.teardown().receipt
    assert receipt["status"] == "ITEMS_REMAIN"
    assert [r["kind"] for r in receipt["resources_remaining"]] == ["aurora-snapshot"]
    assert receipt["issue"] == "#67" and receipt["simulated"] is True
    path = deployed.s.state_dir / "teardown-receipt-t1.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["run_id"] == "t1"


def test_the_receipt_names_the_preexisting_stack_it_never_touched(deployed):
    deployed.s.confirm_run_id = "t1"
    receipt = deployed.teardown().receipt
    assert receipt["pre_existing_untouched"] == [{
        "kind": "cloudformation-stack", "id": deploy.LEGACY_BOOTSTRAP_STACK,
        "status": "ROLLBACK_COMPLETE"}]
    deleted = {p.get("StackName") for _, op, p in deployed.sim.calls if op == "delete-stack"}
    assert deploy.LEGACY_BOOTSTRAP_STACK not in deleted


def test_a_resource_whose_tags_no_longer_match_is_skipped_and_reported(deployed):
    deployed.s.confirm_run_id = "t1"
    victim = next(iter(deployed.sim.buckets))
    deployed.sim.buckets[victim]["tags"] = {"owner-run": "someone-else", "deploy-project": "dc2-v1"}
    foreign_repo = next(iter(deployed.sim.repos))
    deployed.sim.repos[foreign_repo]["tags"] = {}
    receipt = deployed.teardown().receipt
    kept = {(r["kind"], r["id"]) for r in receipt["skipped_not_owned"]}
    assert ("bucket", victim) in kept and ("repository", foreign_repo) in kept
    assert victim in deployed.sim.buckets and foreign_repo in deployed.sim.repos
    assert not [c for c in deployed.ops("delete-bucket") if c[2]["Bucket"] == victim]
    assert not [c for c in deployed.ops("delete-repository")
                if c[2]["repositoryName"] == foreign_repo]
    remaining = {r["id"] for r in receipt["resources_remaining"]}
    assert {victim, foreign_repo} <= remaining


def test_an_untagged_parameter_in_the_run_namespace_is_kept_not_deleted(deployed):
    deployed.s.confirm_run_id = "t1"
    stray = f"/dc2/{deployed.s.env}/hand-made"
    deployed.sim.params[stray] = {}
    receipt = deployed.teardown().receipt
    assert stray in deployed.sim.params
    assert stray in {r["id"] for r in receipt["resources_remaining"]}


def test_a_resource_the_journal_never_recorded_is_not_deleted_even_if_tagged_for_the_run(deployed):
    deployed.s.confirm_run_id = "t1"
    deployed.sim.buckets["unrecorded"] = {
        "tags": {"deploy-project": "dc2-v1", "owner-run": "t1"}, "versions": [], "markers": [],
        "uploads": []}
    receipt = deployed.teardown().receipt
    assert "unrecorded" in deployed.sim.buckets
    assert any(r["kind"] == "tagged-resource" and "unrecorded" in r["id"]
               for r in receipt["resources_remaining"])


def test_a_stack_deleted_while_the_database_still_exists_fails_instead_of_orphaning_it(deployed):
    pipeline = deployed.pipeline()
    pipeline.step = "td-stack"
    pipeline.td_inventory()
    with pytest.raises(DeployError, match="DELETE_FAILED.*dependencies"):
        pipeline.td_stack()


def test_teardown_resumes_after_a_failure_without_redoing_finished_steps(deployed):
    deployed.s.confirm_run_id = "t1"
    deployed.sim.fail[("rds", "delete-db-instance")] = [AwsError("rds", "x", "Throttling")]
    with pytest.raises(AwsError):
        deployed.teardown()
    done = {k for k, v in deployed.steps().items() if v == "done" and k.startswith("td-")}
    assert {"td-inventory", "td-quiesce", "td-buckets-emptied", "td-images-deleted"} <= done
    emptied = len(deployed.ops("delete-objects"))
    receipt = deployed.teardown().receipt
    assert len(deployed.ops("delete-objects")) == emptied
    assert receipt["resources_remaining"][0]["kind"] == "aurora-snapshot"
    assert deployed.sim.clusters == {} and deployed.sim.stacks[deployed.s.env]["status"] == (
        "DELETE_COMPLETE")


def test_teardown_is_idempotent_when_everything_is_already_gone(deployed):
    deployed.s.confirm_run_id = "t1"
    deployed.teardown()
    deployed.journal.mutate(lambda d: [d["steps"].pop(k) for k in list(d["steps"])
                                       if k.startswith("td-")])
    receipt = deployed.teardown().receipt
    assert receipt["status"] == "ITEMS_REMAIN" and len(receipt["resources_remaining"]) == 1


def test_teardown_stops_running_tasks_in_the_project_cluster(deployed):
    deployed.s.confirm_run_id = "t1"
    outputs = deployed.journal.view()["outputs"]
    deployed.sim.tasks["arn:task/stray"] = {"definition": "d", "polls": 0, "stopped": False}
    deployed.teardown()
    stops = deployed.ops("stop-task")
    assert [p["task"] for _, _, p in stops] == ["arn:task/stray"]
    assert stops[0][2]["cluster"] == outputs["ClusterArn"]


def test_teardown_needs_a_journal_to_know_what_this_run_created(tmp_path):
    out = io.StringIO()
    code = deploy.main(["teardown", *ARGS, "--run-id", "t1", "--state-dir",
                        str(private(tmp_path / "s")), "--execute", "--confirm-run-id", "t1"],
                       transport=deploy_sim.SimulatedAws(settings_for(tmp_path)), stdout=out,
                       stderr=io.StringIO())
    assert code == 1 and "No journal" in json.loads(out.getvalue())["error"]


# ---- the command line ----------------------
def private(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def run_main(argv, **kwargs):
    out = io.StringIO()
    code = deploy.main(argv, stdout=out, stderr=io.StringIO(), **kwargs)
    return code, out.getvalue()


def test_rehearse_simulates_the_whole_deploy_and_teardown_without_a_process_or_state_dir(
        monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("a dry run must not start a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    code, text = run_main(["rehearse", *ARGS, "--run-id", "rehearsal1"], today=lambda: TODAY)
    document = text[:text.index("\n## ")] if "\n## " in text else text
    result = json.loads(document)
    assert code == 0 and result["mode"] == "dry-run" and "simulated" in result
    assert list(result["steps"]) == [*DEPLOY_STEPS, *TEARDOWN_STEPS]
    assert result["resources_remaining_receipt"]["status"] == "ITEMS_REMAIN"
    assert result["mutating_calls"] > 40


def test_dry_run_prints_exact_cli_commands_grouped_by_step_and_hides_reads_by_default():
    code, text = run_main(["deploy", *ARGS, "--run-id", "rehearsal1", "--dry-run"],
                          today=lambda: TODAY)
    plan = text[text.index("\n## ") + 1:]
    assert code == 0
    assert plan.index("## bootstrap-stack") < plan.index("## foundation") < plan.index("## images")
    assert "cloudformation execute-change-set" in plan
    assert "describe-stacks" not in plan
    assert "--profile dc2-project2 --region ap-southeast-1" in plan
    assert "<redacted>" in plan and "simulated-master-password" not in plan


def test_dry_run_can_show_every_read_call_too():
    code, text = run_main(["deploy", *ARGS, "--run-id", "rehearsal1", "--dry-run",
                           "--plan-detail", "all"], today=lambda: TODAY)
    assert "cloudformation describe-stacks" in text and "sts get-caller-identity" in text


def test_dry_run_never_touches_a_real_state_directory(tmp_path):
    state = private(tmp_path / "real")
    code, _ = run_main(["deploy", *ARGS, "--run-id", "rehearsal1", "--dry-run",
                        "--state-dir", str(state)], today=lambda: TODAY)
    assert code == 0 and list(state.iterdir()) == []


def test_dry_run_and_execute_are_mutually_exclusive():
    code, text = run_main(["deploy", *ARGS, "--run-id", "t1", "--dry-run", "--execute"])
    assert code == 1 and "mutually exclusive" in text


def test_a_live_run_needs_a_private_state_directory_outside_the_repository(tmp_path):
    code, text = run_main(["deploy", *ARGS, "--run-id", "t1"])
    assert code == 1 and "--state-dir is required" in text
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    os.chmod(loose, 0o755)
    code, text = run_main(["deploy", *ARGS, "--run-id", "t1", "--state-dir", str(loose)])
    assert code == 1 and "private" in text
    code, text = run_main(["deploy", *ARGS, "--run-id", "t1", "--state-dir",
                           str(private(deploy.ROOT / ".cache-test-state"))])
    assert code == 1 and "outside the repository" in text
    (deploy.ROOT / ".cache-test-state").rmdir()


def test_a_live_deploy_without_execute_exits_3_after_describing_the_first_change_set(tmp_path):
    state = private(tmp_path / "state")
    settings = settings_for(tmp_path)
    sim = deploy_sim.SimulatedAws(settings)
    code, text = run_main(["deploy", *ARGS, "--run-id", "t1", "--state-dir", str(state),
                           "--assume-empty-counts"], transport=sim,
                          docker=deploy_sim.SimulatedDocker(sim), today=lambda: TODAY)
    assert code == 3 and "--execute" in json.loads(text)["awaiting_execute"]
    assert not [c for c in sim.calls if c[1] == "execute-change-set"]
    code, text = run_main(["status", *ARGS, "--run-id", "t1", "--state-dir", str(state)])
    steps = json.loads(text)["steps"]
    assert code == 0 and steps["bootstrap-stack"]["status"] == "awaiting-execute"


def test_teardown_dry_run_rehearses_a_recorded_journal_and_leaves_it_untouched(deployed):
    journal_file = deployed.s.state_dir / "deploy-journal.json"
    before = journal_file.read_bytes()
    code, text = run_main(["teardown", *ARGS, "--run-id", "t1", "--dry-run", "--state-dir",
                           str(deployed.s.state_dir)], today=lambda: TODAY)
    assert code == 0 and "delete-stack" in text and "delete-db-cluster" in text
    assert journal_file.read_bytes() == before


def test_teardown_dry_run_without_a_state_dir_points_at_rehearse():
    code, text = run_main(["teardown", *ARGS, "--run-id", "t1", "--dry-run"])
    assert code == 1 and "rehearse" in text


def test_the_format_plan_helper_groups_steps_and_filters_reads():
    plan = [{"step": "a", "mutating": False, "command": "read"},
            {"step": "a", "mutating": True, "command": "write"},
            {"step": "b", "mutating": False, "command": "# note"}]
    assert deploy.format_plan(plan, "mutating") == "## a\nwrite\n\n## b\n# note"
    assert "read" in deploy.format_plan(plan, "all")


# Needs the external AWS CLI and spawns it per request shape, which took over 100 s on a CI
# runner under coverage. Marked integration so the fast tier skips it; the V1 CI job runs it.
@pytest.mark.integration
@pytest.mark.timeout(120)
@pytest.mark.skipif(shutil.which("aws") is None, reason="needs the AWS CLI's offline skeletons")
def test_every_request_field_exists_in_the_installed_cli_skeleton(deployed, tmp_path):
    """`--generate-cli-skeleton` is offline: it proves the JSON keys are real CLI parameters."""
    deployed.s.confirm_run_id = "t1"
    deployed.s.forecast_usd, deployed.sim.forecast = None, 1.0
    first = next(iter(deployed.sim.buckets))
    deployed.sim.buckets[first]["uploads"].append({"Key": "k", "UploadId": "u"})
    deployed.sim.tasks["arn:task/stray"] = {"definition": "d", "polls": 0, "stopped": False}
    pipeline = deployed.pipeline()
    pipeline.cost_guard()
    pipeline._failure_reasons(deployed.s.env)
    deployed.teardown()
    seen = {}
    for service, operation, payload in deployed.sim.calls:
        seen.setdefault((service, operation), set()).update(payload)
    environment = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
                   "AWS_EC2_METADATA_DISABLED": "true"}
    unknown = {}

    def skeleton(item):
        (service, operation), keys = item
        out = subprocess.run(
            ["aws", service, operation, "--generate-cli-skeleton", "input"], env=environment,
            capture_output=True, text=True, check=True, timeout=90)
        return f"{service} {operation}", keys - set(json.loads(out.stdout)) - {"Body"}

    # Each CLI start costs seconds on a CI runner; run them side by side to stay in budget.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, extra in pool.map(skeleton, sorted(seen.items())):
            if extra:
                unknown[name] = sorted(extra)
    assert unknown == {}
    assert {("ce", "get-cost-forecast"), ("ecs", "stop-task"),
            ("s3api", "abort-multipart-upload")} <= set(seen)
