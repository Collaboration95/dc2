"""Pure fake-connection checks; never presented as real PostgreSQL/IAM evidence."""

import ssl

import pytest

from scripts.aws.v1.bootstrap import bootstrap, validate_input


@pytest.fixture
def private_input():
    return {
        "host": "database.example.invalid",
        "port": 5432,
        "user": "dc2bootstrap",
        "password": "not-an-aws-key",
        "role_passwords": {
            f"{domain}_{role}": (domain + role) * 4
            for domain in ("media", "processing")
            for role in ("migrator", "runtime")
        },
    }


class FakeConnection:
    def __init__(self, database, state, *, fail=False):
        self.database = database
        self.state = state
        self.sql = []
        self.closed = False
        self.fail = fail

    async def fetchval(self, statement, value):
        if "rolsuper" in statement:
            return value in self.state.get("elevated", set())
        if "pg_roles" in statement:
            return value in self.state["roles"]
        if "pg_get_userbyid" in statement:
            return self.state["databases"].get(value)
        if "pg_database" in statement:
            return value in self.state["databases"]
        assert "quote_literal" in statement
        return "'" + value.replace("'", "''") + "'"

    async def execute(self, statement):
        if self.fail:
            raise RuntimeError("fake failure")
        # Like Aurora's rds_superuser master: these attributes are superuser-only to name.
        if statement.startswith("ALTER ROLE") and any(
            word in statement for word in ("SUPERUSER", "REPLICATION", "BYPASSRLS")
        ):
            raise PermissionError("Only roles with the SUPERUSER attribute may change it")
        self.sql.append(statement)
        fields = statement.split()
        if fields[:2] == ["CREATE", "ROLE"]:
            self.state["roles"].add(fields[2])
        if fields[:2] == ["CREATE", "DATABASE"]:
            self.state["databases"][fields[2]] = fields[4]

    async def close(self):
        self.closed = True


async def run(private_input, *, existing=None, fail_database=None, elevated=()):
    state = {"roles": set(elevated), "databases": dict(existing or {}),
             "elevated": set(elevated)}
    connections, options = [], []

    async def connect(**kwargs):
        options.append(kwargs)
        connection = FakeConnection(
            kwargs["database"], state, fail=kwargs["database"] == fail_database
        )
        connections.append(connection)
        return connection

    # Use the machine's standard CA for a real verified SSLContext, with no DB call.
    ca_file = ssl.get_default_verify_paths().cafile
    await bootstrap(private_input, ca_file, connect=connect)
    return connections, options, state, connect


@pytest.mark.asyncio
async def test_two_owned_databases_separate_logins_and_restricted_grants(private_input):
    connections, options, state, connect = await run(private_input)
    assert state["databases"] == {"media_db": "media_owner", "processing_db": "processing_owner"}
    assert len(state["roles"]) == 6
    assert all(c.closed for c in connections)
    assert [o["database"] for o in options] == ["postgres", "media_db", "processing_db"]
    assert all(
        o["ssl"].check_hostname and o["ssl"].verify_mode == ssl.CERT_REQUIRED for o in options
    )
    for connection in connections[1:]:
        domain = connection.database.removesuffix("_db")
        sql = "\n".join(connection.sql)
        assert "REVOKE ALL ON SCHEMA public FROM PUBLIC" in sql
        assert f"GRANT USAGE ON SCHEMA public TO {domain}_runtime" in sql
        assert f"GRANT USAGE, CREATE ON SCHEMA public TO {domain}_owner, {domain}_migrator" in sql
        assert f"ALTER DEFAULT PRIVILEGES FOR ROLE {domain}_migrator" in sql
        assert f"ALTER DEFAULT PRIVILEGES FOR ROLE {domain}_owner" in sql
        assert f"REVOKE {domain}_owner, {domain}_migrator FROM CURRENT_USER" in sql
        assert f"GRANT USAGE, CREATE ON SCHEMA public TO {domain}_runtime" not in sql
    admin_sql = "\n".join(connections[0].sql)
    assert (
        "REVOKE ALL ON DATABASE media_db FROM processing_runtime, processing_migrator" in admin_sql
    )
    assert "REVOKE ALL ON DATABASE processing_db FROM media_runtime, media_migrator" in admin_sql
    assert (
        "REVOKE media_owner FROM media_runtime, processing_runtime, processing_migrator"
        in admin_sql
    )
    # A second bootstrap reconciles, never duplicates role/database creation.
    before = len(connections)
    await bootstrap(private_input, ssl.get_default_verify_paths().cafile, connect=connect)
    assert not any(sql.startswith("CREATE ") for c in connections[before:] for sql in c.sql)
    assert all(c.closed for c in connections)


