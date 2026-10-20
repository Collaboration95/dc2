"""Gate combined statement/branch coverage for each package, using matching evidence."""

import argparse
import fnmatch
import json
from pathlib import Path

from coverage import Coverage

from scripts.dev.common import (
    ROOT,
    V1_BOOTSTRAP_FILE,
    V1_BOOTSTRAP_SOURCE,
    coverage_omit_patterns,
    fingerprint,
    packages,
)

PACKAGE_COVERAGE_GOALS = {
    "media": {"combined": 90, "raw_branch": 85},
    "processing": {"combined": 90, "raw_branch": 85},
}
RECOVERY_COVERAGE_GOALS = {
    "media/recovery_v1.py": {"combined": 80, "raw_branch": 75},
    "processing/recovery_v1.py": {"combined": 80, "raw_branch": 75},
}
RISK_MODULES = (
    "media/recovery_v1.py",
    "processing/recovery_v1.py",
    "processing/messaging.py",
    "runtime_support/storage_credentials.py",
)
COMPLETE_BACKEND_TIERS = {
    "fast",
    "legacy-integration",
    "processing-integration",
    "media-integration",
    "v1-integration",
}


def rates(summary: dict) -> tuple[float, float]:
    statements = summary["num_statements"]
    branches = summary["num_branches"]
    covered = summary["covered_lines"] + summary["covered_branches"]
    combined = 100 * covered / (statements + branches) if statements + branches else 100.0
    raw_branch = 100 * summary["covered_branches"] / branches if branches else 100.0
    return combined, raw_branch


def package_totals(files: dict, package: str) -> dict:
    keys = ("num_statements", "num_branches", "covered_lines", "covered_branches")
    omitted = coverage_omit_patterns(ROOT)
    selected = [
        value["summary"]
        for name, value in files.items()
        if Path(name).parts[0] == package
        and not any(fnmatch.fnmatchcase(name, pattern) for pattern in omitted)
    ]
    if not selected:
        raise ValueError(f"No coverage files for {package}; refusing an empty successful gate")
    return {key: sum(summary[key] for summary in selected) for key in keys}


def file_report(files: dict, path: str) -> dict:
    """Summarize a separately deployed Python entrypoint outside the service packages."""
    value = files.get(path)
    if value is None:
        return {"path": path, "status": "NOT_MEASURED"}
    summary = value["summary"]
    combined, branch = rates(summary)
    return {
        "path": path,
        "status": "MEASURED",
        "combined": combined,
        "raw_branch": branch,
        **summary,
    }


