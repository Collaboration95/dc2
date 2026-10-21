## Other Architectural Decisions

The remaining register decisions, and the project decisions that shaped the architecture, are
listed below. Where another section explains the rationale, the table points there.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-03 | Synchronous submit with asynchronous Redis/RQ processing (proposal) | Replaced so that no always-on broker runs and Media does not depend on Processing at request time; see AD-11 | Superseded by AD-11 |
| AD-04 | Idempotent `SubmitJob` keyed on `asset_id`, plus reconciliation; outbox only if needed (proposal) | Idempotency (`SubmissionGuard`, unique `asset_id`) and reconciliation (`repair_work`, lease expiry) were kept. The outbox was adopted from the start because SQL plus SQS is not atomic. | Changed (AD-11) |
| AD-05 | Presigned URLs for source reads and output delivery (proposal) | Uploads and playback stay presigned. The worker reads the source with an IAM grant pinned to a VersionId instead, which removes a live Media callback from the encode path. This is broader than a signed URL, and owner binding is checked in code (section 3.2.3). | Changed (AD-14, AD-20) |
| AD-06 | Service token plus forwarded owner identity on a private network (proposal) | No private network exists between Lambdas, so IAM and the Gateway-trusted actor became the boundary | Superseded by AD-09, AD-20 |
| AD-07 | Containers on AWS in one small environment (proposal) | Same intent, managed serverless mechanism. Only the encoder, migrations and bootstrap run as containers on Fargate. | Changed (AD-10, AD-12, AD-13, AD-15, AD-23) |
| AD-08 | Fresh demonstration data; no Project 1 data migration | Keeps effort on the contribution and sets the data lifecycle (section 3.2.3). The deploy pipeline seeds one smoke account. | Kept |
| AD-19 | Closed-by-default stack operated as booked sessions (V1) | Kept idle spend near zero, but made the platform unavailable outside sessions and cost a full deploy and teardown per check | Superseded by AD-27 |
| AD-22 | Opt-in V2 experiments in the same template, off by default: unattended launcher (#68), short encodes on Lambda (#93), one cluster per database (#94) | Keeps experiments revertible: with default flags the template is byte-identical to V1, which a test checks. #68 ran on AWS and became the V2-live default (AD-27); #93 and #94 are [NOT_RUN]. | New |
| AD-28 | **Release admission scans both the candidate and the retained rollback image**, and handles a newly published advisory that affects only the retained image without bypassing the gate (section 5.3) | A restore target must not silently reintroduce a fixable HIGH/CRITICAL finding, but a newly disclosed advisory against the *old* image must not block the release that fixes it. The policy and its evidence are in `docs/architecture/decisions.md`. | New (21 October) |

**Project decisions with architectural effect.**

| ID | Decision | Effect |
|:-----|:-----------------------------------------------|:-------------------------------------------------------|
| F-01 | Lecturer accepted the proposal and asked for detailed DDD to confirm the service choice | The DDD model and context map (section 3.1.4); AD-01 confirmed |
| D-01 | Baseline is the team's local frozen FlickPond checkout `8854537` (the proposal named `890c5ec`) | Inherited capability is identified separately from Team 17's work |
| D-06 | One progress report, due 16 October | Project-conduct reporting (section 2) |
| Freeze, 20 Oct | Team-accepted demo release frozen at `daee44b` (`docs/release/demo-release-manifest.md`); afterwards, only blocker repairs with verification and a manifest update | Later engineering releases (`629119c` on 20 October, `c7c489c` on 21 October) are recorded as post-freeze addenda with their own receipts and blocker justification |
| #271 | A 503 instead of a 4xx when S3 refused an oversized upload was accepted as a known limitation at the freeze | Fixed in the later engineering release: a missing upload object now returns a recoverable 409, and real storage failures remain 503. The 100 MiB cap was enforced throughout. |

Rationale already given elsewhere is not repeated here:

- Performance decisions (caching, scale-to-zero, direct-to-S3): section 4.1.
- Availability (outbox, leases, repair, DLQs): section 4.2.
- Security (IAM, authorizer, scanning): section 4.3.
- Maintainability (contracts, per-service lanes, legacy quarantine): section 4.4.

## Architectural Limitation

The key outstanding architectural issues are listed below. Owners follow the agreed specialisms
(cloud and delivery: Guruprasath Gopal; backend services: Ibrahim Mammadov; domain, contracts and
verification: Nguyễn Kim Long).

The **timeline** has two horizons:

- **C**: within the course, by 16 November 2026.
- **Post-course roadmap**: applies if FlickPond is taken forward. Phase **R1** is the first month,
  **R2** is months 2–3 and **R3** is later.

The persistent environment is torn down after 16 November 2026. Any post-course phase would
start from the repository and the retained template.

| Identifier | Issue and impact | Description | Resolution | Owner | Status |
|:------|:--------------|:-------------------------------|:-------------------------------|:--------|:---------|
| AISS-01 | Shared database failure and capacity boundary | One Aurora cluster with one instance (0–2 ACU) holds both logical databases. An outage, a failed resume or the capacity ceiling affects both services. Backups are kept 1 day, and no restore drill was run. | R2: deploy the already-rendered one-cluster-per-domain option (#94) after an AWS run; add a reader in the second AZ; run a quarterly restore drill | Guruprasath | Accepted for course scope |
| AISS-02 | No regional or zone failover | Everything runs in ap-southeast-1. The subnets span two AZs, but the database instance does not. Multi-zone and multi-region failover were excluded in the proposal. | R3: Multi-AZ Aurora reader, cross-region backup copy, documented RTO/RPO | Guruprasath | Accepted (out of scope) |
| AISS-03 | Queue wait misses its target: about 37 s against 20 s | Fargate task start (median 25.6 s, n = 12) dominates the wait from `queued` to `processing` for a warm job **[AWS]** | R1: measure a slimmer worker image and lazy image loading; R2: run the opt-in Lambda short-encode lane (#93) for short clips | Long (verify), Guruprasath | Open, measured miss |
| AISS-04 | Two-worker scaling miss and an evidence gap | AWS V1 measured 1.449× against 1.6× at two workers (2.347× against 2.1× at three passed), from a 6-clip backlog with one run per cap. The proposal's 30-clip AWS comparison was not run. | R1: rerun 30 clips × 3 repeats per cap with per-task CPU profiling; report against the unchanged targets | Long | Open, measured miss |
| AISS-05 | Bounded capacity, no general autoscaling | At most three concurrent encodes (a cost choice; the Fargate quota is now 30 vCPU). Work beyond the cap waits in the queue. | R2: raise the cap behind the budget alarm; size the cap from queue age | Guruprasath | Accepted (cost) |
| AISS-06 | Public API endpoint beyond CloudFront, no WAF | The `execute-api` URL is reachable directly. Only the authorizer and a single stage throttle protect it. | R1: CloudFront-only origin (secret origin header checked by the authorizer) plus AWS WAF managed rules | Guruprasath | Open |
| AISS-07 | Owner-only access | Only the owner can play an asset. The contract accepts a `viewer` role that nothing issues, so there is no sharing. | R3: share grants in Media, issuing `viewer`; no contract version change is needed | Ibrahim | Accepted (out of scope) |
| AISS-08 | Image-only rollback | Release restores images and aliases, never schema. Pair compatibility is an operator attestation backed by N/N-1 contract tests. | R2: enforce expand-and-contract migrations with an automated old-image-on-new-schema test in CI | Ibrahim | Accepted, mitigated by policy |
| AISS-09 | Broad deploy role; one environment | The CD role has `AdministratorAccess` with a region lock. Promotion to the single environment is automatic after green Main CI; there is no staging and no reviewer gate on the `aws` environment. | R1: least-privilege deploy policy; required reviewers on the `aws` environment; R2: a staging stack from the same template | Guruprasath | Open |
| AISS-10 | Legacy residue | Peer-era tables and columns (`retry_intents`, `jobs.source_url`) and the `legacy/` package remain. They are kept out of images and unused. | R2: a separately planned contract migration once the last legacy stack is gone | Ibrahim | Accepted, scheduled |
| AISS-11 | Alarms with nobody paged | 13 alarms and a dashboard exist, but there is no notification target, no tracing, and logs last 7 days. No alarm was observed firing. | R1: SNS notification target, an alarm drill and AWS X-Ray | Guruprasath | Open |
| AISS-12 | Undefined production data retention | There is no account deletion, no purge of tombstones or inbox/outbox rows, and no S3 lifecycle rule. For this deployment, all demonstration data is removed at the teardown after 16 November, and the final Aurora snapshot is deleted once grades are released. | C: teardown after 16 Nov 2026; R2: define production retention (noncurrent-version expiry, 30-day inbox/outbox pruning, tombstone purge) | Long | Open (production); planned (demo) |
| AISS-13 | Base-image vulnerabilities | Images carry unfixed (no-fix-available) findings: 44/44/208 rows at the last scan. A new advisory against a retained rollback image blocked CD on 21 October (section 5.3). | Closed for the release path by AD-28; R1: a scheduled weekly rebuild and rescan of retained images; R2: a smaller worker base image | Guruprasath | Closed (gate); Open (hardening) |
| AISS-14 | Evidence not established | Not established: the AWS lost-queue-entry timing (120 s bound), the duplicate-output check after a worker kill, a restore drill, the Publisher's 2 person-day effort, and actual spend (Cost Explorer showed USD 0.00 with credits applied). | C: read the final October bill in Cost Explorer before 16 Nov; R1: run the remaining experiments with retained receipts | Long, Guruprasath | Open |
| AISS-15 | At-least-once delivery | Duplicates and reordering are expected. They are absorbed by inbox and version fences: 18 sends were recorded for 9 jobs. Poison messages stop in a DLQ and need an operator redrive (runbook). | None needed; this is by design and documented | Ibrahim | Accepted |
