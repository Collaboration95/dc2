"""One-command local checks against isolated, disposable test service containers."""

import argparse

from scripts.dev.common import PYTHON, ROOT, run


def verify(run_id, *, full=True):
    run([str(PYTHON), "-m", "scripts.dev.doctor"], label="doctor", timeout=60)
    run([str(PYTHON), "-m", "scripts.dev.checks", "lint"], label="lint", timeout=60)
    run(
        [str(PYTHON), "-m", "scripts.dev.checks", "coverage-fast"],
        label="fast-coverage",
        timeout=150,
    )
    run(
        [str(PYTHON), "-m", "scripts.dev.checks", "coverage-frontend"],
        label="frontend-coverage",
        timeout=120,
    )
    from scripts.dev.owned_checks import owned_checks

    owned_checks(run_id[:32] + "-checks", all_services=True)
    fragments = ["fast", "legacy-integration", "processing-integration", "media-integration"]
    command = [str(PYTHON), "-m", "scripts.dev.coverage"]
    for tier in fragments:
        command += ["--data", str(ROOT / f"artifacts/coverage/.coverage.{tier}")]
    run(command, label="package-coverage-gates", timeout=60)
    if full:
        run(
            [str(PYTHON), "-m", "scripts.dev.runtime", "smoke-infra", "--run-id", run_id],
            label="runtime-smoke",
            timeout=120,
        )
        run(
            [str(PYTHON), "-m", "scripts.dev.browser", "trust-smoke", "--run-id", run_id],
            label="browser-trust",
            timeout=90,
        )
        run(
            [str(PYTHON), "-m", "scripts.dev.e2e", "--run-id", run_id],
            label="complete-client-workflows",
            timeout=900,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--checks-only", action="store_true")
    args = parser.parse_args()
    verify(args.run_id, full=not args.checks_only)


if __name__ == "__main__":
    main()
