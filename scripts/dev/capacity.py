"""Project-local Lima VM for fair worker CPU quotas; never changes Docker Desktop.

Ordinary development uses the small default profile (2 vCPU / 2 GiB). The large 8 / 8
profile exists only for scaling benchmarks and must be requested with --benchmark. Every
start records an expiring lease; an unattended VM is flagged by `status` and stopped by
`reap`. `status` never starts anything. An existing instance keeps its persisted size.
"""

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import signal
import socket
import subprocess
import tarfile
import time
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parents[2]
ROOT = CHECKOUT
# Worktrees share one explicitly scoped VM, avoiding macOS's short socket limit.
try:
    _common = subprocess.check_output(
        ["git", "-C", str(CHECKOUT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if Path(_common).name == ".git":
        ROOT = Path(_common).parent
except (OSError, subprocess.CalledProcessError):
    pass  # Not a Git checkout (for example an export): use the checkout itself.
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
INSTANCE = "d"
LEASE = LIMA_HOME / "d-lease.json"

# Inclusive upper bounds per profile. The default is what an everyday laptop can lend
# without noticing; the benchmark profile is the historical scaling configuration.
PROFILES = {"default": {"cpus": 2, "memory_gib": 2}, "benchmark": {"cpus": 8, "memory_gib": 8}}
DISK_GIB = 64
DEFAULT_LEASE_MINUTES = 120
MAX_LEASE_MINUTES = 480
MAX_KEEP_ALIVE_MINUTES = 24 * 60


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
    # Installation fixes no VM size; start records the size it actually used.
    (CACHE / "provenance.json").write_text(
        json.dumps(
            {
                "lima_version": VERSION,
                "lima_sha256": LIMA_SHA,
                "image_url": IMAGE_URL,
                "image_sha256": IMAGE_SHA,
                "disk_gib": DISK_GIB,
                "instance": read_instance_record(),
            },
            indent=2,
        )
        + "\n"
    )
    return executable, image


def read_instance_record():
    path = CACHE / "instance.json"
    return json.loads(path.read_text()) if path.exists() else None


def write_instance_record(record):
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "instance.json").write_text(json.dumps(record, indent=2) + "\n")
    provenance = CACHE / "provenance.json"
    if provenance.exists():
        data = json.loads(provenance.read_text())
        data["instance"] = record
        data.pop("cpus", None)
        data.pop("memory_gib", None)
        provenance.write_text(json.dumps(data, indent=2) + "\n")


def host_resources():
    cpus = os.cpu_count() or 1
    try:
        memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)) // 2**30
    except (OSError, ValueError, subprocess.CalledProcessError):
        memory = None
    return {"cpus": cpus, "memory_gib": memory}


def resolve_request(*, cpus, memory_gib, benchmark, host=None):
    """Validate the requested size. Anything above the default budget needs --benchmark."""
    host = host or host_resources()
    profile = "benchmark" if benchmark else "default"
    limit = PROFILES[profile]
    chosen = {
        "cpus": limit["cpus"] if cpus is None else cpus,
        "memory_gib": limit["memory_gib"] if memory_gib is None else memory_gib,
    }
    for name in ("cpus", "memory_gib"):
        value = chosen[name]
        if type(value) is not int or value < 1:
            raise SystemExit(f"--{name.replace('_', '-')} must be a whole number of at least 1")
        if value > limit[name]:
            hint = (
                "; the large profile is a deliberate, costly choice, pass --benchmark"
                if not benchmark
                else ""
            )
            raise SystemExit(
                f"{value} {name} exceeds the {profile} profile limit of {limit[name]}{hint}"
            )
    if chosen["cpus"] > host["cpus"] or (
        host["memory_gib"] is not None and chosen["memory_gib"] * 2 > host["memory_gib"]
    ):
        raise SystemExit(
            f"Refusing {chosen['cpus']} CPU / {chosen['memory_gib']} GiB: it would leave the "
            f"host ({host['cpus']} CPU / {host['memory_gib']} GiB) without headroom."
        )
    return {"profile": profile, **chosen, "explicit": cpus is not None or memory_gib is not None}


