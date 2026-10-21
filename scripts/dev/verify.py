"""One-command local checks against isolated, disposable test service containers."""

import argparse
import json
import os
import signal
import subprocess
from uuid import uuid4

from scripts.dev.checks import FAST_COVERAGE_TIMEOUT
from scripts.dev.common import PYTHON, ROOT, local_env, run
from scripts.dev.runtime import configure
from scripts.dev.scenario import ServiceGuard, utcnow


def stop_child(child, *, grace=5):
    """Cancel the child's process group before restoration, including Docker CLIs."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # The direct child can exit while its subprocesses remain alive. Always
    # kill the remaining group before starting any restoration commands.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=5)


def supervised_e2e(run_id, *, timeout=900, command=None, grace=5):
    """Parent-owned worker guard survives forced child termination at 900s."""
    _, state = configure(run_id)
    path = ROOT / "artifacts" / run_id / f"e2e-supervisor-{uuid4().hex[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "started_at": utcnow(), "events": [], "status": "running"}
    failure = None

    def record(event, **values):
        report["events"].append({"event": event, "at": utcnow(), **values})
        path.write_text(json.dumps(report, indent=2) + "\n")

    try:
        # Only worker is mutated by e2e; do not touch unrelated services.
        with ServiceGuard(state, ("worker",), record):
            child = subprocess.Popen(
                command or [str(PYTHON), "-m", "scripts.dev.e2e", "--run-id", run_id],
                cwd=ROOT,
                env=local_env(),
                start_new_session=True,
            )
            try:
                status = child.wait(timeout=timeout)
                if status:
                    raise SystemExit(status)
            except BaseException as error:
                try:
                    stop_child(child, grace=grace)
                except BaseException as cancellation_error:
                    error.add_note("Child process-group cancellation failed")
                    report["events"].append(
                        {
                            "event": "child-cancellation",
                            "status": "FAIL",
                            "failure_type": type(cancellation_error).__name__,
                        }
                    )
                raise
        report["status"] = "PASS"
    except BaseException as error:
        failure = error
        report.update(status="FAIL", failure_type=type(error).__name__)
        raise
    finally:
        report["finished_at"] = utcnow()
        try:
            path.write_text(json.dumps(report, indent=2) + "\n")
        except OSError:
            if failure is None:
                raise
            failure.add_note("Supervisor evidence could not be saved")
        print(f"E2E supervisor: {path}", flush=True)


def verify(run_id, *, full=True):
    run([str(PYTHON), "-m", "scripts.dev.doctor"], label="doctor", timeout=60)
    run([str(PYTHON), "-m", "scripts.dev.checks", "lint"], label="lint", timeout=60)
    run(
        [str(PYTHON), "-m", "scripts.dev.checks", "coverage-fast"],
        label="fast-coverage",
        timeout=FAST_COVERAGE_TIMEOUT + 30,  # the child's own budget plus startup margin
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
        supervised_e2e(run_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--checks-only", action="store_true")
    args = parser.parse_args()
    verify(args.run_id, full=not args.checks_only)


if __name__ == "__main__":
    main()
