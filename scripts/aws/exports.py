"""Bounded, private cross-owner exports through explicit offline test boundaries.

No subprocess, SDK, AWS profile discovery, EBS delete, or production executor lives here.
The production adapter and authentic restore receipts require later authorization.
"""

import argparse
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.aws.config import CloudConfig, validate_nonsecret

WRITERS = {"media_api", "media_reconciler", "processing_api", "processing_recovery", "migrations"}
FILES = {"media.dump", "processing.dump", "roles.sql"}
REVISIONS = {"media": "0002_uncertain_writes", "processing": "processing_0002"}
MAX_EXPORT_BYTES = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


class ExportBlocked(RuntimeError):
    """No backup success or destructive teardown may follow this result."""


def _config(config):
    if isinstance(config, CloudConfig):
        return config
    if hasattr(config, "to_dict"):
        config = config.to_dict()
    return CloudConfig.from_dict(config)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (ValueError, AttributeError) as exc:
        raise ExportBlocked("Quiescence timestamps must be explicit UTC-aware times") from exc


def validate_quiescence(config, proof, *, now, deadline):
    config = _config(config)
    if deadline <= now or deadline - now > 300:
        raise ExportBlocked("Export requires an absolute deadline within five minutes")
    if not isinstance(proof, dict):
        raise ExportBlocked("Common quiescence proof is required")
    if (
        proof.get("environment_id") != config.environment_id
        or proof.get("operator_station") != config.operator_station
        or not config.environment_id
        or not config.operator_station
    ):
        raise ExportBlocked("Quiescence belongs to a different environment or station")
    boundary = proof.get("boundary_id", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", boundary):
        raise ExportBlocked("Quiescence boundary identity is required")
    if any(
        proof.get(name) is not True
        for name in ["intake_closed", "launches_closed", "workers_drained"]
    ):
        raise ExportBlocked("Intake, launches and worker drain must be closed")
    if any(
        type(proof.get(name)) is not int or proof[name] != 0
        for name in ["active_claims", "nonterminal_tasks", "unresolved_launches"]
    ):
        raise ExportBlocked("Unresolved launches, tasks or claims prevent a common export")
    writers = proof.get("writers_quiesced", {})
    if (
        not isinstance(writers, dict)
        or set(writers) != WRITERS
        or any(v is not True for v in writers.values())
    ):
        raise ExportBlocked("Every owner and background writer must be quiesced")
    issued, expires = _timestamp(proof.get("issued_at")), _timestamp(proof.get("expires_at"))
    if (
        not 0 <= now - issued <= 90
        or expires <= now
        or expires < deadline
        or expires - issued > 300
    ):
        raise ExportBlocked("Quiescence proof is stale or does not cover the export deadline")
    return boundary


def export_command_plan():
    """Use libpq environment/0600 pgpass privately; no DSN or password in command arguments."""
    return {
        "databases": {
            owner: [
                "pg_dump",
                "--host",
                "127.0.0.1",
                "--format",
                "custom",
                "--dbname",
                owner + "_db",
                "--file",
                owner + ".dump",
            ]
            for owner in ["media", "processing"]
        },
        "roles": [
            "psql",
            "-X",
            "--no-psqlrc",
            "--host",
            "127.0.0.1",
            "--dbname",
            "postgres",
            "--tuples-only",
            "--no-align",
            "--set",
            "ON_ERROR_STOP=1",
            "--file",
            "roles-export.sql",
        ],
        "revisions": {
            owner: [
                "psql",
                "-X",
                "--host",
                "127.0.0.1",
                "--dbname",
                owner + "_db",
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT version_num FROM alembic_version",
            ]
            for owner in ["media", "processing"]
        },
        "private": True,
        "execute": False,
    }


def _private_directory(directory):
    directory = Path(directory)
    resolved = directory.resolve()
    if directory.is_symlink() or any((p / ".git").exists() for p in (resolved, *resolved.parents)):
        raise ExportBlocked("Export directory must be outside Git and not a symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ExportBlocked("Export directory must be private mode 0700")
    return directory


def _write_private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def export_state(
    config,
    proof,
    commands,
    storage,
    private_directory,
    *,
    deadline,
    clock=time.time,
    max_bytes=MAX_EXPORT_BYTES,
):
    """commands.dump/revision, storage.put/list_sets/delete_set are bounded test hooks.

    Storage methods acknowledge complete writes; uncertain/failed writes never publish
    the manifest. Retention runs only after its confirmed manifest. EBS is untouched.
    """
    config = _config(config)
    kinds = {getattr(b, "evidence_kind", None) for b in (commands, storage)}
    evidence_kind = "offline"
    if kinds == {"local-services"}:
        from scripts.aws.local_adapters import LocalDump, PrivateFiles

        if type(commands) is not LocalDump or type(storage) is not PrivateFiles:
            raise ExportBlocked("Only concrete bounded local export adapters are allowed")
        evidence_kind = "local-services"
    elif kinds != {"offline"}:
        raise ExportBlocked("Preparation exports require matching explicit local boundaries")
    if config.mode != "plan":
        raise ExportBlocked("Actual AWS export execution is disabled")
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_EXPORT_BYTES:
        raise ExportBlocked("Export byte bound must not exceed 64MiB")
    boundary = validate_quiescence(config, proof, now=clock(), deadline=deadline)
    directory = _private_directory(private_directory)
    target = directory / boundary
    target.mkdir(mode=0o700)  # Exclusive set: no overwrite/reuse after uncertain export.
    prefix = f"private/{config.environment_id}/exports/"
    total, entries, revisions = 0, {}, {}

    def check():
        validate_quiescence(config, proof, now=clock(), deadline=deadline)

    try:
        for owner, filename in [
            ("media", "media.dump"),
            ("processing", "processing.dump"),
            ("roles", "roles.sql"),
        ]:
            check()
            data = commands.dump(owner, deadline=deadline, max_bytes=max_bytes - total)
            if not isinstance(data, bytes) or not data or len(data) > max_bytes - total:
                raise ExportBlocked("Export is empty or exceeds the bounded private size")
            total += len(data)
            _write_private(target / filename, data)
            entries[filename] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if owner != "roles":
                revision = commands.revision(owner, deadline=deadline)
                if revision != REVISIONS[owner]:
                    raise ExportBlocked("Exported schema revision does not match this release")
                revisions[owner] = revision
            check()
            if storage.put(prefix + boundary + "/" + filename, data, deadline=deadline) is not True:
                raise ExportBlocked("Private export write is uncertain")
        manifest = {
            "schema_version": 1,
            "environment_id": config.environment_id,
            "boundary_id": boundary,
            "operator_station": config.operator_station,
            "created_at": datetime.fromtimestamp(clock(), UTC).isoformat(),
            "revisions": revisions,
            "files": entries,
            "total_bytes": total,
            "private_prefix": prefix + boundary + "/",
            "evidence_kind": evidence_kind,
            "restore_status": "NOT_RUN",
            "ebs_deleted": False,
        }
        validate_nonsecret(manifest)
        check()
        encoded = json.dumps(manifest, sort_keys=True, indent=2).encode()
        _write_private(target / "manifest.json", encoded)
        if (
            storage.put(prefix + boundary + "/manifest.json", encoded, deadline=deadline)
            is not True
        ):
            raise ExportBlocked("Private manifest write is uncertain; no backup claim")
        check()
        sets = storage.list_sets(prefix, deadline=deadline)
        # Transport returns committed manifests only; verify before any deletion.
        valid = []
        for item in sets:
            if (
                not isinstance(item, dict)
                or item.get("environment_id") != config.environment_id
                or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", item.get("boundary_id", ""))
                or item.get("private_prefix") != prefix + item["boundary_id"] + "/"
            ):
                raise ExportBlocked("Retention inventory escaped the private export prefix")
            restore_plan(
                item,
                target="restore-retention-check",
                source_environment_id=config.environment_id,
                approved=True,
            )
            created = _timestamp(item.get("created_at"))
            if created > _timestamp(manifest["created_at"]):
                raise ExportBlocked("Retention inventory contains future export sets")
            valid.append((created, item["boundary_id"]))
        if boundary not in [name for _, name in valid] or len(
            set(name for _, name in valid)
        ) != len(valid):
            raise ExportBlocked("Retention inventory is uncertain or duplicate")
        for _, old in sorted(valid, reverse=True)[2:]:
            check()
            if storage.delete_set(prefix + old + "/", deadline=deadline) is not True:
                raise ExportBlocked("Retention did not confirm keeping latest two sets")
        check()
        return {
            "status": "PASS",
            "evidence_kind": evidence_kind,
            "boundary_id": boundary,
            "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": total,
            "restore_status": "NOT_RUN",
            "backup_claim": False,
            "destructive_teardown_allowed": False,
            "ebs_deleted": False,
        }
    except Exception:
        # Preserve partial private files for diagnosis; never expose adapter errors/bytes.
        raise ExportBlocked(
            "Export failed or uncertain; backup and teardown claims blocked; EBS preserved"
        ) from None


def verify_private_export(directory, manifest):
    """Verify retained private bytes before a later isolated restore adapter can proceed."""
    directory = Path(directory)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ExportBlocked("Restore input directory must be private")
    # Reuse the plan's manifest/ownership/size checks, without claiming restore approval.
    restore_plan(
        manifest,
        target="restore-hash-check",
        source_environment_id=manifest.get("environment_id"),
        approved=True,
    )
    for name, entry in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ExportBlocked("Restore input file must be private and regular")
        if path.stat().st_size != entry["bytes"]:
            raise ExportBlocked("Private export length mismatch")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ExportBlocked("Private export hash mismatch")
    return {"hashes_verified": True, "restore_status": "NOT_RUN"}


def restore_plan(manifest, *, target, source_environment_id, approved=False):
    """Hash-verifying isolated restore instructions; never execute or assert a restore."""
    validate_nonsecret(manifest)
    if (
        not approved
        or not re.fullmatch(r"restore-[a-z0-9-]{3,40}", target)
        or target == source_environment_id
        or manifest.get("environment_id") != source_environment_id
        or not source_environment_id
    ):
        raise ExportBlocked("Restore requires explicit approval and an isolated throwaway target")
    if (
        set(manifest.get("files", {})) != FILES
        or manifest.get("revisions") != REVISIONS
        or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", manifest.get("boundary_id", ""))
        or manifest.get("private_prefix")
        != f"private/{source_environment_id}/exports/{manifest['boundary_id']}/"
    ):
        raise ExportBlocked("Restore manifest lacks owned schemas or private prefix")
    total = 0
    for item in manifest["files"].values():
        if (
            not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))
            or type(item.get("bytes")) is not int
            or not 0 < item["bytes"] <= MAX_EXPORT_BYTES
        ):
            raise ExportBlocked("Restore requires bounded lengths and hashes")
        total += item["bytes"]
    if total != manifest.get("total_bytes") or total > MAX_EXPORT_BYTES:
        raise ExportBlocked("Restore manifest byte accounting is invalid")
    return {
        "status": "NOT_RUN",
        "execute": False,
        "target": target,
        "isolated": True,
        "steps": [
            "provision only approved throwaway metadata; never attach live/frozen EBS",
            "download private exports; verify every SHA256 and length before SQL",
            "restore only four scoped owner roles; create both databases owned by their migrators",
            "pg_restore --exit-on-error each database without overwriting live metadata",
            "verify both Alembic revisions, runtime DML, denied DDL and both cross-DB denials",
            "check source and job/attempt/output references against private objects",
            "record private receipts; remove only restore compute and its throwaway volume",
        ],
        "backup_claim": False,
        "live_ebs_deleted": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Offline export/restore command plans only")
    parser.add_argument("action", choices=["plan", "restore-plan"])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--source-environment")
    parser.add_argument("--isolated-approved", action="store_true")
    args = parser.parse_args()
    if args.action == "plan":
        result = export_command_plan()
    else:
        if args.manifest is None or not args.target or not args.source_environment:
            parser.error(
                "Restore planning requires manifest, isolated target and source environment"
            )
        result = restore_plan(
            json.loads(args.manifest.read_text()),
            target=args.target,
            source_environment_id=args.source_environment,
            approved=args.isolated_approved,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
