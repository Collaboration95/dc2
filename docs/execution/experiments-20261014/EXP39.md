# LOCAL experiment #39: reject the manual window policy

Workload decision: **REJECT; no policy/default adopted.** All 48 eligible windows
and 504/504 scheduled jobs completed on source
`60f244c8dbc8b4d48f761851c1f0626e1b1c92e1`. The 360 long jobs are full
60-second 1280×720 H.264/AAC clips; 144 are full 2-second clips. All outputs met
MP4/HLS, source-digest and unique Job/Attempt/primary assertions. All repeated fault/release proofs passed. The original accepted demo was restored
on its exact saved containers/images and its public workflow passed.

#38 rejected CPU redistribution before these trials. Baseline nonworker quotas
remain 2 CPU/2304 MiB; every worker remains hard 2 CPU/1536 MiB, with unchanged
quality and independent stores/recovery. Product source remains byte-equivalent
to b913579; the experiment source/images/config/fixtures are frozen and indexed.

| Repeat/policy | Worker seconds | Mixed short wait p90 s | Status p90 ms | Login p90 ms |
|---|---:|---:|---:|---:|
| 1/1 | 1269.0 | 139.7 | 2559.9 | 1680.9 |
| 1/2 | 2015.5 | 50.9 | 2668.9 | 1682.6 |
| 1/3 | 2860.5 | 29.7 | 2664.6 | 1689.5 |
| 1/manual | 2480.6 | 29.2 | 2657.3 | 1680.6 |
| 2/2 | 2059.0 | 51.1 | 2563.4 | 1670.7 |
| 2/3 | 2901.7 | 26.3 | 2481.8 | 1645.9 |
| 2/manual | 2472.2 | 27.9 | 2687.4 | 1685.4 |
| 2/1 | 1313.6 | 127.9 | 2663.7 | 1754.0 |
| 3/3 | 2945.0 | 25.9 | 2580.6 | 1674.0 |
| 3/manual | 2515.6 | 27.9 | 2571.7 | 1678.6 |
| 3/1 | 1314.0 | 129.1 | 2387.1 | 1667.0 |
| 3/2 | 2096.2 | 50.9 | 2283.4 | 1564.6 |

Three rotations used fixed 1/2/3 workers and replayed an advance-planned manual
operator schedule. Every arm ran the same idle-gap, burst, sustained and mixed
arrivals. The 50-user status/20-user login workload ran for 180 seconds after
30-second warmup during every sustained window. The complete final fixed-two arm
is explicitly labelled `3-completed`, logical repetition 3, after a disk stop.

Manual worker residency was 86.72%, 85.20%, and 85.42% of paired fixed-three
residency: reductions of 13.28%, 14.80%, and 14.58%. All miss the preregistered
20% reduction requirement. Short-job p90 wait passed the paired fixed-three+30s
bound in all three comparisons. Every arm met the 300-second observed queue-age,
authoritative queue-wait and sustained-drain bounds. All sustained status p90
values fail the unchanged 700ms gate; all sustained login p90 values pass 2s.
There were 103,221 timed status/login samples with zero timed errors; one status
warmup request timed out after 10 seconds in repetition 2 manual. It is retained
and is not counted as a passing zero-error warmup.

The policy holds one worker through the idle-gap window, activates three at each
known processing window, and warm-drains two after outcomes settle plus 60 seconds
idle. Its backlog≥3/oldest≥30s thresholds were declared before execution as
operator escalation criteria. This is a replay of an advance-planned operator
schedule; a reactive controller was not built or validated. The queue bound was
fixed at 300s from the allowed recovery/failure deadline, not tuned to results.
No arbitrary active job is killed with the former 60s stop grace.

Residency uses captured Docker StartedAt/FinishedAt lifetimes intersected with
policy spans, including cold activation, idle observation, enumeration, cleanup
and drain overhead. It is not the simple replicas×job-time estimate. CPU/pressure,
SQL/connect timing, current memory and disk sampling are retained by window;
resource aggregates keep their observed spans. CPU/memory ceilings are not
reservations. Fewer running workers do not raise Media's CPU ceiling and do not
save a cloud bill on a running host.

