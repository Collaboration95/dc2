# Brief: the new FlickPond study guide and slides

This folder replaces the old explainer site (`showcase-prep/`, which becomes `/archive/`).
It holds two things with the **same structure**: a study guide (pages `index.html`,
`1-overview.html` … `6-demo.html`, `references.html`) and the presentation slides (`deck.html`).
This brief is for the people and agents writing them.

## Reader

A team member who knows little about the project and has about three hours to read the whole guide.
Afterwards they should be able to discuss the system with a professor: what it does, how each part
works, why it was built that way, what the alternatives were, and where it falls short.
Budget: index 5 min · 1 ≈ 15 · 2 ≈ 10 · 3 ≈ 40 · 4 ≈ 40 · 5 ≈ 30 · 6 ≈ 20 minutes.

## Structure (follows the course guideline exactly; keep these ids)

| Page | Subsection ids (`<section class="sub" id="…">`) |
|---|---|
| `1-overview.html` | `1a` context and business problem · `1b` platform thinking · `1c` project scope (what was inherited from Project 1, what Project 2 added) |
| `2-conduct.html` | `2a` current status and outstanding issues · `2b` actual milestones and rough effort per member |
| `3-logical.html` | `3a` key decisions shaping the logical architecture · `3b` logical components (logical deployment diagram + supporting views) · `3c` DDD elements, and how the platform interacts with producers and consumers |
| `4-physical.html` | `4a` key decisions shaping the physical architecture · `4b` network, nodes, technologies, cloud services · `4c` persistence design · `4d` detailed design of one representative use case |
| `5-devops.html` | `5a` source code and artifact strategy · `5b` pipeline and procedures · `5c` technical findings and issues |
| `6-demo.html` | `6a` significant use cases · `6b` quality attributes: scalability (auto-scaling), performance (scripted test), maintainability (run the pipeline) |

Every section page ends with `<section class="sub" id="questions">`: questions a professor may ask
about that section, 5–8 of them, each with a substantive answer (the reasoning, the alternative we
rejected, the cost or limit). No questions anywhere else.

## Explain each concept once

The owner page explains the concept fully, under the anchor below. Every other page links to it
in one line (`<p class="see">…</p>` or an inline link) instead of explaining it again.

| Concept | Owner |
|---|---|
| The business problem, the users, why a platform | `1-overview.html#1a`, `#1b` |
| What came from Project 1 vs what Project 2 built | `1-overview.html#1c` |
| Media and Processing as bounded contexts; context map; ubiquitous language | `3-logical.html#contexts` |
| Asset, Job, Attempt and their states | `3-logical.html#asset-job-attempt` |
| Source pin (immutable S3 object version) | `3-logical.html#source-pin` |
| Outbox and inbox; at-least-once delivery; idempotency | `3-logical.html#outbox`, `#idempotency` |
| Lease (which worker may write a result) | `3-logical.html#lease` |
| Projection (Media's local copy of Processing's results) | `3-logical.html#projection` |
| Who may do what: owners, authorizer, ownership checks | `3-logical.html#access` |
| Browser app and Publisher CLI as producers/consumers; public API contract | `3-logical.html#producers-consumers` |
| Network: VPC, subnets, endpoints, egress | `4-physical.html#network` |
| Compute: API Gateway, Lambda services, authorizer | `4-physical.html#compute` |
| Short Lambda lane vs Fargate encoders; the launcher (how scaling works) | `4-physical.html#lanes`, `#launcher` |
| Cost model (pay for work, not waiting) | `4-physical.html#cost` |
| Aurora cluster per service, auto-pause, S3, SQS; tables | `4-physical.html#4c` |
| One upload from bytes to playback, end to end | `4-physical.html#4d` |
| Repository, branches, PR flow, artifact identity | `5-devops.html#5a` |
| Every check from laptop to production; CI; CD; rollback | `5-devops.html#laptop-to-production`, `#ci`, `#cd`, `#rollback` |
| Security scanning (CodeQL, Trivy, ZAP, gitleaks, Ruff security, Sonar, Dependabot) | `5-devops.html#scanning` |

Measured results sit beside the mechanism they measure (speed-up next to the launcher, short-lane
latency next to the lanes). `2a` and `6b` link to them.

## Writing rules

These come from what went wrong with the old site. Follow them literally.

