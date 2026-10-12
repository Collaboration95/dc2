from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=72)]

    @field_validator("password")
    @classmethod
    def byte_limit(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    role: Literal["user", "operator"]


class Accepted(BaseModel):
    job_id: UUID


class PublicJob(BaseModel):
    id: UUID
    filename: str
    status: Literal["queued", "processing", "done", "failed"]
    submission_status: Literal["pending", "submitted", "error"]
    output_url: str | None = None
    hls_url: str | None = None
    error: str | None = None


class SourceAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]
