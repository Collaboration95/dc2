"""Gate combined statement/branch coverage for each package, using matching evidence."""

import argparse
import json
from pathlib import Path

from coverage import Coverage

from scripts.dev.common import ROOT, fingerprint, packages


def rates(summary: dict) -> tuple[float, float]:
    statements = summary["num_statements"]
    branches = summary["num_branches"]
    covered = summary["covered_lines"] + summary["covered_branches"]
    combined = 100 * covered / (statements + branches) if statements + branches else 100.0
    raw_branch = 100 * summary["covered_branches"] / branches if branches else 100.0
    return combined, raw_branch


def package_totals(files: dict, package: str) -> dict:
    keys = ("num_statements", "num_branches", "covered_lines", "covered_branches")
    selected = [value["summary"] for name, value in files.items() if Path(name).parts[0] == package]
    if not selected:
        raise ValueError(f"No coverage files for {package}; refusing an empty successful gate")
    return {key: sum(summary[key] for summary in selected) for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, action="append", required=True)
    parser.add_argument("--package", choices=packages(), action="append")
    args = parser.parse_args()
    current = fingerprint()
    tiers = []
    for path in args.data:
        metadata = path.with_suffix(path.suffix + ".json")
        if not path.is_file() or not metadata.is_file():
            raise SystemExit(f"Missing coverage evidence/metadata: {path}; collect with checks.py")
        evidence = json.loads(metadata.read_text())
        if evidence["fingerprint"] != current:
            raise SystemExit(
                f"Stale coverage evidence: {path}; collect on the exact current sources"
            )
        tiers.append(evidence["tier"])
    if "fast" not in tiers:
        raise SystemExit(
            "Coverage gate requires current fast evidence, plus real integration as needed"
        )
    output = ROOT / "artifacts/coverage"
    output.mkdir(parents=True, exist_ok=True)
    measured = Coverage(
        data_file=str(output / ".coverage.combined"),
        config_file=str(ROOT / "pyproject.toml"),
        source=packages(),
    )
    measured.erase()
    measured.combine(data_paths=[str(p.resolve()) for p in args.data], strict=True, keep=True)
    measured.save()
    # pytest-cov's global fail_under is bypassed only for reporting; enforce per package below.
    measured.json_report(outfile=str(output / "backend.json"))
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
    (output / "gate.json").write_text(json.dumps(dict(tiers=tiers, packages=rows), indent=2) + "\n")
    if failures:
        raise SystemExit(
            f"Coverage below 80%: {', '.join(failures)}. Database repository coverage "
            "must include real integration; unit-only evidence is not sufficient."
        )


if __name__ == "__main__":
    main()
