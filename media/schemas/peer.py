"""Media-owned wire DTOs matching the authored Processing OpenAPI."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


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


class Output(BaseModel):
    kind: Literal["primary", "hls_manifest"]
    object_key: str = Field(min_length=1)
    media_type: str
    size_bytes: NonnegativeInt | None = None
    sha256: Digest | None = None


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
