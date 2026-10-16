"""Cross-database denial probe. Runs inside the worker image as its own runtime role.

The worker task receives only the Processing runtime DSN. This asks, from inside the VPC over
the database's verified TLS: can that role (1) reach its own database, (2) run DDL there, and
(3) reach or read the Media database? The answer for (2) and (3) must be a denial. The probe
reports exception class names only; a driver message can echo the DSN, so none is printed.
"""

import asyncio
import json
import os
import re

MARKER = "DC2-RESULT"


def other_database(dsn):
    """The same role and host, pointed at the Media database."""
    return re.sub(r"/[^/?]+(\?|$)", r"/media_db\1", dsn, count=1)


async def connect(dsn):
    import asyncpg

    return await asyncpg.connect(dsn, timeout=10, command_timeout=10)


async def attempt(dsn, statement):
    """(connect outcome, statement outcome): classes of failure only, never a message."""
    try:
        connection = await connect(dsn)
    except Exception as error:
        return "connect-denied:" + type(error).__name__, None
    try:
        await connection.execute(statement)
        return "connected", "ALLOWED"
    except Exception as error:
        return "connected", "denied:" + type(error).__name__
    finally:
        await connection.close()


async def main():
    dsn = os.environ["PROCESSING_POSTGRES_DSN"]
    own, _ = await attempt(dsn, "SELECT 1")
    result = {"own_database": own}
    if own != "connected":
        print(f"{MARKER} {json.dumps(result)}", flush=True)
        return 0
    _, ddl = await attempt(dsn, "CREATE TABLE dc2_evidence_probe (x integer)")
    result["own_ddl"] = ddl
    reached, read = await attempt(other_database(dsn), "SELECT count(*) FROM alembic_version")
    result["other_database"] = reached if reached != "connected" else "reached"
    result["other_database_read"] = read
    print(f"{MARKER} {json.dumps(result)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
