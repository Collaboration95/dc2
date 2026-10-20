"""Read-only database probe that runs inside an owner's migration task (V1, #150).

Aurora is private and V1 has no bastion, so the operator's machine cannot read an owner's
Alembic revision or attempt counts. `vpc_reader` ships this file as a `python -c` command
override to the owner's own migration task definition: that task already has the owner's
migration role (injected from its secret reference), the RDS CA bundle and the VPC route.

Hygiene, because the result is read back from CloudWatch Logs:
  * the DSN is read from the environment and is never printed;
  * failures print an exception class name only, since a driver message can echo the DSN;
  * the one result line is tagged and carries a revision or counts, plus TLS facts.

TLS is verified here, not assumed: the connection uses a context that requires a certificate
chain to the RDS CA and a matching hostname, and the server is then asked whether the session
is encrypted. Standard library plus asyncpg, which every owning image already carries.
"""

import asyncio
import json
import os
import re
import ssl
import time

MARKER = "DC2-VPC-READ"
STATES = ("queued", "processing", "succeeded", "failed", "abandoned", "cancelled")
REVISION = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# One session's attempt states (the same read-only statement the SQL station uses).
COUNT_SQL = "SELECT state, count(*) FROM attempts GROUP BY state"
RETRY_SECONDS = 5


def emit(result):
    print(f"{MARKER} {json.dumps(result)}", flush=True)


def asyncpg_dsn(owner):
    raw = (
        os.environ.get(f"{owner.upper()}_MIGRATION_DSN")
        or os.environ[f"{owner.upper()}_POSTGRES_DSN"]
    )
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


async def connect(dsn, context, window):
    """Connect, retrying while a paused Aurora cluster resumes (it can take ~30-120 s).

    A certificate or credential failure is permanent, so it is never retried.
    """
    import asyncpg

    permanent = (
        ssl.SSLError,
        asyncpg.InvalidPasswordError,
        asyncpg.InvalidAuthorizationSpecificationError,
    )
    end = time.monotonic() + window
    attempts = 0
    while True:
        attempts += 1
        try:
            return await asyncpg.connect(dsn, ssl=context, timeout=10, command_timeout=10), attempts
        except permanent:
            raise
        except Exception:
            if time.monotonic() + RETRY_SECONDS >= end:
                raise
            await asyncio.sleep(RETRY_SECONDS)


async def tls_facts(connection, context):
    """What the client enforced and what the server reports for this very session."""
    row = await connection.fetchrow(
        "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
    )
    enforced = context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    server_ssl = bool(row and row["ssl"])
    return {
        "verified": bool(enforced and server_ssl),
        "server_reports_ssl": server_ssl,
        "protocol": (row["version"] if row else None),
    }


async def read(owner, mode):
    window = max(0, min(int(os.environ.get("DC2_RESUME_SECONDS", "150")), 300))
    context = ssl.create_default_context(cafile=os.environ["DB_SSL_CA_FILE"])
    started = time.monotonic()
    connection, attempts = await connect(asyncpg_dsn(owner), context, window)
    try:
        result = {
            "ok": True,
            "mode": mode,
            "owner": owner,
            "connect_attempts": attempts,
            "connect_seconds": round(time.monotonic() - started, 1),
            "tls": await tls_facts(connection, context),
        }
        if mode == "schema":
            rows = await connection.fetch("SELECT version_num FROM alembic_version")
            result["heads"] = len(rows)
            revision = rows[0][0] if len(rows) == 1 else None
            result["revision"] = revision if REVISION.fullmatch(str(revision)) else None
        else:
            counts = {row[0]: int(row[1]) for row in await connection.fetch(COUNT_SQL)}
            result["counts"] = counts
            result["unknown_states"] = sorted(set(counts) - set(STATES))
        return result
    finally:
        await connection.close()


async def main():
    owner, mode = os.environ.get("DC2_OWNER", ""), os.environ.get("DC2_MODE", "")
    try:
        if owner not in {"media", "processing"} or mode not in {"schema", "attempts"}:
            raise ValueError
        emit(await read(owner, mode))
        return 0
    except Exception as error:  # the class name is the whole report; messages can echo a DSN
        emit({"ok": False, "owner": owner, "mode": mode, "error": type(error).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
