"""#196 failure isolation and #68 unattended launcher harnesses, against the simulated account.

Rehearsals only: nothing here says anything about AWS. They pin what decides a verdict: that the
consumer is restored on every way out, what counts as "held", and the launcher's cap and idle
behaviour.
"""

import argparse
import io
import json

import pytest

from scripts.aws.v1 import evidence
from scripts.aws.v1.proof import capacity, isolation, sim, summary, unattended, workflow
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, SessionRefused

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\0" * 4096)
    return path


def build(tmp_path, *faults, session="open", unattended_session=False, **world):
    world.setdefault("encode_seconds", 150.0)
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(
        args,
        session=session,
        world=sim.SimWorld(faults=faults, **world),
        tmp=tmp_path / "state",
        unattended=unattended_session,
    )


def public(proof, name):
    return proof.doc["steps"][name]["public"]


def status(proof, name):
    return proof.doc["steps"][name]["status"]


def commands_mapping(ctx):
    return ctx.world.plan.mappings[ctx.world.commands_mapping]


def stopped(ctx):
    return bool(ctx.world.tasks) and all(
        ctx.world.task_view(t)["lastStatus"] == "STOPPED" for t in ctx.world.tasks.values()
    )


# ---- #196 Media accepts uploads while Processing is down -------------------------------------
def test_media_accepts_and_holds_an_upload_while_the_consumer_is_off_then_it_completes(
    tmp_path, fixture
):
    ctx = build(tmp_path, outbox_seconds=45.0)
    proof = isolation.run(ctx, fixture=fixture)
    step = public(proof, "processing-down")
    assert status(proof, "processing-down") == PASS and proof.overall() == "SIMULATED"
    assert step["finalize_status"] == 202
    assert step["mapping_before"] == "Enabled" and step["mapping_during"] == "Disabled"
    assert step["mapping_after"] == "Enabled" and step["mapping_restore"] == "re-enabled"
    assert step["asset_visible_by_id"] and step["asset_in_list"]
    assert step["status_during_outage"] in {"accepted", "queued"}
    assert step["processing_acknowledged_during_outage"] is False
    assert step["command_held_in"] == "both"  # first in Media's outbox, then in the queue
    assert step["job_status"] == "done" and step["within_gate"]
    assert step["encoders_left_running"] == 0 and commands_mapping(ctx) == "Enabled"
    assert len(ctx.world.jobs) == 1 and stopped(ctx)


def test_a_command_published_at_once_is_held_in_the_queue(tmp_path, fixture):
    proof = isolation.run(build(tmp_path), fixture=fixture)
    assert public(proof, "processing-down")["command_held_in"] == "queue"


def test_the_receipt_view_carries_no_identifier(tmp_path, fixture):
    proof = isolation.run(build(tmp_path), fixture=fixture)
    text = json.dumps(public(proof, "processing-down"))
    assert "arn:" not in text and "http" not in text and "job_id" not in text


def test_an_upload_that_needs_processing_to_be_up_fails_and_still_restores_the_consumer(
    tmp_path, fixture
):
    ctx = build(tmp_path, "finalize-needs-processing")
    proof = isolation.run(ctx, fixture=fixture)
    assert status(proof, "processing-down") == FAIL
    assert "503" in public(proof, "processing-down")["error"]
    assert commands_mapping(ctx) == "Enabled" and not ctx.world.jobs


def test_a_consumer_that_keeps_running_while_disabled_is_not_a_proof(tmp_path, fixture):
    ctx = build(tmp_path, "mapping-ignored")
    proof = isolation.run(ctx, fixture=fixture)
    step = public(proof, "processing-down")
    assert status(proof, "processing-down") == FAIL
    assert step["processing_acknowledged_during_outage"] is True
    assert commands_mapping(ctx) == "Enabled"


def test_a_consumer_that_never_catches_up_fails_and_leaves_nothing_running(tmp_path, fixture):
    ctx = build(tmp_path, "stuck-consumer")
    proof = isolation.run(ctx, fixture=fixture, job_timeout=150)
    # The encoders find no work and exit; the start budget stops the step before the gate.
    assert status(proof, "processing-down") == FAIL
    assert "budget" in public(proof, "processing-down")["error"]
    assert commands_mapping(ctx) == "Enabled" and stopped(ctx)


