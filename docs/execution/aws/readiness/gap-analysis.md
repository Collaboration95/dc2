# AWS readiness synthesis — 15 October 2026

Decision: retain the two existing business services and their working boundaries;
implement small AWS adapters and operator controls. This is analysis/backlog work,
not implementation or cloud validation. Application source inspected at
`af0b21e3c10d6ad62a77549756787eac738e83b5` on Main; `485edac` was the pre-planning
implementation baseline. The handoff itself was introduced at `af0b21e`.
[Provenance](provenance.json) records initial clean status and input hashes.

Four independent standard-tier/high Sol research tasks wrote [A](lanes/a-storage.md),
[B](lanes/b-placement.md), [C](lanes/c-lifecycle.md), [D](lanes/d-delivery.md).
Their tables contain exact code/symbol references, source versus document versus
inference labels, future acceptance, risks and cost effects. They are discovery
reports, not the final audit; [task ledger](task-ledger.json) retains their IDs.
Original proposal was read through ZIP/XML paragraph and table extraction, without
changing or reformatting it. Its sections, rather than differing XML paragraph
numbering conventions between lanes, are the contract references.

## Consolidated retain/change matrix

Every row links to finding IDs in the lane reports. Missing cloud behavior is a
future check or spike; it is never an invented current defect.

