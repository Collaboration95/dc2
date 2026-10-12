VERDICT: REVISE
ISSUE: #15 / #16 / #17 (M1 / M2 / M3; parent E3 #4)
PR: local Media lane; no GitHub access performed

Reviewed head: `3ea770c768025f0693536fab0c173f6ecbc91548`.
Base: `e538819`. Independent audit completed on 13 October 2026.
This is the final assessment of that head, not a provisional verdict. One P2
cleanup finding requires correction and regression evidence before acceptance.

ACCEPTANCE:

- [pass] M1 — Media owns users, Assets, immutable source descriptors, owner/operation
  request keys and durable intents. Independent metadata/migration history; no
  production imports of `app` or `processing`, cross-service foreign keys, or
  Processing database access. The reported real PostgreSQL suite tests runtime DDL
  and opposite-database denial.
- [pass] M1 — Upload/edit replay preserves one Asset and rejects conflicting or
  deleted requests. File bytes, actual length, supported declared type and sniffed
  container are checked before acceptance. Request/source/operations adoption is
  atomic. Evidence: intake/repository fast tests and reported real tests
  `test_concurrent_replay_one_asset_cleanup_only_losers`,
  `test_replay_conflict_owner_operation_and_deleted_key`,
  `test_full_100mib_file_allowed_but_file_over_limit_rejected`, and
  `test_edit_changed_order_conflicts_and_copy_failure_no_acceptance`.
- [pass] M1 — Source and pending Asset commit before submit and 202. HTTP submit
  uses the forward token and recorded owner; URL renewal does not change identity;
  normal upload omits optional operations. Processing outage/lost submit ACK keeps
  durable pending work. Independent schema checks validate actual outgoing submit;
  reported PostgreSQL restart, uncertain submit/delete and serialization cases
  supply persistence evidence.
- [pass] M1 — Reverse source grants require the separate reverse token, recorded
  owner, live Asset and exact revision. Wrong owner/deleted returns 404, revision
  mismatch 409, wrong token 401. Internal signing uses `minio:9000` and the actual
  source bucket. Evidence: reverse-grant API/real tests, real offline SDK signing
  test, and independent validation of the actual SourceAccess response.
- [pass] M2 — Public IDs are Asset IDs. Submitted single/page status is composed
  from live owner-filtered Processing reads; owner/Asset/Job/source link is checked.
  Pending is queued/pending without outputs. Outage, missing links and malformed
  responses give 503. Fast tests pass; reported real single/batch outage tests
  exercise this through HTTP with persisted links.
- [pass] M2 — Retry stores its UUID before dispatch. Keyed replay keeps the same
  UUID; unresolved bodyless retries reuse intent. Lost ACK/restart does not upload
  again. Evidence: retry fast tests and reported real keyed/bodyless lost-ACK,
  reconciliation, concurrent-key and cross-Asset conflict tests.
- [pass] M2 — Owner checks precede MP4/MKV/MP3 signing and HLS access. Public SDK
  signing uses HTTPS, configured host/port and actual bucket paths; HLS playlists
  remain facade-relative bodies with private/no-store, and segments redirect to
  signed output URLs. Asset locks serialize new grants with tombstones. Evidence:
  storage/HLS tests, reported real playback/tombstone race, and independent public
  response schema checks. Final browser playback evidence remains V1.
- [pass] M3 — Pending descriptors and ordered operations survive application/pool
  replacement; reconciliation uses bounded batches/backoff and the same Asset ID.
  Reported PostgreSQL restart and pending edit tests use independent sessions and
  a controlled HTTP Processing peer.
- [pass] M3 — Derived edits copy verified primary bytes into their own source;
  replay resolves the child before the parent. Parent deletion preserves the child
  and saved ordered operations; changed order conflicts. Source-dependent probe
  and geometry failure remains Processing's visible attempt result under CT-20.
- [pass] M3 — Asset deletion commits tombstone/cleanup before peer cancellation,
  cancels by AssetId without requiring a submit ACK, retains source until cancel
  ACK, and repeats source deletion safely without deleting Processing outputs.
  Reported real tests cover both cancellation orderings, lost submit/cancel ACK,
  storage-delete failure and submit/delete serialization.
- [pass] M3 — Authentication uses a separate lookup session, avoiding domain
  transaction autobegin conflicts. Owner filtering and the database's current
  operator role are retained; operator batches/cancel use each target's recorded
  owner. Fast tests pass; reported real cookie/domain transaction and operator
  tests cover these boundaries.
- [fail] M3 lifecycle recovery — Failed upload/edit storage writes can lose their
  only staging cleanup record before an uncertain PUT finishes. See R1.

FINDINGS:

