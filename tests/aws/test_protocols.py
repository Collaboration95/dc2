from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts.aws.protocols import capacity, check, manifest, preconditions, run
from scripts.aws.smoke import Ledger


def terminal():
    return {"inventory_complete": True, "unresolved_launches": 0, "tasks": [{"status": "STOPPED"}]}


def test_manifest_all_original_live_issues_not_run_and_runner_cannot_claim_aws():
    assert {r["issue"] for r in manifest()} == {63, 64, 65, 66, 67}
    assert all(r["mode"] == "aws" and r["status"] == "NOT_RUN" for r in manifest())
    with pytest.raises(ValueError, match="cannot execute AWS"):
        run("ownership", None, mode="aws", deadline=datetime.now(UTC) + timedelta(seconds=10))


def test_approval_deadlines_origin_and_original_window():
    config = {
        "account_id": "dummy",
        "origin_transport_accepted": True,
        "session_end_utc": "2026-10-15T01:00:00Z",
        "approval": {
            "authorization_id": "dummy",
            "account_id": "dummy",
            "currency": "USD",
            "spending_limit": 15,
            "operator_station": "dummy",
        },
    }
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert preconditions(config, now=now).hour == 1
    for change in [
        {"max_worker_tasks": 4},
        {"origin_transport_accepted": False},
        {"account_id": "other"},
        {"session_end_utc": "2026-10-30T00:00:00Z"},
        {"approval": {}},
    ]:
        with pytest.raises(ValueError):
            preconditions({**config, **change}, now=now)
    with pytest.raises(ValueError, match="window exhausted"):
        preconditions(config, now=datetime(2026, 10, 29, tzinfo=UTC))


def test_failed_receipt_safe_and_deadline_required():
    operator = SimpleNamespace(
        observe=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private-token"))
    )
    result = run("worker_loss", operator, deadline=datetime.now(UTC) + timedelta(seconds=10))
    assert result["status"] == "FAIL" and "private" not in str(result)
    with pytest.raises(ValueError, match="deadline"):
        run("worker_loss", operator)


def test_worker_loss_reuses_source_and_fences_publication():
    r = {
        "active_before": True,
        "attempt_before": "old",
        "interrupted_attempt": "old",
        "interrupted_status": "failed",
        "visible_seconds": 299,
        "retry_attempt": "new",
        "source_sha_before": "sha",
        "source_sha_after": "sha",
        "retry_status": "succeeded",
        "retry_upload_bytes": 0,
        "authoritative_primaries": 1,
    }
    check("worker_loss", r)
    for k, v in [
        ("visible_seconds", 301),
        ("retry_upload_bytes", 1),
        ("authoritative_primaries", 2),
        ("retry_attempt", "old"),
        ("interrupted_status", "running"),
    ]:
        with pytest.raises(ValueError):
            check("worker_loss", {**r, k: v})


def test_queue_repair_preserves_attempt_and_deadline():
    r = {
        "removed_entries": 1,
        "job_hash_survived": True,
        "attempt_before": "same",
        "attempt_after": "same",
        "repair_seconds": 120,
        "status": "succeeded",
    }
    check("queue_loss", r)
    with pytest.raises(ValueError):
        check("queue_loss", {**r, "attempt_after": "new"})
    with pytest.raises(ValueError):
        check("queue_loss", {**r, "repair_seconds": 121})


def test_release_peer_unchanged_and_no_manual_rescue_spliced_into_pass():
    r = {
        **terminal(),
        "peer_before": {"tasks": ["media-1"], "digest": "sha", "schema": "head"},
        "migration_status": "STOPPED",
        "migration_exit_code": 0,
        "schema_backward_compatible": True,
        "destructive_downmigration": False,
        "public_smoke_ok": True,
        "scan_disposition": "skipped",
        "tests_passed": True,
        "image_scan_passed": True,
        "active_drain_captured": True,
        "candidate_started": True,
        "candidate_failed": True,
        "automatic_restore": True,
        "manual_rescue": False,
        "digest_after": "old",
        "prior_digest": "old",
        "elapsed_seconds": 299,
    }
    r["peer_after"] = deepcopy(r["peer_before"])
    check("processing_bad_candidate", r)
    for change in [
        {"manual_rescue": True},
        {"peer_after": {"tasks": ["media-2"]}},
        {"elapsed_seconds": 301},
        {"migration_exit_code": 1},
    ]:
        with pytest.raises(ValueError):
            check("processing_bad_candidate", {**r, **change})


def test_zero_compute_uses_complete_nonterminal_inventory_not_only_desired_counts():
    r = {
        **terminal(),
        "services": {"media": 0, "processing_api": 0, "processing_recovery": 0},
        "state_status": "stopped",
        "public_ipv4": None,
        "eips": [],
        "generator_status": "terminated",
        "generator_volume_deleted": True,
        "launch_interlock_closed": True,
        "automatic_launch_paths": [],
    }
    check("zero_compute", r)
    for change in [
        {"tasks": [{"status": "STOPPING"}]},
        {"unresolved_launches": 1},
        {"inventory_complete": False},
        {"generator_volume_deleted": False},
        {"public_ipv4": "dummy-ip"},
    ]:
        with pytest.raises(ValueError):
            check("zero_compute", {**r, **change})


