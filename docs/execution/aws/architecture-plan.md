# V1 delivery, then optional V2 migrations

Accepted direction: 15 October 2026. This is the authoritative target plan.
See [the V1 backlog and handoff](v1/README.md) for execution order. The
[previous AWS2 plan](architecture-plan-aws2-prep-20261015.md),
[readiness packet](readiness/README.md) and [preparation receipts](prep/README.md)
remain historical evidence, not descriptions of implemented V1 behavior.

## Decision and current implementation

Deliver a complete V1 before choosing more aggressive migrations. Make the two
domain boundaries apparent in the gateway, deployments, data ownership and demo.
API Gateway is required. Remove Redis/RQ from the target V1 runtime. Use Lambda
for domain APIs and bounded control handlers; retain one Fargate encoding backend
and the existing media engine.

The reviewed baseline at `8d13194` still uses container APIs, Redis/RQ, HTTP peer
and source-grant calls, and inert EC2/nginx state-host definitions. This planning
merge does **not** implement or deploy Lambda APIs, SQS, direct intake or Aurora.
Historical preparation tests are not acceptance evidence for those migrations.

The user authorizes plan/backlog publication, commits, push and merge into Main
after one practical audit and required checks. Earlier instructions to leave
umbrella PR70 draft are superseded for this publication. This task does not
authorize AWS account operations, provisioning, deployment, spending or Alibaba
operations. Genuine cloud evidence remains open and Blocked until obtained.

## V1 architecture

| Boundary | Decision |
|---|---|
| Public entry | Generated CloudFront HTTPS URL serves the preserved frontend; `/api` forwards to API Gateway HTTP API with explicit `/media/*` and `/processing/*` groups and separate Lambda API applications |
| Media Management | Own users, login/roles, assets, reservations, source grants, ownership and playback; its own API, result/reconciliation handlers, roles and release |
| Processing | Own jobs, attempts, retry, cancellation, leases and output descriptors; its own API, command/recovery handlers, worker image, roles and release |
| Databases | One Aurora PostgreSQL Serverless v2 cluster per service (AD-29; V1 began with one shared cluster), two databases, distinct runtime/migration credentials and histories; no cross-database service queries. Each cluster is its own capacity/failure boundary |
| Messaging | Three SQS Standard queues: `processing-commands`, `processing-work`, `media-results`, each with a matching DLQ. SQL remains authoritative for jobs, leases, inboxes and outboxes |
| Encoding | Reuse FFmpeg/probe/edit/MP4/HLS on disposable Fargate workers, initial 2 vCPU / 4 GiB each, one active encode per worker, zero idle tasks, total cap three including unresolved launch reservations |
| Starts | V1 uses bounded operator batches adapted from the existing journal/RunTask design. Late work stays visibly queued until another batch. Unattended starts are V2, not a claimed V1 capability |
| Bytes | Private source/output S3 plus a private frontend bucket. Browser and Publisher reserve an owned upload, upload directly to S3 and finalize. No 100-MiB video body through API Gateway/Lambda |
| Operations | Per-owner tests/scans, migrations, smoke, rollback, booked-session open/close and safe evidence receipts. Preserve the frontend design, engine, Publisher independence, course documents and frozen measurements |

These are two business services. Workers, queues, gateway, authorizer and recovery
handlers are execution/infrastructure roles. Do not add separate Identity,
Upload, Delivery, Scheduler or Transcoder services, or one application per CRUD
endpoint. Keep a coherent per-domain release. Package the API applications as independently
versioned Lambda container images in ECR; retain one Processing-owned Fargate
worker image/entrypoint and immutable artifact identities. Lambda APIs initially
use 2 GiB per invocation; smaller authorizer/control profiles are measured choices,
not promises of sufficient capacity.

Canonical external and Gateway paths are `/api/media/*` and `/api/processing/*`;
each adapter strips only its own prefix once. The shorter route labels in diagrams
name the same two groups. Login/register exemptions, cookie scope across both
groups and payload-v2 authorizer context are frozen by the first contract issue.

## Contract and security rules

- Preserve cookie/JWT and bcrypt behavior. A Media-owned Gateway authorizer
  validates identity/current role and supplies trusted owner context to both API
  integrations; it is not a third business service. Processing receives context,
  never Media database credentials. Ignore public owner/role headers and deny
  untrusted direct Lambda invocation. No OIDC, new identity provider or broker.
