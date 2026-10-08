Team 17 Project Roadmap
Prepared 9 October 2026, Asia/Singapore.

Open index.html in a browser. Read explanation.html for the separate detailed explanation.
Keep this directory beside project-documentation/ and Media_player/ so original source links work.
No network dependency or build step is required.

For a local HTTP preview, run this from the dc2 repository root:
python3 -m http.server 8765 --bind 127.0.0.1
Then open http://127.0.0.1:8765/project-roadmap/

The website preserves all original documents and links to their existing paths.
It adds a planning guide, not replacement course materials or finished report content.
The original proposal and course documents remain authoritative.

The review is a 9 October planning snapshot. Dates do not imply completed work.
Suggested internal dates are labelled separately from proposal milestones and course dates.
Review marks are stored only in this browser. They are not team completion records.
Print roadmap includes every roadmap step and reference section.

Files:
index.html          Main seven-section roadmap.
explanation.html    Separate detailed project explanation.
style.css           Shared responsive and print styles.
app.js              Navigation and optional local review marks.
roadmap-data.json   Structured reference copy of the steps, milestones and source register.

Step 02 update:
The lecturer accepted the proposal, with detailed DDD justification still required.
The user selected local Media_player commit 885453726d629c524bf511d665311863d9bc70a5.
Upstream updates and the future remote/submodule transition are not step 02 prerequisites.

New files:
business-scope.html  Prepared step 02 business and scope pack.
business-scope.json  Stable persona, use-case and business-decision records.
business-scope.css   Persona and business-pack presentation styles.
records/project-decisions.txt  Exact supplied feedback, baseline and source provenance.
assets/persona-cast.png        Fictional doodle cast.
assets/persona-cast-prompt.txt Image-generation prompt and tool mode.
assets/business-context.svg   Editable black-box business context diagram.

The Project 1 original PDF has an additional byte-identical reference copy in
project-documentation/original-reference/Project Proposal_Ibrahim.pdf.
Its original Downloads file remains unchanged.
Steps 03–05 design documentation is now prepared. Application implementation has not started.

Steps 03–05 update:
design-studio.html / design-studio.css / design-studio.js: the new reading pages.
build-design-studio.py rebuilds this page from design/*/content.json and manifests.
design/03-ddd/: domain analysis, native tldraw diagram references, sources and SVG.
design/04-architecture/: architecture, AD-01–AD-08, diagrams and sources.
design/05-contracts/: three OpenAPI designs, persistence record, examples and
25 planned cases. All are design artifacts, not runtime test results.
assets/persona-poses.png and persona-poses-prompt.txt contain the transparent
illustration variants and their built-in image-generation prompt.
Each module links an editable tldraw board; boards are shared for editing by link.
SVG files are snapshots. Board edits do not automatically update this website.

Steps 06–08 update:
build-preparation.html / preparation.css / preparation.js: preparation UI.
build-preparation.py renders design/06-security-recovery, 07-deployment and
08-build-readiness content.json, choices.json and optional download/diagram
manifests. Run python3 project-roadmap/build-preparation.py from the root.
The generator requires complete authored inputs and referenced artifacts;
it does not publish placeholder final content. Step 08 diagrams are optional.
Recommended defaults await team confirmation; proposal commitments remain
recorded. Native comparison dialogs create no selection or approval.
Print includes every module and a complete comparison appendix.
preparation.js exposes FlickPondComparisons.init(root) for reuse.
AD-01–AD-08 comparisons in design-studio.html derive from the existing
architecture-decisions.json; earlier-choices.json is a generated derivative.
Run python3 project-roadmap/build-design-studio.py to rebuild those buttons.
Steps 06/07 link the user-supplied shared editable tldraw board through their
manifests. No board iframe or new board is created. SVG previews are snapshots.
Local build planning inputs are prepared for a later implementation task;
cloud execution requires verified access, capacity, secrets, TLS and budget.
Step 09 remains not started. Runtime results remain not run.
