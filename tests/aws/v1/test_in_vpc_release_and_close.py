"""The release CLI and session close on a stack with no SQL station (#150): no AWS, no network.

The transport is the simulated account, whose finite tasks answer the in-VPC probe.
"""

import argparse
import io
import json

import pytest
from test_release_cli import CREDENTIALS, SCOPE, private, promote_args
from test_v1_release import proof

from scripts.aws.transport import OperationError
from scripts.aws.v1 import release_cli, session_cli
from scripts.aws.v1.proof import sim
from scripts.aws.v1.vpc_reader import VpcReader

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def release_files(tmp_path):
    """The private inputs `release promote` reads; its --config is replaced per test."""
    base = tmp_path / "release-inputs"
    base.mkdir(mode=0o700)
    compat = {"owner": "processing", "source_sha": "d" * 40, "target_revision": "0002",
              "additive_only": True, "current_image_compatible": True,
              "prior_image_compatible": True}
    return {
        "config": "unused", "creds": private(base / "creds.json", CREDENTIALS),
        "compat": private(base / "compat.json", compat),
        "bundle": private(base / "bundle.json", {"api": proof("processing", "lambda-api"),
                                                 "worker": proof("processing", "finite-worker")}),
    }


def stack(tmp_path, *faults, sql=False):
    world = sim.SimWorld(faults=faults)
    ctx = sim.build(argparse.Namespace(run_id="t", dry_run=True), session="window", sql=sql,
                    tmp=tmp_path / "state", world=world)
    return world, ctx


def cli(ctx, world, *argv):
    out = io.StringIO()
    code = release_cli.main(
        [*argv, "--config", str(ctx.state_dir / "operator-config.json"), *SCOPE], stdout=out,
        transport_factory=lambda scope: world, clock=world.clock.monotonic,
        sleep=world.clock.sleep)
    return code, json.loads(out.getvalue())


def test_the_schema_action_reads_both_owners_in_the_vpc_without_a_sql_station(tmp_path):
    world, ctx = stack(tmp_path)
    code, out = cli(ctx, world, "schema")
    assert code == 0 and out["result"]["schema"] == {"media": "m0007", "processing": "p0005"}
    assert out["result"]["schema_revision_source"] == "in-vpc-task"
    assert len(out["result"]["schema_reads"]) == 2
    assert [c for c in world.calls[:2]] == [("ecs", "run-task")] * 2  # started together


def test_the_schema_action_dry_run_names_the_in_vpc_task_and_touches_no_transport(tmp_path):
    world, ctx = stack(tmp_path)
    out = io.StringIO()
    code = release_cli.main(
        ["schema", "--config", str(ctx.state_dir / "operator-config.json"), *SCOPE, "--dry-run"],
        stdout=out, transport_factory=lambda scope: pytest.fail("dry-run must not connect"))
    plan = json.loads(out.getvalue())["result"]["planned_calls"]
    assert code == 0 and {p["owner"] for p in plan} == {"media", "processing"}
    assert all(p["source"] == "in-vpc-task" and p["operation"] == "run-task" for p in plan)


def test_a_configured_sql_station_is_still_used_and_labelled_as_such(tmp_path, monkeypatch):
    world, ctx = stack(tmp_path, sql=True)
    seen = {}
    real = release_cli.hooks_for

    def spy(*args, **kwargs):
        seen["hooks"] = real(*args, **kwargs)
        return seen["hooks"]

    monkeypatch.setattr(release_cli, "hooks_for", spy)
    cli(ctx, world, "schema")  # the simulated DSN files are not private, so the read itself fails
    _, _, source, vpc = seen["hooks"]
    assert source == "sql-station" and vpc is None and not world.tasks


def test_a_sql_block_without_a_ca_file_is_still_refused(tmp_path):
    world, ctx = stack(tmp_path)
    path = ctx.state_dir / "operator-config.json"
    config = json.loads(path.read_text())
    config["sql"] = {"media_dsn_file": "/dev/null"}
    path.write_text(json.dumps(config))
    code, out = cli(ctx, world, "schema")
    assert code == 1 and "sql.ca_file" in out["error"]


