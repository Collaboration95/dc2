"""Operator-run PostgreSQL bootstrap; private input, verified TLS, no AWS calls.

Never accepts credentials in command arguments. Does not print SQL, passwords or DSNs.
This is deliberately separate from runtime handlers and owning schema migrations.
"""

import argparse
import asyncio
import json
import os
import ssl
from pathlib import Path

DOMAINS = ("media", "processing")
CREDENTIAL_ROLES = tuple(f"{d}_{suffix}" for d in DOMAINS for suffix in ("migrator", "runtime"))
# Aurora Serverless v2 at 0 ACU pauses after five idle minutes, and the first connection only
# starts the resume: it can time out or be refused while the instance warms. The 2026-10-17
# run lost its bootstrap to exactly that, so connecting retries for longer than a resume takes.
WAKE_DEADLINE_SECONDS = 150


async def connect_waking(connect, *, deadline=WAKE_DEADLINE_SECONDS, sleep=asyncio.sleep,
                         clock=None, **options):
    """connect(**options), retrying connection-class failures until the deadline."""
    clock = clock or asyncio.get_running_loop().time
    give_up = clock() + deadline
    delay = 2.0
    while True:
        try:
            return await connect(**options)
        except (OSError, TimeoutError) as error:
            retry = error
        except Exception as error:  # asyncpg's "starting up" refusal has no stable base class
            if type(error).__name__ not in {"CannotConnectNowError", "ConnectionDoesNotExistError"}:
                raise
            retry = error
        if clock() + delay > give_up:
            raise retry
        await sleep(delay)
        delay = min(delay * 2, 15.0)


CONNECTION_FIELDS = ("host", "port", "user", "password")


def _check_connection(source):
    if not isinstance(source["host"], str) or not source["host"] or "://" in source["host"]:
        raise ValueError("Bootstrap requires an explicit DB hostname")
    if type(source["port"]) is not int or not 1 <= source["port"] <= 65535:
        raise ValueError("Bootstrap requires a valid DB port")
    if not all(isinstance(source[k], str) and source[k] for k in ("user", "password")):
        raise ValueError("Explicit bootstrap identity is required")


def targets(data):
    """{domain: connection fields}. One cluster serves both domains, or each has its own.

    The single-cluster input (`host`, `port`, `user`, `password` at the top level) is V1's and
    stays valid. The separate-cluster layout (#94) names each domain's connection under
    `databases`, so the bootstrap never has to guess which cluster holds which database.
    """
    if "databases" in data:
        return {domain: dict(data["databases"][domain]) for domain in DOMAINS}
    return {domain: {k: data[k] for k in CONNECTION_FIELDS} for domain in DOMAINS}


def validate_input(data):
    """Private bootstrap input is never passed through the nonsecret renderer."""
    if isinstance(data, dict) and "databases" in data:
        if data.keys() != {"databases", "role_passwords"}:
            raise ValueError("Private bootstrap input has unsupported fields")
        databases = data["databases"]
        if not isinstance(databases, dict) or set(databases) != set(DOMAINS):
            raise ValueError("Per-domain bootstrap input names the media and processing DBs")
        for entry in databases.values():
            if not isinstance(entry, dict) or entry.keys() != set(CONNECTION_FIELDS):
                raise ValueError("Private bootstrap input has unsupported fields")
            _check_connection(entry)
    else:
        required = {*CONNECTION_FIELDS, "role_passwords"}
        if not isinstance(data, dict) or data.keys() != required:
            raise ValueError("Private bootstrap input has unsupported fields")
        _check_connection(data)
    passwords = data["role_passwords"]
    if not isinstance(passwords, dict) or set(passwords) != set(CREDENTIAL_ROLES):
        raise ValueError("Private bootstrap requires exactly four role credentials")
    if not all(isinstance(v, str) and len(v) >= 24 for v in passwords.values()):
        raise ValueError("Role credentials must contain at least 24 characters")
    if len(set(passwords.values())) != 4:
        raise ValueError("Each database identity requires a distinct password")
    return data


async def bootstrap(data, ca_file, *, connect=None):
    """Create two DBs, no-login owners, restricted migrators/runtimes; close all conns.

    Reruns reconcile grants and reset ONLY the four project role passwords to the
    supplied private values. This is a privileged explicit bootstrap operation.
    The AWS-managed master credential is never granted to a service or saved here.

    Domains that share a connection (V1's one cluster) are reconciled together, exactly as
    before. With one cluster per domain (#94) each cluster is reconciled for its own domain
    only: it never gains the peer's roles, so there is nothing of the peer's to revoke.
    """
    validate_input(data)
    tls = ssl.create_default_context(cafile=str(ca_file))
    if connect is None:
        import asyncpg

        connect = asyncpg.connect
    groups = {}
    for domain, fields in targets(data).items():
        groups.setdefault(tuple(fields[k] for k in CONNECTION_FIELDS), []).append(domain)
    for key, domains in groups.items():
        options = dict(zip(CONNECTION_FIELDS, key, strict=True))
        options |= {"ssl": tls, "timeout": 15, "command_timeout": 30}
        await reconcile(connect, options, domains, data["role_passwords"])


