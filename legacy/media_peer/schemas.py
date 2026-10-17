"""Peer-HTTP wire DTOs matching the retired Processing OpenAPI (legacy local stack only)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from media.schemas.outputs import Digest, Output

PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class StrictObject(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictObject):
    asset_id: UUID
    revision: PositiveInt
    sha256: Digest
    size_bytes: PositiveInt
    media_type: str


class AttemptResponse(BaseModel):
    attempt_id: UUID
    number: PositiveInt
    state: Literal["queued", "processing", "succeeded", "failed", "abandoned", "cancelled"]
    queued_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error: str | None = None


class ProcessingJob(BaseModel):
    job_id: UUID
    asset_id: UUID
    owner_id: UUID
    status: Literal["queued", "processing", "done", "failed"]
    source: Source
    current_attempt: AttemptResponse
    outputs: list[Output]
    error: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
