"""Receipt, guard and HTTP plumbing shared by the cloud-proof harnesses; offline."""

import argparse
import json
import stat

import pytest

from scripts.aws.v1.proof import core, sim
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, Api, Proof, ProofError, SessionRefused

pytestmark = pytest.mark.unmeasured


def make_proof(tmp_path, *, required=("a", "b"), simulated=False, guard=None, run_id="r1"):
    return Proof(
        63,
        directory=tmp_path / "evidence",
        run_id=run_id,
        simulated=simulated,
        scope={"profile": "p"},
        required=required,
        guard=guard,
    )


def ok(public=None):
    return lambda intent: {"status": PASS, "public": public or {"n": 1}, "private": {"x": "y"}}


# ---- receipts -------------------------------------------------------------------------
def test_a_receipt_is_private_and_a_step_that_passed_is_not_run_again(tmp_path):
    proof = make_proof(tmp_path)
    calls = []
    proof.step("a", lambda i: calls.append(1) or {"public": {"n": 1}}, session=None)
    again = make_proof(tmp_path)  # a rerun in a new process
    again.step("a", lambda i: calls.append(2) or {"public": {"n": 2}}, session=None)
    assert calls == [1] and again.ran == []
    assert stat.S_IMODE(proof.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(proof.path.parent.stat().st_mode) == 0o700


def test_a_failed_step_is_retried_and_may_be_forced(tmp_path):
    proof = make_proof(tmp_path)

    def boom(intent):
        raise ProofError("not yet")

    assert proof.step("a", boom, session=None)["status"] == FAIL
    assert make_proof(tmp_path).step("a", ok(), session=None)["status"] == PASS
    seen = []
    make_proof(tmp_path).step(
        "a", lambda i: seen.append(1) or {"public": {}}, session=None, rerun=True
    )
    assert seen == [1]


def test_an_unexpected_exception_records_only_its_class_never_its_text(tmp_path):
    proof = make_proof(tmp_path)

    def boom(intent):
        raise RuntimeError("dsn is postgres://user:hunter2@host/db")

    step = proof.step("a", boom, session=None)
    assert step["public"] == {"error": "RuntimeError"}
    assert "hunter2" not in proof.path.read_text()


def test_intents_survive_a_crash_so_a_rerun_resumes_instead_of_repeating(tmp_path):
    proof = make_proof(tmp_path)

    def crash(intent):
        intent["task"] = "t-1"
        proof.save()
        raise KeyboardInterrupt  # not an Exception: the process dies mid-step

    with pytest.raises(KeyboardInterrupt):
        proof.step("a", crash, session=None)
    assert make_proof(tmp_path).intent("a") == {"task": "t-1"}


def test_the_public_view_is_screened_for_urls_arns_accounts_addresses_and_tokens(tmp_path):
    for leak in (
        "https://x.example/a",
        "arn:aws:s3:::bucket",
        "123456789012",
        "ops@example.com",
        "X-Amz-Signature=abc",
        "A" * 45,
        "Set-Cookie: s=1",
    ):
        proof = make_proof(tmp_path / leak[:4], required=("a",))
        step = proof.step("a", lambda i, leak=leak: {"public": {"v": leak}}, session=None)
        assert step["status"] == FAIL and "withheld" in step["public"]["error"]
        assert leak not in proof.path.read_text()


def test_hashes_numbers_and_statuses_pass_the_public_screen(tmp_path):
    proof = make_proof(tmp_path)
    digest = "ab" * 32
    step = proof.step(
        "a",
        ok({"sha256": digest, "ms": 12.5, "ok": True, "codes": [200, 204], "nested": {"p90": 1}}),
        session=None,
    )
    assert step["status"] == PASS


def test_a_secret_named_key_cannot_be_stored_at_all(tmp_path):
    proof = make_proof(tmp_path)
    with pytest.raises(core.OperationError):
        proof.step("a", lambda i: {"public": {"cookie": "x"}}, session=None)


def test_overall_is_pass_partial_fail_or_incomplete_from_required_steps(tmp_path):
    proof = make_proof(tmp_path)
    assert proof.overall() == "INCOMPLETE"
    proof.step("a", ok(), session=None)
    assert proof.overall() == "INCOMPLETE"
    proof.step("b", ok(), session=None)
    assert proof.overall() == PASS
    proof.step("c", lambda i: {"status": NOT_RUN, "public": {"reason": "none"}}, session=None)
    assert proof.overall() == "PARTIAL"
    proof.step("d", lambda i: {"status": FAIL, "public": {}}, session=None)
    assert proof.overall() == FAIL


def test_a_simulated_receipt_is_never_a_pass_whatever_its_steps_say(tmp_path):
    proof = make_proof(tmp_path, simulated=True)
    proof.step("a", ok(), session=None)
    proof.step("b", ok(), session=None)
    assert proof.overall() == "SIMULATED"
    assert proof.report()["mode"] == "simulated"


def test_a_live_run_refuses_to_continue_a_simulated_receipt_and_vice_versa(tmp_path):
    make_proof(tmp_path, simulated=True).step("a", ok(), session=None)
    with pytest.raises(ProofError, match="other mode"):
        make_proof(tmp_path, simulated=False)


def test_an_unreadable_receipt_is_a_refusal_not_a_reset(tmp_path):
    proof = make_proof(tmp_path)
    proof.step("a", ok(), session=None)
    proof.path.write_text("{ not json")
    with pytest.raises(ProofError, match="unreadable"):
        make_proof(tmp_path)


def test_the_report_carries_statuses_and_public_numbers_only(tmp_path):
    proof = make_proof(tmp_path)
    proof.step("a", ok({"n": 7}), session=None)
    report = proof.report()
    assert report["steps"]["a"]["n"] == 7 and "x" not in json.dumps(report)


# ---- session guard ---------------------------------------------------------------------
def guarded(tmp_path, session, **world):
    args = argparse.Namespace(run_id="g", dry_run=True)
    ctx = sim.build(args, session=session, world=sim.SimWorld(**world), tmp=tmp_path / "state")
    return ctx, ctx.proof(63, ("a",))


def test_a_step_that_needs_an_open_session_refuses_while_the_journal_says_closed(tmp_path):
    _, proof = guarded(tmp_path, "closed")
    ran = []
    with pytest.raises(SessionRefused, match="Session is closed; this step needs open"):
        proof.step("a", lambda i: ran.append(1) or {"public": {}}, session="open")
    assert ran == [] and not proof.path.exists()  # nothing recorded, nothing run


def test_a_window_is_not_a_full_open_and_open_is_not_a_window(tmp_path):
    _, window = guarded(tmp_path / "w", "window")
    with pytest.raises(SessionRefused):
        window.checkpoint("open")
    window.checkpoint("window")
    window.checkpoint("active")
    _, opened = guarded(tmp_path / "o", "open")
    with pytest.raises(SessionRefused):
        opened.checkpoint("window")
    with pytest.raises(SessionRefused):
        opened.checkpoint("closed")


def test_an_open_journal_with_a_shut_gateway_edge_is_refused_too(tmp_path):
    ctx, proof = guarded(tmp_path, "open")
    ctx.world.plan.stage = {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    with pytest.raises(SessionRefused, match="throttle is 0"):
        proof.checkpoint("active")


def test_a_refusal_from_inside_a_long_step_stops_the_command_not_just_the_step(tmp_path):
    ctx, proof = guarded(tmp_path, "open")

    def long_step(intent):
        ctx.world.plan.stage = {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
        proof.checkpoint("active")  # what a polling loop does between polls

    with pytest.raises(SessionRefused):
        proof.step("a", long_step, session="active")
    assert "a" not in proof.doc["steps"]


def test_an_unknown_session_requirement_is_refused(tmp_path):
    _, proof = guarded(tmp_path, "open")
    with pytest.raises(ProofError, match="Unknown session"):
        proof.checkpoint("sometimes")


# ---- HTTP helpers ----------------------------------------------------------------------
def test_the_cookie_is_held_in_memory_and_sent_only_through_the_api_object():
    seen = []

    def http(method, url, headers, body, timeout):
        seen.append(headers)
        return 200, {"set-cookie": ["s=1; HttpOnly"]}, b"{}"

    api = Api("https://d1.cloudfront.net", http)
    api.login({"email": "a", "password": "b"})
    api.request("GET", "/x")
    assert "cookie" not in seen[0] and seen[1]["cookie"] == "s=1"
    assert "cookie" not in repr(sorted(seen[0]))


def test_a_direct_storage_or_queue_request_refuses_a_session_header():
    with pytest.raises(ProofError, match="must not carry the session"):
        core.direct(lambda *a: (200, {}, b""), "POST", "https://s3", {"Cookie": "s=1"}, b"")


def test_the_multipart_body_puts_every_field_before_the_file():
    ctype, body = core.multipart({"key": "k", "policy": "p"}, "v.mp4", b"DATA", "video/mp4")
    assert ctype.startswith("multipart/form-data; boundary=")
    assert body.index(b'name="key"') < body.index(b'name="policy"') < body.index(b'name="file"')
    assert body.rstrip().endswith(b"--") and b"DATA" in body


def test_percentiles_use_nearest_rank():
    values = list(range(1, 101))
    assert [core.percentile(values, f) for f in (0.5, 0.9, 0.95, 0.99)] == [50, 90, 95, 99]
    assert core.percentile([], 0.5) is None


# ---- --fresh ----------------------------------------------------------------------------
def fresh_proof(tmp_path, fresh, guard=None):
    return Proof(
        63,
        directory=tmp_path / "evidence",
        run_id="r1",
        simulated=False,
        scope={"profile": "p"},
        required=("a", "b"),
        guard=guard,
        fresh=fresh,
    )


def test_fresh_archives_the_old_entry_and_intent_and_runs_the_step_again(tmp_path):
    first = fresh_proof(tmp_path, None)
    first.step("a", lambda i: i.update(task="one") or {"public": {"n": 1}}, session=None)
    again = fresh_proof(tmp_path, {"a"})
    seen = []
    again.step(
        "a",
        lambda i: seen.append(dict(i)) or i.update(task="two") or {"public": {"n": 2}},
        session=None,
    )
    assert seen == [{}]  # a new intent: nothing of the old task is reused
    assert again.doc["steps"]["a"]["public"] == {"n": 2}
    (attempt,) = again.doc["attempts"]["a"]
    assert attempt["attempt"] == 1 and attempt["step"]["public"] == {"n": 1}
    assert attempt["intent"] == {"task": "one"} and attempt["archived_at"].endswith("Z")
    assert json.loads(again.path.read_text())["attempts"]["a"][0]["attempt"] == 1  # saved first


def test_fresh_leaves_steps_it_was_not_asked_about_final(tmp_path):
    first = fresh_proof(tmp_path, None)
    first.step("a", ok(), session=None)
    first.step("b", ok(), session=None)
    again = fresh_proof(tmp_path, {"a"})
    again.step("a", ok(), session=None)
    again.step("b", lambda i: pytest.fail("b is final"), session=None)
    assert again.ran == ["a"] and set(again.doc["attempts"]) == {"a"}


def test_fresh_true_means_every_step_and_each_is_archived_once_per_process(tmp_path):
    first = fresh_proof(tmp_path, None)
    first.step("a", ok(), session=None)
    first.step("b", ok(), session=None)
    again = fresh_proof(tmp_path, True)
    for name in ("a", "b", "a"):  # a second request for `a` in this process is a plain rerun
        again.step(name, ok(), session=None)
    assert {n: len(v) for n, v in again.doc["attempts"].items()} == {"a": 1, "b": 1}


def test_fresh_on_a_step_that_never_ran_archives_nothing(tmp_path):
    proof = fresh_proof(tmp_path, True)
    proof.step("a", ok(), session=None)
    assert "attempts" not in proof.doc


def test_a_refused_fresh_step_leaves_the_receipt_untouched(tmp_path):
    ctx, guarded_proof = guarded(tmp_path, "open")
    guarded_proof.step("a", ok(), session="open")
    before = guarded_proof.path.read_text()
    ctx.world.plan.stage = {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    again = ctx.proof(63, ("a",))
    again.fresh = True
    with pytest.raises(SessionRefused):
        again.step("a", ok(), session="active")
    assert again.path.read_text() == before


def test_the_overall_verdict_ignores_archived_attempts(tmp_path):
    first = fresh_proof(tmp_path, None)
    first.step("a", lambda i: {"status": FAIL, "public": {}}, session=None)
    first.step("b", ok(), session=None)
    again = fresh_proof(tmp_path, {"a"})
    again.step("a", ok(), session=None)
    assert again.overall() == PASS


def test_the_stage_throttle_reader_returns_the_live_default_route_settings(tmp_path):
    ctx, _ = guarded(tmp_path, "open")
    assert core.stage_throttle(ctx.aws, ctx.config["gateway"]) == sim.OPEN_EDGE
