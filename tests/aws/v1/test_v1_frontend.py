"""SPA build, bucket sync and CloudFront invalidation; offline against the simulated account."""

import re
import shutil
from pathlib import Path

import pytest
from test_deploy import ARGS, TODAY, FakeGateway, Rig, run_main

from scripts.aws.transport import OperationError
from scripts.aws.v1 import deploy
from scripts.aws.v1 import frontend as spa

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def built(tmp_path):
    return spa.build(spa.SOURCE, tmp_path / "dist")


def by_key(manifest):
    return {f["key"]: f for f in manifest["files"]}


def test_the_files_index_html_loads_get_a_content_hash_and_the_references_follow(built):
    index = Path(by_key(built)["index.html"]["path"]).read_text()
    for original, hashed in built["hashed"].items():
        assert re.fullmatch(r"(vendor/)?[a-z.]+\.[0-9a-f]{10}\.(js|css)", hashed), hashed
        assert f'"{hashed}"' in index and f'"{original}"' not in index
        assert Path(by_key(built)[hashed]["path"]).read_bytes() == (
            spa.SOURCE / original).read_bytes()
    assert set(built["hashed"]) == {
        "app.js", "style.css", "vendor/hls.min.js", "vendor/plyr.min.js", "vendor/plyr.css"}


def test_index_html_is_never_cached_and_hashed_assets_are_immutable(built):
    files = by_key(built)
    assert files["index.html"]["cache_control"] == "no-cache"
    for hashed in built["hashed"].values():
        assert files[hashed]["cache_control"] == "public, max-age=31536000, immutable"


def test_runtime_assets_looked_up_by_fixed_path_keep_their_name_and_a_short_lifetime(built):
    files = by_key(built)
    for key in ("vendor/plyr.svg", "vendor/blank.mp4"):
        assert files[key]["cache_control"] == "public, max-age=86400"


def test_every_file_has_an_explicit_content_type_and_no_repository_extras_ship(built):
    files = by_key(built)
    assert files["index.html"]["content_type"] == "text/html; charset=utf-8"
    assert files["vendor/plyr.svg"]["content_type"] == "image/svg+xml"
    assert files["vendor/blank.mp4"]["content_type"] == "video/mp4"
    hashed_js = next(v for v in built["hashed"].values() if v.startswith("app."))
    assert files[hashed_js]["content_type"].startswith("text/javascript")
    assert not any(k.endswith((".md", ".test.js", ".json")) for k in files)
    assert not any("node_modules" in k for k in files)


def test_the_build_is_deterministic_and_clears_a_stale_output_directory(tmp_path):
    out = tmp_path / "dist"
    first = spa.build(spa.SOURCE, out)
    (out / "app.stale.js").write_text("old")
    second = spa.build(spa.SOURCE, out)
    assert first["sha256"] == second["sha256"]
    assert not (out / "app.stale.js").exists()


def test_a_source_that_calls_another_api_base_is_refused(tmp_path):
    source = tmp_path / "frontend"
    shutil.copytree(spa.SOURCE, source, ignore=shutil.ignore_patterns("node_modules", "coverage"))
    script = source / "app.js"
    script.write_text(script.read_text().replace('"/api/media"', '"https://elsewhere/api"'))
    with pytest.raises(OperationError, match="relative /api/media"):
        spa.build(source, tmp_path / "dist")


def test_a_missing_referenced_asset_stops_the_build(tmp_path):
    source = tmp_path / "frontend"
    shutil.copytree(spa.SOURCE, source, ignore=shutil.ignore_patterns("node_modules", "coverage"))
    (source / "style.css").unlink()
    with pytest.raises(OperationError, match="missing file"):
        spa.build(source, tmp_path / "dist")


def test_only_new_or_changed_bytes_upload_and_index_html_goes_last(built):
    files = by_key(built)
    todo = spa.changed(built, {})
    assert [f["key"] for f in todo][-1] == "index.html"
    assert len(todo) == len(built["files"])
    existing = {k: f["md5"] for k, f in files.items()}
    assert spa.changed(built, existing) == []
    existing["index.html"] = "0" * 32
    assert [f["key"] for f in spa.changed(built, existing)] == ["index.html"]


def test_the_invalidation_reference_is_stable_for_one_manifest_and_new_for_another(built):
    first = spa.invalidation("E1", built)
    assert first == spa.invalidation("E1", built)
    other = dict(built, sha256="f" * 64)
    ref = first["InvalidationBatch"]["CallerReference"]
    assert ref != spa.invalidation("E1", other)["InvalidationBatch"]["CallerReference"]
    assert first["InvalidationBatch"]["Paths"] == {"Quantity": 1, "Items": ["/*"]}


