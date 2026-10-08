# Step 04 — logical architecture and ADRs

Status: designed for team review; not implemented or measured. Reconciled with owner step 05 content and all three OpenAPI files.

- `content.json`: website-ready sections, source register and representative use-case traceability.
- `logical-architecture.md`: complete standalone architecture narrative.
- `architecture-decisions.json` and `AD-01.md` through `AD-08.md`: proposal IDs, context, alternatives, consequences, owners and planned validation.
- `inherited-vs-proposed.mmd` and `success-sequence.mmd`: full semantic diagram sources.
- `diagram-layouts.json` and `render-tldraw.js`: compact editable native-shape layouts and reproducible board script.
- `export-tldraw.js`: exports actual tldraw shapes through `getSvgString`.
- `inherited-vs-proposed.svg` and `success-sequence.svg`: exported and visually inspected diagrams.
- `diagram-manifest.json`: verified board/page/root/shape IDs, dimensions and visual QA record.

Board: https://www.tldraw.com/f/0GOUcscLFXmGeNDXAJTx5

1. Architecture: page `page:page`, 46 editable shapes.
2. Sequence: page `page:team17-step04-success-sequence`, 72 editable shapes.

Submitted status is composed through live owner-filtered Processing reads; outage/missing Job returns 503. Pending intake is queued/pending. Submit/Retry reserves queued Attempts before RQ delivery. Source and output GET grants have a 15-minute design default; output references remain durable in Processing. MKV/MP3 are inherited edit compatibility only. Cancellation uses stable Asset identity and owner-bound submission guards; pending derived edits persist immutable operations.

Only this directory and its assigned board were edited. Application files, original materials and Git remain unchanged. AWS product choices belong to step 07; executable recovery mechanisms and timing evidence belong to step 06. All implementation checks remain planned.
