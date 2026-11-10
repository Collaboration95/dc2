# Quality Attributes

The results below retain the proposal's targets, workloads and timing boundaries. The measurement
record is in `docs/results/actual-vs-target.md` and `docs/evidence-index.md`.

![Figure {#fig:results}. Speedup and Processing release time against target (AWS V1 and V2-live; measured results).](figures/actual-vs-target.png){width=15cm}

| Attribute | Scenario (proposal target) | Result | Verdict |
|:----------|:------------------------------------|:------------------------------------------|:---------|
| Scalability | 2 workers ≥ 1.6× and 3 workers ≥ 2.1× the jobs/min of 1 worker | AWS V1 (6 clips, one run per cap): 0.483 / 0.700 / 1.134 jobs/min → **1.449×** and **2.347×** | **FAIL** at 2; PASS at 3 |
| Scalability | Median queue wait falls at each step; 0 failed jobs | 274.3 s → 135.7 s → 9.6 s; 0 failed; 0 encoders left running | PASS |
| Scalability | (same, local pre-V1 design, 30 clips × 3 repeats) | 2.032× and 2.885× | PASS (different design; not AWS) |
| Scalability | V2-live automatic scale 0 → 3 → 0 | 0 → 3 → 0 with 3 concurrent clips; 9-clip backlog at cap 3 in 239 s (2.26 jobs/min) | PASS (no 1/2/3 comparison) |
| Performance | 50 users polling status for 3 min: p90 ≤ 700 ms, < 1 % errors | p90 **58.2 ms**, 9,000 requests, 0 errors (in-region generator) | PASS |
| Performance | 20 concurrent logins: p90 < 2 s | p90 **178 ms** (20 samples) | PASS |
| Performance | Warm-job queue wait ≤ 20 s (V2-live), standard Fargate lane | about **37 s**; Fargate start median 25.6 s (5-job `sl1021` Fargate arm: 32.6 s median) | **FAIL** |
| Performance | Same wait on the Lambda short-encode lane (≤ 60 s clips, `sl1021`, 5 jobs, 24 s clip) | median **0.26 s** (max 2.6 s) against 32.6 s on Fargate; processing 5.3 s against 8.0 s; billed compute USD 0.0003 against 0.0021 per encode; 0 failures | PASS (queue wait) |
| Performance | Submit-to-done, same run (no proposal target; 20 s end to end is the aim) | Lambda cold 92.0 s (n = 1), warm median 45.2 s; Fargate median 87.7 s | **FAIL** against 20 s on both lanes |
| Availability | Worker killed mid-encode: re-queued or failed within 5 min | Stop detected in **5.8 s**; lease expiry marks the job `failed`; retry creates a new attempt | PASS (reaction time only) |
| Availability | Lost queue entry re-enqueued within 2 min | 23.5 s (local pre-V1); ≤ 120 s asserted on a simulated clock (local V1) | PASS locally; **NOT_RUN** on AWS |
| Availability | Processing temporarily unavailable while Media accepts uploads | Command consumer off for 48 s: Media answered 202 and held the command; job `done` 58.9 s after re-enable | PASS (consumer only) |
| Deployability | Release Processing alone, smoke-tested, in ≤ 10 min; Media unchanged | Operator promote 322.5 s; CD `Release` step 10.1–10.3 min (`r1018b`) and 9 m 39 s (`r1019a`); release plus a separate upload smoke 15 m 38 s; Media unchanged at every snapshot | **FAIL** for the timed release and separate smoke boundary |
| Deployability | Bad candidate restores automatically | CD run 39271754470 (`bad_candidate=true`) → `restored` | PASS (source `7928b7c`) |
| Security | Negative tests 100 % rejected; 0 fixable HIGH/CRITICAL at release | Selected negatives rejected on AWS V1 and on `dc2-live` (#229, 19 October); recorded releases met the fixable-image policy | PASS (dated negative tests and release checks) |
| Reusability | Publisher CLI: 0 service imports, 0 database credentials, ≤ 2 person-days | 0 and 0, enforced by a test; 491 lines; effort not timed | PASS; effort **NOT_MEASURED** |

## Performance

API Gateway routes HTTP requests to Media or Processing Lambda aliases, and Lambda handles
concurrent invocations within the account quota. The stage throttle is 20 requests/s with a burst
of 50. Encoding capacity is controlled separately: SQS buffers bursts, competing consumers pull
work, and the Processing launcher reserves capacity under a database lock before starting finite
Fargate tasks. It reconciles SQL backlog, visible queue demand, live tasks and pending reservations,
with a standard cap of three. There is no ALB. This division of HTTP distribution, queue buffering
and bounded execution is the decision recorded in **AD-30** (section 3.2;
`scripts/aws/v1/definitions.py`, `processing/launcher.py`).

Small videos have a separate short lane when enabled. `processing/short_lane.py` first routes
sources of at most 64 MiB that have not already attempted Lambda execution. The worker downloads
and probes the source, then admits finite positive durations of at most 60 s and heights of at
most 1080 pixels. A refused probe redirects through a fenced successor to standard Fargate work.
The short mapping has batch size one and maximum concurrency two; its Lambda has 3008 MB.
This avoids paying a Fargate task start for each small encode (`processing/short_encoder.py`).

Other performance tactics keep the API path short:

- Upload bytes go directly to S3 using presigned POST; MP4 range requests and HLS segments use
  signed object URLs. Lambda carries JSON control requests.
- CloudFront caches the content-hashed frontend. API caching is disabled and authenticated
  responses carry `Cache-Control: private, no-store`; playlists and signed URLs remain fresh.
- Media answers status from its own projection with one owner-scoped query, without a Processing
  business API call for each poll (`media/repositories/assets.py`).
- Standard encoders use 2 vCPU / 4 GiB tasks. The HLS ladder stays within the source height.
- Per-invocation `NullPool` sessions allow Aurora to pause at 0 ACU. The recorded first read after
  a pause took about 4.7 s; later reads took about 263 ms **[AWS]**.

The table contains the measured outcomes and target misses once. The HTTP generator ran in-region.
The AWS scaling comparison used six clips and one run per cap. The `sl1021` lane comparison used
five jobs per arm and one 24 s clip, padded for the Fargate arm. Its 35–80 s outside queue wait and
encoding remains the subject of AISS-01.

## Availability

Media commits an Asset and command outbox intent in one SQL transaction. A later relay publishes
to SQS. Processing commits its inbox, job state and work/result outboxes before acknowledging a
command. Queue buffering therefore separates accepted business work from the moment an encoder
can run. After a transport interruption, pending outbox rows can be republished and missing queued
work reconstructed from SQL (`delivery/sql.py`, `processing/recovery_v1.py`). The one-minute repair
tick and ECS `STOPPED`/S3 object events trigger recovery passes.

The command/result mappings each allow at most two concurrent Lambda invocations and report
partial batch failures. Standard and short execution retain their separate caps of three and two,
so a burst becomes backlog rather than an unbounded fleet. These capacity and recovery tactics
implement AD-30. The recorded consumer-interruption experiment demonstrates Media acceptance while
Processing consumption is paused; Processing's HTTP authentication still uses Media's authorizer.

Database-clock leases, task bindings and deadlines fence stale workers. A failed attempt becomes
visible, and owner retry creates a new attempt over the stored source. Workers cannot publish
queue messages. DLQs contain poison messages after five receives; the recorded poison message
reached its DLQ after 2,101 s **[AWS]**. Managed services and subnets across two availability zones
provide the infrastructure boundary. Each service's Aurora cluster remains a single instance in
one region, with one-day backups and no recorded restore drill (AD-29).

Owner-release smoke failure initiates automatic restore, as described in section 5.3. Stateful
resources use `DeletionPolicy: Retain`, and deployment rejects replacement of Aurora, buckets or
the distribution. The enabled source configuration defines 15 alarms and a services dashboard;
the historical backlog receipt recorded 13/13 alarms `OK` under its then-current configuration
(`scripts/aws/v1/definitions.py`).

## Security

API Gateway invokes a **Media-owned Lambda REQUEST authorizer** before protected API integrations.
It verifies the session JWT and current user/role. Media then revalidates the cookie and current
User and checks agreement with the trusted Actor (`media/authorizer.py`, `media/api/deps.py`).
The Gateway adapter strips caller-supplied owner, role and cookie headers, reconstructs cookies
from the Gateway event and supplies trusted Actor context to Processing (`contracts/gateway.py`,
`processing/auth.py`). Health and Media register/login/logout routes are public exceptions.

| Area | Implemented control |
|:----------------|:--------------------------------------------------------------|
| Owner scoping | Both services filter by the trusted owner; foreign job/asset IDs return 404. Administrative operations require the operator role. |
| Session and validation | Host-only `HttpOnly`, `Secure`, `SameSite=Strict` cookie; one-hour token; authenticated responses use `private, no-store`. bcrypt cost 10 hashes passwords. Upload validation enforces allowed types and 100 MiB; adoption verifies size, hash, signature and pinned S3 version. |
| Least-privilege IAM | Separate function, migration and worker roles; resource-scoped S3, queue and parameter permissions; queue policies restrict producers/consumers; separate database identities and no runtime DDL. The enabled configuration defines 19 IAM roles (17 at default flags). |
| Developer and delivery credentials | GitHub Actions assumes the AWS deploy role through OIDC and the branch-restricted `aws` environment, without long-lived AWS keys in GitHub. Runtime access uses AWS roles and scoped SSM SecureStrings. |
| Encryption | In transit: CloudFront HTTPS, TLS 1.2 to the API origin, TLS-only S3/SQS policies and Aurora `rds.force_ssl=1` with CA verification. At rest: encrypted Aurora storage, SSE-S3, SQS-managed encryption and SSM SecureStrings. |
| Network | Lambda and Aurora use private subnets; database ingress is restricted to the internal service security group. Worker tasks have no inbound application listener. |
| Source and supply chain | Ruff S and independent CodeQL provide SAST; gitleaks scans history; npm audit, pip-audit and Trivy check dependencies/images; cfn-lint and Checkov inspect generated infrastructure. Section 5.2 gives triggers and dispositions, including the PR #328 additions. |
| Dynamic checks | Authenticated OWASP ZAP runs against the disposable local V1 stack in CI and weekly (`dast.yml`); execution, coverage and cleanup are required, while vulnerability findings are report-only. |
| Operations | Gateway throttles, service/DLQ alarms and a budget alarm support detection and containment; WAF/GuardDuty/IDS are tracked in AISS-02. |

Infrastructure controls are generated in `scripts/aws/v1/definitions.py`; CI credential trust is
specified in `deploy/aws/v1/github-oidc.yaml`. The DevOps inventory distinguishes logs, JSON,
receipts and supported SARIF publication. The 22 October CodeQL dismissals and accepted-unfixed
FFmpeg CVE-2025-52290 are dated triage records (`docs/execution/aws/v1/scan-accepted-unfixed-20261017.json`).

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

The ZAP scope is seven selected GET operations on the local bridge: Media `auth/me`, `health`,
`jobs`, `jobs/{job_id}` and Processing `health`, `jobs`, `jobs/{job_id}`, under `/api/<service>/`;
auth lifecycle POST, upload, HLS, admin and other mutations are excluded. The harness caps requests
at 1,600, seeds two users/uploads and invokes no workers. The 25 October run retained 16 findings
and passed cleanup; ownership-negative fixtures are separate checks (`scripts/dev/v1_dast.py`).

## Extensibility and Maintainability

Media separates HTTP routes/dependencies (`media/api/`), application services (`media/services/`),
repositories and owned SQL models/migrations. Projection, messaging and recovery modules handle
asynchronous state changes. Processing separates API/authentication, lifecycle and messaging,
launcher/adapters, recovery, and worker execution (`processing/worker/`). `media_engine/` provides
validation, probes and FFmpeg command builders. The services share contract/technical libraries
(`contracts/`, `delivery/`, `runtime_support/`) while keeping their business models separate.

A new operation extends `media_engine/` and the submit payload without changing queue transport.
A new client uses the published OpenAPI contract and reserve/upload/finalize/status flow. The
Publisher demonstrates this with 491 Python lines in six files, no service imports and no database
credentials, checked by AST and public-contract tests. Image checks reject opposite-domain and
legacy imports; generated-template freshness and IAM-shape tests protect infrastructure boundaries.

Contract changes are additive within a version, with consumer-owned fixtures. A breaking change
first releases readers for N and N-1, then raises the emitted version after both readers are ready.
`contracts/v1.py` accepts only positive supported versions, so the current N=1 accepts version 1;
the rolling-upgrade policy is exercised with raised-version fixtures (`contracts/README.md`).

### Unit tests for complex classes and modules

The audit in `rev-1.1/A3-CODE-GAPS.md` §4 identifies complex behavior in module functions and
boundary classes. Counts below are static `test_` definitions in each named file, except the two
PR #327 rows, which report expanded parameterized cases. Shared files can support several modules,
so rows are not additive.

| Complex module / class | What it does | Unit test file(s) | Number of tests |
|:----------------------------|:----------------------------------|:-------------------------------------------|:-----------|
| Media projections / `ProjectedJob`; `v1_lifecycle.edit` | Orders result snapshots, fences terminal state, adopts edits and handles replay | `tests/media/test_v1_projection.py` | 12 definitions |
| Media `direct_intake` | Reserves and verifies uploads, adopts pinned versions, schedules late-write cleanup | `tests/media/test_direct_intake.py` | 26 definitions |
| Media `Storage` | Signs, streams, verifies, copies and removes versioned objects | `tests/media/test_media_storage.py`; source-verification cases in `test_direct_intake.py` above | 7 storage definitions |
| Media native recovery | Stops at deadlines, orders cleanup phases and caps batches | `tests/media/test_native_recovery.py` (PR #327) | 13 cases |
| Processing launcher / `LauncherConfig`, `Observation` | Observes ECS/queue demand and controls bounded reservations | `tests/aws/v1/test_unattended_launch.py` | 40 definitions; 44 audit cases |
| Processing launcher `tick()` | Avoids idle I/O, preserves unknown demand and stops refused/ambiguous sends | `tests/processing/test_launcher_tick.py` (PR #327) | 12 cases |
| Processing messaging | Validates durable work identity and lane routing | `tests/processing/test_v1_delivery_rules.py` | 10 definitions |
| Processing SQS worker | Bounds polling and fences claim, acknowledgement and visibility loss | `tests/processing/test_v1_worker.py` | 32 definitions |
| Processing lifecycle / `Claim` | Claims, heartbeats and finishes under lease/attempt fences | `tests/processing/test_lifecycle.py` | 10 definitions, including legacy submission cases |
| Processing recovery helpers | Expiry and output-cleanup rules used by native recovery | `tests/processing/test_recovery.py` | 10 definitions, including legacy repair cases |
| Short-lane admission and encoder | Enforces size/probe bounds, redirects and handles partial batch failure | `tests/processing/test_short_lane.py`; `test_short_encoder.py` | 16 + 16 definitions |
| Engine validation, commands, HLS / `SourceProbe` | Rejects invalid operations and builds safe FFmpeg/probe/HLS commands | `tests/media_engine/test_validation.py`; `test_commands.py`; `test_hls.py` | 10 + 3 + 12 definitions |
| Publisher `PublicClient`, `Intents`, CLI | Persists cookies and upload/file identity; maps CLI outcomes | `tests/publisher/test_publisher.py`; `test_direct_upload.py`; `test_file_identity.py` | 26 + 4 + 3 definitions |
| `Actor`, `Source`, `Envelope`, `GatewayAdapter`, delivery | Validates trusted boundaries, frozen messages, partial failures and poison handling | `tests/contracts/test_prepared_contracts.py`; `tests/v1/test_contract_fixtures.py`; `test_delivery.py` | 7 + 17 + 5 definitions |

PR #327 (`test/native-recovery-launcher`) adds the 13 Media and 12 launcher cases above.
Its focused run passed all 25. Eight temporary mutations were detected by all 18 selected negative
cases, covering deadlines, cleanup failure ordering, batch bounds, idle I/O, unknown demand and
send termination. Real PostgreSQL suites retain transaction, locking and concurrency verification
(`tests/v1/test_media_cleanup_sql.py`, `test_launcher_sql.py`, `test_messaging_sql.py`,
`test_delivery_recovery_sql.py`).

### Test inventory and coverage gates

The 10 November audit recorded **1,316 offline cases passed** across two runs (820 service cases
and 496 V1/launcher cases), with two skips; integration and e2e cases were deselected. Its static
service inventory was **386 unit test definitions** across Media 150, Processing 167, engine 25,
Publisher 34, contracts 7 and runtime support 3. These dated totals precede PR #327.

| Scope | Combined statement/branch minimum | Raw branch minimum | Enforcement |
|:------------------------------|:---------------------|:------------------|:-----------------------------|
| Every measured backend package | 80% | Reported | Per-package gate; missing production files fail |
| Media and Processing packages | 90% | 85% | Additional gate with the complete five backend tiers |
| `media/recovery_v1.py`, `processing/recovery_v1.py` | 80% | 75% | Additional module gate with the complete five tiers |
| Frontend `app.js` | 90% each for statements, branches, functions and lines | 90% | Vitest coverage job |

The exact gates are in `scripts/dev/coverage.py:19–39,97–202` and `frontend/package.json`.
Backend evidence combines source-fingerprint-matched fast, legacy integration, Processing
integration, Media integration and V1 integration fragments; CI retains XML, JSON and `gate.json`.
PR #328 adds readable JUnit and coverage summaries without changing these gates.
