# Deck style — Team 17, FlickPond

Decisions for the 26 Oct deck. Each decision has a one-line rationale. The slide-by-slide plan is in
[`OUTLINE.md`](OUTLINE.md). Facts and sources are in [`research/`](research/).

## 1. Tool and format

| Decision | Rationale |
|---|---|
| **Marp** (Markdown slides) built with `npx @marp-team/marp-cli`. The source is `presentation/deck/deck.md` plus `deck/theme.css`. | It is plain text in the repo, diffs in PRs, and builds with one command. `npx` is already used for mermaid-cli by `final-report/tools/render_figures.py`. |
| Present from the **HTML** build (`deck.html`, full screen in Chrome). Export a **PDF** (`--pdf --allow-local-files`) as the backup and for Canvas (#257). | HTML can embed local video and keeps presenter notes. PDF is the universal fallback if the browser or the clips fail. |
| A PPTX export (`--pptx`) is only a convenience copy. It is not the master. | Marp PPTX slides are images. PowerPoint and Keynote are not installed on the build Mac (only Word is in `/Applications`). |
| Diagrams are **Mermaid `.mmd` → SVG** in `deck/diagrams/`, rendered with mermaid-cli and a shared `deck/mermaid.json` theme. Reused report art is referenced by path, never copied and edited by hand. | The same pipeline the report uses. One theme file keeps colours and fonts consistent, and a redraw is a text diff. |
| Clips (`deck/clips/*.mp4`) are **gitignored** and stored in the team drive. Each slide gets a poster frame (`clips/D1.jpg`) that is committed. | Video files are too large for git. The poster keeps the PDF meaningful. Add the ignore rule in Stage 4. |

## 2. Canvas and type

| Decision | Rationale |
|---|---|
| **16:9**, Marp canvas 1280×720. Export PDF at that size, and clips at 1920×1080. | Zoom screen share is 16:9. 1280 px keeps CSS sizes predictable. |
| Headline **44 px** bold, body **30 px**, absolute minimum **24 px** for anything the audience must read. Footer/receipt line **16 px** (meant to be glanced at, not read aloud). | Zoom often shows a shared screen at about half size. 24 px on a 720-px canvas is about 1/30 of the height, which stays legible as a thumbnail. |
| Diagram labels **≥ 20 px at the size placed on the slide**. Check by viewing the PDF at 50% zoom. | Mermaid defaults (16 px) shrink to unreadable once a tall diagram is fitted. |
| Font: system sans (`-apple-system, "Helvetica Neue", Arial`); mono `Menlo` for IDs, commands and run numbers. Shantell Sans (`showcase-prep/assets/fonts/`) is used **only** inside the reused hand-drawn `aws-topology.svg`. | No font install is needed on any presenter Mac. Plain sans keeps text crisp on a compressed video stream. |
| White background, dark ink. No gradients, no full-bleed photos. | Video compression smears gradients and fine texture, and white keeps the diagrams' own colours honest. |

## 3. Colour palette

This palette is consistent with the existing diagrams (`platform-context.png`, `domain-model.png`,
`aws-topology.svg`, `actual-vs-target.png`). There is **one accent per bounded context**.

| Role | Stroke / text | Fill | Used for |
|---|---|---|---|
| **Media Management** context | `#2563EB` blue | `#DBEAFE` | Media API, authorizer, `media_db`, Asset, projection |
| **Processing** context | `#D97706` amber | `#FEF3C7` | Processing API, launcher, Job/Attempt, encoders, `processing_db` |
| Clients (producers/consumers) | `#059669` green | `#ECFDF5` | Browser SPA, Publisher CLI |
| Shared / managed infrastructure | `#64748B` slate | `#F1F5F9` | Gateway, CloudFront, SQS, S3, shared kernel |
| Ink / muted text | `#0F172A` / `#475569` | `#FFFFFF` / `#F8FAFC` | Text, background, surfaces |
| **Pass** | `#059669` | — | Met targets |
| **Miss** | `#D55E00` orange | — | Missed targets. This matches `actual-vs-target.png`, and it is not red: a miss is information, not an alarm. |
| **Not run / not established** | `#64748B`, dashed outline | — | Evidence that is still missing (AISS-05) |

Rationale: an examiner should be able to tell from colour alone which side of the context boundary a box is on.
Status colours stay separate from the context colours, so a miss never looks like "Processing".

## 4. Text rules

| Rule | Rationale |
|---|---|
| **Headline = the takeaway sentence, ≤ 10 words.** No topic labels such as "Architecture". | The examiner can read the argument from the headlines alone (top-down). |
| **Body ≤ 12 words per slide**, excluding diagram labels. No bullet lists longer than 3 items. | We talk while the slide shows the picture. Reading slides aloud is against the guideline. |
| **One idea per slide.** Split a slide rather than shrink it. | The slide count is fine, because we cut later. Density is the real enemy. |
| **Numbers as big callouts**: 1–3 numbers at 96–120 px, each with a target or comparison and its unit. | A number without a target cannot be judged. |
| Every measured number carries a **receipt chip** in the footer, for example `AWS · 21 Oct · sl1021`, with an evidence label: `[AWS]`, `[Local]`, `[Code]` or `NOT RUN`. | The research rule is to keep evidence types distinct. A chip does this without adding sentences. |
| Use our words consistently: **Asset, Job, Attempt, source pin, lease, projection, Media, Processing**. Never write "microservices" for Lambdas. Write "owner", not "viewer". | This is the ubiquitous language from `docs/architecture/ddd.md`. Examiners will probe any drift. |
| No code on main slides. Commands and IDs appear only in clips or backup. | Code is unreadable at Zoom size and is not the architecture. |

## 5. Diagram treatment

| Source | Treatment | Why |
|---|---|---|
| `showcase-prep/assets/aws-topology.svg` | **Reuse as-is**, with a **progressive build**: 4 frames (edge → private subnets → public subnet and queues → supporting strip), and the other layers dimmed to 25% opacity | It is the only current physical picture. It is too busy to show in one go. |
| `final-report/figures/platform-context.png` | **Redraw** in Mermaid with the same layout. Relabel "Viewers" as "Owners watching their own output", and mark Media → Processing as asynchronous. | The current image has a wrong role and no editable source. |
| `final-report/figures/actual-vs-target.png` | Reuse **cropped** (panel A or B) for backup only | It is already slide-legible and colour-correct. |
| `final-report/figures/architecture-before-after.png` | Reuse the **left half only** (inherited). The right half is the *proposal* (token, Redis) and must not be shown as built. | Showing the proposal as delivered would be a factual error. |
| `final-report/figures/src/report-logical.mmd`, `report-context-map.mmd`, `report-dp2-handoff.mmd`, `report-dp3-identity.mmd`, `report-seq-*.mmd`, `report-cicd.mmd` | **Simplify and redraw in landscape** from these sources. Use the deck theme, ≤ 12 nodes per frame, and split sequences by phase. | The PNGs are portrait (1300–3400 px tall). They become unreadable when fitted to 16:9. |
| `docs/architecture/img/*.svg` (ERs, job states, physical, full sequence) | **Backup only**, unchanged | They are accurate but dense. They are useful when an examiner asks for detail. |
| `final-report/figures/domain-model.png`, `deployment-pipeline.png` | **Do not use** | They are proposal-era (synchronous SubmitJob, service token, Postgres "one per service" on containers). |
| Dense diagrams | **Build slides**: duplicate the slide and reveal the next layer, so new elements appear in full colour and earlier ones in grey. One build counts as one slide in timing. | Each click matches one spoken sentence, so the audience always knows where to look. |

## 6. Recorded clips

| Decision | Rationale |
|---|---|
| Each clip has **its own slide** with a full-bleed `<video>` (local file, `controls`, `preload="auto"`, no autoplay). The presenter clicks play. | The presenter controls the start. Local playback avoids streaming stalls. |
| One **intro line** of ≤ 10 s, spoken over the poster frame. It names the use case or quality and what to watch for, e.g. "Watch the task count go 0 → 3 → 0." | It tells the panel what to look for. Clips then run without commentary from the stage. |
| Clips carry a **recorded voice-over by the clip owner** and **burned-in captions** for key numbers and for every trimmed wait ("wait trimmed — actual 41 s"). | Pre-recorded narration fixes the timing. Captions survive bad audio on the examiner's side. |
| Each clip has a **corner identity stamp**: capture date · `dc2-live` · SHA. | The research requires every take to be dated and labelled. |
| Zoom: share the browser window with **"Share sound"** and **"Optimise for video clip"** ticked. The fallback is to open the same file in QuickTime and share that window. | This was tested in the Stage 6 rehearsal. QuickTime is always present on macOS. |

## 7. Slide types

| Type | Layout | Notes |
|---|---|---|
| **Title** | Product name, one-line thesis, team, date, logo (`final-report/figures/cover-logo.png`) | Used once. |
| **Section divider** | Section number and name, plus a 6-segment progress strip with the current section highlighted, plus the speaker's name | It is also the hand-off cue. Keep it ≤ 5 s on screen. |
| **Statement** | One sentence at 56 px, optional small visual | For drivers and themes. |
| **Big-number** | 1–3 numbers at 96–120 px, each with "vs target", a pass/miss colour and a receipt chip | Missed targets appear here too. |
| **Diagram** | Headline plus a full-width diagram. Body text is at most a 1-line caption. | This is the default slide type. |
| **Decision card** | Header `AD-xx` → three stacked bands: **Choice** · **Why** · **Trade-off accepted**, each ≤ 6 words, with a small diagram on the right | Every key decision uses this shape, so the panel learns to read it. |
| **Before / after** | Two panels, left grey (inherited/proposal), right in context colours (as built), with an arrow in between | Used for scope, handoff and identity. |
| **Clip** | Full-bleed poster or video, clip ID and length top-right (`D4 · 1:50`) | See §6. |
| **Status / honesty** | Chips for each open issue class (AISS-01..05), coloured miss/not-run, one line each | Used once in the main deck. |
| **Q&A backup** | Title phrased as the question ("Is this exactly-once?"), answer ≤ 12 words, plus a diagram or number | These sit after the closing slide and are reached by slide number. |

## 8. Speaker notes convention

Marp notes are HTML comments inside the slide (`<!-- ... -->`). They appear in the presenter view and are stripped from the PDF.

```
<!--
[45 s] Speaker: Guruprasath · Covers 4a · Theme T3
Say: - takeaway in my own words
     - the one number, with its target
Source: docs/results/actual-vs-target.md (LV-8)
If asked: → B09
Hand-off: "Ibrahim will show where the data lives."
-->
```

- The first line is always time · speaker · guideline bullet · theme, so a timing pass can grep for it.
- Notes carry the number and its source path. Slides carry only the number.
- `If asked:` points to a backup slide ID. Do not try to answer a deep question from the main slide.

## 9. Honesty about limitations, without dwelling

| Rule | Rationale |
|---|---|
| A miss is stated **once, at the point of the claim**: the number, the target in orange, and a 4–6-word "next step" in the footer. | It keeps credibility without spending a whole slide on apology. |
| There is a **single status slide** (S09) naming the five issue classes. All detail lives in backup (B01–B03). | This covers guideline 2a and gives the panel a map of where to probe. |
| Never re-label a miss as a pass. Keep the original targets, the workload and the environment on the chip. | Claims with receipts are one of our themes (T4). |
| Phrase limits as **scope and next step**, e.g. "Latency: queue fixed; tracing the rest next." Avoid "unfortunately" or "we didn't have time". | It sounds like engineering judgment, not excuse. |
| Inherited capabilities are credited on S04 by name (FFmpeg, HLS, worker replicas, basic CI). | The panel knows Project 1. Claiming its work would cost more than it gains. |
