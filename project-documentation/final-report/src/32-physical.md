## Physical Architecture & Design

The platform runs in one AWS account, in region **ap-southeast-1 (Singapore)**. One CloudFormation
stack, rendered by `scripts/aws/v1/definitions.py` and checked in as `deploy/aws/v1/template.json`,
defines all of it. The checked-in template is tested to be identical to the rendered output.

Two operating modes used the same template:

- **V1 (10–18 October, tag `project2-v1`).** One stack per proof run (`r1017b`, `r1018b`, `r1019a`).
  Each stack was closed outside booked sessions and deleted afterwards.
- **V2-live (18 October to the end of the course).** One persistent stack, `dc2-live`. It is always
  open, bounded by a throttle and a cost budget, and updated in place by CD after every green CI run
  on `Main`. It scales to zero when idle (AD-27).

Figure {@fig:topology} shows the persistent topology. The network rules and data paths are listed after the component table.

![Figure {#fig:topology}. Persistent V2-live AWS topology (ap-southeast-1): public edge, VPC-attached Lambdas, finite Fargate encoders, Aurora, S3 and SQS.](figures/aws-topology.png){width=15.5cm}


| Component | Deployed as | Placement and sizing |
|:---------------|:----------------------------------|:----------------------------------------------------|
| Web app | Static files in a private S3 bucket behind CloudFront (origin access control) | Global edge, HTTPS only (HTTP redirects); content-hashed assets |
| Public API | One API Gateway HTTP API: `/api/media/*`, `/api/processing/*`, one REQUEST authorizer | Regional; V2-live stage throttle 20 requests/s, burst 50 |
| Media | One container image → 4 Lambda functions (`MediaApi` 2048 MB, `MediaAuthorizer`, `MediaResults`, `MediaRepair`), each with a `live` alias | Private subnets in two AZs, VPC-attached |
| Processing | One container image → 6 Lambda functions in V2-live (`ProcessingApi`, `ProcessingCommands`, `ProcessingRepair`, `ProcessingEcsEvents`, `ProcessingS3Events`, `ProcessingLauncher`) | Private subnets in two AZs |
| Encoder | Worker container image as an ECS Fargate task definition; no ECS service | 2 vCPU, 4 GiB; 0 when idle, at most 3; public subnet with a temporary public IPv4 while running |
| Databases | Aurora PostgreSQL 16 Serverless v2: one cluster, one instance, `media_db` and `processing_db` | Private subnets; 0–2 ACU, auto-pause when idle; encrypted; `rds.force_ssl=1` |
| Object storage | Three S3 buckets: source, output, frontend | Versioned, SSE-S3, public access blocked, TLS-only policies |
| Messaging | Three Standard SQS queues and three DLQs | SQS-managed encryption, TLS-only, role-scoped resource policies |
| Scheduling | EventBridge: one-minute Media and Processing repair ticks, ECS task `STOPPED`, S3 `Object Created` | Regional |
| Configuration | SSM Parameter Store SecureStrings (four role DSNs, JWT secret); RDS-managed master secret | Each handler role reads only its own domain's parameters |
| Images | Three ECR repositories (media, processing, worker) | Immutable tags, scan on push; releases address images by digest |
| Observability | CloudWatch log groups (7 days); 13 alarms (one per queue DLQ, one per function); `ServicesDashboard`; AWS Budget USD 20/month at 50/80/100 % | Per service |

**Network.**

- One VPC (`10.62.0.0/16` plus an Amazon IPv6 block) spans two Availability Zones, with one
  private and one public subnet in each.
- Private subnets have an IPv6 route through an egress-only internet gateway, **no IPv4 default
  route and no NAT gateway**. Lambdas reach SQS, SSM and ECS through dual-stack endpoints.
- One S3 gateway endpoint, attached to all route tables, is restricted to the source and output
  buckets.
- No security group has an inbound rule except the database's, which admits only the Lambda,
  worker and migration groups on port 5432.
- An external scan of the public surface found only ports 80 and 443 open, and 80 redirects to
  HTTPS **[AWS]**.

### Key Architectural Decisions

These decisions are reflected in the physical view. Section 3.1.1 holds the logical ones.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-10 | **Lambda container images, one image per domain**; `ImageConfig.Command` picks the handler; every function has a `live` alias | Scale-to-zero compute with a per-domain release unit; FastAPI code runs unchanged behind an adapter. Trade-offs: cold starts, no pooled connections (per-invocation `NullPool`, so a paused database can stay paused), a 29 s Gateway timeout. | New (changes AD-07) |
| AD-12 | **Aurora Serverless v2**: one cluster, one instance, two logical databases, separate roles; 0–2 ACU with auto-pause | Near-zero idle cost and real role separation. Trade-off: one shared capacity and failure boundary; no replica failover; a request to either domain resumes the cluster (first read after a pause: 4.7 s **[AWS]**). | New (refines AD-02) |
| AD-13 | **Finite Fargate encoders**: one task per attempt, a hard cap of 3, zero when idle | FFmpeg needs minutes of CPU, and nothing should run idle. Each task claims at most one attempt and exits after two empty polls. Alternatives rejected: an always-on ECS service with autoscaling (idle cost) and AWS Batch (another dependency). Trade-off: at most three concurrent encodes; Fargate start time adds to queue wait. | New |
| AD-15 | **CloudFront as the single public entry** for frontend and `/api/*` | Managed HTTPS without buying a domain; one origin for cookies. Trade-off: AWS-generated hostnames; the `execute-api` endpoint is also reachable directly (AISS-03). | New |
| AD-16 | **Per-owner release and rollback by image digest and Lambda alias** | Releases Processing without touching Media (UC-7). Each release builds and scans the owner's image, publishes versions, moves `live` aliases, runs a smoke test, and restores the previous versions on failure. Trade-off: rollback is image-only, and schema changes must be additive. | New |
| AD-17 | **GitHub Actions CD over OIDC**: role `dc2-github-deploy`, assumed only from the `aws` environment, with no stored AWS key | Recorded, repeatable delivery. Trade-off: the role is broad (`AdministratorAccess` with a region lock), protected by the environment's branch policy (AISS-05). | New |
| AD-18 | **Private Lambda subnets with IPv6 egress only, an S3 gateway endpoint and no NAT** | Avoids NAT and interface-endpoint hourly charges, the largest idle cost in a typical VPC design. Trade-off: every AWS dependency must be reachable over IPv6 or the gateway endpoint; Fargate tasks run in public subnets to pull images. | New |
| AD-20 | **Least-privilege IAM per handler**, native role credentials, queue resource policies | Producer and consumer authority is enforced by AWS, not by the message schema. `ProcessingApi` has no S3 or SQS access; `MediaApi` has no SQS access; the worker can read sources, write outputs and receive work, nothing else. Trade-off: the worker's source read is bucket-wide, so owner binding is checked in code before any read. | New (supersedes AD-06) |
| AD-23 | **One CloudFormation stack, applied in two phases** (infrastructure, then applications pinned by digest) | The smallest operational surface for three people. Trade-off: infrastructure for both domains changes together; only code releases are independent. | New |
| AD-25 | **Per-service alarms and one services dashboard** | Failures are attributable to one service: one DLQ alarm per queue and one error alarm per function, tagged by owner. Trade-off: alarms are state to read, with no paging target. | New |
| AD-27 | **One persistent, always-on environment, updated in place, scaling to zero** | Per-run stacks cost a 25-minute deploy and a 25–40-minute teardown for every check. The stack already costs about USD 3–5 a month idle, so it now stays up, bounded by the throttle, the encoder cap and a USD 20 budget. Encoders start automatically from the SQL backlog. Trade-off: the environment is public all the time, and old and new code run side by side for a moment during a release. | New (supersedes AD-19 booked sessions) |

### Technology and Services

| Technology or service | Used for | Rationale | Trade-off accepted |
|:----------------|:---------------------|:-----------------------------------------|:-----------------------------------------|
| Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 (async), Alembic | Both services, the worker and the tooling | Continuity with the inherited code; typed validation at every boundary; one migration history per database | One lockfile for the repository; owner extras keep each image to its own packages (40/36/33 exported packages) |
| FFmpeg and ffprobe | Probing, MP4 encoding, HLS ladder (360/480/720, capped at the source height) | Industry standard and already proven in Project 1 | CPU-bound; HLS is best effort; a large unfixed-CVE surface in the worker image (section 4.3) |
| Plain JavaScript SPA, hls.js, Plyr | Web client | No build step; browsers load `app.js` directly; Vitest tests it | No production bundling or minification |
| Python stdlib plus `httpx` | Publisher CLI | Proves reuse with the smallest dependency set: 491 lines in 6 files | Polling-based status; one cookie jar per process |
| AWS Lambda (container images) | APIs, consumers, repair, launcher | Pay per request, scale to zero, per-domain image release | Cold starts; account concurrency limit of 10 observed |
| Amazon API Gateway HTTP API | Routing, authorizer hook, throttle | Cheapest managed HTTP front for Lambda; REQUEST authorizer | No WAF; one stage-level limit |
| Amazon CloudFront | HTTPS entry, static site, `/api/*` pass-through | Managed TLS, HTTP/2 and HTTP/3, no custom domain needed | Playback bytes come from S3 directly, not through CloudFront |
| Amazon SQS (Standard) with DLQs | Commands, work and results | Serverless, durable, cheap; redrive policy (5 receives) | Unordered and at least once, hence inbox dedupe and version fences |
| Amazon Aurora PostgreSQL Serverless v2 | Two owned relational databases | Transactions, constraints and `SKIP LOCKED` for outbox claims; scales to 0 ACU | Single instance; cold resume of several seconds |
| Amazon S3 (versioned) | Sources, outputs, frontend | Presigned POST/GET keep bytes off the API; versioning makes the pinned source immutable | Cleanup must delete every version |
| Amazon ECS on Fargate | Finite encoders, migrations, bootstrap task | No hosts to manage; per-task CPU caps make capacity predictable | Task start median 25.6 s **[AWS]**, which dominates queue wait |
| Amazon EventBridge | Repair ticks, ECS and S3 event hints | Rebuild lost work and react to stopped tasks without polling clients | One-minute granularity |
| AWS IAM, SSM Parameter Store, Secrets Manager | Per-handler roles, DSNs and JWT secret, Aurora master secret | Secrets stay out of code, images and the template | SSM read at cold start |
| Amazon ECR | Three image repositories | Immutable tags and digests are the release identity | Scan on push complements the CI and CD Trivy scans |
| Amazon CloudWatch, AWS Budgets | Logs, alarms, dashboard, cost alerts | Per-service observability at near-zero cost | 7-day log retention; no paging |
| GitHub Actions, OIDC, Pages | CI, CD, study-guide publication | Integrated with pull requests; no long-lived cloud keys | Hosted runner limits shape the CI lanes |

**Runtime and development tools are separate.**

- Runtime images contain only the owning service's code and its runtime extras. `deploy/v1/check_runtime.py`
  verifies this.
- Development tools run only in CI and on developer machines: pytest, Ruff, Vitest, Playwright,
  Moto, cfn-lint, actionlint, Trivy, gitleaks and ZAP.
