"""Recalculate planning scenarios using captured public prices; no AWS access."""

import json
from pathlib import Path


def calculate(data, scenario):
    r = data["rates_usd"]
    months = data["duration_days"] / data["storage_month_days"]
    hours = scenario["core_hours"]

    def task_rate(profile):
        return (
            profile["vcpu"] * r["fargate_vcpu_hour"]
            + profile["memory_gb"] * r["fargate_gb_hour"]
            + r["ipv4_hour"]
        )

    rows = {
        "State/proxy EC2": hours * r["t3a.small_hour"],
        "State-host IPv4 while running": hours * r["ipv4_hour"],
    }
    for name in ("media", "processing_api", "processing_recovery"):
        rows[f"Fargate {name} incl. IPv4"] = hours * task_rate(data["profiles"][name])
    rows.update({
        "Workers incl. IPv4": scenario["worker_task_hours"] * task_rate(data["profiles"]["worker"]),
        "Migration/release overlap incl. IPv4": scenario["surge_task_hours"] * task_rate(data["profiles"]["media"]),
        "EBS retained during project": (data["ebs_root_gb"] + data["ebs_data_gb"]) * months * r["gp3_gb_month"],
        "S3 storage": scenario["s3_average_gb"] * months * r["s3_gb_month"],
        "S3 PUT/LIST/etc": scenario["s3_tier1_requests"] * r["s3_tier1_request"],
        "S3 GET/etc": scenario["s3_tier2_requests"] * r["s3_tier2_request"],
        "Direct S3 playback egress": scenario["s3_internet_gb"] * r["internet_egress_gb"],
        "CloudFront viewer delivery": scenario["cloudfront_viewer_gb"] * r["cloudfront_viewer_gb"],
        "CloudFront uploads to origin": scenario["cloudfront_origin_gb"] * r["cloudfront_origin_gb"],
        "CloudFront HTTPS requests": scenario["cloudfront_https_requests"] * r["cloudfront_https_request"],
        "ECR retained layers": scenario["ecr_average_gb"] * months * r["ecr_gb_month"],
        "CloudWatch logs": scenario["log_ingest_gb"] * r["log_ingest_gb"] + scenario["log_average_gb"] * months * r["log_storage_gb_month"],
        "Private discovery zone": data["private_zone_month_charges"] * r["private_hosted_zone_month"],
        "Cloud Map registrations/API": data["cloudmap_resources"] * hours / (30 * 24) * r["cloudmap_resource_month"] + data["cloudmap_api_calls"] * r["cloudmap_api_call"],
        "Separate short-lived generator incl. IPv4": scenario["generator_hours"] * (r["c6a.large_hour"] + r["ipv4_hour"] + 8 * r["gp3_gb_month"] / (30 * 24)),
    })
    subtotal = sum(rows.values())
    return {
        "lines_usd": {key: round(value, 6) for key, value in rows.items()},
        "usage_subtotal_usd": round(subtotal, 2),
        "tax_fx_reserve_usd": scenario["tax_fx_reserve_usd"],
        "contingency_usd": scenario["contingency_usd"],
        "total_with_reserves_usd": round(subtotal + scenario["tax_fx_reserve_usd"] + scenario["contingency_usd"], 2),
    }


if __name__ == "__main__":
    data = json.loads(Path(__file__).with_name("cost-worksheet.json").read_text())
    print(json.dumps({name: calculate(data, value) for name, value in data["scenarios"].items()}, indent=2))
