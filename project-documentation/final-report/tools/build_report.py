#!/usr/bin/env python3
"""Build the Team 17 final report from ``src/*.md``.

The course template supplies the page layout, footer, heading styles and heading numbering.
Pandoc converts the Markdown sources. This script then restores the template's heading
numbering, formats tables, and asks Microsoft Word (macOS) to fill the table of contents and
export a PDF.

    python3 project-documentation/final-report/tools/build_report.py            # DOCX and PDF
    python3 project-documentation/final-report/tools/build_report.py --no-word  # DOCX only
    python3 project-documentation/final-report/tools/build_report.py --pages    # also PNG pages
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
TEMPLATE = (
    REPO
    / "project-documentation/original-reference/02 Project Report Template for Practice Project.docx"
)
SRC = ROOT / "src"
OUT_DOCX = ROOT / "Team17-Final-Report.docx"
OUT_PDF = ROOT / "Team17-Final-Report.pdf"

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

# Styles added to (or replacing those in) the template. Sizes are half-points.
EXTRA_STYLES = {
    "BodyText": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="BodyText">
<w:name w:val="Body Text"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="100" w:after="120" w:line="264" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>
<w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>""",
    "FirstParagraph": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="FirstParagraph">
<w:name w:val="First Paragraph"/><w:basedOn w:val="BodyText"/><w:next w:val="BodyText"/><w:qFormat/></w:style>""",
    "Compact": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="Compact">
<w:name w:val="Compact"/><w:basedOn w:val="BodyText"/><w:qFormat/>
<w:pPr><w:spacing w:before="20" w:after="40"/><w:jc w:val="left"/></w:pPr></w:style>""",
    "TableText": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableText">
<w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/></w:pPr>
<w:rPr><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>""",
    "ImageCaption": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="ImageCaption">
<w:name w:val="Image Caption"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="60" w:after="240"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:i/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>""",
    "TableCaption": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableCaption">
<w:name w:val="Table Caption"/><w:basedOn w:val="ImageCaption"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:jc w:val="left"/></w:pPr></w:style>""",
    "CaptionedFigure": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="CaptionedFigure">
<w:name w:val="Captioned Figure"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="120" w:after="0"/><w:jc w:val="center"/></w:pPr></w:style>""",
    "Figure": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="Figure">
<w:name w:val="Figure"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:jc w:val="center"/></w:pPr></w:style>""",
    "CoverLogo": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="CoverLogo">
<w:name w:val="Cover Logo"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="600" w:after="1200"/><w:jc w:val="center"/></w:pPr></w:style>""",
    "CoverTitle": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="CoverTitle">
<w:name w:val="Cover Title"/><w:basedOn w:val="Title"/><w:qFormat/>
<w:pPr><w:spacing w:before="0" w:after="600"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>""",
    "CoverText": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="CoverText">
<w:name w:val="Cover Text"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="0" w:after="240"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>""",
    "CoverSmall": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="CoverSmall">
<w:name w:val="Cover Small"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="0" w:after="60"/><w:jc w:val="center"/></w:pPr>
<w:rPr><w:color w:val="595959"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>""",
    "ContentsHeading": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="ContentsHeading">
<w:name w:val="Contents Heading"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:before="0" w:after="240"/></w:pPr>
<w:rPr><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>""",
    "BlockText": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="BlockText">
<w:name w:val="Block Text"/><w:basedOn w:val="BodyText"/><w:qFormat/>
<w:pPr><w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="2F5496"/></w:pBdr>
<w:shd w:val="clear" w:color="auto" w:fill="F2F5FA"/><w:spacing w:before="120" w:after="160"/>
<w:ind w:left="240" w:right="120"/></w:pPr></w:style>""",
    "SourceCode": """<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode">