## Retained interruptions and explicit continuation

An initial preparation run was interrupted after identifying a possible sampler
race at planned drain. It is excluded from comparisons; the corrected run finishes
in-flight sampling before SIGTERM and records that boundary. Its five durable queued jobs were subsequently settled: 68/68 attempts
succeeded, with the twelve long burst jobs retaining one primary/HLS outcome each.
The excluded backlog settled in 48.508 seconds before demo restoration.

The corrected run hit the preregistered <2GiB disk stop during the final fixed-two
burst. All twelve accepted long jobs subsequently succeeded, with one primary and
HLS each. The complete eleven earlier arms are retained; the original final idle
window and burst are excluded. The entire final four-window arm was repeated
from fifty fresh status fixtures and twenty login accounts, preserving frozen
source/image hashes, quotas, quality, numeric gates and arrival schedules.

Only audited synthetic assets in these newly owned namespaces were retired via
existing Media tombstone/cancellation and dedicated Processing output-cleanup
paths. The first manual scan used the worker/API principal and was correctly
denied; it was corrected to the dedicated cleanup principal without changing any
permissions. A large retained Minio discarded-object trash directory in the
stopped #38 namespace was identified read-only and then cleared at that exact
path. No volume was removed, no global pruning/configuration change occurred,
and original/frozen historical volumes and evidence stayed intact. Exact audit,
cleanup, source/controller and disk records are retained. Numeric gates were
never lowered to continue. The final dataset contains 200 status-fixture jobs,
504 eligible scheduled jobs, and 18 excluded interrupted scheduled jobs: 722
successful attempts in this corrected namespace before fault injections.

The disk stop is an experimental failure and an additional reason to reject
adoption. The completed continuation does not erase it or claim uninterrupted
execution. Original historical acceptance is not reclassified by these new gates.

## Output and later cost inputs

Eligible scheduled jobs produced **22,222,111,464 actual bytes in 11,592 objects**,
including every HLS rendition playlist and segment. The excluded initial final
idle window contributes another 11,527,806 bytes/48 objects and is omitted from
those totals. Each 60s input is 21,050,412 bytes; every 60s output is 60,959,567
bytes/29 objects. Each 2s output is 1,921,301 bytes/8 objects for this fixture.
Database descriptors alone register two objects and are a lower bound.

Raw HTTP ledgers include 103,221 timed samples (68,166 status/35,055 login),
16,623 warmup samples, 47,653 other operations (including 40,577 logout requests),
and 722 successful upload acknowledgements. These scopes include setup/internal
observations and retained interrupted work; do not treat every record as a
billable cloud S3 request. The fault pack separately records actual decoded
60-second HLS/MP4 startup transfers and completed response-body bytes. A playback
start is not full-clip viewing traffic or every internal multipart transaction.

Account/region, retention, traffic, object/request charges, snapshots, persistent
disks and whole-host availability are still required for an all-in $200 total /
about-three-week deployment estimate. No price/SKU, lower-memory, cloud power-off
or bill-savings claim is adopted, and no AWS API or spending occurred. Namespace
restart proves local durable restart; it does not prove cloud-host windows.

## Commands and remaining proof disposition

```sh
python -m scripts.experiments.followups windows --run-id exp39-20261014-r2
PYTHONPATH=. python .local/disk-stop-audit-cleanup.py
PYTHONPATH=. python .local/disk-stop-output-cleanup.py
PYTHONPATH=. python .local/retire-exp38-data.py
PYTHONPATH=. python .local/continue-windows.py
python -m scripts.experiments.faults --run-id exp39-20261014-r2 \
  --profile baseline --window-faults --long-drain
```

Exact operator sources/hashes and raw manifests identify the explicit data
retirement and continuation; no timed requests were retried. Parent owns remote
gist/issue/PR publication and one fresh independent Sol review. Those remain
pending and are not represented by local tests.

## Final criterion disposition

