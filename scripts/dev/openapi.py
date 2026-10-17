"""Generate the published OpenAPI documents of the V1 Media and Processing public APIs.

    python -m scripts.dev.openapi           # rewrite docs/api/*.openapi.json
    python -m scripts.dev.openapi --check   # exit 1 if a committed document is stale

The documents describe what integrators call at the Gateway, so every path carries the prefix
the Gateway strips before the Lambda sees it (`contracts.gateway.PREFIXES`). They are built
from the same FastAPI applications the Lambdas serve, never hand-edited: a route, a model or a
status code that changes shows up here as a diff, and `tests/dev/test_openapi_docs.py` fails
until the document is regenerated. Processing sets `openapi_url=None` (no schema route is served
in production); `FastAPI.openapi()` still builds the schema offline, which is all this needs.

The authored pre-V1 contracts under project-roadmap/design/05-contracts describe the old routes
and remain the input of the example-validation tests, not the integrator contract.
"""

import argparse
import json
import sys
from pathlib import Path

from contracts.gateway import PREFIXES, is_public_route
from media.services.security import COOKIE_NAME
from scripts.dev.common import ROOT

OUT = ROOT / "docs/api"
DESCRIPTIONS = {
    "media": (
        "Public Media API behind the API Gateway: accounts, direct-to-S3 upload reservations, "
        "owned jobs and HLS delivery. Every route except the health probe and the three auth "
        "routes needs the session cookie set by /auth/login."
    ),
    "processing": (
        "Public Processing API behind the API Gateway: owner-scoped job status, retry and "
        "cancel. Needs the same session cookie as the Media API."
    ),
}


def build_app(service: str):
    """Import lazily: importing an application builds it, and a caller may want only one."""
    if service == "media":
        from media.main import create_v1_app

        return create_v1_app()
    from processing.v1_api import create_app

    return create_app()


def document(service: str) -> dict:
    schema = build_app(service).openapi()
    prefix = PREFIXES[service]
    schema["paths"] = {prefix + path: item for path, item in schema["paths"].items()}
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            # Mirror the authorizer so the contract states who may call without a session.
            if is_public_route(service, method.upper(), path.removeprefix(prefix)):
                operation["security"] = []
            else:
                operation["security"] = [{"sessionCookie": []}]
    schema["info"]["description"] = DESCRIPTIONS[service]
    schema.setdefault("components", {})["securitySchemes"] = {
        "sessionCookie": {"type": "apiKey", "in": "cookie", "name": COOKIE_NAME}
    }
    return schema


def render(service: str) -> str:
    return json.dumps(document(service), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def path_of(service: str) -> Path:
    return OUT / f"{service}.openapi.json"


def shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a document is stale")
    args = parser.parse_args(argv)
    stale = []
    for service in PREFIXES:
        text = render(service)
        target = path_of(service)
        if args.check:
            if not target.exists() or target.read_text() != text:
                stale.append(shown(target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            print(f"wrote {shown(target)}")
    if stale:
        print(
            "Stale OpenAPI document(s): " + ", ".join(stale) + "\n"
            "Run `python -m scripts.dev.openapi` and commit the result.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