| Component / evidence | Disposition and smallest necessary outcome | Backlog owner / acceptance boundary |
|---|---|---|
| Service images/package roots; B-01, D-05 | Retain separate Media/Processing Dockerfiles, nonroot commands, locked SDK/engine. Configure amd64 artifact/test/scan/ECR digest binding. Docker config ID is not registry manifest digest. | `aws2-image-delivery`, `aws2-task-definitions`; future exact digest receipts |
| Engine, frontend, Publisher; D-01, AWS-A-07 | Retain FFmpeg/HLS/hash-while-upload, frontend design/assets/editor, relative `/api`, independent API-only Publisher/system trust/private intent jar. | No product rewrite ticket; cloud context/edge checks actual behavior |
| Owned SQL models/roles/migrations; AWS-A-09, B-09, D-08 | Retain two DBs/four roles/default DML grants/private identifiers and owning Alembic chains. Adapt persistent mount/readiness and separate one-off migration invocation. No new extraction/RDS/server. | State/task definitions and per-owner release; actual role refusal/revision checks |
| Media storage constructors; AWS-A-01 | Adapt explicit local-static/ECS mode: existing MinIO IamAwsProvider, no static constructor override, bounded fetch, token refresh and failure-safe diagnostics. | `aws2-media-task-credentials`, Ready offline |
| Writer/cleanup startup; AWS-A-01,A-03 | Adapt current static-key guards/clients to distinct native worker/cleanup roles. API continues without bucket access. | `aws2-processing-task-credentials`, Ready offline |
| Presigning near credential expiry; AWS-A-02 | Adapt one signing snapshot and effective TTL/returned expiry. Provider wiring alone does not correct advertised 900s lifetime. | `aws2-presign-expiry`, after Media provider; simulated clocks first |
| Source grant/ownership; AWS-A-06, C-L05,L06 | Retain reverse token+owner+revision/immutable descriptor, one bounded renewal, source digest checks, SQL fencing. Worker never gets Media IAM source rights. | No new lifecycle/security platform; future storage/fault negatives |
| Source/output policies; AWS-A-03,A-04,A-05, B-11 | Configure BPA/TLS/S3-managed encryption, scoped native roles, both writing roles' multipart abort, one-day incomplete-MPU eligibility, exact browser-origin output CORS. Source List not added without runtime need. | `aws2-core-definitions`; future actual role checks/multipart receipts |
| Free S3 gateway plus image pulls; B-11 | Configure route/endpoint policy to allow Media-signed worker source GET and ECR regional starport layer bucket; no output blanket sourceVpce deny breaking browser signed GET. | Core definitions; future image pull/internal/external flows |
| CloudFront-to-S3 HLS redirect; AWS-A-05, D-03 | Untested check: real browser decode/Range/redirect/CORS. If redirect produces null Origin, record focused failure/spike; never whitelist wildcard/null or invent required frontend refactor before evidence. | Cloud context/workflow; escalate smallest proven delivery fix |
| Network/state topology; B-02,B-06,B-09,B-15 | Configure dedicated parameterized CloudFormation, one public subnet/AZ, t3a.small Standard only PG/Redis/nginx, encrypted16+8-GiB EBS. Reuse old source only as reference; no imported legacy app/minio/certbot deployment. | Core definitions, state bootstrap, task definitions; offline resource assertions |
| Task sizes/placement; B-02, C-L07 | Configure Media1024/2048 shared API+essential reconciler, API512/1024, recovery256/512, worker2048/4096. No automatic application health/ordering from Compose. | Task definitions; actual memory/CPU/quota evidence remains future |
| Readiness/DNS replacement; B-03,B-04, C-L07 | Adapt operator TCP/schema/Redis/auth-peer readiness beyond liveness. nginx VPC resolver/private FQDN+TTL; prove replacement reconnection rather than speculative HTTP client refactor. | Task/edge/lifecycle/release; do not couple Media liveness to Processing |
| Dynamic public edge; B-07,B-08,B-12 | Adapt separate AWS nginx/CloudFront methods/cookies/query/headers, `/api` + `/api/*` TTL0/error TTL0, no authenticated cache/SPA error conversion, origin prefix-list+secret, external HTTPS URLs. Explicit buffering/streaming budget. | Edge definitions after origin decision; real owner/cache/CORS negatives |
| Origin HTTPS contract; B-14, D-13 | Blocked spike: CloudFront viewer TLS does not encrypt HTTP origin. Written requirement-owner acceptance or narrowly costed approved correction needed. No self-signed/EC2-DNS cert assumption or silent paid topology. | `aws2-origin-transport`, externally Blocked |
| Missing project inputs; AWS-A-11, C-L12, D-13 | Blocked prerequisite: named account/access/region/currency/spend/windows/export/deletion owner, single control station and quota/serialized overlap. | `aws2-account-authorization`; does not block offline code/definitions |
| Redis/RQ and burst execution; C-L01,L04,L05 | Retain durable SQL→transport publication/repair, RQ and per-attempt fencing. Burst exits after observed empty transport, not all SQL work complete; late job awaits another manual batch. | No queue replacement/controller; bounded worker adapter |
| Worker start cap and ambiguity; C-L02 | Adapt single-station serialized manual starts, private durable token/reservation/ARN journal, pagination/nonterminal+unresolved cap≤3. All launch paths use same station; cross-station starts fail until quiescent handover. | `aws2-manual-worker-batches`, Ready offline; no mandatory DB launch table |
| Infinite RQ connection retries / warm stop; C-L03,L08 | Adapt cloud-only finite task wrapper/watchdog and pre-StopTask warm drain, correlated RQ identity, one warm command/last claims/task STOPPED. Redis loss/operator loss must not leave unbounded charged task. StopTimeout≤120s is only final grace, not 300s drain. | `aws2-worker-lifetime-drain`; local defaults/900s attempt deadline preserved |
| Interrupted job semantics/cleanup; C-L06,L07, AWS-A-08 | Retain failed/abandoned state, owner stored-source retry, repeated fenced late-write cleanup while online. Recovery separate; no automatic attempt retry or off-hours≤300s claim. | Small capacity/recovery proof; 38/39 rejections intact |
| Independent releases; D-06,D-07,D-08, C-L09 | Adapt Processing exact-candidate/prior journal/migration/drain/smoke with zero-worker baseline; then small Media owner selection reusing helpers. Actual additive/prior-image compatibility, not filename assertion. | Separate Processing/Media release issues; future both-peer unchanged receipts |
| Cloud clients/evidence; D-02,D-03,D-04,D-09 | Adapt explicit cloud context/system trust/strict regional S3 host downloader without API cookies; no local configure/30-file E2E. Allowlisted records/files, sentinel redaction before persistence/archive. | `aws2-cloud-smoke-context`, Ready offline; no raw CLI/HAR/task-env/DB dumps |
| Existing scan coverage; D-10 | Configure integrated isolated service DAST target/triggers and truthful Sonar executed/skipped/error state, retain hard tests/image gates and documented report-only ZAP. No cloud sweep/security rewrite. | `aws2-scan-disposition`, Ready local workflow; missing analysis stays disclosed |
| Quiescent state/export; B-09,B-10, AWS-A-10 | Adapt mount guard plus bounded Redis maxmemory/noeviction/AOF/log headroom. Export both DBs/roles only after all writers quiesce; private manifest/latest two sets/isolated restore if backup claimed. | State/bootstrap and export hook; no snapshots/PITR/backup daemon |
| Wake/close/no orphan billing; B-13, C-L10, D-12 | Adapt all launch/intake interlock, drain/recovery before stores stop, all service/deployment/standalone tasks STOPPED, generator terminated/volume deleted, EC2stopped/publicIPreleased/noEIP. Wake new DNS→CloudFront ETag/deployed readiness. | Environment lifecycle plus actual close/wake/close receipts; stop≠delete |
| Tiny cloud fixtures/latency; D-11, B-02, C-L10 | Configure six long submissions only after1/2/3 fixed-worker prewarming, short workflow fixtures, one separate status50/180s and login20 cycle on priced ephemeral generator. Capacity≠full throughput; failures remain failures. | Workflow→capacity/recovery + latency→release evidence→closeout |
| DNS/billing quantities; B-05, D-12 | Retain private DNS zone singleOctober charge; distinguish free private-zone DNS lookup from priced Cloud Map API/registration. Count image pulling/minimums/drain/migrations/IP/playback/MPUs and delayed bill lines. | Cost closeout; forecasts and original captured rates remain assumptions |
| Starter/Spot/ARM/consolidation/backups; B-16, C-L11, D-14 | Optional separate lane; no required dependency, resident scheduler, default recovery RunTask privilege, launch table, Spot savings or new backups. | `aws2-optional-unattended`, Backlog/optional |

