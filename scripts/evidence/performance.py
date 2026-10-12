"""Local V3 runner. Live acceptance remains separate from offline runner validation.

Run as: python -m scripts.evidence.performance {performance,scaling} --run-id ID
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime
from uuid import UUID, uuid4

from scripts.dev import runtime
from scripts.evidence.common import Artifacts, Client, EvidenceError, utc

GIB = 2**30
WORKER_MEMORY = 1536 * 2**20
TERMINAL = {"succeeded", "failed", "cancelled", "abandoned"}
FIXED_CPU = {
    "media": 0.5,
    "processing": 0.5,
    "postgres": 0.25,
    "minio": 0.25,
    "redis": 0.125,
    "nginx": 0.125,
    "processing-recovery": 0.125,
    "media-recovery": 0.125,
}
FIXED_SERVICES = set(FIXED_CPU)


async def blocking(function, *args):
    """Let a bounded subprocess finish before cancellation cleanup changes workers."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


def positive(value, label, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceError(f"Invalid {label}")
    if value < 0 or (not zero and value == 0):
        raise EvidenceError(f"Invalid {label}")
    return value


def p90(values):
    if not values:
        raise EvidenceError("No latency attempts")
    ordered = sorted(positive(v, "latency", zero=True) for v in values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def latency_metrics(samples, topic):
    if topic not in {"status", "login"}:
        raise EvidenceError("Unknown latency topic")
    if not samples:
        raise EvidenceError("No timed samples")
    for sample in samples:
        if "error" not in sample:
            raise EvidenceError("Missing request outcome")
    errors = sum(sample["error"] is not None for sample in samples)
    percentile = p90([sample["elapsed_ms"] for sample in samples])
    return {
        "requests": len(samples),
        "errors": errors,
        "error_fraction": errors / len(samples),
        "p90_ms": percentile,
        "latency_pass": percentile <= 700 if topic == "status" else percentile < 2000,
        "errors_pass": errors / len(samples) < 0.01 if topic == "status" else None,
    }


def run_order(repeats):
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise EvidenceError("Repeats must be positive")
    return [(r + 1, n) for r in range(repeats) for n in (1, 2, 3)[r % 3 :] + (1, 2, 3)[: r % 3]]


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (AttributeError, TypeError, ValueError):
        raise EvidenceError("Invalid aware attempt timestamp") from None


def attempt_record(job, *, owner, assets):
    """Select public metric fields only; discard URLs, output keys and error bodies."""
    try:
        asset = str(UUID(job["asset_id"]))
        if job["owner_id"] != owner or asset not in assets:
            raise EvidenceError("Processing returned an unrequested asset or owner")
        attempt = job["current_attempt"]
        state = attempt["state"]
        if state not in {"queued", "processing", *TERMINAL}:
            raise EvidenceError("Unknown attempt state")
        record = {
            "asset_id": asset,
            "job_id": str(UUID(job["job_id"])),
            "attempt_id": str(UUID(attempt["attempt_id"])),
            "state": state,
            "queued_at": attempt["queued_at"],
            "started_at": attempt.get("started_at"),
            "finished_at": attempt.get("finished_at"),
            "has_error": bool(attempt.get("error") or job.get("error")),
            "warning_count": len(job.get("warnings") or []),
            "has_primary": any(o["kind"] == "primary" for o in job["outputs"]),
            "has_hls": any(o["kind"] == "hls_manifest" for o in job["outputs"]),
            "source_sha256": job["source"]["sha256"],
        }
        instant(record["queued_at"])
        for field in ("started_at", "finished_at"):
            if record[field] is not None:
                instant(record[field])
        return record
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("Invalid Processing job response") from None


def scaling_metrics(jobs, *, makespan_seconds, expected_jobs):
    positive(makespan_seconds, "makespan")
    if len(jobs) != expected_jobs or expected_jobs < 1:
        raise EvidenceError("Incomplete measured backlog")
    for key in ("asset_id", "job_id", "attempt_id"):
        if len({job[key] for job in jobs}) != len(jobs):
            raise EvidenceError("Duplicate measured identity")
    waits, processing = [], []
    for job in jobs:
        if job["state"] not in TERMINAL:
            raise EvidenceError("Nonterminal measured attempt")
        queued = instant(job["queued_at"])
        finished = instant(job["finished_at"])
        if finished < queued:
            raise EvidenceError("Finish precedes queue time")
        if job["started_at"] is None:
            if job["state"] == "succeeded":
                raise EvidenceError("Successful attempt has no start")
            continue
        started = instant(job["started_at"])
        if not queued <= started <= finished:
            raise EvidenceError("Invalid attempt timestamp order")
        waits.append(started - queued)
        processing.append(finished - started)
        if job["state"] == "succeeded" and not job["has_primary"]:
            raise EvidenceError("Successful attempt has no primary output")
    errors = sum(job["state"] != "succeeded" or job["has_error"] for job in jobs)
    successes = sum(job["state"] == "succeeded" and not job["has_error"] for job in jobs)
    return {
        "jobs": len(jobs),
        "successes": successes,
        "errors": errors,
        "makespan_seconds": makespan_seconds,
        "throughput_jobs_min": successes * 60 / makespan_seconds,
        "queue_wait_seconds": waits,
        "processing_seconds": processing,
        "queue_wait_median_seconds": statistics.median(waits) if waits else None,
        "processing_median_seconds": statistics.median(processing) if processing else None,
        "warnings": sum(job["warning_count"] for job in jobs),
        "missing_hls": sum(not job["has_hls"] for job in jobs),
    }


def scaling_targets(runs, *, repeats=3, pilot=False):
    expected = set(run_order(repeats))
    identities = [(r["repeat"], r["workers"]) for r in runs]
    if len(identities) != len(set(identities)) or set(identities) != expected:
        raise EvidenceError("Missing or duplicate scaling runs")
    grouped = {n: [r["metrics"] for r in runs if r["workers"] == n] for n in (1, 2, 3)}
    throughputs, queues = {}, {}
    for n, metrics in grouped.items():
        for metric in metrics:
            if (
                isinstance(metric["errors"], bool)
                or not isinstance(metric["errors"], int)
                or metric["errors"] < 0
            ):
                raise EvidenceError("Invalid failed-job count")
        throughputs[n] = statistics.median(
            positive(m["throughput_jobs_min"], "throughput", zero=True) for m in metrics
        )
        waits = [
            positive(q, "queue wait", zero=True) for m in metrics for q in m["queue_wait_seconds"]
        ]
        if not waits:
            raise EvidenceError("No measured queue waits")
        queues[n] = statistics.median(waits)
    if throughputs[1] <= 0:
        raise EvidenceError("No successful one-worker baseline")
    rows = [
        {
            "target": "2 workers >= 1.6x",
            "actual": throughputs[2] / throughputs[1],
            "pass": throughputs[2] / throughputs[1] >= 1.6,
        },
        {
            "target": "3 workers >= 2.1x",
            "actual": throughputs[3] / throughputs[1],
            "pass": throughputs[3] / throughputs[1] >= 2.1,
        },
        {
            "target": "decreasing pooled median queue wait",
            "actual": [queues[n] for n in (1, 2, 3)],
            "pass": queues[3] < queues[2] < queues[1],
        },
        {
            "target": "zero failed jobs",
            "actual": sum(r["metrics"]["errors"] for r in runs),
            "pass": all(r["metrics"]["errors"] == 0 for r in runs),
        },
    ]
    return {
        "targets": rows,
        "median_throughput_jobs_min": throughputs,
        "throughput_ranges": {
            n: [
                min(m["throughput_jobs_min"] for m in ms),
                max(m["throughput_jobs_min"] for m in ms),
            ]
            for n, ms in grouped.items()
        },
        "criteria_pass": all(row["pass"] for row in rows),
        "acceptance_eligible": not pilot and repeats >= 3,
        "label": "pilot"
        if pilot
        else (
            "single-repeat diagnostic"
            if repeats == 1
            else "reduced-repeat diagnostic"
            if repeats < 3
            else "full local"
        ),
    }


def container_record(item):
    labels = item["Config"].get("Labels") or {}
    limits = item["HostConfig"]
    cpu = limits.get("NanoCpus", 0) / 1e9
    if not cpu and limits.get("CpuQuota", 0) > 0:
        cpu = limits["CpuQuota"] / (limits.get("CpuPeriod") or 100000)
    return {
        "id": item["Id"],
        "service": labels.get("com.docker.compose.service"),
        "project": labels.get("com.docker.compose.project"),
        "image_digest": item["Image"],
        "running": item["State"]["Running"],
        "cpu_limit": cpu,
        "memory_limit_bytes": limits.get("Memory", 0),
    }


def capacity_check(info, containers, project):
    other = [c for c in containers if c["running"] and c["project"] != project]
    if any(not c["cpu_limit"] or not c["memory_limit_bytes"] for c in other):
        raise EvidenceError(
            "Another namespace has uncapped running containers; serialize live work"
        )
    required_cpu = 8 + sum(c["cpu_limit"] for c in other)
    own = [c for c in containers if c["running"] and c["project"] == project]
    if any(c["service"] not in FIXED_SERVICES | {"worker"} for c in own):
        raise EvidenceError("Unexpected running service in evidence namespace")
    if len({c["service"] for c in own if c["service"] in FIXED_SERVICES}) != len(
        [c for c in own if c["service"] in FIXED_SERVICES]
    ):
        raise EvidenceError("Fixed service replicated unexpectedly")
    fixed = [
        c
        for c in containers
        if c["running"] and c["project"] == project and c["service"] in FIXED_SERVICES
    ]
    if any(c["cpu_limit"] != FIXED_CPU[c["service"]] for c in fixed):
        raise EvidenceError("Fixed service CPU quotas differ from frozen configuration")
    if any(not c["memory_limit_bytes"] for c in fixed):
        raise EvidenceError("Fixed service memory reservations must be bounded")
    required_memory = (
        3 * WORKER_MEMORY
        + sum(c["memory_limit_bytes"] for c in fixed)
        + sum(c["memory_limit_bytes"] for c in other)
    )
    if info["NCPU"] < required_cpu or info["MemTotal"] < required_memory:
        raise EvidenceError(
            "Insufficient Docker capacity: require 8 CPUs plus "
            "actual fixed/worker/other memory reservations"
        )
    if str(info.get("CgroupVersion")) != "2":
        raise EvidenceError("Runner requires verifiable cgroup v2 quotas")
    return {
        "required_cpus": required_cpu,
        "required_memory_bytes": required_memory,
        "docker_cpus": info["NCPU"],
        "docker_memory_bytes": info["MemTotal"],
        "architecture": info.get("Architecture"),
        "cgroup_version": info["CgroupVersion"],
        "other_reservations": other,
    }


def cpu_set_size(value):
    cpus = set()
    try:
        for part in value.split(","):
            ends = [int(n) for n in part.split("-")]
            if len(ends) == 1:
                cpus.add(ends[0])
            elif len(ends) == 2 and 0 <= ends[0] <= ends[1] < 4096:
                cpus.update(range(ends[0], ends[1] + 1))
            else:
                raise ValueError
        return len(cpus)
    except ValueError:
        raise EvidenceError("Invalid effective CPU set") from None


def worker_quota(record, cgroup):
    try:
        quota, period = cgroup["cpu.max"].split()
        memory = int(cgroup["memory.max"])
        cpu = int(quota) / int(period)
    except (KeyError, ValueError, ZeroDivisionError):
        raise EvidenceError("Worker has no readable hard cgroup limits") from None
    if cpu_set_size(cgroup["cpuset.cpus.effective"]) < 2:
        raise EvidenceError("Worker effective CPU set is smaller than its 2 CPU quota")
    if record["cpu_limit"] != 2 or cpu != 2 or memory != WORKER_MEMORY:
        raise EvidenceError("Worker must have actual hard 2 CPU / 1536 MiB limits")
    if record["memory_limit_bytes"] != WORKER_MEMORY:
        raise EvidenceError("Docker and cgroup memory quotas disagree")
    return {
        **record,
        "cgroup_cpu_max": cgroup["cpu.max"],
        "cgroup_memory_max": memory,
        "cgroup_effective_cpus": cgroup["cpuset.cpus.effective"],
    }


class Docker:
    def __init__(self, state, artifacts=None):
        self.state = state
        self.artifacts = artifacts
        self.owned_worker_ids = set()
        self.env = os.environ.copy()
        if state["docker_host"]:
            self.env["DOCKER_HOST"] = state["docker_host"]
            for key in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                self.env.pop(key, None)
        self.env["DOCKER_CONFIG"] = state["docker_config"]

    def command(self, *args, timeout=30):
        try:
            return subprocess.run(
                ["docker", *args],
                env=self.env,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise EvidenceError("Bounded Docker command failed; no retry") from None

    def compose(self, *args):
        try:
            return runtime.compose(
                self.state, *args, timeout=120, capture_output=True, text=True
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise EvidenceError("Bounded Compose command failed; no retry") from None

    def inspect(self, ids):
        if not ids:
            return []
        return [container_record(c) for c in json.loads(self.command("inspect", *ids))]

    def all_running(self):
        return self.inspect(self.command("ps", "-q").split())

    def preflight(self):
        info = json.loads(self.command("info", "--format", "{{json .}}"))
        running = self.all_running()
        if self.artifacts:
            self.artifacts.append(
                "preflight.jsonl",
                {
                    "utc": utc(),
                    "docker_cpus": info["NCPU"],
                    "docker_memory_bytes": info["MemTotal"],
                    "cgroup_version": info.get("CgroupVersion"),
                    "architecture": info.get("Architecture"),
                    "containers": running,
                },
            )
        resources = capacity_check(info, running, self.state["compose_project"])
        own = [c for c in running if c["project"] == self.state["compose_project"]]
        missing = FIXED_SERVICES - {c["service"] for c in own}
        if missing:
            raise EvidenceError(
                "Integrated runtime services missing: " + ", ".join(sorted(missing))
            )
        if any(c["service"] == "worker" for c in own):
            raise EvidenceError("Evidence stack must begin with workers stopped")
        services = self.compose("config", "--services").split()
        if "worker" not in services:
            raise EvidenceError("Compose worker service is not integrated")
        return resources, sorted(own, key=lambda c: c["id"])

    def start_workers(self, count):
        self.compose("up", "-d", "--no-deps", "--scale", f"worker={count}", "worker")
        ids = self.compose("ps", "-q", "worker").split()
        self.owned_worker_ids = set(ids)
        records = self.inspect(ids)
        if len(records) != count or any(
            not r["running"]
            or r["service"] != "worker"
            or r["project"] != self.state["compose_project"]
            for r in records
        ):
            raise EvidenceError("Unexpected running worker replica count")
        checked = []
        for record in records:
            values = {}
            for name in ("cpu.max", "memory.max", "cpuset.cpus.effective"):
                values[name] = self.command(
                    "exec", record["id"], "cat", "/sys/fs/cgroup/" + name
                ).strip()
            if self.artifacts:
                self.artifacts.append(
                    "quotas.jsonl", {"utc": utc(), "worker": record, "cgroup": values}
                )
            checked.append(worker_quota(record, values))
        return checked

    def queue_snapshot(self):
        # Processing-owned Redis diagnosis runs inside Processing. No cross-owner DB read.
        probe = """
import json, os
from redis import Redis
from rq import Queue
from rq.registry import StartedJobRegistry
from rq.intermediate_queue import IntermediateQueue
r = Redis.from_url(os.environ['PROCESSING_REDIS_URL'], socket_timeout=3, socket_connect_timeout=3)
q = Queue(os.environ['PROCESSING_QUEUE_NAME'], connection=r)
print(json.dumps({'ready_attempt_ids': q.get_job_ids(),
                  'intermediate_attempt_ids': IntermediateQueue(q.key, r).get_job_ids(),
                  'started_attempt_ids': StartedJobRegistry(queue=q).get_job_ids(cleanup=False)}))
"""
        return json.loads(self.compose("exec", "-T", "processing", "python", "-c", probe))

    def worker_states(self, ids):
        states = []
        for item in json.loads(self.command("inspect", *ids)):
            record = container_record(item)
            if record["service"] != "worker" or record["project"] != self.state["compose_project"]:
                raise EvidenceError("Refusing mutation of an unowned worker")
            states.append(
                {
                    **record,
                    "paused": item["State"]["Paused"],
                    "hostname": item["Config"]["Hostname"],
                }
            )
        return states

    def warmup_consumer(self, ids, selected):
        states = self.worker_states(ids)
        running = [
            w
            for w in self.all_running()
            if w["service"] == "worker" and w["project"] == self.state["compose_project"]
        ]
        if (
            {w["id"] for w in running} != {selected}
            or {w["id"] for w in states if w["running"]} != {selected}
            or any(w["paused"] for w in states)
        ):
            raise EvidenceError("Warmup requires only the selected owned worker running")
        return next(w for w in states if w["id"] == selected)

    def warmup_assignment(self, attempt_id):
        # Read RQ's execution identity; never infer consumption from intended scheduling.
        probe = """
import json, os, sys
from redis import Redis
from rq.job import Job
r = Redis.from_url(os.environ['PROCESSING_REDIS_URL'], socket_timeout=3, socket_connect_timeout=3)
job = Job.fetch(sys.argv[1], connection=r)
name = job.worker_name
hostname = r.hget('rq:worker:' + name, 'hostname') if name else None
print(json.dumps({'attempt_id': job.id, 'rq_worker_name': name,
                  'hostname': hostname.decode() if hostname else None}))
"""
        return json.loads(
            self.compose("exec", "-T", "processing", "python", "-c", probe, attempt_id)
        )

    def stop_workers(self):
        # start_workers updates this set inside its bounded call, before cancellation escapes.
        errors = []
        ids = set(self.owned_worker_ids)
        try:
            ids.update(self.compose("ps", "--all", "-q", "worker").split())
        except EvidenceError:
            errors.append("worker discovery failed")
        for worker_id in sorted(ids):
            outcome = {"utc": utc(), "worker_id": worker_id, "error": None}
            try:
                state = self.worker_states([worker_id])[0]
                if state["paused"]:
                    self.command("unpause", worker_id)
                self.command("stop", "--time", "10", worker_id)
                state = self.worker_states([worker_id])[0]
                outcome["state"] = state
                if state["running"] or state["paused"]:
                    raise EvidenceError("Worker remained running or paused")
            except (EvidenceError, KeyError, IndexError, json.JSONDecodeError):
                outcome["error"] = "owned_worker_stop_or_state_check_failed"
                errors.append("owned worker stop/state check failed: " + worker_id)
            if self.artifacts:
                self.artifacts.append("cleanup.jsonl", outcome)
        if errors:
            raise EvidenceError("Worker cleanup failed: " + "; ".join(errors))

    def encoding_metadata(self, worker_id):
        # Select only encoder fields from AST/defaults and corresponding environment.
        # This does not import a product package or emit its settings/credentials.
        probe = """
import ast, json, os
from pathlib import Path
fields = {'ffmpeg_binary', 'ffmpeg_preset', 'ffmpeg_crf'}
values = {}
for node in ast.walk(ast.parse(Path('/app/processing/config.py').read_text())):
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        name = node.target.id
        if name in fields:
            value = node.value
            if isinstance(value, ast.Call):
                value = next(k.value for k in value.keywords if k.arg == 'default')
            values[name] = os.environ.get('PROCESSING_' + name.upper(), ast.literal_eval(value))
if set(values) != fields:
    raise ValueError('Encoder fields unavailable')
print(json.dumps(values))
"""
        values = json.loads(self.command("exec", worker_id, "python", "-c", probe))
        # No arbitrary environment-provided executable name is retained in artifacts.
        binary = values.pop("ffmpeg_binary")
        values["ffmpeg_version"] = self.command("exec", worker_id, binary, "-version").splitlines()[
            0
        ]
        values["thread_policy"] = (
            "FFmpeg automatic threads; actual cgroup CPU quota is authoritative"
        )
        values["output_policy"] = "MP4 primary plus best-effort 360/480/720p HLS (frozen design)"
        return values

    def stats(self, records):
        ids = [c["id"] for c in records]
        result = self.command("stats", "--no-stream", "--format", "{{json .}}", *ids)
        return [json.loads(line) for line in result.splitlines() if line]


def host_command(args, timeout=120):
    try:
        return subprocess.run(
            args, cwd=runtime.ROOT, capture_output=True, text=True, check=True, timeout=timeout
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise EvidenceError("Bounded host command failed; no retry") from None


def fixture(directory, seconds):
    path = directory / "source.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-n",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=48000",
        "-t",
        str(seconds),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-threads",
        "2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(path),
    ]
    version = host_command(["ffmpeg", "-version"]).splitlines()[0]
    host_command(command, timeout=300)
    metadata = json.loads(
        host_command(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
        )
    )
    streams = metadata["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    duration = float(metadata["format"]["duration"])
    if video["height"] != 720 or video["width"] != 1280 or abs(duration - seconds) > 0.1:
        raise EvidenceError("Generated fixture dimensions/duration differ from plan")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return path, {
        "sha256": digest,
        "size_bytes": path.stat().st_size,
        "duration_seconds": duration,
        "height": video["height"],
        "width": video["width"],
        "video_codec": video["codec_name"],
        "audio_codec": audio["codec_name"],
        "sample_rate": audio["sample_rate"],
        "ffmpeg_version": version,
        "generation_preset": "veryfast",
        "generation_threads": 2,
        "generation_command": command[:-1] + ["source.mp4"],
    }


async def owner(state, artifacts, index):
    client = Client(state["public_url"], ca_file=state["ca_file"])
    credentials = {"email": f"e-{uuid4().hex}@example.com", "password": secrets.token_urlsafe(24)}
    artifacts.secrets.append(credentials["password"])
    try:
        user = await client.checked(
            "POST",
            "/api/auth/register",
            expected=201,
            json=credentials,
            artifacts=artifacts,
            record={"phase": "owner-preparation", "operation": "register", "client": index},
        )
        owner_id = str(UUID(user["id"]))
        await client.checked(
            "POST",
            "/api/auth/login",
            json=credentials,
            artifacts=artifacts,
            record={"phase": "owner-preparation", "operation": "login", "client": index},
        )
        me = await client.checked(
            "GET",
            "/api/auth/me",
            artifacts=artifacts,
            record={"phase": "owner-preparation", "operation": "session", "client": index},
        )
        if me["id"] != owner_id or not client.http.cookies.get("access_token"):
            raise EvidenceError("Independent authenticated owner session missing")
        return {"index": index, "client": client, "credentials": credentials, "id": owner_id}
    except BaseException:
        await client.close()
        raise


async def upload(person, path, *, artifacts=None, phase=None, sequence=None, acknowledgement=None):
    with path.open("rb") as stream:
        data, sample = await person["client"].request(
            "POST", "/api/upload", expected=202, files={"file": ("source.mp4", stream, "video/mp4")}
        )
    received_monotonic, received_utc = time.monotonic(), utc()
    asset = None
    if sample["error"] is None:
        try:
            asset = str(UUID(data["job_id"]))
        except (KeyError, TypeError, ValueError):
            sample["error"] = "invalid_asset_acknowledgement"
    record = {
        "utc": received_utc,
        "acknowledged_monotonic": received_monotonic if asset else None,
        "phase": phase,
        "sequence": sequence,
        "asset_id": asset,
        **sample,
    }
    if acknowledgement is not None:
        acknowledgement.update(record)
    if artifacts is not None:
        artifacts.append("submissions.jsonl", record)
    if sample["error"]:
        raise EvidenceError("Upload failed: " + sample["error"])
    return asset


async def processing_read(client, person, assets, *, artifacts=None, phase=None):
    data = await client.checked(
        "GET",
        "/internal/v1/jobs",
        params={"asset_ids": ",".join(assets)},
        headers={"X-Owner-Id": person["id"]},
        artifacts=artifacts,
        record={"phase": phase, "operation": "processing_observation", "asset_ids": assets},
    )
    if not isinstance(data, list):
        raise EvidenceError("Processing batch must be an array")
    records = [attempt_record(job, owner=person["id"], assets=assets) for job in data]
    if len({job["asset_id"] for job in records}) != len(records):
        raise EvidenceError("Duplicate Processing batch asset")
    return records


async def wait_jobs(
    client, person, assets, *, deadline, artifacts, phase, digest, queued=False, identities=None
):
    identities = {} if identities is None else identities
    while time.monotonic() < deadline:
        jobs = await processing_read(client, person, assets, artifacts=artifacts, phase=phase)
        for job in jobs:
            if job["source_sha256"] != digest:
                raise EvidenceError("Processing source digest differs from identical fixture")
            identity = (job["job_id"], job["attempt_id"])
            if job["asset_id"] in identities and identities[job["asset_id"]] != identity:
                raise EvidenceError(
                    "Attempt identity changed; automatic retry cannot hide a failure"
                )
            identities[job["asset_id"]] = identity
        artifacts.append("observations.jsonl", {"utc": utc(), "phase": phase, "jobs": jobs})
        if queued and any(j["state"] != "queued" or j["started_at"] is not None for j in jobs):
            raise EvidenceError("Backlog started before timed worker launch")
        if len(jobs) == len(assets) and all(
            j["state"] == "queued" if queued else j["state"] in TERMINAL for j in jobs
        ):
            return jobs
        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
    raise EvidenceError("Backlog deadline exceeded; partial observations retained")


async def wait_queue(docker, expected, *, deadline, artifacts, phase):
    expected = set(expected)
    while time.monotonic() < deadline:
        snapshot = await blocking(docker.queue_snapshot)
        artifacts.append("queue.jsonl", {"utc": utc(), "phase": phase, **snapshot})
        ready = snapshot["ready_attempt_ids"]
        if (
            len(ready) != len(set(ready))
            or set(ready) - expected
            or snapshot["started_attempt_ids"]
            or snapshot["intermediate_attempt_ids"]
        ):
            raise EvidenceError(
                "Evidence namespace has unexpected runnable/started/intermediate work"
            )
        if set(ready) == expected:
            return
        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
    raise EvidenceError("Runnable backlog deadline exceeded; queue observations retained")


def memory_bytes(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)", value)
    units = {
        "B": 1,
        "kB": 1000,
        "MB": 10**6,
        "GB": 10**9,
        "KiB": 2**10,
        "MiB": 2**20,
        "GiB": 2**30,
        "TiB": 2**40,
    }
    if not match or match[2] not in units:
        raise EvidenceError("Invalid Docker memory usage sample")
    return float(match[1]) * units[match[2]]


def resource_summary(samples):
    by_container = {}
    for sample in samples:
        for container in sample:
            key = container["ID"]
            entry = by_container.setdefault(key, {"cpu_percent": [], "memory_bytes": []})
            entry["cpu_percent"].append(
                positive(float(container["CPUPerc"].rstrip("%")), "CPU usage", zero=True)
            )
            entry["memory_bytes"].append(memory_bytes(container["MemUsage"].split(" / ")[0]))
    return {
        key: {
            "samples": len(v["cpu_percent"]),
            "mean_cpu_percent": statistics.mean(v["cpu_percent"]),
            "max_cpu_percent": max(v["cpu_percent"]),
            "peak_sampled_memory_bytes": max(v["memory_bytes"]),
        }
        for key, v in by_container.items()
    }


async def collect_stats(docker, records, artifacts, phase, stop):
    collected = []
    while not stop.is_set():
        samples = await blocking(docker.stats, records)
        collected.append(samples)
        artifacts.append(
            "resources.jsonl",
            {"utc": utc(), "monotonic": time.monotonic(), "phase": phase, "containers": samples},
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass

    return resource_summary(collected)


async def scaling(args, env, state, artifacts, manifest):
    docker = Docker(state, artifacts)
    resources, fixed = await blocking(docker.preflight)
    manifest.update(resources=resources, fixed_services=fixed)
    path, source = await blocking(
        fixture, artifacts.directory, args.pilot_clip_seconds if args.pilot else 60
    )
    manifest["fixture"] = source
    artifacts.write("manifest.json", manifest)
    person = await owner(state, artifacts, 0)
    private = Client(
        f"http://127.0.0.1:{state['processing_port']}",
        headers={"Authorization": "Bearer " + env["PROCESSING_SERVICE_TOKEN"]},
    )
    runs = []
    seen_assets = set()
    try:
        for repeat, count in run_order(args.repeats):
            phase = f"r{repeat}-w{count}"
            # Recheck other namespaces at every launch, never change their containers.
            _, current_fixed = await blocking(docker.preflight)
            if current_fixed != fixed:
                raise EvidenceError("Fixed nonworker identity/resources changed")
            await wait_queue(
                docker,
                [],
                deadline=time.monotonic() + 10,
                artifacts=artifacts,
                phase=phase + "-clean-queue",
            )
            workers = await blocking(docker.start_workers, count)
            encoding = [await blocking(docker.encoding_metadata, w["id"]) for w in workers]
            if any(e != encoding[0] for e in encoding):
                raise EvidenceError("Worker encoding configuration differs across replicas")
            if "worker_encoding" in manifest and manifest["worker_encoding"] != encoding[0]:
                raise EvidenceError("Encoding configuration changed between scaling runs")
            manifest["worker_encoding"] = encoding[0]
            artifacts.write("manifest.json", manifest)
            try:
                worker_ids = [w["id"] for w in workers]
                for sequence, selected in enumerate(workers, 1):
                    # A frozen RQ worker retains its blocking Redis dequeue. Stop disconnects it.
                    others = [key for key in worker_ids if key != selected["id"]]
                    if others:
                        await blocking(docker.command, "stop", "--time", "10", *others)
                    await blocking(docker.command, "start", selected["id"])
                    consumer = await blocking(docker.warmup_consumer, worker_ids, selected["id"])
                    artifacts.append(
                        "warmup-consumers.jsonl",
                        {"utc": utc(), "phase": phase, "sequence": sequence, "consumer": consumer},
                    )
                    warm_asset = await upload(
                        person,
                        path,
                        artifacts=artifacts,
                        phase=phase + "-warmup",
                        sequence=sequence,
                    )
                    warm = await wait_jobs(
                        private,
                        person,
                        [warm_asset],
                        deadline=time.monotonic() + args.job_deadline,
                        artifacts=artifacts,
                        phase=phase + "-warmup",
                        digest=source["sha256"],
                    )
                    consumer = await blocking(docker.warmup_consumer, worker_ids, selected["id"])
                    assignment = await blocking(docker.warmup_assignment, warm[0]["attempt_id"])
                    artifacts.append(
                        "warmups.jsonl",
                        {
                            "utc": utc(),
                            "phase": phase,
                            "worker_id": selected["id"],
                            "consumer": consumer,
                            "assignment": assignment,
                            "jobs": warm,
                        },
                    )
                    if (
                        assignment["attempt_id"] != warm[0]["attempt_id"]
                        or not assignment["rq_worker_name"]
                        or assignment["hostname"] != consumer["hostname"]
                    ):
                        raise EvidenceError(
                            "Warmup execution was not assigned to the selected replica"
                        )
                    if (
                        warm[0]["state"] != "succeeded"
                        or warm[0]["has_error"]
                        or not warm[0]["has_primary"]
                    ):
                        raise EvidenceError("Worker warmup failed")
            finally:
                await blocking(docker.stop_workers)
            # No cache/status reuse: each POST creates a distinct durable Asset.
            accepted_start = None
            assets = []
            deadline = time.monotonic() + args.job_deadline
            for sequence in range(1, (args.pilot_jobs if args.pilot else 30) + 1):
                acknowledgement = {}
                asset = await upload(
                    person,
                    path,
                    artifacts=artifacts,
                    phase=phase,
                    sequence=sequence,
                    acknowledgement=acknowledgement,
                )
                if accepted_start is None:
                    accepted_start = acknowledgement["acknowledged_monotonic"]
                    artifacts.append(
                        "intervals.jsonl",
                        {
                            "phase": phase,
                            "first_acceptance_utc": acknowledgement["utc"],
                            "first_acceptance_monotonic": accepted_start,
                        },
                    )
                if asset in seen_assets:
                    raise EvidenceError("Asset reused between workloads")
                assets.append(asset)
                seen_assets.add(asset)
                if time.monotonic() >= deadline:
                    raise EvidenceError("Backlog submission deadline exceeded")
            identities = {}
            await wait_jobs(
                private,
                person,
                assets,
                deadline=deadline,
                artifacts=artifacts,
                phase=phase + "-backlog-ready",
                digest=source["sha256"],
                queued=True,
                identities=identities,
            )
            await wait_queue(
                docker,
                [attempt for _, attempt in identities.values()],
                deadline=deadline,
                artifacts=artifacts,
                phase=phase + "-runnable-ready",
            )
            _, current_fixed = await blocking(docker.preflight)
            if current_fixed != fixed:
                raise EvidenceError("Fixed services changed during backlog preparation")
            workers = await blocking(docker.start_workers, count)
            stop = asyncio.Event()
            monitor = asyncio.create_task(
                collect_stats(docker, fixed + workers, artifacts, phase, stop)
            )
            try:
                jobs = await wait_jobs(
                    private,
                    person,
                    assets,
                    deadline=deadline,
                    artifacts=artifacts,
                    phase=phase,
                    digest=source["sha256"],
                    identities=identities,
                )
                makespan = time.monotonic() - accepted_start
                metrics = scaling_metrics(
                    jobs, makespan_seconds=makespan, expected_jobs=len(assets)
                )
                rows = []
                for job in jobs:
                    row = {"repeat": repeat, "workers": count, **job}
                    row["queue_wait_seconds"] = (
                        (instant(job["started_at"]) - instant(job["queued_at"]))
                        if job["started_at"]
                        else None
                    )
                    row["processing_seconds"] = (
                        (instant(job["finished_at"]) - instant(job["started_at"]))
                        if job["started_at"]
                        else None
                    )
                    rows.append(row)
                artifacts.write(phase + "-jobs.json", rows)
                artifacts.csv(phase + "-jobs.csv", rows)
                run = {
                    "repeat": repeat,
                    "workers": count,
                    "metrics": metrics,
                    "worker_quotas": workers,
                    "finished_utc": utc(),
                    "makespan_clock": "host monotonic first acceptance to final terminal read",
                }
            finally:
                stop.set()
                try:
                    usage = await monitor
                finally:
                    await blocking(docker.stop_workers)
            _, current_fixed = await blocking(docker.preflight)
            if current_fixed != fixed:
                raise EvidenceError("Fixed services changed during measured processing")
            run["resource_summary"] = usage
            runs.append(run)
            artifacts.write("runs.json", runs)
        result = scaling_targets(runs, repeats=args.repeats, pilot=args.pilot)
        artifacts.write("targets.json", result)
        artifacts.csv("targets.csv", result["targets"])
        return result
    finally:
        # Stop only our named workers; volumes, private configuration and all Assets remain.
        try:
            await blocking(docker.stop_workers)
        finally:
            await private.close()
            await person["client"].close()


async def latency_phase(people, topic, duration, *, artifacts, repeat, timed, operations=None):
    """Release all clients together. Pace each client from its previous launch."""
    start = time.monotonic()
    end = start + duration
    artifacts.append(
        "intervals.jsonl",
        {
            "topic": topic,
            "repeat": repeat,
            "timed": timed,
            "started_utc": utc(),
            "start_monotonic": start,
            "planned_duration_seconds": duration,
            "clients": len(people),
            "pacing_seconds": 1,
        },
    )
    samples = []

    async def exercise(person):
        sequence = 0
        while time.monotonic() < end:
            launched = time.monotonic()
            client = person["client"]
            if topic == "login":
                # Cookies from previous login cannot authenticate a new login attempt.
                client.http.cookies.clear()
                data, sample = await client.request(
                    "POST", "/api/auth/login", json=person["credentials"]
                )
                if sample["error"] is None and (
                    not isinstance(data, dict)
                    or data.get("id") != person["id"]
                    or not client.http.cookies.get("access_token")
                ):
                    sample["error"] = "invalid_login_session"
            else:
                data, sample = await client.request("GET", "/api/jobs/" + person["asset_id"])
                if sample["error"] is None and (
                    not isinstance(data, dict)
                    or data.get("id") != person["asset_id"]
                    or data.get("status") not in {"queued", "processing", "done", "failed"}
                    or data.get("submission_status") == "pending"
                ):
                    sample["error"] = "invalid_status_response"
                sample["asset_state"] = data.get("status") if isinstance(data, dict) else None
            sequence += 1
            row = {
                "repeat": repeat,
                "topic": topic,
                "client": person["index"],
                "sequence": sequence,
                "route": "/api/auth/login" if topic == "login" else "/api/jobs/{asset_id}",
                "started_offset_seconds": launched - start,
                "observed_utc": utc(),
                **sample,
            }
            artifacts.append("requests.jsonl" if timed else "warmup-requests.jsonl", row)
            samples.append(row)
            if topic == "login":
                _, logout = await client.request("POST", "/api/auth/logout", expected=204)
                operation = {
                    "utc": utc(),
                    "topic": "logout",
                    "operation": "logout",
                    "timed": False,
                    "interval_timed": timed,
                    "repeat": repeat,
                    "client": person["index"],
                    "sequence": sequence,
                    "route": "/api/auth/logout",
                    **logout,
                }
                artifacts.append("operations.jsonl", operation)
                if operations is not None:
                    operations.append(operation)
                client.http.cookies.clear()
            await asyncio.sleep(
                max(0, min(end - time.monotonic(), launched + 1 - time.monotonic()))
            )

    await asyncio.gather(*(exercise(person) for person in people))
    # These are samples launched inside the declared interval, even if they time out after its end.
    if not samples or {s["client"] for s in samples} != {p["index"] for p in people}:
        raise EvidenceError("Not every concurrent client generated attempts")
    return samples


async def performance(args, env, state, artifacts, manifest):
    if not args.login_hash_cost:
        raise EvidenceError(
            "--login-hash-cost required: record verified algorithm/cost from integrated Media"
        )
    docker = Docker(state, artifacts)
    # Performance uses an already running integrated stack, without changing its replicas.
    info = json.loads(await blocking(docker.command, "info", "--format", "{{json .}}"))
    containers = await blocking(docker.all_running)
    artifacts.append(
        "preflight.jsonl",
        {
            "utc": utc(),
            "docker_cpus": info["NCPU"],
            "docker_memory_bytes": info["MemTotal"],
            "cgroup_version": info.get("CgroupVersion"),
            "containers": containers,
        },
    )
    manifest["resources"] = capacity_check(info, containers, state["compose_project"])
    own = [c for c in containers if c["project"] == state["compose_project"]]
    if not FIXED_SERVICES <= {c["service"] for c in own}:
        raise EvidenceError("Integrated fixed services missing for latency tests")
    workers = [c for c in own if c["service"] == "worker"]
    if not 1 <= len(workers) <= 3:
        raise EvidenceError("Latency fixture preparation needs 1–3 running capped workers")
    for worker in workers:
        values = {}
        for name in ("cpu.max", "memory.max", "cpuset.cpus.effective"):
            values[name] = (
                await blocking(
                    docker.command, "exec", worker["id"], "cat", "/sys/fs/cgroup/" + name
                )
            ).strip()
        worker_quota(worker, values)
    manifest["fixed_services"] = own
    manifest["login_hash_cost"] = args.login_hash_cost
    path, source = await blocking(fixture, artifacts.directory, 2)
    manifest["fixture"] = source
    manifest["status_fixture_mix"] = (
        "one distinct completed 2s 720p/audio Asset per authenticated owner"
    )
    artifacts.write("manifest.json", manifest)
    status_people, login_people = [], []
    private = Client(
        f"http://127.0.0.1:{state['processing_port']}",
        headers={"Authorization": "Bearer " + env["PROCESSING_SERVICE_TOKEN"]},
    )
    stop = asyncio.Event()
    monitor = None
    results = []
    try:
        for index in range(args.pilot_status_users if args.pilot else 50):
            person = await owner(state, artifacts, index)
            status_people.append(person)
            person["asset_id"] = await upload(
                person, path, artifacts=artifacts, phase="status-fixtures", sequence=index + 1
            )
            finished = await wait_jobs(
                private,
                person,
                [person["asset_id"]],
                deadline=time.monotonic() + args.job_deadline,
                artifacts=artifacts,
                phase="status-fixtures",
                digest=source["sha256"],
            )
            if finished[0]["state"] != "succeeded" or not finished[0]["has_primary"]:
                raise EvidenceError("Status fixture preparation failed")
        for index in range(args.pilot_login_users if args.pilot else 20):
            login_people.append(await owner(state, artifacts, index))
        manifest["status_assets"] = [p["asset_id"] for p in status_people]
        artifacts.write("manifest.json", manifest)
        monitor = asyncio.create_task(collect_stats(docker, own, artifacts, "performance", stop))
        for topic, people in (("status", status_people), ("login", login_people)):
            for repeat in range(1, args.repeats + 1):
                warmup = args.pilot_warmup_seconds if args.pilot else 30
                duration = args.pilot_seconds if args.pilot else 180
                operations = []
                warm = await latency_phase(
                    people,
                    topic,
                    warmup,
                    artifacts=artifacts,
                    repeat=repeat,
                    timed=False,
                    operations=operations,
                )
                # Separate proposal thresholds from observed errors and protocol validity.
                samples = await latency_phase(
                    people,
                    topic,
                    duration,
                    artifacts=artifacts,
                    repeat=repeat,
                    timed=True,
                    operations=operations,
                )
                metrics = latency_metrics(samples, topic)
                metrics["warmup_errors"] = sum(s["error"] is not None for s in warm)
                metrics["logout_requests"] = len(operations)
                metrics["logout_errors"] = sum(s["error"] is not None for s in operations)
                metrics["protocol_errors"] = sum(
                    s["error"] in {"invalid_login_session", "invalid_status_response"}
                    for s in warm + samples
                )
                metrics["protocol_eligible"] = metrics["protocol_errors"] == 0 and (
                    topic != "status" or metrics["warmup_errors"] == 0
                )
                metrics["clients"] = len(people)
                metrics["planned_duration_seconds"] = duration
                metrics["warmup_seconds"] = warmup
                metrics["all_clients_observed"] = len({s["client"] for s in samples}) == len(people)
                results.append({"topic": topic, "repeat": repeat, "metrics": metrics})
                artifacts.csv(f"{topic}-r{repeat}.csv", samples)
                artifacts.write("runs.json", results)
        return {
            "targets": results,
            "criteria_pass": all(
                r["metrics"]["latency_pass"]
                and (r["topic"] != "status" or r["metrics"]["errors_pass"])
                for r in results
            ),
            "protocol_eligible": all(r["metrics"]["protocol_eligible"] for r in results),
            "operational_errors": sum(
                r["metrics"]["errors"]
                + r["metrics"]["warmup_errors"]
                + r["metrics"]["logout_errors"]
                for r in results
            ),
            "acceptance_eligible": not args.pilot
            and args.repeats >= 3
            and all(r["metrics"]["protocol_eligible"] for r in results),
            "label": "pilot"
            if args.pilot
            else "full local"
            if args.repeats >= 3
            else "single-repeat diagnostic"
            if args.repeats == 1
            else "reduced-repeat diagnostic",
        }
    finally:
        stop.set()
        try:
            if monitor:
                manifest["resource_summary"] = await monitor
        finally:
            await private.close()
            for person in status_people + login_people:
                await person["client"].close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("performance", "scaling"))
    result.add_argument("--run-id", required=True)
    result.add_argument("--repeats", type=int, default=3)
    result.add_argument(
        "--pilot", action="store_true", help="Never eligible for proposal acceptance"
    )
    result.add_argument("--pilot-jobs", type=int, default=3)
    result.add_argument("--pilot-clip-seconds", type=int, default=2)
    result.add_argument("--pilot-status-users", type=int, default=3)
    result.add_argument("--pilot-login-users", type=int, default=2)
    result.add_argument("--pilot-seconds", type=int, default=5)
    result.add_argument("--pilot-warmup-seconds", type=int, default=2)
    result.add_argument(
        "--job-deadline", type=int, default=1800, help="Warmup/backlog deadline seconds"
    )
    result.add_argument("--deadline", type=int, default=36000, help="Whole runner deadline seconds")
    result.add_argument(
        "--login-hash-cost", help="Verified Media algorithm/cost, e.g. bcrypt rounds=12"
    )
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    for name in (
        "repeats",
        "pilot_jobs",
        "pilot_clip_seconds",
        "pilot_status_users",
        "pilot_login_users",
        "pilot_seconds",
        "pilot_warmup_seconds",
        "job_deadline",
        "deadline",
    ):
        if getattr(args, name) < 1:
            raise SystemExit(f"{name.replace('_', '-')} must be positive")
    if args.repeats > 20:
        raise SystemExit("repeats must not exceed 20")
    artifacts = None
    manifest = None
    try:
        env, state = runtime.configure(args.run_id)
        # Runtime credentials never enter artifacts. Accounts remain only in process memory.
        private_values = [
            v
            for k, v in env.items()
            if any(s in k for s in ("PASSWORD", "SECRET", "TOKEN", "DSN", "ACCESS_KEY"))
        ]
        measurement_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        directory = (
            runtime.ROOT / "artifacts/evidence" / args.run_id / (args.action + "-" + measurement_id)
        )
        artifacts = Artifacts(directory, private_values)
        revision = host_command(["git", "rev-parse", "HEAD"]).strip()
        dirty = bool(host_command(["git", "status", "--porcelain"]).strip())
        manifest = {
            "schema_version": "v3-runner-1",
            "status": "running",
            "action": args.action,
            "id": measurement_id,
            "run_id": args.run_id,
            "revision": revision,
            "dirty_tree": dirty,
            "started_utc": utc(),
            "configuration": vars(args),
            "command": ["python", "-m", "scripts.evidence.performance", *(argv or sys.argv[1:])],
            "public_url": state["public_url"],
            "compose_project": state["compose_project"],
            "ca_file": state["ca_file"],
            "environment": {
                "kind": "local",
                "host_os": platform.system(),
                "host_architecture": platform.machine(),
                "host_cpus": os.cpu_count(),
                "generator": "host Python/FFmpeg outside Docker/Lima on the SAME physical host",
            },
            "limitations": [
                "Local evidence only; generator shares physical host with Docker VM.",
                "Direct HTTP runner; browser and Publisher CLI evidence collected separately.",
                "CPU/memory stats are sampled Docker cgroup usage, not exact process peak RSS.",
                "Makespan includes submissions, queueing, publication and observation delay.",
            ],
            "scaling_order": run_order(args.repeats) if args.action == "scaling" else None,
            "worker_limits": {"cpus": 2, "memory_bytes": WORKER_MEMORY},
            "target_freeze": "design08 original targets; parent quota update 1536MiB",
        }
        artifacts.write("manifest.json", manifest)

        async def execute():
            action = scaling if args.action == "scaling" else performance
            return await asyncio.wait_for(
                action(args, env, state, artifacts, manifest), args.deadline
            )

        result = asyncio.run(execute())
        result["acceptance_pass"] = (
            result["criteria_pass"] and result["acceptance_eligible"] and not dirty
        )
        artifacts.write("targets.json", result)
        manifest.update(
            status="completed",
            finished_utc=utc(),
            result=result,
            raw_artifacts=sorted(p.name for p in directory.iterdir()),
        )
        artifacts.write("manifest.json", manifest)
        print(
            f"{result['label']}: criteria {'PASS' if result['criteria_pass'] else 'FAIL'}; "
            f"acceptance {'PASS' if result['acceptance_pass'] else 'OPEN'}; artifacts {directory}"
        )
        return 0 if result["criteria_pass"] and result.get("protocol_eligible", True) else 1
    except (
        EvidenceError,
        OSError,
        TimeoutError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
    ) as exc:
        # Do not stringify transport/process/untrusted payload exceptions.
        message = (
            str(exc)
            if isinstance(exc, EvidenceError)
            else "Runner prerequisite, data or deadline failure"
        )
        if artifacts and manifest:
            manifest.update(
                status="failed",
                finished_utc=utc(),
                failure=message,
                result={"acceptance_pass": False},
            )
            artifacts.write("manifest.json", manifest)
        print("evidence: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
