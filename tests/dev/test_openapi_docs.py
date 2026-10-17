"""The published integrator contracts must match the V1 applications that serve them."""

import json

import pytest

from scripts.dev import openapi


@pytest.mark.parametrize("service", ["media", "processing"])
def test_committed_openapi_document_matches_the_application(service):
    committed = openapi.path_of(service)
    assert committed.exists(), "run `python -m scripts.dev.openapi` and commit docs/api"
    assert committed.read_text() == openapi.render(service), (
        f"docs/api/{service}.openapi.json is stale; run `python -m scripts.dev.openapi`"
    )


@pytest.mark.parametrize(
    ("service", "prefix"), [("media", "/api/media"), ("processing", "/api/processing")]
)
def test_every_documented_path_uses_the_gateway_prefix(service, prefix):
    paths = json.loads(openapi.path_of(service).read_text())["paths"]
    assert paths
    assert all(path.startswith(prefix + "/") for path in paths)


def test_only_the_authorizers_public_routes_are_documented_as_open():
    open_routes = set()
    for service in ("media", "processing"):
        for path, item in json.loads(openapi.path_of(service).read_text())["paths"].items():
            open_routes |= {
                f"{method.upper()} {path}" for method, op in item.items() if op["security"] == []
            }
    assert open_routes == {
        "GET /api/media/health",
        "POST /api/media/auth/register",
        "POST /api/media/auth/login",
        "POST /api/media/auth/logout",
        "GET /api/processing/health",
    }


def test_check_mode_reports_a_stale_document(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(openapi, "OUT", tmp_path)
    assert openapi.main(["--check"]) == 1
    assert "Stale OpenAPI" in capsys.readouterr().err
    assert openapi.main([]) == 0
    assert openapi.main(["--check"]) == 0
