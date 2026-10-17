"""The release harness (#65) against a scripted release CLI, the summary writer and the CLI."""

import argparse
import dataclasses
import io
import json
import stat

import pytest

from scripts.aws.v1 import evidence
from scripts.aws.v1.proof import release, sim, summary
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, Proof, ProofError

pytestmark = pytest.mark.unmeasured

IMAGE = {"bundle": "b.zip", "image_uri": "uri", "compat_evidence": "c.json"}


def plan_file(tmp_path, **changes):
    plan = {"owner": "media", "migration_definition": "task:1", "target_revision": "0002",
            "good": {**IMAGE, "image_uri": "good"}, "baseline": {**IMAGE, "image_uri": "base"}}
    plan.update(changes)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


class ScriptedRelease:
    """A release CLI stand-in that keeps an alias table and takes virtual time per action."""

    def __init__(self, clock, *, peer_moves=False, slow=0, bad_restores=True,
                 peer_schema_moves=False, schema_fails=False, source="in-vpc-task",
                 bad_stage="smoke", abandon_ok=True):
        self.clock, self.peer_moves, self.slow = clock, peer_moves, slow
        self.bad_restores, self.bad_stage, self.abandon_ok = bad_restores, bad_stage, abandon_ok
        self.pending = None
        self.peer_schema_moves, self.schema_fails, self.source = (
            peer_schema_moves, schema_fails, source)
        self.table = {"media-a": {"owner": "media", "version": "1"},
                      "proc-a": {"owner": "processing", "version": "7"}}
        self.schema = {"media": "m0002", "processing": "p0001"}
        self.calls, self.argvs = [], []

    def __call__(self, argv, *, environ, transport_factory, stdout, http, clock=None, sleep=None):
        action = argv[0]
        self.calls.append(action)
        self.argvs.append(argv)
        self.clock.sleep(self.slow or 30)
        smoke = {"checks": {"login": "PASS", "upload": "PASS"}}
        source = {"schema_revision_source": self.source, "schema_reads": [{"seconds": 40.0}]}
        if action == "status":
            body = {"ok": True, "result": {"aliases": json.loads(json.dumps(self.table)),
                                           "pending_release": self.pending}}
        elif action == "schema":
            if self.schema_fails:
                print(json.dumps({"ok": False, "error": "In-VPC read failed: TimeoutError"}),
                      file=stdout)
                return 1
            body = {"ok": True, "result": {"schema": dict(self.schema), **source}}
            if self.peer_schema_moves and "promote" in self.calls:
                body["result"]["schema"]["processing"] = "p0002"
        elif action == "promote":
            image = argv[argv.index("--image-uri") + 1]
            if image == "bad":
                # Like the real status summary: a migration failure leaves nothing moved, a
                # smoke failure leaves a migrated, moved intent in the restoring phase.
                self.pending = ({"phase": "preparing", "migration_complete": False, "moved": []}
                                if self.bad_stage == "migration" else
                                {"phase": "restoring", "migration_complete": True,
                                 "moved": ["media-a"]})
                body, code = {"ok": False, "error": "smoke failed"}, 1
                print(json.dumps(body), file=stdout)
                return code
            self.table["media-a"]["version"] = {"good": "2", "base": "1"}[image]
            if self.peer_moves:
                self.table["proc-a"]["version"] = "8"
            body = {"ok": True, "result": {"status": "promoted", "smoke": smoke, **source}}
        elif action == "abandon":
            if not self.abandon_ok or not self.pending:
                print(json.dumps({"ok": False, "error": "Live alias moved"}), file=stdout)
                return 1
            self.pending = None
            body = {"ok": True, "result": {"status": "abandoned", **source}}
        else:  # restore
            if self.pending and not self.pending["migration_complete"]:
                print(json.dumps({"ok": False, "error": "Reconcile/finish migration before "
                                  "restoration"}), file=stdout)
                return 1
            self.pending = None
            body = {"ok": True, "result": {"status": "restored", "smoke": smoke, **source}}
        print(json.dumps(body), file=stdout)
        return 0


def live_ctx(tmp_path, scripted=None, **fake):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", tmp=tmp_path / "state")
    scripted = scripted or ScriptedRelease(ctx.world.clock, **fake)
    # A live-mode context over the simulated plumbing: only the release CLI is scripted.
    return dataclasses.replace(ctx, simulated=False, release_main=scripted), scripted


def statuses(proof):
    return {name: step["status"] for name, step in proof.doc["steps"].items()}


