"""Responsive lease/deadline supervision independent of download/encode/upload."""

import asyncio
import os
import signal
import time
from contextlib import suppress

from processing.lifecycle import heartbeat


class LeaseLost(Exception):
    """Control-flow cancellation; never absorbed by best-effort media fallback."""


class AttemptDeadline(Exception):
    pass


class Supervisor:
    def __init__(self, factory, work, settings):
        self.factory, self.work, self.settings = factory, work, settings
        self.lost = asyncio.Event()
        self.reason = LeaseLost
        self.deadline = time.monotonic() + settings.attempt_timeout_seconds
        self.task = None

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

    async def _heartbeat(self):
        try:
            while True:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    self.reason = AttemptDeadline
                    break
                alive = await asyncio.wait_for(
                    heartbeat(self.factory, self.work, self.settings),
                    timeout=min(self.settings.heartbeat_seconds, remaining),
                )
                if not alive:
                    break
                await asyncio.sleep(min(self.settings.heartbeat_seconds, remaining))
        except Exception:
            # Infrastructure uncertainty revokes authority rather than extending a lease.
            pass
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
