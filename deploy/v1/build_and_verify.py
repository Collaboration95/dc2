#!/usr/bin/env python3
"""Build the three V1 images for linux/amd64, verify their contents, exercise their handlers.

LOCAL evidence only. Nothing here talks to AWS: no registry push, no AWS CLI, no credentials.
The Lambda Runtime Interface Emulator (RIE) binary is copied out of the public
`public.ecr.aws/lambda/python` image (a plain public pull) and bind-mounted over the image
ENTRYPOINT, so the exact built image runs its real `python -m awslambdaric <handler>` command.

    python3 deploy/v1/build_and_verify.py            # from the repository root, clean tree
    python3 deploy/v1/build_and_verify.py --no-cache # rebuild every layer

Steps: build, inspect, runtime-content check (deploy/v1/check_runtime.py, hardened flags and
a Lambda-style foreign uid), installed-content policy, RIE handler invocations, worker
fail-fast. The evidence JSON is written to docs/execution/aws/v1/evidence/ and the exit code
is non-zero if any check failed. Config IDs include the build timestamp, so two builds of the
same source differ; the layer digest is the comparable content identity.
"""

import argparse
import hashlib
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = "linux/amd64"
OWNERS = {  # owner -> (runtime kind, check_runtime owner)
    "media": ("lambda-api", "media"),
    "processing": ("lambda-api", "processing"),
    "worker": ("finite-worker", "worker"),
}
RIE_IMAGE = "public.ecr.aws/lambda/python:3.12"
POSTGRES_IMAGE = "postgres:16"
TEMPLATE = ROOT / "deploy/aws/v1/template.json"
INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "deploy/v1/check_runtime.py",
    "deploy/v1/global-bundle.pem",
    "deploy/v1/media.Dockerfile",
    "deploy/v1/processing.Dockerfile",
    "deploy/v1/worker.Dockerfile",
    "deploy/v1/build_and_verify.py",
    "deploy/aws/v1/template.json",
    "scripts/aws/v1/bootstrap.py",
)
# Never acceptable in any V1 image: the legacy queue stack, test/dev tooling, the uv installer.
FORBIDDEN_EVERYWHERE = {
    "redis",
    "rq",
    "fakeredis",
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-timeout",
    "ruff",
    "aiosqlite",
    "jsonschema",
    "playwright",
    "uv",
    "mangum",
    "psycopg2",
    "psycopg2-binary",
    # uvicorn[standard] belongs to the legacy compose stack; the recipes exclude it.
    "uvicorn",
    "uvloop",
    "httptools",
    "watchfiles",
    "websockets",
    "pyyaml",
    "click",
}
# Lambda runtime client only belongs where Lambda invokes the image.
LAMBDA_ONLY = {"awslambdaric", "simplejson", "snapshot-restore-py"}
# Top-level source directories each image may carry under /app (plus the two lock inputs).
APP_ALLOWED = {
    "media": {"contracts", "delivery", "media", "runtime_support"},
    "processing": {"contracts", "delivery", "processing", "runtime_support"},
    "worker": {"contracts", "delivery", "media_engine", "processing", "runtime_support"},
}
LOCK_FILES = {"pyproject.toml", "uv.lock"}
LAMBDA_UID = "993:990"  # Lambda runs the image as an arbitrary unprivileged uid, not USER.
RUN_ENV_BASE = {"AWS_REGION": "ap-southeast-1", "AWS_DEFAULT_REGION": "ap-southeast-1"}

checks: list[dict] = []
EXERCISED: set[tuple[str, str]] = set()  # (owner, handler) pairs actually invoked
FUNCTION_MEMORY: dict[str, int] = {}  # handler -> deployed MemorySize, from the template


def record(name: str, ok: bool, detail=None) -> bool:
    checks.append({"name": name, "ok": bool(ok), **({"detail": detail} if detail else {})})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    return bool(ok)


