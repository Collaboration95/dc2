# Lane A — storage, credentials and owned data

Research date: 15 October 2026. Source: `Main` at
`af0b21e3c10d6ad62a77549756787eac738e83b5` (also the commit introducing
`handoff-temp.md`). This is a readiness report, not implementation or AWS evidence.

The existing service/data boundaries fit the accepted topology. Retain the MinIO
Python SDK, storage facades, reverse source-grant API, write-only output publisher,
cleanup ledgers, and separate PostgreSQL databases/roles/migration chains. The
necessary changes are native ECS credential-provider wiring, honest presign
expiry, and scoped AWS storage/configuration with focused acceptance checks.
No storage engine, authentication platform, queue or database redesign is justified.
The reverse interface remains `POST /internal/v1/assets/{asset_id}/source-access`
with the existing reverse bearer token, `X-Owner-Id` and revision body.

## Scope, provenance and evidence labels

Read `AGENTS.md`, all of `handoff-temp.md`, the latest worklog entry (15 October,
“PLANNING PUBLICATION AND SOL SWARM HANDOFF”), authoritative AWS README/plan,
worksheet and deployment-input template, interfaces and local handoff. The notice
at `HANDOFF.md:1–9` supersedes its historical assumptions. Also inspected the cost
calculator, captured price rows, active Compose and relevant local evidence notes.

Extracted `word/document.xml` from the original proposal using Python `zipfile`
and XML parsing, without writing an extracted copy. Relevant source locations are
§§1.3–1.4, 2.2–2.5, 3.3–3.5; XML body paragraphs P16–23, P29–50, P57–94, and
tables 1–3, 6–7 (zero-based). AD-02 permits two databases on one PostgreSQL server;
AD-05 retains presigned sources/output delivery; security tests require ownership,
expired/tampered URL rejection and cross-database denial. Full key rotation and
historical data migration are out of scope. Native ECS credential renewal is
necessary runtime compatibility, not that excluded security programme.

At entry, `git status --short` was `?? docs/execution/aws/readiness/`; no tracked
changes existed. Other agents' readiness artifacts are outside this lane's write
scope. This child wrote only this file. No Docker, live workload, AWS account/API,
GitHub operation, product edit, commit, push or recursive child was used.
Public official AWS documentation was consulted for AWS semantics only.

Evidence labels used below:

- **Code**: observed source at the stated HEAD; not a live result.
- **Offline**: bounded local SDK/settings probe with dummy values and HTTP disabled.
- **Docs**: repository plan/proposal or cited official documentation.
- **Inference**: consequence of Code plus Docs; requires future verification.
- **Untested**: AWS/runtime behavior not exercised in this lane.

Relevant SHA-256 receipts:

| File | SHA-256 |
|---|---|
| `handoff-temp.md` | `3af0f1b34dfa76a9d3aa3654fd4d5d72553bcfcdbf8ef7c79883d26e89e7b7a0` |
| `HANDOFF.md` | `10b141ba037d76139b27e07bad6d3eb8c8a8bbb44a67714f74bbdbe8ea35ebb9` |
| `docs/project2-worklog.txt` | `4c9d0f729be87ec3f86ef332ed7daeb94ca6eaf9a8adbd43ddc9cabf17fa6fdc` |
| `docs/execution/aws/architecture-plan.md` | `830d4ec919e55095998152900639f47d5e62a55df7e92662bdea259300dfd83b` |
| `docs/execution/aws/cost-worksheet.json` | `6e229d72c429f05609c4a79cafd739f761f649f7de1ec0d96e6d30877596a862` |
| `docs/execution/aws/job-inputs.template.json` | `0aa2b88a9f2611bd3017e9273433d2bc81ba261ffb8451293de33c420c72ec06` |
| `project-documentation/Team17-Proposal.docx` | `fd620ae83d5a951268b0cc93e074891077577e7ac3d13d1119ea44c20efc7285` |
| `media/config.py` | `64bf84c0d763e25bb76e68543ca4577a8aff886a928ae030f64593dbf72c95b5` |
| `media/services/storage.py` | `c9593a759b6bf86c461e0196705683d55300de441af8d4c7f240e5aea3f06713` |
| `processing/config.py` | `a66c1c65a85e4e1f6fb24546225de6c059b8c52aa5b803e3005ddc273f6b1d50` |
| `processing/worker/storage.py` | `5060cac48027d090966287b93384e3031b40b593267561d926e4def0ab38d070` |
| `media/recovery.py` | `17e04439dca393bdb0b6874a4134814c9156e933d145866f2f1a0b1d0f73e86c` |
| `processing/recovery.py` | `4d93a617be9200d56ba564a1d3e70d83f5e0040ad0d72d97cf7246e24d191d28` |
| `deploy/minio/bootstrap.py` | `d10116ef0d5d04adff6efed2cbe8392a6014eb8dc70adbc03204e74164dad25b` |
| `deploy/postgres/bootstrap.sh` | `b5f6d0962517fb695bf977ed2dc31fecaf6f37728a6636d5c96689ed0d7b092a` |

