"""Publish scanner output to GitHub code scanning (SARIF) without changing any gate.

Trivy, Ruff and gitleaks write SARIF themselves. Two helpers cover the rest:

summary  print a severity-count table for SARIF files, for $GITHUB_STEP_SUMMARY.
zap      convert the sanitized DAST findings into SARIF. ZAP's packaged API scan has no SARIF
         report option, and its raw report is deleted on purpose (it carries URLs and response
         evidence), so the retained alert id, risk and count are all this converter sees. A scan
         that did not execute is not converted: an empty report would mark old alerts as fixed.
"""

import argparse
import json
import sys
from pathlib import Path

# Risk code -> (SARIF level, GitHub security-severity score, label). GitHub maps the score to
# Critical (over 9), High (7+), Medium (4+) and Low (above 0). Informational alerts carry no score.
ZAP_RISK = {
    "3": ("error", "8.0", "High"),
    "2": ("warning", "5.0", "Medium"),
    "1": ("note", "2.0", "Low"),
    "0": ("note", None, "Informational"),
}
SEVERITIES = ("Critical", "High", "Medium", "Low", "Error", "Warning", "Note")
LEVELS = {"error": "Error", "warning": "Warning", "note": "Note"}


def zap_to_sarif(findings: list[dict]) -> dict:
    """One result per sanitized alert, located at the service's committed OpenAPI document."""
    top = {}  # a plugin keeps one rule, so the rule carries the highest risk seen for it
    for finding in findings:
        top[finding["plugin_id"]] = max(top.get(finding["plugin_id"], "0"), finding["risk_code"])
    rules = []
    for plugin_id, risk in sorted(top.items()):
        level, score, label = ZAP_RISK[risk]
        rules.append(
            {
                "id": f"ZAP-{plugin_id}",
                "name": f"ZapAlert{plugin_id}",
                "shortDescription": {"text": f"OWASP ZAP alert {plugin_id} ({label})"},
                "helpUri": f"https://www.zaproxy.org/docs/alerts/{plugin_id}/",
                "defaultConfiguration": {"level": level},
                "properties": {
                    "tags": ["security", "dast"],
                    **({"security-severity": score} if score else {}),
                },
            }
        )
    results = []
    for finding in findings:
        level, _, label = ZAP_RISK[finding["risk_code"]]
        service = finding["service"]
        results.append(
            {
                "ruleId": f"ZAP-{finding['plugin_id']}",
                "level": level,
                "message": {
                    "text": (
                        f"ZAP raised alert {finding['plugin_id']} ({label} risk, "
                        f"{finding['confidence']} confidence) {finding['count']} time(s) against "
                        f"the {service} API in the authenticated local scan. Routes and evidence "
                        "are not retained; see the rule's help link for what the alert means."
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f"docs/api/{service}.openapi.json"},
                            "region": {"startLine": 1},
                        }
                    }
                ],
            }
        )
    driver = {"name": "OWASP ZAP", "informationUri": "https://www.zaproxy.org/", "rules": rules}
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }


def executed_findings(directory: Path) -> list[dict] | None:
    """The sanitized findings of a DAST run that executed, else None."""
    try:
        disposition = json.loads((directory / "scan-disposition.json").read_text())
        findings = json.loads((directory / "sanitized-findings.json").read_text())
    except (OSError, ValueError):
        return None
    return findings if disposition.get("disposition") == "executed" else None


def severity(result: dict, rules: dict) -> str:
    """The label GitHub shows: the rule's security-severity score, else the result level."""
    properties = (rules.get(result.get("ruleId")) or {}).get("properties") or {}
    try:
        score = float(properties.get("security-severity"))
    except (TypeError, ValueError):
        return LEVELS.get(result.get("level", "warning"), "Warning")
    if score > 9.0:
        return "Critical"
    if score >= 7.0:
        return "High"
    if score >= 4.0:
        return "Medium"
    return "Low" if score > 0 else "Note"


def count(path: Path) -> dict | None:
    """Severity counts of every result in a SARIF file, or None when it was not produced."""
    if not path.is_file():
        return None
    counts = {}
    for run in json.loads(path.read_text()).get("runs") or []:
        rules = {r.get("id"): r for r in run.get("tool", {}).get("driver", {}).get("rules") or []}
        for result in run.get("results") or []:
            label = severity(result, rules)
            counts[label] = counts.get(label, 0) + 1
    return counts


def summary(title: str, paths: list[Path]) -> str:
    """A small Markdown table: one row per report, one column per severity that occurs."""
    rows = [(path.stem, count(path)) for path in paths]
    shown = [s for s in SEVERITIES if any(c and s in c for _, c in rows)]
    lines = [f"#### {title}", "", "| Report | " + " | ".join([*shown, "Total"]) + " |"]
    lines.append("|---|" + "---|" * (len(shown) + 1))
    for name, counts in rows:
        if counts is None:
            lines.append(f"| {name} | " + " | ".join(["not produced"] + [""] * len(shown)) + " |")
        else:
            cells = [str(counts.get(s, 0)) for s in shown] + [str(sum(counts.values()))]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    table = commands.add_parser("summary", help="print a severity table for SARIF files")
    table.add_argument("title")
    table.add_argument("files", nargs="+", type=Path)
    zap = commands.add_parser("zap", help="convert a DAST report directory to SARIF")
    zap.add_argument("reports", type=Path, help="directory with the sanitized DAST JSON files")
    zap.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "summary":
        sys.stdout.write(summary(args.title, args.files))
        return 0
    findings = executed_findings(args.reports)
    if findings is None:
        print(f"No executed DAST scan in {args.reports}; nothing to publish.", file=sys.stderr)
    else:
        args.output.write_text(json.dumps(zap_to_sarif(findings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
