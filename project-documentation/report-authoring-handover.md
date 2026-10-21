# GC2 report requirements and source handover

Audit date: 21 October 2026. Team 17, FlickPond.

This handover was written for the person writing the final report. It maps the original report
requirements to existing material, identifies gaps, and explains which sources are current. It is
not a report draft or a submission receipt. The report now exists at
[`final-report/`](final-report/README.md); section 9 records how each gap was resolved.

**Verdict:** substantial technical material exists for every major GC2 report section, including
DDD and the reasons behind the architecture. The package is not yet gap-free. The highest-priority
engineering finding is a newer failed application deployment. Other work concerns report assembly,
human confirmations, incomplete evidence against some proposal targets, and the more detailed
diagram format in the adopted GC1 checklist. None of these findings establishes a need for new
business features.

## 1. Which requirements govern the report

| Source | Use it for | Authority and qualification |
|---|---|---|
| [Current GC2 report template](original-reference/02%20Project%20Report%20Template%20for%20Practice%20Project.docx) | Exact report sections and prompts, mapped in section 3 below. | Primary report structure. Its certificate is **Architecting Scalable Systems**. Quality attributes are section **4**, not proposal section 3.4. |
| [Current GC2 briefing](original-reference/01%20Briefing.pdf) | Page 5: working system, code, report, pipeline and test scripts. Page 6: schedule and report incorporating presentation remarks. Page 9: evidence for platform/cloud benefits. Page 14: progress-report contents. | Primary written requirements. [Briefing interpretation](briefing-requirements.txt) records the lecturer's clarifications; do not turn every example technology into a mandatory feature. |
| [Submitted Team 17 proposal](Team17-Proposal.docx) | Business problem, inherited baseline, scope, seven use cases, original decisions, quality targets, WBS and estimates. | Team-specific commitments. Proposed mechanisms are historical where the as-built design changed. Use the decision register to explain those changes. |
| [GC2 presentation guide](original-reference/04%20Project%20Presentation%20Guidelines%20%26%20Schedule.pdf) | Page 1: overview, conduct, logical/physical design, DevOps and demo. Page 2: team slot. | Team 17: **26 October, 14:35–15:15 SGT**, also explicitly confirmed by the user. The revised local PDF still places Team 17 on 26 October. |
| User-supplied `course_files_export.zip` | Additional GC1/SWE5006 engineering completeness: analysis-to-design, per-use-case models, design problems/patterns and agile artifacts. | Adopted supplementary checklist, not the current GC2 report outline or deadline authority. See section 5 for the gaps that remain against its literal format. |
| [Course evidence checklist](course-evidence-checklist.md) | Existing crosswalk and earlier audit. | Useful index, not a replacement for the originals or proof that every requirement is met. This handover adds a stricter template check and newer delivery status. |

The original GC2 briefing lists report submission on **16 November**, with presentation feedback
incorporated. Exact Canvas cutoff time, required upload format, peer-assessment instructions and
any later course instructions still need confirmation. A tentative internal 31 October code date
in the effort ledger is not a course-imposed deadline.

The attachment inspected has SHA-256
`fec5e4dc9fd2d40af96fdda8f5bcf59a88e2fe8f3a73000390cbb3aac385858c`.
It contains the SWE5006 briefing PPTX, report and progress templates, presentation guide and
three sample proposals. Samples do not add requirements to FlickPond. The repository's GC2
briefing, report template and original presentation guide match the copies in the local
`Downloads/PM_Project_Brief_export` folder byte for byte.

## 2. Read this before describing the release as current

The local documentation audit used source `94f7463212baacfddcb7ff77bd2387a55552acd6`.
GitHub checks observed through the authenticated `gh` CLI identify the merged Main source as
`4ae6a0b71bad730589055dab4746a1e04b1c0f61`.

