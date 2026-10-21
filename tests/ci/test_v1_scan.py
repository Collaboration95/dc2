"""The V1 image scan gate: identity, failure propagation and workflow wiring."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci.policy import classify
from scripts.ci.v1_scan import OWNERS, RETAINED, evaluate, main, scan_receipt, validate_scan

ROOT = Path(__file__).resolve().parents[2]
SHA = "b" * 40


def receipt():
    return {"images": {o: {"source_sha": SHA, "config_id": f"sha256:{o}"} for o in OWNERS}}


def report(owner, vulns=(), image_id=None):
    return {
        "Metadata": {"ImageID": image_id or f"sha256:{owner}"},
        "Results": [
            {"Class": "os-pkgs", "Type": "debian", "Vulnerabilities": list(vulns)},
            {"Class": "lang-pkgs", "Type": "python-pkg"},
        ],
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

    def test_receipt_from_another_candidate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = evaluate(receipt(), tmp, sha="c" * 40)
        self.assertTrue(all("not this candidate" in e["verdict"] for e in entries))

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

    def test_incomplete_reports_fail_for_each_recipe(self):
        for owner in OWNERS:
            for results in (
                None,
                [],
                [{}],
                "bad",
                [1],
                [{"Class": "os-pkgs", "Type": "debian"}],
                [{"Class": "lang-pkgs", "Type": "python-pkg"}],
            ):
                with self.subTest(owner=owner, results=results):
                    reports = self.clean()
                    reports[owner]["Results"] = results
                    self.assertIn("FAIL", self.run_gate(reports)[owner]["verdict"])
            reports = self.clean()
            del reports[owner]["Results"]
            self.assertIn("FAIL", self.run_gate(reports)[owner]["verdict"])

    def test_clean_targets_allow_omitted_null_and_empty_vulnerability_lists(self):
        for value in (None, []):
            reports = self.clean()
            for content in reports.values():
                for target in content["Results"]:
                    target["Vulnerabilities"] = value
            self.assertTrue(all(e["verdict"] == "PASS" for e in self.run_gate(reports).values()))
        self.assertTrue(all(e["verdict"] == "PASS" for e in self.run_gate(self.clean()).values()))

    def test_python_findings_block_the_exact_candidate(self):
        reports = self.clean()
        reports["media"]["Results"][1]["Vulnerabilities"] = [vuln("CRITICAL", "2")]
        self.assertIn("fixable HIGH/CRITICAL", self.run_gate(reports)["media"]["verdict"])

    def test_bad_json_is_a_failed_disposition_and_owner_scans_can_be_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "trivy-media.json").write_text("{")
            result = evaluate(receipt(), tmp, owners=["media"])
        self.assertEqual(len(result), 1)
        self.assertIn("FAIL", result[0]["verdict"])


def raw(content):
    return json.dumps(content).encode()


class RetainedBaselineTests(unittest.TestCase):
    """A rollback target this release replaces may record fixable findings; nothing else may."""

    CONFIG = f"sha256:{'1' * 64}"
    GHSA = "GHSA-6q48-6c7w-9gw2"

    def scan(self, content, *, retained, config=None):
        return scan_receipt(
            raw(content), config_id=config or self.CONFIG, source_sha=SHA, retained=retained
        )

    def fixable(self, *ids):
        return report(
            "x",
            [{**vuln("CRITICAL", "2"), "VulnerabilityID": i, "PkgName": "certifi"} for i in ids],
            image_id=self.CONFIG,
        )

    def test_a_fixable_finding_fails_unless_the_image_is_a_replaced_rollback_target(self):
        with self.assertRaisesRegex(ValueError, "1 fixable HIGH/CRITICAL"):
            self.scan(self.fixable(self.GHSA), retained=False)
        scan = self.scan(self.fixable(self.GHSA), retained=True)
        self.assertEqual(scan["status"], RETAINED)
        self.assertEqual(scan["fixable_high_critical"], 1)
        self.assertEqual(scan["fixable_ids"], [f"{self.GHSA} certifi"])

    def test_a_clean_image_is_a_plain_pass_in_either_mode(self):
        for retained in (False, True):
            scan = self.scan(self.fixable(), retained=retained)
            self.assertEqual(scan["status"], "PASS")
            self.assertEqual(scan["fixable_high_critical"], 0)
            self.assertNotIn("fixable_ids", scan)

    def test_retained_mode_still_refuses_an_unusable_report(self):
        broken = self.fixable(self.GHSA)
        for content, config in (
            (broken, f"sha256:{'2' * 64}"),  # scanned a different image
            ({**broken, "Results": broken["Results"][:1]}, None),  # no Python target
            ({"Metadata": broken["Metadata"]}, None),  # no results at all
        ):
            with self.subTest(content=content.keys(), config=config):
                with self.assertRaises(ValueError):
                    self.scan(content, retained=True, config=config)

    def test_only_a_baseline_validator_accepts_a_retained_receipt(self):
        scan = self.scan(self.fixable(self.GHSA), retained=True)
        with self.assertRaisesRegex(ValueError, "Trivy scan"):
            validate_scan(scan, config_id=self.CONFIG, source_sha=SHA)
        self.assertIs(
            validate_scan(scan, config_id=self.CONFIG, source_sha=SHA, retained=True), scan
        )

    def test_a_retained_receipt_must_name_exactly_the_findings_it_counts(self):
        good = self.scan(self.fixable(self.GHSA), retained=True)
        for change in (
            {"fixable_ids": []},
            {"fixable_ids": [f"{self.GHSA} certifi", "CVE-2026-1 libx"]},
            {"fixable_ids": [1]},
            {"fixable_high_critical": 0},
            {"status": "PASS"},  # a pass cannot list findings
            {"config_id": f"sha256:{'3' * 64}"},
            {"source_sha": "c" * 40},
            {"scanned_at": "2020-01-01T00:00:00+00:00"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_scan(
                        {**good, **change}, config_id=self.CONFIG, source_sha=SHA, retained=True
                    )

    def test_the_cli_records_the_finding_and_exits_zero_only_in_retained_mode(self):
        content = self.fixable(self.GHSA)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "trivy-media.json").write_text(json.dumps(content))
            build = path / "build.json"
            build.write_text(
                json.dumps({"images": {"media": {"source_sha": SHA, "config_id": self.CONFIG}}})
            )
            args = [
                "--receipt",
                str(build),
                "--reports",
                str(path),
                "--out",
                str(path / "summary.json"),
                "--sha",
                "",
                "--attach",
                "--owner",
                "media",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 1)
            self.assertEqual(
                json.loads(build.read_text())["images"]["media"]["trivy_scan"]["status"], "FAIL"
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main([*args, "--retained"]), 0)
            attached = json.loads(build.read_text())["images"]["media"]["trivy_scan"]
            self.assertEqual(attached["status"], RETAINED)
            self.assertEqual(attached["fixable_ids"], [f"{self.GHSA} certifi"])
            self.assertIn("RETAINED: 1 fixable HIGH/CRITICAL", out.getvalue())
            summary = json.loads((path / "summary.json").read_text())["images"][0]
            self.assertEqual(summary["fixable_high_critical"], [f"{self.GHSA} certifi"])
            self.assertTrue(summary["verdict"].startswith("RETAINED:"))


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
        self.assertRegex(
            self.job,
            r"if: always\(\)\n        uses: actions/upload-artifact@[0-9a-f]{40}"
            r"(?: #[^\n]*)?\n        with:\n          name: v1-image-scans-",
        )

    def test_docs_only_change_selects_no_image_work(self):
        self.assertFalse(classify(["docs/ci/policy.md"])["selected"]["images"])
        self.assertTrue(classify(["deploy/v1/worker.Dockerfile"])["selected"]["images"])


if __name__ == "__main__":
    unittest.main()
