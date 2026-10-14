"""Bounded LOCAL #38/#39 experiments, separate from historical acceptance runners.

python -m scripts.experiments.followups quota --run-id exp38-20261014
python -m scripts.experiments.followups windows --run-id exp39-20261014
Images must already be built from clean source. See preregistered PROTOCOL.md.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import httpx

from scripts.dev import runtime
from scripts.evidence import performance as p
from scripts.evidence.common import Artifacts, Client, EvidenceError, utc

ROOT = runtime.ROOT
REPORT = ROOT / "docs/execution/experiments-20261014"
PROFILES = {
    "baseline": dict(p.FIXED_CPU),
    "pg-quarter": {**p.FIXED_CPU, "postgres": 0.25, "processing": 0.375},
}
CGROUP = (
    "cpu.max",
    "cpu.stat",
    "cpu.pressure",
    "cpuset.cpus.effective",
    "memory.max",
    "memory.current",
    "memory.peak",
    "memory.events",
    "memory.pressure",
    "io.pressure",
)
WINDOWS = {
    "idle-gap": [(0, 2)] * 3 + [(90, 2)] * 3,
    "burst": [(0, 60)] * 12,
    "sustained": [(n * 20, 60) for n in range(12)],
    "mixed": [(n * 2, 60 if n % 2 == 0 else 2) for n in range(12)],
}


def status(message):
    print(utc(), message, flush=True)
    with (REPORT / "STATUS.txt").open("a") as stream:
        stream.write(utc() + " " + message + "\n")


def supervise_monitor(parent, monitor):
    """Stop new workload actions if required sampling fails; never hide the gap."""

    def finished(task):
        if not task.cancelled() and task.exception() is not None:
            parent.cancel()

    monitor.add_done_callback(finished)


def parse_counters(text):
    return {
        line.split()[0]: int(line.split()[1])
        for line in text.splitlines()
        if len(line.split()) == 2
    }


def queued_age(jobs, now):
    queued = [now - p.instant(j["queued_at"]) for j in jobs if j["state"] == "queued"]
    return max([0, *queued])


def window_metrics(jobs, arrivals, elapsed):
    if len(jobs) != len(arrivals):
        raise EvidenceError("Missing arrival outcome")
    if any(
        j["state"] != "succeeded" or not j["has_primary"] or not j["has_hls"] or j["has_error"]
        for j in jobs
    ):
        raise EvidenceError("Non-successful or incomplete output")
    for field in ("asset_id", "job_id", "attempt_id"):
        if len({j[field] for j in jobs}) != len(jobs):
            raise EvidenceError("Duplicate outcome identity")
    durations = {a["asset_id"]: a["seconds"] for a in arrivals}
    waits = {
        seconds: [
            p.instant(j["started_at"]) - p.instant(j["queued_at"])
            for j in jobs
            if durations[j["asset_id"]] == seconds
        ]
        for seconds in (2, 60)
    }
    return {
        "jobs": len(jobs),
        "successes": len(jobs),
        "elapsed_seconds": elapsed,
        "throughput_jobs_min": len(jobs) * 60 / elapsed,
        "waits_seconds": {str(k): v for k, v in waits.items()},
        "short_wait_p90_seconds": p.p90(waits[2]) if waits[2] else None,
        "maximum_wait_seconds": max(v for values in waits.values() for v in values),
        "processing_seconds": [
            p.instant(j["finished_at"]) - p.instant(j["started_at"]) for j in jobs
        ],
    }


class ExperimentDocker(p.Docker):
    def __init__(self, state, artifacts):
        super().__init__(state, artifacts)
        self.overlay = Path(state["env_file"]).parent / "experiment.override.json"

    def compose(self, *args):
        return runtime.compose(
            self.state, "-f", str(self.overlay), *args, timeout=180, capture_output=True, text=True
        ).stdout

    def profile(self, name):
        quotas = PROFILES[name]
        if sum(quotas.values()) != 2 or set(quotas) != p.FIXED_SERVICES:
            raise EvidenceError("Invalid fixed CPU envelope")
        services = {k: {"cpus": v} for k, v in quotas.items()}
        for service, image in getattr(self, "frozen_images", {}).items():
            services.setdefault(service, {}).update(image=image, pull_policy="never")
        for service in ("media", "processing"):
            services[service].update(
                environment={"PYTHONPATH": "/experiment:/app", "DC2_EXPERIMENT_TIMINGS": "1"},
                volumes=[str(ROOT / "scripts/experiments") + ":/experiment:ro"],
            )
        self.overlay.write_text(json.dumps({"services": services}, indent=2) + "\n")
        self.compose(
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "120",
            "postgres",
            "media",
            "processing",
        )
        info = json.loads(self.command("info", "--format", "{{json .}}"))
        if info["NCPU"] != 8 or info["MemTotal"] < 7 * p.GIB or str(info["CgroupVersion"]) != "2":
            raise EvidenceError("Experimental VM capacity differs from plan")
        own = self.all_running()
        if any(c["project"] != self.state["compose_project"] for c in own):
            raise EvidenceError("Competing namespace")
        for c in own:
            if c["service"] in quotas and c["cpu_limit"] != quotas[c["service"]]:
                raise EvidenceError("Configured quota not applied")
        self.artifacts.append(
            "profiles.jsonl", {"utc": utc(), "profile": name, "quotas": quotas, "containers": own}
        )
        return own

    def running_workers(self):
        return [c for c in self.all_running() if c["service"] == "worker"]

    def sample(self):
        result = []
        for c in self.all_running():
            if c["project"] != self.state["compose_project"]:
                raise EvidenceError("Competing namespace during measurement")
            script = (
                "for f in " + " ".join(CGROUP) + "; do echo FILE:$f; cat /sys/fs/cgroup/$f; done"
            )
            if c["service"] in ("media", "processing"):
                script += (
                    "; echo FILE:timings; "
                    "cat /tmp/dc2-experiment-timings-1.json 2>/dev/null || true"
                )
            text = self.command("exec", c["id"], "sh", "-c", script)
            fields = {}
            for section in text.split("FILE:")[1:]:
                key, _, value = section.partition("\n")
                fields[key] = value.strip()
            if c["service"] == "worker":
                p.worker_quota(
                    c,
                    {k: fields[k] for k in ("cpu.max", "memory.max", "cpuset.cpus.effective")}
                    if "cpuset.cpus.effective" in fields
                    else {
                        "cpu.max": fields["cpu.max"],
                        "memory.max": fields["memory.max"],
                        "cpuset.cpus.effective": self.command(
                            "exec", c["id"], "cat", "/sys/fs/cgroup/cpuset.cpus.effective"
                        ).strip(),
                    },
                )
            if parse_counters(fields["memory.events"]).get("oom_kill", 0):
                raise EvidenceError("OOM kill in owned container")
            result.append({"container": c, "cgroup": fields})
        host = self.compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            "cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io; "
            "df -Pk /var/lib/postgresql/data; cat /proc/meminfo",
        )
        disk = next(
            line.split()
            for line in host.splitlines()
            if len(line.split()) == 6 and line.split()[0].startswith("/dev/")
        )
        if int(disk[3]) * 1024 < 2 * p.GIB:
            raise EvidenceError("VM free space below preregistered 2GiB stop")
        return {"containers": result, "vm_pressure_disk_memory": host}

    async def drain(self, ids=None):
        """Warm RQ shutdown, no force-kill fallback. Refuse unowned IDs."""
        ids = [c["id"] for c in self.running_workers()] if ids is None else ids
        before = self.worker_states(ids) if ids else []
        if any(not c["running"] or c["paused"] for c in before):
            raise EvidenceError("Drain requires running unpaused owned workers")
        started = time.monotonic()
        for c in before:
            await p.blocking(self.command, "kill", "--signal", "SIGTERM", c["id"])
        while ids:
            states = await p.blocking(self.worker_states, ids)
            if not any(c["running"] for c in states):
                exits = json.loads(await p.blocking(self.command, "inspect", *ids))
                if any(c["State"]["ExitCode"] != 0 or c["State"]["OOMKilled"] for c in exits):
                    raise EvidenceError("Drain exited abnormally")
                break
            if time.monotonic() - started >= 300:
                raise EvidenceError("Warm drain exceeds 300s; leave outcomes intact for recovery")
            await asyncio.sleep(1)
        lifetimes = []
        if ids:
            for container in json.loads(await p.blocking(self.command, "inspect", *ids)):
                lifetimes.append(
                    {
                        "id": container["Id"],
                        "started_at": container["State"]["StartedAt"],
                        "finished_at": container["State"]["FinishedAt"],
                        "exit_code": container["State"]["ExitCode"],
                        "oom_killed": container["State"]["OOMKilled"],
                    }
                )
        self.artifacts.append(
            "drains.jsonl",
            {
                "utc": utc(),
                "workers": ids,
                "elapsed_seconds": time.monotonic() - started,
                "signal": "SIGTERM",
                "forced": False,
                "lifetimes": lifetimes,
            },
        )
        return time.monotonic() - started


async def database(env, state):
    return await asyncpg.connect(
        user="postgres",
        password=env["POSTGRES_PASSWORD"],
        database="postgres",
        host="127.0.0.1",
        port=state["postgres_port"],
        timeout=10,
    )


async def monitor(docker, env, state, artifacts, phase, stop):
    conn = await database(env, state)
    try:
        while not stop.is_set():
            start = time.monotonic()
            sample = await p.blocking(docker.sample)
            waits = await conn.fetch(
                "SELECT datname,state,wait_event_type,wait_event,count(*) AS sessions "
                "FROM pg_stat_activity WHERE pid<>pg_backend_pid() "
                "GROUP BY datname,state,wait_event_type,wait_event",
                timeout=10,
            )
            stats = await conn.fetch(
                "SELECT datname,xact_commit,xact_rollback,blks_read,blks_hit,"
                "blk_read_time,blk_write_time,deadlocks FROM pg_stat_database "
                "WHERE datname IN ('media_db','processing_db')",
                timeout=10,
            )
            artifacts.append(
                "telemetry.jsonl",
                {
                    "utc": utc(),
                    "monotonic": time.monotonic(),
                    "phase": phase,
                    "server_waits": [dict(r) for r in waits],
                    "database_counters": [dict(r) for r in stats],
                    **sample,
                    "sample_duration_seconds": time.monotonic() - start,
                },
            )
            try:
                await asyncio.wait_for(stop.wait(), 5)
            except TimeoutError:
                pass
    finally:
        await conn.close()


def decoded(state, run_id, person, result):
    """Reuse the repository's scoped-trust browser and actual decoded-frame gates."""
    from scripts.dev.browser import trusted_browser
    from scripts.dev.e2e_clients import BrowserMediaRequests, browser_playback

    class Recording:
        def __init__(self):
            self.state, self.artifacts, self.events = state, ROOT / "artifacts" / run_id, []

        def record(self, event, **values):
            self.events.append({"event": event, **values})

    recording = Recording()
    recording.artifacts.mkdir(parents=True, exist_ok=True)
    with trusted_browser(run_id) as browser:
        # Copy session only in memory; no cookie artifact.
        browser.add_cookies(
            [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": "localhost",
                    "path": c.path,
                    "secure": c.secure,
                    "httpOnly": True,
                }
                for c in person["client"].http.cookies.jar
            ]
        )
        page = browser.new_page()
        media = BrowserMediaRequests()
        transfers = []

        def completed(request):
            response = request.response()
            if response is None:
                return
            media.seen(response)
            path = urlsplit(response.url).path
            if path.endswith((".mp4", ".ts", ".m3u8")):
                transfers.append(
                    {
                        "kind": Path(path).suffix,
                        "status": response.status,
                        "bytes": len(response.body()) if response.status in (200, 206) else 0,
                        "method": request.method,
                    }
                )

        page.on("requestfinished", completed)
        page.goto(state["public_url"], wait_until="domcontentloaded", timeout=30000)
        page.locator("#app").wait_for(state="visible", timeout=30000)
        page.evaluate(
            "result => {document.querySelector('#active-job').hidden=false; "
            "window.mountPlayer(document.querySelector('#player'), result);}",
            result,
        )
        browser_playback(page, recording, result, media)
        # Allow requestfinished callbacks for completed reads before aggregating.
        page.wait_for_timeout(300)
        return {
            "decoded": recording.events,
            "transfers": transfers,
            "requests": len(transfers),
            "transfer_bytes": sum(t["bytes"] for t in transfers),
        }


