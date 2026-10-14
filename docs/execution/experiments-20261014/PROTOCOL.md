# Local experiment protocol, fixed before live trials

Baseline product b913579be16ca7f1fb9f685e287d905bfbcfbd6a (#37).
Historical acceptance and scripts/evidence/performance.py remain unchanged.
No quota or scheduling configuration is adopted by running these trials.

## #38

One redistribution: PostgreSQL0.125→0.25CPU, ProcessingAPI0.5→0.375CPU.
Every other quota and memory ceiling unchanged. Nonworkers sum2CPU/2304MiB;
workers each2CPU/1536MiB, maximum3. Recovery and startup allowances retained.
Immutable images, identical opt-in SQL/pool timing instrumentation in both arms.
Pool connect timing includes pre-ping/creation; it is not solely pool saturation.
Query timing includes driver/network/server wait; server wait categories sampled
without query/parameter/user data. cpu.stat/cpu.pressure and memory events/peak
sampled per container; VM CPU/memory/I/O pressure and disk space also sampled.
Verify measured account hash algorithm/cost directly, never record full hashes.

Three pairs ordered baseline/variant, variant/baseline, baseline/variant.
Each arm:50completed-Asset status owners and20login owners; each isolated topic
30s warmup+180s timed, then simultaneous50status/20login30s warmup+180s timed
while publishing a fresh30×60s1280×720H264/AAC batch to3workers. Count all
30outcomes and timings beyond the interactive interval. Decode actual HLS/MP4
in the scoped trusted project browser during mixed load; record transferred bytes
and response counts. Delete only this arm's experimental Assets after evidence.
Fresh owners per arm; same deterministic fixtures. No competing namespaces.
Queue-loss/worker-loss and cold good/bad promotion/restoration on both profiles
after paired trials if correctness permits; comparisons do not use old images.

Rejection gates: statusp90>700ms or errors≥1%; loginp90≥2000ms; queue repair>120s;
worker failure>300s; promotion>600s; restoration>300s; any OOM, lost/duplicate
outcome, stale publication or ownership breach. Donor publication/recovery worsens
means >10% worse median paired throughput/processing or repeated repair/release
regression beyond natural timing resolution (a1s margin). Adoption additionally
needs statusp90 improve≥5% in all3pairs with lower PostgreSQL throttle time and
SQL time, and no gate regression. Thresholds distinguish noise from improvement.
Failed latency gates reject adoption but do not silently shorten safe workloads.
Exact early stop: any correctness/OOM/ownership breach, disk free<2GiB, or
nonconvergent recovery stops the current hypothesis; retain partial data and mark
unexecuted criteria explicitly. Latency alone is not an early-stop shortcut.

## #39 (only after #38 decision)

Use accepted baseline quotas if #38 rejected. Compare fixed1/2/3workers and
manual scheduling in3rotated repetitions:1,2,3,manual;2,3,manual,1;3,manual,1,2.
Every arm executes the same arrivals and fixtures in four successive windows:
idle-gap:3short arrivals at0s, next3short at90s; burst:12long simultaneous;
sustained:12long arrivals every20s; mixed:alternating6long/6short at2s spacing.
Windows begin after previous outcomes settle, with a60s idle observation between
windows. These are explicitly new workloads, not substitutes for historical
30×60s scaling. Three pairs for each fixed comparator use the same repeat index.

Manual policy eligibility, sampled every2s: retain1warm worker while demo available; activate
3 when ready backlog≥3 or oldest queued age≥30s; hold until queue empty and all
workers idle for60s; then warm SIGTERM surplus replicas and wait up to300s for
exit/terminal durable outcomes before removing/restarting them. Never downscale
an active worker by a60s force-kill. Queue bound300s for all job classes; this
matches the existing maximum failure visibility/recovery budget and is more
than3×60s clip duration. Reject if any queued short job exceeds300s, queued age
exceeds300s, or final sustained-window backlog fails to drain within300s after
last arrival. Baselines may fail new window bounds; report failures honestly.
Useful benefit: manual worker-seconds≤80% of fixed3, all outcomes/gates pass,
manual mixed short-job p90 wait≤fixed3+30s; otherwise reject this manual policy.
Manual action plan fixed before trials:1worker throughout the idle-gap window;
activate3 at the start of each known burst/sustained/mixed processing window;
after outcomes settle+60s idle, warm-drain the surplus2. The backlog/age thresholds
are operator escalation criteria, not an automated queue controller. This tests
advance-planned demo/processing windows, not reactive autoscaling. Fixed arms
retain their1/2/3replicas across all four windows; record every operator command.
Each sustained window also runs50status/20login owners30s warmup+180s timed.
Source/encode settings stay fixed.

Fault proof: durable queued backlog across full namespace stop/start preserving
volumes; Redis delivery loss; killed worker and stored retry; active-work rollback;
one explicitly active >60s-processing job safely drains (180s source, same quality)
within300s without a forced signal or outcome loss. Repeat fault experiments3times
for manual policy where practical; whole-host *cloud* windows not adopted from a
namespace restart. Original demo must be restored and smoke checked at finish.

Running-host worker capacity savings are never cloud bill savings. Account/region
are unavailable; record output object bytes/count, HTTP request and decoded
playback transfer inputs for later all-in$200/approximately3week costing. No
prices, affordable SKU or lower-memory claim. Parent owns gist/PR/remote metadata
and fresh independent review. Raw records compressed with stored/decompressed
hashes and exact source/config/fixtures in an index.

Observer correction after failed invocation1:large uploads use a bounded120s
HTTP/body observation deadline; status/login retain10s request observers and all
original numeric gates. No upload retries. Invocation1 remains failed and is not
spliced; all three paired comparisons restart fresh.

Observer correction after failed invocation2:wait for authenticated app/card
visibility and count redirect bodies as0bytes; decode gates remain unchanged.
Run a separate scoped decode preflight before fresh full pairs. Window uploads
also use120s observer; worker Docker start/finish timestamps supplement the
modeled window residency. No failed invocation is spliced into full comparisons.

Invocation3 is invalid for adoption:SQL/pool hooks were imported in health-check
Python processes as well as the API, adding approximately0.28CPU-seconds per
probe (measured paired process CPU). Restrict hooks to API PID1; no strength/quota
change. Stop and retain all partial records; repeat full3pairs fresh. Required
sampler failures cancel new workload actions instead of silently losing coverage.
Actual output bytes/counts must include all Processing prefix objects, not only
registered primary/master descriptors. Trivy uses a worktree-local copy of the
parent's pinned DB; parent cache/binary and frozen measurements remain untouched.
