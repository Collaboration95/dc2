"""The V1 verification entry stays wired into CI and cannot quietly weaken."""

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


def test_v1_registry_selects_core_support_and_password_cases_without_short_lane():
    registry = v1_verify.validate_integration_registry(ROOT)
    assert len(registry["required_core_suites"]) == 9
    assert len(registry["required_support_suites"]) == 2
    assert v1_verify.AUDIT_CORE_CASES == 93
    assert v1_verify.EXPECTED_CORE_CASES == 95
    assert registry["required_regression_node"] == v1_verify.CREDENTIAL_ROTATION_REGRESSION
    assert len(v1_verify.REQUIRED_INTEGRATION_SELECTORS) == 13
    assert set(v1_verify.integration_test_nodes(ROOT)) == {
        *v1_verify.SUPPORT_INTEGRATION_SELECTORS,
        v1_verify.CREDENTIAL_ROTATION_REGRESSION,
    }
    assert "tests/v1/test_short_encoder_sql.py" in registry["optional_dispositions"]
    assert registry["optional_dispositions"]["tests/v1/test_short_encoder_sql.py"]["cases"] == 13
    assert "tests/v1/test_short_encoder_sql.py" not in v1_verify.REQUIRED_INTEGRATION_SELECTORS


def test_new_integration_file_cannot_escape_the_v1_registry(tmp_path):
    directory = tmp_path / "tests/v1"
    directory.mkdir(parents=True)
    (directory / "test_unregistered.py").write_text(
        "import pytest\n\n@pytest.mark.integration\ndef test_live():\n    pass\n"
    )
    with pytest.raises(ValueError, match="test_unregistered.py"):
        v1_verify.validate_integration_registry(tmp_path)


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
