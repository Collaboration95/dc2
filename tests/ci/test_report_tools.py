"""Offline scanner disposition and publication regressions."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci import quality_summary as quality
from scripts.ci import security_scans as scans


class ScannerTests(unittest.TestCase):
    def test_audit_clean_findings_and_execution_errors(self):
        for vulns, code in (([], 0), ([{"id": "fixture"}], 1)):
            report = {"dependencies": [{"name": "fixture", "vulns": vulns}]}
            self.assertEqual(scans.findings("pip-audit", report, code)["findings"], len(vulns))
            with self.assertRaises(ValueError):
                scans.findings("pip-audit", report, 2)
            with self.assertRaises(ValueError):
                scans.findings("pip-audit", report, 1 - code)
        for report in ({}, {"dependencies": []}, {"dependencies": [{"skip_reason": "error"}]}):
            with self.assertRaises((ValueError, KeyError)):
                scans.findings("pip-audit", report, 0)

    def test_checkov_policy_failure_is_advisory_but_parse_error_is_not(self):
        results = {
            "passed_checks": [1],
            "failed_checks": [2],
            "skipped_checks": [],
            "parsing_errors": [],
        }
        self.assertEqual(scans.findings("checkov", {"results": results}, 1)["findings"], 1)
        results["parsing_errors"] = ["broken.json"]
        with self.assertRaises(ValueError):
            scans.findings("checkov", {"results": results}, 1)
        results.update(parsing_errors=[], passed_checks=[], failed_checks=[])
        with self.assertRaises(ValueError):
            scans.findings("checkov", {"results": results}, 0)

    def test_export_must_be_pinned_and_not_empty_or_local(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            for text in ("", "# comment", "-e .", "foo>=1", "foo @ https://example.test/foo"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    scans.pinned_requirements(path)
            path.write_text('foo==1.0 ; python_version >= "3.12"\n')
            self.assertEqual(scans.pinned_requirements(path), 1)

    def test_missing_or_malformed_scanner_report_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(scans.subprocess, "run") as runner:

                def export(*args, **kwargs):
                    (Path(directory) / "runtime-requirements.txt").write_text("foo==1\n")
                    runner.return_value.returncode = 0
                    runner.return_value.stderr = ""
                    return runner.return_value

                runner.side_effect = export
                with self.assertRaises(FileNotFoundError):
                    scans.run("pip-audit", Path(directory), "fixture")

                def malformed(*args, **kwargs):
                    result = export(*args, **kwargs)
                    if args[0][0] == "fixture":
                        (Path(directory) / "runtime-union.json").write_text("broken")
                    return result

                runner.side_effect = malformed
                with self.assertRaises(json.JSONDecodeError):
                    scans.run("pip-audit", Path(directory), "fixture")


class PublicationTests(unittest.TestCase):
    def test_junit_nested_suites_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tests.xml"
            self.assertIn("NOT_MEASURED", quality.junit(path))
            path.write_text(
                '<testsuites><testsuite tests="99"><testsuite tests="7" '
                'failures="1" errors="1" skipped="2"/></testsuite></testsuites>'
            )
            self.assertIn("7 total, 3 passed, 1 failed, 1 errors, 2 skipped", quality.junit(path))

    def test_coverage_displays_existing_values_and_goal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"
            self.assertIn("NOT_MEASURED", quality.coverage(path))
            goal = dict(
                combined=88.25,
                raw_branch=82.5,
                combined_target=90,
                raw_branch_target=85,
                status="BELOW_GOAL",
            )
            path.write_text(
                json.dumps(
                    dict(
                        tiers=["fast"],
                        packages=[dict(package="media", combined=88.25, raw_branch=82.5)],
                        goals=dict(
                            enforced_for_complete_backend_tiers=False,
                            packages={"media": goal},
                            recovery_modules={},
                        ),
                        bootstrap={"status": "NOT_MEASURED"},
                        risk_modules={},
                    )
                )
            )
            text = quality.coverage(path)
            self.assertIn("88.25/90", text)
            self.assertIn("82.50/85", text)
            self.assertIn("BELOW_GOAL", text)
            self.assertIn("enforced: False", text)

    def test_zap_missing_failed_clean_high_and_unknown_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertIn("NOT_EVALUATED", quality.zap(path))
            disposition = path / "scan-disposition.json"
            inventory = path / "sanitized-findings.json"
            inventory.write_text("[]")
            disposition.write_text(json.dumps(dict(disposition="error", scope="fixture")))
            self.assertIn("NOT_EVALUATED", quality.zap(path))
            disposition.write_text(
                json.dumps(
                    dict(
                        disposition="executed",
                        scope="fixture",
                        cleanup="PASS",
                        private_raw_cleanup="PASS",
                    )
                )
            )
            self.assertIn("policy: MET", quality.zap(path))
            disposition.write_text(
                json.dumps(
                    dict(
                        disposition="executed",
                        scope="fixture",
                        cleanup="FAIL",
                        private_raw_cleanup="PASS",
                    )
                )
            )
            self.assertIn("NOT_EVALUATED", quality.zap(path))
            disposition.write_text(
                json.dumps(
                    dict(
                        disposition="executed",
                        scope="fixture",
                        cleanup="PASS",
                        private_raw_cleanup="PASS",
                    )
                )
            )
            inventory.write_text(json.dumps([dict(risk_code="3", count=4)]))
            text = quality.zap(path)
            self.assertIn("| High | 1 | 4 |", text)
            self.assertIn("WOULD_FAIL", text)
            self.assertIn("Scope: fixture", text)
            inventory.write_text(json.dumps([dict(risk_code="9", count=1)]))
            with self.assertRaises(KeyError):
                quality.zap(path)
            output = io.StringIO()
            with (
                patch("sys.argv", ["summary", "zap", str(path)]),
                contextlib.redirect_stdout(output),
            ):
                quality.main()
            self.assertIn("NOT_EVALUATED", output.getvalue())
            self.assertNotIn("policy: MET", output.getvalue())


if __name__ == "__main__":
    unittest.main()
