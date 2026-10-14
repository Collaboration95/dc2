"""Opt-in actual-service composition with a clearly synthetic AWS control plane.

Run from repo: python -m tests... is not used (tests are unpackaged).
PYTHONPATH=. .venv/bin/python tests/aws/local_composition.py --run-id aws2-prep-r1
The namespace must already be built/booted. No cloud, long fixtures or scan PASS
is invented: registry/scan receipts below are synthetic control-state test inputs.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from test_transport_fixtures import NEW, OLD, Fake, artifact
from test_transport_fixtures import config as config_fixture

from scripts.aws.context import Client, Context
from scripts.aws.exports import REVISIONS
from scripts.aws.journal import Journal
from scripts.aws.lifecycle import close, open_session
from scripts.aws.local_adapters import LocalData
from scripts.aws.local_bindings import SERVICE_NAMES, LocalBindings
from scripts.aws.release import promote
from scripts.aws.smoke import Ledger
from scripts.aws.transport import remaining
from scripts.dev import runtime


class LocalControl(Fake):
    """Synthetic inventory, actual owning Compose mutation and finite worker process."""

    def __init__(self, config, state, images):
        super().__init__(config)
        self.state, self.images, self.containers = state, images, {}
        self.bindings = None

    def call(self, service, operation, payload, *, deadline=None):
        remaining(deadline)
        bindings = self.bindings
        if operation in {"describe-tasks", "list-tasks"}:
            for task, container in self.containers.items():
                info = json.loads(
                    runtime.run(
                        ["docker", "inspect", container],
                        capture_output=True,
                        text=True,
                        timeout=remaining(deadline),
                    ).stdout
                )[0]
                if not info["State"]["Running"]:
                    self.tasks[task]["lastStatus"] = "STOPPED"
        result = super().call(service, operation, payload, deadline=deadline)
        if operation == "run-task":
            task = result["tasks"][0]["taskArn"]
            if task not in self.containers:
                ref = payload["taskDefinition"]
                if "migration" in ref:
                    owner = "media" if "media" in ref else "processing"
                    bindings.compose(
                        "run", "--rm", "--no-deps", owner + "-migrate", deadline=deadline
                    )
                else:
                    command = payload["overrides"]["containerOverrides"][0]["command"]
                    self.containers[task] = bindings.compose(
                        "run", "-d", "--no-deps", "worker", *command, deadline=deadline
                    ).strip()
        elif operation == "stop-task" and payload["task"] in self.containers:
            runtime.run(
                ["docker", "stop", "-t", "5", self.containers[payload["task"]]],
                capture_output=True,
                text=True,
                timeout=remaining(deadline),
            )
        elif operation == "update-service":
            key = next(k for k, v in self.config["services"].items() if v == payload["service"])
            owner = "media" if key == "media" else "processing"
            names = (
                SERVICE_NAMES[owner]
                if owner == "media"
                else (("processing",) if key == "processing_api" else ("processing-recovery",))
            )
            if payload["desiredCount"] == 0:
                bindings.compose("stop", "-t", "10", *names, deadline=deadline)
            else:
                reference = payload.get(
                    "taskDefinition", self.services[payload["service"]]["taskDefinition"]
                )
                image = self.images[owner][1 if reference.endswith(":2") else 0]
                overrides = {name: {"image": image} for name in names}
                if self.bad and reference.endswith(":2") and key != "processing_recovery":
                    overrides[names[0]]["command"] = ["python", "-c", "raise SystemExit(42)"]
                path = Path(self.state["env_file"]).parent / "selected-task.json"
                runtime.atomic_write(path, json.dumps({"services": overrides}))
                bindings.compose(
                    "-f",
                    str(path),
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--force-recreate",
                    *names,
                    deadline=deadline,
                )
        elif operation == "stop-instances":
            bindings.compose("stop", "-t", "10", "postgres", "redis", deadline=deadline)
        elif operation == "start-instances":
            bindings.compose(
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--wait",
                "postgres",
                "redis",
                deadline=deadline,
            )
        return result


def run(run_id, report):
    if not run_id.startswith("aws2-"):
        raise ValueError("Select a dedicated aws2 namespace")
    env, state = runtime.configure(run_id)
    private = Path(state["env_file"]).parent
    port_file = private / "redis-port.json"
    if port_file.exists():
        port = json.loads(port_file.read_text())["port"]
    else:
        port = runtime.free_ports(1)[0]
        runtime.atomic_write(port_file, json.dumps({"port": port}))
    runtime.atomic_write(
        private / "release.override.json",
        json.dumps(
            {
                "services": {
                    "redis": {
                        "ports": [f"127.0.0.1:{port}:6379"],
                        "networks": ["processing-data", "host-access"],
                    }
                }
            }
        ),
    )
    runtime.compose(state, "up", "-d", "--no-deps", "--no-build", "redis", capture_output=True)
    dsns = {
        owner: env[owner.upper() + "_POSTGRES_DSN"].replace(
            "@postgres:5432/", f"@127.0.0.1:{state['postgres_port']}/"
        )
        for owner in REVISIONS
    }
    data = LocalData(
        dsns["media"],
        dsns["processing"],
        f"redis://:{quote(env['REDIS_PASSWORD'], safe='')}@127.0.0.1:{port}/0",
    )
    config = config_fixture.__wrapped__()
    config["session_end_epoch"] = time.time() + 1800
    config["worker_lifetime_seconds"] = 300
    images = {
        owner: [f"dc2-{owner}:dc2-final-local-e6eff6ee", env[f"DC2_{owner.upper()}_IMAGE"]]
        for owner in REVISIONS
    }
    control = LocalControl(config, state, images)
    deadline = time.monotonic() + 900
    context = Context(
        state["public_url"],
        "ap-southeast-1",
        (env["SOURCE_BUCKET"], env["OUTPUT_BUCKET"]),
        mode="local-fixture",
        fixture_object_origin=state["public_url"],
    )
    import scripts.aws.release as release_module

    original_restore = release_module._restore

    def observed_restore(*args, **kwargs):
        try:
            return original_restore(*args, **kwargs)
        except Exception as exc:
            from scripts.aws.transport import OperationError

            print(
                "Restore failure",
                type(exc).__name__,
                str(exc) if isinstance(exc, (OperationError, ValueError)) else "redacted",
                flush=True,
            )
            raise

    release_module._restore = observed_restore

    class Receipts(list):
        def append(self, value):
            super().append(value)
            runtime.atomic_write(
                report,
                json.dumps(
                    {
                        "mode": "local-services",
                        "status": "INCOMPLETE",
                        "control_plane": "synthetic-offline",
                        "receipts": self,
                        "aws_status": "NOT_RUN",
                        "restore_status": "NOT_RUN",
                    },
                    indent=2,
                )
                + "\n",
            )

    receipts = Receipts()
    with (
        tempfile.TemporaryDirectory(prefix="dc2-private-prep-") as folder,
        Client(context, ca_file=state["ca_file"]) as client,
    ):
        root = Path(folder)
        root.chmod(0o700)
        journal = Journal(
            root / "journal.json",
            station=config["operator_station"],
            environment=config["environment_id"],
        )
        journal.initialize(verified_empty=True, exclusive_station=True)
        with journal.locked() as saved:
            saved.update(session="open", paused=False)
            journal.save(saved)
        ledger = Ledger(mode="local-services")
        bindings = LocalBindings(
            config, control, journal, data, client, ledger, state, deadline=deadline
        )
        control.bindings = bindings
        original_observe, original_warm = data.observe_worker, data.warm_shutdown

        def observed(task, name, **kwargs):
            result = original_observe(task, name, **kwargs)
            print("RQ", task, result, flush=True)
            return result

        def warmed(task, name, **kwargs):
            result = original_warm(task, name, **kwargs)
            print("ACK", task, result, flush=True)
            return result

        data.observe_worker, data.warm_shutdown = observed, warmed
        # Actual finite nonburst worker/RQ command/SQL observer positive warm ack.
        bindings.prewarm(1, deadline=deadline)
        receipts.append({"case": "finite-rq-warm-drain", **bindings.drain(deadline=deadline)})
        for owner in ("processing", "media"):
            for bad in (False, True):
                control.bad = False
                for key in (
                    ("media",) if owner == "media" else ("processing_api", "processing_recovery")
                ):
                    control.call(
                        "ecs",
                        "update-service",
                        {
                            "service": config["services"][key],
                            "desiredCount": 1,
                            "taskDefinition": config["task_definitions"][key],
                        },
                        deadline=deadline,
                    )
                with journal.locked() as saved:
                    saved["worker_definition"] = config["task_definitions"]["worker"]
                    journal.save(saved)
                control.bad = bad
                candidate = artifact(owner, NEW)
                prior = artifact(owner, OLD)
                # Explicit synthetic gate/manifest receipts; actual prior image
                # executes owner SQL compatibility below. No scan claim follows.
                info = json.loads(
                    runtime.run(
                        ["docker", "image", "inspect", images[owner][0]],
                        capture_output=True,
                        text=True,
                    ).stdout
                )[0]
                prior["config_id"] = prior["manifest_config_id"] = info["Id"]
                for name in ("tests", "artifact_test", "scan"):
                    prior[name]["config_id"] = info["Id"]
                compatibility = bindings.prior_compatibility(
                    owner, info["Id"], prior, additive_reviewed=True, deadline=deadline
                )
                if owner == "media":
                    with journal.locked() as saved:
                        saved["paused"] = False
                        journal.save(saved)
                    bindings.prewarm(1, deadline=deadline)
                definitions = {
                    k: v.replace(":1", ":2") for k, v in config["task_definitions"].items()
                }
                print("TRIAL", owner, bad, flush=True)
                outcome = promote(
                    config,
                    control,
                    journal,
                    owner=owner,
                    artifact=candidate,
                    prior_artifact=prior,
                    definitions=definitions,
                    compatibility=compatibility,
                    schema_revision=bindings.schema_revision,
                    readiness=bindings.readiness,
                    public_smoke=None,
                    smoke_workflow=bindings.smoke_workflow,
                    observe=data.observe_worker,
                    warm_shutdown=data.warm_shutdown,
                    deadline=deadline,
                )
                assert outcome["status"] == ("failed-restored" if bad else "promoted"), outcome
                receipts.append(
                    {
                        "case": owner + ("-bad-restore" if bad else "-release"),
                        "status": outcome["status"],
                    }
                )
                if owner == "media":
                    bindings.drain(deadline=deadline)
                with journal.locked() as saved:
                    saved["paused"] = False
                    journal.save(saved)
        control.bad = False

        def proof(deadline):
            saved = json.loads(journal.path.read_text())
            return bindings.proof_locked(saved, deadline)

        roles = (
            f"postgresql://postgres:{quote(env['POSTGRES_PASSWORD'], safe='')}"
            f"@127.0.0.1:{state['postgres_port']}/postgres"
        )
        exported = []

        def export_hook(proof, end):
            outcome = bindings.export_hook(
                proof,
                end,
                private_directory=root / "dumps",
                private_store=root / "objects",
                roles_dsn=roles,
            )
            exported.append(outcome)
            return outcome

        closed = close(
            config,
            control,
            journal,
            pause_intake=bindings.pause_intake,
            observe=data.observe_worker,
            warm_shutdown=data.warm_shutdown,
            quiesce_writers=proof,
            export_hook=export_hook,
            deadline=deadline,
        )
        receipts.append({"case": "close", **closed})
        receipts.append({"case": "private-export", **exported[0]})
        awake = open_session(
            config,
            control,
            journal,
            state_readiness=bindings.state_readiness,
            peer_readiness=lambda d: all(bindings.readiness(o, d) for o in REVISIONS),
            public_readiness=lambda d: client.request("GET", "/api/health", deadline=d)[0] == 200,
            resume_intake=bindings.resume_intake,
            deadline=deadline,
        )
        receipts.append({"case": "wake", "status": awake["status"]})
        report.write_text(
            json.dumps(
                {
                    "mode": "local-services",
                    "control_plane": "synthetic-offline",
                    "operator_source_sha": runtime.run(
                        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
                    ).stdout.strip(),
                    "operator_source_dirty": bool(
                        runtime.run(
                            ["git", "status", "--porcelain"], capture_output=True, text=True
                        ).stdout.strip()
                    ),
                    "artifact_gates": "synthetic control inputs; real scan/registry NOT_RUN",
                    "namespace": state["compose_project"],
                    "receipts": receipts,
                    "ledger": ledger.records,
                    "restore_status": "NOT_RUN",
                    "aws_status": "NOT_RUN",
                },
                indent=2,
            )
            + "\n"
        )
    runtime.compose(state, "down", capture_output=True)  # owned namespace only; no -v


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.run_id, args.report)