def test_a_job_that_is_still_not_done_at_the_gate_fails_with_its_numbers(tmp_path, fixture):
    ctx = build(tmp_path, encode_seconds=5000.0)
    proof = isolation.run(ctx, fixture=fixture, job_timeout=100)
    step = public(proof, "processing-down")
    assert status(proof, "processing-down") == FAIL
    assert step["job_status"] == "processing" and step["within_gate"] is False
    assert step["encoders_left_running"] == 0 and stopped(ctx)


def test_a_mapping_that_is_not_enabled_blocks_the_step_before_any_upload(tmp_path, fixture):
    ctx = build(tmp_path)
    ctx.world.plan.mappings[ctx.world.commands_mapping] = "Disabled"
    proof = isolation.run(ctx, fixture=fixture)
    assert status(proof, "processing-down") == FAIL
    assert "not Enabled" in public(proof, "processing-down")["error"] and not ctx.world.jobs


def test_an_interrupt_restores_the_consumer_and_stops_the_encoder(tmp_path, fixture):
    ctx = build(tmp_path)
    real, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 3:
            raise KeyboardInterrupt
        real(seconds)

    ctx.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        isolation.run(ctx, fixture=fixture)
    assert commands_mapping(ctx) == "Enabled"
    assert (
        ctx.proof(isolation.ISSUE, isolation.REQUIRED).intent("processing-down")["restore"]
        == "re-enabled"
    )


def test_an_interrupt_after_the_consumer_is_back_stops_the_encoder_too(tmp_path, fixture):
    ctx = build(tmp_path)
    real, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if ctx.world.tasks and len(calls) > 1 and any(t["busy"] for t in ctx.world.tasks.values()):
            raise KeyboardInterrupt
        real(seconds)

    ctx.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        isolation.run(ctx, fixture=fixture)
    assert ctx.world.tasks and stopped(ctx) and commands_mapping(ctx) == "Enabled"


def test_a_session_closed_mid_outage_leaves_the_consumer_to_the_close(tmp_path, fixture):
    ctx = build(tmp_path)
    real, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 2:
            with ctx.journal.locked() as state:
                state.update(session="closed")
                ctx.journal.save(state)
        real(seconds)

    ctx.sleep = sleep
    with pytest.raises(SessionRefused):
        isolation.run(ctx, fixture=fixture)
    # `session close` disables every mapping; re-enabling one would reopen a closed window.
    assert commands_mapping(ctx) == "Disabled"
    intent = ctx.proof(isolation.ISSUE, isolation.REQUIRED).intent("processing-down")
    assert intent["restore"].startswith("left disabled") and not intent["mapping_disabled"]


def test_a_killed_run_resumes_the_same_upload_and_finishes_with_the_consumer_back(
    tmp_path, fixture, monkeypatch
):
    ctx = build(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(isolation, "restore", lambda *a, **k: None)  # a process that was killed
        patch.setattr(
            isolation,
            "observe_outage",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("killed")),
        )
        first = isolation.run(ctx, fixture=fixture)
    assert status(first, "processing-down") == FAIL
    assert commands_mapping(ctx) == "Disabled" and len(ctx.world.jobs) == 1
    again = isolation.run(ctx, fixture=fixture)
    assert status(again, "processing-down") == PASS
    assert len(ctx.world.jobs) == 1 and commands_mapping(ctx) == "Enabled"


def test_a_rerun_after_a_pass_repeats_nothing(tmp_path, fixture):
    ctx = build(tmp_path)
    isolation.run(ctx, fixture=fixture)
    again = isolation.run(ctx, fixture=fixture)
    assert again.ran == [] and len(ctx.world.jobs) == 1


