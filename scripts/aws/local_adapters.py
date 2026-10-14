"""Bounded loopback SQL/RQ and private export bindings for preparation checks."""

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from scripts.aws.exports import WRITERS
from scripts.aws.transport import OperationError, remaining


class LocalData:
    """Each query selects one owner's explicit private loopback DSN; never discovers it."""

    def __init__(self, media_dsn, processing_dsn, redis_url):
        self._dsns = {"media": media_dsn, "processing": processing_dsn}
        for uri in (*self._dsns.values(), redis_url):
            if urlsplit(uri).hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise OperationError("Local preparation data must use explicit loopback endpoints")
        from redis import Redis

        self.redis = Redis.from_url(redis_url, socket_timeout=1, socket_connect_timeout=1)

    def query(self, owner, sql, args=(), *, deadline):
        if owner not in self._dsns:
            raise OperationError("Select an owned database")

        async def execute():
            import asyncpg

            connection = await asyncpg.connect(
                self._dsns[owner].replace("postgresql+asyncpg://", "postgresql://"),
                timeout=min(2, remaining(deadline)),
            )
            try:
                return [
                    dict(row)
                    for row in await connection.fetch(
                        sql, *args, timeout=min(2, remaining(deadline))
                    )
                ]
            finally:
                await connection.close(timeout=min(1, remaining(deadline)))

        try:
            return asyncio.run(asyncio.wait_for(execute(), timeout=remaining(deadline)))
        except Exception:
            raise OperationError("Bounded local owned-database observation failed") from None

    def schema_revision(self, owner, *, deadline):
        rows = self.query(owner, "SELECT version_num FROM alembic_version", deadline=deadline)
        if len(rows) != 1:
            raise OperationError("Owned schema revision is unavailable")
        return rows[0]["version_num"]

    def observe_worker(self, task, name, *, deadline):
        remaining(deadline)
        key = "rq:worker:" + name
        try:
            metadata = self.redis.hgetall(key)
            ids = set(json.loads(metadata.get(b"dc2_claims", b"[]")))
            current = metadata.get(b"current_job")
            if current:
                ids.add(current.decode())
            parsed = [UUID(value) for value in ids]
            rows = (
                self.query(
                    "processing",
                    "SELECT id::text AS id,state FROM attempts WHERE id=ANY($1::uuid[])",
                    (parsed,),
                    deadline=deadline,
                )
                if parsed
                else []
            )
            remaining(deadline)
            return {
                "fresh": self._fresh(metadata),
                "claims_stopped": metadata.get(b"dc2_warm_ack") is not None,
                "claims": sorted(ids),
                "outcomes": {r["id"]: r["state"] for r in rows},
            }
        except Exception:
            raise OperationError("Correlated local worker observation unavailable") from None

    def _fresh(self, metadata):
        heartbeat = metadata.get(b"last_heartbeat")
        ack = metadata.get(b"dc2_warm_ack")
        try:
            stamp = (
                float(ack)
                if ack
                else datetime.fromisoformat(heartbeat.decode().replace("Z", "+00:00"))
                .replace(tzinfo=UTC)
                .timestamp()
            )
            seconds, micros = self.redis.time()
            return -2 <= seconds + micros / 1e6 - stamp <= 120
        except (ValueError, AttributeError, TypeError):
            return False

    def warm_shutdown(self, task, name, *, deadline):
        from rq.command import send_shutdown_command

        try:
            remaining(deadline)
            before = self.redis.time()
            issued = before[0] + before[1] / 1_000_000
            send_shutdown_command(self.redis, name)
            end = min(deadline, time.monotonic() + 3)
            while time.monotonic() < end:
                value = self.redis.hget("rq:worker:" + name, "dc2_warm_ack")
                if value and float(value) >= issued:
                    return True
                time.sleep(min(0.05, remaining(end)))
            return False
        except Exception:
            raise OperationError("Local warm request was not positively acknowledged") from None

    def quiescence(self, config, writers, *, deadline, now=time.time):
        if set(writers) != WRITERS or any(v is not True for v in writers.values()):
            raise OperationError("Observed stopped writer identities required")
        rows = self.query(
            "processing",
            "SELECT count(*) AS n FROM attempts WHERE state='processing'",
            deadline=deadline,
        )
        if rows[0]["n"]:
            raise OperationError("Active attempts prevent a common export")
        issued = now()
        return {
            "environment_id": config.environment_id,
            "operator_station": config.operator_station,
            "boundary_id": uuid4().hex,
            "issued_at": datetime.fromtimestamp(issued, UTC).isoformat(),
            "expires_at": datetime.fromtimestamp(issued + 300, UTC).isoformat(),
            "intake_closed": True,
            "launches_closed": True,
            "workers_drained": True,
            "active_claims": 0,
            "nonterminal_tasks": 0,
            "unresolved_launches": 0,
            "writers_quiesced": dict(writers),
        }


