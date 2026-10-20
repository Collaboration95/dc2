"""Gate the Trivy reports of the exact V1 images that `make v1-images` just built.

Identity comes from the build receipt (source SHA, Dockerfile, local image config ID), and each
report must name that same config ID, so a stale or wrong tag cannot pass. The config ID is a
local Docker image ID, never a registry digest; `registry_digest` stays null here and is bound
by the release-time raw manifest receipt. Policy is zero fixable HIGH/CRITICAL.
Unfixed findings stay in the full report and are counted, but do not fail.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

OWNERS = {
    "media": "Media API (Lambda)",
    "processing": "Processing API (Lambda)",
    "worker": "finite encoder worker (Fargate task)",
}
BLOCKING = {"HIGH", "CRITICAL"}
RECEIPT = "docs/execution/aws/v1/evidence/local-images-{}.json"
TARGETS = (("os-pkgs", "debian"), ("lang-pkgs", "python-pkg"))
POLICY = "zero-fixable-high-critical; Debian OS and Python packages"


def validate_report(report: dict, config_id: str) -> dict:
    """Require actual recipe coverage, while allowing zero vulnerability rows per target."""
    if not isinstance(report, dict) or not isinstance(report.get("Metadata"), dict):
        raise ValueError("Trivy report metadata missing")
    if report["Metadata"].get("ImageID") != config_id:
        raise ValueError("Trivy report scanned a different config ID")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Trivy Results must contain scanned OS and Python targets")
    targets = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Trivy target must be an object")
        targets.add((str(result.get("Class")), str(result.get("Type"))))
        vulns = result.get("Vulnerabilities")
        if vulns is None:
            continue
        if not isinstance(vulns, list) or any(
            not isinstance(v, dict)
            or not isinstance(v.get("Severity"), str)
            or v["Severity"] not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
            for v in vulns
        ):
            raise ValueError("Trivy vulnerability rows are malformed")
    missing = set(TARGETS) - targets
    if missing:
        raise ValueError(
            "Trivy report missing targets: " + ", ".join(t for _, t in sorted(missing))
        )
    return report


def scan_receipt(raw: bytes, *, config_id: str, source_sha: str) -> dict:
    report = validate_report(json.loads(raw), config_id)
    fixable, unfixed = findings(report)
    if fixable:
        raise ValueError(f"Trivy has {len(fixable)} fixable HIGH/CRITICAL")
    return {
        "status": "PASS",
        "config_id": config_id,
        "source_sha": source_sha,
        "policy": POLICY,
        "targets": [list(t) for t in TARGETS],
        "report_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "fixable_high_critical": 0,
        "unfixed_high_critical_count": len(unfixed),
        "scanned_at": datetime.now(UTC).isoformat(),
    }


def validate_scan(scan: dict, *, config_id: str, source_sha: str) -> dict:
    """Release receipts expire after 24 h; retained images are rescanned by digest each run."""
    if (
        not isinstance(scan, dict)
        or scan.get("status") != "PASS"
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(config_id))
        or not re.fullmatch(r"[0-9a-f]{40}", str(source_sha))
        or scan.get("config_id") != config_id
        or scan.get("source_sha") != source_sha
        or scan.get("policy") != POLICY
        or scan.get("targets") != [list(t) for t in TARGETS]
        or scan.get("fixable_high_critical") != 0
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(scan.get("report_sha256")))
    ):
        raise ValueError("Missing or mismatched exact-image Trivy scan")
    try:
        at = datetime.fromisoformat(scan["scanned_at"])
        age = datetime.now(UTC) - at
    except (KeyError, TypeError, ValueError):
        raise ValueError("Trivy scan timestamp missing or invalid") from None
    if not timedelta(minutes=-5) <= age <= timedelta(hours=24):
        raise ValueError("Trivy scan expired; rescan the exact config/digest")
    return scan


def findings(report):
    fixable, unfixed = [], []
    for result in report.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            if vuln.get("Severity") not in BLOCKING:
                continue
            item = f"{vuln.get('VulnerabilityID')} {vuln.get('PkgName')}"
            (fixable if vuln.get("FixedVersion") else unfixed).append(item)
    return fixable, unfixed


def evaluate(receipt, reports_dir, sha=None, owners=None):
    entries = []
    for owner in owners or OWNERS:
        role = OWNERS[owner]
        images = receipt.get("images") if isinstance(receipt, dict) else None
        image = images.get(owner) if isinstance(images, dict) else None
        image = image if isinstance(image, dict) else {}
        entry = {
            "owner": owner,
            "role": role,
            "dockerfile": f"deploy/v1/{owner}.Dockerfile",
            "source_sha": image.get("source_sha"),
            "local_image_config_id": image.get("config_id"),
            "registry_digest": None,
            "report": f"trivy-{owner}.json",
        }
        path = Path(reports_dir) / entry["report"]
        if sha and entry["source_sha"] != sha:
            entry["verdict"] = "FAIL: receipt source SHA is not this candidate"
        elif not entry["local_image_config_id"]:
            entry["verdict"] = "FAIL: image missing from build receipt"
        elif not path.is_file():
            entry["verdict"] = "FAIL: scanner report missing"
        else:
            try:
                raw = path.read_bytes()
                report = validate_report(json.loads(raw), entry["local_image_config_id"])
                fixable, unfixed = findings(report)
                entry["fixable_high_critical"] = fixable
                entry["unfixed_high_critical_count"] = len(unfixed)
                entry["scan"] = scan_receipt(
                    raw, config_id=entry["local_image_config_id"], source_sha=entry["source_sha"]
                )
            except (OSError, ValueError) as error:
                entry["verdict"] = f"FAIL: {error}"
            else:
                entry["verdict"] = "PASS"
        entries.append(entry)
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", default=".", help="directory holding trivy-<owner>.json")
    parser.add_argument("--out", default="v1-scan-summary.json")
    # Committed receipts from earlier candidates sit in the same directory, so the file is
    # selected by this candidate's SHA, never by glob order or age.
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--receipt", type=Path, help="explicit CD build receipt")
    parser.add_argument("--owner", action="append", choices=OWNERS)
    parser.add_argument("--attach", action="store_true", help="attach passing scans to the receipt")
    args = parser.parse_args(argv)
    path = args.receipt or Path(RECEIPT.format(args.sha[:12]))
    try:
        receipt = json.loads(path.read_text()) if path.is_file() else None
    except (OSError, ValueError):
        receipt = None
    entries = evaluate(receipt, args.reports, args.sha or None, args.owner)
    summary = {"scan": "V1 exact-config Debian OS and Python packages", "images": entries}
    Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
    for e in entries:
        print(f"{e['owner']}: {e['verdict']}")
    passed = all(e["verdict"] == "PASS" for e in entries)
    if args.attach and isinstance(receipt, dict) and isinstance(receipt.get("images"), dict):
        for e in entries:
            image = receipt["images"].get(e["owner"])
            if isinstance(image, dict):
                image["trivy_scan"] = e.get("scan", {"status": "FAIL", "error": e["verdict"]})
        path.write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
