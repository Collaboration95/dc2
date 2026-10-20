"""Responsive lease/deadline supervision independent of download/encode/upload."""

import asyncio
import logging
import os
import signal
import time
from contextlib import suppress

from processing.lifecycle import heartbeat

logger = logging.getLogger(__name__)


class LeaseLost(Exception):
    """Control-flow cancellation; never absorbed by best-effort media fallback."""


class AttemptDeadline(Exception):
    pass


class Supervisor:
    def __init__(self, factory, work, settings, *, renew=None, deadline=None):
        self.factory, self.work, self.settings = factory, work, settings
        self.lost = asyncio.Event()
        self.reason = LeaseLost
        self.deadline = time.monotonic() + settings.attempt_timeout_seconds
        self.task = None
        self.renew = renew
        self.renew_lock = asyncio.Lock()
        if deadline is not None:
            self.deadline = min(self.deadline, deadline)

    async def __aenter__(self):
        self.task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(self, *_):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task

    def check(self):
        if self.lost.is_set():
            raise self.reason()
        if time.monotonic() >= self.deadline:
            raise AttemptDeadline()

    async def renew_authority(self):
        async with self.renew_lock:
            self.check()
            try:
                if not await heartbeat(self.factory, self.work, self.settings):
                    raise LeaseLost()
                if self.renew is not None:
                    await self.renew()
            except Exception:
                self.lost.set()
                raise LeaseLost() from None
            self.check()
        return True

    async def _heartbeat(self):
        try:
            while True:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    self.reason = AttemptDeadline
                    break
                alive = await asyncio.wait_for(
                    self.renew_authority(),
                    timeout=min(self.settings.heartbeat_seconds, remaining),
                )
                if not alive:
                    break
                await asyncio.sleep(min(self.settings.heartbeat_seconds, remaining))
        except Exception as error:
            # Infrastructure uncertainty revokes authority rather than extending a lease.
            logger.warning("encoder authority revoked: %s", type(error).__name__)
        self.lost.set()

    async def guard(self, awaitable):
        task = asyncio.ensure_future(awaitable)
        loss = asyncio.create_task(self.lost.wait())
        try:
            self.check()
            remaining = self.deadline - time.monotonic()
            done, _ = await asyncio.wait(
                [task, loss], timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            self.check()
            if task not in done:
                raise AttemptDeadline()
            return await task
        finally:
            for pending in (task, loss):
                if not pending.done():
                    pending.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending

    async def run(self, command):
        self.check()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        completed = False
        try:
            stdout, _stderr = await self.guard(process.communicate())
            if process.returncode != 0:
                raise ValueError("the video could not be processed; check the source or edit")
            completed = True
            return stdout.decode()
        finally:
            if not completed or process.returncode is None:
                # SIGKILL bounds cancellation even when a child ignores SIGTERM.
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