def test_promote_without_a_sql_station_hands_the_release_an_in_vpc_reader(
        tmp_path, release_files, monkeypatch):
    world, ctx = stack(tmp_path)
    seen = {}

    def fake_promote(config, transport, journal, *, schema_revision, deadline, **kwargs):
        seen["reader"] = schema_revision
        schema_revision.prefetch(("processing", "media"), deadline=deadline)
        seen["revisions"] = [schema_revision("processing", deadline=deadline),
                             schema_revision("media", deadline=deadline)]
        return {"owner": kwargs["owner"], "status": "promoted"}

    monkeypatch.setattr(release_cli, "promote", fake_promote)
    argv = promote_args(release_files)
    argv[argv.index("--config") + 1] = str(ctx.state_dir / "operator-config.json")
    out = io.StringIO()
    code = release_cli.main(argv, stdout=out, transport_factory=lambda scope: world,
                            clock=world.clock.monotonic, sleep=world.clock.sleep)
    result = json.loads(out.getvalue())["result"]
    assert code == 0 and isinstance(seen["reader"], VpcReader)
    assert seen["revisions"] == ["p0005", "m0007"]
    assert result["schema_revision_source"] == "in-vpc-task" and len(result["schema_reads"]) == 2


def test_a_failed_release_still_names_the_schema_source_and_leaves_no_read_task_running(
        tmp_path, release_files, monkeypatch):
    world, ctx = stack(tmp_path)

    def failing(config, transport, journal, *, schema_revision, deadline, **kwargs):
        schema_revision.prefetch(("processing", "media"), deadline=deadline)
        raise OperationError("Release incomplete; private intent retained for restore")

    monkeypatch.setattr(release_cli, "promote", failing)
    argv = promote_args(release_files)
    argv[argv.index("--config") + 1] = str(ctx.state_dir / "operator-config.json")
    out = io.StringIO()
    code = release_cli.main(argv, stdout=out, transport_factory=lambda scope: world,
                            clock=world.clock.monotonic, sleep=world.clock.sleep)
    body = json.loads(out.getvalue())
    assert code == 1 and body["schema_revision_source"] == "in-vpc-task"
    assert [c for c in world.calls if c[1] == "stop-task"] == [("ecs", "stop-task")] * 2


def test_an_older_stack_without_migration_outputs_uses_the_pinned_definition_for_its_owner(
        tmp_path, release_files, monkeypatch):
    world, ctx = stack(tmp_path)
    outputs_path = ctx.state_dir / "outputs.json"
    outputs = json.loads(outputs_path.read_text())
    for key in [k for k in outputs if k.endswith("MigrationTaskDefinitionArn")]:
        del outputs[key]
    outputs_path.write_text(json.dumps(outputs))
    seen = {}

    def fake_promote(config, transport, journal, *, schema_revision, **kwargs):
        seen["definitions"] = dict(schema_revision.definitions)
        return {"status": "promoted"}

    monkeypatch.setattr(release_cli, "promote", fake_promote)
    argv = promote_args(release_files)
    argv[argv.index("--config") + 1] = str(ctx.state_dir / "operator-config.json")
    release_cli.main(argv, stdout=io.StringIO(), transport_factory=lambda scope: world,
                     clock=world.clock.monotonic, sleep=world.clock.sleep)
    assert list(seen["definitions"]) == ["processing"]


# ---- session close -------------------------------------------------------------------------
def test_close_can_prove_the_drain_from_in_vpc_counts_instead_of_an_attested_file(tmp_path):
    world, ctx = stack(tmp_path)
    owner, counts = session_cli.build_hooks(
        ctx.data, ctx.hooks, world, dry_run=False, config=ctx.config, in_vpc=True,
        clock=world.clock.monotonic, sleep=world.clock.sleep)
    assert counts.drain(deadline=world.clock.monotonic() + 600) is True
    assert counts.outcomes(deadline=world.clock.monotonic() + 600) == {
        "queued": 0, "succeeded": 3, "failed": 1, "abandoned": 0, "cancelled": 0}
    assert world.vpc_reads and all(r[:2] == ("processing", "attempts") for r in world.vpc_reads)


def test_in_vpc_counts_win_over_a_stale_attested_file_when_asked_for(tmp_path):
    world, ctx = stack(tmp_path)
    ctx.data["counts_file"] = "/nonexistent/attested.json"
    _, counts = session_cli.build_hooks(
        ctx.data, ctx.hooks, world, dry_run=False, config=ctx.config, in_vpc=True,
        clock=world.clock.monotonic, sleep=world.clock.sleep)
    assert counts.outcomes(deadline=world.clock.monotonic() + 600)["succeeded"] == 3


def test_in_vpc_counts_only_apply_to_close(tmp_path):
    world, ctx = stack(tmp_path)
    with pytest.raises(SystemExit):
        session_cli.main(["open", "--config", str(ctx.state_dir / "operator-config.json"),
                          *SCOPE, "--in-vpc-counts"])