def test_an_encoder_already_running_blocks_the_step(tmp_path, fixture):
    ctx = build(tmp_path)
    workflow.start_workers(ctx, 1, 60)
    proof = isolation.run(ctx, fixture=fixture)
    assert status(proof, "processing-down") == FAIL and not ctx.world.jobs
    assert commands_mapping(ctx) == "Enabled"


def test_isolation_runs_through_the_cli_with_its_own_receipt(tmp_path, fixture):
    out = io.StringIO()
    code = evidence.main(
        [
            "isolation",
            "--profile",
            "dc2-project2-mfa",
            "--region",
            "ap-southeast-1",
            "--account",
            "123456789012",
            "--run-id",
            "cli",
            "--dry-run",
            "--fixture",
            str(fixture),
        ],
        stdout=out,
        world=sim.SimWorld(encode_seconds=150.0),
    )
    report = json.loads(out.getvalue())
    assert code == 0 and report["issue"] == "#196" and report["overall"] == "SIMULATED"
    assert report["steps"]["processing-down"]["status"] == PASS


def test_the_isolation_receipt_is_summarized_and_counted(tmp_path, fixture):
    ctx = build(tmp_path)
    isolation.run(ctx, fixture=fixture)
    docs = summary.load(ctx.evidence_dir, "t")
    docs["196"]["mode"] = "live"
    built = summary.build(docs, evidence.REQUIRED, "t", wall=lambda: 0)
    assert built["issues"]["#196"]["steps"]["processing-down"]["status"] == PASS
    assert summary.counts(docs)["succeeded"] == 1


# ---- #68 the unattended launcher ----------------------------------------------------------------
def with_baseline(tmp_path, fixture, *faults, **world):
    """A stack with the launcher: the operator-batch sweep first, then the session is reopened
    with --unattended, as the runbook orders it."""
    ctx = build(tmp_path, *faults, launcher=True, **world)
    capacity.run_backlog(ctx, fixture=fixture)
    sim.opt_in_launcher(ctx)
    return ctx


def test_the_launcher_drains_the_same_backlog_and_is_compared_with_operator_batches(
    tmp_path, fixture
):
    ctx = with_baseline(tmp_path, fixture)
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    assert [status(proof, n) for n in unattended.STEPS] == [PASS, PASS, PASS]
    step = public(proof, "launcher-backlog")
    assert step["jobs_done"] == 6 and step["peak_concurrent_from_task_stamps"] <= 3
    assert step["starts_after_backlog_empty"] == 0 and step["encoders_left_running"] == 0
    assert step["encoders_started"] == 6 and step["starts_per_job"] == 1.0
    assert step["unclaimed_encoders"] == 0 and step["jobs_claimed"] == 6
    assert step["processing_median_seconds"] == 150.0 and step["queue_wait_samples"] == 6
    # The launcher's first tick comes a minute after the rule is enabled.
    assert step["first_start_after_first_queued_seconds"] >= 55
    compare = public(proof, "launcher-compare")
    assert compare["comparable"] and compare["throughput_ratio"] is not None
    assert compare["queue_wait_median_seconds"]["delta"] > 0  # the tick costs waiting
    assert stopped(ctx)


def test_the_harness_starts_no_encoder_itself(tmp_path, fixture, monkeypatch):
    ctx = with_baseline(tmp_path, fixture)
    monkeypatch.setattr(
        workflow,
        "start_workers",
        lambda *a, **k: pytest.fail("the harness must not start encoders"),
    )
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    assert status(proof, "launcher-backlog") == PASS


def test_it_refuses_to_start_without_an_operator_batch_baseline(tmp_path, fixture):
    ctx = build(tmp_path, launcher=True)
    sim.opt_in_launcher(ctx)
    with pytest.raises(ProofError, match="evidence capacity --backlog"):
        unattended.run(ctx, fixture=fixture, iam_simulated=True)
    assert not ctx.world.jobs


def test_the_preflight_demands_the_iam_simulation_and_stops_before_any_upload(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture)
    jobs = len(ctx.world.jobs)
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=False)
    assert status(proof, "launcher-preflight") == FAIL
    assert "simulate-principal-policy" in public(proof, "launcher-preflight")["error"]
    assert "launcher-backlog" not in proof.doc["steps"] and len(ctx.world.jobs) == jobs


