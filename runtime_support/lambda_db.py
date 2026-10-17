"""One SQL engine and one event loop per warm Lambda execution environment.

A fresh engine per invocation made every request pay a TLS + SCRAM handshake and a
pre-ping (twice per API call: authorizer and API). A Lambda environment serves one
request at a time, so a single pooled connection is enough, but asyncpg connections are
bound to the loop that created them. `asyncio.run` builds a new loop each call, so reuse
requires `run()` below to drive every invocation on one persistent loop.
"""

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy.exc import DBAPIError, InterfaceError

from runtime_support.settings import credentials_rejected

# One connection: the environment is single-request. A second concurrent checkout would
# be a bug, so fail fast instead of queueing for the 30 s default.
POOL_OPTIONS = {"pool_size": 1, "max_overflow": 0, "pool_timeout": 10}
# Recycle before idle NAT/ENI tracking (350 s on NAT gateway) can silently drop a
# connection that sat frozen between invocations. Pre-ping still catches the rest.
POOL_RECYCLE_SECONDS = 240

_loop: asyncio.AbstractEventLoop | None = None
# scope -> (dsn, loop, engine)
_engines: dict[str, tuple[str, asyncio.AbstractEventLoop, Any]] = {}


def run(coroutine: Coroutine) -> Any:
    """Drive a coroutine on this environment's persistent loop (replaces `asyncio.run`)."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coroutine)


async def shared_engine(scope: str, dsn: str, build: Callable[[], Any]) -> Any:
    """The cached engine for `scope`, rebuilt when the DSN (a rotated secret) or loop changed."""
    loop = asyncio.get_running_loop()
    cached = _engines.get(scope)
    if cached is not None:
        cached_dsn, cached_loop, engine = cached
        if cached_dsn == dsn and cached_loop is loop:
            return engine
        _engines.pop(scope)
        await _dispose(engine, same_loop=cached_loop is loop)
    engine = build()
    _engines[scope] = (dsn, loop, engine)
    return engine


async def discard_engine(scope: str) -> None:
    cached = _engines.pop(scope, None)
    if cached is not None:
        await _dispose(cached[2], same_loop=cached[1] is asyncio.get_running_loop())


async def _dispose(engine: Any, *, same_loop: bool) -> None:
    with contextlib.suppress(Exception):
        if same_loop:
            await engine.dispose()
        else:
            # Its connections belong to a dead loop and cannot be awaited; just forget them.
            engine.sync_engine.dispose(close=False)


def connection_broken(error: BaseException) -> bool:
    """True when the pooled connection, not the query, is what failed."""
    return (
        credentials_rejected(error)
        or isinstance(error, OSError | InterfaceError)
        or (isinstance(error, DBAPIError) and error.connection_invalidated)
    )


async def release_after(scope: str, error: BaseException) -> None:
    """Do not let one bad connection or stale login poison the warm environment."""
    if connection_broken(error):
        await discard_engine(scope)


def reset() -> None:
    """Forget cached state without awaiting anything (tests only)."""
    global _loop
    _engines.clear()
    if _loop is not None and not _loop.is_closed():
        _loop.close()
    _loop = None
