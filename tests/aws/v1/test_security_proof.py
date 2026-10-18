"""#229 security-negatives harness against the simulated account.

A rehearsal: every receipt is SIMULATED and says nothing about AWS. These tests pin what decides
a verdict (a control must work before a refusal counts, an expiry that cannot be waited for is
NOT_RUN rather than PASS), that each open boundary fails exactly its own step, and that nothing
secret reaches the receipt.
"""

import argparse
import io
import json
import socket
import types

import pytest

from scripts.aws.v1 import evidence
from scripts.aws.v1.proof import security, sim, summary
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, SessionRefused

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\0" * 4096)
    return path


def build(tmp_path, *faults, session="open", **world):
    world.setdefault("encode_seconds", 45.0)
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(args, session=session, world=sim.SimWorld(faults=faults, **world),
                     tmp=tmp_path / "state")


def statuses(proof):
    return {name: step["status"] for name, step in proof.doc["steps"].items()}


def failing(proof):
    return {name for name, status in statuses(proof).items() if status == FAIL}


def public(proof, name):
    return proof.doc["steps"][name]["public"]


# ---- the healthy path --------------------------------------------------------------------
def test_a_healthy_stack_passes_what_can_run_and_marks_the_rest_not_run_with_a_reason(
        tmp_path, fixture):
    proof = security.run(build(tmp_path), fixture=fixture)
    found = statuses(proof)
    assert {n for n, s in found.items() if s == NOT_RUN} == {
        "oversize-100mib", "playback-url-expiry", "upload-url-expiry"}
    assert {s for n, s in found.items() if n in security.STEPS} <= {PASS, NOT_RUN}
    for name in ("oversize-100mib", "playback-url-expiry", "upload-url-expiry"):
        assert public(proof, name)["reason"]
    assert proof.overall() == "SIMULATED"
    assert public(proof, "playback-url-expiry")["signed_lifetime_seconds"] == 900


def test_user_b_gets_404_everywhere_while_user_a_gets_200_as_the_control(tmp_path, fixture):
    proof = security.run(build(tmp_path), fixture=fixture)
    seen = public(proof, "cross-owner")
    for name in ("read", "retry", "playback_master", "playback_segment", "processing_job"):
        assert seen[f"b_{name}"] == 404
    assert seen["a_read"] == seen["a_playback"] == seen["a_processing_job"] == 200
    assert seen["a_job_unchanged_after_b_retry"] and not seen["b_lists_a_job"]


def test_every_protected_route_is_401_without_a_valid_session_on_both_origins(tmp_path, fixture):
    seen = public(security.run(build(tmp_path), fixture=fixture), "unauthenticated")
    assert seen["all_401"] and len(seen["statuses"]) == 18
    assert {"forged_alg_none_jobs", "forged_signature_changed_jobs"} <= set(seen["statuses"])


def test_each_tampered_grant_and_url_is_refused_and_the_untouched_ones_worked(tmp_path, fixture):
    seen = public(security.run(build(tmp_path), fixture=fixture), "tampered-urls")
    assert seen["all_tampering_rejected"] and seen["all_controls_worked"] and seen["mp4_checked"]
    assert seen["upload_signature_changed"] == 403 and seen["segment_key_changed"] == 403
    assert seen["mp4_lifetime_extended"] == 403 and seen["upload_control_status"] == 204


def test_oversize_is_refused_at_reservation_and_by_storage_at_the_reserved_size(
        tmp_path, fixture):
    seen = public(security.run(build(tmp_path), fixture=fixture), "oversized-upload")
    assert seen["reservation_over_limit_status"] == 422
    assert not seen["reservation_over_limit_granted_upload"]
    assert seen["storage_status"] == 400 and seen["storage_rejected_oversize"]
    assert seen["adopted"] is False


def test_the_port_scan_reads_only_the_fixed_list_and_finds_only_80_and_443(tmp_path, fixture):
    seen = public(security.run(build(tmp_path), fixture=fixture), "port-scan")
    assert seen["ports_scanned"] == [21, 22, 25, 80, 443, 3306, 5432, 6379, 8000, 8080, 8443,
                                     9000]
    assert seen["open_ports"] == [80, 443] and seen["plain_http_redirects_to_https"]
    assert seen["addresses_scanned"] == 2 and seen["ipv6_scanned"] is False


def test_the_execute_api_url_is_documented_as_reachable_with_the_authorizer_in_force(
        tmp_path, fixture):
    seen = public(security.run(build(tmp_path), fixture=fixture), "execute-api-direct")
    assert seen["classification"] == "reachable_authorizer_enforced"
    assert seen["a_reads_own_job_status"] == 200 and seen["b_reads_a_job_status"] == 404