class Trial:
    def __init__(self, args):
        self.args = args
        self.env, self.state = runtime.configure(args.run_id)
        directory = (
            ROOT / "artifacts" / args.run_id / (args.action + "-" + time.strftime("%Y%m%dT%H%M%S"))
        )
        self.artifacts = Artifacts(
            directory,
            [self.env[k] for k in self.env if any(s in k for s in ("PASSWORD", "SECRET", "TOKEN"))],
        )
        self.docker = ExperimentDocker(self.state, self.artifacts)
        self.docker.frozen_images = {
            c["service"]: c["image_digest"]
            for c in self.docker.all_running()
            if c["project"] == self.state["compose_project"]
        }
        self.private = Client(
            f"http://127.0.0.1:{self.state['processing_port']}",
            headers={"Authorization": "Bearer " + self.env["PROCESSING_SERVICE_TOKEN"]},
        )
        self.people = []
        self.paths = {}
        self.fixtures = {}
        self.results = []
        self.manifest = {
            "scope": "LOCAL experimental",
            "started_utc": utc(),
            "command": os.sys.argv,
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "protocol_sha256": hashlib.sha256((REPORT / "PROTOCOL.md").read_bytes()).hexdigest(),
            "profiles": PROFILES,
            "run_id": args.run_id,
            "fixture": self.fixtures,
        }
        self.artifacts.write("manifest.json", self.manifest)

    async def fixtures_prepare(self):
        for seconds in (2, 60):
            directory = ROOT / ".local" / "experiment-fixtures" / str(seconds)
            directory.mkdir(parents=True, exist_ok=True)
            if (directory / "metadata.json").exists():
                source = json.loads((directory / "metadata.json").read_text())
                path = directory / "source.mp4"
                if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                    raise EvidenceError("Cached fixture changed")
            else:
                path, source = await p.blocking(p.fixture, directory, seconds)
                (directory / "metadata.json").write_text(json.dumps(source, indent=2))
            self.paths[seconds], self.fixtures[seconds] = path, source
        self.manifest["images"] = await p.blocking(self.docker.all_running)
        self.manifest["source_files"] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in (
                "scripts/experiments",
                "media",
                "processing",
                "media_engine",
                "compose/local",
                "deploy",
            )
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.manifest["build_labels"] = runtime.build_labels()
        self.artifacts.write("manifest.json", self.manifest)

    async def person(self, index):
        person = await p.owner(self.state, self.artifacts, index)
        self.people.append(person)
        return person

    async def completed(self, person, assets, phase, seconds=2):
        jobs = await p.wait_jobs(
            self.private,
            person,
            assets,
            deadline=time.monotonic() + 1800,
            artifacts=self.artifacts,
            phase=phase,
            digest=self.fixtures[seconds]["sha256"],
        )
        if any(
            j["state"] != "succeeded" or not j["has_primary"] or not j["has_hls"] or j["has_error"]
            for j in jobs
        ):
            raise EvidenceError("Outcome/quality gate failed")
        return jobs

    async def delete(self, person, assets):
        for asset in assets:
            await person["client"].checked(
                "DELETE",
                "/api/jobs/" + asset,
                expected=204,
                artifacts=self.artifacts,
                record={"operation": "experiment-delete", "asset_id": asset},
            )

    async def hash_cost(self, people, phase):
        code = """import asyncio,json,os,asyncpg
async def main():
 c=await asyncpg.connect(os.environ['MEDIA_POSTGRES_DSN'].replace('postgresql+asyncpg://','postgresql://'))
 try:
  query=("SELECT id::text AS owner_id,split_part(password_hash,'$',2) AS algorithm,"
         "split_part(password_hash,'$',3) AS cost FROM users WHERE id::text=ANY($1::text[])")
  rows=await c.fetch(query,IDS)
  print(json.dumps([dict(r) for r in rows]))
 finally: await c.close()
asyncio.run(main())
""".replace("IDS", repr([person["id"] for person in people]))
        rows = json.loads(
            await p.blocking(self.docker.compose, "exec", "-T", "media", "python", "-c", code)
        )
        if len(rows) != len(people) or any(
            r["cost"] != "10" or r["algorithm"] not in ("2b", "2a") for r in rows
        ):
            raise EvidenceError("Measured-account bcrypt cost differs from frozen source")
        self.artifacts.append("hash-costs.jsonl", {"phase": phase, "accounts": rows})

    async def latency(self, people, topic, repeat, phase):
        warm = await p.latency_phase(
            people, topic, 30, artifacts=self.artifacts, repeat=phase + "-warm", timed=False
        )
        samples = await p.latency_phase(
            people, topic, 180, artifacts=self.artifacts, repeat=phase, timed=True
        )
        metrics = p.latency_metrics(samples, topic)
        metrics["warmup_errors"] = sum(s["error"] is not None for s in warm)
        self.artifacts.append(
            "latency-results.jsonl",
            {"phase": phase, "repeat": repeat, "topic": topic, "metrics": metrics},
        )
        status(
            f"{phase} {topic} n={metrics['requests']} "
            f"p90={metrics['p90_ms']:.1f}ms errors={metrics['errors']}"
        )
        return metrics

    async def quota_arm(self, profile, repeat):
        phase = f"r{repeat}-{profile}"
        await self.docker.drain()
        await p.blocking(self.docker.profile, profile)
        await p.blocking(self.docker.start_workers, 3)
        status(phase + " preparation:50 status owners/20 login owners")
        statuses, logins = [], []
        for index in range(50):
            person = await self.person(index)
            person["asset_id"] = await p.upload(
                person, self.paths[2], artifacts=self.artifacts, phase=phase + "-status-fixture"
            )
            await self.completed(person, [person["asset_id"]], phase)
            statuses.append(person)
        for index in range(20):
            logins.append(await self.person(index))
        await self.hash_cost(statuses + logins, phase)
        stop = asyncio.Event()
        telemetry = asyncio.create_task(
            monitor(self.docker, self.env, self.state, self.artifacts, phase, stop)
        )
        supervise_monitor(asyncio.current_task(), telemetry)
        try:
            isolated = {}
            for topic, people in (("status", statuses), ("login", logins)):
                isolated[topic] = await self.latency(
                    people, topic, repeat, phase + "-isolated-" + topic
                )
            # Renew outside mixed timing and check cross-owner response explicitly.
            for person in statuses:
                await p.renew_session(person, self.artifacts, phase)
            await statuses[1]["client"].checked(
                "GET",
                "/api/jobs/" + statuses[0]["asset_id"],
                expected=404,
                artifacts=self.artifacts,
                record={"operation": "wrong-owner-check"},
            )
            publisher = await self.person(70)
            # Uploads have no numeric latency gate; observe the complete body/ACK.
            publisher["client"].timeout = 120
            publisher["client"].http.timeout = httpx.Timeout(120)
            playback = await statuses[0]["client"].checked(
                "GET", "/api/jobs/" + statuses[0]["asset_id"]
            )
            arrivals, batch_assets = [], []

            async def batch():
                started = time.monotonic()
                for index in range(30):
                    acknowledgement = {}
                    asset = await p.upload(
                        publisher,
                        self.paths[60],
                        artifacts=self.artifacts,
                        phase=phase + "-mixed",
                        sequence=index + 1,
                        acknowledgement=acknowledgement,
                    )
                    batch_assets.append(asset)
                    arrivals.append(
                        {"asset_id": asset, "seconds": 60, "offset": time.monotonic() - started}
                    )
                    self.artifacts.append("arrivals.jsonl", {"phase": phase, **arrivals[-1]})
                jobs = await self.completed(publisher, batch_assets, phase + "-mixed", 60)
                metrics = p.scaling_metrics(
                    jobs, makespan_seconds=time.monotonic() - started, expected_jobs=30
                )
                self.artifacts.write(phase + "-jobs.json", jobs)
                return metrics

            async def play():
                await asyncio.sleep(50)
                record = await p.blocking(
                    decoded, self.state, self.args.run_id, statuses[0], playback
                )
                self.artifacts.append("playback.jsonl", {"phase": phase, **record})

            status(phase + " mixed:50 status+20 login+fresh30x60s+decoded playback")
            mixed_status, mixed_login, batch_metrics, _ = await asyncio.gather(
                self.latency(statuses, "status", repeat, phase + "-mixed-status"),
                self.latency(logins, "login", repeat, phase + "-mixed-login"),
                batch(),
                play(),
            )
            record = {
                "repeat": repeat,
                "profile": profile,
                "isolated": isolated,
                "mixed": {"status": mixed_status, "login": mixed_login},
                "batch": batch_metrics,
            }
            self.results.append(record)
            self.artifacts.write("results.json", self.results)
            # Record actual retained object sizes/count using Processing's output metadata.
            await self.output_inventory(publisher, batch_assets, phase)
            await self.delete(publisher, batch_assets)
            for person in statuses:
                await self.delete(person, [person["asset_id"]])
            status(
                phase + f" complete:30/30 throughput={batch_metrics['throughput_jobs_min']:.3f}/min"
            )
        finally:
            stop.set()
            await telemetry
        for person in statuses + logins + [publisher]:
            await person["client"].close()
            self.people.remove(person)

    async def output_inventory(self, person, assets, phase):
        jobs = await self.private.checked(
            "GET",
            "/internal/v1/jobs",
            params={"asset_ids": ",".join(assets)},
            headers={"X-Owner-Id": person["id"]},
        )
        if any(sum(o["kind"] == "primary" for o in j["outputs"]) != 1 for j in jobs):
            raise EvidenceError("Output inventory does not have exactly one primary per job")
        records = [
            {
                "asset_id": j["asset_id"],
                "outputs": [
                    {"kind": o["kind"], "size_bytes": o["size_bytes"]} for o in j["outputs"]
                ],
            }
            for j in jobs
        ]
        # Metadata registers primary+master only. List the Processing-owned
        # attempt prefix to include every rendition playlist/segment before delete.
        attempts = [p.attempt_record(j, owner=person["id"], assets=assets) for j in jobs]
        pairs = [(j["job_id"], j["attempt_id"]) for j in attempts]
        code = """import json
from uuid import UUID
from pathlib import Path
from collections import Counter
from processing.config import get_settings
from processing.recovery import CleanupStore
from processing.lifecycle import output_prefix
store=CleanupStore(get_settings())
rows=[]
for job,attempt in PAIRS:
 counts=Counter();sizes=Counter()
 prefix=output_prefix(UUID(job),UUID(attempt))
 for item in store.client.list_objects(store.bucket,prefix=prefix,recursive=True):
  suffix=Path(item.object_name).suffix
  counts[suffix]+=1;sizes[suffix]+=item.size
 rows.append({'job_id':job,'attempt_id':attempt,'objects':sum(counts.values()),
              'bytes':sum(sizes.values()),'counts_by_extension':dict(counts),
              'bytes_by_extension':dict(sizes)})
print(json.dumps(rows))
""".replace("PAIRS", repr(pairs))
        actual = json.loads(
            await p.blocking(
                self.docker.compose, "exec", "-T", "processing-recovery", "python", "-c", code
            )
        )
        if len(actual) != len(jobs) or any(
            r["counts_by_extension"].get(".mp4") != 1 or r["counts_by_extension"].get(".ts", 0) < 1
            for r in actual
        ):
            raise EvidenceError("Actual output inventory incomplete or duplicate primary")
        self.artifacts.append(
            "actual-objects.jsonl",
            {
                "phase": phase,
                "attempts": actual,
                "output_bytes": sum(r["bytes"] for r in actual),
                "objects": sum(r["objects"] for r in actual),
            },
        )
        self.artifacts.append(
            "outputs.jsonl",
            {
                "phase": phase,
                "jobs": records,
                "output_bytes": sum(o["size_bytes"] or 0 for j in records for o in j["outputs"]),
                "objects": sum(len(j["outputs"]) for j in records),
            },
        )

    async def quota(self):
        await p.blocking(self.docker.profile, "baseline")
        await self.fixtures_prepare()
        for repeat, order in enumerate(
            (("baseline", "pg-quarter"), ("pg-quarter", "baseline"), ("baseline", "pg-quarter")), 1
        ):
            for profile in order:
                await self.quota_arm(profile, repeat)
        gates = all(
            m["latency_pass"] and m["errors"] == 0 and m["warmup_errors"] == 0
            for r in self.results
            if r["profile"] == "pg-quarter"
            for category in ("isolated", "mixed")
            for m in r[category].values()
        )
        improvements = [
            next(r for r in self.results if r["repeat"] == n and r["profile"] == "pg-quarter")[
                "isolated"
            ]["status"]["p90_ms"]
            / next(r for r in self.results if r["repeat"] == n and r["profile"] == "baseline")[
                "isolated"
            ]["status"]["p90_ms"]
            for n in (1, 2, 3)
        ]
        decision = {
            "status": "REJECT"
            if not gates or any(v > 0.95 for v in improvements)
            else "REVIEW_REQUIRED",
            "all_latency_gates": gates,
            "paired_status_p90_ratios": improvements,
            "adopted": False,
            "causality_and_fault_review_required": True,
        }
        self.artifacts.write("decision.json", decision)
        status(
            "#38 workload decision: "
            + decision["status"]
            + "; fault/release disposition follows separately"
        )
        await self.docker.drain()
        await p.blocking(self.docker.profile, "baseline")

    async def window(self, policy, repeat, name, person, statuses, logins):
        phase = f"r{repeat}-{policy}-{name}"
        count = int(policy) if policy != "manual" else (1 if name == "idle-gap" else 3)
        # Explicit preplanned operator commands, never a queue-driven controller.
        launched = time.monotonic()
        await p.blocking(self.docker.start_workers, count)
        startup = time.monotonic() - launched
        self.artifacts.append(
            "operator-actions.jsonl",
            {
                "phase": phase,
                "action": "activate",
                "workers": count,
                "reason": "predeclared operator processing window",
                "startup_seconds": startup,
            },
        )
        started = time.monotonic()
        stop = asyncio.Event()
        telemetry = asyncio.create_task(
            monitor(self.docker, self.env, self.state, self.artifacts, phase, stop)
        )
        assets, arrivals = [], []
        identities = {}
        max_age = 0
        last_arrival = None

        async def submit():
            nonlocal last_arrival
            for index, (offset, seconds) in enumerate(WINDOWS[name]):
                await asyncio.sleep(max(0, started + offset - time.monotonic()))
                acknowledgement = {}
                launched = time.monotonic()
                asset = await p.upload(
                    person,
                    self.paths[seconds],
                    artifacts=self.artifacts,
                    phase=phase,
                    sequence=index + 1,
                    acknowledgement=acknowledgement,
                )
                assets.append(asset)
                last_arrival = time.monotonic()
                arrival = {
                    "asset_id": asset,
                    "seconds": seconds,
                    "scheduled_offset_seconds": offset,
                    "launched_offset_seconds": launched - started,
                    "acknowledged_offset_seconds": last_arrival - started,
                    "upload_elapsed_ms": acknowledgement["elapsed_ms"],
                    "utc": utc(),
                }
                arrivals.append(arrival)
                self.artifacts.append("arrivals.jsonl", {"phase": phase, **arrival})

        supervise_monitor(asyncio.current_task(), telemetry)
        submission = asyncio.create_task(submit())
        interactive = []
        if name == "sustained":
            for owner in statuses:
                await p.renew_session(owner, self.artifacts, phase)
            for topic, people in (("status", statuses), ("login", logins)):
                interactive.append(
                    asyncio.create_task(
                        self.latency(people, topic, repeat, phase + "-mixed-" + topic)
                    )
                )
        try:
            while True:
                jobs = (
                    await p.processing_read(
                        self.private, person, list(assets), artifacts=self.artifacts, phase=phase
                    )
                    if assets
                    else []
                )
                for job in jobs:
                    identity = job["job_id"], job["attempt_id"]
                    if job["asset_id"] in identities and identities[job["asset_id"]] != identity:
                        raise EvidenceError("Changed attempt during scheduling trial")
                    identities[job["asset_id"]] = identity
                age = queued_age(jobs, time.time())
                max_age = max(age, max_age)
                self.artifacts.append(
                    "queue-age.jsonl",
                    {
                        "phase": phase,
                        "utc": utc(),
                        "oldest_seconds": age,
                        "jobs": jobs,
                        "workers": count,
                    },
                )
                if submission.done():
                    await submission
                    if len(jobs) == len(arrivals) and all(j["state"] in p.TERMINAL for j in jobs):
                        break
                if time.monotonic() - started > 1500:
                    raise EvidenceError("Window hard deadline exceeded")
                await asyncio.sleep(2)
            elapsed = time.monotonic() - started
            latency = await asyncio.gather(*interactive)
            durations = {a["asset_id"]: a["seconds"] for a in arrivals}
            if any(
                j["source_sha256"] != self.fixtures[durations[j["asset_id"]]]["sha256"]
                for j in jobs
            ):
                raise EvidenceError("Window source digest changed")
            metrics = window_metrics(jobs, arrivals, elapsed)
            if latency:
                metrics["mixed_latency"] = dict(zip(("status", "login"), latency, strict=True))
            metrics.update(
                maximum_observed_queue_age_seconds=max_age,
                after_last_arrival_drain_seconds=time.monotonic() - last_arrival,
                queue_bound_pass=max_age <= 300 and metrics["maximum_wait_seconds"] <= 300,
                sustained_drain_pass=name != "sustained" or time.monotonic() - last_arrival <= 300,
                worker_seconds=count * elapsed,
                startup_seconds=startup,
            )
            self.artifacts.write(phase + "-jobs.json", jobs)
            await self.output_inventory(person, assets, phase)
            # Idle residency belongs to this window's resource budget.
            await asyncio.sleep(60)
            if policy == "manual" and count > 1:
                workers = await p.blocking(self.docker.running_workers)
                drain_seconds = await self.docker.drain([w["id"] for w in workers[1:]])
                metrics["idle_worker_seconds"] = count * 60
                metrics["safe_drain_seconds"] = drain_seconds
            else:
                metrics["idle_worker_seconds"] = count * 60
            record = {"repeat": repeat, "policy": policy, "window": name, "metrics": metrics}
            self.results.append(record)
            self.artifacts.write("results.json", self.results)
            await self.delete(person, assets)
            status(
                phase + f" complete:{len(jobs)}/{len(jobs)} maxage={max_age:.1f}s "
                f"worker-seconds={metrics['worker_seconds']:.1f}"
            )
        finally:
            for task in interactive:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*interactive, return_exceptions=True)
            if not submission.done():
                submission.cancel()
                await asyncio.gather(submission, return_exceptions=True)
            stop.set()
            await telemetry

    async def windows(self):
        await p.blocking(self.docker.profile, "baseline")
        await self.fixtures_prepare()
        policies = ("1", "2", "3", "manual")
        for repeat in (1, 2, 3):
            order = policies[repeat - 1 :] + policies[: repeat - 1]
            statuses, logins = [], []
            await p.blocking(self.docker.start_workers, 3)
            for index in range(50):
                owner = await self.person(index)
                owner["asset_id"] = await p.upload(
                    owner,
                    self.paths[2],
                    artifacts=self.artifacts,
                    phase=f"r{repeat}-status-fixtures",
                )
                await self.completed(owner, [owner["asset_id"]], "window-status-preparation")
                statuses.append(owner)
            for index in range(20):
                logins.append(await self.person(index))
            await self.hash_cost(statuses + logins, f"r{repeat}-window-accounts")
            for policy in order:
                await self.docker.drain()
                arm_start = utc()
                activation_started = time.monotonic()
                await p.blocking(
                    self.docker.start_workers, int(policy) if policy != "manual" else 1
                )
                self.artifacts.append(
                    "cold-activations.jsonl",
                    {
                        "repeat": repeat,
                        "policy": policy,
                        "command_seconds": time.monotonic() - activation_started,
                        "started_utc": arm_start,
                        "running_verified_utc": utc(),
                    },
                )
                person = await self.person(70)
                person["client"].timeout = 120
                person["client"].http.timeout = httpx.Timeout(120)
                for name in WINDOWS:
                    await p.renew_session(person, self.artifacts, f"r{repeat}-{policy}-{name}")
                    await self.window(policy, repeat, name, person, statuses, logins)
                await self.docker.drain()
                self.artifacts.append(
                    "policy-spans.jsonl",
                    {
                        "repeat": repeat,
                        "policy": policy,
                        "started_utc": arm_start,
                        "finished_utc": utc(),
                    },
                )
                await person["client"].close()
                self.people.remove(person)
            for owner in statuses:
                await self.delete(owner, [owner["asset_id"]])
            for owner in statuses + logins:
                await owner["client"].close()
                self.people.remove(owner)
        self.artifacts.write(
            "decision.json",
            {
                "status": "REVIEW_REQUIRED",
                "adopted": False,
                "reason": "Review workload, fault, latency and worker-residency evidence",
            },
        )
        await self.docker.drain()

    async def run(self):
        try:
            await getattr(self, self.args.action)()
            self.artifacts.write("completion.json", {"status": "completed", "utc": utc()})
        except BaseException as error:
            self.artifacts.write(
                "failure.json",
                {
                    "utc": utc(),
                    "type": type(error).__name__,
                    "safe_error": str(error) if isinstance(error, EvidenceError) else None,
                },
            )
            status(self.args.action + " STOP:" + type(error).__name__)
            raise
        finally:
            await self.private.close()
            for person in self.people:
                await person["client"].close()
        status("Raw evidence: " + str(self.artifacts.directory.relative_to(ROOT)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("quota", "windows"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.startswith("exp38-" if args.action == "quota" else "exp39-"):
        parser.error("Experiment run IDs must begin exp38-/exp39-")
    asyncio.run(Trial(args).run())


if __name__ == "__main__":
    main()
