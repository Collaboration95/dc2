import json

import pytest

from scripts.aws.cost import WORKSHEET, forecasts, reconcile, task_charge


def test_captured_forecasts_unchanged_and_retained_baseline_once():
    result = forecasts()
    assert result["expected"]["total_with_reserves_usd"] == 13.03
    assert result["conservative"]["total_with_reserves_usd"] == 28.27
    assert result["continuous_core_sensitivity"]["total_with_reserves_usd"] == 82.62
    data = json.loads(WORKSHEET.read_text())
    s = data["scenarios"]["expected"]
    activity = {
        k: 0
        for k in [
            "state_hours",
            "state_ip_hours",
            "s3_tier1_requests",
            "s3_tier2_requests",
            "s3_internet_gb",
            "cloudfront_viewer_gb",
            "cloudfront_origin_gb",
            "cloudfront_https_requests",
            "log_ingest_gb",
            "generator_hours",
            "generator_volume_hours",
            "cloudmap_registration_hours",
            "cloudmap_api_calls",
        ]
    }
    activity.update({k: s[k] for k in ["s3_average_gb", "ecr_average_gb", "log_average_gb"]})
    result = reconcile([], activity)
    assert result["retained_usd"] == pytest.approx(1.7275666667)
    assert result["estimated_usage_usd"] == result["retained_usd"]
    assert result["billing_status"] == "PENDING" and result["bill_delta_usd"] is None


def test_pull_start_minimum_overlap_ip_and_unknown_termination():
    data = json.loads(WORKSHEET.read_text())
    task = {
        "task_id": "task",
        "kind": "worker",
        "pull_started_at": "2026-10-15T00:00:00Z",
        "stopped_at": "2026-10-15T00:00:10Z",
        "ip_started_at": "2026-10-15T00:00:00Z",
        "ip_released_at": "2026-10-15T00:01:00Z",
    }
    r = task_charge(task, data["rates_usd"], data["profiles"])
    assert r["billed_seconds"] == 60 and r["amount_usd"] == pytest.approx(0.12824 / 60)
    del task["stopped_at"]
    assert task_charge(task, data["rates_usd"], data["profiles"])["billing_status"] == "PENDING"
    task["stopped_at"] = "2026-10-14T00:00:00Z"
    with pytest.raises(ValueError):
        task_charge(task, data["rates_usd"], data["profiles"])


def test_incomplete_activity_and_duplicate_task_rejected():
    with pytest.raises(ValueError, match="Missing measured"):
        reconcile([], {})
    with pytest.raises(ValueError, match="Duplicate"):
        reconcile([{"task_id": "same"}, {"task_id": "same"}], {})
