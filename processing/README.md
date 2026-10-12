# Processing

Processing owns jobs, attempts, retry identities, leases and output references in
its own PostgreSQL database. It imports neither Media's persistence nor the
inherited `app` service. Media supplies owner-bound, renewable source grants over
HTTP. Workers write output objects; recovery uses a separate cleanup principal.

Run from the repository/worktree root using the configured Python environment:

```sh
python -m alembic -c processing/alembic.ini upgrade head
python -m uvicorn processing.main:app --host 0.0.0.0 --port 8000
python -m processing.worker
python -m processing.recovery
```

The migration command receives the Processing migration role through
`PROCESSING_MIGRATION_DSN` (or its own `PROCESSING_POSTGRES_DSN`). API, worker and
recovery receive the runtime role. `python -m processing.worker --burst` drains
available deliveries; `python -m processing.recovery --once` runs one recovery
pass. FFmpeg and ffprobe must be installed in the worker image. Keep the API on
the private network. `/health` checks PostgreSQL and identifies the attempt-aware
stage; it is not proof that Redis, storage or a worker is healthy.

## Configuration and privileges

Settings read only `PROCESSING_*` values. They do not load Media's environment.
Supply configured values from the runtime's private per-run configuration through
explicit service mappings; do not give any process the whole runtime env file.

| Process | Required configuration |
| --- | --- |
| API | `PROCESSING_POSTGRES_DSN`, `PROCESSING_SERVICE_TOKEN`, `PROCESSING_REDIS_URL`, `PROCESSING_QUEUE_NAME` |
| Worker | Runtime DB/Redis/queue above, `PROCESSING_MEDIA_URL`, `PROCESSING_SOURCE_SERVICE_TOKEN`, storage fields below; no forward token |
| Recovery | Runtime DB/Redis/queue plus storage fields with cleanup credentials; no service tokens |
| Migration | Own migration DSN; no Redis/storage credentials |

Storage fields: `PROCESSING_MINIO_ENDPOINT` (host:port, no scheme),
`PROCESSING_MINIO_USE_SSL`, `PROCESSING_MINIO_REGION`,
`PROCESSING_MINIO_OUTPUT_BUCKET`, `PROCESSING_MINIO_ACCESS_KEY` and
`PROCESSING_MINIO_SECRET_KEY`. The worker gets output PUT/multipart only. Recovery
maps `CLEANUP_MINIO_ACCESS_KEY/SECRET_KEY` into the corresponding Processing
credential fields and gets output List/Delete only. Workers have no source
credentials and never use output HEAD/Get. Configure an explicit region to avoid
an implicit bucket-location request. API settings allow storage fields to be
absent; worker/recovery entry points validate only their own requirements.

Optional defaults:

| Field | Default |
| --- | --- |
| `PROCESSING_LEASE_SECONDS` | 60 |
| `PROCESSING_HEARTBEAT_SECONDS` | 10; must be less than half the lease |
| `PROCESSING_ATTEMPT_TIMEOUT_SECONDS` | 900 across all stages |
| `PROCESSING_RECOVERY_INTERVAL_SECONDS` | 15 |
| `PROCESSING_QUEUE_RETRY_CAP_SECONDS` | 60 |
| `PROCESSING_HTTP_TIMEOUT_SECONDS` | 15 |
| `PROCESSING_FFMPEG_BINARY`, `PROCESSING_FFPROBE_BINARY` | `ffmpeg`, `ffprobe` |
| `PROCESSING_FFMPEG_PRESET`, `PROCESSING_FFMPEG_CRF` | `veryfast`, 23 |

## HTTP and lifecycle

Every job operation requires the forward Bearer token and `X-Owner-Id: UUID`:

- `POST /internal/v1/jobs`: 201 new durable submission; 200 immutable replay.
- `GET /internal/v1/jobs/{job_id}`: owner-filtered current job and attempt.
- `GET /internal/v1/jobs?asset_ids=UUID,UUID`: owner-filtered batch, 1–200 IDs.
- `POST /internal/v1/jobs/{job_id}/retry`: `{ "retry_request_id": "UUID" }`, 202
  new attempt or saved replay; a new request requires a failed job.
- `DELETE /internal/v1/assets/{asset_id}/job`: 204 retained owner-bound tombstone,
  including cancellation before Submit or after a lost Submit response.

Normal upload HTTP requests omit `operations`; explicit `[]` and null are invalid.
Stored normal uploads use `[]`. Edits use the authored `{operation, params}` shape.
Fingerprinting includes the complete immutable source descriptor and ordered
operations, excluding source URL/expiry. Owner mismatch is 404, same-owner Submit
against a tombstone is 410, and changed immutable content is 409. Submit and cancel
lock the same persistent asset guard. Guards remain for the demo lifetime.

Submit/retry commit the reserved job/attempt before queue publication. Redis
outages leave durable queued work for recovery. RQ messages carry both IDs and
use the attempt UUID as the deterministic RQ identifier. Queue repair checks
actual list or live started-registry membership, not just a surviving RQ hash.

Claim, heartbeat, success and failure serialize on the Job and use database time,
current attempt and lease token fences. A heartbeat supervisor runs independently
through renewal, download, ffprobe, FFmpeg and upload. Lease loss cancels work and
kills the subprocess group, including descendants whose leader has exited.
One deadline covers the whole attempt; expired or stale failures cannot write.

Every claim renews the source through
`/internal/v1/assets/{asset_id}/source-access`, with the reverse token, owner header
and `{revision}` body. The worker compares the entire source descriptor and
verifies downloaded length/SHA-256. Outputs use
`jobs/<job_id>/attempts/<attempt_id>/`. Verified PUT acknowledgements plus local
length/digest precede fenced publication. Normal uploads produce primary MP4 and
best-effort HLS; HLS fallback propagates cancellation/deadline control flow. The
pure `media_engine/` helpers retain inherited MKV/MP3 edit behavior and geometry
checks; their provenance is recorded in `media_engine/README.md`.

Recovery marks expired current attempts abandoned/failed and repairs missing
queued deliveries with capped backoff. Cleanup intents persist and re-scan every
60 seconds to catch late PUTs after cancellation. Cleanup never targets source
objects, active attempts or winning outputs.

## Verification

Fast, offline checks:

```sh
python -m pytest tests/processing tests/media_engine -q
```

Real owned integration (configure isolated services first):

```sh
RUN_PROCESSING_TESTS=1 RUN_PROCESSING_REDIS_TESTS=1 RUN_PROCESSING_STORAGE_TESTS=1 \
  python -m pytest tests/integration/test_processing_*.py -q
```

Processing DSN/token are required for the PG tier; Redis adds
`PROCESSING_REDIS_URL`. Storage adds the Processing writer fields plus test-only
`MEDIA_MINIO_ACCESS_KEY/SECRET_KEY`, `MEDIA_MINIO_SOURCE_BUCKET`, and
`CLEANUP_MINIO_ACCESS_KEY/SECRET_KEY`. These seed/read/cleanup test credentials are
never supplied to the worker task. Use a unique queue namespace without a
background consumer for synthetic intake tests. The worker tests invoke the real
worker task explicitly. Fixtures remove only their own IDs/object prefixes;
Redis tests use unique queues. See the lane implementation review for exact
results and the boundary between owned tests and full service integration.
