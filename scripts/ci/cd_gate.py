"""Admit only exact-source full CI; read GitHub exclusively through authenticated gh."""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.ci.policy import expected_jobs
from scripts.dev.ci_timings import gh_json, tested_source

FIELDS = "databaseId,attempt,event,headSha,headBranch,status,conclusion,url,workflowName"


def validate(run: dict, selection: dict, sha: str) -> dict:
    if run.get("workflowName") != "CI" or run.get("headSha") != sha:
        raise ValueError("CI workflow/source mismatch")
    if (
        run.get("event") not in {"push", "workflow_dispatch"}
        or run["event"] == "push"
        and run.get("headBranch") != "Main"
    ):
        raise ValueError(
            "CI admission needs a Main push or exact-source full dispatch; PR head is insufficient"
        )
    if run.get("status") != "completed":
        raise ValueError("CI is still running for this source/attempt")
    if run.get("conclusion") != "success":
        raise ValueError("CI attempt did not succeed: " + str(run.get("conclusion")))
    provenance = {
        "id": run["databaseId"],
        "run_attempt": run["attempt"],
        "event": run["event"],
        "head_sha": run["headSha"],
    }
    if tested_source({"run": provenance, "selection": selection}) != sha:
        raise ValueError("CI selection did not verify the intended source SHA")
    if selection.get("mode") != "full":
        raise ValueError("CI selection must be full tier")
    expected_jobs(selection, "full")  # rejects missing lanes and a full tier with deselections
    gates = [job for job in run.get("jobs", []) if job.get("name") == "Full verification"]
    if (
        len(gates) != 1
        or gates[0].get("status") != "completed"
        or gates[0].get("conclusion") != "success"
    ):
        raise ValueError("Full verification must complete successfully in this CI attempt")
    return {
        "status": "PASS",
        "source_sha": sha,
        "run_id": run["databaseId"],
        "run_attempt": run["attempt"],
        "event": run["event"],
        "tier": "full",
        "required_gate": "Full verification",
        "url": run["url"],
    }


def admit(
    repository: str, sha: str, *, trigger_id: str | None = None, trigger_attempt: str | None = None
) -> dict:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Exact repository and source SHA required")
    if trigger_id:
        if not str(trigger_id).isdecimal() or not str(trigger_attempt).isdecimal():
            raise ValueError("Automatic CD needs the exact triggering CI run and attempt")
        run_id, attempt = str(trigger_id), str(trigger_attempt)
    else:
        runs = gh_json(
            [
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "ci.yml",
                "--commit",
                sha,
                "--limit",
                "100",
                "--json",
                FIELDS + ",createdAt",
            ]
        )
        eligible = [
            r
            for r in runs
            if r["event"] == "workflow_dispatch"
            or r["event"] == "push"
            and r["headBranch"] == "Main"
        ]
        if not eligible:
            raise ValueError("No CI run exists for full Main push/exact-source dispatch; reverify")
        latest = max(eligible, key=lambda r: r["createdAt"])
        run_id, attempt = str(latest["databaseId"]), str(latest["attempt"])
    args = ["run", "view", run_id, "--repo", repository]
    run = gh_json([*args, "--attempt", attempt, "--json", FIELDS + ",jobs"])
    if str(run.get("databaseId")) != run_id or str(run.get("attempt")) != attempt:
        raise ValueError("CI run/attempt differs from the requested provenance")
    if trigger_id and (run.get("event") != "push" or run.get("headBranch") != "Main"):
        raise ValueError("Automatic CD requires its triggering Main push CI run")
    with tempfile.TemporaryDirectory(prefix="dc2-cd-admission-") as directory:
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                f"ci-selection-{attempt}",
                "--dir",
                directory,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        selection = json.loads((Path(directory) / "ci-policy.json").read_text())
    receipt = validate(run, selection, sha)
    # A rerun started while evidence was read invalidates the admission, including auto CD.
    current = gh_json([*args, "--json", FIELDS])
    if (
        str(current.get("attempt")) != attempt
        or current.get("status") != "completed"
        or current.get("conclusion") != "success"
    ):
        raise ValueError("CI attempt changed while admitting the candidate; reverify")
    return receipt


def main():
    try:
        automatic = os.environ["CD_EVENT"] == "workflow_run"
        trigger = os.environ.get("CD_CI_RUN_ID") if automatic else None
        attempt = os.environ.get("CD_CI_RUN_ATTEMPT") if automatic else None
        if automatic and (not trigger or not attempt):
            raise ValueError("Automatic CD needs the exact triggering CI run and attempt")
        receipt = admit(
            os.environ["CD_REPO"], os.environ["CD_SHA"], trigger_id=trigger, trigger_attempt=attempt
        )
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit(
            "CI admission failed (missing/expired evidence requires reverify): " + detail
        ) from None
    out = Path(os.environ["RUNNER_TEMP"]) / "cd-out/public/ci-admission.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        f"Full CI passed for {receipt['source_sha']}: {receipt['url']} "
        f"(attempt {receipt['run_attempt']})"
    )


if __name__ == "__main__":
    main()
