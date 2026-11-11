# Report v1.1 authoring guide (every writing agent reads this first)

Team 17 (FlickPond), NUS SWE5001 Architecting Scalable Systems (GC2) practice project.
The final report is due on **16 November 2026**. Today is 10 November 2026.

Repo: `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-report`, branch `dev/report-v1.1`.
`R/` below means `project-documentation/final-report/`.

## Inputs (read the ones relevant to your section)

- Template: `project-documentation/original-reference/02 Project Report Template for Practice Project.docx`. A text copy is at `/private/tmp/claude-501/-Users-speedpowermac-Documents-projects-CODE-MAIN-NUS-dc2/bdfd7790-34bb-4233-90c5-6b0a4b7138a9/scratchpad/inputs/project-template-dc2.txt`.
- The user's coverage list and tone rules: `/private/tmp/claude-501/-Users-speedpowermac-Documents-projects-CODE-MAIN-NUS-dc2/bdfd7790-34bb-4233-90c5-6b0a4b7138a9/scratchpad/inputs/coverage-list.md`
- Gap analysis: `R/rev-1.1/A1-GAP-MATRIX.md`. Code truth with file:line citations: `R/rev-1.1/A3-CODE-GAPS.md`. Artifacts and assets: `R/rev-1.1/A4-ARTIFACTS-INVENTORY.md`. Reference depth: `R/rev-1.1/A2-REFERENCE-DEPTH.md`.
- Presentation feedback: `project-documentation/presentation/feedback-20261026/FEEDBACK.md`. The 42 proposed report changes: `.../REPORT-CHANGES.md`. Reviewed notes and corrections: `.../report-notes/W1..W6.md` and `.../review/W*-review.md`.
- Reviewed PlantUML figures from the rescue: `project-documentation/presentation/feedback-20261026/uml-src/W1-*..W6-*.puml`. Reuse them by copying and adapting; don't link the deck.
- The current report v1.0 is in `R/src/*.md`. `R/README.md` explains the build and figure syntax.
- Architecture docs: `docs/architecture/` (views.md, ddd.md, decisions.md, use-case-design.md). The code is the source of truth.

## Team (Project 2 has three members; the five-person team is the inherited Project 1)

| Member | Specialism | Use cases | Design problem |
|---|---|---|---|
| Guruprasath Gopal | Cloud and delivery: AWS, CI/CD | UC-6, UC-7 | DP-1 Bounded cloud capacity and safe per-owner release |
| Ibrahim Mammadov | Backend services: Processing and Media | UC-1, UC-2, UC-4 | DP-2 Durable asynchronous Processing handoff |
| Nguyễn Kim Long | Domain, contracts and verification | UC-3, UC-5 | DP-3 Trusted owner identity and reusable public contract |

Use-case titles: when sources disagree, use the titles in `src/70-appendices.md` (e.g. UC-3 "Track status and play the result").

State this as the responsibility for analysis and design. Don't add caveats about who typed what or about shared GitHub accounts.

## Section layout for v1.1 (files are concatenated in filename order)

| File | Section | Writer |
|---|---|---|
| `00-front.md` | Cover (v1.1, date 16 Nov 2026) | S-CONDUCT |
| `10-introduction.md` | 1 Introduction | S-CONDUCT |
| `20-conduct.md` | 2 Project Conduct: plan with UC/DP owners, agile artifacts, status, metrics | S-CONDUCT |
| `30-logical.md` | 3.1 Logical architecture, with DDD platform design | S-ARCH |
| `32-physical.md` | 3.2 Physical, including the deployment view | S-ARCH |
| `34-persistence-detailed.md` | 3.2.3 Persistence (full schemas), 3.2.4 Detailed design | S-DATA |
| `36-other-limitations.md` | 3.3 and 3.4 | S-ARCH |
| `40-quality.md` | 4 Quality attributes | S-DEVOPS |
| `50-devops.md` | 5 DevOps | S-DEVOPS |
| `60-other.md` | 6 Other things to be highlighted. Its intro lists the subsections; 6.1 is Presentation Feedback and Response | S-OTHER |
| `61-use-case-model.md` | 6.2 Use Case Model (diagram with in-scope and out-of-scope use cases, catalogue) and 6.3 Analysis-to-Design Transition Strategies | S-UCMODEL |
| `62-ad-ibrahim.md` | 6.4 Analysis and Design Models, starting with UC-1, UC-2, UC-4 (Ibrahim). This file opens with the `## Analysis and Design Models` heading | M-IBRAHIM |
| `63-ad-long.md` | continues 6.4 with UC-3, UC-5 (Long), `###` headings only | M-LONG |
| `64-ad-guru.md` | continues 6.4 with UC-6, UC-7 (Guruprasath), `###` headings only | M-GURU |
| `65-dp-guru.md` | 6.5 Design Problems and Patterns, opening with `## Design Problems and Patterns` and a short intro, then DP-1 | M-GURU |
| `66-dp-ibrahim.md` | DP-2, `###` only | M-IBRAHIM |
| `67-dp-long.md` | DP-3, `###` only | M-LONG |
| `68-contributions.md` | 6.6 Member contributions, lessons, evidence and reproduction, AI declaration (moved from the old 60-other.md) | S-OTHER |
| `70-appendices.md` | Appendices: glossary, traceability, extra figures | S-OTHER (once the use-case material has moved out) |

