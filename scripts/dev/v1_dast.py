"""Run a bounded authenticated ZAP scan against the disposable V1 gateway harness.

The API handlers, Media authorizer, TLS wrapper, real PostgreSQL and fixture acceptance
helpers come from the existing V1 local harness. S3/SQS remain run-scoped Moto emulation.
This is local handler evidence, not AWS API Gateway, IAM, CloudFront or S3 evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from scripts.aws.artifacts import scan_disposition
from scripts.dev.v1_gateway import Gateway
from scripts.dev.v1_runtime import ROOT
from scripts.dev.v1_runtime import down as runtime_down

SERVICES = ("media", "processing")
EXPECTED_OPERATIONS = {"media": 15, "processing": 5}
REQUEST_CAP = 300
MAX_FIXTURE_USERS = 2
MAX_FIXTURE_UPLOADS = 2
MAX_WORKER_INVOCATIONS = 0
ZAP_TIMEOUT_SECONDS = 300
ZAP_MAX_SCAN_MINUTES = 2
ZAP_MAX_RULE_MINUTES = 1
ZAP_THREADS_PER_HOST = 2
ZAP_IMAGE = (
    "ghcr.io/zaproxy/zaproxy:stable@sha256:"
    "781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
)
BLOCKING_PLUGIN_IDS = frozenset({"6", "40018", "90020"})
METHODS = frozenset({"get", "head", "options", "post", "put", "patch", "delete"})


def operation_rows(specs):
    """Return the full documented API inventory with an explicit scan decision per operation."""
    rows = []
    for service in SERVICES:
        spec = specs[service]
        for path, path_item in spec.get("paths", {}).items():
            for method, operation in path_item.items():
                if method.lower() not in METHODS:
                    continue
                method = method.upper()
                reason = exclusion_reason(service, method, path)
                rows.append(
                    {
                        "service": service,
                        "method": method,
                        "route": path,
                        "operation_id": operation.get("operationId", ""),
                        "scan": "excluded" if reason else "imported",
                        **({"reason": reason} if reason else {}),
                    }
                )
        count = sum(row["service"] == service for row in rows)
        if count != EXPECTED_OPERATIONS[service]:
            raise ValueError(f"{service} OpenAPI operation inventory changed; review DAST scope")
    return sorted(rows, key=lambda row: (row["service"], row["route"], row["method"]))


def exclusion_reason(service, method, path):
    """Keep non-read operations and routes with privileged or signed-output behavior out."""
    if "/admin/" in path:
        return "Operator-only route; the DAST actor has a normal user role."
    if service == "media" and path.startswith("/api/media/auth/") and method == "POST":
        return "Account/session lifecycle; seeded owner sessions are tested outside ZAP."
    if service == "media" and path.startswith("/api/media/uploads/"):
        return "Creates signed upload grants or adopts objects; seeded uploads cover this flow."
    if "/hls/" in path:
        return "May return a signed object-store URL; keep the cookie inside the API origin."
    if method not in {"GET", "HEAD", "OPTIONS"}:
        return "State-changing operation; owner denial is checked on disposable fixtures."
    return None


def loopback_base(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DAST target must be the exact HTTPS loopback gateway origin")
    return f"https://127.0.0.1:{parsed.port}"


def current_specs():
    """Regenerate each schema from its app and reject stale committed OpenAPI documents."""
    from scripts.dev import openapi

    specs, hashes = {}, {}
    for service in SERVICES:
        rendered = openapi.render(service)
        committed = openapi.path_of(service).read_text()
        if rendered != committed:
            raise ValueError(f"Committed {service} OpenAPI document is stale")
        specs[service] = json.loads(rendered)
        hashes[service] = hashlib.sha256(rendered.encode()).hexdigest()
    return specs, hashes


def scan_document(service, spec, base_url, fixtures):
    """Build a private read-only scan contract from one generated owner schema."""
    base_url = loopback_base(base_url)
    selected = {}
    for path, path_item in spec.get("paths", {}).items():
        for method, source_operation in path_item.items():
            if method.lower() not in METHODS or exclusion_reason(service, method.upper(), path):
                continue
            operation = copy.deepcopy(source_operation)
            for parameter in operation.get("parameters", []):
                name = parameter.get("name")
                if name == "job_id":
                    parameter["example"] = fixtures[
                        "media_job" if service == "media" else "processing_job"
                    ]
                elif name == "asset_ids" and service == "processing":
                    parameter["example"] = fixtures["media_job"]
            selected.setdefault(path, {})[method.lower()] = operation
    if not selected:
        raise ValueError(f"No reviewed {service} routes selected for ZAP")
    scan = {
        key: copy.deepcopy(value) for key, value in spec.items() if key not in {"paths", "servers"}
    }
    scan["servers"] = [{"url": base_url}]
    scan["paths"] = selected
    return scan


def context_xml(port):
    """Limit ZAP to this run's two API prefixes and exclude risky URL families."""
    root = ET.Element("configuration")
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = "FlickPond V1 local DAST"
    ET.SubElement(context, "desc")
    ET.SubElement(context, "inscope").text = "true"
    origin = rf"https://127\.0\.0\.1:{port}"
    ET.SubElement(context, "incregexes").text = origin + r"/api/(?:media|processing)(?:/.*)?"
    for suffix in (
        r"/api/media/admin(?:/.*)?",
        r"/api/media/auth/(?:register|login|logout)(?:/.*)?",
        r"/api/media/uploads(?:/.*)?",
        r"/api/media/jobs/[^/]+/(?:edit|retry|hls)(?:/.*)?",
        r"/api/processing/jobs/[^/]+/retry(?:/.*)?",
    ):
        ET.SubElement(context, "excregexes").text = origin + suffix
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode()


