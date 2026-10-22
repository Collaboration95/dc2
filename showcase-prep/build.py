#!/usr/bin/env python3
"""Build the offline showcase guide. Python standard library only."""

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

from draw_map import render as render_map
from sketch_render import visual

ROOT = Path(__file__).resolve().parent
ORDER = [
    "basics",
    "architecture",
    "aws",
    "delivery",
    "code",
    "data",
    "security",
    "quality",
    "meeting",
]
SHORT = [
    "The project",
    "Architecture",
    "AWS",
    "CI / CD",
    "Code & abstractions",
    "Data & recovery",
    "Security",
    "Tests & evidence",
    "The showcase",
]
LEVELS = {1: "Understand the basics", 2: "Explain the design", 3: "Defend the details"}


def esc(value):
    return html.escape(str(value), quote=True)


def rich(value):
    value = esc(value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)


def link(source):
    href = source.get("href") or "../" + quote(source["path"], safe="/#")
    return f'<a href="{esc(href)}">{esc(source["label"])}</a>'


def block(b):
    kind = b["type"]
    if kind == "p":
        return f"<p>{rich(b['text'])}</p>"
    if kind == "list":
        tag = "ol" if b.get("ordered") else "ul"
        return f"<{tag}>" + "".join(f"<li>{rich(x)}</li>" for x in b["items"]) + f"</{tag}>"
    if kind == "table":
        head = "".join(f'<th scope="col">{rich(x)}</th>' for x in b["headers"])
        rows = "".join(
            "<tr>"
            + "".join(
                f'<td data-label="{esc(b["headers"][i])}">{rich(x)}</td>' for i, x in enumerate(row)
            )
            + "</tr>"
            for row in b["rows"]
        )
        title = f'<p class="table-title"><strong>{rich(b["title"])}</strong></p>' if b.get("title") else ""
        return (
            title + '<div class="table-wrap"><table class="grid"><thead><tr>'
            f"{head}"
            "</tr></thead><tbody>"
            f"{rows}"
            "</tbody></table></div>"
        )
    if kind == "code":
        return (
            '<div class="code-label">'
            f"{esc(b.get('language', 'example'))}"
            "</div><pre><code>"
            f"{esc(b['text'])}"
            "</code></pre>"
        )
    if kind == "callout":
        return (
            '<aside class="callout '
            f"{esc(b.get('tone', 'note'))}"
            '"><strong>'
            f"{esc(b['title'])}"
            "</strong><p>"
            f"{rich(b['text'])}"
            "</p></aside>"
        )
    if kind == "qa":
        return (
            '<details class="qa"><summary>'
            f"{rich(b['q'])}"
            '</summary><div class="answer">'
            f"{rich(b['a'])}"
            "</div></details>"
        )
    if kind == "visual":
        fig = visual(b["spec"], icon_dir=ROOT / "assets/icons", icon_url="assets/icons")
        spec = b["spec"]
        nodes = spec.get("steps", spec.get("layers", spec.get("items", [])))
        if "center" in spec:
            nodes = [spec["center"]] + nodes
        notes = "".join(
            f"<li><strong>{esc(n['label'])}</strong> — {esc(n['detail'])}</li>"
            for n in nodes
            if n.get("detail")
        )
        return fig + (
            (
                '<details class="diagram-notes"><summary>Read all diagram '
                "notes</summary><ul>"
                f"{notes}"
                "</ul></details>"
            )
            if notes
            else ""
        )
    if kind == "svg":
        return (
            '<figure class="visual physical-map"><p class="vtitle">'
            f"{esc(b['title'])}"
            '</p><div class="map-scroll" tabindex="0" role="region" '
            'aria-label="Physical architecture diagram; scroll horizontally '
            'on a small screen"><img src="'
            f"{esc(b['path'])}"
            '" alt="'
            f"{esc(b['alt'])}"
            '" width="1000" height="850"></div><p class="caption">'
            f"{rich(b['caption'])}"
            '</p><a class="small" href="'
            f"{esc(b['path'])}"
            '" target="_blank" rel="noopener">Open the full-size diagram ↗</a>'
            "</figure>"
        )
    raise ValueError(f"Unknown block: {kind}")


