"""Estimate the printed size of the smallest text in each report figure.

PlantUML figures use `skinparam dpi 110` with 13-15 px fonts, so a 13 px label is
about 13 * 110/72 = 20 px tall in the PNG. Scaling the PNG to its markdown width
gives the printed height in points. Aim for >= 7 pt; flag < 6 pt.
"""
import glob
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png_size(path):
    with open(path, "rb") as handle:
        handle.read(16)
        return struct.unpack(">II", handle.read(8))


def main():
    rows = []
    for md in sorted(glob.glob(str(ROOT / "src" / "*.md"))):
        text = Path(md).read_text()
        for match in re.finditer(r"\]\((figures/[\w-]+\.png)\)(\{width=([\d.]+)cm\})?", text):
            rel = match.group(1)
            width_cm = float(match.group(3) or 15.0)
            w, h = png_size(ROOT / rel)
            label_px = 20 if Path(rel).stem.split("-")[0] not in {"conduct", "actual", "cover"} else None
            if label_px is None:
                continue  # matplotlib charts and logos: check by eye
            pt = label_px * (width_cm / 2.54 * 72) / w
            rows.append((pt, rel, Path(md).name, w, h, width_cm, width_cm * h / w))
    rows.sort()
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
    for pt, rel, md, w, h, wcm, hcm in rows:
        if pt < limit:
            print(f"{pt:4.1f} pt  {rel:45s} {w}x{h}px  width={wcm}cm  height={hcm:.0f}cm  {md}")


if __name__ == "__main__":
    main()
