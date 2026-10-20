# Course engineering evidence checklist

Engineering evidence crosswalk, not a final report, deck or submission receipt. The design and
engineering changes are integrated in the candidate branch. See the
[engineering handoff](../docs/release/engineering-handoff.md) for current verification and delivery;
the accepted persistent V2-live fallback remains `daee44b` until a replacement release is verified.

## Authority and status labels

- The attached `course_files_export.zip` is SWE5006/Designing Modern Software Systems material.
  The user adopts its engineering-completeness checklist for this package, including the detailed
  analysis/design views and three design-problem bundles below.
- Current GC2 dates, formats and scope remain governed by the repository's current
  [GC2 briefing interpretation](briefing-requirements.txt), [Team 17 proposal](Team17-Proposal.docx),
  [current report template](original-reference/02%20Project%20Report%20Template%20for%20Practice%20Project.docx)
  and [presentation guide/schedule](original-reference/04%20Project%20Presentation%20Guidelines%20%26%20Schedule.pdf).
  The attached older template's weights, dates and outline do not replace them.
- The attached sample proposals are examples only. They add no Flickpond business features, platforms,
  performance targets, security commitments or team roles.
- **Completed / source-backed:** the artifact or retained evidence exists; this does not mean it was
  freshly re-run in this task or that later live cloud state was checked.
- **Submission-phase deferred:** reusable engineering evidence exists or the gap is recorded, but
  final report/deck/demo assembly is left to the course submission phase.
- **Human-confirmation required:** a member, course owner or submission receipt must establish the
  fact. Do not infer it from commits, tool activity or an estimate.
- **Candidate verification:** implementation exists on the engineering branch; the handoff records
  its exact test, image, scan and delivery status. This label does not imply a cloud deployment.

## Attached engineering deliverables

