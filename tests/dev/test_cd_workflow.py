"""Offline guards for the CD workflow: no stored AWS key, pinned actions, a real CI gate."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci.policy import classify

ROOT = Path(__file__).resolve().parents[2]
CD_SCRIPT = ROOT / "scripts/ci/cd.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())


def test_every_action_is_pinned_to_a_commit(workflow):
    uses = [
        step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
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
    assert '--environment "$CD_ENVIRONMENT"' in script and '--run-id "$CD_RUN_ID"' not in script
    assert "--unattended-launch" not in script  # the environment always deploys the launcher
    assert script.count("s3://$CD_STATE_BUCKET/envs/$CD_ENVIRONMENT/") == 2


def test_green_ci_on_main_updates_the_environment_in_place(workflow):
    trigger = workflow[True]["workflow_run"]
    assert trigger == {"workflows": ["CI"], "types": ["completed"], "branches": ["Main"]}
    condition = workflow["jobs"]["gate"]["if"]
    for clause in (
        "conclusion == 'success'",
        "event == 'push'",
        "head_repository.full_name == github.repository",
    ):
        assert clause in condition
    assert "workflow_run' && 'deploy'" in workflow["env"]["CD_OPERATION"]
    assert "workflow_run.head_sha" in workflow["env"]["CD_SHA"]
    checkouts = [
        s
        for job in workflow["jobs"].values()
        for s in job["steps"]
        if s.get("uses", "").startswith("actions/checkout")
    ]
    assert checkouts and all(s["with"]["ref"] == "${{ env.CD_SHA }}" for s in checkouts)


def test_releases_run_online_and_cd_never_closes_or_reopens_the_environment():
    script = CD_SCRIPT.read_text()
    # The kill switch is the operator's: CD neither engages it nor undoes it.
    assert "scripts.aws.v1.session" not in script
    calls = [line for line in script.splitlines() if "scripts.aws.v1.release " in line]
    assert len(calls) == 3  # promote, restore, abandon
    for call in (
        'local promote=(--config "$config" "${SCOPE[@]}" --online',
        'local restore=(--config "$config" "${SCOPE[@]}" --online',
        'release abandon --config "$config" "${SCOPE[@]}" --online',
    ):
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
    """Real gh CLI contracts, backed only by local fixtures; no GitHub/network calls."""
    (tmp_path / "gh").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "data = json.loads(pathlib.Path(os.environ['FAKE_RUNS']).read_text())\n"
        "if args[:2] == ['run', 'list']:\n"
        "    print(json.dumps(data)); sys.exit()\n"
        "run_id = int(args[2])\n"
        "r = next(r for r in data if r['databaseId'] == run_id)\n"
        "if args[:2] == ['run', 'view']:\n"
        "    print(json.dumps(r)); sys.exit()\n"
        "if args[:2] == ['run', 'download']:\n"
        "    if r.get('missing_artifact'): sys.exit(1)\n"
        "    directory = pathlib.Path(args[args.index('--dir') + 1])\n"
        "    (directory / 'ci-policy.json').write_text(json.dumps(r.get('selection')))\n"
    )
    (tmp_path / "gh").chmod(0o755)

    def run(runs, **overrides):
        reply = tmp_path / "runs.json"
        reply.write_text(json.dumps(runs))
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
            "CD_CI_RUN_ID": "1",
            "CD_CI_RUN_ATTEMPT": "1",
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


def ci_run(
    conclusion,
    *,
    status="completed",
    created="2026-10-18T00:00:00Z",
    run_id=1,
    attempt=1,
    event="push",
):
    plan = classify([], full=True, source_sha=SHA)
    plan.update(run_id=str(run_id), run_attempt=str(attempt), event=event, head_sha=SHA)
    return {
        "databaseId": run_id,
        "attempt": attempt,
        "headSha": SHA,
        "headBranch": "Main",
        "status": status,
        "conclusion": conclusion,
        "event": event,
        "workflowName": "CI",
        "url": f"https://github.com/x/y/actions/runs/{run_id}",
        "createdAt": created,
        "jobs": [{"name": "Full verification", "status": "completed", "conclusion": "success"}],
        "selection": plan,
    }


def test_gate_accepts_a_green_ci_run(gate):
    done = gate([ci_run("success")])
    assert done.returncode == 0, done.stdout + done.stderr


def test_gate_refuses_a_commit_that_never_ran_ci(gate):
    done = gate([])
    assert done.returncode == 1
    assert "No CI run exists" in done.stderr


def test_gate_refuses_a_failed_latest_run_even_after_an_older_green_one(gate):
    done = gate([ci_run("success"), ci_run("failure", run_id=2, created="2026-10-18T01:00:00Z")])
    assert done.returncode == 1
    assert "failure" in done.stderr


def test_gate_refuses_while_ci_is_still_running(gate):
    done = gate([ci_run(None, status="in_progress")])
    assert done.returncode == 1
    assert "still running" in done.stderr


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
    assert (
        gate(
            [ci_run("success")],
            CD_EVENT="workflow_run",
            CD_OPERATION="teardown",
            CD_EXECUTE="true",
            CD_CONFIRM="live",
        ).returncode
        == 1
    )


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
    assert (
        gate(
            [ci_run("success")], CD_BAD_CANDIDATE="true", **{**ok, "CD_EXECUTE": "false"}
        ).returncode
        == 1
    )
    assert (
        gate(
            [ci_run("success")], CD_BAD_CANDIDATE="true", CD_OPERATION="deploy", CD_EXECUTE="true"
        ).returncode
        == 1
    )
    assert (
        gate([ci_run("success")], CD_BAD_CANDIDATE="false", CD_OPERATION="deploy").returncode == 0
    )


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
    tmp_path, owner, handler, variable
):
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
    env = {
        **os.environ,
        "CD_ENVIRONMENT": "live",
        "CD_OPERATION": "release",
        "RUNNER_TEMP": str(tmp_path),
    }
    done = subprocess.run(
        ["bash", str(CD_SCRIPT), "inject-bad-candidate", owner],
        env=env,
        cwd=repo,
        capture_output=True,
        text=True,
    )
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


def script_function(name):
    """One function of cd.sh, as text, so its logic runs without the rest of the script."""
    found = re.search(rf"^{name}\(\) [{{(].*?^[}})]\n", CD_SCRIPT.read_text(), re.M | re.S)
    assert found, name
    return found.group(0)


def test_an_owner_with_changed_migrations_stays_deferred_after_the_other_owners_adoption(tmp_path):
    # Media releases first and its adoption re-runs the deploy, which rewrites the images step:
    # Processing's changed migrations must still hold it back (attestation, not green CI).
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    journal = tmp_path / "deploy-journal.json"

    def write(migrations):
        journal.write_text(
            json.dumps(
                {
                    "deploy": {
                        "steps": {
                            "images": {
                                "detail": {
                                    "changed_owners": ["media", "processing"],
                                    "changed_images": ["media", "processing", "worker"],
                                    "migrations_changed": migrations,
                                }
                            }
                        }
                    }
                }
            )
        )

    write(["processing"])
    stubs = f"""