def test_decoded_hls_uses_existing_pure_assertion_and_records_null_origin_failure():
    r = {
        "normal_trust": True,
        "range_status": 206,
        "seek_succeeded": True,
        "hls_decoded_frames": 5,
        "redirect_cors_ok": True,
        "before": {"current_time": 0, "decoded_frames": 0},
        "after": {
            "current_time": 1,
            "decoded_frames": 5,
            "selected_hls": True,
            "ready": 2,
            "error": None,
        },
    }
    check("web_playback", r)
    with pytest.raises(ValueError):
        check("web_playback", {**r, "redirect_cors_ok": False})
    r["after"]["decoded_frames"] = 0
    with pytest.raises(AssertionError):
        check("web_playback", r)


class Operator:
    def __init__(self, fail=False):
        self.events, self.count, self.fail = [], 0, fail

    def prewarm(self, count, **kw):
        self.events.append(("prewarm", count))
        self.count = count
        return {
            "ready": True,
            "task_ids": list(range(count)),
            "nonterminal_plus_reserved": count,
            "ordinary_nonburst": True,
        }

    def submit(self, fixture, **kw):
        self.events.append(("submit", fixture["id"]))
        if self.fail:
            raise RuntimeError("private-failure")
        return fixture["id"]

    def wait_jobs(self, jobs, **kw):
        return [{"job_id": j, "status": "succeeded"} for j in jobs]

    def drain(self, **kw):
        self.events.append(("drain", self.count))
        return terminal()


def test_capacity_exact_six_after_prewarm_and_drain_between_batches():
    operator, ledger = Operator(), Ledger()
    fixtures = [{"id": str(n), "payload": b"tiny-offline-long-fixture"} for n in range(6)]
    result = capacity(
        operator, fixtures, ledger, deadline=datetime.now(UTC) + timedelta(seconds=10)
    )
    assert [b["count"] for b in result] == [1, 2, 3] and ledger.long_jobs == 6
    assert [e for e in operator.events if e[0] == "prewarm"] == [
        ("prewarm", 1),
        ("prewarm", 2),
        ("prewarm", 3),
    ]
    assert operator.events[:3] == [("prewarm", 1), ("submit", "0"), ("drain", 1)]
    with pytest.raises(ValueError):
        ledger.reserve("extra", b"x", duration_seconds=60, batch=3)


def test_capacity_failure_consumes_reservation_and_still_drains():
    operator, ledger = Operator(fail=True), Ledger()
    with pytest.raises(ValueError, match="^Capacity protocol failed$"):
        capacity(
            operator,
            [{"id": str(n), "payload": b"x"} for n in range(6)],
            ledger,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
        )
    assert ledger.long_jobs == 1 and operator.events[-1] == ("drain", 1)
    with pytest.raises(ValueError, match="batch"):
        ledger.reserve("retry", b"x", duration_seconds=60, batch=1)


def test_ledger_upload_limits_tasks_and_stored_retry_no_reupload():
    ledger = Ledger(upload_limit=4, task_hour_limit=1)
    with pytest.raises(ValueError, match="prewarmed"):
        ledger.reserve("f", b"x", duration_seconds=60)
    ledger.reserve("f", b"abc", duration_seconds=1)
    ledger.job("job", "f", "failed")
    ledger.job("job", "f", "succeeded")
    assert ledger.upload_bytes == 3
    with pytest.raises(ValueError, match="exhausted"):
        ledger.reserve("more", b"xx", duration_seconds=1)
    ledger.task("task", 0.9)
    with pytest.raises(ValueError, match="duplicate"):
        ledger.task("task", 0.1)
    with pytest.raises(ValueError, match="allowance"):
        ledger.task("other", 0.2)


def test_runner_positive_is_offline_only_and_pass_does_not_set_aws_status():
    r = {
        "processing_unavailable": True,
        "media_accepted": True,
        "durable_intent": True,
        "reconciled": True,
        "same_job": True,
        "status": "succeeded",
    }
    observed = []

    def observe(action, **kw):
        observed.append((action, kw))
        return r

    result = run(
        "processing_outage",
        SimpleNamespace(observe=observe),
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert result == {"mode": "offline", "issue": 64, "case": "processing_outage", "status": "PASS"}
    assert observed[0][1]["preconditions"] == ("durable_media_intent", "short_fixture")
    assert all(record["status"] == "NOT_RUN" for record in manifest())


def test_uncertain_drain_blocks_capacity_and_retains_safe_failure(tmp_path):
    from scripts.aws.evidence import Evidence

    operator = Operator()
    operator.drain = lambda **kw: {
        "inventory_complete": False,
        "unresolved_launches": 0,
        "tasks": [],
    }
    evidence = Evidence(tmp_path / "records")
    ledger = Ledger(evidence=evidence)
    with pytest.raises(ValueError, match="^Capacity drain failed$"):
        capacity(
            operator,
            [{"id": str(n), "payload": b"x"} for n in range(6)],
            ledger,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
        )
    assert ledger.long_jobs == 1
    assert ledger.records[-1]["failure_code"] == "capacity_drain_failed"
    assert "private" not in (evidence.directory / "ledger.jsonl").read_text()
