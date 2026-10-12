# V3 local performance/scaling runner handoff

Runner implementation is ready for parent integration. **No live pilot,
performance, scaling, browser or CLI experiment was run by this lane. V3 acceptance
remains open.** Offline simulated scheduling is not processing evidence.

Worktree: `.worktrees/evidence`, branch `work/evidence`. Owned changes only:
`scripts/evidence/performance.py`, `scripts/evidence/common.py`,
`tests/evidence/test_performance.py`, and this review. Shared dispatcher, Make,
Compose, packaging and CI remain parent-owned. No AWS, Alibaba or GitHub operation
was performed. No other namespace or volume was touched.

## Parent wiring and invocation

Dispatch `performance` / `scaling` to
`scripts.evidence.performance.main([action, *remaining_args])`; propagate its
exit code and options. Namespace packages work without adding `__init__.py`.
Use the root Python environment until integrated setup includes these paths.
Include `tests/evidence/test_performance.py` in the offline test selection and
`scripts/evidence/` in lint selection. HTTPX is already locked in foundation.

Run from repository root, after the integrated runtime is healthy. Both actions
use frozen `runtime.configure(run_id) -> (private_env, public_state)` and
`runtime.compose(state, *args)`. Keep daemon selection consistent with the stack's
startup. No builds, `up` of the entire stack, global Docker setting changes,
volume deletion, registry writes or deployment occur in this module.

```sh
# Dedicated integrated stack, all fixed services healthy, workers STOPPED.
.venv/bin/python -m scripts.evidence.performance scaling --run-id v3-scale-a

# Short diagnostic: still checks fair capacity and all three worker counts.
.venv/bin/python -m scripts.evidence.performance scaling --run-id v3-scale-pilot \
  --pilot --repeats 1 --pilot-jobs 3 --pilot-clip-seconds 2 --job-deadline 120

# Separate dedicated integrated stack with 1–3 RUNNING capped workers.
# Verify Media's actual password hashing configuration before declaring this cost.
.venv/bin/python -m scripts.evidence.performance performance --run-id v3-perf-a \
  --login-hash-cost 'bcrypt rounds=12'

.venv/bin/python -m scripts.evidence.performance performance --run-id v3-perf-pilot \
  --login-hash-cost 'bcrypt rounds=12' --pilot --repeats 1 \
  --pilot-status-users 3 --pilot-login-users 2 --pilot-seconds 5 \
  --pilot-warmup-seconds 2 --job-deadline 120
```

`--repeats` defaults to 3. Explicit one/two-repeat diagnostics and every `--pilot`
run remain ineligible for acceptance even if numerical criteria pass. Dirty-tree
runs also remain ineligible. Each invocation gets a unique artifact directory;
misses and reruns are retained rather than overwritten. Exit 1 means a failed
criterion or prerequisite. Exit 0 on a pilot means its diagnostic criteria passed,
not proposal acceptance; consult `acceptance_pass` and the printed label.

## Frozen capacity and resource checks

The latest parent instruction supersedes the initial 2 GiB worker plan: **each
worker has a hard 2 CPU / 1536 MiB cap**. The eight persistent nonworkers total
2 CPU: Media .5, Processing API .5, PostgreSQL .25, MinIO .25, Redis .125,
nginx .125, Processing recovery .125, Media recovery .125. Service names are
`media`, `processing`, `postgres`, `minio`, `redis`, `nginx`,
`processing-recovery`, `media-recovery`, `worker`.

The runner requires Docker-reported capacity of at least 8 CPU, plus any other
running namespace's CPU reservations. Memory capacity must cover three worker
caps, all actual fixed-service memory caps, and other reservations. Every fixed
service needs a bounded memory cap. Other running uncapped containers cause a
refusal. Unknown extra services or replicated nonworkers also cause a refusal.
No other project is stopped to make room. Serialize live experiments with the
other product lanes on the shared daemon.

