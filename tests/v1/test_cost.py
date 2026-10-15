import pytest

from scripts.aws.v1.cost import QUANTITIES, RETAINED, reconcile


def ledger():
    return {
        "activity": dict.fromkeys(QUANTITIES, 0),
        "retained_usd": dict.fromkeys(RETAINED, 0),
        "tasks": [],
    }


def test_real_db_awake_quantities_and_sqs_polls_are_charged():
    data = ledger()
    data["activity"].update(
        aurora_acu_hours=168,
        sqs_request_units=1000000,
        lambda_gb_seconds=1000,
        lambda_requests=1000,
    )
    data["retained_usd"]["s3"] = 1
    result = reconcile(data)
    assert result["activity_rows_usd"]["aurora_acu_hours"] == 33.6
    assert result["activity_rows_usd"]["sqs_request_units"] == pytest.approx(0.4)
    assert result["billing_status"] == "PENDING"
    assert result["selected_bill_delta_usd"] is None


def test_task_pull_minimum_ip_lifetime_and_pending_receipts():
    data = ledger()
    task = {
        "task_id": "one",
        "kind": "generator",
        "vcpu": 2,
        "memory_gib": 4,
        "pull_started_at": "2026-10-15T00:00:00Z",
        "stopped_at": "2026-10-15T00:00:10Z",
        "ip_started_at": "2026-10-15T00:00:00Z",
        "ip_released_at": "2026-10-15T00:01:30Z",
    }
    data["tasks"] = [task, {"task_id": "pending", "kind": "migration"}]
    result = reconcile(data)
    assert result["tasks"][0]["billed_seconds"] == 60
    assert result["usage_status"] == "PENDING"
    assert result["tasks"][0]["usd"] > 0
    data["tasks"].append(task)
    with pytest.raises(ValueError, match="Unique"):
        reconcile(data)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_quantities_rejected(value):
    data = ledger()
    data["activity"]["aurora_acu_hours"] = value
    with pytest.raises(ValueError):
        reconcile(data)
