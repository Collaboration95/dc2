# Direct intake integration contract

`POST /api/media/uploads/reservations` accepts only request_id (UUID), filename,
content_type, positive size_bytes <= 104857600, and lowercase hex SHA256. The
server creates the owner/key/asset identity. The returned POST fields include an
exact key and content type; a signed policy bounds size and expiry. Reusing the
same owner/request UUID with different input returns 409. Expired unfinished
reservations return 410; replaying an adopted reservation returns the original
identity with upload=null so the client can replay finalize without rewriting.

`POST /api/media/uploads/reservations/{id}/finalize` accepts only request_id.
The server HEADs the current object and GETs that explicit VersionId to verify
size, digest and container MIME. Unversioned/null revisions are refused. Storage
reads occur outside SQL row locks. A second transaction locks/rechecks expiry
and replay, then commits the Asset, version pin and Media command outbox together.
The public job_id remains the Asset UUID. A lost response can safely replay with
the same request UUID; it cannot emit a second command or resurrect deletion.

Both clients use the domain API for JSON only. Browser storage requests specify
credentials=omit, redirect=error and mode=cors. Publisher uses a separate client,
removes Cookie explicitly and refuses redirects/non-HTTPS URLs. The browser's
visual markup/styles/player are unchanged. The default browser prefix is
/api/media. The explicit FLICKPOND_LEGACY_API=true switch is only for isolated
pre-Gateway regression pages. Gateway requests to deprecated /upload are denied.

Replay window: the staging key stays writable by an unexpired grant after finalize, and a
versioned bucket answers an unversioned GET with the newest object. The VersionId pinned at
finalize (`upload_reservations.version_id`, or `asset_source_versions` for derived sources) is
therefore the only valid way to name an adopted source. Retry, derive, result binding,
cleanup and the worker use `source_for_asset`, which refuses a descriptor whose key differs
from the asset; the legacy signed-URL readers now sign with the pin. Migration `media_0007`
adds a CHECK so a finalized reservation cannot exist without a real VersionId. Cleanup keeps
the pin and removes every other version of the key after grant expiry, repeatedly.
`tests/v1/test_direct_intake_s3.py` exercises this against Moto and PostgreSQL; Moto does not
enforce POST policy signatures, so real S3 policy enforcement stays a cloud check.

Storage requirements: versioning enabled before intake; browser CORS permits
POST from the actual frontend origin; native Media role permits source
PutObject/GetObject/GetObjectVersion/AbortMultipartUpload on source objects and
ListBucketVersions/DeleteObjectVersion for cleanup, scoped to the source bucket and its
`sources/` and `staging/` prefixes. The repair role holds only the last two. No role needs
a plain DeleteObject: it adds a delete marker and releases nothing.
Presigned POST uses MEDIA_MINIO_PUBLIC_ENDPOINT (host[:port], no URL scheme),
MEDIA_MINIO_PUBLIC_USE_SSL, MEDIA_MINIO_REGION and native signing credentials.
Internal validation uses MEDIA_MINIO_ENDPOINT/MEDIA_MINIO_USE_SSL. Buckets use
MEDIA_MINIO_SOURCE_BUCKET and MEDIA_MINIO_OUTPUT_BUCKET. AWS values use regional
S3 HTTPS hosts; emulator values remain explicit local configuration.

Exports in media.services.direct_intake:

- source_for_asset(session, asset_or_id) returns the immutable canonical source
  dict or None for historical sources without a V1 pin.
- pin_copied_source(session, storage, asset) verifies a newly copied derived source
  and stores its VersionId in the caller's adoption/outbox transaction. The prior
  output-copy operation validates encoder output; this helper rechecks size/hash
  without restricting derived audio to video signatures.
- cleanup_expired_uploads(factory, storage, limit=100) must run from Media repair.
  It scans bounded fair batches after grant expiry, removes all unadopted versions
  and preserves the adopted version. It retains the ledger and repeats deletion
  because a POST begun before expiry can finish late, but on a schedule: batches are
  ordered by `cleanup_next_at`, each scan reserves its row for 60s, rescans back off
  60s doubling to a 6h cap (the capped tail snaps to a shared 6h grid so waiting rows share one
  database wake-up, AD-27), and a clean scan at least a day after expiry sets
  `cleanup_retired_at` (Media migration `media_0008`). A failed scan never retires a
  row. Storage calls occur outside SQL locks. Tombstone cleanup must explicitly delete all source object versions;
  creating a delete marker alone does not reclaim pinned source bytes.

Staged copies. An edit copies an output into `sources/<owner>/<asset>/source` behind a
`StagedObject` row. If adoption fails or the Lambda dies, `cleanup_staged_objects` (Media
repair, bounded by `recovery_batch_size`) finds rows older than `orphan_grace_seconds` that
no Asset adopted, deletes every version and delete marker of the key, then the row. A failed
or timed-out deletion keeps the row, leaves it stale and retries on the next pass. A
write of unknown outcome keeps its row too, with a fresh clock once a deletion has returned.
Adoption (`intake.assert_adoptable`) refuses a row older than `orphan_grace_seconds`, so a
stale row is the cleanup's alone even if an abandoned S3 deletion is still running; the row
lock is held across the deletion as well, but age is the durable fence.

Local offline tests cover policy bounds, ownership predicate, expiry, unsupported
or altered content, digest/size/version rejection, replay, lost-response behavior,
late cleanup and cookie isolation. Real PostgreSQL rollback/concurrency, browser
CORS/TLS and emulator/cloud integration belong to the integrated runtime lane;
o offline pass establishes those live acceptance criteria.