def run(cmd, *, timeout=900, check=True, input_text=None):
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, input=input_text
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd[:4])} failed ({result.returncode}): {result.stderr[-800:]}"
        )
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker_info() -> dict:
    out = json.loads(run(["docker", "info", "--format", "{{json .}}"]).stdout)
    return {
        "server_version": out.get("ServerVersion"),
        "operating_system": out.get("OperatingSystem"),
        "host_architecture": out.get("Architecture"),
        "context": run(["docker", "context", "show"]).stdout.strip(),
    }


def template_contract():
    """The Lambda handlers/memory and ECS command shapes the deployed template requests."""
    template = json.loads(TEMPLATE.read_text())
    functions, tasks = {}, {}
    for name, resource in template["Resources"].items():
        props = resource.get("Properties", {})
        if resource["Type"] == "AWS::Lambda::Function":
            parameter = props["ImageConfig"]["Command"][0]["Ref"]
            functions[name] = {
                "owner": props["Code"]["ImageUri"]["Ref"].removesuffix("ImageUri").lower(),
                "handler": template["Parameters"][parameter]["Default"],
                "memory_mb": props["MemorySize"],
                "timeout_seconds": props["Timeout"],
            }
        elif resource["Type"] == "AWS::ECS::TaskDefinition":
            container = props["ContainerDefinitions"][0]
            tasks[name] = {
                "owner": container["Image"]["Ref"].removesuffix("ImageUri").lower(),
                "entrypoint": container.get("EntryPoint") or [],
                "command": container.get("Command") or [],
            }
    return functions, tasks


def build(owner: str, tag: str, sha: str, no_cache: bool) -> dict:
    cmd = ["docker", "build", "--platform", PLATFORM, "--build-arg", f"SOURCE_SHA={sha}"]
    if no_cache:
        cmd.append("--no-cache")
    cmd += ["-f", f"deploy/v1/{owner}.Dockerfile", "-t", tag, "."]
    started = time.monotonic()
    result = run(cmd, timeout=3600, check=False)
    elapsed = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
    inspected = {}
    if result.returncode == 0:
        data = json.loads(run(["docker", "image", "inspect", tag]).stdout)[0]
        layers = data["RootFS"]["Layers"]
        inspected = {
            "config_id": data["Id"],
            "size_bytes": data["Size"],
            "os": data["Os"],
            "architecture": data["Architecture"],
            "user": data["Config"]["User"],
            "entrypoint": data["Config"]["Entrypoint"],
            "cmd": data["Config"]["Cmd"],
            "revision_label": data["Config"]["Labels"].get("org.opencontainers.image.revision"),
            "layer_count": len(layers),
            "layers_sha256": hashlib.sha256("\n".join(layers).encode()).hexdigest(),
        }
    return {
        "tag": tag,
        "build_command": cmd,
        "build_exit_code": result.returncode,
        "build_elapsed_seconds": elapsed,
        **inspected,
    }


def docker_run(tag, args, *, entrypoint=None, user=None, network="none", env=None, timeout=120):
    cmd = ["docker", "run", "--rm", "--platform", PLATFORM, "--network", network]
    cmd += ["--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL"]  # noqa: S108
    if user:
        cmd += ["--user", user]
    if entrypoint:
        cmd += ["--entrypoint", entrypoint]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    return run([*cmd, tag, *args], timeout=timeout, check=False)