# ---- #65 release -----------------------------------------------------------------------
def test_a_good_promotion_and_its_rollback_leave_the_peer_untouched_and_pass(tmp_path):
    ctx, _ = live_ctx(tmp_path)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof) == {"baseline": PASS, "promote-good": PASS, "rollback": PASS,
                               "owner-isolation": PASS, "bad-candidate-restore": NOT_RUN}
    assert proof.overall() == "PARTIAL"  # the optional failing candidate was not supplied


def test_a_promotion_that_moves_the_peer_owners_alias_fails_the_isolation_checks(tmp_path):
    ctx, _ = live_ctx(tmp_path, peer_moves=True)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["promote-good"] == FAIL
    assert statuses(proof)["owner-isolation"] == FAIL


def test_a_promotion_slower_than_its_gate_fails_even_when_it_worked(tmp_path):
    ctx, _ = live_ctx(tmp_path, slow=release.GOOD_GATE_SECONDS + 1)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["promote-good"] == FAIL
    assert proof.doc["steps"]["promote-good"]["public"]["within_gate"] is False


def test_a_failing_candidate_is_restored_inside_the_gate_and_counts_as_proof(tmp_path):
    ctx, scripted = live_ctx(tmp_path)
    plan = plan_file(tmp_path, bad={**IMAGE, "image_uri": "bad"})
    proof = release.run(ctx, plan_path=plan)
    public = proof.doc["steps"]["bad-candidate-restore"]["public"]
    assert statuses(proof)["bad-candidate-restore"] == PASS
    assert public["candidate_failed_as_expected"] and public["aliases_restored"]
    assert public["failed_stage"] == "smoke"
    assert "restore" in scripted.calls and "abandon" not in scripted.calls


def test_a_candidate_that_fails_its_migration_is_abandoned_and_the_step_fails(tmp_path):
    ctx, scripted = live_ctx(tmp_path, bad_stage="migration")
    plan = plan_file(tmp_path, bad={**IMAGE, "image_uri": "bad"})
    proof = release.run(ctx, plan_path=plan)
    step = proof.doc["steps"]["bad-candidate-restore"]
    public = step["public"]
    assert step["status"] == FAIL
    assert public["failed_stage"] == "migration" and public["abandoned"] is True
    assert public["reason"] == release.MIGRATION_STAGE_REASON
    assert public["pending_release_after"] is False and public["aliases_restored"]
    assert "abandon" in scripted.calls and "restore" not in scripted.calls
    assert proof.overall() == "FAIL"


def test_a_migration_failure_that_abandon_refuses_is_recorded_as_not_abandoned(tmp_path):
    ctx, scripted = live_ctx(tmp_path, bad_stage="migration", abandon_ok=False)
    plan = plan_file(tmp_path, bad={**IMAGE, "image_uri": "bad"})
    proof = release.run(ctx, plan_path=plan)
    public = proof.doc["steps"]["bad-candidate-restore"]["public"]
    assert proof.doc["steps"]["bad-candidate-restore"]["status"] == FAIL
    assert public["failed_stage"] == "migration" and public["abandoned"] is False
    assert public["pending_release_after"] is True


def test_the_release_steps_run_without_a_sql_station_and_record_the_in_vpc_source(tmp_path):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", sql=False, tmp=tmp_path / "state")
    scripted = ScriptedRelease(ctx.world.clock)
    ctx = dataclasses.replace(ctx, simulated=False, release_main=scripted)
    assert not ctx.data.get("sql")
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof) == {"baseline": PASS, "promote-good": PASS, "rollback": PASS,
                               "owner-isolation": PASS, "bad-candidate-restore": NOT_RUN}
    steps = proof.doc["steps"]
    assert steps["baseline"]["public"]["schema_revision_source"] == "in-vpc-task"
    assert steps["promote-good"]["public"]["schema_revision_source"] == "in-vpc-task"
    assert steps["promote-good"]["public"]["schema_reads"] == 1
    assert steps["owner-isolation"]["public"]["peer_schema_unchanged"] is True


def test_a_promotion_that_does_not_say_where_the_schema_was_read_from_fails(tmp_path):
    ctx, _ = live_ctx(tmp_path, source=None)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["promote-good"] == FAIL


def test_a_sql_station_remains_a_valid_schema_source(tmp_path):
    ctx, _ = live_ctx(tmp_path, source="sql-station")
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["promote-good"] == PASS


