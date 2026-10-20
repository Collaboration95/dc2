"""Media facade for the shared native MinIO credential policy."""

from runtime_support.storage_credentials import (
    ContainerProvider,
    LambdaProvider,
    validate_container_environment,
)
from runtime_support.storage_credentials import (
    credential_provider as _credential_provider,
)

__all__ = [
    "ContainerProvider",
    "LambdaProvider",
    "credential_provider",
    "validate_container_environment",
]


def credential_provider(settings):
    def reveal(value):
        return value.get_secret_value() if hasattr(value, "get_secret_value") else value

    return _credential_provider(
        getattr(settings, "storage_credential_mode", "static"),
        reveal(settings.minio_access_key),
        reveal(settings.minio_secret_key),
    )
