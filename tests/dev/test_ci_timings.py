"""Timing metrics remain honest for concurrent, missing and incomplete jobs."""

import copy
import json
import subprocess

import pytest

from scripts.dev import ci_timings as timings


@pytest.fixture
def receipt():
    return {
        "run": {
            "id": 1, "head_sha": "a" * 40, "event": "pull_request", "run_attempt": 1,
            "status": "completed", "conclusion": "success",
            "created_at": "2026-10-17T00:00:00Z", "run_started_at": "2026-10-17T00:00:00Z",
            "updated_at": "2026-10-17T00:05:00Z",
            "pull_requests": [{"base": {"ref": "dev/v1-integration"}}],
        },
        "jobs": [
            {"id": 1, "name": "offline", "status": "completed", "conclusion": "success",
             "started_at": "2026-10-17T00:01:00Z", "completed_at": "2026-10-17T00:03:00Z"},
            {"id": 2, "name": "live", "status": "completed", "conclusion": "success",
             "started_at": "2026-10-17T00:01:00Z", "completed_at": "2026-10-17T00:04:00Z"},
            {"id": 3, "name": "gate", "status": "completed", "conclusion": "success",
             "started_at": "2026-10-17T00:04:01Z", "completed_at": "2026-10-17T00:04:03Z"},
            {"id": 4, "name": "images", "status": "completed", "conclusion": "skipped",
             "started_at": "2026-10-17T00:01:07Z", "completed_at": "2026-10-17T00:01:06Z"},
        ],
    }


def test_concurrency_queue_required_gate_and_workflow_are_different(receipt):
    result = timings.summarize(receipt, ["gate"], "dev")
    assert result["queue_start_delay_seconds"] == 60
    assert result["required_gate_seconds"] == 243
    assert result["required_gate_execution_seconds"] == 183
    assert result["workflow_elapsed_seconds"] == 300
    assert result["sum_job_execution_seconds"] == 302
    assert result["sum_job_execution_complete"]
    assert result["required_gate_passed"]
    assert result["skipped_jobs"] == ["images"]
    assert result["jobs"][-1]["execution_seconds"] is None
    assert result["base_branches"] == ["dev/v1-integration"]
    assert result["source_sha"] == "a" * 40
    assert "proxy" in result["workflow_end_source"]


@pytest.mark.parametrize("state", ["queued", "in_progress", "skipped", "missing", "duplicate"])
def test_pending_missing_ambiguous_or_skipped_gate_is_never_a_pass(receipt, state):
    gate = receipt["jobs"][2]
    if state == "missing":
        receipt["jobs"].pop(2)
    elif state == "duplicate":
        receipt["jobs"].append(copy.deepcopy(gate))
    elif state == "skipped":
        gate["conclusion"] = "skipped"
    else:
        gate.update(status=state, conclusion=None, completed_at=None)
        if state == "queued":
            gate["started_at"] = "0001-01-01T00:00:00Z"
        receipt["run"].update(status="in_progress", conclusion=None)
    result = timings.summarize(receipt, ["gate"], "dev")
    assert not result["required_gate_passed"]
    assert result["required_gate_seconds"] is None
    if state in {"queued", "in_progress"}:
        assert result["workflow_elapsed_seconds"] is None
        assert result["sum_job_execution_seconds"] == 300
        assert not result["sum_job_execution_complete"]


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "neutral"])
def test_failed_gate_has_latency_but_is_not_a_success(receipt, conclusion):
    receipt["jobs"][2]["conclusion"] = conclusion
    result = timings.summarize(receipt, ["gate"], "dev")
    assert result["required_gate_seconds"] == 243
    assert not result["required_gate_passed"]
    if conclusion != "neutral":
        assert "gate" in result["failed_jobs"]


