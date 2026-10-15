# Executable V1 contracts

`contracts/v1.py` and `contracts/gateway.py` are the shared wire substrate.
`tests/v1/` exercises payload-v2 requests, immutable envelopes, ownership filters,
source creation refusal, safe errors, and invocation SQL cleanup with explicit
fake inputs. These tests are not live PostgreSQL, Gateway/IAM or AWS evidence.

The external paths are `/api/media/*` and `/api/processing/*`. Each adapter strips
its own prefix exactly once. GET `/health` is public. Media POST `/auth/register`,
`/auth/login` and `/auth/logout` are public; all other requests require the Media
Lambda authorizer. Disable authorizer caching (TTL zero). Media verifies JWT
expiry and the current user/role. Existing Media user/operator roles both map to
`publisher` to preserve uploads; operator privileges still use the current Media
row. `viewer` is accepted as a read-only actor for Processing.

The authorizer returns `requestContext.authorizer.lambda` fields:

```json
{"schema_version":1,"integration":"dc2-gateway-v1","owner_id":"00000000-0000-4000-8000-000000000001","role":"publisher"}
```

This marker is a schema fence, not an authentication secret. Lambda resource
policies must restrict invocation to the configured Gateway. Public owner/role
headers are stripped; the ASGI application receives a validated `Actor` only in
`request.state.actor` with `gateway_v1=True`. Processing has no Media DB credential,
ORM or JWT lookup. Cookies use Path=/, Secure, HttpOnly, SameSite=Strict. Payload-v2
cookie arrays, raw query strings and base64 bodies survive the adapter. Response
cookies stay separate. Errors do not reflect validation inputs or driver secrets.

Processing exposes GET `/jobs?asset_ids=<comma-separated UUIDs>`, GET `/jobs/{id}`,
POST `/jobs/{id}/retry` with `retry_request_id` UUID, and DELETE `/jobs/{id}`.
Here `{id}` is the Processing job UUID. Media's public `job_id` remains the asset
UUID; `processing_job_id` is separate. Processing's public adapter mounts no
legacy `/internal/v1` routes and accepts no source creation. Only trusted Media
commands create jobs. API mutations write owned SQL/outbox via Processing
messaging; no encode or network queue send occurs inside the API request.

Direct intake is Media-owned: reserve with request_id, filename, content_type,
size_bytes and SHA256; receive reservation_id, asset_id, expires_at, presigned POST
url/fields and finalize_url. The limit is 100 MiB. Clients send no session cookie
to S3. Finalize with request_id; Media verifies actual size, content, SHA256 and
VersionId, checks owner/expiry/replay, then adopts the immutable revision. The
server chooses staging keys. Uncertain and late writes retain cleanup intent.

Every message includes all envelope fields, including nullable job_id, attempt_id
and source. `Source` is `{bucket,key,version_id,sha256,size_bytes,content_type}`;
no URLs, credentials or bytes belong in queues. Submit/work require source;
work/result require job and attempt. Cancel may precede submit and carry null
source/job/attempt. Only Media produces submit/retry/cancel commands; Processing
dispatch produces work; Processing completion produces results. Queue IAM policies
establish producer authority; schema validation does not authenticate a producer.

Consumers commit inbox/domain/outbox before ACK. Identical message-id/content
replay is a no-op; conflicting content is rejected. Inbox hashes include canonical
content. State versions never move projections backwards; cancel-before-submit
persists a tombstone. Current attempt/lease fences reject stale completion.
Workers compare the entire owner/asset/job/attempt/source against persisted
accepted state before using project-source GET with explicit VersionId. Workers
have source GET authority, broader than the historical signed-only capability;
they have no Media DB, source write/delete or unrelated-bucket authority.

Outbox publish and cleanup run outside SQL row locks. Repair retains sent work
intent across queue-retention gaps. During open sessions, repair gates are 120s
for lost work and 300s for interrupted work. When closed, work remains visibly
queued; V1 requires another operator worker batch for subsequent encodes. Concrete
SQL/SQS/worker recovery tests belong to the messaging/worker integration lanes;
these contract fixtures alone do not certify recovery timing.

The API uses invocation-local NullPool engines and finally-disposal. TLS verifies
certificate chains and hostnames. `PROCESSING_DATABASE_CA_FILE` selects the
installed RDS trust bundle; local emulators explicitly use
`PROCESSING_DATABASE_TLS=false`. DSN TLS query overrides are refused. In V1 CA
mode, migrations require `PROCESSING_MIGRATION_DSN`, use the same verifying TLS
and never fall back to runtime credentials. SSM runtime DSN resolution belongs to
`runtime_support.settings.runtime_values("PROCESSING")`; no credentials are stored
in this document or the fixtures.
