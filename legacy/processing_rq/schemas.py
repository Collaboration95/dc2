"""Retired HTTP bodies that carried a presigned ``source_url`` (submission and source grant)."""

from typing import Self
from uuid import UUID

from pydantic import AnyUrl, AwareDatetime, Field, model_validator

from processing.schemas import EditOperation, Source, StrictObject


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


class SourceAccess(StrictObject):
    source_url: AnyUrl
    expires_at: AwareDatetime
    source: Source
