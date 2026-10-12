"""Bounded SQL session doubles for fast domain decisions, not persistence proof."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from processing.models import Attempt, Job, SubmissionGuard

NOW = datetime(2026, 10, 13, 1, tzinfo=UTC)


class Rows:
    def __init__(self, values=()):
        self.values = values

    def all(self):
        return self.values

    def scalar_one(self):
        return self.values[0]

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def one_or_none(self):
        return self.values[0] if self.values else None

    def __iter__(self):
        return iter(self.values)


class Session:
    def __init__(self):
        self.execute = AsyncMock(return_value=Rows())
        self.scalar = AsyncMock(return_value=NOW)
        self.get = AsyncMock(return_value=None)
        self.flush = AsyncMock()
        self.add = Mock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    @asynccontextmanager
    async def begin(self):
        yield self


def pair(state="processing"):
    asset, owner, jobid, attemptid = uuid4(), uuid4(), uuid4(), uuid4()
    job = Job(
        id=jobid,
        asset_id=asset,
        owner_id=owner,
        status=state,
        current_attempt_id=attemptid,
        source={
            "asset_id": str(asset),
            "revision": 1,
            "sha256": "a" * 64,
            "size_bytes": 10,
            "media_type": "video/mp4",
        },
        source_url="http://source.test",
        source_url_expires_at=NOW,
        operations=[],
        request_hash="hash",
        outputs=[],
        created_at=NOW,
        updated_at=NOW,
    )
    attempt = Attempt(
        id=attemptid,
        job_id=jobid,
        attempt_number=1,
        state=state,
        queued_at=NOW,
        lease_token=uuid4(),
        deadline_at=NOW + timedelta(minutes=15),
        lease_expires_at=NOW + timedelta(seconds=60),
        dispatch_count=0,
    )
    guard = SubmissionGuard(asset_id=asset, owner_id=owner, job_id=jobid)
    work = SimpleNamespace(job_id=jobid, attempt_id=attemptid, lease_token=attempt.lease_token)
    return job, attempt, guard, work