## Cross-lane decisions and narrowly justified clarifications

1. A suggested one credential ticket; the coordinator split Media and Processing
   for owning-package reviews, with a separate presign-expiry change. Existing SDK
   remains; `uv.lock` pins MinIO7.2.20. No boto3 replacement or shared settings import.
2. C recommends private single-station manual journaling rather than mandatory
   Processing launch reservations. Accept that bounded default: every manual/CI/
   smoke/release launch path shares one serialized station. Multi-station use is
   explicitly a stop/optional-coordination boundary, never a hidden guarantee.
3. B/C identified diagrams/tables implying mandatory recovery RunTask/reservations.
   The current architecture text was clarified to mark those optional and use an
   operator journal by default. Recovery gets only cleanup rights by default.
   This is a docs clarification with zero new cost/resource/component.
4. A observed no runtime source ListBucket/GetBucketLocation call with explicit
   region; least-privilege AWS definitions omit unused rights, retaining all actual
   source operations and multipart abort. Source-owner invariants remain unchanged.
5. B raises nginx buffering intent versus current streaming config. Do not invent
   an upload rewrite: edge issue must select/document either bounded path and prove
   contract/scratch behavior. Larger disks/host require pressure evidence and approval.
6. D identified Media release missing beyond UC-7 Processing proof. Use separate
   small Media owner operation built from Processing primitives, not a framework.
7. B/D differ on the recommended first ticket (definitions/cloud context); choose
   Media native task credentials because it removes an observed runtime/signing
   blocker and has a complete no-account mock verification path. Seven local issues
   can proceed independently; there is one recommended next issue, not seven gates.
