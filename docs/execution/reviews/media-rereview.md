VERDICT: PASS
ISSUE: #15 / #16 / #17 (M1 / M2 / M3; parent E3 #4)
PR: local branch `work/media`; no GitHub access performed

Reviewed head: `96bd6d7ecec8de9e3bfb2b5f8e893e5350723094`.
Fix/tested code: `f63b07e598159d32afe33a5de3d83a59f11eb468`.
Rereview base: `3ea770c768025f0693536fab0c173f6ecbc91548`.
Independent bounded R1 rereview completed on 13 October 2026. The complete
base-to-head change was inspected. Head adds only the fix report to the tested
code/test commit; `media/` and `tests/` are identical between those commits.
This is the final verdict for the R1 correction and its regressions at this head.
It does not certify V1, release readiness or completion of the parent epic.

ACCEPTANCE:

- [pass] R1 — Uncertain upload/edit writes retain durable staging authority after
  an acknowledged or failed immediate DELETE. `media/services/intake.py:53`
  reserves `write_uncertain=True` before writing. Upload at `:133` and edit at
  `media/services/lifecycle.py:265` hold the reservation lock while writing and
  record completion only after a successful writer return, in the guarded SQL
  transaction. A failed transaction leaves the durable conservative state.
  `discard_stage` at `intake.py:58` refreshes an uncertain reservation and keeps
  it after DELETE. Failure therefore returns 503 without accepting an Asset or
  request key and without surrendering the key needed to find late bytes.
- [pass] R1 — A PUT completing after DELETE, after the first aged recovery pass,
  or after parent deletion remains discoverable. `media/recovery.py:78` selects
  aged, unadopted reservations in bounded age/key order with `SKIP LOCKED`.
  Successful cleanup at `:98` refreshes uncertain evidence instead of deleting
  it, including when the object was absent. Later eligible reconciliation removes
  a late object; another reappearance can be removed again. The six PostgreSQL
  cases at `tests/integration/test_media_persistence.py:968` parameterize both
  upload/edit and all three completion orderings with explicit events, not sleeps.
  They assert 503, no accepted Asset/request key, first DELETE acknowledgement,
  durable uncertainty, fresh grace protection, removal through a replacement
  pool/session, repeated cleanup and a harmless fresh pass.
- [pass] R1 regression guards — Active writers and healthy adopted sources are
  protected. The aged in-flight upload/edit cases at persistence test `:706`
  prove locking rather than grace prevents cleanup. Recovery excludes all Asset
  source keys, including tombstoned Assets whose own cleanup intent controls
  deletion. The six late-PUT cases preserve healthy uploads/children, including
  the child after parent deletion and through a replacement application.
  The existing lost successful SQL commit acknowledgement case at `:922` and
  concurrent replay loser-only cleanup at `:354` remain in the supplied passing
  real suite. Discard still checks adoption and never treats a missing reservation
  as permission to delete a durable source.
- [pass] New adoption guard — `intake.py:88` locks the same reservation before
  Asset/request-key adoption. Cleanup winning the race on a confirmed completed
  reservation now produces 503 instead of accepting a missing source. The two
  new PostgreSQL cases at persistence test `:1104` cover upload and edit; the
  focused fast missing-reservation guard also passes.
- [pass] Migration ownership and compatibility — `0002_uncertain_writes` follows
  `0001_media` in Media's independent Alembic chain. Its sole upgrade operation
  adds `staged_objects.write_uncertain BOOLEAN DEFAULT true NOT NULL`, so existing
  reservations receive the conservative state without deleting data. ORM defaults
  and nullability match. No Processing schema, cross-service foreign key, public
  contract, role/grant or credential change is introduced. The supplied real
  migration upgrade/schema check and runtime DDL/opposite-database denial pass.
  Apply this migration before starting the updated API/recovery processes.
- [pass] M1/M2/M3 regression scope — The previous review's passing dispositions
  stand; no new substantive regression was found in the changed paths. Known
  completed unadopted writes still permit object/ledger removal, immutable replay
  and loser cleanup remain intact, and the parent/child source boundary remains
  independent. The intentional `test_media_lifecycle.py` and
  `test_media_storage.py` renames avoid root test-module collisions. Storage test
  content is unchanged; lifecycle adds only the completion-state assertion.

