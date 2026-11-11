# Rescue work plan: deck and report notes

Read `FEEDBACK.md` first. The research in `research/` is the evidence base:

| File | Contents |
|---|---|
| R1 | Old-deck lessons, toolchain, slide structure |
| R2 | Runtime and deployment truth, deck corrections |
| R3 | DDD, detailed design, data schemas, NoSQL assessment |
| R4 | Feedback audit (F1–F24) |
| R5 | External references |

Research can be wrong. Check every fact you use against the code at `76282d3` before you draw it.

## Workstreams

| ID | Scope | Deck slides touched | Feedback IDs (R4) |
|---|---|---|---|
| W1 | Request path, authorizer, deployment view, load/work distribution, Lambda vs Fargate decision | 20, 22, 23, 24, 63 | F1 F2 F11 F12 F16 F18 |
| W2 | Strategic + tactical DDD: context derivation, context map, aggregates with entities/VOs | 11, 16, 17, 18, 60 | F4 F5 F6 |
| W3 | Detailed design: component diagrams, class + object-level sequence for 2 critical use cases, edit flow | 28, 29, 30, 31 (+ new) | F3 F7 F8 F9 |
| W4 | Data: ER with columns per database, S3 keys, message schemas, NoSQL decision | 26, 27, 65 (+ new) | F10 F13 F24 |
| W5 | DevSecOps: pipeline as activity diagram with SAST/DAST visible, accurate gate claims | 33, 34, 35, 36, 37, 66, 68 | F14 F15 F17 F22 |
| W6 | Logical view, messaging chain, views map with course tags | 12, 13, 14, 15, 19 (+ new views-map slide) | F11 F19 |

## Rules for every workstream

1. **No code, IaC or workflow changes.** Code-only fixes go in your report notes under "CODE backlog".
2. **Do not edit `site/deck.html`.** The coordinator integrates the slides. You write:
   - `slides/Wn.html`: complete `<section class="slide" ...>` elements in the deck's existing markup and CSS. Read `site/deck.html` lines 1–108 for the CSS, and copy an existing section for the structure (`h1`, `.body`, `.sec`, `.foot`, `aside.notes`).
     - Put an HTML comment before each section: `<!-- REPLACES s22 -->`, `<!-- NEW after s24 -->` or `<!-- NEW backup -->`.
     - Keep the deck's headline style: the `h1` is a claim, not a topic.
     - Speaker notes in `aside.notes` must say what to point at and must cite the permalinks.
   - Diagram sources in `site/assets/uml/Wn-*.puml`, rendered to `site/assets/uml/Wn-*.svg`. Embed them in slides as `<img src="assets/uml/Wn-x.svg" style="max-width:1180px;max-height:560px;display:block;margin:0 auto">`.
   - `report-notes/Wn.md`: the report changes for your scope. Give the target file and heading in `final-report/src/`, then draft text, figures to add or replace (with paths to your `.puml`/`.svg`), corrections to existing report statements, and a CODE backlog.
3. **Toolchain.** PlantUML jar: `~/dc2-tools/plantuml-1.2026.9.jar`. Graphviz is installed. Render with:

   ```
   java -Djava.awt.headless=true -jar ~/dc2-tools/plantuml-1.2026.9.jar -tsvg <file>.puml
   ```

   - Start every `.puml` with `!include _style.iuml`. It sets the shared look; use its `$MEDIA`, `$PROC`, `$CLIENT` and `$INFRA` colours.
   - The bundled AWS icons (`!include <awslib/...>`) and C4 (`!include <C4/...>`) are available.
   - Formal notation only: UML stereotypes, multiplicities, typed attributes, numbered messages, `alt`/`opt` fragments, and a legend where colour or line style carries meaning.
   - Give each figure a title naming the view, for example "Deployment view · dc2-live · as built at 76282d3".
4. **Legibility.** A figure must be readable at 1280×720. Split a big model across slides rather than shrinking it.
   - Check by rendering the slide: open `site/deck.html#<n>` headless, or render the SVG to PNG with `npx -y @resvg/resvg-js-cli@2.6.2-beta.1`. Then look at it.
   - Main-talk figures: about 20 boxes at most. Full detail goes in a backup slide and in the report.
5. **Accuracy.**
   - Use real names from the code: modules, functions, classes, tables, queues, Lambda logical names.
   - Do not invent OO classes the code doesn't have. Python modules can be drawn as `<<module>>` with their functions.
   - Mark anything proposed or not built as such.
6. **Course tags.** Tag every architecture slide, as the old deck did, with a small line under the `h1`:
   `<div style="font:600 15px Menlo,monospace;color:#64748b;margin:-10px 0 8px">ARCHSS · Deployment view (4+1 physical)</div>`
   - Use ARCHSS (Architecting Software Solutions), PE (Platform Engineering), SAD (Software Analysis & Design), SDP (Software Design Patterns) or DevSecOps.
7. **Reply.** Finish with a short summary listing your sections and the slides each one replaces, your figures, and anything you could not verify.
