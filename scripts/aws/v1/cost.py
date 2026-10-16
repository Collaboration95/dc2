"""Offline V1 measured-usage estimate; no bill, price lookup or spending cap.

Use captured local rates and measured quantities including all DB wake tails,
SQS polls/retries, Lambda authorizer/repair, pulls, migrations and generator.
Missing task timestamps remain pending. Never substitute booked DB hours for
actual ACU-hours. Forecasts remain in docs/execution/aws/v1/cost-model.json.
"""

import argparse
import json
import math
from pathlib import Path

from scripts.aws.cost import seconds

ROOT = Path(__file__).resolve().parents[3]

QUANTITIES = {
    "aurora_acu_hours": "acu_hour",
    "aurora_gb_months": "aurora_gb_month",
    "aurora_io": "aurora_io",
    "lambda_gb_seconds": "lambda_gb_second",
    "lambda_requests": "lambda_request",
    "http_api_requests": "http_api_request",
    "sqs_request_units": "sqs_request",
    "secret_months": "secret_month",
    "secret_reads": "secret_request",
}
RETAINED = {"s3", "ecr", "logs", "cloudfront", "transfer", "snapshots"}


def number(value):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("Finite nonnegative measured quantity required")
    return value


def reconcile(ledger):
    rates = json.loads((ROOT / "docs/execution/aws/v1/cost-inputs.json").read_text())["rates_usd"]
    task_rates = json.loads((ROOT / "docs/execution/aws/cost-worksheet.json").read_text())[
        "rates_usd"
    ]
    activity, retained = ledger["activity"], ledger["retained_usd"]
    if set(activity) != QUANTITIES.keys() or set(retained) != RETAINED:
        raise ValueError("Explicit measured activity and retained charge categories required")
    rows = {key: number(activity[key]) * rates[rate] for key, rate in QUANTITIES.items()}
    rows.update({"retained_" + key: number(value) for key, value in retained.items()})
    tasks, pending, seen = [], False, set()
    for task in ledger["tasks"]:
        identity = task["task_id"]
        if identity in seen or task["kind"] not in {"worker", "migration", "generator"}:
            raise ValueError("Unique bounded worker/migration/generator task required")
        seen.add(identity)
        if not task.get("pull_started_at") or not task.get("stopped_at"):
            tasks.append({"task_id": identity, "status": "PENDING"})
            pending = True
            continue
        duration = max(60, math.ceil(seconds(task["pull_started_at"], task["stopped_at"])))
        ip_duration = seconds(task["ip_started_at"], task["ip_released_at"])
        vcpu, memory = number(task["vcpu"]), number(task["memory_gib"])
        amount = (
            duration
            / 3600
            * (vcpu * task_rates["fargate_vcpu_hour"] + memory * task_rates["fargate_gb_hour"])
        )
        amount += ip_duration / 3600 * task_rates["ipv4_hour"]
        tasks.append(
            {
                "task_id": identity,
                "kind": task["kind"],
                "status": "ESTIMATED",
                "billed_seconds": duration,
                "usd": amount,
            }
        )
    total = sum(rows.values()) + sum(t.get("usd", 0) for t in tasks)
    bill = ledger.get("selected_bill_usd")
    if bill is not None:
        number(bill)
    return {
        "scope": "V1 captured-rate estimate; AWS billing/pause NOT_PROVEN",
        "currency_assumption": "USD",
        "rate_status": "CAPTURED_2026_10_15_NOT_REVALIDATED",
        "activity_rows_usd": rows,
        "tasks": tasks,
        "estimated_usd": total,
        "usage_status": "PENDING" if pending else "COMPLETE_INPUTS",
        "billing_status": "PENDING" if bill is None else "SELECTED_RECEIPT",
        "selected_bill_delta_usd": None if pending or bill is None else bill - total,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(json.loads(args.ledger.read_text())), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
