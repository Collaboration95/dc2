from uuid import UUID

from sqlalchemy import select

from processing.models import Attempt, Job, SubmissionGuard
from processing.schemas import AttemptResponse, ProcessingJob


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