def test_initially_queued_jobs_have_no_execution_duration(receipt):
    receipt["run"].update(status="queued", conclusion=None)
    receipt["jobs"] = [{"name": "gate", "status": "queued", "conclusion": None,
                        "started_at": "0001-01-01T00:00:00Z", "completed_at": None}]
    result = timings.summarize(receipt, ["gate"], "dev")
    assert result["queue_start_delay_seconds"] is None
    assert result["sum_job_execution_seconds"] == 0
    assert not result["sum_job_execution_complete"]


def test_empty_job_receipt_cannot_report_complete_execution(receipt):
    receipt["jobs"] = []
    result = timings.summarize(receipt, ["gate"], "dev")
    assert not result["sum_job_execution_complete"]
    assert not result["required_gate_passed"]


def test_rerun_queue_starts_at_attempt_not_original_creation(receipt):
    receipt["run"].update(run_attempt=2, created_at="2026-10-16T00:00:00Z")
    result = timings.summarize(receipt, ["gate"], "dev")
    assert result["queue_start_delay_seconds"] == 60
    assert result["workflow_elapsed_seconds"] == 300
    assert result["timing_origin"] == "run_started_at"


def test_multi_gate_waits_for_all_and_invalid_timestamps_fail(receipt):
    result = timings.summarize(receipt, ["offline", "live"], "full")
    assert result["required_gate_seconds"] == 240
    receipt["jobs"][0]["completed_at"] = "2026-10-16T00:00:00Z"
    with pytest.raises(ValueError, match="completion precedes start"):
        timings.summarize(receipt, ["offline"], "full")
    with pytest.raises(ValueError, match="no timezone"):
        timings.timestamp("2026-10-17T00:00:00")


def test_comparison_uses_completed_successes_and_labels_empty_after(receipt):
    before = timings.summarize(receipt, ["gate"], "full")
    receipt["jobs"][2]["completed_at"] = "2026-10-17T00:04:02Z"
    after = timings.summarize(receipt, ["gate"], "dev")
    comparison = timings.compare([before], [after])
    assert comparison["metrics"]["required_gate_seconds"]["delta_seconds"] == -1
    after["required_gate_passed"] = False
    assert timings.compare([before], [after])["sample_count"] == 0
    empty = timings.compare([before], [])["metrics"]["required_gate_seconds"]
    assert empty["delta_seconds"] is None


def test_reads_only_authenticated_gh_and_paginates_exact_attempt(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs == {"check": True, "capture_output": True, "text": True, "timeout": 60}
        response = {"run_attempt": 2} if len(calls) == 1 else [
            {"jobs": [{"name": "a"}]}, {"jobs": [{"name": "b"}]}
        ]
        return subprocess.CompletedProcess(command, 0, json.dumps(response))

    monkeypatch.setattr(subprocess, "run", run)
    result = timings.fetch_receipt("Collaboration95/dc2", "123")
    assert [job["name"] for job in result["jobs"]] == ["a", "b"]
    assert calls == [
        ["gh", "api", "repos/Collaboration95/dc2/actions/runs/123"],
        ["gh", "api", "repos/Collaboration95/dc2/actions/runs/123/attempts/2/jobs?per_page=100",
         "--paginate", "--slurp"],
    ]
    with pytest.raises(ValueError):
        timings.fetch_receipt("../other", "x")


def test_json_fixture_cli_is_offline_and_preserves_receipts(receipt, tmp_path, monkeypatch):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(receipt))
    output = tmp_path / "report.json"

    def forbidden(*args):
        pytest.fail("fixture mode must not invoke gh")

    monkeypatch.setattr(timings, "gh_json", forbidden)
    assert timings.main([
        "--fixture", str(fixture), "--baseline-fixture", str(fixture),
        "--gate", "gate", "--tier", "dev", "--output", str(output),
    ]) == 0
    report = json.loads(output.read_text())
    assert report["comparison"]["sample_count"] == 1
    assert report["comparison"]["metrics"]["required_gate_seconds"]["delta_seconds"] == 0
    fixture.write_text("{")
    with pytest.raises(SystemExit) as exc:
        timings.main(["--fixture", str(fixture), "--gate", "gate", "--tier", "dev"])
    assert exc.value.code == 1
