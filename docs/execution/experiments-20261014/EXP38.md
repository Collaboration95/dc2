# LOCAL experiment #38: reject CPU redistribution

Decision: **REJECT; baseline quotas retained.** Three rotated comparisons completed,
with 180/180 fresh 60-second 720p jobs producing successful MP4 and HLS outcomes.
This resolves the hypothesis, but does **not** satisfy the latency acceptance gates.
The accepted historical measurements and product defaults remain unchanged.

Baseline product source is `b913579be16ca7f1fb9f685e287d905bfbcfbd6a`.
The eligible measurement and release source is
`08ec06c22a8950007cc6db2a934cf957a4621a3c`. Product files are byte-equivalent to
the baseline; opt-in instrumentation and a separate harness are additions.
Exact source-file hashes, immutable image IDs, CPU/memory ceilings, fixtures,
protocol hash, command and measured-account bcrypt algorithm/cost are in the raw
manifest, quota records and hash-cost records. All measured accounts used bcrypt
cost 10; hashing strength was not changed.

Only PostgreSQL and Processing CPU ceilings changed: `.125→.25` and `.5→.375`.
Nonworkers still total 2 CPU/2304 MiB; each worker remains hard 2 CPU/1536 MiB.
The project-local 8-CPU/8-GiB VM hosted one active experiment namespace. Ceilings
are not reservations. Startup and release jobs remain uncapped one-shot work.

| Pair/profile | Isolated status p90 ms | Isolated login p90 ms | Mixed status p90 ms | Mixed login p90 ms | Long jobs/min |
|---|---:|---:|---:|---:|---:|
| 1 baseline | 701.6 | 2213.3 | 2779.3 | 1781.6 | 6.421 |
| 1 variant | 263.7 | 2271.6 | 2674.0 | 1731.6 | 6.147 |
| 2 variant | 252.5 | 2318.8 | 2836.5 | 1813.5 | 6.025 |
| 2 baseline | 729.3 | 2266.8 | 2654.3 | 1753.9 | 6.491 |
| 3 baseline | 740.1 | 2284.2 | 2681.9 | 1748.8 | 6.614 |
| 3 variant | 258.6 | 2191.9 | 2597.9 | 1724.5 | 6.207 |

Each arm ran the unchanged 50-user status and 20-user login workloads separately
for 180 seconds after 30-second warmup, then concurrently with a fresh 30-job
batch and actual HLS/MP4 browser decoding. Timed requests were never retried.
Pair 2 baseline was explicitly restarted after preparation failed; its eligible
phase is `r2-completed-baseline`. The two earlier partial isolated intervals are
retained but excluded from the 24 eligible interval aggregates.

The causal evidence supports the isolated status improvement. PostgreSQL
throttle-counter deltas were 383–431 million microseconds for baseline versus
44–51 million for variant. These are cumulative kernel counters, not wall time;
sampling spans are retained for normalization. Media SQL mean fell from
11.6–13.1 ms to 4.17–4.28 ms; Pool.connect mean fell from 86.9–88.0 ms to
33.9–34.5 ms. Pool.connect includes connection creation and pre-ping, so it must
not be described as a pure pool semaphore wait. Per-service pressure, memory/OOM
counters, active database wait categories, queue age and processing times remain
available in raw and interval aggregates. Processing throttle increased when its
CPU ceiling decreased. Variant throughput was 4.3%, 7.2%, and 6.2% lower than its
paired baseline; it fails to improve the complete workload even though these
differences fall below the protocol's 10% donor throughput rejection threshold.

