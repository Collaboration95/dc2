"""Tooling contracts: preserve secrets, reject stale evidence and fail unavailable tiers."""

import json
import socket
import sys
import tomllib
from pathlib import Path

import pytest
from coverage import Coverage

from scripts.dev import checks, common, coverage, setup


def test_setup_preserves_existing_env_and_permissions(tmp_path):
    existing = tmp_path / ".env"
    existing.write_text("JWT_SECRET=configured-by-owner\n")
    existing.chmod(0o600)
    (tmp_path / ".env.example").write_text("JWT_SECRET=example\n")
    assert not setup.preserve_env(tmp_path)
    assert existing.read_text() == "JWT_SECRET=configured-by-owner\n"
    assert existing.stat().st_mode & 0o777 == 0o600


def test_setup_creates_private_env_once(tmp_path):
    (tmp_path / ".env.example").write_text("LOCAL_EXAMPLE=1\n")
    assert setup.preserve_env(tmp_path)
    assert not setup.preserve_env(tmp_path)
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_setup_preserves_env_symlink(tmp_path):
    target = tmp_path / "configured"
    target.write_text("owner-configured")
    (tmp_path / ".env").symlink_to(target)
    assert not setup.preserve_env(tmp_path)
    assert target.read_text() == "owner-configured"


def test_caches_and_environment_remain_worktree_local(tmp_path, monkeypatch):
    monkeypatch.setenv("UV_CACHE_DIR", "/global/cache")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/other/venv")
    env = common.local_env(tmp_path)
    for key in (
        "UV_CACHE_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON_INSTALL_DIR",
        "npm_config_cache",
        "PLAYWRIGHT_BROWSERS_PATH",
        "RUFF_CACHE_DIR",
    ):
        assert Path(env[key]).is_relative_to(tmp_path)
    assert env["UV_PYTHON_DOWNLOADS"] == "never"


def test_future_packages_enter_selection_and_fingerprint(tmp_path):
    (tmp_path / "media").mkdir()
    source = tmp_path / "media/client.py"
    source.write_text("first = 1\n")
    assert common.packages(tmp_path) == ["media"]
    first = common.fingerprint(tmp_path)
    source.write_text("first = 2\n")
    assert common.fingerprint(tmp_path) != first


def test_fast_tier_blocks_real_socket_connection():
    with socket.socket() as client:
        with pytest.raises(AssertionError, match="forbids network"):
            client.connect(("127.0.0.1", 1))


def test_fast_tier_discards_ambient_live_configuration(monkeypatch):
    monkeypatch.setenv("RUN_POSTGRES_TESTS", "1")
    monkeypatch.setenv("RUN_LIVE_TESTS", "1")
    monkeypatch.setenv("PROCESSING_SERVICE_TOKEN", "ambient-secret")
    assert "RUN_POSTGRES_TESTS" not in checks.fast_env()
    assert "RUN_LIVE_TESTS" not in checks.fast_env()
    assert "PROCESSING_SERVICE_TOKEN" not in checks.fast_env()


def test_explicit_integration_cannot_return_success_when_disabled(monkeypatch):
    monkeypatch.delenv("RUN_POSTGRES_TESTS", raising=False)
    monkeypatch.delenv("RUN_PROCESSING_TESTS", raising=False)
    monkeypatch.delenv("RUN_MEDIA_TESTS", raising=False)
    with pytest.raises(SystemExit, match="Integration is opt-in"):
        checks.integration()


@pytest.mark.parametrize("name", ["POSTGRES_DSN", "PROCESSING_POSTGRES_DSN"])
def test_enabled_integration_requires_explicit_resource_configuration(name, monkeypatch):
    monkeypatch.delenv("RUN_POSTGRES_TESTS", raising=False)
    monkeypatch.delenv("RUN_PROCESSING_TESTS", raising=False)
    monkeypatch.delenv("RUN_MEDIA_TESTS", raising=False)
    monkeypatch.setenv(
        "RUN_POSTGRES_TESTS" if name == "POSTGRES_DSN" else "RUN_PROCESSING_TESTS", "1"
    )
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match=name):
        checks.integration()


def test_coverage_combined_rate_is_distinct_from_raw_branch_rate():
    combined, branch = coverage.rates(
        dict(num_statements=90, covered_lines=90, num_branches=10, covered_branches=0)
    )
    assert combined == 90
    assert branch == 0


def test_v1_coverage_rc_uses_the_pyproject_source_and_omit_policy():
    from configparser import ConfigParser
    from io import StringIO

    from scripts.dev import v1_verify

    parser = ConfigParser()
    parser.read_file(StringIO(v1_verify.coverage_rc()))
    configured = tomllib.loads((common.ROOT / "pyproject.toml").read_text())
    assert parser["run"]["omit"].split() == configured["tool"]["coverage"]["run"]["omit"]
    assert "scripts.aws.v1.bootstrap" in parser["run"]["source"].split()


def test_package_coverage_totals_exclude_migrations_from_the_denominator():
    files = {
        "processing/migrations/versions/001.py": {
            "summary": {
                "num_statements": 10,
                "num_branches": 2,
                "covered_lines": 10,
                "covered_branches": 2,
            }
        },
        "processing/recovery_v1.py": {
            "summary": {
                "num_statements": 4,
                "num_branches": 2,
                "covered_lines": 3,
                "covered_branches": 1,
            }
        },
    }
    assert coverage.package_totals(files, "processing") == {
        "num_statements": 4,
        "num_branches": 2,
        "covered_lines": 3,
        "covered_branches": 1,
    }


