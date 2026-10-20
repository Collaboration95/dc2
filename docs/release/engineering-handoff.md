# GC2 study guide and engineering handoff

This guide is a reading path for learning the as-built FlickPond project and preparing a factual course handoff. It is reusable study material, not a report, presentation, demo script, or authorship statement. Follow the links into the source, architecture, test, and evidence records rather than treating this summary as proof by itself.

## Start with source identity

- The accepted persistent V2-live release is source `daee44b61a6e8eef3f62505df69f8bfd076d68b8`. The [release manifest](demo-release-manifest.md) records its image identities, read-back on 20 October 2026, and evidence limits. The project’s frozen `project2-v1` tag is `f33b2a899fe2a1b7f1dab8480e03904d80838701`; it is a different, earlier release.
- The documentation snapshot described in the handoff notes was Main at `f9ce3b949826a7f329839cd7dc2b3a48464e1661`, after the freeze. The checkout used to prepare this guide is candidate source `ef1b8e01c119514ec2074c908ad55e110d66fc9b`. Candidate code changes have not been deployed. Until the parent completes integration and verification, use `daee44b` as the release identity and fallback.
- Baseline hashes need care. The submitted proposal names inherited baseline `890c5ec`; decision D-01 says the working plan used local `8854537` instead. That Git object is not present in this checkout, so do not claim a fresh code diff between those baseline hashes. See the [project decisions](../../project-roadmap/records/project-decisions.txt), [effort ledger](../../project-documentation/effort-ledger.md), and [baseline inspection](../../project-documentation/project-2-baseline-and-plan.txt).

## Recommended reading order

1. [Project documentation index](../../project-documentation/README.md), [GC2 briefing interpretation](../../project-documentation/briefing-requirements.txt), and the submitted [Team 17 proposal](../../project-documentation/Team17-Proposal.docx): learn the current scope and course authority.
2. [Project 1 history](../history/README-project1-and-pre-aws-local-stack.md), the [baseline inspection](../../project-documentation/project-2-baseline-and-plan.txt), and the [effort ledger](../../project-documentation/effort-ledger.md): separate inherited capability from Team 17’s work and from team-level effort allocation.
3. [Root README](../../README.md), [DDD model](../architecture/ddd.md), [architecture decisions](../architecture/decisions.md), [architecture views](../architecture/views.md), and the [UC/design catalogue](../architecture/use-case-design.md): follow the business and implementation boundaries.
4. [Release manifest](demo-release-manifest.md), [results against targets](../results/actual-vs-target.md), and [evidence index](../evidence-index.md): compare results by source, environment, workload, and verdict.
5. [Course evidence checklist](../../project-documentation/course-evidence-checklist.md): map the inherited course bundle to current GC2 requirements and identify submission or human-confirmation work.

## What changed from inherited GC1 to GC2

### Inherited capability

The Project 1 system already had a FastAPI browser application, owner accounts and uploads, job state, retry and recovery concepts, Redis/RQ, MinIO, nginx, FFmpeg workers, MP4 and best-effort HLS playback, and basic CI. Team 17 inherited and reshaped these capabilities. It did not build video encoding from zero or complete the earlier roadmap items for search, moderation, analytics, sharing, 4K, or a new editor. The [history note](../history/README-project1-and-pre-aws-local-stack.md), [baseline inspection](../../project-documentation/project-2-baseline-and-plan.txt), and [effort ledger](../../project-documentation/effort-ledger.md) are the evidence trail.

### GC2 decisions and timeline

- On 22 September–4 October, the three-member Team 17 exception, focused scope, and proposal were recorded. The new scope became UC-1–UC-7, with two product clients and operator evidence. The ledger assigns work packages and milestones; it is not individual time tracking or proof of personal authorship.
- A 9 October roadmap snapshot still said implementation had not started. Treat it as a dated planning record, not current status. Implementation and integration are recorded from 8–14 October; cloud delivery, CI/CD, experiments, and closeout followed through 20 October.
- The persistent `dc2-live` environment was deployed on 18 October, updated and read back on 19–20 October, and frozen at `daee44b` on 20 October. The release manifest is the authority for that runtime. Later candidate commits are not deployed merely because they are newer.

