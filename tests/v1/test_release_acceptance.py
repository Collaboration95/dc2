"""Release, rollback and session close/wake against real local SQL.

Real: both PostgreSQL databases, the owners' alembic history (really stepped back and
re-applied), the runtime-role reads, the actual repair handlers, the SQS-backed work
queue contents and the finite encoder command the session would hand to Fargate.
Emulated: the Lambda and ECS control plane (an in-memory transport that records alias,
concurrency and RunTask calls) and Moto for SQS/S3. A fake transport proves our state
machine, not AWS API behaviour, IAM or timing, and the run manifest says so.
"""

import copy
import os
import subprocess
import sys
import time
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]

TABLE_OF_RECORD = {"media": "users", "processing": "jobs"}


def require_attachment():
    if not os.environ.get("V1_RUNTIME_CONFIG"):
        pytest.skip("Explicit Lead C runtime attachment required")


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_owner_release_applies_a_real_migration_and_failed_candidate_restores_aliases(
    tmp_path, owner
):
    require_attachment()
    from publisher.client import PublicClient
    from scripts.aws.transport import OperationError
    from scripts.aws.v1.release import promote, restore
    from scripts.dev.v1_acceptance import (
        app_runtime,
        migrate,
        script_revisions,
        sql_fetch,
        step_back,
    )
    from tests.aws.v1.test_v1_release import setup

    previous, head = script_revisions(owner)
    peer = "processing" if owner == "media" else "media"
    peer_head = script_revisions(peer)[1]
    with app_runtime(os.environ["V1_RUN_ID"]) as runtime:
        client = PublicClient(
            runtime["url"] + "/api/media", tmp_path / "cookies", ca_file=runtime["ca"]
        )
        identity = client.authenticate(
            "register", f"release-{uuid4().hex}@example.com", "local-release-password"
        )

        def revision(which, **kwargs):
            return sql_fetch(runtime, which, "SELECT version_num FROM alembic_version")[0][0]

        def rows(which):
            return sql_fetch(runtime, which, f"SELECT count(*) FROM {TABLE_OF_RECORD[which]}")[0][
                0
            ]

        def smoke(*args, **kwargs):
            return (
                client.identity() == identity["id"]
                and client.request("GET", "health")["service"] == "media"
            )

        def release_rig(name):
            station = tmp_path / name
            station.mkdir(mode=0o700)
            config, aws, journal, args = setup.__wrapped__(station)
            original = aws.call
            launched = []

            def call(service, operation, payload, **kwargs):
                # The fake ECS "task" is the owner's real migrator running alembic.
                if service == "ecs" and operation == "run-task":
                    migrate(owner, runtime["env"])
                    launched.append(owner)
                return original(service, operation, payload, **kwargs)

            aws.call = call
            return config, aws, journal, args, launched

        try:
            # A schema one revision behind makes the promotion's migration do real work.
            step_back(owner, runtime["env"])
            assert revision(owner) == previous != head
            peer_schema, rows_before = revision(peer), rows(owner)
            config, aws, journal, args, launched = release_rig("station")
            peer_aliases = {
                name: copy.deepcopy(aws.aliases[name])
                for name in config["owner_functions"][peer].values()
            }
            options = args(owner)
            options.update(target_revision=head, schema_revision=revision, public_smoke=smoke)
            receipt = promote(config, aws, journal, **options)
            assert receipt["status"] == "promoted"
            assert launched == [owner] and revision(owner) == head
            assert revision(peer) == peer_schema == peer_head
            assert rows(owner) == rows_before
            assert all(aws.aliases[name]["FunctionVersion"] == "2" for name in receipt["versions"])
            assert {name: aws.aliases[name] for name in peer_aliases} == peer_aliases

            # Failed candidate: migrate forward again, fail the public smoke, then roll back.
            step_back(owner, runtime["env"])
            config2, failed, journal2, args2, launched2 = release_rig("failed-station")
            bad = args2(owner)
            bad.update(
                target_revision=head,
                schema_revision=revision,
                public_smoke=lambda *a, **kw: False,
            )
            with pytest.raises(OperationError, match="private intent retained"):
                promote(config2, failed, journal2, **bad)
            assert launched2 == [owner] and revision(owner) == head
            restored = restore(
                config2,
                failed,
                journal2,
                schema_revision=revision,
                quiescent=lambda *a, **kw: True,
                public_smoke=smoke,
                deadline=bad["deadline"],
            )
            assert restored["status"] == "restored" and restored["schema_rollback"] is False
            # Image rollback never undoes a migration: the schema stays forward.
            assert revision(owner) == head and revision(peer) == peer_schema
            assert all(value["FunctionVersion"] == "1" for value in failed.aliases.values())
            assert rows(owner) == rows_before
        finally:
            client.close()