Worker Docker inspect limits must agree with actual cgroup v2 `cpu.max` and
`memory.max`; effective CPU sets must permit at least two CPUs. Replica counts
and project/service labels are checked. The fixed service IDs, image identities
and resource caps must stay unchanged across scaling runs. CPU/memory metadata,
quota probes and preflight diagnostics are retained even on refusal. Changes to
the frozen CPU distribution require a corresponding parent-reviewed update to
`FIXED_CPU`; do not silently run a different baseline.

The host Python generator and source FFmpeg run outside Docker/Lima, on the same
physical macOS host as the VM. That differs from design08's separate-host generator
and is explicitly recorded as a local limitation. These are local observations,
never AWS results or a capacity guarantee.

## Scaling protocol and metrics

Generate one source on the host with FFmpeg: 60 seconds, 1280×720, 30 fps,
H.264/AAC with audio, fixed generation preset/CRF/threads and bitexact flags. Probe
actual dimensions, duration, codecs and audio; retain bytes, SHA-256, source
command and FFmpeg version. All measured uploads reuse those identical bytes but
must receive fresh distinct Asset IDs. Each of nine full runs has 30 Assets.

Order is rotated: `1,2,3`, `2,3,1`, `3,1,2`. Before each configuration, require a
clean Processing runnable/started queue. Warm each replica once with a distinct
untimed Asset, pausing only the other owned replicas so the chosen worker must
perform that warmup. Unpause in cleanup, stop the owned workers, upload all 30
measured Assets, confirm their current attempts are queued/unstarted, and require
exact runnable RQ membership before launching workers. Old outputs, failed runs
and partially submitted backlogs are retained; the next invocation should use a
fresh dedicated stack rather than resetting or deleting data.

Primary observation is authenticated Processing batch HTTP:
`GET /internal/v1/jobs?asset_ids=...`, forward Bearer service token,
`X-Owner-Id`. Asset IDs from public upload acknowledgements identify private Job
and Attempt IDs. Every response must match the requested owner/assets and fixture
digest. Identity changes between queued and terminal reads fail the run rather
than concealing a retry. No product package imports or database reads are used.

The only queue diagnostic executes inside the Processing container, using its
own Redis/RQ credentials and installed libraries, selecting runnable and started
Attempt IDs only. It checks `Queue.get_job_ids()` and started registry membership
without cleanup. This is a read of Processing-owned infrastructure; no Media or
PostgreSQL credentials are passed across ownership boundaries. Queue snapshots
are recorded. Expected RQ IDs are Attempt UUIDs, as frozen by Processing's enqueue
implementation. Update that diagnostic explicitly if this queue identity changes.

Makespan is host monotonic time from the first upload's 202 acknowledgement to the
last terminal observation, including subsequent submissions, queue readiness,
worker startup, encoding and output publication. Server queue/start/finish aware
UTC timestamps supply each attempt's queue wait and processing duration. Polling
adds up to the configured request deadline plus one-second pacing, and is visible
in raw observations; first acknowledgement follows the server's durable acceptance
by transport latency. Failed jobs stay in the full makespan denominator.
Throughput is successful jobs × 60 / makespan seconds. Per-run metrics retain
throughput, queue/processing medians and raw intervals, errors, missing HLS and
available warning counts. A succeeded attempt must have a primary output.

Median throughput by worker count supplies speedup; queue waits are pooled by
count with per-run medians retained. Original targets remain visible: 2 workers
≥1.6×, 3 workers ≥2.1×, decreasing median queue wait, zero errors across all runs.
Worker FFmpeg version and actual preset/CRF are selected from the container's
configuration source AST and corresponding environment variables, without importing
product settings. Configuration must match across replicas/runs. Image identities
are retained. FFmpeg uses automatic threads in the current product pipeline;
actual CPU quota, not generation thread count, defines worker capacity. HLS's
frozen best-effort 360/480/720p policy is recorded and missing HLS stays visible.

Docker stats capture CPU percent and container memory usage, with per-run means,
maximum sampled CPU and maximum sampled memory bytes. Raw samples are retained.
This is sampled cgroup memory, not a precise per-process peak RSS measurement.

## Status and login protocols

