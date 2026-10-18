"""Redacted, committable summary of the private receipts, and the close-proof counts file.

The summary is built only from each step's `public` view (already screened when it was stored,
screened again here) plus step statuses and durations. It names no account, resource, URL,
principal or credential. A receipt from the simulated account is refused outright: a committed
file must never be able to pass a rehearsal off as AWS evidence.
"""

import json
from pathlib import Path

from scripts.aws.v1.proof.core import (
    PASS,
    ProofError,
    check_public,
    private_write,
    stamp,
)

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = ROOT / "docs/execution/aws/v1/evidence"
ISSUES = ("63", "64", "65", "66", "67", "68", "185", "196", "229")
NOT_PROVEN = (
    "Invoice lines: Cost Explorer lags about a day and is an estimate, not a bill.",
    "A rollback of a good promotion is an image rollback; no schema is reversed.",
    "Latency was measured from a Fargate generator in the same region, not from users.",
    "Local fakes, emulators and hosted CI are not AWS evidence and are excluded here.",
)


def load(directory, run_id):
    found = {}
    for issue in ISSUES:
        path = Path(directory) / f"evidence-{issue}-{run_id}.json"
        if path.exists():
            found[issue] = json.loads(path.read_text())
    return found


def overall(doc, required):
    """Recompute the verdict from the stored steps so an edited file cannot upgrade itself."""
    steps = doc["steps"]
    statuses = [steps[n]["status"] for n in required if n in steps]
    if any(s["status"] == "FAIL" for s in steps.values()) or "FAIL" in statuses:
        return "FAIL"
    if any(n not in steps for n in required):
        return "INCOMPLETE"
    if any(s["status"] == "NOT_RUN" for s in steps.values()):
        return "PARTIAL"
    return PASS


def build(docs, required, run_id, *, wall):
    if not docs:
        raise ProofError("No receipts for this run id; nothing to summarize")
    issues = {}
    for issue, doc in docs.items():
        if doc.get("mode") != "live" or doc.get("run_id") != run_id:
            raise ProofError(
                f"Receipt for #{issue} is not a live receipt of this run; "
                "a rehearsal can never be summarized for the repository")
        issues[f"#{issue}"] = {
            "overall": overall(doc, required[issue]),
            "steps": {name: {"status": step["status"], "seconds": step["seconds"],
                             "public": step["public"]} for name, step in doc["steps"].items()},
        }
    for issue in ISSUES:
        issues.setdefault(f"#{issue}", {"overall": "NOT_RUN", "steps": {}})
    summary = {
        "document_kind": "V1_CLOUD_PROOF_SUMMARY_REDACTED", "run_id": run_id,
        "generated_at": stamp(wall()), "mode": "live",
        "closes": "nothing by itself: an issue closes only when its acceptance list is met "
                  "by the receipts and a reviewer accepts them",
        "issues": issues, "not_proven": list(NOT_PROVEN),
    }
    check_public(summary, "summary")
    return summary


def write(summary, directory):
    path = Path(directory) / f"cloud-proof-{summary['run_id']}.json"
    private_write(path, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    path.chmod(0o644)  # public by design: it passed the redaction screen
    return path


def counts(docs):
    """Attempt counts implied by the receipts, for `session close --counts-file`.

    Drain only needs `processing == 0`, and these are what the harnesses observed to be
    terminal. The operator attests that nothing else ran against this stack; that attestation
    is stated in the output, not hidden in a file.
    """
    result = dict.fromkeys(("queued", "processing", "succeeded", "failed", "abandoned",
                            "cancelled"), 0)
    for issue, doc in docs.items():
        if doc.get("mode") != "live":
            raise ProofError("Counts come from live receipts only")
        for name, step in doc["steps"].items():
            public = step["public"]
            if issue == "63" and name == "direct-upload-e2e":
                result["succeeded" if public.get("job_status") == "done" else "failed"] += 1
            if issue == "64" and name.startswith("run-"):
                result["succeeded"] += public.get("outcomes", {}).get("done", 0)
                result["failed"] += public.get("outcomes", {}).get("failed", 0)
                result["cancelled"] += public.get("outcomes", {}).get("cancelled", 0)
            if (issue == "185" and name.startswith("backlog-") and name != "backlog-compare") or (
                    issue == "68" and name == "launcher-backlog"):
                outcomes = public.get("outcomes", {})
                result["succeeded"] += outcomes.get("done", 0)
                result["failed"] += outcomes.get("failed", 0)
                result["cancelled"] += outcomes.get("cancelled", 0)
                # A timed-out step stops its encoders: any job still queued or processing is a
                # real leftover, so it is counted and the close proof stays honest.
                result["queued"] += public.get("jobs_not_terminal", 0)
            if issue == "229" and name == "setup-job":
                result["succeeded" if public.get("job_status") == "done" else "failed"] += 1
            if issue == "196" and name == "processing-down":
                result["succeeded" if public.get("job_status") == "done" else "failed"] += 1
            if issue == "64" and name == "recovery":
                result["abandoned"] += public.get("interrupted_attempts", 0)
                result["succeeded" if public.get("final_status") == "done" else "failed"] += 1
    return result


def write_counts(state_dir, docs):
    """Write the private counts file and point the operator config's close-proof at it."""
    state = Path(state_dir)
    config_path = state / "operator-config.json"
    config = json.loads(config_path.read_text())
    if config.get("sql"):
        raise ProofError("The operator config reads attempt counts from SQL; no file is needed")
    path = state / "evidence-counts.json"
    private_write(path, json.dumps(counts(docs)))
    config["counts_file"] = path.name  # relative to the config: see operations.STATE_PATH_KEYS
    private_write(config_path, json.dumps(config, indent=2))
    return path

