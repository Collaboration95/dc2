"""Deterministic fast checks and opt-in real integration, without retry-to-green."""

import argparse
import json
import shutil
from pathlib import Path

from scripts.dev.common import PYTHON, ROOT, fingerprint, local_env, packages, run

COVERAGE_DIR = ROOT / "artifacts/coverage"


def service_tests(domain: str) -> list[str]:
    """Explicit filename ownership prevents a new service leaking into the legacy tier."""
    paths = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests/integration").glob(f"test_{domain}_*.py")
    )
    if domain == "processing":
        paths.append("tests/integration/test_database_ownership.py")
    return paths


def fast_env() -> dict[str, str]:
    env = local_env()
    prefixes = (
        "RUN_",
        "POSTGRES",
        "PROCESSING_",
        "MEDIA_",
        "MINIO_",
        "REDIS_",
        "JWT_",
        "WORKER_",
        "REAPER_",
        "OUTPUT_",
        "API_PUBLIC_",
        "AWS_",
        "LOCALSTACK_",
    )
    return {key: value for key, value in env.items() if not key.startswith(prefixes)}


def pytest_args(*, integration: bool = False) -> list[str]:
    return [
        str(PYTHON),
        "-m",
        "pytest",
        "-q",
        "-p",
        "scripts.dev.pytest_plugin",
        "--require-integration" if integration else "--offline-fast",
    ]


def measure(command: list[str], tier: str, env: dict[str, str], timeout: int) -> Path:
    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    data = COVERAGE_DIR / f".coverage.{tier}"
    # Never accept a stale fragment after a failed new attempt.
    data.unlink(missing_ok=True)
    data.with_suffix(data.suffix + ".json").unlink(missing_ok=True)
    env = dict(env, COVERAGE_FILE=str(data))
    command += [f"--cov={name}" for name in packages()]
    command += ["--cov-report=", "--cov-fail-under=0"]
    run(command, label=f"coverage-{tier}", timeout=timeout, env=env)
    data.with_suffix(data.suffix + ".json").write_text(
        json.dumps(
            {
                "fingerprint": fingerprint(),
                "tier": tier,
                "packages": packages(),
            }
        )
        + "\n"
    )
    return data


def fast(*, coverage: bool = False, domain: str | None = None) -> Path | None:
    paths = ["tests"]
    if domain:
        if domain not in packages():
            raise SystemExit(f"{domain} is not implemented yet; await its owning lane")
        paths = (
            [f"tests/{domain}"]
            if domain != "app"
            else sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_*.py"))
        )
        if not paths or any(not (ROOT / path).exists() for path in paths):
            raise SystemExit(f"No focused tests found for {domain}; its lane must supply them")
    # Tests marked `unmeasured` exercise only code outside the measured packages (the AWS
    # operator tooling), and tracing them made the coverage run four times slower. They still
    # run in `make test` and in the V1 CI job, which has no coverage tracer.
    selection = "not integration and not e2e" + (" and not unmeasured" if coverage else "")
    ignored = ["--ignore=tests/integration", "--ignore=tests/e2e"]
    command = pytest_args() + paths + ignored + ["-m", selection]
    if coverage:
        return measure(command, "fast", fast_env(), 120)
    run(command, label=f"test-python-{domain or 'fast'}", timeout=120, env=fast_env())
    return None


def frontend(*, coverage: bool = False) -> None:
    command = [
        "npm",
        "run",
        "test:coverage" if coverage else "test",
        "--",
        "--exclude",
        "**/*.live.test.js",
    ]
    if coverage:
        command += ["--coverage.reporter=text", "--coverage.reporter=lcov"]
    run(
        command,
        label="coverage-frontend" if coverage else "test-frontend",
        timeout=90,
        env=fast_env(),
        cwd=ROOT / "frontend",
    )


