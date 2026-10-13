"""Fast run isolation checks; real runtime evidence remains the integration gate."""

import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture
def compose_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "selected_docker", lambda *a: (None, "/project/docker"))
    env, state = runtime.configure("release", tmp_path)
    calls = []
    monkeypatch.setattr(runtime, "subprocess_env", lambda: os.environ.copy())
    monkeypatch.setattr(
        runtime.subprocess, "run", lambda command, **kw: calls.append((command, kw))
    )
    return env, state, calls


def compose_files(command):
    return [command[index + 1] for index, part in enumerate(command) if part == "-f"]


@pytest.mark.parametrize("candidate", [False, True])
def test_persisted_image_selection_precedes_explicit_candidate(compose_calls, candidate):
    _, state, calls = compose_calls
    persisted = Path(state["env_file"]).parent / "release.override.json"
    persisted.write_text(json.dumps({"services": {"processing": {"image": "sha256:" + "a" * 64}}}))
    arguments = ("-f", "/candidate.json", "up") if candidate else ("ps",)
    runtime.compose(state, *arguments)
    assert compose_files(calls[0][0]) == [
        str(runtime.COMPOSE),
        str(persisted),
        *(["/candidate.json"] if candidate else []),
    ]


def test_compose_without_release_preserves_default_selection(compose_calls):
    _, state, calls = compose_calls
    runtime.compose(state, "ps", "--all")
    assert compose_files(calls[0][0]) == [str(runtime.COMPOSE)]
    assert calls[0][0][-2:] == ["ps", "--all"]


def test_build_omits_persisted_id_and_uses_fresh_nonsecret_labels(compose_calls, monkeypatch):
    project, state, calls = compose_calls
    env_file = Path(state["env_file"])
    original = env_file.read_bytes()
    persisted = env_file.parent / "release.override.json"
    immutable = "sha256:" + "b" * 64
    persisted.write_text(json.dumps({"services": {"processing": {"image": immutable}}}))
    monkeypatch.setenv("DC2_PROCESSING_IMAGE", immutable)
    monkeypatch.setenv("MEDIA_JWT_SECRET", "ambient-secret")
    monkeypatch.setenv("DC2_BUILD_REVISION", "stale-head")
    roots = []

    def labels(root):
        roots.append(root)
        return {
            "DC2_BUILD_REVISION": "current-head",
            "DC2_BUILD_SOURCE_FINGERPRINT": "current-hash",
        }

    monkeypatch.setattr(runtime, "build_labels", labels)
    runtime.compose(state, "build", "processing", "media")
    command, options = calls[0]
    assert compose_files(command) == [str(runtime.COMPOSE)]
    assert immutable not in command
    assert "DC2_PROCESSING_IMAGE" not in options["env"]
    assert project["DC2_PROCESSING_IMAGE"].startswith("dc2-processing:")
    assert roots == [Path(project["DC2_ROOT"])]
    assert "MEDIA_JWT_SECRET" not in options["env"]
    assert options["env"]["DC2_BUILD_REVISION"] == "current-head"
    assert env_file.read_bytes() == original


@pytest.mark.parametrize("key", ["DC2_PROCESSING_IMAGE", "DC2_MEDIA_IMAGE", "DC2_MINIO_IMAGE"])
@pytest.mark.parametrize("reference", ["sha256:" + "c" * 64, "example@sha256:" + "c" * 64])
def test_build_refuses_immutable_configured_image(compose_calls, key, reference):
    _, state, calls = compose_calls
    path = Path(state["env_file"])
    project = runtime.read_env(path)
    project[key] = reference
    path.write_text("".join(f"{name}={value}\n" for name, value in project.items()))
    with pytest.raises(ValueError, match="mutable image tags"):
        runtime.compose(state, "build", "processing")
    assert not calls


def test_build_refuses_explicit_image_override(compose_calls):
    _, state, calls = compose_calls
    with pytest.raises(ValueError, match="without image overrides"):
        runtime.compose(state, "-f", "/candidate.json", "build", "processing")
    assert not calls


