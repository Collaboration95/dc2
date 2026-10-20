"""All mutations lock Job before Attempt, using DB time and current-attempt fences.

No lock is held while fetching media or running FFmpeg. A unique lease token
prevents even a duplicate delivery of the same Attempt from writing as its owner.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from processing.errors import ProcessingError
from processing.models import Attempt, CleanupIntent, Job, RetryRequest, SubmissionGuard
from processing.schemas import Output
from processing.service import job_response


def output_prefix(job_id: UUID, attempt_id: UUID) -> str:
    return f"jobs/{job_id}/attempts/{attempt_id}/"


async def db_now(session):
    return await session.scalar(select(func.clock_timestamp()))


async def lock_pair(session, job_id, attempt_id):
    job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.deleted_at is not None or job.current_attempt_id != attempt_id:
        return None
    attempt = await session.get(Attempt, attempt_id)
    if attempt is None or attempt.job_id != job.id:
        return None
    return job, attempt


def live(pair, token, now):
    if pair is None:
        return False
    job, attempt = pair
    return (
        job.status == "processing"
        and attempt.state == "processing"
        and attempt.lease_token == token
        and attempt.lease_expires_at > now
        and attempt.deadline_at > now
    )


async def cleanup_intent(session, job_id, attempt_id, now):
    await session.execute(
        insert(CleanupIntent)
        .values(job_id=job_id, attempt_id=attempt_id, next_try_at=now)
        .on_conflict_do_nothing(index_elements=[CleanupIntent.attempt_id])
    )


async def retry_job(session, owner_id, job_id, request_id):
    async with session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.owner_id != owner_id:
            raise ProcessingError(404, "Job not found")
        if job.deleted_at is not None:
            raise ProcessingError(410, "Asset processing is deleted")
        attempt = await session.get(Attempt, job.current_attempt_id)
        saved = await session.scalar(
            select(RetryRequest).where(
                RetryRequest.job_id == job_id, RetryRequest.request_id == request_id
            )
        )
        if saved is None:
            if job.status != "failed":
                raise ProcessingError(409, "Only failed jobs can be retried")
            now = await db_now(session)
            await cleanup_intent(session, job.id, attempt.id, now)
            attempt = Attempt(
                id=uuid4(),
                job_id=job.id,
                attempt_number=attempt.attempt_number + 1,
                state="queued",
                queued_at=now,
            )
            session.add(attempt)
            await session.flush()
            session.add(RetryRequest(job_id=job.id, request_id=request_id, attempt_id=attempt.id))
            job.current_attempt_id = attempt.id
            job.status, job.error, job.outputs, job.updated_at = "queued", None, [], now
        result = job_response(job, attempt)
    return result


async def cancel_asset(session, owner_id, asset_id, *, on_change=None):
    async with session.begin():
        await session.execute(
            insert(SubmissionGuard)
            .values(asset_id=asset_id, owner_id=owner_id)
            .on_conflict_do_nothing(index_elements=[SubmissionGuard.asset_id])
        )
        guard = await session.scalar(
            select(SubmissionGuard).where(SubmissionGuard.asset_id == asset_id).with_for_update()
        )
        if guard.owner_id != owner_id:
            raise ProcessingError(404, "Job not found")
        now = await db_now(session)
        guard.deleted_at = guard.deleted_at or now
        if guard.job_id is not None:
            job = await session.scalar(select(Job).where(Job.id == guard.job_id).with_for_update())
            job.deleted_at = job.deleted_at or now
            job.outputs, job.updated_at = [], now
            attempts = (
                await session.scalars(select(Attempt).where(Attempt.job_id == job.id))
            ).all()
            for attempt in attempts:
                if attempt.state in {"queued", "processing"}:
                    attempt.state, attempt.finished_at = "cancelled", now
                    attempt.lease_expires_at = now
                await cleanup_intent(session, job.id, attempt.id, now)
            if on_change is not None:
                await on_change(session, job, await session.get(Attempt, job.current_attempt_id))


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    attempt_id: UUID
    lease_token: UUID
    owner_id: UUID
    source: dict
    operations: list
    source_url: str = field(repr=False)
    source_url_expires_at: datetime
    deadline_at: datetime


async def claim(factory, job_id, attempt_id, settings, *, on_change=None, before_claim=None):
    async with factory() as session, session.begin():
        if before_claim is not None and not await before_claim(session):
            return None
        pair = await lock_pair(session, job_id, attempt_id)
        if pair is None:
            return None
        job, attempt = pair
        if job.status != "queued" or attempt.state != "queued":
            return None
        now = await db_now(session)
        token = uuid4()
        job.status, job.updated_at = "processing", now
        attempt.state, attempt.started_at, attempt.heartbeat_at = "processing", now, now
        attempt.lease_token = token
        attempt.deadline_at = now + timedelta(seconds=settings.attempt_timeout_seconds)
        attempt.lease_expires_at = min(
            attempt.deadline_at, now + timedelta(seconds=settings.lease_seconds)
        )
        if on_change is not None:
            await on_change(session, job, attempt)
        return Claim(
            job.id,
            attempt.id,
            token,
            job.owner_id,
            job.source,
            job.operations,
            job.source_url,
            job.source_url_expires_at,
            attempt.deadline_at,
        )


async def heartbeat(factory, work, settings):
    async with factory() as session, session.begin():
        pair = await lock_pair(session, work.job_id, work.attempt_id)
        now = await db_now(session)
        if not live(pair, work.lease_token, now):
            return False
        job, attempt = pair
        attempt.heartbeat_at, job.updated_at = now, now
        attempt.lease_expires_at = min(
            attempt.deadline_at, now + timedelta(seconds=settings.lease_seconds)
        )
        return True


async def finish(factory, work, *, outputs=None, error=None, on_change=None):
    # Validate the acknowledged primary and attempt namespace before any DB write.
    checked = []
    if error is None:
        checked = [
            Output.model_validate(item).model_dump(mode="json", exclude_none=True)
            for item in (outputs or [])
        ]
        prefix = output_prefix(work.job_id, work.attempt_id)
        if (
            sum(x["kind"] == "primary" for x in checked) != 1
            or len({x["kind"] for x in checked}) != len(checked)
            or any(
                not x["object_key"].startswith(prefix)
                or ".." in x["object_key"].split("/")
                or not x.get("size_bytes")
                or not x.get("sha256")
                for x in checked
            )
        ):
            raise ValueError("Verified outputs in the current attempt namespace are required")
    async with factory() as session, session.begin():
        pair = await lock_pair(session, work.job_id, work.attempt_id)
        now = await db_now(session)
        if not live(pair, work.lease_token, now):
            return False
        job, attempt = pair
        attempt.finished_at, job.updated_at = now, now
        if error is None:
            job.status, job.outputs, attempt.state = "done", checked, "succeeded"
            job.error, attempt.error = None, None
        else:
            # Caller supplies curated errors only; never persist exception URLs/tokens.
            job.status, job.error, attempt.state, attempt.error = "failed", error, "failed", error
            await cleanup_intent(session, job.id, attempt.id, now)
        if on_change is not None:
            await on_change(session, job, attempt)
        return True