def persisted_resources(lima_home=None):
    """cpus/memory recorded by Lima for an existing instance, or None."""
    path = (lima_home or LIMA_HOME) / INSTANCE / "lima.yaml"
    if not path.exists():
        return None
    text = path.read_text()
    cpus = re.search(r"^cpus:\s*(\d+)", text, re.M)
    memory = re.search(r"^memory:\s*[\"']?([\d.]+)\s*(GiB|MiB|GB|MB)?", text, re.M)
    if not cpus or not memory:
        return None
    amount = float(memory.group(1))
    unit = memory.group(2) or "GiB"
    gib = amount if unit in {"GiB", "GB"} else amount / 1024
    return {"cpus": int(cpus.group(1)), "memory_gib": gib}


def effective_resources(request, persisted):
    """An existing instance keeps its size; growing it needs a deliberate manual edit."""
    if persisted is None:
        return {**{k: request[k] for k in ("cpus", "memory_gib")}, "source": "new instance"}
    if request["explicit"] and (
        request["cpus"] > persisted["cpus"] or request["memory_gib"] > persisted["memory_gib"]
    ):
        raise SystemExit(
            f"Instance {INSTANCE} is configured for {persisted['cpus']} CPU / "
            f"{persisted['memory_gib']:g} GiB and is not resized implicitly. To grow it on "
            f"purpose, stop it and run: limactl edit {INSTANCE} --cpus N --memory M"
        )
    return {**persisted, "source": "persisted instance (kept)"}


def read_lease(path=None):
    path = path or LEASE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def lease_state(lease, now):
    if lease is None:
        return "NONE"
    return "EXPIRED" if now >= lease["expires_at"] else "ACTIVE"


def current_owner():
    return {
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "worktree": str(CHECKOUT),
        "pid": os.getpid(),
    }


def make_lease(minutes, *, keep_alive, resources, now, owner=None, existing=None):
    ceiling = MAX_KEEP_ALIVE_MINUTES if keep_alive else MAX_LEASE_MINUTES
    if type(minutes) is not int or not 1 <= minutes <= ceiling:
        demo = f"; use --keep-alive for a demo (up to {MAX_KEEP_ALIVE_MINUTES})"
        raise SystemExit(f"Lease must be 1..{ceiling} minutes" + ("" if keep_alive else demo))
    expires = now + minutes * 60
    owners = list(existing["owners"]) if existing else []
    mine = owner or current_owner()
    if mine["worktree"] not in {o["worktree"] for o in owners}:
        owners.append(mine)
    if existing and lease_state(existing, now) == "ACTIVE":
        expires = max(expires, existing["expires_at"])
    return {
        "owners": owners,
        "started_at": existing["started_at"] if existing else now,
        "expires_at": expires,
        "keep_alive": bool(keep_alive or (existing and existing.get("keep_alive"))),
        "resources": resources,
    }


def write_lease(lease):
    LEASE.parent.mkdir(parents=True, exist_ok=True)
    LEASE.write_text(json.dumps(lease, indent=2) + "\n")