Heading levels: `#` = top section, `##` = x.y, `###` = x.y.z, `####` = x.y.z.w. The build numbers headings itself, so never type numbers into headings.

**Only edit the files assigned to you.** Every other file is read-only, and so is any file another agent owns. Never run `git checkout`, `switch`, `commit`, `push`, `stash` or `reset`. The orchestrator commits.

## Per-use-case content (M-* agents)

For each use case: a short description, an analysis class diagram, an analysis sequence diagram for each major flow (usually the normal flow plus one or two important exception or alternative flows), a design class diagram, and a design sequence diagram for each major flow. End with a short "Analysis → design" paragraph or table showing which analysis objects became which classes and modules, and why.
- **Analysis models** are conceptual: `<<boundary>>`, `<<control>>`, `<<entity>>` stereotypes, with no framework names.
- **Design models** use only classes, modules and functions that exist in the code. Draw a module of functions as a `<<module>>` class with its real functions as operations. Give typed attributes and real method signatures, multiplicities, numbered messages, and `alt`/`opt`/`loop` frames. Verify every name against the code and cite paths in the prose, e.g. (`processing/short_lane.py`).

## Per-design-problem content (M-* agents)

1. The problem: context, forces, and what goes wrong. Include a problem class diagram and a problem sequence diagram showing the naive or failing design.
2. Candidate patterns, two or three, in a comparison table.
3. Why the chosen pattern.
4. A solution class diagram and a solution sequence diagram with pattern roles labelled, e.g. `<<outbox>>`, `<<relay>>`.
5. Implementation decisions, with code paths and the tests that prove them.

## Diagrams

- Write PlantUML in `R/figures/src/puml/<name>.puml`, starting with `!include _style.iuml`. Prefix names with your scope (`uc1-`, `uc6-`, `dp2-`, `arch-`, `data-`, `conduct-`, `devops-`) so names never clash.
- Render with: `cd R/figures/src/puml && java -jar ~/dc2-tools/plantuml-1.2026.9.jar -tpng -o ../.. <name>.puml`. The PNG lands in `R/figures/<name>.png`. Open the PNG and check it's readable: at most ~20 boxes, and split it if bigger.
- Embed figures as `![Figure {#fig:<label>}. Caption.](figures/<name>.png){width=15cm}` and refer to them as `Figure {@fig:<label>}`. Labels must be unique, so prefix them like the file names.
- UI and UX screenshots, GIF frames and persona images go in `R/assets/`. **Link** them, e.g. `[Upload screen](assets/ui-upload.png)`; embed only one or two key UI images. Major charts (burndown, sprint plan, issue reduction) are embedded inline.
- Old Mermaid figures in `R/figures/src/*.mmd` can stay where they're still correct. Replace a figure wherever the gap matrix says it's wrong or too coarse.

## Tone and claims

- Be confident and factual. Don't be self-critical, don't nitpick, and don't confess every gap between plan and build. Mention only big pivots, e.g. Kubernetes autoscaling → finite Fargate launcher. Keep the measured misses already reported (1.449x vs a 1.6x scaling target, a 10.1-min release vs 10 min, a 37 s queue wait vs 20 s) as short, neutral statements in the results. Don't repeat them everywhere.
- Every system claim must match the code in this checkout. Cite code paths in prose and keep them short.
- Don't invent meetings, people, hours or measurements. Where an agile artifact is reconstructed from issue data, give the data source in one neutral clause ("derived from GitHub issue timestamps") and leave it at that.
- Write plain, clear English: short sentences, no marketing words, no "seamless", "robust" or "leverage".
- Keep the template's sub-headings in sections 1–5.

## Done means

Your files are written, every figure you reference exists as a PNG in `R/figures/`, and your figure labels are unique. Your final message lists your files, your figures, and any open questions.
