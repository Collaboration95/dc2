# Study content contract

This folder contains the editable source for the local showcase study site.
Each chapter is a JSON object with `id`, `title`, `kicker`, `summary`,
`opening_answer` (a short answer to say aloud), `sections`, and `takeaways`.

Each section has `id`, `title`, `level` (1 = basics, 2 = design, 3 = implementation),
and `blocks`. A block is one of:

- `{"type":"p","text":"Plain-language paragraph"}`
- `{"type":"list","items":["item"],"ordered":false}`
- `{"type":"table","headers":["Column"],"rows":[["Cell"]]}`
- `{"type":"code","language":"python","text":"literal code or pseudocode"}`
- `{"type":"callout","title":"Remember","text":"...","tone":"note"}`
- `{"type":"qa","q":"Question?","a":"Answer"}`
- `{"type":"visual","spec":{...sketch-diagrams JSON...}}`

Sections also have `sources`: `[{"path":"repo/relative/path","label":"Why read this"}]`.
All paths are relative to the repository root; page-local links can use an optional
`href` instead. Text permits **bold** and `inline code`, but no raw HTML.
Diagrams use the existing sketch-diagrams flow/layers/cards/hub/compare schema,
with at most four steps per flow. Diagram detail is plain text. Avoid unexplained
acronyms; teach what, why, how, and the tradeoff. Anchor claims to checked-in source.

Current reading snapshot: Main `8152ede`, verified engineering image source
`629119c` on 20 October 2026. Historical receipts retain their own identities.
This is a learning guide, not proof of personal authorship or team acceptance.

`glossary.json` is a list of term definitions. `aws-map.json` is a positioned SVG
topology specification for `draw_map.py`, not a chapter. The AWS chapter embeds
that generated diagram with a `svg` block.
