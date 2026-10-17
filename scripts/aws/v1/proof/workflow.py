"""The real upload-to-playback workflow, shared by the #63 and #64 harnesses.

reserve -> presigned POST straight to S3 -> finalize -> job -> done -> HLS through CloudFront.
Every call goes through the public origin exactly as the browser or Publisher CLI makes it; the
only privileged actions are the ones the session design reserves for the operator: starting the
finite encoder tasks (`Session.batch`) and stopping them.
"""

import hashlib
import posixpath
import uuid
from pathlib import Path
from urllib.parse import urljoin

from scripts.aws.v1.proof import tasks
from scripts.aws.v1.proof.core import ProofError, direct, host_of, multipart
from scripts.aws.v1.session import Session
from scripts.aws.workers import describe_tasks, inventory

TERMINAL = {"done", "failed", "cancelled"}
UPLOAD_OK = {200, 201, 204}
CONTENT_TYPE = "video/mp4"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def login(ctx, origin="frontend"):
    api = ctx.api(origin)
    reply, flags = api.login(ctx.credentials())
    if reply.status != 200 or not api.cookie:
        raise ProofError(f"Smoke login failed with HTTP {reply.status}")
    return api, reply, flags


def reserve(api, path, request_id, *, replay_ok=False):
    """Reserve an upload. A replay of a finalized reservation answers `upload: null`.

    Media issues no new writable grant once a reservation is finalized, so 201 with
    `upload: null` is success for a resumed run (`replay_ok`) and a failure for a caller that
    needs a grant to use.
    """
    path = Path(path)
    reply = api.request("POST", "/api/media/uploads/reservations", body={
        "request_id": request_id, "filename": path.name, "content_type": CONTENT_TYPE,
        "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    data = reply.json()
    if reply.status != 201 or not isinstance(data, dict) or not data.get("reservation_id"):
        raise ProofError(f"Reservation failed with HTTP {reply.status}")
    if not data.get("upload") and not replay_ok:
        raise ProofError(f"Reservation returned no upload grant (HTTP {reply.status})")
    return reply, data


def submit(ctx, api, path, intent, save):
    """reserve -> upload -> finalize, resumable: ids are recorded before the next side effect.

    Every step may be repeated: the reservation is idempotent on `request_id`, the upload is
    skipped once recorded (or once the replay shows the reservation finalized), and finalize
    returns the same job. The first measurement of each timing is kept, so a resumed run
    reports the original latency and not the replay's.
    """
    path = Path(path)
    if not path.is_file():
        raise ProofError("The fixture file does not exist")
    intent.setdefault("request_id", str(uuid.uuid4()))
    save()
    timing = intent.setdefault("timing", {})
    reply, data = reserve(api, path, intent["request_id"], replay_ok=True)
    timing.setdefault("reserve_ms", reply.ms)
    intent["reservation_id"] = data["reservation_id"]
    save()
    grant = data.get("upload")
    if grant is None:
        # Finalized already: an earlier attempt uploaded, and Media accepted, the bytes.
        intent["uploaded"] = True
        save()
    elif not intent.get("uploaded"):
        if not str(grant["url"]).startswith("https://"):
            raise ProofError("The storage upload URL is not HTTPS")
        ctype, body = multipart(grant["fields"], path.name, path.read_bytes(), CONTENT_TYPE)
        # No cookie: storage is a different origin and must never see the session.
        sent = direct(ctx.http, "POST", grant["url"], {"content-type": ctype}, body,
                      timeout=600, clock=ctx.clock)
        if sent.status not in UPLOAD_OK:
            raise ProofError(f"Direct upload to storage returned HTTP {sent.status}")
        timing["upload_ms"], timing["upload_status"] = sent.ms, sent.status
        timing["storage_host_is_s3"] = host_of(grant["url"]).endswith(".amazonaws.com")
        intent["uploaded"] = True
        save()
    final = api.request(
        "POST", f"/api/media/uploads/reservations/{intent['reservation_id']}/finalize",
        body={"request_id": intent["request_id"]})
    accepted = final.json()
    if final.status not in {200, 201, 202} or not isinstance(accepted, dict) or not accepted.get(
            "job_id"):
        raise ProofError(f"Finalize failed with HTTP {final.status}")
    timing.setdefault("finalize_ms", final.ms)
    timing.setdefault("finalize_status", final.status)
    if intent.get("job_id") not in {None, accepted["job_id"]}:
        raise ProofError("Finalize replay named a different job than the one recorded")
    intent["job_id"] = accepted["job_id"]
    save()
    return {"job_id": accepted["job_id"], "bytes": path.stat().st_size, **timing}


def poll_job(ctx, api, job_id, *, timeout, interval=5, until=TERMINAL, checkpoint=None,
             check_every=12):
    """Poll a job; returns (transitions, last document). Transitions are (seconds, status)."""
    start, transitions, polls = ctx.clock(), [], 0
    while True:
        reply = api.request("GET", f"/api/media/jobs/{job_id}")
        job = reply.json() if reply.status == 200 else None
        if job and (not transitions or transitions[-1][1] != job["status"]):
            transitions.append((round(ctx.clock() - start, 1), job["status"]))
        if job and job["status"] in until:
            return transitions, job
        if ctx.clock() - start >= timeout:
            raise ProofError(f"Job did not reach {sorted(until)} within {timeout} seconds")
        polls += 1
        if checkpoint and polls % check_every == 0:
            checkpoint("open")
        ctx.sleep(interval)


def session(ctx, minutes):
    ctx.config["session_end_epoch"] = ctx.wall() + 60 * minutes
    return Session(ctx.config, ctx.aws, ctx.journal, clock=ctx.clock, sleep=ctx.sleep)


def start_workers(ctx, count, minutes):
    """Reserve-then-RunTask through the shared session logic (it enforces the cap of three)."""
    return session(ctx, minutes).batch(count=count, deadline=ctx.deadline(300), epoch=ctx.wall)


def live_tasks(ctx):
    found = inventory(ctx.config, ctx.aws, deadline=ctx.deadline(120))
    return {arn: t for arn, t in found.items() if t["lastStatus"] != "STOPPED"}


def wait_stopped(ctx, arns, *, timeout, checkpoint=None):
    """Block until every named task is STOPPED; returns their final descriptions."""
    def check():
        found = describe_tasks(ctx.config, ctx.aws, arns, deadline=ctx.deadline(60))
        return all(t["lastStatus"] == "STOPPED" for t in found.values()), found

    return tasks.wait_until(ctx, check, timeout=timeout, interval=10, checkpoint=checkpoint,
                            session="open")


def playback(ctx, api, job):
    """Fetch the HLS ladder through CloudFront, then a segment through its S3 redirect."""
    out = {"hls_url_present": bool(job.get("hls_url")),
           "output_url_present": bool(job.get("output_url"))}
    if not job.get("hls_url"):
        return False, out
    master = api.request("GET", job["hls_url"])
    out["master_status"] = master.status
    out["master_is_playlist"] = master.body.startswith(b"#EXTM3U")
    out["served_by_cloudfront"] = "cloudfront" in master.first("x-cache").lower()
    out["playlist_not_cached"] = "no-store" in master.first("cache-control").lower()
    if master.status != 200 or not out["master_is_playlist"]:
        return False, out
    reference, path = _first_reference(master.body), job["hls_url"]
    variant_path = urljoin(path, reference) if reference else None
    segment_path = variant_path
    if variant_path and variant_path.endswith(".m3u8"):
        variant = api.request("GET", variant_path)
        out["variant_status"] = variant.status
        inner = _first_reference(variant.body) if variant.status == 200 else None
        segment_path = urljoin(variant_path, inner) if inner else None
    if not segment_path or not segment_path.endswith(".ts"):
        out["segment_found"] = False
        return False, out
    segment = api.request("GET", segment_path)
    out["segment_status"] = segment.status
    location = segment.first("location")
    out["segment_redirects_to_s3"] = segment.status == 307 and host_of(location).endswith(
        ".amazonaws.com")
    ok = False
    if out["segment_redirects_to_s3"]:
        ok = _ranged(ctx, location, out, "segment")
    if job.get("output_url"):
        out["mp4_ok"] = _ranged(ctx, job["output_url"], out, "mp4")
        ok = ok and out["mp4_ok"]
    return ok, out


def _ranged(ctx, url, out, label):
    """A signed GET with Range and no cookie; only status and length are kept."""
    got = direct(ctx.http, "GET", url, {"range": "bytes=0-1023"}, None, clock=ctx.clock)
    out[f"{label}_fetch_status"] = got.status
    out[f"{label}_fetch_bytes"] = len(got.body)
    return got.status in {200, 206} and len(got.body) > 0


def _first_reference(body):
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return posixpath.normpath(line) if "://" not in line else None
    return None
