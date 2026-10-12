from contextlib import asynccontextmanager
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.datastructures import UploadFile

from media.config import Settings
from media.models import Asset, User, now
from media.schemas.peer import ProcessingJob


@asynccontextmanager
async def transaction():
    yield


@pytest.fixture
def session():
    mock = MagicMock()
    mock.begin.side_effect = transaction
    mock.get = AsyncMock(return_value=None)
    mock.scalar = AsyncMock(return_value=None)
    mock.scalars = AsyncMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.rollback = AsyncMock()
    return mock


@pytest.fixture
def settings():
    return Settings(
        postgres_dsn="postgresql+asyncpg://unused:unused@invalid/media_db",
        jwt_secret="unit-signing-secret-at-least-32-bytes",
        source_service_token="reverse-unit",
        processing_service_token="forward-unit",
        minio_source_bucket="owned-source",
        minio_output_bucket="owned-output",
        minio_public_endpoint="localhost:4443",
    )


@pytest.fixture
def user():
    return User(id=uuid4(), email="unit@example.com", password_hash="unusable", role="user")


@pytest.fixture
def asset(user):
    return Asset(
        id=uuid4(),
        owner_id=user.id,
        filename="lesson.mp4",
        source_key=f"sources/{user.id}/{uuid4()}/lesson.mp4",
        source_revision=1,
        source_size_bytes=1024,
        source_sha256="a" * 64,
        source_media_type="video/mp4",
        submission_state="submitted",
        processing_job_id=uuid4(),
        operations=[],
        submit_attempts=0,
        created_at=now(),
        next_submit_at=now(),
    )


@pytest.fixture
def job(asset):
    stamp = now()
    return ProcessingJob.model_validate(
        {
            "job_id": asset.processing_job_id,
            "asset_id": asset.id,
            "owner_id": asset.owner_id,
            "status": "queued",
            "source": {
                "asset_id": asset.id,
                "revision": 1,
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "media_type": "video/mp4",
            },
            "current_attempt": {
                "attempt_id": uuid4(),
                "number": 1,
                "state": "queued",
                "queued_at": stamp,
            },
            "outputs": [],
            "created_at": stamp,
            "updated_at": stamp,
        }
    )


@pytest.fixture
def peer():
    return AsyncMock()


@pytest.fixture
def storage():
    mock = AsyncMock()
    mock.source_grant.return_value = (
        "http://minio:9000/owned-source/source?signed=test",
        now() + timedelta(minutes=15),
    )
    mock.sign_output.return_value = "https://localhost:4443/owned-output/output?signed=test"
    return mock


@pytest.fixture
def video():
    return b"\x00\x00\x00\x18ftypisom" + b"video" * 20


@pytest.fixture
def upload_file(video):
    return UploadFile(BytesIO(video), filename="lesson.mp4", headers={"content-type": "video/mp4"})


@pytest.fixture(autouse=True)
def offline_network_guard(monkeypatch):
    """Fast Media tests must not open Internet or local service connections."""
    import socket

    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("fast Media tests attempted a network connection")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