set -euo pipefail
CD_STATE={tmp_path}
summary() {{ :; }}
fail() {{ echo "FAIL: $*"; exit 1; }}
release_owner() {{
  echo "RELEASED $1 ${{*:4}}"
  # The adoption deploy: a fresh images step that no longer reports the migrations.
  echo '{{"deploy": {{"steps": {{"images": {{"detail": {{"migrations_changed": []}}}}}}}}}}' \\
    >"$CD_STATE/deploy-journal.json"
}}
{script_function("journal_value")}
{script_function("release_changed_owners")}
release_changed_owners images.json "media processing"
"""
    done = subprocess.run(["bash", "-c", stubs], capture_output=True, text=True)
    assert done.returncode == 1, done.stdout + done.stderr
    assert done.stdout.splitlines() == [
        "RELEASED media media",
        "FAIL: processing changed migrations; release it by hand with attest_additive=true",
    ]


@pytest.mark.parametrize(
    "change",
    [
        "pr-head",
        "source",
        "dev",
        "deselected",
        "run",
        "attempt",
        "event",
        "head",
        "missing",
        "skipped",
        "failed",
        "duplicate",
        "expired",
        "cancelled",
    ],
)
def test_full_source_admission_refuses_incomplete_or_mixed_evidence(gate, change):
    run = ci_run("success")
    selection = run["selection"]
    if change == "pr-head":
        run["event"] = selection["event"] = "pull_request"
        selection["source_sha"] = "a" * 40
    elif change == "source":
        selection["source_sha"] = "b" * 40
    elif change == "dev":
        selection["mode"] = "dev"
    elif change == "deselected":
        selection["selected"]["images"] = False
    elif change == "run":
        selection["run_id"] = "2"
    elif change == "attempt":
        selection["run_attempt"] = "2"
    elif change == "event":
        selection["event"] = "pull_request"
    elif change == "head":
        selection["head_sha"] = "c" * 40
    elif change == "missing":
        run["jobs"] = []
    elif change in {"skipped", "failed"}:
        run["jobs"][0]["conclusion"] = change
    elif change == "duplicate":
        run["jobs"] *= 2
    elif change == "expired":
        run["missing_artifact"] = True
    elif change == "cancelled":
        run["conclusion"] = "cancelled"
    done = gate([run])
    assert done.returncode != 0, done.stdout + done.stderr


def test_full_exact_dispatch_is_accepted_and_records_run_attempt(gate, tmp_path):
    done = gate([ci_run("success", event="workflow_dispatch", attempt=2)])
    assert done.returncode == 0, done.stdout + done.stderr
    receipt = json.loads((tmp_path / "cd-out/public/ci-admission.json").read_text())
    assert (receipt["source_sha"], receipt["run_id"], receipt["run_attempt"], receipt["tier"]) == (
        SHA,
        1,
        2,
        "full",
    )


def test_automatic_cd_uses_only_the_triggering_run_and_attempt(gate):
    old = ci_run("failure")
    later = ci_run("success", run_id=2, created="2026-10-18T01:00:00Z")
    assert gate([old, later], CD_EVENT="workflow_run").returncode != 0
    old["conclusion"] = "success"
    later["conclusion"] = "failure"
    assert gate([old, later], CD_EVENT="workflow_run").returncode == 0
    assert gate([old], CD_EVENT="workflow_run", CD_CI_RUN_ATTEMPT="2").returncode != 0
    assert gate([old], CD_EVENT="workflow_run", CD_CI_RUN_ID="").returncode != 0


def test_emergency_teardown_does_not_depend_on_ci_availability(gate):
    done = gate([], CD_OPERATION="teardown", CD_EXECUTE="true", CD_CONFIRM="live")
    assert done.returncode == 0, done.stdout + done.stderr


def install_fake_trivy(binary):
    """A `trivy` whose report is chosen by $SCAN_FAULT; it records its argv in $SCAN_ARGS."""
    (binary / "trivy").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "fault = os.environ['SCAN_FAULT']\n"
        "pathlib.Path(os.environ['SCAN_ARGS']).write_text(json.dumps(sys.argv[1:]))\n"
        "if fault == 'error': sys.exit(2)\n"
        "if fault == 'no-output': sys.exit(0)\n"
        "config = sys.argv[-1]\n"
        "# A registry reference is repo@digest; its report names the image's config ID.\n"
        "if '@' in config: config = os.environ['SCAN_CONFIG']\n"
        "if fault == 'wrong-config': config = 'sha256:' + '2' * 64\n"
        "results = [{'Class': 'os-pkgs', 'Type': 'debian'}, "
        "{'Class': 'lang-pkgs', 'Type': 'python-pkg'}]\n"
        "if fault in ['os', 'python']:\n"
        "    results[fault == 'python']['Vulnerabilities'] = "
        "[{'Severity': 'HIGH', 'FixedVersion': '2', 'VulnerabilityID': 'CVE-X', "
        "'PkgName': 'libx'}]\n"
        "if fault == 'incomplete': results.pop()\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text("
        "json.dumps({'Metadata': {'ImageID': config}, 'Results': results}))\n"
    )
    (binary / "trivy").chmod(0o755)


@pytest.mark.parametrize(
    "fault", ["clean", "os", "python", "incomplete", "wrong-config", "error", "no-output"]
)
def test_cd_scans_the_selected_exact_candidate_before_publication(tmp_path, fault):
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    config_id = "sha256:" + "1" * 64
    build = tmp_path / "build.json"
    build.write_text(
        json.dumps(
            {
                "status": "LOCAL_ARTIFACT_PASS",
                "images": {
                    "media": {
                        "config_id": config_id,
                        "source_sha": sha,
                        "tag": "mutable-media-tag",
                        "trivy_scan": {"status": "PASS"},
                    }
                },
            }
        )
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    install_fake_trivy(binary)
    output = tmp_path / "public"
    output.mkdir()
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "SCAN_FAULT": fault,
        "SCAN_ARGS": str(tmp_path / "argv.json"),
    }
    shell = f"""