@pytest.mark.parametrize("dirty", ["clean", "modified", "staged", "untracked"])
def test_bootstrap_labels_match_runner_index_hash_and_mark_dirty(tmp_path, dirty):
    from scripts.dev.release import PRODUCT_PATHS

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout

    git("init", "-q")
    source = tmp_path / "processing/café.py"
    source.parent.mkdir()
    source.write_text("value = 1\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Offline Test",
        "-c",
        "user.email=offline@example.com",
        "commit",
        "-qm",
        "base",
    )
    if dirty in ("modified", "staged"):
        source.write_text("value = 2\n")
        if dirty == "staged":
            git("add", ".")
    elif dirty == "untracked":
        (source.parent / "new.py").write_text("value = 3\n")
    tree = git("ls-files", "-s", "--", *PRODUCT_PATHS)
    assert tree.endswith("\n")
    prefix = "" if dirty == "clean" else "dirty:"
    assert runtime.build_labels(tmp_path) == {
        "DC2_BUILD_REVISION": prefix + git("rev-parse", "HEAD").strip(),
        "DC2_BUILD_SOURCE_FINGERPRINT": prefix + hashlib.sha256(tree.encode("utf-8")).hexdigest(),
        "DC2_BUILD_SOURCE_STATE": "clean" if dirty == "clean" else "dirty",
    }


@pytest.mark.parametrize("action", ["up", "images"])
@pytest.mark.parametrize("pending", [{"previous": "sha256:" + "d" * 64}, {}])
def test_pending_recovery_refuses_start_and_build(compose_calls, monkeypatch, action, pending):
    project, state, calls = compose_calls
    directory = Path(state["env_file"]).parent / "releases"
    directory.mkdir()
    (directory / "journal.json").write_text(json.dumps({"pending": pending}))
    monkeypatch.setattr(runtime, "configure", lambda run_id: (project, state))
    monkeypatch.setattr(runtime, "fetch_minio", lambda: pytest.fail("must not fetch/build"))
    assert runtime.main([action, "--run-id", "release"]) == 1
    assert not calls


@pytest.mark.parametrize("action", ["up", "down", "images"])
def test_runtime_actions_contend_with_release_runner_lock(tmp_path, monkeypatch, action):
    from scripts.dev.release import Runner

    monkeypatch.setattr(runtime, "selected_docker", lambda *a: (None, "/project/docker"))
    project, state = runtime.configure("release", tmp_path)
    runner = Runner("release", root=tmp_path)
    monkeypatch.setattr(runtime, "configure", lambda run_id: (project, state))
    monkeypatch.setattr(runtime, "compose", lambda *a: pytest.fail("must not mutate"))
    monkeypatch.setattr(runtime, "fetch_minio", lambda: pytest.fail("must not fetch/build"))
    with runner.locked():
        assert runtime.main([action, "--run-id", "release"]) == 1
    # Closing either entry point releases the OS lock for the other.
    with runtime.runtime_lock(state):
        with pytest.raises(Exception, match="another release runner"):
            with runner.locked():
                pytest.fail("release must not acquire runtime's lock")
    with runner.locked():
        pass


def test_release_compose_does_not_double_lock_or_block_pending(tmp_path, monkeypatch):
    from scripts.dev import release

    monkeypatch.setattr(runtime, "selected_docker", lambda *a: (None, "/project/docker"))
    runner = release.Runner("release", root=tmp_path)
    runner.operation = {"id": "offline"}
    runner.journal["pending"] = {"previous": "sha256:" + "e" * 64}
    runner.save()
    runner.persisted.write_text(json.dumps(release.override("sha256:" + "e" * 64)))
    calls = []
    monkeypatch.setattr(release.runtime, "subprocess_env", lambda: {})
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kw: calls.append(command) or SimpleNamespace(stdout="ok"),
    )
    monkeypatch.setattr(runner, "remaining", lambda cap: 10)
    with runner.locked():
        assert runner.compose("up", image="sha256:" + "f" * 64) == "ok"
    assert compose_files(calls[0]) == [
        str(release.runtime.COMPOSE),
        str(runner.persisted),
        str(runner.persisted),
        str(runner.directory / "offline.override.json"),
    ]


