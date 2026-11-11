"""Advisory runtime SCA and offline rendered CloudFormation scans; execution errors fail."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.aws.v1.definitions import SEPARATE, DatabaseOptions, template

ROOT = Path(__file__).resolve().parents[2]


def findings(kind: str, report: dict, code: int) -> dict:
    """Accept findings exits only with complete machine-readable evidence."""
    if code not in (0, 1):
        raise ValueError(f"{kind} execution failed: exit {code}")
    if kind == "pip-audit":
        deps = report["dependencies"]
        if not deps or any("skip_reason" in dep for dep in deps):
            raise ValueError("Empty or partially skipped dependency audit")
        counts = {
            "packages": len(deps),
            "vulnerable_packages": sum(bool(dep["vulns"]) for dep in deps),
            "findings": sum(len(dep["vulns"]) for dep in deps),
        }
    else:
        results = report["results"]
        if results["parsing_errors"]:
            raise ValueError("Checkov template parsing failed")
        counts = {
            key: len(results[key]) for key in ("passed_checks", "failed_checks", "skipped_checks")
        }
        if not counts["passed_checks"] + counts["failed_checks"]:
            raise ValueError("Checkov evaluated no checks")
        counts["findings"] = counts["failed_checks"]
    if (code == 1) != bool(counts["findings"]):
        raise ValueError("Scanner exit and finding report disagree")
    return counts


def pinned_requirements(path: Path) -> int:
    """Reject empty, editable, project, URL or unpinned exports before auditing."""
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    requirements = [line for line in lines if not line.startswith("#")]
    if not requirements or any(
        "==" not in line or line.startswith("-") or " @ " in line for line in requirements
    ):
        raise ValueError("Expected nonempty fully pinned runtime requirements")
    return len(requirements)


def run(kind: str, output: Path, tool: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    records = []
    if kind == "pip-audit":
        requirements = output / "runtime-requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--no-emit-project",
                "--no-hashes",
                "--extra",
                "v1-media",
                "--extra",
                "v1-processing",
                "--extra",
                "v1-worker",
                "--output-file",
                str(requirements),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        exported = pinned_requirements(requirements)
        targets = [("runtime-union", ["-r", str(requirements), "--no-deps", "--disable-pip"])]
    else:
        exported = None
        targets = []
    with tempfile.TemporaryDirectory(prefix="dc2-security-") as directory:
        rendered = Path(directory)
        if kind == "checkov":
            bodies = {
                "shared": template(),
                "separate": template(DatabaseOptions(SEPARATE)),
                "split": template(DatabaseOptions(SEPARATE, clone_processing=True)),
            }
            for name, body in bodies.items():
                (rendered / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n")
            shutil.copyfile(ROOT / "deploy/aws/v1/github-oidc.yaml", rendered / "oidc.yaml")
            # Keep rendered input bytes with reports after the disposable scan directory closes.
            shutil.copytree(rendered, output / "templates", dirs_exist_ok=True)
            targets = [(path.stem, ["-f", str(path)]) for path in sorted(rendered.iterdir())]
        for name, arguments in targets:
            report_path = output / f"{name}.json"
            report_path.unlink(missing_ok=True)
            command = [tool, *arguments]
            if kind == "pip-audit":
                command += ["-f", "json", "-o", str(report_path)]
            else:
                command += [
                    "--framework",
                    "cloudformation",
                    "--skip-download",
                    "--skip-results-upload",
                    "-o",
                    "json",
                ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=600, check=False
            )
            (output / f"{name}.stderr.txt").write_text(result.stderr)
            if kind == "checkov":
                report_path.write_text(result.stdout)
            counts = findings(kind, json.loads(report_path.read_text()), result.returncode)
            records.append({"scope": name, "exit_status": result.returncode, **counts})
    version = subprocess.check_output([tool, "--version"], text=True).strip()
    evidence = {
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "tool": kind,
        "version": version,
        "advisory": True,
        "exported_requirement_lines": exported,
        "results": records,
    }
    (output / "execution.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"### {kind} (advisory)\n")
    print(
        "Runtime extras union; environment markers apply, no dev dependencies."
        if exported
        else "Static rendered shared/separate/split + OIDC CloudFormation; no cloud validation."
    )
    print(f"\nSource: `{evidence['source_sha']}`; tool: `{version}`\n")
    print("| Scope | Findings | Details |\n|---|---:|---|")
    for record in records:
        print(f"| {record['scope']} | {record['findings']} | `{json.dumps(record)}` |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("pip-audit", "checkov"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--tool", required=True)
    args = parser.parse_args()
    run(args.kind, args.output.resolve(), args.tool)


if __name__ == "__main__":
    main()
