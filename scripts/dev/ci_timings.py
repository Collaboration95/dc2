"""Read CI receipts with authenticated gh, or compare saved JSON receipts offline.

No runs are started or modified. A fixture is {"run": <REST run>, "jobs": [<REST job>]}.
All metrics use seconds. Missing/unfinished timestamps stay null, never zero success.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

METRICS = (
    "queue_start_delay_seconds",
    "required_gate_seconds",
    "required_gate_execution_seconds",
    "workflow_elapsed_seconds",
    "sum_job_execution_seconds",
)


def timestamp(value: str | None) -> datetime | None:
    if not value or value.startswith("0001-"):
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value}")
    return result.astimezone(UTC)


def seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    if value < 0:
        raise ValueError("completion precedes start")
    return value


def gh_json(arguments: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *arguments], check=True, capture_output=True, text=True, timeout=60
    )
    return json.loads(result.stdout)


def fetch_receipt(repository: str, run_id: str) -> dict:
    """Fetch exactly one attempt, paginating its jobs (never mix rerun attempts)."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not run_id.isdecimal():
        raise ValueError("expected owner/repository and a numeric run ID")
    root = f"repos/{repository}/actions/runs/{run_id}"
    run = gh_json(["api", root])
    attempt = run["run_attempt"]
    pages = gh_json([
        "api", f"{root}/attempts/{attempt}/jobs?per_page=100", "--paginate", "--slurp"
    ])
    return {"run": run, "jobs": [job for page in pages for job in page["jobs"]]}


def summarize(receipt: dict, gates: list[str], tier: str) -> dict:
    run, jobs = receipt["run"], receipt["jobs"]
    created = timestamp(run["created_at"])
    # A rerun has the original created_at, but a new attempt start. Do not charge the
    # time between attempts to its queue; the original creation remains in the receipt.
    origin = created if run["run_attempt"] == 1 else timestamp(run.get("run_started_at"))
    rows = []
    for job in jobs:
        skipped = job.get("conclusion") == "skipped"
        start = timestamp(job.get("started_at"))
        end = timestamp(job.get("completed_at"))
        # GitHub can give skipped jobs synthetic timestamps, even end < start.
        duration = None
        if not skipped and job["status"] == "completed":
            duration = seconds(start, end)
        rows.append({
            "id": job.get("id"), "name": job["name"], "status": job["status"],
            "conclusion": job.get("conclusion"), "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"), "execution_seconds": duration,
        })
    starts = [timestamp(row["started_at"]) for row in rows
              if row["conclusion"] != "skipped" and row["status"] in {"completed", "in_progress"}
              and timestamp(row["started_at"]) is not None]
    first_start = min(starts, default=None)
    gate_rows = [row for row in rows if row["name"] in gates]
    missing = [name for name in gates if not any(row["name"] == name for row in rows)]
    duplicate = [name for name in gates if sum(row["name"] == name for row in rows) > 1]
    gate_ready = bool(gates) and not missing and not duplicate and all(
        row["status"] == "completed" and row["conclusion"] != "skipped"
        and row["execution_seconds"] is not None and row["conclusion"] is not None
        for row in gate_rows
    )
    gate_end = max((timestamp(row["completed_at"]) for row in gate_rows), default=None) \
        if gate_ready else None
    gate_state = "complete" if gate_ready else "incomplete"
    if missing or duplicate or any(row["conclusion"] == "skipped" for row in gate_rows):
        gate_state = "invalid"
    # Failures stay visible immediately, even if the aggregate is still pending.
    failed = [row["name"] for row in rows if row["conclusion"] in {
        "failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"
    }]
    complete = run["status"] == "completed"
    # REST has no dedicated workflow completed_at. updated_at is an explicit proxy only.
    workflow_end = timestamp(run.get("updated_at")) if complete else None
    durations = [row["execution_seconds"] for row in rows
                 if row["execution_seconds"] is not None]
    sum_complete = complete and bool(rows) and all(
        row["conclusion"] == "skipped" or row["execution_seconds"] is not None for row in rows
    )
    return {
        "run_id": run["id"], "url": run.get("html_url"), "source_sha": run["head_sha"],
        "event": run["event"], "head_branch": run.get("head_branch"),
        "base_branches": sorted({pr["base"]["ref"] for pr in run.get("pull_requests", [])
                                 if pr.get("base", {}).get("ref")}),
        "tier": tier, "tier_source": "operator-supplied; verify selection artifact",
        "attempt": run["run_attempt"], "status": run["status"],
        "conclusion": run.get("conclusion"), "created_at": run["created_at"],
        "run_started_at": run.get("run_started_at"), "updated_at": run.get("updated_at"),
        "first_job_started_at": first_start.isoformat() if first_start else None,
        "timing_origin": "created_at" if run["run_attempt"] == 1 else "run_started_at",
        "queue_start_delay_seconds": seconds(origin, first_start),
        "required_gates": gates, "required_gate_state": gate_state,
        "required_gate_conclusions": {row["name"]: row["conclusion"] for row in gate_rows},
        "required_gate_passed": gate_ready and all(
            row["conclusion"] == "success" for row in gate_rows
        ),
        "missing_gates": missing, "ambiguous_gates": duplicate,
        "required_gate_seconds": seconds(origin, gate_end),
        "required_gate_execution_seconds": seconds(first_start, gate_end),
        "workflow_elapsed_seconds": seconds(origin, workflow_end),
        "workflow_end_source": "REST updated_at completion proxy" if complete else None,
        "sum_job_execution_seconds": sum(durations),
        "sum_job_execution_complete": sum_complete,
        "sum_job_execution_note": "completed job wall time; not billed time; partial if unfinished",
        "selected_jobs": [row["name"] for row in rows if row["conclusion"] != "skipped"],
        "skipped_jobs": [row["name"] for row in rows if row["conclusion"] == "skipped"],
        "failed_jobs": failed, "jobs": rows,
    }


