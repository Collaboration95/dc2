# Media review R1 fix and regression evidence

13 October 2026. Review input: `media-review.md`, reviewed head
`3ea770c768025f0693536fab0c173f6ecbc91548`. M1/M2/M3 and the implementation
report were read. All code/test results below were collected on committed head
`f63b07e598159d32afe33a5de3d83a59f11eb468` in `.worktrees/media`, branch
`work/media`. This report is a subsequent documentation-only commit.

R1 is fixed by retaining durable cleanup authority for uncertain source PUTs.
`StagedObject.write_uncertain` defaults to true before upload/copy begins. Only
a successful writer return, recorded in the guarded SQL transaction, changes it
to false. Crash, timeout or lost SQL acknowledgement before that transaction
commits leaves the conservative state. Independent migration
`0002_uncertain_writes` adds the column and marks existing reservations uncertain.
Apply `python -m alembic -c media/alembic.ini upgrade head` before starting the
updated Media API/recovery processes.

Failed intake still attempts an immediate source DELETE. It refreshes and keeps
an uncertain reservation even if DELETE succeeds or fails. Recovery checks
non-adoption, skips locked writers, and DELETEs aged uncertain keys repeatedly.
Successful scans refresh their timestamp for the existing grace period; selection
orders by age/key and remains bounded by the configured batch size. Confirmed
completed, unadopted writers can have their object and ledger row removed.

The user's required late PUT beyond the first recovery pass is stronger than
the review's suggestion to eventually remove the uncertain ledger after grace.
A finite grace period or an absent object does not prove the remote writer has
stopped. Uncertain rows therefore remain durable for repeated cleanup, including
when their objects are absent, for the demonstration lifetime. There is no new
broker, automatic purge or guessed writer timeout. This intentionally retains one
small row per uncertain write; recovery must remain running to remove late objects.
This change cannot reconstruct keys whose ledger was already removed by old code.

Adoption locks the same reservation before inserting the Asset/request key. This
serializes acceptance against cleanup; an already expired completed reservation
returns 503 rather than accepting an Asset with a removed source. The existing
adoption check in discard protects lost successful SQL commit acknowledgements.
Recovery excludes every recorded Asset source, including tombstoned sources
whose deletion is controlled separately by the cancellation/cleanup intent.

The required basename renames are included: `tests/media/test_lifecycle.py` to
`test_media_lifecycle.py`, and `test_storage.py` to `test_media_storage.py`.
The lifecycle file also gains a writer-completion assertion. Parent integration
rename commit `f0dc82e` was reported as already applied; it was not accessed or
modified here. The coordinator can apply the fix with its existing rename handling.

Regression evidence:

- Six real PostgreSQL cases parameterize upload/edit and remote PUT completion
  after the HTTP 503, after the first aged cleanup, and after parent deletion.
  Explicit events control the remote write; no sleeps are used. Each proves the
  first DELETE is acknowledged, no failed Asset/request key is accepted, the
  ledger persists, fresh evidence is protected by grace, late bytes are removed
  through a replacement pool/session, and subsequent reappearance is removed
  again. A further fresh pass is harmless. Healthy adopted upload/edit sources
  remain protected, including a child after its parent is deleted, and a replacement
  application still serves that child.
- The aged in-flight reservation test now covers upload and edit under PostgreSQL
  row locks. Two additional cases prove completed-source cleanup before adoption
  cannot accept a missing source. Existing concurrent replay loser-only cleanup,
  lost SQL commit ACK, old/fresh/adopted orphan, submit/delete, playback/delete and
  persistence cases all pass in the full run.
- Fast checks cover uncertainty retention on acknowledged/failed DELETE, grace
  refresh/rescan, known-completed cleanup, successful writer state transitions,
  missing-reservation rejection and adopted/missing-reservation protection.

Commands used root `.venv` Python 3.12.11 with cwd `.worktrees/media`, bytecode
disabled and pytest cache disabled. Private runtime/migrator DSNs were read from
the lane's generated env and adjusted only to its host PG port; no credentials
are recorded or committed. Coverage outputs are isolated under
`/tmp/dc2-media-r1-f63b07e`.

```sh
python -m alembic -c media/alembic.ini upgrade head
python -m alembic -c media/alembic.ini check
python -m pytest tests/media -q -p no:cacheprovider \
  --cov=media --cov-branch --cov-fail-under=80
RUN_MEDIA_TESTS=1 python -m pytest tests/media \
  tests/integration/test_media_persistence.py -q -p no:cacheprovider \
  --cov=media --cov-branch --cov-fail-under=80
ruff check --no-cache media tests/media tests/integration/test_media_persistence.py
git diff --check 3ea770c..f63b07e
```

- Fast: **124 passed**, 1.15 s; combined statement/branch **97.81%**;
  statements **1083/1100**, raw branches **214/226 (94.69%)**.
- Combined: **162 passed**, including **38 real PostgreSQL tests**, 9.62 s;
  combined coverage **98.19%**; statements **1085/1100**, raw branches
  **217/226 (96.02%)**. Both 80% gates pass, and coverage JSON includes every
  Media production Python file under the established migration omission policy.
- Migration upgrade and subsequent schema checks pass with no new upgrade
  operations. Ruff and the fix's complete base-to-head whitespace check pass.
  Historical `0001_media.py` whitespace is outside this fix range and unchanged.

Only the Media lane PostgreSQL 16 namespace `dc2-media-pg-04cdf2a9`, port 64875,
was started. Runtime role tests still verify DDL/opposite-database denial. The
namespace was stopped after checks and its data volume retained. No other
namespace, shared files, GitHub, child agents, AWS or Alibaba were operated.
The supplied untracked `media-review.md` remains untouched and uncommitted.

Storage and Processing fault timing is controlled; persistence is real PostgreSQL.
These results do not establish a real MinIO outage, encoding, browser playback,
CLI, full integrated workflow, deployment or scaling acceptance. Parent-reported
public HTTP/CLI batches and separate browser diagnosis are context only; no Media
browser issue or full integration verdict is claimed. Focused rereview and
coordinator integration remain the parent's work.
