VERDICT: REVISE
ISSUE: #22 (V3); parent #6 (E5), dependency #20 (V1)
PR: local branch work/evidence; no GitHub access
HEAD: ecd9d5f4d5b43cfa2bd40bb1338353e30df7ab59
BASE: 702b5f8 (HEAD^)

Independent bounded review of the runner only, completed 13 October 2026.
The approach is viable. Fix the five findings below before relying on the pilot
or full-run artifacts. This verdict does not depend on experiments having run.
Actual V3 experiment acceptance remains pending separately.

Reviewed the complete four-file diff, AGENTS.md, project2-worklog.txt,
issues/V3.md, issues/V1.md, issues/E5.md, plan.md, the implementation handoff
performance-runner.md, and the frozen design08 evidence protocols. Read-only
compatibility checks used current Processing in the root at
d534184e92f72afcd851b7e2866e18cca0622305 and Media/Compose in integration at
b146921a671d41adcaa838ff2be199a1df47dd87. Those moving product branches are
context, not additional reviewed changes. RQ 2.12.0 and fakeredis 2.39.0 match
the local lock/environment.

ACCEPTANCE:

- [pass] Statistical calculations: nearest-rank ceil(0.9*N), all timed latency
  attempts including timeouts, status <=700 ms and strictly <1% errors, login
  strictly <2000 ms, successful jobs*60/full makespan, median throughput by
  worker count, pooled queue waits, per-run medians/ranges, >=1.6x / >=2.1x,
  strictly decreasing median queue wait, and zero failed scaling jobs. Failure
  time is included. The separate login error gate needs correction (R5).
- [pass] Declared full workload: nine rotated runs (1,2,3 / 2,3,1 / 3,1,2),
  30 fresh measured Assets per run from one hashed 60-second 1280x720 H.264/AAC
  fixture. No reduced pilot or fewer than three repeats is acceptance-eligible;
  dirty-tree results cannot claim acceptance. Eighteen warmup submissions are
  scheduled, but per-replica delivery is not established (R1).
- [pass] Capacity and limits: requires eight Docker CPUs plus other namespaces'
  reservations; eight fixed nonworkers total two CPUs; reserves three 1536 MiB
  worker caps plus bounded fixed/other memory caps. Rejects insufficient capacity,
  uncapped other containers, unexpected services/replicas, incorrect worker
  Docker/cgroup v2 limits, and effective worker CPU sets smaller than two CPUs.
  Fixed identities/images/resources are compared across scaling configurations.
- [pass] Clocks and bounds: host monotonic makespan starts after the first 202
  acknowledgement and ends at final terminal observation; aware server clocks
  supply attempt intervals with ordering validation. HTTP total/phase bounds,
  subprocess bounds, polling bounds, and whole-action deadline are present.
  Cleanup may extend the action deadline as documented. Cancellation state
  tracking still has a concrete gap (R3).
- [pass] Status/login load construction: distinct owners and cookie jars,
  50 status clients and separate 20 login clients, 30-second warmup and
  180-second full intervals, three repeats, and closed-client one-second pacing.
  Focused short offline phases reached 50 and 20 simultaneous mocked requests.
  This validates scheduling, not real server concurrency, duration or latency.
  The completed-Asset endpoint mix is declared explicitly.
- [pass] Current HTTP/parser/configuration compatibility: public upload returns
  an Asset ID in job_id; auth returns id and access_token; status uses id/status;
  private batch uses asset_ids plus service token and X-Owner-Id. Selected current
  Job/Attempt identities, owner, source digest and terminal timing fields match
  Processing. Attempt changes fail rather than conceal retries. Current encoder
  AST defaults parse as veryfast/CRF 23; version/policy and image digests are
  retained. CLI help/options parse. Optional HLS absence stays visible.
- [fail] Legitimate clean queue and deterministic worker warmup: R1/R2.
- [fail] Cleanup after cancellation and retained actual failed operations: R3/R4.
- [fail] Proposal-only login target reporting: R5.
- [pending, outside this review] Real pilots; 50 users/180 seconds and separate
  20-user login measurements; nine full 30x60-second scaling runs; observed
  throughput, queue/processing time, failures and resources. No live result or
  capacity limitation is asserted here. Parent owns wiring, final image/config
  verification, P3 integration and experiment acceptance.

FINDINGS:

R1 [P1] Pausing other replicas does not guarantee the chosen worker gets a warmup.
Location: scripts/evidence/performance.py:767-790;
tests/evidence/test_performance.py:480-489.

All replicas are started before the nonselected replicas are paused. Current
Processing uses a normal blocking RQ Worker; locked RQ's single-queue dequeue
uses Redis BLMOVE into an intermediate list. A paused container retains its
already-issued blocking Redis request. Redis can deliver the new job to that
connection while its worker is frozen, leaving the selected worker without the
job. The run can wait for repair/deadline, and warmups.jsonl records the selected
worker ID without observing which worker actually consumed the attempt. The
existing scheduling test assumes that only an unpaused worker can receive work,
so it does not exercise this failure mode.

Required change: isolate warmup consumers by disconnecting/stopping nonselected
owned workers before enqueue, or an equivalent deterministic mechanism; verify
the selected replica's execution. Preserve the existing one-warmup-per-replica
protocol. Add a focused offline regression covering a pending dequeue on a
nonselected replica. No product feature or new security infrastructure is needed.

R2 [P1] The clean-queue test ignores RQ's intermediate list.
Location: scripts/evidence/performance.py:448-458, 654-667, 750-756, 832-838.

