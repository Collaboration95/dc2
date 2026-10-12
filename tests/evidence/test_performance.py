"""Offline metric, isolation, HTTP and redaction checks. No live results asserted."""

import asyncio
import json
import re
import threading
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts.evidence import performance as runner
from scripts.evidence.common import Artifacts, Client, EvidenceError, redact


@pytest.fixture
def job():
    owner, asset, internal, attempt = (str(uuid4()) for _ in range(4))
    return {
        "owner_id": owner,
        "asset_id": asset,
        "job_id": internal,
        "status": "done",
        "source": {"sha256": "a" * 64, "source_url": "https://store/a?signature=hidden"},
        "current_attempt": {
            "attempt_id": attempt,
            "number": 1,
            "state": "succeeded",
            "queued_at": "2026-10-13T00:00:00Z",
            "started_at": "2026-10-13T00:00:10Z",
            "finished_at": "2026-10-13T00:00:30Z",
            "error": None,
        },
        "outputs": [{"kind": "primary", "object_key": "private/key"}],
        "output_url": "https://store/a?X-Amz-Signature=hidden",
        "error": None,
    }


def selected(job):
    return runner.attempt_record(job, owner=job["owner_id"], assets=[job["asset_id"]])


def metric_runs(repeats=3):
    return [
        {
            "repeat": repeat,
            "workers": workers,
            "metrics": {
                "throughput_jobs_min": {1: 10, 2: 16, 3: 21}[workers],
                "queue_wait_seconds": [{1: 30, 2: 20, 3: 10}[workers]],
                "errors": 0,
            },
        }
        for repeat, workers in runner.run_order(repeats)
    ]


def test_rotated_selection():
    assert runner.run_order(3) == [
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 2),
        (2, 3),
        (2, 1),
        (3, 3),
        (3, 1),
        (3, 2),
    ]
    assert runner.parser().parse_args(["scaling", "--run-id", "x"]).repeats == 3
    for value in (0, -1, True, 1.5):
        with pytest.raises(EvidenceError):
            runner.run_order(value)


def test_nearest_rank_including_errors():
    samples = [{"elapsed_ms": 700, "error": None} for _ in range(99)]
    samples.append({"elapsed_ms": 10000, "error": "timeout"})
    result = runner.latency_metrics(samples, "status")
    assert result["p90_ms"] == 700
    assert result["latency_pass"]
    assert result["errors"] == 1
    assert not result["errors_pass"]  # Strict <1%, never discard timeout samples.
    assert runner.p90(list(range(1, 11))) == 9
    assert runner.p90(list(range(1, 12))) == 10
    assert not runner.latency_metrics([{"elapsed_ms": 2000, "error": None}], "login")[
        "latency_pass"
    ]


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [-1], [True], ["1"]])
def test_invalid_latency_fails(values):
    with pytest.raises(EvidenceError):
        runner.p90(values)


def test_attempt_selection_discards_capabilities(job):
    record = selected(job)
    encoded = json.dumps(record)
    assert "signature" not in encoded and "private/key" not in encoded
    assert record["has_primary"] and not record["has_hls"]
    assert record["job_id"] != record["asset_id"]
    with pytest.raises(EvidenceError, match="unrequested"):
        runner.attempt_record(job, owner=str(uuid4()), assets=[job["asset_id"]])
    with pytest.raises(EvidenceError, match="unrequested"):
        runner.attempt_record(job, owner=job["owner_id"], assets=[str(uuid4())])


@pytest.mark.parametrize(
    "field,value",
    [
        ("queued_at", "2026-10-13T00:00:00"),
        ("started_at", "bad"),
        ("state", "invented"),
        ("attempt_id", "bad-id"),
    ],
)
def test_invalid_attempt_fields(job, field, value):
    job["current_attempt"][field] = value
    with pytest.raises(EvidenceError):
        selected(job)


def test_throughput_includes_failure_duration(job):
    good = selected(job)
    failed = {
        **good,
        "asset_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "job_id": str(uuid4()),
        "state": "failed",
        "has_error": True,
        "finished_at": "2026-10-13T00:02:00Z",
    }
    result = runner.scaling_metrics([good, failed], makespan_seconds=120, expected_jobs=2)
    assert result["errors"] == 1 and result["throughput_jobs_min"] == 0.5
    assert result["queue_wait_median_seconds"] == 10
    assert result["processing_seconds"] == [20, 110]


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "reversed", "nonterminal", "no-output", "no-start"]
)
def test_bad_job_metrics_fail(job, mutation):
    jobs = [selected(job)]
    count = 1
    if mutation == "missing":
        count = 2
    elif mutation == "duplicate":
        jobs *= 2
        count = 2
    elif mutation == "reversed":
        jobs[0]["started_at"] = "2026-10-12T23:59:00Z"
    elif mutation == "nonterminal":
        jobs[0]["state"] = "processing"
    elif mutation == "no-output":
        jobs[0]["has_primary"] = False
    else:
        jobs[0]["started_at"] = None
    with pytest.raises(EvidenceError):
        runner.scaling_metrics(jobs, makespan_seconds=60, expected_jobs=count)