## Evidence and change matrix

Severity is relative to successful/safe AWS demonstration: High blocks the relevant
cloud workflow, Medium needs configuration/acceptance, Info records reuse. A
blocked cloud check does not block implementing an offline adapter.

| Stable ID; severity; category | Exact evidence and observed behavior versus target | Smallest change; preserved invariants; owner/interface | Future observable acceptance; method, dependencies and risk | Cost/idle effect; unresolved question |
|---|---|---|---|---|
| **AWS-A-01 — High / adapt** | **Code:** `media/config.py:18–26`, `media/services/storage.py:22–38`, `processing/config.py:18–23,35–56`, `processing/worker/storage.py:24–39`; `processing/recovery.py:117–120,217–225`. Media's two Minio clients receive access/secret strings; worker and cleanup receive the same field names with separate principals. No session-token setting or provider is wired. Worker/recovery explicitly reject missing static keys. Media permits blank keys, which creates an anonymous client rather than discovering ECS credentials. **Offline:** both startup failures and unsigned Media source URL reproduced. **Docs:** plan `:416–425` requires native temporary task credentials. | Explicit local-static versus ECS-task credential mode; retain existing local variables/defaults. In ECS mode supply a refreshing SDK provider through `credentials=`, omit access/secret constructor arguments, and allow missing static fields in entrypoint guards while retaining Redis/reverse-token requirements. Apply to both Media clients and worker/cleanup. Reject incomplete static pairs and ambiguous cloud configuration without printing values. No broker, OIDC or service-to-service credential sharing. Owners: Media and Processing; internal storage constructors only. | Offline mocked ECS endpoint rotates credentials; ordinary requests and both presign clients use session tokens and new credentials without reconstructing the application. Worker/recovery start with only their task role; missing role/provider fails clearly and boundedly. Local MinIO behavior remains covered. Depends on selecting/recording deployed SDK version and task-role definitions. Avoid silently falling back to another identity/EC2 IMDS when ECS mode lacks the container endpoint. **Untested:** actual task metadata and S3 calls. | No new resident process or paid service. Local work Ready. Do not “solve” startup by placing long-lived IAM keys in SSM or task environment. |
| **AWS-A-02 — High / adapt** | **Code:** `media/services/storage.py:53–69` signs for configured TTL (default 900 s, `media/config.py:29`) and source grants report `now + TTL`. **Offline SDK:** MinIO 7.2.20 accepts 900 s with credentials expiring in about 30 s; its provider refresh threshold is only 10 s. **Docs:** temporary-credential URLs expire with credentials, even if requested expiry is later. Thus adding the provider alone leaves an inaccurate source expiry and potentially very short playback lifetime. | Bound signing to the credential snapshot actually used: effective TTL no greater than requested TTL and remaining credential validity minus a small skew margin; calculate reported source `expires_at` from the same signing time/TTL. Use a bounded refresh/retrieve attempt or return a safe unavailable response if insufficient validity remains. Use the same expiry policy for public output signing. Keep static MinIO TTL unchanged, no public schema change required. Media owns source-grant/signing interfaces. | Clock-controlled offline tests for fresh/near-expiry/expired/failed-refresh credentials and concurrent signs; no source grant claims later validity than the used credential. The token in the URL must belong to that snapshot. Verify actual signed GET, expiry/tampering and a newly requested URL using existing assets after rotation in the later authorized smoke. Depends on A-01. A URL being revoked earlier by policy is always possible; TTL is an upper bound. | No extra compute. No hours-long waiting experiment: simulate rotation offline and check naturally occurring refresh within booked cloud time. Minimum usable source-grant lifetime can stay an internal adapter constant, not new product scope. |
| **AWS-A-03 — High / configure** | **Code:** `deploy/minio/bootstrap.py:20–39` already separates Media/source owner, output writer and output cleanup. `compose/local/docker-compose.yml:104–113` gives Processing API no object credentials. Explicit regions avoid discovery. **Mismatch:** source-writer policy has no explicit multipart abort permission, whereas the SDK error path invokes AbortMultipartUpload. **Docs:** plan `:420–425` requires distinct task/execution roles. | Translate operations into AWS task policies scoped to the two buckets and existing prefixes; see next table. Media/reconciler share one task role as planned. Processing API and migration tasks have no S3 privileges. Worker has no IAM source read or output GET/HEAD/List/Delete. Cleanup has output List/Delete, no Put/Get/source rights. Add explicit source multipart abort permission. Keep execution-role image/log/parameter access distinct. No mandatory ECS RunTask/PassRole permission on cleanup for a manual demo. | Future positive/negative calls from each actual task role, including multipart abort; worker source download succeeds only via Media's signed GET. Forged/unsigned source requests, worker HEAD/Get/Delete/List and cleanup Get/Put fail; Media output Put/Delete fails. Check AWS IAM+bucket+endpoint policies together. A policy simulator alone cannot establish all runtime conditions. Depends on actual account/bucket ARNs, new AWS IaC and A-01. | IAM has no idle compute; scoped roles add no broker. Question: final bucket names/region/account are pending. Keep infrastructure implementation in Lane B's ownership. |
| **AWS-A-04 — Medium / configure** | **Code:** `media/services/storage.py:40–48,85–115`, `processing/worker/storage.py:46–63` use SDK `put_object` with known length. Installed SDK selects multipart above 5 MiB and attempts abort on caught exceptions (`minio/api.py:1909,1998–2015`). It cannot catch hard task death. `processing/recovery.py:123–127` lists completed objects, not incomplete multipart uploads. **Docs:** plan `:305` calls for abort after a day. | Retain SDK multipart upload; give both writing roles their abort permission. Configure `AbortIncompleteMultipartUpload` eligibility after one day on both buckets. Keep completed-source retention separate; do not expire retryable sources by age. No always-on janitor or extra MPU ledger. An operator can inspect/abort leftover MPUs during authorized teardown using operator-only rights. | Future ~21-MB upload through Media proves actual multipart source PUT; output upload proves writer multipart where output size crosses threshold. Controlled offline failed-part probe verifies abort call/permissions requirements. Later bounded interruption can inspect leftover upload IDs and uploaded parts; read back lifecycle configuration rather than waiting a day to call it passed. Existing cleanup must still remove late *completed* objects. Depends on A-03 and bucket IaC. | Prevents retained partial-byte charges after compute stops. Object DELETE does not remove unfinished parts. Lifecycle eligibility is not an exact one-day deletion SLA. Count part operations within existing S3 request allowance. |
| **AWS-A-05 — High / configure** | **Code:** `media/config.py:18–29` defaults to internal MinIO HTTP and public localhost TLS; `media/api/hls.py:26–50` serves owner-checked playlists and 307-redirects segments; `media/services/lifecycle.py:93–103` signs MP4. Local nginx `deploy/nginx/local.conf.template:25–38` makes object reads same-origin. `frontend/app.js:783–800` uses default hls.js. **Inference:** direct regional S3 in AWS introduces a real cross-origin segment path that local success cannot prove. **Docs:** plan `:253–271` expressly preserves external signed S3 playback. | Configure regional HTTPS S3 endpoints/region/buckets for internal SDK clients and public signer; keep CloudFront as API/public URL, not an S3 signing hostname. Configure output-bucket CORS for the exact generated HTTPS viewer origin, GET and necessary Range headers; expose Content-Range/Accept-Ranges/ETag only as used by the client/checks. CORS needs no public source upload rights. Preserve private buckets/Block Public Access and no anonymous listing. Avoid blanket endpoint-only Get denial on outputs. | Future browser hls.js playback decodes actual redirected segments; MP4 Range/seek succeeds; allowed-origin preflight returns required headers and wrong-origin browser access is not enabled. Test redirects from the real API path, not only direct S3 curl. Anonymous/tampered/expired requests fail. Inspect actual redirect/preflight Origin: if cross-origin redirects produce `Origin: null`, do not add wildcard/null CORS; coordinate a minimal segment delivery/URL adapter with Lane D and verify it. Cloud browser behavior is **Untested**. Depends on A-01/02, bucket config, final viewer origin and networking/TLS prerequisite resolution. | Keeps expected direct-playback egress in worksheet (2 GB ≈ $0.24); CORS grants no authorization. No signed-CloudFront redesign. Endpoint policies must allow a source GET authenticated by the **Media signer**, even when the network client is a worker. |
| **AWS-A-06 — Info / retain** | **Code:** `media/api/deps.py:45–55` validates distinct reverse service token and owner header; `media/api/source_access.py:14–26` checks live owned asset/revision; `media/repositories/assets.py:30–48` filters owner/deletion. `processing/worker/tasks.py:29–72` renews on every claim, checks the complete immutable descriptor, retries a 401/403 once with a new grant, and verifies downloaded length/SHA-256. `processing/service.py:15` excludes ephemeral URLs from immutable submission identity. | Reuse authenticated reverse grant and immutable descriptor. Only endpoint/credential/expiry adapters change. Workers keep an output-only task identity and receive an object-specific Media-signed GET, not Media's credential secret or database DSN. Do not replace this with worker source-bucket Get or automatic job retry. Owners: Media source authorization; Processing downloader. | Future contract negatives cover missing/wrong reverse token, wrong owner/revision/deleted asset, changed digest/length, expired grant renewal, then stored-source retry without a new upload. Reuse existing fixture and local tests. These are accepted local mechanisms, not newly proved AWS behavior. Depends on A-01/02/03 and private reverse HTTP reachability. | No new services; signing is local apart from credential retrieval. Retain bounded one-renewal retry. No per-object STS call/broker needed. |
| **AWS-A-07 — Info / retain** | **Code:** `processing/worker/storage.py:11–21,46–71` hashes exactly the SDK input with one upload reader, checks nonempty ETag, consumed length and no trailing byte, and stores size/SHA-256. It never performs output Get/HEAD. `processing/lifecycle.py:20–21` gives attempts unique output prefixes; `processing/worker/tasks.py:118–133,169` uploads master last then delegates publication to fenced lifecycle finish. | Retain output-write-only publication, immutable attempt prefixes and fenced SQL outcome. ETag is acknowledgment, not a claimed content digest (especially multipart). Preserve Media's verified streaming output-to-source copy (`media/services/storage.py:85–120`) for independent derived assets; no server-side copy or new cross-service permissions required. | Future multipart output ETag may differ from a simple content hash; persisted SHA-256/size still match bytes read by Media/operator after upload. Denied worker HEAD/Get and stale-attempt publication must remain denied. Existing `tests/processing/test_storage_performance.py`, `tests/processing/test_worker.py:170–185` and real-storage test `tests/integration/test_processing_storage.py:58` supply reusable cases; none rerun live here. | Avoids an additional output download/pass for writer verification. Existing 20-GiB Fargate scratch and S3 output bytes remain the plan; no durable local media cache. |
| **AWS-A-08 — Info / retain** | **Code:** `media/recovery.py:78–104` retains uncertain source-write cleanup authority. `media/services/lifecycle.py:219–238` cancels Processing before deleting source. `processing/recovery.py:134–200` checks terminal/deleted attempts, rescans prefixes every 60 s, keeps cleanup intent after an empty scan and releases SQL locks before object I/O. `run_once:203–212` isolates queue failure from expiration/cleanup. | Reuse these ledgers and restricted cleanup operations. No cross-service DB read, replacement queue or new background storage controller. Bind cleanup to its native role and explicit region via A-01. Source deletion and output deletion remain owned by different business services. | Future authorized worker interruption/retry/deletion checks show late completed writes are deleted eventually, successful current retry survives and old attempt cannot publish. Stop/start retains cleanup intents and resumes scans only when environment is online. Bucket lifecycle complements this for incomplete MPUs, not a replacement for attempt cleanup. Depends on owned DB persistence and A-01/03/04. | Existing cleanup requests already appear in worksheet: 10 failed/deleted prefixes × 1 scan/min × 20 h is about 12,000 LISTs (~$0.06 at captured rates), before pagination/deletes. Scans stop with recovery desired count 0. Retained storage can still bill; no claim that cleanup runs while off. |
| **AWS-A-09 — Info / retain** | **Code:** `deploy/postgres/bootstrap.sh:11–50` creates two DBs and four non-superuser/non-create-role DB roles, revokes PUBLIC database/schema privileges and grants each runtime DML/default privileges only within its DB. `deploy/postgres/smoke.sh:18–38` tests own DML, denied runtime DDL and both runtime/migrator cross-DB connection denials. Separate Base/session factories: `media/database.py:12–25`, `processing/database.py:12–28`; migrations remain `0001_media → 0002_uncertain_writes` and `processing_0001 → processing_0002`. Models store cross-service IDs without cross-service foreign keys. | Reuse bootstrap and migration histories on the accepted PostgreSQL host. Each task gets only its owner's runtime DSN; owner migrator DSN is injected solely into its one-off task. `media/migrations/env.py:11–12` and Processing equivalent permit migration DSN fallback; this is compatible with Compose's migration-only POSTGRES_DSN mapping (`compose/local/docker-compose.yml:61–65,95–99`), so no compulsory migration refactor. Preserve existing deny checks when adapting their invocation. | Future bootstrap fresh demo DBs; run each owning Alembic upgrade separately, confirm both current heads and runtime/other-service denials through the actual private endpoint. Processing migration/release leaves Media head unchanged. A live shared host is one failure domain, explicitly not DB-server HA. Depends on state-host deployment, TCP readiness and scoped secrets; no current cloud grant result claimed. | Preserves cheap one-server design and metadata-only EBS. No RDS/ElastiCache, database IAM authentication or extra server. Migration tasks must exit and be absent during downtime; Lane D owns release/shutdown command adaptation. |
| **AWS-A-10 — Medium / configure** | **Code:** Compose passes distinct DSNs/forward/reverse tokens and storage principals per role (`:21–36,61–65,95–113,131–162`); migration credentials are absent from normal service mappings. Secrets use SecretStr or hidden-repr DSNs (`media/config.py:10–15`, `processing/config.py:10–22`). Worker suppresses HTTPX signed-URL INFO logging (`processing/worker/tasks.py:25–26`), recovery avoids exception text. **Docs:** plan `:285,308–314,424–425` calls for scoped SSM injection and quiescent exports. Export/restore is proposed, not implemented evidence. | Preserve configuration separation using execution-role access to only needed SSM parameters; app task roles own S3 operations, not global secret reads. Media/reconciler retain Media secrets, worker reverse token plus Processing runtime DSN/Redis, API forward token plus owned DSN/Redis, cleanup owned DSN/Redis. No full runtime.env injection. Operator exports both DBs/role definitions to an isolated private backup prefix after intake/drain; application roles cannot read/delete that prefix. No new export service. | Future inspect task definitions/parameter references and safe metadata (never secret values), confirm no migration DSN in resident tasks, no source keys on workers, no query tokens or DSNs in logs/images/evidence. Verify private quiescent export/restore once only if backup is claimed. Exports may contain password hashes and persisted signed source URLs (`processing/models.py:29–30`); treat their contents as private, not portable evidence. Depends on account/SSM, role mapping and Lane B/D operational workflow. | Tiny exports fit S3 allowance; no snapshots or permanent backup task. State loss beyond retained exports means dataset recreation, not ownership recovery from S3 media files. No separate KMS platform or rotation project. |
| **AWS-A-11 — High / blocked** | **Docs:** `docs/execution/aws/job-inputs.template.json` leaves actual account, authorized login, currency, demo windows and resource-plan approval null. Current code/local evidence cannot prove role policy evaluation, real token rotation, AWS multipart behavior, external CORS/expiry or restart durability. CloudFront origin HTTP remains a separately disclosed unresolved proposal rule, not resolved by S3 HTTPS. | Keep only paid/cloud acceptance and application of account-specific policies blocked. Drafting provider code, offline tests and parameterized policy definitions can start now. Record account/region/bucket/viewer-origin inputs and spending authorization before later cloud work. Do not access another account or add services to hide unresolved inputs. | Future funded, bounded storage check from actual task roles and real browser with source SHA, task/image IDs, SDK version, region, request counts and redacted outcomes. Coordinator resolves account/TLS blockers; no deployment approval inferred from this report. | Original window remains anchored to 15 October, at most 14 days. Respect six long submissions total, ~0.25-GB upload plan and $13.03/$28.27 reserves-inclusive scenarios ($15/$30 targets), not a fresh test campaign or bill cap. |