def compare(baseline: list[dict], samples: list[dict]) -> dict:
    """Compare successful complete receipts only; keep incomplete runs in the raw report."""
    def eligible(rows):
        return [row for row in rows if row["status"] == "completed"
                and row["conclusion"] == "success" and row["required_gate_passed"]
                and row["sum_job_execution_complete"]]

    before, after = eligible(baseline), eligible(samples)
    metrics = {}
    for key in METRICS:
        b = [row[key] for row in before if row[key] is not None]
        a = [row[key] for row in after if row[key] is not None]
        old = statistics.median(b) if b else None
        new = statistics.median(a) if a else None
        metrics[key] = {
            "baseline_median": old, "sample_median": new,
            "delta_seconds": new - old if new is not None and old is not None else None,
        }
    return {"baseline_count": len(before), "sample_count": len(after),
            "note": "small samples; match tier/change/cache conditions before claiming a speedup",
            "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="Collaboration95/dc2")
    parser.add_argument("--run", action="append", default=[], help="sample run ID (read only)")
    parser.add_argument("--baseline-run", action="append", default=[])
    parser.add_argument("--fixture", action="append", default=[], type=Path)
    parser.add_argument("--baseline-fixture", action="append", default=[], type=Path)
    parser.add_argument("--gate", action="append", required=True, help="exact sample job name")
    parser.add_argument("--baseline-gate", action="append", help="defaults to sample gate names")
    parser.add_argument("--tier", required=True, help="observed sample tier; not inferred")
    parser.add_argument("--baseline-tier", default="full-baseline")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--save-receipts", type=Path, help="save fetched REST JSON for offline reuse"
    )
    args = parser.parse_args(argv)
    if not any((args.run, args.baseline_run, args.fixture, args.baseline_fixture)):
        parser.error("provide at least one run or fixture")
    try:
        baseline = [fetch_receipt(args.repo, run) for run in args.baseline_run]
        samples = [fetch_receipt(args.repo, run) for run in args.run]
        if args.save_receipts:
            args.save_receipts.mkdir(parents=True, exist_ok=True)
            for receipt in baseline + samples:
                run = receipt["run"]
                path = args.save_receipts / f"{run['id']}-attempt-{run['run_attempt']}.json"
                path.write_text(json.dumps(receipt, indent=2) + "\n")
        baseline += [json.loads(path.read_text()) for path in args.baseline_fixture]
        samples += [json.loads(path.read_text()) for path in args.fixture]
        before = [summarize(r, args.baseline_gate or args.gate, args.baseline_tier)
                  for r in baseline]
        after = [summarize(r, args.gate, args.tier) for r in samples]
        report = {"baseline": before, "samples": after, "comparison": compare(before, after)}
        output = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output)
        else:
            print(output, end="")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"ci-timings: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
