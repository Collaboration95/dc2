"""Offline guards for the CD workflow: no stored AWS key, pinned actions, a real CI gate."""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CD_SCRIPT = ROOT / "scripts/ci/cd.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())


def test_every_action_is_pinned_to_a_commit(workflow):
    uses = [
        step["uses"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert uses
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref) for ref in uses), uses


def test_no_long_lived_aws_key_is_ever_referenced():
    text = (ROOT / ".github/workflows/cd.yml").read_text()
    script = CD_SCRIPT.read_text()
    for forbidden in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "secrets."):
        assert forbidden not in text.replace("unset AWS_ACCESS_KEY_ID", "")
    # The script only unsets them; it never sets one.
    assert not re.search(r"(?<!unset )AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)=", script)


def test_aws_runs_only_in_the_protected_environment_with_oidc(workflow):
    run = workflow["jobs"]["run"]
    assert run["environment"] == "aws"
    assert run["needs"] == "gate"
    assert run["permissions"]["id-token"] == "write"
    # The gate job reads CI results and must not be able to mint AWS credentials.
    assert "id-token" not in workflow["jobs"]["gate"]["permissions"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assume = next(
        s for s in run["steps"] if s.get("uses", "").startswith("aws-actions/configure-aws")
    )
    assert assume["with"]["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    assert assume["with"]["aws-profile"] == "dc2-gha"
    assert assume["with"]["allowed-account-ids"] == "866865534361"


def test_dispatch_offers_the_four_operations_and_nothing_applies_by_default(workflow):
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert inputs["operation"]["options"] == ["preflight", "deploy", "release", "teardown"]
    assert inputs["owner"]["options"] == ["none", "media", "processing"]
    assert inputs["execute"]["default"] is False
    # V2-live (#235): one persistent environment instead of a run id per stack.
    assert inputs["environment"]["default"] == "live" and "run_id" not in inputs
    assert inputs["confirm"]["default"] == ""
    assert inputs["budget_usd"]["default"] == "30"
    assert inputs["planned_hours"]["default"] == "3"


def test_state_is_saved_even_when_the_run_fails_and_never_after_a_failed_restore(workflow):
    steps = {s.get("name"): s for s in workflow["jobs"]["run"]["steps"]}
    save = steps["Save the environment's state to the private bucket"]
    assert "always()" in save["if"]
    assert "steps.state.outcome == 'success'" in save["if"]
    upload = steps["Upload the redacted results"]
    assert upload["with"]["path"].endswith("cd-out/public/")


def test_the_wrapped_entry_points_are_the_existing_ones():
    script = CD_SCRIPT.read_text()
    for entry in (
        "scripts.aws.v1.deploy",
        "scripts.aws.v1.release",
        "scripts.aws.v1.evidence",
        "deploy/v1/build_and_verify.py",
    ):
        assert entry in script


def test_every_deploy_call_targets_the_persistent_environment_and_state_follows_it():
    script = CD_SCRIPT.read_text()
    assert '--environment "$CD_ENVIRONMENT"' in script and "--run-id \"$CD_RUN_ID\"" not in script
    assert "--unattended-launch" not in script  # the environment always deploys the launcher
    assert script.count("s3://$CD_STATE_BUCKET/envs/$CD_ENVIRONMENT/") == 2


def test_green_ci_on_main_updates_the_environment_in_place(workflow):
    trigger = workflow[True]["workflow_run"]
    assert trigger == {"workflows": ["CI"], "types": ["completed"], "branches": ["Main"]}
    condition = workflow["jobs"]["gate"]["if"]
    for clause in ("conclusion == 'success'", "event == 'push'",
                   "head_repository.full_name == github.repository"):
        assert clause in condition
    assert "workflow_run' && 'deploy'" in workflow["env"]["CD_OPERATION"]
    assert "workflow_run.head_sha" in workflow["env"]["CD_SHA"]
    checkouts = [s for job in workflow["jobs"].values() for s in job["steps"]
                 if s.get("uses", "").startswith("actions/checkout")]
    assert checkouts and all(s["with"]["ref"] == "${{ env.CD_SHA }}" for s in checkouts)


def test_releases_run_online_and_cd_never_closes_or_reopens_the_environment():
    script = CD_SCRIPT.read_text()
    # The kill switch is the operator's: CD neither engages it nor undoes it.
    assert "scripts.aws.v1.session" not in script
    calls = [line for line in script.splitlines() if "scripts.aws.v1.release " in line]
    assert len(calls) == 3  # promote, restore, abandon
    for call in ('local promote=(--config "$config" "${SCOPE[@]}" --online',
                 'local restore=(--config "$config" "${SCOPE[@]}" --online',
                 'release abandon --config "$config" "${SCOPE[@]}" --online'):
        assert call in script, call
    # No task definition revision is ever deregistered by CD: another record may name it.
    assert "--deregister" not in script


def test_an_automatic_deploy_never_creates_the_environment():
    script = CD_SCRIPT.read_text()
    deploy = script.split("cmd_deploy() {", 1)[1]
    guard = deploy.split("cost_flags", 1)[0]
    assert 'CD_EVENT:-}" = workflow_run' in guard and ".deploy.established" in guard
    assert "return 0" in guard


def test_script_is_executable_and_parses():
    assert CD_SCRIPT.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(CD_SCRIPT)], check=True)