Status uses 50 distinct owners, cookie jars and Assets; login uses a separate 20
owners and cookie jars. Synthetic UUID addresses use `example.com`, since
Pydantic rejects `example.test`; the platform does not send email. Credentials
remain in process memory only. Status has an explicitly frozen endpoint mix:
100% `GET /api/jobs/{asset_id}`, one completed owned 2-second 720p/audio Asset per
client. Preparation verifies a real successful Processing attempt and primary
output. This completed-fixture mix keeps repeats comparable; do not represent it
as a mixed queued/encoding workload. The endpoint still reads current Processing
state through the Media contract. Parent may choose an additional mixed-state
experiment with a separately recorded protocol, rather than alter this result.

Each topic runs independently for three repeats: 30 seconds of warmup, then 180
seconds at its full client count. Clients start together and each paces requests
one second from its previous launch; slow requests are not piled up. Interval,
route, client, repeat, timestamp, latency, status and error data are retained.
Nearest-rank p90 uses `ceil(.9*N)` over every timed attempt including timeouts.
Every status repeat needs p90 ≤700 ms and errors <1%; every login repeat needs
p90 <2 seconds. Login failures and logout failures remain recorded and prevent
acceptance. Cookie jars clear between login attempts; login is timed separately
from logout. Warmup errors remain visible and also prevent acceptance.

`--login-hash-cost` is mandatory and is operator-verified metadata, not automatic
hash/database inspection. Current Media source uses bcrypt's default rounds=12;
parent must verify that on the final image. The 180-second login duration is the
design08 recommendation, not a duration specified by the proposal. Browser and
Publisher CLI are separate parent evidence; this runner exercises contract HTTP.

## Artifacts, deadlines and validation

Artifacts live under ignored
`artifacts/evidence/<run-id>/<action>-<timestamp>-<unique-id>/`: safe manifest,
raw request/attempt/queue/resource JSONL, per-run jobs or requests JSON/CSV,
run metrics, target JSON and scaling target CSV. Manifest records Git revision,
dirty state, UTC, workload/order, configuration, command, fixture, quotas,
resources, image identities, limits and target assessment. Unexpected response
bodies, output object keys, presigned URLs and password/cookie/token/DSN values
are never selected. A defensive redactor also removes known secret values,
sensitive fields, URL queries/fragments and credential-bearing URLs in every
artifact format. Docker/Compose command output is captured and never printed.
Existing private runtime configuration remains runtime-owned; this runner adds
no persisted account credential file.

HTTP has per-phase and total request bounds of 10 seconds, verified project CA,
no redirects, no proxy inheritance and no retries. Ready/terminal polling is
bounded; HTTP failures abort or remain latency errors. Docker reads are bounded
at 30 seconds, Compose at 120, source generation at 300, each warmup/backlog at
`--job-deadline` (default 1800). The whole async action has `--deadline` (default
36000). Cancellation waits for the current bounded subprocess before scoped
cleanup, so final cleanup can extend the overall deadline by those bounded calls.
Scaling workers are stopped on success/failure/cancellation, clients closed and paused
replicas unpaused. A cleanup command failure is reported; reruns never hide it.
Preserve volumes and inspect a failed stack before using it again.

Validation in this lane, using root venv and no external services:

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/evidence tests/evidence/test_performance.py -q --timeout=5
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
  check scripts/evidence tests/evidence/test_performance.py
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m scripts.evidence.performance --help
git diff --check
```

48 tests passed in 0.11 seconds; lint, CLI help and whitespace checks passed.
Tests include full offline selection with all nine 30-Asset runs and 18 individual
replica warmups, invalid/missing/nonterminal/duplicate/timestamp data, strict target
boundaries, median/range calculation, capacity refusal, actual quota and CPU-set
mismatches, queue membership, HTTP owner/token/Asset selection, bounded timeout and
no retry, cancellation ordering, independent sessions and manifest/CSV redaction.
These checks validate the runner, not product performance. Parent still owns final
integration, live pilots, full workloads, result assessment and shared wiring.
