"""Strip credentials from text before it reaches a CI log, manifest or artifact.

A failing browser assertion prints request headers, URLs and page state. Those can carry
the session cookie, a JWT or a presigned object-store URL, and a CI artifact outlives the
run, so everything that leaves the private runtime directory goes through `redact` first.
"""

import re

_JWT = re.compile(r"eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[\w.~+/=-]{8,}")
# Header lines ("Cookie: a=b") and quoted mapping entries ({'cookie': 'a=b'}, "set-cookie": "...").
_COOKIE_QUOTED = re.compile(
    r"""(?i)(?P<head>(?P<q>['"])(?:set-)?cookie(?P=q)\s*[:=]\s*)(?P<v>(?P<vq>['"]).*?(?<!\\)(?P=vq))"""
)
_COOKIE_LINE = re.compile(r"(?im)^(?P<head>\s*(?:set-)?cookie\s*[:=]\s*).*$")
# Any query string or fragment: presigned URLs keep their signature there.
_QUERY = re.compile(r"[?#][\w.~%!$&'()*+,;=:@/-]*=[^\s'\"<>)\]}]*")
# Form fields of a presigned POST and AWS key material that appear outside a URL.
_AWS_FIELD = re.compile(
    r"(?i)\b(x-amz-(?:signature|credential|security-token)|signature|policy)\b(\s*['\"]?\s*[:=]\s*['\"]?)[^\s'\",&}]+"
)
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{12,}\b")


def redact(text):
    """Return `text` with cookie values, JWTs, bearer tokens and URL queries removed."""
    text = str(text)
    text = _COOKIE_QUOTED.sub(lambda m: m["head"] + m["vq"] + "<redacted>" + m["vq"], text)
    text = _COOKIE_LINE.sub(lambda m: m["head"] + "<redacted>", text)
    text = _JWT.sub("<jwt>", text)
    text = _BEARER.sub(lambda m: m[1] + " <redacted>", text)
    text = _QUERY.sub("?<redacted>", text)
    text = _AWS_FIELD.sub(lambda m: m[1] + m[2] + "<redacted>", text)
    return _AWS_KEY.sub("<aws-key>", text)


def first_lines(text, *, lines=6, chars=600):
    """A bounded, redacted excerpt that still shows the assertion and its message."""
    kept = "\n".join(str(text).strip().splitlines()[:lines])
    return redact(kept)[:chars]
