"""Captured-price task/request/IP accounting, never a billing API or zero-bill claim."""

import argparse
import importlib.util
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from scripts.aws.evidence import select

ROOT = Path(__file__).resolve().parents[2]
WORKSHEET = ROOT / "docs/execution/aws/cost-worksheet.json"


def forecasts(worksheet=None):
    data = worksheet or json.loads(WORKSHEET.read_text())
    spec = importlib.util.spec_from_file_location(
        "captured_cost_calculator", WORKSHEET.with_name("calculate-costs.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {name: module.calculate(data, scenario) for name, scenario in data["scenarios"].items()}


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Accounting requires timezone-aware timestamps")
    return result.astimezone(UTC)


def seconds(start, end):
    elapsed = (stamp(end) - stamp(start)).total_seconds()
    if elapsed < 0:
        raise ValueError("Accounting interval reversed")
    return elapsed


def task_charge(task, rates, profiles):
    if not task.get("pull_started_at") or not task.get("stopped_at"):
        return {"task_id": task["task_id"], "billing_status": "PENDING"}
    profile = profiles[task["kind"]]
    duration = max(60, math.ceil(seconds(task["pull_started_at"], task["stopped_at"])))
    ip_seconds = seconds(
        task.get("ip_started_at", task["pull_started_at"]),
        task.get("ip_released_at", task["stopped_at"]),
    )
    amount = (
        duration
        / 3600
        * (
            profile["vcpu"] * rates["fargate_vcpu_hour"]
            + profile["memory_gb"] * rates["fargate_gb_hour"]
        )
        + ip_seconds / 3600 * rates["ipv4_hour"]
    )
    return {
        "task_id": task["task_id"],
        "kind": task["kind"],
        "billed_seconds": duration,
        "task_hours": duration / 3600,
        "vcpu": profile["vcpu"],
        "memory_gb": profile["memory_gb"],
        "amount_usd": amount,
        "billing_status": "ESTIMATED",
    }


def reconcile(tasks, activity, *, bill_lines=None, worksheet=None):
    data = worksheet or json.loads(WORKSHEET.read_text())
    rates = data["rates_usd"]
    if len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task costs would double count")
    rows = [select(task_charge(t, rates, data["profiles"])) for t in tasks]
    required = {
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
        "s3_average_gb",
        "ecr_average_gb",
        "log_average_gb",
        "cloudmap_registration_hours",
        "cloudmap_api_calls",
    }
    if not required <= activity.keys():
        raise ValueError("Missing measured activity quantities")
    if any(
        not isinstance(activity[k], (int, float))
        or not math.isfinite(activity[k])
        or activity[k] < 0
        for k in required
    ):
        raise ValueError("Invalid measured activity quantity")
    months = data["duration_days"] / data["storage_month_days"]
    # Retained baseline appears once here; never added on top of worksheet forecasts.
    retained = (
        (data["ebs_root_gb"] + data["ebs_data_gb"]) * months * rates["gp3_gb_month"]
        + data["private_zone_month_charges"] * rates["private_hosted_zone_month"]
        + months
        * (
            activity["s3_average_gb"] * rates["s3_gb_month"]
            + activity["ecr_average_gb"] * rates["ecr_gb_month"]
            + activity["log_average_gb"] * rates["log_storage_gb_month"]
        )
    )
    quantities = {
        "state_hours": "t3a.small_hour",
        "state_ip_hours": "ipv4_hour",
        "s3_tier1_requests": "s3_tier1_request",
        "s3_tier2_requests": "s3_tier2_request",
        "s3_internet_gb": "internet_egress_gb",
        "cloudfront_viewer_gb": "cloudfront_viewer_gb",
        "cloudfront_origin_gb": "cloudfront_origin_gb",
        "cloudfront_https_requests": "cloudfront_https_request",
        "log_ingest_gb": "log_ingest_gb",
    }
    activity_cost = sum(activity[k] * rates[r] for k, r in quantities.items())
    activity_cost += activity["generator_hours"] * (rates["c6a.large_hour"] + rates["ipv4_hour"])
    activity_cost += activity["generator_volume_hours"] * 8 * rates["gp3_gb_month"] / 720
    # Registration-hours / API operations differ from free private DNS lookup queries.
    for key in ["cloudmap_registration_hours", "cloudmap_api_calls"]:
        if key not in activity or activity[key] < 0:
            raise ValueError("Missing Cloud Map accounting")
    activity_cost += (
        activity["cloudmap_registration_hours"] / 720 * rates["cloudmap_resource_month"]
        + activity["cloudmap_api_calls"] * rates["cloudmap_api_call"]
    )
    measured = sum(r.get("amount_usd", 0) for r in rows) + activity_cost + retained
    pending = any(r["billing_status"] == "PENDING" for r in rows)
    if bill_lines is not None and any(not math.isfinite(v) or v < 0 for v in bill_lines.values()):
        raise ValueError("Invalid selected bill lines")
    return {
        "tasks": rows,
        "retained_usd": retained,
        "estimated_usage_usd": measured,
        "task_accounting": "PENDING" if pending else "COMPLETE",
        "billing_status": "PENDING" if bill_lines is None else "DELAYED_RECEIPT",
        "bill_delta_usd": None
        if bill_lines is None or pending
        else sum(bill_lines.values()) - measured,
        "forecasts": forecasts(data),
        "rate_status": "CAPTURED_2026_10_15_NOT_REVALIDATED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    if args.ledger:
        ledger = json.loads(args.ledger.read_text())
        result = reconcile(ledger["tasks"], ledger["activity"], bill_lines=ledger.get("bill_lines"))
    else:
        result = forecasts()
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