# ---- each open boundary fails exactly its own step ----------------------------------------
@pytest.mark.parametrize(("fault", "steps"), [
    ("cross-owner-open", {"cross-owner", "execute-api-direct"}),
    ("tamper-open", {"tampered-urls"}),
    ("oversize-open", {"oversized-upload"}),
    ("adopts-oversize", {"oversized-upload"}),
    ("s3-listable", {"s3-direct-denied", "tampered-urls"}),  # the unsigned variant too
    ("port-8080-open", {"port-scan"}),
    ("gateway-anonymous-open", {"unauthenticated", "execute-api-direct"}),
])
def test_a_boundary_left_open_fails_its_own_steps_and_nothing_else(
        tmp_path, fixture, fault, steps):
    proof = security.run(build(tmp_path, fault), fixture=fixture)
    assert failing(proof) == steps
    assert set(proof.failed_now()) == steps


def test_storage_that_takes_oversize_bytes_but_finalize_refuses_them_still_passes_and_says_so(
        tmp_path, fixture):
    proof = security.run(build(tmp_path, "no-s3-limit"), fixture=fixture)
    seen = public(proof, "oversized-upload")
    assert statuses(proof)["oversized-upload"] == PASS
    assert seen["refused_only_at_finalize"] and not seen["storage_rejected_oversize"]
    assert seen["finalize_status"] == 422


def test_a_failed_job_skips_every_step_that_needs_it_and_leaves_the_receipt_incomplete(
        tmp_path, fixture):
    ctx = build(tmp_path, encode_seconds=10_000.0)
    proof = security.run(ctx, fixture=fixture, job_timeout=30)
    found = statuses(proof)
    assert found["setup-job"] == FAIL
    assert not security.NEEDS_JOB & set(found)
    assert {"unauthenticated", "port-scan"} <= set(found)
    assert proof.overall() == "SIMULATED"
    assert ctx.world.reservations  # the upload did happen


# ---- the long steps ------------------------------------------------------------------------
def test_both_expiries_run_when_the_wait_covers_them_and_nothing_stays_valid(tmp_path, fixture):
    proof = security.run(build(tmp_path), fixture=fixture, max_expiry_wait=1000)
    assert statuses(proof)["playback-url-expiry"] == PASS
    assert statuses(proof)["upload-url-expiry"] == PASS
    assert public(proof, "playback-url-expiry")["status_after_expiry"] == 403
    assert public(proof, "upload-url-expiry")["control_status"] == 204
    assert public(proof, "upload-url-expiry")["status_after_expiry"] == 403


def test_a_url_that_still_works_after_expiry_fails(tmp_path, fixture):
    proof = security.run(build(tmp_path, "expiry-open"), fixture=fixture, max_expiry_wait=1000)
    assert {"playback-url-expiry", "upload-url-expiry"} <= failing(proof)


def test_the_expiry_wait_rechecks_the_window_and_stops_when_it_closes(tmp_path, fixture):
    ctx = build(tmp_path)
    proof = security.run(ctx, fixture=fixture, only={"setup-job"})
    checks = []
    real = proof.checkpoint
    proof.checkpoint = lambda kind: (checks.append(kind), real(kind))[1]
    security.wait_for(ctx, proof, 45)
    assert checks == ["active"] * 3
    with ctx.journal.locked() as state:
        state["session"] = "closed"
        ctx.journal.save(state)
    with pytest.raises(SessionRefused):
        security.wait_for(ctx, proof, 45)


def test_the_full_size_limit_uploads_one_byte_over_and_must_not_be_adopted(
        tmp_path, fixture, monkeypatch):
    monkeypatch.setattr(security, "MAX_BYTES", 8192)
    ctx = build(tmp_path)
    ctx.world.max_bytes = 8192
    proof = security.run(ctx, fixture=fixture, full_size=True)
    seen = public(proof, "oversize-100mib")
    assert statuses(proof)["oversize-100mib"] == PASS
    assert seen["sent_bytes"] == 8193 and seen["storage_status"] == 400 and not seen["adopted"]


def test_the_full_size_limit_fails_when_the_oversize_object_is_adopted(
        tmp_path, fixture, monkeypatch):
    monkeypatch.setattr(security, "MAX_BYTES", 8192)
    ctx = build(tmp_path, "adopts-oversize")
    ctx.world.max_bytes = 8192
    proof = security.run(ctx, fixture=fixture, full_size=True)
    assert statuses(proof)["oversize-100mib"] == FAIL


