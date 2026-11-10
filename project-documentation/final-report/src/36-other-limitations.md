## Other Architectural Decisions

The remaining register decisions, and the project decisions that shaped the architecture, are
listed below. Where another section explains the rationale, the table points there.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-03 | Synchronous submit with asynchronous Redis/RQ processing (proposal) | Replaced so that no always-on broker runs and Media does not depend on Processing at request time; see AD-11 | Superseded by AD-11 |
| AD-04 | Idempotent `SubmitJob` keyed on `asset_id`, plus reconciliation; outbox only if needed (proposal) | Idempotency (`SubmissionGuard`, unique `asset_id`) and reconciliation (`repair_work`, lease expiry) were kept. The outbox was adopted from the start because SQL plus SQS is not atomic. | Changed (AD-11) |
| AD-05 | Presigned URLs for source reads and output delivery (proposal) | Uploads and playback stay presigned. The worker reads the source with an IAM grant pinned to a VersionId instead, which removes a live Media callback from the encode path. This is broader than a signed URL, and owner binding is checked in code (section 3.2.3). | Changed (AD-14, AD-20) |
| AD-06 | Service token plus forwarded owner identity on a private network (proposal) | Peer business HTTP is unused. The deployment has a VPC; Gateway-trusted Actor and IAM establish the invocation boundary, with SQL roles enforcing data ownership | Superseded by AD-09, AD-20 |
| AD-07 | Containers on AWS in one small environment (proposal) | Same small-environment intent, managed execution: domain handlers use Lambda container images; finite encoders, migrations and bootstrap use Fargate tasks. WorkerImageUri also supplies the short Lambda. | Changed (AD-10, AD-12, AD-13, AD-15, AD-23) |
| AD-08 | Fresh demonstration data; no Project 1 data migration | Keeps effort on the contribution and sets the data lifecycle (section 3.2.3). The deploy pipeline seeds one smoke account. | Kept |
| AD-19 | Closed-by-default stack operated as booked sessions (V1) | Kept idle spend near zero, but made the platform unavailable outside sessions and cost a full deploy and teardown per check | Superseded by AD-27 |
| AD-22 | Opt-in V2 experiments in the same template, off by default: unattended launcher (#68), short encodes on Lambda (#93), one cluster per database (#94) | Keeps experiments revertible: with default flags the template is byte-identical to V1, which a test checks. #68 ran on AWS and became the V2-live default (AD-27). #93 and #94 were enabled on `dc2-live` on 21 October and measured there (section 4.1, AD-29); per-run stacks keep the defaults. | New |
| AD-29 | One Aurora cluster per service, split in place from the shared one (section 3.2) | The shared cluster was a shared capacity and failure boundary. Rehearsed on a throwaway stack, delivered by CD, pre-split snapshot kept | New (21 October) |
| AD-28 | **Release admission scans both the candidate and the retained rollback image**, and handles a newly published advisory that affects only the retained image without bypassing the gate (section 5.3) | A restore target must not silently reintroduce a fixable HIGH/CRITICAL finding, but a newly disclosed advisory against the *old* image must not block the release that fixes it. The retained-image exception is Trivy-only; ECR completed-scan validation still applies. See `docs/architecture/decisions.md`. | New (21 October) |

AD-30 (Gateway/Lambda plus queue-based load distribution without an ALB) and AD-31
(PostgreSQL/JSONB versus MongoDB/DynamoDB) continue the numbering in Physical Architecture.
They record this report's explicit alternative analyses; the read-only repository register
retains AD-01–29. No topology or persistence migration is required by these report responses.

**Project decisions with architectural effect.**

| ID | Decision | Effect |
|:-----|:-----------------------------------------------|:-------------------------------------------------------|
| F-01 | Lecturer accepted the proposal and asked for detailed DDD to confirm the service choice | The capability derivation, typed domain models and context map (section 3.1.4) explain AD-01 |
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

The table retains material design limits, their impact and a resolution horizon. Owners follow
the agreed specialisms: cloud/delivery — Guruprasath Gopal; backend — Ibrahim Mammadov;
domain/contracts/verification — Nguyễn Kim Long.

**C** means the course deadline, 16 November 2026. A conditional post-course roadmap uses
**R1** for month 1, **R2** for months 2–3 and **R3** for later work. The course environment is
planned for teardown after 16 November; later work starts from the repository/template.

| Identifier | Issue and impact | Description | Resolution | Owner | Status |
|:------|:--------------|:-------------------------------|:-------------------------------|:--------|:---------|
| AISS-01 | Startup and finite-capacity latency | Standard queue wait remains about 37 s against 20 s; task start median 25.6 s (n=12) dominates. Two-worker speedup was 1.449× against 1.6×; three workers achieved 2.347× against 2.1×. Short-lane queue wait met its target, but end-to-end latency still missed; workloads and receipts remain in section 4. | R1: stage timestamps, repeated representative workloads and worker CPU/image profiling. R2: consider wider short bounds only after measurement. | Long, Guruprasath | Open; measured limits |
| AISS-02 | Public regional API, no WAF | The execute-api endpoint bypasses CloudFront; authorizer plus stage throttle remain the HTTP controls. | R1: evaluate CloudFront-only origin restriction and managed WAF rules with negative-access checks. | Guruprasath | Open |
| AISS-03 | Image-only restore | Alias/image rollback does not restore schema. Current consumers accept version 1; compatible database changes remain a release obligation. | R2: expand-and-contract migrations and automated old-image-on-new-schema verification. | Ibrahim | Accepted, policy mitigation |
| AISS-04 | Single-environment operations | The 10 November read-only settings audit recorded no Main protection or aws reviewer rule. Qualifying Main delivery is automatic; the deploy role is broad. Source config has 15 alarms/dashboard, without paging/tracing and with seven-day logs. | R1: required stable checks, least-privilege deployment, paging target/alarm drill. R2: staging from the same template. | Guruprasath | Open; dated settings/source evidence |
| AISS-05 | Single-instance recovery | Separate clusters remove the shared service capacity boundary, but each has one instance and no reader failover. A restore drill and bounded lost-work recovery timing are not established by the retained evidence. | R1: retained restore/recovery drills against unchanged bounds. Reassess replica capacity if availability needs justify it. | Long, Guruprasath | Open |

At-least-once delivery, finite encoder caps, legacy quarantine and demonstration data retention
are deliberate properties explained with their decisions. Scope exclusions remain in section
1.4.2. The optional implementation backlog stays in supporting feedback notes; it is not an
additional set of architectural limitations.