def test_an_unreadable_baseline_schema_fails_the_baseline_without_hiding_why(tmp_path):
    ctx, _ = live_ctx(tmp_path, schema_fails=True)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["baseline"] == FAIL
    assert proof.doc["steps"]["baseline"]["public"]["schema_read"] is False
    assert "TimeoutError" in proof.doc["steps"]["baseline"]["private"]["error"]


def test_a_peer_schema_that_changed_during_the_releases_fails_the_isolation_step(tmp_path):
    ctx, _ = live_ctx(tmp_path, peer_schema_moves=True)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["owner-isolation"] == FAIL
    public = proof.doc["steps"]["owner-isolation"]["public"]
    assert public["peer_schema_unchanged"] is False and public["peer_unchanged_at_every_snapshot"]


def test_each_image_is_promoted_with_its_own_migration_definition(tmp_path):
    ctx, scripted = live_ctx(tmp_path)
    good = {**IMAGE, "image_uri": "good", "migration_definition": "task:2"}
    base = {**IMAGE, "image_uri": "base", "migration_definition": "task:1"}
    release.run(ctx, plan_path=plan_file(tmp_path, good=good, baseline=base))
    used = {a[a.index("--image-uri") + 1]: a[a.index("--migration-definition") + 1]
            for a in scripted.argvs if a[0] == "promote"}
    assert used == {"good": "task:2", "base": "task:1"}


def test_a_simulated_release_only_exercises_the_offline_gates_and_proves_nothing(tmp_path):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", tmp=tmp_path / "state")

    def dry(argv, **kwargs):
        assert "--dry-run" in argv
        body = {"ok": True, "result": {"planned_calls": ["a", "b"]}}
        print(json.dumps(body), file=kwargs["stdout"])
        return 0

    proof = release.run(dataclasses.replace(ctx, release_main=dry), plan_path=plan_file(tmp_path))
    assert statuses(proof)["baseline"] == FAIL  # the double cannot read a schema
    assert statuses(proof)["promote-good"] == PASS
    assert proof.overall() == "SIMULATED"


def test_a_simulated_release_reads_the_schema_through_the_simulated_in_vpc_task(tmp_path):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", sql=False, tmp=tmp_path / "state")
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    baseline = proof.doc["steps"]["baseline"]
    assert baseline["status"] == PASS and baseline["public"]["schema_read"] is True
    assert baseline["public"]["schema_revision_source"] == "in-vpc-task"
    assert {read[:2] for read in ctx.world.vpc_reads} == {("media", "schema"),
                                                          ("processing", "schema")}
    assert proof.overall() == "SIMULATED"


def test_a_plan_with_relative_files_resolves_them_beside_the_plan(tmp_path):
    """The plan is synced between machines; its bundle files are named relative to it."""
    folder = tmp_path / "release"
    folder.mkdir()
    relative = {**IMAGE, "bundle": "bundle-good.json", "compat_evidence": "compat-good.json"}
    path = plan_file(folder, good={**relative, "image_uri": "good"})
    plan = release.load_plan(path)
    assert plan["good"]["bundle"] == str(folder.resolve() / "bundle-good.json")
    assert plan["good"]["compat_evidence"] == str(folder.resolve() / "compat-good.json")


@pytest.mark.parametrize("change", [
    {"owner": "everyone"}, {"extra": 1}, {"good": {"bundle": "b"}},
    {"owner": "processing"},  # a Processing release needs a worker definition
    {"migration_definition": None},  # and no image names one either
])
def test_a_malformed_release_plan_is_refused_before_anything_runs(tmp_path, change):
    with pytest.raises(ProofError):
        release.load_plan(plan_file(tmp_path, **change))


def test_a_release_cli_that_prints_garbage_is_a_refusal(tmp_path):
    ctx, _ = live_ctx(tmp_path)
    ctx = dataclasses.replace(
        ctx, release_main=lambda argv, **kw: print("not json", file=kw["stdout"]) or 0)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert statuses(proof)["baseline"] == FAIL


# ---- summary and counts ----------------------------------------------------------------
def live_receipts(tmp_path, *, simulated=False):
    proof = Proof(63, directory=tmp_path / "evidence", run_id="r", simulated=simulated,
                  scope={"account": "123456789012"}, required=("direct-upload-e2e",))
    proof.step("direct-upload-e2e", lambda i: {"public": {"job_status": "done", "seconds": 61}},
               session=None)
    capacity = Proof(64, directory=tmp_path / "evidence", run_id="r", simulated=simulated,
                     scope={}, required=("run-1", "recovery"))
    capacity.step("run-1", lambda i: {"public": {"outcomes": {"done": 1}}}, session=None)
    capacity.step("recovery", lambda i: {"public": {"final_status": "done",
                                                    "interrupted_attempts": 1}}, session=None)
    return summary.load(tmp_path / "evidence", "r")


