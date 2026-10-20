"""The V1 verification entry stays wired into CI and cannot quietly weaken."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


@pytest.fixture
def v1():
    return load("v1.yml")


@pytest.fixture
def steps(v1):
    return {
        s["name"]: s
        for lane in ("v1-offline", "v1-local")
        for s in v1["jobs"][lane]["steps"]
        if "name" in s
    }


def test_v1_workflow_defaults_to_every_flow_for_dispatch_and_call(v1):
    triggers = v1[True]  # YAML parses the bare key "on" as boolean True
    assert triggers["workflow_call"]["inputs"]["flow"]["default"] == "all"
    assert triggers["workflow_dispatch"]["inputs"]["flow"]["default"] == "all"
    assert v1["jobs"]["v1-local"]["env"]["FLOW"].endswith("|| 'all' }}")


def test_v1_job_requires_the_browser_leg_and_collects_coverage(v1):
    env = v1["jobs"]["v1-local"]["env"]
    assert env["V1_BROWSER"] == "1"
    assert env["V1_COVERAGE"] == "1"


def test_v1_job_requires_a_pinned_cfn_lint_that_stays_out_of_the_lockfile(steps):
    install = next(
        step["run"]
        for step in steps.values()
        if "uv sync --locked --extra dev" in step.get("run", "")
    )
    assert "uv pip install" in install and "cfn-lint==" in install
    assert "uv sync --locked" in install
    assert "--extra v1-media" in install and "--extra legacy" not in install
    lint = steps["Lint the V1 template (render, snapshot freshness, cfn-lint required)"]["run"]
    assert "make lint-cfn" in lint and "--require" in lint
    assert "cfn-lint" not in (ROOT / "uv.lock").read_text()
    makefile = (ROOT / "Makefile").read_text()
    assert "offline-fast" in makefile.split("\ntest-aws-v1:", 1)[1].split("\n\n", 1)[0]
    name = "Offline AWS control-plane suite for the no-legacy environment (network guarded)"
    assert steps[name]["run"] == "make test-aws-v1"


def test_v1_job_fails_unless_complete_acceptance_passed_for_the_all_flow(steps):
    step = steps["Require complete local acceptance when every flow was requested"]
    assert "complete_v1_acceptance" in step["run"] and step["if"]
    assert "continue-on-error" not in step


def test_v1_job_keeps_only_redacted_failure_detail_when_it_fails(steps):
    step = steps["Retain redacted failure detail (junit, screenshot, page state)"]
    assert step["if"] == "failure()" and step["uses"].startswith("actions/upload-artifact@")
    paths = step["with"]["path"].splitlines()
    # Raw junit, private logs, traces and the SQL volume can hold cookies or presigned URLs.
    assert any(p.endswith("junit-*.redacted.xml") for p in paths)
    assert all("private" not in p and "trace" not in p and not p.endswith("/*.xml") for p in paths)
    assert all("/failure-" in p or p.endswith(".redacted.xml") for p in paths)


def test_combined_coverage_gate_waits_for_and_consumes_the_v1_tier():
    ci = load("ci.yml")
    gate = ci["jobs"]["coverage-gate"]
    assert "v1-local" in gate["needs"]
    command = next(s["run"] for s in gate["steps"] if "coverage-report" in str(s.get("run")))
    assert ".coverage.v1-integration" in command
    assert ci["jobs"]["v1-local"]["uses"] == "./.github/workflows/v1.yml"
    assert "v1-local" in ci["jobs"]["integration"]["needs"]


def test_make_test_v1_uses_the_same_offline_guard_as_make_test():
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("\ntest-v1:", 1)[1].split("\n\n", 1)[0]
    assert "-p scripts.dev.pytest_plugin --offline-fast" in recipe
