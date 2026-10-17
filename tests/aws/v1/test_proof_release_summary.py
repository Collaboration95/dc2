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

    def __init__(self, clock, *, peer_moves=False, slow=0, bad_restores=True):
        self.clock, self.peer_moves, self.slow = clock, peer_moves, slow
        self.bad_restores = bad_restores
        self.table = {"media-a": {"owner": "media", "version": "1"},
                      "proc-a": {"owner": "processing", "version": "7"}}
        self.calls = []

    def __call__(self, argv, *, environ, transport_factory, stdout, http):
        action = argv[0]
        self.calls.append(action)
        self.clock.sleep(self.slow or 30)
        smoke = {"checks": {"login": "PASS", "upload": "PASS"}}
        if action == "status":
            body = {"ok": True, "result": {"aliases": json.loads(json.dumps(self.table)),
                                           "pending_release": None}}
        elif action == "promote":
            image = argv[argv.index("--image-uri") + 1]
            if image == "bad":
                body, code = {"ok": False, "error": "smoke failed"}, 1
                print(json.dumps(body), file=stdout)
                return code
            self.table["media-a"]["version"] = {"good": "2", "base": "1"}[image]
            if self.peer_moves:
                self.table["proc-a"]["version"] = "8"
            body = {"ok": True, "result": {"status": "promoted", "smoke": smoke}}
        else:  # restore
            body = {"ok": True, "result": {"status": "restored", "smoke": smoke}}
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
    assert "restore" in scripted.calls


def test_the_release_steps_are_not_run_without_a_sql_station_rather_than_passed(tmp_path):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", sql=False, tmp=tmp_path / "state")
    ctx = dataclasses.replace(ctx, simulated=False)
    proof = release.run(ctx, plan_path=plan_file(tmp_path))
    assert set(statuses(proof).values()) == {NOT_RUN}


def test_a_simulated_release_only_exercises_the_offline_gates_and_proves_nothing(tmp_path):
    args = argparse.Namespace(run_id="rel", dry_run=True)
    ctx = sim.build(args, session="window", tmp=tmp_path / "state")

    def dry(argv, **kwargs):
        assert "--dry-run" in argv
        body = {"ok": True, "result": {"planned_calls": ["a", "b"]}}
        print(json.dumps(body), file=kwargs["stdout"])
        return 0

    proof = release.run(dataclasses.replace(ctx, release_main=dry), plan_path=plan_file(tmp_path))
    assert statuses(proof)["baseline"] == NOT_RUN and statuses(proof)["promote-good"] == PASS
    assert proof.overall() == "SIMULATED"


@pytest.mark.parametrize("change", [
    {"owner": "everyone"}, {"extra": 1}, {"good": {"bundle": "b"}},
    {"owner": "processing"},  # a Processing release needs a worker definition
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
    assert config["counts_file"] == str(path) and stat.S_IMODE(path.stat().st_mode) == 0o600
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
    assert code == 0 and report["mode"] == "simulated"
    assert set(report["harnesses"]) == {"gateway", "capacity", "latency", "spend", "short-encode"}
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
