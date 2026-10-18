"""Settings only the retired peer-calling Media app reads (Processing URL and service tokens)."""

from functools import lru_cache

from pydantic import Field, SecretStr

from media.config import Settings


class LegacyMediaSettings(Settings):
    processing_url: str = "http://processing:8000"
    processing_service_token: SecretStr = SecretStr("")
    source_service_token: SecretStr = SecretStr("")
    processing_timeout_seconds: float = Field(default=5, gt=0, le=30)


@lru_cache
def get_settings() -> LegacyMediaSettings:
    from runtime_support.settings import runtime_values

    return LegacyMediaSettings(**runtime_values("MEDIA"))