# ---- receipt hygiene and resumability ----------------------------------------------------
def test_the_receipt_holds_no_credential_token_cookie_or_signed_url(tmp_path, fixture):
    ctx = build(tmp_path)
    proof = security.run(ctx, fixture=fixture, max_expiry_wait=1000, full_size=False)
    text = proof.path.read_text().lower()
    secrets = [security.derived(ctx, label)["password"] for label in ("a", "b")]
    secrets += [security.derived(ctx, label)["email"] for label in ("a", "b")]
    secrets += ["sim-password", "x-amz-signature", "x-amz-credential", "policy-", "sig-",
                "set-cookie", "access_token", "https://", "http://", "203.0.113."]
    for secret in secrets:
        assert secret.lower() not in text, secret
    assert proof.path.stat().st_mode & 0o777 == 0o600


def test_a_rerun_repeats_nothing_that_already_passed(tmp_path, fixture):
    ctx = build(tmp_path)
    security.run(ctx, fixture=fixture)
    users, reservations, claims = len(ctx.world.users), len(ctx.world.reservations), (
        ctx.world.claims)
    again = security.run(ctx, fixture=fixture)
    assert again.ran == [] and again.failed_now() == []
    assert (len(ctx.world.users), len(ctx.world.reservations), ctx.world.claims) == (
        users, reservations, claims)


def test_the_two_users_are_the_same_on_a_resume_and_a_second_register_is_not_an_error(
        tmp_path, fixture):
    ctx = build(tmp_path)
    first, second = security.account(ctx, "a"), security.account(ctx, "a")
    assert first.cookie == second.cookie and len(ctx.world.users) == 2  # smoke user + A
    assert security.derived(ctx, "a") != security.derived(ctx, "b")
    assert len(security.derived(ctx, "a")["password"]) == 40


def test_only_selects_steps_and_a_step_needing_the_job_is_skipped_without_it(tmp_path, fixture):
    proof = security.run(build(tmp_path), fixture=fixture, only={"cross-owner", "port-scan"})
    assert set(statuses(proof)) == {"port-scan"}


def test_the_harness_refuses_while_the_session_is_closed(tmp_path, fixture):
    with pytest.raises(SessionRefused):
        security.run(build(tmp_path, session="closed"), fixture=fixture)


def test_fresh_may_repeat_a_cheap_step_but_never_the_encoder_job(tmp_path, fixture):
    ctx = build(tmp_path)
    security.run(ctx, fixture=fixture)
    ctx.fresh = {"port-scan"}
    again = security.run(ctx, fixture=fixture)
    assert again.ran == ["port-scan"]
    assert "attempts" in again.doc and again.doc["attempts"]["port-scan"]
    for fresh in (True, {"setup-job", "port-scan"}):
        ctx.fresh = fresh
        with pytest.raises(ProofError, match="second encoder job"):
            security.run(ctx, fixture=fixture)


def test_a_throttled_call_is_retried_and_never_read_as_a_denial(tmp_path):
    ctx = build(tmp_path)
    real, calls = ctx.http, []

    def throttled(method, url, headers, body, timeout):
        calls.append(url)
        if len(calls) <= 2:
            return 429, {}, b"{}"
        return real(method, url, headers, body, timeout)

    ctx.http = throttled
    reply = security.ask(ctx, ctx.api("frontend"), "GET", "/api/media/jobs")
    assert reply.status == 401 and len(calls) == 3  # the authorizer's answer, after two 429s


def test_a_gateway_that_never_stops_throttling_is_reported_as_429_not_as_a_pass(tmp_path):
    ctx = build(tmp_path)
    ctx.http = lambda *args: (429, {}, b"{}")
    reply = security.ask(ctx, ctx.api("frontend"), "GET", "/api/media/jobs")
    assert reply.status == 429


