"""The in-VPC schema/count reader (#150) against the simulated account and a fake probe driver.

No AWS call and no database: the host side runs against `SimWorld` (virtual time), the probe's
database access against a fake `asyncpg.connect`.
"""

import argparse
import asyncio
import io
import json
import os
import ssl
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.aws.transport import OperationError, safe_record
from scripts.aws.v1 import vpc_probe, vpc_reader
from scripts.aws.v1.proof import sim
from scripts.aws.v1.transport import OperatorTransport
from scripts.aws.v1.vpc_reader import VpcReader

pytestmark = pytest.mark.unmeasured
ROOT = Path(__file__).resolve().parents[3]


def rig(tmp_path, *faults, **world_kwargs):
    world = sim.SimWorld(faults=faults, **world_kwargs)
    ctx = sim.build(
        argparse.Namespace(run_id="t", dry_run=True),
        session="window",
        sql=False,
        tmp=tmp_path / "state",
        world=world,
    )
    reader = VpcReader(ctx.config, world, clock=world.clock.monotonic, sleep=world.clock.sleep)
    return world, ctx, reader


def deadline(world, seconds=900):
    return world.clock.monotonic() + seconds


# ---- host side ---------------------------------------------------------------------------
def test_an_owners_revision_is_read_from_the_log_line_of_a_finite_task(tmp_path):
    world, _, reader = rig(tmp_path)
    assert reader.schema("media", deadline=deadline(world)) == "m0007"
    assert reader("processing", deadline=deadline(world)) == "p0005"
    assert [r[:2] for r in world.vpc_reads] == [("media", "schema"), ("processing", "schema")]
    receipt = reader.receipt()
    assert receipt["schema_revision_source"] == "in-vpc-task"
    assert all(r["tls_verified"] and r["tls_protocol"] == "TLSv1.3" for r in receipt["reads"])


def test_each_owner_is_read_with_its_own_deployed_migration_definition(tmp_path):
    world, ctx, reader = rig(tmp_path)
    reader.schema("media", deadline=deadline(world))
    reader.schema("processing", deadline=deadline(world))
    assert [r[2] for r in world.vpc_reads] == [
        ctx.config["migration_definitions"]["media"],
        ctx.config["migration_definitions"]["processing"],
    ]


def test_the_task_override_carries_no_secret_and_fits_the_ecs_limit(tmp_path):
    world, _, reader = rig(tmp_path)
    seen = []
    original = world.call
    world.call = lambda *a, **k: (
        (seen.append(a) if a[1] == "run-task" else None) or original(*a, **k)
    )
    reader.schema("media", deadline=deadline(world))
    payload = seen[0][2]
    safe_record(payload)  # the operator transport refuses anything credential-looking
    overrides = payload["overrides"]["containerOverrides"][0]
    names = {e["name"] for e in overrides["environment"]}
    assert names == {"DC2_SCRIPT", "DC2_OWNER", "DC2_MODE", "DC2_RESUME_SECONDS"}
    text = json.dumps(payload["overrides"])
    assert (
        len(text) < 8192
        and "postgres" not in text.lower()
        and "dsn" not in overrides["command"][-1].lower()
    )
    assert overrides["command"][:2] == ["python", "-c"]


def test_the_shipped_wrapper_runs_the_probe_and_a_bad_environment_prints_a_class_name(tmp_path):
    packed, command = vpc_reader.ship()
    assert "=" not in packed
    env = {**os.environ, "DC2_SCRIPT": packed, "DC2_OWNER": "nobody", "DC2_MODE": "schema"}
    done = subprocess.run(
        [sys.executable, *command[1:]],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
        check=False,
    )
    assert done.returncode == 1
    line = next(x for x in done.stdout.splitlines() if x.startswith("DC2-VPC-READ "))
    assert json.loads(line.split(" ", 1)[1])["error"] == "ValueError" and not done.stderr


def test_a_slow_resume_is_waited_out_inside_the_task_and_still_reads_the_revision(tmp_path):
    world, _, reader = rig(tmp_path, "read-slow-resume")
    started = world.clock.monotonic()
    assert reader.schema("media", deadline=deadline(world)) == "m0007"
    assert world.clock.monotonic() - started >= 140


