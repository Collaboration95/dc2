"""Bootstrap with the host Python; install only into this checkout."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.dev.common import ROOT, local_env, run


def preserve_env(root: Path) -> bool:
    """Exclusive creation also preserves a configured file or symlink."""
    try:
        with (root / ".env").open("xb") as stream:
            os.chmod(root / ".env", 0o600)
            stream.write((root / ".env.example").read_bytes())
        return True
    except FileExistsError:
        return False


def find_python(version: str) -> str:
    # Reading an already installed uv interpreter is allowed; never install globally.
    discovery_env = local_env()
    discovery_env.pop("UV_PYTHON_INSTALL_DIR")
    result = subprocess.run(
        ["uv", "python", "find", "--system", "--no-project", "--no-python-downloads", version],
        env=discovery_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise SystemExit(
            f"Python {version} is missing. Provide an installed interpreter matching "
            ".python-version (uv python find --no-python-downloads). "
            "Setup never installs or updates global Python."
        )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-install", action="store_true", help="Install local Firefox")
    args = parser.parse_args()
    os.chdir(ROOT)
    for name in ("uv", "node", "npm"):
        if not shutil.which(name):
            raise SystemExit(f"Missing {name} on PATH. Supply it, then rerun make setup.")
    version = subprocess.check_output(["node", "--version"], text=True, timeout=10).strip()
    if int(version.lstrip("v").split(".")[0]) < 20:
        raise SystemExit(f"Node >=20 required; found {version}")
    python = find_python((ROOT / ".python-version").read_text().strip())
    run(
        [
            "uv",
            "sync",
            "--locked",
            "--extra",
            "dev",
            "--extra",
            "browser",
            "--extra",
            "legacy",
            "--python",
            python,
        ],
        label="setup-python",
        timeout=180,
    )
    run(
        ["npm", "ci", "--no-audit", "--no-fund"],
        label="setup-frontend",
        timeout=180,
        cwd=ROOT / "frontend",
    )
    print("Created .env (0600)" if preserve_env(ROOT) else "Preserved existing .env")
    print(f"Host bootstrap Python {sys.version.split()[0]}; Node {version}")
    if args.browser_install:
        helper = ROOT / "scripts/dev/browser.py"
        if not helper.is_file():
            raise SystemExit("Browser helper is pending parent foundation integration")
        run(
            [str(ROOT / ".venv/bin/python"), str(helper), "install", "--run-id", "local"],
            label="setup-firefox",
            timeout=180,
        )


if __name__ == "__main__":
    main()
