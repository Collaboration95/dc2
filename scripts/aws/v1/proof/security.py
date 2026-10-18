"""#229: the proposal section 3.3 negatives that had never been tried on AWS.

User A uploads one short clip and the encoder finishes it. Then, through the public origins only:

* `cross-owner`: user B gets 404 on A's job, retry, playback and Processing job, and A's job is
  unchanged afterwards. A's own reads are the control (200), so a 404 cannot mean a dead route.
* `unauthenticated`: every protected route answers exactly 401 with no session on both CloudFront
  and the execute-api origin; a forged token and a token with a changed signature are denied
  (401, or 403 when API Gateway's Lambda authorizer rejects a cookie that is present).
* `tampered-urls`: an upload grant and the two kinds of signed GET (HLS segment, MP4) are refused
  once the signature, policy, key, content type or lifetime is changed or the signature removed.
  The untouched grant or URL is the control (it works), so the refusal is the tampering's.
* `oversized-upload`: a reservation above 100 MiB is refused; bytes larger than the reserved size
  are rejected by storage or, failing that, not adopted at finalize.
* `oversize-100mib` (opt-in, `--full-size-limit`): the limit itself against real S3 bytes, one
  upload of 100 MiB plus one byte.
* `s3-direct-denied`: unsigned list, versions, GET and PUT on both buckets are 403.
* `playback-url-expiry` and `upload-url-expiry`: a signed GET and an upload grant fail after
  expiry. Media fixes both lifetimes (15 minutes), so they run only when `--max-expiry-wait`
  covers them and are NOT_RUN, with the reason, otherwise. Tampering is tested either way.
* `port-scan`: a TCP connect scan of the CloudFront hostname over a fixed list of twelve ports
  expects exactly 80 and 443 open, and plain HTTP redirecting to HTTPS. Nothing else is scanned.
* `execute-api-direct`: what the API Gateway URL does without CloudFront, recorded as `refused`
  or `reachable_authorizer_enforced`; anonymous data exposed is a FAIL.

The receipt (`evidence-229-<run>.json`) carries status codes, counts and booleans in its public
view. Cookies, tokens, signed URLs, upload fields and passwords exist only in memory: the two
users' credentials are recomputed from the smoke secret and the run id, never stored, so a rerun
signs in again instead of reading them back.

Needs a full `session open` (the job reaches `done` only with consumers on). The harness starts
its encoder through `isolation.finish_job`, the rule the other proofs share, and stops it.
"""

import datetime as dt
import hashlib
import posixpath
import socket
import uuid
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from contracts.v1 import MAX_UPLOAD_BYTES
from scripts.aws.v1.proof import capacity, isolation, tasks, workflow
from scripts.aws.v1.proof.core import (
    FAIL,
    NOT_RUN,
    PASS,
    ProofError,
    direct,
    host_of,
    multipart,
    parse_time,
)

ISSUE = 229
STEPS = ("setup-job", "cross-owner", "unauthenticated", "tampered-urls", "oversized-upload",
         "oversize-100mib", "s3-direct-denied", "playback-url-expiry", "upload-url-expiry",
         "port-scan", "execute-api-direct")
REQUIRED = STEPS
NEEDS_JOB = {"cross-owner", "tampered-urls", "s3-direct-denied", "playback-url-expiry"}
MAX_BYTES = MAX_UPLOAD_BYTES
# The only ports ever probed, and the only host: the CloudFront hostname of this stack.
PORTS = (21, 22, 25, 80, 443, 3306, 5432, 6379, 8000, 8080, 8443, 9000)
EXPECTED_OPEN = [80, 443]
CONNECT_TIMEOUT = 3.0
MAX_ADDRESSES = 4
EXPIRY_WAIT = 120  # seconds a run will sit waiting for a URL to expire, unless told otherwise
EXPIRY_MARGIN = 10  # past the stated expiry, for clock skew between here and S3
CONTENT_TYPE = workflow.CONTENT_TYPE
DENIED_STORAGE = {403}
PACE_SECONDS = 0.25  # between API calls: the Gateway's default throttle is 5 requests a second


# ---- small helpers ------------------------------------------------------------------------
def ask(ctx, api, method, path, **kwargs):
    """`api.request`, paced, and retried while the Gateway answers 429.

    A 429 is the throttle speaking, not the authorizer or the owner check, so it must never be
    read as a denial (or as a failure of one).
    """
    for attempt in range(1, 7):
        reply = api.request(method, path, **kwargs)
        if reply.status != 429:
            ctx.sleep(PACE_SECONDS)
            return reply
        ctx.sleep(attempt)
    return reply