@pytest.fixture
def gate(tmp_path):
    """Run `cd.sh gate` with a fake `gh` that answers the workflow-runs query."""
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    # gh applies --jq itself, so the fake must as well or the real filter would go untested.
    (tmp_path / "gh").write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
        '  if [ "$1" = --jq ]; then jq "$2" "$FAKE_RUNS"; exit; fi\n  shift\ndone\n'
    )
    (tmp_path / "gh").chmod(0o755)

    def run(runs, **overrides):
        reply = tmp_path / "runs.json"
        reply.write_text(json.dumps({"workflow_runs": runs}))
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "FAKE_RUNS": str(reply),
            "RUNNER_TEMP": str(tmp_path),
            "CD_OPERATION": "deploy",
            "CD_ENVIRONMENT": "live",
            "CD_SHA": SHA,
            "CD_REPO": "Collaboration95/dc2",
            "CD_EVENT": "workflow_dispatch",
            "CD_BUDGET_USD": "30",
            "CD_PLANNED_HOURS": "3",
            "CD_FORECAST_USD": "5",
            "CD_OWNER": "none",
            **overrides,
        }
        return subprocess.run(
            ["bash", str(CD_SCRIPT), "gate"], env=env, capture_output=True, text=True, cwd=ROOT
        )

    return run


def ci_run(conclusion, *, status="completed", created="2026-10-18T00:00:00Z"):
    return {
        "id": 1,
        "status": status,
        "conclusion": conclusion,
        "event": "pull_request",
        "html_url": "https://github.com/x/y/actions/runs/1",
        "created_at": created,
    }


def test_gate_accepts_a_green_ci_run(gate):
    done = gate([ci_run("success")])
    assert done.returncode == 0, done.stdout + done.stderr


def test_gate_refuses_a_commit_that_never_ran_ci(gate):
    done = gate([])
    assert done.returncode == 1
    assert "No CI run exists" in done.stdout


def test_gate_refuses_a_failed_latest_run_even_after_an_older_green_one(gate):
    done = gate([ci_run("success"), ci_run("failure", created="2026-10-18T01:00:00Z")])
    assert done.returncode == 1
    assert "failure" in done.stdout


def test_gate_refuses_while_ci_is_still_running(gate):
    done = gate([ci_run(None, status="in_progress")])
    assert done.returncode == 1
    assert "still running" in done.stdout


def test_gate_validates_inputs_before_trusting_ci(gate):
    assert gate([ci_run("success")], CD_ENVIRONMENT="Bad_ID").returncode == 1
    assert gate([ci_run("success")], CD_OPERATION="release").returncode == 1
    assert gate([ci_run("success")], CD_OPERATION="release", CD_OWNER="media").returncode == 0
    assert gate([ci_run("success")], CD_BUDGET_USD="lots").returncode == 1