1. **Explain, don't coach.** No "say it in your own words", no reading routes, no rehearsal prompts,
   no "memorise this", no advice about what to tell the professor. No personas or user-story framing
   ("Maya uploads…", "As a … I want …"). Say "an owner uploads a video".
2. **No levels.** No level 1/2/3, no depth toggles, no click-to-reveal diagrams. One complete
   explanation per idea, in order: what it is → how it works → why this way → what it costs or limits.
3. **No jargon in boxes.** Never name an abstraction without saying what it does. Not
   "Route → Service → Repository → Adapter" but what each one receives, decides and hands on.
4. **Mechanisms, not catalogues.** For each component say what comes in, what it does, what changes
   (state, data, side effects), and what goes out. The `table.mech` helper is there for this; prose
   is fine too.
5. **Diagrams only where they earn it**: when relationships, boundaries, movement or timing become
   clearer than in prose. Otherwise use prose or a table. Each diagram gets a one-sentence caption
   saying what to notice. Build diagrams with the HTML helpers (`.flow`, `.node`, `.zone`, `.cols`)
   or inline SVG; reuse an image from `assets/img/` only if it is readable and correct.
6. **No defensive commentary.** No disclaimers about personas or authorship, no lists of features we
   don't have, no repeated "do not claim" warnings. State limits once, plainly, beside the mechanism
   they limit (`<div class="limit">`). Trade-offs go in `<div class="limit tradeoff">`.
7. **Evidence stays out of the way.** Run IDs, commit SHAs, workflow run numbers, file paths and
   historical receipts go in `references.html`. In the text, at most a small chip:
   `<a class="ref" href="references.html#r-sl1021">sl1021</a>`.
8. **Explain once, link back** (table above).
9. Plain, direct English. Short paragraphs. Numbers with units and a comparison or target.
   Use the project's words consistently: Asset, Job, Attempt, source pin, lease, projection,
   Media, Processing, owner. Media and Processing are the two services; a Lambda function is a
   deployment unit, not a separate microservice.

## HTML conventions

- Copy the page shell from `_template.html`: same sidebar on every page (set `aria-current="page"`),
  `assets/guide.css`, `<ul class="toc">`, `<section class="sub" id="…">` with `<span class="tag">3a</span>`
  in the heading, the pager at the bottom. No JavaScript in the study pages. No external fonts,
  scripts or CDNs. Everything must work from a static folder.
- Components: `.point` (the claim of a subsection), `table.grid` / `table.grid.mech`, `.limit`,
  `.limit.tradeoff`, `.stats/.stat(.pass|.miss)`, `figure.dia` with `.flow/.node(.media|.proc|.client|.infra|.ghost)/.zone/.cols/.legend`,
  `p.see`, `a.ref`, `details.qa`.
- Colours carry meaning: blue = Media, amber = Processing, green = clients, slate = managed
  infrastructure, orange = a missed target or limit.
- References: write your page's evidence entries to `_refs/<page>.html` as
  `<section id="r-…"><h3>…</h3><p>…</p></section>` blocks (id prefix `r-`). They are stitched into
  `references.html` at the end. Don't edit another writer's pages; link to the anchors above.

## Sources, in priority order

1. The final report source: `project-documentation/final-report/src/*.md` (its chapters follow the
   same six sections).
2. `docs/architecture/` (`README.md`, `ddd.md`, `decisions.md`, `views.md`, `use-case-design.md`),
   `docs/results/`, `docs/execution/aws/v2/`, `project-documentation/effort-ledger.md`.
3. `project-documentation/presentation/research/sections-1-4.md` and `sections-5-6-demo.md`
   (facts, numbers and likely questions, with sources).
4. The code (`media/`, `processing/`, `publisher/`, `frontend/`, `infra/` or `scripts/aws/`, `.github/workflows/`)
   when a mechanism needs checking.
5. The old site's text (`showcase-prep/content/*.json`) may be reused, but rewrite it under these rules.

Check every number against a source. If two sources disagree, use the newer one (22 Oct state:
Lambda short lane live, Aurora cluster per service) and mention the disagreement in your report
back, not on the page.

## Done means

- Pages open from `python3 -m http.server` in this folder, every internal link and anchor resolves,
  no console errors, nothing loaded from outside the folder.
- Each page reads top-down: requirement → high-level design → decisions → detail.
- Nothing in the page breaks the writing rules above.
