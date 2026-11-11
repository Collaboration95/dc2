## Other Architectural Decisions

The remaining register decisions, and the project decisions that shaped the architecture, are
listed below. AD-29 is recorded with the physical decisions (section 3.2.1).

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-03 | Synchronous submit with asynchronous Redis/RQ processing (proposal) | Replaced so that no always-on broker runs and Media does not depend on Processing at request time; see AD-11 | Superseded by AD-11 |
| AD-04 | Idempotent `SubmitJob` keyed on `asset_id`, plus reconciliation; outbox only if needed (proposal) | Idempotency (`SubmissionGuard`, unique `asset_id`) and reconciliation (`repair_work`, lease expiry) were kept. The outbox was adopted from the start because SQL plus SQS is not atomic. | Changed (AD-11) |
| AD-05 | Presigned URLs for source reads and output delivery (proposal) | Uploads and playback stay presigned. The worker reads the source with an IAM grant pinned to a VersionId instead, which removes a live Media callback from the encode path. This is broader than a signed URL, and owner binding is checked in code (section 3.2.3). | Changed (AD-14, AD-20) |
| AD-06 | Service token plus forwarded owner identity on a private network (proposal) | Peer business HTTP is unused. Gateway-trusted Actor and IAM establish the invocation boundary, with SQL roles enforcing data ownership | Superseded by AD-09, AD-20 |
| AD-07 | Containers on AWS in one small environment (proposal) | Same small-environment intent, managed execution: domain handlers use Lambda container images; finite encoders, migrations and bootstrap use Fargate tasks. WorkerImageUri also supplies the short Lambda. | Changed (AD-10, AD-12, AD-13, AD-15, AD-23) |
| AD-08 | Fresh demonstration data; no Project 1 data migration | Keeps effort on the contribution and sets the data lifecycle (section 3.2.3). The deploy pipeline seeds one smoke account. | Kept |
| AD-19 | Closed-by-default stack operated as booked sessions (V1) | Kept idle spend near zero, but made the platform unavailable outside sessions and cost a full deploy and teardown per check | Superseded by AD-27 |
| AD-22 | Opt-in V2 experiments in the same template, off by default: unattended launcher (#68), short encodes on Lambda (#93), one cluster per database (#94) | Keeps experiments revertible: with default flags the template is byte-identical to V1, which a test checks. #68 became the V2-live default (AD-27). #93 and #94 were enabled on `dc2-live` on 21 October (section 4.1, AD-29); per-run stacks keep the defaults. | New |
| AD-28 | **Release admission scans both the candidate and the retained rollback image**, and handles a newly published advisory that affects only the retained image without bypassing the gate (section 5.3) | A restore target must not silently reintroduce a fixable HIGH/CRITICAL finding, but a newly disclosed advisory against the *old* image must not block the release that fixes it. The retained-image exception is Trivy-only; ECR completed-scan validation still applies. See `docs/architecture/decisions.md`. | New (21 October) |

**Project decisions with architectural effect.**

| ID | Decision | Effect |
|:-----|:-----------------------------------------------|:-------------------------------------------------------|
| F-01 | Lecturer accepted the proposal and asked for detailed DDD to confirm the service choice | The capability derivation, typed domain models and context map (section 3.1.4) explain AD-01 |
| D-01 | Baseline is the team's local frozen FlickPond checkout `8854537` (the proposal named `890c5ec`) | Inherited capability is identified separately from Team 17's work |
| Freeze, 20 Oct | Team-accepted demo release frozen at `daee44b` (`docs/release/demo-release-manifest.md`); afterwards, only blocker repairs with verification and a manifest update | Later engineering releases (`629119c` on 20 October, `c7c489c` on 21 October) are recorded as post-freeze addenda with their own receipts |

## Architectural Limitation

The table lists the material architectural limitations, their impact and a resolution
horizon. Owners follow the agreed specialisms: cloud and delivery, Guruprasath Gopal; backend,
Ibrahim Mammadov; domain, contracts and verification, Nguyễn Kim Long.

**C** means the course deadline, 16 November 2026. The post-course roadmap uses **R1** for
month 1, **R2** for months 2–3 and **R3** for later work. The course environment is planned for
teardown after 16 November; later work starts from the repository and template.

| Identifier | Issue and impact | Description | Resolution | Owner | Status |
|:------|:--------------|:-------------------------------|:-------------------------------|:--------|:---------|
| AISS-01 | Startup and finite-capacity latency | Finite Fargate task start dominates standard-lane queue wait. Startup latency and finite capacity constrain response time; measured results are in section 4.1. | R1: stage timestamps, repeated representative workloads and worker CPU/image profiling. R2: consider wider short-lane bounds after measurement. | Long, Guruprasath | Open |
| AISS-02 | Public regional API, no WAF | The execute-api endpoint is reachable without CloudFront; the authorizer and stage throttle are the HTTP controls. | R1: evaluate CloudFront-only origin restriction and managed WAF rules with negative-access checks. | Guruprasath | Open |
| AISS-03 | Image-only restore | Alias and image rollback does not restore schema. Consumers accept contract version 1; database changes must stay compatible with the retained image. | R2: expand-and-contract migrations and automated old-image-on-new-schema verification. | Ibrahim | Accepted; release policy |
| AISS-04 | Single-environment operations | `dc2-live` is the only environment. Main requires a pull request and Full verification, and delivery then runs automatically with no separate environment approval. The deploy role holds AdministratorAccess with a region lock. Alarms and a dashboard exist without paging or tracing; logs are kept seven days. | R1: least-privilege deployment role, paging target and alarm drill. R2: a staging environment from the same template. | Guruprasath | Open |
| AISS-05 | Single-instance recovery | Separate clusters remove the shared capacity boundary, but each cluster has one instance and no reader failover. No restore drill or recovery-time measurement has been recorded. | R1: restore and recovery drills against unchanged bounds. Reassess replica capacity if availability needs justify it. | Long, Guruprasath | Open |

At-least-once delivery, finite encoder caps, legacy quarantine and demonstration data retention
are deliberate properties explained with their decisions. Scope exclusions are in section 1.4.2.