### Architecture evolution

The submitted proposal is the “before” for the GC2 design comparison; it is not the same as the still earlier Project 1 implementation. The proposal described synchronous Media-to-Processing `SubmitJob`, Redis/RQ, and a service token. The current design uses two owned business contexts and asynchronous contracts:

1. Media owns identity, owner-scoped upload reservations, verified source identity, the public asset/job view, and playback authorization. Browser and Publisher upload bytes directly to versioned S3 using a scoped reservation. Media checks size, hash, and file signature, pins the exact S3 VersionId, then adopts the asset and writes a durable outbox command. See [direct intake](../../media/services/direct_intake.py), [upload routes](../../media/api/uploads.py), and [AD-11/AD-12](../architecture/decisions.md).
2. Processing owns jobs, attempts, leases, retries, worker execution, and output descriptors. SQL outbox/inbox transactions publish commands and results through SQS. Consumers handle at-least-once delivery with message identity/body checks, state-version and attempt fences, and repair paths; this is not exactly-once delivery. See [Processing worker tasks](../../processing/worker/tasks.py), [messaging](../../processing/messaging.py), [delivery helpers](../../delivery/sql.py), and the [DDD/context map](../architecture/ddd.md).
3. Media and Processing use separate logical databases, roles, and migrations on one Aurora cluster. There are no cross-database foreign keys. Logical ownership is real; physical database failure isolation is not. The API Gateway authorizer is Media-owned and passes a trusted actor context. Publisher uses the public HTTPS/OpenAPI contract without service or database imports. See [Media authorization](../../media/authorizer.py), [Gateway contract](../../contracts/gateway.py), [Publisher](../../publisher/README.md), and [persistence views](../architecture/views.md).
4. Media maintains a versioned projection of Processing state for owner-facing reads. Playback URLs are signed at read time; HLS is optional and MP4 remains the fallback. Retry uses the previously verified source and creates a new fenced attempt; it does not ask the user to upload the file again.
5. V1 used per-run stacks and operator-started finite Fargate batches. The later V2-live mode keeps one persistent stack, updates it after green Main CI, launches finite workers from SQL backlog, and caps workers at three. Its 0→N→0 launcher is an operator/platform capability, not a new product dashboard or general-purpose autoscaling service. The detailed [architecture views](../architecture/views.md) describe V1; read them with the V2 qualifications in the [manifest](demo-release-manifest.md) and [AD-27](../architecture/decisions.md).

## Personas and demonstrable UC-1–UC-7 journey

Maya, Arun, Jules, and Sam are fictional planning personas, not interviewed customers, application roles, or authorship evidence. Maya’s course-team context does not imply shared accounts, student access, or an LMS. Sam is an operator, not a product administrator. Persona definitions and stable UC IDs are in [business-scope.json](../../project-roadmap/business-scope.json); use the linked [UC/design catalogue](../architecture/use-case-design.md) for preconditions, normal and exception flows, tests, and design views.

| Persona | UC mapping | Demonstrable path | Keep the claim bounded |
|---|---|---|---|
| **Maya (P-01), content owner** | UC-1 upload; UC-2 process; UC-3 status/playback; UC-4 stored-source retry; UC-5 batch publish | Authenticate with Publisher, submit a small prepared folder, retain each per-file outcome and one job ID, then open the web app to show owner status and a completed MP4 or available HLS. Use retry only for a known failed job that is already recorded. | One owner account; no shared classroom, LMS, or student access. Do not cause a live failure just to show retry. The CLI batch is nonrecursive and skips directories/symlinks. |
| **Arun (P-02), another owner** | UC-1–UC-4 | Use the browser for one supported upload, follow its status, and play a completed result. If a known failed job exists, show that retry reuses the stored source. | This helps explain personal ownership and MP4 fallback. HLS is best effort, not guaranteed for every source. Do not turn a local V1 run into V2-live proof. |
| **Jules (P-03), integrator** | UC-1, UC-3, UC-4, UC-5 | Show the OpenAPI contract and Publisher README/commands; demonstrate `status`, `output`, or bodyless `retry`, and the import-boundary test. | Publisher is a thin API client, not a third portal; it has no player or database access. Retry is an implemented command; transport polling is bounded. |
| **Sam (P-04), operator** | UC-6 capacity; UC-7 release/restore | Show recorded scaling results and the exact frozen release/CI/CD identities. Show a prior bad-candidate restore with its source SHA. | Do not deploy, scale, inject a fault, or perform rollback during the presentation. The recorded bad-candidate restore is from `7928b7c`, not `daee44b`. |

