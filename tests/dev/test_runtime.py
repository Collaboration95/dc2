"""Fast run isolation checks; real runtime evidence remains the integration gate."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dc2_runtime", ROOT / "scripts/dev/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_run_configuration_is_idempotent_and_private(tmp_path):
    env, state = runtime.configure("one", tmp_path)
    path = Path(state["env_file"])
    with path.open("a") as handle:
        handle.write("CUSTOM_SETTING=keep-this\n")
    original = path.read_bytes()
    again, second = runtime.configure("one", tmp_path)
    assert again["MEDIA_JWT_SECRET"] == env["MEDIA_JWT_SECRET"]
    assert again["CUSTOM_SETTING"] == "keep-this"
    assert path.read_bytes() == original
    assert second == state
    assert path.stat().st_mode & 0o777 == 0o600
    assert set(state) == {
        "docker_host",
        "docker_config",
        "public_url",
        "postgres_port",
        "processing_port",
        "ca_file",
        "compose_project",
        "env_file",
    }
    serialized = json.dumps(state)
    for key, value in env.items():
        if "PASSWORD" in key or "TOKEN" in key or "SECRET" in key:
            assert value not in serialized


def test_runs_and_worktrees_are_isolated(tmp_path):
    first, a = runtime.configure("one", tmp_path)
    second, b = runtime.configure("two", tmp_path)
    third, c = runtime.configure("one", tmp_path / "other-worktree")
    for key in ("compose_project", "env_file"):
        assert len({a[key], b[key], c[key]}) == 3
    ports = [s[key] for s in (a, b) for key in ("postgres_port", "processing_port")]
    ports += [int(s["public_url"].rsplit(":", 1)[1]) for s in (a, b)]
    assert len(set(ports)) == 6
    for key in (
        "DC2_PROCESSING_IMAGE",
        "DC2_MINIO_IMAGE",
        "SOURCE_BUCKET",
        "OUTPUT_BUCKET",
        "PROCESSING_QUEUE_NAME",
        "MEDIA_JWT_SECRET",
    ):
        assert len({first[key], second[key], third[key]}) == 3
    assert first["MEDIA_SOURCE_SERVICE_TOKEN"] == first["PROCESSING_SOURCE_SERVICE_TOKEN"]
    assert first["MEDIA_PROCESSING_SERVICE_TOKEN"] == first["PROCESSING_SERVICE_TOKEN"]
    assert "MEDIA_S3" not in first["PROCESSING_MINIO_ACCESS_KEY"]


@pytest.mark.parametrize("run_id", ["../escape", "Upper", "", "a" * 41, "a/b"])
def test_invalid_id_rejected(tmp_path, run_id):
    with pytest.raises(ValueError):
        runtime.configure(run_id, tmp_path)
    assert not (tmp_path / ".local").exists()


def test_daemon_override_is_subprocess_only(monkeypatch):
    monkeypatch.setenv("DOCKER_CONTEXT", "unrelated")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DC2_DOCKER_HOST", "unix:///project/docker.sock")
    monkeypatch.setenv("DC2_DOCKER_CONFIG", "/project/docker-config")
    env = runtime.subprocess_env()
    assert env["DOCKER_HOST"] == "unix:///project/docker.sock"
    assert env["DOCKER_CONFIG"] == "/project/docker-config"
    assert "DOCKER_CONTEXT" not in env and "DOCKER_TLS_VERIFY" not in env
    assert os.environ["DOCKER_CONTEXT"] == "unrelated"


def test_compose_does_not_use_caller_secrets(tmp_path, monkeypatch):
    _, state = runtime.configure("one", tmp_path)
    monkeypatch.setenv("POSTGRES_PASSWORD", "unrelated-secret")
    calls = []
    monkeypatch.setattr(runtime, "selected_docker", lambda: (None, "/project/docker"))
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    runtime.compose(state, "down")
    command = calls[0][0][0]
    assert "--env-file" in command and state["env_file"] in command
    assert "-p" in command and state["compose_project"] in command
    assert "-v" not in command
    assert "POSTGRES_PASSWORD" not in calls[0][1]["env"]


def test_cli_help_contract():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev/runtime.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    for action in runtime.ACTIONS:
        assert action in result.stdout
    assert "--run-id" in result.stdout


@pytest.mark.parametrize("healthy", [True, False])
def test_project_vm_selection_checks_health_and_stays_scoped(tmp_path, monkeypatch, healthy):
    from types import SimpleNamespace

    for key in ("DC2_DOCKER_HOST", "DOCKER_HOST", "DC2_DOCKER_CONFIG", "DOCKER_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    monkeypatch.setattr(runtime, "common_root", lambda root: tmp_path)
    monkeypatch.setattr(Path, "is_socket", lambda path: True)
    calls = []

    def probe(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0 if healthy else 1)

    monkeypatch.setattr(runtime.subprocess, "run", probe)
    host, config = runtime.selected_docker(tmp_path)
    if healthy:
        assert host == "unix://" + str(tmp_path / ".local/lima/d/sock/docker.sock")
        assert config == str(tmp_path / ".local/docker")
    else:
        assert host is None
    assert "DOCKER_CONTEXT" not in calls[0]["env"]
    assert os.environ["DOCKER_CONTEXT"] == "desktop-linux"


@pytest.mark.parametrize("revision,accepted", [(runtime.MINIO_COMMIT, True), ("wrong", False)])
def test_prebuilt_storage_requires_pinned_revision(tmp_path, monkeypatch, revision, accepted):
    from types import SimpleNamespace

    _, state = runtime.configure("cached", tmp_path)
    monkeypatch.setenv("DC2_USE_PREBUILT_MINIO", "1")
    monkeypatch.setattr(runtime, "fetch_minio", lambda: None)
    monkeypatch.setattr(
        runtime,
        "run",
        lambda *a, **kw: SimpleNamespace(
            stdout=json.dumps(
                [{"Config": {"Labels": {"org.opencontainers.image.revision": revision}}}]
            )
        ),
    )
    builds = []
    monkeypatch.setattr(runtime, "compose", lambda state, *parts: builds.append(parts))
    if accepted:
        runtime.images(state)
        assert builds == [("build", "processing", "media")]
    else:
        with pytest.raises(ValueError, match="pinned source"):
            runtime.images(state)
        assert builds == []
