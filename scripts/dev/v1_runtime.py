"""Isolated Redis-free local V1 dependencies; never discovers AWS credentials."""

import argparse
import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/v1-local/compose.yml"


def run(argv, **kwargs):
    return subprocess.run(argv, cwd=ROOT, check=True, text=True, **kwargs)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def directory(run_id):
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,47}", run_id) or run_id in {
        "local",
        "final-measurements",
    }:
        raise ValueError("Choose a unique V1 run ID (3..48 lowercase letters/digits/hyphens)")
    path = ROOT / ".cache/v1-runtime" / run_id
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def load(run_id):
    explicit = os.environ.get("V1_RUNTIME_CONFIG")
    path = Path(explicit).resolve() if explicit else directory(run_id) / "runtime.json"
    data = json.loads(path.read_text())
    expected = Path(data.get("root", "/invalid")) / ".cache/v1-runtime" / run_id / "runtime.json"
    if (
        data.get("run_id") != run_id
        or data.get("project") != "dc2-v1-" + run_id
        or path.resolve() != expected.resolve()
        or (not explicit and data.get("root") != str(ROOT))
    ):
        raise ValueError("Runtime ownership mismatch")
    return data


def compose(data, *args):
    env = dict(
        os.environ,
        V1_POSTGRES_PORT=str(data["postgres_port"]),
        V1_TLS_DIR=str(directory(data["run_id"]) / "tls"),
    )
    # Explicit selected context; never change the user's active Docker context.
    return run(
        [
            "docker",
            "--context",
            data["docker_context"],
            "compose",
            "--project-name",
            data["project"],
            "--file",
            str(COMPOSE),
            *args,
        ],
        env=env,
    )


def moto_python():
    selected = os.environ.get("V1_MOTO_PYTHON")
    if selected:
        # Not resolve(): a venv's python is a symlink to the base interpreter, and following
        # it drops the venv's site-packages, so Moto would fail to import in a fresh venv.
        return os.path.abspath(selected)
    common = Path(run(["git", "rev-parse", "--git-common-dir"], capture_output=True).stdout.strip())
    repo = (ROOT / common).resolve().parent
    executable = repo / ".cache/aws-test-tools/bin/python"
    if not executable.exists():
        raise ValueError("Set V1_MOTO_PYTHON to a Python environment with moto[server]==5.2.4")
    return str(executable)


def start_moto(data, path):
    command = [moto_python(), "-m", "moto.server", "-H", "127.0.0.1", "-p", str(data["moto_port"])]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_DEFAULT_REGION": "ap-southeast-1",
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    }
    with (path / "moto-private.log").open("a") as log:
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True
        )
    data["moto_pid"] = process.pid
    data["moto_command"] = " ".join(command)
    save(path / "runtime.json", data)
    end = time.monotonic() + 20
    while time.monotonic() < end:
        if process.poll() is not None:
            # The Moto log holds only local emulator output (no application data).
            tail = (path / "moto-private.log").read_text()[-1500:]
            raise RuntimeError("Moto exited; inspect the private runtime log. Tail:\n" + tail)
        try:
            with urllib.request.urlopen(data["endpoint_url"] + "/moto-api/", timeout=1) as reply:
                if reply.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Moto readiness timed out; partial runtime retained")


def stop_moto(data):
    pid = data.get("moto_pid")
    if not pid:
        return
    result = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True)
    if result.returncode:
        return
    # Never signal a reused PID or a pre-existing server.
    if result.stdout.strip() != data["moto_command"]:
        raise RuntimeError("Moto PID identity changed; refusing to signal it")
    os.kill(pid, signal.SIGTERM)


def local_tls(path):
    """Create scoped PostgreSQL TLS material; no system trust installation."""
    tls = path / "tls"
    tls.mkdir(mode=0o700, exist_ok=True)
    cert, key = tls / "server.crt", tls / "server.key"
    if cert.exists() and key.exists():
        return
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "30",
            "-subj",
            "/CN=dc2-v1-local-postgres",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:postgres",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        capture_output=True,
        timeout=10,
    )
    key.chmod(0o600)


def up(run_id):
    path = directory(run_id)
    if (path / "runtime.json").exists():
        data = load(run_id)
        if data["state"] != "down":
            raise ValueError("Run ID active/partial; use v1-status/down or a fresh unique ID")
        data["state"] = "starting"
    else:
        context = run(["docker", "context", "show"], capture_output=True).stdout.strip()
        run(
            ["docker", "--context", context, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=30,
        )
        data = {
            "version": 1,
            "run_id": run_id,
            "root": str(ROOT),
            "project": "dc2-v1-" + run_id,
            "docker_context": context,
            "postgres_port": free_port(),
            "moto_port": free_port(),
            "state": "starting",
        }
        data["endpoint_url"] = "http://127.0.0.1:" + str(data["moto_port"])
    save(path / "runtime.json", data)
    local_tls(path)
    # Partial failures retain the exact IDs and volumes for deliberate down/review.
    compose(data, "up", "--detach", "--wait", "--wait-timeout", "90", "postgres")
    start_moto(data, path)
    from scripts.dev.v1_verify import provision_local_objects

    data["resources"] = provision_local_objects(data)
    data["state"] = "running"
    save(path / "runtime.json", data)
    return {
        "run_id": run_id,
        "project": data["project"],
        "state": "running",
        "postgres": "real PostgreSQL 16",
        "s3_sqs": "Moto emulation",
        "redis": "absent",
        "cloud_acceptance": "NOT_RUN",
    }


def down(run_id, *, delete_data=False):
    data = load(run_id)
    if data["root"] != str(ROOT):
        raise ValueError("Teardown must run from the owning runtime checkout")
    stop_moto(data)
    compose(data, "down", *(["--volumes"] if delete_data else []))
    data.update(state="down", moto_pid=None, retained_data=not delete_data)
    save(directory(run_id) / "runtime.json", data)
    return {
        "state": "down",
        "volumes": "deleted" if delete_data else "retained",
        "private_logs_and_evidence": "retained",
        "moto_s3_sqs": "ephemeral; discarded on server stop (not a durable AWS receipt)",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "status", "verify"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--flow", choices=["a", "b", "c", "all"], default="all")
    parser.add_argument("--delete-data", action="store_true")
    args = parser.parse_args()
    path = directory(args.run_id)
    with (path / "operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "up":
            result = up(args.run_id)
        elif args.action == "down":
            result = down(args.run_id, delete_data=args.delete_data)
        elif args.action == "verify":
            from scripts.dev.v1_verify import verify

            result = verify(args.run_id, args.flow)
        else:
            data = load(args.run_id)
            result = {k: data[k] for k in ["run_id", "project", "state", "docker_context"]}
            compose(data, "ps")
        print(json.dumps(result, indent=2))
        if result.get("status") in {"FAIL", "INCOMPLETE"}:
            sys.exit(1)


if __name__ == "__main__":
    main()
