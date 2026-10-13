VERDICT: PASS
ISSUE: #22 (V3); parent #6 (E5), dependency #20 (V1)
PR: local branch work/evidence; no GitHub access
HEAD: 24b1aa43f047dc0b05a6841464fa9aecd3564dfa
BASE: ecd9d5f4d5b43cfa2bd40bb1338353e30df7ab59

Independent bounded R1–R5 rereview completed 13 October 2026. All five prior
runner findings are resolved at this HEAD. This is the final runner verdict;
V3's live experiment acceptance remains parent-pending separately.

Read the review-work skill, AGENTS.md, docs/project2-worklog.txt, V3/V1/E5 issue
contracts, execution plan/decisions/interfaces, the complete correction diff,
performance-runner-review.md, performance-runner-fixes.md and the full original
performance-runner.md handoff. Checked the frozen design08 E-01/E-02/E-03
protocols and metric definitions. The correction note explicitly supersedes the
original handoff's affected pause, queue, cleanup and login-gate wording; those
historical statements are not the current runner contract. The retained prior
review still hashes to blob 32e5b412c7ad5c0bf34b886ee41fcc48a7cca369.

ACCEPTANCE:

- [pass] R1 — Deterministic replica warmup. performance.py:885–939 stops every
  nonselected owned worker with a ten-second stop grace, starts the selected
  existing container, and inspects before submission and after completion that
  it is the only running owned worker and no known replica is paused.
  Docker.warmup_assignment at :496–511 reads the completed Attempt's RQ job
  worker_name and worker hash hostname; :926–933 rejects missing/mismatched
  execution identity after retaining the observation. Scheduling no longer
  assumes a paused worker cannot steal a job through its pending Redis dequeue.
  test_full_selection_prequeues_and_warms_every_replica models pending dequeues
  independently of execution state and checks all 18 individual warmups.
  test_wrong_warmup_assignment_is_retained_and_rejected verifies rejection and
  cleanup. The real RQ/FakeRedis assignment diagnostic test confirms the selected
  RQ fields, rather than merely mocking their shape.

- [pass] R2 — Intermediate membership is visible and disqualifying.
  performance.py:450–464 retains ready, intermediate and started Attempt IDs;
  :770–788 requires intermediate and started lists to be empty for both clean
  preflight and exact measured-backlog readiness. Missing ready work may be
  awaited, but extra, duplicate or intermediate work fails visibly. The two
  test_real_rq_intermediate_entries_fail_clean_and_prelaunch_checks cases execute
  the actual diagnostic against locked RQ/FakeRedis after Queue.lmove. Both
  expected=[] and an otherwise exact measured ready set are rejected while the
  old intermediate entry remains intact. No registry cleanup or deletion occurs.

- [pass] R3 — Cancellation-safe owned-worker cleanup. Scaling creates no paused
  state. start_workers records IDs inside the bounded mutation before
  cancellation escapes (:424–448); blocking waits for that mutation (:41–50).
  stop_workers (:513–538) combines tracked IDs with scoped discovery, validates
  ownership/state, unpauses a discovered paused replica, stops and verifies each
  worker, and continues with the remaining replicas after a worker failure.
  Per-worker outcomes are retained in cleanup.jsonl before aggregate failure is
  raised. Inner and outer finally paths invoke cleanup; the outer path closes
  both clients even if worker cleanup fails (:1054–1060).
  The suite exercises cancellation inside actual scaling warmup isolation and
  continued cleanup after a stop failure with paused replicas. Additional
  event-controlled probes used the actual Docker.start_workers implementation
  during warmup launch and measured launch, cancelled after IDs were tracked,
  and returned no IDs from cleanup discovery. Both still stopped every tracked
  worker, disconnected pending dequeues and closed clients. The measured-launch
  probe preserved all 30 acknowledged measured Assets. Docker calls remain
  bounded at 30 seconds and Compose at 120 seconds; cleanup may extend the
  action deadline as documented.

- [pass] R4 — Partial identities and actual failed request samples survive.
  upload (:698–724) immediately closes an append to submissions.jsonl with
  phase/sequence, Asset ID, UTC/acknowledgement monotonic clock and the actual
  elapsed/status/error sample, before returning or raising. Every scaling
  warmup/measured upload and status-fixture upload supplies artifacts. The first
  captured acknowledgement starts makespan before artifact-writing overhead.
  Client.checked (common.py:120–126) retains safe HTTP samples before errors
  escape, including private observations and owner preparation. Login rows are
  appended before logout; logout receives its own untimed operations.jsonl row
  with repeat/client/sequence, interval context, real status, duration and error
  (:1110–1139), without rewriting the login result.
  The suite verifies a successful measured acknowledgement followed by timeout,
  failed private observation and twenty independent logout 503 records.
  Additional delayed MockTransport probes retained an upload timeout of
  32.10 ms and private 503 of 17.24 ms with the earlier Asset still present.
  A separate logout 503 retained 27.27 ms while login-only p90 remained 6.88 ms.
  These are synthetic probe durations, not product latency measurements.
  Selected records exclude response bodies, credentials, cookies and URLs.

