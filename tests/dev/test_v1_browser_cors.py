from scripts.dev.v1_browser import shipped_cors


def test_browser_harness_applies_the_templates_output_cors_for_the_page_origin():
    rule = shipped_cors("Output", "https://127.0.0.1:1")["CORSRules"][0]
    assert rule["AllowedOrigins"] == ["https://127.0.0.1:1"]
    assert rule["AllowedMethods"] == ["GET", "HEAD"]
    assert "Range" in rule["AllowedHeaders"]
    assert "Content-Range" in rule["ExposeHeaders"] and rule["MaxAgeSeconds"] == 300


def test_browser_harness_applies_the_templates_source_cors_for_direct_posts():
    rule = shipped_cors("Source", "https://127.0.0.1:1")["CORSRules"][0]
    assert rule["AllowedMethods"] == ["POST"] and "ETag" in rule["ExposeHeaders"]
