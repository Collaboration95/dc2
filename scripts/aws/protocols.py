"""Runnable bounded receipt checks for 63–67; AWS execution is deliberately gated."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.aws.evidence import select
from scripts.dev.e2e_clients import assert_video_progress

ANCHOR = datetime(2026, 10, 15, tzinfo=UTC)
END = datetime(2026, 10, 29, tzinfo=UTC)


@dataclass(frozen=True)
class Case:
    issue: int
    name: str
    operator_action: str
    requirements: tuple[str, ...]


CASES = (
    Case(
        63,
        "public_workflow",
        "workflow",
        ("approved_account", "origin_decision", "three_services", "owner_migrations"),
    ),
    Case(63, "storage_permissions", "storage_permissions", ("task_roles", "private_buckets")),
    Case(63, "web_playback", "web_playback", ("normal_trust", "short_fixture", "actual_browser")),
    Case(63, "cli_partial_failure", "cli_partial_failure", ("private_jar", "short_fixture")),
    Case(63, "ownership", "ownership", ("two_owners", "authenticated_http")),
    Case(
        63,
        "wake_persistence",
        "wake_persistence",
        ("lifecycle_adapter", "owned_metadata", "stored_source"),
    ),
    Case(
        64,
        "capacity",
        "capacity",
        ("manual_interlock", "fixed_prewarm", "six_long_upload_allowance"),
    ),
    Case(64, "worker_loss", "worker_loss", ("active_attempt", "online_recovery", "stored_source")),
    Case(64, "queue_loss", "queue_loss", ("queued_attempt", "online_recovery")),
    Case(64, "processing_outage", "processing_outage", ("durable_media_intent", "short_fixture")),
    Case(64, "finite_worker", "finite_worker", ("finite_wrapper", "manual_interlock")),
    Case(
        65,
        "processing_release",
        "processing_release",
        ("scanned_exact_digest", "owner_release_adapter"),
    ),
    Case(
        65,
        "processing_bad_candidate",
        "processing_bad_candidate",
        ("tested_bad_digest", "automatic_restore"),
    ),
    Case(
        65, "media_release", "media_release", ("owner_release_adapter", "prior_schema_compatible")
    ),
    Case(
        65, "media_rollback", "media_rollback", ("owner_release_adapter", "prior_schema_compatible")
    ),
    Case(
        66,
        "latency",
        "latency",
        ("independent_generator", "one_status_login_cycle", "actual_hash_cost"),
    ),
    Case(
        67,
        "zero_compute",
        "zero_compute",
        ("all_task_inventory", "launch_interlock", "close_adapter"),
    ),
    Case(67, "restore", "restore", ("quiescent_export", "isolated_restore_target")),
    Case(
        67,
        "cost_closeout",
        "cost_closeout",
        ("pull_to_stop_ledger", "retained_inventory", "selected_bill_lines"),
    ),
)


def manifest():
    return [
        {
            "issue": c.issue,
            "case": c.name,
            "operator_action": c.operator_action,
            "preconditions": list(c.requirements),
            "mode": "aws",
            "status": "NOT_RUN",
        }
        for c in CASES
    ]


def preconditions(config, *, now=None):
    """Plain config values; no optional bundle import, profiles, credentials or discovery."""
    if hasattr(config, "to_dict"):
        config = config.to_dict()
    now = now or datetime.now(UTC)
    if not ANCHOR <= now < END:
        raise ValueError("Original fourteen-day window exhausted")
    if not 0 < config.get("max_worker_tasks", 3) <= 3:
        raise ValueError("Worker cap exceeds approved topology")
    if config.get("origin_transport_accepted") is not True:
        raise ValueError("Origin interpretation remains unresolved")
    approval = config.get("approval", {})
    for key in ["authorization_id", "account_id", "currency", "spending_limit", "operator_station"]:
        if not approval.get(key):
            raise ValueError("Missing named approval input")
    if config.get("account_id") != approval["account_id"]:
        raise ValueError("Approval account differs from context")
    deadline = datetime.fromisoformat(config["session_end_utc"].replace("Z", "+00:00"))
    if deadline.tzinfo is None or not now < deadline <= END:
        raise ValueError("Invalid session deadline")
    return deadline


def require(condition):
    if not condition:
        raise ValueError("Protocol receipt assertion failed")


def terminal_tasks(receipt):
    require(receipt.get("inventory_complete") is True)
    require(receipt.get("unresolved_launches") == 0)
    require(all(t.get("status") == "STOPPED" for t in receipt["tasks"]))


def check(case, r):
    """Consume selected typed observations, never rely on an operator-supplied PASS."""
    if case == "public_workflow":
        require(r["normal_trust"] and r["publisher_api_only"] and r["private_peers"])
        require(
            r["services"]
            == {"media": [1, 2], "processing_api": [0.5, 1], "processing_recovery": [0.25, 0.5]}
        )
        require(
            r["state_type"] == "t3a.small"
            and r["state_processes"] == ["postgres", "redis", "nginx"]
        )
        require(r["owner_migrations"] == {"media": 0, "processing": 0})
        require(r["db_denials"] == {"media_to_processing": True, "processing_to_media": True})
        require(all(r[k] for k in ["login", "upload", "status", "retry", "edit", "delete"]))
        require(r["cpu_credits_ok"] and r["disk_headroom_ok"] and r["rss_limits_ok"])
    elif case == "storage_permissions":
        expected_denials = {
            "worker_source_get",
            "worker_output_get",
            "worker_output_head",
            "worker_output_delete",
            "worker_output_list",
            "cleanup_put",
            "cleanup_get",
            "media_output_put",
            "media_output_delete",
            "unsigned",
            "tampered",
            "expired",
        }
        require(
            expected_denials <= set(r["denials"]) and all(r["denials"][k] for k in expected_denials)
        )
        require(r["writer_multipart_parts"] >= 2 and r["writer_abort_ack"])
        require(r["media_source_grant"] and r["cleanup_list_delete"] and r["new_grant_valid"])
        require(r["credential_refresh"] in {"OBSERVED", "NOT_RUN"})
    elif case == "web_playback":
        require(r["normal_trust"] and r["range_status"] == 206 and r["seek_succeeded"])
        require(r["hls_decoded_frames"] > 0 and r["redirect_cors_ok"])
        assert_video_progress(r["before"], r["after"], "hls")
    elif case == "cli_partial_failure":
        require(r["api_only"] and r["private_jar"] and r["file_count"] == 2)
        require(r["successes"] == 1 and r["failures"] == 1 and r["exit_code"] != 0)
    elif case == "ownership":
        expected = {
            "read",
            "retry",
            "play",
            "unauthenticated",
            "internal_public",
            "same_url_other_owner",
            "error_forwarding",
            "cookie_forwarding",
            "no_auth_cache",
        }
        require(expected <= r["denials"].keys() and all(r["denials"][k] for k in expected))
    elif case == "wake_persistence":
        require(r["viewer_before"] == r["viewer_after"] and r["origin_before"] != r["origin_after"])
        require(
            r["owner_before"] == r["owner_after"] and r["metadata_before"] == r["metadata_after"]
        )
        require(r["source_sha_before"] == r["source_sha_after"] and r["playback_ok"])
    elif case == "capacity":
        require([b["count"] for b in r["batches"]] == [1, 2, 3])
        jobs = []
        for b in r["batches"]:
            count = b["count"]
            require(b["prewarmed"] and b["ordinary_nonburst"] and b["previous_batch_stopped"])
            require(len(set(b["task_ids"])) == count and len(b["jobs"]) == count)
            require(b["concurrent_claims"] == count and b["nonterminal_plus_reserved"] <= 3)
            require(b["vcpu"] == 2 and b["memory_gb"] == 4 and b["stopped_after"])
            require(
                all(j["status"] == "succeeded" and j["mp4_ok"] and j["hls_ok"] for j in b["jobs"])
            )
            jobs.extend(b["jobs"])
        require(len({j["job_id"] for j in jobs}) == 6)
        require(r["long_uploads_total"] == 6 and r["source_multipart_parts"] >= 2)
        require(r["source_multipart_ack"] and r["upload_bytes"] <= 250_000_000)
        terminal_tasks(r)
    elif case == "worker_loss":
        require(r["active_before"] and r["attempt_before"] == r["interrupted_attempt"])
        require(
            r["interrupted_status"] in {"failed", "abandoned"} and 0 <= r["visible_seconds"] <= 300
        )
        require(
            r["retry_attempt"] != r["attempt_before"]
            and r["source_sha_before"] == r["source_sha_after"]
        )
        require(
            r["retry_status"] == "succeeded"
            and r["retry_upload_bytes"] == 0
            and r["authoritative_primaries"] == 1
        )
    elif case == "queue_loss":
        require(r["removed_entries"] == 1 and r["job_hash_survived"])
        require(r["attempt_before"] == r["attempt_after"] and 0 <= r["repair_seconds"] <= 120)
        require(r["status"] == "succeeded")
    elif case == "processing_outage":
        require(r["processing_unavailable"] and r["media_accepted"] and r["durable_intent"])
        require(r["reconciled"] and r["same_job"] and r["status"] == "succeeded")
    elif case == "finite_worker":
        require(
            r["burst_empty_stopped"] and r["late_arrival_queued"] and r["manual_restart_required"]
        )
        require(
            r["redis_loss_stopped"]
            and r["continuous_work_stopped"]
            and r["finite_lifetime_seconds"] > 0
        )
        require(
            r["elapsed_seconds"] <= r["finite_lifetime_seconds"] + r["warm_drain_bound_seconds"]
        )
        require(r["warm_drain_outcome"] in {"completed", "forced_with_failed_claim"})
        terminal_tasks(r)
    elif case in {
        "processing_release",
        "processing_bad_candidate",
        "media_release",
        "media_rollback",
    }:
        require(r["peer_before"] == r["peer_after"] and bool(r["peer_before"]))
        require(r["migration_status"] == "STOPPED" and r["migration_exit_code"] == 0)
        require(r["schema_backward_compatible"] and not r["destructive_downmigration"])
        require(r["public_smoke_ok"] and r["scan_disposition"] in {"executed", "skipped", "error"})
        require(r["tests_passed"] and r["image_scan_passed"] and r["active_drain_captured"])
        if case == "processing_bad_candidate":
            require(r["candidate_started"] and r["candidate_failed"] and r["automatic_restore"])
            require(not r["manual_rescue"] and r["digest_after"] == r["prior_digest"])
            require(0 <= r["elapsed_seconds"] <= 300)
        elif case == "media_rollback":
            require(r["rollback_executed"] and r["digest_after"] == r["prior_digest"])
            require(0 <= r["elapsed_seconds"] <= 300)
        else:
            require(r["digest_after"] == r["selected_digest"] and 0 <= r["elapsed_seconds"] <= 600)
        terminal_tasks(r)
    elif case == "latency":
        require(r["generator_independent"] and r["cycles"] == 1 and r["serial_windows"])
        require(r["hash_cost"] == r["configured_hash_cost"])
        for name in ["status", "login"]:
            require(r[name]["eligible"] and r[name]["status"] == "PASS")
        require(r["status"]["users"] == 50 and r["status"]["duration_seconds"] == 180)
        require(
            r["login"]["users"] == 20
            and r["generator_type"] == "c6a.large"
            and r["generator_root_gb"] == 8
        )
    elif case == "zero_compute":
        require(r["services"] == {"media": 0, "processing_api": 0, "processing_recovery": 0})
        terminal_tasks(r)
        require(r["state_status"] == "stopped" and not r["public_ipv4"] and not r["eips"])
        require(r["generator_status"] == "terminated" and r["generator_volume_deleted"])
        require(r["launch_interlock_closed"] and not r["automatic_launch_paths"])
    elif case == "restore":
        require(r["quiescent_both_owners"] and r["roles_restored"] and r["references_consistent"])
        require(r["source_consistent"] and r["isolated_target"] and r["restore_verified"])
        terminal_tasks(r)
    elif case == "cost_closeout":
        require(r["all_tasks_accounted"] and r["pull_minimums_overlap_ip_included"])
        require(r["retained_baseline_count"] == 1 and r["private_zone_october_charges"] == 1)
        require(r["billing_status"] in {"PENDING", "DELAYED_RECEIPT"})
        require(r["latency_receipt_consumed"] and r["original_local_provenance_preserved"])
        required_inventory = {
            "ebs",
            "s3",
            "incomplete_mpu",
            "ecr",
            "logs",
            "private_dns",
            "cloudfront",
        }
        require(required_inventory <= r["retained_inventory"].keys())
        require(r["teardown"] in {"NOT_RUN", "AUTHORIZED_RECEIPTS"})
    else:
        raise ValueError("Unknown protocol case")


def run(case, operator, *, mode="offline", deadline=None):
    if mode not in {"offline", "emulator", "local-services"}:
        raise ValueError("Preparation runner cannot execute AWS cases")
    spec = next(c for c in CASES if c.name == case)
    if deadline is None or deadline.tzinfo is None or deadline <= datetime.now(UTC):
        raise ValueError("Finite future protocol deadline required")
    record = {"mode": mode, "issue": spec.issue, "case": case, "status": "NOT_RUN"}
    try:
        receipt = operator.observe(
            spec.operator_action, deadline=deadline, preconditions=spec.requirements
        )
        if datetime.now(UTC) > deadline:
            raise ValueError("Protocol deadline exceeded")
        check(case, receipt)
        record["status"] = "PASS"
    except Exception:
        record.update(status="FAIL", failure_code="protocol_check_failed")
    return select(record)


def capacity(operator, fixtures, ledger, *, deadline):
    """Prewarm before reservations/submissions; drain in finally, stop on uncertainty."""
    if deadline is None or deadline.tzinfo is None or deadline <= datetime.now(UTC):
        raise ValueError("Finite future capacity deadline required")
    if len(fixtures) != 6:
        raise ValueError("Exactly six future long capacity fixtures required")
    batches, offset = [], 0
    for count in [1, 2, 3]:
        try:
            require(datetime.now(UTC) < deadline)
            warm = operator.prewarm(count, deadline=deadline)
            require(
                warm["ready"]
                and len(set(warm["task_ids"])) == count
                and warm["nonterminal_plus_reserved"] <= 3
                and warm["ordinary_nonburst"]
            )
            jobs = []
            for fixture in fixtures[offset : offset + count]:
                require(datetime.now(UTC) < deadline)
                ledger.reserve(fixture["id"], fixture["payload"], duration_seconds=60, batch=count)
                jobs.append(operator.submit(fixture, deadline=deadline))
            result = operator.wait_jobs(jobs, deadline=deadline)
            require(all(j["status"] == "succeeded" for j in result))
            batches.append({"count": count, "task_ids": warm["task_ids"], "jobs": result})
            offset += count
        except Exception:
            ledger.append({"case": "capacity", "status": "FAIL", "failure_code": "capacity_failed"})
            raise ValueError("Capacity protocol failed") from None
        finally:
            try:
                drained = operator.drain(deadline=deadline)
                terminal_tasks(drained)
            except Exception:
                ledger.append(
                    {"case": "capacity", "status": "FAIL", "failure_code": "capacity_drain_failed"}
                )
                raise ValueError("Capacity drain failed") from None
    return batches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipts", type=Path)
    args = parser.parse_args()
    if args.receipts:
        # Offline replay only. No mode override or dynamic operator/plugin execution.
        results = []
        for r in json.loads(args.receipts.read_text()):
            record = {"mode": "offline", "case": r["case"], "status": "PASS"}
            try:
                check(r["case"], r["observations"])
            except Exception:
                record.update(status="FAIL", failure_code="protocol_check_failed")
            results.append(select(record))
        print(json.dumps(results, indent=2))
        if any(r["status"] == "FAIL" for r in results):
            raise SystemExit(1)
    else:
        print(json.dumps(manifest(), indent=2))


if __name__ == "__main__":
    main()