- [pass] R5 — Proposal-only login assessment. latency_metrics (:68–85) reports
  login errors/error fraction and returns errors_pass=null, while preserving
  the strict p90 <2000 ms target. performance (:1249–1283) reports timed, warmup
  and logout errors; numeric criteria do not impose a login zero-error gate.
  Invalid session/status protocol observations and failed preparation are
  distinguished from numeric targets. Protocol eligibility is required for
  acceptance, and invalid protocol causes CLI exit 1 independently of the
  numeric assessment (:1416). Tests verify that ordinary login/logout errors
  remain reported without introducing an acceptance threshold, while invalid
  login sessions make the run ineligible. Status still requires p90 <=700 ms
  and strictly <1% timed errors; scaling still requires zero failed jobs.

- [pass] Frozen full protocol and interfaces. AST comparison against BASE
  confirms p90, run_order, attempt_record, scaling_metrics, scaling_targets,
  capacity_check, worker_quota, fixture and parser are unchanged. Full selection
  remains nine rotated configurations (1,2,3 / 2,3,1 / 3,1,2), 30 fresh measured
  Assets per run from one hashed identical 60-second 1280x720 H.264/AAC fixture,
  plus 18 individual warmups. The scheduling test observes 270 measured and 18
  warmup acknowledgements, all distinct. Each worker retains hard 2 CPU /
  1536 MiB Docker and cgroup checks; eight fixed nonworkers total 2 CPU; capacity
  requires eight Docker CPUs plus other namespaces' reservations and bounded
  memory. Full status/login defaults remain separate 50/20-owner tests with
  30-second warmup, 180-second intervals and three repeats. Pilot, reduced-repeat
  and dirty-tree results remain ineligible. Throughput, failure inclusion,
  speedup and falling pooled median queue-wait targets remain unchanged.

- [pass] Current parent source compatibility, checked read-only. Processing was
  inspected in the root at 013e2194a52eadb4f0074dea8dad81c0127ca1ee;
  Media/Processing/Compose/runtime source was inspected in integration at
  42091584456bc01d7efa271f69e74b617e5dddf6. Media returns AssetId in upload job_id,
  owner id in auth responses, access_token cookies and logout 204; public status
  exposes id/status/submission_status. Processing batch accepts comma-separated
  asset_ids with the forward Bearer token and X-Owner-Id, and returns the selected
  Job/Attempt/source/timestamp fields. Current worker uses RQ Worker; enqueue
  reserves Attempt UUID as the RQ ID with retained results. Encoder defaults and
  PROCESSING_ environment names match the runner's source AST diagnostic.
  Integration Compose matches the frozen service names, CPU split and worker
  memory cap. No relevant product/config source changes were present in that
  integration working-tree diff during inspection. These source checks are not
  claims about running images. Pure helper signatures remain stable; documented
  optional artifact/context keywords and login errors_pass=null are compatible
  with the inspected parent consumers. No cross-service product import or DB
  access was added; RQ diagnosis remains Processing-owned and read-only.

FINDINGS:

- None remaining within the bounded R1–R5 correction scope.

CHECKS:

- Root .venv Python, from the evidence worktree:
  PYTHONDONTWRITEBYTECODE=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python
  -m pytest -p no:cacheprovider --confcutdir=tests/evidence
  tests/evidence/test_performance.py -q --timeout=5 — 63 passed in 0.67 seconds.
- Root .venv/bin/ruff check --no-cache scripts/evidence
  tests/evidence/test_performance.py — passed.
- Root .venv/bin/python -m scripts.evidence.performance --help — exit 0.
- git diff ecd9d5f 24b1aa43f047dc0b05a6841464fa9aecd3564dfa --check — passed.
- Additional inline offline probes — actual start mutation cancellation during
  warmup and measured launch; retained partial-backlog identities; delayed
  failed upload/private HTTP samples; separate delayed logout sample; frozen
  helper AST equality. All final assertions passed. Probe data used disposable
  system temporary directories; no probe files were added to the repository.
- Installed diagnostic dependencies: RQ 2.12.0, fakeredis 2.39.0,
  HTTPX 0.28.1. No Redis service or other external service was used.

SCOPE:

Only docs/execution/reviews/performance-runner-rereview.md is written by this
reviewer. No application code or parent configuration was modified. No GitHub,
container, child-agent or live-experiment operation was performed. The correction
stays within the existing runner and 80/20 scope. No feature expansion, merge or
release authorization is implied.

FOLLOW_UP:

Parent owns the bounded live pilot, final integrated image/configuration checks
and full performance/scaling measurements, including retained failures and
measured target results. These deliberately pending measurements are not a
finding or condition on this runner PASS. V3/E5 experiment acceptance remains
open until that evidence is collected and assessed.
