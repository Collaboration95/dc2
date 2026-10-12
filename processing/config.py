from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROCESSING_", extra="ignore")

    postgres_dsn: str
    service_token: SecretStr = SecretStr("")
    migration_dsn: str | None = None

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
    return Settings()