def test_a_session_not_opened_unattended_fails_the_preflight(tmp_path, fixture):
    ctx = build(tmp_path, launcher=True)
    capacity.run_backlog(ctx, fixture=fixture)  # no opt-in afterwards
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    step = public(proof, "launcher-preflight")
    assert status(proof, "launcher-preflight") == FAIL
    assert step["session_unattended"] is False and step["launcher_rule_state"] == "DISABLED"
    assert "launcher-backlog" not in proof.doc["steps"]


def test_a_stack_without_the_launcher_is_refused_with_the_fix_named(tmp_path, fixture):
    ctx = build(tmp_path)
    capacity.run_backlog(ctx, fixture=fixture)
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    assert "--unattended-launch" in public(proof, "launcher-preflight")["error"]


def test_a_launcher_that_exceeds_the_cap_fails(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture, "launcher-overshoot")
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    step = public(proof, "launcher-backlog")
    assert status(proof, "launcher-backlog") == FAIL
    assert step["peak_concurrent_from_task_stamps"] == 4 > step["cap_limit"]
    assert status(proof, "launcher-compare") == FAIL


def test_an_idle_respawn_after_the_backlog_emptied_fails(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture, "launcher-respawn")
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    step = public(proof, "launcher-backlog")
    assert status(proof, "launcher-backlog") == FAIL
    assert step["starts_after_backlog_empty"] >= 1 and step["unclaimed_encoders"] >= 1


def test_a_launcher_that_never_starts_anything_times_out_and_is_reported(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture, "launcher-dead")
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True, drain_timeout=300)
    step = public(proof, "launcher-backlog")
    assert status(proof, "launcher-backlog") == FAIL
    assert step["timed_out"] and step["jobs_done"] == 0 and step["encoders_started"] == 0


def test_a_different_fixture_than_the_baseline_cannot_pass_the_comparison(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture)
    other = tmp_path / "other.mp4"
    other.write_bytes(b"\0" * 2048)
    proof = unattended.run(ctx, fixture=other, iam_simulated=True)
    assert status(proof, "launcher-backlog") == PASS
    assert status(proof, "launcher-compare") == FAIL
    assert public(proof, "launcher-compare")["comparable"] is False


def test_an_interrupt_stops_the_encoders_the_launcher_started(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture)
    real, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if ctx.world.launcher and len(ctx.world.tasks) > 3 and len(calls) > 40:
            raise KeyboardInterrupt
        real(seconds)

    ctx.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        unattended.run(ctx, fixture=fixture, iam_simulated=True)
    assert stopped(ctx)


def test_unattended_without_a_baseline_is_an_error_through_the_cli(tmp_path, fixture):
    out = io.StringIO()
    code = evidence.main(
        [
            "unattended",
            "--profile",
            "dc2-project2-mfa",
            "--region",
            "ap-southeast-1",
            "--account",
            "123456789012",
            "--run-id",
            "cli",
            "--dry-run",
            "--fixture",
            str(fixture),
            "--iam-simulated",
        ],
        stdout=out,
        world=sim.SimWorld(launcher=True),
    )
    body = json.loads(out.getvalue())
    assert code == 1 and "#185" in body["error"]


def test_the_unattended_receipt_is_summarized_without_identifiers(tmp_path, fixture):
    ctx = with_baseline(tmp_path, fixture)
    unattended.run(ctx, fixture=fixture, iam_simulated=True)
    docs = summary.load(ctx.evidence_dir, "t")
    for doc in docs.values():
        doc["mode"] = "live"
    built = summary.build(docs, evidence.REQUIRED, "t", wall=lambda: 0)
    text = json.dumps(built["issues"]["#68"])
    assert built["issues"]["#68"]["steps"]["launcher-compare"]["status"] == PASS
    assert "arn:" not in text and "http" not in text
    # 18 operator-batch jobs plus the launcher's 6 are all terminal for the close proof.
    assert summary.counts(docs)["succeeded"] == 24
