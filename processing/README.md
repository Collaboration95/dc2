# Processing intake

This private service owns its PostgreSQL database and migration history. It has
no imports from `app`, no user/asset foreign keys, and no inherited worker dispatch.
This is an **intake-only stage**: worker dispatch, reconciliation, media probing,
output storage/completion, retry and cancellation endpoints are not yet connected.
Accepted jobs remain queued. `outputs` is always empty in this stage.

Run from the repository root with the existing Python 3.12 environment:

```sh
export PROCESSING_POSTGRES_DSN='postgresql+asyncpg://processing_runtime:YOUR_PASSWORD@localhost:55432/processing_db'
export PROCESSING_MIGRATION_DSN='postgresql+asyncpg://processing_migrator:YOUR_PASSWORD@localhost:55432/processing_db'
export PROCESSING_SERVICE_TOKEN='YOUR_SHARED_SERVICE_SECRET'
python -m alembic -c processing/alembic.ini upgrade head
python -m uvicorn processing.main:app --host 127.0.0.1 --port 8010
```

`PROCESSING_MIGRATION_DSN` is optional and falls back to `PROCESSING_POSTGRES_DSN`.
Settings do not load Media Management's `.env` or unprefixed environment values.
The service secret has no usable default; missing configuration fails closed.
`/health` checks the database with `SELECT 1`, returns 503 when unavailable, and
identifies the intake-only stage. Keep the entire service on the private network.

Implemented contract routes:

- `POST /internal/v1/jobs`: 201 for new durable intake, 200 for immutable replay.
- `GET /internal/v1/jobs/{job_id}`: owner-filtered current job and attempt.
- `GET /internal/v1/jobs?asset_ids=UUID,UUID`: owner-filtered batch of 1–200 IDs.

All job routes require `Authorization: Bearer ...` and `X-Owner-Id: UUID`.
Operations follow the prepared `{operation, params}` contract. An original upload
omits `operations`; explicit empty arrays and nulls are invalid. Geometry cannot
be checked from the source descriptor and will require the future media probe.
Optional response fields are omitted when absent.

Integration interfaces: `processing.config.Settings/get_settings`,
`processing.database.Base/get_session`, `processing.main.create_app/app`.
`processing.models` contains `Job`, `Attempt`, `SubmissionGuard` in tables
`jobs`, `attempts`, `submission_guards` in the dedicated database's public schema.
Job/Attempt IDs are `id`; the attempt counter is `attempt_number`. The response
maps these to `job_id`, `attempt_id`, and `number`.

Submit first inserts the asset guard with PostgreSQL `ON CONFLICT DO NOTHING`,
then locks it. Owner checks precede tombstone checks: another owner gets 404,
same-owner deleted intake gets 410, and changed immutable content gets 409.
SHA-256 fingerprints cover asset, owner, complete source descriptor and ordered
operations, excluding the temporary source URL and expiry. Replays preserve the
original job and attempt; the temporary locator is currently retained as first
submitted. Future worker source-access renewal must handle expiration.

The guard link, job and first queued attempt commit in one transaction. The
current-attempt FK is deferred until commit, permitting a nonnullable pointer
while inserting its attempt. Both FKs remain entirely inside Processing.
No success response is returned if commit fails.
