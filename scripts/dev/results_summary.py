"""Rebuild the actual-versus-target table and figure from docs/results/actual-vs-target.csv.

Usage: python scripts/dev/results_summary.py [--check]

The CSV is the source of truth. This script (standard library only) validates it, rewrites the
table between the markers in docs/results/actual-vs-target.md and redraws
docs/results/actual-vs-target.svg. Every receipt path must exist. With --check nothing is
written; it exits 1 if the committed table or figure is stale.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[2] / "docs" / "results"
CSV_PATH = OUT / "actual-vs-target.csv"
MD_PATH = OUT / "actual-vs-target.md"
SVG_PATH = OUT / "actual-vs-target.svg"
START, END = "<!-- table:start -->", "<!-- table:end -->"
COLUMNS = [
    "id",
    "group",
    "scenario",
    "environment",
    "source",
    "workload",
    "timing_boundary",
    "unit",
    "target",
    "observed",
    "verdict",
    "receipt_path",
    "locator",
    "note",
]
GROUPS = [
    ("scaling", "Scaling"),
    ("deployability", "Deployability"),
    ("performance", "Performance"),
    ("availability", "Availability"),
    ("security", "Security"),
    ("reuse", "Reuse"),
    ("cost", "Cost"),
    ("live", "Newer live evidence (r1019a and V2-live)"),
]


def load() -> list[dict[str, str]]:
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, strict=True))
    for row in rows:
        if None in row or None in row.values() or list(row) != COLUMNS:
            raise SystemExit(f"{row.get('id')}: wrong column count")
        path = row["receipt_path"]
        if not path.startswith("http") and not (OUT / path).exists():
            raise SystemExit(f"{row['id']}: receipt path does not exist: {path}")
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate ids")
    return rows


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ") or "-"


def table(rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for key, title in GROUPS:
        part = [r for r in rows if r["group"] == key]
        lines += [
            f"### {title}",
            "",
            "| ID | Scenario | Environment and source | Workload | Timing boundary | Target "
            "| Observed | Verdict | Receipt | Note |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in part:
            plain = re.fullmatch(r"[\d.,/ ]+", r["observed"])
            unit = f" {r['unit']}" if r["unit"] and plain else ""
            target = r["target"]
            if r["unit"] and re.fullmatch(r"(<=|>=|<)? ?[\d.]+", target):
                target = f"{target} {r['unit']}"
            link = r["receipt_path"]
            label = Path(link).name if not link.startswith("http") else "Actions run"
            loc = f" `{r['locator']}`" if r["locator"] else ""
            verdict = r["verdict"]
            if verdict.split(" ")[0] in {"FAIL", "NOT_RUN", "PENDING", "NOT_MEASURED", "NOT"}:
                verdict = f"**{verdict}**"
            lines.append(
                "| "
                + " | ".join(
                    cell(x)
                    for x in (
                        r["id"],
                        r["scenario"],
                        f"{r['environment']}; {r['source']}",
                        r["workload"],
                        r["timing_boundary"],
                        target,
                        r["observed"] + unit,
                        verdict,
                        f"[{label}]({link}){loc}",
                        r["note"],
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def num(rows: dict[str, dict[str, str]], key: str) -> float:
    return float(re.search(r"\d+\.\d+", rows[key]["observed"]).group())


def bar(x: float, y: float, w: float, h: float, fill: str, label: str, below: str) -> str:
    value, _, verdict = label.partition("|")
    cx = x + w / 2
    text = (
        f'<text x="{cx:.0f}" y="{y + 16:.0f}" text-anchor="middle" font-size="12" '
        f'fill="#ffffff" font-weight="bold">{escape(value)}</text>'
    )
    if verdict:
        text += (
            f'<text x="{cx:.0f}" y="{y + 31:.0f}" text-anchor="middle" font-size="11" '
            f'fill="#ffffff">{escape(verdict)}</text>'
        )
    return (
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="{fill}"/>'
        f'{text}<text x="{cx:.0f}" y="{y + h + 14:.0f}" text-anchor="middle" '
        f'font-size="10">{escape(below)}</text>'
    )


def svg(rows: list[dict[str, str]]) -> str:
    by = {r["id"]: r for r in rows}
    base, scale = 330.0, 80.0  # axis y, px per speedup unit (panel A)
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="430" '
        'viewBox="0 0 1000 430" font-family="sans-serif" font-size="12">',
        '<rect width="1000" height="430" fill="#ffffff"/>',
        '<text x="20" y="24" font-size="15" font-weight="bold">Actual against target, from '
        "docs/results/actual-vs-target.csv</text>",
        '<text x="20" y="44" font-size="11">Panels use different designs, environments and timing '
        "boundaries; see the table. Target lines are the proposal section 3.4 values.</text>",
        '<text x="20" y="64" font-size="13" font-weight="bold">A. Speedup over one worker '
        "(x)</text>",
        f'<line x1="40" y1="{base}" x2="400" y2="{base}" stroke="#333"/>',
    ]
    groups = [
        ("2 workers", 1.6, "SC-AWS-4", "SC-LOC-1"),
        ("3 workers", 2.1, "SC-AWS-5", "SC-LOC-2"),
    ]
    series = (("#d55e00", "AWS V1"), ("#0072b2", "local"))
    for i, (name, target, aws, loc) in enumerate(groups):
        x0 = 60 + i * 180
        for j, (rid, (fill, tag)) in enumerate(zip((aws, loc), series, strict=True)):
            v = num(by, rid)
            verdict = by[rid]["verdict"].split(" ")[0]
            out.append(
                bar(x0 + j * 70, base - v * scale, 60, v * scale, fill, f"{v:.3f}x|{verdict}", tag)
            )
        y = base - target * scale
        out.append(
            f'<line x1="{x0 - 10}" y1="{y:.0f}" x2="{x0 + 140}" y2="{y:.0f}" '
            f'stroke="#000" stroke-dasharray="5 3"/>'
        )
        out.append(
            f'<text x="{x0 + 65}" y="{base + 32}" text-anchor="middle">'
            f"{name} (target {target}x, dashed)</text>"
        )
    out += [
        '<text x="40" y="378" font-size="10">AWS V1 (orange): 6 clips, one run per cap, 2 vCPU '
        "Fargate tasks, r1018b.</text>",
        '<text x="40" y="392" font-size="10">Local pre-V1 (blue): 30 clips, three rotated repeats, '
        "Redis/RQ design; not comparable with AWS.</text>",
        '<text x="540" y="64" font-size="13" font-weight="bold">B. Processing release time '
        "(min)</text>",
    ]
    pscale = 14.0
    out.append(f'<line x1="540" y1="{base}" x2="960" y2="{base}" stroke="#333"/>')
    rounds = [float(x) for x in re.findall(r"\d+\.\d+", by["DP-1"]["observed"])]
    bars = [
        (v, k, "r1018b round 1" if k == 0 else f"round {k + 1}", "Release step")
        for k, v in enumerate(rounds)
    ]
    bars += [
        (num(by, "DP-3"), 3, "r1019a", "Release step"),
        (num(by, "DP-4"), 4, "r1019a", "Release + upload smoke"),
    ]
    for v, k, tag, what in bars:
        x = 550 + k * 80
        fill = "#d55e00" if v > 10 else "#009e73"
        out.append(bar(x, base - v * pscale, 60, v * pscale, fill, f"{v:.2f}", tag))
        out.append(
            f'<text x="{x + 30}" y="{base + 28}" text-anchor="middle" font-size="9">'
            f"{escape(what)}</text>"
        )
    ty = base - 10 * pscale
    out.append(
        f'<line x1="540" y1="{ty:.0f}" x2="930" y2="{ty:.0f}" stroke="#000" '
        f'stroke-dasharray="5 3"/><text x="934" y="{ty + 4:.0f}" font-size="10">'
        f"target 10 min</text>"
    )
    out += [
        '<text x="540" y="378" font-size="10">Orange = over 10 min. r1018b Release step: '
        "build, push, scan, promote, smoke, close.</text>",
        '<text x="540" y="392" font-size="10">r1019a: Actions job-step durations; smoke is a '
        "separate step (15m38s together).</text>",
        "</svg>",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    rows = load()
    md = MD_PATH.read_text(encoding="utf-8")
    head, rest = md.split(START, 1)
    tail = rest.split(END, 1)[1]
    new_md = f"{head}{START}\n\n{table(rows)}\n{END}{tail}"
    new_svg = svg(rows)
    if "--check" in argv:
        stale = new_md != md or not SVG_PATH.exists() or SVG_PATH.read_text() != new_svg
        print("stale" if stale else "up to date")
        return 1 if stale else 0
    MD_PATH.write_text(new_md, encoding="utf-8")
    SVG_PATH.write_text(new_svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