async def reconcile(connect, options, domains, role_passwords):
    """One cluster: the databases and identities of `domains`, nothing else."""
    admin = await connect_waking(connect, **options, database="postgres")
    try:
        # Refuse unrelated databases before changing any role/password.
        for domain in domains:
            current = await admin.fetchval(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=$1",
                f"{domain}_db",
            )
            if current is not None and current != f"{domain}_owner":
                raise ValueError("Existing project DB has an unexpected owner; refusing adoption")
        for domain in domains:
            owner, migrator, runtime = (f"{domain}_{s}" for s in ("owner", "migrator", "runtime"))
            for role in (owner, migrator, runtime):
                exists = await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role)
                if not exists:
                    await admin.execute(f"CREATE ROLE {role} NOLOGIN")
                # Aurora's master is rds_superuser, not SUPERUSER, and PostgreSQL refuses it any
                # ALTER that names SUPERUSER, REPLICATION or BYPASSRLS, even to the current value
                # (the 2026-10-17 run failed here). New roles never have them, so verify instead
                # and refuse to adopt an existing role that does.
                elevated = await admin.fetchval(
                    "SELECT rolsuper OR rolreplication OR rolbypassrls FROM pg_roles "
                    "WHERE rolname=$1",
                    role,
                )
                if elevated:
                    raise ValueError("Existing project role is elevated; refusing adoption")
                await admin.execute(f"ALTER ROLE {role} NOCREATEDB NOCREATEROLE")
            await admin.execute(f"ALTER ROLE {owner} NOLOGIN NOINHERIT")
            for role in (migrator, runtime):
                # Role identifiers are fixed constants; PostgreSQL quotes secrets.
                # No private values are interpolated into error or receipt output.
                quoted = await admin.fetchval(
                    "SELECT quote_literal($1::text)", role_passwords[role]
                )
                await admin.execute(f"ALTER ROLE {role} LOGIN INHERIT PASSWORD {quoted}")
            await admin.execute(f"GRANT {owner} TO {migrator}")
            # PostgreSQL16 CREATEROLE is not SUPERUSER: explicitly allow the
            # bootstrap identity to SET owner and change migration defaults.
            await admin.execute(f"GRANT {owner}, {migrator} TO CURRENT_USER")
            # PUBLIC defaults never grant access to the peer database.
            database = f"{domain}_db"
            exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", database)
            if not exists:
                await admin.execute(f"CREATE DATABASE {database} OWNER {owner}")
            actual_owner = await admin.fetchval(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=$1", database
            )
            if actual_owner != owner:
                raise ValueError("Existing project DB has an unexpected owner; refusing adoption")
            await admin.execute(f"REVOKE ALL ON DATABASE {database} FROM PUBLIC")
            await admin.execute(f"GRANT CONNECT ON DATABASE {database} TO {migrator}, {runtime}")
        # Every database of this cluster now exists; remove accidental owner memberships and
        # grants between the domains that share it.
        for domain in domains:
            peers = [d for d in domains if d != domain]
            if peers:
                denied = ", ".join(f"{p}_{s}" for p in peers for s in ("runtime", "migrator"))
                await admin.execute(f"REVOKE ALL ON DATABASE {domain}_db FROM {denied}")
            held = ", ".join([f"{domain}_runtime", *(f"{p}_runtime" for p in peers),
                              *(f"{p}_migrator" for p in peers)])
            await admin.execute(f"REVOKE {domain}_owner FROM {held}")
    finally:
        await asyncio.wait_for(admin.close(), timeout=5)
    for domain in domains:
        owner, migrator, runtime = (f"{domain}_{s}" for s in ("owner", "migrator", "runtime"))
        connection = await connect_waking(connect, **options, database=f"{domain}_db")
        try:
            await connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            await connection.execute(f"GRANT USAGE, CREATE ON SCHEMA public TO {owner}, {migrator}")
            await connection.execute(f"GRANT USAGE ON SCHEMA public TO {runtime}")
            await connection.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {runtime}"
            )
            await connection.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {runtime}"
            )
            for creator in (owner, migrator):
                await connection.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA public "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime}"
                )
                await connection.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA public "
                    f"GRANT USAGE, SELECT ON SEQUENCES TO {runtime}"
                )
        finally:
            try:
                await connection.execute(f"REVOKE {owner}, {migrator} FROM CURRENT_USER")
            finally:
                await asyncio.wait_for(connection.close(), timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", type=Path, default=Path("/opt/rds/global-bundle.pem"))
    args = parser.parse_args()
    # ECS injects the temporary SecureString without placing its value in the
    # task definition or command. Remove it from the inherited environment.
    try:
        private_json = os.environ.pop("DC2_BOOTSTRAP_INPUT_JSON", None)
        if private_json is not None:
            if "DC2_BOOTSTRAP_INPUT_FILE" in os.environ:
                raise ValueError("Choose one explicit private bootstrap input")
            data = json.loads(private_json)
        else:
            path = Path(os.environ["DC2_BOOTSTRAP_INPUT_FILE"])
            if path.stat().st_mode & 0o077:
                raise ValueError("Bootstrap input file must be private")
            data = json.loads(path.read_text())
        asyncio.run(asyncio.wait_for(bootstrap(data, args.ca_file), timeout=330))
    except Exception as error:
        # The class name carries no SQL, host or secret, and separates "Aurora never woke"
        # (TimeoutError) from a rejected credential or grant without exposing either.
        parser.exit(
            1,
            f"DB bootstrap failed ({type(error).__name__}); inspect private operator "
            "diagnostics, not public SQL logs\n",
        )
    print("Created/reconciled two owned DBs and restricted runtime/migration identities")


if __name__ == "__main__":
    main()