set -euo pipefail
CD_STATE='{tmp_path}'
PUBLIC='{output}'
PY='{sys.executable}'
fail() {{ echo "FAIL: $*"; exit 1; }}
{script_function("scan_images")}
scan_images '{build}' local media
# This stands for the next publication step; failure must prevent reaching it.
touch '{tmp_path / "published"}'
"""
    done = subprocess.run(["bash", "-c", shell], env=env, cwd=ROOT, capture_output=True, text=True)
    assert (done.returncode == 0) is (fault == "clean"), done.stdout + done.stderr
    assert (tmp_path / "published").exists() is (fault == "clean")
    argv = json.loads((tmp_path / "argv.json").read_text())
    assert argv[-1] == config_id and "mutable-media-tag" not in argv
    assert argv[argv.index("--image-src") + 1] == "docker"
    scan = json.loads(build.read_text())["images"]["media"]["trivy_scan"]
    if fault != "clean":
        assert scan["status"] != "PASS"
    if fault == "clean":
        assert scan["status"] == "PASS" and scan["source_sha"] == sha
        assert len(scan["targets"]) == 2 and scan["report_sha256"].startswith("sha256:")


def test_cd_installs_the_existing_scanner_only_for_image_delivery(workflow):
    setup = next(
        step
        for step in workflow["jobs"]["run"]["steps"]
        if step.get("uses", "").startswith("aquasecurity/setup-trivy@")
    )
    assert "CD_EXECUTE == 'true'" in setup["if"]
    assert setup["with"]["version"] == "v0.70.0"


RELEASED_SHA = "e" * 40  # the retained image's own source, not the checkout being released
REGISTRY_REF = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/media@sha256:" + "a" * 64


@pytest.mark.parametrize("mode", ["registry", "retained"])
@pytest.mark.parametrize(
    "fault", ["clean", "os", "python", "incomplete", "wrong-config", "error", "no-output"]
)
def test_only_a_replaced_rollback_target_may_record_fixable_findings_on_rescan(
    tmp_path, mode, fault
):
    # The incident: an advisory published after the running image shipped made its rescan fail,
    # which blocked the release that fixes it. A replaced rollback target now records the finding;
    # a kept image is still gated, and a scanner problem or a bad report fails in both modes.
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    config_id = "sha256:" + "1" * 64
    state = tmp_path / "state"
    state.mkdir()
    (state / "deploy-journal.json").write_text(
        json.dumps({"deploy": {"images": {"media": {"uri": REGISTRY_REF}}}})
    )
    build = tmp_path / "build-baseline.json"
    build.write_text(
        json.dumps(
            {
                "status": "LOCAL_ARTIFACT_PASS",
                "images": {
                    "media": {
                        "config_id": config_id,
                        "source_sha": RELEASED_SHA,
                        "trivy_scan": {"status": "PASS"},
                    }
                },
            }
        )
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    install_fake_trivy(binary)
    for tool, body in (("aws", "echo token"), ("docker", "cat >/dev/null")):
        (binary / tool).write_text(f"#!/bin/sh\n{body}\n")
        (binary / tool).chmod(0o755)
    public = tmp_path / "public"
    public.mkdir()
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "SCAN_FAULT": fault,
        "SCAN_CONFIG": config_id,
        "SCAN_ARGS": str(tmp_path / "argv.json"),
    }
    shell = f"""