A safe end-to-end presentation sequence is: Maya’s accepted job → background Processing → Maya’s status and playback → Jules’s public-contract reuse → Sam’s recorded capacity and release evidence. Keep a ready test file below 100 MiB and use only prepared accounts/data. Cloud state may have changed since the manifest read; check availability through the team’s approved access before relying on a live path. Keep a recorded or local fallback labeled with its actual source and environment.

## Course requirements and artifact map

Use the supplied course ZIP as the inherited engineering-completeness checklist: working system and source, business/domain analysis, architecture, design-to-code explanation, use-case flows, tests, security, development lifecycle, and evidence. The ZIP is SWE5006 material from another course context. Current GC2 briefing, proposal, report template, and presentation guide govern current scope, dates, deliverable format, and final outline. The older template’s grading weights, dates, 13+4-minute demo guidance, and sample proposal features do not replace current GC2 requirements. The [course evidence checklist](../../project-documentation/course-evidence-checklist.md) records the crosswalk; the three sample proposals add no FlickPond features.

| Current GC2 competency or commitment | Where to study it | Evidence and limit |
|---|---|---|
| **Architecting Software Solutions:** business need, stakeholders, decisions, trade-offs, quality attributes | Proposal; [DDD](../architecture/ddd.md); [decisions](../architecture/decisions.md); [results](../results/actual-vs-target.md) | Personas are planning assumptions. Explain measured misses as well as passes. |
| **Platform Engineering:** bounded contexts, contracts, data ownership, seed/producers/consumers, reuse | [DDD](../architecture/ddd.md); [OpenAPI contracts](../api/); [Publisher](../../publisher/README.md); [UC/design catalogue](../architecture/use-case-design.md) | The second client is the Publisher CLI. No portal, billing, or third client is implied. |
| **Cloud Native Solution Design:** service/network/storage choices, independent worker capacity, failure behavior | [physical/persistence views](../architecture/views.md); [release manifest](demo-release-manifest.md); [capacity results](../results/actual-vs-target.md) | One region, one stack, and one Aurora cluster/instance are shared failure/capacity boundaries; do not call this high availability. |
| **DevSecOps:** repeatable build, tests, security checks, deployment, lifecycle | [CI/CD workflows](../../.github/workflows/); [CI scripts](../../scripts/ci/); [AWS delivery scripts](../../scripts/aws/); [evidence index](../evidence-index.md) | Ruff security rules are security lint, not whole-program data-flow SAST. A passing local control test is not hosted CI, an image scan, or AWS proof. |
| **Attached design and project-conduct expectations** | [UC/design catalogue](../architecture/use-case-design.md); [course checklist](../../project-documentation/course-evidence-checklist.md); [effort ledger](../../project-documentation/effort-ledger.md) | The catalogue has shared class/sequence views and three retrospective design-problem bundles. Suggested explanation owners are not verified authors. No current verified burndown/retrospective package was found. |

The current GC2 report template has six sections: Introduction, Project Conduct, Solution Overview, Quality Attributes, DevOps and Development Lifecycle, and Other Items. The current presentation order is Overview, Project Conduct, Logical Architecture, Physical Architecture, DevOps/Lifecycle, and Demonstration. The recorded Team 17 slot is 26 October 2026, 14:35–15:15 Singapore time, with a 40-minute slot including questions and an 8+2-minute demo; verify the current Canvas schedule, Zoom/access details, and peer-assessment instructions before use.

