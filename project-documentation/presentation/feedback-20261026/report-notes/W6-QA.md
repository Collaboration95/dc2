# W6 render and source checks

Baseline: Main `76282d3b5a141f6548056f2506f9d5aff0742692`. Inspected 26 October 2026.

- Seven slide sections: new S10a, replacement S12, new S12a, replacements S13, S14, S15 and S19.
- Six PlantUML sources rendered successfully to both SVG and PNG using `~/dc2-tools/plantuml-1.2026.9.jar`. SVG XML parses, with no syntax-error or ignored-setting warning panels.
- Every final slide was rendered by T3 `html_preview` at **1280×720** and visually inspected, including all six figures. Seven PNGs are saved in `../slides/W6-QA/`; `../slides/W6-review.html` displays them offline. Renderer console messages: none.
- The collaborative preview's screenshot snapshot failed twice with `Preview automation snapshot timed out after 15000ms.` Screenshots were then produced with the HTML preview renderer. The preview's DOM evaluator remained available and independently checked a viewport of 1280×720.
- DOM bounds: all seven slides passed. Body content stays within x=50…1230, below the course tag (bottom 102.4), and above body bottom 644/footer top 682. Images all loaded. Views table and caption end at y=594.4; S12a figure/table at 597.9; the deepest diagram ends at 639.7. No title, tag, figure, table or footer overlap remained.
- The logical model was split into a service overview and Processing expansion. Two over-long headlines were shortened. The ten-row views table was compacted after an initial overflow check.
- **141 code citations, 62 distinct permalink targets** in `slides/W6.html` and `report-notes/W6.md`: each file and line exists in the pinned git tree, all links use `76282d3`. This is a local target/line audit, not a GitHub network-availability check.
- External framework links were checked through their primary sites: Kruchten's arXiv record, C4, arc42 section 7, and Rozanski/Woods viewpoints. A first arXiv HTML-format URL returned 404; the cited `https://arxiv.org/abs/2006.04975` record succeeded.
- `site/deck.html` is byte-identical to `git show 76282d3:project-documentation/presentation/site/deck.html`. `git diff --check` passes. No tracked file changes or commit were made. W6 outputs remain untracked for coordinator integration.

Limits: no live AWS inspection, deployed-source verification, encode execution, queue-denial test, CI run or assessor acceptance. W1–W5 figures and W3's added class-model slide remain their owners' integration work. The views map preserves original slide IDs; renumber it after integration.
