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
    assert inputs["run_id"]["required"] is True
    assert inputs["budget_usd"]["default"] == "30"
    assert inputs["planned_hours"]["default"] == "3"


def test_state_is_saved_even_when_the_run_fails_and_never_after_a_failed_restore(workflow):
    steps = {s.get("name"): s for s in workflow["jobs"]["run"]["steps"]}
    save = steps["Save the run's state to the private bucket"]
    assert "always()" in save["if"]
    assert "steps.state.outcome == 'success'" in save["if"]
    upload = steps["Upload the redacted results"]
    assert upload["with"]["path"].endswith("cd-out/public/")


def test_the_wrapped_entry_points_are_the_existing_ones():
    script = CD_SCRIPT.read_text()
    for entry in (
        "scripts.aws.v1.deploy",
        "scripts.aws.v1.session",
        "scripts.aws.v1.release",
        "scripts.aws.v1.evidence",
        "deploy/v1/build_and_verify.py",
    ):
        assert entry in script


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
            "CD_RUN_ID": "r1018a",
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
    assert gate([ci_run("success")], CD_RUN_ID="Bad_ID").returncode == 1
    assert gate([ci_run("success")], CD_OPERATION="release").returncode == 1
    assert gate([ci_run("success")], CD_OPERATION="release", CD_OWNER="media").returncode == 0
    assert gate([ci_run("success")], CD_BUDGET_USD="lots").returncode == 1


def test_a_non_dispatch_trigger_may_only_run_the_read_only_preflight(gate):
    assert gate([], CD_EVENT="push", CD_OPERATION="preflight").returncode == 0
    assert gate([], CD_EVENT="push", CD_OPERATION="deploy").returncode == 1
