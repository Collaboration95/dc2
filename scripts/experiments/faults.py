"""LOCAL fault/release adjunct; unchanged historical recovery/release assertions.

python -m scripts.experiments.faults --run-id exp38-20261014 --profile baseline
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import time
from types import SimpleNamespace

from scripts.dev import runtime
from scripts.dev.release import Runner
from scripts.dev.scenario import Scenario
from scripts.evidence import performance as p
from scripts.evidence import recovery
from scripts.evidence.common import Artifacts, Client, EvidenceError, utc
from scripts.experiments.followups import REPORT, ExperimentDocker, decoded, status


class ExperimentRelease(Runner):
    """Apply only preregistered CPU/telemetry overlay to historical release steps."""

    def command(self, args, **kwargs):
        # The inherited scanner uses the common-root cache. Route only its cache
        # to this worktree; pinned binary, DB bytes, offline/exact-image gates stay.
        if "--cache-dir" in args:
            args = list(args)
            args[args.index("--cache-dir") + 1] = str(self.root / ".cache/trivy-experiments")
        return super().command(args, **kwargs)

    def compose(self, *args, **kwargs):
        overlay = runtime.ROOT / ".local/runs" / self.run_id / "experiment.override.json"
        return super().compose("-f", str(overlay), *args, **kwargs)


class ReadyGuard:
    """Wait for public readiness after the historical process restoration."""

    def __init__(self, scenario, guard):
        self.scenario, self.guard = scenario, guard

    def __enter__(self):
        return self.guard.__enter__()

    def __exit__(self, *args):
        result = self.guard.__exit__(*args)
        started = time.monotonic()
        client = self.scenario.client()
        while time.monotonic() - started < 120:
            try:
                ready = client.get("health", timeout=2).status_code == 200
            except Exception:
                ready = False
            if ready:
                self.scenario.record(
                    "restoration-http-ready",
                    bound_seconds=120,
                    elapsed_seconds=time.monotonic() - started,
                )
                return result
            time.sleep(0.5)
        raise EvidenceError("Public restoration readiness exceeded120s")


class ExperimentScenario(Scenario):
    def restore_services(self, *services):
        return ReadyGuard(self, super().restore_services(*services))


async def drain_long(run_id, docker, artifacts, env, state):
    """A real >60s active encode must survive warm draining without a retry."""
    folder = runtime.ROOT / ".local/experiment-fixtures/180"
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "metadata.json").exists():
        source = json.loads((folder / "metadata.json").read_text())
        path = folder / "source.mp4"
    else:
        path, source = await p.blocking(p.fixture, folder, 180)
        (folder / "metadata.json").write_text(json.dumps(source, indent=2))
    await docker.drain()
    await p.blocking(docker.start_workers, 1)
    person = await p.owner(state, artifacts, 0)
    private = Client(
        f"http://127.0.0.1:{state['processing_port']}",
        headers={"Authorization": "Bearer " + env["PROCESSING_SERVICE_TOKEN"]},
    )
    try:
        asset = await p.upload(person, path, artifacts=artifacts, phase="active-long-drain")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            jobs = await p.processing_read(
                private, person, [asset], artifacts=artifacts, phase="active-long-before"
            )
            if jobs and jobs[0]["state"] == "processing":
                before = jobs[0]
                break
            await asyncio.sleep(0.5)
        else:
            raise EvidenceError("Long drain did not capture processing")
        workers = await p.blocking(docker.running_workers)
        drained = await docker.drain([w["id"] for w in workers])
        jobs = await p.wait_jobs(
            private,
            person,
            [asset],
            deadline=time.monotonic() + 30,
            artifacts=artifacts,
            phase="active-long-after",
            digest=source["sha256"],
            identities={asset: (before["job_id"], before["attempt_id"])},
        )
        job = jobs[0]
        processing = p.instant(job["finished_at"]) - p.instant(job["started_at"])
        if (
            job["state"] != "succeeded"
            or not job["has_primary"]
            or not job["has_hls"]
            or processing <= 60
            or drained <= 60
        ):
            raise EvidenceError("Long drain did not prove >60s successful active processing")
        artifacts.write(
            "active-long-drain.json",
            {
                "utc": utc(),
                "fixture": source,
                "before": before,
                "after": job,
                "processing_seconds": processing,
                "drain_seconds": drained,
                "forced": False,
            },
        )
        await person["client"].checked("DELETE", "/api/jobs/" + asset, expected=204)
    finally:
        await private.close()
        await person["client"].close()


def run(args):
    env, state = runtime.configure(args.run_id)
    cache = runtime.ROOT / ".cache/trivy-experiments"
    if not (cache / "db/trivy.db").exists():
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(runtime.common_root() / ".cache/trivy/db", cache / "db")
    directory = (
        runtime.ROOT
        / "artifacts"
        / args.run_id
        / ("faults-" + args.profile + "-" + time.strftime("%Y%m%dT%H%M%S"))
    )
    artifacts = Artifacts(directory)
    docker = ExperimentDocker(state, artifacts)
    asyncio.run(docker.drain())
    docker.profile(args.profile)
    docker.start_workers(1)
    # Persist the same experimental profile so unchanged Scenario/ServiceGuard
    # commands honor it, while exact candidate overrides remain last in release.
    persisted = json.loads(docker.overlay.read_text())
    for container in docker.all_running():
        persisted["services"].setdefault(container["service"], {}).update(
            image=container["image_digest"], pull_policy="never"
        )
    (runtime.ROOT / ".local/runs" / args.run_id / "release.override.json").write_text(
        json.dumps(persisted, indent=2)
    )
    # Scan the distinct live Media image as well as the Processing images that
    # the unchanged release runner scans below. Use only our local cache.
    media_gate = ExperimentRelease(args.run_id)
    media_gate.run_id = args.run_id
    media_gate.begin("experimental-media-artifact", 600)
    media_gate.operation["docker_capacity"] = media_gate.local_preflight()
    source_proof = media_gate.source()
    media_image = next(c["image_digest"] for c in docker.all_running() if c["service"] == "media")
    info = media_gate.image_info(media_image)
    if (
        info["revision"] != source_proof["revision"]
        or info["source_fingerprint"] != source_proof["source_fingerprint"]
    ):
        raise EvidenceError("Live Media source/image mismatch before gates")
    media_scan = media_gate.scan(media_image)
    media_gate.command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            media_image,
            "-c",
            "import media.main,media.recovery",
        ]
    )
    db = cache / "db/trivy.db"
    with db.open("rb") as stream:
        db_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    artifacts.write(
        "media-artifact.json",
        {
            "source": source_proof,
            "image": info,
            "scan": media_scan,
            "offline_imports_pass": True,
            "trivy_db_sha256": db_digest,
        },
    )
    media_gate.finish("passed")
    scenario = ExperimentScenario(args.run_id, "experimental-" + args.profile + "-recovery")
    path = runtime.ROOT / ".local/experiment-fixtures/60/source.mp4"
    try:
        scenario.report["fixture"] = json.loads(path.with_name("metadata.json").read_text())
        for _ in range(3 if args.window_faults else 1):
            recovery.worker_kill(scenario, path)
            recovery.queue_loss(scenario, path)
            recovery.processing_outage(scenario, path)
            if args.window_faults:
                durable_restart(scenario, path)
                redis_loss(scenario, path)
        scenario.finish()
        artifacts.write("recovery-result.json", scenario.report)
        status(args.run_id + " " + args.profile + " worker-loss/queue-loss/outage PASS")
    except BaseException as error:
        scenario.finish(error)
        raise
    if args.long_drain:
        asyncio.run(drain_long(args.run_id, docker, artifacts, env, state))
        status(args.run_id + " >60s active warm-drain PASS")
        docker.start_workers(1)
    # Existing runner owns exact-image tests/scans, real active work, injected bad
    # startup, tested-image restoration and unchanged Media checks.
    release = ExperimentRelease(args.run_id)
    release.run_id = args.run_id
    with release.locked():
        result = release.evidence()
    artifacts.write(
        "release-result.json",
        {"exit": result, "journal": release.journal, "operation": release.operation},
    )
    if result:
        raise EvidenceError("Historical good/bad release gate failed; inspect retained operation")
    status(args.run_id + " " + args.profile + " exact-image good/bad release PASS")
    if args.window_faults:
        active_rollback(args, docker, artifacts, release)
    (REPORT / "STATUS.txt").open("a").write(
        "Fault evidence: " + str(directory.relative_to(runtime.ROOT)) + "\n"
    )


def durable_restart(scenario, source):
    client, user, _ = scenario.account("durable-backlog")
    recovery.command(scenario, "stop", "worker")
    assets = [scenario.upload(client, source)["job_id"] for _ in range(12)]
    before = [scenario.processing_job(user["id"], a) for a in assets]
    assert all(j["current_attempt"]["state"] == "queued" for j in before)
    started = time.monotonic()
    # No active work; stop only our namespace. This is a process/namespace restart,
    # not a claim about VM power-off or cloud-host billing/availability.
    recovery.command(scenario, "stop", "--timeout", "10", timeout=45)
    recovery.command(
        scenario,
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "120",
        "--scale",
        "worker=3",
        timeout=180,
    )
    for asset, previous in zip(assets, before, strict=True):
        scenario.wait(client, asset, timeout=max(1, 300 - (time.monotonic() - started)))
        after = scenario.processing_job(user["id"], asset)
        assert after["job_id"] == previous["job_id"]
        assert after["current_attempt"]["attempt_id"] == previous["current_attempt"]["attempt_id"]
        assert after["current_attempt"]["number"] == 1
        assert sum(o["kind"] == "primary" for o in after["outputs"]) == 1
        scenario.request(client, "DELETE", f"jobs/{asset}", 204)
    elapsed = time.monotonic() - started
    assert elapsed <= 300
    scenario.record(
        "durable-backlog-namespace-restart",
        jobs=12,
        elapsed_seconds=elapsed,
        preserved_attempt_ids=[j["current_attempt"]["attempt_id"] for j in before],
        bound_seconds=300,
        cloud_host_window_adopted=False,
    )


def redis_loss(scenario, source):
    client, user, _ = scenario.account("redis-loss")
    with scenario.restore_services("worker", "processing-recovery") as guard:
        recovery.command(scenario, "stop", "worker", "processing-recovery")
        assets = [scenario.upload(client, source)["job_id"] for _ in range(12)]
        before = [scenario.processing_job(user["id"], a) for a in assets]
        attempts = [j["current_attempt"]["attempt_id"] for j in before]
        assert all(j["current_attempt"]["state"] == "queued" for j in before)
        # This Redis instance/database belongs only to the experiment namespace.
        code = (
            "from processing.queue import get_queue; q=get_queue(); "
            "q.connection.flushdb(); assert q.connection.dbsize()==0; print('flushed')"
        )
        assert (
            recovery.command(
                scenario, "exec", "-T", "processing", "python", "-c", code
            ).stdout.strip()
            == "flushed"
        )
        started = time.monotonic()
        guard.start("processing-recovery")
        probe = (
            "import json; from processing.queue import get_queue; q=get_queue(); "
            "print(json.dumps(q.get_job_ids()))"
        )
        while time.monotonic() - started < 120:
            ready = json.loads(
                recovery.command(scenario, "exec", "-T", "processing", "python", "-c", probe).stdout
            )
            if set(ready) == set(attempts):
                assert len(ready) == len(set(ready))
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Redis loss did not repair within120s")
        repaired = time.monotonic() - started
        scenario.record(
            "redis-db-loss-repair",
            jobs=12,
            reenqueue_seconds=repaired,
            bound_seconds=120,
            same_attempt_ids=True,
        )
    for index, (asset, old) in enumerate(zip(assets, before, strict=True)):
        result = scenario.wait(client, asset, timeout=300)
        if index == 0:
            playback = decoded(
                scenario.state, scenario.run_id, {"client": SimpleNamespace(http=client)}, result
            )
            scenario.record("60s-decoded-cost-input", source_seconds=60, **playback)
        job = scenario.processing_job(user["id"], asset)
        assert job["current_attempt"]["attempt_id"] == old["current_attempt"]["attempt_id"]
        assert job["current_attempt"]["number"] == 1
        assert sum(o["kind"] == "primary" for o in job["outputs"]) == 1
        scenario.request(client, "DELETE", f"jobs/{asset}", 204)


def active_rollback(args, docker, artifacts, release):
    # Use the retained exact-tested previous image, with genuine active work.
    scenario = Scenario(args.run_id, "active-rollback")
    source = runtime.ROOT / ".local/experiment-fixtures/60/source.mp4"
    docker.start_workers(1)
    client, user, _ = scenario.account("active-rollback")
    asset = scenario.upload(client, source)["job_id"]
    scenario.wait(client, asset, states=("processing",), timeout=45)
    before = scenario.processing_job(user["id"], asset)
    started = time.monotonic()
    assert release.rollback() == 0
    assert time.monotonic() - started <= 300
    scenario.wait(client, asset, timeout=300)
    after = scenario.processing_job(user["id"], asset)
    assert after["current_attempt"]["attempt_id"] == before["current_attempt"]["attempt_id"]
    assert sum(o["kind"] == "primary" for o in after["outputs"]) == 1
    scenario.record(
        "active-work-rollback",
        elapsed_seconds=time.monotonic() - started,
        bound_seconds=300,
        unchanged_attempt=True,
        one_primary=True,
    )
    scenario.request(client, "DELETE", f"jobs/{asset}", 204)
    scenario.finish()
    artifacts.write("active-rollback.json", scenario.report)
    status(args.run_id + " active-work rollback PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("baseline", "pg-quarter"), default="baseline")
    parser.add_argument("--long-drain", action="store_true")
    parser.add_argument("--window-faults", action="store_true")
    args = parser.parse_args()
    if not args.run_id.startswith(("exp38-", "exp39-")):
        parser.error("Only exp38-/exp39- namespaces permitted")
    run(args)


if __name__ == "__main__":
    main()
