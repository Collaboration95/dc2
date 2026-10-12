#!/usr/bin/env python3
"""Run-scoped local infrastructure; no global Docker context or trust changes."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
MINIO_COMMIT = "20960b6a2ddb9594ee418035b3c7c7fe92ae6a12"
COMPOSE = ROOT / "compose/local/docker-compose.yml"
ACTIONS = ("up", "down", "logs", "smoke-infra", "images", "env", "status")


def common_root(root=ROOT):
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()).parent if result.returncode == 0 else root


def selected_docker(root=ROOT):
    """Prefer an explicit override, then the healthy project VM, then caller context."""
    env = os.environ.copy()
    host = env.get("DC2_DOCKER_HOST") or env.get("DOCKER_HOST")
    config = env.get("DC2_DOCKER_CONFIG") or env.get("DOCKER_CONFIG")
    if not host:
        shared = common_root(root)
        candidate = shared / ".local/lima/d/sock/docker.sock"
        if candidate.is_socket():
            probe = env.copy()
            probe["DOCKER_HOST"] = "unix://" + str(candidate)
            probe["DOCKER_CONFIG"] = config or str(shared / ".local/docker")
            for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                probe.pop(key, None)
            try:
                result = subprocess.run(
                    ["docker", "info", "--format", "{{.NCPU}}"],
                    env=probe,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if result.returncode == 0:
                    host, config = probe["DOCKER_HOST"], probe["DOCKER_CONFIG"]
            except (OSError, subprocess.TimeoutExpired):
                pass
    return host, config or str(Path.home() / ".docker")


def subprocess_env():
    env = os.environ.copy()
    host, config = selected_docker()
    if host:
        env["DOCKER_HOST"] = host
        for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            env.pop(key, None)
    env["DOCKER_CONFIG"] = config
    return env


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, env=subprocess_env(), check=True, **kwargs)


def read_env(path):
    """Our generated dotenv uses literal values; preserve existing user entries verbatim."""
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, separator, value = line.partition("=")
                if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise ValueError(f"Invalid configuration line in {path}")
                result[key] = value
    return result


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp = Path(handle.name)
    temp.chmod(0o600)
    temp.replace(path)


def free_ports(count, reserved=()):
    sockets = []
    ports = []
    try:
        while len(ports) < count:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
            port = sock.getsockname()[1]
            if port not in reserved:
                ports.append(port)
    finally:
        for sock in sockets:
            sock.close()
    return ports


def configure(run_id, root=ROOT):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", run_id):
        raise ValueError("run-id must be 1–40 lowercase letters, digits or hyphens")
    directory = root / ".local/runs" / run_id
    path = directory / "runtime.env"
    env = read_env(path)
    project = "dc2-" + run_id + "-" + hashlib.sha256(str(root).encode()).hexdigest()[:8]
    reserved = set()
    for other in (root / ".local/runs").glob("*/state.json"):
        state = json.loads(other.read_text())
        reserved.update((state["postgres_port"], state["processing_port"]))
        reserved.add(int(state["public_url"].rsplit(":", 1)[1]))
    port_keys = ("DC2_HTTPS_PORT", "DC2_POSTGRES_PORT", "DC2_PROCESSING_PORT")
    missing = [key for key in port_keys if key not in env]
    env.update(zip(missing, map(str, free_ports(len(missing), reserved)), strict=True))
    defaults = {
        "DC2_ROOT": str(root),
        "DC2_RUN_DIR": str(directory),
        "COMPOSE_PROJECT_NAME": project,
        "DC2_MINIO_SOURCE": str(root / ".cache/minio" / MINIO_COMMIT),
        "DC2_PROCESSING_IMAGE": f"dc2-processing:{project}",
        "DC2_MEDIA_IMAGE": f"dc2-media:{project}",
        "DC2_MINIO_IMAGE": f"dc2-minio:{project}",
        "MINIO_ROOT_USER": "root-" + hashlib.sha256(project.encode()).hexdigest()[:14],
        "MINIO_REGION": "us-east-1",
        "SOURCE_BUCKET": f"{project}-source",
        "OUTPUT_BUCKET": f"{project}-output",
        "MEDIA_MINIO_ACCESS_KEY": "mm-" + hashlib.sha256(project.encode()).hexdigest()[:14],
        "PROCESSING_MINIO_ACCESS_KEY": "p-" + hashlib.sha256(project.encode()).hexdigest()[:14],
        "CLEANUP_MINIO_ACCESS_KEY": "clean-" + hashlib.sha256(project.encode()).hexdigest()[:14],
        "PROCESSING_QUEUE_NAME": f"{project}-processing",
    }
    secret_keys = (
        "POSTGRES_PASSWORD",
        "MEDIA_MIGRATION_PASSWORD",
        "MEDIA_RUNTIME_PASSWORD",
        "PROCESSING_MIGRATION_PASSWORD",
        "PROCESSING_RUNTIME_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "MEDIA_MINIO_SECRET_KEY",
        "PROCESSING_MINIO_SECRET_KEY",
        "CLEANUP_MINIO_SECRET_KEY",
        "MEDIA_JWT_SECRET",
        "PROCESSING_SERVICE_TOKEN",
        "SOURCE_SERVICE_TOKEN",
    )
    for key in secret_keys:
        if key not in env:
            env[key] = secrets.token_hex(32)
    for key, value in defaults.items():
        env.setdefault(key, value)
    public = f"https://localhost:{env['DC2_HTTPS_PORT']}"
    mappings = {
        "MEDIA_PUBLIC_URL": public,
        "MEDIA_PROCESSING_URL": "http://processing:8000",
        "PROCESSING_MEDIA_URL": "http://media:8000",
        "MEDIA_SOURCE_SERVICE_TOKEN": env["SOURCE_SERVICE_TOKEN"],
        "PROCESSING_SOURCE_SERVICE_TOKEN": env["SOURCE_SERVICE_TOKEN"],
        "MEDIA_PROCESSING_SERVICE_TOKEN": env["PROCESSING_SERVICE_TOKEN"],
        "MEDIA_MINIO_ENDPOINT": "minio:9000",
        "PROCESSING_MINIO_ENDPOINT": "minio:9000",
        "MEDIA_MINIO_PUBLIC_ENDPOINT": public.removeprefix("https://"),
        "MEDIA_MINIO_PUBLIC_USE_SSL": "true",
        "MEDIA_MINIO_USE_SSL": "false",
        "PROCESSING_MINIO_USE_SSL": "false",
        "MEDIA_MINIO_REGION": env["MINIO_REGION"],
        "PROCESSING_MINIO_REGION": env["MINIO_REGION"],
        "MEDIA_MINIO_SOURCE_BUCKET": env["SOURCE_BUCKET"],
        "MEDIA_MINIO_OUTPUT_BUCKET": env["OUTPUT_BUCKET"],
        "PROCESSING_MINIO_OUTPUT_BUCKET": env["OUTPUT_BUCKET"],
        "PROCESSING_REDIS_URL": f"redis://:{quote(env['REDIS_PASSWORD'], safe='')}@redis:6379/0",
    }
    for service in ("MEDIA", "PROCESSING"):
        for purpose, role in (("POSTGRES", "runtime"), ("MIGRATION", "migrator")):
            password = env[f"{service}_{'RUNTIME' if role == 'runtime' else 'MIGRATION'}_PASSWORD"]
            mappings[f"{service}_{purpose}_DSN"] = (
                f"postgresql+asyncpg://{service.lower()}_{role}:{quote(password, safe='')}"
                f"@postgres:5432/{service.lower()}_db"
            )
    for key, value in mappings.items():
        env.setdefault(key, value)
    original = path.read_text() if path.exists() else "# Private run configuration; never commit.\n"
    old = read_env(path)
    additions = "".join(f"{key}={value}\n" for key, value in env.items() if key not in old)
    if additions:
        atomic_write(path, original.rstrip("\n") + "\n" + additions)
    path.chmod(0o600)
    docker_host, docker_config = selected_docker(root)
    state = {
        "docker_host": docker_host,
        "docker_config": docker_config,
        "public_url": public,
        "postgres_port": int(env["DC2_POSTGRES_PORT"]),
        "processing_port": int(env["DC2_PROCESSING_PORT"]),
        "ca_file": str(directory / "tls/ca.crt"),
        "compose_project": env["COMPOSE_PROJECT_NAME"],
        "env_file": str(path),
    }
    atomic_write(directory / "state.json", json.dumps(state, indent=2) + "\n")
    return env, state


def compose(state, *arguments, **kwargs):
    # The generated file must win over any unrelated variables in the caller's shell.
    env = subprocess_env()
    for key in read_env(Path(state["env_file"])):
        env.pop(key, None)
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            state["env_file"],
            "-p",
            state["compose_project"],
            "-f",
            str(COMPOSE),
            *arguments,
        ],
        cwd=ROOT,
        env=env,
        check=True,
        **kwargs,
    )


def fetch_minio():
    """Immutable source transfer only through authenticated gh; cache after success."""
    destination = ROOT / ".cache/minio" / MINIO_COMMIT
    if (destination / ".dc2-source-commit").exists():
        if (destination / ".dc2-source-commit").read_text().strip() != MINIO_COMMIT:
            raise ValueError("MinIO source cache marker differs from the pinned commit")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        archive = Path(tmp) / "source.tar.gz"
        with archive.open("wb") as output:
            run(["gh", "api", f"repos/minio/minio/tarball/{MINIO_COMMIT}"], stdout=output)
        unpacked = Path(tmp) / "unpacked"
        with tarfile.open(archive) as source:
            # data filter rejects absolute/escaping paths and unsafe links.
            source.extractall(unpacked, filter="data")
        directories = list(unpacked.iterdir())
        if len(directories) != 1 or not (directories[0] / "go.mod").exists():
            raise ValueError("Unexpected pinned MinIO source archive")
        if destination.exists():
            raise ValueError(f"Incomplete MinIO cache at {destination}; inspect before removing")
        shutil.move(str(directories[0]), destination)
        atomic_write(destination / ".dc2-source-commit", MINIO_COMMIT + "\n")


def images(state):
    fetch_minio()
    if os.environ.get("DC2_USE_PREBUILT_MINIO") == "1":
        # CI loads a cached build of this exact pinned source before starting
        # the runtime. Refuse an absent or differently sourced image.
        image = read_env(Path(state["env_file"]))["DC2_MINIO_IMAGE"]
        result = run(["docker", "image", "inspect", image], capture_output=True, text=True)
        labels = json.loads(result.stdout)[0]["Config"].get("Labels") or {}
        if labels.get("org.opencontainers.image.revision") != MINIO_COMMIT:
            raise ValueError("Prebuilt MinIO image does not match the pinned source revision")
        print("Reusing verified prebuilt MinIO image; source compilation skipped.")
        compose(state, "build", "processing", "media")
    else:
        compose(state, "build", "minio", "processing", "media")


def smoke(state):
    # Lima forwarding can lag behind container health; poll TCP readiness only.
    deadline = time.monotonic() + 20
    ports = (
        int(state["public_url"].rsplit(":", 1)[1]),
        state["postgres_port"],
        state["processing_port"],
    )
    for port in ports:
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Loopback port {port} did not become reachable") from None
                time.sleep(0.1)
    context = ssl.create_default_context(cafile=state["ca_file"])
    for route in ("/health", "/api/health", "/", "/minio/health/live"):
        with urllib.request.urlopen(
            state["public_url"] + route, context=context, timeout=10
        ) as reply:
            if reply.status != 200:
                raise ValueError(f"Infrastructure route failed: {route}")
    with urllib.request.urlopen(
        f"http://127.0.0.1:{state['processing_port']}/health",
        timeout=10,
    ) as reply:
        if json.load(reply)["status"] != "ok":
            raise ValueError("Processing health failed")
    compose(
        state, "exec", "-T", "redis", "sh", "-c", 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping'
    )
    compose(
        state,
        "exec",
        "-T",
        "postgres",
        "sh",
        "-s",
        input=(ROOT / "deploy/postgres/smoke.sh").read_bytes(),
    )
    compose(state, "run", "--rm", "storage-bootstrap", "python", "/bootstrap/storage.py", "--smoke")
    print("Infrastructure smoke passed (TLS, frontend, Processing DB, Redis, scoped storage).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument(
        "--run-id", required=True, help="isolated stack identity, e.g. foundation-a"
    )
    args = parser.parse_args(argv)
    try:
        env, state = configure(args.run_id)
        if args.action == "env":
            print(json.dumps(state, indent=2))
        elif args.action == "images":
            images(state)
        elif args.action == "up":
            tls = ROOT / "scripts/dev/tls.py"
            if not tls.exists():
                raise ValueError(
                    "Parent TLS helper scripts/dev/tls.py must be integrated before up"
                )
            run([sys.executable, str(tls), "--run-id", args.run_id])
            for name in ("ca.crt", "server.crt", "server.key"):
                if not (Path(env["DC2_RUN_DIR"]) / "tls" / name).is_file():
                    raise ValueError(f"TLS helper did not create {name}")
            info = run(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True)
            capacity = json.loads(info.stdout)
            print(f"Docker: {capacity['NCPU']} CPUs, {capacity['MemTotal'] / 2**30:.2f} GiB")
            images(state)
            compose(state, "up", "-d", "--wait", "--wait-timeout", "180")
            smoke(state)
            print(state["public_url"])
        elif args.action == "down":
            compose(state, "down")  # Intentionally no -v: retain all owned data.
        elif args.action == "logs":
            compose(state, "logs", "--tail", "100")
        elif args.action == "status":
            print(json.dumps(state, indent=2))
            compose(state, "ps", "--all")
        else:
            smoke(state)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Do not print command/env representations: they can contain credentials.
        message = (
            "subprocess failed; see output above"
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        print(f"runtime: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