8. Preserve accepted plan's cloud status/login gates with one dedicated bounded
   timed evidence issue. No repeated three-replicate/full cloud scaling campaign.
   All six 21-MB uploads happen in capacity batches after prewarming; short workflow
   fixtures may prove multipart early, while the required21-MB receipt belongs to
   capacity. This avoids spending/invalidating the capacity sample in prerequisite
   workflow checks. No source reupload on retry.
9. CloudFormation is the coordinator's minimal parameterized IaC choice, permitting
   offline schema/policy checks without Terraform state or provisioning. Existing
   local scripts/Compose remain intact; tasks/roles/output contracts stay explicit.

## Readiness, dependencies and deadlines

[Backlog](backlog.json) contains four outcome epics and 24 children:21 required
implementation/evidence changes, one account prerequisite, one transport spike,
and one optional lane. Seven issues are Ready for offline/local adapter/definition
work; dependency-bearing local work is Backlog, and five live evidence issues plus
the two external prerequisites are Blocked. Epic existence and audit PASS never
mean cloud architecture implemented. No implementation issue is closed here.

Critical flow: credentials/definitions/image delivery/cloud context/manual starts
in parallel → presign, state/task/edge configuration and lifetime/drain → owner
release/lifecycle → quiescent exports and authorized workflow → six-job capacity/
recovery plus one serial latency cycle → both-owner release proof → closeout.
Origin/account decisions run in parallel, blocking their actual dependent steps.
Optional unattended/Spot/ARM/etc have no required blocking edge.

Maximum 14 elapsed days is anchored to 15 October 2026 (no later than the corresponding
29 October checkpoint, not a new two-week clock if implementation starts later).
Presentation 26 October is the nearer preparation milestone. No new schedule was
promised without actual booked windows. Targets are 20 core / 2 worker-task hours,
with 40 / 8 larger case; include startup, pull, propagation, drain, retry/overlap.

## Checks performed, versus future proof

Coordinator read current code/proposal and authenticated `gh` state: 30 historical
issues closed, 30 Project14 items Done/Done, no open PR. Active Collaboration95
account supports repository/Project access; unrelated inactive login is invalid
and was not used. Source CI was still running at preflight, not claimed passed.
Four lanes used bounded source/SDK/mock/AST/cost checks as recorded individually.
No product tests/containers/live workloads/cloud accounts were operated.

Offline calculator reproduced expected $6.03 usage/$13.03 with reserves, larger
$13.27/$28.27 and continuous sensitivity $67.62/$82.62. Retained baseline
$1.727567 includes 24 GiB EBS, private zone and assumed S3/ECR/log storage across 14 days;
it is already in totals. Core $0.151435/hour; worker $0.12824/task-hour incl. IPv4.
Captured official price evidence is preserved, not a new account/rate or tax
calculation. Working $15/$30 targets are not bill caps/spend approval.

New readiness validation checks stable keys, acyclic/topological dependencies,
parent coverage, only dependency-free Ready work, optional isolation, body fields
and fresh native GitHub relationships/Project state. Actual AWS IAM, multipart,
CORS/decode, quotas, memory/disk, lifetime/drain, deployment/rollback, restore,
latency, zero-compute and bill reconciliation all remain **future**.

Official sources used to verify provider/edge/gateway assumptions include
[AWS task roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html),
[CloudFront origin settings](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesOrigin.html)
and [S3 gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html).
They describe AWS semantics; they do not prove this repository's deployment.

## Independent audit outcome

The fresh standard-tier/high Sol auditor returned PASS for backlog readiness; deployment remains blocked. It independently checked all 28 remote keys, 24 native parent links, 42 blocking edges and preserved historical 30 Done items. Minor AUD-L01 supplemental diagram wording was corrected during publication. No product/cloud implementation is certified. See [audit report](audit-sol.md). The subsequent user goal authorizes local preparation and grouped implementation, with AWS deployment excluded.
