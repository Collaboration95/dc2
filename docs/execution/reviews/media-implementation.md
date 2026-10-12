# Media lane implementation and local validation

13 October 2026. Scope: M1/M2/M3 (#15/#16/#17), implemented only in
`.worktrees/media`. No branch/PR publication or issue changes. No AWS, Alibaba,
legacy `app/`, frontend, shared packaging, Compose, Docker, Make or CI changes.

## Local commits and integration order

1. `a2d7b4b` — independent Media service and durable Asset lifecycle.
2. `dd46ab1` — serialize playback grants with Asset tombstones.
3. `0acf3e2` — offline contracts and real PostgreSQL lifecycle/race tests.
4. `47dec2a3c4d286322e23d66c02fa0156d17b7acf` — preserve an adopted source after
   a lost database commit acknowledgement; additional persistence/cleanup tests.

The final code/test SHA above was validated after committing. The subsequent
review-file-only commit does not change tested production or test files.
Coordinator may cherry-pick these commits in order. All production changes are
under `media/`; tests are under `tests/media/` and the uniquely named
`tests/integration/test_media_persistence.py`. This review is the only owned
execution-document change.

## Coordinator entry points and shared needs

- API: `uvicorn media.main:app --host 0.0.0.0 --port 8000`.
- Independent migrations: `python -m alembic -c media/alembic.ini upgrade head`.
- Recovery daemon: `python -m media.recovery`; bounded single pass:
  `python -m media.recovery --once`. Run one continuous recovery service alongside
  the API; database state persists all pending submission/retry/cleanup work.
- Required configuration: `MEDIA_POSTGRES_DSN`, `MEDIA_MIGRATION_DSN` for migration,
  `MEDIA_JWT_SECRET`, `MEDIA_PROCESSING_SERVICE_TOKEN`,
  `MEDIA_SOURCE_SERVICE_TOKEN`, frozen `MEDIA_MINIO_*` variables, and
  `MEDIA_PROCESSING_URL=http://processing:8000`. Configuration names match
  `foundation-runtime-results.md`; no alternate credential aliases.
- Defaults: HTTP timeout 5 seconds; signed URL lifetime 900 seconds;
  `MEDIA_API_PUBLIC_PREFIX=/api`; recovery interval 10 seconds; batch size 100;
  orphan grace 3600 seconds. Their optional overrides use the corresponding
  uppercase `MEDIA_` settings names in `media/config.py`.
- Media receives only its runtime DB role, source Get/Put/Delete/List + output
  Get credential, forward/reverse tokens and JWT secret. Migration uses its own
  migrator. Never inject the full generated runtime env into a service.
- Gateway strips `/api/`, blocks public `/internal/`, preserves signed storage
  Host/port and actual bucket paths. Its upload body allowance must exceed
  100 MiB to accommodate multipart overhead. Media measures actual file bytes.
- Coordinator owns Media image/Compose/recovery wiring, HTTPX/packaging and
  Make/CI selection. Extend lint and per-package coverage with `media`, its tests,
  and exact Media image scans. The current foundation already declares HTTPX
  and the package discovery includes Media. No further dependency is needed.
- Storage SDK transport has explicit connect/read timeouts and bounded retries.
  Source grants sign internal `minio:9000`; output grants sign public
  `localhost:<HTTPS-port>` with explicit region, HTTPS and real output bucket.

## Acceptance behavior

M1: users, immutable source descriptors, Assets, owner/operation/request keys,
pending submissions, retry and cleanup intents live in the Media database and
independent Alembic chain. There are no Processing/legacy service imports or ORM
relationships. Upload validates supported declared type, sniffed container and
actual file length <=104857600 bytes, then computes SHA-256 off the event loop.
Staging reservation precedes storage writing. Asset/source/ordered operations and
request identity commit before HTTP dispatch. Temporary Processing failure leaves
durable queued/pending intake and returns 202. A replay retains the same Asset;
changed immutable payload is 409; retained deleted key is 410. Reverse access
requires the separate token, recorded owner, live Asset and matching revision,
returning the complete immutable descriptor and fresh internal grant.

M2: public IDs remain Asset IDs and inherited response shapes remain compatible.
Pending is queued/pending without output URLs. Linked status is read live from
Processing and checked against owner, Asset ID, Job ID and source descriptor;
missing linked jobs, malformed responses and outages yield 503. List pages batch
only submitted Assets and group operator requests by the actual owner. Bodyless
retry persists its internal UUID before dispatch; a lost acknowledgement reuses
that unresolved intent. Optional retry keys are owner/operation scoped and map to
a stable internal UUID. Explicit-key replay of a confirmed retry is accepted
without creating another attempt. Primary MP4/MKV/MP3 output URLs use the public
signer. Owner-checked HLS playlists are served as bodies with private/no-store;
renditions remain facade-relative and segments redirect to fresh signed URLs.
Playback signing holds the Asset guard so tombstone commit cannot precede a new
grant. No performance target is claimed from these tests.

M3: reconciliation uses persisted descriptors/operations, safe diagnostics and
bounded backoff (up to 60 seconds). Edit copies primary output bytes into its own
private source, verifies length/digest when supplied, calculates its own immutable
SHA-256, then commits ordered operations before submission. Parent deletion cannot
break the child or its replay. Source-dependent geometry/probe validation remains
Processing's visible attempt result, as CT-20 specifies. Delete commits tombstone
and cleanup intent before any cancel request, then cancels by Asset ID even when
no Job ID was acknowledged. Lost cancellation acknowledgements retain the source;
source removal starts only after cancellation acknowledgement. Cleanup repeats
safely and never deletes Processing-owned outputs. Operator list/delete requires
the database's current role and forwards the target's specific recorded owner.

The staging row is locked during upload/copy, its timestamp refreshes after the
write, and orphan cleanup skips locked rows, checks non-adoption and uses a
one-hour grace. Discard also checks reservation/non-adoption under lock: loss of a
successful SQL commit acknowledgement cannot delete the newly accepted source.
No tombstones or request keys are purged during the demonstration lifetime.

## Contracts and reuse

Authoritative public, Processing and reverse source-access OpenAPI, examples,
persistence model and CT cases were read. They remain unchanged. Normal uploads
store `operations=[]` internally and **omit** that property on outgoing SubmitJob;
nonempty edit operations preserve their authored order. No contract adjustment
was needed. Cookie JWT/bcrypt, edit validation, container sniffing and HLS facade
behavior were extracted/copied from the corresponding `app/` files with provenance
comments. Blocking bcrypt work uses the thread pool, with a valid cost-12 dummy
hash for unknown users. Auth lookup owns a separate SQL session, avoiding domain
`session.begin()` conflicts caused by authentication SELECT autobegin.

## Validation on the exact code/test SHA

Host Python 3.12.11 from the root project's available `.venv`; commands executed
with explicit cwd `.worktrees/media`. No source edits outside assigned paths.

```sh
python -m alembic -c media/alembic.ini upgrade head
python -m alembic -c media/alembic.ini check
python -m pytest tests/media -q --cov=media --cov-branch --cov-fail-under=80
RUN_MEDIA_TESTS=1 python -m pytest tests/media tests/integration/test_media_persistence.py \
  -q --cov=media --cov-branch --cov-fail-under=80
ruff check media tests/media tests/integration/test_media_persistence.py
```

The real commands inject runtime/migrator DSNs from the private generated run
configuration through a local helper; credential values are never recorded here.
`RUN_MEDIA_TESTS=1` uses the coordinator's stated environment names. Disabled real
suite collects/skips cleanly without external service access. Fast tests enforce a
socket guard against any IPv4/IPv6 network connection.

- Three final fast passes: **120 passed**, pytest durations 1.02 / 1.01 / 1.00 s;
  complete command wall times 1.796 / 1.777 / 1.787 s.
- Final combined run: **149 passed**, including **29 real PostgreSQL tests**;
  pytest duration 6.45 s on the initial successful full set. Repeated exact-head
  verification also passed; its duration is recorded by the coordinator console.
- Fast statement+branch coverage: **97.93%**; statements 1070/1085 (98.62%);
  raw branches 206/218 (**94.50%**).
- Combined coverage: **98.31%**; statements 1072/1085 (98.80%); raw branches
  209/218 (**95.87%**). `--cov=media` includes unexecuted production files;
  migrations use the project's existing migration omission policy.
- Ruff and diff whitespace checks pass. Independent migration upgrade succeeded;
  Alembic `check` reports no new upgrade operations/schema drift.

Dedicated real PostgreSQL 16 ran on the existing project Lima 8 CPU / 8 GiB VM,
Compose namespace `dc2-media-pg-04cdf2a9`, host PG port 64875. Only this namespace's
PostgreSQL service was started; no image build or other namespace operation.
Media migrator created the schema; Media runtime executed tests. Runtime DDL and
connection to the opposite Processing database were denied. This lane's tests
remove only their UUID users/assets, intents and source reservations. Run config
remains in `.local/runs/media-pg/runtime.env` (mode 0600); no values enter Git.
The dedicated namespace is stopped after validation, retaining its volume/config.

Real persistence cases cover concurrent identical upload replay, loser-only source
cleanup, owner/key isolation, conflicting/deleted replay, pending restart, lost
submit/retry/cancel acknowledgements, stable concurrent keyed retry, live status
outage/missing links, reverse owner/revision/token denial, independent pending edit
and replay after parent delete, ordered-operation conflicts, storage/copy failures,
operator boundary, cookie auth plus explicit domain transactions, exact 100 MiB
multipart admission, in-flight staging lock, old/fresh/adopted orphan distinctions,
submit/delete serialization, playback/delete serialization, and lost SQL commit
acknowledgement after adoption.

## Evidence boundary

Owned persistence is real PostgreSQL with independent sessions and actual
migrations/roles. Processing is a controlled HTTP peer and object data uses focused
controlled storage, plus real offline MinIO SDK signing tests. These results do
**not** prove actual Processing encoding, actual MinIO playback, CLI/browser/TLS,
load targets, integrated fault timing or complete public workflow. Coordinator V1+
retains those acceptance checks, image scans and shared runtime verification.
M1–M3 implementation is ready for that integration and independent review; this
lane does not update issue state or claim the whole proposal complete.
