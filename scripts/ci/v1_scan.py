"""Gate the Trivy reports of the exact V1 images that `make v1-images` just built.

Identity comes from the build receipt (source SHA, Dockerfile, local image config ID), and each
report must name that same config ID, so a stale or wrong tag cannot pass. The config ID is a
local Docker image ID, never a registry digest; `registry_digest` stays null here and is proven
only by the release-time ECR scan. Policy matches the inherited scan: zero fixable HIGH/CRITICAL.
Unfixed findings stay in the full report and are counted, but do not fail.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

OWNERS = {
    "media": "Media API (Lambda)",
    "processing": "Processing API (Lambda)",
    "worker": "finite encoder worker (Fargate task)",
}
BLOCKING = {"HIGH", "CRITICAL"}
RECEIPT_GLOB = "docs/execution/aws/v1/evidence/local-images-*.json"


def findings(report):
    fixable, unfixed = [], []
    for result in report.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            if vuln.get("Severity") not in BLOCKING:
                continue
            item = f"{vuln.get('VulnerabilityID')} {vuln.get('PkgName')}"
            (fixable if vuln.get("FixedVersion") else unfixed).append(item)
    return fixable, unfixed


def evaluate(receipt, reports_dir):
    entries = []
    for owner, role in OWNERS.items():
        image = (receipt or {}).get("images", {}).get(owner, {})
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
        if not entry["local_image_config_id"]:
            entry["verdict"] = "FAIL: image missing from build receipt"
        elif not path.is_file():
            entry["verdict"] = "FAIL: scanner report missing"
        else:
            report = json.loads(path.read_text())
            fixable, unfixed = findings(report)
            entry["fixable_high_critical"] = fixable
            entry["unfixed_high_critical_count"] = len(unfixed)
            scanned = (report.get("Metadata") or {}).get("ImageID")
            if scanned != entry["local_image_config_id"]:
                entry["verdict"] = f"FAIL: report scanned {scanned}, receipt has the other ID"
            elif fixable:
                entry["verdict"] = f"FAIL: {len(fixable)} fixable HIGH/CRITICAL"
            else:
                entry["verdict"] = "PASS"
        entries.append(entry)
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", default=".", help="directory holding trivy-<owner>.json")
    parser.add_argument("--out", default="v1-scan-summary.json")
    args = parser.parse_args(argv)
    receipts = sorted(glob.glob(RECEIPT_GLOB))
    receipt = json.loads(Path(receipts[-1]).read_text()) if receipts else None
    entries = evaluate(receipt, args.reports)
    summary = {"scan": "V1 images, CI local candidates", "images": entries}
    Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
    for e in entries:
        print(f"{e['owner']}: {e['verdict']}")
    return 0 if all(e["verdict"] == "PASS" for e in entries) else 1


if __name__ == "__main__":
    sys.exit(main())