def verify_contents(owner: str, tag: str, built: dict) -> dict:
    kind, check_owner = OWNERS[owner]
    check_args = ["/opt/check_runtime.py", kind, check_owner]
    summary = {}
    # Exact-image gate with the README flags, then as a Lambda-style foreign uid.
    for label, user in (("image_user", None), ("lambda_uid", LAMBDA_UID)):
        result = docker_run(tag, check_args, entrypoint="python", user=user)
        ok = result.returncode == 0
        record(f"{owner}: check_runtime passes ({label})", ok, result.stderr[-400:])
        if ok and label == "image_user":
            payload = json.loads(result.stdout.splitlines()[-1])
            summary = {
                "runtime_exit_code": 0,
                "runtime_output_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                "runtime_platform": payload["platform"],
                "runtime_contents": payload["runtime_contents"],
                "imported_executables": payload["imports"],
                "installed_package_count": len(payload["installed_packages"]),
                "installed_packages": payload["installed_packages"],
                "binaries": payload["binaries"],
            }
    packages = set(summary.get("installed_packages", {}))
    found = sorted(FORBIDDEN_EVERYWHERE & packages)
    record(f"{owner}: no legacy-queue/dev/test distributions", not found, found)
    if kind == "lambda-api":
        record(f"{owner}: Lambda runtime client present", "awslambdaric" in packages)
        dpkg = docker_run(tag, ["-W", "ffmpeg"], entrypoint="dpkg-query")
        record(f"{owner}: ffmpeg package absent from API image", dpkg.returncode != 0)
        record(
            f"{owner}: no ffmpeg/ffprobe binary on PATH",
            not summary.get("binaries")
            and summary.get("runtime_contents", {}).get("ffmpeg") is False,
        )
    else:
        leaked = sorted(LAMBDA_ONLY & packages)
        record(f"{owner}: no Lambda-only runtime client in worker", not leaked, leaked)
        record(
            "worker: ffmpeg and ffprobe installed",
            set(summary.get("binaries", {})) == {"ffmpeg", "ffprobe"},
        )
    listing = docker_run(tag, ["-1", "/app"], entrypoint="ls")
    entries = set(listing.stdout.split())
    extra = sorted(entries - APP_ALLOWED[owner] - LOCK_FILES)
    missing = sorted(APP_ALLOWED[owner] - entries)
    record(
        f"{owner}: /app carries exactly its owning source",
        not extra and not missing,
        [extra, missing],
    )
    summary["app_entries"] = sorted(entries)
    record(
        f"{owner}: runs as non-root image user", built.get("user") == "flickpond", built.get("user")
    )
    record(
        f"{owner}: image is {PLATFORM}",
        (built.get("os"), built.get("architecture")) == ("linux", "amd64"),
    )
    record(
        f"{owner}: revision label equals source SHA",
        built.get("revision_label") == built["source_sha"],
    )
    return summary


# --- Lambda Runtime Interface Emulator -------------------------------------------------------


def extract_rie(workdir: Path) -> dict:
    run(["docker", "pull", "--platform", PLATFORM, RIE_IMAGE], timeout=900)
    info = json.loads(run(["docker", "image", "inspect", RIE_IMAGE]).stdout)[0]
    name = f"dc2-v1-rie-src-{os.getpid()}"
    run(["docker", "create", "--name", name, "--platform", PLATFORM, RIE_IMAGE])
    try:
        target = workdir / "aws-lambda-rie"
        run(["docker", "cp", f"{name}:/usr/local/bin/aws-lambda-rie", str(target)])
    finally:
        run(["docker", "rm", "-f", name], check=False)
    target.chmod(0o755)
    return {
        "image": RIE_IMAGE,
        "repo_digest": (info.get("RepoDigests") or [None])[0],
        "binary_sha256": sha256(target),
    }


class Rie:
    """One image container running one Lambda handler behind the RIE (bridge net, loopback port)."""

    def __init__(self, tag, handler, rie_dir, *, env=None, network=None, memory_mb=None):
        self.name = f"dc2-v1-rie-{os.getpid()}-{secrets.token_hex(3)}"
        cmd = ["docker", "run", "-d", "--name", self.name, "--platform", PLATFORM]
        cmd += ["--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", "--user", LAMBDA_UID]  # noqa: S108
        cmd += ["-v", f"{rie_dir}:/rie:ro", "-p", "127.0.0.1::8080"]
        if network:
            cmd += ["--network", network]
        if memory_mb:  # The deployed function's MemorySize, with swap disabled.
            cmd += ["--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m"]
        for key, value in {**RUN_ENV_BASE, **(env or {})}.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += ["--entrypoint", "/rie/aws-lambda-rie", tag, "python", "-m", "awslambdaric", handler]
        run(cmd)
        port = run(["docker", "port", self.name, "8080/tcp"]).stdout.split(":")[-1].strip()
        self.url = f"http://127.0.0.1:{port}/2015-03-31/functions/function/invocations"

    def invoke(self, event, timeout=120):
        request = urllib.request.Request(self.url, data=json.dumps(event).encode(), method="POST")
        started = time.monotonic()
        # Docker's port proxy accepts connections before the RIE listens; the emulator has not
        # seen the request until it answers, so retrying a refused/closed connection is safe.
        for attempt in range(40):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                    raw = response.read().decode()
                    error = response.headers.get("X-Amz-Function-Error")
                break
            except urllib.error.HTTPError as exc:
                raw, error = exc.read().decode(), f"http-{exc.code}"
                break
            except (urllib.error.URLError, ConnectionError, http.client.RemoteDisconnected):
                if attempt == 39:
                    raise
                time.sleep(0.5)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw
        if isinstance(body, dict) and {"errorType", "errorMessage"} <= body.keys():
            # The RIE reports an unhandled handler exception as a 200 body; keep it compact.
            error = body["errorType"]
            body = {"errorType": error, "errorMessage": body["errorMessage"]}
        return {
            "body": body,
            "function_error": error,
            "seconds": round(time.monotonic() - started, 2),
        }

    def close(self):
        run(["docker", "rm", "-f", self.name], check=False)