def test_targets_medians_ranges_and_diagnostics():
    runs = metric_runs()
    result = runner.scaling_targets(runs)
    assert result["criteria_pass"] and result["acceptance_eligible"]
    runs[0]["metrics"]["throughput_jobs_min"] = 1000  # Median, not optimistic best run.
    assert runner.scaling_targets(runs)["median_throughput_jobs_min"][1] == 10
    assert not runner.scaling_targets(metric_runs(1), repeats=1)["acceptance_eligible"]
    assert runner.scaling_targets(metric_runs(1), repeats=1)["label"] == "single-repeat diagnostic"
    assert not runner.scaling_targets(metric_runs(), pilot=True)["acceptance_eligible"]
    runs[2]["metrics"]["errors"] = 1
    assert not runner.scaling_targets(runs)["criteria_pass"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "zero-baseline", "nan", "no-waits"])
def test_incomplete_or_invalid_runs_fail(mutation):
    runs = metric_runs()
    if mutation == "missing":
        runs.pop()
    elif mutation == "duplicate":
        runs[-1] = runs[0]
    elif mutation == "zero-baseline":
        for run in runs:
            if run["workers"] == 1:
                run["metrics"]["throughput_jobs_min"] = 0
    elif mutation == "nan":
        runs[0]["metrics"]["throughput_jobs_min"] = float("nan")
    else:
        for run in runs:
            if run["workers"] == 1:
                run["metrics"]["queue_wait_seconds"] = []
    with pytest.raises(EvidenceError):
        runner.scaling_targets(runs)


def fixed_containers():
    profile = {
        "media": 1.0,
        "processing": 0.5,
        "postgres": 0.125,
        "minio": 0.125,
        "redis": 0.0625,
        "nginx": 0.0625,
        "processing-recovery": 0.0625,
        "media-recovery": 0.0625,
    }
    return [
        {
            "id": name,
            "service": name,
            "project": "own",
            "running": True,
            "cpu_limit": cpu,
            "memory_limit_bytes": 256 * 2**20,
        }
        for name, cpu in profile.items()
    ]


def test_compose_and_runner_share_fixed_two_cpu_budget():
    compose = runner.runtime.COMPOSE.read_text()
    actual = {}
    for name, body in re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|^\S|\Z)", compose, re.M | re.S):
        cpu = re.search(r"^    cpus: ([\d.]+)$", body, re.M)
        if cpu:
            actual[name] = float(cpu[1])
    assert actual.pop("worker") == 2
    assert actual == runner.FIXED_CPU
    assert sum(actual.values()) == 2


def test_capacity_real_quotas_and_other_namespaces():
    info = {"NCPU": 8, "MemTotal": 8 * runner.GIB, "CgroupVersion": "2"}
    fixed = fixed_containers()
    assert runner.capacity_check(info, fixed, "own")["required_cpus"] == 8
    with pytest.raises(EvidenceError, match="Insufficient"):
        runner.capacity_check({**info, "NCPU": 7}, fixed, "own")
    other = {**fixed[0], "project": "other", "cpu_limit": 1}
    with pytest.raises(EvidenceError, match="Insufficient"):
        runner.capacity_check(info, fixed + [other], "own")
    with pytest.raises(EvidenceError, match="uncapped"):
        runner.capacity_check(info, fixed + [{**other, "cpu_limit": 0}], "own")
    with pytest.raises(EvidenceError, match="memory"):
        runner.capacity_check({**info, "MemTotal": 4 * runner.GIB}, fixed, "own")
    fixed[0]["cpu_limit"] = 0.5  # Reject the previous Media resource profile.
    with pytest.raises(EvidenceError, match="CPU quotas"):
        runner.capacity_check(info, fixed, "own")


def test_worker_actual_cgroup_caps():
    record = {"cpu_limit": 2, "memory_limit_bytes": runner.WORKER_MEMORY}
    actual = {
        "cpu.max": "200000 100000",
        "memory.max": str(runner.WORKER_MEMORY),
        "cpuset.cpus.effective": "0-7",
    }
    assert runner.worker_quota(record, actual)["cgroup_cpu_max"] == "200000 100000"
    for bad in (
        {**actual, "cpu.max": "max 100000"},
        {**actual, "cpu.max": "100000 100000"},
        {**actual, "memory.max": "max"},
        {**actual, "memory.max": str(2 * runner.GIB)},
        {**actual, "cpuset.cpus.effective": "0"},
    ):
        with pytest.raises(EvidenceError):
            runner.worker_quota(record, bad)
    with pytest.raises(EvidenceError):
        runner.worker_quota({**record, "cpu_limit": 0}, actual)