class LocalDump:
    evidence_kind = "local-services"

    def __init__(self, data, *, roles_file, roles_dsn, pg_dump="pg_dump", psql="psql"):
        self.data, self.roles_file, self.pg_dump, self.psql = data, Path(roles_file), pg_dump, psql
        if urlsplit(roles_dsn).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise OperationError("Private role export must use explicit loopback")
        self._roles_dsn = roles_dsn

    def _run(self, argv, dsn, *, deadline, max_bytes):
        uri = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://"))
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PGHOST": uri.hostname,
            "PGPORT": str(uri.port or 5432),
            "PGUSER": unquote(uri.username or ""),
            "PGPASSWORD": unquote(uri.password or ""),
            "PGCONNECT_TIMEOUT": "2",
        }
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(argv, env=env, stdout=out, stderr=err)
            try:
                while process.poll() is None:
                    if out.tell() > max_bytes or err.tell() > 1024 * 1024:
                        raise OperationError("Private dump byte allowance exceeded")
                    remaining(deadline)
                    time.sleep(min(0.02, remaining(deadline)))
                if process.returncode or out.tell() > max_bytes:
                    raise OperationError("Private dump failed or exceeded allowance")
                out.seek(0)
                return out.read(max_bytes + 1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)

    def dump(self, owner, *, deadline, max_bytes):
        deadline = time.monotonic() + remaining_epoch(deadline)
        if owner == "roles":
            return self._run(
                [
                    self.psql,
                    "-X",
                    "--tuples-only",
                    "--no-align",
                    "--dbname",
                    "postgres",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--file",
                    str(self.roles_file),
                ],
                self._roles_dsn,
                deadline=deadline,
                max_bytes=max_bytes,
            )
        return self._run(
            [self.pg_dump, "--format", "custom", "--dbname", owner + "_db"],
            self.data._dsns[owner],
            deadline=deadline,
            max_bytes=max_bytes,
        )

    def revision(self, owner, *, deadline):
        return self.data.schema_revision(
            owner, deadline=time.monotonic() + remaining_epoch(deadline)
        )


def remaining_epoch(deadline):
    seconds = deadline - time.time()
    if seconds <= 0 or seconds > 300:
        raise OperationError("A bounded export wall-clock deadline is required")
    return seconds


class PrivateFiles:
    evidence_kind = "local-services"

    def __init__(self, root, *, prefix):
        self.root, self.prefix = Path(root).resolve(), prefix
        if any((p / ".git").exists() for p in (self.root, *self.root.parents)):
            raise OperationError("Private export storage must be outside any checkout")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise OperationError("Private storage permissions must be0700")

    def _path(self, key):
        path = (self.root / key).resolve()
        if not key.startswith(self.prefix) or not path.is_relative_to(self.root):
            raise OperationError("Private export key escaped its approved prefix")
        return path

    def put(self, key, data, *, deadline):
        remaining_epoch(deadline)
        path = self._path(key)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()

    def list_sets(self, prefix, *, deadline):
        remaining_epoch(deadline)
        return [json.loads(p.read_text()) for p in self._path(prefix).glob("*/manifest.json")]

    def delete_set(self, prefix, *, deadline):
        import shutil

        remaining_epoch(deadline)
        path = self._path(prefix)
        if path.parent != self._path(self.prefix) or not (path / "manifest.json").is_file():
            raise OperationError("Only committed private export sets may be retained/deleted")
        shutil.rmtree(path)
        return not path.exists()
