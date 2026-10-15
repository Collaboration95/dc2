import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from scripts.aws.exports import (
    REVISIONS,
    WRITERS,
    ExportBlocked,
    export_command_plan,
    export_state,
    restore_plan,
    validate_quiescence,
    verify_private_export,
)

NOW = datetime(2026, 10, 15, 3, tzinfo=UTC).timestamp()
CONFIG = {
    "mode": "plan",
    "region": "ap-southeast-1",
    "account_id": "",
    "environment_id": "aws2-demo",
    "public_url": "",
    "source_bucket": "demo-source",
    "output_bucket": "demo-output",
    "operator_station": "station-a",
}


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def proof(**changes):
    value = {
        "environment_id": "aws2-demo",
        "operator_station": "station-a",
        "boundary_id": "session-boundary-001",
        "issued_at": iso(NOW - 2),
        "expires_at": iso(NOW + 120),
        "intake_closed": True,
        "launches_closed": True,
        "workers_drained": True,
        "active_claims": 0,
        "nonterminal_tasks": 0,
        "unresolved_launches": 0,
        "writers_quiesced": dict.fromkeys(WRITERS, True),
    }
    value.update(changes)
    return value


class Commands:
    evidence_kind = "offline"

    def __init__(self, fail=None, bad_revision=False, empty=False):
        self.calls = []
        self.fail = fail
        self.bad_revision = bad_revision
        self.empty = empty

    def dump(self, owner, *, deadline, max_bytes):
        self.calls.append((owner, deadline, max_bytes))
        if self.fail == owner:
            raise RuntimeError("PRIVATE-SENTINEL postgres://fake-secret")
        return b"" if self.empty else ("PRIVATE-SENTINEL-" + owner).encode()

    def revision(self, owner, *, deadline):
        return "wrong-revision" if self.bad_revision else REVISIONS[owner]


class Storage:
    evidence_kind = "offline"

    def __init__(self, fail_suffix=None, inventory=None):
        self.objects = {}
        self.deleted = []
        self.fail_suffix = fail_suffix
        self.inventory = inventory

    def put(self, key, data, *, deadline):
        assert key.startswith("private/aws2-demo/exports/")
        if self.fail_suffix and key.endswith(self.fail_suffix):
            return False
        self.objects[key] = data
        return True

    def list_sets(self, prefix, *, deadline):
        if self.inventory is not None:
            return self.inventory
        current = [json.loads(v) for k, v in self.objects.items() if k.endswith("/manifest.json")]
        return current + [
            {
                **current[0],
                "environment_id": "aws2-demo",
                "boundary_id": name,
                "created_at": iso(NOW - age),
                "private_prefix": prefix + name + "/",
            }
            for name, age in [("previous-set-001", 3600), ("previous-set-002", 7200)]
        ]

    def delete_set(self, prefix, *, deadline):
        self.deleted.append(prefix)
        return True


def run_export(tmp_path, **changes):
    commands, storage = changes.pop("commands", Commands()), changes.pop("storage", Storage())
    result = export_state(
        CONFIG,
        changes.pop("proof", proof()),
        commands,
        storage,
        tmp_path / "private",
        deadline=NOW + 60,
        clock=lambda: NOW,
        **changes,
    )
    return result, commands, storage


def test_both_owners_roles_common_boundary_private_hashes_and_latest_two(tmp_path):
    result, commands, storage = run_export(tmp_path)
    assert [c[0] for c in commands.calls] == ["media", "processing", "roles"]
    assert all(c[1] == NOW + 60 for c in commands.calls)
    assert result["status"] == "PASS" and result["evidence_kind"] == "offline"
    assert not result["backup_claim"] and not result["destructive_teardown_allowed"]
    assert not result["ebs_deleted"] and result["restore_status"] == "NOT_RUN"
    assert storage.deleted == ["private/aws2-demo/exports/previous-set-002/"]
    directory = tmp_path / "private" / proof()["boundary_id"]
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["revisions"] == REVISIONS
    assert "PRIVATE-SENTINEL" not in json.dumps(manifest) + json.dumps(result)
    assert directory.stat().st_mode & 0o077 == 0
    assert all(f.stat().st_mode & 0o077 == 0 for f in directory.iterdir())
    assert verify_private_export(directory, manifest) == {
        "hashes_verified": True,
        "restore_status": "NOT_RUN",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"environment_id": "different-env"},
        {"operator_station": "different-station"},
        {"boundary_id": "../escape"},
        {"intake_closed": False},
        {"launches_closed": False},
        {"workers_drained": False},
        {"active_claims": 1},
        {"nonterminal_tasks": 1},
        {"unresolved_launches": 1},
        {"unresolved_launches": False},
        {"issued_at": iso(NOW - 91)},
        {"issued_at": iso(NOW + 1)},
        {"expires_at": iso(NOW + 30)},
        {"writers_quiesced": {"media_api": True}},
        {"writers_quiesced": {**dict.fromkeys(WRITERS, True), "processing_recovery": False}},
    ],
)
def test_invalid_quiescence_refuses_before_any_dump_or_storage(tmp_path, changes):
    commands, storage = Commands(), Storage()
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, proof=proof(**changes), commands=commands, storage=storage)
    assert commands.calls == [] and storage.objects == {} and storage.deleted == []