set -euo pipefail
CD_STATE='{state}'
PUBLIC='{public}'
PY='{sys.executable}'
CD_ACCOUNT=123456789012 CD_REGION=ap-southeast-1 CD_PROFILE=none
fail() {{ echo "FAIL: $*"; exit 1; }}
{script_function("journal_value")}
{script_function("scan_images")}
scan_images '{build}' {mode} media
"""
    done = subprocess.run(["bash", "-c", shell], env=env, cwd=ROOT, capture_output=True, text=True)
    recorded = mode == "retained" and fault in ("os", "python")
    assert (done.returncode == 0) is (fault == "clean" or recorded), done.stdout + done.stderr
    argv = json.loads((tmp_path / "argv.json").read_text())
    assert argv[argv.index("--image-src") + 1] == "remote" and argv[-1] == REGISTRY_REF
    scan = json.loads(build.read_text())["images"]["media"]["trivy_scan"]
    if fault == "clean" or recorded:
        # Keeps its own source SHA, never the commit being released; the summary is published.
        assert scan["source_sha"] == RELEASED_SHA and scan["config_id"] == config_id
        assert (public / f"scan-build-baseline-{mode}.json").is_file()
    else:
        assert scan["status"] not in ("PASS", "RETAINED_FIXABLE")
        assert not list(public.iterdir())
    if recorded:
        assert scan["status"] == "RETAINED_FIXABLE" and scan["fixable_high_critical"] == 1
        assert scan["fixable_ids"] == ["CVE-X libx"]
    elif fault == "clean":
        assert scan["status"] == "PASS" and scan["fixable_high_critical"] == 0


def baseline_scan_run(tmp_path, rebuilt, names, *, retained, stale=False):
    """scan_baseline with scan_images stubbed: the calls it makes and what it announces."""
    public = tmp_path / "public"
    public.mkdir(exist_ok=True)
    summary = {
        "images": [
            {
                "owner": names[0],
                "source_sha": "629119c5b3bd390ce072df0a43fe926cd7a161c7",
                "verdict": "RETAINED: 1 fixable HIGH/CRITICAL" if retained else "PASS",
                "fixable_high_critical": ["GHSA-6q48-6c7w-9gw2 certifi"] if retained else [],
            }
        ]
    }
    if stale:  # another owner's release in this run left it
        (public / "scan-build-baseline-retained.json").write_text(
            json.dumps({**summary, "images": [{**summary["images"][0], "verdict": "RETAINED: 1"}]})
        )
    shell = f"""
