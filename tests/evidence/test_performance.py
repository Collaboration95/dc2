"""Offline metric, isolation, HTTP and redaction checks. No live results asserted."""

import asyncio
import json
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
    return [
        {
            "id": name,
            "service": name,
            "project": "own",
            "running": True,
            "cpu_limit": cpu,
            "memory_limit_bytes": 256 * 2**20,
        }
        for name, cpu in runner.FIXED_CPU.items()
    ]


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
    fixed[0]["cpu_limit"] = 1
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
            return {"ready_attempt_ids": ["a", "b"], "started_attempt_ids": []}

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


@pytest.mark.asyncio
async def test_full_selection_prequeues_and_warms_every_replica(monkeypatch, tmp_path, job):
    events = []
    active = []
    phase_counts = []
    prepared = []
    records = {}
    paused = set()

    class Docker:
        def __init__(self, state, artifacts):
            pass

        def preflight(self):
            assert not active
            return {}, []

        def compose(self, *args):
            assert args == ("stop", "worker")
            active.clear()

        def start_workers(self, count):
            active[:] = [f"worker-{i}" for i in range(count)]
            events.append(("launch", count, len(prepared)))
            return [{"id": key} for key in active]

        def command(self, operation, worker):
            if operation == "pause":
                paused.add(worker)
            else:
                paused.remove(worker)

        def encoding_metadata(self, worker):
            return {"preset": "veryfast", "ffmpeg_version": "fake offline"}

        def queue_snapshot(self):
            return {"ready_attempt_ids": list(prepared), "started_attempt_ids": []}

        def stats(self, containers):
            return []

    class Session:
        async def close(self):
            pass

    async def owner(state, artifact, index):
        return {"id": job["owner_id"], "client": Session()}

    async def upload(person, path):
        asset = str(uuid4())
        original = dict(job)
        original["asset_id"] = asset
        original["job_id"] = str(uuid4())
        original["current_attempt"] = {**job["current_attempt"], "attempt_id": str(uuid4())}
        records[asset] = selected(original)
        if active:
            assert len(set(active) - paused) == 1  # Exactly one replica can take this warmup.
            events.append(("warmup", tuple(set(active) - paused)))
        else:
            prepared.append(records[asset]["attempt_id"])
        return asset

    async def wait_jobs(client, person, assets, **kwargs):
        if kwargs.get("queued"):
            assert not active and len(assets) == 30
            phase_counts.append((kwargs["phase"], len(assets)))
            for asset in assets:
                kwargs["identities"][asset] = (
                    records[asset]["job_id"],
                    records[asset]["attempt_id"],
                )
        elif active and prepared:
            assert len(prepared) == 30
            prepared.clear()
        return [records[asset] for asset in assets]

    path = tmp_path / "source.mp4"
    path.write_bytes(b"offline")
    monkeypatch.setattr(runner, "Docker", Docker)
    monkeypatch.setattr(runner, "Client", lambda *a, **kw: Session())
    monkeypatch.setattr(runner, "owner", owner)
    monkeypatch.setattr(runner, "upload", upload)
    monkeypatch.setattr(runner, "wait_jobs", wait_jobs)
    monkeypatch.setattr(runner, "fixture", lambda *args: (path, {"sha256": "a" * 64}))
    args = runner.parser().parse_args(["scaling", "--run-id", "offline"])
    artifact = Artifacts(tmp_path / "run")
    result = await runner.scaling(
        args, {"PROCESSING_SERVICE_TOKEN": "private"}, {"processing_port": 1}, artifact, {}
    )
    assert result["acceptance_eligible"]  # Simulation checks scheduling, not numerical acceptance.
    assert len(phase_counts) == 9
    assert len([e for e in events if e[0] == "warmup"]) == 18
    launches = [e for e in events if e[0] == "launch"]
    assert [(launches[i + 1][1], launches[i + 1][2]) for i in range(0, len(launches), 2)] == [
        (workers, 30) for _, workers in runner.run_order(3)
    ]
    assert not active and not paused
    assert "private" not in (artifact.directory / "runs.json").read_text()


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