def test_artifacts_redact_all_formats_and_never_overwrite(tmp_path):
    private = "sensitive-account-value"
    artifact = Artifacts(tmp_path / "run", [private])
    value = {
        "password": private,
        "Authorization": "Bearer abc",
        "nested": {"source_url": "bad"},
        "message": f"request https://store/a?X-Amz-Signature=leak and {private}",
        "origin": "https://localhost:123",
        "dsn_note": "postgresql://user:pw@host/db",
    }
    artifact.write("manifest.json", value)
    artifact.append("raw.jsonl", value)
    artifact.csv("raw.csv", [value])
    for path in artifact.directory.iterdir():
        contents = path.read_text()
        assert private not in contents and "leak" not in contents and "Bearer abc" not in contents
        assert "user:pw" not in contents
    assert redact("redis://:password@host/0") == "[redacted-url]"
    with pytest.raises(FileExistsError):
        Artifacts(tmp_path / "run")


@pytest.mark.asyncio
async def test_private_client_contract_and_no_retries(job):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=[job])

    client = Client(
        "http://127.0.0.1:9999",
        headers={"Authorization": "Bearer PRIVATE"},
        transport=httpx.MockTransport(respond),
    )
    try:
        rows = await runner.processing_read(client, {"id": job["owner_id"]}, [job["asset_id"]])
        assert rows[0]["job_id"] == job["job_id"]
        assert len(calls) == 1
        assert calls[0].url.path == "/internal/v1/jobs"
        assert calls[0].url.params["asset_ids"] == job["asset_id"]
        assert calls[0].headers["X-Owner-Id"] == job["owner_id"]
        assert calls[0].headers["Authorization"] == "Bearer PRIVATE"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_timeout_is_bounded_recorded_without_body_leak():
    calls = []

    async def delayed(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json={"secret": "never"})

    client = Client("http://localhost", timeout=0.01, transport=httpx.MockTransport(delayed))
    try:
        data, sample = await client.request("GET", "/test")
        assert data is None and sample["error"] == "timeout"
        assert 5 <= sample["elapsed_ms"] < 200
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,error",
    [
        (503, {"error": "password=leak"}, "unexpected_status"),
        (200, b"invalid", "invalid_json"),
        (302, b"", "unexpected_status"),
    ],
)
async def test_unexpected_responses_are_not_retried_or_logged(status, body, error):
    calls = []

    def respond(request):
        calls.append(request)
        kwargs = {"content": body} if isinstance(body, bytes) else {"json": body}
        return httpx.Response(status, **kwargs)

    client = Client("http://localhost", transport=httpx.MockTransport(respond))
    try:
        data, result = await client.request("GET", "/test")
        assert data is None and result["error"] == error
        assert len(calls) == 1 and "leak" not in json.dumps(result)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_backlog_must_be_ready_before_launch(job, tmp_path):
    client = Client(
        "http://localhost",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[job])),
    )
    artifacts = Artifacts(tmp_path / "run")
    try:
        with pytest.raises(EvidenceError, match="before timed"):
            await runner.wait_jobs(
                client,
                {"id": job["owner_id"]},
                [job["asset_id"]],
                deadline=runner.time.monotonic() + 0.1,
                artifacts=artifacts,
                phase="backlog",
                digest="a" * 64,
                queued=True,
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_attempt_change_between_ready_and_terminal_fails(job, tmp_path):
    client = Client(
        "http://localhost",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[job])),
    )
    identity = {job["asset_id"]: (job["job_id"], str(uuid4()))}
    try:
        with pytest.raises(EvidenceError, match="identity changed"):
            await runner.wait_jobs(
                client,
                {"id": job["owner_id"]},
                [job["asset_id"]],
                deadline=runner.time.monotonic() + 0.1,
                artifacts=Artifacts(tmp_path / "run"),
                phase="timed",
                digest="a" * 64,
                identities=identity,
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_queue_ready_requires_exact_runnable_membership(tmp_path):
    class Queue:
        def queue_snapshot(self):
            return {
                "ready_attempt_ids": ["a", "b"],
                "started_attempt_ids": [],
                "intermediate_attempt_ids": [],
            }

    artifact = Artifacts(tmp_path / "run")
    await runner.wait_queue(
        Queue(),
        ["a", "b"],
        deadline=runner.time.monotonic() + 0.1,
        artifacts=artifact,
        phase="ready",
    )
    with pytest.raises(EvidenceError, match="unexpected runnable"):
        await runner.wait_queue(
            Queue(),
            ["a"],
            deadline=runner.time.monotonic() + 0.1,
            artifacts=artifact,
            phase="extra",
        )


@pytest.mark.asyncio
async def test_bounded_mutation_finishes_before_cancellation_cleanup():
    import time

    events = []

    def mutation():
        time.sleep(0.01)
        events.append("mutation-finished")

    task = asyncio.create_task(runner.blocking(mutation))
    await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    events.append("cleanup")
    assert events == ["mutation-finished", "cleanup"]


@pytest.fixture
def scaling_model(monkeypatch, tmp_path, job):
    """Pending Redis dequeues survive pause, but disconnect on a container stop."""
    model = SimpleNamespace(
        events=[],
        active=set(),
        paused=set(),
        pending=set(),
        known=set(),
        phase_counts=[],
        prepared=[],
        records={},
        assignments={},
        stop_entered=threading.Event(),
        stop_release=threading.Event(),
        cancel_stop=False,
        bad_assignment=False,
        fail_upload=False,
        fail_stop=None,
        uploads=0,
    )
    docker_type = runner.Docker

    class Docker(docker_type):
        def __init__(self, state, artifacts):
            self.state = {"compose_project": "own"}
            self.owned_worker_ids = set()
            self.artifacts = artifacts
            model.docker = self

        def preflight(self):
            assert not model.active
            return {}, []

        def compose(self, *args):
            assert args == ("ps", "--all", "-q", "worker")
            return " ".join(model.known)

        def start_workers(self, count):
            model.known = {f"worker-{i}" for i in range(count)}
            self.owned_worker_ids = set(model.known)
            model.active = set(model.known)
            model.pending = set(model.known)  # Already-issued blocking dequeue per replica.
            model.events.append(("launch", count, len(model.prepared)))
            return [{"id": key} for key in sorted(model.active)]

        def command(self, operation, *args):
            if operation == "stop":
                assert args[:2] == ("--time", "10")
                ids = args[2:]
                if model.cancel_stop and len(model.active) > 1:
                    model.stop_entered.set()
                    assert model.stop_release.wait(1)
                    model.cancel_stop = False
                for worker in ids:
                    model.events.append(("stop", worker))
                    if worker == model.fail_stop:
                        raise EvidenceError("offline stop failure")
                    model.active.discard(worker)
                    model.pending.discard(worker)
            elif operation == "unpause":
                model.paused.discard(args[0])
            elif operation == "start":
                model.active.add(args[0])
                model.pending.add(args[0])
            else:
                raise AssertionError("Pause/unpause cannot isolate outstanding Redis dequeues")

        def worker_states(self, ids):
            return [
                {
                    "id": key,
                    "hostname": key,
                    "running": key in model.active,
                    "paused": key in model.paused,
                    "service": "worker",
                    "project": "own",
                }
                for key in ids
            ]

        def all_running(self):
            return self.worker_states(sorted(model.active))

        def warmup_assignment(self, attempt):
            return {
                "attempt_id": attempt,
                "rq_worker_name": "rq-offline",
                "hostname": "wrong-worker" if model.bad_assignment else model.assignments[attempt],
            }

        def encoding_metadata(self, worker):
            return {"preset": "veryfast", "ffmpeg_version": "fake offline"}

        def queue_snapshot(self):
            return {
                "ready_attempt_ids": list(model.prepared),
                "started_attempt_ids": [],
                "intermediate_attempt_ids": [],
            }

        def stats(self, containers):
            return []

    def respond(request):
        model.uploads += 1
        if model.fail_upload and not model.active and len(model.prepared) == 1:
            raise httpx.ReadTimeout("private URL and body must never be retained")
        asset = str(uuid4())
        original = {
            **job,
            "asset_id": asset,
            "job_id": str(uuid4()),
            "current_attempt": {**job["current_attempt"], "attempt_id": str(uuid4())},
        }
        model.records[asset] = selected(original)
        if model.active:
            # Redis delivers to issued requests, even if the requesting worker were frozen.
            assert len(model.pending) == 1
            consumer = next(iter(model.pending))
            model.assignments[model.records[asset]["attempt_id"]] = consumer
            model.events.append(("warmup", consumer))
        else:
            model.prepared.append(model.records[asset]["attempt_id"])
        return httpx.Response(
            202, json={"job_id": asset, "source_url": "https://secret/?token=bad"}
        )

    clients = []

    def session(*args, **kwargs):
        client = Client("http://localhost", transport=httpx.MockTransport(respond))
        clients.append(client)
        return client

    async def owner(state, artifact, index):
        return {"id": job["owner_id"], "client": session()}

    async def wait_jobs(client, person, assets, **kwargs):
        if kwargs.get("queued"):
            assert not model.active and len(assets) == 30
            model.phase_counts.append((kwargs["phase"], len(assets)))
            for asset in assets:
                kwargs["identities"][asset] = (
                    model.records[asset]["job_id"],
                    model.records[asset]["attempt_id"],
                )
        elif model.active and model.prepared:
            assert len(model.prepared) == 30
            model.prepared.clear()
        return [model.records[asset] for asset in assets]

    path = tmp_path / "source.mp4"
    path.write_bytes(b"offline")
    monkeypatch.setattr(runner, "Docker", Docker)
    monkeypatch.setattr(runner, "Client", session)
    monkeypatch.setattr(runner, "owner", owner)
    monkeypatch.setattr(runner, "wait_jobs", wait_jobs)
    monkeypatch.setattr(runner, "fixture", lambda *args: (path, {"sha256": "a" * 64}))
    model.args = runner.parser().parse_args(["scaling", "--run-id", "offline"])
    model.artifact = Artifacts(tmp_path / "run")
    model.clients = clients

    async def run():
        return await runner.scaling(
            model.args,
            {"PROCESSING_SERVICE_TOKEN": "private"},
            {"processing_port": 1},
            model.artifact,
            {},
        )

    model.run = run
    return model


@pytest.mark.asyncio
async def test_full_selection_prequeues_and_warms_every_replica(scaling_model):
    model = scaling_model
    result = await model.run()
    assert result["acceptance_eligible"]  # Scheduling simulation is not experiment evidence.
    assert len(model.phase_counts) == 9
    assert len([e for e in model.events if e[0] == "warmup"]) == 18
    launches = [e for e in model.events if e[0] == "launch"]
    assert [(launches[i + 1][1], launches[i + 1][2]) for i in range(0, len(launches), 2)] == [
        (workers, 30) for _, workers in runner.run_order(3)
    ]
    assert not model.active and not model.pending
    assert "private" not in (model.artifact.directory / "runs.json").read_text()
    warmups = jsonl(model.artifact, "warmups.jsonl")
    assert len(warmups) == 18
    assert all(w["worker_id"] == w["assignment"]["hostname"] for w in warmups)
    submissions = jsonl(model.artifact, "submissions.jsonl")
    assert len(submissions) == 270 + 18
    assert len({s["asset_id"] for s in submissions}) == 288
    intervals = jsonl(model.artifact, "intervals.jsonl")
    for interval in intervals:
        first = next(s for s in submissions if s["phase"] == interval["phase"])
        assert interval["first_acceptance_monotonic"] == first["acknowledged_monotonic"]
        assert interval["first_acceptance_utc"] == first["utc"]


def jsonl(artifacts, name):
    return [json.loads(line) for line in (artifacts.directory / name).read_text().splitlines()]


@pytest.mark.asyncio
async def test_wrong_warmup_assignment_is_retained_and_rejected(scaling_model):
    scaling_model.bad_assignment = True
    with pytest.raises(EvidenceError, match="selected replica"):
        await scaling_model.run()
    assert not scaling_model.active and not scaling_model.pending
    assert (
        jsonl(scaling_model.artifact, "warmups.jsonl")[0]["assignment"]["hostname"]
        == "wrong-worker"
    )


@pytest.mark.asyncio
async def test_cancellation_during_warmup_stop_reconciles_every_worker(scaling_model):
    model = scaling_model
    model.cancel_stop = True
    task = asyncio.create_task(model.run())
    # The first two-worker warmup blocks inside the actual scaling mutation path.
    assert await asyncio.to_thread(model.stop_entered.wait, 1)
    task.cancel()
    model.stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not model.active and not model.pending
    assert all(c.http.is_closed for c in model.clients)


@pytest.mark.asyncio
async def test_cleanup_attempts_remaining_workers_after_one_failure(scaling_model):
    model = scaling_model
    docker = runner.Docker({}, model.artifact)
    docker.start_workers(3)
    model.fail_stop = "worker-0"
    model.paused = {"worker-0", "worker-1"}
    with pytest.raises(EvidenceError, match="cleanup failed"):
        await runner.blocking(docker.stop_workers)
    assert model.active == {"worker-0"}
    assert not model.paused
    cleanups = jsonl(model.artifact, "cleanup.jsonl")
    assert [row["worker_id"] for row in cleanups if row["error"]] == ["worker-0"]
    assert {e[1] for e in model.events if e[0] == "stop"} == model.known


@pytest.mark.asyncio
async def test_partial_submission_failure_retains_acknowledgements(scaling_model):
    model = scaling_model
    model.fail_upload = True
    with pytest.raises(EvidenceError, match="Upload failed: timeout"):
        await model.run()
    submissions = jsonl(model.artifact, "submissions.jsonl")
    assert [s["phase"] for s in submissions] == ["r1-w1-warmup", "r1-w1", "r1-w1"]
    acknowledged, failed = submissions[-2:]
    assert acknowledged["asset_id"] in model.records
    assert acknowledged["sequence"] == 1 and acknowledged["status_code"] == 202
    assert acknowledged["utc"] and acknowledged["acknowledged_monotonic"] > 0
    assert failed["asset_id"] is None and failed["sequence"] == 2
    assert failed["error"] == "timeout" and 0 <= failed["elapsed_ms"] < 1000
    assert not model.active and not model.pending
    assert "secret" not in (model.artifact.directory / "submissions.jsonl").read_text()


def test_resource_stats_preserve_percent_and_sampled_peak():
    summary = runner.resource_summary(
        [
            [{"ID": "worker", "CPUPerc": "150%", "MemUsage": "512MiB / 1.5GiB"}],
            [{"ID": "worker", "CPUPerc": "200%", "MemUsage": "1GiB / 1.5GiB"}],
        ]
    )["worker"]
    assert summary["samples"] == 2
    assert summary["mean_cpu_percent"] == 175
    assert summary["peak_sampled_memory_bytes"] == runner.GIB
    with pytest.raises(EvidenceError):
        runner.memory_bytes("unknown")


def test_redaction_handles_metric_maps():
    assert redact({1: {"throughput": 10}}) == {1: {"throughput": 10}}


@pytest.mark.asyncio
async def test_auth_owners_use_valid_synthetic_domain_and_private_sessions(monkeypatch, tmp_path):
    owner_id = str(uuid4())
    clients = []

    class Session:
        def __init__(self, *args, **kwargs):
            self.http = type("HTTP", (), {"cookies": {"access_token": "private-cookie"}})()
            self.credentials = None
            clients.append(self)

        async def checked(self, method, path, **kwargs):
            if path.endswith("register"):
                self.credentials = kwargs["json"]
                assert self.credentials["email"].endswith("@example.com")
            return {"id": owner_id}

        async def close(self):
            pass

    monkeypatch.setattr(runner, "Client", Session)
    artifact = Artifacts(tmp_path / "run")
    people = [
        await runner.owner({"public_url": "https://localhost", "ca_file": "ca"}, artifact, i)
        for i in range(2)
    ]
    assert people[0]["client"] is not people[1]["client"]
    assert people[0]["credentials"] != people[1]["credentials"]
    artifact.write("record.json", {"diagnostic": clients[0].credentials["password"]})
    assert (
        clients[0].credentials["password"] not in (artifact.directory / "record.json").read_text()
    )


@pytest.mark.parametrize(
    "workers,field,value",
    [
        (2, "throughput_jobs_min", 15.99),
        (3, "throughput_jobs_min", 20.99),
        (3, "queue_wait_seconds", [20]),
    ],
)
def test_each_scaling_target_can_fail(workers, field, value):
    runs = metric_runs()
    for run in runs:
        if run["workers"] == workers:
            run["metrics"][field] = value
    assert not runner.scaling_targets(runs)["criteria_pass"]


@pytest.mark.parametrize("errors", [-1, 0.5, False])
def test_invalid_error_counts_fail(errors):
    runs = metric_runs()
    runs[0]["metrics"]["errors"] = errors
    with pytest.raises(EvidenceError, match="failed-job"):
        runner.scaling_targets(runs)


@pytest.mark.asyncio
@pytest.mark.parametrize("expected", [[], ["measured-attempt"]])
async def test_real_rq_intermediate_entries_fail_clean_and_prelaunch_checks(
    monkeypatch, tmp_path, expected
):
    import contextlib
    import io

    from fakeredis import FakeRedis
    from redis import Redis
    from rq import Queue
    from rq.intermediate_queue import IntermediateQueue

    connection = FakeRedis()
    queue = Queue("offline", connection=connection)
    queue.enqueue("math.floor", 1, job_id="old-attempt")
    Queue.lmove(connection, queue.key, timeout=1)
    if expected:
        queue.enqueue("math.floor", 2, job_id=expected[0])
    monkeypatch.setenv("PROCESSING_REDIS_URL", "redis://unused")
    monkeypatch.setenv("PROCESSING_QUEUE_NAME", queue.name)
    monkeypatch.setattr(Redis, "from_url", lambda *a, **kw: connection)
    docker = runner.Docker({"docker_host": None, "docker_config": "unused"})

    def compose(*args):
        # Execute the runner's actual read-only diagnostic against locked RQ/FakeRedis.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(args[-1], {})
        return output.getvalue()

    monkeypatch.setattr(docker, "compose", compose)
    artifact = Artifacts(tmp_path / "run")
    with pytest.raises(EvidenceError, match="intermediate work"):
        await runner.wait_queue(
            docker,
            expected,
            deadline=runner.time.monotonic() + 1,
            artifacts=artifact,
            phase="clean" if not expected else "prelaunch",
        )
    snapshot = jsonl(artifact, "queue.jsonl")[0]
    assert snapshot["ready_attempt_ids"] == expected
    assert snapshot["started_attempt_ids"] == []
    assert snapshot["intermediate_attempt_ids"] == ["old-attempt"]
    assert IntermediateQueue(queue.key, connection).get_job_ids() == ["old-attempt"]


def test_real_rq_assignment_diagnostic_reads_job_worker_and_hostname(monkeypatch):
    import contextlib
    import io
    import sys

    from fakeredis import FakeRedis
    from redis import Redis
    from rq import Queue, Worker

    connection = FakeRedis()
    queue = Queue("offline", connection=connection)
    job = queue.enqueue("math.floor", 1, job_id=str(uuid4()))
    worker = Worker([queue], connection=connection, name="observed-rq-worker")
    worker.register_birth()
    pipeline = connection.pipeline()
    job.prepare_for_execution(worker.name, pipeline)
    pipeline.execute()
    monkeypatch.setenv("PROCESSING_REDIS_URL", "redis://unused")
    monkeypatch.setattr(Redis, "from_url", lambda *a, **kw: connection)
    docker = runner.Docker({"docker_host": None, "docker_config": "unused"})

    def compose(*args):
        output = io.StringIO()
        monkeypatch.setattr(sys, "argv", ["-c", args[-1]])
        with contextlib.redirect_stdout(output):
            exec(args[-2], {})
        return output.getvalue()

    monkeypatch.setattr(docker, "compose", compose)
    assert docker.warmup_assignment(job.id) == {
        "attempt_id": job.id,
        "rq_worker_name": worker.name,
        "hostname": worker.hostname,
    }


@pytest.mark.asyncio
async def test_failed_private_observation_retains_actual_http_sample(job, tmp_path):
    client = Client(
        "http://localhost",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"password": "hidden-response-body"})
        ),
    )
    artifact = Artifacts(tmp_path / "run")
    try:
        with pytest.raises(EvidenceError, match="unexpected_status"):
            await runner.wait_jobs(
                client,
                {"id": job["owner_id"]},
                [job["asset_id"]],
                deadline=runner.time.monotonic() + 1,
                artifacts=artifact,
                phase="measured",
                digest="a" * 64,
            )
    finally:
        await client.close()
    sample = jsonl(artifact, "operations.jsonl")[0]
    assert sample["status_code"] == 503 and sample["error"] == "unexpected_status"
    assert 0 <= sample["elapsed_ms"] < 1000
    assert sample["asset_ids"] == [job["asset_id"]]
    assert sample["phase"] == "measured" and sample["operation"] == "processing_observation"
    assert "hidden-response-body" not in json.dumps(sample)


