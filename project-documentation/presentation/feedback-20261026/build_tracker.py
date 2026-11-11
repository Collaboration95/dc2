"""Build tracker.html from tracker_data.py and the research files.

Run: python3 build_tracker.py   (from any directory)
"""
import html
import json
import re
from pathlib import Path

import tracker_data as d

HERE = Path(__file__).resolve().parent


def r5_refs():
    """Parse R5's reference tables into {item_id: [ref, ...]}."""
    text = (HERE / "research/R5-external-references.md").read_text()
    by_item, section = {}, None
    row = re.compile(r"\| ([A-Z]+\d+) \| \[(.*?)\]\((http[^)]+)\) \| (.*?) \| (.*?) \| (.*?) \|")
    for line in text.splitlines():
        m = re.match(r"## (F\d+|Course)", line)
        if m:
            section = m.group(1)
        m = row.match(line)
        if not m or section is None:
            continue
        ref = dict(rid=m.group(1), title=m.group(2), url=m.group(3), pub=m.group(4), note=m.group(5))
        for item in d.R5_MAP.get(section, []):
            by_item.setdefault(item, []).append(ref)
    return by_item


SLIDE_WS = {12: "W6", 13: "W6", 14: "W6", 15: "W6", 16: "W2", 19: "W6", 20: "W1", 22: "W1",
            24: "W1", 27: "W4", 28: "W3", 29: "W3", 30: "W3", 31: "W3", 55: "W1", 61: "W3",
            63: "W1", 67: "W3"}


def r2_corrections():
    """Parse R2's numbered 'Corrections to the deck' list."""
    text = (HERE / "research/R2-runtime-deployment-truth.md").read_text()
    part = text.split("## Corrections to the deck", 1)[1]
    out = []
    for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*(.*)$", part, re.M):
        head, body = m.group(1), m.group(2)
        nums = [int(n) for n in re.findall(r"\b(\d{2})\b", head.split("—")[0])]
        ws = next((SLIDE_WS[n] for n in nums if n in SLIDE_WS), "W6")
        body = re.sub(r"\s*Slides?: .*$", "", body).strip()
        links = re.findall(r"\[([^\]]+)\]\((https://github[^)]+)\)", m.group(2))
        truth = [(lbl.split("/")[-1], url) for lbl, url in links if "deck.html" not in url]
        out.append(dict(head=head, body=body, ws=ws, links=truth[:4], done=True))
    return out


def report_changes():
    """Map F-ids to RC entries in REPORT-CHANGES.md ('**RC-05 · F7–F11, F19 · add text**')."""
    path = HERE / "REPORT-CHANGES.md"
    out, section = {}, ""
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        m = re.match(r"\*\*(RC-\d+) · (.+?) · (.+?)\*\*", line)
        if not m:
            continue
        ids = set()
        for a, b in re.findall(r"F(\d+)(?:[–-]F(\d+))?", m.group(2)):
            ids.update(range(int(a), int(b or a) + 1))
        for n in ids:
            out.setdefault(f"F{n}", []).append(f"{m.group(1)} · {section} · {m.group(3)}")
    return out


def main():
    refs = r5_refs()
    deck = (HERE.parent / "site/deck.html").read_text()
    pos = {}
    for n, sec in enumerate(re.findall(r"<section\b.*?</section>", deck, re.S), 1):
        title = re.sub(r"<[^>]+>", "", re.search(r"<h1[^>]*>(.*?)</h1>", sec, re.S).group(1)).strip()
        pos[re.search(r'id="([^"]+)"', sec).group(1)] = (n, title)
    rcs = report_changes()
    items = []
    for it in d.ITEMS:
        it = dict(it)
        it["refs"] = refs.get(it["id"], [])
        it["rc"] = rcs.get(it["id"], [])
        it["slides"] = [pos[s] for s in d.SLIDES.get(it["id"], []) if s in pos]
        if it["id"] in d.DECK_DONE and it["status"] == "doing":
            it["status"] = "done" if it["kind"] == "deck" else "review"
        items.append(it)
    data = dict(items=items, corrections=r2_corrections(), backlog=d.CODE_BACKLOG,
                ws=d.WORKSTREAMS)
    page = (HERE / "tracker_template.html").read_text()
    page = page.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    (HERE / "tracker.html").write_text(page)
    print("tracker.html:", len(items), "items,", len(data["corrections"]), "corrections,",
          sum(len(i["refs"]) for i in items), "reference links")


if __name__ == "__main__":
    main()