| Evidence | Observed outcome | Meaning for the report |
|---|---|---|
| [Main CI 39531399249](https://github.com/Collaboration95/dc2/actions/runs/39531399249), source `4ae6a0b` | Success. | Current source passed CI. |
| [Showcase guide 39531399274](https://github.com/Collaboration95/dc2/actions/runs/39531399274), source `4ae6a0b` | Success. | The study guide published. This is separate from application delivery. |
| [Application CD 39532075705](https://github.com/Collaboration95/dc2/actions/runs/39532075705), source `4ae6a0b` | **Failure**, 21 October. Exact-source CI admission passed; the `Deploy` step failed; the following upload-to-playback smoke was skipped. | Do not claim the latest Main application deployment completed successfully. |
| [Retained engineering delivery receipt](../docs/results/engineering-20261020/delivery-629119c.json), source `629119c` | Prior successful delivery, upload/playback smoke, image and alias read-back on 20 October. | Valid dated evidence. It is not a fresh statement about all live resources after the later failed run. |
| [Team-accepted demo manifest](../docs/release/demo-release-manifest.md), source `daee44b` | Earlier team-accepted freeze. | Keep team acceptance separate from later engineering delivery. A new successful deployment does not itself establish a replacement team freeze. |

The new failure is more specific than “CI failed.” The CD log shows the newly built Media image
passed its scan, then a registry scan reported `media: FAIL: Trivy has 1 fixable HIGH/CRITICAL`.
The [release script](../scripts/ci/cd.sh), function `release_owner`, scans the local candidate
followed by the retained baseline image before promotion. This places the failure at the retained
Media image scan. The downloaded public artifact includes the passing candidate scan; it does not
include a public report naming the failing vulnerability. Do not guess that vulnerability's ID.

The run also retained a successful infrastructure/deploy-stage receipt. That receipt alone does
not establish successful owner promotion or a completed end-to-end deployment. No fresh AWS
resource read-back or live smoke was performed during this documentation audit. Resolve this
delivery item and retain the resulting scan, release and smoke evidence before describing Main
as fully delivered. Do not bypass the scan gate to obtain a green status.

## 3. Current GC2 template section by section

Status meanings:

- **Source ready:** the relevant technical or historical material exists; it still needs to be
  selected, explained and incorporated into the report.
- **Partial:** useful sources exist, but a specific fact, synthesis or evidence item is missing.
- **Human confirmation:** project members or the course/submission system must establish the fact.

### Front matter and section 1 Introduction

| Template item | Where to find the material | Status and authoring instruction |
|---|---|---|
| Cover and contents | [Team 17 proposal](Team17-Proposal.docx), title/team fields; current report template. | **Source ready.** Use the project title, Team 17 and confirmed member names. Generate the contents table from the final report headings. |
| 1.1 Background | Proposal §§1.1 and 1.4; [engineering handoff, “What changed from inherited GC1 to GC2”](../docs/release/engineering-handoff.md#what-changed-from-inherited-gc1-to-gc2); [historical baseline](project-2-baseline-and-plan.txt). | **Source ready with provenance confirmation.** Explain inherited FlickPond at `890c5ec` and the GC2 contribution. Resolve the member/Project 1 provenance tension in section 4 before assigning credit. |
| 1.2 Business Needs | Proposal §§1.2–1.3; [business scope and personas](../project-roadmap/business-scope.json); [study guide basics](../showcase-prep/basics.html). | **Source ready.** Repeated video-workflow implementation, bursty CPU work, API reuse and independent Processing capacity. Personas are planning assumptions, not evidence of customer interviews. |
| 1.3 Stakeholders | Proposal sponsor/team fields; [handoff persona table](../docs/release/engineering-handoff.md#personas-and-demonstrable-uc-1uc-7-journey); [business scope](../project-roadmap/business-scope.json). | **Source ready.** Maya and Arun are owner personas, Jules an integrator, Sam an operator. Name real team/course stakeholders separately. The proposal states no external sponsor. |
| 1.4 Project Scope | Proposal §3; [current use-case catalogue](../docs/architecture/use-case-design.md); [proposal-to-as-built deviations](../docs/architecture/decisions.md#4-proposal-to-as-built-deviations). | **Source ready.** Distinguish architected, implemented and experimentally verified scope; explain changes from the proposal. |
| 1.4.1 Functionality in scope | Catalogue UC-1–UC-7; proposal §3.2. | **Source ready.** Owned upload, processing, status/playback, stored-source retry, Publisher CLI, capacity experiments and independent release/rollback. |
| 1.4.2 Functionality out of scope | Proposal scope/exclusions; [briefing interpretation](briefing-requirements.txt); [handoff limits](../docs/release/engineering-handoff.md#honest-limits-and-likely-questions). | **Source ready.** Preserve exclusions such as public sharing, LMS/student access, tenants/billing, search/moderation/product analytics and a third client. Some old planning exclusions were later superseded; for example, the persistent system does start finite workers automatically. |

### Section 2 Project Conduct

| Template item | Where to find the material | Status and authoring instruction |
|---|---|---|
| 2.1 Project Plan | Proposal §4.1 WBS and §4.2 schedule; [effort ledger](effort-ledger.md); [recorded project decisions](../project-roadmap/records/project-decisions.txt). | **Source ready.** Use the submitted **31 person-day estimate**, with recorded changes. Earlier 30-day planning interpretations are superseded. |
| 2.2 Project Status | [Engineering handoff](../docs/release/engineering-handoff.md); [actual vs target](../docs/results/actual-vs-target.md); section 2 of this handover; [close-out epic #181](https://github.com/Collaboration95/dc2/issues/181). | **Partial.** Describe completed capabilities, delivery status, measured misses and submission work. Include the newer CD failure. Do not copy an older “all green” summary. |
| 2.3 Project Metrics | [Effort ledger, milestones and work packages](effort-ledger.md); proposal §4; [issue #191](https://github.com/Collaboration95/dc2/issues/191). | **Human confirmation.** Actual milestone evidence exists. The 33 pd / 264 h total and 11 pd / 88 h per person are explicitly an equal allocation, not timesheets. Confirm actual rough effort and contributions, including later work. |

### Section 3 Solution Overview

| Template item | Where to find the material | Status and authoring instruction |
|---|---|---|
| 3.1 Logical Architecture & Design | [Views §§1–2](../docs/architecture/views.md); [DDD model](../docs/architecture/ddd.md); [current catalogue](../docs/architecture/use-case-design.md); [architecture explainer](../showcase-prep/architecture.html). | **Source ready.** Show static responsibilities and dynamic interactions. Identify custom code, libraries and managed-service providers. Detailed `views.md` diagrams are labelled V1; explain persistent V2-live changes. |
| 3.1.1 Key Architectural Decisions | [Decision register](../docs/architecture/decisions.md), especially service ownership, AD-09, AD-11, AD-21, AD-24 and deviations. | **Source ready.** Summarize selected trade-offs and rationale. Preserve ADR identifiers; do not renumber the original decisions or present superseded choices as deployed. |
| 3.1.2 Tiers and Layers | [Views §1](../docs/architecture/views.md#1-tiers-and-layers-logical-view); [code and abstractions explainer](../showcase-prep/code.html); catalogue “Common implemented design class model.” | **Source ready.** Connect browser/CLI, transport adapters, domain services, data access, contracts and delivery helpers to actual modules. |
| 3.1.3 Nodes and Subsystems | [Views §2](../docs/architecture/views.md#2-nodes-and-subsystems); [DDD bounded contexts](../docs/architecture/ddd.md#3-bounded-contexts); [repository map](../README.md). | **Source ready.** Media and Processing are the business boundaries. Workers are Processing components; SQL outbox/inbox and contracts are shared mechanisms, not extra business services. |
| 3.1.4 Platform Design | [DDD §§1–7](../docs/architecture/ddd.md); [versioned contract policy](../contracts/README.md); [Media API](../docs/api/media.openapi.json); [Processing API](../docs/api/processing.openapi.json); [Publisher](../publisher/). | **Source ready.** Covers context map, ubiquitous language, Asset and ProcessingJob aggregates, invariants, actual message forms, seed, producers, consumers and client reuse. Do not invent named domain events or claim event sourcing/exactly-once delivery. |
| 3.2 Physical Architecture & Design | [Views §3](../docs/architecture/views.md#3-physical-architecture-aws-ap-southeast-1); [AWS explainer](../showcase-prep/aws.html); [persistent AWS topology](../showcase-prep/assets/aws-topology.svg); [CloudFormation template](../deploy/aws/v1/template.json); AD-27. | **Source ready with current-state qualification.** Map components to AWS services, networking, storage and deployed modes. The topology is a dated explanatory snapshot; use release evidence for deployment claims. |
| 3.2.1 Key Architectural Decisions | [Decision register](../docs/architecture/decisions.md), especially AD-10, AD-12–20, AD-23, AD-25 and AD-27. | **Source ready.** Explain Lambda containers, Aurora, finite Fargate tasks, S3, CloudFront, IAM, network choices and persistent operation. |
| 3.2.2 Technology and Services | [Views §3.2](../docs/architecture/views.md#32-services-used-and-why); [handoff AWS service table](../docs/release/engineering-handoff.md#existing-aws-services-and-their-jobs); [Python dependencies](../pyproject.toml); [frontend tooling](../frontend/package.json). | **Source ready.** Explain purpose and trade-offs, including Python/FastAPI/SQLAlchemy, browser JavaScript, FFmpeg, PostgreSQL and managed AWS services. Separate runtime dependencies from development tools. |
| 3.2.3 Persistence Design | [Views §4](../docs/architecture/views.md#4-persistence-design); [catalogue data lifecycle](../docs/architecture/use-case-design.md#data-lifecycle-security-and-limits); [data explainer](../showcase-prep/data.html); [Media migrations](../media/migrations/versions/); [Processing migrations](../processing/migrations/versions/). | **Partial synthesis.** Schema, transactions, concurrency, object versioning and many retention settings exist. Assemble the template's data inventory/classification, formats, storage, access controls, retention and trade-offs. Explicitly state the unspecified active-media, account and audit/tombstone purge policies; do not invent periods. |
| 3.2.4 Detailed Design | [Catalogue](../docs/architecture/use-case-design.md), shared analysis/design classes, mapping and grouped sequences; [code explainer](../showcase-prep/code.html); [representative upload sequence](../docs/architecture/views.md#5-representative-use-case-upload-process-play). | **Source ready for GC2 representative cases.** Use upload-to-play plus retry or safe release. Connect classes/functions, invariants, exceptional flows and named tests. See section 5 for the stricter GC1 per-use-case diagram gap. |
| 3.3 Other Architectural Decisions | [Decision register, deviations and inconsistencies](../docs/architecture/decisions.md); [catalogue design-problem bundles](../docs/architecture/use-case-design.md#three-design-problem-bundles). | **Source ready.** Cross-reference decisions explained elsewhere instead of duplicating rationale. Include accepted simplicity/cost trade-offs and legacy quarantine where relevant. |
| 3.4 Architectural Limitation | [Decision register §6](../docs/architecture/decisions.md#6-architectural-limitations); [handoff limits](../docs/release/engineering-handoff.md#honest-limits-and-likely-questions); [results](../docs/results/actual-vs-target.md); this handover's gap list. | **Partial.** The template labels this section optional but recommends it. Existing limitations lack a consolidated issue/impact/resolution/owner/status table and any agreed future dates. Add confirmed dispositions or explicitly mark them undecided. |

### Section 4 Quality Attributes

| Template item | Where to find the material | Status and authoring instruction |
|---|---|---|
| 4.1 Performance | Proposal §3.4 targets; [actual vs target, Scaling and Performance](../docs/results/actual-vs-target.md); [evidence index](../docs/evidence-index.md); [manifest acceptance rows](../docs/release/demo-release-manifest.md#acceptance-rows); [quality explainer](../showcase-prep/quality.html). | **Evidence available with misses.** Preserve workload, environment, source, units and timing boundary. Explain six-clip V1 scaling, nine-clip fixed-cap V2-live evidence, the cap-2 miss and ~37 s queue wait against 20 s. |
| 4.2 Availability | [Results, Availability](../docs/results/actual-vs-target.md#availability); catalogue messaging/lease/release fences; [AD-11, AD-12 and AD-27](../docs/architecture/decisions.md); [DLQ runbook](../docs/execution/aws/v1/dlq-runbook.md). | **Partial evidence.** Explain recovery mechanisms and their measured limits. One Aurora cluster/instance is a shared failure boundary. A configured backup is not a demonstrated restore; no multi-AZ failover or uptime SLA is established by the retained worker tests. |
| 4.3 Security | [Security evidence index](../docs/evidence-index.md#security-controls-proposal-section-33); [manifest](../docs/release/demo-release-manifest.md); [engineering handoff](../docs/release/engineering-handoff.md); [security explainer](../showcase-prep/security.html); [CI](../.github/workflows/ci.yml) and [DAST workflow](../.github/workflows/dast.yml). | **Evidence available with scope limits.** Explain owner trust, private storage, bounded upload grants, IAM, hashing, TLS, diagnostics, SAST/dependency/image/secret scanning and authenticated DAST. Sonar was unconfigured; DAST findings are report-only and its route coverage is limited. Newer CD scan failure is open. “Zero fixable HIGH/CRITICAL at a dated scan” never means no vulnerabilities. |
| 4.4 Extensibility and Maintainability | [DDD](../docs/architecture/ddd.md); [contracts policy](../contracts/README.md); [Publisher](../publisher/); [handoff testing/maintainability](../docs/release/engineering-handoff.md#testing-quality-and-maintainability); [verification results](../docs/release/engineering-handoff.md#current-engineering-validation-and-delivery); catalogue design bundles. | **Source ready; effort claim incomplete.** Explain stable boundaries, reusable contracts/helpers, independent capacity/release, tests, shared credential rules and dependency cleanup. Coverage gains are measured for named tiers. Publisher's public-contract boundary is tested; the two-person-day build-effort target was not measured. |

### Sections 5 and 6

| Template item | Where to find the material | Status and authoring instruction |
|---|---|---|
| 5.1 Source Control Strategy | [Repository map](../README.md); [contract change policy](../contracts/README.md); current Git/PR history; [workflow sources](../.github/workflows/); [delivery explainer](../showcase-prep/delivery.html). | **Partial.** Repository layout, PR activity and automation are evidenced. Write the actual current branch/review/release strategy. Confirm developer authentication/access and any enforced protections; no current consolidated policy establishing MFA, required reviewers or promotion authority was found. Historical Project 1 branch policy is not current proof. GitHub-to-AWS OIDC is automation authentication, not developer login evidence. |
| 5.2 Continuous Integration | [CI workflow](../.github/workflows/ci.yml); [verification selection](../scripts/ci/policy.py); [V1 workflow](../.github/workflows/v1.yml); [CI scripts](../scripts/ci/); [tests](../tests/); [delivery explainer](../showcase-prep/delivery.html); handoff validation section. | **Source ready.** Document PR, Main push, manual and weekly triggers; selected versus full lanes; lint/style, unit/integration/browser tests, coverage tiers, security tools, image checks and source-bound artifacts. Include the evidence from the exact run cited. |
| 5.3 Continuous Delivery | [CD workflow](../.github/workflows/cd.yml); [CD script](../scripts/ci/cd.sh); [CI admission gate](../scripts/ci/cd_gate.py); [deploy runbook](../docs/execution/aws/v1/deploy-runbook.md); [release receipt](../docs/results/engineering-20261020/delivery-629119c.json); section 2 above. | **Partial status and governance.** Explain one persistent AWS environment plus local/CI verification, successful Main-push admission, immutable images, owner promotion, smoke and restore. The workflow automatically promotes qualifying changes; do not invent a manual approval gate or staging environment. Confirm who controls merges/manual operations and describe the current failed run. |
| 6 Other things to be highlighted | [Engineering handoff](../docs/release/engineering-handoff.md); [course crosswalk](course-evidence-checklist.md); evidence index and selected source links. | **Optional assembly.** Suitable additions are the GC1→GC2 contribution summary, lessons from failures, evidence index and any course-required AI-use declaration. Check the current declaration requirement before claiming one is mandatory or complete. |

## 4. Gaps and the smallest useful next action

These are audit findings, not new feature requests. “Partial evidence” means the final report must
state the limitation unless a new, attributable experiment establishes more.

| ID | Gap | Smallest useful action | Where it belongs |
|---|---|---|---|
| G1 | Latest Main application CD is blocked by a fixable HIGH/CRITICAL finding on the retained Media image scan. | Inspect the exact failing scan and baseline identity; resolve the release path while retaining the security gate; retain successful release, smoke and image read-back receipts. No fix or cloud mutation was made in this audit. | Report §§2.2, 4.3, 5.3; source links in section 2 above. |
| G2 | Actual per-member effort and contribution are not established by the allocation table. The ledger also counts report/presentation effort while their final artifacts remain pending. | Each member confirms rough actual hours, work and dates; distinguish estimated, allocated, completed and remaining work. Record Publisher-specific effort only if a defensible record exists. | §2.3; [effort ledger](effort-ledger.md); [#191](https://github.com/Collaboration95/dc2/issues/191). |
| G3 | Project 1 provenance wording is inconsistent: the ledger names Ibrahim in FlickPond track A but says Project 2 continues no member's own Project 1. | Confirm the factual team history. Attribute inherited code to its original team; keep each member's own Project 1 effort separate from new GC2 work. | §§1.1 and 2.3; handoff and ledger. |
| G4 | Current source-control authentication and governance are not fully documented. | Record the real developer login/access method, branch/review practice, and authority for merges/manual promotions. Claim enforcement only if verified. | §§5.1 and 5.3. |
| G5 | Data classification and retention are distributed across sources; some policies do not exist. | Consolidate accounts/authentication, source videos, jobs/attempts, outputs, messages, secrets and operational logs into the template's data-group format. Record actual formats/controls and explicitly unspecified retention. | §3.2.3. |
| G6 | Known limitations are not collected with resolution, owner, status and agreed future dates. | Build a short disposition table from the actual limits and open issues. Mark accepted scope limits and unassigned future work honestly; do not invent owners or deadlines. | Optional §3.4. |
| G7 | Several proposal targets have incomplete or failing evidence. | Report the actual values and changed workload. If the team chooses a new experiment, preserve the old result and add the new source, configuration, fixture, timing boundary and receipt. | §§2.2 and 4; detailed evidence cautions below. |
| G8 | Progress-report submission, current cutoffs, peer assessment and any required AI-use declaration have no verified completion receipt in the inspected sources. | Obtain the actual course instructions and submission/assessment confirmations through the team. A prepared document or an issue is not a receipt. | [#257](https://github.com/Collaboration95/dc2/issues/257); final submission checklist. |
| G9 | Presentation feedback and final report assembly are pending. | Use this map to author the current template; collect actual remarks after 26 October and incorporate them before submission. | [#193](https://github.com/Collaboration95/dc2/issues/193); briefing p. 6. |
| G10 | Recording access and a replacement team-accepted freeze are not established by the study site. | Verify the actual demo/backup recording and team access; explicitly record the release the team will present. | [#254](https://github.com/Collaboration95/dc2/issues/254), [#192](https://github.com/Collaboration95/dc2/issues/192), manifest and delivery receipt. |

Evidence cautions for G7:

- **Scalability:** AWS V1 used six clips, one run per cap; cap 2 achieved 1.449× against 1.6×,
  while cap 3 achieved 2.347× against 2.1×. The proposal's 30-clip AWS comparison was not run.
  V2-live's nine clips at fixed cap 3, 239 seconds and 2.26 jobs/min do not supply a 1/2/3 comparison.
- **Queue latency:** the retained V2-live result is about 37 seconds against a 20-second target.
  Explain the recorded startup trade-off without asserting an unmeasured optimization fixed it.
- **Release time:** the later release step took 9m39s, but release plus the separate upload smoke
  took 15m38s. Do not report an unqualified “release plus smoke under ten minutes.” See DP-1–DP-6
  in [actual vs target](../docs/results/actual-vs-target.md#deployability).
- **Recovery:** the retained worker-kill cloud result establishes reaction time, not every
  retry/duplicate-output criterion. The lost-queue-entry 120-second AWS bound was not measured;
  the idle-marker caveats remain. A one-day backup setting is not a restore test.
- **Security and rollback:** earlier cloud negative checks and deliberate bad-candidate rollback
  retain their original source identities. The successful `629119c` smoke is not a repeat of the
  complete negative/rollback suite. Local DAST is not an assessment of all public AWS edge behavior.
- **Reuse/cost:** zero service imports and zero database credentials are tested; a two-person-day
  client implementation or percentage effort saving is not established. One observed Aurora
  pause is not a measured monthly bill.

## 5. Additional gaps against the adopted GC1 bundle

This matters because the user explicitly asked to carry the original `course_files_export.zip`
engineering expectations forward. The current GC2 template asks for representative detailed
design; the older SWE5006 template asks for a more exhaustive presentation of models.

| Original SWE5006 requirement | Existing material | Remaining qualification or gap |
|---|---|---|
| Report §3.2: transition strategies covering affected analysis objects/use cases, static and dynamic changes and rationale. | Catalogue “Analysis-to-design mapping,” class models, grouped sequences and design bundles. | Substantial content exists. Make the affected UC mapping explicit when reusing it as a GC1 appendix; the current catalogue is a shared model, not a separately completed template for each strategy. |
| §3.3.1: overall UML use-case diagram including in-scope and out-of-scope cases. | Persona/UC catalogue, scope JSON, platform/context diagrams. | No dedicated current use-case diagram satisfying that exact prompt was located. A context or deployment diagram is not a substitute. Add it only as documentation, or record this adopted-checklist gap. |
| §3.4: each in-scope use case has analysis and design class diagrams plus sequences for each major flow; each member has a named case. | Seven descriptions, two shared class models and six grouped analysis/design sequence views in the catalogue. | The grouped views do not literally establish a separate complete diagram set for every UC and major exceptional flow. Explicitly map or expand them and obtain real member ownership if claiming full compliance with the older format. |
| §3.5: each member has a design problem, alternatives, and before/after class and sequence diagrams. | Three real design-problem bundles with alternatives, structural/behavioral explanations, decisions and tests. | Per-bundle before/after diagram sets are not separately supplied. Suggested explanation owners are not verified authors. Do not claim GoF-pattern selection or historical diagrams that were never produced. |
| Briefing slide 6 and progress template: backlog/stories, sprint plans, burndown, review and retrospective artifacts. | GitHub history, proposal/roadmap and inherited Project 1 material. | No verified current GC2 burndown/retrospective package was found. Locate real retained artifacts or disclose absence. Do not reconstruct past ceremonies or label Project 1 records as GC2 records. |
| Named use-case/pattern responsibility, actual metrics and individual contribution summary. | Ledger specialisms and allocation; suggested bundle owners. | Member confirmation is still needed. This overlaps G2/G3 rather than creating new engineering work. |

The current [course evidence checklist](course-evidence-checklist.md) correctly labels the
catalogue integrated/source-backed. That label should not be expanded into “every literal GC1
template sub-deliverable is complete.” GC1 sample proposals add no requirements. GC1 dates,
grading weights and presentation timings must not replace the GC2 originals.

## 6. Diagram and evidence source map

| Report use | Source to reuse | Qualification |
|---|---|---|
| Business participants and scope | Proposal Figures 1–2; [personas/scope](../project-roadmap/business-scope.json); [study basics](../showcase-prep/basics.html). | Proposal and scope JSON are planning history; use the catalogue for implemented behavior. |
| DDD context map | [DDD model](../docs/architecture/ddd.md); [rendered context map](../docs/architecture/img/ddd-context-map.svg). | Explain actual commands/results, ownership and shared contracts. |
| Logical tiers | [Views](../docs/architecture/views.md); [logical SVG](../docs/architecture/img/views-logical.svg). | V1-labelled diagram; explain persistent V2 operation separately. |
| Current persistent AWS explanation | [AWS chapter](../showcase-prep/aws.html); [topology SVG](../showcase-prep/assets/aws-topology.svg); AD-27 and CloudFormation source. | Source snapshot is 20 October; no fresh live topology read-back in this audit. |
| Persistence | [Media ER](../docs/architecture/img/views-er-media.svg), [Processing ER](../docs/architecture/img/views-er-processing.svg), catalogue lifecycle table. | Two logical databases and roles share one Aurora cluster. |
| Analysis/design and sequences | Mermaid blocks in [use-case catalogue](../docs/architecture/use-case-design.md). | Two shared class models and six grouped sequences; see the GC1 format gaps above. |
| CI/CD | [Delivery chapter](../showcase-prep/delivery.html), [diagram/content source](../showcase-prep/content/delivery.json), actual workflows/scripts. | Study diagrams explain the process; cited run evidence establishes whether a particular execution passed. |
| Quality graphs/tables | [Actual vs target](../docs/results/actual-vs-target.md); [evidence index](../docs/evidence-index.md); [manifest](../docs/release/demo-release-manifest.md); [engineering handoff](../docs/release/engineering-handoff.md). | Preserve source/environment labels and misses. Retain original receipts alongside any new visualization. |
| Complete successful engineering delivery | [Delivery receipt for `629119c`](../docs/results/engineering-20261020/delivery-629119c.json). | Dated historical success; newer CD issue is described in section 2. |

The public [study guide](https://collaboration95.github.io/dc2/) is the easiest reading path.
Its [architecture](https://collaboration95.github.io/dc2/architecture.html),
[AWS](https://collaboration95.github.io/dc2/aws.html),
[delivery](https://collaboration95.github.io/dc2/delivery.html) and
[questions](https://collaboration95.github.io/dc2/questions.html) pages help with explanation.
They are study material pinned to a reviewed source snapshot, not a continuously updated live
status page. The local [site README](../showcase-prep/README.md) records the snapshot and build steps.

## 7. Sources that need careful handling

- [Older report outline](../project-roadmap/design/08-build-readiness/report-outline.txt) is a
  planning skeleton. Its “not collected” placeholders do not prove that later evidence is absent.
- [Report-template notes](original-reference/report-template-notes.md) are an older interpretation,
  not a report. They include stale checkout assumptions.
- [Sprint 1 report](../docs/sprint1-report.md), [Sprint 2 report](../docs/sprint2-report.md),
  [Project 1 history](../docs/history/README-project1-and-pre-aws-local-stack.md) and `CLAUDE.md`
  contain inherited material. Preserve that attribution.
- The effort ledger's progress paragraph still mentions `daee44b` and open #271. The engineering
  handoff records the later missing-upload `409` fix and `629119c` delivery. Do not repeat #271
  as an unfixed current defect merely because it remains in that historical paragraph.
- Historical rows in the evidence index/results still describe their own earlier verification
  gaps, including #229. Later manifest receipts establish additional checks at later sources;
  they do not retrospectively alter what an old run tested.
- The architecture index says AD-01–AD-26, while the decision document also includes **AD-27**.
  Read that persistent-environment decision before describing booked sessions as current operation.
- Old plans describe peer HTTP/service tokens and Redis/RQ; current native AWS uses SQS with
  SQL outbox/inbox and Media-issued trusted identity. Keep the proposal's figures as evolution
  evidence, not the current architecture diagram.
- The inspected `Downloads/report.pdf` belongs to Plotline, and
  `Downloads/progress-report-document.docx` belongs to Rewind/Team 14. Neither is the missing
  Team 17 GC2 final report or its progress-submission receipt.
- Do not republish course PDFs, private meeting access, credentials, signed URLs or raw deployment
  journals as part of report-support web material. Use the public study guide's existing sanitized
  guidance and the repository's redacted evidence.

## 8. Suggested authoring order

1. Read the current template, then proposal §§1 and 3. Select the exact source/release that the
   report will describe; keep the newly failed CD visible until its disposition is known.
2. Obtain actual contribution/effort and provenance confirmations. Confirm current source-control
   access/governance facts. These cannot be recovered reliably from code alone.
3. Write §§1 and 3 using the DDD model, decision register, views and catalogue. Include the
   persistence data inventory and make proposal-to-as-built changes explicit.
4. Write §4 from the results and retained receipts. Carry forward misses and evidence limits.
   Write §5 from the actual workflows and one successful dated delivery, plus the latest status.
5. Complete §2 with actual milestones, member-confirmed metrics and current outstanding work.
   Decide whether the additional GC1 diagram appendix is being completed or disclosed as partial.
6. After the showcase, add real presentation feedback and resulting changes. Verify submission
   details, supporting artifact access and the final report against every row in section 3.

Audit method: inspected the original DOCX text/tables, GC2 briefing and presentation PDFs
(including rendered schedule/outline pages), the original attached SWE5006 templates/briefing,
the submitted proposal, current documentation and workflow/script sources. A separate read-only
review checked the requirement mapping. GitHub issue/run status and the failed CD log/public
artifact were read through `gh`; Canvas and AWS live state were not checked. Validation found
all 124 local source links and 22 Markdown heading anchors valid, with all 29 mapped template
rows present exactly once. No application code, existing documentation, GitHub resources or
cloud resources were changed. Leave this file uncommitted as requested.

## 9. Resolution in the final report (21 October 2026)

| ID | Disposition | Where |
|---|---|---|
| G1 | Root cause: the retained Media rollback image (`629119c`) carried GHSA-6q48-6c7w-9gw2 in certifi 2026.7.22, published after it shipped; the candidate fixed it. AD-28 records fixable findings on a *replaced* rollback image instead of blocking; candidates and kept images stay strict. PRs #285 and #286; redelivery recorded in the engineering handoff. | Report §§2.2, 4.3, 5.3; `docs/architecture/decisions.md` AD-28 |
| G2 | The team-agreed equal split stands as the attribution of record (33 pd recorded, 36 pd forecast at submission, 12 pd per member). The report states that git history has one account and cannot attribute work. | Report §2.3; effort ledger |
| G3 | Resolved in the ledger: FlickPond was Ibrahim Mammadov's Project 1 team (track A); a different team's project for the other two; no Project 1 feature work continued. | Report §1.1; effort ledger "Project 1 effort" |
| G4 | Documented from the GitHub API: one collaborator account, no branch protection or rulesets, `aws` environment branch policy without reviewers, OIDC with an immutable subject. Recorded as AISS-09 with the recommended ruleset. | Report §§5.1, 5.3, 3.4 |
| G5 | Data inventory in the template's data-group format with a four-level classification; configured retention values; unspecified retention stated explicitly (AISS-12). | Report §3.2.3 |
| G6 | AISS-01 to AISS-15 with issue, description, resolution, owner (by specialism), status and a course/post-course timeline. | Report §3.4 |
| G7 | Every target reported with its actual value, environment and verdict; misses kept. | Report §4 |
| G8 | Canvas receipts, peer assessment and the final upload stay with #257 (owner Guruprasath Gopal); the report carries an AI tool declaration. | Report §§2.2, 6.5 |
| G9 | Report v1.0 assembled; the post-presentation feedback step is written down in the report README. | `final-report/README.md` |
| G10 | The demo presents the team-accepted freeze `daee44b` and the later verified engineering release; recordings stay with #254. | Report §2.2 |
| GC1 | Added a use-case diagram (in and out of scope), a per-use-case traceability matrix with responsible members, analysis-to-design transition table, and before/after views for each design problem. Implemented sequences stay in the catalogue because they are too wide to print. | Report §§1.4, 7.1–7.3 |
