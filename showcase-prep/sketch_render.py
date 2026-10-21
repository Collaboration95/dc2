#!/usr/bin/env python3
"""Render the exam-prep sketch diagram specifications as HTML."""

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def esc(s):
    return html.escape(str(s), quote=True)


def rich(s):
    """Escape, then allow **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))


def node(item, cls="box", i=0, icon_dir=HERE / "icons", icon_url="icons"):
    """One box. c0..c5 cycles the pastel fill; `detail` makes it clickable."""
    has_icon = item.get("icon") and (icon_dir / f"{item['icon']}.svg").exists()
    icon = f'<img class="logo" src="{icon_url}/{esc(item["icon"])}.svg" alt="">' if has_icon else ""
    sub = f'<span class="sub">{esc(item["sub"])}</span>' if item.get("sub") else ""
    accent = " accent" if item.get("accent") else ""
    inner = f'{icon}<span class="label">{esc(item["label"])}</span>{sub}'
    if item.get("detail"):
        return (
            '<button type="button" class="'
            f"{cls}"
            " c"
            f"{i % 6}"
            f"{accent}"
            '" data-detail="'
            f"{esc(item['detail'])}"
            '">'
            f"{inner}"
            "</button>"
        )
    return f'<div class="{cls} c{i % 6}{accent}">{inner}</div>'


def visual(v, icon_dir=HERE / "icons", icon_url="icons"):
    def nd(item, cls="box", i=0):
        return node(item, cls, i, icon_dir, icon_url)

    t = v["type"]
    boxes = []
    if t == "flow":
        boxes = v["steps"]
        n = len(boxes)
        # Even grid: up to 4 boxes per row; longer flows continue on the next row.
        cols = (
            "minmax(0,1fr) 40px " * (n - 1) + "minmax(0,1fr)"
            if n <= 4
            else "minmax(0,1fr) 40px " * 4
        )
        body = '<span class="arrow">→</span>'.join(nd(x, i=k) for k, x in enumerate(boxes))
        body = f'<div class="flow" style="grid-template-columns:{cols}">{body}</div>'
    elif t == "layers":
        boxes = v["layers"]
        body = (
            '<div class="layers">'
            + "".join(nd(x, "box layer", k) for k, x in enumerate(boxes))
            + "</div>"
        )
    elif t == "cards":
        boxes = v["items"]
        body = '<div class="cards">' + "".join(nd(x, i=k) for k, x in enumerate(boxes)) + "</div>"
    elif t == "hub":
        boxes = [v["center"]] + v["items"]
        items = "".join(nd(x, i=k) for k, x in enumerate(v["items"]))
        body = (
            '<div class="hub">'
            f"{nd(v['center'], 'box center')}"
            '<span class="arrow down">↓</span><div class="cards">'
            f"{items}"
            "</div></div>"
        )
    elif t == "compare":

        def th(k):
            return "th" if k == 0 else "td"

        head = "".join(f"<th>{esc(c)}</th>" for c in v["columns"])
        rows = "".join(
            "<tr>" + "".join(f"<{th(k)}>{rich(c)}</{th(k)}>" for k, c in enumerate(r)) + "</tr>"
            for r in v["rows"]
        )
        body = (
            '<div class="scroll"><table class="compare"><thead><tr>'
            f"{head}"
            "</tr></thead><tbody>"
            f"{rows}"
            "</tbody></table></div>"
        )
    else:
        raise ValueError(f"Unknown visual type {t!r}")
    title = f'<p class="vtitle">{esc(v["title"])}</p>' if v.get("title") else ""
    caption = f'<p class="caption">{rich(v["caption"])}</p>' if v.get("caption") else ""
    panel = (
        '<div class="detail" aria-live="polite">Click a box for details.</div>'
        if any(b.get("detail") for b in boxes)
        else ""
    )
    return f'<figure class="visual v-{t}">{title}{body}{panel}{caption}</figure>'


def page(specs, title="Diagrams"):
    figs = "".join(visual(v) for v in specs)
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" '
        'content="width=device-width,initial-scale=1">\n<title>'
        f"{esc(title)}"
        '</title><link rel="stylesheet" href="sketch.css">\n<style>'
        "body{margin:0;font:16px/1.6 "
        '-apple-system,BlinkMacSystemFont,"Segoe '
        'UI",sans-serif;color:#1f2328}main{max-width:900px;margin:0 '
        "auto;padding:24px 16px}</style>\n</head><body><main>"
        f"{figs}"
        '</main><script src="sketch.js"></script></body></html>\n'
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.write(page(json.loads(Path(sys.argv[1]).read_text())))
