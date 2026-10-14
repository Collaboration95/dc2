"""Offline window resource/outcome report. Use: python -m scripts.experiments.windows_report SOURCE.

Docker lifetimes include startup, observed idle, inventory and drain overhead.
Only complete policy spans enter paired comparisons; raw interruptions remain.
"""

import json
from pathlib import Path

from scripts.evidence import performance as p
from scripts.experiments.analyze import interval_aggregate, lines


def summarize(source):
    source = Path(source)
    results = json.loads((source / "results.json").read_text())
    spans = lines(source / "policy-spans.jsonl")
    lifetimes = {
        (r["id"], r["started_at"], r["finished_at"])
        for d in lines(source / "drains.jsonl")
        for r in d["lifetimes"]
    }
    arms = []
    for span in spans:
        start, end = p.instant(span["started_utc"]), p.instant(span["finished_utc"])
        total = sum(
            max(0, min(end, p.instant(finish)) - max(start, p.instant(begin)))
            for _, begin, finish in lifetimes
        )
        rows = [
            r for r in results if r["repeat"] == span["repeat"] and r["policy"] == span["policy"]
        ]
        if len(rows) != 4:
            raise ValueError("Incomplete policy arm")
        arms.append(
            {
                **span,
                "actual_worker_seconds": total,
                "jobs": sum(r["metrics"]["jobs"] for r in rows),
                "all_queue_bounds_pass": all(r["metrics"]["queue_bound_pass"] for r in rows),
                "sustained_drain_pass": all(r["metrics"]["sustained_drain_pass"] for r in rows),
                "sustained_latency": next(
                    r["metrics"]["mixed_latency"] for r in rows if r["window"] == "sustained"
                ),
                "mixed_short_p90_wait_seconds": next(
                    r["metrics"]["short_wait_p90_seconds"] for r in rows if r["window"] == "mixed"
                ),
                "windows": rows,
            }
        )
    comparisons = []
    for repeat in [1, 2, 3]:
        manual = next((a for a in arms if a["repeat"] == repeat and a["policy"] == "manual"), None)
        fixed = next((a for a in arms if a["repeat"] == repeat and a["policy"] == "3"), None)
        if not manual or not fixed:
            continue
        comparisons.append(
            {
                "repeat": repeat,
                "manual_to_fixed3_worker_seconds": manual["actual_worker_seconds"]
                / fixed["actual_worker_seconds"],
                "resource_benefit_pass": manual["actual_worker_seconds"]
                <= 0.8 * fixed["actual_worker_seconds"],
                "short_wait_pass": manual["mixed_short_p90_wait_seconds"]
                <= fixed["mixed_short_p90_wait_seconds"] + 30,
            }
        )
    counts = {}
    for category in ["requests", "warmup-requests", "operations", "submissions"]:
        rows = lines(source / (category + ".jsonl"))
        counts[category] = {
            "records": len(rows),
            "errors": sum(r.get("error") is not None for r in rows),
        }
    memory = {}
    disk = []
    telemetry = lines(source / "telemetry.jsonl")
    resources = []
    for result in results:
        phase = f"r{result['repeat']}-{result['policy']}-{result['window']}"
        selected = [r for r in telemetry if r["phase"] == phase]
        if not selected:
            raise ValueError("Completed window has no telemetry")
        agg = interval_aggregate(selected, selected[0]["monotonic"], selected[-1]["monotonic"])
        agg["phase"] = phase
        agg["maximum_sampled_aggregate_worker_memory_current_bytes"] = max(
            sum(
                int(c["cgroup"]["memory.current"])
                for c in row["containers"]
                if c["container"]["service"] == "worker"
            )
            for row in selected
        )
        resources.append(agg)
    for row in telemetry:
        for c in row["containers"]:
            service = c["container"]["service"]
            memory[service] = max(memory.get(service, 0), int(c["cgroup"]["memory.current"]))
        for line in row["vm_pressure_disk_memory"].splitlines():
            fields = line.split()
            if len(fields) == 6 and fields[0].startswith("/dev/"):
                disk.append(int(fields[3]) * 1024)
    eligible = {f"r{r['repeat']}-{r['policy']}-{r['window']}" for r in results}
    outputs = [r for r in lines(source / "actual-objects.jsonl") if r["phase"] in eligible]
    result = {
        "source_directory": str(source),
        "arms": arms,
        "comparisons": comparisons,
        "http_record_counts": counts,
        "actual_output_bytes": sum(r["output_bytes"] for r in outputs),
        "actual_output_objects": sum(r["objects"] for r in outputs),
        "maximum_sampled_service_memory_current_bytes": memory,
        "minimum_sampled_free_disk_bytes": min(disk) if disk else None,
        "billing_scope": "Measured running-host worker residency; not cloud bill savings",
        "lifetime_count": len(lifetimes),
        "window_resource_aggregates": resources,
    }
    (source / "window-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return {
        "complete_arms": len(arms),
        "complete_windows": len(results),
        "comparisons": comparisons,
    }


if __name__ == "__main__":
    import sys

    print(summarize(sys.argv[1]))