<w:name w:val="Source Code"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:before="60" w:after="60" w:line="240" w:lineRule="auto"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Menlo" w:hAnsi="Menlo" w:cs="Menlo"/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr></w:style>""",
    "VerbatimChar": """<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar">
<w:name w:val="Verbatim Char"/>
<w:rPr><w:rFonts w:ascii="Menlo" w:hAnsi="Menlo" w:cs="Menlo"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>""",
    "Hyperlink": """<w:style w:type="character" w:styleId="Hyperlink">
<w:name w:val="Hyperlink"/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>""",
    "Table": """<w:style w:type="table" w:customStyle="1" w:styleId="Table">
<w:name w:val="Table"/><w:basedOn w:val="TableNormal"/><w:qFormat/>
<w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
<w:left w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
<w:right w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
<w:insideV w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>
</w:tblBorders><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>
<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>
<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr>
<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="DCE4F2"/></w:tcPr></w:tblStylePr>
</w:style>""",
}

TOC_FIELD = (
    '<w:p><w:pPr><w:pStyle w:val="TOC1"/><w:tabs><w:tab w:val="right" w:leader="dot" '
    'w:pos="9016"/></w:tabs></w:pPr><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>Update this field to show the '
    'table of contents.</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
)

WORD_SCRIPT = r"""
on run argv
  set inPath to item 1 of argv
  set pdfPath to item 2 of argv
  with timeout of 1200 seconds
  tell application "Microsoft Word"
    open (POSIX file inPath)
    repeat 600 times
      if (count of documents) > 0 then exit repeat
      delay 1
    end repeat
    set theDoc to document 1
    update table of contents 1 of theDoc
    save theDoc
    save as theDoc file name pdfPath file format format PDF
    close theDoc saving no
  end tell
  end timeout
end run
"""


