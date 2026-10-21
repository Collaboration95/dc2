# Team 17 final report (GC2)

`Team17-Final-Report.docx` is the submission file. It follows the course template
(`../original-reference/02 Project Report Template for Practice Project.docx`): cover, contents,
sections 1–6 with every template sub-heading, and appendices. `Team17-Final-Report.pdf` is the
same document exported by Word.

## Layout

| Path | Contents |
|---|---|
| `src/*.md` | Report text, one file per template section, concatenated in file-name order |
| `figures/*.png` | Rendered figures (2x). `figures/src/` holds the Mermaid and SVG sources written for the report (`report-*`), and the blocks extracted from `docs/architecture/` |
| `data/issue-burnup.csv` | Issue counts per day from `gh issue list --state all`; drawn by `tools/chart_burnup.py` |
| `tools/build_report.py` | Pandoc build against the template's styles; restores heading numbering, formats tables, numbers figures, adds landscape pages; Word fills the contents and exports the PDF |
| `tools/render_figures.py` | Renders SVG and Mermaid sources to PNG with headless Chrome and mermaid-cli |

## Rebuild

Needs pandoc, Google Chrome, Node (for `npx` mermaid-cli) and Microsoft Word for macOS.

```bash
python3 project-documentation/final-report/tools/chart_burnup.py      # only if the CSV changed
python3 project-documentation/final-report/tools/render_figures.py    # only changed figures render
python3 project-documentation/final-report/tools/build_report.py      # DOCX and PDF
python3 project-documentation/final-report/tools/build_report.py --no-word   # DOCX only, no Word
```

Figures are referenced by label: write `![Figure {#fig:key}. Caption](figures/x.png)` and refer to
it as `Figure {@fig:key}`. The build numbers them in order and fails on a missing or duplicate
label. Wrap wide figures in the `LANDSCAPE-START` / `LANDSCAPE-END` raw blocks used in
`src/70-appendices.md`.

## After the presentation (26 October 2026)

The briefing asks the final report to incorporate the presentation remarks.

1. Add a section **"Presentation Feedback and Response"** to `src/60-other.md`, after "Lessons
   Learned". Use a table with one row per remark: *Remark*, *Response*, *Change made* (with the
   section it changed) and *Status*.
2. Make the changes the remarks require in the relevant `src/` files.
3. Change the report version on the cover (`src/00-front.md`) to 1.1 and the date.
4. Update the milestone rows for 26 October onwards in `src/20-conduct.md`, and the effort ledger
   if the forecast changed.
5. Rebuild and upload the DOCX (or PDF, if the Canvas instructions ask for it) before
   **16 November 2026**.