def test_a_non_dispatch_trigger_may_only_run_the_read_only_preflight(gate):
    assert gate([], CD_EVENT="push", CD_OPERATION="preflight").returncode == 0
    assert gate([], CD_EVENT="push", CD_OPERATION="deploy").returncode == 1


def test_a_ci_completion_may_only_deploy_and_still_needs_green_ci_for_its_commit(gate):
    assert gate([ci_run("success")], CD_EVENT="workflow_run").returncode == 0
    assert gate([ci_run("failure")], CD_EVENT="workflow_run").returncode == 1
    assert gate([ci_run("success")], CD_EVENT="workflow_run", CD_OPERATION="teardown",
                CD_EXECUTE="true", CD_CONFIRM="live").returncode == 1


def test_an_executed_teardown_needs_the_environment_name_typed_again(gate):
    down = {"CD_OPERATION": "teardown", "CD_EXECUTE": "true"}
    assert gate([ci_run("success")], **down).returncode == 1
    assert gate([ci_run("success")], CD_CONFIRM="other", **down).returncode == 1
    assert gate([ci_run("success")], CD_CONFIRM="live", **down).returncode == 0
    # The plan alone deletes nothing and needs no confirmation.
    assert gate([ci_run("success")], CD_OPERATION="teardown").returncode == 0


def test_a_bad_candidate_is_only_accepted_for_an_executed_release(gate):
    ok = {"CD_OPERATION": "release", "CD_OWNER": "processing", "CD_EXECUTE": "true"}
    assert gate([ci_run("success")], CD_BAD_CANDIDATE="true", **ok).returncode == 0
    assert gate([ci_run("success")], CD_BAD_CANDIDATE="true", **{**ok, "CD_EXECUTE": "false"}
                ).returncode == 1
    assert gate([ci_run("success")], CD_BAD_CANDIDATE="true", CD_OPERATION="deploy",
                CD_EXECUTE="true").returncode == 1
    assert gate([ci_run("success")], CD_BAD_CANDIDATE="false", CD_OPERATION="deploy"
                ).returncode == 0


def test_the_bad_candidate_input_reaches_the_script_off_by_default(workflow):
    spec = workflow[True]["workflow_dispatch"]["inputs"]["bad_candidate"]
    assert spec["type"] == "boolean" and spec["default"] is False
    assert "CD_BAD_CANDIDATE" in workflow["env"]


@pytest.mark.parametrize(
    ("owner", "handler", "variable"),
    [
        ("processing", "processing/lambda_handler.py", "PROCESSING_DATABASE_CA_FILE"),
        ("media", "media/lambda_handler.py", "MEDIA_POSTGRES_SSL_CA"),
    ],
)
def test_the_bad_candidate_changes_only_the_lambda_handler_and_commits_it_locally(
        tmp_path, owner, handler, variable):
    repo = tmp_path / "repo"
    (repo / owner).mkdir(parents=True)
    original = '"""entrypoint"""\n\nfrom contracts import x\n'
    (repo / handler).write_text(original)
    (repo / "other.py").write_text("untouched\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@invalid"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "base"], cwd=repo, check=True)
    before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True)
    env = {**os.environ, "CD_ENVIRONMENT": "live", "CD_OPERATION": "release",
           "RUNNER_TEMP": str(tmp_path)}
    done = subprocess.run(["bash", str(CD_SCRIPT), "inject-bad-candidate", owner], env=env,
                          cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    patched = (repo / handler).read_text()
    # The assignment comes before every import of the service, and the original is intact.
    assert patched.startswith("import os\nimport certifi\n")
    assert f'os.environ["{variable}"] = certifi.where()' in patched
    assert patched.endswith(original)
    assert (repo / "other.py").read_text() == "untouched\n"
    after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True)
    assert after != before  # a new commit, so the image label differs from the deployed one
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True)
    assert status.strip() == ""