def instance_state(executable, env):
    """Lima's own report. `limactl list` never starts or changes an instance."""
    if not executable.exists():
        return "NOT_INSTALLED"
    reply = subprocess.run(
        [str(executable), "list", "--format", "json", INSTANCE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    for line in reply.stdout.splitlines():
        try:
            return json.loads(line).get("status", "UNKNOWN")
        except ValueError:
            continue
    return "ABSENT"


def other_container_vms():
    """Sockets of other local container VMs (Docker Desktop); this tool never touches them."""
    candidates = (Path("/var/run/docker.sock"), Path.home() / ".docker/run/docker.sock")
    return [str(p) for p in candidates if p.exists()]


def describe(state, resources, lease, now):
    lines = [
        f"instance {INSTANCE}: {state}",
        f"size: {resources['cpus']} CPU / {resources['memory_gib']:g} GiB"
        + (f" ({resources['source']})" if resources.get("source") else ""),
    ]
    status = lease_state(lease, now)
    if lease:
        left = int((lease["expires_at"] - now) / 60)
        who = ", ".join(o["worktree"] for o in lease["owners"])
        lines.append(f"lease: {status}, {left} min left, keep-alive={lease['keep_alive']}")
        lines.append(f"owners: {who}")
    elif state == "Running":
        lines.append("lease: NONE; this VM is running unattended. Stop it or take a lease.")
    if status == "EXPIRED" and state == "Running":
        lines.append("EXPIRED lease on a running VM: run `make capacity-reap` to stop it.")
    return "\n".join(lines)


def stop_instance(executable, env):
    # Stopping an already stopped instance is a Lima error; make the command idempotent.
    if instance_state(executable, env) == "Running":
        run([executable, "stop", INSTANCE], env=env)
    LEASE.unlink(missing_ok=True)


def may_stop(lease, owner, now, force):
    """Another task's unexpired lease protects its VM; only a clearly expired one may go."""
    if force or lease is None or lease_state(lease, now) == "EXPIRED":
        return True
    holders = {o["worktree"] for o in lease["owners"]}
    return holders == {owner["worktree"]}


def start(args, env, executable, image):
    now = time.time()
    request = resolve_request(
        cpus=args.cpus, memory_gib=args.memory_gib, benchmark=args.benchmark
    )
    persisted = persisted_resources()
    resources = effective_resources(request, persisted)
    state = instance_state(executable, env)
    lease = read_lease()
    if lease and lease_state(lease, now) == "EXPIRED" and state == "Running":
        print("Note: the previous lease expired; this start takes the VM over with a new lease.")
    if args.benchmark and persisted is None:
        print(
            f"BENCHMARK PROFILE: this reserves {resources['cpus']} vCPU and "
            f"{resources['memory_gib']:g} GiB RAM of the host until the lease ends."
        )
    elif resources["memory_gib"] > PROFILES["default"]["memory_gib"] or (
        resources["cpus"] > PROFILES["default"]["cpus"]
    ):
        print(
            "WARNING: the persisted instance is larger than the default 2 CPU / 2 GiB budget. "
            "It was not resized; stop it and use `limactl edit` to shrink it."
        )
    owner_lease = make_lease(
        args.lease_minutes,
        keep_alive=args.keep_alive,
        resources=resources,
        now=now,
        existing=lease if state == "Running" else None,
    )
    print(describe(state, resources, owner_lease, now))
    if other_container_vms():
        print(
            "WARNING: another local container VM looks active "
            f"({', '.join(other_container_vms())}). A second VM adds its memory to the host's; "
            "Docker Desktop settings are never changed by this tool."
        )
    if state != "Running":
        if persisted is not None:
            run([executable, "start", "--yes", INSTANCE], env=env)
        else:
            images = json.dumps(
                [{"location": str(image), "arch": "aarch64", "digest": "sha256:" + IMAGE_SHA}]
            )
            run(
                [
                    executable,
                    "start",
                    "--yes",
                    f"--name={INSTANCE}",
                    "--vm-type=vz",
                    "--arch=aarch64",
                    f"--cpus={resources['cpus']}",
                    f"--memory={resources['memory_gib']}",
                    f"--disk={DISK_GIB}",
                    "--mount-type=virtiofs",
                    f"--mount-only={ROOT}:w",
                    "--set",
                    f".images = {images}",
                    "template:docker-rootful",
                ],
                env=env,
            )
    write_lease(owner_lease)
    write_instance_record(
        {
            "profile": request["profile"] if persisted is None else "persisted",
            "cpus": resources["cpus"],
            "memory_gib": resources["memory_gib"],
            "recorded_at": now,
        }
    )
    run(["docker", "info", "--format", INFO], env=env)
    return state != "Running"


INFO = "{{.NCPU}} CPUs / {{.MemTotal}} bytes / cgroup {{.CgroupVersion}}"


def status(env, executable):
    """Read-only: never starts, stops or leases anything."""
    now = time.time()
    state = instance_state(executable, env)
    lease = read_lease()
    persisted = persisted_resources() or {"cpus": "?", "memory_gib": float("nan")}
    resources = {**persisted, "source": "persisted instance"}
    print(describe(state, resources, lease, now))
    if state == "Running" and SOCKET.exists():
        run(["docker", "info", "--format", INFO], env=env)
    elif state != "Running":
        print("Project-local VM is not running. Use make capacity-start.")
    return {
        "state": state,
        "lease": lease_state(lease, now),
        "expired_but_running": state == "Running" and lease_state(lease, now) == "EXPIRED",
    }


def stop(args, env, executable):
    lease, now = read_lease(), time.time()
    owner = current_owner()
    if not may_stop(lease, owner, now, args.force):
        who = ", ".join(o["worktree"] for o in lease["owners"])
        raise SystemExit(
            f"Not stopping {INSTANCE}: it is leased to {who} until "
            f"{time.strftime('%H:%M', time.localtime(lease['expires_at']))}. "
            "Ask them, wait for expiry, or pass --force if you are sure."
        )
    stop_instance(executable, env)


def reap(env, executable):
    """Stop a running VM whose lease has lapsed; leave unexpired and untracked VMs alone."""
    now = time.time()
    lease = read_lease()
    if instance_state(executable, env) != "Running":
        LEASE.unlink(missing_ok=True)
        print("Nothing to stop: the VM is not running.")
    elif lease_state(lease, now) == "EXPIRED":
        print("Lease expired: stopping the VM (data and containers are preserved).")
        stop_instance(executable, env)
    else:
        print(f"Not stopping: lease is {lease_state(lease, now)}.")


def renew(args, env, executable):
    lease, now = read_lease(), time.time()
    if lease is None or instance_state(executable, env) != "Running":
        raise SystemExit("Nothing to renew: no running VM with a lease.")
    if not may_stop(lease, current_owner(), now, args.force):
        raise SystemExit("The lease belongs to another owner; pass --force to extend it.")
    write_lease(
        make_lease(
            args.lease_minutes,
            keep_alive=args.keep_alive,
            resources=lease["resources"],
            now=now,
            existing=lease,
        )
    )
    print("Lease extended; stop the VM yourself when the work ends.")


def run_job(args, env, executable, image):
    """Start if needed, run the command, and stop only what this invocation started."""
    if not args.command:
        raise SystemExit("run needs a command after --")
    started_here = False

    def interrupted(*_):
        raise SystemExit(130)

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        started_here = start(args, env, executable, image)
        result = subprocess.run(
            args.command, cwd=ROOT, env=env, timeout=args.lease_minutes * 60, check=False
        )
        return result.returncode
    finally:
        # Success, failure, timeout and cancellation all reach here.
        signal.signal(signal.SIGTERM, previous)
        if started_here and not args.keep_alive:
            stop_instance(executable, env)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["install", "start", "status", "stop", "env", "reap", "renew", "run"],
    )
    parser.add_argument("--cpus", type=int, help="default profile allows 1..2")
    parser.add_argument("--memory-gib", type=int, help="default profile allows 1..2")
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="allow up to 8 CPU / 8 GiB for scaling measurements; costly, never implicit",
    )
    parser.add_argument("--lease-minutes", type=int, default=DEFAULT_LEASE_MINUTES)
    parser.add_argument("--keep-alive", action="store_true", help="intentional demo lease (<=24h)")
    parser.add_argument("--force", action="store_true", help="act on a lease held by another owner")
    parser.add_argument("command", nargs="*", help="run: command after --")
    args = parser.parse_args(argv)
    env = environment()
    executable = DIST / "bin/limactl"
    if args.action in ("install", "start", "run"):
        # Validate before downloading or booting anything.
        resolve_request(cpus=args.cpus, memory_gib=args.memory_gib, benchmark=args.benchmark)
        make_lease(args.lease_minutes, keep_alive=args.keep_alive, resources={}, now=time.time())
    if args.action in ("install", "start"):
        executable, image = install()
        if args.action == "start":
            start(args, env, executable, image)
    elif args.action == "run":
        executable, image = install()
        raise SystemExit(run_job(args, env, executable, image))
    elif args.action == "stop":
        stop(args, env, executable)
    elif args.action == "reap":
        reap(env, executable)
    elif args.action == "renew":
        renew(args, env, executable)
    elif args.action == "env":
        print(json.dumps({k: env[k] for k in ("DOCKER_HOST", "DOCKER_CONFIG", "LIMA_HOME")}))
    else:
        status(env, executable)


if __name__ == "__main__":
    main()