def zap_options(port, cookie):
    """Restrict the native cookie replacer to this local API origin and path."""
    if not cookie.startswith("access_token=") or "\n" in cookie or "\r" in cookie:
        raise ValueError("Expected one private access-token cookie")
    scope = rf"^https://127\.0\.0\.1:{port}/api/(?:media|processing)(?:/.*)?$"
    return "\n".join(
        (
            "replacer.full_list(0).description=local-v1-session",
            "replacer.full_list(0).enabled=true",
            "replacer.full_list(0).matchtype=REQ_HEADER",
            "replacer.full_list(0).matchstr=Cookie",
            "replacer.full_list(0).regex=false",
            "replacer.full_list(0).replacement=" + cookie,
            "replacer.full_list(0).url=" + scope,
            "scanner.threadPerHost=" + str(ZAP_THREADS_PER_HOST),
            "scanner.maxScanDurationInMins=" + str(ZAP_MAX_SCAN_MINUTES),
            "scanner.maxRuleDurationInMins=" + str(ZAP_MAX_RULE_MINUTES),
            "",
        )
    )


def _path_pattern(template):
    parts = re.split(r"(\{[^{}]+\})", template)
    return (
        "^"
        + "".join(
            ".*" if part == "{path}" else "[^/]+" if part.startswith("{") else re.escape(part)
            for part in parts
        )
        + "$"
    )


def match_operation(routes, method, path):
    for row in routes:
        if row["method"] == method.upper() and re.fullmatch(
            _path_pattern(row["route"])[1:-1], path
        ):
            return row
    return None