@pytest.mark.asyncio
@pytest.mark.parametrize("topic,count", [("login", 20), ("status", 50)])
async def test_concurrent_phases_retain_logout_separately(tmp_path, topic, count):
    artifact = Artifacts(tmp_path / "run")
    gate = asyncio.Event()
    arrivals = []
    people = []

    async def respond(request):
        if request.url.path.endswith("logout"):
            return httpx.Response(503, json={"cookie": "hidden-body"})
        arrivals.append(request)
        if len(arrivals) == count:
            gate.set()
        await gate.wait()
        if topic == "login":
            return httpx.Response(
                200, json={"id": "owner"}, headers={"set-cookie": "access_token=private; Path=/"}
            )
        return httpx.Response(200, json={"id": "asset", "status": "done"})

    for index in range(count):
        people.append(
            {
                "index": index,
                "id": "owner",
                "asset_id": "asset",
                "credentials": {"email": "private", "password": "private"},
                "client": Client("http://localhost", transport=httpx.MockTransport(respond)),
            }
        )
    operations = []
    try:
        samples = await runner.latency_phase(
            people,
            topic,
            0.2,
            artifacts=artifact,
            repeat=1,
            timed=True,
            operations=operations,
        )
    finally:
        for person in people:
            await person["client"].close()
    assert len(arrivals) == len(samples) == count
    assert all(s["status_code"] == 200 and s["error"] is None for s in samples)
    if topic == "login":
        assert len(operations) == count
        assert all(
            s["status_code"] == 503 and s["error"] == "unexpected_status" for s in operations
        )
        assert all(s["timed"] is False and s["interval_timed"] is True for s in operations)
        assert all(0 <= s["elapsed_ms"] < 1000 for s in operations)
        assert jsonl(artifact, "operations.jsonl") == operations
        assert "private" not in (artifact.directory / "operations.jsonl").read_text()
        assert not any(p["client"].http.cookies for p in people)
    else:
        assert not operations


