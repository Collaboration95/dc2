"""Settings only the retired Redis/RQ stack reads (queue, source-grant callback to Media)."""

from functools import lru_cache

from pydantic import Field, SecretStr

from processing.config import Settings


class LegacySettings(Settings):
    redis_url: SecretStr = SecretStr("")
    queue_name: str = "processing"
    media_url: str = "http://media:8000"
    # Media-to-Processing bearer secret (forward) and Processing-to-Media source grant (reverse).
    service_token: SecretStr = SecretStr("")
    source_service_token: SecretStr = SecretStr("")
    queue_retry_cap_seconds: int = Field(default=60, ge=1, le=90)

    def require_worker(self):
        if (
            not self.redis_url.get_secret_value()
            or not self.source_service_token.get_secret_value()
        ):
            raise ValueError("Worker requires Redis and source access token")
        self.require_storage()

    def require_recovery(self):
        if not self.redis_url.get_secret_value():
            raise ValueError("Recovery requires Redis")
        self.require_storage()


@lru_cache
def get_settings() -> LegacySettings:
    from runtime_support.settings import runtime_values

    return LegacySettings(**runtime_values("PROCESSING"))