def rejected(status):
    """A refusal: some 4xx. 2xx is acceptance and 5xx or no answer proves nothing."""
    return status is not None and 400 <= status < 500


def flip(text):
    """The same string with its last character changed (still the same length and alphabet)."""
    return text[:-1] + ("0" if text[-1] != "0" else "1")


def derived(ctx, label):
    seed = ctx.credentials()["password"]
    digest = hashlib.sha256(f"{seed}:{ctx.run_id}:{label}".encode()).hexdigest()
    return {"email": f"security-{label}-{digest[:12]}@example.com", "password": digest[12:52]}


def account(ctx, label):
    """Register (409 on a rerun is fine) and sign in a throwaway user; returns the signed-in Api.

    Email and password are derived from the smoke secret and the run id each time, so nothing
    that signs in is ever written down and a resumed run reaches the same two users.
    """
    credentials = derived(ctx, label)
    api = ctx.api("frontend")
    reply = ask(ctx, api, "POST", "/api/media/auth/register", body=credentials, auth=False)
    if reply.status not in {201, 409}:
        raise ProofError(f"Registering user {label} returned HTTP {reply.status}")
    return sign_in(ctx, api, label, credentials)


def sign_in(ctx, api, label, credentials):
    for attempt in range(1, 7):
        reply, _ = api.login(credentials)
        if reply.status != 429:
            break
        ctx.sleep(attempt)
    if reply.status != 200 or not api.cookie:
        raise ProofError(f"Signing in user {label} returned HTTP {reply.status}")
    return api