def test_a_task_that_never_stops_is_given_up_on_and_stopped(tmp_path):
    world, _, reader = rig(tmp_path, "read-hang")
    started = world.clock.monotonic()
    with pytest.raises(OperationError, match="did not finish in time"):
        reader.schema("media", deadline=deadline(world, 3600))
    assert ("ecs", "stop-task") in world.calls
    assert world.clock.monotonic() - started < 400  # start 180 + resume 150 + slack 30
    assert all(t["stopped_at"] is not None for t in world.tasks.values())


def test_an_unverified_tls_session_is_never_accepted(tmp_path):
    world, _, reader = rig(tmp_path, "read-tls-unverified")
    with pytest.raises(OperationError, match="TLS was not verified"):
        reader.schema("media", deadline=deadline(world))


def test_a_database_that_cannot_be_reached_reports_a_class_name_and_nothing_else(tmp_path):
    world, _, reader = rig(tmp_path, "read-db-unreachable")
    with pytest.raises(OperationError, match="TimeoutError") as error:
        reader.schema("media", deadline=deadline(world))
    assert "postgres" not in str(error.value).lower()


def test_a_task_that_printed_no_line_fails_with_its_exit_code_after_a_bounded_wait(tmp_path):
    world, _, reader = rig(tmp_path, "read-no-log")
    started = world.clock.monotonic()
    with pytest.raises(OperationError, match="no result line"):
        reader.schema("media", deadline=deadline(world))
    assert world.clock.monotonic() - started < 80


def test_more_than_one_alembic_head_is_refused(tmp_path):
    world, _, reader = rig(tmp_path, "read-two-heads")
    with pytest.raises(OperationError, match="Exactly one Alembic head"):
        reader.schema("media", deadline=deadline(world))


def test_an_owner_without_a_known_migration_definition_is_a_clear_refusal(tmp_path):
    world, ctx, _ = rig(tmp_path)
    bare = {k: v for k, v in ctx.config.items() if k != "migration_definitions"}
    reader = VpcReader(bare, world, clock=world.clock.monotonic, sleep=world.clock.sleep)
    with pytest.raises(OperationError, match="MigrationTaskDefinitionArn"):
        reader.schema("media", deadline=deadline(world))
    assert not world.tasks


def test_prefetched_reads_start_together_so_two_owners_cost_one_task_time(tmp_path):
    world, _, reader = rig(tmp_path)
    started = world.clock.monotonic()
    reader.schema("media", deadline=deadline(world))
    single = world.clock.monotonic() - started

    world, _, reader = rig(tmp_path / "second")
    started = world.clock.monotonic()
    reader.prefetch(("media", "processing"), deadline=deadline(world))
    assert [c for c in world.calls if c[1] == "run-task"] == [("ecs", "run-task")] * 2
    assert reader.schema("media", deadline=deadline(world)) == "m0007"
    assert reader.schema("processing", deadline=deadline(world)) == "p0005"
    assert world.clock.monotonic() - started < single * 1.5
    assert len(reader.receipt()["reads"]) == 2 and not reader.pending


def test_abandoning_stops_a_prefetched_read_that_was_never_collected(tmp_path):
    world, _, reader = rig(tmp_path)
    reader.prefetch(("media", "processing"), deadline=deadline(world))
    reader.abandon()
    assert [c for c in world.calls if c[1] == "stop-task"] == [("ecs", "stop-task")] * 2
    assert not reader.pending


def test_attempt_counts_are_read_for_processing_and_validated(tmp_path):
    world, _, reader = rig(tmp_path)
    counts = reader.attempt_counts(deadline(world))
    assert counts["succeeded"] == 3 and counts["processing"] == 0
    assert world.vpc_reads[0][:2] == ("processing", "attempts")
    world.attempt_counts["mystery"] = 1
    with pytest.raises(OperationError, match="attempt counts"):
        reader.attempt_counts(deadline(world))


# ---- the real operator transport accepts exactly these calls ---------------------------------
def client(**methods):
    config = SimpleNamespace(retries={"total_max_attempts": 1}, connect_timeout=2, read_timeout=3)
    return SimpleNamespace(
        meta=SimpleNamespace(region_name="ap-southeast-1", config=config), **methods
    )


