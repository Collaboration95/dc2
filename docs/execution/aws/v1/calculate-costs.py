"""Recalculate the conditional V1 forecast offline; never call AWS."""

import json
from pathlib import Path


def calculate(data, *, hours=None, acu=None, clusters=None):
    assumptions = data["assumptions"]
    rates = data["rates_usd"]
    hours = assumptions["db_awake_hours"] if hours is None else hours
    acu = assumptions["db_average_acu"] if acu is None else acu
    clusters = assumptions["db_clusters"] if clusters is None else clusters
    months = data["duration_days"] / data["storage_month_days"]
    rows = dict(data["retained_rows_usd"])
    rows.update(
        {
            "HTTP API requests": assumptions["api_requests"] * rates["http_api_request"],
            "API Lambda duration": assumptions["api_invocations"]
            * assumptions["api_memory_gib"]
            * assumptions["api_average_seconds"]
            * rates["lambda_gb_second"],
            "Control/repair Lambda duration": assumptions["control_invocations"]
            * assumptions["control_memory_gib"]
            * assumptions["control_average_seconds"]
            * rates["lambda_gb_second"],
            "Authorizer Lambda duration": assumptions["authorizer_invocations"]
            * assumptions["authorizer_memory_gib"]
            * assumptions["authorizer_average_seconds"]
            * rates["lambda_gb_second"],
            "Lambda requests": (
                assumptions["api_invocations"]
                + assumptions["control_invocations"]
                + assumptions["authorizer_invocations"]
            )
            * rates["lambda_request"],
            "SQS request units": assumptions["sqs_request_units"] * rates["sqs_request"],
            "Aurora compute": hours * acu * clusters * rates["acu_hour"],
            "Aurora storage allowance": assumptions["db_storage_gb_each"]
            * clusters
            * months
            * rates["aurora_gb_month"],
            "Aurora storage I/O": assumptions["db_storage_io"] * rates["aurora_io"],
            "Managed master secrets": assumptions["master_secrets_each"]
            * clusters
            * months
            * rates["secret_month"],
            "Secret reads": assumptions["secret_reads"] * rates["secret_request"],
        }
    )
    subtotal = sum(rows.values())
    reserve = assumptions["tax_fx_reserve"] + assumptions["contingency"]
    return {
        "db_awake_hours_each": hours,
        "average_acu_while_awake": acu,
        "clusters": clusters,
        "rows_usd": {key: round(value, 6) for key, value in rows.items()},
        "usage_usd": round(subtotal, 2),
        "reserves_usd": reserve,
        "with_reserves_usd": round(subtotal + reserve, 2),
    }


def build(data):
    scenarios = {
        "v1_low": calculate(data),
        "v1_one_acu": calculate(data, acu=1),
        "v2_two_clusters_comparison": calculate(data, clusters=2),
        "never_pauses_sensitivity": calculate(data, hours=336),
    }
    budget = data["observed_account_facts"]["budget_alert_usd_per_month"]
    for scenario in scenarios.values():
        # A forecast over the account's alert threshold is a decision point, not a failure.
        scenario["exceeds_monthly_budget_alert"] = scenario["with_reserves_usd"] > budget
    assumptions = data["assumptions"]
    rates = data["rates_usd"]
    return {
        "document_kind": data["document_kind"],
        "status": data["status"],
        "region": data["region"],
        "currency_assumption": data["currency_assumption"],
        "planning_envelope": data["planning_envelope"],
        "observed_account_facts": data["observed_account_facts"],
        "notes": data["notes"],
        "marginal_rates_usd": {
            # What one more hour of an open session costs, excluding retained storage.
            "db_awake_hour_at_average_acu": round(
                assumptions["db_average_acu"] * rates["acu_hour"], 6
            ),
            "encoder_task_hour_incl_ipv4": rates["fargate_worker_hour"],
            "three_encoders_hour_incl_ipv4": round(3 * rates["fargate_worker_hour"], 5),
        },
        "scenarios": scenarios,
    }


def main():
    directory = Path(__file__).parent
    data = json.loads((directory / "cost-inputs.json").read_text())
    print(json.dumps(build(data), indent=2))


if __name__ == "__main__":
    main()
