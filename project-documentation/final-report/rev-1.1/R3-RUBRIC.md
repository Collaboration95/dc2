# R3 — Rubric, structure, length and tone review

Reviewed 10 November 2026 (SGT), Team 17 FlickPond, NUS SWE5001. **Overall: PARTIAL — revise before submission.**

**Checklist: 149 PASS / 27 PARTIAL / 1 FAIL (177 rows). Proposed net cut: about 7,000 words (20.0%), from 35,081 to about 28,081 Markdown whitespace words.** Counts cover the matrices in §§1–5 below; aggregate requirements and detailed member/UC/DP/TR cross-checks deliberately overlap and are not independent marks. A1 rechecks and structural findings are separately reported, not added to those counts.

## Scope, authority and evidence

Read-only review of all 19 filename-ordered `src/*.md` files in `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-report`, HEAD `b7227a3a2a6d3285de1683e0c0cded5091b994ab`. Combined source fingerprint (filename + NUL + bytes + NUL, sorted): `fa928eba31634457c09418ce6a52015a1064485a1527e018cc3d0cb8a13f832d`. Existing modified DOCX and other reviewers’ outputs were left alone. Only `rev-1.1/R3-RUBRIC.md` is written.

Requirements were checked against the supplied scratchpad `project-template-dc2.txt` and verbatim `coverage-list.md`, `briefing-requirements.txt`, original `project-documentation/original-reference/01 Briefing.pdf` (text extracted read-only), `FEEDBACK.md`, A1 and AUTHORING-GUIDE. T/U/B/F IDs retain A1 traceability; its old statuses and locations are superseded here. F17–F24 include derived audit follow-ups, not eight additional assessor quotations. The 14 actual response rows in §6.1 cover all oral/written comments and the team’s routing question. No requirement for ALB, MongoDB migration, cloud DAST or more application code is inferred.

PASS means the report materially covers the requirement; it does not mean every experiment target passed, source claim was re-tested, recording is shareable or Canvas upload occurred. Administrative completion not evidenced is PARTIAL, with a private coordinator action rather than a demand to publish private records. Model PASS covers report presence, selected PlantUML content/flows and per-case cross-mapping; exhaustive model correctness and print readability belong to model/figure QA. No build, application test, AWS operation, GitHub access, checkout, commit or push was run.

File locators below are relative to `project-documentation/final-report/src/` unless stated otherwise. Figures and assets resolve from the report root, as the build expects.

## 1. Every template heading and its substantive guidance

| ID | Requirement | Status | File — section heading / evidence | Exact fix when not PASS |
|---|---|---|---|---|
| T-00 | Project title, practice module, team number and member names; contents | PARTIAL | 00-front.md — Cover / CONTENTS | Keep v1.1; label 16 November as the due/submission date and 10 November as the review snapshot, or date the cover at actual finalization. Rebuild and refresh CONTENTS after the final source edits; the current DOCX is not exact-source verified. |
| T-1 | Introduction | PASS | 10-introduction.md — Introduction | — |
| T-1.1 | Background, context and current project status | PASS | 10-introduction.md — Background | — |
| T-1.2 | Business needs and drivers | PASS | 10-introduction.md — Business Needs | — |
| T-1.3 | Key business and IT stakeholders | PASS | 10-introduction.md — Stakeholders | — |
| T-1.4 | Overall scope; phases; architected versus implemented scope and references | PASS | 10-introduction.md — Project Scope | — |
| T-1.4.1 | Functionality in scope / requirements | PASS | 10-introduction.md — Functionality in scope | — |
| T-1.4.2 | Functionality out of scope | PASS | 10-introduction.md — Functionality out of scope | — |
| T-2 | Project Conduct | PARTIAL | 20-conduct.md — Project Conduct | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| T-2.1 | Rough WBS tasks and estimated effort | PASS | 20-conduct.md — Project Plan | — |
| T-2.2 | Current status and outstanding issues | PASS | 20-conduct.md — Project Status | — |
| T-2.3 | Actual milestones and rough effort per member | PARTIAL | 20-conduct.md — Project Metrics / Effort per member — agreed allocation and forecast | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| T-3 | Solution Overview | PARTIAL | 30-logical.md — Solution Overview | Resolve S4–S6 below: primary-output and release-transport descriptions conflict; AD-29 is repeated as a full decision. Preserve all substantive template headings. |
| T-3.1 | Logical decomposition; static/dynamic relationships; element types and providers | PASS | 30-logical.md — Logical Architecture & Design | — |
| T-3.1.1 | Significant logical decisions with identifiers, alternatives, trade-offs and rationale | PASS | 30-logical.md — Key Architectural Decisions | — |
| T-3.1.2 | Tiers and layers, or explicit alternative organization | PASS | 30-logical.md — Tiers and Layers | — |
| T-3.1.3 | Nodes/subsystems and decomposition responsibilities | PASS | 30-logical.md — Nodes and Subsystems | — |
| T-3.1.4 | Platform design: entities, bounded contexts, aggregates, events; producer/consumer interactions | PASS | 30-logical.md — Platform Design | — |
| T-3.2 | Physical network, technology, nodes/machines, deployment and cloud services | PASS | 32-physical.md — Physical Architecture & Design | — |
| T-3.2.1 | Physical decisions with continued, unique identifiers and rationale | PASS | 32-physical.md — Key Architectural Decisions | — |
| T-3.2.2 | Technology/cloud service purpose, trade-offs and rationale | PASS | 32-physical.md — Technology and Services | — |
| T-3.2.3a | Persistence management, transactions/concurrency and logical data model | PASS | 34-persistence-detailed.md — Persistence Design / Transactions and concurrency | — |
| T-3.2.3b | Which data persists beyond transaction/session, and duration | PASS | 34-persistence-detailed.md — What persists, and for how long | — |
| T-3.2.3c | Data inventory/classification; per-group formats, technology/rationale, security, trade-off | PASS | 34-persistence-detailed.md — Information architecture: data inventory and classification | — |
| T-3.2.4 | Detailed classes/objects/functions for representative use cases | PASS | 34-persistence-detailed.md — Detailed Design; 62–64 — Analysis and Design Models | — |
| T-3.3 | Other significant decisions, rationale or references | PASS | 36-other-limitations.md — Other Architectural Decisions | — |
| T-3.4 | Architectural limitations, impact, description, resolution, owner, status; timeline beyond plan | PASS | 36-other-limitations.md — Architectural Limitation | — |
| T-4 | Quality Attributes | PASS | 40-quality.md — Quality Attributes | — |
| T-4.1 | Performance tactics: caching, distribution, optimization | PASS | 40-quality.md — Performance | — |
| T-4.2 | Availability tactics and requirements | PASS | 40-quality.md — Availability | — |
| T-4.3 | Security services/controls: IAM, encryption, hashing, detection/prevention as relevant | PASS | 40-quality.md — Security | — |
| T-4.4 | Extensibility/maintainability; future enhancement and platform linkage | PASS | 40-quality.md — Extensibility and Maintainability | — |
| T-5 | DevOps and Development Lifecycle | PARTIAL | 50-devops.md — DevOps and Development Lifecycle | Name the promotion authority and reconcile branch-protection wording as in S3. |
| T-5.1 | Source/artifact structures, repositories, branches, developer authentication | PARTIAL | 50-devops.md — Source Control Strategy | Replace the unqualified future promise “Main branch protection will require…” with the dated settings fact and actual team PR practice; Project Status and AISS-04 state no enforcement. |
| T-5.2 | CI triggers, jobs, tests and integration pipeline | PASS | 50-devops.md — Continuous Integration | — |
| T-5.3 | CD environments, promotion approver and deployment verification | PARTIAL | 50-devops.md — Continuous Delivery | In Promotion approval, name the responsible member/role (the retained allocation names Guruprasath for cloud/delivery), who authorizes the Main merge, and state that subsequent qualifying CD is automatic with no second reviewer gate. Obtain confirmation before attributing a new approval policy. |
| T-6 | Other things to highlight (open placeholder) | PASS | 60-other.md — Other Things to Be Highlighted | — |

## 2. Every user coverage item and tone/format rule

