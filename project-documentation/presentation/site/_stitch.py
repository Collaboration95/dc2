"""Rebuild references.html from the per-page fragments in _refs/ (run after editing a fragment)."""

from pathlib import Path

HERE = Path(__file__).parent
GROUPS = [
    ("1-3.html", "Sections 1–3: context, conduct, logical architecture"),
    ("4-5.html", "Sections 4–5: physical architecture, DevOps"),
    ("6.html", "Section 6: demo"),
]
LEDE = (
    "Run IDs, commits, receipts and source files behind the numbers in the guide. "
    'The pages link here with small chips such as <a class="ref" href="#r-sl1021">sl1021</a>.'
)

shell = (HERE / "_template.html").read_text()
head = shell.split("<main>", 1)[0].replace(' aria-current="page"', "")
head = head.replace('<a href="references.html">', '<a href="references.html" aria-current="page">')
head = head.replace(
    "<title>3 · Logical architecture — FlickPond</title>", "<title>References — FlickPond</title>"
)
body = [
    '<main>\n  <p class="eyebrow">Evidence</p>\n  <h1>References</h1>\n'
    f'  <p class="lede">{LEDE}</p>\n'
]
for name, title in GROUPS:
    fragment = (HERE / "_refs" / name).read_text()
    body.append(f'  <section class="sub refs">\n    <h2>{title}</h2>\n{fragment}\n  </section>\n')
body.append("</main>\n</div>\n</body>\n</html>\n")
(HERE / "references.html").write_text(head + "".join(body))