def sections(page, prefix=""):
    result = ""
    for s in sorted(page["sections"], key=lambda item: item["level"]):
        sources = " · ".join(link(x) for x in s.get("sources", []))
        result += (
            '<section id="'
            f"{prefix}"
            f"{esc(s['id'])}"
            '" data-level="'
            f"{s['level']}"
            '"><p class="eyebrow">Level '
            f"{s['level']}"
            " / "
            f"{LEVELS[s['level']]}"
            "</p><h2>"
            f"{esc(s['title'])}"
            "</h2>"
        )
        result += "".join(block(b) for b in s["blocks"])
        if sources:
            result += (
                '<details class="sources"><summary>Check the source</summary><p>'
                f"{sources}"
                "</p></details>"
            )
        result += "</section>"
    return result


def nav(active):
    items = "".join(
        (
            "<a "
            f"""{('aria-current="page"' if active == slug else "")}"""
            ' href="'
            f"{slug}"
            '.html"><span>'
            f"{i + 1:02d}"
            "</span>"
            f"{label}"
            "</a>"
        )
        for i, (slug, label) in enumerate(zip(ORDER, SHORT, strict=True))
    )
    refs = "".join(
        (
            "<a "
            f"""{('aria-current="page"' if active == slug else "")}"""
            ' href="'
            f"{slug}"
            '.html">'
            f"{label}"
            "</a>"
        )
        for slug, label in [
            ("questions", "Practise Q&A"),
            ("glossary", "Plain-English glossary"),
            ("sources", "Evidence & source map"),
            ("all-in-one", "Everything on one page"),
        ]
    )
    return (
        '<aside class="sidebar"><a class="brand" href="index.html"><span '
        'class="brand-mark">fp.</span><span>FlickPond<small>Showcase '
        'field guide</small></span></a><details class="chapter-nav" open>'
        '<summary>Learning path</summary><nav aria-label="Chapters"><a '
        f"""{('aria-current="page"' if active == "index" else "")}"""
        ' href="index.html"><span>↗</span>Start here</a>'
        f"{items}"
        '<p class="nav-label">Keep within reach</p>'
        f"{refs}"
        '</nav></details><p class="sidebar-note">Team 17 · GC2<br>Source '
        "snapshot · 22 Oct 2026<br><a "
        'href="sources.html#release-identities">Code d0d745f / runtime '
        "c7c489c</a></p></aside>"
    )


def shell(
    active,
    title,
    content,
    description="A progressive study guide to FlickPond, its AWS architecture, CI/CD and code.",
):
    versions = {
        name: hashlib.sha256((ROOT / "assets" / name).read_bytes()).hexdigest()[:10]
        for name in ("site.css", "sketch.css", "site.js")
    }
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width,initial-scale=1"><meta '
        'name="description" content="'
        f"{esc(description)}"
        '"><title>'
        f"{esc(title)}"
        ' · FlickPond study guide</title><link rel="icon" '
        'href="assets/favicon.svg" type="image/svg+xml"><link '
        'rel="stylesheet" href="assets/site.css?v='
        f"{versions['site.css']}"
        '"><link rel="stylesheet" href="assets/sketch.css?v='
        f"{versions['sketch.css']}"
        '"></head>\n<body data-page="'
        f"{esc(active)}"
        '"><a class="skip" href="#main">Skip to content</a><div '
        'class="layout">'
        f"{nav(active)}"
        '<main id="main">'
        f"{content}"
        "<footer><span>Learn the system. Explain the choices. Keep the "
        'evidence honest.</span><a href="index.html">Back to the learning '
        'path ↑</a></footer></main></div><script src="assets/site.js?v='
        f"{versions['site.js']}"
        '"></script></body></html>'
    )


def controls():
    return (
        '<div class="depth-controls" role="group" aria-label="Reading '
        'depth"><span>Reading depth</span><button type="button" '
        'data-depth="1" aria-pressed="false">1 · Basics</button><button '
        'type="button" data-depth="2" aria-pressed="false">2 · + '
        'Design</button><button type="button" data-depth="3" '
        'aria-pressed="true">3 · + Details</button></div><p '
        'class="depth-hint" aria-live="polite">All three levels are '
        "visible. Start with Basics if this is your first read.</p>"
    )


