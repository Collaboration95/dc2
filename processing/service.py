import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from processing.errors import ProcessingError
from processing.models import Attempt, Job, SubmissionGuard
from processing.schemas import AttemptResponse, ProcessingJob, SubmitJob


def request_fingerprint(request: SubmitJob) -> str:
    immutable = request.model_dump(mode="json", exclude={"source_url", "source_url_expires_at"})
    canonical = json.dumps(immutable, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def job_response(job: Job, attempt: Attempt) -> ProcessingJob:
    return ProcessingJob(
        job_id=job.id,
        asset_id=job.asset_id,
        owner_id=job.owner_id,
        status=job.status,
        source=job.source,
        current_attempt=AttemptResponse(
            attempt_id=attempt.id,
            number=attempt.attempt_number,
            state=attempt.state,
            queued_at=attempt.queued_at,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            error=attempt.error,
        ),
        outputs=job.outputs or [],
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def submit_job(
    session: AsyncSession, owner_id: UUID, request: SubmitJob
) -> tuple[ProcessingJob, bool]:
    if owner_id != request.owner_id:
        raise ProcessingError(404, "Job not found")
    fingerprint = request_fingerprint(request)
    async with session.begin():
        # ON CONFLICT waits for concurrent inserts; the following row lock also
        # serializes submissions against a future cancellation on this asset.
        await session.execute(
            insert(SubmissionGuard)
            .values(asset_id=request.asset_id, owner_id=owner_id)
            .on_conflict_do_nothing(index_elements=[SubmissionGuard.asset_id])
        )
        guard = (
            await session.execute(
                select(SubmissionGuard)
                .where(SubmissionGuard.asset_id == request.asset_id)
                .with_for_update()
            )
        ).scalar_one()
        if guard.owner_id != owner_id:
            raise ProcessingError(404, "Job not found")
        if guard.deleted_at is not None:
            raise ProcessingError(410, "Asset processing is deleted")

        if guard.job_id is not None:
            job = await session.get(Job, guard.job_id)
            if job is None or job.owner_id != owner_id:
                raise ProcessingError(503, "Processing submission is inconsistent")
            if job.deleted_at is not None:
                raise ProcessingError(410, "Asset processing is deleted")
            if job.request_hash != fingerprint:
                raise ProcessingError(409, "Asset already has a different processing request")
            attempt = await session.get(Attempt, job.current_attempt_id)
            if attempt is None or attempt.job_id != job.id:
                raise ProcessingError(503, "Processing attempt is unavailable")
            result = job_response(job, attempt)
            created = False
        else:
            now = await session.scalar(select(func.clock_timestamp()))
            job_id, attempt_id = uuid4(), uuid4()
            job = Job(
                id=job_id,
                asset_id=request.asset_id,
                owner_id=owner_id,
                source=request.source.model_dump(mode="json"),
                operations=[op.model_dump(mode="json") for op in request.operations],
                request_hash=fingerprint,
                source_url=str(request.source_url),
                source_url_expires_at=request.source_url_expires_at,
                status="queued",
                current_attempt_id=attempt_id,
                created_at=now,
                updated_at=now,
            )
            session.add(job)
            # current_attempt_id's FK is deferred until commit, allowing the
            # nonnullable pointer and its attempt to be created atomically.
            await session.flush()
            attempt = Attempt(
                id=attempt_id,
                job_id=job_id,
                attempt_number=1,
                state="queued",
                queued_at=now,
            )
            session.add(attempt)
            guard.job_id = job_id
            await session.flush()
            result = job_response(job, attempt)
            created = True
    # The transaction (including its deferred FK) committed before success.
    # Intake only: worker dispatch and reconciliation are not connected yet.
    return result, created


def owned_jobs(owner_id: UUID):
    return (
        select(Job, Attempt)
        .join(Attempt, (Attempt.id == Job.current_attempt_id) & (Attempt.job_id == Job.id))
        .join(SubmissionGuard, SubmissionGuard.asset_id == Job.asset_id)
        .where(
            Job.owner_id == owner_id,
            Job.deleted_at.is_(None),
            SubmissionGuard.owner_id == owner_id,
            SubmissionGuard.deleted_at.is_(None),
        )
    )


async def get_job(session: AsyncSession, owner_id: UUID, job_id: UUID) -> ProcessingJob:
    row = (await session.execute(owned_jobs(owner_id).where(Job.id == job_id))).one_or_none()
    if row is None:
        raise ProcessingError(404, "Job not found")
    return job_response(*row)


async def list_jobs(
    session: AsyncSession, owner_id: UUID, asset_ids: list[UUID]
) -> list[ProcessingJob]:
    rows = await session.execute(
        owned_jobs(owner_id).where(Job.asset_id.in_(asset_ids)).order_by(Job.created_at, Job.id)
    )
    return [job_response(*row) for row in rows]