| Deliverable in attached SWE5006 briefing/template | Evidence and state | Handoff / limit |
|---|---|---|
| Working system and source repository | **Completed / source-backed.** The [release manifest](../docs/release/demo-release-manifest.md) records the accepted `daee44b` freeze; the repository and workflows are present. | Manifest read-back is dated 20 Oct; it does not establish later live state. This documentation commit is not deployed. |
| Business need, stakeholders, scope and quality scenarios | **Completed / source-backed.** Proposal and current use-case catalogue use Maya, Arun, Jules and Sam; see [use-case and design catalogue](../docs/architecture/use-case-design.md). | Personas are fictional planning assumptions, not interview evidence. Team content ownership remains personal; no student/LMS sharing, tenant model or third client is implied. |
| High-level architecture, platform and key decisions | **Completed / source-backed.** Reuse [DDD model](../docs/architecture/ddd.md), [views and persistence diagrams](../docs/architecture/views.md), [AD register](../docs/architecture/decisions.md) and the grouped implementation views in the new catalogue. | Existing detailed logical/physical views describe V1; the new catalogue labels persistent V2-live differences instead of relabeling the older views. |
| Analysis-to-design transition, all in-scope use cases and normal/important exceptional flows | **Integrated / source-backed.** One conceptual class model, one implemented design class model, seven use-case descriptions, shared mapping and grouped analysis/implementation sequences are in [the catalogue](../docs/architecture/use-case-design.md). | Acceptance references point to actual test functions; the handoff identifies executed suites and their source. The attached per-use-case/per-member format is engineering completeness, not the current GC2 report's required outline. |
| Three design-problem bundles with alternatives, before/after, behavior, decisions and tests | **Integrated / source-backed.** The catalogue covers bounded cloud capacity/release, SQL outbox/inbox messaging, and trusted owner identity/public contracts. | Guruprasath, Ibrahim and Nguyen are listed only as suggested review/explanation owners based on recorded specialisms. No original authorship is verified or assigned here. |
| Database schemas and data lifecycle | **Completed / source-backed.** Reuse the linked [Media ER diagram](../docs/architecture/img/views-er-media.svg) and [Processing ER diagram](../docs/architecture/img/views-er-processing.svg); lifecycle, deletion, retention and unknowns are summarized in the catalogue. | Two logical databases share one Aurora cluster. Configured one-day backups do not establish a restore drill; no general retention deadline for active media is documented. |
| Quality attributes, security, reuse and operational limits | **Completed / source-backed evidence; final synthesis deferred.** See [measured results](../docs/results/actual-vs-target.md), [evidence index](../docs/evidence-index.md), [release manifest](../docs/release/demo-release-manifest.md) and [architecture limitations](../docs/architecture/decisions.md). | Preserve environment, source SHA, workload and verdict. Do not promote a test to AWS proof, infer a cause without measurement, or hide an accepted miss. |
| Well-structured code and tests for complex behavior | **Completed / source-backed.** Runtime modules and targeted tests are linked per UC; CI and test selection are in `.github/workflows/ci.yml` and the repository test tree. | The candidate adds required integration discovery, shared credential policy, a bounded asset query, safe diagnostics, dependency cleanup and consistent formatting. Use the handoff for actual test and coverage results. |
| DevOps design, source control, pipeline/test scripts and minimal security | **Completed / source-backed; final narrative deferred.** `.github/workflows/`, `scripts/ci/`, `scripts/aws/`, architecture decisions and retained CI/CD receipts provide the implementation evidence. | Exact per-image scan details for `daee44b` are unknown in the manifest; the CD smoke JSON was not re-read. DAST findings are report-only. Candidate CI admission and scan gates have passing offline counterexamples; see the handoff for actual candidate scans and hosted CI. |
| Backlog, stories, plans, burndown, reviews and retrospectives | **Mixed.** GitHub issue/project history, proposal scope, dated roadmap and milestone evidence exist; earlier Project 1 records remain labeled inherited. | The attached briefing explicitly names plans, burndown, sprint review and retrospective. No current verified burndown/retrospective package was found in the inspected repository. During submission authoring, use only real retained artifacts; if none exist, disclose the gap. Do not reconstruct Scrum, TDD, pairing or past reviews. |
| WBS, named use-case/pattern owner, milestones and individual effort | **Submission-phase deferred / Human-confirmation required.** The [effort ledger](effort-ledger.md) records specialisms, milestones and equal work-package allocation. | Its 33 person-days / 264 hours and 11 pd / 88 h per person are team-agreed allocation, not timesheets. Confirm each member's actual contribution, any Project 1 hours and who will explain each design bundle. |
| Readable presentation, working demo/recording, report and progress submission | **Submission-phase deferred; receipt/access is Human-confirmation required.** Current GC2 artifacts remain the report and presentation originals linked above; issues #192, #193, #254 and #257 track close-out. | The frozen manifest says no recording identifier is attached. Verify recording access, current Canvas cutoffs, peer-assessment instructions, the 16 Oct progress-report receipt and final AI-use declaration through the team/course owner. Do not use the older SWE5006 dates, timing or grading weights. |

The attached deliverable sources are the SWE5006 briefing slides 5–6; report template sections
Introduction, Project Conduct and System Design (including the transition strategy, each use case,
analysis/design views, one design problem per member and schema); the progress template; and its
presentation guide. These came from the user-supplied `course_files_export.zip` (not republished
in this repository), SHA-256 `fec5e4dc9fd2d40af96fdda8f5bcf59a88e2fe8f3a73000390cbb3aac385858c`.
The three sample proposals are examples, not additional project requirements.

## Current GC2 outcome cross-check