## Native AWS permission translation

This is an operation inventory for new AWS IaC, not an applied IAM policy. Use
actual bucket/object ARNs and trust scoped to ECS tasks/account. These principals
describe execution responsibilities, not additional business services. S3 permissions belong on task
roles; image pull/log delivery/SSM injection belong on execution roles.
[AWS task roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html),
[AWS execution roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html).

| Task principal | Required S3 operations from observed paths | Exclusions / notes |
|---|---|---|
| Media API + Media reconciler | Source `GetObject`, `PutObject`, `DeleteObject`, `AbortMultipartUpload` on `sources/*`; output `GetObject` on `jobs/*` | Source Get also authorizes source presigning; output Get authorizes playlist reads, playback presign and derived-source verification. No output Put/Delete or backup rights. Source ListBucket/GetBucketLocation exist locally but are not called by the inspected runtime with explicit region; do not add them to AWS automatically. |
| Processing API | None | No bucket policy, key or cleanup/worker credential. |
| Processing encoding worker | Output `PutObject`, `AbortMultipartUpload` on `jobs/*` | Put covers create/upload-part/complete. Existing local ListMultipartUploadParts is not invoked by the inspected put path; include only if a chosen SDK/test path demonstrates need. No output Get/HEAD/List/Delete, no source IAM read. |
| Processing recovery | Output `ListBucket` with a `jobs/*` prefix condition, and `DeleteObject` on `jobs/*` | Listing permission is bucket-scoped; deletion is object-scoped. Runtime always supplies an attempt prefix. No source/backup access, Get, Put or unconditional RunTask/PassRole. |
| Media/Processing migration tasks | None | Their owned migration DSNs grant DB DDL; image identity does not imply the resident task's S3 role. |
| Operator/export/teardown | Separate scoped backup writes/restore and MPU inspect/abort/data removal as authorized | Never union all operator privileges into an application role. Put backup data in its own restricted prefix (or approved existing backup location), outside source/output runtime grants. |