def chapter(page, index):
    word_count = len(re.findall(r"\b\w+\b", json.dumps(page, ensure_ascii=False)))
    header = (
        '<header class="page-head"><p class="eyebrow">Chapter '
        f"{index + 1:02d}"
        " / "
        f"{esc(page['kicker'])}"
        "</p><h1>"
        f"{esc(page['title'])}"
        '</h1><p class="lede">'
        f"{esc(page['summary'])}"
        '</p><p class="meta">Three levels · approximately '
        f"{max(5, round(word_count / 220))}"
        " minutes for the full chapter</p></header>"
    )
    opening = (
        '<div class="say-it"><span class="eyebrow">Say it in your own '
        "words</span><p>"
        f"{rich(page['opening_answer'])}"
        "</p></div>"
    )
    toc = (
        '<nav class="on-page" aria-label="On this page">'
        + "".join(
            f'<a data-level="{s["level"]}" href="#{esc(s["id"])}">{esc(s["title"])}</a>'
            for s in sorted(page["sections"], key=lambda x: x["level"])
        )
        + "</nav>"
    )
    end = (
        (
            '<div class="go-deeper"><p>Ready for the next layer?</p><button '
            'type="button" id="next-depth">Show the design</button></div>'
            '<section class="takeaways"><p class="eyebrow">Before you move '
            "on</p><h2>Can you explain these without reading?</h2><ul>"
        )
        + "".join(f"<li>{rich(t)}</li>" for t in page["takeaways"])
        + '</ul><a href="questions.html?chapter='
        + page["id"]
        + '">Practise this chapter’s questions →</a></section>'
    )
    prev = "index" if index == 0 else ORDER[index - 1]
    nxt = "questions" if index == len(ORDER) - 1 else ORDER[index + 1]
    pager = (
        '<div class="pager"><a href="'
        f"{prev}"
        '.html">← Previous</a><a class="next" href="'
        f"{nxt}"
        '.html">'
        f"{('Practise Q&A' if nxt == 'questions' else SHORT[index + 1])}"
        " →</a></div>"
    )
    return shell(
        page["id"],
        page["title"],
        header + opening + controls() + toc + sections(page) + end + pager,
    )