# ---- the network helpers never touch the network in a rehearsal ---------------------------
def test_a_simulated_scan_never_opens_a_socket(tmp_path, fixture, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("a rehearsal opened a socket")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    proof = security.run(build(tmp_path), fixture=fixture, only={"port-scan"})
    assert statuses(proof) == {"port-scan": PASS}


def test_a_live_context_uses_real_sockets_and_a_simulated_one_does_not():
    live = types.SimpleNamespace(simulated=False)
    assert security.edge_hooks(live) == (security.socket_resolve, security.socket_connect)


def test_the_connect_probe_tells_open_refused_filtered_and_unknown_apart(monkeypatch):
    outcomes = {1: None, 2: ConnectionRefusedError(), 3: TimeoutError(), 4: OSError("unreachable")}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def connect(address, timeout):
        outcome = outcomes[address[1]]
        if outcome:
            raise outcome
        return Connection()

    monkeypatch.setattr(socket, "create_connection", connect)
    assert [security.socket_connect("192.0.2.1", port, 1.0) for port in (1, 2, 3, 4)] == [
        "open", "closed", "filtered", "error"]


def test_a_scan_that_cannot_resolve_the_host_is_not_run(tmp_path, fixture):
    ctx = build(tmp_path)
    ctx.world.resolve = lambda host: (_ for _ in ()).throw(OSError("no such host"))
    proof = security.run(ctx, fixture=fixture, only={"port-scan"})
    assert statuses(proof) == {"port-scan": NOT_RUN}


def test_an_unclassifiable_connect_failure_makes_the_scan_not_run_rather_than_pass(
        tmp_path, fixture):
    ctx = build(tmp_path)
    real = ctx.world.connect
    ctx.world.connect = lambda a, p, t: "error" if p == 3306 else real(a, p, t)
    proof = security.run(ctx, fixture=fixture, only={"port-scan"})
    assert statuses(proof) == {"port-scan": NOT_RUN}


# ---- url helpers ---------------------------------------------------------------------------
def test_get_variants_change_one_thing_each_and_keep_the_rest():
    url = ("https://b.s3.ap-southeast-1.amazonaws.com/out/seg0.ts?X-Amz-Algorithm=AWS4"
           "&X-Amz-Expires=900&X-Amz-Signature=abc123")
    variants = security.get_variants(url)
    assert set(variants) == {"signature_changed", "key_changed", "lifetime_extended",
                             "signature_removed", "unsigned"}
    assert security.query_of(variants["signature_changed"])["X-Amz-Signature"] == "abc120"
    assert variants["key_changed"].split("?")[0].endswith("seg0.tsx")
    assert security.query_of(variants["lifetime_extended"])["X-Amz-Expires"] == "9000"
    assert "X-Amz-Signature" not in security.query_of(variants["signature_removed"])
    assert "?" not in variants["unsigned"]


def test_flip_always_changes_the_last_character_and_keeps_the_length():
    assert security.flip("abc0") == "abc1" and security.flip("abc1") == "abc0"
    assert security.flip("a") != "a"


def test_only_a_4xx_counts_as_a_refusal():
    assert [security.rejected(s) for s in (None, 200, 204, 302, 400, 403, 404, 500)] == [
        False, False, False, False, True, True, True, False]


def test_bucket_urls_work_for_path_style_and_virtual_hosted_hosts():
    assert security.bucket_base("https://src.s3.r.amazonaws.com/", "src") == (
        "https://src.s3.r.amazonaws.com")
    assert security.bucket_base("https://s3.r.amazonaws.com/src", "src") == (
        "https://s3.r.amazonaws.com/src")


# ---- wiring --------------------------------------------------------------------------------
def test_the_command_line_runs_the_harness_and_writes_issue_229(tmp_path, fixture):
    out = io.StringIO()
    code = evidence.main(["security", "--profile", "p", "--region", "ap-southeast-1",
                          "--account", "123456789012", "--run-id", "cli", "--dry-run",
                          "--fixture", str(fixture)], stdout=out, world=sim.SimWorld())
    report = json.loads(out.getvalue())
    assert code == 0 and report["issue"] == "#229" and report["overall"] == "SIMULATED"
    assert report["steps"]["port-scan"]["status"] == PASS
    assert report["steps"]["upload-url-expiry"]["status"] == NOT_RUN


def test_the_wait_and_size_options_reach_the_harness(tmp_path, fixture):
    parsed = evidence.build_parser().parse_args([
        "security", "--profile", "p", "--region", "r", "--account", "1", "--run-id", "x",
        "--fixture", "f.mp4", "--max-expiry-wait", "960", "--full-size-limit"])
    assert parsed.max_expiry_wait == 960 and parsed.full_size_limit
    default = evidence.build_parser().parse_args([
        "security", "--profile", "p", "--region", "r", "--account", "1", "--run-id", "x",
        "--fixture", "f.mp4"])
    assert default.max_expiry_wait == security.EXPIRY_WAIT and not default.full_size_limit


def test_the_receipt_is_summarized_with_its_not_run_steps_and_the_job_is_counted(
        tmp_path, fixture):
    ctx = build(tmp_path)
    security.run(ctx, fixture=fixture)
    docs = summary.load(ctx.evidence_dir, "t")
    docs["229"]["mode"] = "live"
    built = summary.build(docs, evidence.REQUIRED, "t", wall=lambda: 0)
    assert built["issues"]["#229"]["overall"] == "PARTIAL"
    assert built["issues"]["#229"]["steps"]["port-scan"]["status"] == PASS
    assert summary.counts(docs)["succeeded"] == 1


def test_every_security_step_is_required_so_a_missing_one_is_incomplete(tmp_path, fixture):
    assert evidence.REQUIRED["229"] == security.STEPS
    ctx = build(tmp_path)
    security.run(ctx, fixture=fixture, only={"port-scan"})
    docs = summary.load(ctx.evidence_dir, "t")
    docs["229"]["mode"] = "live"
    assert summary.overall(docs["229"], security.REQUIRED) == "INCOMPLETE"
