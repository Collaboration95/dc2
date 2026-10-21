# Quality Attributes

Each attribute below gives the design tactics first, then the evidence against the proposal's
targets (proposal §3.4, unchanged). Results keep their environment, source, workload and timing
boundary. Local results never stand in for AWS results, and misses stay misses. The complete record
is in `docs/results/actual-vs-target.md` (with its CSV) and `docs/evidence-index.md`.

![Figure {#fig:results}. Speedup and Processing release time against target (AWS V1 and V2-live; misses shown as misses).](figures/actual-vs-target.png){width=15.5cm}

| Attribute | Scenario (proposal target) | Result | Verdict |
|:----------|:------------------------------------|:------------------------------------------|:---------|
| Scalability | 2 workers ≥ 1.6× and 3 workers ≥ 2.1× the jobs/min of 1 worker | AWS V1 (6 clips, one run per cap): 0.483 / 0.700 / 1.134 jobs/min → **1.449×** and **2.347×** | **FAIL** at 2; PASS at 3 |
| Scalability | Median queue wait falls at each step; 0 failed jobs | 274.3 s → 135.7 s → 9.6 s; 0 failed; 0 encoders left running | PASS |
| Scalability | (same, local pre-V1 design, 30 clips × 3 repeats) | 2.032× and 2.885× | PASS (different design; not AWS) |
| Scalability | V2-live automatic scale 0 → 3 → 0 | 0 → 3 → 0 with 3 concurrent clips; 9-clip backlog at cap 3 in 239 s (2.26 jobs/min) | PASS (no 1/2/3 comparison) |
| Performance | 50 users polling status for 3 min: p90 ≤ 700 ms, < 1 % errors | p90 **58.2 ms**, 9,000 requests, 0 errors (in-region generator) | PASS |
| Performance | 20 concurrent logins: p90 < 2 s | p90 **178 ms** (20 samples) | PASS |
| Performance | Warm-job queue wait ≤ 20 s (V2-live) | about **37 s**; Fargate start median 25.6 s | **FAIL** |
| Availability | Worker killed mid-encode: re-queued or failed within 5 min | Stop detected in **5.8 s**; lease expiry marks the job `failed`; retry creates a new attempt | PASS (reaction time only) |
| Availability | Lost queue entry re-enqueued within 2 min | 23.5 s (local pre-V1); ≤ 120 s asserted on a simulated clock (local V1) | PASS locally; **NOT_RUN** on AWS |
| Availability | Processing temporarily unavailable while Media accepts uploads | Command consumer off for 48 s: Media answered 202 and held the command; job `done` 58.9 s after re-enable | PASS (consumer only) |
| Deployability | Release Processing alone, smoke-tested, in ≤ 10 min; Media unchanged | Operator promote 322.5 s; CD `Release` step 10.1–10.3 min (`r1018b`) and 9 m 39 s (`r1019a`); release plus a separate upload smoke 15 m 38 s; Media unchanged at every snapshot | **FAIL** (marginal); not established with the smoke |
| Deployability | Bad candidate restores automatically | CD run 39271754470 (`bad_candidate=true`) → `restored` | PASS (source `7928b7c`) |
| Security | Negative tests 100 % rejected; 0 fixable HIGH/CRITICAL at release | All selected negatives rejected on AWS V1 and on `dc2-live` (#229); 0 fixable HIGH/CRITICAL at each release | PASS (checks run) |
| Reusability | Publisher CLI: 0 service imports, 0 database credentials, ≤ 2 person-days | 0 and 0, enforced by a test; 491 lines; effort not timed | PASS; effort **NOT_MEASURED** |

## Performance

**Tactics in the design.**

- **No bytes through the API.** Uploads go straight to S3 by presigned POST. Playback reads MP4
  (with range requests) and HLS segments straight from S3 by presigned URL. Lambda handles only
  small JSON requests, and there is no payload limit to hit.
- **Caching where it is safe.** CloudFront caches the content-hashed frontend at the edge. API
  responses deliberately use the AWS managed *caching-disabled* policy, and authenticated responses
  carry `Cache-Control: private, no-store`: status and signed URLs are per-owner and short-lived,
  so caching them would leak or go stale. HLS playlists are never cached.
- **Load balancing is managed.** API Gateway and Lambda spread requests across concurrent
  executions. SQS distributes work across up to three encoders, and each encoder pulls one attempt
  at a time.
- **Reads come from a local projection.** Status is answered from Media's own projection in one
  owner-local query (an earlier N+1 lookup was replaced by one outer join). There is no
  cross-service call per poll.
- **Bounded, predictable encoding.** Each encoder is a 2 vCPU / 4 GiB task. FFmpeg uses every core
  it sees, so the per-task cap is what makes the 1/2/3 comparison fair. The HLS ladder never
  exceeds the source height, so no work is wasted upscaling.
- **Connections suited to a pausing database.** Per-invocation sessions (`NullPool`) let Aurora
  pause at 0 ACU. The first read after a pause costs about 4.7 s; later reads take about 263 ms
  **[AWS]**.

**Results and explanation.**

- **Latency.** Status p90 was 58.2 ms against 700 ms, and login p90 was 178 ms against 2 s
  **[AWS]**. The generator was a Fargate task in the same region, so these numbers exclude
  internet latency to end users.
- **Two-worker miss.** The 1.449× result is measured on six clips with one run per cap.
  Fargate task-time variability against a fast single-worker baseline is the most probable cause,
  but no per-task CPU profile was captured, so the cause is an inference. The three-worker result
  (2.347×) passed, and the median queue wait fell at each step.
- **Queue-wait miss.** The V2-live wait of about 37 s is a deliberate trade-off of scale-to-zero:
  no encoder runs idle, so each burst pays a Fargate start (median 25.6 s) plus image pull. The
  target was not revised, and AISS-03 records the options.

## Availability

**Tactics in the design.**

- **Durable state first.** SQL is the source of truth, and the outbox commits every message with
  its state change. A lost queue therefore delays work but cannot lose it: `repair_work` rebuilds
  queued work from `jobs` and `attempts` on the one-minute repair tick. ECS `STOPPED` and S3
  `Object Created` events trigger the same pass early.
- **Failure isolation between services.** Media never calls Processing. While Processing's
  command consumer was off, Media kept accepting uploads (202), and the job completed after
  re-enable **[AWS]**.
- **Fenced, disposable workers.** Leases on the database clock, task binding and a hard deadline
  mean a dead or stuck worker cannot finish late. Its attempt is visibly `abandoned`/`failed`, and
  the owner retries from the stored source. The worker cannot send messages, so a dying worker
  cannot publish a half-finished result.
- **Poison-message containment.** Each queue redrives to a DLQ after five receives. A poison
  message reached the DLQ after 2,101 s and was removed **[AWS]**. A DLQ runbook covers redrive.
- **Managed redundancy where it is free.** Lambda, SQS, S3, API Gateway and CloudFront are
  regional or global managed services spanning multiple AZs. The subnets cover two AZs.
- **Self-healing deploys.** A failed release smoke restores the previous images automatically
  (section 5.3). Stateful resources use `DeletionPolicy: Retain`, and CloudFormation refuses a
  change set that would replace Aurora, a bucket or the distribution.
- **Observability.** Per-service alarms (DLQ depth per queue, errors per function: 13 in V2-live) and one dashboard. 13
  of 13 alarms were `OK` after the backlog tests **[AWS]**.

**Limits, stated plainly.**

- The platform is **not highly available** in the strict sense. One Aurora instance in one region
  is a shared failure boundary (AISS-01, AISS-02).
- Backups are kept one day, and no restore drill was run.
- No uptime SLA is claimed.
- The lost-queue-entry timing was not measured on AWS (AISS-14).

## Security

**Controls in the solution.**

| Area | Control |
|:-----------|:----------------------------------------------------------------------------------|
| Identity and access | Media-owned Lambda authorizer on every route except health, register, login and logout. It verifies the HS256 session JWT and re-reads the current user and role. The Gateway adapter strips caller-supplied `x-owner-id`, `x-role` and cookie headers and builds the actor only from the authorizer context. Owner filters apply in both services, and a foreign ID returns 404. Admin routes need the `operator` role. |
| Session | Host-only, `HttpOnly`, `Secure`, `SameSite=Strict` cookie through CloudFront; 1-hour token; `private, no-store` on authenticated responses |
| Hashing | bcrypt (cost 10) with a password byte limit; SHA-256 over every uploaded source and every output |
| Encryption | TLS everywhere: CloudFront HTTPS only (TLS 1.2+ to the origin), TLS-only S3 and SQS policies, `rds.force_ssl=1` with verified CA. At rest: Aurora storage encryption, SSE-S3, SQS-managed encryption, SecureString parameters. |
| IAM (least privilege) | One role per Lambda, migration task and worker (17 roles at default flags). Queue resource policies deny unlisted producers and consumers. Separate database roles; native role credentials; no static keys anywhere. GitHub reaches AWS only through OIDC. |
| Input validation | Type allow-list and a 100 MiB cap, enforced at four points: the frontend, the grant, the S3 POST policy and the Publisher. Finalize checks size, hash and file signature at a pinned version. Envelope validation rejects secret- or URL-like payloads. HLS file names are allow-listed. |
| Network | No inbound security-group rules except the database's internal rule; no NAT; private subnets for Lambdas and Aurora; only ports 80/443 public (80 redirects) |
| Secrets | SSM SecureStrings scoped per role; RDS-managed master secret; gitleaks secret scanning; receipts sanitized before commit |
| Supply chain and testing | Ruff security lint (flake8-bandit rules); Trivy on all three exact images in CI and again on the deployed builds in CD (zero *fixable* HIGH/CRITICAL gate); ECR scan on push; authenticated OWASP ZAP DAST; dependency audits (npm audit: 0 findings) |
| Intrusion detection and prevention | Not deployed. There is no WAF, GuardDuty or IDS/IPS (AISS-06). The compensating controls are the authorizer, the stage throttle (20 rps, burst 50), the budget alarm and the per-service error alarms. |

**Verification.** The proposal's negative tests were run on AWS: on V1 stacks `r1017b`/`r1018b`,
and in full on the persistent `dc2-live` environment for issue #229 on 19 October **[AWS]**.

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
| Zero fixable HIGH/CRITICAL image findings at release | Met at every release, with the retained-image incident described in section 5.3 |

**Scope limits.**

- "Zero fixable HIGH/CRITICAL" never means zero vulnerabilities. The images still carry unfixed
  findings (44/44/208 rows at the last scan), and an earlier accepted set included one CRITICAL
  with no fix available.
- DAST findings are report-only, cover seven selected routes, and ran against the local gateway,
  not the AWS edge. Eight low and eight informational entries remain, mostly missing hardening
  headers on the local bridge.
- SonarCloud analysis is advisory and was not configured with a token.
- The #229 negatives ran before the final frozen source and were not repeated on it.

## Extensibility and Maintainability

**How the platform is extended.**

- **A new client application.** It uses only the two OpenAPI 1.0.0 documents and the public flow:
  reserve, upload, finalize, status, retry. The Publisher CLI is the worked example: 491 lines of
  Python in 6 files, using only the standard library and `httpx`. It has 0 imports from service
  code and 0 database credentials, enforced by an AST test, and it is validated against the
  published OpenAPI schema in CI.
- **A new processing capability.** Add an operation to `media_engine/` (pure command builders) and
  to the operation list carried in `submit`. Additive payload fields need no contract version
  change, because consumers ignore unknown fields. The edit feature (clip, crop, scale, convert)
  was added this way without touching the transport.
- **A contract change.** The policy in `contracts/README.md` applies. Changes are additive within a
  version. Consumers accept versions N and N-1, and producers emit the lower version until every
  consumer reads the new one. Each consumer owns a fixture of the fields it reads, and the
  producer's tests check its real messages against that fixture. A breaking change takes two
  releases, in either service order.
- **More capacity.** Raise the encoder cap behind the budget alarm (AISS-05). Media is unaffected.

**What keeps it maintainable.**

- **Boundaries are enforced by tests and builds.**
  - Image builds fail if the opposite domain or a legacy module is importable.
  - IAM permissions are generated from a code-to-permission map and asserted in
    `tests/aws/v1/test_infrastructure.py`.
  - The checked-in template is byte-compared with its generator.
- **Per-service CI lanes.** Path filters select tests and builds per service. `CODEOWNERS` maps
  the directories to the specialism leads.
- **Tests and coverage.** The complete offline regression is 3,697 tests (plus 177 frontend tests)
  **[Local]**. The five backend coverage tiers pass their floors (Media 93.91 % combined, Processing
  93.90 %). Frontend coverage is 96.24 % of statements against a 90 % floor.
- **Recent maintainability work.**
  - Shared storage-credential policy: 253 → 175 lines.
  - Owner-image dependency exports: 44 → 40/36/33 packages.
  - The frontend dependency tree went from 214 to 171 packages, with 9 npm audit findings removed.
  - An obsolete 300-line Compose file and unused CI services were deleted.
  - Ruff formatting was applied everywhere except released migrations, whose bytes are protected by
    a release guard.
- **Retired code is quarantined, not deleted.** The `legacy/` package keeps the Project 1 and
  proposal-era paths testable without shipping them (AD-26).
- **Documentation sits next to the code.** The ADR register, DDD model, views, use-case catalogue,
  runbooks and sanitized receipts are all in the repository. A study guide is published from the
  same sources (GitHub Pages).

**Limits.**

- `contracts/` is still a shared kernel copied into both images.
- There is one lockfile and one CloudFormation stack for both services (AD-23).
- Only contract version 1 exists, so the N-1 path is exercised by tests rather than by a real
  second version.
- The Publisher's two person-day build-effort target was not measured. Its first commit was on
  13 October, with changes on 15 and 18 October.