def test_login_proposal_assessment_has_no_numeric_error_threshold():
    result = runner.latency_metrics(
        [
            {"elapsed_ms": 100, "error": None},
            {"elapsed_ms": 100, "error": "unexpected_status"},
        ],
        "login",
    )
    assert result["latency_pass"] and result["p90_ms"] == 100
    assert result["errors"] == 1 and result["error_fraction"] == 0.5
    assert result["errors_pass"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "login_error,eligible", [("unexpected_status", True), ("invalid_login_session", False)]
)
async def test_performance_targets_separate_observed_errors_from_protocol_eligibility(
    monkeypatch, tmp_path, job, login_error, eligible
):
    fixed = fixed_containers()
    own = fixed + [
        {
            "id": "worker",
            "service": "worker",
            "project": "own",
            "running": True,
            "cpu_limit": 2,
            "memory_limit_bytes": runner.WORKER_MEMORY,
        }
    ]

    class Docker:
        def __init__(self, *args):
            pass

        def command(self, *args):
            if args[0] == "info":
                return json.dumps({"NCPU": 8, "MemTotal": 8 * runner.GIB, "CgroupVersion": "2"})
            return {
                "cpu.max": "200000 100000",
                "memory.max": str(runner.WORKER_MEMORY),
                "cpuset.cpus.effective": "0-7",
            }[args[-1].split("/")[-1]]

        def all_running(self):
            return own

        def stats(self, *args):
            return []

    class Session:
        async def close(self):
            pass

    async def owner(*args):
        return {"index": args[-1], "client": Session(), "id": job["owner_id"]}

    async def upload(*args, **kwargs):
        return str(uuid4())

    async def wait_jobs(*args, **kwargs):
        return [selected(job)]

    async def latency_phase(people, topic, duration, **kwargs):
        if topic == "login":
            kwargs["operations"].append({"error": "unexpected_status"})
        return [
            {
                "client": p["index"],
                "elapsed_ms": 100,
                "error": login_error if topic == "login" and p["index"] == 0 else None,
            }
            for p in people
        ]

    monkeypatch.setattr(runner, "Docker", Docker)
    monkeypatch.setattr(runner, "Client", lambda *a, **kw: Session())
    monkeypatch.setattr(runner, "owner", owner)
    monkeypatch.setattr(runner, "upload", upload)
    monkeypatch.setattr(runner, "wait_jobs", wait_jobs)
    monkeypatch.setattr(runner, "latency_phase", latency_phase)
    monkeypatch.setattr(
        runner, "fixture", lambda *a: (tmp_path / "source.mp4", {"sha256": "a" * 64})
    )
    args = runner.parser().parse_args(
        [
            "performance",
            "--run-id",
            "offline",
            "--login-hash-cost",
            "bcrypt rounds=12",
        ]
    )
    result = await runner.performance(
        args,
        {"PROCESSING_SERVICE_TOKEN": "private"},
        {"processing_port": 1, "compose_project": "own"},
        Artifacts(tmp_path / "run"),
        {},
    )
    assert result["criteria_pass"]  # Original numeric proposal thresholds pass.
    assert result["acceptance_eligible"] is eligible
    assert result["protocol_eligible"] is eligible
    assert result["operational_errors"] == 12  # Three repeats: login+warmup+two logout failures.
    login_runs = [r for r in result["targets"] if r["topic"] == "login"]
    assert len(login_runs) == 3
    assert all(
        r["metrics"]["errors"] == 1 and r["metrics"]["logout_errors"] == 2 for r in login_runs
    )


@pytest.mark.parametrize("protocol_valid,expected_exit", [(True, 0), (False, 1)])
def test_cli_reports_protocol_invalidity_separately_from_numeric_targets(
    monkeypatch, tmp_path, protocol_valid, expected_exit
):
    monkeypatch.setattr(runner.runtime, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner.runtime,
        "configure",
        lambda run_id: (
            {},
            {
                "public_url": "https://localhost",
                "compose_project": "own",
                "ca_file": "unused",
            },
        ),
    )
    monkeypatch.setattr(runner, "host_command", lambda args: "" if "status" in args else "ecd9d5f")

    async def performance(*args):
        return {
            "criteria_pass": True,
            "protocol_eligible": protocol_valid,
            "acceptance_eligible": protocol_valid,
            "operational_errors": 2,
            "label": "full local",
        }

    monkeypatch.setattr(runner, "performance", performance)
    assert runner.main(["performance", "--run-id", "offline"]) == expected_exit
    manifest_path = next((tmp_path / "artifacts").rglob("manifest.json"))
    result = json.loads(manifest_path.read_text())["result"]
    assert result["criteria_pass"] and result["operational_errors"] == 2
    assert result["acceptance_pass"] is protocol_valid
