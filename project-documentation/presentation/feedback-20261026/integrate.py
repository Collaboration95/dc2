"""Merge the workstream slide fragments into site/deck.html.

The base is always the deck as presented on 26 Oct (Main 76282d3), so this
script can be re-run as fragments change. The presented deck is kept as
site/deck-presented-20261026.html.

Fragment rules (slides/Wn.html):
  <!-- REPLACES s22 -->       section(s) take the place of s22
  <!-- NEW after <id> -->      inserted after <id> (original or new id)
  <!-- NEW backup -->         goes to that workstream's appendix group
"""
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "site"
BASE_REV = "76282d3"
ORDER = ["W6", "W2", "W1", "W3", "W4", "W5", "W7"]
APPENDIX = {
    "W1": "Appendix A · Deployment and runtime",
    "W2": "Appendix B · Domain models (DDD)",
    "W3": "Appendix C · Detailed design",
    "W4": "Appendix D · Data schemas",
    "W5": "Appendix E · DevSecOps",
    "W6": "Appendix F · Logical view",
    "W7": "Appendix G · Whole-deck clarifications",
}
SECTION = re.compile(r"<section\b.*?</section>", re.S)
DIRECTIVE = re.compile(r"<!--\s*(REPLACES\s+(\S+)|NEW\s+after\s+(\S+)|NEW\s+backup)\s*-->\s*(<section\b.*?</section>)", re.S)


def sid(section):
    return re.search(r'\bid="([^"]+)"', section).group(1)


def load_base():
    rel = "project-documentation/presentation/site/deck.html"
    text = subprocess.run(["git", "show", f"{BASE_REV}:{rel}"], cwd=HERE, check=True,
                          capture_output=True, text=True).stdout
    first = text.index("<section")
    last = text.rindex("</section>") + len("</section>")
    return text[:first], SECTION.findall(text[first:last]), text[last:]


def load_fragments():
    replaces, after, backup = {}, {}, {}
    for ws in ORDER:
        path = HERE / "slides" / f"{ws}.html"
        if not path.exists():
            continue
        for m in DIRECTIVE.finditer(path.read_text()):
            sec = m.group(4).replace('data-kind="backup"', 'data-kind="back"')
            if m.group(2):
                replaces.setdefault(m.group(2), []).append(sec)
            elif m.group(3):
                after.setdefault(m.group(3), []).append(sec)
            else:
                backup.setdefault(ws, []).append(sec)
    return replaces, after, backup


def divider(title, n):
    return (f'<section class="slide" id="appx-{n}" data-kind="back" data-num="Appx">'
            f'<h1>{title}</h1><div class="body"><div class="col cc" style="height:100%">'
            '<div class="cap" style="font-size:32px">Full-detail models behind the main talk. '
            'Sources: site/assets/uml/*.puml, pinned to Main 76282d3.</div></div></div>'
            '<div class="sec">Appendix</div><div class="foot"><span></span><span>Appendix</span></div>'
            f'<aside class="notes"><b>{title}</b></aside></section>')


def emit_after(anchor, after, out, seen):
    for sec in after.get(anchor, []):
        new_id = sid(sec)
        if new_id in seen:
            continue
        seen.add(new_id)
        out.append(sec)
        emit_after(new_id, after, out, seen)


def renumber(sections):
    mains = [s for s in sections if 'data-kind="main"' in s]
    total, i, out = len(mains), 0, []
    for position, s in enumerate(sections, 1):
        if 'data-kind="main"' in s:
            i += 1
            badge, label = f"S{i}", f"{i} / {total}"
        else:
            # Numeric keyboard navigation uses the physical slide position.
            badge, label = f"B{position}", f"{position} / {len(sections)}"
        s = re.sub(r'data-num="[^"]*"', f'data-num="{badge}"', s, count=1)
        # Original footers can put a link and the number inside span.fr.
        # Replace only the final text node, preserving every citation/link.
        s = re.sub(r'(<div class="foot">)(.*?)(?=<aside\b)',
                   lambda m: m.group(1) + re.sub(
                       r'[^<>]+(?=</span>\s*</div>\s*$)', label,
                       m.group(2), count=1), s, count=1, flags=re.S)
        s = s.replace('<aside class="notes">',
                      f'<aside class="notes"><b>Slide {position} · {sid(s)}</b><br>', 1)
        out.append(s)
    return out, total


def main():
    head, base, tail = load_base()
    replaces, after, backup = load_fragments()
    # Reusing an original id in a placement comment moves the slide, whether
    # to an appendix or after another slide. The comment remains the sole
    # authority for editorial ordering.
    placed = [s for group in (*backup.values(), *after.values()) for s in group]
    moved = {sid(s) for s in placed} & {sid(s) for s in base}
    out, seen = [], set()
    for sec in base:
        orig = sid(sec)
        if orig in moved and orig not in replaces:
            emit_after(orig, after, out, seen)
            continue
        group = replaces.get(orig, [sec])
        for g in group:
            seen.add(sid(g))
            out.append(g)
            emit_after(sid(g), after, out, seen)
        emit_after(orig, after, out, seen)
    for n, ws in enumerate(sorted(APPENDIX, key=APPENDIX.get), 1):
        if backup.get(ws):
            out.append(divider(APPENDIX[ws], n))
            out.extend(backup[ws])
    missing = [a for a in after if a not in seen and not any(sid(s) == a for s in base)]
    ids = [sid(s) for s in out]
    if missing or len(set(ids)) != len(ids):
        raise ValueError(f"Unresolved anchors or duplicate slide ids: {missing}")
    out, total = renumber(out)
    (SITE / "deck-presented-20261026.html").write_text(head + "\n".join(base) + tail)
    (SITE / "deck.html").write_text(head + "\n".join(out) + tail)
    print(f"deck.html: {len(out)} slides, {total} main, {len(out) - total} backup/appendix")


if __name__ == "__main__":
    main()
