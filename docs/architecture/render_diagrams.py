"""Render every Mermaid block marked `%% img: <name>` in this folder to img/<name>.svg.

Usage: python3 docs/architecture/render_diagrams.py
Needs Node; the first run downloads @mermaid-js/mermaid-cli and a headless browser.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BLOCK = re.compile(r"```mermaid\n%% img: ([a-z0-9-]+)\n(.*?)```", re.S)


def main() -> int:
    out = HERE / "img"
    out.mkdir(exist_ok=True)
    count = 0
    with tempfile.TemporaryDirectory() as scratch:
        for page in sorted(HERE.glob("*.md")):
            for name, body in BLOCK.findall(page.read_text()):
                source = Path(scratch) / f"{name}.mmd"
                source.write_text(body)
                target = out / f"{name}.svg"
                command = ["npx", "-y", "@mermaid-js/mermaid-cli", "-q", "-i", str(source)]
                subprocess.run([*command, "-o", str(target)], check=True)
                print(f"rendered {target.relative_to(HERE)}")
                count += 1
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
