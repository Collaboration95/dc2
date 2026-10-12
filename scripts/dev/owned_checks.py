"""Real service-owned PostgreSQL/Redis/storage checks in an isolated local stack."""

import argparse
import json
import socket
import time
from pathlib import Path

from scripts.dev.common import PYTHON, local_env, run
from scripts.dev.runtime import MINIO_COMMIT, atomic_write, compose, configure, free_ports, images
from scripts.dev.runtime import run as docker_run


def host_dsn(value, port):
    return value.replace("@postgres:5432/", f"@127.0.0.1:{port}/")


def integration_environment(values, state, storage_port, redis_port, *, all_services=False):
    env = local_env()
    # Explicit flags below must win over unrelated enabled test tiers in the shell.
    for key in list(env):
        if key.startswith("RUN_"):
            env.pop(key)
    env.update(values)
    for service in ("MEDIA", "PROCESSING"):
        for suffix in ("POSTGRES_DSN", "MIGRATION_DSN"):
            key = f"{service}_{suffix}"
            env[key] = host_dsn(values[key], state["postgres_port"])
        env[f"{service}_MINIO_ENDPOINT"] = f"127.0.0.1:{storage_port}"
    env.update(
        RUN_PROCESSING_TESTS="1",
        RUN_PROCESSING_REDIS_TESTS="1",
        RUN_PROCESSING_STORAGE_TESTS="1",
        P2_POSTGRES_PORT=str(state["postgres_port"]),
        PROCESSING_REDIS_URL=values["PROCESSING_REDIS_URL"].replace(
            "@redis:6379/", f"@127.0.0.1:{redis_port}/"
        ),
    )
    if all_services:
        env.update(
            RUN_POSTGRES_TESTS="1",
            RUN_MEDIA_TESTS="1",
            POSTGRES_DSN=(
                f"postgresql://postgres:{values['POSTGRES_PASSWORD']}"
                f"@127.0.0.1:{state['postgres_port']}/legacy_regression"
            ),
            MINIO_ENDPOINT=f"127.0.0.1:{storage_port}",
            MINIO_PUBLIC_ENDPOINT=f"127.0.0.1:{storage_port}",
            MINIO_ACCESS_KEY=values["MINIO_ROOT_USER"],
            MINIO_SECRET_KEY=values["MINIO_ROOT_PASSWORD"],
            MINIO_BUCKET="legacy-regression",
            MINIO_REGION="us-east-1",
            MINIO_USE_SSL="false",
            MINIO_PUBLIC_USE_SSL="false",
        )
    return env


def wait_ports(ports):
    for port in ports:
        deadline = time.monotonic() + 20
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Test container loopback forwarding unavailable") from None
                time.sleep(0.1)


def owned_checks(run_id, *, all_services=False, build=True):
    values, state = configure(run_id)
    ports = free_ports(2)
    overlay = Path(values["DC2_RUN_DIR"]) / "test-ports.json"
    atomic_write(
        overlay,
        json.dumps(
            {
                "services": {
                    "minio": {
                        "ports": [f"127.0.0.1:{ports[0]}:9000"],
                        "networks": ["object-data", "host-access"],
                    },
                    "redis": {
                        "ports": [f"127.0.0.1:{ports[1]}:6379"],
                        "networks": ["processing-data", "host-access"],
                    },
                }
            }
        ),
    )

    def test_compose(*args, **kwargs):
        return compose(state, "-f", str(overlay), *args, **kwargs)

    try:
        run(
            [str(PYTHON), "-m", "scripts.dev.tls", "--run-id", run_id], label="test-tls", timeout=30
        )
        if build:
            images(state)
        else:
            for key in ("DC2_PROCESSING_IMAGE", "DC2_MINIO_IMAGE"):
                result = docker_run(
                    ["docker", "image", "inspect", values[key]],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                metadata = json.loads(result.stdout)[0]
                if key == "DC2_MINIO_IMAGE":
                    labels = metadata["Config"].get("Labels") or {}
                    if labels.get("org.opencontainers.image.revision") != MINIO_COMMIT:
                        raise ValueError("Test storage image must match pinned source")
        # Only persistent services belong in --wait. Compose versions differ in
        # whether an already-completed one-shot is accepted there, and a running
        # migrator without a healthcheck is not proof that its migration finished.
        test_compose(
            "up",
            "--no-build",
            "-d",
            "--wait",
            "--wait-timeout",
            "180",
            "postgres",
            "redis",
            "minio",
            timeout=240,
        )
        one_shots = ["storage-bootstrap", "processing-migrate"]
        if all_services:
            one_shots.append("media-migrate")
        for service in one_shots:
            test_compose("run", "--rm", "-T", "--no-deps", service, timeout=120)
        wait_ports((state["postgres_port"], *ports))
        env = integration_environment(values, state, *ports, all_services=all_services)
        if all_services:
            existing = test_compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname='legacy_regression'",
                capture_output=True,
                text=True,
                timeout=15,
            )
            if existing.stdout.strip() != "1":
                test_compose(
                    "exec",
                    "-T",
                    "postgres",
                    "createdb",
                    "-U",
                    "postgres",
                    "legacy_regression",
                    timeout=15,
                )
            run(
                [str(PYTHON), "-m", "alembic", "upgrade", "head"],
                label="legacy-test-migrations",
                timeout=60,
                env=env,
            )
        run(
            [str(PYTHON), "-m", "scripts.dev.checks", "integration-coverage"],
            label="owned-service-integration",
            timeout=900,
            env=env,
        )
    finally:
        test_compose("down", timeout=120)  # Deliberately preserve this namespace's test volumes.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="owned-checks")
    parser.add_argument("--all-services", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    owned_checks(args.run_id, all_services=args.all_services, build=not args.no_build)


if __name__ == "__main__":
    main()
