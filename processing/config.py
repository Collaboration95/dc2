from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROCESSING_", extra="ignore")

    postgres_dsn: str = Field(repr=False)
    database_tls: bool = True
    database_ca_file: str | None = None
    database_connect_timeout_seconds: float = Field(default=10, gt=0, le=30)
    release_version: str = "v1-dev"
    service_token: SecretStr = SecretStr("")
    migration_dsn: str | None = Field(default=None, repr=False)

    redis_url: SecretStr = SecretStr("")
    queue_name: str = "processing"
    media_url: str = "http://media:8000"
    source_service_token: SecretStr = SecretStr("")
    storage_credential_mode: Literal["static", "ecs", "lambda"] = "static"
    minio_endpoint: str = "minio:9000"
    minio_use_ssl: bool = False
    minio_region: str = "us-east-1"
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_output_bucket: str = "outputs"
    lease_seconds: int = Field(default=60, ge=2, le=240)
    heartbeat_seconds: float = Field(default=10, gt=0)
    attempt_timeout_seconds: int = Field(default=900, ge=1)
    recovery_interval_seconds: float = Field(default=15, gt=0, le=60)
    queue_retry_cap_seconds: int = Field(default=60, ge=1, le=90)
    http_timeout_seconds: float = Field(default=15, gt=0)
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_preset: str = "veryfast"
    ffmpeg_crf: int = Field(default=23, ge=0, le=51)

    def require_storage(self):
        from processing.storage_credentials import credential_provider

        if self.storage_credential_mode == "static" and not (
            self.minio_access_key.get_secret_value() and self.minio_secret_key.get_secret_value()
        ):
            raise ValueError("Output storage requires a complete credential pair")
        credential_provider(self)  # Validate only; no credential endpoint fetch at startup.

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

    @model_validator(mode="after")
    def heartbeat_within_lease(self):
        if self.heartbeat_seconds >= self.lease_seconds / 2:
            raise ValueError("heartbeat interval must be less than half the lease")
        return self

    @field_validator("postgres_dsn", "migration_dsn")
    @classmethod
    def async_postgres_dsn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                value = "postgresql+asyncpg://" + value[len(prefix) :]
                break
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("Processing requires a PostgreSQL asyncpg DSN")
        return value


@lru_cache
def get_settings() -> Settings:
    from runtime_support.settings import runtime_values

    return Settings(**runtime_values("PROCESSING"))
