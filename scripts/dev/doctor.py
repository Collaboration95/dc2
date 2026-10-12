"""Read-only prerequisite checks; optional infrastructure checks need Docker."""

import argparse
import importlib.metadata
import shutil
import subprocess
import sys

from scripts.dev.common import PYTHON, ROOT, local_env


def probe(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command, env=local_env(), capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--infra", action="store_true")
    args = parser.parse_args()
    failed = []

    def check(name, value, fix):
        print(f"{'OK' if value else 'MISSING'} {name}: {value or fix}")
        if not value:
            failed.append(name)

    for name in ("make", "uv", "node", "npm", "git"):
        version = probe([name, "--version"]) if shutil.which(name) else None
        if name == "node" and version and int(version.lstrip("v").split(".")[0]) < 20:
            version = None
        check(name, version, f"Supply {name} on PATH (Node >=20); no global install is performed")
    check("local Python", str(PYTHON) if PYTHON.exists() else None, "Run make setup")
    expected = (ROOT / ".python-version").read_text().strip()
    check(
        "Python pin",
        sys.version.split()[0] if sys.version.split()[0] == expected else None,
        f"Run make setup; expected {expected}",
    )
    for package in ("pytest", "ruff", "coverage", "httpx", "playwright"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = None
        check(package, version, "Run make setup")
    check(
        "frontend lock install",
        "present" if (ROOT / "frontend/node_modules/vitest").exists() else None,
        "Run make setup",
    )
    check(
        "environment file",
        "present (values withheld)" if (ROOT / ".env").exists() else None,
        "Run make setup; runtime helper generates isolated stack secrets",
    )
    if args.infra:
        for name in ("ffmpeg", "ffprobe", "openssl", "certutil"):
            check(name, shutil.which(name), f"Supply {name} on PATH for real integration/TLS")
        check("Docker Compose", probe(["docker", "compose", "version"]), "Start your Docker engine")
        check(
            "Docker engine",
            probe(["docker", "info", "--format", "{{.NCPU}} CPU, {{.MemTotal}} bytes"]),
            "Choose a running Docker context; make capacity-status reports the isolated option",
        )
        for helper in ("runtime", "tls", "browser", "capacity"):
            check(
                f"{helper} helper",
                "present" if (ROOT / f"scripts/dev/{helper}.py").exists() else None,
                "Await foundation integration from the owning lane",
            )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