set -euo pipefail
PUBLIC='{public}'
summary() {{ echo "SUMMARY $*"; }}
scan_images() {{
  echo "SCAN $2 ${{*:3}}"
  if [ "$2" = retained ]; then
    echo '{json.dumps(summary)}' >"$PUBLIC/scan-$(basename "$1" .json)-$2.json"
  fi
}}
{script_function("retained_findings")}
{script_function("scan_baseline")}
scan_baseline /state/build-baseline.json '{rebuilt}' {" ".join(names)}
"""
    done = subprocess.run(["bash", "-c", shell], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.splitlines()


@pytest.mark.parametrize(
    ("rebuilt", "names", "scans"),
    [
        ("media", ["media"], ["SCAN retained media"]),
        ("worker", ["processing", "worker"], ["SCAN registry processing", "SCAN retained worker"]),
        ("processing worker", ["processing", "worker"], ["SCAN retained processing worker"]),
    ],
)
def test_a_release_gates_what_it_keeps_and_only_records_what_it_replaces(
    tmp_path, rebuilt, names, scans
):
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    lines = baseline_scan_run(tmp_path, rebuilt, names, retained=True)
    assert lines[: len(scans)] == scans
    # Loud: a workflow warning naming the image, its source and the finding, and a run summary.
    warning = next(line for line in lines if line.startswith("::warning"))
    assert (
        "GHSA-6q48-6c7w-9gw2 certifi" in warning and f"{names[0]} (source 629119c5b3bd)" in warning
    )
    assert any(line.startswith("SUMMARY **Rollback target not clean**") for line in lines)


def test_a_clean_rollback_target_announces_nothing_and_a_stale_summary_is_not_reused(tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq is not installed")
    assert baseline_scan_run(tmp_path, "media", ["media"], retained=False) == [
        "SCAN retained media"
    ]
    # Nothing replaced here (only a kept image is scanned): the earlier owner's file is ignored.
    assert baseline_scan_run(tmp_path, "worker", ["processing"], retained=True, stale=True) == [
        "SCAN registry processing"
    ]


def test_the_candidate_is_gated_before_the_rollback_target_and_the_receipt_records_findings():
    release = script_function("release_owner")
    assert release.index('scan_images "$build" local') < release.index("scan_baseline")
    assert 'scan_baseline "$baseline" "${rebuilt[*]}" "${names[@]}"' in release
    assert "rollback_target_findings" in release