For AWS, MinIO admin bootstrap (`deploy/minio/bootstrap.py:52–77`) is a local
mechanism to retain, not something to deploy against S3. Define private buckets,
IAM, CORS and lifecycle declaratively in the dedicated AWS deployment. Keep
unencrypted HTTP denied for object traffic and use ordinary S3-managed encryption
unless the actual account requires otherwise. SSE-KMS would change multipart
permissions and cost assumptions; it is an account-policy question, not default
scope. Required multipart operation mapping is documented by
[AWS multipart upload permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html).

**Policy interaction for Lane B:** gateway endpoint access must include the Media
signer identity for worker source GETs; a signed request uses its signer's
authority. A blanket output-bucket `aws:SourceVpce` denial blocks public signed
playback. Internal routes may use the free endpoint while external signed GETs
use S3 public HTTPS. CORS is a browser permission, not proof of ownership or a
replacement for signing. Actual IAM/bucket/endpoint policy composition remains
untested. [AWS presign authorization/expiry](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html),
[AWS CORS matching and continuing policy enforcement](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cors.html),
[AWS CORS fields](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ManageCorsUsing.html).

## Smallest credential adapter and checked SDK behavior

The current environment has `minio==7.2.20`; `pyproject.toml:15` permits
`minio>=7.2,<8`, so this is not a promise about a future unrecorded image version.
Installed SDK source was inspected locally; no GitHub browser/API fetch was used:

- `minio/api.py:137–166`: an access-key argument overrides `credentials=` with a
  StaticProvider. Passing both does not enable refresh. With neither, no automatic
  default credential chain is created.
- `minio/credentials/providers.py:392–538`: `IamAwsProvider` reads the ECS relative
  URI, obtains AccessKeyId/SecretAccessKey/Token/Expiration and caches/refetches.
  It also supports other identity mechanisms; the application should explicitly
  select the ECS mode rather than accidentally discovering a different identity.
- `minio/credentials/credentials.py:43–53`: expiration is normalized and refresh
  is triggered within about 10 seconds of expiry. That threshold is insufficient
  to guarantee a full 900-second presign lifetime.
- `minio/api.py:243–244,2480–2499`: session token goes in ordinary request headers
  and presign query, respectively; signing retrieves credentials but does not
  clamp requested expiry to credential expiration.

Use the existing SDK's provider instead of adding boto3 or building a credentials
HTTP client. Tiny per-service factories can accept explicit settings; no shared
business model/config import is needed. Keep each service independently packaged.
The ECS mode must not pass the old static access-key arguments. Provider HTTP
timeouts/retries must be bounded; worker/recovery/API error text must remain safe.
For signing, take a credential snapshot and sign with that snapshot plus the
bounded TTL; do not compute expiry from one retrieval and sign using a different
credential that might rotate concurrently. A short-lived snapshot signer is
compatible with a long-lived refreshing provider; do not cache a snapshot for
normal subsequent requests or mutate SDK private fields as the implementation.

