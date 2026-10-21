"Small SVG renderer for the physical topology spec; shares the sketch palette/font."

import base64
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render():
    spec = json.loads((ROOT / "content/aws-map.json").read_text())
    esc = html.escape
    font = base64.b64encode((ROOT / "assets/fonts/shantell-sans-latin.woff2").read_bytes()).decode()
    svg = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '
            f"{spec['width']}"
            " "
            f"{spec['height']}"
            '" role="img" aria-labelledby="title desc"><title id="title">'
            f"{esc(spec['title'])}"
            '</title><desc id="desc">'
            f"{esc(spec['description'])}"
            "</desc>"
        ),
        (
            "<defs><style>@font-face{font-family:Sketch;src:url(data:font/woff"
            "2;base64,"
            f"{font}"
            ') format("woff2")}text{font-family:Sketch,sans-serif;fill:#1d1d1d'
            "}.label{font-size:18px;font-weight:650}.sub{font-size:13px}.edge-"
            "label{font-size:13px;paint-order:stroke;stroke:#f8f9fa;stroke-wid"
            "th:6px;stroke-linejoin:round}</style>"
        ),
        (
            '<pattern id="dots" width="18" height="18" '
            'patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" '
            'fill="#d4d6da"/></pattern>'
        ),
        (
            '<marker id="arrow" viewBox="0 0 12 12" refX="10" refY="6" '
            'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            '<path d="M2 1 L10 6 L2 11" fill="none" stroke="context-stroke" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            "</marker></defs>"
        ),
        (
            '<rect width="100%" height="100%" fill="#f8f9fa"/><rect '
            'width="100%" height="100%" fill="url(#dots)"/>'
        ),
    ]
    for r in spec["regions"]:
        svg += [
            (
                '<rect x="'
                f"{r['x']}"
                '" y="'
                f"{r['y']}"
                '" width="'
                f"{r['w']}"
                '" height="'
                f"{r['h']}"
                '" rx="12" fill="'
                f"{r['fill']}"
                '" stroke="#586373" stroke-width="1.8" stroke-dasharray="7 5"/>'
            ),
            (
                '<text x="'
                f"{r['x'] + 14}"
                '" y="'
                f"{r['y'] + 25}"
                '" font-size="15" font-weight="600">'
                f"{esc(r['label'])}"
                "</text>"
            ),
        ]
    colors = {"control": "#323941", "data": "#177267", "sql": "#65519a"}
    for e in spec["edges"]:
        start = ' marker-start="url(#arrow)"' if e.get("both") else ""
        end = ' marker-end="url(#arrow)"' if e.get("end", True) else ""
        if e.get("bridge"):
            svg.append(f'<path d="{e["path"]}" stroke="#f8f9fa" stroke-width="6" fill="none"/>')
        svg.append(
            '<path d="'
            f"{e['path']}"
            '" stroke="'
            f"{colors[e['kind']]}"
            '" stroke-width="2.1" stroke-linejoin="round" fill="none"'
            f"{end}"
            f"{start}"
            "/>"
        )
        if e.get("label"):
            svg.append(
                '<text class="edge-label" text-anchor="middle" x="'
                f"{e['x']}"
                '" y="'
                f"{e['y']}"
                '">'
                f"{esc(e['label'])}"
                "</text>"
            )
    for n in spec["nodes"]:
        x, y, w, h = (n[k] for k in ("x", "y", "w", "h"))
        shape = (
            "M"
            f"{x + 2}"
            " "
            f"{y + 4}"
            " Q"
            f"{x + w / 2}"
            " "
            f"{y - 2}"
            " "
            f"{x + w - 3}"
            " "
            f"{y + 2}"
            " L"
            f"{x + w + 1}"
            " "
            f"{y + h - 4}"
            " Q"
            f"{x + w / 2}"
            " "
            f"{y + h + 2}"
            " "
            f"{x + 1}"
            " "
            f"{y + h - 1}"
            " Z"
        )
        if n.get("accent"):
            svg.append(f'<path d="{shape}" transform="translate(4 4)" fill="#1d1d1d"/>')
        svg.append(f'<path d="{shape}" fill="{n["fill"]}" stroke="#1d1d1d" stroke-width="2"/>')
        subs = n["sub"].split("\n")
        top = y + (h - (25 + len(subs) * 18)) / 2 + 17
        size = f' style="font-size:{n["fontSize"]}px"' if n.get("fontSize") else ""
        svg.append(
            '<text class="label"'
            f"{size}"
            ' text-anchor="middle" x="'
            f"{x + w / 2}"
            '" y="'
            f"{top}"
            '">'
            f"{esc(n['label'])}"
            "</text>"
        )
        for i, line in enumerate(subs):
            svg.append(
                '<text class="sub" text-anchor="middle" x="'
                f"{x + w / 2}"
                '" y="'
                f"{top + 23 + i * 18}"
                '">'
                f"{esc(line)}"
                "</text>"
            )
    for note in spec["notes"]:
        for i, line in enumerate(note["lines"]):
            svg.append(
                f'<text class="sub" x="{note["x"]}" y="{note["y"] + i * 21}">{esc(line)}</text>'
            )
    svg.append("</svg>")
    (ROOT / "assets/aws-topology.svg").write_text("".join(svg))


if __name__ == "__main__":
    render()
