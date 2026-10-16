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
    return {s["name"]: s for s in v1["jobs"]["v1-local"]["steps"] if "name" in s}


def test_v1_workflow_defaults_to_every_flow_for_dispatch_and_call(v1):
    triggers = v1[True]  # YAML parses the bare key "on" as boolean True
    assert triggers["workflow_call"]["inputs"]["flow"]["default"] == "all"
    assert triggers["workflow_dispatch"]["inputs"]["flow"]["default"] == "all"
    assert v1["jobs"]["v1-local"]["env"]["FLOW"].endswith("|| 'all' }}")


def test_v1_job_requires_the_browser_leg_and_collects_coverage(v1):
    env = v1["jobs"]["v1-local"]["env"]
    assert env["V1_BROWSER"] == "1"
    assert env["V1_COVERAGE"] == "1"


def test_v1_job_lints_the_cloudformation_template_with_a_pinned_isolated_linter(steps):
    install = steps["Install V1 and isolated emulator tools (no legacy extra)"]["run"]
    assert "cfn-lint==" in install and ".cache/cfn-lint" in install
    assert "deploy/aws/v1/template.json" in steps["Lint the V1 template and control scripts"]["run"]


def test_v1_job_fails_unless_complete_acceptance_passed_for_the_all_flow(steps):
    step = steps["Require complete local acceptance when every flow was requested"]
    assert "complete_v1_acceptance" in step["run"] and step["if"]
    assert "continue-on-error" not in step


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
