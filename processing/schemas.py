from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AnyUrl, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

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


class ClipParams(StrictObject):
    start: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    end: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def ordered_interval(self) -> Self:
        if self.end <= self.start:
            raise ValueError("clip end must exceed start")
        return self


class CropParams(StrictObject):
    x: NonnegativeInt
    y: NonnegativeInt
    w: PositiveInt
    h: PositiveInt


class ScaleParams(StrictObject):
    height: PositiveInt


class ConvertParams(StrictObject):
    format: Literal["mkv", "mp3"]


class ClipOperation(StrictObject):
    operation: Literal["clip"]
    params: ClipParams


class CropOperation(StrictObject):
    operation: Literal["crop"]
    params: CropParams


class DownscaleOperation(StrictObject):
    operation: Literal["downscale"]
    params: ScaleParams


class UpscaleOperation(StrictObject):
    operation: Literal["upscale"]
    params: ScaleParams


class ConvertOperation(StrictObject):
    operation: Literal["convert"]
    params: ConvertParams


EditOperation = Annotated[
    ClipOperation | CropOperation | DownscaleOperation | UpscaleOperation | ConvertOperation,
    Field(discriminator="operation"),
]


class SubmitJob(StrictObject):
    asset_id: UUID
    owner_id: UUID
    source: Source
    source_url: AnyUrl
    source_url_expires_at: AwareDatetime
    # Omitted means original upload; explicit [] or null violates the contract.
    operations: list[EditOperation] = Field(default_factory=list, min_length=1, max_length=5)

    @model_validator(mode="after")
    def consistent_request(self) -> Self:
        if self.source.asset_id != self.asset_id:
            raise ValueError("source.asset_id must equal asset_id")
        names = [op.operation for op in self.operations]
        if len(names) != len(set(names)):
            raise ValueError("operation names must be unique")
        if "upscale" in names and "downscale" in names:
            raise ValueError("upscale and downscale cannot be combined")
        return self


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


class RetryJob(StrictObject):
    retry_request_id: UUID


class SourceAccess(StrictObject):
    source_url: AnyUrl
    expires_at: AwareDatetime
    source: Source
