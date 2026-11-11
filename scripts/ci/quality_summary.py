"""Publish existing quality evidence without making a new gate."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.ci.sarif import executed_findings


def junit(path: Path) -> str:
    if not path.is_file():
        return "Unit tests: NOT_MEASURED (JUnit unavailable).\n"
    root = ET.parse(path).getroot()
    # Count leaf suites only, so nested aggregate totals are never counted twice.
    suites = [s for s in root.iter("testsuite") if not s.findall("testsuite")]
    counts = {
        key: sum(int(s.get(key, 0)) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    passed = counts["tests"] - sum(counts[k] for k in ("failures", "errors", "skipped"))
    return (
        f"Unit tests (fast suite): {counts['tests']} total, {passed} passed, "
        f"{counts['failures']} failed, {counts['errors']} errors, {counts['skipped']} skipped.\n"
    )


def coverage(path: Path) -> str:
    if not path.is_file():
        return "Coverage: NOT_MEASURED (gate.json unavailable).\n"
    data = json.loads(path.read_text())
    lines = [
        "### Existing coverage gate",
        "",
        f"Tiers: {', '.join(data['tiers'])}.",
        "",
        "| Package | Combined % | Raw branch % | 80% floor |",
        "|---|---:|---:|---|",
    ]
    for row in data["packages"]:
        lines.append(
            f"| {row['package']} | {row['combined']:.2f} | {row['raw_branch']:.2f} | "
            f"{'MET' if row['combined'] >= 80 else 'BELOW'} |"
        )
    goals = data["goals"]
    lines += [
        "",
        f"Additional goals enforced: {goals['enforced_for_complete_backend_tiers']}",
        "",
        "| Goal | Combined actual/target % | Branch actual/target % | Status |",
        "|---|---:|---:|---|",
    ]
    for category in ("packages", "recovery_modules"):
        for name, row in goals[category].items():
            lines.append(
                f"| {name} | {row['combined']:.2f}/{row['combined_target']} | "
                f"{row['raw_branch']:.2f}/{row['raw_branch_target']} | {row['status']} |"
            )
    for name, row in {"bootstrap": data["bootstrap"], **data["risk_modules"]}.items():
        if row["status"] != "MEASURED":
            lines.append(f"\n{name}: NOT_MEASURED")
    return "\n".join(lines) + "\n"


def zap(directory: Path) -> str:
    findings = executed_findings(directory)
    disposition_path = directory / "scan-disposition.json"
    disposition = json.loads(disposition_path.read_text()) if disposition_path.is_file() else {}
    prefix = (
        "### ZAP severity evaluation (advisory)\n\n"
        f"Scope: {disposition.get('scope', 'NOT_MEASURED')}.\n\n"
        "Excluded: deployed AWS endpoints, admin/mutation/HLS operations outside the "
        "committed scan inventory.\n\n"
    )
    if (
        findings is None
        or disposition.get("cleanup") != "PASS"
        or disposition.get("private_raw_cleanup") != "PASS"
    ):
        return prefix + "Policy verdict: NOT_EVALUATED (scan incomplete or unavailable).\n"
    labels = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}
    counts = {label: 0 for label in labels.values()}
    instances = dict(counts)
    for finding in findings:
        label = labels[finding["risk_code"]]
        counts[label] += 1
        instances[label] += int(finding["count"])
    lines = [prefix, "| Severity | Alert records | Instances |", "|---|---:|---:|"]
    for label in counts:
        lines.append(f"| {label} | {counts[label]} | {instances[label]} |")
    lines.append(
        "\nProposed HIGH/CRITICAL policy: "
        + ("WOULD_FAIL" if counts["High"] else "MET")
        + " (advisory; ZAP has no Critical risk code)."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("junit", "coverage", "zap"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        text = {"junit": junit, "coverage": coverage, "zap": zap}[args.kind](args.path)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        # Publication must not change scan/test gates or turn invalid evidence into a clean verdict.
        text = (
            f"{args.kind}: NOT_EVALUATED / NOT_MEASURED (invalid evidence: {type(error).__name__})."
        )
    print(text)


if __name__ == "__main__":
    main()
