"""Run a bounded authenticated ZAP scan against the disposable V1 gateway harness.

This exercises local V1 handlers, authorizer logic, PostgreSQL and Moto-backed storage.
It provides no evidence about deployed AWS API Gateway, IAM, CloudFront or S3.
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
import ssl
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from scripts.aws.artifacts import scan_disposition
from scripts.dev.v1_gateway import Gateway
from scripts.dev.v1_runtime import ROOT, load
from scripts.dev.v1_runtime import down as runtime_down

SERVICES = ("media", "processing")
EXPECTED_OPERATIONS = {"media": 15, "processing": 5}
SCAN_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REQUEST_CAP = 1600
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
METHODS = frozenset({"get", "head", "options", "post", "put", "patch", "delete"})


def exclusion_reason(service, method, path):
    """Explain why an inventory operation is not in the active scan document."""
    if "/admin/" in path:
        return "Operator-only route; fixtures use normal user roles."
    if service == "media" and path.startswith("/api/media/auth/") and method == "POST":
        return "Account/session lifecycle; missing and expired sessions are checked directly."
    if service == "media" and path.startswith("/api/media/uploads/"):
        return "Creates upload grants or adopts objects; seeded uploads cover this flow."
    if "/hls/" in path:
        return "May return signed storage URLs; keep the session cookie at the API origin."
    if method not in SCAN_METHODS:
        return "State-changing operation; disposable fixtures check owner denial directly."
    return None


def operation_rows(specs):
    """Inventory every generated operation and mark the reviewed active-scan subset."""
    rows = []
    for service in SERVICES:
        for path, path_item in specs[service].get("paths", {}).items():
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
        if sum(row["service"] == service for row in rows) != EXPECTED_OPERATIONS[service]:
            raise ValueError(f"{service} OpenAPI inventory changed; review the DAST scope")
    return sorted(rows, key=lambda row: (row["service"], row["route"], row["method"]))


def local_origin(url):
    parsed = urlsplit(url)
    hosts = {"127.0.0.1"} | ({"postgres"} if sys.platform == "darwin" else set())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DAST origin must be HTTPS loopback or its Docker Desktop host alias")
    return f"https://{parsed.hostname}:{parsed.port}"


def scanner_base(url):
    base = local_origin(url)
    return base.replace("127.0.0.1", "postgres") if sys.platform == "darwin" else base


def current_specs():
    """Regenerate app schemas and refuse stale committed OpenAPI documents."""
    from scripts.dev import openapi

    specs, hashes = {}, {}
    for service in SERVICES:
        rendered = openapi.render(service)
        if rendered != openapi.path_of(service).read_text():
            raise ValueError(f"Committed {service} OpenAPI document is stale")
        specs[service] = json.loads(rendered)
        hashes[service] = hashlib.sha256(rendered.encode()).hexdigest()
    return specs, hashes


def scan_document(service, spec, base_url, fixtures, rows):
    """Copy only reviewed read operations into a private, fixture-addressed schema."""
    base_url = local_origin(base_url)
    document = copy.deepcopy(spec)
    paths = {}
    for row in rows:
        if row["service"] != service or row["scan"] != "imported":
            continue
        method = row["method"].lower()
        operation = document["paths"][row["route"]][method]
        for parameter in operation.get("parameters", []):
            name = parameter.get("name")
            if name == "job_id":
                parameter["example"] = fixtures[
                    "media_job" if service == "media" else "processing_job"
                ]
            elif name == "asset_ids" and service == "processing":
                parameter["example"] = fixtures["media_job"]
        paths.setdefault(row["route"], {})[method] = operation
    if not paths:
        raise ValueError(f"No reviewed {service} routes selected for ZAP")
    document["servers"] = [{"url": base_url}]
    document["paths"] = paths
    return document


def context_xml(port, host="127.0.0.1"):
    """Keep ZAP on the local origin; the gateway refuses every excluded operation."""
    root = ET.Element("configuration")
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = "FlickPond V1 local DAST"
    ET.SubElement(context, "inscope").text = "true"
    origin = rf"https://{re.escape(host)}:{port}"
    ET.SubElement(context, "incregexes").text = "^" + origin + r"(?:/.*)?$"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode()


def zap_options(port, cookie, host="127.0.0.1"):
    """Apply the owner cookie only to the two local API prefixes."""
    if (
        not cookie.startswith("access_token=")
        or not cookie.removeprefix("access_token=")
        or any(char in cookie for char in "\r\n;")
    ):
        raise ValueError("Expected one private access-token cookie")
    scope = rf"^https://{re.escape(host)}:{port}/api/(?:media|processing)(?:/.*)?$"
    return "\n".join(
        (
            "replacer.full_list(0).description=local-v1-session",
            "replacer.full_list(0).enabled=true",
            "replacer.full_list(0).matchtype=REQ_HEADER",
            "replacer.full_list(0).matchstr=Cookie",
            "replacer.full_list(0).regex=false",
            "replacer.full_list(0).replacement=" + cookie,
            "replacer.full_list(0).url=" + scope,
            f"scanner.threadPerHost={ZAP_THREADS_PER_HOST}",
            f"scanner.maxScanDurationInMins={ZAP_MAX_SCAN_MINUTES}",
            f"scanner.maxRuleDurationInMins={ZAP_MAX_RULE_MINUTES}",
            "",
        )
    )


@lru_cache(maxsize=64)
def _path_pattern(template):
    parts = re.split(r"(\{[^{}]+\})", template)
    pattern = "".join(
        ".*" if part == "{path}" else "[^/]+" if part.startswith("{") else re.escape(part)
        for part in parts
    )
    return re.compile("^" + pattern + "$")


def match_operation(routes, method, path):
    return next(
        (
            row
            for row in routes
            if row["method"] == method.upper() and _path_pattern(row["route"]).fullmatch(path)
        ),
        None,
    )


class DastGateway(Gateway):
    """Reuse the V1 handler bridge, refusing writes and counting actual scan traffic."""

    routes = ()

    def __init__(self, *args):
        super().__init__(*args)
        self._lock = threading.Lock()
        self._scanning = False
        self._request_cap = REQUEST_CAP
        self._seen = self._forwarded = self._blocked = self._unmatched = 0
        self._auth_denials = 0
        self._cap_exceeded = False
        self._coverage = Counter()

    def begin_scan(self, request_cap=REQUEST_CAP):
        with self._lock:
            self._scanning = True
            self._request_cap = request_cap
            self._seen = self._forwarded = self._blocked = self._unmatched = 0
            self._auth_denials = 0
            self._cap_exceeded = False
            self._coverage.clear()

    def end_scan(self):
        with self._lock:
            self._scanning = False

    def invoke(self, method, target, headers, body=b""):
        route = match_operation(self.routes, method, urlsplit(target).path)
        with self._lock:
            scanning = self._scanning
            if scanning:
                self._seen += 1
                self._unmatched += route is None
                if (
                    route is None
                    or route["scan"] != "imported"
                    or method.upper() not in SCAN_METHODS
                ):
                    self._blocked += 1
                    return {
                        "statusCode": 405,
                        "body": '{"detail":"out-of-scope local DAST request"}',
                    }
                if self._forwarded >= self._request_cap:
                    self._cap_exceeded = True
                    self._coverage[(route["service"], route["method"], route["route"], "429")] += 1
                    return {"statusCode": 429, "body": '{"detail":"local DAST request cap"}'}
                self._forwarded += 1
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
                self._auth_denials += status in {401, 403}
        return reply

    def scan_evidence(self):
        with self._lock:
            return {
                "request_cap": self._request_cap,
                "requests_seen": self._seen,
                "requests_forwarded": self._forwarded,
                "cap_exceeded": self._cap_exceeded,
                "blocked_out_of_scope_requests": self._blocked,
                "unmatched_requests": self._unmatched,
                "in_scope_auth_denials": self._auth_denials,
                "routes": [
                    {
                        **{
                            name: row[name]
                            for name in ("service", "method", "route", "operation_id")
                        },
                        "responses": {
                            family: self._coverage[
                                (row["service"], row["method"], row["route"], family)
                            ]
                            for family in ("2xx", "3xx", "4xx", "5xx", "429")
                        },
                    }
                    for row in self.routes
                    if row["scan"] == "imported"
                ],
            }


def validate_report(report, port, host="127.0.0.1"):
    """Reject empty, malformed, or nonlocal ZAP JSON before calling a scan executed."""
    if (
        not isinstance(report, dict)
        or not all(
            isinstance(report.get(key), str) and report[key].strip()
            for key in ("@version", "@generated")
        )
        or not isinstance(report.get("site"), list)
        or not report["site"]
    ):
        raise RuntimeError("ZAP JSON report is empty or has an invalid shape")
    for site in report["site"]:
        if (
            not isinstance(site, dict)
            or site.get("@host") != host
            or str(site.get("@port")) != str(port)
            or str(site.get("@ssl")).lower() != "true"
            or not isinstance(site.get("alerts"), list)
            or not all(isinstance(alert, dict) for alert in site["alerts"])
        ):
            raise RuntimeError("ZAP JSON report includes invalid or out-of-scope site data")
        for alert in site["alerts"]:
            alert_fields(alert)


def alert_fields(alert):
    """Validate the bounded fields retained from a ZAP alert, without exposing its payload."""
    if not isinstance(alert, dict):
        raise RuntimeError("ZAP alert record is malformed")
    plugin_id = str(alert.get("pluginid", ""))
    risk = str(alert.get("riskcode", ""))
    confidence = str(alert.get("confidence", "")).strip().casefold()
    count = str(alert.get("count", ""))
    if (
        not re.fullmatch(r"[0-9]{1,10}", plugin_id)
        or risk not in {"0", "1", "2", "3"}
        or confidence not in {"0", "1", "2", "3", "4", "low", "medium", "high"}
        or not re.fullmatch(r"[0-9]{1,6}", count)
        or int(count) > 100000
    ):
        raise RuntimeError("ZAP alert record is malformed")
    return {
        "plugin_id": plugin_id,
        "risk_code": risk,
        "confidence": confidence,
        "count": int(count),
    }


def sanitized_findings(service, report):
    """Keep alert identifiers and severity only; drop site, route, parameter and evidence data."""
    return [
        {"service": service, **alert_fields(alert)}
        for site in report["site"]
        for alert in site["alerts"]
    ]


def _run_zap(private, ca_file, schema_file, timeout=ZAP_TIMEOUT_SECONDS):
    """Run the pinned scanner with a host cidfile so only its captured container can be stopped."""
    schema = json.loads(schema_file.read_text())
    base = local_origin(schema["servers"][0]["url"])
    parsed = urlsplit(base)
    script = r"""mkdir -p /tmp/.ZAP/policies || exit 3
