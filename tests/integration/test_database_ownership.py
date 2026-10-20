"""Prove database ownership using PostgreSQL grants, not mocked connections."""

import os
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PROCESSING_TESTS") != "1",
    reason="set RUN_PROCESSING_TESTS=1 with the Project 2 PostgreSQL stack running",
)


def dsn(service: str, role: str) -> str:
    suffix = "MIGRATION" if role == "migrator" else "RUNTIME"
    default_password = f"dc2_local_{service}" + ("_migrate" if role == "migrator" else "")
    password = os.getenv(f"{service.upper()}_{suffix}_PASSWORD", default_password)
    port = os.getenv("P2_POSTGRES_PORT", "55432")
    return f"postgresql://{service}_{role}:{quote(password, safe='')}@127.0.0.1:{port}/{service}_db"


@pytest.mark.parametrize("service", ["media", "processing"])
async def test_migration_owns_schema_while_runtime_can_only_use_its_data(service):
    migrator = await asyncpg.connect(dsn(service, "migrator"))
    runtime = await asyncpg.connect(dsn(service, "runtime"))
    table = f"ownership_probe_{uuid4().hex}"
    try:
        await migrator.execute(f"CREATE TABLE {table} (id integer PRIMARY KEY, value text)")
        await runtime.execute(f"INSERT INTO {table} VALUES (1, 'before')")
        await runtime.execute(f"UPDATE {table} SET value = 'after' WHERE id = 1")
        assert await runtime.fetchval(f"SELECT value FROM {table} WHERE id = 1") == "after"
        await runtime.execute(f"DELETE FROM {table} WHERE id = 1")
        assert await runtime.fetchval(f"SELECT count(*) FROM {table}") == 0
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute(f"ALTER TABLE {table} ADD COLUMN forbidden integer")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await runtime.execute(f"CREATE TABLE forbidden_{table} (id integer)")
    finally:
        await migrator.execute(f"DROP TABLE IF EXISTS {table}")
        await runtime.close()
        await migrator.close()


@pytest.mark.parametrize("service", ["media", "processing"])
@pytest.mark.parametrize("role", ["runtime", "migrator"])
async def test_service_credentials_cannot_connect_to_the_other_database(service, role):
    own_dsn = dsn(service, role)
    # Establish that the server and these credentials work before checking denial.
    own_connection = await asyncpg.connect(own_dsn)
    await own_connection.close()
    other = "processing" if service == "media" else "media"
    other_dsn = own_dsn.rsplit("/", 1)[0] + f"/{other}_db"
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await asyncpg.connect(other_dsn)
