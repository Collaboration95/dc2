"""Validate a built copy of the site: local links and anchors resolve, nothing private is published.

Usage: python3 _check.py <built-site-dir>
"""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

STATIC = {".html", ".css", ".js", ".svg", ".woff2", ".txt"}
PRIVATE = (r"zoom\.us", r"[?&]pwd=", r"Meeting ID:", r"Passcode:", r"/Users/")


class Page(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.links: list[str] = []
        self.ids: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        self.links += [values[a] for a in ("href", "src") if a in values]


def check(site: Path) -> int:
    site = site.resolve()
    pages = {p: Page(p.read_text()) for p in site.rglob("*.html")}
    checked = 0
    for path, page in pages.items():
        if len(page.ids) != len(set(page.ids)):
            raise SystemExit(f"Duplicate id in {path.name}")
        for href in page.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                if url.scheme != "https":
                    raise SystemExit(f"Non-HTTPS external link in {path.name}: {href}")
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if not target.is_relative_to(site) or not target.exists():
                raise SystemExit(f"Broken link in {path.name}: {href}")
            if url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                raise SystemExit(f"Broken anchor in {path.name}: {href}")
            checked += 1
    for path in site.rglob("*"):
        if path.is_file() and path.name != ".nojekyll":
            if path.suffix not in STATIC:
                raise SystemExit(f"Unexpected file: {path.name}")
            if any(re.search(p, path.read_text(), re.IGNORECASE) for p in PRIVATE):
                raise SystemExit(f"Private reference pattern in {path.name}")
    print(f"{len(pages)} pages, {checked} local links checked")
    return 0


if __name__ == "__main__":
    sys.exit(check(Path(sys.argv[1])))