- Each API checks its own records against that identity. Public Processing routes
  inspect/retry/cancel existing owned jobs. Creation from a raw source descriptor
  is accepted only from the trusted Media command path, not arbitrary client S3
  keys or URLs. Freeze concrete actor/route/message schemas in the first issue.
- Media reserves a server-generated owner-scoped object key, enforces the 100-MiB
  limit/content rules, and validates actual S3 bytes/checksum before adopting a
  revision. Finalization/replay are idempotent. Reject wrong-owner, absent,
  changed, oversized and late objects; retain uncertain-write/orphan cleanup.
- Queue only versioned command/event IDs, owner/asset/job/attempt IDs, monotonic
  state version and immutable source key/revision/digest. No media bytes, secrets
  or expiring signed URLs. Workers get scoped project-source GET instead of a
  live Media source-grant callback. This broadens today's signed-only capability;
  it grants no Media DB access, source writes/deletes or unrelated bucket access.
- Restrict command producers to Media, work producers to Processing dispatch and
  result producers to Processing's completion path. Public API roles cannot inject
  raw-source work. Consumers validate owner/asset/source revision against their
  durable accepted command/job before using the worker's broader GET role. Reject
  forged or mismatched descriptors even when the referenced key exists. Pin an
  immutable verified source revision so a replayed upload grant cannot replace
  accepted bytes. Cover these rules with policy and cross-owner negative tests.
- Commit owned state and its outbox together; publish after commit. Commit inbox
  dedupe/state before deleting a message. Duplicate/reordered delivery and lost
  send/delete responses are expected. Preserve leases, version/attempt fencing,
  cancel-before-submit tombstones and stale-completion rejection. SQL/SQS dual
  writes still require repair.
- Commands go only to Processing control, work only to encoders, results only to
  Media projection handlers. Replace synchronous peer dispatch/status projection
  and reverse worker-to-Media source calls in the V1 critical path.
- Use 20-second long polls, seven-day source queues and fourteen-day DLQs; renew
  work visibility while the SQL lease is valid. Owner repair replays SQL state
  after retention gaps. Use bounded recovery Lambda invocations, ECS terminal
  events and late-output notifications, with a session-scoped repair tick for
  stranded outboxes/cleanup. Disable the tick on close. Events alone do not make
  the SQL/SQS handoff atomic.
- Add native Lambda storage credentials: current providers intentionally accept
  only ECS container credentials. Retain native ECS credentials on workers and
  explicit local credentials for emulators. No metadata/profile fallback into
  another account, secrets in Git/images, or secret-bearing evidence/logs.

## Managed placement, session behavior and HTTPS

CloudFront reads static objects through S3 OAC and sends API traffic to the
AWS-generated API Gateway **HTTPS** origin. Gateway invokes the domain Lambdas.
There is no CloudFront-to-public-EC2 HTTP origin in V1. This resolves the owner
architecture decision in #46. Actual TLS/cookie/CORS/client traces still require
#63/#66; the decision is not runtime evidence.

Use the AWS-generated `*.cloudfront.net` and `*.execute-api.<region>.amazonaws.com`
hostnames and regional S3 HTTPS endpoints. AWS manages their public certificates;
no purchased domain or custom public certificate is required. Browser/Publisher
must use normal trust validation. Database TLS uses the RDS trust chain below.

Use a supported Aurora PostgreSQL Serverless v2 version, minimum zero ACUs,
initial maximum two ACUs and five-minute pause. Settings are starting points,
not measured sufficient capacity or a billing cap. Use invocation-scoped SQL
connections/NullPool or explicit disposal; persistent pools or RDS Proxy can
prevent pause. Verify database TLS with the RDS trust chain and retain owner-only
migrations. Image rollback never automatically undoes destructive migrations.

Private Lambda/DB subnets span two AZs. The low-cost network candidate uses
dual-stack Lambda with IPv6 egress-only routing to SQS/SSM/ECS APIs and a free S3
gateway route. Fargate worker/migration/generator tasks use public IPv4 only while
running and private DB access through narrow groups. No NAT, paid endpoints, ALB,
application EC2, nginx or managed Redis is selected. Public Singapore SQS/SSM/
Batch IPv6 DNS was verified during consultation; actual VPC routing and required
SDK endpoint support remain unverified. Batch is not a V1 dependency. RDS Data API
is an alternative future adapter, not a required SQLAlchemy rewrite.