| ID | Requirement | Status | File — section heading / evidence | Exact fix when not PASS |
|---|---|---|---|---|
| U-01 | Agile backlog | PASS | 20-conduct.md — Product backlog | — |
| U-02 | User stories | PASS | 20-conduct.md — User stories | — |
| U-03 | Sprint plans | PASS | 20-conduct.md — Iterations and sprint-plan summaries / Iterations 1–5 | — |
| U-04 | Burndown | PASS | 20-conduct.md — Burndown, burnup and issue reduction | — |
| U-05 | Reviews | PASS | 20-conduct.md — Iterations 1–5, Review paragraphs | — |
| U-06 | Retrospectives | PASS | 20-conduct.md — Iterations 1–5, Retrospective paragraphs (prepared 10 Nov) | — |
| U-07 | High-level design/software architecture | PASS | 30-logical.md — Logical Architecture & Design; 32-physical.md — Physical Architecture & Design | — |
| U-08 | Explicit analysis-to-design transition | PARTIAL | 61-use-case-model.md — Analysis-to-Design Transition Strategies | Correct TR-6’s Planner/CLITransport mapping to the current release collaborators and OperatorTransport; tie to the UC-7 class/sequence models. See S5. |
| U-09 | Detailed analysis/design for each scoped UC | PASS | 62–64-ad-*.md — Analysis and Design Models, UC-1–UC-7 | — |
| U-10 | Design problems solved with patterns, detailed discussion | PASS | 65–67-dp-*.md — Design Problems and Patterns, DP-1–DP-3 | — |
| U-11 | Well-structured code | PASS | 30-logical.md — Tiers and Layers; 40-quality.md — Extensibility and Maintainability | — |
| U-12 | Unit tests for complex classes/behavior | PASS | 40-quality.md — Unit tests for complex classes and modules / Test inventory and coverage gates | — |
| U-13 | DevOps pipeline design, appropriate tools, basic security | PASS | 50-devops.md — Continuous Integration / Continuous Delivery; 40-quality.md — Security | — |
| U-14 | Project Plan names responsible person for each UC's analysis AND design | PASS | 20-conduct.md — Responsibility for analysis and design | — |
| U-15 | Project Plan names person for each design problem | PASS | 20-conduct.md — Responsibility for analysis and design | — |
| U-16 | Each transition lists affected analysis objects | PASS | 61-use-case-model.md — TR-1–TR-6, Analysis objects rows | — |
| U-17 | Each transition lists affected use cases | PASS | 61-use-case-model.md — TR-1–TR-6, Use cases rows | — |
| U-18 | Each transition states class-diagram changes | PARTIAL | 61-use-case-model.md — TR-1–TR-6, Class-diagram changes rows | Correct TR-6’s Planner/CLITransport mapping to the current release collaborators and OperatorTransport; tie to the UC-7 class/sequence models. See S5. |
| U-19 | Each transition states sequence-diagram changes | PASS | 61-use-case-model.md — TR-1–TR-6, Sequence-diagram changes rows | — |
| U-20 | Each transition explains reasons | PASS | 61-use-case-model.md — TR-1–TR-6, Reason rows | — |
| U-21 | Use-case diagram includes in-scope AND out-of-scope | PASS | 61-use-case-model.md — Use Case Model, ucm-scope | — |
| U-22 | Each in-scope UC described with normal AND exception flows | PASS | 62–64-ad-*.md — each UC Description | — |
| U-23 | Every member has ≥1 named UC | PASS | 20-conduct.md — Responsibility for analysis and design; 62–64 UC headings | — |
| U-24 | Per UC: analysis class diagram | PASS | 62–64-ad-*.md — each UC Analysis class diagram | — |
| U-25 | Per UC: analysis sequence for EVERY major flow | PASS | 62–64-ad-*.md — each UC Analysis sequence diagrams | — |
| U-26 | Per UC: design class diagram | PASS | 62–64-ad-*.md — each UC Design class diagram | — |
| U-27 | Per UC: design sequence for EVERY major flow | PASS | 62–64-ad-*.md — each UC Design sequence diagrams | — |
| U-28 | Every member has ≥1 named design problem | PASS | 65–67-dp-*.md — DP-1/2/3 owned headings | — |
| U-29 | Each DP: problem statement | PASS | 65–67-dp-*.md — The problem | — |
| U-30 | Each DP: problem CLASS diagram | PASS | 65–67-dp-*.md — The problem, dp1/2/3-problem-class | — |
| U-31 | Each DP: problem SEQUENCE diagram | PASS | 65–67-dp-*.md — The problem, dp1/2/3-problem-sequence | — |
| U-32 | Each DP: candidate patterns | PASS | 65–67-dp-*.md — Candidate patterns | — |
| U-33 | Each DP: rationale for chosen pattern | PASS | 65–67-dp-*.md — Why the chosen pattern | — |
| U-34 | Each DP: solution CLASS diagram | PASS | 65–67-dp-*.md — Solution models / Solution class and sequence diagrams | — |
| U-35 | Each DP: solution SEQUENCE diagram | PASS | 65–67-dp-*.md — Solution models / Solution class and sequence diagrams | — |
| U-36 | Each DP: implementation decisions | PASS | 65–67-dp-*.md — Implementation decisions | — |
| U-37 | Database schema | PASS | 34-persistence-detailed.md — Persistence Design, typed ERs / full dictionaries | — |
| U-38 | Source control strategy | PARTIAL | 50-devops.md — Source Control Strategy | Replace the unqualified future promise “Main branch protection will require…” with the dated settings fact and actual team PR practice; Project Status and AISS-04 state no enforcement. |
| U-39 | CI pipeline | PASS | 50-devops.md — Continuous Integration, devops-ci | — |
| U-40 | CD environments | PASS | 50-devops.md — Continuous Delivery, environment table | — |
| U-41 | Who approves promotion | PARTIAL | 50-devops.md — Continuous Delivery, Promotion approval | In Promotion approval, name the responsible member/role (the retained allocation names Guruprasath for cloud/delivery), who authorizes the Main merge, and state that subsequent qualifying CD is automatic with no second reviewer gate. Obtain confirmation before attributing a new approval policy. |
| U-42 | How deployment is verified | PASS | 50-devops.md — Deployment verification, six steps | — |
| U-43 | Each member's contribution summary | PASS | 68-contributions.md — Per-Member Contribution Summary | — |
| U-44 | Incorporate presentation comments | PASS | 60-other.md — Presentation Feedback and Response | — |
| U-45 | Tone: no over-self-criticism; major pivots only; no exhaustive plan/build confession | PARTIAL | 36-other-limitations.md — Architectural Limitation; 50-devops.md — Recorded deliveries; repeated evidence disclaimers in 62–67 | Apply the sentence replacements in the tone table and remove repeated target misses outside Quality Attributes. Preserve neutral measured misses and necessary source/scope labels. |
| U-46 | Personas website and presentation GIFs/clips may be reused (permission, not obligation) | PASS | 10-introduction.md — Stakeholders / User journey evidence; 70-appendices.md — Supporting Assets | — |
| U-47 | Markdown sources first; linked images | PASS | src/*.md in filename order; image links resolve from final-report/ | — |
| U-48 | Major burndown/sprint-planning/issue-reduction figures inline | PARTIAL | 20-conduct.md — Burndown, burnup and issue reduction / Iterations and sprint-plan summaries | Keep burndown and issue-reduction panels inline; add an inline planning timeline for the five documented iterations with dates, goals and leads, marked reconstructed from the proposal/worklog. The current three figures show issue state, not the iteration plan. |
| U-49 | UI/UX images in assets/ and linked as assets/filename | PASS | 10-introduction.md — User journey evidence; 70-appendices.md — Supporting Assets | — |

## 3. Every briefing requirement, including original-PDF additions

| ID | Requirement | Status | File — section heading / evidence | Exact fix when not PASS |
|---|---|---|---|---|
| B-01 | Use Team17-Proposal.docx for team-specific scope/commitments | PASS | 10-introduction.md — Background / Project Scope; 20-conduct.md — Project Plan | — |
| B-02 | Working distributed application | PASS | 30-logical.md — Logical Architecture & Design; 50-devops.md — Recorded deliveries | — |
| B-03 | Scalability demonstrated by repeatable measurements | PASS | 40-quality.md — Quality Attributes / Performance (six-clip AWS 1/2/3 comparison; local 30×3 repeats) | — |
| B-04 | Cloud-native design with appropriate cloud capabilities/services | PASS | 32-physical.md — Technology and Services | — |
| B-05 | Cloud hosting alone is not cloud-native evidence | PASS | 32-physical.md — Physical Architecture & Design; 68-contributions.md — What Team 17 Contributed | — |
| B-06 | ≥1 working web/mobile frontend | PASS | 10-introduction.md — User journey evidence; 50-devops.md — upload-to-playback smoke | — |
| B-07 | Demonstrate one integrated system | PASS | 50-devops.md — Recorded deliveries; 10-introduction.md — User journey evidence | — |
| B-08 | Reusable platform preferred, not mandatory | PASS | 10-introduction.md — Business Needs / Project Scope | — |
| B-09 | Show Architecting Software Solutions, Platform Engineering, Cloud Native competencies | PASS | 30-logical.md — Architecture views table; chapters 3–5 | — |
| B-10 | Business problem, decisions and quality attributes | PASS | 10-introduction.md — Business Needs; chapters 3–5 | — |
| B-11 | For a platform: seed, producers, consumers, reusable capabilities | PASS | 30-logical.md — Platform producers and consumers | — |
| B-12 | Evidence for reuse and cloud-native benefits | PASS | 40-quality.md — Reusability result / Extensibility and Maintainability; Performance lane comparison | — |
| B-13 | Explain selected cloud services/infrastructure | PASS | 32-physical.md — deployment, artifact/entrypoint table / Technology and Services | — |
| B-14 | Automate development/deployment through DevOps pipeline | PASS | 50-devops.md — Continuous Integration / Continuous Delivery | — |
| B-15 | Submit pipeline scripts AND test scripts | PARTIAL | 50-devops.md — Source Control Strategy, tests/ and workflows; 68-contributions.md — Evidence and How to Reproduce It | Add a final submission manifest identifying report version, source archive/repository SHA, pipeline and test script locations and accessible demonstration material. Record the upload receipt when submitted; source coverage alone does not establish submission. |
| B-16 | Minimum security appropriate to scope | PASS | 40-quality.md — Security | — |
| B-17 | Prioritize scalability/cloud-native/integrated delivery over extra security features | PASS | 10-introduction.md — Functionality out of scope; 40-quality.md — Security | — |
| B-18 | Reuse earlier project encouraged, optional | PASS | 10-introduction.md — Background | — |
| B-19 | Separate current contribution from inherited capabilities | PASS | 10-introduction.md — inherited/new table; 68-contributions.md — What Team 17 Contributed | — |
| B-20 | Domain analysis/DDD justifies microservice boundaries | PASS | 30-logical.md — Platform Design / Deriving the bounded contexts | — |
| B-21 | Microservices/Kubernetes/autoscaling/provider not course-mandated | PASS | 10-introduction.md — Project Scope / Functionality out of scope | — |
| B-22 | Explain how scope demonstrates scalability, cloud-native, platform and DevOps | PASS | 30-logical.md — Architecture views; 40-quality.md — results; 50-devops.md — CI/CD | — |
| B-23 | Logical architecture sufficient at proposal stage if deployment undecided | PASS | 30-logical.md — Solution Overview; 36-other-limitations.md — proposal decisions | — |
| B-24 | Proposal details can change while core requirements remain | PASS | 36-other-limitations.md — Other Architectural Decisions | — |
| B-25 | Each member's effort separately for earlier and current projects | PARTIAL | 20-conduct.md — Effort per member — agreed allocation and forecast | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| B-26 | Progress reports: completed work, hours/member, problems, next two weeks | PARTIAL | 20-conduct.md — milestones; 36-other-limitations.md — D-06 | Reference the actual dated Team 17 progress report (title/date, completed tasks, member hours, problems, next two weeks) and submission record. Retain D-06’s approved one-report exception; reconstructed iteration reviews do not establish the progress submission. |
| B-27 | Assigned team slot and current Canvas date/time/Zoom | PASS | 20-conduct.md — Project Status / Milestones planned against actual (presented 26 Oct) | — |
| B-28 | Actual milestones and member effort in presentation/final report | PARTIAL | 20-conduct.md — Project Metrics | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| B-29 | Presentation: average current-project effort and BOTH-project effort | FAIL | 20-conduct.md — Effort per member — agreed allocation and forecast | Add member-confirmed mean actual Project 2 effort and mean combined Project 1+2 effort, with consistent units and a reference to the presentation metric. Project 1 totals and both averages are absent; equal allocations are not actual averages. |
| B-30 | Original p.5 deliverables: working system, codebase, report incl. decisions/quality/DevOps, scripts/tests | PARTIAL | 00-front.md — repository; 50-devops.md — scripts/tests; 68-contributions.md — reproduction | Add a final submission manifest identifying report version, source archive/repository SHA, pipeline and test script locations and accessible demonstration material. Record the upload receipt when submitted; source coverage alone does not establish submission. |
| B-31 | p.6: ~10 person-days/member; milestones/proposal review/progress/presentation; final report by 16 Nov incorporating remarks | PARTIAL | 20-conduct.md — Project Plan / milestone table; 60-other.md — Presentation Feedback and Response | Feedback integration and deadline are covered; close the actual-effort and final-submission facts in B-28/B-30. Do not claim 16 November submission from its planned date. |
| B-32 | p.7: form team, enroll in Canvas, source suitable approved project, submit proposal in PM Project Proposals | PARTIAL | 10-introduction.md — Background (three-member approval, accepted proposal) | Keep the approved three-member exception; coordinator confirms Canvas team enrollment and proposal-submission receipt privately. No need to add a fourth member or publish private Canvas records. |
| B-33a | p.8 proposal: title, sponsor if applicable, members | PASS | 00-front.md — cover; 10-introduction.md — Stakeholders (no external sponsor) | — |
| B-33b | p.8 proposal: problem/context, general architecture, platform roles/use cases and demonstration plan, WBS estimate | PASS | 10-introduction.md — Background / Scope; 20-conduct.md — Project Plan; chapters 3–5 | — |
| B-34 | p.9 questions: pain point, ecosystem, reuse benefits, supported scale/proof, technical/nontechnical benefits, cloud value, automation effort, feasibility | PASS | 10-introduction.md — Business Needs; 30-logical.md — Platform Design; 40-quality.md — results; 50-devops.md — CI/CD | — |
| B-35 | p.13 peer assessment: rank contributions uniquely by deadline; effort hours are not contribution ranking | PARTIAL | 20-conduct.md — Project Status, Remaining close-out | Coordinator confirms each member completed unique contribution ranks by the course deadline through the private peer-grading system. Keep ranks private; do not use hours as the ranking. Current report calls the receipt pending. |
| B-36 | p.14 fortnightly Canvas progress report incl. project title/date, work done, each member hours, problems and next-2-week plan | PARTIAL | 36-other-limitations.md — D-06; 20-conduct.md — milestone table | Reference the actual dated Team 17 progress report (title/date, completed tasks, member hours, problems, next two weeks) and submission record. Retain D-06’s approved one-report exception; reconstructed iteration reviews do not establish the progress submission. |
| B-37 | p.3 all-three modules/DevSecOps competency; p.12 assessments | PASS | 30-logical.md — Architecture views; chapters 3–5; original briefing pp.3–4/12 | — |

## 4. Every presentation remark and A1 feedback follow-up

| ID | Requirement | Status | File — section heading / evidence | Exact fix when not PASS |
|---|---|---|---|---|
| F1 | “Report → Slide 20”, “More detailed”: expand client workflow | PASS | 34-persistence-detailed.md — Detailed Design; 62-ad-ibrahim.md — UC-1 | — |
| F2 | Authorizer tied to API Gateway | PASS | 30-logical.md — Public request and identity boundary, arch-authorizer; 67-dp-long.md — DP-3 | — |
| F3 | Editing does not go directly to SQS | PASS | 34-persistence-detailed.md — Edit-derived intake, data-edit-sequence | — |
| F4 | How bounded contexts are grouped | PASS | 30-logical.md — Deriving the bounded contexts | — |
| F5 | How aggregates are grouped | PASS | 30-logical.md — Media/Processing domain model and invariants / Supporting consistency boundaries | — |
| F6 | Detailed DDD diagrams with entities; revisit PE | PASS | 30-logical.md — Platform Design, typed Asset/intake/Job figures | — |
| F7 | Component-level detailed design | PASS | 30-logical.md — Tiers and Layers, two component figures | — |
| F8 | Class diagrams for 1–2 critical UCs; revisit SAD/SDP | PASS | 62-ad-ibrahim.md — UC-1/UC-2 Design class diagram | — |
| F9 | Class/object-level sequence diagrams for critical UCs | PASS | 62-ad-ibrahim.md — UC-1/UC-2 Design sequence diagrams | — |
| F10 | Database schemas and data model | PASS | 34-persistence-detailed.md — Persistence Design / dictionaries / JSONB / SQS / objects | — |
| F11 | Revisit ARCHSS diagrams; more perspectives, e.g. deployment | PASS | 30-logical.md — Architecture views; 32-physical.md — Physical Architecture & Design | — |
| F12 | Physical design does not explain load balancing | PASS | 32-physical.md — AD-30 / Load distribution and execution admission | — |
| F13 | Consider NoSQL/MongoDB | PASS | 32-physical.md — AD-31 / Technology and Services | — |
| F14 | SAST not visible in pipeline | PASS | 50-devops.md — Verification and security stages, Ruff S / CodeQL | — |
| F15 | DAST not visible in pipeline | PASS | 50-devops.md — Dynamic security (DAST); 40-quality.md — seven-route ZAP scope | — |
| F16 | Team: where/how Lambda versus Fargate is decided | PASS | 32-physical.md — Dispatch / Short executor admission / Fenced redirect / Standard capacity | — |
| F17 | Derived optional expansion of cloud DAST/finding gate | PASS | 40-quality.md — Dynamic checks; 50-devops.md — DAST disposition (findings advisory, local target) | — |
| F18 | Derived reconciliation of diagrams/configuration | PASS | 32-physical.md — component table, 11 Lambdas / 4 queue-DLQ pairs / 15 alarms / Worker artifact | — |
| F19 | Derived source/version/mode provenance of figures | PASS | 30-logical.md — evidence labels; 32-physical.md — source-configuration versus historical receipt captions | — |
| F20 | Briefing: incorporate actual presentation remarks | PASS | 60-other.md — Presentation Feedback and Response, all 14 response rows | — |
| F21 | Course follow-up: working demo/quality demonstrations | PARTIAL | 10-introduction.md — User journey evidence; 70-appendices.md — Supporting Assets | Frames and provenance are present, but durable shared recording access remains pending in Project Status. Add accessible D1–D5 recording links, source/date/timecodes and final access confirmation to the submission manifest; no new demo run is required for this review. |
| F22 | Derived security gate/vulnerability-policy accuracy | PASS | 50-devops.md — scanner inventory / exact-source admission / retained-image exception | — |
| F23 | Course follow-up: current status, milestones, rough effort | PARTIAL | 20-conduct.md — Project Status / Project Metrics | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| F24 | Derived slide ER layering/readability issue | PASS | 34-persistence-detailed.md — six separate schema figures; no presentation layering in report | — |

## 5. Explicit member, use-case, design-problem and transition checks

Each UC row checks all five named model/specification deliverables separately in its cited subsections. Each DP row checks all eight requested components. Combined normal/exception sequence diagrams satisfy the flow requirement when their alternatives are explicit; separate images for every exception are unnecessary.

| ID | Requirement | Status | File — section heading / evidence | Exact fix when not PASS |
|---|---|---|---|---|
| M-GG | Guruprasath Gopal: named analysis/design owner, ≥1 complete UC and ≥1 DP; contribution summary | PASS | 64-ad-guru.md; 65-dp-guru.md — named UC/DP headings; 20-conduct.md — Responsibility; 68-contributions.md — Guruprasath Gopal | — |
| M-IM | Ibrahim Mammadov: named analysis/design owner, ≥1 complete UC and ≥1 DP; contribution summary | PASS | 62-ad-ibrahim.md; 66-dp-ibrahim.md — named UC/DP headings; 20-conduct.md — Responsibility; 68-contributions.md — Ibrahim Mammadov | — |
| M-NKL | Nguyễn Kim Long: named analysis/design owner, ≥1 complete UC and ≥1 DP; contribution summary | PASS | 63-ad-long.md; 67-dp-long.md — named UC/DP headings; 20-conduct.md — Responsibility; 68-contributions.md — Nguyễn Kim Long | — |
| UC-1 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including registration/login/refusal; reserve/upload/finalize; replay, changed/expired/missing bytes and owner refusal | PASS | 62-ad-ibrahim.md — UC-1, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-2 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including accept/duplicate/conflict; claim/encode/finish; optional HLS failure, admission redirect, lease loss and stale execution | PASS | 62-ad-ibrahim.md — UC-2, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-3 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including status/playback; missing/foreign/terminal states; result replay/order/conflict; expired access and absent HLS | PASS | 63-ad-long.md — UC-3, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-4 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including public retry and successor; replay/wrong state/owner; retry-before-submit; stale worker/result fences | PASS | 62-ad-ibrahim.md — UC-4, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-5 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including batch loop; per-file success/failure; auth/transport uncertainty, polling exhaustion, pending key/accepted-ID retention | PASS | 63-ad-long.md — UC-5, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-6 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including wake/observe/reserve/commit/send; no demand/disable; concurrent wakes, unreadable inventory and ambiguous RunTask | PASS | 64-ad-guru.md — UC-6, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| UC-7 | Description + analysis class + analysis sequence(s) + design class + design sequence(s), including exact-source admission, promote/smoke/adopt; reject/restore/restore-failed, alias drift, lost publication reply and later-smoke boundary | PASS | 64-ad-guru.md — UC-7, Description / Analysis class diagram / Analysis sequence diagrams / Design class diagram / Design sequence diagrams / Analysis to design | — |
| DP-1 | Problem statement; problem class; problem sequence; candidate comparison; chosen-pattern rationale; solution class; solution sequence; implementation decisions/tests | PASS | 65-dp-guru.md — DP-1, The problem / Candidate patterns / Why the chosen pattern / Solution models / Implementation decisions | — |
| DP-2 | Problem statement; problem class; problem sequence; candidate comparison; chosen-pattern rationale; solution class; solution sequence; implementation decisions/tests | PASS | 66-dp-ibrahim.md — DP-2, The problem / Candidate patterns / Why the chosen pattern / Solution models / Implementation decisions | — |
| DP-3 | Problem statement; problem class; problem sequence; candidate comparison; chosen-pattern rationale; solution class; solution sequence; implementation decisions/tests | PASS | 67-dp-long.md — DP-3, The problem / Candidate patterns / Why the chosen pattern / Solution models / Implementation decisions | — |
| TR-1 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PASS | 61-use-case-model.md — TR-1 | — |
| TR-2 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PASS | 61-use-case-model.md — TR-2 | — |
| TR-3 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PASS | 61-use-case-model.md — TR-3 | — |
| TR-4 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PASS | 61-use-case-model.md — TR-4 | — |
| TR-5 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PARTIAL | 61-use-case-model.md — TR-5 | Replace “one primary MP4” with “one primary output (MP4 by default; MKV/MP3 for conversion); HLS is optional for eligible unedited input”. |
| TR-6 | Affected analysis objects, UCs, class changes, sequence changes and reasons | PARTIAL | 61-use-case-model.md — TR-6 | Replace release Planner/CLITransport executor wording with the UC-7 current release functions, Journal and OperatorTransport; see S5. |
| BQ-1 | Original briefing p.9 question 1: Pain points | PASS | 10-introduction.md — Business Needs | — |
| BQ-2 | Original briefing p.9 question 2: Platform ecosystem, reusable services/libraries | PASS | 30-logical.md — Platform Design / Tiers and Layers | — |
| BQ-3 | Original briefing p.9 question 3: Benefits of a new use case on the platform and demonstration | PASS | 40-quality.md — Extensibility and Maintainability / Reusability result | — |
| BQ-4 | Original briefing p.9 question 4: Supported scale and proof | PASS | 40-quality.md — scaling results / Performance | — |
| BQ-5 | Original briefing p.9 question 5: Technical and nontechnical benefits and evidence | PASS | 10-introduction.md — Business Needs; 40-quality.md — results (effort not timed) | — |
| BQ-6 | Original briefing p.9 question 6: Cloud-native value and demonstration | PASS | 32-physical.md — services / AD-30; 40-quality.md — idle/startup and lane measurements | — |
| BQ-7 | Original briefing p.9 question 7: Lifecycle automation and effort reduction | PASS | 50-devops.md — CI/CD (automated steps evidenced; no quantified developer saving claimed) | — |
| BQ-8 | Original briefing p.9 question 8: Implementation effort within guideline | PARTIAL | 20-conduct.md — Project Plan / Effort per member | Obtain each member’s rough actual Project 2 effort through the report snapshot, in hours/pd (8 h/pd); retain the October allocation and forecast only as comparators. Add each member’s Project 1 total and the two required averages. Do not turn forecasts into actuals. |
| BC-1 | Original pp.4/12 assessment context: project/exam weighting, separate pass thresholds, certificate/stacking rules | PASS | Briefing pp.4/12; report cover identifies the module. These are student administration, not additional report headings. | — |
| BC-2 | Original pp.10–11 example projects are examples, not FlickPond requirements | PASS | 10-introduction.md — Project Scope; no mandated e-wallet, travel platform or analytics inferred | — |

## 6. Recheck of every A1 P0/P1 priority

These are revision dispositions, separate from the checklist totals. A1's opening “absent” claims describe the older source and must not be copied forward as current findings.

| A1 opening item | Status now | Current evidence and remaining exact fix |
|---|---|---|
| 1 — P0 actual feedback/response table | PASS | `60-other.md` — Presentation Feedback and Response: 14 rows cover written comments, oral notes and the team's decision-location question. |
| 2 — P0 per-member and all-UC bundles | PASS | `62/63/64` — seven UC sections, named owners, conceptual and implemented class/sequence models and normal/exception descriptions. Keep these in the cut plan. |
| 3 — P0 all three DP bundles | PASS | `65/66/67` — each problem has separate problem class/sequence and solution class/sequence figures, candidates, rationale and implementation decisions. DP-1 legitimately references UC-7 for its release sub-scenario. |
| 4 — P0 detailed DDD and boundary derivation | PASS | `30-logical.md` — Platform Design: capability/vocabulary/consistency derivation; Asset/Job/Attempt/value models; independent User/reservation/guard lifecycle explanation. |
| 5 — P0 real class/module/object design | PASS | `30-logical.md` — component views; `62–64` — typed implemented records and real function/module collaborations. The old empty common model is not embedded. |
| 6 — P0 edit acceptance before relay | PASS | `34-persistence-detailed.md` — Edit-derived intake: copy, pin, Asset/SourceVersion/optional RequestKey/outbox transaction, separate relay and inbox; response ordering correctly qualified. |
| 7 — P0 Gateway/lane/capacity/image/count truth | PASS | `30-logical.md` — Gateway hook; `32-physical.md` — dispatch/admission/redirect/capacity, Worker artifact supplies both encoders, four queues/DLQs and separate 3+2 bounds. Historical three-queue receipts remain dated. |
| 8 — P0 typed schemas and message/object shapes | PASS | `34-persistence-detailed.md` — six typed schema figures, 22-table dictionary, constraints/indexes, JSONB, all message kinds and object namespaces. |
| 9 — P1 visible SAST/DAST | PASS | `50-devops.md` — CI figure and inventory identify Ruff S, CodeQL, ZAP, dependency/image/IaC tools, triggers and advisory versus blocking results; `40-quality.md` scopes the seven local GETs. |
| 10 — P1 dated status, presentation, v1.1 cover | PARTIAL | `20-conduct.md` now records the presentation as completed and the latest failed CI. Cover version is fixed, but `00-front.md:26` uses the future 16 Nov without saying due/submission. Apply T-00; refresh final DOCX after integration. |
| 11 — P1 named UC/DP responsibility in Project Plan | PASS | `20-conduct.md` — Responsibility for analysis and design has all seven UCs and three DPs, all assigned by full name. |
| 12 — P1 current-project Agile evidence | PARTIAL | Backlog, stories, issue burndown, dated reconstructed iteration plans/reviews/retrospectives are present and honestly labelled. Add the requested inline iteration-planning visual (U-48). Do not relabel reconstruction as historical Scrum ceremonies. |
| 13 — P1 confirmed effort/contributions/demo/submission facts | PARTIAL | `68-contributions.md` now gives member output summaries; `20-conduct.md` retains allocations/forecasts, lacks earlier-project totals and averages, and calls recording/submission/peer receipts pending. Apply B-25/26/28/29/30/35/36 and F21. |
| 14 — P1 preserve required model/chart budget | PARTIAL | Analysis models and all per-member problem/solution sets are present. U-48 still needs a planning visual. Preserve the required issue-reduction view when consolidating redundant charts. |

A1 P0/P1 disposition: **10 PASS / 4 PARTIAL / 0 FAIL**. A1 item 15 (P2) is also substantively addressed: AD-30 explains distribution/no ALB; AD-31 compares PostgreSQL/JSONB, MongoDB and DynamoDB. No implementation migration is required.

## 7. Structure, references, stale content and draft synchronization

### S1 — Heading hierarchy and section 6: PASS with one navigational cleanup

All 19 sources were scanned in filename order. No level jump exceeds one, no heading is empty, and no orphaned continuation was found. `32-physical.md` continues section 3.2; `34-persistence-detailed.md` correctly starts with level-3 Persistence Design within 3.2. `63/64` continue 6.4 at level 3 and `66/67` continue 6.5 at level 3. The hierarchy is a property of the concatenated report; these continuation files need no artificial parent heading.

Section 6 has exactly these level-2 headings, in order:

| Number | Exact heading | Source |
|---|---|---|
| 6.1 | Presentation Feedback and Response | `60-other.md:13` |
| 6.2 | Use Case Model | `61-use-case-model.md:1` |
| 6.3 | Analysis-to-Design Transition Strategies | `61-use-case-model.md:25` |
| 6.4 | Analysis and Design Models | `62-ad-ibrahim.md:1` |
| 6.5 | Design Problems and Patterns | `65-dp-guru.md:1` |
| 6.6 | Member Contributions and Lessons Learned | `68-contributions.md:1` |

`60-other.md:8` shortens 6.3 to “Transition Strategies”; replace that menu item with “6.3 Analysis-to-Design Transition Strategies” to match the actual heading. It still points to the correct subsection. Repeated child headings (“Description”, “Analysis class diagram”, “The problem”) are scoped to different UCs/DPs; the two “Key Architectural Decisions” headings are explicitly required by the template. These are not duplicate sections. The template's blank `##` and section-6 placeholder are not required literal headings. AD-29, however, is repeated as a full decision row; see S6.

The DOCX contains all six subsection names as Heading2. This confirms their structural presence, not final page/TOC readability. Do not type section numbers into Markdown headings: the build uses template numbering.

### S2 — Figure labels, image paths and assets: PASS

Automated scan of the reviewed source found:

- 83 unique `{#fig:...}` definitions; every `{@fig:...}` resolves; zero duplicate labels.
- 84 inline image occurrences: 83 captioned figures plus the cover logo. There are 90 image links to `figures/` counting the seven supporting diagrams linked rather than embedded. Thus “about 90 figures” is a reasonable inventory description, but not the number of numbered inline figures.
- All Markdown inline images and relative Markdown link destinations exist when resolved from the report root. No referenced image is missing.
- UI/persona links use `assets/filename`, including the one inline playback image. Architecture diagrams use `figures/filename`. Seven unique PNG assets and the register are referenced; repeated asset links in Introduction and Supporting Assets are valid.

No conversion/re-render was performed. File existence and model-source inspection do not certify legibility at printed size. The existing R4 figure lane owns that final check.

### S3 — Material approval/governance inconsistency: PARTIAL

`50-devops.md:30–31`, Source Control Strategy, says **“Main branch protection will require a pull request and the ‘Full verification’ check.”** `36-other-limitations.md`, AISS-04, states that the 10 November audit found no Main protection or aws reviewer rule. The future promise is unresolved in a final-state description and implies an implementation commitment not established here.

Replace it with: **“At the 10 November settings audit, Main had no enforced branch-protection rule. The team used PR review and successful Full verification before promotion; eligible Main-push CI then admitted automatic CD.”** In Continuous Delivery — Promotion approval, identify the authorized Main approver by member/role, consistent with confirmed cloud/delivery responsibility. Do not turn the author's review recommendation into a claimed GitHub setting.

### S4 — Output-format contradiction carried into transition prose: PARTIAL

`61-use-case-model.md:87`, TR-5, says output validation **“requires one primary MP4”**. `34-persistence-detailed.md`, JSONB value schemas / Object storage, permits primary MKV or MP3 for conversion and specifies HLS for unedited inputs. This is an internal contradiction, regardless of whether the normal upload case uses MP4.

Replace the TR-5 sentence with: **“Successful finish requires one validated primary output, MP4 by default or MKV/MP3 for conversion; HLS is optional for eligible unedited inputs.”** Preserve the simple normal-flow MP4 description in UC-2, or explicitly prefix it “For an unedited upload”.

### S5 — Transition strategy names the old release transport: PARTIAL

`61-use-case-model.md:95,99`, TR-6, maps cloud execution to `Planner`/`CLITransport.call`. `64-ad-guru.md`, UC-7 — Design class diagram, explicitly states that `OperatorTransport.call` is the current AWS execution port and `CLITransport` is restricted to planning/emulator execution. Both cannot describe the same execution role.

Replace the class-change cell with: **“Map capacity to LauncherControl and LaunchReservation. Map release coordination to release.promote/restore, durable intent to Journal/DeployJournal, deployment adoption to deploy.adopt_release, and AWS operations to OperatorTransport.”** Replace the final paragraph's executor claim with: **“release.promote and restore execute per-owner changes through OperatorTransport; Journal retains intent, and deploy.adopt_release records the accepted deployment baseline. CLITransport is used for planning/emulator execution.”** Cross-reference UC-7's three design figures. Do not add a fictional runtime Planner role simply because a proof harness has a class with that name.

### S6 — Duplicate decision and imprecise boundary description: PARTIAL

`36-other-limitations.md:16` repeats AD-29 already fully documented in `32-physical.md` — Key Architectural Decisions. Replace the second full row with a one-line cross-reference, or delete it since the section already promises only remaining decisions. Preserve one canonical AD-29, its date, rationale and rehearsal evidence in 3.2.1.

`66-dp-ibrahim.md:27` groups **“Envelope, Source and Actor … across the boundary”** in a queue-handoff paragraph. `30-logical.md` correctly says Actor is trusted API context and not part of the queue envelope. Replace this sentence with: **“Envelope and Source carry message identities and source values; Actor represents trusted HTTP request identity. IAM and queue policies establish message-producer authority.”** The ambiguity should not survive compression.

### S7 — Old use-case chapter/version/schedule and cross-references: PASS with corrections above

No v1.0 cover, old October cover date, future “scheduled presentation”, duplicated old Use-Case Specifications chapter or shared empty analysis/design appendix remains in the concatenated source. `70-appendices.md` contains Glossary, Use-Case Traceability Matrix and Supporting Assets only. Historical V1 versus V2-live and October dates identify actual phases/receipts and should remain.

Report section references 3.1.4 (Platform Design), 3.2.1 (physical decisions), 3.2.2 (Technology and Services), 3.2.3 (Persistence Design), 4.1–4.4 and 5.2–5.3 resolve to the right headings. Section 6.2/6.4/6.5 references target the new use-case/model/pattern homes. Proposal references such as “proposal §3.5” and architecture-document “§4” are external document sections, not broken report numbering. Fix the shortened 6.3 menu name in S1, and the TR-6 conceptual crosswalk in S5. Plain code-path mentions are not guaranteed hyperlinks; the local-link existence result applies to actual Markdown links.

### S8 — DOCX source identity remains PARTIAL

The built DOCX reports v1.1, contains all new chapter-6 headings and has no TOC-PLACEHOLDER. It contains 85 `word/media/` entries and about 32,056 extracted whitespace words; the Markdown count is 35,081 because table delimiters, paths and markup tokenize differently. These word/image totals alone do **not** establish missing chapters or draft drift. Its three conduct-chart captions match the current source.

A stronger byte comparison found that the current inline `figures/arch-media-components.png` SHA-256 is absent from the DOCX embedded-media set, whereas the other 83 inline image occurrences have matching bytes. This is evidence that the current component figure is not embedded verbatim; it may reflect an older figure or build-time transformation. Rebuild from the final source and record that build's source/asset hashes, then inspect the component view and final CONTENTS/page layout. This review did not mutate/rebuild the draft or certify exact-source/rendered parity.

## 8. Specific cut/merge plan: about 7,000 words, 20.0%

The measured baseline is `wc -w src/*.md`: **35,081 words**. A 15–25% cut is 5,262–8,770 words. The following **net editorial budgets**, not already executed diffs, total **7,000 words** and leave about **28,081**. They include replacement summaries/captions; the final editor should measure the actual net reduction after rewriting. Each row identifies the paragraphs/tables to cut or merge and the canonical copy to keep. No schema, mandatory heading, UC/DP diagram deliverable, major normal/exception flow, member allocation, result or target disappears.

| Cut ID | File and heading | Cut or merge, with paragraph boundary / specific material | Keep this canonical copy / rubric safeguard | Net words |
|---|---|---|---|---:|
| C01 | `10-introduction.md` — Background / Business Needs / Project Scope / Stakeholders | Merge the first two Background paragraphs into a short baseline/provenance account retaining team approval and both baseline SHAs. Delete the second prose inventory beginning “FFmpeg encoding, HLS output…” after the inherited/new table. Replace the four long driver explanations with one sentence each. Trim repeated phase delivery detail and the persona-site/register explanation to a short provenance clause. | Keep the inherited/new table, scope levels, seven UC rows, phase dates, named stakeholders and exclusions. Full runtime inventory stays in 3.2; dated delivery sequence stays in 2.3/5.3; platform roles stay in 3.1.4. | 450 |
| C02 | `20-conduct.md` — Iterations and sprint-plan summaries / five Iteration headings / Project Metrics | Merge the five separate Review and Retrospective narratives into a five-row table: increment/evidence, went well, improvement/action. Cut PR-by-PR chronology from those paragraphs after preserving one acceptance source per iteration. Replace the two opening iteration-method paragraphs with one dated reconstruction sentence. Remove the second per-member 11/12-pd table after incorporating its hours in the WBS totals. Shorten issue-count reconciliation/reproduction prose to source/date/unit plus one command; retain timestamp/reopen caveat in a note. | Keep all five goals/windows/issue groups, reviews/retrospectives/actions, WBS and named UC/DP responsibility; actual effort still needs adding. Keep current issue-state caveats once. Add the inline planning timeline; its caption/replacement words are included in this net budget. | 700 |
| C03 | `30-logical.md` — Public request and identity boundary / Durable upload and edit acceptance / Nodes and Subsystems / Platform Design | Keep the authorizer figure, but merge its two long protocol paragraphs into a four-sentence path/dependency explanation. Reduce both intake/relay paragraphs to commit-before-publication and a pointer to Detailed Design/DP-2. Merge node-role prose with the tier/provider tables instead of repeating APIs/repair/encoders. Delete the ten-field Envelope/Source paragraph and queue-policy receipt paragraph after the message-kind table; point to Persistence Design. Condense duplicated invariant prose already specified in the supporting-boundary and dictionary tables. | Keep provider/type and tiers tables, component figures, capability-to-context derivation, roots/entities/values, invariant ownership, context-map semantics and platform role table. Detailed auth belongs in DP-3; wire fields in 3.2.3; transaction/replay protocol in DP-2. Preserve the synchronous Media-authorizer dependency once here. | 1,000 |
| C04 | `32-physical.md` — deployment table / Artifacts, entry points and authority / Queue and store placement / Load distribution and execution admission | Merge component deployment and source-export/trigger tables into one compact deployment table with runtime, artifact, entrypoint/trigger, placement/bound and authority columns. Cut the repeated queue/store path narrative whose rows already carry batch/concurrency/placement. Replace the four-step dispatch/admission/redirect/capacity tutorial with a compact decision-location table, retaining feature/size/history and probe limits; replace full network-route prose with a concise route summary and link the detailed network view. | Keep the main deployment figure, every relevant physical placement/control fact, AD-30 no-ALB comparison, AD-31 NoSQL comparison and rationale. UC-2 owns detailed dispatch/admission interactions; UC-6 owns reserve/send/reconciliation. No loss of response to routing or load-distribution feedback. | 700 |
| C05 | `34-persistence-detailed.md` — Information architecture / Transactions and concurrency / Detailed Design | Merge the eight data-group bullet blocks into one compact inventory with classification, format/store, applicable controls, rationale/trade-off columns; replace repeated JWT/S3/queue/IAM control explanations with §4.3 references while retaining group-specific controls. Reduce Transactions and concurrency to a boundary/lock/commit/failure table; point to DP-2 for the full relay protocol. Replace the Upload/process/play step table and long stored-source retry tutorial with short architectural context and precise §6.4 figure references. Remove `data-edit-relay` inline duplication (F01 below), retaining the edit adoption sequence and its distinct inside-transaction pin verification. | Keep all typed ERs, the complete physical dictionary, all JSONB/message/object shapes, retention table and per-group classification/security/trade-offs. Keep the edit sequence and unique copy/pin/adoption/cleanup facts. UC-1/2/3/4 own full operation-level explanations; DP-2 owns relay. | 1,000 |
| C06 | `36-other-limitations.md` — Other Architectural Decisions / Architectural Limitation | Delete the repeated AD-29 row. Reduce the #271 oversized-upload anecdote to its final status or remove the row because it is a small resolved defect. Remove the four “Rationale already given elsewhere” bullets; the decision rows already provide locators. Replace AISS-01's repeated numeric target results with impact plus §4 reference. | Keep every major proposal pivot, F-01/D-01/D-06/freeze, all five limitations with owner/status/impact/horizon, and the unique retained-image decision AD-28. Keep measured misses in the results table. | 200 |
| C07 | `40-quality.md` — Performance / Availability / Security / Test inventory | Replace the first two Performance mechanism paragraphs with a short tactic-to-result bridge referencing AD-30/UC-2. Cut the first Availability transaction tutorial beginning “Media commits an Asset…” and shorten repeated capacity-limit prose; keep recovery/availability implications. Replace Security's opening authorizer tutorial with a cross-reference and resource-ownership consequence. Merge unit/static/test-run methodology notes so the same “not additive/not new cloud result” explanation is stated once. | Keep the complete target/result/verdict table, relevant workload/timing boundaries, single-instance/restore caveats, security controls and negative-result table, seven-route DAST scope, complex-module test inventory and unchanged coverage gates. | 450 |
| C08 | `50-devops.md` — Dated verification evidence / Recorded deliveries / scanner explanatory prose | Reduce the introductory 21 October job timing paragraph and both post-delivery incident paragraphs to one neutral AD-28/Aurora-wake summary. Remove the repeated final c7c489c read-back/timing narrative after keeping its row and required timing boundary in §4. Merge prose repeating stage inventory details into table notes; retain independent/advisory versus blocking semantics. | Keep triggers, scanner inventory/results, branch strategy/authentication, environments/approver, exact-source admission, owner restore versus later playback smoke, and representative receipts including failures. DP-1/UC-7 own journal internals; no loss of SAST/DAST visibility. | 350 |
| C09 | `60-other.md` — Presentation Feedback and Response | Merge Response and Change made into one concise “response / evidence” column; replace long figure lists with the decisive one or two references per row. Cut repeated architectural tutorials and PR #327/#328 implementation descriptions from response cells. | Keep all 14 remark rows verbatim in meaning, assessor/source/date attribution, the distinct spoken versus written remarks and team follow-up, and exact section/figure evidence. Technical detail stays in the cited chapters. | 600 |
| C10 | `61-use-case-model.md` — Use Case Model / TR-1–TR-6 | Remove the long final backlog-map paragraph after retaining the catalogue's UC-to-model ownership path and appendix traceability. Delete the implementation tutorial paragraph after each TR table after carrying any unique qualification into the corresponding row; shorten the opening scope/persona prose to a pointer to §1. | Keep all six strategy tables with affected analysis objects, UCs, class/sequence changes and reasons. Correct TR-5/TR-6 under S4/S5. Preserve the use-case diagram and catalogue. | 350 |
| C11 | `62-ad-ibrahim.md` — UC-1/UC-2/UC-4 model introductions | Cut tautological “Figure … shows …” lead-ins that merely restate the next caption. Replace the UC-2 dispatch-size/duration tutorial with a precise pointer to the architecture decision and keep exception behavior in its diagrams. Compress repeated verification caveats to one local-test note. | Keep each Description's actors/preconditions/normal/exception/postconditions, all required figures, meaningful class/interaction distinctions, analysis→design mapping and relevant tests. | 200 |
| C12 | `63-ad-long.md` — UC-3/UC-5 model introductions | Merge each class/sequence caption lead-in with its following explanatory paragraph; remove repeated owner allocation/persona descriptions already in the catalogue. Shorten the final “These are local client/contract tests” disclaimer to one common evidence note. | Keep every status/playback/replay and Publisher uncertain/partial-failure flow; keep intent persistence distinctions and all required models/mapping. | 150 |
| C13 | `64-ad-guru.md` — UC-6 / UC-7 | Cut the UC-6 paragraph beginning “The launcher controls standard capacity…” after the sequences, replacing it with a one-line AD-30/UC-2 pointer. Remove redundant owner/persona sentences and generic figure lead-ins; compress suite-fake qualifications into one note. | Keep capacity exception flows, shared/send-versus-disable locking, separate capacity/claim authority, exact-source/release/restore/alias-drift semantics and all required models. | 150 |
| C14 | `65-dp-guru.md` — Design Problems and Patterns introduction / Implementation decisions | Replace the opening 68-word repeated assignment paragraph with “DP-1–DP-3 follow the ownership allocation in Project Plan.” Shorten the final release tutorial to a UC-7/CD pointer retaining the pattern consequence. | Keep problem/forces, both candidate comparisons, chosen-pattern rationale, all four DP-1 diagrams and implementation-specific capacity decisions/tests. | 100 |
| C15 | `66-dp-ibrahim.md` — Solution models / Implementation decisions | Merge the first two Implementation decisions paragraphs with the existing solution-sequence explanation; remove generic restatements of outbox/inbox benefits already in Why the chosen pattern. Correct Actor wording. | Keep failure windows, candidates, rationale, all four DP-2 diagrams and named consistency/repair tests. | 75 |
| C16 | `67-dp-long.md` — Why the chosen pattern / Solution class and sequence diagrams | Remove repeated authorizer route/TTL tutorial from Implementation decisions after preserving one configured-boundary sentence; shorten the chosen-pattern paragraph to its trade-off and refer to the solution sequence. | Keep all four DP-3 problem/solution diagrams plus the contract-consumer figure, alternatives/rationale and actual adapter/owner-filter behavior. | 75 |
| C17 | `68-contributions.md` — What Team 17 Contributed / Per-Member Contribution Summary / Evidence and How to Reproduce It | Replace the six-item inherited/new contribution inventory with one paragraph referencing §1's comparison table. For each member, merge the introductory paragraph with the bullets and delete the repeated full UC/DP title list (Project Plan/catalogue already assigns them). Remove the PR #327/#328 reproduction rows, replacing them with a §4.4/§5.2 pointer. | Keep one concrete output/leadership summary for every member, cross-review contribution, five consequential lessons, core evidence/reproduction index and AI declaration. Member attribution still needs confirmation through the team process. | 350 |
| C18 | `70-appendices.md` — Use-Case Traceability Matrix / Supporting Assets | Replace repeated full UC section titles in the matrix with “§6.4 UC-n” and one legend; shorten asset-purpose prose/captions that duplicate §1 and the asset register. | Keep every UC→owner→implementation→test row, glossary and all asset links/provenance. | 100 |
| **Total** | | | **Keep all substantive rubric items and all mandatory UC/DP model sets.** | **7,000** |

### Figures with no additional report value, or strong consolidation candidates

| ID | Figure / location | Specific action | Coverage retained |
|---|---|---|---|
| F01 | `data-edit-relay`, `34-persistence-detailed.md` — Edit-derived intake | Remove the inline image and duplicate relay explanation; replace every `{@fig:data-edit-relay}` reference with `{@fig:dp2-solution-sequence}`. The extra relay figure repeats the fenced claim/send/ack/inbox protocol. | Keep `data-edit-sequence` for the unique edit copy/pin/adoption flow. DP-2 solution sequence supplies the same relay/consumption detail. |
| F02 | `conduct-issue-reduction` after the conduct reconciliation table | This plot repeats the remaining-open line of `conduct-overall-issues`. Consolidate the overall burnup/burndown and issue-reduction presentation into a clearly labelled composite inline figure; retain a distinct issue-reduction panel or caption so the user's explicit requirement remains satisfied. Do not simply delete issue reduction. | Burndown and issue reduction remain inline; per-iteration burndown remains available. Add the separate planning timeline. |
| F03 | Linked `arch-delivery-ledgers`, `30-logical.md` — Supporting consistency boundaries | Remove the redundant standalone link/caption and point to the typed `data-delivery-schema` figure plus DP-2. It repeats schema/ledger roles already documented in their canonical homes. It is linked, so removing it saves explanation/link clutter rather than a whole inline page. | Complete local delivery schemas and pattern roles remain. |
| F04 | Linked `arch-launcher-control`, `30-logical.md` — Supporting consistency boundaries | Remove the extra supporting image link if its selected records add no detail beyond `data-processing-launcher` and UC-6 design class; use those exact references instead. | Reservation/control schema, uniqueness and execution logic remain in Persistence and UC-6. |

No entire UC or DP model set is a safe deletion. Similar analysis/design class diagrams answer different requested questions. A large component, deployment or schema diagram can be shortened only after preserving its unique interfaces, placement or constraints; low readability alone is not proof that it adds nothing. The target/result chart helps comparison and need not be removed simply because the results table exists.

## 9. Tone: exact sentence replacements

The revision is substantially more neutral than A1's baseline. The main remaining tone issue is repeated defensive evidence qualification and authoring instructions, rather than overtly self-critical admissions. Keep one common evidence-scope note, dated result labels and consequential limitations. The following edits remove hedging without changing the evidence class.

| File — heading | Exact sentence / wording | Replacement |
|---|---|---|
| `30-logical.md` — Architecture views | “These are view correspondences, not full conformance claims for C4, 4+1 or arc42.” | “The views organize context, logical, development, runtime, deployment, information and delivery concerns.” |
| `30-logical.md` — Context-map relationships | “Shared libraries establish code reuse, while Customer/Supplier and Shared Kernel would additionally require governance agreements. Those formal patterns are not assumed.” | “The services reuse contract and technical libraries; the context map labels the implemented message and translation relationships.” |
| `32-physical.md` — AD-30 | “AD-30 records this report's analysis, without a historical ALB trial or comparative benchmark.” | “AD-30 compares the alternatives against the deployed workload and idle-cost goals.” Keep “No comparative benchmark” once if any adjacent wording otherwise implies measured superiority. |
| `34-persistence-detailed.md` — Transactions and concurrency | “There is no SQL/SQS or cross-database atomic commit, or unconditional loss guarantee.” | “SQL commits locally; durable outbox intent, inbox deduplication and repair bridge the SQS boundary.” |
| `34-persistence-detailed.md` — Compact physical data dictionaries | “These representation differences do not establish live schema drift.” | “The dictionary follows migration DDL for those indexes and the singleton default.” |
| `34-persistence-detailed.md` — Information architecture / owner media content | “Object storage is the only sensible store at this size.” | “S3 stores video bytes; PostgreSQL stores transactional metadata and descriptors.” This removes an unsupported absolute rather than a confession. |
| `34-persistence-detailed.md` — Messages in transit | “The repository does not record a formal FIFO evaluation.” | Delete; retain the adjacent Standard/FIFO ordering, deduplication and design trade-off explanation. |
| `61-use-case-model.md` — TR-4 | “The diagram must therefore distinguish a committed command from a successfully acknowledged send; a transport timeout does not cancel accepted domain work.” | “The sequence separates adoption commit, relay send and send acknowledgement; response loss leaves accepted work available for replay.” |
| `61-use-case-model.md` — Use Case Model | “All seven cases have Must priority as retained proposal scope (business decision BS-06); this is a scope classification, not a claim about GitHub priority fields.” | “All seven proposal use cases have Must priority (BS-06); the backlog separately records implementation priority.” |
| `62-ad-ibrahim.md` — UC-2 verification | “These are implementation tests, not claims of measured cloud recovery latency.” | “These local tests verify redirect, terminal commit and stale-authority rejection; measured cloud timings are in §4.” |
| `63-ad-long.md` — UC-3 verification | “...it does not exercise an actual S3 Range transfer.” | “The route test uses mocked storage; the dated playback receipts cover S3 Range access.” Retain the first clause even if no receipt is selected for the second. |
| `64-ad-guru.md` — UC-6 verification | “ECS and SQS are fakes in this suite. ... neither suite alone establishes live cloud execution.” | “The SQL suite uses PostgreSQL with fake ECS/SQS ports; dated cloud execution results are reported in §4.” |
| `65-dp-guru.md` — The problem | “These are deliberately hypothetical failing models, not a claim that this code path is deployed.” | “The problem models illustrate the unprotected observe-then-launch alternative.” |
| `65-dp-guru.md` — Candidate patterns | “These are a comparison of design alternatives against the implemented constraints, rather than a claim that all candidates were benchmarked.” | “The comparison evaluates each alternative against finite-task operation, bounded spend and recoverability.” |
| `65-dp-guru.md` — Implementation decisions | “These tests establish the modeled decisions without asserting a fresh deployment or rollback demonstration.” | “The tests verify release selection, image policy and recovery behavior; the recorded cloud demonstrations are listed in §5.3.” |
| `66-dp-ibrahim.md` — Solution models | “The ledgers are technical consistency records rather than children reached through cross-database foreign keys.” | “Each context owns independent delivery ledgers and commits them with its local state.” |
| `66-dp-ibrahim.md` — Implementation decisions | “These tests establish the stated local consistency mechanisms; cloud recovery latency is a separate measurement.” | “These PostgreSQL tests verify atomic acceptance, replay identity and acknowledgement ordering.” |
| `67-dp-long.md` — verification | “These local tests substantiate the design without asserting a fresh hosted authorization result.” | “These local tests verify current-user checks, trusted context, owner filtering and independent client consumption.” |
| `36-other-limitations.md` — final paragraph | “The optional implementation backlog stays in supporting feedback notes; it is not an additional set of architectural limitations.” | Delete; the five-row AISS table already defines the material limitations. |

Retain the following measured misses, ideally once in the Quality Attributes results table, in neutral one-line form:

- “AWS V1 two-worker speedup was 1.449× against the 1.6× target; three workers achieved 2.347× against 2.1×.”
- “Standard-lane queue wait was about 37 s against the 20 s target.”
- “The r1018b release step took 10.1–10.3 min against 10 min; release plus the separate upload smoke took 15 min 38 s.” Keep the distinct r1019a 9 min 39 s result and its workload/boundary.
- “In sl1021, warm short-lane submit-to-done was 45.2 s against the 20 s aim.” Label it an aim, not a retroactively imposed proposal acceptance threshold.

Do not soften these to “nearly achieved” or change FAIL to PASS. Replace repeated numerical misses in AISS-01 with “Startup latency and finite capacity constrain response time; measured results are in §4.” The roadmap/owner/impact stay. A measured failure is not a tone failure.

## 10. Review handoff and validation

Authoring fixes before final review: add the planning timeline; reconcile actual and combined-project effort/averages through the members; name the promotion authority; correct TR-5/TR-6 and the Actor boundary sentence; remove duplicate AD-29; clarify the cover date; apply the cut/tone plan. Coordinator-only completion facts remain progress submission, recording access, final upload and private peer-assessment receipts. These are distinguished from missing architecture content.

Validation performed: all 19 sources inspected; complete T/U/B/F ID sets cross-checked with A1 and the primary requirement files; original briefing text inspected; every in-report figure reference resolved; no duplicate figure IDs; every Markdown relative destination checked; concatenated heading progression checked; all six section-6 parents checked in source and DOCX XML; current inline image hashes compared with DOCX media. Selected UC/DP PlantUML was inspected to distinguish actual class/sequence/alternative models from old flowcharts. The cut budgets total 7,000 net words. No source edits, source-generation commands, build/render, application tests or external operations were performed.

The report is **PARTIAL pending the listed content and editorial fixes**. The extensive new models and feedback response are present; the unresolved effort averages, planning visual and internal inconsistencies are the concrete remaining rubric/structure issues. Final rendered-page quality and comprehensive code/model truth require their owning review lanes.
