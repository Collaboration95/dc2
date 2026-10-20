"""Stage the Flickpond SPA for the V1 frontend bucket. Pure functions; no AWS call lives here.

The frontend has no bundler (`frontend/vendor/README.md` says adding one is not the point), so
"build" means: copy the files the browser actually loads, give the ones `index.html` references
a content hash in their name, and rewrite those references. Hashed names are what make a long
immutable cache lifetime safe; `index.html` is the one file whose name never changes, so it is
the one that must not be cached (CloudFront honours the origin's Cache-Control for it).

API base: `app.js` calls the relative path `/api/media`. CloudFront serves this bucket as its
default origin and forwards `/api/*` to the HTTP API origin, so a same-origin relative path
already reaches the Gateway and the session cookie (SameSite=Strict, HttpOnly) stays first-party.
Nothing needs injecting; `build` instead refuses a source tree that would call something else.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

from scripts.aws.transport import OperationError

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "frontend"
# Explicit table rather than the platform's mimetypes database, which differs between hosts.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".mp4": "video/mp4",
    ".LICENSE": "text/plain; charset=utf-8",
}
NO_CACHE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"
# Unhashed runtime assets (plyr.svg, blank.mp4) are looked up by a fixed path from app.js.
SHORT = "public, max-age=86400"
# Only these are shipped from vendor/: not the README or anything a test run leaves behind.
VENDOR_SUFFIXES = (".js", ".css", ".svg", ".mp4", ".LICENSE")
_REFERENCE = re.compile(r'(?P<attr>src|href)="(?P<path>(?:vendor/)?[A-Za-z0-9._-]+\.(?:js|css))"')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _content_type(path):
    suffix = ".LICENSE" if path.name.endswith(".LICENSE") else path.suffix
    if suffix not in CONTENT_TYPES:
        raise OperationError(f"No content type for {path.name}; refusing to guess")
    return CONTENT_TYPES[suffix]


def _check_api_base(source):
    html = (source / "index.html").read_text()
    script = (source / "app.js").read_text()
    if 'const API = LEGACY_API ? "/api" : "/api/media";' not in script:
        raise OperationError("app.js no longer calls the relative /api/media base; review first")
    if "FLICKPOND_LEGACY_API" in html:
        raise OperationError("index.html opts into the legacy API; V1 serves /api/media only")


def build(source=SOURCE, out=None):
    """Write the deployable tree to `out` and return its manifest (sorted, deterministic)."""
    source, out = Path(source), Path(out)
    if not (source / "index.html").is_file() or not (source / "app.js").is_file():
        raise OperationError("Frontend source tree is incomplete")
    _check_api_base(source)
    if out.exists():
        shutil.rmtree(out)  # a stale hashed file from an earlier build must not be uploaded
    out.mkdir(parents=True, mode=0o700)
    html = (source / "index.html").read_text()
    renames = {}

    def hashed(match):
        path = match.group("path")
        original = source / path
        if not original.is_file():
            raise OperationError(f"index.html references a missing file: {path}")
        name = Path(path)
        digest = _digest(original.read_bytes())[:10]
        renames[path] = name.with_name(f"{name.stem}.{digest}{name.suffix}").as_posix()
        return f'{match.group("attr")}="{renames[path]}"'

    rewritten = _REFERENCE.sub(hashed, html)
    if not renames:
        raise OperationError("index.html references no local assets; the build would be empty")
    entries = {"index.html": (rewritten.encode(), NO_CACHE)}
    for original, name in renames.items():
        entries[name] = ((source / original).read_bytes(), IMMUTABLE)
    for path in sorted((source / "vendor").iterdir()):
        key = f"vendor/{path.name}"
        keep = path.is_file() and path.name.endswith(VENDOR_SUFFIXES)
        if keep and key not in renames and key not in entries:
            entries[key] = (path.read_bytes(), SHORT)
    manifest = []
    for key, (data, cache) in sorted(entries.items()):
        target = out / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append(
            {
                "key": key,
                "path": str(target),
                "content_type": _content_type(Path(key)),
                "cache_control": cache,
                "size": len(data),
                "sha256": _digest(data),
                "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
            }
        )
    return {
        "files": manifest,
        "sha256": _digest(
            json.dumps(
                [(f["key"], f["sha256"], f["content_type"], f["cache_control"]) for f in manifest]
            ).encode()
        ),
        "hashed": renames,
    }


def upload_order(manifest):
    """index.html last: it is the file that names the others, so it must never go first."""
    files = manifest["files"]
    return [f for f in files if f["key"] != "index.html"] + [
        f for f in files if f["key"] == "index.html"
    ]


def changed(manifest, existing):
    """The files whose bytes or headers are not already in the bucket.

    `existing` maps key -> md5 (an S3 ETag without quotes; single-part SSE-S3 objects use md5).
    Headers cannot be seen in a listing, so a header-only change needs a new content hash; the
    build guarantees that by hashing every asset whose cache lifetime is immutable.
    """
    return [f for f in upload_order(manifest) if existing.get(f["key"]) != f["md5"]]


def invalidation(distribution_id, manifest):
    """One idempotent request: the same manifest always reuses the same caller reference."""
    return {
        "DistributionId": distribution_id,
        "InvalidationBatch": {
            "Paths": {"Quantity": 1, "Items": ["/*"]},
            "CallerReference": f"fe-{manifest['sha256'][:24]}",
        },
    }
