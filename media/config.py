from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIA_", extra="ignore")

    postgres_dsn: str = Field(repr=False)
    migration_dsn: str | None = Field(default=None, repr=False)
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_seconds: int = Field(default=3600, ge=60)
    processing_url: str = "http://processing:8000"
    processing_service_token: SecretStr = SecretStr("")
    source_service_token: SecretStr = SecretStr("")
    processing_timeout_seconds: float = Field(default=5, gt=0, le=30)
    storage_credential_mode: Literal["static", "ecs"] = "static"
    minio_endpoint: str = "minio:9000"
    minio_use_ssl: bool = False
    minio_region: str = "us-east-1"
    minio_access_key: str = ""
    minio_secret_key: SecretStr = SecretStr("")
    minio_source_bucket: str = "sources"
    minio_output_bucket: str = "outputs"
    minio_public_endpoint: str = "localhost:3443"
    minio_public_use_ssl: bool = True
    public_url: str = "https://localhost:3443"
    api_public_prefix: str = "/api"
    signed_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    recovery_interval_seconds: float = Field(default=10, gt=0)
    recovery_batch_size: int = Field(default=100, ge=1, le=200)
    orphan_grace_seconds: int = Field(default=3600, ge=60)

    @field_validator("postgres_dsn", "migration_dsn")
    @classmethod
    def postgres_only(cls, value: str | None) -> str | None:
        if value is None:
            return value
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                value = "postgresql+asyncpg://" + value[len(prefix) :]
                break
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("Media requires PostgreSQL asyncpg")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