FINDINGS:

- None. R1 is RESOLVED; no additional revision is required for this bounded review.
- The original review suggested eventually deleting the uncertain ledger after
  grace. The stronger required late-completion ordering cannot be guaranteed by
  a finite grace period or an absent object. Keeping uncertain rows for repeated
  cleanup is accepted here: late objects are removed, while their ledger authority
  intentionally remains for the demonstration lifetime. This documented cost is
  one small row per uncertain write and recurring bounded DELETEs. Continuous
  recovery is required; the fix cannot reconstruct keys erased by the old code.

CHECKS:

- Read the review-work skill, root/worktree AGENTS, worklog, prior review/fix report,
  Media implementation report, E3/M1/M2/M3 contracts and relevant execution
  interfaces/decisions. Inspected the complete `3ea770c..96bd6d7` diff and affected
  intake, lifecycle, recovery, model, migration and test context.
- Independent offline run, cwd `.worktrees/media`, root virtualenv:
  `PYTHONDONTWRITEBYTECODE=1 RUN_MEDIA_TESTS=0 ../../.venv/bin/python -m pytest
  tests/media tests/integration/test_media_persistence.py --no-cov
  -p no:cacheprovider -q` — **124 passed, 38 skipped**, 0.81 s. Fast tests enforce
  their IPv4/IPv6 socket guard. No coverage or pytest-cache artifact was written.
- Root `.venv/bin/ruff check --no-cache media tests/media
  tests/integration/test_media_persistence.py` — **passed**.
- Independent offline Alembic/model inspection — **passed**: correct private
  revision chain, additive PostgreSQL column/default/nullability and matching ORM
  defaults. No database connection or migration execution by this reviewer.
- `git diff --check 3ea770c..96bd6d7` — **passed**.
  `git diff --exit-code f63b07e..96bd6d7 -- media tests` — **passed**.
- Supplied exact-fix evidence in `media-fixes.md`: **162 passed**, including
  **38 real PostgreSQL tests**, 9.62 s; upgrade and Alembic schema check passed.
  These real results were inspected against the actual tests and were not rerun
  by this reviewer. The additional nine database cases are six late-PUT cases,
  the second in-flight writer case and two cleanup-before-adoption cases.
- Independently read the saved `/tmp/dc2-media-r1-f63b07e/fast.json` and `real.json`.
  Totals match the report: fast combined coverage **97.81%**, statements
  **1083/1100**, branches **214/226 (94.69%)**; combined coverage **98.19%**,
  statements **1085/1100**, branches **217/226 (96.02%)**. Both artifacts include
  every Media production Python file under the established migration omission
  policy. Coverage corroborates the supplied report; it is not an independent
  rerun of its PostgreSQL test count or migrations.

SCOPE:

- Only this report was written, and it remains uncommitted for parent copy.
  No application/test/shared-file edits, GitHub access, containers, child agents,
  AWS or Alibaba operations were performed.
- Persistence evidence uses real PostgreSQL with controlled storage and a
  controlled HTTP Processing peer. It proves the recorded fault orderings and
  durable authority, not a real MinIO outage, encoding or browser playback.
- Parent-reported live public HTTP and CLI batches pass. Browser verification is
  pending the separate platform-decoder investigation. Those are supplied context,
  not independently verified here; no full V1 proof or Media decoder finding is
  claimed. Deployment, image scans, performance/scaling and the other worktree's
  login-resource tuning remain outside this R1 assessment.
- The fix stays within the user's 80/20 Media cleanup scope and existing private
  ledger. No added security feature or new issue is required.

FOLLOW_UP:

- Parent may copy this report and integrate the reviewed correction/migration with
  its existing rename handling. Keep V1/browser and later release evidence tracked
  separately. PASS is a review assessment, not merge, release or Done authorization;
  no GitHub synchronization was performed.
