"""The finite worker exits with its usual codes but now says which setting is wrong."""

import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError

from processing.config import Settings
from processing.worker import sqs

DSN = "postgresql://worker:hunter2@db.example.internal:5432/processing"


def run_main(monkeypatch, deadline=300):
    monkeypatch.setattr(
        sys, "argv", ["sqs", "--deadline", str(time.time() + deadline), "--name", "task"]
    )
    with pytest.raises(SystemExit) as exit_:
        sqs.main()
    return exit_.value.code


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("PROCESSING_POSTGRES_DSN", "PROCESSING_WORK_QUEUE_URL", "WORK_QUEUE_URL"):
        monkeypatch.delenv(name, raising=False)
    sqs.get_settings.cache_clear()
    yield
    sqs.get_settings.cache_clear()


def test_a_missing_dsn_names_the_setting_and_exits_one(monkeypatch, capsys):
    assert run_main(monkeypatch) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "PROCESSING_POSTGRES_DSN" in err


def test_an_invalid_setting_is_named_without_its_value(monkeypatch, capsys):
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", DSN)
    monkeypatch.setenv("PROCESSING_LEASE_SECONDS", "not-a-number-hunter2")
    assert run_main(monkeypatch) == 1
    err = capsys.readouterr().err
    assert "PROCESSING_LEASE_SECONDS" in err
    assert "hunter2" not in err and "db.example.internal" not in err


def test_a_missing_queue_url_is_named_and_exits_one(monkeypatch, capsys):
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", DSN)
    monkeypatch.setenv("PROCESSING_MINIO_ACCESS_KEY", "key")
    monkeypatch.setenv("PROCESSING_MINIO_SECRET_KEY", "secret")
    assert run_main(monkeypatch) == 1
    assert "PROCESSING_WORK_QUEUE_URL" in capsys.readouterr().err


def test_an_expired_deadline_still_exits_124_without_a_config_message(monkeypatch, capsys):
    assert run_main(monkeypatch, deadline=-5) == 124
    assert capsys.readouterr().err == ""


def test_an_unexpected_failure_stays_silent_and_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(sqs, "async_main", AsyncMock(side_effect=RuntimeError(DSN)))
    assert run_main(monkeypatch) == 1
    assert capsys.readouterr().err == ""


def refusal():
    return DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate="28P01"))


class FakeEngine:
    def __init__(self, error):
        self.error, self.disposed = error, False

    def connect(self):
        return self

    async def __aenter__(self):
        if self.error:
            raise self.error
        return SimpleNamespace(execute=AsyncMock())

    async def __aexit__(self, *_):
        return False

    async def dispose(self):
        self.disposed = True


def stub_engines(monkeypatch, errors):
    engines = [FakeEngine(error) for error in errors]
    monkeypatch.setattr(sqs, "create_async_engine", lambda *a, **k: engines.pop(0))
    monkeypatch.setattr(sqs, "load_configuration", lambda: (Settings(postgres_dsn=DSN), "q"))
    return engines


async def test_a_login_refusal_at_startup_rereads_settings_once_then_connects(monkeypatch):
    engines = stub_engines(monkeypatch, [refusal(), None])
    first = Settings(postgres_dsn=DSN)
    settings, engine = await sqs.connect_engine(first)
    assert settings is not first and engine.error is None and engines == []


async def test_a_second_login_refusal_fails_with_a_sanitized_message(monkeypatch):
    stub_engines(monkeypatch, [refusal(), refusal()])
    with pytest.raises(sqs.WorkerConfigurationError) as caught:
        await sqs.connect_engine(Settings(postgres_dsn=DSN))
    assert "hunter2" not in str(caught.value) and "db.example" not in str(caught.value)


async def test_another_startup_database_error_does_not_reread_settings(monkeypatch):
    engines = stub_engines(monkeypatch, [OSError("network"), None])
    settings = Settings(postgres_dsn=DSN)
    returned, _ = await sqs.connect_engine(settings)
    assert returned is settings and len(engines) == 1
