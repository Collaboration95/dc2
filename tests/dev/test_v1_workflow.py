"""The V1 verification entry stays wired into CI and cannot quietly weaken."""

import os
import re
from pathlib import Path

import pytest
import yaml

from scripts.dev import v1_verify

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


def test_new_marked_tests_run_automatically_and_separate_flows_remain_excluded(
    tmp_path, monkeypatch
):
    directory = tmp_path / "tests/v1"
    directory.mkdir(parents=True)
    # Use aliases, a marked class and parametrization: native pytest knows all these shapes.
    (directory / "test_new.py").write_text(
        "from pytest import mark\n\n"
        "@mark.integration\ndef test_new_case():\n    pass\n\n"
        "@mark.integration\nclass TestNew:\n"
        "    @mark.parametrize('value', [1, 2])\n"
        "    def test_parameters(self, value):\n        assert value > 0\n\n"
        "def test_unit_not_in_this_tier():\n    assert False\n"
    )
    for path in v1_verify.EXISTING_INTEGRATION_SUITES:
        (tmp_path / path).write_text(
            "import pytest\npytestmark = pytest.mark.integration\n"
            "def test_owned_by_another_flow():\n    assert False\n"
        )
    monkeypatch.setattr(v1_verify, "ROOT", tmp_path)
    monkeypatch.setattr(
        v1_verify,
        "local_environment",
        lambda *args, **kwargs: dict(os.environ, PYTHONPATH=str(ROOT)),
    )
    result = v1_verify.selected_tests(
        ["tests/v1"],
        tmp_path,
        {},
        require_integration=True,
        pytest_options=v1_verify.REQUIRED_INTEGRATION_ARGS,
    )
    assert result["status"] == "PASS", result
    assert result["counts"] == {"tests": 3, "errors": 0, "failures": 0, "skipped": 0}
    assert set(result["node_ids"]) == {
        "tests/v1/test_new.py::test_new_case",
        "tests/v1/test_new.py::TestNew::test_parameters[1]",
        "tests/v1/test_new.py::TestNew::test_parameters[2]",
    }


def test_the_short_encoder_cases_are_in_the_required_cohort_not_deferred():
    # #93 went live on the persistent environment: its 13 integration cases are no longer an
    # explicit exception, so the cohort must not ignore them and the registry must count them.
    ignored = [a for a in v1_verify.REQUIRED_INTEGRATION_ARGS if a.startswith("--ignore=")]
    assert f"--ignore={v1_verify.SHORT_ENCODER_INTEGRATION_SUITE}" not in ignored
    assert v1_verify.SHORT_ENCODER_INTEGRATION_SUITE not in v1_verify.EXISTING_INTEGRATION_SUITES
    assert not hasattr(v1_verify, "OPTIONAL_INTEGRATION_DISPOSITIONS")
    suite = ROOT / v1_verify.SHORT_ENCODER_INTEGRATION_SUITE
    cases = len(re.findall(r"^(?:async )?def test_", suite.read_text(), flags=re.MULTILINE))
    assert cases == v1_verify.SHORT_ENCODER_INTEGRATION_CASES
    result = {
        "node_ids": [f"{v1_verify.SHORT_ENCODER_INTEGRATION_SUITE}::test_{n}" for n in range(cases)]
    }
    counts = v1_verify.summarize_required_nodes(result)["short_encoder"]
    assert counts == {"selected": cases, "passed": cases, "skipped": 0, "failed": 0}


def test_explicit_local_test_environment_contains_owned_admin_dsns_endpoints_and_tls(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AWS_PROFILE", "ambient-profile")
    data = {
        "root": str(tmp_path),
        "run_id": "t3-local-test",
        "endpoint_url": "http://127.0.0.1:49123",
        "postgres_port": 49124,
        "resources": {
            "buckets": {"source": "owned-source", "output": "owned-output"},
            "queues": {
                "commands": "owned-commands",
                "work": "owned-work",
                "results": "owned-results",
            },
        },
    }

    env = v1_verify.local_environment(data)

    assert "AWS_PROFILE" not in env
    assert "/media_db?ssl=verify-full" in env["V1_TEST_MEDIA_DSN"]
    assert "/processing_db?ssl=verify-full" in env["V1_TEST_PROCESSING_DSN"]
    assert env["PGSSLROOTCERT"].endswith("/tls/server.crt")
    assert env["V1_TEST_S3_ENDPOINT"] == data["endpoint_url"]
    assert env["V1_TEST_SQS_ENDPOINT"] == data["endpoint_url"]
    assert env["MEDIA_POSTGRES_SSL_CA"].endswith("/tls/server.crt")
    assert env["PROCESSING_DATABASE_TLS"] == "true"
    assert env["PROCESSING_DATABASE_CA_FILE"].endswith("/tls/server.crt")
    assert env["MEDIA_MINIO_ENDPOINT"] == "127.0.0.1:49123"
    assert "local_v1_admin@127.0.0.1:49124" in env["V1_TEST_MEDIA_DSN"]
    assert env["MEDIA_STORAGE_CREDENTIAL_MODE"] == "lambda"
    assert (
        v1_verify.local_environment(data, storage_mode="static")["MEDIA_STORAGE_CREDENTIAL_MODE"]
        == "static"
    )


def test_local_test_environment_rejects_non_loopback_emulator(tmp_path):
    data = {
        "root": str(tmp_path),
        "run_id": "t3-local-test",
        "endpoint_url": "https://example.invalid",
        "postgres_port": 49124,
        "resources": {"buckets": {}, "queues": {}},
    }
    with pytest.raises(ValueError, match="owned loopback emulator"):
        v1_verify.local_environment(data)
