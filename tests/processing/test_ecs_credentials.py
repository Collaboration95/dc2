from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from minio.credentials import Credentials
from urllib3 import HTTPResponse

from legacy.processing_rq.config import LegacySettings as Settings
from processing import storage_credentials
from processing.recovery import CleanupStore
from processing.worker.storage import OutputStore


@pytest.fixture
def ecs(monkeypatch):
    for key in [
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/credentials/fake")
    return Settings(
        postgres_dsn="postgresql://dummy@invalid/processing_db",
        storage_credential_mode="ecs",
        redis_url="redis://invalid",
        source_service_token="dummy-reverse",
    )


def test_worker_and_recovery_guards_keep_redis_and_reverse_token(ecs):
    ecs.require_worker()
    ecs.require_recovery()
    with pytest.raises(ValueError, match="Redis"):
        ecs.model_copy(update={"redis_url": type(ecs.redis_url)("")}).require_worker()
    with pytest.raises(ValueError, match="source access token"):
        ecs.model_copy(
            update={"source_service_token": type(ecs.source_service_token)("")}
        ).require_worker()
    ecs.model_copy(
        update={"source_service_token": type(ecs.source_service_token)("")}
    ).require_recovery()
    with pytest.raises(ValueError, match="overrides"):
        ecs.model_copy(
            update={"minio_access_key": type(ecs.minio_access_key)("dummy")}
        ).require_recovery()


def test_api_needs_no_storage_or_container_environment(monkeypatch):
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
    # Settings alone is the API's unchanged boundary; worker/recovery have explicit guards.
    cfg = Settings(postgres_dsn="postgresql://dummy@invalid/db", storage_credential_mode="ecs")
    assert not cfg.minio_access_key.get_secret_value()
    with pytest.raises(ValueError, match="Redis"):
        cfg.require_recovery()


async def test_writer_and_cleanup_use_separate_native_providers(ecs, monkeypatch, tmp_path):
    tokens = ["writer-A", "writer-B", "cleanup-C", "cleanup-D"]
    native = Mock(
        retrieve=Mock(
            side_effect=[
                Credentials(
                    "dummy-access", "dummy-secret", token, datetime.now(UTC) + timedelta(minutes=5)
                )
                for token in tokens
            ]
        )
    )
    factory = Mock(return_value=native)
    monkeypatch.setattr(storage_credentials, "IamAwsProvider", factory)
    writer, cleanup = OutputStore(ecs), CleanupStore(ecs)
    assert factory.call_count == 2
    seen = []

    def request(method, url, **kw):
        seen.append((method, kw["headers"].get("X-Amz-Security-Token")))
        return HTTPResponse(status=200, headers={"etag": '"ack"'}, body=b"")

    monkeypatch.setattr(writer.client._http, "urlopen", request)
    monkeypatch.setattr(cleanup.client._http, "urlopen", request)
    path = Path(tmp_path / "output")
    import asyncio

    await asyncio.to_thread(path.write_bytes, b"output")
    first = await writer.put("attempt/key", path, "video/mp4", "primary")
    second = await writer.put("attempt/key", path, "video/mp4", "primary")
    assert first["sha256"] == second["sha256"] and first["size_bytes"] == 6
    cleanup.client.remove_object("outputs", "attempt/key")
    cleanup.client.remove_object("outputs", "attempt/key")
    assert seen == [
        ("PUT", "writer-A"),
        ("PUT", "writer-B"),
        ("DELETE", "cleanup-C"),
        ("DELETE", "cleanup-D"),
    ]


def test_native_transport_is_bounded_and_failure_has_no_fallback(ecs, monkeypatch):
    pool = Mock()
    native = Mock(retrieve=Mock(side_effect=RuntimeError("secret-endpoint-token")))
    monkeypatch.setattr(storage_credentials, "PoolManager", pool)
    monkeypatch.setattr(storage_credentials, "IamAwsProvider", Mock(return_value=native))
    provider = storage_credentials.ContainerProvider()
    assert pool.call_args.kwargs["retries"] is False
    assert pool.call_args.kwargs["timeout"].connect_timeout == 1
    assert pool.call_args.kwargs["timeout"].read_timeout == 2
    with pytest.raises(ValueError, match="^Task storage credentials unavailable$"):
        provider.retrieve()
    assert native.retrieve.call_count == 1