def build_reference(tmp: Path) -> Path:
    """Return a reference DOCX: the template with the extra styles."""
    ref = tmp / "reference.docx"
    with zipfile.ZipFile(TEMPLATE) as src, zipfile.ZipFile(ref, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/styles.xml":
                xml = data.decode("utf-8")
                for style_id, style in EXTRA_STYLES.items():
                    pattern = re.compile(
                        rf'<w:style [^>]*w:styleId="{re.escape(style_id)}"[^>]*>.*?</w:style>', re.S
                    )
                    xml = pattern.sub("", xml)
                    xml = xml.replace("</w:styles>", style.replace("\n", "") + "</w:styles>")
                data = xml.encode("utf-8")
            dst.writestr(item, data)
    return ref


def balance_tables(text: str) -> str:
    """Rewrite each pipe table's separator row so column widths follow their content.

    Pandoc sizes columns by the separator's dash counts. Each column gets a share that covers its
    longest word (capped, since long code spans wrap anyway) and grows with its average cell
    length, so short identifier, owner and status columns no longer break mid-word.
    """
    lines = text.split("\n")
    sep = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    for i, line in enumerate(lines):
        if not sep.match(line) or i == 0:
            continue
        aligns = cells(line)
        rows = [cells(lines[i - 1])]
        j = i + 1
        while j < len(lines) and lines[j].startswith("|"):
            rows.append(cells(lines[j]))
            j += 1
        if any(len(r) != len(aligns) for r in rows):
            continue
        weights = []
        for c in range(len(aligns)):
            column = [re.sub(r"[`*\\]", "", r[c]) for r in rows]
            longest = max((len(w) for v in column for w in v.split()), default=1)
            average = sum(len(v) for v in column) / len(column)
            weights.append(max((min(longest, 14) + 2) * 1.7, min(average, 90) * 0.55, 8))
        total = sum(weights)
        new = []
        for align, weight in zip(aligns, weights, strict=False):
            dashes = "-" * max(3, round(120 * weight / total))
            left = ":" if align.startswith(":") else ""
            right = ":" if align.endswith(":") else ""
            new.append(left + dashes + right)
        lines[i] = "|" + "|".join(new) + "|"
    return "\n".join(lines)


def number_figures(text: str) -> str:
    """Number ``{#fig:key}`` captions in order and resolve ``{@fig:key}`` references."""
    numbers: dict[str, int] = {}
    for key in re.findall(r"\{#fig:([\w-]+)\}", text):
        if key in numbers:
            sys.exit(f"duplicate figure label {key}")
        numbers[key] = len(numbers) + 1
    missing = sorted(set(re.findall(r"\{@fig:([\w-]+)\}", text)) - set(numbers))
    if missing:
        sys.exit("unknown figure references: {}".format(", ".join(missing)))
    text = re.sub(r"\{#fig:([\w-]+)\}", lambda m: str(numbers[m.group(1)]), text)
    return re.sub(r"\{@fig:([\w-]+)\}", lambda m: str(numbers[m.group(1)]), text)


def run_pandoc(reference: Path, out: Path) -> None:
    sources = sorted(SRC.glob("*.md"))
    if not sources:
        sys.exit(f"no sources in {SRC}")
    combined = out.with_suffix(".md")
    text = number_figures("\n\n".join(p.read_text(encoding="utf-8") for p in sources))
    text = balance_tables(text)
    combined.write_text(text, encoding="utf-8")
    subprocess.run(
        [
            "pandoc",
            str(combined),
            "--from",
            "markdown+pipe_tables+grid_tables+raw_attribute+fenced_divs+bracketed_spans"
            "+implicit_figures+link_attributes-auto_identifiers+auto_identifiers",
            "--reference-doc",
            str(reference),
            "--resource-path",
            str(ROOT),
            "-o",
            str(out),
        ],
        check=True,
    )


def heading_numbering(template_numbering: str, numbering: str) -> str:
    """Copy the template's numId 1 (heading numbering) into pandoc's numbering part."""
    num = re.search(r'<w:num w:numId="1"[^>]*>.*?</w:num>', template_numbering, re.S).group(0)
    abstract_id = re.search(r'<w:abstractNumId w:val="(\d+)"', num).group(1)
    abstract = re.search(
        rf'<w:abstractNum [^>]*w:abstractNumId="{abstract_id}"[^>]*>.*?</w:abstractNum>',
        template_numbering,
        re.S,
    ).group(0)
    new_id = "990"
    abstract = re.sub(r'w:abstractNumId="\d+"', f'w:abstractNumId="{new_id}"', abstract, count=1)
    num = re.sub(r'<w:abstractNumId w:val="\d+"', f'<w:abstractNumId w:val="{new_id}"', num)
    first_num = numbering.find("<w:num ")
    if first_num == -1:
        numbering = numbering.replace("</w:numbering>", abstract + num + "</w:numbering>")
    else:
        numbering = numbering[:first_num] + abstract + numbering[first_num:]
        numbering = numbering.replace("</w:numbering>", num + "</w:numbering>")
    return numbering


def format_tables(document: str) -> str:
    def one_table(match: re.Match) -> str:
        table = match.group(0)
        # Pandoc styles cell paragraphs "Compact"; tables use the smaller "Table Text".
        table = re.sub(r'<w:pStyle w:val="Compact"\s*/>', '<w:pStyle w:val="TableText"/>', table)
        table = re.sub(
            r'<w:rStyle w:val="VerbatimChar"\s*/>',
            '<w:rStyle w:val="VerbatimChar"/><w:sz w:val="15"/><w:szCs w:val="15"/>',
            table,
        )
        table = re.sub(r"<w:tblW [^>]*/>", '<w:tblW w:type="pct" w:w="5000"/>', table, count=1)
        # Pandoc already repeats the header row; also keep each row on one page.
        table = re.sub(r"<w:tr>(?!<w:trPr>)", "<w:tr><w:trPr><w:cantSplit/></w:trPr>", table)
        # Keep the header and the first two rows together, so a table never starts with a lone
        # row at the foot of a page; longer tables still break normally after that.
        rows = re.split(r"(?=<w:tr>)", table)
        for k in range(1, min(4, len(rows) - 1)):
            rows[k] = rows[k].replace(
                '<w:pStyle w:val="TableText"/>', '<w:pStyle w:val="TableText"/><w:keepNext/>'
            )
        return "".join(rows)

    return re.sub(r"<w:tbl>.*?</w:tbl>", one_table, document, flags=re.S)


def insert_toc(document: str) -> str:
    marker = re.search(r"<w:p>(?:(?!<w:p>).)*?TOC-PLACEHOLDER.*?</w:p>", document, re.S)
    if not marker:
        sys.exit("TOC-PLACEHOLDER paragraph not found")
    return document[: marker.start()] + TOC_FIELD + document[marker.end() :]


def landscape_sections(document: str) -> str:
    """Turn LANDSCAPE-START/END marker paragraphs into section breaks around landscape pages."""
    portrait = re.findall(r"<w:sectPr\b.*?</w:sectPr>", document, re.S)[-1]
    landscape = re.sub(
        r"<w:pgSz\b[^>]*/>", '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>', portrait
    )

    def marker(name: str) -> re.Pattern:
        return re.compile(rf"<w:p>(?:(?!<w:p>).)*?{name}.*?</w:p>", re.S)

    document = marker("LANDSCAPE-START").sub(
        lambda _: f"<w:p><w:pPr>{portrait}</w:pPr></w:p>", document
    )
    return marker("LANDSCAPE-END").sub(lambda _: f"<w:p><w:pPr>{landscape}</w:pPr></w:p>", document)


def postprocess(body: Path, out: Path) -> None:
    with zipfile.ZipFile(TEMPLATE) as tpl:
        template_numbering = tpl.read("word/numbering.xml").decode("utf-8")
    with zipfile.ZipFile(body) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/numbering.xml":
                data = heading_numbering(template_numbering, data.decode("utf-8")).encode("utf-8")
            elif item.filename == "docProps/core.xml":
                xml = data.decode("utf-8")
                for tag, value in (
                    (
                        "dc:title",
                        "Project Report for FlickPond: A Reusable Cloud Media Processing Platform",
                    ),
                    ("dc:creator", "Team 17: Guruprasath Gopal, Ibrahim Mammadov, Nguyen Kim Long"),
                    ("dc:subject", "SWE5001 Architecting Scalable Systems practice module report"),
                ):
                    xml = re.sub(rf"<{tag}>.*?</{tag}>|<{tag}\s*/>", "", xml, flags=re.S)
                    xml = xml.replace(
                        "</cp:coreProperties>", f"<{tag}>{value}</{tag}></cp:coreProperties>"
                    )
                data = xml.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                xml = data.decode("utf-8")
                if 'Extension="png"' not in xml:
                    png = '<Default Extension="png" ContentType="image/png"/>'
                    xml = xml.replace("<Default ", png + "<Default ", 1)
                data = xml.encode("utf-8")
            elif item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                xml = format_tables(xml)
                xml = insert_toc(xml)
                xml = landscape_sections(xml)
                data = xml.encode("utf-8")
            dst.writestr(item, data)


def word_export(docx: Path, pdf: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as script:
        script.write(WORD_SCRIPT)
    subprocess.run(["osascript", script.name, str(docx), str(pdf)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-word", action="store_true", help="skip the Word TOC and PDF step")
    parser.add_argument("--pages", action="store_true", help="render PDF pages to PNG for review")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        reference = build_reference(tmp)
        body = tmp / "body.docx"
        run_pandoc(reference, body)
        postprocess(body, OUT_DOCX)
    print("wrote", OUT_DOCX.relative_to(REPO))
    if args.no_word:
        return
    word_export(OUT_DOCX, OUT_PDF)
    print("wrote", OUT_PDF.relative_to(REPO))
    if args.pages:
        pages = REPO / ".claude" / "report-work" / "pages"
        shutil.rmtree(pages, ignore_errors=True)
        pages.mkdir()
        subprocess.run(
            ["pdftoppm", "-png", "-r", "70", str(OUT_PDF), str(pages / "page")], check=True
        )
        print("pages in", pages)


if __name__ == "__main__":
    main()