def test_the_summary_names_only_statuses_and_public_numbers_and_is_world_readable(tmp_path):
    docs = live_receipts(tmp_path)
    built = summary.build(docs, evidence.REQUIRED, "r", wall=lambda: 1_800_000_000)
    path = summary.write(built, tmp_path / "out")
    text = path.read_text()
    assert "123456789012" not in text and '"scope"' not in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert built["issues"]["#63"]["steps"]["direct-upload-e2e"]["status"] == PASS
    assert built["issues"]["#66"]["overall"] == "NOT_RUN"


def test_archived_attempts_never_reach_the_summary_or_the_counts(tmp_path):
    docs = live_receipts(tmp_path)
    docs["63"]["attempts"] = {"direct-upload-e2e": [{
        "attempt": 1, "archived_at": "2026-10-17T00:00:00Z",
        "step": {"status": "FAIL", "seconds": 1, "public": {}, "private": {
            "task": "arn:aws:ecs:ap-southeast-1:123456789012:task/c/abc"}},
        "intent": {"task": "arn:aws:ecs:ap-southeast-1:123456789012:task/c/abc"}}]}
    built = summary.build(docs, evidence.REQUIRED, "r", wall=lambda: 0)  # screens the whole file
    text = json.dumps(built)
    assert "archived_at" not in text and "arn:aws" not in text
    assert built["issues"]["#63"]["overall"] != FAIL  # an archived FAIL does not count
    assert summary.counts(docs)["succeeded"] == 3 and summary.counts(docs)["failed"] == 0


def test_the_fresh_flag_applies_to_the_steps_named_by_only_or_to_all(tmp_path):
    parsed = evidence.build_parser().parse_args(
        ["latency", "--profile", "p", "--region", "r", "--account", "1", "--run-id", "x",
         "--only", "generator", "--fresh"])
    assert parsed.fresh and evidence.only(parsed) == {"generator"}
    plain = evidence.build_parser().parse_args(
        ["latency", "--profile", "p", "--region", "r", "--account", "1", "--run-id", "x"])
    assert plain.fresh is False and plain.pause_wait_minutes == 15


@pytest.mark.parametrize("command", [
    ["gateway", "--fixture", "f.mp4"], ["capacity", "--fixture", "f.mp4"],
    ["release", "--plan", "p.json"], ["release-plan"], ["spend"],
    ["short-encode", "--arm", "compare"], ["db-topology", "--arm", "compare"],
    ["isolation", "--fixture", "f.mp4"], ["unattended", "--fixture", "f.mp4"],
])
def test_fresh_is_refused_for_every_proof_but_latency_before_anything_is_built(command):
    out = io.StringIO()

    def factory(args):
        raise AssertionError("no context may be built for a refused --fresh")

    code = evidence.main([*command, "--profile", "p", "--region", "r", "--account", "1",
                          "--run-id", "x", "--state-dir", "/nonexistent", "--fresh"],
                         stdout=out, factory=factory)
    body = json.loads(out.getvalue())
    assert code == 1 and body["ok"] is False
    assert "--fresh is not supported" in body["error"] and "cumulative" in body["error"]


def test_a_simulated_command_with_fresh_archives_through_the_cli(tmp_path):
    out = io.StringIO()
    factory = None
    args = ["latency", "--dry-run", "--profile", "p", "--region", "r", "--account", "1",
            "--run-id", "cli", "--only", "cold-wake"]
    world = sim.SimWorld()
    assert evidence.main(args, stdout=out, world=world, factory=factory) == 0
    again = io.StringIO()
    assert evidence.main([*args, "--fresh"], stdout=again, world=sim.SimWorld()) == 0
    assert json.loads(again.getvalue())["steps"]["cold-wake"]["status"] == "PASS"


def test_a_summary_cannot_be_built_from_a_simulated_receipt(tmp_path):
    docs = live_receipts(tmp_path, simulated=True)
    with pytest.raises(ProofError, match="never be summarized"):
        summary.build(docs, evidence.REQUIRED, "r", wall=lambda: 0)


def test_an_edited_receipt_cannot_upgrade_its_own_verdict(tmp_path):
    docs = live_receipts(tmp_path)
    docs["64"]["steps"]["recovery"]["status"] = "FAIL"
    docs["64"]["overall"] = PASS
    built = summary.build(docs, evidence.REQUIRED, "r", wall=lambda: 0)
    assert built["issues"]["#64"]["overall"] == FAIL