def goal_report(actual: dict, target: dict) -> dict:
    met = actual["combined"] >= target["combined"] and actual["raw_branch"] >= target["raw_branch"]
    return {
        "combined_target": target["combined"],
        "raw_branch_target": target["raw_branch"],
        "combined": actual["combined"],
        "raw_branch": actual["raw_branch"],
        "status": "MET" if met else "BELOW_GOAL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, action="append", required=True)
    parser.add_argument("--package", choices=packages(), action="append")
    args = parser.parse_args()
    current = fingerprint()
    tiers = []
    expected_omit = coverage_omit_patterns(ROOT)
    for path in args.data:
        metadata = path.with_suffix(path.suffix + ".json")
        if not path.is_file() or not metadata.is_file():
            raise SystemExit(f"Missing coverage evidence/metadata: {path}; collect with checks.py")
        evidence = json.loads(metadata.read_text())
        if evidence["fingerprint"] != current:
            raise SystemExit(
                f"Stale coverage evidence: {path}; collect on the exact current sources"
            )
        if evidence.get("omit") != expected_omit:
            raise SystemExit(
                f"Coverage omit mismatch: {path}; collect every tier with the current "
                "pyproject.toml"
            )
        tiers.append(evidence["tier"])
    if "fast" not in tiers:
        raise SystemExit(
            "Coverage gate requires current fast evidence, plus real integration as needed"
        )
    output = ROOT / "artifacts/coverage"
    output.mkdir(parents=True, exist_ok=True)
    sources = packages()
    if (ROOT / V1_BOOTSTRAP_FILE).is_file():
        sources.append(V1_BOOTSTRAP_SOURCE)
    measured = Coverage(
        data_file=str(output / ".coverage.combined"),
        config_file=str(ROOT / "pyproject.toml"),
        source=sources,
    )
    measured.erase()
    measured.combine(data_paths=[str(p.resolve()) for p in args.data], strict=True, keep=True)
    measured.save()
    # pytest-cov's global fail_under is bypassed only for reporting; enforce per package below.
    measured.json_report(outfile=str(output / "backend.json"), omit=expected_omit)
    measured.xml_report(outfile=str(output / "backend.xml"))
    files = json.loads((output / "backend.json").read_text())["files"]
    failures = []
    rows = []
    for package in args.package or packages():
        try:
            summary = package_totals(files, package)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        # Verify the source scanner included every production Python file, even never imported.
        expected = {
            str(p.relative_to(ROOT))
            for p in (ROOT / package).rglob("*.py")
            if "migrations" not in p.parts and "__pycache__" not in p.parts
        }
        missing = expected - set(files)
        if missing:
            raise SystemExit(f"Unmeasured production files in {package}: {sorted(missing)}")
        combined, branch = rates(summary)
        print(f"{package}: combined {combined:.2f}% (>=80), raw branches {branch:.2f}%")
        rows.append(dict(package=package, combined=combined, raw_branch=branch, **summary))
        if combined < 80:
            failures.append(package)
    bootstrap = file_report(files, V1_BOOTSTRAP_FILE)
    if "v1-integration" in tiers and bootstrap["status"] != "MEASURED":
        failures.append(V1_BOOTSTRAP_FILE)
    if bootstrap["status"] == "MEASURED":
        print(
            f"{V1_BOOTSTRAP_FILE}: combined {bootstrap['combined']:.2f}%, "
            f"raw branches {bootstrap['raw_branch']:.2f}% (reported separately; no floor)"
        )
    elif "v1-integration" not in tiers:
        print(f"{V1_BOOTSTRAP_FILE}: NOT_MEASURED (V1 integration tier not supplied)")
    package_rows = {row["package"]: row for row in rows}
    package_goals = {
        package: goal_report(package_rows[package], target)
        for package, target in PACKAGE_COVERAGE_GOALS.items()
        if package in package_rows
    }
    recovery_reports = {path: file_report(files, path) for path in RECOVERY_COVERAGE_GOALS}
    recovery_goals = {
        path: goal_report(recovery_reports[path], target)
        for path, target in RECOVERY_COVERAGE_GOALS.items()
        if recovery_reports[path]["status"] == "MEASURED"
    }
    risk_modules = {
        path: file_report(files, path)
        for path in RISK_MODULES
        if path not in RECOVERY_COVERAGE_GOALS
    }
    for name, result in (*package_goals.items(), *recovery_goals.items()):
        print(
            f"goal {name}: {result['status']} "
            f"(combined {result['combined']:.2f}%/{result['combined_target']}%, "
            f"branches {result['raw_branch']:.2f}%/{result['raw_branch_target']}%)"
        )
    for name, result in risk_modules.items():
        if result["status"] == "MEASURED":
            print(
                f"risk module {name}: combined {result['combined']:.2f}%, "
                f"raw branches {result['raw_branch']:.2f}% (no floor)"
            )
    if COMPLETE_BACKEND_TIERS.issubset(tiers):
        for package, result in package_goals.items():
            if result["status"] != "MET":
                failures.append(f"{package} coverage goal")
        for path, result in recovery_goals.items():
            if result["status"] != "MET":
                failures.append(f"{path} coverage goal")
    gate = {
        "tiers": tiers,
        "omit": expected_omit,
        "packages": rows,
        "bootstrap": bootstrap,
        "goals": {
            "enforced_for_complete_backend_tiers": COMPLETE_BACKEND_TIERS.issubset(tiers),
            "packages": package_goals,
            "recovery_modules": recovery_goals,
        },
        "risk_modules": {**recovery_reports, **risk_modules},
    }
    (output / "gate.json").write_text(json.dumps(gate, indent=2) + "\n")
    if failures:
        raise SystemExit(
            f"Coverage below 80%: {', '.join(failures)}. Database repository coverage "
            "must include real integration; unit-only evidence is not sufficient."
        )


if __name__ == "__main__":
    main()
