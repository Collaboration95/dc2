"""Explicit isolated Compose bindings for the preparation operator; no AWS executor."""

import hashlib
import json
import secrets
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from scripts.aws.exports import REVISIONS, WRITERS, export_state
from scripts.aws.local_adapters import LocalDump, PrivateFiles
from scripts.aws.smoke import Workflow
from scripts.aws.transport import OperationError, remaining
from scripts.aws.workers import drain, inventory, start, worker_inventory
from scripts.dev import runtime

SERVICE_NAMES = {
    "media": ("media", "media-recovery"),
    "processing": ("processing", "processing-recovery"),
}


class LocalBindings:
    """One explicit namespace, deadline, journal, ledger and loopback data/client set.

    Control-plane responses supplied by an emulator remain emulator observations.
    These bindings independently execute/observe actual local application services.
    No default run-id, credentials, image, task network or cloud endpoint is guessed.
    """

    def __init__(self, config, transport, journal, data, client, ledger, state, *, deadline):
        if config.get("mode") != "plan" or ledger.mode != "local-services":
            raise OperationError("Local bindings cannot execute a cloud configuration")
        self.config, self.transport, self.journal = config, transport, journal
        self.data, self.client, self.ledger, self.state = data, client, ledger, state
        self.deadline = deadline
        directory = Path(state["env_file"]).parent
        env = runtime.read_env(Path(state["env_file"]))
        if directory.name == "local" or not state["compose_project"].startswith("dc2-aws2-"):
            raise OperationError("A new explicit aws2 namespace is required")
        if env.get("COMPOSE_PROJECT_NAME") != state["compose_project"]:
            raise OperationError("Namespace configuration differs from selected services")
        if (
            client.context.mode != "local-fixture"
            or client.context.public_url != state["public_url"]
        ):
            raise OperationError("Explicit namespace HTTPS client required")
        self.private_env = env
        self.override = directory / "local-operator.json"
        journal.check_context(config)

    def compose(self, *args, deadline, input=None):
        try:
            result = runtime.compose(
                self.state,
                *(["-f", str(self.override)] if self.override.exists() else []),
                *args,
                input=input,
                capture_output=True,
                text=True,
                timeout=remaining(min(deadline, self.deadline)),
            )
            return result.stdout
        except (subprocess.SubprocessError, OSError):
            raise OperationError("Bounded isolated local operation failed") from None

    def running(self, service, *, deadline):
        raw = self.compose("ps", "--format", "json", "--all", service, deadline=deadline)
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        return any(row.get("State") == "running" for row in rows)

    def schema_revision(self, owner, *, deadline):
        return self.data.schema_revision(owner, deadline=min(deadline, self.deadline))

    def readiness(self, owner, deadline):
        try:
            if not all(self.running(name, deadline=deadline) for name in SERVICE_NAMES[owner]):
                return False
            if self.data.schema_revision(owner, deadline=deadline) != REVISIONS[owner]:
                return False
            status, _, _ = self.client.request("GET", "/api/health")
            if owner == "processing":
                # Execute within the selected owning task network, not host/peer fallback.
                self.compose(
                    "exec",
                    "-T",
                    "processing",
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)",
                    deadline=deadline,
                )
            remaining(deadline)
            return status == 200

        except (OperationError, ValueError):
            return False  # Startup is retried only within the caller's absolute deadline.

    def state_readiness(self, deadline):
        revisions = {
            owner: self.data.schema_revision(owner, deadline=deadline) for owner in REVISIONS
        }
        remaining(deadline)
        ping = self.data.redis.ping()
        # Local named-volume observation only; it is not an EBS UUID/mount receipt.
        ids = self.compose("ps", "-q", "postgres", deadline=deadline).strip().splitlines()
        if len(ids) != 1:
            raise OperationError("One local state database required")
        inspected = runtime.run(
            ["docker", "inspect", ids[0]],
            capture_output=True,
            text=True,
            timeout=remaining(deadline),
        )
        mount = any(
            m.get("Type") == "volume"
            and m.get("RW") is True
            and m.get("Destination") == "/var/lib/postgresql/data"
            for m in json.loads(inspected.stdout)[0].get("Mounts", [])
        )
        return {
            "mount": mount,
            "postgres_tcp": True,
            "redis": ping is True,
            "media_schema": revisions["media"] == REVISIONS["media"],
            "processing_schema": revisions["processing"] == REVISIONS["processing"],
        }

    def _intake(self, paused, deadline):
        # A namespace-only nginx guard keeps health/read routes usable on wake.
        # It never edits the shared template or inherited demo gateway.
        template = (runtime.ROOT / "deploy/nginx/local.conf.template").read_text()
        if paused:
            template = template.replace(
                "location /api/ {",
                "location /api/ {\n"
                "        if ($request_method !~ ^(GET|HEAD|OPTIONS)$) { return 503; }",
            )
        private = Path(self.state["env_file"]).parent / "operator-nginx.template"
        runtime.atomic_write(private, template)
        runtime.atomic_write(
            self.override,
            json.dumps(
                {
                    "services": {
                        "nginx": {
                            "volumes": [f"{private}:/etc/nginx/templates/default.conf.template:ro"]
                        }
                    }
                }
            ),
        )
        self.compose(
            "up", "-d", "--no-deps", "--no-build", "--force-recreate", "nginx", deadline=deadline
        )
        while remaining(deadline):
            try:
                status, _, _ = self.client.request("POST", "/api/upload")
                if (status == 503) == paused:
                    return True
            except Exception:
                pass
            time.sleep(min(0.1, remaining(deadline)))
        return False

    def pause_intake(self, deadline):
        return self._intake(True, deadline)

    def resume_intake(self, deadline):
        return self._intake(False, deadline)

    def intake_closed(self):
        return self.client.request("POST", "/api/upload")[0] == 503

    def quiesce_writers(self, deadline):
        services = [
            *SERVICE_NAMES["media"],
            *SERVICE_NAMES["processing"],
            "media-migrate",
            "processing-migrate",
        ]
        self.compose("stop", "-t", "10", *services, deadline=deadline)
        if any(self.running(name, deadline=deadline) for name in services):
            raise OperationError("Actual local writer container still running")
        with self.journal.path.open() as stream:
            state = json.load(stream)
        if not state["paused"] or state.get("pending_release"):
            raise OperationError("Launches or release not quiescent")
        with self.journal.locked() as locked:
            # Callers inside lifecycle already hold the station lock. This method
            # is used directly outside that operation; lifecycle uses proof_locked.
            return self.proof_locked(locked, deadline)

    def proof_locked(self, state, deadline):
        if not state["paused"] or not self.intake_closed():
            raise OperationError("Intake/launches must actually be closed")
        workers, occupied = worker_inventory(self.config, self.transport, state, deadline=deadline)
        tasks = inventory(self.config, self.transport, deadline=deadline)
        if state.get("pending_release") or any(
            t["lastStatus"] != "STOPPED" for t in tasks.values()
        ):
            raise OperationError("All local control tasks and migrations must be terminal")
        if occupied or any(t["lastStatus"] != "STOPPED" for t in workers.values()):
            raise OperationError("Observed worker inventory not quiescent")
        services = [
            *SERVICE_NAMES["media"],
            *SERVICE_NAMES["processing"],
            "media-migrate",
            "processing-migrate",
        ]
        if any(self.running(name, deadline=deadline) for name in services):
            raise OperationError("Actual local application writer is running")
        from scripts.aws.config import CloudConfig

        identity = CloudConfig(
            environment_id=self.config["environment_id"],
            operator_station=self.config["operator_station"],
        )
        return self.data.quiescence(identity, {name: True for name in WRITERS}, deadline=deadline)

    def export_hook(self, proof, epoch_deadline, *, private_directory, private_store, roles_dsn):
        from scripts.aws.config import CloudConfig

        identity = CloudConfig(
            environment_id=self.config["environment_id"],
            operator_station=self.config["operator_station"],
        )
        commands = LocalDump(
            self.data,
            roles_file=runtime.ROOT / "deploy/aws/state/roles-export.sql",
            roles_dsn=roles_dsn,
            pg_dump="pg_dump",
            psql="psql",
        )
        storage = PrivateFiles(private_store, prefix=f"private/{identity.environment_id}/exports/")
        return export_state(
            identity, proof, commands, storage, private_directory, deadline=epoch_deadline
        )

    def prior_compatibility(self, owner, image, prior_artifact, *, additive_reviewed, deadline):
        from scripts.aws.artifacts import validate

        validate(prior_artifact, owner=owner)
        if image != prior_artifact["config_id"] or additive_reviewed is not True:
            raise OperationError("Explicit reviewed exact prior artifact required")
        service = "media" if owner == "media" else "processing"
        # Prior image executes its owning health/schema code with only its owning
        # runtime DSN. No rollback downgrades or synthetic compatibility booleans.
        module = "media.config" if owner == "media" else "processing.config"
        query = f"""import asyncio, asyncpg
from {module} import get_settings
async def check():
    s = get_settings()
    c = await asyncpg.connect(s.postgres_dsn.replace(
        "postgresql+asyncpg://", "postgresql://"), timeout=2)
    try:
        print(await c.fetchval("SELECT version_num FROM alembic_version"))
    finally:
        await c.close()
asyncio.run(check())
"""
        override = Path(self.state["env_file"]).parent / "prior-check.json"
        runtime.atomic_write(override, json.dumps({"services": {service: {"image": image}}}))
        revision = self.compose(
            "-f",
            str(override),
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            service,
            "-c",
            query,
            deadline=deadline,
        ).strip()
        if revision != REVISIONS[owner]:
            raise OperationError("Prior image did not observe the owning candidate schema")
        return {
            "additive_reviewed": True,
            "prior_image_tested": True,
            "prior_config_id": image,
            "expected_revision": revision,
        }

    def smoke_workflow(self, owner, deadline, operations):
        workflow = Workflow(self.client, self.ledger)
        credentials = {
            "email": f"aws2-{uuid4().hex}@example.com",
            "password": secrets.token_urlsafe(24),
        }
        workflow.json("POST", "/api/auth/register", expected=201, json=credentials)
        workflow.login(**credentials)
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "short.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:r=10:d=1",
                    "-c:v",
                    "libx264",
                    "-y",
                    str(fixture),
                ],
                check=True,
                capture_output=True,
                timeout=min(10, remaining(deadline)),
            )
            payload = fixture.read_bytes()
            result = workflow.upload(uuid4().hex, payload, duration_seconds=1)
            job_id = result["job_id"]
            if owner == "processing":
                operations["launch_workers"](1)
            job = workflow.poll(job_id, deadline=deadline)
            if job["status"] != "done":
                raise OperationError("Actual short public encode did not succeed")
            output_url = job["output_url"]
            if self.client.context.capability_allowed(output_url):
                status, body, headers = self.client.download(output_url)
                workflow.range(output_url)
            else:
                parsed = urlsplit(output_url)
                origin = urlsplit(self.client.context.public_url)
                if parsed.scheme or parsed.netloc:
                    if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                        raise OperationError("Public output facade left its explicit API origin")
                    output_url = parsed.path + ("?" + parsed.query if parsed.query else "")
                status, body, headers = self.client.request("GET", output_url)
                if status == 307:
                    capability = headers["location"]
                    status, body, headers = self.client.download(capability)
                    workflow.range(capability)
            if status != 200 or not body:
                raise OperationError("Actual public output unavailable")
            output = Path(folder) / "output.mp4"
            output.write_bytes(body)
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-i", str(output), "-f", "null", "-"],
                check=True,
                capture_output=True,
                timeout=min(10, remaining(deadline)),
            )
            workflow.delete(job_id)
        return {
            "status": "PASS",
            "mode": "local-services",
            "job_id": job_id,
            "fixture_sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(body),
        }

    def drain(self, *, deadline):
        if isinstance(deadline, datetime):
            deadline = time.monotonic() + deadline.timestamp() - time.time()
        with self.journal.locked() as state:
            result = drain(
                self.config,
                self.transport,
                self.journal,
                state,
                observe=self.data.observe_worker,
                warm_shutdown=self.data.warm_shutdown,
                deadline=deadline,
            )
        return result

    def prewarm(self, count, *, deadline):
        if hasattr(deadline, "timestamp"):
            deadline = time.monotonic() + deadline.timestamp() - time.time()
        tasks = start(
            self.config, self.transport, self.journal, count=count, prewarm=True, deadline=deadline
        )
        with self.journal.locked() as state:
            records = {r["task"]: r for r in state["launches"].values() if r.get("task")}
            ready = False
            while remaining(deadline) > 0:
                ready = all(
                    self.data.observe_worker(t, records[t]["rq_name"], deadline=deadline)["fresh"]
                    for t in tasks
                )
                if ready:
                    break
                time.sleep(min(0.1, remaining(deadline)))
            occupied = worker_inventory(self.config, self.transport, state, deadline=deadline)[1]
        return {
            "ready": ready,
            "task_ids": tasks,
            "nonterminal_plus_reserved": occupied,
            "ordinary_nonburst": True,
        }

    def submit(self, fixture, *, deadline):
        if isinstance(deadline, datetime):
            deadline = time.monotonic() + deadline.timestamp() - time.time()
        remaining(deadline)
        # capacity() has already reserved these exact bytes in this shared ledger.
        if not any(
            r.get("fixture_sha256") == hashlib.sha256(fixture["payload"]).hexdigest()
            and r.get("fixture_id") == fixture["id"]
            for r in self.ledger.records
        ):
            raise OperationError("Submission requires its prior shared fixture reservation")
        return Workflow(self.client, self.ledger).json(
            "POST",
            "/api/upload",
            expected=202,
            route="/upload",
            files={"file": ("capacity.mp4", fixture["payload"], "video/mp4")},
        )["job_id"]

    def wait_jobs(self, jobs, *, deadline):
        if isinstance(deadline, datetime):
            deadline = time.monotonic() + deadline.timestamp() - time.time()
        workflow = Workflow(self.client, self.ledger)
        return [
            {
                "id": job,
                "status": "succeeded"
                if workflow.poll(job, deadline=deadline)["status"] == "done"
                else "failed",
            }
            for job in jobs
        ]