def test_the_operator_transport_admits_every_call_the_reader_makes(tmp_path):
    world, ctx, _ = rig(tmp_path)
    ecs = client(
        run_task=lambda **kw: world.call("ecs", "run-task", kw),
        describe_tasks=lambda **kw: world.call("ecs", "describe-tasks", kw),
        describe_task_definition=lambda **kw: world.call("ecs", "describe-task-definition", kw),
        stop_task=lambda **kw: world.call("ecs", "stop-task", kw),
    )
    logs = client(get_log_events=lambda **kw: world.call("logs", "get-log-events", kw))
    transport = OperatorTransport(
        {"ecs": ecs, "logs": logs},
        identity={"Account": "123456789012"},
        account="123456789012",
        region="ap-southeast-1",
        clock=world.clock.monotonic,
    )
    reader = VpcReader(ctx.config, transport, clock=world.clock.monotonic, sleep=world.clock.sleep)
    assert reader.schema("processing", deadline=deadline(world)) == "p0005"


# ---- the probe, with a fake driver ----------------------------------------------------------
class Connection:
    def __init__(self, rows, ssl_on=True):
        self.rows, self.ssl_on, self.closed = rows, ssl_on, False

    async def fetchrow(self, sql):
        return {"ssl": self.ssl_on, "version": "TLSv1.3"}

    async def fetch(self, sql):
        return self.rows["alembic_version" if "alembic_version" in sql else "attempts"]

    async def close(self):
        self.closed = True


def run_probe(monkeypatch, connect, *, owner="media", mode="schema", resume="0"):
    import asyncpg

    secret = "postgresql+asyncpg://role:S3CRETPW@db.example.internal:5432/media_db"
    for name, value in {
        "DC2_OWNER": owner,
        "DC2_MODE": mode,
        "DC2_RESUME_SECONDS": resume,
        "DB_SSL_CA_FILE": str(ROOT / "deploy/v1/global-bundle.pem"),
        f"{owner.upper()}_MIGRATION_DSN": secret,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(asyncpg, "connect", connect)
    monkeypatch.setattr(vpc_probe, "RETRY_SECONDS", 0)
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = asyncio.run(vpc_probe.main())
    monkeypatch.undo()
    assert "S3CRETPW" not in out.getvalue() and "db.example.internal" not in out.getvalue()
    line = next(x for x in out.getvalue().splitlines() if x.startswith("DC2-VPC-READ "))
    return code, json.loads(line.split(" ", 1)[1])


def test_the_probe_verifies_tls_with_a_required_chain_and_hostname_then_reads_the_head(monkeypatch):
    seen = {}

    async def connect(dsn, **kwargs):
        seen.update(dsn=dsn, context=kwargs["ssl"])
        return Connection({"alembic_version": [("0007_media",)]})

    code, result = run_probe(monkeypatch, connect)
    assert code == 0 and result["revision"] == "0007_media" and result["heads"] == 1
    assert result["tls"] == {"verified": True, "server_reports_ssl": True, "protocol": "TLSv1.3"}
    assert seen["dsn"].startswith("postgresql://")  # the driver form of the SQLAlchemy DSN
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED and seen["context"].check_hostname


def test_a_server_that_does_not_report_ssl_is_not_called_verified(monkeypatch):
    async def connect(dsn, **kwargs):
        return Connection({"alembic_version": [("0007",)]}, ssl_on=False)

    _, result = run_probe(monkeypatch, connect)
    assert result["tls"]["verified"] is False


def test_the_probe_retries_while_aurora_resumes_then_connects(monkeypatch):
    calls = []

    async def connect(dsn, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("starting up")
        return Connection({"alembic_version": [("0007",)]})

    code, result = run_probe(monkeypatch, connect, resume="3600")
    assert code == 0 and result["connect_attempts"] == 3


def test_a_certificate_failure_is_permanent_and_prints_only_its_class(monkeypatch):
    calls = []

    async def connect(dsn, **kwargs):
        calls.append(1)
        raise ssl.SSLCertVerificationError("hostname role:S3CRETPW mismatch")

    code, result = run_probe(monkeypatch, connect, resume="3600")
    assert code == 1 and result == {
        "ok": False,
        "owner": "media",
        "mode": "schema",
        "error": "SSLCertVerificationError",
    }
    assert len(calls) == 1


def test_the_probe_reads_attempt_counts_for_the_drain_proof(monkeypatch):
    async def connect(dsn, **kwargs):
        return Connection({"attempts": [("succeeded", 4), ("processing", 0)]})

    code, result = run_probe(monkeypatch, connect, owner="processing", mode="attempts")
    assert code == 0 and result["counts"] == {"succeeded": 4, "processing": 0}
    assert result["unknown_states"] == []
