"""V1 forecast integrity, job-input template hygiene and the offline cfn-lint entry."""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.aws.config import validate_nonsecret
from scripts.aws.v1 import lint
from scripts.aws.v1.cost import QUANTITIES

DOCS = Path(__file__).resolve().parents[3] / "docs/execution/aws/v1"


def calculator():
    spec = importlib.util.spec_from_file_location("calculate_costs", DOCS / "calculate-costs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_forecast_is_exactly_what_the_inputs_calculate():
    inputs = json.loads((DOCS / "cost-inputs.json").read_text())
    assert calculator().build(inputs) == json.loads((DOCS / "cost-model.json").read_text())


def test_forecast_is_labelled_as_a_forecast_and_flags_scenarios_over_the_account_budget():
    model = json.loads((DOCS / "cost-model.json").read_text())
    assert model["document_kind"] == "FORECAST_NOT_BILL"
    assert model["observed_account_facts"]["budget_alert_usd_per_month"] == 30
    flags = {k: v["exceeds_monthly_budget_alert"] for k, v in model["scenarios"].items()}
    assert flags["never_pauses_sensitivity"] is True and flags["v1_low"] is False


def test_priced_topology_has_no_legacy_core_or_cache_rows_and_no_concurrency_line():
    model = json.loads((DOCS / "cost-model.json").read_text())
    rows = " ".join(model["scenarios"]["v1_low"]["rows_usd"]).lower()
    for legacy in ("ec2", "redis", "elasticache", "nat", "alb", "core", "state host"):
        assert legacy not in rows.split() and legacy + " " not in rows
    assert "concurrency" not in rows
    for needed in ("aurora compute", "sqs", "api lambda", "http api", "workers", "cloudfront"):
        assert needed in rows


def test_reconciler_quantities_cover_every_forecast_priced_service_family():
    # The bill reconciler must be able to price what the forecast promises.
    assert {"aurora_acu_hours", "lambda_gb_seconds", "sqs_request_units"} <= QUANTITIES.keys()


def test_job_input_template_is_nonsecret_unfilled_and_v1_shaped():
    template = json.loads((DOCS / "job-inputs.template.json").read_text())
    validate_nonsecret(template)
    assert template["topology"].startswith("v1-")
    assert template["scope"]["account_id"] is None and template["scope"]["profile_name"] is None
    assert template["session"]["lambda_reserved_concurrency"] == "none"
    assert template["session"]["max_encoder_tasks"] == 3
    assert template["close_handoff"]["database_pause"] == "NOT_OBSERVED"
    assert set(template["evidence"]["issues"].values()) == {"NOT_RUN"}
    assert template["spend"]["forecast_is_a_bill"] is False
    text = json.dumps(template).lower()
    assert "866865534361" not in text and "redis" not in text and "ec2" not in text


def test_lint_skips_cleanly_without_the_tool_and_fails_when_required():
    out = io.StringIO()
    assert lint.run(which=lambda name: None, stdout=out) == 0
    assert "SKIPPED" in out.getvalue()
    assert lint.run(require=True, which=lambda name: None, stdout=io.StringIO()) == 2


def test_lint_runs_the_tool_against_the_rendered_template_in_the_v1_region():
    seen = {}

    def runner(command, **kwargs):
        seen["command"] = command
        assert json.loads(Path(command[1]).read_text())["Resources"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert lint.run(which=lambda name: "/bin/cfn-lint", runner=runner, stdout=io.StringIO()) == 0
    assert seen["command"][2:] == ["--regions", "ap-southeast-1"]


def test_lint_failure_and_stale_snapshot_are_reported(monkeypatch, tmp_path):
    failing = lambda *a, **k: SimpleNamespace(returncode=2, stdout="E3001", stderr="")  # noqa: E731
    out = io.StringIO()
    assert lint.run(which=lambda n: "/bin/x", runner=failing, stdout=out) == 1
    assert "E3001" in out.getvalue()
    stale = tmp_path / "template.json"
    stale.write_text("{}")
    monkeypatch.setattr(lint, "SNAPSHOT", stale)
    out = io.StringIO()
    assert lint.run(which=lambda n: None, stdout=out) == 1 and "stale" in out.getvalue()


@pytest.mark.skipif(lint.find_linter() is None, reason="cfn-lint is not installed")
def test_rendered_template_passes_the_real_cfn_lint():
    command = [sys.executable, "-m", "scripts.aws.v1.lint", "--require"]
    assert subprocess.run(command, check=False).returncode == 0
