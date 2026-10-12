# Processing P1/P2/P3 implementation

Owned worktree: `.worktrees/processing`, branch `work/processing`. No shared
packaging/runtime/CI files, other lane code, roadmap assets, inherited intake
tests or root checkout were changed. No branch/PR/issue publication was performed.
No AWS or inherited Alibaba operation was performed.

Local implementation commits, in order:

- `a2989cb`: P1 durable retries, cancellation guards, claim/lease/publication fences.
- `dd3b99c`: P2 pure media extraction, worker/source renewal/output PUT and supervision.
- `369f78a`: RQ 2.12 compatibility correction; queue default timeout is applied by RQ.
- `fbe343d`: P3 recovery/cleanup, live fault/storage tests, offline decision/contract tests.
- `8ce679d`: rename the queue test to avoid an inherited pytest module collision.

The final documentation commit updates `processing/README.md` and this review.
Coordinator owns integration/publishing and independent review; issue closure is
not claimed by this lane report.

## Implemented contracts and decisions

P1 uses an additive independent `processing_0002` migration after
`processing_0001`. Retry requests commit with a newly reserved attempt; replay
returns the current job without another transition even after success. New
requests in queued/processing/done states conflict. Cancellation uses stable
AssetId and the retained guard in both race orders, including lost Submit reply.
Claim, heartbeat and both terminal writes require the current live attempt and
lease token under a Job lock. Domain mutation timestamps and authority checks
use PostgreSQL clock time. Submit replay also locks the Job for a consistent
job/attempt response.

The authored HTTP schemas/cases are unchanged. Normal upload omits `operations`
on the wire and stores `[]`; explicit HTTP `[]` remains invalid. Two internal
representation choices simplify the proposed persistence sketch: retry identities
have a separate table with unique `(job_id, request_id)`; winning output descriptors
are an atomically published Job JSONB list, with attempt ownership enforced by
immutable namespace keys, rather than a separate output-reference table. Cleanup
intents are per attempt, making failed/retried/deleted prefix cleanup independent.
These retain the authored retry and output invariants; the coordinator can record
them in shared decisions without changing public/OpenAPI contracts.

P2 extracts only media command/probe/validation helpers from the inherited engine,
with provenance in `media_engine/README.md`. A worker renews the internal source
capability on every claim and once more on an expired/denied GET, checks owner/
revision through the reverse HTTP boundary, compares the complete returned
source descriptor, then verifies downloaded length and SHA-256. The worker has
no Media ORM/DB imports or source-storage credentials. Acknowledged output PUTs
and locally computed length/digest precede fenced publication; no output HEAD/Get.

The independent heartbeat spans every media stage. Loss of lease cancels pending
work and kills the FFmpeg/ffprobe process group, including descendants after their
leader exits. HLS fallback cannot absorb lease loss, task cancellation or deadline.
The total budget is shared across source access/download/probe/encode/upload.
An expired worker cannot write success or failure; recovery owns the visible
interruption/timeout result. MP4 and HLS decode proofs pass; inherited MKV/MP3
conversions decode too. User errors/log messages are curated; HTTPX URL logging
is suppressed and DSN/capability representations are hidden.

P3 rechecks current DB state under the same Job lock before expiring an attempt
or dispatching queued work. Repair distinguishes runnable Redis list/live started
membership from lingering job hashes or expired registry metadata. The existing
reserved UUID is reused; queue errors/backoff are durable. Cleanup uses only
output List/Delete, retains its intents and rescans every 60 seconds to catch
late uploads. Erroneous intents cannot delete active or winning prefixes.

## Coordinator wiring

Entry points are frozen: `processing.main:app`, `python -m processing.worker`,
`python -m processing.recovery`; both CLIs support bounded `--burst`/`--once`
respectively. API/worker may share an image; COPY `media_engine` and install
FFmpeg/ffprobe. The parent already owns these shared changes.

Exact fields/defaults and commands are in `processing/README.md`. API receives
DB/Redis/forward token only. Worker receives DB/Redis/reverse source token/private
Media origin/output writer. Recovery receives DB/Redis/output fields with
`CLEANUP_MINIO_ACCESS_KEY/SECRET_KEY` mapped into `PROCESSING_MINIO_*` credentials.
Never inject the complete per-run env file. Default lease/heartbeat/recovery are
60/10/15 seconds; total deadline 900 seconds, queue backoff capped at 60 seconds.

