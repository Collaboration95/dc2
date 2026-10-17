"""A warm Lambda environment reuses one pooled SQL connection and one event loop (#66).

Live evidence (r1017b): opening a fresh TLS + SCRAM connection per invocation, twice per
request, left Aurora at its capacity ceiling and the status p90 at 1.8 s against 0.7 s.
asyncpg connections belong to the loop that made them, so reuse is only valid if every
invocation runs on the same loop.
"""

import asyncio
import ssl
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from media import authorizer
from media import database as media_database
from media.config import Settings, get_settings
from runtime_support import lambda_db


def media_settings(password="pw", **kwargs):
    kwargs.setdefault("postgres_ssl_ca", "/opt/rds/global-bundle.pem")
    return Settings(
        runtime_mode="lambda",
        postgres_dsn=f"postgresql+asyncpg://media_runtime:{password}@db.example/media",
        **kwargs,
    )


@pytest.fixture
def tls(monkeypatch):
    """Record TLS construction without needing the RDS bundle on this machine."""
    calls, real = [], ssl.create_default_context

    def create(*args, **kwargs):
        calls.append(kwargs)
        return real()

    monkeypatch.setattr(ssl, "create_default_context", create)
    return calls


@pytest.fixture
def engines(monkeypatch):
    made = []

    def build(*args, **kwargs):
        engine = SimpleNamespace(dispose=AsyncMock(), args=args, kwargs=kwargs)
        made.append(engine)
        return engine

    monkeypatch.setattr(media_database, "create_async_engine", build)
    monkeypatch.setattr(
        media_database,
        "async_sessionmaker",
        lambda *a, **k: lambda: AsyncMock(),
    )
    return made


async def use_session(settings, error=None):
    async with media_database.invocation_session(settings):
        if error is not None:
            raise error


async def test_two_invocations_in_one_environment_reuse_one_engine(engines, tls):
    settings = media_settings()
    await use_session(settings)
    await use_session(settings)
    assert len(engines) == 1
    engines[0].dispose.assert_not_awaited()


async def test_a_rotated_dsn_gets_a_new_engine_and_retires_the_old_one(engines, tls):
    await use_session(media_settings("old"))
    await use_session(media_settings("rotated"))
    assert len(engines) == 2
    engines[0].dispose.assert_awaited_once()
    engines[1].dispose.assert_not_awaited()


async def test_a_credentials_refusal_disposes_the_engine_and_clears_settings(
    engines, tls, monkeypatch
):
    cleared = Mock()
    monkeypatch.setattr(get_settings, "cache_clear", cleared)
    settings = media_settings()
    refusal = DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate="28P01"))
    with pytest.raises(DBAPIError):
        await use_session(settings, refusal)
    cleared.assert_called_once()
    engines[0].dispose.assert_awaited_once()
    await use_session(settings)
    assert len(engines) == 2  # the next invocation reconnects


async def test_a_dropped_connection_does_not_poison_the_environment(engines, tls):
    settings = media_settings()
    with pytest.raises(OSError):
        await use_session(settings, OSError("connection reset by peer"))
    engines[0].dispose.assert_awaited_once()
    await use_session(settings)
    assert len(engines) == 2


async def test_an_ordinary_query_error_keeps_the_warm_engine(engines, tls):
    settings = media_settings()
    with pytest.raises(ValueError):
        await use_session(settings, ValueError("bad input"))
    await use_session(settings)
    assert len(engines) == 1


def test_lambda_engine_keeps_certificate_verification_and_a_connect_timeout(tls):
    options = media_database.engine_options(media_settings(), invocation=True)
    assert tls == [{"cafile": "/opt/rds/global-bundle.pem"}]
    assert options["connect_args"]["timeout"] == 10
    assert options["connect_args"]["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert options["connect_args"]["ssl"].check_hostname is True


def test_lambda_engine_refuses_to_start_without_a_trusted_ca():
    with pytest.raises(ValueError, match="CA"):
        media_database.engine_options(media_settings(postgres_ssl_ca=None), invocation=True)


def test_lambda_engine_is_a_single_pre_pinged_recycled_connection(tls):
    options = media_database.engine_options(media_settings(), invocation=True)
    engine = create_async_engine(media_settings().postgres_dsn, **options)
    pool = engine.pool
    assert "poolclass" not in options
    assert (pool.size(), pool._max_overflow) == (1, 0)
    assert pool._pre_ping is True
    assert 0 < pool._recycle < 300


def test_the_persistent_loop_is_reused_across_invocations():
    async def current():
        return asyncio.get_running_loop()

    first, second = lambda_db.run(current()), lambda_db.run(current())
    assert first is second
    assert not first.is_closed()


def test_a_closed_loop_is_replaced_not_reused():
    async def current():
        return asyncio.get_running_loop()

    first = lambda_db.run(current())
    first.close()
    assert lambda_db.run(current()) is not first


def test_the_authorizer_runs_on_the_persistent_loop(monkeypatch):
    seen = []

    async def authorize(event):
        seen.append(asyncio.get_running_loop())
        return {"isAuthorized": False}

    monkeypatch.setattr(authorizer, "authorize", authorize)
    authorizer.handler({})
    authorizer.handler({})
    assert seen[0] is seen[1]


def test_an_engine_built_on_another_loop_is_replaced_without_awaiting_it():
    engine = SimpleNamespace(dispose=AsyncMock(), sync_engine=Mock())
    lambda_db._engines["svc"] = ("dsn", asyncio.new_event_loop(), engine)
    built = object()

    async def fetch():
        return await lambda_db.shared_engine("svc", "dsn", lambda: built)

    assert asyncio.run(fetch()) is built
    engine.dispose.assert_not_awaited()
    engine.sync_engine.dispose.assert_called_once_with(close=False)