| Current GC2 outcome / Team 17 commitment | Recorded result | Evidence and caveat |
|---|---|---|
| Working platform/business ecosystem and reusable application | **Implemented and retained.** Media and Processing boundaries, public API and Publisher client exist. | [`README.md`](../README.md), [`Team17-Proposal.docx`](Team17-Proposal.docx), Publisher tests. The second client is the proposal commitment; no portal or third client is implied. |
| Cloud-native platform using suitable services | **Implemented and retained.** Persistent `dc2-live`, API Gateway, Lambda, SQS, Aurora PostgreSQL, S3, CloudFront and finite Fargate workers are recorded. | [Manifest source identity](../docs/release/demo-release-manifest.md#release-identity). One region, one Aurora cluster/instance and one shared capacity/failure boundary; not a high-availability proof. |
| Independently vary Processing capacity and demonstrate scalability | **Partial with honest misses.** V1 AWS 6-clip run: 1.449× at two workers (**FAIL** against 1.6×), 2.347× at three (**PASS** against 2.1×). V2-live: 9 clips, fixed cap 3, 2.26 jobs/min in one run; no 1/2/3 comparison. | [Results §Scaling](../docs/results/actual-vs-target.md#scaling), [manifest](../docs/release/demo-release-manifest.md#acceptance-rows). The proposal's 30-clip AWS protocol was not run; V1 and V2-live are separate. |
| Quality and recovery | **Partial.** V2-live queued-to-processing was about 37 s against 20 s; the exact frozen source's duplicate-work recheck passed 9/9 jobs in one burst. | [Manifest acceptance rows](../docs/release/demo-release-manifest.md#acceptance-rows), [results](../docs/results/actual-vs-target.md). The 20 s miss stands; one burst is not a broad reliability guarantee. |
| Scripted development, security and deployment automation | **Implemented, with evidence limits.** Exact `daee44b` CI succeeded on rerun and its CD deploy run succeeded. | [Manifest](../docs/release/demo-release-manifest.md#source-verification). Exact image scan details are unknown; exact-source bad-candidate rollback was not run. One earlier-source CD rollback passed. Candidate verification is recorded separately in the engineering handoff. |
| Minimum scope-appropriate security | **Controls and retained checks exist; exact-source coverage is partial.** Owner checks, private/versioned storage, scoped roles, TLS and negative checks are documented. | AWS #229 checks ran before the final `daee44b` deploy; #271 is a frozen-release finalize `503` limitation after an S3-refused oversize body. The candidate returns `409` for a missing object and adopts no source; storage outages remain `503`. See [manifest limitations](../docs/release/demo-release-manifest.md#known-limitations-and-open-issues). |
| Current course report, presentation and records | **Submission-phase deferred / human confirmation required.** This engineering reference is not the final report or deck. | Follow the current GC2 originals and verify Canvas dates/receipts. Attached SWE5006 material provides engineering completeness guidance only. |

## Human and submission handoff

- Confirm actual individual contribution and hours with each member. Keep the effort ledger's
  allocation basis separate from timesheets and from the inherited Project 1 team's work.
- Ask each suggested bundle owner to confirm the explanation they can defend. A suggestion based on
  a recorded specialism is not proof of design or code authorship.
- Confirm current course/Canvas deadlines, peer assessment, progress-report receipt, presentation
  recording access and required AI-use declaration through the authorized team/course process.
- The engineering handoff records verification and release status. All eight design diagrams have
  rendered successfully and their code references were refreshed. Keep the frozen release distinct
  from the engineering candidate until delivery is verified.

## Source map

- Attached SWE5006/GC1 engineering material: the briefing deck, report template, progress template,
  presentation guidelines and three sample proposals in `course_files_export.zip` identified above.
- Current GC2 source set and authority: [project-documentation index](README.md),
  [briefing requirements](briefing-requirements.txt), [current template](original-reference/02%20Project%20Report%20Template%20for%20Practice%20Project.docx),
  [current presentation guide](original-reference/04%20Project%20Presentation%20Guidelines%20%26%20Schedule.pdf)
  and [submitted Team 17 proposal](Team17-Proposal.docx).
- Current evidence set: [architecture](../docs/architecture/README.md),
  [evidence index](../docs/evidence-index.md), [results](../docs/results/actual-vs-target.md),
  [release manifest](../docs/release/demo-release-manifest.md) and
  [effort ledger](effort-ledger.md).
