"""Exercise the local HTTPS product using actual services, files and clients."""

import argparse
import json
import subprocess
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from scripts.dev.scenario import Scenario, fixture


def playback(scenario, client, asset, result, *, require_hls=True):
    """Download/probe MP4 and traverse real HLS playlist and segment access."""
    response = client.get(result["output_url"])
    assert response.status_code == 200
    output = scenario.artifacts / f"{asset}.mp4"
    output.write_bytes(response.content)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    streams = json.loads(probe.stdout)["streams"]
    assert any(stream.get("codec_type") == "video" for stream in streams)
    scenario.record(
        "primary-playable", asset_id=asset, bytes=len(response.content), streams=streams
    )
    if not result.get("hls_url"):
        assert not require_hls, "Acceptance fixture must produce optional HLS successfully"
        return
    pending = [urljoin(scenario.state["public_url"], result["hls_url"])]
    playlists = set()
    segments = 0
    while pending:
        url = pending.pop()
        if url in playlists:
            continue
        assert len(playlists) < 10, "HLS traversal exceeded expected bounded ladder"
        playlists.add(url)
        response = client.get(url)
        assert response.status_code == 200 and response.text.startswith("#EXTM3U")
        for line in response.text.splitlines():
            if not line or line.startswith("#"):
                continue
            target = urljoin(url, line)
            if urlparse(target).path.endswith(".m3u8"):
                pending.append(target)
            else:
                reply = client.get(target, follow_redirects=True)
                assert reply.status_code == 200 and reply.content
                segments += 1
    assert segments > 0
    scenario.record("hls-readable", asset_id=asset, playlists=len(playlists), segments=segments)


def public_workflow(scenario):
    source = scenario.artifacts / "owned.mp4"
    scenario.report["fixture"] = fixture(source)
    other = scenario.artifacts / "different.mp4"
    fixture(other, seconds=1)
    owner, user, _ = scenario.account()
    stranger, _, _ = scenario.account("other")
    key = str(uuid4())
    accepted = scenario.upload(owner, source, key)
    asset = accepted["job_id"]
    assert scenario.upload(owner, source, key)["job_id"] == asset
    scenario.passed("CT-01", "Same owner/key/bytes returned the same public Asset ID")
    scenario.upload(owner, other, key, expected=409)
    scenario.passed("CT-02", "Changed bytes with retained key returned 409")
    for method, suffix, route in (
        ("GET", "", "/jobs/{job_id}"),
        ("DELETE", "", "/jobs/{job_id}"),
        ("POST", "/retry", "/jobs/{job_id}/retry"),
    ):
        scenario.request(stranger, method, f"jobs/{asset}{suffix}", 404, route=route)
    result = scenario.wait(owner, asset)
    job = scenario.processing_job(user["id"], asset)
    assert job["asset_id"] == asset and len(job["outputs"]) >= 1
    playback(scenario, owner, asset, result)
    response = stranger.get(urljoin(scenario.state["public_url"], result["hls_url"]))
    assert response.status_code == 404
    scenario.passed("CT-10", "Other owner cannot read status, retry, delete or HLS facade")
    edit_key = str(uuid4())
    operations = {"operations": [{"operation": "clip", "params": {"start": 0, "end": 1}}]}
    child = scenario.request(
        owner,
        "POST",
        f"jobs/{asset}/edit",
        202,
        route="/jobs/{job_id}/edit",
        json=operations,
        headers={"Idempotency-Key": edit_key},
    )["job_id"]
    replay = scenario.request(
        owner,
        "POST",
        f"jobs/{asset}/edit",
        202,
        route="/jobs/{job_id}/edit",
        json=operations,
        headers={"Idempotency-Key": edit_key},
    )
    assert replay["job_id"] == child
    scenario.request(owner, "DELETE", f"jobs/{asset}", 204, route="/jobs/{job_id}")
    scenario.request(owner, "GET", f"jobs/{asset}", 404, route="/jobs/{job_id}")
    child_result = scenario.wait(owner, child)
    playback(scenario, owner, child, child_result, require_hls=False)
    scenario.passed("CT-17", "Derived source finishes and plays after parent deletion")
    scenario.upload(owner, source, key, expected=410)
    scenario.passed("CT-21", "Deleted accepted upload key returns 410 without recreation")
    scenario.request(
        owner,
        "POST",
        f"jobs/{child}/retry",
        409,
        route="/jobs/{job_id}/retry",
        headers={"Idempotency-Key": str(uuid4())},
    )
    scenario.passed("CT-07", "Fresh retry request against done Asset is 409; wrong owner is 404")
    scenario.request(owner, "DELETE", f"jobs/{child}", 204, route="/jobs/{job_id}")
    scenario.request(owner, "DELETE", f"jobs/{child}", 204, route="/jobs/{job_id}")
    scenario.passed("CT-23", "Observed public and private responses pass prepared JSON schemas")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="local")
    parser.add_argument(
        "--public-only", action="store_true", help="Development subset; not full V1"
    )
    args = parser.parse_args()
    scenario = Scenario(args.run_id, "e2e")
    try:
        public_workflow(scenario)
        if not args.public_only:
            # Added with integrated client CLI and browser acceptance in the same wave.
            from scripts.dev.e2e_clients import browser_workflow, cli_workflow

            cli_workflow(scenario)
            browser_workflow(scenario)
        scenario.report["scope"] = "public-only" if args.public_only else "full"
        scenario.finish()
    except BaseException as error:
        scenario.finish(error)
        raise
    print(f"PASS: {scenario.artifacts / 'result.json'}")


if __name__ == "__main__":
    main()