def home(pages):
    hero = (
        '<header class="page-head"><p class="eyebrow">Team 17 / Project '
        "showcase preparation</p><h1>Know the project.<br>Tell its "
        'story.</h1><p class="lede">A guided tour of FlickPond, from '
        "“what did we build?” to the code, cloud services and engineering "
        "choices you can defend in a discussion.</p></header>\n<aside "
        'class="callout"><strong>Team 17 · 26 October · 14:35–15:15 '
        "SGT</strong><p>Both local presentation guides list this "
        "40-minute slot, including questions. The showcase chapter maps "
        "the six presentation areas to what you can explain and "
        'demonstrate. <a href="meeting.html#authority">Read the '
        'presentation guidance →</a></p></aside>\n<div class="say-it">'
        '<span class="eyebrow">The project in one breath</span><p>'
        "FlickPond is a reusable video-processing platform. A browser app "
        "and a Publisher command-line client use the same public APIs to "
        "upload an owner’s video, track background conversion and play "
        "the result. Media owns the user’s content; Processing owns the "
        "work.</p></div>"
    )
    route = {
        "type": "flow",
        "title": "Follow one video through the system",
        "steps": [
            {
                "label": "An owner uploads",
                "sub": "Browser or Publisher",
                "detail": (
                    "Maya and Arun represent content owners. Clients ask for "
                    "permission, then send the video bytes directly to S3."
                ),
            },
            {
                "label": "Media accepts",
                "sub": "Verified source + durable intent",
                "detail": (
                    "Media checks the uploaded object, pins an immutable version and "
                    "records the processing command in its database transaction."
                ),
            },
            {
                "label": "Processing converts",
                "sub": "Queue + bounded FFmpeg worker",
                "accent": True,
                "detail": (
                    "Processing tracks the job and attempt. A finite Fargate worker "
                    "encodes only after obtaining a valid lease."
                ),
            },
            {
                "label": "The owner plays",
                "sub": "Checked, short-lived access",
                "detail": (
                    "A result updates Media’s local view. Media checks ownership "
                    "before returning temporary playback access."
                ),
            },
        ],
        "caption": (
            "This is the story to remember. The chapters explain the choices underneath it."
        ),
    }
    routes = (
        '<section><p class="eyebrow">Choose your first pass</p><h2>Three '
        'ways through the guide</h2><div class="paths"><a class="path" '
        'href="basics.html?depth=1"><b>01 · Get oriented</b><span>Read '
        "level 1 across the chapters. Learn the nouns and follow one "
        "video.</span><small>About 25–35 minutes</small></a><a "
        'class="path" href="architecture.html?depth=2"><b>02 · Understand '
        "why</b><span>Add level 2. Follow ownership, AWS placement, "
        "delivery and failure handling.</span><small>About 50–70 "
        'minutes</small></a><a class="path" href="code.html?depth=3"><b>'
        "03 · Defend the details</b><span>Open level 3, trace the real "
        "code, then rehearse questions aloud.</span><small>Go at your own "
        'pace</small></a></div><p class="muted small">These are suggested '
        "study budgets, not measured rehearsal times. Depth controls "
        "reveal each additional layer without losing the basics.</p>"
        "</section>"
    )
    cards = (
        (
            '<section><p class="eyebrow">The full learning path</p><h2>Start '
            'at the top. Go one level deeper.</h2><div class="chapter-list">'
        )
        + "".join(
            (
                '<a href="'
                f"{p['id']}"
                '.html"><span class="chapter-number">'
                f"{i + 1:02d}"
                "</span><span><strong>"
                f"{esc(p['title'])}"
                "</strong><small>"
                f"{esc(p['summary'])}"
                '</small></span><span aria-hidden="true">↗</span></a>'
            )
            for i, p in enumerate(pages)
        )
        + "</div></section>"
    )
    ending = (
        '<section><p class="eyebrow">Before the meeting</p><h2>Build '
        "understanding, then rehearse.</h2><ol><li>Explain the owner → "
        "Media → Processing → playback journey without acronyms.</li><li>"
        'Open the <a href="aws.html?depth=3">AWS</a> and <a '
        'href="delivery.html?depth=3">CI/CD</a> chapters. Click each '
        "diagram box and explain why it exists.</li><li>Use <a "
        'href="questions.html">Practise Q&A</a> with answers closed. Say '
        "an answer before revealing it.</li><li>Use the <a "
        'href="meeting.html?depth=3">showcase run-through</a> to connect '
        "Maya, Arun, Jules and Sam to the six presentation areas.</li>"
        "</ol><p>A completed final GC2 report was not found in the "
        "repository or the inspected local course folders. This guide "
        "uses the proposal, presentation guides, source code and "
        'engineering evidence. <a href="sources.html">See the source map '
        'and known gaps.</a></p><p><a class="button" '
        'href="basics.html?depth=1">Start with the basics →</a> <a '
        'class="text-button" href="all-in-one.html">Read or print '
        "everything</a></p></section>"
    )
    return shell(
        "index",
        "Start here",
        hero + block({"type": "visual", "spec": route}) + routes + cards + ending,
    )


def questions(pages):
    entries = []
    for p in pages:
        for s in p["sections"]:
            for b in s["blocks"]:
                if b["type"] == "qa":
                    entries.append((p, s, b))
    options = "".join(f'<option value="{p["id"]}">{esc(p["title"])}</option>' for p in pages)
    body = (
        '<header class="page-head"><p class="eyebrow">Rehearsal / Active '
        "recall</p><h1>Explain it before you reveal it.</h1><p "
        'class="lede">'
        f"{len(entries)}"
        " questions from the guide. Give the short answer first, explain "
        "the mechanism, then state the tradeoff or evidence limit.</p>"
        '</header><div class="practice-controls"><label>Find a '
        'question<input type="search" id="question-search" '
        'placeholder="Try outbox, rollback or ownership"></label><label>'
        'Chapter<select id="question-chapter"><option value="">All '
        "chapters</option>"
        f"{options}"
        '</select></label><button type="button" id="question-random">Pick '
        'a question</button></div><p id="question-count" '
        'aria-live="polite"></p><div id="question-list">'
    )
    for p, s, b in entries:
        body += (
            '<article class="question-item" data-chapter="'
            f"{p['id']}"
            '"><p class="eyebrow">'
            f"{esc(SHORT[ORDER.index(p['id'])])}"
            " · Level "
            f"{s['level']}"
            "</p>"
            f"{block(b)}"
            '<a class="small" href="'
            f"{p['id']}"
            ".html?depth="
            f"{s['level']}"
            "#"
            f"{s['id']}"
            '">Review the explanation →</a></article>'
        )
    body += (
        '</div><p id="no-questions" hidden>No matching questions. Try a '
        "shorter term or select all chapters.</p>"
    )
    return shell("questions", "Practise Q&A", body)


