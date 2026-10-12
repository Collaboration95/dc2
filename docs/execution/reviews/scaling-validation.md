# Full local scaling acceptance

**PASS**, frozen source `f46599f8048b30087a4e9a8b8a0e1108dcc6fe03`, clean checkout.
The corrected full invocation ran on 13 October 2026, 04:48:36–06:08:40 Singapore.
All nine batches completed: three rotated repeats of 30 fresh Assets from the
same 60-second 1280×720 H264/AAC fixture at one, two and three workers. Each
replica received its own verified warmup before measurement. No completed output
was reused. Every one of the **270 measured jobs succeeded and produced HLS**.

| Workers | Median throughput, jobs/min | Throughput range | Pooled median queue wait, s | Pooled median processing, s | Mean worker CPU, % | Peak sampled worker memory, MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.337 | 2.309–2.347 | 375.381 | 24.082 | 187.31 | 517.1 |
| 2 | 4.749 | 4.534–4.755 | 175.976 | 22.915 | 182.07 | 518.3 |
| 3 | 6.743 | 6.659–6.836 | 120.360 | 22.783 | 183.06 | 524.0 |

Original targets, evaluated without revision:

- Two workers: **2.032×**, target ≥1.6× — PASS.
- Three workers: **2.885×**, target ≥2.1× — PASS.
- Decreasing pooled median queue wait — PASS.
- Zero failed measured jobs — PASS. Missing HLS: zero.

Throughput is the median of three per-batch throughputs at each worker count;
queue/processing medians pool the 90 corresponding Job/Attempt observations.
Worker CPU means are weighted by sampled observations; 100% represents one CPU.
Memory is the maximum sampled Docker value, not exact process peak RSS. The raw
per-batch and per-job data remain available; ranges are not hidden by the medians.

The dedicated local Lima VM reports eight CPUs and 8 GiB configured memory
(8,296,857,600 bytes usable). Persistent nonworkers total two CPU quotas. Each
worker has a hard two-CPU quota (`cpu.max=200000 100000`) and 1536 MiB limit,
verified at every launch. No other stack ran in this VM during the invocation.
Its sparse disk was expanded to 64 GiB to preserve failed-run data and fit the
fresh experiment. CPU/memory quotas and numeric targets were unchanged.
The generator shares the physical Mac with the VM; this is local evidence,
not an AWS result or a separate-host load-generator claim.

Makespan starts at the first accepted upload and ends at the final terminal
observation; it includes remaining submissions, queueing, publication, startup
and observation delay. Queue and processing durations use the owning database's
Attempt timestamps. Owner login renewal occurs before each batch's warmup and
timing. It does not retry failed requests or extend application login lifetime.

Selected original JSON/CSV plus all compressed JSONL are in
[`../evidence/scaling-f46599f/index.json`](../evidence/scaling-f46599f/index.json).
The index records stored and uncompressed SHA-256 values; decompression was checked.
The generated fixture remains locally in the original directory; its exact hash,
size, codec/probe metadata and FFmpeg generation command are in the manifest.
Use `gzip.open(path, 'rt')` or `gzip -dc` to read retained JSONL.

The first invocation at `621c03a` remains **FAIL** because its session expired
at eighth-batch upload preparation. Its seven completed batches are diagnostic,
and were not spliced into this result. All original records are separately retained
at [`../evidence/failed-scaling-621c03a/index.json`](../evidence/failed-scaling-621c03a/index.json).
The corrected run started fresh and passed all nine batches on its own.

Separate full status/login measurements are still pending at this checkpoint.
This scaling PASS alone does not close V3 or certify final Main.