def api_event(service, method, path, *, cookies=None):
    prefix = {"media": "/api/media", "processing": "/api/processing"}[service]
    event = {
        "version": "2.0",
        "routeKey": f"{method} {prefix}{path}",
        "rawPath": prefix + path,
        "rawQueryString": "",
        "headers": {"host": "example.invalid"},
        "requestContext": {
            "http": {"method": method, "path": prefix + path, "sourceIp": "192.0.2.1"},
            "requestId": "local-rie",
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }
    if cookies:
        event["cookies"] = cookies
    return event


def sqs_event(body):
    return {
        "Records": [
            {
                "messageId": "00000000-0000-4000-8000-000000000001",
                "receiptHandle": "local",
                "body": body,
                "attributes": {"ApproximateReceiveCount": "1"},
                "eventSource": "aws:sqs",
            }
        ]
    }


def unreachable_dsn(owner):
    return f"postgresql://{owner}_runtime:unused@127.0.0.1:1/{owner}_db"


def status(result):
    body = result["body"]
    return body.get("statusCode") if isinstance(body, dict) else None


def exercise(owner, handler, tag, rie_dir, env, cases, network=None):
    """Start one handler under RIE and run (name, event, predicate) cases; record each."""
    observed = {}
    container = None
    EXERCISED.add((owner, handler))
    try:
        container = Rie(
            tag, handler, rie_dir, env=env, network=network, memory_mb=FUNCTION_MEMORY.get(handler)
        )
        for name, event, predicate in cases:
            result = container.invoke(event)
            ok = bool(predicate(result))
            observed[name] = {
                "function_error": result["function_error"],
                "seconds": result["seconds"],
                "response": result["body"] if len(json.dumps(result["body"])) < 600 else "(large)",
            }
            record(f"{owner}: RIE {handler}: {name}", ok, json.dumps(result)[:500])
    except Exception as exc:  # noqa: BLE001 - a harness failure is a failed check, not a crash
        record(f"{owner}: RIE {handler}: harness", False, str(exc)[:500])
    finally:
        if container:
            container.close()
    return {"handler": handler, "cases": observed}


def health_ok(service):
    def check(result):
        body = result["body"]
        if status(result) != 200:
            return False
        payload = json.loads(body["body"])
        return payload.get("status") == "ok" and payload.get("service") == service

    return check


def database_down(result):
    """Finite, never a success, and the DSN password never appears in the response.

    SQS handlers must report per-item failure (so messages are retried); scheduled/event
    handlers must raise so Lambda retries and alarms, rather than return a green result.
    """
    body = result["body"]
    visible = (isinstance(body, dict) and body.get("batchItemFailures")) or (
        result["function_error"] in {"ConnectionRefusedError", "OSError", "TimeoutError"}
    )
    return bool(visible) and result["seconds"] < 60 and "unused" not in json.dumps(body)


LOCAL_JWT_SECRET = "local-rie-" + "0" * 32  # Settings requires at least 32 bytes.
ISSUE_TOKEN = (
    "import uuid; from media.config import get_settings; "
    "from media.services.security import issue_token; "
    "print(issue_token(uuid.uuid4(), get_settings()))"
)


def rie_media(tag, rie_dir):
    env = {"MEDIA_POSTGRES_DSN": unreachable_dsn("media"), "MEDIA_JWT_SECRET": LOCAL_JWT_SECRET}
    api = exercise(
        "media",
        "media.lambda_handler.handler",
        tag,
        rie_dir,
        env,
        [
            (
                "GET /health through payload v2 is 200 ok",
                api_event("media", "GET", "/health"),
                health_ok("media"),
            ),
            (
                "protected route without trusted actor is 401",
                api_event("media", "GET", "/jobs"),
                lambda r: status(r) == 401,
            ),
            (
                "path outside the service prefix is 404",
                {**api_event("media", "GET", "/health"), "rawPath": "/health"},
                lambda r: status(r) == 404,
            ),
        ],
    )
    cookie = {"cookies": ["access_token=not-a-token"]}
    issued = docker_run(
        tag,
        ["-c", ISSUE_TOKEN],
        entrypoint="python",
        env={"MEDIA_POSTGRES_DSN": unreachable_dsn("media"), "MEDIA_JWT_SECRET": LOCAL_JWT_SECRET},
    )
    record("media: image can issue a session token with its own code", issued.returncode == 0)
    signed = {"cookies": [f"access_token={issued.stdout.strip()}"]}
    authorizer = exercise(
        "media",
        "media.lambda_handler.authorizer",
        tag,
        rie_dir,
        env,
        [
            (
                "request without a session cookie is denied",
                api_event("media", "GET", "/jobs"),
                lambda r: r["body"] == {"isAuthorized": False},
            ),
            (
                "forged session cookie is denied",
                api_event("media", "GET", "/jobs", cookies=cookie["cookies"]),
                lambda r: r["body"] == {"isAuthorized": False},
            ),
            (
                "validly signed session is denied while its database is unreachable",
                api_event("media", "GET", "/jobs", cookies=signed["cookies"]),
                lambda r: r["body"] == {"isAuthorized": False} and r["seconds"] < 60,
            ),
            (
                "non payload-v2 event fails closed",
                {"hello": "world"},
                lambda r: r["body"] == {"isAuthorized": False},
            ),
        ],
    )
    results = exercise(
        "media",
        "media.handlers.result_handler",
        tag,
        rie_dir,
        env,
        [
            (
                "undeliverable SQS message is a batch item failure",
                sqs_event("{not json"),
                database_down,
            )
        ],
    )
    repair = exercise(
        "media",
        "media.handlers.repair_handler",
        tag,
        rie_dir,
        env,
        [
            (
                "repair without a database raises a retryable connection error",
                {"source": "aws.events"},
                database_down,
            )
        ],
    )
    return {"api": api, "authorizer": authorizer, "results": results, "repair": repair}


def ready_false(result):
    return result["body"] == {
        "service": "processing",
        "ready": False,
        "error": "database unavailable",
    }


def ready_true(result):
    return result["body"] == {"service": "processing", "ready": True}


def rie_processing(tag, rie_dir, postgres_network):
    base = {"PROCESSING_POSTGRES_DSN": unreachable_dsn("processing")}
    ready = {"dc2_operation": "ready"}
    api = exercise(
        "processing",
        "processing.lambda_handler.handler",
        tag,
        rie_dir,
        base,
        [
            (
                "GET /health through payload v2 is 200 ok",
                api_event("processing", "GET", "/health"),
                health_ok("processing"),
            ),
            (
                "protected route without trusted actor is 401",
                api_event("processing", "GET", "/jobs"),
                lambda r: status(r) == 401,
            ),
            ("direct ready probe without a database is a clean not-ready", ready, ready_false),
            (
                "ready probe shape is not reachable through Gateway events",
                {**ready, "version": "2.0"},
                lambda r: status(r) in (400, 401, 404),
            ),
        ],
    )
    control = {}
    for name, handler, event in (
        ("command", "processing.handlers.command_handler", sqs_event("{not json")),
        ("repair", "processing.handlers.repair_handler", {"source": "aws.events"}),
        ("ecs", "processing.handlers.ecs_handler", {"source": "aws.ecs", "detail": {}}),
        ("s3", "processing.handlers.s3_handler", {"Records": []}),
    ):
        control[name] = exercise(
            "processing",
            handler,
            tag,
            rie_dir,
            base,
            [
                (
                    "without a database: batch item failure or retryable connection error",
                    event,
                    database_down,
                )
            ],
        )
    with_db = None
    if postgres_network:
        live = {
            "PROCESSING_POSTGRES_DSN": postgres_network["dsn"],
            "PROCESSING_DATABASE_TLS": "false",
        }
        with_db = exercise(
            "processing",
            "processing.lambda_handler.handler",
            tag,
            rie_dir,
            live,
            [("direct ready probe against throwaway PostgreSQL is ready", ready, ready_true)],
            network=postgres_network["network"],
        )
    return {"api": api, "control": control, "ready_with_postgres": with_db}


class ThrowawayPostgres:
    """Unique network + postgres container, removed on exit; only objects created here."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.suffix = f"{os.getpid()}-{secrets.token_hex(3)}"
        self.info = None

    def __enter__(self):
        if not self.enabled:
            return None
        network, name = f"dc2-v1-verify-net-{self.suffix}", f"dc2-v1-verify-pg-{self.suffix}"
        self.network, self.name = network, name
        password = secrets.token_hex(8)  # throwaway, never recorded
        try:
            run(["docker", "network", "create", network])
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    network,
                    "-e",
                    f"POSTGRES_PASSWORD={password}",
                    POSTGRES_IMAGE,
                ]
            )
            for _ in range(60):
                if (
                    run(
                        ["docker", "exec", name, "pg_isready", "-U", "postgres"], check=False
                    ).returncode
                    == 0
                ):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("throwaway PostgreSQL did not become ready")
            time.sleep(2)  # pg_isready answers during the init-time restart
            self.info = {
                "network": network,
                "container": name,
                "dsn": f"postgresql://postgres:{password}@{name}:5432/postgres",
            }
        except Exception as exc:  # noqa: BLE001
            record("throwaway PostgreSQL started", False, str(exc)[:300])
            self.__exit__()
        return self.info

    def __exit__(self, *exc):
        if self.enabled and hasattr(self, "name"):
            run(["docker", "rm", "-f", self.name], check=False)
            run(["docker", "network", "rm", self.network], check=False)


def pg_sql(pg, sql, database="postgres"):
    command = ["docker", "exec", pg["container"], "psql", "-U", "postgres", "-d", database]
    return run([*command, "-tAc", sql], check=False)


def task_shapes(images, tasks, pg):
    """Run the ECS entryPoint+command shapes the template pins, against the owning image."""
    observed = {}
    for name, task in tasks.items():
        owner = task["owner"]
        if owner not in images or images[owner]["build_exit_code"] != 0:
            continue
        tag = images[owner]["tag"]
        argv = [*task["entrypoint"], *task["command"]]
        if name == "WorkerTaskDefinition":
            result = docker_run(tag, [*argv[1:], "--help"], entrypoint=argv[0])
            ok = result.returncode == 0 and "--deadline-epoch" in result.stdout
            detail = result.stderr[-300:]
        elif name.endswith("MigrationTaskDefinition"):
            domain = owner
            if pg:
                pg_sql(pg, f"CREATE DATABASE {domain}_db")
                dsn = pg["dsn"].rsplit("/", 1)[0] + f"/{domain}_db"
                env = {
                    "MEDIA_MIGRATION_DSN" if domain == "media" else "PROCESSING_POSTGRES_DSN": dsn
                }
                result = docker_run(
                    tag, argv[1:], entrypoint=argv[0], env=env, network=pg["network"], timeout=300
                )
                version = pg_sql(pg, "SELECT version_num FROM alembic_version", f"{domain}_db")
                ok = result.returncode == 0 and bool(version.stdout.strip())
                detail = (result.stderr or version.stderr)[-300:]
                observed[name] = {"alembic_head": version.stdout.strip()}
            else:
                heads = [*argv[1:-2], "heads"]
                env = {"PROCESSING_POSTGRES_DSN": unreachable_dsn("processing")}
                result = docker_run(tag, heads, entrypoint=argv[0], env=env)
                ok, detail = result.returncode == 0, result.stderr[-300:]
        elif name == "BootstrapTaskDefinition":
            result = docker_run(tag, argv[1:], entrypoint=argv[0])
            out = result.stdout + result.stderr
            ok = result.returncode == 1 and "DB bootstrap failed" in out and "Traceback" not in out
            detail = out[-300:]
            for other in ("media", "processing"):
                if other in images and images[other]["build_exit_code"] == 0:
                    absent = docker_run(
                        images[other]["tag"],
                        ["-e", "/opt/db-bootstrap.py"],
                        entrypoint="/usr/bin/test",
                    )  # noqa: E501
                    record(
                        f"{other}: image does not carry the DB bootstrap script",
                        absent.returncode != 0,
                    )
        else:
            continue
        observed.setdefault(name, {}).update(
            {"image": owner, "entrypoint": task["entrypoint"], "command": task["command"], "ok": ok}
        )
        record(f"{owner}: ECS shape {name} runs from the template entryPoint/command", ok, detail)
    return observed


# --- finite worker -----------------------------------------------------------------------------


def worker_failfast(tag):
    results = {}
    soon = str(time.time() + 120)
    base_args = ["--deadline-epoch", soon, "--name", "local-verify", "--max-empty-polls", "1"]
    dsn = {"PROCESSING_POSTGRES_DSN": unreachable_dsn("processing")}
    cases = (
        ("no configuration at all", base_args, {}, {1}),
        ("database configured, no work queue", base_args, dsn, {1}),
        ("expired deadline", ["--deadline-epoch", "1", "--name", "x"], dsn, {124}),
        ("--help", ["--help"], {}, {0}),
    )
    for name, args, env, allowed in cases:
        started = time.monotonic()
        try:
            result = docker_run(tag, args, env=env, timeout=60)
            code, out = result.returncode, (result.stdout + result.stderr)
        except subprocess.TimeoutExpired:
            code, out = "timeout", ""
        seconds = round(time.monotonic() - started, 1)
        leaks = [s for s in ("unused", "127.0.0.1", "Traceback") if s in out]
        ok = code in allowed and seconds < 45 and not leaks
        results[name] = {
            "exit_code": code,
            "seconds": seconds,
            "output_bytes": len(out),
            "output_head": out[:200],
        }
        record(
            f"worker: fail-fast entrypoint: {name} exits {sorted(allowed)}",
            ok,
            f"{code} in {seconds}s leaks={leaks}",
        )
    return results


# --- main --------------------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-cache", action="store_true", help="rebuild every layer")
    parser.add_argument("--skip-build", action="store_true", help="reuse existing tagged images")
    parser.add_argument("--no-postgres", action="store_true", help="skip the throwaway PostgreSQL")
    parser.add_argument("--allow-dirty", action="store_true", help="permit uncommitted changes")
    parser.add_argument("--only", choices=sorted(OWNERS), action="append", help="limit owners")
    parser.add_argument("--out", type=Path, help="evidence JSON path")
    args = parser.parse_args()

    sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())
    if dirty and not args.allow_dirty:
        sys.exit("Working tree is dirty: the image label would not match the commit. Commit first.")
    short = sha[:12]
    out = args.out or ROOT / f"docs/execution/aws/v1/evidence/local-images-{short}.json"
    owners = args.only or list(OWNERS)
    started = datetime.now(UTC)

    images = {}
    for owner in owners:
        tag = f"dc2-v1-{owner}:local-{short}"
        if args.skip_build:
            built = build_from_existing(owner, tag, sha)
        else:
            built = build(owner, tag, sha, args.no_cache)
        built["source_sha"] = sha
        record(f"{owner}: image builds", built["build_exit_code"] == 0)
        images[owner] = built
        if built["build_exit_code"] == 0:
            built.update(verify_contents(owner, tag, built))

    functions, tasks = template_contract()
    FUNCTION_MEMORY.update({f["handler"]: f["memory_mb"] for f in functions.values()})
    built_ok = {o for o in owners if images[o]["build_exit_code"] == 0}
    work = Path(tempfile.mkdtemp(prefix="dc2-v1-rie-"))
    rie = {}
    task_results = {}
    try:
        with ThrowawayPostgres(not args.no_postgres) as pg:
            if {"media", "processing"} & built_ok:
                rie["emulator"] = extract_rie(work)
                record("RIE binary extracted from public Lambda Python image", True)
            if "media" in built_ok:
                images["media"]["rie"] = rie_media(images["media"]["tag"], work)
            if "processing" in built_ok:
                images["processing"]["rie"] = rie_processing(images["processing"]["tag"], work, pg)
            task_results = task_shapes(images, tasks, pg)
        if "worker" in built_ok:
            images["worker"]["entrypoint_failfast"] = worker_failfast(images["worker"]["tag"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for owner in sorted({"media", "processing"} & built_ok):
        wanted = {f["handler"] for f in functions.values() if f["owner"] == owner}
        exercised = {h for o, h in EXERCISED if o == owner}
        record(
            f"{owner}: every template Lambda handler was invoked under RIE",
            wanted == exercised,
            [sorted(wanted - exercised), sorted(exercised - wanted)],
        )

    failures = [c for c in checks if not c["ok"]]
    evidence = {
        "schema_version": 2,
        "scope": "LOCAL exact-image packaging, content and Lambda-RIE handler proof only; "
        "NOT cloud evidence",
        "status": "LOCAL_ARTIFACT_PASS" if not failures else "LOCAL_ARTIFACT_FAIL",
        "source_sha": sha,
        "working_tree_dirty": dirty,
        "platform": PLATFORM,
        "generated_utc": started.isoformat(timespec="seconds"),
        "host_python": sys.version.split()[0],
        "docker": docker_info(),
        "input_sha256": {name: sha256(ROOT / name) for name in INPUTS},
        "lambda_runtime_interface_emulator": rie.get("emulator"),
        "template_functions": functions,
        "ecs_task_shapes": task_results,
        "images": images,
        "checks": checks,
        "promotion_eligible": False,
        "scan": "NOT_RUN",
        "registry_manifest_receipt": "NOT_RUN",
        "aws": "NOT_RUN",
        "limitations": [
            "Local config IDs are not registry digests and embed the build timestamp",
            "No vulnerability scan performed",
            "No registry manifest/publication proof; no AWS call of any kind",
            "RIE emulates the invoke protocol only: no IAM, VPC, API Gateway, SQS or RDS TLS",
            "Handlers ran without a reachable database. Only the Processing ready probe and "
            "the owner migrations used a throwaway PostgreSQL, with TLS disabled (no RDS CA)",
            "Host runs amd64 images under emulation when the host is ARM; no performance claim",
        ],
        "failures": [c["name"] for c in failures],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed; evidence: {out}")
    sys.exit(1 if failures else 0)


def build_from_existing(owner, tag, sha):
    data = json.loads(run(["docker", "image", "inspect", tag]).stdout)[0]
    layers = data["RootFS"]["Layers"]
    return {
        "tag": tag,
        "build_command": None,
        "build_exit_code": 0,
        "build_elapsed_seconds": 0,
        "config_id": data["Id"],
        "size_bytes": data["Size"],
        "os": data["Os"],
        "architecture": data["Architecture"],
        "user": data["Config"]["User"],
        "entrypoint": data["Config"]["Entrypoint"],
        "cmd": data["Config"]["Cmd"],
        "revision_label": data["Config"]["Labels"].get("org.opencontainers.image.revision"),
        "layer_count": len(layers),
        "layers_sha256": hashlib.sha256("\n".join(layers).encode()).hexdigest(),
    }


if __name__ == "__main__":
    main()
