# Road to presentation — Team 17, FlickPond

**Slot:** Mon 26 Oct 2026, 2.35–3.15 pm, Zoom (SE34FT session). 40 minutes including Q&A.
**Source of the structure:** `project-documentation/original-reference/04 Project Presentation Guidelines & Schedule.pdf` (V2.8).
**Tracking issue:** #192 (deck, demo script, rehearsal).

The explainer site (https://collaboration95.github.io/dc2/) is internal study material.
The deck is a separate artifact: slides, little text, diagram-first.

## Time budget (from the guideline, X talk + Y Q&A)

| # | Section | Talk | Q&A | Must cover |
|---|---|---|---|---|
| 1 | Overview | 2 | 1 | Business problem and context; platform-thinking aspects; project scope (inherited vs Project 2) |
| 2 | Project conduct | 1.5 | 0.5 | Current status and outstanding issues; actual milestones; rough effort per member |
| 3 | Logical architecture & design | 7 | 2 | Key decisions shaping the logical design; logical components (logical detail deployment diagram + supporting views); DDD elements; how the platform serves producers and consumers |
| 4 | Physical architecture & design | 7 | 2 | Key decisions shaping the physical design; network, nodes, technologies, cloud services; persistence design; detailed design of one architecturally representative use case |
| 5 | DevOps & lifecycle | 6 | 1 | Source code and artifact strategy; pipeline and procedures; technical findings and issues |
| 6 | Demo | 8 | 2 | Significant use cases; quality attributes: scalability (auto-scaling), performance (scripted test), maintainability (run the pipeline) |
| | **Total** | **31.5** | **8.5** | 40 min |

Guideline tips to design against: highlight what is unique, not what is common; don't read slides;
top-down (requirements → high-level design → decisions → detail); readable from a distance.

## Checklist

### Stage 0 — Code freeze (22 Oct)
- [x] Short-encode Lambda lane live on dc2-live (#93), benchmark receipt `sl1021`
- [x] Per-service Aurora clusters live (#94, AD-29)
- [x] Code scanning / SARIF / CodeQL / Dependabot; alerts triaged
- [x] Final report rebuilt (DOCX/PDF, 66 pp) and on Main
- [x] Architecture/DDD docs and explainer site consistent with the live system
- [x] CD green on Main (run 39733859422); Main == dev/closeout
- [ ] Decide: keep or drop the CVE-2025-52290 sentence in report/site (accept-list entry stays)
- [ ] Announce the freeze to the team: no merges to Main except presentation material and blocking fixes

### Stage 1 — Explainer site read-through (each member, by 23 Oct)
- [ ] Each member reads Basics → Architecture → AWS → Delivery → Security → Quality on the site
- [ ] Each member reads the report sections they will present (see owners below)
- [ ] Note anything unclear or wrong as an issue/comment; fix only what is wrong, not style
- [ ] Each member can answer the Q&A bank for their section without notes (see `research/` once ready)

### Stage 2 — Rough outline (by 23 Oct)
- [ ] Research briefs per section: facts, numbers, existing diagrams, unique points, likely questions (`research/`)
- [ ] Demo plan: what runs live on dc2-live vs recorded fallback, timing, cost, failure plan (`research/`)
- [ ] Style decision: slide format, visual language, diagram treatment, text density (`STYLE.md`)
- [ ] Slide-by-slide outline with timing and speaker per slide (`OUTLINE.md`); over-long is fine, cut later

### Stage 3 — Finalize ideas and topics (by 24 Oct)
- [ ] Pick the 3–5 "remember us for this" points and make every section point back to them
- [ ] Choose the one architecturally representative use case for §4d and the demo
- [ ] Cut the outline to fit 31.5 talk-minutes; move overflow to backup/appendix slides for Q&A
- [ ] Agree speaker per section and hand-offs
- [ ] Freeze the topic list

### Stage 4 — Build the deck (24–25 Oct)
- [ ] Slides built in the chosen format from existing diagrams (report figures, `docs/architecture/img/`, site diagrams)
- [ ] Readability check at presentation size (Zoom screen share)
- [ ] Backup slides for likely questions (limitations AISS-01..05, cost, security triage, decision records)

### Stage 5 — Demo preparation (24–25 Oct)
- [ ] Demo script with exact clicks/commands and expected output
- [ ] Recorded fallback for every live step (#254)
- [ ] Pre-warm plan (Aurora auto-pause, Lambda cold start) and cost check
- [ ] Pipeline demo: which run to show / trigger

### Stage 6 — Rehearse (25 Oct)
- [ ] One full timed rehearsal, all speakers, on Zoom with screen share
- [ ] Fix timing overruns; second partial rehearsal of weak sections
- [ ] Final deck exported (PDF backup) and uploaded where Canvas asks (#257)

### Stage 7 — Present (26 Oct, 2.35 pm)
- [ ] Join Zoom 15 min early; test screen share and audio
- [ ] Wake dc2-live (Aurora + Lambda) ~10 min before the demo
- [ ] After: collect feedback for the report's post-26-Oct update (`final-report/README.md`)

## Section owners (from the report's responsibility split; adjust as agreed)

| Section | Proposed speaker |
|---|---|
| 1 Overview, 2 Conduct | TBD |
| 3 Logical architecture | TBD |
| 4 Physical architecture | TBD |
| 5 DevOps | TBD |
| 6 Demo | TBD |

## Files in this folder

| File | Purpose | Status |
|---|---|---|
| `ROAD-TO-PRESENTATION.md` | This checklist | started |
| `research/sections-1-4.md` | Facts, visuals, unique points and Q&A for sections 1–4 | in progress |
| `research/sections-5-6-demo.md` | DevOps material, demo plan and Q&A for sections 5–6 | in progress |
| `STYLE.md` | Slide style decision | after research |
| `OUTLINE.md` | Slide-by-slide outline with timing | after research |