class DastGateway(Gateway):
    """Existing real-handler bridge with a scan-only forwarded-request ceiling."""

    routes = ()

    def __init__(self, *args):
        super().__init__(*args)
        self._lock = threading.Lock()
        self._scan_active = False
        self._request_cap = 0
        self._requests_seen = 0
        self._requests_forwarded = 0
        self._cap_exceeded = False
        self._blocked_requests = 0
        self._coverage = Counter()
        self._unmatched = 0

    def begin_scan(self, request_cap=REQUEST_CAP):
        with self._lock:
            self._scan_active = True
            self._request_cap = request_cap
            self._requests_seen = self._requests_forwarded = self._unmatched = 0
            self._cap_exceeded = False
            self._blocked_requests = 0
            self._coverage.clear()

    def end_scan(self):
        with self._lock:
            self._scan_active = False

    def invoke(self, method, target, headers, body=b""):
        parsed = urlsplit(target)
        route = match_operation(self.routes, method, parsed.path)
        with self._lock:
            scanning = self._scan_active
            if scanning:
                self._requests_seen += 1
                if route is None:
                    self._unmatched += 1
                if (
                    route is None
                    or route["scan"] != "imported"
                    or method.upper() not in {"GET", "HEAD", "OPTIONS"}
                ):
                    self._blocked_requests += 1
                    return {
                        "statusCode": 405,
                        "body": '{"detail":"out-of-scope local DAST request"}',
                    }
                if self._requests_forwarded >= self._request_cap:
                    self._cap_exceeded = True
                    if route:
                        key = (route["service"], route["method"], route["route"], "429")
                        self._coverage[key] += 1
                    return {"statusCode": 429, "body": '{"detail":"local DAST request cap"}'}
                self._requests_forwarded += 1
        try:
            reply = super().invoke(method, target, headers, body)
        except Exception:
            if scanning and route:
                with self._lock:
                    self._coverage[(route["service"], route["method"], route["route"], "5xx")] += 1
            raise
        if scanning and route:
            status = int(reply.get("statusCode", 502))
            family = f"{status // 100}xx"
            with self._lock:
                self._coverage[(route["service"], route["method"], route["route"], family)] += 1
        return reply

    def scan_evidence(self):
        with self._lock:
            coverage = [
                {
                    "service": row["service"],
                    "method": row["method"],
                    "route": row["route"],
                    "operation_id": row["operation_id"],
                    "responses": {
                        family: sum(
                            count
                            for (service, method, route, response), count in self._coverage.items()
                            if (service, method, route)
                            == (
                                row["service"],
                                row["method"],
                                row["route"],
                            )
                            and response == family
                        )
                        for family in ("2xx", "3xx", "4xx", "5xx", "429")
                    },
                }
                for row in self.routes
                if row["scan"] == "imported"
            ]
            return {
                "request_cap": self._request_cap,
                "requests_seen": self._requests_seen,
                "requests_forwarded": self._requests_forwarded,
                "cap_exceeded": self._cap_exceeded,
                "blocked_out_of_scope_requests": self._blocked_requests,
                "unmatched_requests": self._unmatched,
                "routes": coverage,
            }


def sanitized_findings(reports):
    """Retain alert identity/severity only; never persist sites, paths, parameters or evidence."""
    output = []
    for service, report in reports:
        for site in report.get("site", []):
            for alert in site.get("alerts", []):
                plugin_id = str(alert.get("pluginid", ""))
                risk = str(alert.get("riskcode", ""))
                confidence = str(alert.get("confidence", "")).strip().casefold()
                try:
                    count = max(0, min(int(alert.get("count", 0)), 100000))
                except (TypeError, ValueError):
                    count = 0
                blocked = (
                    plugin_id in BLOCKING_PLUGIN_IDS
                    and risk == "3"
                    and confidence in {"3", "4", "high", "confirmed"}
                )
                output.append(
                    {
                        "service": service,
                        "plugin_id": plugin_id if plugin_id.isdigit() else "unknown",
                        "risk_code": risk if risk in {"0", "1", "2", "3"} else "unknown",
                        "confidence": confidence
                        if confidence
                        in {
                            "0",
                            "1",
                            "2",
                            "3",
                            "4",
                            "low",
                            "medium",
                            "high",
                            "confirmed",
                            "false positive",
                        }
                        else "unknown",
                        "count": count,
                        "blocking": blocked,
                    }
                )
    return output


