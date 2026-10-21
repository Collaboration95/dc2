#!/usr/bin/env python3
"""Render the final report's figures to PNG (2x scale, white background, tight crop).

Usage (from anywhere):

    python3 project-documentation/final-report/tools/render_figures.py            # everything
    python3 project-documentation/final-report/tools/render_figures.py views-logical aws-topology
    python3 project-documentation/final-report/tools/render_figures.py 'use-case-design-*'
    python3 project-documentation/final-report/tools/render_figures.py --force    # ignore up-to-date check
    python3 project-documentation/final-report/tools/render_figures.py --list     # names only

Two kinds of source become ``figures/<name>.png``:

* SVG files (``SVG_SOURCES`` below). Each is inlined into a throw-away HTML page and screenshotted
  by headless Google Chrome at ``--force-device-scale-factor=2``. Hand-drawn SVGs are first
  measured in the browser (``getBBox``) and cropped to their content plus a small margin. Mermaid
  output (recognised by ``aria-roledescription``) already carries an exact ``viewBox`` and keeps it.
* Mermaid sources (``figures/src/*.mmd``) rendered by ``@mermaid-js/mermaid-cli`` (``mmdc``,
  fetched with ``npx`` on first use) driving the same Chrome (``PUPPETEER_EXECUTABLE_PATH``).

Before rendering, every ```mermaid block of ``MERMAID_DOCS`` is extracted to
``figures/src/<doc>-<nn>-<slug>.mmd`` (slug = nearest preceding heading). Files are rewritten only
when their content changes, so re-running is idempotent. A PNG is skipped when it is newer than its
source unless ``--force`` is given. Standard library only; needs Chrome, Node and (first run) network.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIGURES = REPO / "project-documentation" / "final-report" / "figures"
SRC = FIGURES / "src"

CHROME = os.environ.get(
    "CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
SCALE = 2  # device scale factor for every PNG
PAD = 12  # user units of margin kept around cropped hand-drawn SVGs
MMDC_PACKAGE = (
    "@mermaid-js/mermaid-cli@12.0.0"  # pinned: later/earlier versions style diagrams differently
)
MAX_CSS_PX = 7000  # Chrome refuses window sizes much beyond this once multiplied by SCALE

# (glob relative to the repo root) -> every match becomes figures/<file stem>.png
SVG_SOURCES = [
    "docs/architecture/img/*.svg",
    "showcase-prep/assets/aws-topology.svg",
    "docs/results/actual-vs-target.svg",
    "project-documentation/images/*.svg",
    "project-documentation/final-report/figures/src/*.svg",
]

# Markdown files whose ```mermaid blocks are extracted to figures/src
MERMAID_DOCS = [
    ("use-case-design", "docs/architecture/use-case-design.md"),
    ("ddd", "docs/architecture/ddd.md"),
]


# --------------------------------------------------------------------------- helpers


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        head = handle.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def slugify(text: str) -> str:
    text = re.sub(r"^#+\s*", "", text.strip())
    text = re.sub(r"^\d+[.)]\s+", "", text)  # "1. Context map" -> "Context map"
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-") or "figure"


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")
    return True


def extract_mermaid() -> list[Path]:
    """Write every mermaid block of MERMAID_DOCS to figures/src; return the files."""
    written: list[Path] = []
    SRC.mkdir(parents=True, exist_ok=True)
    for doc, rel in MERMAID_DOCS:
        heading = "figure"
        count = 0
        inside = False
        body: list[str] = []
        for line in (REPO / rel).read_text(encoding="utf8").splitlines():
            if not inside:
                if re.match(r"^#{1,6}\s", line):
                    heading = line
                elif line.strip().startswith("```mermaid"):
                    inside, body = True, []
                continue
            if line.strip() == "```":
                inside = False
                count += 1
                target = SRC / f"{doc}-{count:02d}-{slugify(heading)}.mmd"
                if write_if_changed(target, "\n".join(body).rstrip() + "\n"):
                    print(f"extracted {target.relative_to(REPO)}")
                written.append(target)
            else:
                body.append(line)
    return written


# --------------------------------------------------------------------------- chrome / svg


def chrome_run(args: list[str], profile: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    command = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        *args,
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


ROOT_TAG = re.compile(r"<svg\b[^>]*>", re.S)


def set_root(
    svg: str, view_box: tuple[float, float, float, float], width: float, height: float
) -> str:
    """Give the root <svg> an explicit viewBox and pixel size (drops %, max-width)."""
    match = ROOT_TAG.search(svg)
    if match is None:
        raise ValueError("no <svg> root element")
    tag = match.group(0)
    tag = re.sub(r'\s(?:width|height|viewBox)="[^"]*"', "", tag)
    style = re.search(r'\sstyle="([^"]*)"', tag)
    if style:
        kept = [p for p in style.group(1).split(";") if p.strip() and "max-width" not in p]
        tag = tag.replace(style.group(0), f' style="{";".join(kept)}"' if kept else "")
    vb = " ".join(f"{v:.3f}".rstrip("0").rstrip(".") for v in view_box)
    tag = tag[:-1].rstrip("/ ") + f' width="{width:g}" height="{height:g}" viewBox="{vb}">'
    return svg[: match.start()] + tag + svg[match.end() :]


def page(svg: str, probe: bool = False) -> str:
    script = (
        "<script>window.addEventListener('load',()=>{const s=document.querySelector('svg');"
        "const b=s.getBBox();document.body.setAttribute('data-bbox',"
        "[b.x,b.y,b.width,b.height].join(' '));});</script>"
        if probe
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "html,body{margin:0;padding:0;background:#fff}svg{display:block}"
        f"</style></head><body>{svg}{script}</body></html>"
    )


def render_svg(source: Path, target: Path, profile: Path, scratch: Path) -> None:
    svg = source.read_text(encoding="utf8")
    svg = re.sub(r"^\s*<\?xml[^>]*\?>", "", svg).lstrip()
    root = ROOT_TAG.search(svg).group(0)
    vb = re.search(r'viewBox="([^"]+)"', root)
    if vb is None:
        w = float(re.search(r'\swidth="([\d.]+)', root).group(1))
        h = float(re.search(r'\sheight="([\d.]+)', root).group(1))
        box = (0.0, 0.0, w, h)
    else:
        box = tuple(float(v) for v in vb.group(1).replace(",", " ").split())  # type: ignore[assignment]

    if "aria-roledescription" not in root:  # hand-drawn: measure and crop to content
        probe = scratch / "probe.html"
        probe.write_text(page(set_root(svg, box, box[2], box[3]), probe=True), encoding="utf8")
        done = chrome_run(["--dump-dom", "--virtual-time-budget=3000", probe.as_uri()], profile)
        measured = re.search(r'data-bbox="([^"]+)"', done.stdout)
        if measured:
            x, y, w, h = (float(v) for v in measured.group(1).split())
            # never grow past the authored canvas
            x0, y0 = max(box[0], x - PAD), max(box[1], y - PAD)
            x1, y1 = min(box[0] + box[2], x + w + PAD), min(box[1] + box[3], y + h + PAD)
            box = (x0, y0, x1 - x0, y1 - y0)
        else:
            print(f"  warning: no bbox for {source.name}; keeping authored viewBox")

    width, height = box[2], box[3]
    scale_down = min(1.0, MAX_CSS_PX / max(width, height))
    css_w, css_h = width * scale_down, height * scale_down
    html = scratch / "render.html"
    html.write_text(page(set_root(svg, box, css_w, css_h)), encoding="utf8")
    win_w, win_h = math.ceil(css_w), math.ceil(css_h)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    done = chrome_run(
        [
            f"--screenshot={target}",
            f"--window-size={win_w},{win_h}",
            f"--force-device-scale-factor={SCALE}",
            "--default-background-color=ffffffff",
            "--virtual-time-budget=3000",
            html.as_uri(),
        ],
        profile,
    )
    if not target.exists():
        raise RuntimeError(f"Chrome produced no PNG for {source.name}:\n{done.stderr[-800:]}")


# --------------------------------------------------------------------------- mermaid


def render_mermaid(source: Path, target: Path, scratch: Path) -> None:
    config = scratch / "puppeteer.json"
    config.write_text(
        json.dumps({"executablePath": CHROME, "args": ["--no-sandbox"]}), encoding="utf8"
    )
    # useMaxWidth=false keeps each diagram at its natural size; the default squeezes wide
    # diagrams (sequences, ER) into mmdc's 800 px viewport and makes the text unreadable.
    mermaid_config = scratch / "mermaid.json"
    mermaid_config.write_text(
        json.dumps(
            {
                "maxTextSize": 200000,
                **{
                    kind: {"useMaxWidth": False}
                    for kind in (
                        "flowchart",
                        "sequence",
                        "class",
                        "er",
                        "state",
                        "gantt",
                        "journey",
                    )
                },
            }
        ),
        encoding="utf8",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    env = {**os.environ, "PUPPETEER_EXECUTABLE_PATH": CHROME}
    done = subprocess.run(
        [
            "npx", "-y", MMDC_PACKAGE, "-q",
            "-p", str(config), "-c", str(mermaid_config), "-i", str(source), "-o", str(target),
            "-s", str(SCALE), "-b", "white",
        ],  # fmt: skip
        capture_output=True, text=True, env=env, timeout=300,
    )  # fmt: skip
    if not target.exists():
        raise RuntimeError(f"mmdc produced no PNG for {source.name}:\n{done.stderr[-800:]}")


# --------------------------------------------------------------------------- main


def collect() -> dict[str, tuple[str, Path]]:
    jobs: dict[str, tuple[str, Path]] = {}
    for pattern in SVG_SOURCES:
        for path in sorted(REPO.glob(pattern)):
            jobs[path.stem] = ("svg", path)
    for path in sorted(SRC.glob("*.mmd")):
        jobs[path.stem] = ("mmd", path)
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", help="figure names (file stems or globs); default all")
    parser.add_argument("--force", action="store_true", help="re-render even if the PNG is newer")
    parser.add_argument("--list", action="store_true", help="print the figure names and exit")
    args = parser.parse_args()

    extract_mermaid()
    jobs = collect()
    if args.names:
        wanted = {n for n in jobs if any(fnmatch.fnmatch(n, pat) for pat in args.names)}
        unknown = [p for p in args.names if not fnmatch.filter(jobs, p)]
        if unknown:
            print(f"unknown figure name(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        jobs = {n: jobs[n] for n in sorted(wanted)}
    if args.list:
        for name, (kind, path) in jobs.items():
            print(f"{name}\t{kind}\t{path.relative_to(REPO)}")
        return 0
    if not Path(CHROME).exists():
        print(f"Chrome not found at {CHROME}; set CHROME_BIN", file=sys.stderr)
        return 1

    failures = 0
    FIGURES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dc2-figures-") as tmp:
        scratch = Path(tmp)
        profile = scratch / "chrome-profile"
        for name, (kind, path) in jobs.items():
            target = FIGURES / f"{name}.png"
            if (
                not args.force
                and target.exists()
                and target.stat().st_mtime >= path.stat().st_mtime
                and target.stat().st_mtime >= Path(__file__).stat().st_mtime
            ):
                print(f"up to date  {target.name}")
                continue
            try:
                if kind == "svg":
                    render_svg(path, target, profile, scratch)
                else:
                    render_mermaid(path, target, scratch)
                w, h = png_size(target)
                print(f"rendered    {target.name}  {w}x{h}  <- {path.relative_to(REPO)}")
            except Exception as error:  # keep going so one bad source does not hide the rest
                failures += 1
                print(f"FAILED      {name}: {error}", file=sys.stderr)
            shutil.rmtree(profile, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
