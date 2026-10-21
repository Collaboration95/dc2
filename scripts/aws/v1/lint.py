"""Offline cfn-lint of the rendered V1 template; skips cleanly when cfn-lint is absent.

python -m scripts.aws.v1.lint [--require]

Renders the template from code (never reads AWS), proves the committed snapshot is
current, then runs cfn-lint against ap-southeast-1. cfn-lint is a lint-only dependency
that is deliberately not in uv.lock, so a missing tool is a clean skip locally and a
failure in CI, which passes --require. cfn-lint itself makes no AWS calls.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.aws.v1.definitions import SEPARATE, SHARED, DatabaseOptions, template

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "deploy/aws/v1/template.json"
REGION = "ap-southeast-1"


def find_linter(which=shutil.which):
    # The active interpreter's environment counts even when its bin/ is not on PATH.
    sibling = Path(sys.executable).parent / "cfn-lint"
    found = which("cfn-lint")
    if found is None and which is shutil.which and sibling.exists():
        found = str(sibling)
    return found


def run(*, require=False, which=shutil.which, runner=subprocess.run, stdout=sys.stdout):
    built = template()
    if json.loads(SNAPSHOT.read_text()) != built:
        print(
            "deploy/aws/v1/template.json is stale; run "
            "python -m scripts.aws.v1.definitions --output deploy/aws/v1/template.json",
            file=stdout,
        )
        return 1
    linter = find_linter(which)
    if linter is None:
        print("cfn-lint not installed: SKIPPED (CI passes --require)", file=stdout)
        return 2 if require else 0
    # Every layout the generator can render is linted, not only the committed one: the V2
    # separate-cluster template (#94) has no snapshot and would otherwise never be checked, and
    # nor would the one a split stack keeps rendering (Processing's cluster as a clone).
    layouts = {
        SHARED: built,
        SEPARATE: template(DatabaseOptions(SEPARATE)),
        "split": template(DatabaseOptions(SEPARATE, clone_processing=True)),
    }
    with tempfile.TemporaryDirectory(prefix="dc2-cfn-lint-") as directory:
        for topology, body in layouts.items():
            rendered = Path(directory) / f"template-{topology}.json"
            rendered.write_text(json.dumps(body, indent=2) + "\n")
            result = runner(
                [linter, str(rendered), "--regions", REGION],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode:
                print(f"[{topology}] " + result.stdout + result.stderr, file=stdout)
                return 1
    print(
        "cfn-lint: PASS for shared, separate and split (offline; not evidence of deployability)",
        file=stdout,
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require", action="store_true", help="fail if cfn-lint is missing")
    return run(require=parser.parse_args(argv).require)


if __name__ == "__main__":
    raise SystemExit(main())