@pytest.mark.parametrize("released", [False, True])
def test_normal_up_preserves_bootstrap_defaults_and_freezes_released_selection(
    compose_calls, monkeypatch, released
):
    project, state, calls = compose_calls
    root = Path(project["DC2_ROOT"])
    monkeypatch.setattr(runtime, "ROOT", root)
    tls = root / "scripts/dev/tls.py"
    tls.parent.mkdir(parents=True)
    tls.touch()
    directory = Path(state["env_file"]).parent
    (directory / "tls").mkdir()
    for name in ("ca.crt", "server.crt", "server.key"):
        (directory / "tls" / name).touch()
    if released:
        (directory / "release.override.json").write_text(
            json.dumps({"services": {"processing": {"image": "sha256:" + "a" * 64}}})
        )
    monkeypatch.setattr(runtime, "configure", lambda run_id: (project, state))
    monkeypatch.setattr(
        runtime,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=json.dumps({"NCPU": 8, "MemTotal": 8 * 2**30})),
    )
    monkeypatch.setattr(runtime, "fetch_minio", lambda: None)
    monkeypatch.delenv("DC2_USE_PREBUILT_MINIO", raising=False)
    monkeypatch.setattr(runtime, "build_labels", lambda root: {"DC2_BUILD_REVISION": "dirty:head"})

    def smoke(state):
        fd = os.open(directory / "releases/runner.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    monkeypatch.setattr(runtime, "smoke", smoke)
    assert runtime.main(["up", "--run-id", "release"]) == 0
    build, up = [command for command, options in calls]
    assert build[-4:] == ["build", "minio", "processing", "media"]
    assert compose_files(build) == [str(runtime.COMPOSE)]
    if released:
        assert "--no-build" in up and up[up.index("--pull") + 1] == "never"
    else:
        assert up[-5:] == ["up", "-d", "--wait", "--wait-timeout", "180"]
        assert "--no-build" not in up and "--pull" not in up
    assert compose_files(up) == [
        str(runtime.COMPOSE),
        *([str(directory / "release.override.json")] if released else []),
    ]


def test_down_allows_pending_without_removing_data(compose_calls, monkeypatch):
    project, state, calls = compose_calls
    directory = Path(state["env_file"]).parent / "releases"
    directory.mkdir()
    (directory / "journal.json").write_text(json.dumps({"pending": {"previous": "retained"}}))
    monkeypatch.setattr(runtime, "configure", lambda run_id: (project, state))
    assert runtime.main(["down", "--run-id", "release"]) == 0
    assert calls[0][0][-1] == "down" and "-v" not in calls[0][0]


def test_images_keeps_lock_until_build_failure_and_then_releases(compose_calls, monkeypatch):
    _, state, calls = compose_calls

    def failed_build(state):
        with pytest.raises(ValueError, match="owns this run-id"):
            with runtime.runtime_lock(state):
                pytest.fail("build must retain the lock")
        raise ValueError("build failed")

    monkeypatch.setattr(runtime, "_images", failed_build)
    with pytest.raises(ValueError, match="build failed"):
        runtime.images(state)
    with runtime.runtime_lock(state):
        pass
    assert not calls


@pytest.mark.parametrize("journal", ["broken-json", "[]"])
def test_unreadable_recovery_state_fails_closed(compose_calls, monkeypatch, journal):
    project, state, calls = compose_calls
    directory = Path(state["env_file"]).parent / "releases"
    directory.mkdir()
    (directory / "journal.json").write_text(journal)
    monkeypatch.setattr(runtime, "configure", lambda run_id: (project, state))
    assert runtime.main(["up", "--run-id", "release"]) == 1
    assert not calls
