"""Media-owned DTO for the outputs a Processing result reports."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Output(BaseModel):
    kind: Literal["primary", "hls_manifest"]
    object_key: str = Field(min_length=1)
    media_type: str
    size_bytes: NonnegativeInt | None = None
    sha256: Digest | None = None