@pytest.mark.asyncio
async def test_wrong_existing_owner_is_not_adopted(private_input):
    with pytest.raises(ValueError, match="unexpected owner"):
        await run(private_input, existing={"media_db": "someone_else"})


@pytest.mark.parametrize(
    "change", ["shared_password", "missing_role", "short_password", "url_host", "extra_key"]
)
def test_private_input_validation(private_input, change):
    if change == "shared_password":
        private_input["role_passwords"]["media_runtime"] = private_input["role_passwords"][
            "processing_runtime"
        ]
    elif change == "missing_role":
        private_input["role_passwords"].pop("media_runtime")
    elif change == "short_password":
        private_input["role_passwords"]["media_runtime"] = "short"
    elif change == "url_host":
        private_input["host"] = "postgres://credentials@example.invalid"
    else:
        private_input["other"] = True
    with pytest.raises(ValueError):
        validate_input(private_input)


def test_cli_never_echoes_private_parse_errors(monkeypatch, capsys):
    from scripts.aws.v1.bootstrap import main

    monkeypatch.setenv("DC2_BOOTSTRAP_INPUT_JSON", "private-value-that-is-not-json")
    monkeypatch.setattr("sys.argv", ["bootstrap"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "private-value-that-is-not-json" not in captured.out + captured.err
    assert "DB bootstrap failed" in captured.err
    import os

    assert "DC2_BOOTSTRAP_INPUT_JSON" not in os.environ


class CannotConnectNowError(Exception):
    """Stands in for asyncpg's refusal while Aurora is still resuming."""


class WakingDatabase:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    async def connect(self, **options):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return options["database"]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


async def test_a_paused_aurora_is_given_time_to_resume_before_bootstrap_gives_up():
    from scripts.aws.v1.bootstrap import connect_waking

    database = WakingDatabase([TimeoutError(), CannotConnectNowError(), OSError()])
    clock = FakeClock()
    result = await connect_waking(
        database.connect, sleep=clock.sleep, clock=clock, database="postgres")
    assert result == "postgres"
    assert database.calls == 4


async def test_a_database_that_never_wakes_still_fails_within_the_deadline():
    from scripts.aws.v1.bootstrap import connect_waking

    database = WakingDatabase([TimeoutError()] * 100)
    clock = FakeClock()
    with pytest.raises(TimeoutError):
        await connect_waking(
            database.connect, deadline=150, sleep=clock.sleep, clock=clock, database="postgres")
    assert clock.now <= 150


async def test_a_rejected_credential_is_not_retried():
    from scripts.aws.v1.bootstrap import connect_waking

    class InvalidPasswordError(Exception):
        pass

    database = WakingDatabase([InvalidPasswordError()])
    clock = FakeClock()
    with pytest.raises(InvalidPasswordError):
        await connect_waking(database.connect, sleep=clock.sleep, clock=clock, database="x")
    assert database.calls == 1


def test_cli_failure_names_only_the_error_class(monkeypatch, capsys):
    from scripts.aws.v1.bootstrap import main

    monkeypatch.setenv("DC2_BOOTSTRAP_INPUT_JSON", "private-value-that-is-not-json")
    monkeypatch.setattr("sys.argv", ["bootstrap"])
    with pytest.raises(SystemExit):
        main()
    assert "(JSONDecodeError)" in capsys.readouterr().err


async def test_an_existing_elevated_role_is_refused_rather_than_altered(private_input):
    with pytest.raises(ValueError, match="elevated"):
        await run(private_input, elevated={"media_runtime"})