- [P2] R1 — `media/services/intake.py:58` and `:125`,
  `media/services/lifecycle.py:270`, `media/recovery.py:80` — Retain cleanup evidence
  after an uncertain source write. Both storage-failure handlers call
  `discard_stage`. It deletes the source and immediately deletes `StagedObject`
  when DELETE succeeds. A PUT timeout does not establish that the remote PUT
  stopped. If that PUT finishes after DELETE, the private source reappears without
  an Asset or staging row. Recovery only selects recorded staged keys, so it can
  never discover or remove that object. Repeated failed uploads/edits therefore
  leave permanent orphan sources despite the crash-safe staging design.

  **Observed proof:** Two independent offline checks invoked the production
  upload and edit functions with a controlled storage peer. The peer recorded a
  remote PUT, raised TimeoutError, acknowledged the subsequent DELETE, then
  completed its PUT after the 503. In each case `discard_stage` executed the
  staged-row DELETE; one object remained with zero ledger rows. For upload, a
  production reconciliation pass then returned `orphan=0` and left the object.
  These are controlled fault reproductions, not a claim that a real MinIO outage
  was run. Existing failure fixtures raise before writing, so the passing suite
  does not cover this ordering.

  **Required change:** Preserve a durable staging/cleanup record for uncertain
  source writes through the existing cleanup grace period, even if an immediate
  DELETE succeeds. Refresh its age as appropriate and let later guarded orphan
  cleanup perform the final deletion. The existing ledger is sufficient; no new
  service or security infrastructure is needed. Preserve the adoption check that
  protects a source after a lost successful SQL commit acknowledgement.

  **Required test proof:** Add upload and edit cases with real PostgreSQL ledger
  persistence and a controlled late PUT. Assert: response 503; no accepted child
  Asset/request key; staging evidence survives the first acknowledged DELETE;
  complete the remote PUT after that response; fresh evidence is protected by
  grace; age it and reconcile through a fresh session/application; the source and
  ledger are eventually removed; another reconciliation is harmless. Use explicit
  events/state transitions, not sleeps. Also rerun adopted-source/lost SQL commit
  ACK, concurrent replay loser cleanup, locked in-flight stage and old/fresh/adopted
  orphan tests to prove the fix cannot delete a durable or unrelated source.

CHECKS:

- Read AGENTS, worklog, plan, E3/M1/M2/M3 contracts, interfaces, decisions,
  `media-implementation.md`, all three prepared OpenAPI contracts and all 25 CT
  cases. Inspected every changed production, migration, test and document file
  in `e538819..3ea770c`.
- Root `.venv/bin/python -m pytest tests/media
  tests/integration/test_media_persistence.py --no-cov -p no:cacheprovider -q`,
  with cwd `.worktrees/media` and bytecode disabled — **120 passed, 29 skipped**
  in 0.78 seconds. No coverage artifact was touched. Real PostgreSQL was already
  down and was not restarted.
- Root `.venv/bin/ruff check --no-cache media tests/media
  tests/integration/test_media_persistence.py` — **passed**.
- Independent service-free checks — **13 Draft 2020-12 schema validations passed**
  for actual submit/retry wire payloads, peer DTOs, four public status responses
  and reverse SourceAccess response; authenticated owner headers verified.
  The shared jsonschema dependency/lock integration is already coordinator work,
  not a new lane finding.
- Independent controlled late-PUT checks — **R1 reproduced for upload and edit**.
- Author/parent-supplied persistence evidence, inspected against reviewed tests:
  **149 passed** including **29 real PostgreSQL tests**, combined coverage
  **98.31%**, raw branch rate **95.87%**, independent migration upgrade/check passed.
  Production/test files at the reported tested code SHA `47dec2a` match this head;
  the final commit adds the implementation report. These real results were not
  rerun by this reviewer.
- `git diff --check e538819..3ea770c` — **failed on trailing whitespace inside
  generated migration SQL strings**. Cosmetic, not a substantive review finding;
  the implementation report's whitespace-pass statement is not reproducible for
  the complete base-to-head range.

SCOPE:

- Review writes only this file. No product/shared-file edits, GitHub access,
  containers, child agents, AWS/deployment operations or coverage mutations.
- Parent reports the integration worktree renames the colliding test basenames
  to `test_media_lifecycle.py` and `test_media_storage.py` without content changes.
  That coordinator fix must accompany integration; this review worktree retains
  the frozen head. It is not an additional newly discovered finding.
- Parent reports initial real two-service public MP4/HLS/replay/conflict/derived
  lifecycle success, plus CLI 30 successes/one rejection and stored retry success.
  Final V1/browser playback verification is still pending; the playback-promise
  hang has not been attributed to Media. Those results are context, not this
  review's final V1 acceptance. Full deployment/scaling evidence is outside lane.
- Media supplies source URL capabilities over HTTP, not source credentials or
  a shared Processing ORM/database. No OIDC/security scope was added.

FOLLOW_UP:

- Parent fixes R1 and supplies the required regression results on the corrected
  integrated head, then obtains a focused rereview. Keep existing issues/scope;
  no new issue, GitHub synchronization, merge authorization or Done claim here.