def test_bootstrap_report_is_a_separate_measured_file():
    summary = {"num_statements": 10, "num_branches": 4, "covered_lines": 9, "covered_branches": 3}
    result = coverage.file_report(
        {"scripts/aws/v1/bootstrap.py": {"summary": summary}}, "scripts/aws/v1/bootstrap.py"
    )
    assert result["status"] == "MEASURED"
    assert result["combined"] == 85.71428571428571
    assert result["raw_branch"] == 75


def test_coverage_goals_require_both_combined_and_raw_branch_targets():
    target = {"combined": 90, "raw_branch": 85}
    met = coverage.goal_report({"combined": 91, "raw_branch": 85}, target)
    below = coverage.goal_report({"combined": 95, "raw_branch": 84.9}, target)
    assert met["status"] == "MET"
    assert below["status"] == "BELOW_GOAL"


def test_coverage_rejects_tiers_with_different_omit_settings(tmp_path, monkeypatch):
    data = tmp_path / ".coverage.fast"
    data.write_bytes(b"unused")
    data.with_suffix(data.suffix + ".json").write_text(
        json.dumps(
            {"fingerprint": "current", "tier": "fast", "omit": ["processing/recovery_v1.py"]}
        )
    )
    monkeypatch.setattr(coverage, "fingerprint", lambda: "current")
    monkeypatch.setattr(sys, "argv", ["coverage", "--data", str(data)])
    with pytest.raises(SystemExit, match="Coverage omit mismatch"):
        coverage.main()


def test_coverage_cannot_pass_by_measuring_only_another_package():
    with pytest.raises(ValueError, match="No coverage files"):
        coverage.package_totals({"app/empty.py": {"summary": {}}}, "processing")


def test_coverage_rejects_stale_data(tmp_path, monkeypatch):
    data = tmp_path / ".coverage.fast"
    data.write_bytes(b"unused")
    data.with_suffix(data.suffix + ".json").write_text(
        json.dumps({"fingerprint": "old", "tier": "fast"})
    )
    monkeypatch.setattr(coverage, "fingerprint", lambda: "new")
    monkeypatch.setattr(sys, "argv", ["coverage", "--data", str(data)])
    with pytest.raises(SystemExit, match="Stale coverage evidence"):
        coverage.main()


def test_coverage_includes_never_imported_production_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").touch()
    executed = package / "executed.py"
    executed.write_text("answer = 42\n")
    (package / "unexecuted.py").write_text("a = 1\nb = 2\nc = 3\n")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.coverage.run]\nbranch = true\nrelative_files = true\nsource = ["app"]\n'
    )
    data = tmp_path / ".coverage.fast"
    measured = Coverage(data_file=str(data), config_file=str(tmp_path / "pyproject.toml"))
    measured.start()
    exec(compile(executed.read_text(), str(executed), "exec"), {})
    measured.stop()
    measured.save()
    data.with_suffix(data.suffix + ".json").write_text(
        json.dumps(
            {
                "fingerprint": "current",
                "tier": "fast",
                "omit": common.coverage_omit_patterns(tmp_path),
            }
        )
    )
    monkeypatch.setattr(coverage, "ROOT", tmp_path)
    monkeypatch.setattr(coverage, "packages", lambda: ["app"])
    monkeypatch.setattr(coverage, "fingerprint", lambda: "current")
    monkeypatch.setattr(sys, "argv", ["coverage", "--data", str(data)])
    with pytest.raises(SystemExit, match="Coverage below 80%"):
        coverage.main()
    files = json.loads((tmp_path / "artifacts/coverage/backend.json").read_text())["files"]
    assert files["app/unexecuted.py"]["summary"]["covered_lines"] == 0
    assert files["app/unexecuted.py"]["summary"]["num_statements"] == 3


def test_clean_preserves_secrets_and_external_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("secret")
    (tmp_path / ".venv").mkdir()
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (tmp_path / ".pytest_cache").symlink_to(outside)
    with pytest.raises(SystemExit, match="Refusing to clean symlink"):
        checks.clean()
    assert (outside / "keep").read_text() == "keep"
    assert (tmp_path / ".env").read_text() == "secret"
    assert (tmp_path / ".venv").exists()


def test_integration_selection_tracks_service_ownership(tmp_path, monkeypatch):
    directory = tmp_path / "tests/integration"
    directory.mkdir(parents=True)
    for name in (
        "test_processing_worker.py",
        "test_processing_intake.py",
        "test_media_assets.py",
        "test_jobs.py",
    ):
        (directory / name).touch()
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    assert checks.service_tests("processing") == [
        "tests/integration/test_processing_intake.py",
        "tests/integration/test_processing_worker.py",
        "tests/integration/test_database_ownership.py",
    ]
    assert checks.service_tests("media") == ["tests/integration/test_media_assets.py"]


def selection_of(monkeypatch, *, coverage):
    seen = {}
    monkeypatch.setattr(checks, "run", lambda command, **kwargs: seen.update(command=command))
    monkeypatch.setattr(checks, "measure", lambda command, *a: seen.update(command=command))
    checks.fast(coverage=coverage)
    command = seen["command"]
    return command[len(command) - 1 - command[::-1].index("-m") + 1]


def test_coverage_run_skips_unmeasured_tests_but_the_plain_fast_run_keeps_them(monkeypatch):
    assert "unmeasured" in selection_of(monkeypatch, coverage=True)
    assert "unmeasured" not in selection_of(monkeypatch, coverage=False)
