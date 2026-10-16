# Product lane integration interfaces

Foundation supplies the runtime and public contract baseline. The three product
lanes implement against these interfaces; the coordinator owns shared packaging,
Make, Compose and CI edits. Request a small coordinator patch instead of editing
those shared files concurrently.

## Modules and commands

- Media lane owns `media/` and `tests/media/`, plus uniquely named real integration
  tests. Runtime entry: `uvicorn media.main:app --host 0.0.0.0 --port 8000`
  (the V1 app; the inherited peer-calling app is `media.main:legacy_app`).
  Migration: `python -m alembic -c media/alembic.ini upgrade head`.
  Reconciliation: `python -m media.recovery`.
- Processing lane owns `processing/`, optional pure `media_engine/`, and their
  tests. API entry remains `processing.main:app`; migrations remain independent.
  Worker entry: `python -m processing.worker`. Recovery/cleanup entry:
  `python -m processing.recovery`. API/worker may use one image digest with
  different commands and narrowly scoped credentials.
- Client lane owns `publisher/`, browser behavior changes and their tests. Provide
  `python -m publisher` plus a small independent package/entry point if useful.
  No service imports or database credentials. Preserve frontend design/assets.
- `app/` and the inherited migration chain stay the regression reference. Final
  default `make up` exposes only the new Media service through `/api/`.

The exact storage/database/token environment names and privileges are frozen in
`reviews/foundation-runtime-results.md`, section "Frozen storage/configuration
interface". `scripts/dev/runtime.py` generates them in a private per-run env file.
Do not inject that entire file into a service: Compose passes only its values.

Additional service client configuration uses `MEDIA_PROCESSING_URL=http://processing:8000`
and `PROCESSING_MEDIA_URL=http://media:8000`. Both are private container-network
origins. Explicit request timeouts are required; this is not a new public auth flow.

## HTTP boundary

Authoritative design operations and schemas:

- `project-roadmap/design/05-contracts/public.openapi.json`
- `project-roadmap/design/05-contracts/processing.openapi.json`
- `project-roadmap/design/05-contracts/media-internal.openapi.json`

Processing implements `/internal/v1/jobs` submit/batch, single-job read, job retry
with stable `retry_request_id`, and AssetId cancellation. Every operation uses the
forward service token and `X-Owner-Id`. Submit commits before queue publication.

Media implements reverse `/internal/v1/assets/{asset_id}/source-access`, using the
separate reverse token plus owner header and `{revision}` body. Response includes
`source_url`, `expires_at`, and the complete immutable source descriptor. Sign the
source URL against internal `minio:9000`; a container's `localhost` is not the host.

Public clients use cookie authentication and stable Asset IDs through the existing
routes. Public retry remains bodyless with optional `Idempotency-Key`; Media turns
that request into a stable internal retry UUID. Upload and edit replay keys are
scoped by owner and operation. Expected public status mappings, error shapes and
editing/cancellation invariants remain in the prepared contract; do not infer new
response fields from the legacy ORM.

## Storage and media

Media gets source Get/Put/Delete/List and output Get. Processing workers get output
Put/multipart write only. Cleanup gets output List/Delete only. Workers never get
Media's source credential. Successful upload acknowledgement, ETag and locally
calculated length/digest can verify a worker PUT without granting output Get/HEAD.

Public signing uses `localhost:<HTTPS port>` and real bucket paths, preserving the
Host header and port through nginx. Sign primary output; serve HLS playlist bodies
through Media with owner checks, and return authorised segment access. Source and
output descriptor fields are durable; URLs are expiring capabilities.

Reuse existing FFmpeg/probe/edit/HLS code with provenance. The shared helper
package, if used, contains media operations only and accepts explicit arguments;
it imports neither service's settings, ORM nor repositories. Nonempty operations
means an edit; empty operations is a normal upload. MP4 primary and optional HLS
remain the standard upload result; inherited MKV/MP3 conversions remain valid.

## Acceptance by lane and after integration

A lane may use controlled HTTP peer responses for its own tests. It must also
exercise owned persistence with real PostgreSQL, and Processing must encode real
short media before its PR can pass. No lane claims the complete public workflow
until V1 runs both services and both clients together.

User-facing errors and timing are part of the workflow. Offload blocking password
hashing and media work from async HTTP handlers. Recovery uses current Attempt IDs,
leases and durable state; no blind enqueue retries, unfenced terminal writes or
cross-service database access. Preserve lost-response, cancel-first and late-write
cases already specified in P1–P3/M1–M3.

The coordinator extends real integration selections, coverage package gates, live
image scans, gateway routes and runtime environment mappings as each lane lands.
Fast tests remain service-free. API/frontend/CLI examples in the final handoff must
run through the same HTTPS origin and explicit project CA.
