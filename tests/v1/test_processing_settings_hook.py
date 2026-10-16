import sys
from types import ModuleType
from unittest.mock import Mock

from processing.config import get_settings


def test_owned_runtime_secret_overrides_local_dsn_without_media_settings(monkeypatch):
    runtime = ModuleType("runtime_support")
    support = ModuleType("runtime_support.settings")
    support.runtime_values = Mock(
        return_value={"postgres_dsn": "postgresql://owned@unused/processing_db"}
    )
    monkeypatch.setitem(sys.modules, "runtime_support", runtime)
    monkeypatch.setitem(sys.modules, "runtime_support.settings", support)
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", "postgresql://local@unused/processing_local")
    monkeypatch.setenv("MEDIA_POSTGRES_DSN", "postgresql://media@unused/media_db")
    get_settings.cache_clear()
    try:
        value = get_settings()
        assert value.postgres_dsn == "postgresql+asyncpg://owned@unused/processing_db"
        assert get_settings() is value
        support.runtime_values.assert_called_once_with("PROCESSING")
    finally:
        get_settings.cache_clear()
