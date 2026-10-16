"""A warm Lambda that cached a DSN must recover after the secret is rotated.

Settings are cached per execution environment (lru_cache), so the SSM-held DSN is read once.
Decision: a database login refusal discards that cache; the failing invocation still fails
and the next one re-reads SSM. Anything else (network, SQL errors) leaves the cache alone.
"""

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from media import database as media_database
from media.config import get_settings as media_settings
from processing import database as processing_database
from processing.config import Settings as ProcessingSettings
from processing.config import get_settings as processing_settings
from runtime_support.settings import credentials_rejected


def refusal(code="28P01"):
    return DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate=code))


@pytest.mark.parametrize(
    "error,expected",
    [
        (refusal("28P01"), True),
        (refusal("28000"), True),
        (refusal("42P01"), False),
        (refusal("57P03"), False),
        (OperationalError("SELECT 1", {}, OSError("connection refused")), False),
        (OSError("timeout"), False),
        (ValueError("28P01"), False),
    ],
)
def test_only_a_login_refusal_counts_as_rejected_credentials(error, expected):
    assert credentials_rejected(error) is expected


def test_a_refusal_wrapped_as_a_cause_is_still_recognised():
    driver = RuntimeError("driver")
    driver.sqlstate = "28P01"
    outer = RuntimeError("wrapped")
    outer.__cause__ = driver
    assert credentials_rejected(outer) is True


class RotatingSecret:
    """Stands in for SSM: each read returns the password current at that moment."""

    def __init__(self):
        self.password, self.reads = "old", 0

    def __call__(self, service, **_):
        self.reads += 1
        return {"postgres_dsn": f"postgresql://{service.lower()}_runtime:{self.password}@db/x"}


@pytest.fixture
def secret(monkeypatch):
    source = RotatingSecret()
    monkeypatch.setattr("runtime_support.settings.runtime_values", source)
    for key in list(os.environ):
        if key.startswith(("MEDIA_", "PROCESSING_")):
            monkeypatch.delenv(key)
    media_settings.cache_clear()
    processing_settings.cache_clear()
    yield source
    media_settings.cache_clear()
    processing_settings.cache_clear()


def fake_engine(monkeypatch, module):
    engine = SimpleNamespace(disposed=0)

    async def dispose():
        engine.disposed += 1

    engine.dispose = dispose
    monkeypatch.setattr(module, "create_async_engine", lambda *a, **k: engine)
    return engine


class Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


async def test_media_session_discards_cached_dsn_when_the_database_refuses_it(
    secret, monkeypatch
):
    engine = fake_engine(monkeypatch, media_database)
    monkeypatch.setattr(media_database, "engine_options", lambda *a, **k: {})
    monkeypatch.setattr(media_database, "async_sessionmaker", lambda *a, **k: Session)
    first = media_settings()
    assert media_settings() is first and secret.reads == 1  # warm: cached

    secret.password = "rotated"
    with pytest.raises(DBAPIError):
        async with media_database.invocation_session(first):
            raise refusal()
    assert engine.disposed == 1  # the connection is still released

    refreshed = media_settings()
    assert secret.reads == 2
    assert ":rotated@" in refreshed.postgres_dsn and ":old@" in first.postgres_dsn


async def test_media_session_keeps_the_cache_for_unrelated_failures(secret, monkeypatch):
    fake_engine(monkeypatch, media_database)
    monkeypatch.setattr(media_database, "engine_options", lambda *a, **k: {})
    monkeypatch.setattr(media_database, "async_sessionmaker", lambda *a, **k: Session)
    first = media_settings()
    for error in (refusal("42P01"), OSError("network down")):
        with pytest.raises(type(error)):
            async with media_database.invocation_session(first):
                raise error
    assert media_settings() is first and secret.reads == 1


async def test_processing_session_discards_cached_dsn_when_the_database_refuses_it(
    secret, monkeypatch
):
    engine = fake_engine(monkeypatch, processing_database)
    monkeypatch.setattr(processing_database, "async_sessionmaker", lambda *a, **k: Session)
    settings = ProcessingSettings(
        postgres_dsn="postgresql://p:old@db/x", database_tls=False
    )
    first = processing_settings()
    secret.password = "rotated"

    generator = processing_database.get_v1_session(SimpleNamespace(), settings)
    await generator.__anext__()
    with pytest.raises(DBAPIError):
        await generator.athrow(refusal())
    assert engine.disposed == 1

    assert ":rotated@" in processing_settings().postgres_dsn
    assert ":old@" in first.postgres_dsn


async def test_readiness_report_also_drops_a_refused_dsn_without_leaking_it(
    secret, monkeypatch
):
    @asynccontextmanager
    async def refused(_settings):
        raise refusal()
        yield

    monkeypatch.setattr(media_database, "invocation_session", refused)
    first = media_settings()
    secret.password = "rotated"
    result = await media_database.database_ready(first)
    assert result == {"service": "media", "ready": False, "error": "database unavailable"}
    assert ":rotated@" in media_settings().postgres_dsn


async def test_a_real_wrong_password_is_recognised_as_a_login_refusal():
    dsn = os.environ.get("V1_TEST_MEDIA_DSN")
    if not dsn:
        pytest.skip("V1_TEST_MEDIA_DSN (real Media PostgreSQL) not provided")
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = make_url(dsn).set(password="definitely-not-the-password")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        with pytest.raises(Exception) as caught:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    assert credentials_rejected(caught.value)

