"""Check that relative Markdown links and images point at files that exist.

Usage: python scripts/dev/check_md_links.py FILE.md [FILE.md ...]

External (http, mailto) links and in-page anchors are not followed: this only catches the
broken-path kind of rot, offline. A `#fragment` after a path is stripped before the check.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

# [text](target) and ![alt](target); the target may not contain spaces unless wrapped in <>.
LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def broken(path: Path) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
        if in_fence:
            continue
        for match in LINK.finditer(re.sub(r"`[^`]*`", "", line)):
            target = match.group(1).strip("<>")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            relative = unquote(target.split("#", 1)[0])
            if relative and not (path.parent / relative).exists():
                bad.append((number, target))
    return bad


def main(argv: list[str]) -> int:
    failures = 0
    for name in argv:
        for number, target in broken(Path(name)):
            print(f"{name}:{number}: missing {target}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