The diagnostic checks only ready IDs and StartedJobRegistry. Between BLMOVE and
worker execution registration, an attempt exists in neither; it is in
rq:queue:<name>:intermediate. This state can persist after a paused/interrupted
worker. A previous attempt can therefore pass the empty-queue preflight or hide
beside an exact measured ready set, then cause delayed work/repair during the
experiment. The runner has not established the clean baseline it claims.

Offline reproduction used real locked RQ with FakeRedis, not a Redis service:
enqueue old-attempt; call Queue.lmove(connection, queue.key, timeout=1); read
the runner's two snapshot fields. Both are empty; wait_queue(expected=[]) returns
success while IntermediateQueue(queue.key, connection).get_job_ids() still
returns [old-attempt].

Required change: include read-only intermediate membership in the retained queue
snapshot. Require it to be empty for clean and prelaunch measured-backlog checks,
and fail visibly on unexpected work. Do not run registry cleanup or erase data.
Add the FakeRedis regression to the existing offline selection.

R3 [P2] Cancellation after pause succeeds can leave an owned replica paused.
Location: scripts/evidence/performance.py:41-50, 770-771, 794-797, 902-908.

blocking() waits for the subprocess to finish, then re-raises cancellation.
However, paused.add(worker_id) occurs only after that await returns. If the action
deadline cancels during pause, the pause can succeed while the cleanup set stays
empty. Neither finally block then unpauses that replica; stop may fail against
a paused container. An offline event-controlled mutation reproduced this: pause
finished, cancellation propagated, cleanup issued zero unpause calls, and w1
remained paused. The existing cancellation test checks ordering only.

Required change: track attempted mutations before cancellation can escape, and
reconcile the actual pause state of the known owned replicas during cleanup.
Attempt cleanup for every affected replica even if one cleanup call fails, then
report the failure. Add cancellation-during-pause coverage using the actual
scaling control flow.

R4 [P2] Failed operations lose actual request data and partial-backlog identity.
Location: scripts/evidence/common.py:120-124;
scripts/evidence/performance.py:602-610, 802-831, 947-972.

checked() discards the safe latency/status/error sample. Scaling keeps successful
upload Asset IDs only in memory until the complete backlog reaches wait_jobs().
If a later upload times out, the already-acknowledged measured Assets are absent
from all artifacts. A focused scaling simulation confirmed that one successful
measured acknowledgement followed by an upload timeout leaves its Asset ID
nowhere in the retained records. The failure manifest keeps only a generic
operation/error label, not the actual status or duration. Separately, login
discards logout's sample and folds failure into the login row. An offline phase
with twenty logout 503s retained twenty login rows reporting status_code=200 and
logout_failed, but no logout statuses or durations.

Required change: immediately retain a selected acknowledgement record for every
upload, including phase/sequence, Asset ID, timestamp and safe request sample;
retain failed submission/private observation samples as well. Record logout as
its own untimed operation so login p90 remains login-only. Keep its real status,
duration and error category. Response bodies, passwords, cookies and URLs are
not necessary. Add failure-after-partial-submission and logout-failure checks.

R5 [P2] Login acceptance adds a zero-error threshold absent from the proposal.
Location: scripts/evidence/performance.py:84, 1079-1083;
docs/execution/reviews/performance-runner.md:158-162.

latency_metrics(login) sets errors_pass to errors==0 and performance requires it
for criteria_pass. V3 specifies login p90<2 seconds; design08 content.json:41
explicitly says to report error count without inventing a proposal error
threshold. An offline sample with p90=100 ms and one error passed the specified
latency target but failed the runner's additional gate. The scaling zero-failure
target and status <1% target do not supply a login error threshold.

Required change: report login error counts and operational/protocol failures
explicitly, while keeping the proposal login target assessment strictly tied to
p90<2 seconds. Distinguish invalid preparation/protocol eligibility from a new
numeric acceptance target. Correct the handoff wording and add a regression for
proposal target reporting; do not relax status or scaling thresholds.

CHECKS:

- Root .venv/bin/python -m pytest --confcutdir=tests/evidence
  tests/evidence/test_performance.py -q --timeout=5: 48 passed in 0.10 seconds.
- Root .venv/bin/ruff check scripts/evidence tests/evidence/test_performance.py:
  passed.
- Root .venv/bin/python -m scripts.evidence.performance --help: passed.
- git diff HEAD^ HEAD --check: passed.
- Additional inline offline assertions: real RQ/FakeRedis intermediate-list
  blind spot; event-controlled cancellation inside scaling pause; partial
  backlog acknowledgement omission; 50/20 mocked concurrent phase launches;
  discarded logout 503 samples; login target mismatch; encoder AST evaluated
  against current Processing config. All completed with the expected outcomes.
  Mock latency values and shortened intervals are not experiment evidence.
- No container commands, network services, GitHub access, child agents, product
  edits or live experiments were used. Probe records were held in memory.

SCOPE:

Only docs/execution/reviews/performance-runner-review.md is written by this
reviewer. No merge or release authorization is implied. The original proposal
targets, source documents and roadmap remain intact. Sampled Docker memory is
accurately described as sampled container usage, not exact process peak RSS;
the shared physical generator host is an explicit local limitation.

FOLLOW_UP:

Fix R1-R5 in the existing runner lane and recheck those changes. Parent can then
run the bounded pilot and full experiments against its final integrated head,
retaining failures and reporting measured pass/fail. Pending live acceptance is
not a reason for this runner REVISE verdict and is not marked BLOCKED here.