The briefing interpretation asks progress reports to state completed work, each member’s hours, problems, and the next two weeks; decision D-06 records one weekly report due 16 October, but its submission receipt is unverified. The presentation/report also need actual effort figures for the current project and both projects. The ledger’s 33 person-days / 264 hours total and 11 person-days / 88 hours per member are equal team-agreed allocation using 8 hours per person-day, not timesheets. The ledger also lists Ibrahim in FlickPond Project 1 track A while saying Project 2 continues no member’s own Project 1; resolve that provenance tension with the team before assigning Project 1 history or credit. Confirm actual contribution and Project 1 hours, who will explain each design bundle, the progress-report receipt, recording access, and any AI-use declaration with the members/course owner. Do not infer effort, authorship, TDD, pairing, sprint events, or personal understanding from commits or agent activity. The final report, deck, and course submission are outside this guide.

## Testing, quality, and maintainability

Follow the invariant to the test, not just the module name. Useful examples include owner denial and forged identity, exact source VersionId pinning, outbox lost-send replay, inbox duplicate handling, attempt/lease fencing, stored-source retry, output namespace checks, launcher cap and ambiguous RunTask replies, Publisher import boundaries, and release restoration. The [UC/design catalogue](../architecture/use-case-design.md) links the relevant tests and states whether each reference is code, local test, AWS evidence, or not run.

Recent candidate engineering work has a few bounded maintainability measures:

- The shared native storage-credential policy went from 253 to 175 source lines (78 fewer before Ruff formatting), while owner modules keep thin Media/Processing facades. The intent is to reduce policy drift while preserving endpoint restrictions, refresh locking, expiry, and safe errors.
- The Media asset-page query now uses one owner-local outer join instead of an N+1 projection lookup. Focused SQLite tests assert one SELECT at several page sizes and retain ordering/visibility cases. Do not claim a PostgreSQL latency improvement from those tests.
- Candidate image dependency exports narrowed from 44 packages per image to 40 for Media, 36 for Processing, and 33 for the worker. These are package counts, not image-size measurements.
- Ruff formatting was applied across maintained Python. It increases physical line count in formatted files; describe it as consistent formatting, not a total-repository LOC reduction. Targeted code and dependency reductions are separate measures.
- A new real PostgreSQL/Moto integration cohort recorded 99/99 required core cases and 157/157 selected cases overall on source `a9bf1c43f5584d74d4986d885156f229561dd344` (run `t3-91448b6d-commit-20261020`). That child source is separate from this checkout and its result is not hosted CI, cloud acceptance, or final integrated-source verification. The single parent-owned validation section below controls the current disposition.

These checks improve confidence in specific behaviors; they do not establish complete coverage, exactly-once delivery, or general reliability. Read the [evidence index](../evidence-index.md) and [actual-vs-target results](../results/actual-vs-target.md) with each workload and source label intact.

## Presentation order and backup evidence

Use the current course’s six-part order as a study outline, not a slide draft or speaking script:

1. **Overview:** business problem, platform seed/producers/consumers, inherited GC1 capability, and Team 17’s actual contribution. Start from the [README](../../README.md) and proposal.
2. **Project Conduct:** real milestones, issue/review evidence, and the effort ledger’s allocation basis. State which individual facts still need member confirmation.
3. **Logical Architecture:** two contexts, contracts, data ownership, representative UC flows, and the rationale for outbox/inbox and trusted owner identity. Use [DDD](../architecture/ddd.md), [decisions](../architecture/decisions.md), and the [UC/design catalogue](../architecture/use-case-design.md).
4. **Physical Architecture:** show V2-live as built using the [manifest](demo-release-manifest.md); label the detailed V1 diagrams as V1. Explain the shared Aurora and single-region limits.
5. **DevOps and Lifecycle:** workflows, test selectors, scan/release gates, release identity, and retained receipts. Keep local, hosted, and AWS evidence distinct.
6. **Demonstration:** use the Maya → Jules → Sam journey above. Reserve the current presentation guidance’s 8+2-minute demo allowance and keep a source-labeled backup.

Have these backup evidence items ready for questions:

- Frozen source/images and successful CI/CD identity: manifest source `daee44b`; CI run `39278870533` (attempt 2) and deploy run `39286933644`. The manifest says the per-image scan details and deploy smoke JSON were not re-read, so do not assert their uninspected contents.
- Capacity: V1 AWS used six clips and one run per cap: 0.483, 0.700, and 1.134 jobs/min at caps 1, 2, and 3. Cap 2 was 1.449× and **missed** its 1.6× target; cap 3 was 2.347× and passed its 2.1× target. The proposed 30-clip AWS workload was not run. V2-live used one nine-clip, fixed-cap-3 run: 239 seconds and 2.26 jobs/min; it is not a 1/2/3 comparison.
- Queue wait: V2-live measured about 37 seconds against a 20-second target. Keep this miss visible.
- Security: the retained #229 AWS negative checks preceded the final frozen source. The frozen #271 behavior is described below; do not convert an earlier-source test into exact-freeze proof.
- Restore: CD run `39271754470` restored a bad Processing candidate from `7928b7c`. It does not prove rollback of `daee44b`.
- Browser, Publisher, local integration, coverage, and DAST: use only receipts that name the exact source, environment, command, and outcome. A test-selection count is not a substitute for the required evidence artifact.

## Honest limits and likely questions

- **Why two contexts?** Media owns accounts, assets, upload identity, and user-facing reads; Processing owns attempts, leases, encoding, and outputs. Their contracts and exclusive records support separate change and worker capacity.
- **Why do separate databases still share a failure boundary?** Both logical databases and roles are on one Aurora cluster/instance in one region. This is logical separation, not physical isolation or HA proof.
- **Why outbox/inbox?** A local SQL transaction cannot atomically commit an SQS send. The outbox makes intent durable; consumers commit inbox and owned state before ACK. Repair and deduplication handle at-least-once transport, with bounded eventual consistency.
- **Why does Media own authorization?** It owns accounts and current role state. Processing receives a trusted actor through the Gateway, rather than a caller-supplied owner header or a copy of Media’s JWT secret/user table.
- **What does the capacity result prove?** The V1 cap-2 target miss and cap-3 pass apply only to the stated six-clip workload. The later V2 run shows one fixed-cap-3 workload, not a comparative scaling curve.
- **What does rollback prove?** One earlier-source bad-candidate restore. It does not establish exact-frozen-source rollback or schema rollback.
- **What is not in scope?** Search, moderation workflow, product analytics, sharing/tenancy, student/LMS access, billing, a developer portal, live streaming, or a third client.

One frozen-release limitation is important for the live story: the 100 MiB cap held, and an S3-refused oversized object was not adopted, but finalize could return 503 instead of the ideal client error (#271). Candidate code changes classify a missing object as recoverable 409 while retaining 503 for other storage failures; that candidate behavior is not deployed proof. HLS remains best effort, active-media retention is not generally specified, one-day backups do not establish a restore drill, and current live availability after the manifest read is unknown.

## Parent-owned current validation — finalize this section after integration

At handoff, the accepted release remains frozen at `daee44b61a6e8eef3f62505df69f8bfd076d68b8`; candidate code in this checkout has not been deployed. The 99/99 core integration cases and 157/157 selected cases above belong to child source `a9bf1c43f5584d74d4986d885156f229561dd344`, not this checkout. Parent native-pytest-discovery and integrated-source verification are still required. The parent is addressing independent-review findings F1 (CD test dependencies), F2 (logger-sink failures must not interrupt failure handling), and F3 (manual release runbook must attach exact-image scan receipts). A separate DAST handoff on source `bc6a3e12badab3b1d69ec0f8a9f98ecdaa53515d` records a successful two-owner local handler/auth harness, but no active ZAP scan ran; fixture proof is not an active-scan pass. Final integrated tests, DAST, exact image builds/scans, and hosted CI are not established by this guide. The accepted `daee44b` runtime remains the fallback.

After integration, replace this whole section with the integrated source SHA and date, exact run/evidence links, commands, pass/fail/skip results and limits, DAST disposition, image/scan identity, hosted-CI identity, and whether any authorized release occurred. Keep the freeze status explicit; do not copy child-source results forward as final-source results.
