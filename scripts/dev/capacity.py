"""Project-local Lima VM for fair worker CPU quotas; never changes Docker Desktop."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Worktrees share one explicitly scoped VM, avoiding macOS's short socket limit.
_common = subprocess.check_output(
    ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
    text=True,
).strip()
if Path(_common).name == ".git":
    ROOT = Path(_common).parent
VERSION = "2.2.1"
ASSET = f"lima-{VERSION}-Darwin-arm64.tar.gz"
LIMA_SHA = "9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e"
IMAGE_URL = (
    "https://cloud-images.ubuntu.com/releases/resolute/release-20260927/"
    "ubuntu-26.04-server-cloudimg-arm64.img"
)
IMAGE_SHA = "63a93bd5a8d76e33b15ceb5daa3657bd79be804748051ab178e643b0f5da22e7"
CACHE = ROOT / ".cache/capacity"
DIST = ROOT / ".local/lima-dist"
LIMA_HOME = ROOT / ".local/lima"
DOCKER_CONFIG = ROOT / ".local/docker"
SOCKET = LIMA_HOME / "d/sock/docker.sock"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, cwd=ROOT, **kwargs)


def environment():
    env = os.environ.copy()
    env.update(
        LIMA_HOME=str(LIMA_HOME), DOCKER_CONFIG=str(DOCKER_CONFIG), TMPDIR=str(ROOT / ".cache/tmp")
    )
    for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        env.pop(key, None)
    env["DOCKER_HOST"] = f"unix://{SOCKET}"
    return env


def install():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This optional project VM installer supports macOS arm64 only.")
    for path in (CACHE, DIST, LIMA_HOME, DOCKER_CONFIG / "cli-plugins", ROOT / ".cache/tmp"):
        path.mkdir(parents=True, exist_ok=True)
    archive = CACHE / ASSET
    if not archive.exists():
        run(
            [
                "gh",
                "release",
                "download",
                f"v{VERSION}",
                "--repo",
                "lima-vm/lima",
                "--pattern",
                ASSET,
                "--dir",
                CACHE,
            ]
        )
    if digest(archive) != LIMA_SHA:
        raise SystemExit("Lima archive checksum mismatch; refusing to execute it.")
    executable = DIST / "bin/limactl"
    if not executable.exists():
        with tarfile.open(archive) as source:
            source.extractall(DIST, filter="data")
    run(["codesign", "--verify", "--strict", executable])
    for name in ("docker-compose", "docker-buildx"):
        candidates = [
            Path.home() / ".docker/cli-plugins" / name,
            Path("/Applications/Docker.app/Contents/Resources/cli-plugins") / name,
        ]
        existing = next((p for p in candidates if p.exists()), None)
        if existing is None:
            raise SystemExit(f"Existing {name} plugin not found; no global install attempted.")
        target = DOCKER_CONFIG / "cli-plugins" / name
        if not target.exists():
            target.symlink_to(existing.resolve())
    image = CACHE / "ubuntu-arm64.img"
    if not image.exists():
        temporary = image.with_suffix(".download")
        run(
            [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "2",
                "--connect-timeout",
                "30",
                "--max-time",
                "1800",
                IMAGE_URL,
                "--output",
                temporary,
            ]
        )
        if digest(temporary) != IMAGE_SHA:
            raise SystemExit("Ubuntu image checksum mismatch; refusing to boot it.")
        temporary.rename(image)
    elif digest(image) != IMAGE_SHA:
        raise SystemExit("Cached Ubuntu image checksum mismatch; refusing to boot it.")
    (CACHE / "provenance.json").write_text(
        json.dumps(
            {
                "lima_version": VERSION,
                "lima_sha256": LIMA_SHA,
                "image_url": IMAGE_URL,
                "image_sha256": IMAGE_SHA,
                "cpus": 8,
                "memory_gib": 8,
                "disk_gib": 40,
            },
            indent=2,
        )
        + "\n"
    )
    return executable, image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "start", "status", "stop", "env"])
    args = parser.parse_args()
    env = environment()
    executable = DIST / "bin/limactl"
    if args.action in ("install", "start"):
        executable, image = install()
        if args.action == "start":
            if (LIMA_HOME / "d/lima.yaml").exists():
                run([executable, "start", "--yes", "d"], env=env)
            else:
                images = json.dumps(
                    [{"location": str(image), "arch": "aarch64", "digest": "sha256:" + IMAGE_SHA}]
                )
                run(
                    [
                        executable,
                        "start",
                        "--yes",
                        "--name=d",
                        "--vm-type=vz",
                        "--arch=aarch64",
                        "--cpus=8",
                        "--memory=8",
                        "--disk=40",
                        "--mount-type=virtiofs",
                        f"--mount-only={ROOT}:w",
                        "--set",
                        f".images = {images}",
                        "template:docker-rootful",
                    ],
                    env=env,
                )
            run(
                [
                    "docker",
                    "info",
                    "--format",
                    "{{.NCPU}} CPUs / {{.MemTotal}} bytes / cgroup {{.CgroupVersion}}",
                ],
                env=env,
            )
    elif args.action == "stop":
        if executable.exists():
            run([executable, "stop", "d"], env=env)
    elif args.action == "env":
        print(json.dumps({k: env[k] for k in ("DOCKER_HOST", "DOCKER_CONFIG", "LIMA_HOME")}))
    elif executable.exists() and SOCKET.exists():
        run(
            [
                "docker",
                "info",
                "--format",
                "{{.NCPU}} CPUs / {{.MemTotal}} bytes / cgroup {{.CgroupVersion}}",
            ],
            env=env,
        )
    else:
        raise SystemExit("Project-local VM is not running. Use make capacity-start.")


if __name__ == "__main__":
    main()