All `tests/integration/test_processing_*.py` belong to the owned PG tier.
`RUN_PROCESSING_REDIS_TESTS=1` plus `PROCESSING_REDIS_URL` enables real RQ repair.
`RUN_PROCESSING_STORAGE_TESTS=1` enables real private MinIO using test-only MM
seed/read credentials and cleanup credentials. Absence of those opt-in flags
skips those capabilities explicitly; a required live gate must provide them.
The tests use unique Redis queues and remove only their own SQL IDs/object keys.
Do not run a background queue consumer for synthetic intake fixtures; controlled
worker tasks are invoked explicitly by their own tests.

## Validation

Local environment: Python 3.12.11, pytest 9.1.1, RQ 2.12.0, Redis client 6.4.0,
SQLAlchemy 2.1.4, HTTPX 0.28.1, MinIO SDK 7.2.20, host FFmpeg 8.1.2. Real PG16,
Redis7 and foundation-pinned MinIO run in the already-existing 8 CPU Lima VM.
The uniquely scoped project is `dc2-processing-lane-51d2de4c`; local diagnostic
ports/config are under this worktree's ignored `.local/runs/processing-lane/`.
The private configuration and coverage JSON are not committed.

Commands used project-root `.venv/bin/python` from this isolated worktree. The
ignored `.local/run-tests.py` launcher maps only this run's PG/Redis/storage host
ports and credentials into a test subprocess; no credentials are printed. Migrate
with the migration role before the live tier. Reproduction using any configured
isolated runtime:

```sh
python -m alembic -c processing/alembic.ini upgrade head
python -m pytest tests/processing tests/media_engine \
  --cov=processing --cov=media_engine --cov-branch -q
RUN_PROCESSING_TESTS=1 RUN_PROCESSING_REDIS_TESTS=1 RUN_PROCESSING_STORAGE_TESTS=1 \
  python -m pytest tests/processing tests/media_engine tests/integration/test_processing_*.py \
  --cov=processing --cov=media_engine --cov-branch -q
python -m pytest --collect-only -q
```

Latest code validation: **238 fast tests passed in 1.41s**; **273 total tests passed
in 7.01s**, including all **35 real owned integration tests**, with zero skips.
The original 15-case Processing intake module remains unchanged and passes.
Full repository collection after `8ce679d`: **713 tests**, no duplicate module names.
Scoped Ruff and `git diff --check` pass. Final documentation does not change tested
production code; the final head receives the same checks before handoff.

Combined statement/branch gates include unexecuted production files. Migration
scripts are excluded by the existing coverage configuration and tested via offline
SQL/history plus real migration application. Rates are calculated separately:

| Package/tier | Covered statements | Covered branches | Combined | Raw branch |
| --- | --- | --- | --- | --- |
| Processing fast | 849/891 | 138/172 | 92.85% | 80.23% |
| Processing fast + real | 884/891 | 161/172 | 98.31% | 93.60% |
| media_engine both tiers | 122/122 | 49/50 | 99.42% | 98.00% |

Real checks cover concurrent claims/retries, cancel-first/submit-first/concurrent
orders, stale success/failure rejection, DB-clock expiry, short actual MP4/HLS
and MKV/MP3 decode, source-expiry refresh and digest failure, queue-list loss with
surviving RQ hash, repeat cleanup and source/active/winning preservation.

An actual OS worker-task process is killed while source access is blocked. Its
independent heartbeat is observed in PG, its real two-second test lease expires,
and recovery marks interruption within the bounded five-second assertion.
Stored-source retry then encodes into one published winning output set. This is
an owned shortened-lease fault proof, not the default-topology V2 timing result.
Separate live MinIO proof encodes with the PUT-only principal, verifies output
HEAD/Get/source Get denials, deletes via the cleanup principal, repeats cleanup
following a late real PUT, and verifies the source remains intact.

## Evidence limits

The lane's source-access HTTP peer is controlled; it does not prove a complete
Media/Processing/web/CLI workflow. The actual short-media encoder, owned PG,
Redis and MinIO operations are real. Parent V1/V2 own full service/browser/fault
experiments and default-configuration timing. Scaling, image scanning and release/
rollback evidence are not claimed here. No proposal-wide or AWS completion is
claimed. The owned containers are stopped at handoff without deleting volumes,
run configuration, images or another namespace.
