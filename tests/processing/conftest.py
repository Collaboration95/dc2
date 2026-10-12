import os
from uuid import uuid4

import pytest


@pytest.fixture
def submission():
    asset_id = str(uuid4())
    return {
        "asset_id": asset_id,
        "owner_id": str(uuid4()),
        "source": {
            "asset_id": asset_id,
            "revision": 1,
            "sha256": "a" * 64,
            "size_bytes": 1234,
            "media_type": "video/mp4",
        },
        "source_url": "https://media.test/internal/source?signature=temporary",
        "source_url_expires_at": "2026-10-13T00:00:00Z",
    }


@pytest.fixture(autouse=True)
def isolate_processing_configuration(monkeypatch):
    """Fast tests cannot inherit a developer's live queue/storage credentials."""
    from processing.config import get_settings

    for name in list(os.environ):
        if name.startswith("PROCESSING_"):
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
