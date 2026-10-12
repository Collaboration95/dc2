# Processing review R1 fix

13 October 2026, Singapore. Local branch `work/processing`, starting head
`0466f1a`. Scope: `processing/recovery.py`, its offline and real PostgreSQL
recovery tests, and this report. The copied independent review remains unchanged
and untracked. Coordinator owns cherry-pick, PR/CI and independent re-review.

R1 is addressed: cleanup of an older attempt no longer holds a Job lock while
awaiting output listing/deletion. Cleanup now has three boundaries:

1. A short transaction locks Job first, validates the persisted Job/Attempt/intent
   identities and terminal eligibility, then reserves the scan by incrementing
   `tries` and scheduling `next_try_at`. Live prefixes and undeleted successful
   prefixes are protected, including erroneous intents. Existing lifecycle
   transitions never reactivate terminal attempts: retry reserves a new UUID,
   and asset deletion is irreversible.
2. The transaction and session close before attempt-specific object I/O. No
   Job, Attempt or intent lock is retained during that I/O.
3. A fresh short transaction locks only the cleanup intent and records the safe
   outcome if Job identity, reserved try count and scheduled timestamp still
   match. An older scan cannot overwrite a newer reservation/reschedule. No Job
   or Attempt state is written using authority released before object I/O.

Intents survive successful/empty scans and task cancellation. Reservations are
committed before I/O; a crashed/cancelled scan remains retryable. Completed scans
schedule another pass 60 seconds later, retaining late-PUT cleanup. No schema,
worker supervision, shared helper, contract or service feature was changed.

## Regression evidence

`test_old_cleanup_does_not_revoke_healthy_retry` uses real PostgreSQL and the real
Supervisor/heartbeat/finish functions. It fails attempt A, reserves and claims
retry B, then blocks A's object deletion with Events. While cleanup remains
blocked for longer than B's 0.5-second heartbeat timeout, three independently
read committed SQL heartbeat timestamps must advance with a live lease; B's
guarded work must remain pending and uncancelled. Releasing cleanup allows B to
finish and publish its own primary. Only A's prefix is removed; B's object and
the source key survive. No test sleep or timestamp polling orders this race.
The heartbeat observation wrapper calls the unchanged real lifecycle heartbeat;
the blocking storage boundary is controlled, while the retained MinIO acceptance
case separately proves real List/Delete and repeated late-PUT behavior.

Before changing production code, this regression failed on `0466f1a` with
`processing.worker.supervisor.LeaseLost` in 0.70 seconds. After the change, the
same regression passed in 1.29 seconds. Additional real PostgreSQL tests prove
that stale success cannot overwrite a newer cleanup failure, stale failure cannot
overwrite newer success, and cancelling object I/O leaves a committed reservation
which can be scanned again. Offline tests verify there is no open SQL session at
the object boundary and protect malformed identities/live/successful prefixes.

## Validation

Commands ran from this worktree using the coordinator's existing root
`.venv/bin/python`. Secrets stayed in the ignored lane runtime configuration.

- Full offline Python tier: **637 passed in 3.68s** using `fast_env()`,
  `-p scripts.dev.pytest_plugin --offline-fast`, `tests`, integration/e2e excluded,
  and bytecode/cache writes disabled. One inherited JWT test warning.
- Owned live tier: **39 passed in 7.50s**, zero skips, selecting every
  `tests/integration/test_processing_*.py` with `--require-integration` and all
  three Processing/Redis/storage flags enabled by `.local/run-tests.py`.
  This is the previous lane's 35 tests plus four R1 cases; the coordinator's
  six separate DB ownership cases are outside this lane run.
- Matching fast/live coverage fragments passed `scripts.dev.coverage` with
  `--package processing --package media_engine`: Processing **98.32% combined,
  93.68% raw branches**; media engine **99.42%, 98.00%**. Every production Python
  file in these packages outside migrations is measured. Evidence matches the
  changed sources; logs/fragments remain ignored under `.local/` and generated
  gate results under `artifacts/coverage/`.
- Scoped Ruff passed for Processing, its offline/integration tests and the media
  engine. Changed-file formatting and diff whitespace checks passed. Full
  repository collection: **726 tests**, with no module-name collision.

Real services reused only the existing lane configuration and retained data in
`dc2-processing-lane-51d2de4c` on the existing 8 CPU project VM. Only this lane's
PostgreSQL/Redis/MinIO services were started; no background worker consumed
synthetic intake jobs. Test cleanup remains restricted to its UUIDs/queues/object
keys. Those services were stopped after validation; volumes/configuration remain.
No root/shared files, other lane namespaces, GitHub, AWS or Alibaba resources
were changed or operated. The root's one-shot CI helper fix remains separate.
The coordinator must refresh its full-head evidence and obtain independent
re-review/green PR checks after cherry-picking this local fix.