def glossary():
    entries = json.loads((ROOT / "content/glossary.json").read_text())
    body = (
        '<header class="page-head"><p class="eyebrow">Reference / '
        "Language without the fog</p><h1>What do these words mean?</h1><p "
        'class="lede">A short definition, then the specific meaning in '
        'FlickPond.</p></header><label class="search-label">Find a '
        'term<input type="search" id="glossary-search" placeholder="Try '
        'lease, Lambda, ACU or idempotency"></label><dl class="glossary">'
    )
    for e in sorted(entries, key=lambda x: x["term"].lower()):
        body += (
            '<div class="term"><dt>'
            f"{esc(e['term'])}"
            "</dt><dd><p>"
            f"{rich(e['definition'])}"
            '</p><p class="muted"><strong>Here:</strong> '
            f"{rich(e['project'])}"
            '</p><a href="'
            f"{esc(e['page'])}"
            '.html?depth=3">See it in the project →</a></dd></div>'
        )
    return shell(
        "glossary",
        "Glossary",
        body + '</dl><p id="no-terms" hidden>No terms found. Try a shorter word.</p>',
    )


def source_page(pages):
    paths = {}
    for p in pages:
        for s in p["sections"]:
            for src in s.get("sources", []):
                if "path" in src:
                    paths.setdefault(src["path"], set()).add(p["title"])
    body = (
        '<header class="page-head"><p class="eyebrow">Reference / Know '
        "what backs the claim</p><h1>Evidence, sources and "
        'boundaries.</h1><p class="lede">The project has several dated '
        "designs and releases. This guide explains the current "
        "implementation while preserving the scope of older "
        'measurements.</p></header>\n<section id="release-identities"><h2>'
        'Three identities to keep separate</h2><table class="grid"><thead>'
        "<tr><th>Identity</th><th>Meaning</th></tr></thead><tbody><tr><td>"
        "<code>d0d745f</code></td><td>The Main documentation/code "
        "snapshot used to build this guide, 22 October 2026.</td></tr><tr>"
        "<td><code>c7c489c</code></td><td>Verified engineering runtime "
        "image source delivered to dc2-live on 21 October (CI 39544952625, "
        "CD 39545554380; earlier <code>629119c</code>). Short lane and "
        "per-service databases were enabled on dc2-live afterwards "
        "(CD 39644028238).</td></tr><tr><td><code>daee44b</code>"
        "</td><td>The earlier team-accepted freeze. Its manifest remains "
        "historical; successful later delivery does not imply a new team "
        "acceptance.</td></tr></tbody></table><p>The guide does not "
        "continuously check the live environment. A later document commit "
        "is not a newly built runtime image.</p></section>\n<section><h2>"
        "Which documents govern the presentation?</h2><p>The current GC2 "
        "briefing, submitted Team 17 proposal and presentation guide "
        "govern the showcase. The older SWE5006 ZIP contributes an "
        "engineering completeness checklist; its dates, marking weights, "
        "examples and demo timing do not replace GC2 guidance.</p><p>Both "
        "local presentation guides place Team 17 on 26 October, "
        "14:35–15:15 SGT. Their copies are linked in the showcase "
        "chapter; check Canvas for any later change. No completed final "
        "GC2 report was found in the inspected repository and local "
        "course folders. The report template is a template, not a "
        "finished submission.</p></section>\n<section><h2>What a claim can "
        'safely mean</h2><table class="grid"><thead><tr><th>Evidence</th>'
        "<th>What it supports</th><th>What remains separate</th></tr>"
        "</thead><tbody><tr><td>Code/configuration</td><td>The "
        "implementation or configured intent.</td><td>Successful "
        "execution and production behavior.</td></tr><tr><td>Local "
        "test</td><td>The named behavior under the test's setup.</td><td>"
        "IAM, real managed services and live cloud state.</td></tr><tr>"
        "<td>Hosted CI</td><td>The recorded selected/full checks at a "
        "source and run attempt.</td><td>Which artifacts are actually "
        "deployed.</td></tr><tr><td>AWS receipt</td><td>The operation and "
        "workload at its stated source/time.</td><td>Later releases, "
        "long-term reliability and unrun workloads.</td></tr></tbody>"
        "</table></section>\n<section><h2>High-value reading anchors</h2>"
        '<ul><li><a href="../docs/release/engineering-handoff.md">'
        "Engineering handoff: full GC2 story and current validation</a>"
        '</li><li><a href="../docs/architecture/use-case-design.md">Seven '
        "use cases, detailed design, sequences and tests</a></li><li><a "
        'href="../project-documentation/course-evidence-checklist.md">'
        "Course requirements and remaining human confirmations</a></li>"
        '<li><a href="../docs/results/engineering-20261020/delivery-629119'
        'c.json">Current delivery receipt: CI, CD, deployed images and '
        'smoke</a></li><li><a href="../docs/results/actual-vs-target.md">'
        "Performance outcomes, misses and unmeasured commitments</a></li>"
        '<li><a href="../project-roadmap/business-scope.json">Original '
        "fictional personas</a></li></ul></section>"
    )
    body += (
        "<section><h2>Chapter-to-source index</h2><p>These are local "
        "repository links. If you move the guide away from the "
        "repository, the study pages still work, but these source links "
        'need the repository beside them.</p><div class="source-index">'
    )
    for path, titles in sorted(paths.items()):
        body += (
            "<p>"
            f"{link({'path': path, 'label': path})}"
            "<small>"
            f"{esc(' · '.join(sorted(titles)))}"
            "</small></p>"
        )
    body += (
        "</div></section><section><h2>Visual style and rebuilding</h2><p>"
        "Diagrams reuse the local exam-prep sketch-diagrams renderer, "
        "dotted canvas, pastel palette and bundled Shantell Sans font. "
        "They are HTML/CSS diagrams with clickable detail, with no "
        "image-generation service or remote CDN.</p><p>Edit the chapter "
        "JSON files under <code>content/</code>, then run <code>python3 "
        "showcase-prep/build.py</code> from the repository root. No npm "
        "install or server is required to read the generated HTML.</p>"
        "</section>"
    )
    return shell("sources", "Sources and evidence", body)