cp /home/zap/.ZAP/policies/API-Minimal.policy /tmp/.ZAP/policies/API-Minimal.policy || exit 3
cp "$JAVA_HOME/lib/security/cacerts" /tmp/dast-trust || exit 3
keytool -importcert -noprompt -alias flickpond-v1-dast -file /tmp/dast-ca.crt \
  -keystore /tmp/dast-trust -storepass changeit >/dev/null 2>&1 || exit 3
export _JAVA_OPTIONS="-Djavax.net.ssl.trustStore=/tmp/dast-trust"
export _JAVA_OPTIONS="$_JAVA_OPTIONS -Djavax.net.ssl.trustStorePassword=changeit -Duser.home=/tmp"
zap-api-scan.py -t "$DAST_SCHEMA" -f openapi -J "/zap/wrk/$DAST_REPORT" -T 2 \
  -n /zap/wrk/dast.context -I -z "-configfile /zap/wrk/zap.options"
"""
    report_name = schema_file.stem.replace(".", "-") + "-raw.json"
    cid_file = (private / (schema_file.stem + ".cid")).resolve()
    cid_file.unlink(missing_ok=True)
    network = (
        ["--network", "bridge", "--add-host", "postgres:host-gateway"]
        if sys.platform == "darwin"
        else ["--network", "host"]
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--cidfile",
        str(cid_file),
        "--init",
        *network,
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
        f"{Path(private).resolve()}:/zap/wrk:rw",
        "--volume",
        f"{Path(ca_file).resolve()}:/tmp/dast-ca.crt:ro",
        "--entrypoint",
        "sh",
        ZAP_IMAGE,
        "-c",
        script,
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        try:
            container_id = cid_file.read_text().strip()
        except OSError:
            container_id = ""
        if re.fullmatch(r"[0-9a-f]{64}", container_id):
            subprocess.run(
                ["docker", "rm", "--force", container_id],
                capture_output=True,
                timeout=15,
                check=False,
            )
        raise RuntimeError("ZAP timed out") from error
    raw = private / report_name
    if result.returncode not in {0, 1, 2}:
        raise RuntimeError(f"ZAP scanner exit {result.returncode}")
    try:
        report = json.loads(raw.read_text())
        validate_report(report, parsed.port, parsed.hostname)
    except (OSError, json.JSONDecodeError, KeyError, IndexError) as error:
        raise RuntimeError("ZAP JSON report is unreadable or missing its local target") from error
    return result.returncode, report


def _client(url, ca_file, *, cookie=None):
    import httpx

    return httpx.Client(
        base_url=url.rstrip("/") + "/",
        verify=ssl.create_default_context(cafile=str(ca_file)),
        timeout=5,
        trust_env=False,
        cookies={"access_token": cookie} if cookie else None,
        follow_redirects=False,
    )


@contextlib.contextmanager
def _seed_and_verify(run_id, private, specs, rows):
    import jwt

    from publisher.client import PublicClient
    from scripts.dev.v1_acceptance import app_runtime, pump, short_video

    with app_runtime(run_id, gateway=DastGateway) as local:
        DastGateway.routes = tuple(rows)
        owners = [
            PublicClient(
                local["url"] + "/api/media",
                private / f"owner-{name}.cookies",
                ca_file=local["ca"],
                timeout=5,
            )
            for name in ("a", "b")
        ]
        processing = [_client(local["url"], local["ca"]) for _ in owners]
        try:
            identities = [
                client.authenticate(
                    "register",
                    f"dast-{name}-{uuid.uuid4().hex}@example.com",
                    f"local-dast-pass-{name}",
                )
                for name, client in zip(("a", "b"), owners, strict=True)
            ]
            if any(
                client.identity() != user["id"]
                for client, user in zip(owners, identities, strict=True)
            ):
                raise AssertionError("Owner login did not resolve to its registered identity")
            source = private / "fixture.mp4"
            short_video(source, seconds=1, size="160x90")
            assets = [client.upload(source, str(uuid.uuid4())) for client in owners]
            if len(set(assets + [user["id"] for user in identities])) != 4:
                raise AssertionError("Fixture owners/assets are not distinct")

            pump(local, results=False)
            for public, api in zip(owners, processing, strict=True):
                api.cookies.set("access_token", public.http.cookies.get("access_token"))
            job_lists = [
                api.get("/api/processing/jobs", params={"asset_ids": asset})
                for api, asset in zip(processing, assets, strict=True)
            ]
            if any(reply.status_code != 200 or not reply.json() for reply in job_lists):
                raise AssertionError("Owner processing list read failed")
            jobs = [reply.json()[0]["job_id"] for reply in job_lists]

            owner_reads = [
                (client.http.get(f"jobs/{asset}"), api.get(f"/api/processing/jobs/{job}"))
                for client, api, asset, job in zip(owners, processing, assets, jobs, strict=True)
            ]
            denied = (
                owners[1].http.get(f"jobs/{assets[0]}"),
                owners[1].http.get(
                    f"jobs/{assets[0]}",
                    headers={"X-Owner-Id": identities[0]["id"], "X-Role": "operator"},
                ),
                processing[1].get(f"/api/processing/jobs/{jobs[0]}"),
                owners[1].http.delete(f"jobs/{assets[0]}"),
                processing[1].delete(f"/api/processing/jobs/{jobs[0]}"),
            )
            stable_media = owners[0].http.get(f"jobs/{assets[0]}")
            stable_processing = processing[0].get(f"/api/processing/jobs/{jobs[0]}")
            if (
                any(reply.status_code != 200 for pair in owner_reads for reply in pair)
                or stable_media.status_code != 200
                or stable_processing.status_code != 200
                or any(reply.status_code != 404 for reply in denied)
                or owner_reads[0][0].json() != stable_media.json()
                or owner_reads[0][1].json() != stable_processing.json()
            ):
                raise AssertionError("Owner isolation or cross-owner mutation denial failed")

            with _client(local["url"], local["ca"]) as missing:
                missing_status = missing.get("/api/media/auth/me").status_code
            now = int(time.time())
            expired_token = jwt.encode(
                {"sub": identities[0]["id"], "iat": now - 120, "exp": now - 60},
                "local-v1-emulator-jwt-key-never-deploy",
                algorithm="HS256",
            )
            with _client(local["url"], local["ca"], cookie=expired_token) as expired:
                expired_status = expired.get("/api/media/auth/me").status_code
            if missing_status != 401 or expired_status != 401:
                raise AssertionError("Missing or expired session was not denied")

            fixtures = {"media_job": assets[0], "processing_job": jobs[0]}
            base = scanner_base(local["url"])
            scans = {
                service: scan_document(service, specs[service], base, fixtures, rows)
                for service in SERVICES
            }
            scan_hashes = {
                service: hashlib.sha256(
                    json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                for service, document in scans.items()
            }
            for service, document in scans.items():
                (private / f"{service}.openapi.json").write_text(
                    json.dumps(document, sort_keys=True)
                )
            port = urlsplit(base).port
            host = urlsplit(base).hostname
            (private / "dast.context").write_text(context_xml(port, host))
            options = private / "zap.options"
            options.write_text(
                zap_options(
                    port, "access_token=" + owners[0].http.cookies.get("access_token"), host
                )
            )
            options.chmod(0o600)

            yield {
                "local": local,
                "owners": owners,
                "processing": processing,
                "fixtures": fixtures,
                "scan_hashes": scan_hashes,
                "owner_a_id": identities[0]["id"],
                "auth_proof": {
                    "positive_owner_reads": {
                        "media": len(owner_reads),
                        "processing": len(owner_reads),
                        "status": "PASS",
                    },
                    "cross_owner_media_read": "DENIED_404",
                    "forged_owner_header": "DENIED_404",
                    "cross_owner_processing_read": "DENIED_404",
                    "cross_owner_media_delete": "DENIED_404_RESOURCE_UNCHANGED",
                    "cross_owner_processing_cancel": "DENIED_404_RESOURCE_UNCHANGED",
                    "missing_session": "DENIED_401",
                    "expired_session": "DENIED_401",
                    "fixture_users": MAX_FIXTURE_USERS,
                    "fixture_uploads": MAX_FIXTURE_UPLOADS,
                    "worker_invocations": MAX_WORKER_INVOCATIONS,
                },
            }
        finally:
            for client in owners + processing:
                client.close()


def _validate_coverage(gateway, rows):
    evidence = gateway.scan_evidence()
    covered = {
        (route["service"], route["method"], route["route"]): route["responses"]
        for route in evidence["routes"]
    }
    missing = [
        row["operation_id"]
        for row in rows
        if row["scan"] == "imported"
        and not covered.get((row["service"], row["method"], row["route"]), {}).get("2xx")
    ]
    if evidence["cap_exceeded"]:
        raise RuntimeError("ZAP reached the local forwarded-request cap")
    if evidence["in_scope_auth_denials"]:
        raise RuntimeError("ZAP received in-scope authentication denials")
    if missing:
        raise RuntimeError("ZAP did not successfully exercise routes: " + ",".join(missing))
    return evidence


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def validate_run_id(run_id):
    if len(run_id) > 48 or not re.fullmatch(r"dast-[0-9]+-[0-9]+", run_id):
        raise ValueError("Choose a unique DAST run ID in the form dast-<run>-<attempt>")


def _source_sha():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=5
    ).strip()
    event_sha = os.environ.get("GITHUB_SHA")
    if event_sha and event_sha != head:
        raise ValueError("DAST source SHA does not match the checked-out commit")
    return head


def run_scan(run_id, output):
    validate_run_id(run_id)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = ROOT / ".cache/v1-dast" / run_id
    if private.exists():
        raise ValueError("Refusing to reuse a DAST private directory; select a fresh run ID")
    private.mkdir(parents=True, mode=0o700)
    disposition = {
        "engine": "zap",
        "disposition": "error",
        "target": "isolated-v1-local-gateway",
        "scope": "Generated Media and Processing V1 APIs; authenticated normal owner; local only.",
        "report_retained": False,
        "source_sha": "unknown",
        "cloud_scan": "NOT_RUN",
        "harness": "scripts.dev.v1_acceptance.app_runtime + scripts.dev.v1_dast.DastGateway",
        "runtime": "real PostgreSQL; run-scoped Moto S3/SQS; V1 handlers and Media authorizer",
        "cleanup": "PENDING",
    }
    findings, exit_codes = [], {}
    gateway = None
    try:
        runtime = load(run_id)
        if runtime["state"] != "running":
            raise ValueError("Start the exact unique V1 runtime before local DAST")
        disposition["source_sha"] = _source_sha()
        specs, schema_hashes = current_specs()
        rows = operation_rows(specs)
        DastGateway.routes = tuple(rows)
        disposition.update(
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
        with _seed_and_verify(run_id, private, specs, rows) as seeded:
            local = seeded["local"]
            gateway = local["gateway"]
            disposition.update(
                scan_schema_hashes=seeded["scan_hashes"], auth_proof=seeded["auth_proof"]
            )
            gateway.begin_scan(REQUEST_CAP)
            for service in SERVICES:
                code, report = _run_zap(
                    private, Path(local["ca"]), private / f"{service}.openapi.json"
                )
                exit_codes[service] = code
                findings.extend(sanitized_findings(service, report))
                disposition["report_retained"] = True
            gateway.end_scan()
            route_evidence = _validate_coverage(gateway, rows)

            if seeded["owners"][0].identity() != seeded["owner_a_id"]:
                raise RuntimeError("Owner session did not remain valid after scanning")
            asset = seeded["fixtures"]["media_job"]
            job = seeded["fixtures"]["processing_job"]
            media_after = seeded["owners"][0].http.get(f"jobs/{asset}")
            processing_after = seeded["processing"][0].get(f"/api/processing/jobs/{job}")
            if media_after.status_code != 200 or processing_after.status_code != 200:
                raise RuntimeError("Seeded owner resources changed or auth expired during scanning")
            if local["observations"]["storage_cookie_headers"]:
                raise RuntimeError("A session cookie reached the local object-storage proxy")
            disposition.update(
                disposition="executed",
                exit_codes=exit_codes,
                findings_count=len(findings),
                route_coverage=route_evidence,
                storage_cookie_forwarded=False,
                worker_invocations=MAX_WORKER_INVOCATIONS,
            )
    except Exception as error:
        if gateway:
            gateway.end_scan()
            disposition["route_coverage"] = gateway.scan_evidence()
        disposition.update(
            disposition="error", error_type=type(error).__name__, exit_codes=exit_codes
        )
        if isinstance(error, RuntimeError) and str(error).startswith("ZAP "):
            disposition["error_detail"] = str(error)
    finally:
        shutil.rmtree(private, ignore_errors=True)
        disposition["private_raw_cleanup"] = "PASS" if not private.exists() else "FAIL"
        disposition["sanitized_findings_retained"] = bool(disposition["report_retained"])
        disposition.update(
            scan_disposition(
                "zap",
                outcome=disposition["disposition"],
                target=disposition["target"],
                scope=disposition["scope"],
                report_retained=disposition["sanitized_findings_retained"],
            )
        )
        _write_json(output / "scan-disposition.json", disposition)
        _write_json(output / "sanitized-findings.json", findings)

    exercised = sum(
        any(route["responses"].values())
        for route in disposition.get("route_coverage", {}).get("routes", [])
    )
    print(
        f"DAST disposition={disposition['disposition']} routes={exercised} "
        f"findings={len(findings)} blocked_out_of_scope="
        f"{disposition.get('route_coverage', {}).get('blocked_out_of_scope_requests', 0)}"
    )
    return int(
        disposition["disposition"] != "executed" or disposition.get("private_raw_cleanup") != "PASS"
    )


def cleanup_runtime(run_id, output):
    """Stop only this run's V1 runtime, then remove its private scan and runtime files."""
    validate_run_id(run_id)
    output = Path(output).resolve()
    runtime_dir = ROOT / ".cache/v1-runtime" / run_id
    state = runtime_dir / "runtime.json"
    private = ROOT / ".cache/v1-dast" / run_id
    result, error_type = "NOT_STARTED", None
    try:
        if state.exists():
            load(run_id)
            runtime_down(run_id, delete_data=True)
            shutil.rmtree(runtime_dir)
            result = "PASS"
    except Exception as error:
        result, error_type = "FAIL", type(error).__name__
    shutil.rmtree(private, ignore_errors=True)
    private_cleaned = not private.exists()
    record = output / "scan-disposition.json"
    if record.exists():
        data = json.loads(record.read_text())
        data["cleanup"] = result
        data["private_raw_cleanup"] = "PASS" if private_cleaned else "FAIL"
        if error_type:
            data["cleanup_error_type"] = error_type
        _write_json(record, data)
    print(
        f"DAST local runtime cleanup={result} private files={'PASS' if private_cleaned else 'FAIL'}"
    )
    return int(result == "FAIL" or not private_cleaned)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("--run-id", required=True)
        command.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    return (
        run_scan(args.run_id, args.output)
        if args.command == "scan"
        else cleanup_runtime(args.run_id, args.output)
    )


if __name__ == "__main__":
    raise SystemExit(main())
