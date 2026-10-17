"""Public Processing V1 API: owned reads and mutations, command-only creation.

The legacy private HTTP application remains a separate regression surface. This
application never mounts it or imports Redis/RQ, a worker, or any Media package.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from contracts.v1 import Actor
from processing.auth import gateway_actor
from processing.config import Settings, get_settings
from processing.database import get_v1_session
from processing.errors import ProcessingError
from processing.schemas import RetryJob
from processing.service import owned_jobs

Identity = Annotated[Actor, Depends(gateway_actor)]
Session = Annotated[AsyncSession, Depends(get_v1_session)]
Configuration = Annotated[Settings, Depends(get_settings)]


def publisher(actor: Identity) -> Actor:
    if actor.role != "publisher":
        raise ProcessingError(403, "Publisher role required")
    return actor


Publisher = Annotated[Actor, Depends(publisher)]


def public_job(job, attempt) -> dict:
    """Return metadata only: immutable source remains in trusted command storage."""
    return {
        "job_id": job.id,
        "processing_job_id": job.id,
        "asset_id": job.asset_id,
        "owner_id": job.owner_id,
        "status": job.status,
        "current_attempt": {
            "attempt_id": attempt.id,
            "number": attempt.attempt_number,
            "state": attempt.state,
            "queued_at": attempt.queued_at,
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
            "error": attempt.error,
        },
        "outputs": job.outputs or [],
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


async def owned_pair(session, owner_id, job_id):
    from processing.models import Job

    result = await session.execute(owned_jobs(owner_id).where(Job.id == job_id))
    pair = result.one_or_none()
    if pair is None:
        raise ProcessingError(404, "Job not found")
    return pair


async def retry_owned(session, owner_id, job_id, request_id):
    # Imported only when required: the public API has no SQS-send dependency.
    from processing.messaging import retry_job

    await retry_job(session, owner_id, job_id, request_id)
    return public_job(*await owned_pair(session, owner_id, job_id))


async def cancel_owned(session, owner_id, job_id):
    from processing.messaging import cancel_asset

    pair = await owned_pair(session, owner_id, job_id)
    asset_id = pair[0].asset_id
    # Finish the read-only autobegin before the messaging mutation owns its tx.
    await session.rollback()
    await cancel_asset(session, owner_id, asset_id)


def parse_ids(asset_ids: Annotated[str, Query()]) -> list[UUID]:
    try:
        values = asset_ids.split(",")
        if not 1 <= len(values) <= 200:
            raise ValueError
        return [UUID(value) for value in values]
    except ValueError as exc:
        raise ProcessingError(422, "asset_ids must contain 1 to 200 UUIDs") from exc


def create_app() -> FastAPI:
    app = FastAPI(
        title="FlickPond Processing V1 API",
        version="1.0.1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ProcessingError)
    async def domain_error(_request: Request, exc: ProcessingError):
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid_request(_request: Request, _exc):
        return JSONResponse({"error": "Invalid request"}, status_code=422)

    async def unavailable(_request: Request, _exc):
        return JSONResponse({"error": "Processing database unavailable"}, status_code=503)

    for error in (SQLAlchemyError, OSError, TimeoutError):
        app.add_exception_handler(error, unavailable)

    @app.get("/health")
    async def health(settings: Configuration):
        # Public and unauthenticated: it must never open a connection, or any caller could
        # wake a paused Aurora cluster. Database readiness is the operator-only `ready()`.
        return {
            "status": "ok",
            "service": "processing",
            "schema_version": 1,
            "version": settings.release_version,
        }

    @app.get("/jobs")
    async def batch(
        actor: Identity, session: Session, asset_ids: Annotated[list[UUID], Depends(parse_ids)]
    ):
        from processing.models import Job

        rows = await session.execute(
            owned_jobs(UUID(actor.owner_id))
            .where(Job.asset_id.in_(asset_ids))
            .order_by(Job.created_at, Job.id)
        )
        return [public_job(*row) for row in rows]

    @app.get("/jobs/{job_id}")
    async def read(job_id: UUID, actor: Identity, session: Session):
        return public_job(*await owned_pair(session, UUID(actor.owner_id), job_id))

    @app.post("/jobs/{job_id}/retry", status_code=202)
    async def retry(job_id: UUID, request: RetryJob, actor: Publisher, session: Session):
        return await retry_owned(session, UUID(actor.owner_id), job_id, request.retry_request_id)

    @app.delete("/jobs/{job_id}", status_code=204)
    async def cancel(job_id: UUID, actor: Publisher, session: Session):
        await cancel_owned(session, UUID(actor.owner_id), job_id)
        return Response(status_code=204)

    return app


app = create_app()
