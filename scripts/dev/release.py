#!/usr/bin/env python3
"""Independent LOCAL Processing release/rollback; no registry or cloud operations."""

import argparse
import contextlib
import fcntl
import hashlib
import http.cookiejar
import json
import os
import re
import secrets
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

try:
    from scripts.dev import runtime
except ModuleNotFoundError:  # Direct script invocation, as used by Make.
    import runtime

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("processing", "worker", "processing-recovery")
IMAGE_SERVICES = (*SERVICES, "processing-migrate")
PRODUCT_PATHS = (
    "app",
    "media",
    "processing",
    "media_engine",
    "publisher",
    "frontend",
    "tests",
    "scripts/dev",
    "deploy",
    "compose",
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".dockerignore",
)
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")
TRIVY_VERSION = "0.75.0"
TRIVY_ARCHIVE_SHA256 = "4a77108cccf8e55c8d6823e1e759939a622277e66cd0daa3c1fc621ed69e4568"
RELEASE_SECONDS = 600
ROLLBACK_SECONDS = 300
DRAIN_SECONDS = 300
INJECTION = "uvicorn-startup-exit42"
INJECTION_MARKER = "dc2.release.injection=" + INJECTION


class ReleaseError(Exception):
    """A safe, fixed diagnostic; never includes child output or HTTP capabilities."""


def utcnow():
    return datetime.now(UTC).isoformat()


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_text(path, content):
    """Replace and fsync both file and directory, keeping all run files private."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def require_image(value):
    if not isinstance(value, str) or not IMAGE_ID.fullmatch(value):
        raise ReleaseError("expected immutable local Docker image ID sha256:<64 hex>")
    return value


def override(image):
    require_image(image)
    return {"services": {name: {"image": image, "pull_policy": "never"} for name in IMAGE_SERVICES}}


def clean_scan(report, image):
    """Bind the scanner's artifact metadata and results to the inspected local ID."""
    require_image(image)
    if report.get("Metadata", {}).get("ImageID") != image:
        raise ReleaseError("Trivy report does not identify the exact image")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ReleaseError("Trivy returned no package scan results")
    if not any(result.get("Class") == "os-pkgs" for result in results):
        raise ReleaseError("Trivy did not scan operating system packages")
    vulnerabilities = [v for result in results for v in result.get("Vulnerabilities", []) or []]
    blocked = [
        v
        for v in vulnerabilities
        if v.get("Severity") in ("HIGH", "CRITICAL") and v.get("FixedVersion")
    ]
    if blocked:
        raise ReleaseError("Trivy found fixable HIGH/CRITICAL vulnerabilities")
    return {
        "image_id": image,
        "version": TRIVY_VERSION,
        "archive_sha256": TRIVY_ARCHIVE_SHA256,
        "fixable_high_critical": 0,
        "report_sha256": hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
    }


def terminal_attempt(row):
    if not row["finished"]:
        return False
    if row["state"] == "succeeded":
        return row["job_status"] == "done"
    if row["state"] in ("failed", "abandoned"):
        if not row["attempt_error"] or not row["current_attempt_id"]:
            return False
        # A supported retry creates a new Attempt and clears the Job error.
        # The old Attempt's durable failure remains valid after that retry.
        return row["current_attempt_id"] != row["id"] or (
            row["job_status"] == "failed" and row["has_error"]
        )
    return row["state"] == "cancelled" and row["deleted"]