def main():
    render_map()
    pages = [json.loads((ROOT / "content" / f"{slug}.json").read_text()) for slug in ORDER]
    for i, p in enumerate(pages):
        assert p["id"] == ORDER[i]
        (ROOT / f"{p['id']}.html").write_text(chapter(p, i))
    (ROOT / "index.html").write_text(home(pages))
    (ROOT / "questions.html").write_text(questions(pages))
    (ROOT / "glossary.html").write_text(glossary())
    (ROOT / "sources.html").write_text(source_page(pages))
    book = (
        '<header class="page-head"><p class="eyebrow">Complete study '
        "edition</p><h1>FlickPond, from basics to details.</h1><p "
        'class="lede">Every chapter in one place. Printing includes all '
        "depth levels, diagram notes and question answers.</p><button "
        'type="button" class="print-button">Print / save as PDF</button>'
        "</header>"
    )
    for i, p in enumerate(pages):
        book += (
            '<div class="book-chapter" id="'
            f"{p['id']}"
            '"><p class="eyebrow">Chapter '
            f"{i + 1:02d}"
            "</p><h1>"
            f"{esc(p['title'])}"
            '</h1><p class="lede">'
            f"{esc(p['summary'])}"
            '</p><div class="say-it"><p>'
            f"{rich(p['opening_answer'])}"
            "</p></div>"
            f"{sections(p, p['id'] + '-')}"
            "</div>"
        )
    (ROOT / "all-in-one.html").write_text(shell("all-in-one", "Complete study edition", book))
    print(f"Built {len(pages) + 5} HTML pages from {len(pages)} chapters.")


if __name__ == "__main__":
    main()
