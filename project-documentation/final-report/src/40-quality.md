# Quality Attributes

The results below keep the proposal's targets, workloads and timing boundaries; Figure
{@fig:results} charts the speedup and release-time results. The measurement record is in
`docs/results/actual-vs-target.md` and `docs/evidence-index.md`.

![Figure {#fig:results}. Speedup and Processing release time against the proposal targets (AWS V1 and local pre-V1 speedup; r1018b and r1019a release times).](figures/results-actual-vs-target.png){width=15cm}

| Attribute | Scenario (proposal target) | Result | Verdict |
|:----------|:------------------------------------|:------------------------------------------|:---------|
| Scalability | 2 workers ≥ 1.6× and 3 workers ≥ 2.1× the jobs/min of 1 worker | AWS V1 (6 clips, one run per cap): 0.483 / 0.700 / 1.134 jobs/min → **1.449×** and **2.347×** | **FAIL** at 2; PASS at 3 |
| Scalability | Median queue wait falls at each step; 0 failed jobs | 274.3 s → 135.7 s → 9.6 s; 0 failed; 0 encoders left running | PASS |
| Scalability | (same, local pre-V1 design, 30 clips × 3 repeats) | 2.032× and 2.885× | PASS (pre-V1 design) |
| Scalability | V2-live automatic scale 0 → 3 → 0 | 0 → 3 → 0 with 3 concurrent clips; 9-clip backlog at cap 3 in 239 s (2.26 jobs/min) | PASS |
| Performance | 50 users polling status for 3 min: p90 ≤ 700 ms, < 1 % errors | p90 **58.2 ms**, 9,000 requests, 0 errors (in-region generator) | PASS |
| Performance | 20 concurrent logins: p90 < 2 s | p90 **178 ms** (20 samples) | PASS |
| Performance | Warm-job queue wait ≤ 20 s (V2-live), standard Fargate lane | about **37 s**; Fargate start median 25.6 s | **FAIL** |
| Performance | Same wait on the Lambda short-encode lane (≤ 60 s clips, `sl1021`, 5 jobs per arm, one 24 s clip) | median **0.26 s** (max 2.6 s) against 32.6 s on Fargate; processing 5.3 s against 8.0 s; billed compute USD 0.0003 against 0.0021 per encode; 0 failures | PASS |
| Performance | Submit-to-done, same run (20 s aim; no proposal target) | Lambda cold 92.0 s (n = 1), warm median **45.2 s**; Fargate median 87.7 s | Above the 20 s aim |
| Availability | Worker killed mid-encode: re-queued or failed within 5 min | Stop detected in **5.8 s**; lease expiry marks the job `failed`; retry creates a new attempt | PASS |
| Availability | Lost queue entry re-enqueued within 2 min | 23.5 s (local pre-V1); ≤ 120 s asserted on a simulated clock (local V1) | PASS locally; **NOT_RUN** on AWS |
| Availability | Processing temporarily unavailable while Media accepts uploads | Command consumer off for 48 s: Media answered 202 and held the command; job `done` 58.9 s after re-enable | PASS |
| Deployability | Release Processing alone, smoke-tested, in ≤ 10 min; Media unchanged | Operator promote 322.5 s; CD `Release` step **10.1–10.3 min** (`r1018b`) and 9 min 39 s (`r1019a`); release plus the separate upload smoke **15 min 38 s**; Media unchanged at every snapshot | **FAIL** for `r1018b` and release + smoke; PASS for the `r1019a` step |
| Deployability | Bad candidate restores automatically | CD run 39271754470 (`bad_candidate=true`) → `restored` | PASS (source `7928b7c`) |
| Security | Negative tests 100 % rejected; 0 fixable HIGH/CRITICAL at release | Selected negatives rejected on AWS V1 and on `dc2-live` (#229, 19 October); recorded releases met the fixable-image policy | PASS |
| Reusability | Publisher CLI: 0 service imports, 0 database credentials, ≤ 2 person-days | 0 and 0, enforced by a test; 495 physical Python lines across five files; effort not timed | PASS; effort **NOT_MEASURED** |

## Performance

HTTP distribution, queue buffering and bounded encoding are separated, as recorded in **AD-30**
(section 3.2). API Gateway routes requests to Media or Processing Lambda aliases with a stage
throttle of 20 requests/s and a burst of 50. SQS buffers encode work; the Processing launcher
reserves capacity under a database lock and starts at most three finite Fargate tasks. Sources of
at most 64 MiB, 60 s and 1080 pixels can use the short Lambda lane (batch size one, concurrency two,
3008 MB), which avoids a Fargate task start for small encodes; a refused probe redirects to the
standard lane (`processing/short_lane.py`, `processing/short_encoder.py`; UC-2 in section 6.4).

Other tactics keep the API path short:

- Upload bytes go directly to S3 using presigned POST; MP4 range requests and HLS segments use
  signed object URLs. Lambda carries JSON control requests.
- CloudFront caches the content-hashed frontend. API caching is disabled and authenticated
  responses carry `Cache-Control: private, no-store`; playlists and signed URLs remain fresh.
- Media answers status from its own projection without a Processing business API call. Listing
  joins owned assets and projections in one query; a single-job read loads the owned asset and
  then its projection (`media/repositories/assets.py`, `media/projections.py`).
- Standard encoders use 2 vCPU / 4 GiB tasks. The HLS ladder stays within the source height.
- Warm Lambda environments reuse one pooled SQL connection; a 60 s server-side idle-session
  timeout releases idle connections so Aurora can auto-pause (`runtime_support/lambda_db.py`).
  The recorded first read after a pause took about 4.7 s; later reads took about 263 ms **[AWS]**.

## Availability

Media commits accepted work and its outbox intent together, and Processing commits its inbox,
job state and outboxes before acknowledging a command, so queue buffering separates accepted work
from the moment an encoder can run (DP-2). Pending outbox rows are republished and missing queued
work is rebuilt from SQL by a one-minute repair tick and by ECS `STOPPED` and S3 object events
(`delivery/sql.py`, `processing/recovery_v1.py`). The command/result mappings each allow at most
two concurrent Lambda invocations and report partial batch failures. With the standard cap of
three and the short cap of two, a burst becomes backlog rather than an unbounded fleet. In the
consumer-interruption experiment Media kept accepting uploads while Processing consumption was
paused.

Database-clock leases, task bindings and deadlines fence stale workers. A failed attempt becomes
visible, and owner retry creates a new attempt over the stored source. Workers cannot publish
queue messages. DLQs hold poison messages after five receives; the recorded poison message
reached its DLQ after 2,101 s **[AWS]**. Managed services and subnets across two availability zones
provide the infrastructure boundary. Each service's Aurora cluster is a single instance in one
region, with one-day backups (AD-29).

Owner-release smoke failure starts automatic restore (section 5.3). Stateful resources use
`DeletionPolicy: Retain`, and deployment rejects replacement of Aurora, buckets or the
distribution. The enabled configuration defines 15 alarms and a services dashboard
(`scripts/aws/v1/definitions.py`).

## Security

Every protected request passes the Media-owned Lambda REQUEST authorizer and then service-side
checks of the current user and trusted Actor (section 3.1 and DP-3), so each service acts only
for a verified current owner. Health and the Media register/login/logout routes are the only
public exceptions.

| Area | Implemented control |
|:----------------|:--------------------------------------------------------------|
| Owner scoping | Both services filter by the trusted owner; foreign job/asset IDs return 404. Administrative operations require the operator role. |
| Session and validation | Host-only `HttpOnly`, `Secure`, `SameSite=Strict` cookie; one-hour token; authenticated responses use `private, no-store`. bcrypt cost 10 hashes passwords. Upload validation enforces allowed types and 100 MiB; adoption verifies size, hash, signature and pinned S3 version. |
| Least-privilege IAM | Separate function, migration and worker roles; resource-scoped S3, queue and parameter permissions; queue policies restrict producers/consumers; separate database identities and no runtime DDL. The enabled configuration defines 19 IAM roles (17 at default flags). |
| Developer and delivery credentials | GitHub Actions assumes the AWS deploy role through OIDC and the branch-restricted `aws` environment, without long-lived AWS keys in GitHub. Runtime access uses AWS roles and scoped SSM SecureStrings. |
| Encryption | In transit: CloudFront HTTPS, TLS 1.2 to the API origin, TLS-only S3/SQS policies and Aurora `rds.force_ssl=1` with CA verification. At rest: encrypted Aurora storage, SSE-S3, SQS-managed encryption and SSM SecureStrings. |
| Network | Lambda and Aurora use private subnets. Media database ingress on TCP 5432 permits the Lambda and migration security groups; Processing additionally permits the worker security group. Worker tasks have no inbound application listener. |
| Source and supply chain | Ruff S and CodeQL provide SAST; gitleaks scans history; npm audit, pip-audit and Trivy check dependencies and images; cfn-lint and Checkov inspect generated infrastructure. Section 5.2 gives triggers and dispositions. |
| Dynamic checks | Authenticated OWASP ZAP runs against the disposable local V1 stack in CI and weekly (`dast.yml`); execution, coverage and cleanup are required, and findings are reported for triage. |
| Operations | Gateway throttles, service/DLQ alarms and a budget alarm support detection and containment; WAF/GuardDuty/IDS are tracked in AISS-02. |

Infrastructure controls are generated in `scripts/aws/v1/definitions.py`; CI credential trust is
specified in `deploy/aws/v1/github-oidc.yaml`. The 22 October CodeQL dismissals and the
accepted-unfixed FFmpeg CVE-2025-52290 are dated triage records
(`docs/execution/aws/v1/scan-accepted-unfixed-20261017.json`).

**Verification.** The following negative tests were recorded on AWS V1 stacks `r1017b`/`r1018b`
and on `dc2-live` for issue #229 on 19 October **[AWS]**.

| Control (proposal §3.3) | Result |
|:----------------------------------------|:-----------------------------------------------------------|
| Unauthenticated requests rejected | 401 on all six probed job routes, through CloudFront and directly through Gateway |
| User A cannot read, retry, edit, delete or play User B's assets | 404 for B on every Media and Processing route for A's job |
| Forged identity headers and token-less internal calls | Forged headers changed nothing; anonymous admin 401, non-operator 403 |
| Direct queue send by an unlisted principal | 403 on all three queues; 0 messages accepted |
| Each service's credentials refused on the other's database | `InsufficientPrivilegeError`; runtime DDL denied |
| Expired and tampered presigned URLs; no public listing | Tampered 400/403; both 900 s expiries waited out (206/204 before, 403 after); unsigned S3 403 |
| Invalid and oversized uploads | 100 MiB + 1 byte refused by S3 (400) and never adopted |
| External port scan; private datastores | Only 80 and 443 open; Aurora `PubliclyAccessible=false`; no `0.0.0.0/0` ingress |
| Secrets out of git and images | gitleaks green in CI |
| Zero fixable HIGH/CRITICAL image findings at release | Met at the recorded releases; retained-image handling is described in section 5.3 |

The ZAP scope is seven GET operations on the local bridge: Media `auth/me`, `health`, `jobs`,
`jobs/{job_id}` and Processing `health`, `jobs`, `jobs/{job_id}`, under `/api/<service>/`. The
harness caps requests at 1,600, seeds two users and uploads, and invokes no workers. The 25 October
run retained 16 findings and passed cleanup; ownership-negative fixtures are separate checks
(`scripts/dev/v1_dast.py`).

## Extensibility and Maintainability

Media separates routes (`media/api/`), application services (`media/services/`), repositories,
owned models/migrations and projection, messaging and recovery modules. Processing separates
API/authentication, lifecycle and messaging, launcher/adapters, recovery and worker execution
(`processing/worker/`); `media_engine/` holds validation, probes and FFmpeg command builders. The
services share only contract and technical libraries (`contracts/`, `delivery/`,
`runtime_support/`).

A new operation extends `media_engine/` and the submit payload without changing queue transport.
A new client uses the published OpenAPI contract and reserve/upload/finalize/status flow. The
Publisher demonstrates this with 495 physical Python lines across five files, no service imports
and no database credentials, checked by AST and public-contract tests. Image checks reject
opposite-domain and legacy imports; generated-template freshness and IAM-shape tests protect
infrastructure boundaries.

Contract changes are additive within a version, with consumer-owned fixtures. A breaking change
first releases readers for N and N-1, then raises the emitted version after both readers are ready.
`contracts/v1.py` accepts only positive supported versions, so the current N=1 accepts version 1;
the rolling-upgrade policy is exercised with raised-version fixtures (`contracts/README.md`).

### Unit tests for complex classes and modules

The modules below hold the most complex behavior. Counts are static `test_` definitions in each
named file; the two parameterized files report collected cases. Shared files support several
modules, so rows are not additive.

| Complex module / class | What it does | Unit test file(s) | Number of tests |
|:----------------------------|:----------------------------------|:-------------------------------------------|:-----------|
| Media projections / `ProjectedJob`; `v1_lifecycle.edit` | Orders result snapshots, fences terminal state, adopts edits and handles replay | `tests/media/test_v1_projection.py` | 12 definitions |
| Media `direct_intake` | Reserves and verifies uploads, adopts pinned versions, schedules late-write cleanup | `tests/media/test_direct_intake.py` | 26 definitions |
| Media `Storage` | Signs, streams, verifies, copies and removes versioned objects | `tests/media/test_media_storage.py`; source-verification cases in `test_direct_intake.py` above | 7 storage definitions |
| Media native recovery | Stops at deadlines, orders cleanup phases and caps batches | `tests/media/test_native_recovery.py` | 13 cases |
| Processing launcher / `LauncherConfig`, `Observation` | Observes ECS/queue demand and controls bounded reservations | `tests/aws/v1/test_unattended_launch.py` | 40 definitions |
| Processing launcher `tick()` | Avoids idle I/O, preserves unknown demand and stops refused/ambiguous sends | `tests/processing/test_launcher_tick.py` | 12 cases |
| Processing messaging | Validates durable work identity and lane routing | `tests/processing/test_v1_delivery_rules.py` | 10 definitions |
| Processing SQS worker | Bounds polling and fences claim, acknowledgement and visibility loss | `tests/processing/test_v1_worker.py` | 32 definitions |
| Processing lifecycle / `Claim` | Claims, heartbeats and finishes under lease/attempt fences | `tests/processing/test_lifecycle.py` | 10 definitions |
| Processing recovery helpers | Expiry and output-cleanup rules used by native recovery | `tests/processing/test_recovery.py` | 10 definitions |
| Short-lane admission and encoder | Enforces size/probe bounds, redirects and handles partial batch failure | `tests/processing/test_short_lane.py`; `test_short_encoder.py` | 16 + 16 definitions |
| Engine validation, commands, HLS / `SourceProbe` | Rejects invalid operations and builds safe FFmpeg/probe/HLS commands | `tests/media_engine/test_validation.py`; `test_commands.py`; `test_hls.py` | 10 + 3 + 12 definitions |
| Publisher `PublicClient`, `Intents`, CLI | Persists cookies and upload/file identity; maps CLI outcomes | `tests/publisher/test_publisher.py`; `test_direct_upload.py`; `test_file_identity.py` | 26 + 4 + 3 definitions |
| `Actor`, `Source`, `Envelope`, `GatewayAdapter`, delivery | Validates trusted boundaries, frozen messages, partial failures and poison handling | `tests/contracts/test_prepared_contracts.py`; `tests/v1/test_contract_fixtures.py`; `test_delivery.py` | 7 + 17 + 5 definitions |

All 25 native-recovery and launcher-tick cases passed, and eight deliberate mutations (deadlines,
cleanup failure ordering, batch bounds, idle I/O, unknown demand and send termination) were each
detected. Real PostgreSQL suites verify transactions, locking and concurrency
(`tests/v1/test_media_cleanup_sql.py`, `test_launcher_sql.py`, `test_messaging_sql.py`,
`test_delivery_recovery_sql.py`).

### Test inventory and coverage gates

The 10 November audit recorded **1,316 offline cases passed** across two runs (820 service cases
and 496 V1/launcher cases), with two skips; integration and e2e cases were deselected. Its
static service inventory was **386 unit test definitions** across Media 150, Processing 167,
engine 25, Publisher 34, contracts 7 and runtime support 3, before the 25 cases above were added.

| Scope | Combined statement/branch minimum | Raw branch minimum | Enforcement |
|:------------------------------|:---------------------|:------------------|:-----------------------------|
| Every measured backend package | 80% | Reported | Per-package gate; missing production files fail |
| Media and Processing packages | 90% | 85% | Additional gate with the complete five backend tiers |
| `media/recovery_v1.py`, `processing/recovery_v1.py` | 80% | 75% | Additional module gate with the complete five tiers |
| Frontend `app.js` | 90% each for statements, branches, functions and lines | 90% | Vitest coverage job |

The exact gates are in `scripts/dev/coverage.py:19–39,97–202` and `frontend/package.json`.
Backend evidence combines source-fingerprint-matched fast, legacy integration, Processing
integration, Media integration and V1 integration fragments; CI retains XML, JSON and `gate.json`,
plus JUnit and coverage summaries (`scripts/ci/quality_summary.py`).