class Runner:
    def __init__(self, run_id, *, root=ROOT):
        self.root = root
        self.private_env, self.state = runtime.configure(run_id, root)
        self.directory = Path(self.state["env_file"]).parent / "releases"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.journal_path = self.directory / "journal.json"
        self.persisted = self.directory.parent / "release.override.json"
        self.journal = (
            json.loads(self.journal_path.read_text())
            if self.journal_path.exists()
            else {
                "schema": 1,
                "tested_images": {},
                "current": None,
                "previous": None,
                "pending": None,
                "operations": [],
            }
        )
        self.operation = None
        self.deadline = 0

    @contextlib.contextmanager
    def locked(self):
        path = self.directory / "runner.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ReleaseError("another release runner owns this run-id") from None
            # Reload after taking the lock: another runner may have just finished.
            if self.journal_path.exists():
                self.journal = json.loads(self.journal_path.read_text())
            yield
        finally:
            os.close(fd)

    def save(self):
        atomic_json(self.journal_path, self.journal)
        if self.operation:
            atomic_json(self.directory / (self.operation["id"] + ".json"), self.operation)

    def begin(self, action, seconds):
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.operation = {
            "id": uuid.uuid4().hex,
            "action": action,
            "scope": "local",
            "started_at": utcnow(),
            "status": "running",
            "steps": [],
            "limit_seconds": seconds,
        }
        self.journal["operations"].append(self.operation)
        self.save()

    def finish(self, status):
        self.operation.update(
            status=status,
            finished_at=utcnow(),
            elapsed_seconds=round(time.monotonic() - self.started, 3),
        )
        self.save()

    def remaining(self, cap=None):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise ReleaseError("overall operation deadline exceeded")
        return min(seconds, cap) if cap else seconds

    def step(self, name, function):
        record = {"name": name, "started_at": utcnow(), "status": "running"}
        self.operation["steps"].append(record)
        self.save()
        started = time.monotonic()
        print(f"local release: {name}", flush=True)
        try:
            value = function()
            record["status"] = "passed"
            return value
        except Exception as exc:
            # Only these diagnostics are safe to store; arbitrary exceptions may
            # contain a DSN, signed URL, cookie, container environment or command.
            record["status"] = "failed"
            record["error"] = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
            raise
        finally:
            record.update(
                finished_at=utcnow(), elapsed_seconds=round(time.monotonic() - started, 3)
            )
            self.save()

    def command(self, args, *, input=None, cap=None, merge_stderr=False):
        """Capture child output in memory; no raw output/credentials in the journal."""
        timeout = self.remaining(cap)
        record = {"argv": args, "started_at": utcnow(), "status": "running"}
        self.operation.setdefault("command_evidence", []).append(record)
        self.save()
        try:
            process = subprocess.Popen(
                args,
                cwd=self.root,
                env=runtime.subprocess_env(),
                stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(input=input, timeout=timeout)
            except subprocess.TimeoutExpired:
                # make launches grandchildren; killing only make leaves tests
                # alive holding our pipes. Kill the whole group in bounded time.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=2)
                record["timed_out"] = True
                raise ReleaseError(f"{Path(args[0]).name} exceeded its command deadline") from None
            stderr = stderr or ""
            record.update(
                exit_code=process.returncode,
                stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest(),
                stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest(),
                stdin_sha256=hashlib.sha256(input.encode()).hexdigest() if input else None,
            )
            if process.returncode:
                raise ReleaseError(f"{Path(args[0]).name} exited {process.returncode}")
            record["status"] = "passed"
            return stdout
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            raise
        finally:
            record["finished_at"] = utcnow()
            self.save()

    def compose(self, *args, image=None, cap=None, input=None):
        prefix = []
        # Current runtime doesn't load persisted releases yet. Explicitly include
        # it here, then candidate last. Parent must also load it for normal up.
        if self.persisted.exists():
            prefix += ["-f", str(self.persisted)]
        if image:
            path = self.directory / (self.operation["id"] + ".override.json")
            atomic_json(path, override(image))
            prefix += ["-f", str(path)]
        try:
            result = runtime.compose(
                self.state,
                *prefix,
                *args,
                input=input,
                capture_output=True,
                text=True,
                timeout=self.remaining(cap),
            )
        except subprocess.CalledProcessError as exc:
            raise ReleaseError(f"compose {args[0]} exited {exc.returncode}") from None
        return result.stdout

    def source(self):
        revision = self.command(["git", "rev-parse", "HEAD"]).strip()
        dirty = self.command(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", *PRODUCT_PATHS]
        )
        if dirty.strip():
            raise ReleaseError("commit product/build/test paths before release")
        tree = self.command(["git", "ls-files", "-s", "--", *PRODUCT_PATHS])
        fingerprint = hashlib.sha256(tree.encode()).hexdigest()
        return {"revision": revision, "source_fingerprint": fingerprint}

    def local_preflight(self):
        host = runtime.subprocess_env().get("DOCKER_HOST")
        if not host:
            contexts = json.loads(self.command(["docker", "context", "inspect"], cap=10))
            host = contexts[0]["Endpoints"]["docker"]["Host"]
        if not host.startswith("unix://"):
            raise ReleaseError("release runner requires a local Unix-socket Docker daemon")
        info = json.loads(self.command(["docker", "info", "--format", "{{json .}}"], cap=10))
        return {
            "docker_host": host,
            "cpus": info["NCPU"],
            "memory_bytes": info["MemTotal"],
            "architecture": info["Architecture"],
        }

    def image_info(self, image):
        info = json.loads(self.command(["docker", "image", "inspect", image]))[0]
        return {
            "image_id": require_image(info["Id"]),
            "revision": (info["Config"].get("Labels") or {}).get(
                "org.opencontainers.image.revision"
            ),
            "source_fingerprint": (info["Config"].get("Labels") or {}).get(
                "dc2.release.source-fingerprint"
            ),
            "injection": (info["Config"].get("Labels") or {}).get("dc2.release.injection"),
        }

    def containers(self, service):
        ids = self.compose("ps", "--all", "-q", service).split()
        if not ids:
            raise ReleaseError(f"integrated local service {service} has no containers")
        result = []
        for container in json.loads(self.command(["docker", "inspect", *ids])):
            if container["State"]["Status"] != "running":
                raise ReleaseError(f"local service {service} is not running")
            result.append(
                {
                    "container_id": container["Id"],
                    "image_id": require_image(container["Image"]),
                    "revision": (container["Config"].get("Labels") or {}).get(
                        "org.opencontainers.image.revision"
                    ),
                    "cpu_nano_limit": container["HostConfig"].get("NanoCpus", 0),
                    "memory_limit_bytes": container["HostConfig"].get("Memory", 0),
                }
            )
        return sorted(result, key=lambda item: item["container_id"])

    def diagnostic(self, service, query, parameters=()):
        # Credentials stay inside the owning service container. Only allowlisted
        # SELECTs are supplied by this file, using the runtime role, never admin.
        prefix = "MEDIA" if service == "media" else "PROCESSING"
        # Recovery survives a stopped candidate API and owns the same runtime
        # DB role, so rollback can still inspect interrupted attempts.
        target = "media" if service == "media" else "processing-recovery"
        code = f"""import asyncio,json,os,asyncpg
async def main():
    dsn=os.environ[{prefix + "_POSTGRES_DSN"!r}].replace('postgresql+asyncpg://','postgresql://',1)
    connection=await asyncpg.connect(dsn,timeout=5)
    try:
        rows=await connection.fetch({query!r},*{parameters!r},timeout=5)
        print(json.dumps([dict(row) for row in rows],default=str))
    finally:
        await connection.close()
asyncio.run(main())
"""
        # A freshly restored recovery container has only 1/16 CPU; its startup
        # and this diagnostic interpreter share that quota. Keep a bounded cold
        # start allowance, always clipped by the unchanged operation deadline.
        return json.loads(self.compose("exec", "-T", target, "python", "-", input=code, cap=45))

    def revisions(self, service):
        rows = self.diagnostic(
            service, "SELECT version_num FROM alembic_version ORDER BY version_num"
        )
        if not rows:
            raise ReleaseError(f"{service} database has no migration revision")
        return [row["version_num"] for row in rows]

    def media_snapshot(self):
        return {
            "media": self.containers("media"),
            "media-recovery": self.containers("media-recovery"),
            "migration_revisions": self.revisions("media"),
        }

    def unchanged(self, expected):
        actual = self.media_snapshot()
        if actual != expected:
            raise ReleaseError("Media container/image/revision changed during independent release")
        return actual

    def active_attempts(self):
        return self.diagnostic(
            "processing",
            """SELECT a.id::text AS id,
            a.state, a.finished_at IS NOT NULL AS finished, j.status AS job_status,
            a.error AS attempt_error, j.current_attempt_id::text AS current_attempt_id,
            j.error IS NOT NULL AND j.error <> '' AS has_error,
            j.deleted_at IS NOT NULL AS deleted FROM attempts a JOIN jobs j ON j.id=a.job_id
            WHERE a.state='processing' ORDER BY a.id""",
        )

    def attempt_states(self, ids):
        return self.diagnostic(
            "processing",
            """SELECT a.id::text AS id,
            a.state, a.finished_at IS NOT NULL AS finished, j.status AS job_status,
            a.error AS attempt_error, j.current_attempt_id::text AS current_attempt_id,
            j.error IS NOT NULL AND j.error <> '' AS has_error,
            j.deleted_at IS NOT NULL AS deleted FROM attempts a JOIN jobs j ON j.id=a.job_id
            WHERE a.id::text=ANY($1::text[]) ORDER BY a.id""",
            (ids,),
        )

    def drain(self, *, expected_attempt=None):
        started = time.monotonic()
        before = self.active_attempts()
        self.operation["drain"] = {
            "started_at": utcnow(),
            "attempts_before": before,
            "grace_seconds": 60,
            "limit_seconds": DRAIN_SECONDS,
        }
        self.operation.setdefault("drain_history", []).append(self.operation["drain"])
        self.save()
        if expected_attempt is not None:
            captured = next((row for row in before if row["id"] == expected_attempt), None)
            if (
                not captured
                or captured["state"] != "processing"
                or captured["job_status"] != "processing"
                or captured["finished"]
                or captured["current_attempt_id"] != expected_attempt
            ):
                raise ReleaseError(
                    "evidence upload is no longer processing immediately before drain"
                )
            self.operation["active_work"]["captured_attempt"] = captured
            self.operation["active_work"]["captured_at"] = utcnow()
            self.save()
        # Recovery remains running to make interrupted leases visibly failed.
        self.compose("stop", "--timeout", "60", "worker", cap=70)
        # A worker can claim one last attempt between SELECT and SIGTERM.
        ids = sorted({row["id"] for row in before + self.active_attempts()})
        deadline = min(self.deadline, started + DRAIN_SECONDS)
        while True:
            rows = self.attempt_states(ids) if ids else []
            self.operation["drain"]["attempts_after"] = rows
            if time.monotonic() > deadline:
                raise ReleaseError("worker lease drain did not finish visibly within five minutes")
            if len(rows) == len(ids) and all(terminal_attempt(row) for row in rows):
                self.operation["drain"].update(
                    attempts_after=rows,
                    finished_at=utcnow(),
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                self.save()
                return
            if time.monotonic() >= deadline:
                raise ReleaseError("worker lease drain did not finish visibly within five minutes")
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))

    def tests(self, source):
        self.command(["make", "lint", "test"])
        if self.source() != source:
            raise ReleaseError("source changed while fast tests ran")
        self.operation["fast_tests"] = {
            **source,
            "command": ["make", "lint", "test"],
            "passed_at": utcnow(),
        }
        self.save()

    def scan(self, image):
        shared = runtime.common_root(self.root)
        binary = shared / ".local/trivy/trivy"
        if not binary.is_file():
            raise ReleaseError("parent-installed pinned .local/trivy/trivy is missing")
        version = json.loads(self.command([str(binary), "--version", "--format", "json"], cap=10))
        if version.get("Version") != TRIVY_VERSION:
            raise ReleaseError("Trivy version must be pinned to 0.75.0")
        host = self.operation.get("docker_capacity", {}).get("docker_host") or (
            runtime.subprocess_env().get("DOCKER_HOST")
        )
        docker_host = ["--docker-host", host] if host else []
        report = json.loads(
            self.command(
                [
                    str(binary),
                    "image",
                    "--image-src",
                    "docker",
                    "--scanners",
                    "vuln",
                    "--skip-db-update",
                    "--skip-java-db-update",
                    "--offline-scan",
                    "--cache-dir",
                    str(shared / ".cache/trivy"),
                    "--timeout",
                    "3m",
                    "--format",
                    "json",
                    "--quiet",
                    *docker_host,
                    image,
                ],
                cap=190,
            )
        )
        return clean_scan(report, image)

    def artifact_test(self, image):
        # Run the artifact itself without network or production secrets. Full
        # behavioral fast tests above bind the clean source to its revision label.
        code = (
            "import importlib,shutil; "
            "[importlib.import_module(x) for x in "
            "('processing.main','processing.worker','processing.recovery')]; "
            "assert shutil.which('ffmpeg') and shutil.which('ffprobe')"
        )
        self.command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                image,
                "-c",
                code,
            ],
            cap=30,
        )
        return {
            "image_id": image,
            "kind": "offline artifact imports and encoder presence",
            "passed_at": utcnow(),
        }

    def build(self, source, *, bad_from=None):
        tag = f"dc2-release:{self.state['compose_project']}-{self.operation['id']}"
        args = [
            "docker",
            "build",
            "--label",
            "org.opencontainers.image.revision=" + source["revision"],
            "--label",
            "dc2.release.source-fingerprint=" + source["source_fingerprint"],
            "--label",
            "dc2.release.build-id=" + self.operation["id"],
            "-t",
            tag,
        ]
        if bad_from:
            require_image(bad_from)
            if self.image_info(bad_from)["image_id"] != bad_from:
                raise ReleaseError("retained build parent ID changed")
            # BuildKit resolves named local references, not FROM sha256:<ID>.
            # This operation owns a unique tag; check its binding around build.
            base_tag = tag + "-parent"
            self.command(["docker", "image", "tag", bad_from, base_tag])
            if self.image_info(base_tag)["image_id"] != bad_from:
                raise ReleaseError("local build parent tag does not bind retained ID")
            self.operation["build_parent"] = {
                "tag": base_tag,
                "image_id": bad_from,
                "verified_before_at": utcnow(),
            }
            self.save()
            # Intentional synthetic startup failure; offline imports still work.
            # Actual image bytes differ, are resolved/scanned/tested independently.
            injection = (
                "import sys\nif sys.argv[0].endswith('uvicorn'):\n"
                f"    print({INJECTION_MARKER!r}, file=sys.stderr, flush=True)\n"
                "    raise SystemExit(42)\n"
            )
            dockerfile = (
                f"FROM {base_tag}\nUSER root\nRUN "
                + json.dumps(
                    [
                        "python",
                        "-c",
                        "from pathlib import Path; p=Path('/app/processing/main.py'); "
                        f"p.write_text(p.read_text()+'\\n'+{injection!r})",
                    ]
                )
                + "\nUSER 10001\n"
            )
            args += [
                "--pull=false",
                "--network",
                "none",
                "--label",
                INJECTION_MARKER,
                "-f",
                "-",
                ".",
            ]
            self.command(args, input=dockerfile)
            if self.image_info(base_tag)["image_id"] != bad_from:
                raise ReleaseError("local build parent tag changed during build")
            self.operation["build_parent"]["verified_after_at"] = utcnow()
        else:
            args += ["-f", "deploy/processing.Dockerfile", "."]
            self.command(args)
        image = self.image_info(tag)
        self.operation["build"] = {
            **image,
            "tag": tag,
            "passed_at": utcnow(),
            "derived_from": bad_from,
        }
        self.save()
        return image["image_id"]

    def migration_check(self, previous, source, additive):
        changes = self.command(
            [
                "git",
                "diff",
                "--name-status",
                previous["revision"],
                source["revision"],
                "--",
                "processing/migrations/versions",
            ]
        )
        if changes.strip():
            if not additive or any(not line.startswith("A\t") for line in changes.splitlines()):
                raise ReleaseError("migration changes require declared additive-only new revisions")
        self.operation["migration_policy"] = {
            "additive_only_declared": additive,
            "changed_revisions": changes.splitlines(),
            "rollback": "image only; never downgrade Processing or migrate Media",
        }
        self.save()

    def smoke(self):
        return public_smoke(self)

    def proof(self, image, source, *, allow_injected=False):
        info = self.image_info(require_image(image))
        if info["revision"] != source["revision"]:
            raise ReleaseError("image revision label does not match tested HEAD")
        if info["source_fingerprint"] != source["source_fingerprint"]:
            raise ReleaseError("image source fingerprint does not match tested source")
        if info["injection"] and not allow_injected:
            raise ReleaseError("synthetic bad images are permitted only in evidence experiments")
        artifact = self.step("artifact-test", lambda: self.artifact_test(image))
        scan = self.step("trivy", lambda: self.scan(image))
        return {
            **info,
            "fast_tests": self.operation["fast_tests"],
            "artifact_test": artifact,
            "scan": scan,
            "build": self.operation.get("build"),
        }

    def tested_prior(self, image, source):
        previous = self.journal["tested_images"].get(image)
        if previous:
            require_tested(previous, image)
            self.image_info(image)  # Fail if someone removed the retained artifact.
        else:
            previous = self.proof(image, source)
        previous["smoke"] = self.step("baseline-public-smoke", self.smoke)
        self.journal["tested_images"][image] = previous
        self.save()
        return previous

    def apply(self, image, workers, *, migrate):
        if migrate:
            self.step(
                "candidate-migration",
                lambda: self.compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "--pull",
                    "never",
                    "processing-migrate",
                    image=image,
                    cap=90,
                ),
            )

        def startup():
            self.compose(
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "90",
                "--scale",
                f"worker={workers}",
                *SERVICES,
                image=image,
                cap=100,
            )

        if migrate:
            try:
                self.step("candidate-startup", startup)
            except Exception:
                # Read the failed API before restoration can replace it. Missing
                # evidence never prevents recovery, but cannot pass an experiment.
                try:
                    self.operation["candidate_failure"] = self.failed_candidate(image)
                except Exception as exc:
                    self.operation["candidate_failure_capture_error"] = type(exc).__name__
                self.save()
                raise
        else:
            startup()
        counts = {service: self.containers(service) for service in SERVICES}
        if len(counts["worker"]) != workers:
            raise ReleaseError("worker replica count was not restored")
        if any(container["image_id"] != image for group in counts.values() for container in group):
            raise ReleaseError("API, worker and recovery are not running the exact image")
        self.operation["processing_containers"] = counts
        self.save()

    def failed_candidate(self, image):
        ids = self.compose("ps", "--all", "-q", "processing", cap=10).split()
        records = []
        if ids:
            for container in json.loads(self.command(["docker", "inspect", *ids], cap=10)):
                state = container["State"]
                record = {
                    "container_id": container["Id"],
                    "image_id": require_image(container["Image"]),
                    "injection": (container["Config"].get("Labels") or {}).get(
                        "dc2.release.injection"
                    ),
                    "status": state["Status"],
                    "exit_code": state["ExitCode"],
                    "oom_killed": state.get("OOMKilled", False),
                    "has_runtime_error": bool(state.get("Error")),
                    "started_at": state["StartedAt"],
                    "finished_at": state["FinishedAt"],
                    "injection_marker_seen": False,
                }
                if record["image_id"] == image and record["status"] == "exited":
                    # Docker logs uses stderr as well; merge it inside the child
                    # without retaining arbitrary runtime output in the journal.
                    logs = self.command(
                        ["docker", "logs", "--tail", "40", container["Id"]],
                        cap=10,
                        merge_stderr=True,
                    )
                    record["injection_marker_seen"] = INJECTION_MARKER in logs.splitlines()
                    record["logs_sha256"] = hashlib.sha256(logs.encode()).hexdigest()
                records.append(record)
        return {"captured_at": utcnow(), "image_id": image, "containers": records}

    def restore(self, pending, *, recovery_budget=True, drain_workers=True):
        # Reserve recovery time before inspecting the retained image: a timed
        # out release must still be able to reach the Docker daemon to restore.
        recovery_deadline = time.monotonic() + ROLLBACK_SECONDS
        self.deadline = (
            recovery_deadline if recovery_budget else min(self.deadline, recovery_deadline)
        )
        image = require_image(pending["previous"])
        require_tested(self.journal["tested_images"].get(image), image)
        self.image_info(image)
        if drain_workers:
            # The candidate recovery process may also have crashed. Restore the
            # known reaper first so interrupted leases can become visibly failed.
            self.step(
                "rollback-recovery-start",
                lambda: self.compose(
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "30",
                    "processing-recovery",
                    image=image,
                    cap=40,
                ),
            )
            self.step("rollback-worker-drain", self.drain)
        # A fresh bounded recovery budget is explicit, not a retry of promotion.
        self.step("rollback-apply", lambda: self.apply(image, pending["workers"], migrate=False))
        smoke = self.step("rollback-public-smoke", self.smoke)
        self.step("rollback-media-unchanged", lambda: self.unchanged(pending["media"]))
        revisions = self.revisions("processing")
        self.remaining()
        atomic_json(self.persisted, override(image))
        self.journal.update(current=image, pending=None)
        self.operation["rollback"] = {
            "image_id": image,
            "status": "restored",
            "smoke": smoke,
            "finished_at": utcnow(),
        }
        self.operation["processing_revisions_after_rollback"] = revisions
        self.save()

    def release(self, *, additive=False, bad_from=None, active_work=False):
        self.begin("injected-release" if bad_from else "release", RELEASE_SECONDS)
        prior = None
        try:
            if self.journal["pending"]:
                raise ReleaseError("unfinished deployment exists; run rollback first")
            source = self.step("clean-source", self.source)
            self.operation.update(source)
            self.operation["docker_capacity"] = self.step("local-daemon", self.local_preflight)
            media = self.step("media-baseline", self.media_snapshot)
            containers = {name: self.containers(name) for name in SERVICES}
            images = {item["image_id"] for items in containers.values() for item in items}
            if len(images) != 1:
                raise ReleaseError("baseline API/worker/recovery must share one immutable image")
            prior = images.pop()
            if bad_from and bad_from != prior:
                raise ReleaseError("injected build must derive from the tested running image")
            workers = len(containers["worker"])
            self.operation.update(
                media_before=media,
                prior_image=prior,
                worker_replicas=workers,
                processing_revisions_before=self.revisions("processing"),
            )
            self.step("fast-tests", lambda: self.tests(source))
            previous = self.step("tested-rollback-image", lambda: self.tested_prior(prior, source))
            image = self.step("build", lambda: self.build(source, bad_from=bad_from))
            require_image(image)
            self.operation["candidate_image"] = image
            proof = self.proof(image, source, allow_injected=bool(bad_from))
            self.operation["candidate_proof"] = proof
            self.step("migration-policy", lambda: self.migration_check(previous, source, additive))
            if self.source() != source:
                raise ReleaseError("source changed before deployment")
            # Evidence only: baseline smoke and all candidate proof gates have
            # finished before introducing real work. Keep HTTP cookies in memory.
            request = None
            if active_work:
                request = self.step(
                    "evidence-public-upload", lambda: public_smoke(self, prepare_drain=True)
                )
            pending = {
                "previous": prior,
                "candidate": image,
                "workers": workers,
                "media": media,
                "operation_id": self.operation["id"],
            }
            self.journal["pending"] = pending
            self.save()  # Crash recovery intent is durable before any mutation.
            self.step(
                "worker-drain",
                (lambda: self.drain(expected_attempt=self.operation["active_work"]["attempt_id"]))
                if active_work
                else self.drain,
            )
            if active_work:
                self.step("evidence-public-outcome", lambda: public_drain_outcome(self, request))
            self.step("candidate-apply", lambda: self.apply(image, workers, migrate=True))
            proof["smoke"] = self.step("candidate-public-smoke", self.smoke)
            self.step("media-unchanged", lambda: self.unchanged(media))
            self.operation["processing_revisions_after"] = self.revisions("processing")
            self.remaining()  # All promotion gates, including smoke, must be <=10min.
            atomic_json(self.persisted, override(image))
            self.journal["tested_images"][image] = proof
            self.journal.update(previous=prior, current=image, pending=None)
            self.finish("promoted")
            return 0
        except Exception as exc:
            self.operation["promotion_deadline_exceeded"] = time.monotonic() >= self.deadline
            self.operation["failure"] = (
                str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
            )
            if (
                self.journal["pending"]
                and self.journal["pending"]["operation_id"] == self.operation["id"]
            ):
                try:
                    self.restore(self.journal["pending"])
                except Exception as rollback_exc:
                    self.operation["rollback_failure"] = (
                        str(rollback_exc)
                        if isinstance(rollback_exc, ReleaseError)
                        else type(rollback_exc).__name__
                    )
                    self.finish("recovery_required")
                    return 3
                self.finish("failed_rolled_back")
                return 2
            self.finish("rejected")
            return 1

    def rollback(self):
        self.begin("rollback", DRAIN_SECONDS + ROLLBACK_SECONDS)
        try:
            self.operation["docker_capacity"] = self.step("local-daemon", self.local_preflight)
            pending = self.journal["pending"]
            interrupted = pending is not None
            if not pending:
                image = self.journal["previous"]
                if not image:
                    raise ReleaseError("no retained tested previous image")
                require_tested(self.journal["tested_images"].get(image), image)
                self.image_info(image)
                pending = {
                    "previous": image,
                    "workers": len(self.containers("worker")),
                    "media": self.media_snapshot(),
                    "operation_id": self.operation["id"],
                }
                # Durable recovery intent also covers an interrupted manual rollback.
                self.journal["pending"] = pending
                self.save()
                self.step("worker-drain", self.drain)
            old_current = self.journal["current"]
            self.restore(pending, recovery_budget=False, drain_workers=interrupted)
            self.journal["previous"] = old_current
            self.finish("rolled_back")
            return 0
        except Exception as exc:
            self.operation["failure"] = (
                str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
            )
            self.finish("recovery_required" if self.journal["pending"] else "rejected")
            return 3 if self.journal["pending"] else 1

    def evidence(self, additive=False):
        started = time.monotonic()
        if self.release(additive=additive, active_work=True):
            return 1
        good = self.operation
        good_image = self.journal["current"]
        result = self.release(bad_from=good_image)
        bad = self.operation
        passed = (
            active_drain_evidence(good)
            and result == 2
            and bad["status"] == "failed_rolled_back"
            and self.journal["current"] == good_image
            and self.journal["pending"] is None
            and bad.get("candidate_image") != good_image
            and bad.get("candidate_proof", {}).get("injection") == INJECTION
            and bad.get("build", {}).get("derived_from") == good_image
            and not bad.get("promotion_deadline_exceeded", True)
            and any(
                step["name"] == "candidate-migration" and step["status"] == "passed"
                for step in bad["steps"]
            )
            and any(
                step["name"] == "candidate-startup" and step["status"] == "failed"
                for step in bad["steps"]
            )
            and injected_failure(bad.get("candidate_failure", {}), bad.get("candidate_image"))
        )
        evidence = {
            "scope": "local",
            "status": "passed" if passed else "failed",
            "finished_at": utcnow(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "good_operation": good["id"],
            "bad_operation": bad["id"],
            "restored_image": self.journal["current"],
            "bad_release_exit": result,
            "candidate_failure": bad.get("candidate_failure"),
            "active_work": good.get("active_work"),
            "good_drain": good.get("drain"),
        }
        atomic_json(self.directory / ("experiment-" + good["id"] + ".json"), evidence)
        return 0 if passed else 1


def injected_failure(failure, image):
    """Require an exact deployed API, its declared fault marker and startup exit."""
    containers = failure.get("containers", [])
    return (
        bool(image)
        and failure.get("image_id") == image
        and len(containers) == 1
        and all(
            row.get("container_id")
            and row.get("image_id") == image
            and row.get("injection") == INJECTION
            and row.get("status") == "exited"
            and row.get("exit_code") == 42
            and not row.get("oom_killed", True)
            and not row.get("has_runtime_error", True)
            and row.get("injection_marker_seen")
            and row.get("started_at")
            and not row["started_at"].startswith("0001-")
            and row.get("finished_at")
            and not row["finished_at"].startswith("0001-")
            for row in containers
        )
    )


def require_tested(proof, image):
    if not proof or proof.get("image_id") != image or not proof.get("revision"):
        raise ReleaseError("rollback image has no exact tested provenance")
    if (
        proof.get("scan", {}).get("image_id") != image
        or proof["scan"].get("fixable_high_critical") != 0
    ):
        raise ReleaseError("rollback image lacks an exact passing vulnerability scan")
    if proof.get("artifact_test", {}).get("image_id") != image or not proof.get("smoke"):
        raise ReleaseError("rollback image lacks artifact/public smoke evidence")
    if proof.get("fast_tests", {}).get("revision") != proof["revision"]:
        raise ReleaseError("rollback image lacks exact revision test evidence")
    if (
        not proof.get("source_fingerprint")
        or proof["fast_tests"].get("source_fingerprint") != proof["source_fingerprint"]
    ):
        raise ReleaseError("rollback image lacks exact source fingerprint test evidence")


def active_drain_evidence(operation):
    """An idle drain or a different upload cannot satisfy the experiment."""
    work = operation.get("active_work", {})
    attempt = work.get("attempt_id")
    captured = work.get("captured_attempt", {})
    terminal = work.get("terminal_attempt", {})
    drain = operation.get("drain", {})
    return bool(
        attempt
        and work.get("job_id")
        and work.get("asset_id")
        and work.get("public_processing_at")
        and work.get("captured_at")
        and captured.get("id") == attempt
        and captured.get("state") == "processing"
        and captured.get("job_status") == "processing"
        and captured.get("current_attempt_id") == attempt
        and not captured.get("finished", True)
        and captured in drain.get("attempts_before", [])
        and terminal.get("id") == attempt
        and terminal in drain.get("attempts_after", [])
        and terminal_attempt(terminal)
        and work.get("public_terminal_status") == terminal.get("job_status")
        and work.get("public_terminal_status") in ("done", "failed")
        and (work["public_terminal_status"] != "failed" or work.get("public_has_error"))
        and work.get("public_terminal_at")
        and work.get("deleted_at")
        and drain.get("finished_at")
    )


def public_drain_outcome(runner, request):
    work = runner.operation["active_work"]
    rows = runner.operation["drain"]["attempts_after"]
    terminal = next((row for row in rows if row["id"] == work["attempt_id"]), None)
    if not terminal or not terminal_attempt(terminal):
        raise ReleaseError("evidence upload has no captured terminal attempt")
    work["terminal_attempt"] = terminal
    runner.save()
    while True:
        job = request("/api/jobs/" + work["asset_id"])
        status = job["status"]
        if status in ("done", "failed"):
            if status != terminal["job_status"] or (status == "failed" and not job.get("error")):
                raise ReleaseError("evidence public outcome does not match the drained attempt")
            work.update(
                public_terminal_status=status,
                public_has_error=bool(job.get("error")),
                public_terminal_at=utcnow(),
            )
            runner.save()
            break
        if status not in ("queued", "processing"):
            raise ReleaseError("evidence public outcome returned an unknown job state")
        time.sleep(min(0.25, runner.remaining()))
    request("/api/jobs/" + work["asset_id"], method="DELETE", expected=204)
    work["deleted_at"] = utcnow()
    runner.save()


def public_smoke(runner, *, prepare_drain=False):
    """Real upload, durable processing and playable bytes through Media HTTPS only."""
    base = runner.state["public_url"]
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ReleaseError("public smoke accepts only local HTTPS origins")
    context = ssl.create_default_context(cafile=runner.state["ca_file"])
    cookies = http.cookiejar.CookieJar()

    class LocalRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urlsplit(newurl)
            if (target.scheme, target.netloc) != (parsed.scheme, parsed.netloc):
                raise ReleaseError("smoke redirect is outside the local HTTPS origin")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies),
        urllib.request.HTTPSHandler(context=context),
        LocalRedirects(),
    )
    deadline = runner.deadline if prepare_drain else min(runner.deadline, time.monotonic() + 90)

    def request(path, *, method="GET", data=None, headers=None, expected=200, raw=False):
        # Permit capabilities only on this run's TLS origin, never arbitrary hosts.
        url = path if path.startswith("https://") else base + path
        target = urlsplit(url)
        if (target.scheme, target.netloc) != (parsed.scheme, parsed.netloc):
            raise ReleaseError("smoke playback URL is outside the local HTTPS origin")
        left = min(runner.remaining(10), deadline - time.monotonic())
        if left <= 0:
            raise ReleaseError(
                "public evidence workflow deadline exceeded"
                if prepare_drain
                else "public workflow smoke exceeded 90 seconds"
            )
        try:
            with opener.open(
                urllib.request.Request(url, data=data, headers=headers or {}, method=method),
                timeout=left,
            ) as response:
                if response.status != expected:
                    raise ReleaseError(f"public smoke expected HTTP {expected}")
                body = response.read(16 * 1024 * 1024 + 1)
                if len(body) > 16 * 1024 * 1024:
                    raise ReleaseError("short smoke response exceeded 16 MiB")
                return body if raw or not body else json.loads(body)
        except urllib.error.HTTPError as exc:
            raise ReleaseError(f"public smoke HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReleaseError("public smoke transport/TLS failed") from None

    request("/api/health")
    credentials = {
        "email": f"release-{uuid.uuid4().hex}@example.com",
        "password": secrets.token_urlsafe(24),
    }
    payload = json.dumps(credentials).encode()
    request(
        "/api/auth/register",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/json"},
        expected=201,
    )
    request(
        "/api/auth/login", method="POST", data=payload, headers={"Content-Type": "application/json"}
    )
    if not any(cookie.secure for cookie in cookies):
        raise ReleaseError("public login did not establish a Secure cookie")
    request("/api/auth/me")
    with tempfile.TemporaryDirectory(dir=runner.directory) as directory:
        fixture = Path(directory) / "release.mp4"
        runner.command(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30:duration=60"
                if prepare_drain
                else "color=c=blue:s=160x90:r=10:d=1",
                *(
                    [
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=997:sample_rate=48000:duration=60",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-shortest",
                    ]
                    if prepare_drain
                    else ["-an"]
                ),
                "-c:v",
                "libx264",
                *(["-preset", "ultrafast"] if prepare_drain else []),
                "-threads",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-map_metadata",
                "-1",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                str(fixture),
            ],
            cap=30 if prepare_drain else 10,
        )
        video = fixture.read_bytes()
        boundary = "dc2-release-" + uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="release.mp4"\r\nContent-Type: video/mp4\r\n\r\n'
        ).encode()
        body += video + f"\r\n--{boundary}--\r\n".encode()
        accepted = request(
            "/api/upload",
            method="POST",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            expected=202,
        )
        asset = str(uuid.UUID(accepted["job_id"]))
        if prepare_drain:
            work = {
                "asset_id": asset,
                "uploaded_at": utcnow(),
                "fixture_sha256": hashlib.sha256(video).hexdigest(),
                "fixture_seconds": 60,
                "fixture_width": 1280,
                "fixture_height": 720,
            }
            runner.operation["active_work"] = work
            runner.save()
            while True:
                job = request("/api/jobs/" + asset)
                if job["status"] not in ("queued", "processing"):
                    raise ReleaseError("evidence upload finished before processing confirmation")
                if job["status"] == "processing":
                    rows = runner.diagnostic(
                        "processing",
                        """SELECT j.id::text AS job_id, a.id::text AS attempt_id
                        FROM jobs j JOIN attempts a ON a.id=j.current_attempt_id
                        WHERE j.asset_id=$1::uuid AND j.status='processing'
                        AND a.state='processing' AND a.finished_at IS NULL""",
                        (asset,),
                    )
                    if len(rows) == 1:
                        work.update(
                            job_id=str(uuid.UUID(rows[0]["job_id"])),
                            attempt_id=str(uuid.UUID(rows[0]["attempt_id"])),
                            public_processing_at=utcnow(),
                        )
                        runner.save()
                        return request
                time.sleep(min(0.25, runner.remaining()))
        while True:
            job = request("/api/jobs/" + asset)
            if job["status"] == "failed":
                raise ReleaseError("public upload became visibly failed")
            if job["status"] == "done":
                break
            if job["status"] not in ("queued", "processing"):
                raise ReleaseError("public smoke returned an unknown job state")
            if time.monotonic() >= deadline:
                raise ReleaseError("public processing smoke exceeded 90 seconds")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        output = request(job["output_url"], raw=True)
        playable = Path(directory) / "output.mp4"
        playable.write_bytes(output)
        probe = json.loads(
            runner.command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    str(playable),
                ],
                cap=10,
            )
        )
        if not any(stream.get("codec_type") == "video" for stream in probe.get("streams", [])):
            raise ReleaseError("public output did not contain a playable video stream")
        request("/api/jobs/" + asset, method="DELETE", expected=204)
    return {
        "asset_id": asset,
        "fixture_sha256": hashlib.sha256(video).hexdigest(),
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_bytes": len(output),
        "workflow": "health/register/login/upload/process/playback/delete",
        "passed_at": utcnow(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("release", "rollback", "evidence"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--additive-migrations",
        action="store_true",
        help="declare reviewed NEW Processing revisions backward compatible with prior image",
    )
    args = parser.parse_args(argv)
    try:
        runner = Runner(args.run_id)
        with runner.locked():
            if args.action == "release":
                result = runner.release(additive=args.additive_migrations)
            elif args.action == "rollback":
                result = runner.rollback()
            else:
                result = runner.evidence(additive=args.additive_migrations)
        print(f"local release: exit={result}; journal={runner.journal_path}")
        if result and runner.operation:
            print(
                f"local release: {runner.operation['status']}: "
                f"{runner.operation.get('failure', 'experiment criteria failed')}",
                file=sys.stderr,
            )
        return result
    except Exception as exc:
        message = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
        print(f"local release: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
