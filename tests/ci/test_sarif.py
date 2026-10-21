"""SARIF publication helpers: ZAP conversion and the severity summary, offline."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci import sarif

ROOT = Path(__file__).resolve().parents[2]
FINDINGS = [
    {"service": "media", "plugin_id": "40018", "risk_code": "3", "confidence": "high", "count": 2},
    {
        "service": "media",
        "plugin_id": "10021",
        "risk_code": "1",
        "confidence": "medium",
        "count": 3,
    },
    {
        "service": "processing",
        "plugin_id": "10021",
        "risk_code": "0",
        "confidence": "low",
        "count": 1,
    },
]


def report(results, rules=()):
    return {"runs": [{"tool": {"driver": {"name": "t", "rules": list(rules)}}, "results": results}]}


class ZapConversionTests(unittest.TestCase):
    def test_each_alert_becomes_a_result_with_its_rule_and_risk(self):
        run = sarif.zap_to_sarif(FINDINGS)["runs"][0]
        rules = {rule["id"]: rule for rule in run["tool"]["driver"]["rules"]}
        self.assertEqual(set(rules), {"ZAP-40018", "ZAP-10021"})
        self.assertEqual(rules["ZAP-40018"]["properties"]["security-severity"], "8.0")
        self.assertEqual(rules["ZAP-10021"]["properties"]["security-severity"], "2.0")
        self.assertEqual([r["level"] for r in run["results"]], ["error", "note", "note"])
        self.assertIn("2 time(s)", run["results"][0]["message"]["text"])

    def test_results_point_at_committed_openapi_documents_and_carry_no_scan_detail(self):
        document = sarif.zap_to_sarif(FINDINGS)
        for result in document["runs"][0]["results"]:
            uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            self.assertTrue((ROOT / uri).is_file(), uri)
        # The raw report is deleted on purpose; the converter only sees retained fields.
        self.assertNotIn("http", json.dumps(document["runs"][0]["results"]))

    def test_informational_alerts_have_no_security_severity(self):
        only = [FINDINGS[2]]
        rule = sarif.zap_to_sarif(only)["runs"][0]["tool"]["driver"]["rules"][0]
        self.assertNotIn("security-severity", rule["properties"])

    def test_only_an_executed_scan_is_converted(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            (directory / "sanitized-findings.json").write_text(json.dumps(FINDINGS))
            self.assertIsNone(sarif.executed_findings(directory))  # no disposition yet
            for disposition, expected in (("error", None), ("executed", FINDINGS)):
                (directory / "scan-disposition.json").write_text(
                    json.dumps({"disposition": disposition})
                )
                self.assertEqual(sarif.executed_findings(directory), expected)
            output = directory / "zap.sarif"
            self.assertEqual(sarif.main(["zap", name, str(output)]), 0)
            self.assertEqual(len(json.loads(output.read_text())["runs"][0]["results"]), 3)
            (directory / "scan-disposition.json").write_text('{"disposition": "error"}')
            output.unlink()
            self.assertEqual(sarif.main(["zap", name, str(output)]), 0)
            self.assertFalse(output.exists())


class SummaryTests(unittest.TestCase):
    def test_severity_uses_the_score_then_the_level(self):
        rules = {"A": {"properties": {"security-severity": "9.8"}}}
        rules["B"] = {"properties": {"security-severity": "7.5"}}
        rules["C"] = {"properties": {"security-severity": "5.0"}}
        rules["D"] = {"properties": {"security-severity": "2.0"}}
        got = [sarif.severity({"ruleId": rule}, rules) for rule in "ABCD"]
        self.assertEqual(got, ["Critical", "High", "Medium", "Low"])
        self.assertEqual(sarif.severity({"ruleId": "X", "level": "error"}, rules), "Error")
        self.assertEqual(sarif.severity({"ruleId": "X"}, rules), "Warning")  # SARIF default

    def test_table_counts_per_report_and_marks_a_missing_report(self):
        rules = [{"id": "CVE-1", "properties": {"security-severity": "8.1"}}]
        with tempfile.TemporaryDirectory() as name:
            found = Path(name) / "trivy-media.sarif"
            found.write_text(json.dumps(report([{"ruleId": "CVE-1"}, {"ruleId": "CVE-1"}], rules)))
            clean = Path(name) / "trivy-worker.sarif"
            clean.write_text(json.dumps(report([])))
            table = sarif.summary("Images", [found, clean, Path(name) / "trivy-gone.sarif"])
        self.assertEqual(
            table.splitlines()[2:],
            [
                "| Report | High | Total |",
                "|---|---|---|",
                "| trivy-media | 2 | 2 |",
                "| trivy-worker | 0 | 0 |",
                "| trivy-gone | not produced |  |",
            ],
        )

    def test_clean_reports_show_only_the_total(self):
        with tempfile.TemporaryDirectory() as name:
            clean = Path(name) / "gitleaks.sarif"
            clean.write_text(json.dumps(report([])))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                sarif.main(["summary", "Secrets", str(clean)])
        self.assertIn("| Report | Total |", out.getvalue())
        self.assertIn("| gitleaks | 0 |", out.getvalue())


if __name__ == "__main__":
    unittest.main()
