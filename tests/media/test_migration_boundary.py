"""Execute Alembic's environment with fake connections and real TLS contexts."""

import runpy
import ssl
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import context
from sqlalchemy.pool import NullPool

from media.config import Settings

ENV = Path(__file__).parents[2] / "media" / "migrations" / "env.py"
RUNTIME = "postgresql+asyncpg://media_runtime@unused/media_db"
MIGRATION = "postgresql+asyncpg://media_migrator@unused/media_db"


@contextmanager
def transaction():
    yield


@pytest.fixture
def migrate_env(monkeypatch):
    from sqlalchemy.ext import asyncio as sqlalchemy_async

    from media import config

    monkeypatch.delenv("MEDIA_MIGRATION_DSN", raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(context, "configure", Mock())
    monkeypatch.setattr(context, "begin_transaction", transaction)
    monkeypatch.setattr(context, "run_migrations", Mock())
    engine = Mock()
    connection = AsyncMock()
    connection.run_sync.side_effect = lambda callback: callback("owned-connection")
    engine.connect.return_value = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = connection
    engine.dispose = AsyncMock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(sqlalchemy_async, "create_async_engine", factory)

    def run(**overrides):
        values = {"postgres_dsn": RUNTIME} | overrides
        monkeypatch.setattr(config, "get_settings", lambda: Settings(**values))
        return runpy.run_path(str(ENV))

    return run, factory, engine, connection


def test_cloud_migration_uses_owned_dsn_verified_ca_and_registers_all_models(migrate_env):
    run, factory, engine, _ = migrate_env
    result = run(
        migration_dsn=MIGRATION,
        runtime_mode="lambda",
        postgres_ssl_ca=str(Path(__file__).parents[2] / "deploy/v1/global-bundle.pem"),
    )
    assert factory.call_args.args == (MIGRATION,)
    options = factory.call_args.kwargs
    assert options["poolclass"] is NullPool
    assert options["connect_args"]["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert options["connect_args"]["ssl"].check_hostname
    engine.dispose.assert_awaited_once()
    metadata = result["Base"].metadata
    assert {
        "users",
        "assets",
        "upload_reservations",
        "asset_source_versions",
        "processing_projections",
        "message_inbox",
        "message_outbox",
    } <= set(metadata.tables)


@pytest.mark.parametrize("mode", [{"runtime_mode": "lambda"}, {"storage_credential_mode": "ecs"}])
def test_cloud_migration_refuses_runtime_credential_fallback(migrate_env, mode):
    run, factory, _, _ = migrate_env
    with pytest.raises(ValueError, match="owned migration credentials"):
        run(**mode)
    factory.assert_not_called()


@pytest.mark.parametrize("query", ["ssl=false", "sslmode=disable", "sslrootcert=untrusted"])
def test_cloud_migration_refuses_dsn_tls_overrides(migrate_env, query):
    run, factory, _, _ = migrate_env
    with pytest.raises(ValueError, match="owned settings"):
        run(runtime_mode="lambda", migration_dsn=MIGRATION + "?" + query)
    factory.assert_not_called()


def test_cloud_migration_missing_ca_fails_without_plaintext_fallback(migrate_env):
    run, factory, _, _ = migrate_env
    with pytest.raises(FileNotFoundError):
        run(runtime_mode="lambda", migration_dsn=MIGRATION, postgres_ssl_ca="/absent/rds-ca.pem")
    factory.assert_not_called()


def test_explicit_legacy_local_migration_remains_plaintext_and_nullpool(migrate_env):
    run, factory, engine, _ = migrate_env
    run(runtime_mode="http", storage_credential_mode="static")
    assert factory.call_args.args == (RUNTIME,)
    assert factory.call_args.kwargs == {"poolclass": NullPool}
    engine.dispose.assert_awaited_once()


def test_migration_only_ecs_secret_never_loads_runtime_credentials(migrate_env, monkeypatch):
    from media import config

    _, factory, engine, _ = migrate_env
    monkeypatch.setenv("MEDIA_MIGRATION_DSN", MIGRATION)
    monkeypatch.setenv("MEDIA_STORAGE_CREDENTIAL_MODE", "ecs")
    monkeypatch.setenv(
        "MEDIA_POSTGRES_SSL_CA", str(Path(__file__).parents[2] / "deploy/v1/global-bundle.pem")
    )
    monkeypatch.setattr(
        config, "get_settings", Mock(side_effect=AssertionError("runtime secret read"))
    )
    runpy.run_path(str(ENV))
    assert factory.call_args.args == (MIGRATION,)
    engine.dispose.assert_awaited_once()


def test_failed_migration_disposes_its_owned_engine(migrate_env):
    run, _, engine, connection = migrate_env
    connection.run_sync.side_effect = RuntimeError("migration failed")
    with pytest.raises(RuntimeError, match="migration failed"):
        run()
    engine.dispose.assert_awaited_once()