def test_a_summary_without_receipts_is_refused(tmp_path):
    with pytest.raises(ProofError, match="No receipts"):
        summary.build({}, evidence.REQUIRED, "r", wall=lambda: 0)


def test_counts_come_from_the_terminal_outcomes_the_receipts_recorded(tmp_path):
    counts = summary.counts(live_receipts(tmp_path))
    assert counts["succeeded"] == 3 and counts["abandoned"] == 1 and counts["processing"] == 0


def test_counts_are_refused_for_simulated_receipts(tmp_path):
    with pytest.raises(ProofError, match="live receipts"):
        summary.counts(live_receipts(tmp_path, simulated=True))


def test_writing_counts_points_the_operator_config_at_a_private_file(tmp_path):
    state = tmp_path / "state"
    ctx = sim.build(argparse.Namespace(run_id="r", dry_run=True), session="closed", sql=False,
                    tmp=state)
    path = summary.write_counts(state, live_receipts(tmp_path))
    config = json.loads((state / "operator-config.json").read_text())
    assert config["counts_file"] == path.name  # relative to the config, so the state can move
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert ctx.state_dir == state


def test_counts_are_not_written_when_the_config_reads_them_from_sql(tmp_path):
    state = tmp_path / "state"
    sim.build(argparse.Namespace(run_id="r", dry_run=True), session="closed", sql=True, tmp=state)
    with pytest.raises(ProofError, match="SQL"):
        summary.write_counts(state, live_receipts(tmp_path))


# ---- command line ----------------------------------------------------------------------
def cli(*argv, **kwargs):
    out = io.StringIO()
    code = evidence.main(list(argv), stdout=out, **kwargs)
    return code, out.getvalue()


SCOPE = ("--profile", "dc2-project2-mfa", "--region", "ap-southeast-1", "--account",
         "123456789012", "--run-id", "cli")


def test_a_dry_run_gateway_prints_a_simulated_report_and_exits_zero(tmp_path):
    fixture = tmp_path / "f.mp4"
    fixture.write_bytes(b"\0" * 64)
    code, out = cli("gateway", *SCOPE, "--dry-run", "--fixture", str(fixture))
    report = json.loads(out)
    assert code == 0 and report["mode"] == "simulated" and report["overall"] == "SIMULATED"


def test_a_live_run_without_a_state_directory_is_refused(tmp_path):
    fixture = tmp_path / "f.mp4"
    code, out = cli("gateway", *SCOPE, "--fixture", str(fixture))
    assert code == 1 and "--state-dir" in json.loads(out)["error"]


def test_a_live_run_with_the_default_profile_is_refused_before_any_call(tmp_path):
    scope = ["--profile", "default", "--region", "ap-southeast-1", "--account", "123456789012",
             "--run-id", "x", "--state-dir", str(tmp_path)]
    code, out = cli("spend", *scope)
    assert code == 1 and "non-default profile" in json.loads(out)["error"]


def test_rehearse_runs_every_harness_offline_and_fails_nothing(tmp_path):
    code, out = cli("rehearse")
    report = json.loads(out)
    assert code == 0 and report["mode"] == "simulated", out
    assert set(report["harnesses"]) == {
        "gateway", "capacity", "capacity-backlog", "isolation", "unattended", "latency", "spend",
        "release", "short-encode", "db-topology"}
    # No SQL station is simulated: the release harness reads schemas through the in-VPC task.
    assert report["harnesses"]["release"]["steps"]["baseline"] == "PASS"
    assert all(h["overall"] == "SIMULATED" for h in report["harnesses"].values())


def test_the_summary_command_refuses_a_directory_of_simulated_receipts(tmp_path):
    live_receipts(tmp_path, simulated=True)
    code, out = cli("summary", "--state-dir", str(tmp_path), "--run-id", "r",
                    "--out", str(tmp_path / "o"))
    assert code == 1 and "never be summarized" in json.loads(out)["error"]
    assert not (tmp_path / "o").exists()


def test_a_failed_step_makes_the_command_exit_one(tmp_path):
    fixture = tmp_path / "f.mp4"
    fixture.write_bytes(b"\0" * 64)
    world = sim.SimWorld(faults=("cors-open",))
    code, out = cli("gateway", *SCOPE, "--dry-run", "--fixture", str(fixture), world=world)
    assert code == 1 and json.loads(out)["steps"]["cors-preflight"]["status"] == FAIL