AWS documents the ECS container endpoint and task-role credential mechanism in
[Container credential provider](https://docs.aws.amazon.com/sdkref/latest/guide/feature-container-credentials.html).
That AWS page does not certify MinIO compatibility; the SDK findings above come
from the installed code and bounded mock probe.

**Checks actually performed:** Python with `PYTHONDONTWRITEBYTECODE=1`, cleared
process environment inside the probe and `urllib3.PoolManager.urlopen` replaced
with a failing guard. Dummy provider responses were mocked; no credential URL,
token or signed URL was printed or written. Results:

1. `IamAwsProvider` fetched mock credential A, then B after simulated expiry;
   both presign queries included the corresponding session token. PASS.
2. Credentials with ~30 seconds left were considered usable while the generated
   query retained `X-Amz-Expires=900`. Mismatch reproduced.
3. Current Media Storage with blank static fields generated an unsigned source
   URL, not an ECS-role signature. Static-key gap reproduced.
4. Current `require_worker` and `require_recovery` rejected blank static keys even
   with the non-storage required dummy fields supplied. Startup gap reproduced.
5. AST inspection confirmed separate migration roots and current head revisions.

These checks establish SDK/configuration facts only. They do not prove AWS IAM
grants, S3 rejection at expiry, successful rotation on ECS, multipart upload or
browser playback. No tests against services or long performance suites were run.

## Focused issue recommendations for coordinator synthesis

These are proposed stable keys, not remotely created issues. Merge infrastructure,
release and shared acceptance portions into the matching Lane B/D issue rather
than creating duplicate platform-wide epics or reopening completed local work.
All sizes are focused implementation sessions, not a new elapsed schedule.

| Suggested key / outcome | Findings; files; smallest scope | Readiness / dependency; acceptance boundary | Size / cost / stop condition |
|---|---|---|---|
| `aws2-runtime-task-credentials` — use native ECS credentials in the existing storage SDK | A-01; both configs, Media Storage, OutputStore/CleanupStore constructors and entrypoint guards. Preserve static MinIO and API-without-storage mode. | **Ready for local adapter work**. Mock credentials, rotate without process restart, verify session token propagation in ordinary and signed paths, fail closed on missing provider; task deployment depends on later infrastructure/account. | ~1 session; no spend. Stop if it becomes SDK replacement, credential broker, new shared settings package or product auth redesign. |
| `aws2-presign-session-expiry` — keep signed grants within task credential validity | A-02/A-06; Media source/output signing. Keep existing schemas, owner checks and worker renewal. | **Waiting on runtime credential adapter**; can design offline cases now. Future tests assert snapshot consistency, requested/effective expiry and safe unavailable behavior. | ~0.5–1 session; no spend. Do not extend token lifetimes or promise immediate revocation of an already-issued bearer URL. |
| `aws2-owned-s3-policies` — private buckets, minimal role rights, real multipart/CORS configuration | A-03/04/05; dedicated AWS IaC, no changes to original course docs/local MinIO admin flow. Include one-day MPU abort eligibility, exact origin and no public-playback-blocking endpoint denial. | Parameterized definition can start locally; **apply and AWS validation blocked on account/region/buckets/viewer-origin/authorization** and Lane B topology. Runtime smoke waits on first two issues. | ~1 session for storage portion, plus shared integration; no new compute line. Stop for account-required KMS/organization policy change and report cost/permissions effect. |
| Reuse Lane B/D owned-state and per-service migration issue | A-09/10; reuse PostgreSQL bootstrap/smoke, owner-specific task secret injection, one-off migrations and quiescent private export. | **Configure/integrate**, not a new database extraction. Cloud apply blocked as above. Rehearse separate heads/cross-DB denial and no resident migration task at close. | Storage/security review ~0.5 session; EBS/SSM/export already in plan. No RDS/snapshots/rotation project. |
| Reuse Lane D small cloud acceptance issue | A-03–11; storage deny matrix, actual multipart, HLS CORS/MP4 Range, expiry/tamper, stored-source retry, cleanup/persistence. | **Waiting** on adapters/infrastructure/authorized cloud session. Reuse six total long submissions plus short smokes; record actual SDK, task roles and redacted outcomes. | One bounded shared smoke window, not separate campaigns per finding. Stop on transfer/hour allowance, wrong account, unapproved paid resource or secret-bearing evidence. |

The next independent local change is `aws2-runtime-task-credentials`. The native
provider removes the primary runtime blocker without changing the working domain
boundary. Account inputs and the origin-TLS decision remain deployment blockers,
not reasons to delay offline implementation.

Optional work stays outside the first demo: signed CloudFront media delivery,
unattended worker starts/RunTask authority on recovery, custom KMS keys, extra
snapshots, object-version retention, resumable client uploads and broader key
rotation. None is needed to preserve current storage contracts.

## Remaining questions and honest acceptance limits

- Confirm actual account, region, bucket names and exact generated viewer origin;
  bind scoped role/SSM ARNs only after those inputs exist. No account was read.
- Actual AWS credential refresh/presign behavior must be checked in the chosen
  image; broad SDK dependency bounds mean the inspected local version is evidence
  to record, not an assumed pin. Simulated rotation avoids an hours-long trial.
- Direct S3 segment redirects must be exercised in a real browser. Do not claim
  CORS correctness from CLI success, or change the frontend's design to hide a
  delivery failure. Any redirect-Origin problem needs a demonstrated small fix.
- Incomplete-upload lifecycle deletion is asynchronous and separate from object
  cleanup. One-day eligibility handles retained partial data while compute is
  off; it is not immediate teardown or a reason to leave cleanup running.
  [AWS incomplete-multipart lifecycle semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html).
- Quiescent DB exports preserve a common ownership/job boundary; they are private
  and require restore verification if claimed. S3 media alone cannot recreate
  erased owners/accounts. PostgreSQL/Redis/nginx remain a shared host/AZ failure.
- Original throughput/recovery targets and all accepted/rejected local evidence
  remain intact. Small cloud storage tests establish compatibility only; they do
  not recertify full 30-clip scaling targets or reverse the 38/39 rejections.

Downtime means all three service desired counts zero, no standalone tasks
(including migrations/generators/workers), EC2 stopped and no retained EIP. This
lane adds no resident helper. S3/metadata/image retention and viewer request costs
can remain while compute is off; source-presign permissions do not require tasks
to stay alive after issuance, but the issued credential expiry still bounds use.