| Issue criterion | Disposition |
|---|---|
| #38 establishes/rejects redistribution before combined configuration | PASS; #38 rejected before #39; baseline quotas used |
| Immutable source/config, hard 2CPU/1536MiB, same quality | PASS; source60f244c, source-file/image/config/fixture manifests; core byte-equivalent to b913579 |
| Three paired rotated fixed1/2/3 versus manual comparisons | PASS; twelve complete arms,48eligible windows,504/504scheduled successes; one full-arm continuation explicitly labelled |
| Predeclared activation/drain thresholds and concrete queue-age bound | PASS; protocol fixed before trials;300s bound,300s warm drain,advance-planned commands;no reactive controller |
| Arrival/oldest age/throughput/startup/drain/latency/memory/disk evidence | PASS; raw,window aggregates and exact Docker lifetimes;disk stop retained |
| Queue bound and final sustained backlog drain≤300s | PASS in all12eligible arms;no unbounded continuous-arrival guarantee inferred |
| Short-job starvation bound | PASS for tested schedule;manual p90≤fixed3+30s in all3pairs;all queued waits≤300s |
| Churn/useful resource benefit | FAIL adoption threshold;13.28/14.80/14.58%residency reductions<20%;startup/drain overhead included |
| Statusp90≤700ms/errors<1% | FAIL latency in all12sustained windows;timed errors0/68166status samples;one warmup timeout retained |
| Loginp90<2s | PASS in all12sustained windows;1.565–1.754s;no isolated-login acceptance rewritten |
| Worker loss/failure visibility≤300s | PASS all3;77.241/76.991/65.951s;intentional failures and explicit stored retries |
| Queue-list loss repair≤120s | PASS all3;22.480/21.600/24.477s |
| Full Redis loss/durable reconstruction≤120s | PASS all3;12jobs each,23.707/22.991/21.335s;original attempts preserved |
| Durable queued backlog across namespace restart≤300s | PASS all3;12jobs each,122.820/125.476/123.963s;original attempts/one primary preserved |
| Arbitrary active work beyond former60sgrace safely drains≤300s | PASS;real180ssource,processing70.823s,warm drain70.589s,same attempt,MP4/HLS,exit0,no force/OOM |
| Cold good promotion≤600s | PASS;118.568s;exact image tests/offline scan/clean source;Media unchanged |
| Cold bad candidate restoration≤300s | PASS;whole failed-candidate+tested-image-restoration145.357s;expected exit42;Media unchanged |
| Active-work rollback≤300s | PASS;72.669s,unchanged attempt,one primary;rollback operation72.608s |
| Zero lost/duplicate outputs/stale publication/OOM/ownership failures | PASS in tested eligible and fault outcomes;intentional killed attempts distinguished from lost jobs;original interrupted accepted work settled |
| Whole-host windows/availability/durable-state cost proof | NOT ADOPTED/NOT EXECUTED;namespace restart is local durable proof;no VM/cloud power-window or bill-saving claim |
| Actual output/request/decoded transfer inputs | PASS with stated scopes;22,222,111,464B/11,592objects;HTTP ledgers;3real60sdecoded playback starts |
| Original demo restored | PASS;exact original9containers/images f10bf04899e6cc80f992c65193a92fbe0b0ce8b2 at https://localhost:54440;11.432s including public workflow |
| Raw publication/decision gist/fresh independent Sol review/PR | Local indexed evidence supplied;parent-owned remote publication/review remain pending;no new remoteCI claim |

Playback-start completed response transfers for the three 60s clips were
13/12/12 requests and 5,174,856/4,158,152/4,158,152 bytes. These are observed startup
transfers, not extrapolated full viewing traffic. Original demo restoration also
read and hashed a609,355-byte primary output from a fresh2s job;that synthetic
Asset was deleted after the availability proof.

The predeclared disk early stop and warmup timeout remain failed observations.
They are not erased by passing recovery checks. Both #38 and #39 hypotheses are
rejected, no runtime default is changed, and accepted historical targets remain
unchanged. The original demo retains accepted f10bf04 images, so restoration does
not claim that its images were rebuilt to PR37.
