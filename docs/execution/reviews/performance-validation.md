# Full local V3 performance validation

**PASS for the retained full local measurement**, 13 October 2026.
Clean measurement source: `f46599f8048b30087a4e9a8b8a0e1108dcc6fe03`.
Latency invocation: 06:08:41–06:31:41 Singapore; scaling completed beforehand.
This bounded offline review adds the completed latency delta to the accepted
[scaling review](scaling-validation.md) and the independent delivery CHECKPOINT
to be preserved in [delivery-review.md](delivery-review.md) when the reviewer
supplies the final file.
V3 is ready for Review; V5 remains In progress, pending final delta review,
accepted PR31 merge, exact Main checks and issue/project reconciliation.

| Topic / repeat | Timed requests | Warmup requests | p90, ms | Timed errors | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Status 1 | 8,999 | 1,500 | 605.0455410004361 | 0 | PASS |
| Status 2 | 8,999 | 1,500 | 580.1747090008575 | 0 | PASS |
| Status 3 | 9,000 | 1,500 | 544.0224170015426 | 0 | PASS |
| Login 1 | 2,468 | 409 | 1872.9860420135083 | 0 | PASS |
| Login 2 | 2,387 | 411 | 1888.0860839999514 | 0 | PASS |
| Login 3 | 2,374 | 407 | 1898.5162919998402 | 0 | PASS |

Original targets are unchanged: every status repeat has 50 owners for 180s,
p90 ≤700ms and errors <1%; each separate 20-owner login repeat has p90 <2000ms.
Login error counts are reported; `errors_pass=null` correctly avoids inventing a
proposal error threshold. Each repeat has a separate 30s warmup. Nearest-rank
`ceil(0.9*N)` over all timed attempts independently reproduces every exact p90.
There are 34,227 timed attempts, 5,727 warmup attempts and 8,456 separate untimed
logouts, all successful. Login repeat logout counts, including warmup, are
2,877 / 2,798 / 2,781; each matches its login sample by client/sequence/interval.
All logout responses are 204. Warmup and protocol errors are zero.

Offline checks covered all twelve nonoverlapping declared intervals, all 50/20
clients in both warmup and measurement, launch offsets inside their declared
intervals, contiguous per-client sequences and one-second launch pacing. Status
rows all report `done`; the selected mix is 50 distinct completed 2s 720p H264/AAC
Assets, one per owner. All 50 acknowledged uploads and final Processing records
match the manifest, succeed and retain primary/HLS output plus the fixture hash.
All 70 owner registrations, initial logins and `/auth/me` checks succeeded.
Runner source clears each login cookie jar before a timed credential check,
requires the returned owner ID and cookie, then records logout separately.
No invalid session/status response is recorded. Summary, targets and manifest
agree; full mode, three repeats and clean source satisfy acceptance eligibility.

All **17 indexed files** match stored byte lengths/SHA-256 and decompressed
original byte lengths/SHA-256, and equal their original raw files byte for byte.
All six CSVs match every raw request field and row in order. The original video
also matches its manifest hash. Portable raw records and individual hashes:
[performance index](../evidence/performance-f46599f/index.json), whose SHA-256 is
`1f270827cfd04548f6d8a1238e602ca49d8066aed4c32f24f32725d7a81245ae`.
Original directory:
`.worktrees/final-measurements/artifacts/evidence/v3-final/performance-20261013T060841-88579745`.

Preflight retains only the measured namespace: eight Docker CPUs,
8,296,857,600 bytes usable memory, cgroup v2, no other reservations, fixed services
totaling two CPU quotas and one 2-CPU / 1536-MiB worker. Media has one CPU /
384 MiB. The frozen runner, HTTP client, Media security/auth and Media Dockerfile
are byte-identical to the revision and current root. Recorded Media image:
`sha256:7cff0354baad9180862972c8235458f73a4ab3fc5550f9c8c589c6f02e083562`.

Hash-cost provenance: the command and manifest record **bcrypt rounds=10**.
Matching Media source creates new accounts with `BCRYPT_ROUNDS=10`, verifies the
stored hash with `bcrypt.checkpw`, and uses a cost-10 dummy hash; the runner
registers fresh owners. Security source SHA-256:
`2a779ee96c4e3b1f3c386a0a5c128470d3c694dd79717b4d45df4e6bf7b6514a`.
Thus cost 10 is supported by the recorded configuration and source/registration
path. The pack does **not** retain direct measured-image code inspection or a
measured-account database hash-cost query; the runner's label is operator-supplied,
not an automatic cost measurement. Earlier pilot image/database checks in
[login-performance.md](login-performance.md) belong to that pilot. Existing
cost-12 accounts retain their embedded cost; these results do not cover them.

Combined with accepted scaling: nine fresh batches/270 successes, zero failures
or missing HLS, speedups 2.032× / 2.885× and falling pooled median queue wait
375.381 / 175.976 / 120.360s satisfy all original V3 targets. The earlier failed
scaling invocation and prior failed release experiments remain failed historical
records; no results were spliced or overwritten.

Local evidence only: generator and VM share the physical Mac; direct HTTP load,
completed-Asset status mix, sampled Docker CPU/memory, no cloud result. Current
root local startup/status and infrastructure/browser-trust smoke are coordinator-confirmed, not rerun by this reviewer; portable logs are in
[local demo index](../evidence/local-demo-20261013/index.json). Measurements are
complete and the VM is released. No application, frozen worktree, Git index,
commit, remote or live workload was changed by this review. Verification used
only read-only Git/source inspection and Python hash/gzip/JSON/CSV/math checks.