@pytest.mark.parametrize("deadline", [NOW, NOW + 301])
def test_absolute_deadline_is_required(deadline):
    with pytest.raises(ExportBlocked):
        validate_quiescence(CONFIG, proof(), now=NOW, deadline=deadline)


@pytest.mark.parametrize("owner", ["media", "processing", "roles"])
def test_failed_dump_preserves_partial_private_data_and_no_manifest_claim(tmp_path, owner):
    commands, storage = Commands(fail=owner), Storage()
    with pytest.raises(ExportBlocked) as error:
        run_export(tmp_path, commands=commands, storage=storage)
    assert "PRIVATE-SENTINEL" not in str(error.value)
    assert "EBS preserved" in str(error.value)
    assert not any(k.endswith("manifest.json") for k in storage.objects)
    assert storage.deleted == []


@pytest.mark.parametrize("suffix", ["media.dump", "processing.dump", "roles.sql", "manifest.json"])
def test_uncertain_storage_write_blocks_claim_and_retention(tmp_path, suffix):
    storage = Storage(fail_suffix=suffix)
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, storage=storage)
    assert storage.deleted == []


def test_bad_schema_empty_or_oversize_export_blocked(tmp_path):
    for index, changes in enumerate(
        [
            {"commands": Commands(bad_revision=True)},
            {"commands": Commands(empty=True)},
            {"max_bytes": 1},
        ]
    ):
        folder = tmp_path / str(index)
        with pytest.raises(ExportBlocked):
            run_export(folder, **changes)


def test_clock_expiry_after_first_dump_blocks_manifest(tmp_path):
    ticks = iter([NOW, NOW, NOW + 100])
    storage = Storage()
    with pytest.raises(ExportBlocked):
        export_state(
            CONFIG,
            proof(),
            Commands(),
            storage,
            tmp_path / "private",
            deadline=NOW + 60,
            clock=lambda: next(ticks),
        )
    assert storage.objects == {} and storage.deleted == []


def test_retention_does_not_delete_outside_prefix(tmp_path):
    bad = {
        "environment_id": "aws2-demo",
        "boundary_id": "previous-set-001",
        "created_at": iso(NOW - 1),
        "private_prefix": "sources/private/",
    }
    storage = Storage(inventory=[bad])
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, storage=storage)
    assert storage.deleted == []


def test_real_adapter_and_shared_directory_refused(tmp_path):
    commands = Commands()
    commands.evidence_kind = "aws"
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, commands=commands)
    private = tmp_path / "private"
    private.mkdir(mode=0o755)
    private.chmod(0o755)
    with pytest.raises(ExportBlocked):
        run_export(tmp_path)


def test_isolated_restore_plan_and_tampered_bytes(tmp_path):
    run_export(tmp_path)
    directory = tmp_path / "private" / proof()["boundary_id"]
    manifest = json.loads((directory / "manifest.json").read_text())
    plan = restore_plan(
        manifest, target="restore-check-001", source_environment_id="aws2-demo", approved=True
    )
    assert plan["status"] == "NOT_RUN" and plan["execute"] is False and plan["isolated"]
    for target, approval in [("aws2-demo", True), ("restore-check-001", False), ("../live", True)]:
        with pytest.raises(ExportBlocked):
            restore_plan(
                manifest, target=target, source_environment_id="aws2-demo", approved=approval
            )
    corrupted = deepcopy(manifest)
    corrupted["files"]["media.dump"]["sha256"] = "0" * 64
    with pytest.raises(ExportBlocked, match="hash mismatch"):
        verify_private_export(directory, corrupted)
    (directory / "media.dump").write_bytes(b"tampered")
    with pytest.raises(ExportBlocked, match="length mismatch"):
        verify_private_export(directory, manifest)


def test_export_plan_uses_libpq_private_injection_and_scoped_roles():
    plan = export_command_plan()
    assert plan["execute"] is False and plan["private"]
    assert "pg_dumpall" not in json.dumps(plan)
    assert "postgres://" not in json.dumps(plan)
    assert "roles-export.sql" in plan["roles"]


def test_lost_quiescence_between_owner_dumps_blocks_common_manifest(tmp_path):
    common = proof()

    class LostFence(Commands):
        def dump(self, owner, *, deadline, max_bytes):
            data = super().dump(owner, deadline=deadline, max_bytes=max_bytes)
            common["writers_quiesced"]["processing_recovery"] = False
            return data

    storage = Storage()
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, commands=LostFence(), storage=storage, proof=common)
    assert storage.objects == {} and storage.deleted == []


def test_incomplete_manifest_cannot_displace_latest_two_sets(tmp_path):
    storage = Storage(
        inventory=[
            {
                "environment_id": "aws2-demo",
                "boundary_id": "partial-set-001",
                "private_prefix": "private/aws2-demo/exports/partial-set-001/",
                "created_at": iso(NOW - 1),
            }
        ]
    )
    with pytest.raises(ExportBlocked):
        run_export(tmp_path, storage=storage)
    assert storage.deleted == []