def _run_zap(private, ca_file, schema_file, timeout=ZAP_TIMEOUT_SECONDS):
    script = r"""cp "$JAVA_HOME/lib/security/cacerts" /tmp/dast-trust || exit 3
keytool -importcert -noprompt -alias flickpond-v1-dast -file /tmp/dast-ca.crt \
  -keystore /tmp/dast-trust -storepass changeit >/dev/null 2>&1 || exit 3
export _JAVA_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/dast-trust \\
  -Djavax.net.ssl.trustStorePassword=changeit -Duser.home=/tmp"
zap-api-scan.py -t "$DAST_SCHEMA" -f openapi -J "/zap/wrk/$DAST_REPORT" -T 2 \
  -n /zap/wrk/dast.context -I \
  -z "-configfile /zap/wrk/zap.options"
"""
    report_name = schema_file.stem.replace(".", "-") + "-raw.json"
    cid_file = private / (schema_file.stem + ".container-id")
    cid_file.unlink(missing_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--cidfile",
        f"/zap/wrk/{cid_file.name}",
        "--init",
        "--network",
        "host",
        "--cpus=2",
        "--memory=2g",
        "--pids-limit=128",
        "--stop-timeout=10",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--workdir",
        "/zap/wrk",
        "--env",
        "HOME=/tmp",
        "--env",
        "DAST_SCHEMA=/zap/wrk/" + schema_file.name,
        "--env",
        "DAST_REPORT=" + report_name,
        "--volume",
        f"{private}:/zap/wrk:rw",
        "--volume",
        f"{ca_file}:/tmp/dast-ca.crt:ro",
        "--entrypoint",
        "sh",
        ZAP_IMAGE,
        "-c",
        script,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as error:
        (private / (schema_file.stem + "-scanner-private.log")).write_text(
            "ZAP exceeded the explicit per-schema timeout.\n"
        )
        if cid_file.is_file():
            container_id = cid_file.read_text().strip()
            if re.fullmatch(r"[0-9a-f]{12,64}", container_id):
                for command in (
                    ["docker", "stop", "--time", "5", container_id],
                    ["docker", "rm", "-f", container_id],
                ):
                    subprocess.run(command, capture_output=True, timeout=12, check=False)
        raise RuntimeError("ZAP timed out") from error
    (private / (schema_file.stem + "-scanner-private.log")).write_text(
        (result.stdout + "\n" + result.stderr)[-200000:]
    )
    raw = private / report_name
    if result.returncode not in {0, 1, 2}:
        raise RuntimeError(f"ZAP execution failed with exit {result.returncode}")
    if not raw.is_file():
        raise RuntimeError("ZAP completed without a JSON report")
    try:
        report = json.loads(raw.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("ZAP JSON report is unreadable") from error
    return result.returncode, report


def _client(url, ca_file, *, cookie=None):
    import httpx

    trust = __import__("ssl").create_default_context(cafile=str(ca_file))
    return httpx.Client(
        base_url=url.rstrip("/") + "/",
        verify=trust,
        timeout=5,
        trust_env=False,
        cookies={"access_token": cookie} if cookie else None,
        follow_redirects=False,
    )


@contextlib.contextmanager
def _seed_and_verify(runtime, private, specs, rows):
    import jwt

    from publisher.client import PublicClient
    from scripts.dev.v1_acceptance import app_runtime, pump, short_video

    with app_runtime(runtime["data"]["run_id"], gateway=DastGateway) as local:
        DastGateway.routes = tuple(rows)
        media_base = local["url"] + "/api/media"
        a = PublicClient(media_base, private / "owner-a.cookies", ca_file=local["ca"], timeout=5)
        b = PublicClient(media_base, private / "owner-b.cookies", ca_file=local["ca"], timeout=5)
        proc_a = _client(local["url"], local["ca"], cookie="")
        proc_b = _client(local["url"], local["ca"], cookie="")
        source = private / "fixture.mp4"
        try:
            owner_a = a.authenticate(
                "register", f"dast-a-{uuid.uuid4().hex}@example.com", "local-dast-pass-a"
            )
            owner_b = b.authenticate(
                "register", f"dast-b-{uuid.uuid4().hex}@example.com", "local-dast-pass-b"
            )
            if a.identity() != owner_a["id"] or b.identity() != owner_b["id"]:
                raise AssertionError("Owner login did not resolve to its registered identity")
            short_video(source, seconds=1, size="160x90")
            asset_a = a.upload(source, str(uuid.uuid4()))
            asset_b = b.upload(source, str(uuid.uuid4()))
            if len({owner_a["id"], owner_b["id"], asset_a, asset_b}) != 4:
                raise AssertionError("Fixture owners/assets are not distinct")
            pump(local, results=False)
            proc_a.cookies.set("access_token", a.http.cookies.get("access_token"))
            proc_b.cookies.set("access_token", b.http.cookies.get("access_token"))
            jobs_a = proc_a.get("/api/processing/jobs", params={"asset_ids": asset_a})
            jobs_b = proc_b.get("/api/processing/jobs", params={"asset_ids": asset_b})
            if jobs_a.status_code != 200 or jobs_b.status_code != 200:
                raise AssertionError("Owner processing list read failed")
            processing_a = jobs_a.json()[0]["job_id"]
            processing_b = jobs_b.json()[0]["job_id"]

            own_media = a.http.get(f"jobs/{asset_a}")
            own_processing = proc_a.get(f"/api/processing/jobs/{processing_a}")
            own_processing_b = proc_b.get(f"/api/processing/jobs/{processing_b}")
            cross_media = b.http.get(f"jobs/{asset_a}")
            forged_media = b.http.get(
                f"jobs/{asset_a}",
                headers={"X-Owner-Id": owner_a["id"], "X-Role": "operator"},
            )
            cross_processing = proc_b.get(f"/api/processing/jobs/{processing_a}")
            cross_media_mutation = b.http.delete(f"jobs/{asset_a}")
            cross_processing_mutation = proc_b.delete(f"/api/processing/jobs/{processing_a}")
            stable_media = a.http.get(f"jobs/{asset_a}")
            stable_processing = proc_a.get(f"/api/processing/jobs/{processing_a}")
            if not (
                own_media.status_code
                == own_processing.status_code
                == own_processing_b.status_code
                == 200
                and cross_media.status_code == forged_media.status_code == 404
                and cross_processing.status_code == 404
                and cross_media_mutation.status_code == cross_processing_mutation.status_code == 404
                and stable_media.status_code == stable_processing.status_code == 200
                and own_media.json() == stable_media.json()
                and own_processing.json() == stable_processing.json()
            ):
                raise AssertionError("Owner isolation or cross-owner mutation denial failed")

            no_cookie = _client(local["url"], local["ca"])
            try:
                missing_identity = no_cookie.get("/api/media/auth/me").status_code
            finally:
                no_cookie.close()
            now = int(time.time())
            expired_token = jwt.encode(
                {"sub": owner_a["id"], "iat": now - 120, "exp": now - 60},
                "local-v1-emulator-jwt-key-never-deploy",
                algorithm="HS256",
            )
            expired = _client(local["url"], local["ca"], cookie=expired_token)
            try:
                expired_identity = expired.get("/api/media/auth/me").status_code
            finally:
                expired.close()
            if missing_identity != 401 or expired_identity != 401:
                raise AssertionError("Missing or expired session was not denied")

            base = loopback_base(local["url"])
            fixtures = {
                "media_job": asset_a,
                "processing_job": processing_a,
                "other_media_job": asset_b,
                "other_processing_job": processing_b,
            }
            scans = {
                service: scan_document(service, specs[service], base, fixtures)
                for service in SERVICES
            }
            scan_hashes = {
                service: hashlib.sha256(
                    json.dumps(scans[service], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                for service in SERVICES
            }
            for service, document in scans.items():
                (private / f"{service}.openapi.json").write_text(
                    json.dumps(document, sort_keys=True)
                )
            port = urlsplit(base).port
            (private / "dast.context").write_text(context_xml(port))
            (private / "zap.options").write_text(
                zap_options(port, "access_token=" + a.http.cookies.get("access_token"))
            )
            (private / "zap.options").chmod(0o600)

            proof = {
                "owner_a_self_media": "PASS",
                "owner_b_self_media": "PASS",
                "owner_a_self_processing": "PASS",
                "owner_b_self_processing": "PASS",
                "cross_owner_media_read": "DENIED_404",
                "forged_owner_header": "DENIED_404",
                "cross_owner_processing_read": "DENIED_404",
                "cross_owner_media_delete": "DENIED_404_RESOURCE_UNCHANGED",
                "cross_owner_processing_cancel": "DENIED_404_RESOURCE_UNCHANGED",
                "missing_session": "DENIED_401",
                "expired_session": "DENIED_401",
                "fixture_users": MAX_FIXTURE_USERS,
                "fixture_uploads": MAX_FIXTURE_UPLOADS,
                "worker_invocations": 0,
            }
            yield {
                "local": local,
                "clients": (a, b),
                "proc_clients": (proc_a, proc_b),
                "fixtures": fixtures,
                "proof": proof,
                "owner_a_id": owner_a["id"],
                "scan_hashes": scan_hashes,
            }
        finally:
            a.close()
            b.close()
            proc_a.close()
            proc_b.close()


def _validate_coverage(gateway, rows):
    evidence = gateway.scan_evidence()
    by_key = {(row["service"], row["method"], row["route"]): row for row in evidence["routes"]}
    missing = []
    for operation in rows:
        if operation["scan"] != "imported":
            continue
        route = by_key.get((operation["service"], operation["method"], operation["route"]), {})
        responses = route.get("responses", {})
        if not responses.get("2xx"):
            missing.append(operation["operation_id"])
    if evidence["cap_exceeded"]:
        raise RuntimeError("ZAP reached the local forwarded-request cap")
    if evidence["blocked_out_of_scope_requests"]:
        raise RuntimeError("ZAP attempted an excluded route or a write method")
    if missing:
        raise RuntimeError(
            "ZAP did not exercise reviewed routes successfully: " + ",".join(missing)
        )
    return evidence


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def validate_run_id(run_id):
    if len(run_id) > 48 or not re.fullmatch(r"dast-[a-z0-9]+(?:-[a-z0-9]+)*", run_id):
        raise ValueError("Choose a unique DAST run ID using lowercase letters, digits and hyphens")


def run_scan(run_id, output):
    from scripts.dev.v1_runtime import load

    validate_run_id(run_id)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = ROOT / ".cache/v1-dast" / run_id
    if private.exists():
        raise ValueError("Refusing to reuse a DAST private directory; select a fresh run ID")
    private.mkdir(parents=True, mode=0o700)
    rows = []
    disposition = {
        "engine": "zap",
        "disposition": "error",
        "target": "isolated-v1-local-gateway",
        "scope": "Generated Media and Processing V1 APIs; authenticated normal owner; local only.",
        "report_retained": False,
        "policy": "bounded-high-confidence-findings-block; other alerts are reviewable",
        "source_sha": os.environ.get("GITHUB_SHA", "local"),
        "cloud_scan": "NOT_RUN",
        "harness": "scripts.dev.v1_acceptance.app_runtime + scripts.dev.v1_gateway.Gateway",
        "runtime": "real PostgreSQL; Moto S3/SQS; actual V1 Lambda handlers and Media authorizer",
        "worker_cap": MAX_WORKER_INVOCATIONS,
        "request_cap": REQUEST_CAP,
        "cleanup": "PENDING",
    }
    findings = []
    exit_codes = {}
    runtime = load(run_id)
    if runtime["state"] != "running":
        raise ValueError("Start the exact unique V1 runtime before local DAST")
    clients = proc_clients = None
    local = None
    gateway = None
    try:
        specs, schema_hashes = current_specs()
        rows = operation_rows(specs)
        DastGateway.routes = tuple(rows)
        disposition.update(
            source_sha=os.environ.get("GITHUB_SHA")
            or subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=5
            ).strip(),
            schema_operation_counts=EXPECTED_OPERATIONS,
            schema_hashes=schema_hashes,
            operation_inventory=rows,
            zap_image=ZAP_IMAGE,
            active_scan_limits={
                "max_scan_minutes_per_service": ZAP_MAX_SCAN_MINUTES,
                "max_rule_minutes": ZAP_MAX_RULE_MINUTES,
                "threads_per_host": ZAP_THREADS_PER_HOST,
                "timeout_seconds_per_service": ZAP_TIMEOUT_SECONDS,
                "max_forwarded_requests_total": REQUEST_CAP,
                "max_worker_invocations": MAX_WORKER_INVOCATIONS,
            },
        )
        with _seed_and_verify({"data": runtime}, private, specs, rows) as seeded:
            local = seeded["local"]
            clients = seeded["clients"]
            proc_clients = seeded["proc_clients"]
            gateway = local["gateway"]
            disposition.update(
                scan_schema_hashes=seeded["scan_hashes"],
                auth_proof=seeded["proof"],
            )
            gateway.begin_scan(REQUEST_CAP)
            for service in SERVICES:
                schema = private / f"{service}.openapi.json"
                code, report = _run_zap(private, Path(local["ca"]), schema)
                exit_codes[service] = code
                findings.extend(sanitized_findings([(service, report)]))
                disposition["report_retained"] = True
            gateway.end_scan()
            route_evidence = _validate_coverage(gateway, rows)
            if clients[0].identity() != seeded["owner_a_id"]:
                raise RuntimeError("Authenticated session did not remain valid after scanning")
            asset_a = seeded["fixtures"]["media_job"]
            processing_a = seeded["fixtures"]["processing_job"]
            after_media = clients[0].http.get(f"jobs/{asset_a}")
            after_processing = proc_clients[0].get(f"/api/processing/jobs/{processing_a}")
            if after_media.status_code != 200 or after_processing.status_code != 200:
                raise RuntimeError("Seeded owner resources changed or auth expired during the scan")
            if local["observations"]["storage_cookie_headers"]:
                raise RuntimeError("A session cookie reached the local object-storage proxy")
            blocking = [item for item in findings if item["blocking"]]
            disposition.update(
                disposition="executed",
                exit_codes=exit_codes,
                findings_count=len(findings),
                blocking_findings=len(blocking),
                route_coverage=route_evidence,
                storage_cookie_forwarded=False,
                worker_invocations=0,
                report_retained=True,
                finding_gate="FAIL" if blocking else "PASS",
            )
    except Exception as error:
        if gateway:
            gateway.end_scan()
            disposition["route_coverage"] = gateway.scan_evidence()
        disposition.update(
            disposition="error",
            error_type=type(error).__name__,
            exit_codes=exit_codes,
        )
    finally:
        shutil.rmtree(private, ignore_errors=True)
        disposition["private_raw_cleanup"] = "PASS" if not private.exists() else "FAIL"
        try:
            disposition = scan_disposition(
                "zap",
                outcome=disposition["disposition"],
                target=disposition["target"],
                scope=disposition["scope"],
                report_retained=bool(disposition.get("report_retained")),
            ) | {
                key: value
                for key, value in disposition.items()
                if key not in {"engine", "target", "scope", "report_retained", "policy"}
            }
            disposition["policy"] = "High risk + high confidence for ZAP IDs 6, 40018, 90020 block"
        except Exception:
            pass
        _write_json(output / "scan-disposition.json", disposition)
        _write_json(output / "sanitized-findings.json", findings)
    success = (
        disposition.get("disposition") == "executed"
        and disposition.get("finding_gate") == "PASS"
        and disposition.get("private_raw_cleanup") == "PASS"
    )
    exercised = sum(
        bool(route.get("responses") and any(route["responses"].values()))
        for route in disposition.get("route_coverage", {}).get("routes", [])
    )
    print(
        "DAST disposition="
        + str(disposition.get("disposition"))
        + f" routes={exercised}"
        + f" findings={len(findings)} blocking={disposition.get('blocking_findings', 0)}"
    )
    return 0 if success else 1


def cleanup_runtime(run_id, output):
    """Tear down only the matching run, delete its owned volume and private runtime files."""
    validate_run_id(run_id)
    output = Path(output).resolve()
    runtime_dir = ROOT / ".cache/v1-runtime" / run_id
    state = runtime_dir / "runtime.json"
    private = ROOT / ".cache/v1-dast" / run_id
    result = "NOT_STARTED"
    error_type = None
    try:
        if state.exists():
            loaded = json.loads(state.read_text())
            if loaded.get("run_id") != run_id or loaded.get("root") != str(ROOT):
                raise ValueError("Runtime ownership mismatch; refusing cleanup")
            runtime_down(run_id, delete_data=True)
            shutil.rmtree(runtime_dir)
            result = "PASS"
    except Exception as error:
        result, error_type = "FAIL", type(error).__name__
    shutil.rmtree(private, ignore_errors=True)
    private_cleaned = not private.exists()
    disposition_path = Path(output).resolve() / "scan-disposition.json"
    if disposition_path.exists():
        data = json.loads(disposition_path.read_text())
        data["cleanup"] = result
        data["private_raw_cleanup"] = "PASS" if private_cleaned else "FAIL"
        if error_type:
            data["cleanup_error_type"] = error_type
        _write_json(disposition_path, data)
    print(
        "DAST local runtime cleanup="
        + result
        + " private files="
        + ("PASS" if private_cleaned else "FAIL")
    )
    return 1 if result == "FAIL" or not private_cleaned else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--run-id", required=True)
    scan.add_argument("--output", required=True, type=Path)
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--run-id", required=True)
    cleanup.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "scan":
        return run_scan(args.run_id, args.output)
    return cleanup_runtime(args.run_id, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