# ---- the pipeline step ---------------------------------------------------------------------
@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_the_step_runs_after_applications_and_before_the_database_work(rig):
    steps = list(deploy.DEPLOY_STEPS)
    assert steps.index("applications") + 1 == steps.index("frontend") < steps.index("db-bootstrap")


def test_the_step_uploads_with_content_types_and_cache_headers_then_invalidates(rig):
    rig.deploy(stop_after="frontend")
    puts = rig.sim.puts
    template_puts = [p for p in puts if p["Key"].startswith("templates/")]
    site = [p for p in puts if not p["Key"].startswith("templates/")]
    assert len(template_puts) == 2 and site
    assert site[-1]["Key"] == "index.html" and site[-1]["CacheControl"] == "no-cache"
    assert all(p["ContentType"] and p["ServerSideEncryption"] == "AES256" for p in site)
    assert {p["Bucket"] for p in site} == {next(
        b for b in rig.sim.buckets if "frontendbucket" in b)}
    batch = next(i for i in rig.sim.invalidations["E1SIMULATED"].values())["batch"]
    assert batch["Paths"]["Items"] == ["/*"]
    assert rig.steps()["frontend"] == "done"
    detail = rig.journal.view()["steps"]["frontend"]["detail"]
    assert detail["served_through_cloudfront"] == "PASS" and detail["uploaded"] == len(site)


def test_a_rerun_of_the_step_uploads_nothing_and_reuses_the_invalidation(rig):
    pipeline = rig.deploy(stop_after="frontend")
    first = len(rig.sim.puts)
    again = rig.pipeline()
    again.step = "frontend"
    result = again.step_frontend()
    assert result["uploaded"] == 0 and len(rig.sim.puts) == first
    assert len(rig.sim.invalidations["E1SIMULATED"]) == 1
    assert pipeline.detail("frontend")["invalidation"] == result["invalidation"]


def test_a_changed_script_uploads_only_it_and_the_page_that_names_it(rig, monkeypatch, tmp_path):
    rig.deploy(stop_after="frontend")
    source = tmp_path / "frontend"
    shutil.copytree(spa.SOURCE, source, ignore=shutil.ignore_patterns("node_modules", "coverage"))
    (source / "app.js").write_text((source / "app.js").read_text() + "\n// v2\n")
    monkeypatch.setattr(spa, "SOURCE", source)
    before = len(rig.sim.puts)
    pipeline = rig.pipeline()
    pipeline.step = "frontend"
    result = pipeline.step_frontend()
    keys = [p["Key"] for p in rig.sim.puts[before:]]
    assert result["uploaded"] == 2 and keys[0].startswith("app.") and keys[-1] == "index.html"
    assert len(rig.sim.invalidations["E1SIMULATED"]) == 2  # a new manifest, a new reference


def test_a_distribution_still_serving_the_old_page_fails_the_step(tmp_path):
    rig = Rig(tmp_path, gateway=FakeGateway(index=b"<html>old page</html>"))
    with pytest.raises(deploy.DeployError, match="freshly uploaded index.html"):
        rig.deploy(stop_after="frontend")
    assert rig.steps()["frontend"] == "failed"


def test_teardown_empties_the_frontend_bucket_like_every_other_owned_bucket(rig):
    rig.deploy(stop_after="frontend")
    frontend = next(b for b in rig.sim.buckets if "frontendbucket" in b)
    assert rig.sim.buckets[frontend]["versions"]
    rig.s.confirm_run_id = "t1"
    rig.teardown()
    removed = {(p["Bucket"], o["Key"]) for _, op, p in rig.sim.calls if op == "delete-objects"
               for o in p["Delete"]["Objects"]}
    assert (frontend, "index.html") in removed
    assert frontend not in rig.sim.buckets


def test_a_dry_run_plans_the_upload_and_the_invalidation_without_a_network_check():
    code, text = run_main(["deploy", *ARGS, "--run-id", "rehearsal1", "--dry-run"],
                          today=lambda: TODAY)
    plan = text[text.index("\n## ") + 1:]
    assert code == 0
    assert plan.index("## applications") < plan.index("## frontend") < plan.index("## db-bootstrap")
    frontend = plan[plan.index("## frontend"):plan.index("## db-bootstrap")]
    assert "s3api put-object" in frontend and "cloudfront create-invalidation" in frontend
    assert "--body" in frontend and "no-cache" in frontend

# Controlled CI selection sample for #165; no test behavior changes.