def probe_file(ctx, name, size=1024):
    """A small deterministic file: reservations need a size and a checksum, not a real video."""
    path = ctx.state_dir / "evidence" / f"security-{name}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    seed = f"dc2-security-{name}-".encode()
    path.write_bytes((seed * (size // len(seed) + 1))[:size])
    return path


def grant_for(api, path, request_id):
    _, data = workflow.reserve(api, path, request_id)
    grant = data["upload"]
    if not str(grant.get("url", "")).startswith("https://") or not isinstance(
            grant.get("fields"), dict):
        raise ProofError("The upload grant is not an HTTPS presigned POST")
    return data, grant


def field_name(fields, wanted):
    for name in fields:
        if name.lower() == wanted:
            return name
    raise ProofError(f"The upload grant has no {wanted.split('-')[-1]} field")


def post_grant(ctx, grant, fields, filename, content, *, timeout=60):
    """A POST to storage with exactly these fields; never a cookie (direct() refuses one)."""
    ctype, body = multipart(fields, filename, content, CONTENT_TYPE)
    return direct(ctx.http, "POST", grant["url"], {"content-type": ctype}, body,
                  timeout=timeout, clock=ctx.clock)


def tampered_fields(fields, change):
    """A copy of the grant's fields with one thing wrong."""
    mutated = dict(fields)
    signature = field_name(mutated, "x-amz-signature")
    if change == "signature_changed":
        mutated[signature] = flip(mutated[signature])
    elif change == "signature_removed":
        del mutated[signature]
    elif change == "policy_changed":
        policy = field_name(mutated, "policy")
        mutated[policy] = flip(mutated[policy])
    elif change == "key_changed":
        mutated[field_name(mutated, "key")] += "-tampered"
    elif change == "content_type_changed":
        mutated[field_name(mutated, "content-type")] = "application/x-msdownload"
    return mutated


UPLOAD_TAMPERING = ("signature_changed", "signature_removed", "policy_changed", "key_changed",
                    "content_type_changed")


def query_of(url):
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


def get_variants(url):
    """The signed GET with one thing wrong each: signature, key, lifetime, signature dropped."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)

    def rebuild(path=None, edit=None, drop=None):
        kept = [(k, edit[1] if edit and k == edit[0] else v) for k, v in pairs if k != drop]
        return urlunsplit((parts.scheme, parts.netloc, path or parts.path, urlencode(kept), ""))

    query = dict(pairs)
    return {
        "signature_changed": rebuild(edit=("X-Amz-Signature", flip(query["X-Amz-Signature"]))),
        "key_changed": rebuild(path=parts.path + "x"),
        "lifetime_extended": rebuild(edit=("X-Amz-Expires",
                                           str(int(query.get("X-Amz-Expires", "60")) * 10))),
        "signature_removed": rebuild(drop="X-Amz-Signature"),
        "unsigned": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
    }


def ranged(ctx, url):
    return direct(ctx.http, "GET", url, {"range": "bytes=0-1023"}, None, clock=ctx.clock)


def first_reference(body):
    for line in body.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return posixpath.normpath(line) if "://" not in line else None
    return None


def hls_paths(api, job):
    """The master, variant and segment paths as the owner sees them."""
    master_path = job.get("hls_url")
    if not master_path:
        raise ProofError("The finished job has no HLS URL")
    master = api.request("GET", master_path)
    reference = first_reference(master.body) if master.status == 200 else None
    if not reference:
        raise ProofError(f"The owner could not read the master playlist (HTTP {master.status})")
    follow = urljoin(master_path, reference)
    variant = None
    if follow.endswith(".m3u8"):
        variant, listing = follow, api.request("GET", follow)
        inner = first_reference(listing.body) if listing.status == 200 else None
        if not inner:
            raise ProofError("The owner could not read the variant playlist")
        follow = urljoin(variant, inner)
    return {"master": master_path, "variant": variant, "segment": follow}


def segment_url(api, paths):
    """The signed GET Media redirects the owner to for one segment."""
    reply = api.request("GET", paths["segment"])
    location = reply.first("location")
    if reply.status != 307 or not host_of(location).endswith(".amazonaws.com"):
        raise ProofError(f"The segment was not a redirect to storage (HTTP {reply.status})")
    return location


def own_job(api, job_id):
    reply = api.request("GET", f"/api/media/jobs/{job_id}")
    job = reply.json()
    if reply.status != 200 or not isinstance(job, dict) or job.get("status") != "done":
        raise ProofError(f"The owner could not read the finished job (HTTP {reply.status})")
    return job


def setup_ids(proof):
    setup = proof.doc["intents"].get("setup-job", {})
    if not setup.get("job_id") or proof.doc["steps"].get("setup-job", {}).get("status") != PASS:
        raise ProofError("No finished job: run the setup-job step first")
    return setup["job_id"]


def bucket_base(url, bucket):
    """The bucket's own URL, from any URL on the same S3 host (virtual-hosted or path style)."""
    host = host_of(url)
    return f"https://{host}" if host.startswith(f"{bucket}.") else f"https://{host}/{bucket}"


def wait_for(ctx, proof, seconds):
    """Sleep in short steps, re-checking the window: an expiry wait must not outlive it."""
    end = ctx.clock() + seconds
    while (left := end - ctx.clock()) > 0:
        proof.checkpoint("active")
        ctx.sleep(min(15, left))


# ---- setup -----------------------------------------------------------------------------
def setup_job(ctx, proof, fixture, *, timeout, minutes):
    """Register A and B; A uploads the clip through the real direct-to-S3 path; encode it."""
    intent = proof.intent("setup-job")
    api = account(ctx, "a")
    account(ctx, "b")
    row = intent.setdefault("row", {})
    intent.setdefault("tasks", [])
    if not row.get("finalized"):
        row.update(workflow.submit(ctx, api, fixture, row, proof.save))
        row["finalized"] = True
        intent["job_id"] = row["job_id"]
        proof.save()
    try:
        final = isolation.finish_job(ctx, proof, api, intent, gate=timeout, minutes=minutes)
        if not final or final["status"] not in workflow.TERMINAL:
            capacity.stop_ours(ctx, intent["tasks"], "dc2 evidence: security gate passed")
        stopped = workflow.wait_stopped(ctx, intent["tasks"], timeout=600,
                                        checkpoint=proof.checkpoint) if intent["tasks"] else {}
    except BaseException:
        capacity.stop_ours(ctx, intent["tasks"], "dc2 evidence: security step aborted")
        raise
    left = len(workflow.live_tasks(ctx))
    status = final["status"] if final else None
    public = {
        "users_registered": 2, "job_status": status, "bytes": row.get("bytes"),
        "upload_status": row.get("upload_status"), "finalize_status": row.get("finalize_status"),
        "storage_host_is_s3": row.get("storage_host_is_s3"),
        "encoders_started": len(intent["tasks"]), "encoders_left_running": left,
        "encoder_billed_seconds": [tasks.summary(t)["billed_seconds"]
                                   for t in stopped.values()],
    }
    return {"status": PASS if status == "done" and left == 0 else FAIL, "public": public,
            "private": {"job_id": intent["job_id"], "tasks": intent["tasks"]}}


# ---- ownership and authentication -----------------------------------------------------
def cross_owner(ctx, proof):
    job_id = setup_ids(proof)
    a, b = account(ctx, "a"), account(ctx, "b")
    job = own_job(a, job_id)
    pid = job.get("processing_job_id")
    if not pid:
        raise ProofError("The finished job names no Processing job")
    paths = hls_paths(a, job)
    controls = {
        "a_read": ask(ctx, a, "GET", f"/api/media/jobs/{job_id}").status,
        "a_playback": ask(ctx, a, "GET", paths["master"]).status,
        "a_processing_job": ask(ctx, a, "GET", f"/api/processing/jobs/{pid}").status,
    }
    replies = {
        "read": ask(ctx, b, "GET", f"/api/media/jobs/{job_id}"),
        "retry": ask(ctx, b, "POST", f"/api/media/jobs/{job_id}/retry", raw=b""),
        "playback_master": ask(ctx, b, "GET", paths["master"]),
        "playback_segment": ask(ctx, b, "GET", paths["segment"]),
        "processing_job": ask(ctx, b, "GET", f"/api/processing/jobs/{pid}"),
    }
    listing = ask(ctx, b, "GET", "/api/media/jobs")
    by_asset = ask(ctx, b, "GET", f"/api/processing/jobs?asset_ids={job_id}")
    after = ask(ctx, a, "GET", f"/api/media/jobs/{job_id}")
    listed = listing.status == 200 and job_id in listing.body.decode("utf-8", "replace")
    leaked = pid in by_asset.body.decode("utf-8", "replace") or job_id in by_asset.body.decode(
        "utf-8", "replace")
    exposed = any(marker in reply.body for reply in replies.values()
                  for marker in (b"output_url", b"hls_url", b"X-Amz-Signature"))
    unchanged = after.status == 200 and (after.json() or {}).get("status") == "done" and (
        (after.json() or {}).get("processing_job_id") == pid)
    statuses = {f"b_{name}": reply.status for name, reply in replies.items()}
    public = {**statuses, **controls, "b_listing_status": listing.status,
              "b_lists_a_job": listed, "b_processing_by_asset_status": by_asset.status,
              "b_processing_by_asset_leaks": leaked, "b_sees_output_or_playback_urls": exposed,
              "a_job_unchanged_after_b_retry": unchanged}
    ok = (all(s == 404 for s in statuses.values()) and all(s == 200 for s in controls.values())
          and not listed and not leaked and not exposed and unchanged)
    return {"status": PASS if ok else FAIL, "public": public, "private": {"job_id": job_id}}


def forged_tokens(api):
    """Two bad session cookies, built in memory: an unsigned token and A's with a bad signature."""
    name, _, value = api.cookie.split(";")[0].partition("=")
    header = urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    claims = urlsafe_b64encode(b'{"sub":"' + str(uuid.uuid4()).encode() + b'"}').rstrip(
        b"=").decode()
    return {"alg_none": f"{name}={header}.{claims}.", "signature_changed": f"{name}={flip(value)}"}


def unauthenticated(ctx, proof):
    known = proof.doc["intents"].get("setup-job", {}).get("job_id")
    job_id = known or str(uuid.uuid4())
    pid = str(uuid.uuid4())
    routes = (("jobs", "GET", "/api/media/jobs"), ("job", "GET", f"/api/media/jobs/{job_id}"),
              ("retry", "POST", f"/api/media/jobs/{job_id}/retry"),
              ("playback", "GET", f"/api/media/jobs/{job_id}/hls/master.m3u8"),
              ("processing_job", "GET", f"/api/processing/jobs/{pid}"),
              ("reserve", "POST", "/api/media/uploads/reservations"),
              ("finalize", "POST", f"/api/media/uploads/reservations/{uuid.uuid4()}/finalize"),
              ("me", "GET", "/api/media/auth/me"))
    seen = {}
    for origin in ("frontend", "gateway"):
        api = ctx.api(origin)
        for name, method, path in routes:
            reply = ask(ctx, api, method, path, body={} if method == "POST" else None)
            seen[f"{origin}_{name}"] = reply.status
    for variant, cookie in forged_tokens(account(ctx, "a")).items():
        reply = ask(ctx, ctx.api("frontend"), "GET", "/api/media/jobs", headers={"cookie": cookie})
        seen[f"forged_{variant}_jobs"] = reply.status
    # API Gateway answers 401 when the cookie is absent (identity source) but 403 when the Lambda
    # authorizer runs and returns isAuthorized=false for a present-but-invalid token (measured on
    # AWS in r1019a). Both stop the request before the API; a forged token may get nothing else.
    absent = {k: v for k, v in seen.items() if not k.startswith("forged_")}
    forged = {k: v for k, v in seen.items() if k.startswith("forged_")}
    ok = all(s == 401 for s in absent.values()) and all(s in (401, 403) for s in forged.values())
    return {"status": PASS if ok else FAIL,
            "public": {"statuses": seen, "all_401": all(s == 401 for s in seen.values()),
                       "absent_session_all_401": all(s == 401 for s in absent.values()),
                       "forged_token_denied": all(s in (401, 403) for s in forged.values())}}


# ---- signed URLs ---------------------------------------------------------------------
def tampered_urls(ctx, proof):
    job_id = setup_ids(proof)
    a = account(ctx, "a")
    job = own_job(a, job_id)
    paths = hls_paths(a, job)
    public, bad = {}, []
    # An upload grant first: every variant on a fresh reservation (never finalized), then the
    # untouched grant, so a refusal above cannot be a grant that never worked.
    path = probe_file(ctx, "tamper")
    intent = proof.intent("tampered-urls")
    _, grant = grant_for(a, path, intent.setdefault("request_id", str(uuid.uuid4())))
    proof.save()
    content = path.read_bytes()
    for change in UPLOAD_TAMPERING:
        fields = tampered_fields(grant["fields"], change)
        status = post_grant(ctx, grant, fields, path.name, content).status
        public[f"upload_{change}"] = status
        bad.append(rejected(status))
    control = post_grant(ctx, grant, grant["fields"], path.name, content).status
    public["upload_control_status"] = control
    # Then both kinds of signed GET Media hands out.
    targets = {"segment": segment_url(a, paths)}
    if job.get("output_url"):
        targets["mp4"] = job["output_url"]
    for label, url in targets.items():
        for change, variant in get_variants(url).items():
            status = ranged(ctx, variant).status
            public[f"{label}_{change}"] = status
            bad.append(rejected(status))
        public[f"{label}_control_status"] = ranged(ctx, url).status
    controls = [public["upload_control_status"] in workflow.UPLOAD_OK] + [
        public[f"{label}_control_status"] in {200, 206} for label in targets]
    public["all_tampering_rejected"] = all(bad)
    public["all_controls_worked"] = all(controls)
    public["mp4_checked"] = "mp4" in targets
    return {"status": PASS if all(bad) and all(controls) and "mp4" in targets else FAIL,
            "public": public}


def playback_expiry(ctx, proof, *, max_wait):
    job_id = setup_ids(proof)
    a = account(ctx, "a")
    url = segment_url(a, hls_paths(a, own_job(a, job_id)))
    query = query_of(url)
    try:
        lifetime = int(query["X-Amz-Expires"])
        issued = dt.datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=dt.UTC)
    except (KeyError, ValueError):
        raise ProofError("The signed URL does not state its date and lifetime") from None
    left = issued.timestamp() + lifetime - ctx.wall() + EXPIRY_MARGIN
    if left > max_wait:
        return {"status": NOT_RUN, "public": {
            "reason": f"the signed playback URL lives {lifetime} s, more than the {max_wait} s "
                      "this run may wait; pass --max-expiry-wait to test it. Tampering is "
                      "covered by the tampered-urls step",
            "signed_lifetime_seconds": lifetime, "max_wait_seconds": max_wait}}
    control = ranged(ctx, url).status
    wait_for(ctx, proof, left)
    after = ranged(ctx, url).status
    return {"status": PASS if control in {200, 206} and rejected(after) else FAIL, "public": {
        "signed_lifetime_seconds": lifetime, "control_status": control,
        "status_after_expiry": after, "waited_seconds": round(left, 1)}}


def upload_expiry(ctx, proof, *, max_wait):
    intent = proof.intent("upload-url-expiry")
    a = account(ctx, "a")
    path = probe_file(ctx, "expiry")
    data, grant = grant_for(a, path, intent.setdefault("request_id", str(uuid.uuid4())))
    proof.save()
    left = parse_time(data["expires_at"]).timestamp() - ctx.wall() + EXPIRY_MARGIN
    if left > max_wait:
        return {"status": NOT_RUN, "public": {
            "reason": f"an upload grant lives about {round(left - EXPIRY_MARGIN)} s (fixed at "
                      f"15 minutes in Media), more than the {max_wait} s this run may wait; "
                      "pass --max-expiry-wait to test it. Tampering is covered by the "
                      "tampered-urls step",
            "grant_seconds_left": round(left - EXPIRY_MARGIN), "max_wait_seconds": max_wait}}
    content = path.read_bytes()
    control = post_grant(ctx, grant, grant["fields"], path.name, content).status
    wait_for(ctx, proof, left)
    after = post_grant(ctx, grant, grant["fields"], path.name, content).status
    ok = control in workflow.UPLOAD_OK and rejected(after)
    return {"status": PASS if ok else FAIL, "public": {
        "control_status": control, "status_after_expiry": after, "waited_seconds": round(left, 1)}}


# ---- size ------------------------------------------------------------------------------
def finalize(a, reservation_id, request_id):
    return a.request("POST", f"/api/media/uploads/reservations/{reservation_id}/finalize",
                     body={"request_id": request_id})


def refused_oversize_upload(ctx, a, request_id, reserved, sent, name):
    """Reserve `reserved` bytes, send `sent`, then try to finalize: returns what happened."""
    reply = a.request("POST", "/api/media/uploads/reservations", body={
        "request_id": request_id, "filename": f"{name}.mp4", "content_type": CONTENT_TYPE,
        "size_bytes": reserved, "sha256": "0" * 64})
    data = reply.json()
    if reply.status != 201 or not isinstance(data, dict) or not data.get("upload"):
        raise ProofError(f"The in-limit reservation was refused (HTTP {reply.status})")
    grant = data["upload"]
    result = {"reserve_status": reply.status}
    try:
        stored = post_grant(ctx, grant, grant["fields"], f"{name}.mp4", b"\0" * sent,
                            timeout=900).status
        result["storage_status"], result["storage_connection_closed"] = stored, False
    except OSError:  # S3 may close the connection once it has seen too many bytes
        result["storage_status"], result["storage_connection_closed"] = None, True
    done = finalize(a, data["reservation_id"], request_id)
    result["finalize_status"] = done.status
    result["adopted"] = done.status in {200, 201, 202}
    result["storage_stored_bytes"] = result["storage_status"] in workflow.UPLOAD_OK
    return result


def oversized_upload(ctx, proof):
    a = account(ctx, "a")
    intent = proof.intent("oversized-upload")
    refused = a.request("POST", "/api/media/uploads/reservations", body={
        "request_id": intent.setdefault("request_id_over", str(uuid.uuid4())),
        "filename": "oversize.mp4", "content_type": CONTENT_TYPE,
        "size_bytes": MAX_BYTES + 1, "sha256": "0" * 64})
    body = refused.json()
    granted = isinstance(body, dict) and bool(body.get("upload"))
    proof.save()
    size = 1024
    result = refused_oversize_upload(ctx, a, intent.setdefault("request_id_bytes", str(
        uuid.uuid4())), size, 2 * size, "bytes-over-reservation")
    public = {
        "limit_bytes": MAX_BYTES, "reservation_over_limit_status": refused.status,
        "reservation_over_limit_granted_upload": granted,
        "reserved_bytes": size, "sent_bytes": 2 * size,
        "storage_status": result["storage_status"],
        "storage_rejected_oversize": rejected(result["storage_status"]),
        "finalize_status": result["finalize_status"], "adopted": result["adopted"],
        "refused_only_at_finalize": result["storage_stored_bytes"] and not result["adopted"],
    }
    ok = rejected(refused.status) and not granted and not result["adopted"] and (
        rejected(result["storage_status"]) or result["storage_stored_bytes"])
    return {"status": PASS if ok else FAIL, "public": public}


def full_size_limit(ctx, proof, *, enabled):
    if not enabled:
        return {"status": NOT_RUN, "public": {
            "reason": "uploading 100 MiB plus one byte was not requested; pass "
                      "--full-size-limit. The same size condition is exercised at the "
                      "reserved size by oversized-upload",
            "limit_bytes": MAX_BYTES}}
    a = account(ctx, "a")
    intent = proof.intent("oversize-100mib")
    result = refused_oversize_upload(
        ctx, a, intent.setdefault("request_id", str(uuid.uuid4())), MAX_BYTES, MAX_BYTES + 1,
        "limit-plus-one")
    proof.save()
    stopped = rejected(result["storage_status"]) or result["storage_connection_closed"]
    ok = not result["adopted"] and (stopped or result["storage_stored_bytes"])
    return {"status": PASS if ok else FAIL, "public": {
        "limit_bytes": MAX_BYTES, "sent_bytes": MAX_BYTES + 1,
        "storage_status": result["storage_status"],
        "storage_connection_closed": result["storage_connection_closed"],
        "storage_rejected_oversize": stopped, "finalize_status": result["finalize_status"],
        "adopted": result["adopted"],
        "refused_only_at_finalize": result["storage_stored_bytes"] and not result["adopted"]}}


# ---- storage is private --------------------------------------------------------------
def s3_direct_denied(ctx, proof):
    job_id = setup_ids(proof)
    a = account(ctx, "a")
    intent = proof.intent("s3-direct-denied")
    path = probe_file(ctx, "direct")
    _, grant = grant_for(a, path, intent.setdefault("request_id", str(uuid.uuid4())))
    proof.save()
    key = grant["fields"][field_name(grant["fields"], "key")]
    stored = post_grant(ctx, grant, grant["fields"], path.name, path.read_bytes()).status
    source = bucket_base(grant["url"], ctx.outputs["SourceBucketName"])
    segment = segment_url(a, hls_paths(a, own_job(a, job_id)))
    output = bucket_base(segment, ctx.outputs["OutputBucketName"])
    unsigned_segment = urlunsplit(urlsplit(segment)._replace(query=""))
    probes = {
        "source_list": ("GET", f"{source}/?list-type=2"),
        "source_versions": ("GET", f"{source}/?versions"),
        "source_object": ("GET", f"{source}/{key}"),
        "source_put": ("PUT", f"{source}/{key}"),
        "output_list": ("GET", f"{output}/?list-type=2"),
        "output_versions": ("GET", f"{output}/?versions"),
        "output_object": ("GET", unsigned_segment),
    }
    seen = {}
    for name, (method, url) in probes.items():
        body = b"dc2-unsigned" if method == "PUT" else None
        seen[name] = direct(ctx.http, method, url, {}, body, clock=ctx.clock).status
    public = {"statuses": seen, "staged_object_stored": stored in workflow.UPLOAD_OK,
              "all_denied": all(s in DENIED_STORAGE for s in seen.values())}
    ok = public["staged_object_stored"] and public["all_denied"]
    return {"status": PASS if ok else FAIL, "public": public}


# ---- the network edge ----------------------------------------------------------------
def socket_connect(address, port, timeout):
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "closed"
    except TimeoutError:
        return "filtered"
    except OSError:
        return "error"


def socket_resolve(host):
    found = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    return sorted({item[4][0] for item in found})


def edge_hooks(ctx):
    """The simulation answers for itself: a dry run must never open a socket."""
    if ctx.simulated:
        return ctx.world.resolve, ctx.world.connect
    return socket_resolve, socket_connect


def port_scan(ctx):
    host = urlsplit(ctx.frontend_url).hostname
    resolve, connect = edge_hooks(ctx)
    try:
        addresses = resolve(host)[:MAX_ADDRESSES]
    except OSError:
        addresses = []
    if not addresses:
        return {"status": NOT_RUN, "public": {"reason": "the public hostname did not resolve"}}
    jobs = [(address, port) for address in addresses for port in PORTS]
    with ThreadPoolExecutor(max_workers=16) as pool:
        states = list(pool.map(lambda job: connect(job[0], job[1], CONNECT_TIMEOUT), jobs))
    by_port = {port: {s for (_, p), s in zip(jobs, states, strict=True) if p == port}
               for port in PORTS}
    summary = {port: ("open" if "open" in seen else "error" if "error" in seen
                      else "closed" if seen == {"closed"} else "filtered")
               for port, seen in by_port.items()}
    opened = sorted(port for port, state in summary.items() if state == "open")
    try:
        plain = direct(ctx.http, "GET", f"http://{host}/", {}, None, timeout=15, clock=ctx.clock)
        redirect = plain.status in {301, 302, 307, 308} and plain.first("location").startswith(
            "https://")
        plain_status = plain.status
    except OSError:
        redirect, plain_status = False, None
    public = {
        "ports_scanned": list(PORTS), "addresses_scanned": len(addresses),
        "ipv6_scanned": False, "connect_timeout_seconds": CONNECT_TIMEOUT,
        "port_states": {str(p): s for p, s in summary.items()}, "open_ports": opened,
        "only_80_and_443_open": opened == EXPECTED_OPEN,
        "plain_http_status": plain_status, "plain_http_redirects_to_https": redirect,
        "method": "tcp connect, python sockets",
    }
    if "error" in summary.values():
        public["reason"] = "a connect failed in a way that is neither refused nor timed out"
        return {"status": NOT_RUN, "public": public}
    ok = opened == EXPECTED_OPEN and redirect
    return {"status": PASS if ok else FAIL, "public": public}


def execute_api_direct(ctx, proof):
    """The Gateway URL without CloudFront: refused, or reachable with the authorizer in force."""
    gateway = ctx.api("gateway")
    probes = {"health": "/api/media/health", "media_jobs": "/api/media/jobs",
              "processing_jobs": f"/api/processing/jobs?asset_ids={uuid.uuid4()}",
              "admin_jobs": "/api/media/admin/jobs"}
    statuses = {}
    for name, path in probes.items():
        try:
            statuses[name] = ask(ctx, gateway, "GET", path).status
        except OSError:
            statuses[name] = None
    exposed = any(statuses[n] is not None and 200 <= statuses[n] < 300
                  for n in ("media_jobs", "processing_jobs", "admin_jobs"))
    answers = statuses["health"] == 200 or 401 in statuses.values()
    classification = ("anonymous_data_exposed" if exposed else
                      "reachable_authorizer_enforced" if answers else "refused")
    public = {"statuses": statuses, "classification": classification}
    job_id = proof.doc["intents"].get("setup-job", {}).get("job_id")
    if job_id and answers and not exposed:
        a, b = account_on(ctx, "a", "gateway"), account_on(ctx, "b", "gateway")
        public["a_reads_own_job_status"] = ask(ctx, a, "GET", f"/api/media/jobs/{job_id}").status
        public["b_reads_a_job_status"] = ask(ctx, b, "GET", f"/api/media/jobs/{job_id}").status
    ok = classification != "anonymous_data_exposed" and (
        public.get("a_reads_own_job_status", 200) == 200
        and public.get("b_reads_a_job_status", 404) == 404)
    public["note"] = ("The execute-api URL answers without CloudFront; the authorizer is the "
                      "control." if answers else "The execute-api URL refused anonymous calls.")
    return {"status": PASS if ok else FAIL, "public": public}


def account_on(ctx, label, origin):
    """The same user as account(), signed in through another origin."""
    return sign_in(ctx, ctx.api(origin), label, derived(ctx, label))


# ---- driver ----------------------------------------------------------------------------
def run(ctx, *, fixture, job_timeout=900, minutes=45, only=None, max_expiry_wait=EXPIRY_WAIT,
        full_size=False):
    if ctx.fresh and (ctx.fresh is True or "setup-job" in ctx.fresh):
        raise ProofError("--fresh would start a second encoder job: name the steps to repeat "
                         "with --only and leave setup-job out")
    proof = ctx.proof(ISSUE, REQUIRED)
    plan = {
        "setup-job": ("open", lambda i: setup_job(
            ctx, proof, fixture, timeout=job_timeout, minutes=minutes)),
        "cross-owner": ("active", lambda i: cross_owner(ctx, proof)),
        "unauthenticated": ("active", lambda i: unauthenticated(ctx, proof)),
        "tampered-urls": ("active", lambda i: tampered_urls(ctx, proof)),
        "oversized-upload": ("active", lambda i: oversized_upload(ctx, proof)),
        "oversize-100mib": ("active", lambda i: full_size_limit(ctx, proof, enabled=full_size)),
        "s3-direct-denied": ("active", lambda i: s3_direct_denied(ctx, proof)),
        "playback-url-expiry": ("active", lambda i: playback_expiry(
            ctx, proof, max_wait=max_expiry_wait)),
        "upload-url-expiry": ("active", lambda i: upload_expiry(
            ctx, proof, max_wait=max_expiry_wait)),
        "port-scan": (None, lambda i: port_scan(ctx)),
        "execute-api-direct": ("active", lambda i: execute_api_direct(ctx, proof)),
    }
    for name, (kind, action) in plan.items():
        if only and name not in only:
            continue
        passed = proof.doc["steps"].get("setup-job", {}).get("status") == PASS
        if name in NEEDS_JOB and not passed and name != "setup-job":
            continue  # nothing to test without the finished job; the receipt stays INCOMPLETE
        proof.step(name, action, session=kind)
    return proof