V1 is a **booked-session demo**, not unattended 24/7 operation. Open restores
bounded Lambda concurrency, queue mappings and repair scheduling, waits for
application/DB readiness and permits worker batches. Close quiesces intake,
drains/stops workers, captures terminal SQL outcomes, disables mappings/schedules
and sets the Gateway stage throttle to zero. (As built, no Lambda reserved concurrency is used: the
account limit of 10 forbids it, so the closed state is disabled mappings and rules plus the zero
throttle; see `deploy/aws/v1/README.md`.) Verify Aurora
reaches zero ACUs after connections close; maintenance can wake it. Retained
storage and frontend/CDN/API requests may still bill. Document offline/warm-up
states and bounded client retries. Timed warm tests keep their existing observers
and thresholds, without hidden retries or exclusion of failures.

## V1 exit criteria

- Browser and independent Publisher exercise authorized upload, status, encode,
  edit, stored-source retry, playback and deletion. Publisher has no service
  imports or DB credentials; frontend design is preserved.
- Two visible route groups, separate contracts/versions/roles/logs and independent
  releases. Promote Processing with Media artifacts/schema/version unchanged,
  then exercise failed-candidate rollback.
- Refuse forged identity, cross-owner and cross-database access. V1 API/worker
  artifacts and default V1 local/cloud runtime have no Redis/RQ dependency.
  Frozen legacy regression tests may retain an explicitly isolated Redis fixture;
  it is not a V1 runtime or new V1 evidence.
- Prove duplicate/reorder/lost-response handling, interruption, stale writes,
  cancellation, finite drain and close/wake with durable ownership intact.
  During an open session, preserve the original recovery gates: lost committed queue work is re-enqueued
  within 120 seconds; interrupted work is requeued or marked failed within 300
  seconds. A later encode may still need another explicit operator batch.
- Obtain controlled 1/2/3-worker capacity/recovery, independent releases, warm
  status/login, actual cost and resource-close receipts. Keep the six-long-upload
  cloud envelope and full historical local measurements distinct. A small cloud
  smoke does not certify full throughput/SLA targets.

Local implementation closes only after merged code and specified local checks.
#45 and live acceptance #63–#67 remain open **Blocked** until authentic evidence.
#46 is an owner/document decision and closes after this decision merges into Main;
it does not certify runtime TLS. Four V1 epics stay open until required evidence.
Tag `project2-v1` only after the required V1 checks and live acceptance pass. V1
must be independently suitable for submission even if no V2 work happens.

## Time, budget and optional V2

Target an integrated local V1 in 48 continuous agent hours; plan three elapsed
implementation days, five maximum. Two real calendar weeks include cloud proof,
fixes, documentation and rehearsal. Implementation T0 starts with implementation;
planning does not restart the inherited 15–29 October window or 26 October
presentation anchor.

The planning ceiling is approximately **$200**. The [V1 worksheet](v1/cost-model.json)
uses USD explicitly; actual project account, billing currency, scope and live
permission remain #45 prerequisites. Previous $15/$30 AWS2 targets are historical.
No free tier or credits are assumed. Price charged DB-awake time, idle polling,
image pulls, retries, migrations, generator, storage and egress. Forecasts are not
bills or automatic caps. Later authorized cloud runs retain daily spend receipts.

After accepted V1, choose **one** V2 experiment at a time on a branch from its tag:
bounded short encoding on Lambda; independently scaled database clusters; or
unattended starts/further cost cuts (#68). Keep a combined executor cap if mixing
backends later: three Lambda plus three Fargate encodes is not the three-worker
limit. Batch, Data API, DSQL/DynamoDB, ARM/Spot, broad autoscaling and extra business
services are not V1 work. No V1 issue depends on V2. Revert failed experiments to
V1 when correctness, latency, cost or operational effort does not improve. V2 is
optional when time or money is exhausted.

Future implementation bundles contain at least four issues per agent; one
coordinator owns shared contracts/integration. This publication uses one practical
backlog audit and fixes substantive defects without cosmetic review loops.
