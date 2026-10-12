from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from processing import lifecycle, service
from processing.auth import get_owner_id
from processing.database import get_session
from processing.errors import ProcessingError
from processing.schemas import ProcessingJob, RetryJob, SubmitJob

Owner = Annotated[UUID, Depends(get_owner_id)]
Session = Annotated[AsyncSession, Depends(get_session)]
AssetIds = Annotated[list[UUID], Field(min_length=1, max_length=200)]


def parse_asset_ids(asset_ids: Annotated[str, Query()]) -> list[UUID]:
    try:
        return TypeAdapter(AssetIds).validate_python(asset_ids.split(","))
    except ValidationError as exc:
        errors = [{**error, "loc": ("query", "asset_ids", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors) from exc


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        yield
    finally:
        engine = getattr(application.state, "engine", None)
        if engine is not None:
            await engine.dispose()
            application.state.engine = None


def create_app() -> FastAPI:
    application = FastAPI(
        title="FlickPond Processing private API",
        version="1.0.0-intake",
        description=(
            "Intake only. Jobs and initial queued attempts are durable. "
            "Worker dispatch and reconciliation are not yet connected."
        ),
        lifespan=lifespan,
    )

    @application.exception_handler(ProcessingError)
    async def processing_error(_request: Request, exc: ProcessingError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse({"error": exc.message}, status_code=exc.status_code, headers=headers)

    async def unavailable(_request: Request, _exc: Exception):
        return JSONResponse({"error": "Processing database unavailable"}, status_code=503)

    for error_type in (SQLAlchemyError, OSError, TimeoutError):
        application.add_exception_handler(error_type, unavailable)

    @application.get("/health")
    async def health(session: Session):
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "stage": "intake-only", "worker_dispatch_connected": False}

    @application.post(
        "/internal/v1/jobs",
        response_model=ProcessingJob,
        status_code=201,
        response_model_exclude_none=True,
        operation_id="submitJob",
    )
    async def submit(request: SubmitJob, response: Response, owner_id: Owner, session: Session):
        job, created = await service.submit_job(session, owner_id, request)
        response.status_code = 201 if created else 200
        return job

    @application.get(
        "/internal/v1/jobs",
        response_model=list[ProcessingJob],
        response_model_exclude_none=True,
        operation_id="listJobs",
        openapi_extra={
            "parameters": [
                {
                    "name": "asset_ids",
                    "in": "query",
                    "required": True,
                    "style": "form",
                    "explode": False,
                    "schema": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "minItems": 1,
                        "maxItems": 200,
                    },
                }
            ]
        },
    )
    async def batch(
        owner_id: Owner,
        session: Session,
        asset_ids: Annotated[list[UUID], Depends(parse_asset_ids)],
    ):
        return await service.list_jobs(session, owner_id, asset_ids)

    @application.get(
        "/internal/v1/jobs/{job_id}",
        response_model=ProcessingJob,
        response_model_exclude_none=True,
        operation_id="getJob",
    )
    async def read(job_id: UUID, owner_id: Owner, session: Session):
        return await service.get_job(session, owner_id, job_id)

    @application.post(
        "/internal/v1/jobs/{job_id}/retry",
        response_model=ProcessingJob,
        status_code=202,
        response_model_exclude_none=True,
        operation_id="retryJob",
    )
    async def retry(job_id: UUID, request: RetryJob, owner_id: Owner, session: Session):
        return await lifecycle.retry_job(session, owner_id, job_id, request.retry_request_id)

    @application.delete(
        "/internal/v1/assets/{asset_id}/job", status_code=204, operation_id="cancelAssetJob"
    )
    async def cancel(asset_id: UUID, owner_id: Owner, session: Session):
        await lifecycle.cancel_asset(session, owner_id, asset_id)
        return Response(status_code=204)

    return application


app = create_app()