def test_session_close_and_wake_keep_real_queued_work_and_run_one_finite_encode(tmp_path):
    require_attachment()
    from media.handlers import repair_handler as media_repair
    from processing.handlers import repair_handler as processing_repair
    from publisher.client import PublicClient
    from scripts.aws.journal import Journal
    from scripts.aws.transport import OperationError
    from scripts.aws.v1.session import Session
    from scripts.dev.v1_acceptance import (
        ROOT,
        app_runtime,
        pump,
        script_revisions,
        short_video,
        sql_fetch,
    )
    from scripts.dev.v1_verify import sdk
    from tests.v1.test_session import Fake

    source = short_video(tmp_path / "wake.mp4")
    with app_runtime(os.environ["V1_RUN_ID"]) as runtime:
        client = PublicClient(
            runtime["url"] + "/api/media", tmp_path / "cookies", ca_file=runtime["ca"]
        )
        sqs = sdk(runtime["data"], "sqs")
        work_queue = runtime["data"]["resources"]["queues"]["work"]
        fake = Fake()
        private = tmp_path / "private"
        private.mkdir(mode=0o700)
        journal = Journal(private / "session.json", station="station", environment="v1-local")
        journal.initialize(verified_empty=True, exclusive_station=True)
        session = Session(
            {
                "operator_station": "station",
                "environment_id": "v1-local",
                "functions": {"media-api": 2, "processing-command": 2, "authorizer": 1},
                "intake_functions": ["media-api"],
                "mappings": ["commands", "results"],
                "schedules": ["media-repair", "processing-repair"],
                "cluster": "local",
                "task_definitions": {"worker": "worker:1"},
                "network": {
                    "subnets": ["subnet-local"],
                    "security_groups": ["sg-local"],
                    "assign_public_ip": "ENABLED",
                },
                "session_end_epoch": time.time() + 600,
                "worker_lifetime_seconds": 120,
            },
            fake,
            journal,
        )

        def ready(**kwargs):
            # Owning SQL answers as its own runtime role, at its own head revision.
            return all(
                sql_fetch(runtime, owner, "SELECT version_num FROM alembic_version")[0][0]
                == script_revisions(owner)[1]
                for owner in ("media", "processing")
            )

        def repair(**kwargs):
            # The actual repair Lambdas, invoked in-process with no remaining-time budget.
            return isinstance(media_repair({}, None), dict) and isinstance(
                processing_repair({}, None), dict
            )

        def active_attempts():
            return sql_fetch(
                runtime, "processing", "SELECT count(*) FROM attempts WHERE state='processing'"
            )[0][0]

        def drain(**kwargs):
            stopped = all(task["lastStatus"] == "STOPPED" for task in fake.tasks.values())
            return stopped and active_attempts() == 0

        def outcomes(**kwargs):
            counts = {
                "queued": "status='queued' AND deleted_at IS NULL",
                "succeeded": "status='done' AND deleted_at IS NULL",
                "failed": "status='failed' AND deleted_at IS NULL",
                "cancelled": "deleted_at IS NOT NULL",
            }
            found = {
                name: sql_fetch(runtime, "processing", f"SELECT count(*) FROM jobs WHERE {where}")[
                    0
                ][0]
                for name, where in counts.items()
            }
            found["abandoned"] = sql_fetch(
                runtime, "processing", "SELECT count(*) FROM attempts WHERE state='abandoned'"
            )[0][0]
            return found

        def deadline():
            return time.monotonic() + 30

        def queued_messages():
            attributes = sqs.get_queue_attributes(
                QueueUrl=work_queue, AttributeNames=["ApproximateNumberOfMessages"]
            )["Attributes"]
            return int(attributes["ApproximateNumberOfMessages"])

        try:
            client.authenticate("register", f"wake-{uuid4().hex}@example.com", "local-wake-pass")
            opened = session.open(ready=ready, repair=repair, deadline=deadline())
            assert opened["worker_starts"] == 0

            # Real work arrives while the session is open, but no worker is started for it.
            asset = client.upload(source, str(uuid4()))
            pump(runtime, results=False)
            assert queued_messages() >= 1
            assert not any(op == "run-task" for _, op, _ in fake.calls)

            closed = session.close(drain=drain, outcomes=outcomes, deadline=deadline())
            assert closed["queued_work"] == "retained"
            assert closed["database_pause"] == "NOT_OBSERVED"
            assert set(fake.functions.values()) == {0}
            assert set(fake.mappings.values()) == {"Disabled"}
            assert set(fake.rules.values()) == {"DISABLED"}
            # Close recorded SQL truth and neither purged the queue nor touched the work.
            recorded = journal.path.read_text()
            assert '"close_outcomes"' in recorded
            assert queued_messages() >= 1
            # Media has not seen a result yet, so it still reports the accepted projection;
            # Processing's own SQL holds the queued attempt that close must not disturb.
            assert client.request("GET", f"jobs/{asset}")["status"] in {"accepted", "queued"}
            assert outcomes()["queued"] >= 1
            assert all(op not in {"purge-queue", "stop-db-cluster"} for _, op, _ in fake.calls)
            with pytest.raises(OperationError):
                session.batch(count=1, deadline=deadline())

            # Wake: readiness and repair run against the same retained SQL, then one batch.
            woken = session.open(ready=ready, repair=repair, deadline=deadline())
            assert woken["session"] == "open"
            # Repair re-stages every queued attempt in this SQL volume, including ones an
            # earlier interrupted run left behind, and a finite task takes exactly one
            # message. Late work stays queued until another explicit batch, so issue batches
            # until this asset's turn comes; the bound keeps the loop finite.
            for _ in range(8):
                tasks = session.batch(count=1, deadline=deadline())
                assert len(tasks) == 1
                launch = [p for _, op, p in fake.calls if op == "run-task"][-1]
                command = launch["overrides"]["containerOverrides"][0]["command"]
                assert command[:3] == ["python", "-m", "processing.v1_worker"]
                # The would-be Fargate task: the exact command the session issued, run locally.
                ran = subprocess.run(
                    [sys.executable, *command[1:]],
                    cwd=ROOT,
                    env=runtime["env"],
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                assert ran.returncode in {0, 1}, f"Session encoder exited {ran.returncode}"
                fake.tasks[tasks[0]]["lastStatus"] = "STOPPED"
                pump(runtime)
                if client.status(asset)["status"] == "done":
                    break
            assert client.status(asset)["status"] == "done"

            final = session.close(drain=drain, outcomes=outcomes, deadline=deadline())
            assert final["queued_work"] == "retained"
            assert set(fake.functions.values()) == {0}
            client.delete(asset)
            pump(runtime)
        finally:
            client.close()
