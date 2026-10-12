"""Fast tests cannot contact services; explicitly enabled integration cannot skip."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_fast_tests(monkeypatch, pytestconfig):
    if not pytestconfig.getoption("--offline-fast"):
        return

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Fast tier forbids network access; mock the boundary or use integration"
        )

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    # Settings tests must not inherit secrets or defaults from a configured .env.
    from app.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)


def pytest_addoption(parser):
    parser.addoption("--offline-fast", action="store_true")
    parser.addoption("--require-integration", action="store_true")


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--require-integration"):
        terminal = session.config.pluginmanager.getplugin("terminalreporter")
        skipped = terminal.stats.get("skipped", []) if terminal else []
        if skipped:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            if terminal:
                terminal.write_sep(
                    "!", "Explicit integration requires every selected test; skips fail"
                )
