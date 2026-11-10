# Team 14 reference: depth profile

## Scope and counting method

The supplied DOCX is an **individual reflection**, not the large team report repeatedly cited within it. It is from a different course and rubric. The larger report is not supplied, so its full diagram inventory, per-use-case diagram density, and pattern-section lengths cannot be inferred. This profile benchmarks the reflection actually provided, not the unseen team report. People are anonymized; the author is member 1.

Counts use the extracted text, DOCX XML, package metadata, and caption descriptions. Word counts are approximate regex counts, including headings, table text and captions; document metadata uses a different method. Section counts exclude subsections, except where explicitly aggregated. Image types below are characterized from captions and surrounding prose, not visual inspection.

## Complete heading outline and length

- **1. Reflection** — approximately 3,946 words including subsections; introductory text and ownership table approximately 267 words.
  - **1.1 Process** — approximately 503 words.
  - **1.2 Architecture and Design** — approximately 1,147 words.
  - **1.3 Development and Implementation** — approximately 988 words.
  - **1.4 Lesson Learnt** — approximately 406 words.
  - **1.5 Innovation** — approximately 308 words.
  - **1.6 Value** — approximately 327 words.
- **Appendix: Use of Large Language Models** — approximately 14 words.

The document also has a title page and contents. The extraction totals approximately **4,034 words**, including front matter and contents; Word's stored metadata reports **3,646 words**, which may reflect different counting or saved-state conventions. The contents and DOCX metadata both indicate **12 pages**, an estimate based on the saved document rather than a fresh rendering.

## Figures, tables and appendices

- XML: **4 drawing elements** and **1 table**. There are **5 packaged media files**, which cannot all be equated to placed figures; the four numbered captions are the safer visible-figure count.
- Figure 1: UC04 design sequence, showing verification, acceptance transaction and subsequent processing: **one sequence diagram**.
- Figure 2: DP02 Strategy and Adapter structure: **one pattern/structural diagram**; its caption does not establish whether it is a formal UML class diagram.
- Figure 3: hosted development deployment: **one architecture/deployment diagram**.
- Figure 4: before/after hosted security alert types: **one chart**.
- **No identified use-case diagram, screenshot, or explicitly labelled UML class diagram** in this document. No claim is made about the unseen team report.
- One captioned table maps member 1's responsibilities across roles, use cases, design problems, operations and PRs. **One appendix** discloses LLM assistance.
- Figure captions 1 and 3 say redrawn from the team report; 2 and 4 cite its figures. Team-report figure numbers reach 168, but numbering alone does not prove that report's total or categories.

## Presentation and evidential depth

**Agile and ownership.** Process describes four approximately two-week sprints, planning, reviews and retrospectives, a concrete Definition of Done, one review distinction between merged and hosted acceptance, and a retrospective action followed by an observed later application. It quantifies planned and estimated actual capacity, explicitly labels estimates, describes workload redistribution, and reflects on overlapping Product Owner, Scrum Master and integrator responsibilities. It does not reproduce a backlog, sprint table or burndown chart. Ownership is detailed for the author; contributions of other members are acknowledged in prose, not a complete member-by-member matrix.

**Use cases and models.** Three owned use cases are named. UC04 receives a sequence diagram and detailed acceptance/retry discussion; UC06 receives a quota/correction trade-off and an analysis-to-implementation mapping; UC05 is named but is not separately diagrammed or developed to the same depth. Analysis boundary/control/entity concepts are explicitly mapped to modules and records rather than invented classes. There is no basis to claim a fixed number of diagrams for each use case.

**Patterns and architecture.** DP02 explains the motivating storage problem, Strategy interface and implementations, Adapter boundary, implementation evidence and a remaining improvement, with one structural figure. DP05 explains a functional Decorator, streaming verification, four call sites and a limitation, without its own figure. The architecture section argues for a modular monolith, names transactional and operational trade-offs, and shows a deployment diagram and indicative costs.

**Testing, CI/CD and security.** The report connects claims to specific tests and failures: concurrent duplicate completion, multi-database CI, runtime image dependency failure and recovery, scanner findings, regression tests and security remediation. It describes a required aggregate quality gate, exact-image scanning, temporary cloud credentials, deployment fallback and reported deployment measurements. Security includes a concrete SSRF mechanism, fix and regression test; a scan/triage/fix/rescan loop with before/after figures; residual risk; and a security change that introduced a functional regression. It distinguishes provisioned release infrastructure from the application left switched off.

**Tone and evidence.** First person, technically specific and reflective: benefits are paired with costs, failed assumptions and specific changes for a redo. Evidence takes the form of dates, issue/PR numbers, quantitative observations, tests and numbered references to figures from the team report. These references are pointers, not independent verification of the underlying claims. The single table provides a concise ownership map; four descriptive captions explain what each visual illustrates and several cross-reference the larger report. The prose uses figure references, though not every quantitative claim has a direct citation or reproducible source in this reflection.

## Fifteen comparable depth benchmarks

These are targets inferred from this reflection, not requirements of the current course or claims about the unseen report.

1. Target roughly 3,600–4,000 words across about 12 pages, subject to the actual rubric and layout.
2. Provide an ownership table covering roles, use cases, design problems and delivery responsibilities.
3. Describe the sprint cadence and actual review, planning and retrospective practices, not just the framework name.
4. Include one retrospective finding, its concrete action and subsequent evidence that the action was applied.
5. Quantify capacity or workload where evidence exists; mark estimates and discuss a resulting planning decision.
6. Name around three owned use cases, then examine at least two in substantive detail rather than implying equal coverage.
7. Include a design sequence for one critical use case, showing state changes and transaction boundaries.
8. Explain one failure or retry scenario, the mechanism protecting it, and a specific test result.
9. Present one explicit design trade-off, its user-visible downside and a plausible alternative.
10. Map at least one analysis-model concept to its real implementation and explain any mismatch with textbook notation.
11. Discuss two design problems or patterns: one with a structural diagram, concrete interface and implementations, and another with mechanism, use sites and limitations. This reference does not support a two-diagrams-per-pattern rule.
12. Explain the architecture choice with a system diagram, operational constraints and at least one cost or reliability trade-off.
13. Describe the quality gate and delivery pipeline with concrete environments, checks and a real failure-and-recovery example.
14. Trace one security issue from mechanism through fix and regression test, and report a scan/remediation comparison with residual limitations.
15. Close with several specific lessons and redo actions, a value/cost assessment, and a brief disclosure of AI assistance; use descriptive numbered captions and trace claims to available evidence.
