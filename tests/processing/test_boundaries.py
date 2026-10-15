import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from processing.config import Settings, get_settings
from processing.database import Base
from processing.messaging_models import (
    AttemptTask,
    JobMessaging,
    ProcessingInbox,
    ProcessingOutbox,
)
from processing.models import Attempt, Job, SubmissionGuard

ROOT = Path(__file__).resolve().parents[2]


def test_settings_use_only_processing_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://media:private@media/media_db")
    monkeypatch.setenv("SERVICE_TOKEN", "media-secret")
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", "postgres://processing@processing/processing_db")
    monkeypatch.setenv("PROCESSING_SERVICE_TOKEN", "processing-secret")
    monkeypatch.setenv("PROCESSING_MIGRATION_DSN", "postgresql://migrator@processing/processing_db")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.postgres_dsn == "postgresql+asyncpg://processing@processing/processing_db"
        assert settings.migration_dsn == "postgresql+asyncpg://migrator@processing/processing_db"
        assert settings.service_token.get_secret_value() == "processing-secret"
        assert "processing-secret" not in repr(settings)
        assert get_settings() is settings
    finally:
        get_settings.cache_clear()


def test_dsn_is_required_and_no_mm_fallback(monkeypatch):
    monkeypatch.delenv("PROCESSING_POSTGRES_DSN", raising=False)
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://media@media/media_db")
    with pytest.raises(ValidationError):
        Settings()


def test_non_postgres_dsn_rejected():
    with pytest.raises(ValidationError):
        Settings(postgres_dsn="sqlite:///processing.db")


def test_models_have_only_processing_tables_and_foreign_keys():
    assert set(Base.metadata.tables) == {
        "jobs",
        "attempts",
        "submission_guards",
        "retry_requests",
        "cleanup_intents",
        "message_inbox",
        "message_outbox",
        "job_messaging",
        "attempt_tasks",
    }
    assert all(
        model.metadata is Base.metadata
        for model in (
            Job,
            Attempt,
            SubmissionGuard,
            JobMessaging,
            ProcessingInbox,
            ProcessingOutbox,
            AttemptTask,
        )
    )
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.metadata is Base.metadata
            assert fk.column.table.name in {"jobs", "attempts"}
        if "owner_id" in table.c:
            assert not table.c.owner_id.foreign_keys
    assert not SubmissionGuard.__table__.c.asset_id.foreign_keys
    assert not Job.__table__.c.asset_id.foreign_keys


def test_import_without_app_worker_or_infrastructure_configuration():
    # A fresh process prevents the inherited root conftest's app imports from
    # hiding an accidental dependency. Import hooks fail before any app runs.
    script = """
import importlib.abc
import sys
class RejectInherited(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'app', 'rq', 'redis', 'minio'}:
            raise AssertionError('Inherited dependency: ' + fullname)
sys.meta_path.insert(0, RejectInherited())
from processing.main import app
from processing.models import Job, Attempt, SubmissionGuard
assert app.title == 'FlickPond Processing private API'
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PROCESSING_")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_independent_migration_paths_and_offline_history(tmp_path):
    env = {
        **os.environ,
        "PROCESSING_POSTGRES_DSN": "postgresql://runtime@unused/runtime_db",
        "PROCESSING_MIGRATION_DSN": "postgresql://migrator@unused/processing_db",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "processing/alembic.ini"),
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    for name in ("jobs", "attempts", "submission_guards"):
        assert f"CREATE TABLE {name}" in result.stdout
    assert "processing_0001" in result.stdout
    assert "DEFERRABLE INITIALLY DEFERRED" in result.stdout
    assert "CREATE TABLE users" not in result.stdout