| Criterion | Disposition |
|---|---|
| Immutable source/images/config, actual hash cost | PASS; raw manifests/cost records |
| CPU throttle/pressure, SQL/connect timings, queue/HTTP/processing latency | PASS; opt-in PID-1 hooks and sampled categories, no SQL text |
| Three rotated original isolated and mixed workloads, fresh batches, decoded playback | PASS; six complete arms, 180 long successes; explicit preparation continuation |
| Separate harness; historical scripts/checks and targets preserved | PASS; no historical runner edits |
| Status p90 ≤700 ms | FAIL; baseline isolated and every mixed arm fail; variant isolated passes |
| Status errors <1% | PASS in eligible timed arms; two baseline 503s, each far below 1% |
| Login p90 <2 s | FAIL for every isolated arm; every mixed arm passes |
| Zero lost/duplicate successful outcomes, OOM, ownership failures | PASS for eligible jobs; fresh owners/wrong-owner checks, digest and attempt/output assertions |
| Worker-loss failure visible ≤300 s | PASS; baseline 79.806 s, variant 69.874 s; intentional killed attempts fail and explicit retries succeed |
| Queue-loss repair ≤120 s | PASS; baseline 25.561 s, variant 21.893 s; surviving hash, same attempt |
| Durable pending Processing outage/restart | PASS after explicit HTTP readiness; retain the initial baseline observer failure |
| Good cold promotion ≤600 s | PASS; baseline 116.776 s, variant 117.577 s |
| Bad cold promotion and tested-image restoration ≤300 s | PASS; whole bad operation 153.215/139.621 s, including restoration; unchanged Media |
| Reproducible safe improvement before adoption | FAIL; explained isolated improvement does not meet complete latency gates; rejected |
| Raw publication/gist, independent fresh Sol review, PR | Local evidence supplied; remote publication and independent review belong to parent and remain pending |

Commands:

```sh
python -m scripts.experiments.followups quota --run-id exp38-20261014-r4
# Explicit same-source continuations, archived with exact operator source hashes:
PYTHONPATH=. python .local/continue-quota.py
PYTHONPATH=. python .local/continue-quota-preparation.py
python -m scripts.experiments.faults --run-id exp38-20261014-r4 --profile baseline
PYTHONPATH=. python .local/recovery-readiness-gates.py
PYTHONPATH=. python .local/variant-readiness-gates.py
python -m scripts.experiments.analyze artifacts/exp38-20261014-r4/quota-20261014T122005
```

The reusable fault adjunct now waits explicitly for public readiness after
process restoration. The original guard restarted services without waiting for
HTTP, so its first baseline post-restoration request saw 502. A fresh outage
proof passed with readiness bounded at 120 seconds; numeric recovery/release
assertions were preserved. Original failure records are retained.

Earlier invocations are excluded from paired acceptance: invocation 1 hit a
10-second upload observer timeout; invocation 2 hit a browser fixture mounting
problem; invocation 3 imported SQLAlchemy in healthcheck subprocesses, increasing
probe CPU. Durable post-stop audits found 52/52, 59/59 and 290/290 successes,
respectively. The corrected PID-1-only instrumentation restarted all pairs.
Within invocation 4, two preparation-only 401s could not be reproduced by 200
auth probes, 200 upload probes and 1000 renewal probes. No auth strength or timed
request behavior changed. The continuation allowed at most one preparation retry
and recorded it; no such retry was needed in the successful continuation.
The root cause of those 401s remains unresolved and bars an adoption claim.

The preregistered correctness/sampling/deadline stop rules were preserved. A
latency miss determines rejection but does not silently remove required arms or
fault checks. No historical threshold was rewritten. The implementation does not
lower memory, change authentication, or claim cloud affordability.

For each completed 30-job batch, actual Processing object-prefix enumeration
found 870 objects and 1,828,787,010 bytes, including HLS variant playlists and
segments. Each 60-second input is 21,050,412 bytes; output is 60,959,567 bytes/job
for this deterministic fixture. Database descriptors alone are a lower bound.
Playback records count actual transferred response bodies and redirects; the
mixed-arm browser fixture was 2 seconds, so it is not a full 60-second viewing
cost estimate. Experiment #39 separately records 60-second playback transfers.
No AWS calls or spending occurred. Account, region, retention and viewing volume
remain necessary for an all-in budget under the unchanged $200 total/three-week
cap.
