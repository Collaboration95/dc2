#!/usr/bin/env python3
"""Build a standalone public guide without private course attachments."""

import argparse
import html
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import build

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SOURCE_REVISION = "d0d745faee003f8b40402360370561d95cc3475c"
SOURCE_URL = f"https://github.com/Collaboration95/dc2/blob/{SOURCE_REVISION}/"
STATIC_SUFFIXES = {".css", ".js", ".svg", ".woff2", ".txt"}
PRIVATE_PATTERNS = (r"zoom\.us", r"[?&]pwd=", r"Meeting ID:", r"Passcode:", r"/Users/")


def public_link(href: str) -> str:
    """Keep navigation local; open reviewed source on GitHub, never a local path."""
    parsed = urlsplit(href)
    path = unquote(parsed.path)
    if path.startswith("references/"):
        return "course-guidance.html#schedule"
    if not path.startswith("../"):
        return href
    relative = path.removeprefix("../")
    target = (REPO / relative).resolve()
    if not target.is_relative_to(REPO) or not target.exists():
        raise ValueError(f"Invalid source reference: {relative}")
    if target.suffix.lower() in {".pdf", ".docx"}:
        return "course-guidance.html#primary-sources"
    base = SOURCE_URL.replace("/blob/", "/tree/") if target.is_dir() else SOURCE_URL
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return base + quote(relative, safe="/") + fragment


class Links(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.links: list[str] = []
        self.ids: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        for attribute in ("href", "src"):
            if attribute in values:
                self.links.append(values[attribute])


def public_html(text: str) -> str:
    def replace_link(match):
        href = html.unescape(match.group(1))
        return f'href="{html.escape(public_link(href), quote=True)}"'

    text = re.sub(r'href="([^"]*)"', replace_link, text)
    text = text.replace(
        "These are local repository links. If you move the guide away from the repository, "
        "the study pages still work, but these source links need the repository beside them.",
        "Code and evidence links open the reviewed source snapshot on GitHub. "
        "You do not need to download the repository. Course attachments are represented "
        "by a public guidance summary that omits meeting access details.",
    )
    text = text.replace(
        "Their copies are linked in the showcase chapter; check Canvas for any later change.",
        "The user confirmed that date. The public guidance summary is linked in the "
        "showcase chapter; check Canvas for later changes.",
    )
    for label in (
        "Revised local guide: Team 17 in the 26 October afternoon table",
        "Archived presentation guide: same Team 17 slot",
    ):
        text = text.replace(label, "Presentation guidance and confirmed slot (public summary)")
    return text


def guidance() -> str:
    rows = [
        ("Overview", "2 + 1 min", "Problem, platform thinking and scope."),
        (
            "Project Conduct",
            "1.5 + 0.5 min",
            "Status, issues, actual milestones and member effort.",
        ),
        (
            "Logical Architecture",
            "7 + 2 min",
            "Decisions, components, DDD, producers and consumers.",
        ),
        (
            "Physical Architecture",
            "7 + 2 min",
            "Network, nodes, cloud services, persistence and one detailed use case.",
        ),
        (
            "DevOps / Lifecycle",
            "6 + 1 min",
            "Source/artifact management, pipeline, procedures and technical findings.",
        ),
        (
            "Demonstration",
            "8 + 2 min",
            "Significant use cases and evidence for quality attributes.",
        ),
    ]
    body = """<header class="page-head"><p class="eyebrow">Course reference / Public summary</p>
<h1>Presentation guidance.</h1><p class="lede">The relevant course expectations, without
republishing private meeting access details or course attachments.</p></header>
<section id="schedule"><h2>Team 17: 26 October, 14:35–15:15 SGT</h2>
<p>The user confirmed this date. Both inspected local schedule tables place Team 17 in the
26 October afternoon slot. The total slot is 40 minutes, including questions.
Use Canvas and the team’s existing course materials for meeting access and later updates.</p>
</section>
<section><h2>Six areas in the presentation outline</h2>
<p>These are the guide’s approximate suggested allocations. Each pair is explanation time
plus Q&amp;A time, not a minimum speaking duration.</p>"""
    body += build.block(
        {"type": "table", "headers": ["Area", "Suggested time", "Cover"], "rows": rows}
    )
    body += """<p>Present from the business problem down to the implementation. Highlight the
decisions, significant outcomes and limitations. Rehearse a prepared demo and a clearly
labelled fallback. <a href="meeting.html?depth=3">Use the complete rehearsal chapter →</a></p>
</section>
<section id="primary-sources"><h2>Which sources this summary represents</h2>
<p>The current GC2 briefing, Team 17 proposal, report template and presentation guide govern
the project scope and showcase. The original PDFs and proposal document are not bundled
with this public website. This page is a paraphrased study aid, not a new course instruction.</p>
<p>The older SWE5006 course ZIP contributes an engineering-completeness checklist. Its sample
proposals, dates, grading weights and 13+4-minute demo timing do not replace GC2 guidance.</p>
<p>A finished final GC2 report was not found when the study guide was prepared. The guide uses
the proposal, implementation and dated engineering evidence. Personal contributions, actual
hours and submission receipts still need their own team-confirmed records.</p>
<p><a href="sources.html">Return to the evidence and source map →</a></p></section>"""
    return build.shell("sources", "Presentation guidance", body)


def validate(output: Path) -> dict:
    output = output.resolve()
    pages = {p: Links(p.read_text()) for p in output.glob("*.html")}
    checked = 0
    for path, page in pages.items():
        if len(page.ids) != len(set(page.ids)):
            raise ValueError(f"Duplicate HTML id in {path.name}")
        for href in page.links:
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc:
                if parsed.scheme != "https":
                    raise ValueError(f"Non-HTTPS external link in {path.name}")
                continue
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if not target.is_relative_to(output) or not target.exists():
                raise ValueError(f"Broken public link in {path.name}: {href}")
            if (
                parsed.fragment
                and target in pages
                and unquote(parsed.fragment) not in pages[target].ids
            ):
                raise ValueError(f"Broken anchor in {path.name}: {href}")
            checked += 1
    for path in output.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in STATIC_SUFFIXES | {".html"} and path.name != ".nojekyll":
            raise ValueError(f"Unexpected public artifact: {path.name}")
        if path.suffix in {".html", ".js", ".css", ".svg", ".txt"}:
            text = path.read_text()
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in PRIVATE_PATTERNS):
                raise ValueError(f"Private reference pattern in {path.name}")
    return {"pages": len(pages), "local_references_checked": checked, "private_attachments": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT.is_relative_to(output) or output.exists():
        parser.error("output must be a new directory outside the source tree's ancestors")
    build.main()
    output.mkdir(parents=True)
    for source in ROOT.glob("*.html"):
        (output / source.name).write_text(public_html(source.read_text()))
    for source in (ROOT / "assets").rglob("*"):
        if source.is_file() and source.suffix in STATIC_SUFFIXES:
            target = output / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (output / "course-guidance.html").write_text(guidance())
    (output / ".nojekyll").touch()
    print(json.dumps(validate(output), indent=2))


if __name__ == "__main__":
    main()
