"""Project-local paths and bounded command execution; no global installation."""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/bin/python"
PACKAGE_NAMES = (
    "app", "processing", "media", "media_engine", "publisher",
    "contracts", "delivery", "runtime_support",
)


def packages(root: Path = ROOT) -> list[str]:
    return [name for name in PACKAGE_NAMES if (root / name).is_dir()]


def local_env(root: Path = ROOT) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        UV_CACHE_DIR=str(root / ".cache/uv"),
        UV_PYTHON_INSTALL_DIR=str(root / ".local/uv/python"),
        UV_PROJECT_ENVIRONMENT=str(root / ".venv"),
        UV_PYTHON_DOWNLOADS="never",
        npm_config_cache=str(root / ".cache/npm"),
        RUFF_CACHE_DIR=str(root / ".cache/ruff"),
        PLAYWRIGHT_BROWSERS_PATH=str(root / ".local/playwright"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def run(command, *, label: str, timeout: int, env=None, cwd: Path = ROOT) -> None:
    print(f"[{label}] {' '.join(map(str, command))}", flush=True)
    start = time.monotonic()
    status = 1
    try:
        result = subprocess.run(command, cwd=cwd, env=env or local_env(), timeout=timeout)
        status = result.returncode
        if status:
            raise SystemExit(status)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"{label} exceeded {timeout}s; no retry was attempted") from exc
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing {command[0]}; run make setup or make doctor") from exc
    finally:
        elapsed = round(time.monotonic() - start, 3)
        print(f"[{label}] {elapsed:.3f}s, exit {status}", flush=True)
        path = ROOT / "artifacts/tooling/timings.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            stream.write(json.dumps(dict(label=label, seconds=elapsed, exit_code=status)) + "\n")


def fingerprint(root: Path = ROOT) -> str:
    """Reject evidence from different product, test, lock or tooling contents."""
    files = [root / "pyproject.toml", root / "uv.lock", root / "frontend/package-lock.json"]
    for directory in (
        *packages(root),
        "tests",
        "scripts/dev",
        "scripts/aws",
        "migrations",
        "frontend",
    ):
        files.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".js", ".html", ".mjs"}
            and not any(part in {"node_modules", "coverage", "__pycache__"} for part in p.parts)
        )
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if path.exists():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
