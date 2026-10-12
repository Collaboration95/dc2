VERDICT: REVISE
ISSUE: #12 (P1), #13 (P2), #14 (P3); parent #3 (E2)
PR: [#28](https://github.com/Collaboration95/dc2/pull/28), branch `wave/02-processing`

Independent grouped review, 13 October 2026 (Singapore).
Base: `49b693ef8392d33d756f217d30e3a9e4d2205002` (merged foundation).
Reviewed product/test/tooling head: `810a8a6911959f26da4e5ce38760d47e538d2a79`.
Reviewed PR head: `a702da5ce97115c9283554aa88ab8d963553b93b`.
Changes through `d5097d95bc700832072612efd38dad13fe7ce0d5` are documentation only,
including `processing/README.md`. This review also includes the parent's
subsequent committed correction to `scripts/dev/owned_checks.py`, Git blob
`1e98e2bf07d71e4efe901c7edea2026d688034f4`: persistent-service readiness is followed
by checked foreground bootstrap/migration commands. Processing production and
tests still match `810a8a6`. Both coverage fragment fingerprints match the final
reviewed head's production, tests, locks and tooling.

The audit is complete for this head. One substantive recovery defect remains:
cleanup of an older attempt can block the heartbeat of a healthy current retry.
This is a final REVISE assessment, not a provisional PASS or merge authorization.

ACCEPTANCE:

- [pass] P1: reserved attempts and conditional terminal fences — Job-row locking,
  current Attempt ID, unique lease token, deletion, DB-clock lease and deadline
  checks protect claim, heartbeat, success and failure. Real PostgreSQL tests
  exercise eight concurrent claims, expired authority and delayed success/failure
  after retry and cancellation. Verified primary descriptors must precede success.
- [pass] P1: durable retry identity and state/owner restrictions — retry creation,
  `(job_id, request_id)` recording and current-attempt replacement commit together.
  Eight concurrent identical retries reserve one attempt; replay after success
  creates none. New requests in nonfailed states return 409; another owner gets
  404; tombstones reject retry. The frozen OpenAPI/CT-06 explicitly returns the
  current job on replay, which this implementation follows.
- [pass] P1: cancellation by AssetId in both race orders — submit/cancel lock the
  same retained owner-bound guard. Real cancel-first, submit-first and concurrent
  tests reject delayed submission with 410, hide cancelled jobs and reject stale
  work. Cancellation does not require possession of a lost Submit response.
- [pass] P1: independent additive migrations — `processing_0002` extends its own
  `processing_0001`; no Media tables or cross-service foreign keys. Offline
  migration checks and the coordinator's actual migration/role-denial tests pass.

- [pass] P2: queue identity, single claim and engine reuse — RQ payload contains
  the reserved Job/Attempt UUIDs; SQL claim is authoritative. Helpers retain
  inherited command/validation behavior with recorded provenance and no service
  settings/ORM imports. Real repeated execution cannot claim a completed attempt.
- [pass] P2: renewable private source access — every claim obtains a reverse-HTTP
  grant using the owner and revision, compares the complete immutable descriptor,
  and verifies downloaded length/SHA-256. Tests exercise expired access, a denied
  first GET, descriptor drift and digest failure. The live storage test proves
  that the output writer cannot read Media's source or HEAD/Get outputs.
- [pass] P2: attempt-specific MP4/HLS and inherited conversions — real FFmpeg
  MP4/HLS, MKV and MP3 outputs decode successfully. HLS remains optional; ordinary
  HLS failure preserves primary output. Cancellation/deadline exceptions propagate
  through the fallback instead of being converted into success.
- [pass] P2: playable output and stale publication rejection — actual short
  media completes through real PostgreSQL and scoped MinIO, with acknowledged
  PUT plus local size/digest descriptors. Namespace and live-attempt fences reject
  stale success and failure; retries cannot replace the winning output set.
- [pass] P2: supervision across all worker stages — renewal/download, probe,
  encode and upload use one supervisor/deadline. Offline tests stop the process
  group, including descendants after the leader exits, interrupt pending I/O,
  and prove the budget is not reset between stages. R1 is a recovery interaction
  that prevents P3's healthy-worker criterion from passing.

- [fail] P3: interruption detection and healthy long encoding — DB-clock expiry
  and independent heartbeats are implemented. A killed actual worker-task OS
  process is detected with a shortened real lease and then successfully retried.
  Healthy retries can nevertheless lose supervision during old-attempt cleanup
  because that cleanup holds their Job lock: R1.
- [pass] P3: durable queued delivery repair — real Redis list loss with a surviving
  RQ hash is repaired using the same reserved payload. Membership checks inspect
  the runnable list/live started registry rather than hash existence; expired
  registry metadata is covered offline. Default polling/backoff is bounded at
  15/60 seconds. This is owned repair evidence, not the later V2 topology timing
  experiment.
- [pass] P3: reserved-attempt reconciliation, observable backoff and output-only
  cleanup — dispatch counts/errors/next retry and cleanup tries/errors persist;
  errors and logs omit capabilities. Cleanup uses the separate List/Delete
  principal and attempt prefixes. R1 requires changing its lock lifetime.
- [pass] P3: killed worker followed by stored-source retry — real PostgreSQL
  observes the independent heartbeat before OS process death. Recovery abandons
  that attempt; the retry encodes real media and publishes one winning primary
  under its new attempt UUID. No original source re-upload is used.
- [pass] P3: repeated late-write cleanup and source/winner protection — cleanup
  intents survive empty/successful scans. Real MinIO late PUTs are removed by
  another scan; source deletion is denied and its original bytes remain intact.
  Additional real PostgreSQL tests protect active/winning prefixes even from an
  erroneous intent. These safety properties must be retained when fixing R1.

FINDINGS:

- [P1] R1 — `processing/recovery.py:147–170`, especially the Job lock at line 150
  and awaited object deletion at line 164; `processing/worker/supervisor.py:50–59`.
  `cleanup_outputs()` holds `SELECT ... FOR UPDATE` on the Job throughout S3
  listing/deletion. Cleanup of failed/abandoned attempt A is allowed after retry B
  becomes current and starts processing. B's independent heartbeat needs the
  same Job lock through `lifecycle.lock_pair()`. If A's cleanup is slow, that
  heartbeat times out and sets lease loss, stopping B's download/encoder/upload
  even though B's SQL lease remains valid. The default heartbeat wait is 10s;
  the storage read timeout alone is 15s, and a prefix scan may make multiple
  requests. SQL time and attempt-token fences therefore do not prevent this
  healthy-worker interruption. It can turn a valid stored-source retry into
  another abandoned attempt, and also delay retry/cancellation on the Job.

  Required change: perform remote cleanup without retaining the Job lock. Check
  eligibility under the normal lock order, ensure the selected attempt cannot
  become active/winning, release that lock for object I/O, then record the result
  safely. Preserve repeatable intents, deletion fences and active/winner/source
  protection. A small change to cleanup transaction boundaries is sufficient;
  no new security or service architecture is requested.

  Reproduction: the reviewer ran the unchanged `cleanup_outputs()`,
  `lifecycle.heartbeat()` and `Supervisor` against session doubles with a shared
  asynchronous Job-row lock. An old failed attempt's `delete_prefix()` was held
  while the current processing attempt had an unexpired lease/deadline. Output:
  `healthy_current_SQL_attempt_still_live=True`,
  `supervisor_revoked_during_old_attempt_cleanup=True`,
  `cleanup_holds_Job_lock=True`; releasing storage completed cleanup. The
  heartbeat interval was shortened to 0.05s. This is a deterministic contention
  reproduction, not claimed as an additional real PostgreSQL test.

  Required proof: add a real PostgreSQL regression that fails on this head. Fail
  A, reserve/claim retry B, hold A's cleanup at the storage boundary for longer
  than B's heartbeat timeout, and run B's real supervisor/heartbeats concurrently.
  While deletion is still blocked, multiple heartbeats must advance in SQL, B
  must remain live and its work must not be cancelled. After releasing cleanup,
  B must publish successfully; only A's prefix may be removed. Retain the real
  late-PUT and source/active/winner protection cases. Rerun owned tests, package
  gates and the PR checks on the corrected product head.

CHECKS:

- Reviewer: 244 focused offline tests passed in 1.09s:
  `.venv/bin/python -m pytest -q -p scripts.dev.pytest_plugin --offline-fast
  tests/processing tests/media_engine tests/contracts --no-cov -p no:cacheprovider`,
  launched with the repository's `fast_env()` and bytecode writes disabled.
- Reviewer: scoped Ruff with `--no-cache` and complete diff whitespace checks
  passed. Inspected the complete branch diff, contracts/CT cases, migration chain,
  real/fake test boundaries, worker/RQ entry points, runtime and CI wiring.
- Reviewer: both coverage metadata fingerprints match final reviewed head
  `a702da5`; every production Python file outside migrations is measured.
  Recomputed combined/raw branch rates from the existing JSON without changing
  coverage artifacts. The parent refreshed the evidence after the helper change.
- Coordinator evidence, read from
  `.cache/execution/processing-final-{fast,owned,gate,runtime}.log`: 635 offline
  Python tests passed in 4.00s; 41 real owned PostgreSQL/Redis/MinIO/FFmpeg tests
  passed in 6.70s with all three Processing flags enabled and no selected skips.
  The implementation agent's 35 owned cases exclude the six DB ownership cases;
  those figures are consistent.
- Existing combined package gate: Processing 98.31% (raw branches 93.60%);
  `media_engine` 99.42% (98.00%); inherited `app` 86.77% (78.70%).
- Coordinator's actual runtime boot/smoke passes with API, worker and recovery,
  migrations, scoped private storage and separate DB roles. Worker is capped at
  2 CPU/1536 MiB; recovery receives the cleanup principal. API/worker/recovery
  share the Processing image. No Media workflow acceptance is inferred from this.
- PR #28 and CI run 38288179878 were inspected read-only through authenticated
  `gh`, on `d5097d9`. Fast checks, frontend, legacy integration, Firefox trust and
  both app/Processing image scans passed. Processing integration failed before
  pytest because Compose `up --wait` rejected the successfully exited one-shot
  bootstrap; combined coverage was skipped and Integration checks failed.
  `.cache/execution/processing-ci-failed.log` records `storage-bootstrap ...
  exited (0)`. This is a harness failure, not a failed Processing test.
- The parent's helper correction removes bootstrap/migrators from `up --wait`
  and executes them sequentially through checked `compose run --rm -T
  --no-deps`. Each must finish successfully before pytest; this also prevents a
  merely running migrator from being mistaken for an applied migration. There
  is no retry-to-green loop. Reviewer Ruff/diff checks pass; three offline probes
  of the unchanged helper control flow pass for Processing-only success,
  all-services success, and bootstrap failure. Failure prevents pytest and still
  performs scoped teardown. No containers were started by the reviewer.
- The corrected helper's coordinator log,
  `.cache/execution/processing-oneshot-fix.log`, shows persistent-service readiness,
  foreground bootstrap completion and all 41 owned tests passing in 6.28s with
  no skips. This resolves the sequencing defect in the inspected patch, now
  committed as `a702da5` with the identical reviewed blob. Fast and integration
  fragment fingerprints both match that head. The replacement PR checks were
  running on `a702da5` at final inspection; green CI is still required before
  merge. R1 remains independently open.
- CI selects all Processing integration modules plus DB ownership, enables real
  Redis/storage tests, fails selected skips, gates each measured package and
  retains stable aggregate checks. Fast tests reject network connections. Images,
  queues, buckets, ports and Compose resources are scoped by run/worktree; live
  tests do not consume synthetic intake jobs through a background worker.

SCOPE:

- P1/P2/P3 and their shared runtime/test/CI changes are in scope. Earlier
  foundation review history and current progress metadata were inspected but not
  rewritten. Original proposal/roadmap visuals and inherited app behavior remain
  outside product edits. Media/client/V1/V2–V4/AWS acceptance is not a lane gate.
- Only `docs/execution/reviews/processing-review.md` was written. No application
  edits, commits, GitHub writes, container operations or additional agents.

FOLLOW_UP:

- Fix R1 within PR #28 and obtain an independent re-review of the changed cleanup
  path and its real regression proof. The parent owns PR/CI/merge/issue metadata.
  No separate issue or additional architecture is required.
