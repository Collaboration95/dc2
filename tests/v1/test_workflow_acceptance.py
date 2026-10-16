"""Real PG + actual Publisher/Gateway/domain/FFmpeg round trip on Lead C's stack.

Gateway event mapping and S3/SQS are emulated. Domain SQL, source verification,
public cookie authentication, Publisher direct POST, worker watchdog/FFmpeg and
owned projections execute for real. Browser rendering and AWS IAM remain NOT_RUN.
"""

import hashlib
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]


def test_publisher_direct_post_encode_projection_and_ownership(tmp_path):
    if not os.environ.get("V1_RUNTIME_CONFIG"):
        pytest.skip("Explicit Lead C runtime attachment required")
    import media
    import processing
    import publisher
    from publisher.client import PublicClient, PublisherError
    from scripts.dev.v1_acceptance import app_runtime, encode_one, pump

    # Exact candidate imports are part of the evidence, never shared installed code.
    root = Path.cwd().resolve()
    assert all(
        Path(package.__file__).resolve().is_relative_to(root)
        for package in (media, processing, publisher)
    )
    source = tmp_path / "short-av.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    with app_runtime(os.environ["V1_RUN_ID"]) as runtime:
        client = PublicClient(
            runtime["url"] + "/api/media", tmp_path / "publisher.cookies", ca_file=runtime["ca"]
        )
        other = PublicClient(
            runtime["url"] + "/api/media", tmp_path / "other.cookies", ca_file=runtime["ca"]
        )
        try:
            identity = client.authenticate(
                "register", f"accept-{uuid4().hex}@example.com", "local-acceptance-password"
            )
            other.authenticate(
                "register", f"other-{uuid4().hex}@example.com", "local-other-password"
            )
            assert client.identity() == identity["id"]
            request_id = str(uuid4())
            asset = client.upload(source, request_id)
            assert client.upload(source, request_id) == asset  # finalize/reservation replay
            with pytest.raises(PublisherError) as denied:
                other.status(asset)
            assert denied.value.status == 404
            forged = other.http.get(
                f"jobs/{asset}", headers={"X-Owner-Id": identity["id"], "X-Role": "publisher"}
            )
            assert forged.status_code == 404
            pump(runtime, results=False)
            encode_one(runtime)
            # Newest result first, then duplicates/older queued+processing results.
            pump(runtime, reverse=True)
            completed = client.request("GET", f"jobs/{asset}")
            assert completed["status"] == "done", (
                "Real worker result did not reach Media projection"
            )
            assert completed["processing_job_id"] != asset
            with httpx.Client(
                verify=__import__("ssl").create_default_context(cafile=runtime["ca"]),
                trust_env=False,
            ) as objects:
                result = objects.get(completed["output_url"], headers={"Range": "bytes=0-31"})
                assert result.status_code == 206 and len(result.content) == 32
            # hls_url is origin-relative; httpx would append it to the /api/media base_url.
            playlist = client.http.get(runtime["url"] + completed["hls_url"])
            assert playlist.status_code == 200 and "#EXTM3U" in playlist.text
            # Stored-source edit command, then cancel before execution: no worker auto-starts.
            derived = client.edit(
                asset, [{"operation": "clip", "params": {"start": 0, "end": 0.5}}], str(uuid4())
            )
            assert derived != asset
            client.delete(derived)
            pump(runtime)
            client.delete(asset)
            pump(runtime)
            with pytest.raises(PublisherError) as gone:
                client.status(asset)
            assert gone.value.status in {404, 410}
            assert runtime["observations"]["storage_cookie_headers"] == 0
            receipt = {
                "scope": "real Publisher/TLS/Gateway-emulated/SQL/S3-SQS-emulated/FFmpeg",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_bytes": source.stat().st_size,
                "roundtrip": "PASS",
                "duplicate_reordered_results": "PASS",
                "wrong_owner_forged_header": "PASS",
                "stored_source_edit_cancel_delete": "PASS",
                "storage_cookie_leak": False,
                "browser_rendering": "NOT_RUN",
                "AWS_IAM_Fargate": "NOT_RUN",
            }
            (tmp_path / "workflow-receipt.json").write_text(
                __import__("json").dumps(receipt, indent=2)
            )
        finally:
            client.close()
            other.close()
