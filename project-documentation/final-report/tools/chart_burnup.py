#!/usr/bin/env python3
"""Draw the GitHub issue burn-up (data/issue-burnup.csv) as figures/src/report-burnup.svg.

The CSV is derived from issue timestamps (gh issue list --state all): cumulative issues opened
(scope) and closed (done) per UTC day. Render to PNG with tools/render_figures.py report-burnup.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = list(csv.DictReader(open(ROOT / "data" / "issue-burnup.csv")))
W, H = 900, 420
L, R, T, B = 70, 150, 50, 60
ymax = 160
pw, ph = W - L - R, H - T - B
n = len(rows)


def x(i):
    return L + pw * i / (n - 1)


def y(v):
    return T + ph * (1 - v / ymax)


series = [
    ("cumulative_opened", "Opened (scope)", "#2a78d6", ""),
    ("cumulative_closed", "Closed (done)", "#eb6834", "6 4"),
]
out = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
    'font-family="Arial, Helvetica, sans-serif">',
    f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
    f'<text x="{L}" y="24" font-size="16" font-weight="bold" fill="#1f1f1f">'
    "GitHub issues, cumulative opened and closed per day (UTC), 12–21 October 2026</text>",
]
for v in range(0, ymax + 1, 40):
    out.append(
        f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e6e6e3" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{L - 10}" y="{y(v) + 4:.1f}" font-size="12" text-anchor="end" fill="#5c5c58">{v}</text>'
    )
out.append(
    f'<line x1="{L}" x2="{L + pw}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#8a8a85" stroke-width="1"/>'
)
for i, r in enumerate(rows):
    label = r["date"][8:] + " Oct"
    out.append(
        f'<text x="{x(i):.1f}" y="{y(0) + 20:.1f}" font-size="12" text-anchor="middle" fill="#5c5c58">{label}</text>'
    )
out.append(
    f'<text x="18" y="{T + ph / 2:.1f}" font-size="12" fill="#5c5c58" '
    f'transform="rotate(-90 18 {T + ph / 2:.1f})" text-anchor="middle">Issues (count)</text>'
)
for key, name, colour, dash in series:
    pts = " ".join(f"{x(i):.1f},{y(int(r[key])):.1f}" for i, r in enumerate(rows))
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(
        f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2.5"{dash_attr}/>'
    )
    for i, r in enumerate(rows):
        out.append(
            f'<circle cx="{x(i):.1f}" cy="{y(int(r[key])):.1f}" r="4" fill="{colour}" stroke="#ffffff" stroke-width="2"/>'
        )
    last = int(rows[-1][key])
    out.append(
        f'<text x="{x(n - 1) + 12:.1f}" y="{y(last) + (-4 if key == "cumulative_opened" else 14):.1f}" '
        f'font-size="13" fill="#1f1f1f">{name}: {last}</text>'
    )
# Legend (identity is also carried by the dash pattern and the direct labels).
lx, ly = L, H - 16
for j, (_, name, colour, dash) in enumerate(series):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    ox = lx + j * 180
    out.append(
        f'<line x1="{ox}" x2="{ox + 28}" y1="{ly - 4}" y2="{ly - 4}" stroke="{colour}" stroke-width="2.5"{dash_attr}/>'
    )
    out.append(f'<text x="{ox + 36}" y="{ly}" font-size="12" fill="#1f1f1f">{name}</text>')
out.append("</svg>")
(ROOT / "figures" / "src" / "report-burnup.svg").write_text("\n".join(out))
print("wrote figures/src/report-burnup.svg")
