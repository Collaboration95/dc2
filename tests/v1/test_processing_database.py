import ssl
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from processing import database
from processing.config import Settings


def settings(**kwargs):
    kwargs.setdefault("postgres_dsn", "postgresql://runtime@unused/processing_db")
    return Settings(**kwargs)


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


def build_session_mocks(monkeypatch):
    engine = AsyncMock()
    create = Mock(return_value=engine)
    monkeypatch.setattr(database, "create_async_engine", create)
    context = AsyncMock()
    session = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(
        database, "async_sessionmaker", Mock(return_value=Mock(return_value=context))
    )
    return engine, create, context, session


@pytest.mark.parametrize("failure", [False, True])
async def test_request_closes_its_session_but_keeps_the_warm_pooled_engine(monkeypatch, failure):
    engine, create, context, session = build_session_mocks(monkeypatch)
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    assert await anext(iterator) is session
    if failure:
        with pytest.raises(RuntimeError):
            await iterator.athrow(RuntimeError("request failed"))
    else:
        await iterator.aclose()
    options = create.call_args.kwargs
    assert "poolclass" not in options  # the default QueuePool, not NullPool
    assert (options["pool_size"], options["max_overflow"]) == (1, 0)
    assert options["pool_pre_ping"] is True
    assert 0 < options["pool_recycle"] < 300
    assert options["connect_args"]["ssl"] is False
    context.__aexit__.assert_awaited_once()
    engine.dispose.assert_not_awaited()


async def test_two_requests_in_one_environment_share_one_engine(monkeypatch):
    _engine, create, _context, _session = build_session_mocks(monkeypatch)
    for _ in range(2):
        iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
        await anext(iterator)
        await iterator.aclose()
    assert create.call_count == 1


async def test_a_changed_dsn_gets_a_new_engine_and_retires_the_old_one(monkeypatch):
    engine, create, _context, _session = build_session_mocks(monkeypatch)
    for password in ("old", "rotated"):
        dsn = f"postgresql://runtime:{password}@unused/processing_db"
        iterator = database.get_v1_session(
            Request({"type": "http"}), settings(postgres_dsn=dsn, database_tls=False)
        )
        await anext(iterator)
        await iterator.aclose()
    assert create.call_count == 2
    engine.dispose.assert_awaited_once()


async def test_a_dead_connection_retires_the_engine_so_the_next_request_reconnects(monkeypatch):
    engine, create, _context, _session = build_session_mocks(monkeypatch)
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    await anext(iterator)
    with pytest.raises(OSError):
        await iterator.athrow(OSError("connection reset"))
    engine.dispose.assert_awaited_once()
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    await anext(iterator)
    assert create.call_count == 2


async def test_session_creation_failure_keeps_the_engine(monkeypatch):
    engine = AsyncMock()
    monkeypatch.setattr(database, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(database, "async_sessionmaker", Mock(side_effect=ValueError("bad factory")))
    iterator = database.get_v1_session(Request({"type": "http"}), settings(database_tls=False))
    with pytest.raises(ValueError):
        await anext(iterator)
    engine.dispose.assert_not_awaited()
