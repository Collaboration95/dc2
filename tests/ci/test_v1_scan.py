"""The V1 image scan gate: identity, failure propagation and workflow wiring."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci.policy import classify
from scripts.ci.v1_scan import OWNERS, evaluate

ROOT = Path(__file__).resolve().parents[2]
SHA = "b" * 40


def receipt():
    return {"images": {o: {"source_sha": SHA, "config_id": f"sha256:{o}"} for o in OWNERS}}


def report(owner, vulns=(), image_id=None):
    return {
        "Metadata": {"ImageID": image_id or f"sha256:{owner}"},
        "Results": [{"Vulnerabilities": list(vulns)}],
    }


def vuln(severity, fixed):
    return {
        "VulnerabilityID": "CVE-1",
        "PkgName": "libx",
        "Severity": severity,
        "FixedVersion": fixed,
    }


class ScanGateTests(unittest.TestCase):
    def run_gate(self, reports, rcpt=None):
        with tempfile.TemporaryDirectory() as tmp:
            for owner, content in reports.items():
                (Path(tmp) / f"trivy-{owner}.json").write_text(json.dumps(content))
            return {e["owner"]: e for e in evaluate(rcpt or receipt(), tmp)}

    def clean(self):
        return {o: report(o) for o in OWNERS}

    def test_clean_reports_pass_with_source_and_local_image_identity(self):
        entries = self.run_gate(self.clean())
        for owner, entry in entries.items():
            self.assertEqual(entry["verdict"], "PASS")
            self.assertEqual(entry["source_sha"], SHA)
            self.assertEqual(entry["local_image_config_id"], f"sha256:{owner}")
            self.assertEqual(entry["dockerfile"], f"deploy/v1/{owner}.Dockerfile")
            self.assertIsNone(entry["registry_digest"])

    def test_fixable_high_fails_only_that_image(self):
        reports = self.clean()
        reports["worker"] = report("worker", [vuln("HIGH", "1.2")])
        entries = self.run_gate(reports)
        self.assertTrue(entries["worker"]["verdict"].startswith("FAIL"))
        self.assertEqual(entries["media"]["verdict"], "PASS")

    def test_unfixed_and_low_findings_are_counted_but_do_not_fail(self):
        reports = self.clean()
        reports["media"] = report("media", [vuln("CRITICAL", ""), vuln("LOW", "2")])
        entry = self.run_gate(reports)["media"]
        self.assertEqual(entry["verdict"], "PASS")
        self.assertEqual(entry["unfixed_high_critical_count"], 1)

    def test_missing_report_wrong_image_or_missing_receipt_entry_fail(self):
        reports = self.clean()
        del reports["processing"]
        reports["media"] = report("media", image_id="sha256:other")
        entries = self.run_gate(reports)
        self.assertIn("missing", entries["processing"]["verdict"])
        self.assertTrue(entries["media"]["verdict"].startswith("FAIL"))
        self.assertTrue(
            self.run_gate(self.clean(), rcpt={"images": {}})["worker"]["verdict"].startswith("FAIL")
        )


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / ".github/workflows/v1.yml").read_text()
        self.job = text.split("\n  images:\n", 1)[1].split("\n  v1-result:", 1)[0]

    def test_all_three_images_are_scanned_in_the_existing_image_job(self):
        for owner in OWNERS:
            self.assertIn(f"image-ref: dc2-v1-{owner}:local-", self.job)
            self.assertIn(f"output: trivy-{owner}.json", self.job)
        self.assertEqual(self.job.count("docker build"), 0)

    def test_gate_runs_after_scans_and_reports_upload_even_on_failure(self):
        gate = self.job.index("scripts.ci.v1_scan")
        upload = self.job.index("name: v1-image-scans-")
        self.assertLess(self.job.index("trivy-worker.json"), gate)
        self.assertLess(gate, upload)
        self.assertIn("if: always()\n        run: python3 -m scripts.ci.v1_scan", self.job)
        self.assertIn(
            "if: always()\n        uses: actions/upload-artifact@v4\n        with:\n"
            "          name: v1-image-scans-",
            self.job,
        )

    def test_docs_only_change_selects_no_image_work(self):
        self.assertFalse(classify(["docs/ci/policy.md"])["selected"]["images"])
        self.assertTrue(classify(["deploy/v1/worker.Dockerfile"])["selected"]["images"])


if __name__ == "__main__":
    unittest.main()
