import ssl
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from processing import database
from processing.config import Settings


def settings(**kwargs):
    return Settings(postgres_dsn="postgresql://runtime@unused/processing_db", **kwargs)


def test_database_tls_verifies_chain_and_hostname_by_default():
    args = database.v1_connect_args(settings())
    assert isinstance(args["ssl"], ssl.SSLContext)
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert args["ssl"].check_hostname is True
    assert args["timeout"] == 10


def test_invalid_ca_never_downgrades_tls():
    with pytest.raises(FileNotFoundError):
        database.v1_connect_args(settings(database_ca_file="/missing/rds-ca.pem"))


def test_explicit_local_tls_opt_out():
    assert database.v1_connect_args(settings(database_tls=False))["ssl"] is False


@pytest.mark.parametrize("query", ["ssl=false", "sslmode=disable", "sslrootcert=untrusted"])
def test_dsn_cannot_override_owned_tls_settings(query):
    value = Settings(postgres_dsn="postgresql://runtime@unused/processing_db?" + query)
    with pytest.raises(ValueError, match="owned settings"):
        database.v1_connect_args(value)


@pytest.mark.parametrize("failure", [False, True])
async def test_invocation_owns_nullpool_closes_session_and_disposes_engine(monkeypatch, failure):
    engine = AsyncMock()
    create = Mock(return_value=engine)
    monkeypatch.setattr(database, "create_async_engine", create)
    context = AsyncMock()
    session = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(
        database, "async_sessionmaker", Mock(return_value=Mock(return_value=context))
    )
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    assert await anext(iterator) is session
    if failure:
        with pytest.raises(RuntimeError):
            await iterator.athrow(RuntimeError("request failed"))
    else:
        await iterator.aclose()
    assert create.call_args.kwargs["poolclass"] is NullPool
    assert create.call_args.kwargs["connect_args"]["ssl"] is False
    context.__aexit__.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_session_creation_failure_still_disposes(monkeypatch):
    engine = AsyncMock()
    monkeypatch.setattr(database, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(database, "async_sessionmaker", Mock(side_effect=ValueError("bad factory")))
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    with pytest.raises(ValueError):
        await anext(iterator)
    engine.dispose.assert_awaited_once()