def integration(*, coverage: bool = False) -> list[Path]:
    env = local_env()
    selected = []
    if env.get("RUN_POSTGRES_TESTS") == "1":
        if not env.get("POSTGRES_DSN"):
            raise SystemExit(
                "RUN_POSTGRES_TESTS=1 requires explicit POSTGRES_DSN for an isolated DB"
            )
        for name in ("ffmpeg", "ffprobe"):
            if not shutil.which(name):
                raise SystemExit(f"Explicit integration requires {name} on PATH; cannot skip")
        selected.append(
            (
                "legacy-integration",
                ["tests/integration"]
                + [
                    f"--ignore={path}"
                    for path in service_tests("processing") + service_tests("media")
                ],
            )
        )
    if env.get("RUN_PROCESSING_TESTS") == "1":
        for name in ("PROCESSING_POSTGRES_DSN", "PROCESSING_SERVICE_TOKEN", "P2_POSTGRES_PORT"):
            if not env.get(name):
                raise SystemExit(f"RUN_PROCESSING_TESTS=1 requires explicit {name}")
        selected.append(("processing-integration", service_tests("processing")))
    if env.get("RUN_MEDIA_TESTS") == "1":
        if not env.get("MEDIA_POSTGRES_DSN"):
            raise SystemExit("RUN_MEDIA_TESTS=1 requires explicit MEDIA_POSTGRES_DSN")
        paths = service_tests("media")
        if not paths:
            raise SystemExit("Media integration has no selected tests")
        selected.append(("media-integration", paths))
    if not selected:
        raise SystemExit(
            "Integration is opt-in: set RUN_POSTGRES_TESTS=1 with POSTGRES_DSN, or "
            "RUN_PROCESSING_TESTS=1 with PROCESSING_POSTGRES_DSN, "
            "PROCESSING_SERVICE_TOKEN and P2_POSTGRES_PORT, or RUN_MEDIA_TESTS=1 "
            "with MEDIA_POSTGRES_DSN. See README local setup."
        )
    fragments = []
    for tier, paths in selected:
        command = pytest_args(integration=True) + paths
        if coverage:
            fragments.append(measure(command, tier, env, 300))
        else:
            run(command, label=tier, timeout=300, env=env)
    return fragments


def lint() -> None:
    paths = packages() + [
        str(p)
        for p in ("tests", "migrations", "scripts/dev", "scripts/evidence", "scripts/aws")
        if (ROOT / p).exists()
    ]
    run([str(PYTHON), "-m", "ruff", "check", *paths], label="lint", timeout=60)


def clean() -> None:
    # Only generated test/lint output; preserve secrets, environments, browsers and volumes.
    for directory in (".pytest_cache", ".cache/ruff", "frontend/coverage", "artifacts/coverage"):
        path = ROOT / directory
        if path.is_symlink():
            raise SystemExit(f"Refusing to clean symlink: {directory}")
        if path.exists():
            shutil.rmtree(path)
        print(f"Cleaned {directory}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "test",
            "test-python",
            "test-frontend",
            "lint",
            "coverage",
            "coverage-fast",
            "coverage-frontend",
            "integration",
            "integration-coverage",
            "clean",
        ),
    )
    parser.add_argument(
        "--domain", choices=("app", "processing", "media", "media_engine", "publisher")
    )
    args = parser.parse_args()
    if args.action in {"test", "test-python"}:
        fast(domain=args.domain)
    if args.action in {"test", "test-frontend"}:
        frontend()
    if args.action == "lint":
        lint()
    if args.action == "coverage-fast":
        fast(coverage=True)
    if args.action == "coverage-frontend":
        frontend(coverage=True)
    if args.action in {"integration", "integration-coverage"}:
        integration(coverage=args.action == "integration-coverage")
    if args.action == "coverage":
        data = [fast(coverage=True)]
        frontend(coverage=True)
        if any(
            local_env().get(name) == "1"
            for name in ("RUN_POSTGRES_TESTS", "RUN_PROCESSING_TESTS", "RUN_MEDIA_TESTS")
        ):
            data.extend(integration(coverage=True))
        command = [str(PYTHON), "-m", "scripts.dev.coverage"]
        for path in data:
            command += ["--data", str(path)]
        run(command, label="coverage-gate", timeout=60)
    if args.action == "clean":
        clean()


if __name__ == "__main__":
    main()
