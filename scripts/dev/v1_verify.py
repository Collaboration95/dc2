"""Real local V1 dependency evidence, with explicit integration gates.

A = real owned SQL + immutable S3/SQS emulation + actual engine MP4/HLS.
B = integrated API/browser/Publisher workflow (registered owning test selection).
C = session failure contracts plus independent release adapter selection.
Absent acceptance tests are INCOMPLETE, never a skip converted to PASS.
"""

import asyncio
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from scripts.dev.v1_redact import first_lines, redact
from scripts.dev.v1_runtime import ROOT, directory, load, moto_python, run, save

CORE_INTEGRATION_SUITES = (
    "tests/v1/test_delivery_recovery_sql.py",
    "tests/v1/test_direct_intake_s3.py",
    "tests/v1/test_domain_sql_boundary.py",
    "tests/v1/test_media_cleanup_sql.py",
    "tests/v1/test_media_messaging_sql.py",
    "tests/v1/test_messaging_sql.py",
    "tests/v1/test_processing_activity_sql.py",
    "tests/v1/test_sqs_emulator.py",
    "tests/v1/test_upload_cleanup_sql.py",
)
SUPPORT_INTEGRATION_SELECTORS = (
    "tests/v1/test_dlq.py::test_quarantined_message_in_emulator_dlq_is_inspectable",
    "tests/v1/test_dlq.py::test_emulator_redrive_returns_a_quarantined_envelope_and_keeps_the_invalid_one",
    "tests/v1/test_local_gateway.py::test_real_http_bridge_preserves_multiple_set_cookie_and_binary_response",
)
AUDIT_CORE_CASES = 93
ADDITIONAL_RECOVERY_CASES = 2
EXISTING_INTEGRATION_SUITES = (
    "tests/v1/test_browser_acceptance.py",
    "tests/v1/test_launcher_sql.py",
    "tests/v1/test_release_acceptance.py",
    "tests/v1/test_workflow_acceptance.py",
)
OPTIONAL_INTEGRATION_DISPOSITIONS = {
    "tests/v1/test_short_encoder_sql.py": {
        "cases": 13,
        "status": "DEFERRED_OPTIONAL_V2",
        "reason": ("Optional short-encoder lane; its tests do not enable the lane in runtime."),
    }
}
CREDENTIAL_ROTATION_REGRESSION = (
    "tests/v1/test_credential_rotation.py::"
    "test_a_real_wrong_password_is_recognised_as_a_login_refusal"
)
# Use pytest's own collection and markers; new marked V1 cases run by default. These
# exclusions already run in their owning flows or are explicitly deferred optional code.
REQUIRED_INTEGRATION_ARGS = (
    "-m",
    "integration",
    *[
        f"--ignore={path}"
        for path in (*EXISTING_INTEGRATION_SUITES, *OPTIONAL_INTEGRATION_DISPOSITIONS)
    ],
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sdk(data, service):
    import boto3
    from botocore.config import Config

    endpoint = urlsplit(data["endpoint_url"])
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or not endpoint.port
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("Only the explicitly owned loopback emulator is allowed")
    return boto3.client(
        service,
        endpoint_url=data["endpoint_url"],
        region_name="ap-southeast-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        aws_session_token="testing",
        # Moto shares two CPUs with Chromium, FFmpeg and PostgreSQL on a CI runner. The old
        # 2s/5s limits turned one slow loopback call into a failed acceptance run. No retry:
        # a repeated SendMessage or DeleteMessage would change what the tests count.
        config=Config(
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )


def provision_local_objects(data, *, purge=False):
    """Create distinct versioned stores, three queues and DLQs in owned Moto.

    ``purge`` deletes and recreates every queue and DLQ. A reused runtime otherwise hands the
    next run the previous run's undeleted work (for example a cancelled edit's message), and
    the finite encoder, which takes exactly one message per task, then fails on a job that no
    longer exists. Recreation rather than PurgeQueue: AWS and Moto both allow one purge per
    queue per 60 seconds, which would make back-to-back runs fail, and a purge cannot drop
    messages still invisible from an earlier receive. The namespace is owned by this run ID.
    """
    s3, sqs = sdk(data, "s3"), sdk(data, "sqs")
    buckets = {owner: "dc2-v1-" + data["run_id"] + "-" + owner for owner in ("source", "output")}
    for bucket in buckets.values():
        try:
            s3.head_bucket(Bucket=bucket)
        except s3.exceptions.ClientError:
            s3.create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"}
            )
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_cors(
        Bucket=buckets["source"],
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": ["http://127.0.0.1:*", "https://127.0.0.1:*"],
                    "AllowedMethods": ["POST", "GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag", "x-amz-version-id"],
                }
            ]
        },
    )
    queues = {}
    for name in ("commands", "work", "results"):
        if purge:
            for suffix in ("", "-dlq"):
                try:
                    url = sqs.get_queue_url(QueueName=f"{data['project']}-{name}{suffix}")
                except sqs.exceptions.QueueDoesNotExist:
                    continue
                sqs.delete_queue(QueueUrl=url["QueueUrl"])
        dlq = sqs.create_queue(QueueName=f"{data['project']}-{name}-dlq")["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"][
            "QueueArn"
        ]
        queues[name] = sqs.create_queue(
            QueueName=f"{data['project']}-{name}",
            Attributes={
                "VisibilityTimeout": "60",
                "RedrivePolicy": json.dumps({"deadLetterTargetArn": arn, "maxReceiveCount": "3"}),
            },
        )["QueueUrl"]
    return {"buckets": buckets, "queues": queues, "purged_queues": bool(purge)}


async def sql_probe(data, probe_id):
    import asyncpg

    port = data["postgres_port"]
    tables = []
    for owner in ("media", "processing"):
        params = {
            "host": "127.0.0.1",
            "port": port,
            "database": owner + "_db",
            "timeout": 5,
            "ssl": ssl.create_default_context(
                cafile=str(
                    Path(data["root"]) / ".cache/v1-runtime" / data["run_id"] / "tls/server.crt"
                )
            ),
        }
        connection = await asyncpg.connect(
            **params, user=owner + "_migrator", password=f"local_v1_{owner}_migrate"
        )
        try:
            assert await connection.fetchval(
                "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS public.v1_runtime_probe "
                "(id uuid PRIMARY KEY, state text NOT NULL)"
            )
        finally:
            await connection.close()
        connection = await asyncpg.connect(
            **params, user=owner + "_runtime", password=f"local_v1_{owner}"
        )
        try:
            await connection.execute(
                "INSERT INTO public.v1_runtime_probe VALUES ($1, 'queued')", probe_id
            )
            assert (
                await connection.fetchval(
                    "SELECT state FROM public.v1_runtime_probe WHERE id=$1", probe_id
                )
                == "queued"
            )
            try:
                await connection.execute("CREATE TABLE public.forbidden_runtime_ddl (id int)")
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("Runtime DDL was allowed")
        finally:
            await connection.close()
        for role, password in [
            (owner + "_runtime", f"local_v1_{owner}"),
            (owner + "_migrator", f"local_v1_{owner}_migrate"),
        ]:
            opposite = "processing" if owner == "media" else "media"
            try:
                denied = await asyncpg.connect(
                    **{**params, "database": opposite + "_db"}, user=role, password=password
                )
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                await denied.close()
                raise AssertionError("Cross-database connection was allowed")
        tables.append(owner)
    return {
        "owners": tables,
        "runtime_dml": "PASS",
        "runtime_ddl_denied": "PASS",
        "cross_database_runtime_and_migrator_denied": "PASS",
        "postgres_tls": "verified local certificate",
        "queued_rows": "retained",
    }


def receive_matching(sqs, queue, message_id, *, visibility):
    for _ in range(10):
        for message in sqs.receive_message(
            QueueUrl=queue, MaxNumberOfMessages=10, VisibilityTimeout=visibility, WaitTimeSeconds=0
        ).get("Messages", []):
            if json.loads(message["Body"]).get("message_id") == message_id:
                return message
            sqs.change_message_visibility(
                QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0
            )
    raise AssertionError("Expected work message was not delivered")


def objects_and_encode(data, output, probe_id):
    from media_engine.hls import build_ladder_command
    from media_engine.operations import build_edit_command

    s3, sqs = sdk(data, "s3"), sdk(data, "sqs")
    resources = provision_local_objects(data, purge=True)
    bucket = resources["buckets"]["source"]
    output_bucket = resources["buckets"]["output"]
    queues = resources["queues"]
    source = output / "source.mp4"
    run(
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
            "-c:a",
            "aac",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-y",
            str(source),
        ],
        capture_output=True,
        timeout=20,
    )
    key = f"staging/{probe_id}/source.mp4"
    receipt = s3.put_object(
        Bucket=bucket, Key=key, Body=source.read_bytes(), ContentType="video/mp4"
    )
    version = receipt["VersionId"]
    # Real HTTP to Moto. A later write must not replace immutable accepted bytes.
    s3.put_object(Bucket=bucket, Key=key, Body=b"late replacement")
    accepted = s3.get_object(Bucket=bucket, Key=key, VersionId=version)["Body"].read()
    assert hashlib.sha256(accepted).hexdigest() == digest(source)
    downloaded = output / "downloaded.mp4"
    downloaded.write_bytes(accepted)
    payload = {
        "schema_version": 1,
        "message_id": str(probe_id),
        "kind": "work",
        "owner_id": str(uuid.uuid4()),
        "asset_id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "attempt_id": str(uuid.uuid4()),
        "state_version": 0,
        "source": {
            "bucket": bucket,
            "key": key,
            "version_id": version,
            "sha256": digest(source),
            "size_bytes": source.stat().st_size,
            "content_type": "video/mp4",
        },
        "payload": {},
    }
    # This is a transport seam, not a substitute for the owning SQL inbox handler.
    queue = queues["work"]
    sqs.send_message(QueueUrl=queue, MessageBody=json.dumps(payload))
    # A reused runtime may still hold earlier runs' work, so pick this payload by ID
    # and hand every foreign message straight back instead of assuming queue order.
    message = receive_matching(sqs, queue, payload["message_id"], visibility=0)
    assert json.loads(message["Body"]) == payload
    duplicate = receive_matching(sqs, queue, payload["message_id"], visibility=30)
    assert duplicate["MessageId"] == message["MessageId"]
    sqs.delete_message(QueueUrl=queue, ReceiptHandle=duplicate["ReceiptHandle"])
    encoded = output / "output.mp4"
    command = build_edit_command(
        [],
        ffmpeg_binary="ffmpeg",
        source_path=downloaded,
        output_path=encoded,
        preset="ultrafast",
        crf=28,
    )
    run(command, capture_output=True, timeout=20)
    hls = output / "hls"
    hls.mkdir()
    run(
        build_ladder_command(encoded, hls, heights=(90,), preset="ultrafast"),
        capture_output=True,
        timeout=20,
    )
    manifest = hls / "master.m3u8"
    assert manifest.is_file() and list(hls.rglob("*.ts"))
    probe = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(encoded),
        ],
        capture_output=True,
        timeout=5,
    )
    assert json.loads(probe.stdout)["streams"][0]["codec_name"] == "h264"
    s3.put_object(Bucket=output_bucket, Key=f"outputs/{probe_id}.mp4", Body=encoded.read_bytes())
    ranged = s3.get_object(Bucket=output_bucket, Key=f"outputs/{probe_id}.mp4", Range="bytes=0-31")
    assert ranged["Body"].read() == encoded.read_bytes()[:32]
    return {
        "s3_immutable_version": "PASS",
        "sqs_redelivery": "PASS",
        "mp4_hls_ffmpeg": "PASS",
        "s3_range": "PASS",
        "source_sha256": digest(source),
        "output_sha256": digest(encoded),
        "source_bytes": source.stat().st_size,
        "output_bytes": encoded.stat().st_size,
        "cloud_iam_gateway_lambda_fargate": "NOT_RUN",
    }


def local_environment(data, *, storage_mode="lambda"):
    """Explicit local-only child environment; no inherited AWS profiles/credentials."""
    if storage_mode not in {"lambda", "static"}:
        raise ValueError("V1 local test storage mode must be lambda or static")
    env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    env.update(
        PYTHONPATH=str(ROOT),
        V1_RUN_ID=data["run_id"],
        V1_RUNTIME_CONFIG=str(
            Path(data["root"]) / ".cache/v1-runtime" / data["run_id"] / "runtime.json"
        ),
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_SESSION_TOKEN="testing",
        # LambdaProvider refuses to read credentials outside a Lambda runtime.
        AWS_LAMBDA_FUNCTION_NAME="local-v1-media",
        AWS_REGION="ap-southeast-1",
        AWS_DEFAULT_REGION="ap-southeast-1",
        AWS_EC2_METADATA_DISABLED="true",
        AWS_CONFIG_FILE="/dev/null",
        AWS_SHARED_CREDENTIALS_FILE="/dev/null",
        AWS_ENDPOINT_URL=data["endpoint_url"],
        MEDIA_POSTGRES_SSL_CA=str(
            Path(data["root"]) / ".cache/v1-runtime" / data["run_id"] / "tls/server.crt"
        ),
        PROCESSING_DATABASE_TLS="true",
        PROCESSING_DATABASE_CA_FILE=str(
            Path(data["root"]) / ".cache/v1-runtime" / data["run_id"] / "tls/server.crt"
        ),
        SQS_ENDPOINT_URL=data["endpoint_url"],
        S3_ENDPOINT_URL=data["endpoint_url"],
    )
    resources = data.get("resources") or provision_local_objects(data)
    endpoint = urlsplit(data["endpoint_url"])
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or not endpoint.port
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("V1 tests require the explicitly owned loopback emulator")
    env.update(
        MEDIA_RUNTIME_MODE="lambda",
        MEDIA_STORAGE_CREDENTIAL_MODE=storage_mode,
        MEDIA_MINIO_ENDPOINT=endpoint.netloc,
        MEDIA_MINIO_USE_SSL="false",
        MEDIA_MINIO_PUBLIC_ENDPOINT=endpoint.netloc,
        MEDIA_MINIO_PUBLIC_USE_SSL="false",
        MEDIA_MINIO_SOURCE_BUCKET=resources["buckets"]["source"],
        MEDIA_MINIO_OUTPUT_BUCKET=resources["buckets"]["output"],
        MEDIA_MINIO_REGION="ap-southeast-1",
        MEDIA_API_PUBLIC_PREFIX="/api/media",
        MEDIA_JWT_SECRET="local-v1-emulator-jwt-key-never-deploy",
        PROCESSING_COMMANDS_QUEUE_URL=resources["queues"]["commands"],
        PROCESSING_WORK_QUEUE_URL=resources["queues"]["work"],
        MEDIA_RESULTS_QUEUE_URL=resources["queues"]["results"],
        WORK_QUEUE_URL=resources["queues"]["work"],
    )
    tls_ca = Path(data["root"]) / ".cache/v1-runtime" / data["run_id"] / "tls/server.crt"
    env["PGSSLROOTCERT"] = str(tls_ca)

    def admin_dsn(database):
        # Schema-per-test fixtures use the disposable stack's admin login, and verify its
        # loopback certificate just like the owner runtime connections do.
        query = "ssl=verify-full"
        return (
            f"postgresql+asyncpg://postgres:local_v1_admin@127.0.0.1:{data['postgres_port']}"
            f"/{database}?{query}"
        )

    env["V1_TEST_MEDIA_DSN"] = admin_dsn("media_db")
    env["V1_TEST_PROCESSING_DSN"] = admin_dsn("processing_db")
    env["V1_TEST_S3_ENDPOINT"] = data["endpoint_url"]
    env["V1_TEST_SQS_ENDPOINT"] = data["endpoint_url"]
    for owner in ("media", "processing"):
        env[owner.upper() + "_POSTGRES_DSN"] = (
            f"postgresql+asyncpg://{owner}_runtime:local_v1_{owner}"
            f"@127.0.0.1:{data['postgres_port']}/{owner}_db"
        )
    return env


def coverage_rc():
    """Use the pyproject omit list in V1 subprocess coverage as in every other tier."""
    from scripts.dev.common import V1_BOOTSTRAP_SOURCE, coverage_omit_patterns, packages

    sources = [*packages(), V1_BOOTSTRAP_SOURCE]
    omit = coverage_omit_patterns()
    return "\n".join(
        [
            "[run]",
            "branch = True",
            "parallel = True",
            "relative_files = True",
            "patch = subprocess",
            "source =",
            *[f"    {source}" for source in sources],
            "omit =",
            *[f"    {pattern}" for pattern in omit],
            "",
        ]
    )


def resolve_test_selectors(selectors, root=ROOT):
    """Resolve paths or one exact pytest node per path without widening the selection."""
    tests = set()
    for selector in selectors:
        path, separator, node = selector.partition("::")
        candidates = sorted(root.glob(path)) if any(c in path for c in "*?[") else [root / path]
        candidates = [
            candidate
            for candidate in candidates
            if candidate.is_file() or (not separator and candidate.is_dir())
        ]
        if not candidates or (separator and len(candidates) != 1):
            return []
        for candidate in candidates:
            selected = str(candidate.relative_to(root))
            tests.add(f"{selected}::{node}" if separator else selected)
    return sorted(tests)


def selected_tests(
    patterns,
    output,
    data,
    *,
    tag="tests",
    timeout=180,
    require_integration=False,
    storage_mode="lambda",
    pytest_options=(),
):
    tests = resolve_test_selectors(patterns, root=ROOT)
    if not tests:
        return {"status": "INCOMPLETE", "reason": "Owning acceptance tests not integrated"}
    report = output / f"{tag}.xml"
    env = local_environment(data, storage_mode=storage_mode)
    # Tests that can capture a screenshot or page state on failure write it here. Only
    # redacted files are meant to leave the runtime directory (see the CI artifact step).
    env["V1_FAILURE_DIR"] = str(output / f"failure-{tag}")
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        *pytest_options,
        "-q",
        "--junitxml",
        str(report),
    ]
    if require_integration:
        # The existing plugin and JUnit result both reject missing fixture resources/skips.
        command += ["-p", "scripts.dev.pytest_plugin", "--require-integration"]
    if os.environ.get("V1_COVERAGE") == "1":
        # The encoder, alembic and watchdog run as child processes, so measure those too
        # (patch = subprocess). Each invocation writes its own fragment for later combining.
        from scripts.dev.common import V1_BOOTSTRAP_SOURCE, packages

        rc = output / f"coveragerc-{tag}"
        rc.write_text(coverage_rc())
        env["COVERAGE_FILE"] = str(output / f".coverage.{tag}")
        command += [f"--cov-config={rc}", "--cov-report=", "--cov-fail-under=0"]
        command += [f"--cov={name}" for name in (*packages(), V1_BOOTSTRAP_SOURCE)]
    reason = None
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout
        )
        log, returncode = result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired as expired:
        # subprocess.run has killed the child; whatever it printed is still evidence.
        reason = f"The test run exceeded its {timeout}s budget and was killed"
        returncode = None
        log = "".join(
            part.decode(errors="replace") if isinstance(part, bytes) else part or ""
            for part in (expired.stdout, expired.stderr)
        )
    (output / f"pytest-private-{tag}.log").write_text(log)
    if not report.exists():
        reason = reason or "Test runner did not produce an execution report"
        # No junit to name a test, so name the run: the log must still say what died.
        run_failure = {"id": " ".join(tests), "kind": "run", "message": reason}
        return {"status": "FAIL", "reason": reason, "failed_tests": [run_failure]}
    counts, failed, skipped = read_junit(report)
    node_ids = junit_test_ids(report)
    if reason:
        failed.append({"id": " ".join(tests), "kind": "run", "message": reason})
    # The raw report may quote request headers; only this redacted copy is published.
    (output / f"junit-{tag}.redacted.xml").write_text(redact(report.read_text()))
    status = (
        "PASS"
        if (returncode == 0 and counts["tests"] > 0 and not counts["skipped"])
        else "INCOMPLETE"
        if returncode == 0
        else "FAIL"
    )
    return {
        "status": status,
        "counts": counts,
        "junit_sha256": digest(report),
        "tests": tests,
        "node_ids": node_ids,
        "passed": max(0, len(node_ids) - len(failed) - len(skipped)),
        # Counts alone cannot say which test flaked, so name the failing ones.
        "failed_tests": failed,
        "skipped_tests": skipped,
        **({"reason": reason} if reason else {}),
    }


def junit_node_id(case):
    parts = case.get("classname", "").split(".")
    for count in range(len(parts), 0, -1):
        source = Path(*parts[:count]).with_suffix(".py")
        if (ROOT / source).is_file():
            return "::".join([str(source), *parts[count:], case.get("name", "")])
    return f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name', '')}"


def read_junit(report):
    """(counts, failed, skipped) from a junit file. Messages are redacted and bounded."""
    from xml.etree import ElementTree as ET

    root = ET.parse(report).getroot()
    suites = list(root) if root.tag == "testsuites" else [root]
    counts = {
        k: sum(int(s.attrib.get(k, 0)) for s in suites)
        for k in ("tests", "errors", "failures", "skipped")
    }
    failed, skipped = [], []
    for case in root.iter("testcase"):
        identity = junit_node_id(case)
        for outcome in case:
            if outcome.tag in {"failure", "error"}:
                message = outcome.get("message") or outcome.text or ""
                failed.append(
                    {"id": identity, "kind": outcome.tag, "message": first_lines(message)}
                )
            elif outcome.tag == "skipped":
                skipped.append(identity)
    return counts, failed, skipped


def junit_test_ids(report):
    """Return the exact collected pytest node IDs recorded in this execution report."""
    from xml.etree import ElementTree as ET

    root = ET.parse(report).getroot()
    return [junit_node_id(case) for case in root.iter("testcase")]


def summarize_required_nodes(result):
    """Count exact selected, passed, skipped and failed nodes by registry group."""
    node_ids = result.get("node_ids", [])
    failed = {item["id"] for item in result.get("failed_tests", [])}
    skipped = set(result.get("skipped_tests", []))

    def summarize(selectors):
        selected = set()
        for selector in selectors:
            path, separator, node = selector.partition("::")
            if separator:
                selected.update(item for item in node_ids if item == f"{path}::{node}")
            else:
                selected.update(item for item in node_ids if item.startswith(f"{path}::"))
        return {
            "selected": len(selected),
            "passed": len(selected - failed - skipped),
            "skipped": len(selected & skipped),
            "failed": len(selected & failed),
        }

    return {
        "core": summarize(CORE_INTEGRATION_SUITES),
        "support": summarize(SUPPORT_INTEGRATION_SELECTORS),
        "real_password": summarize([CREDENTIAL_ROTATION_REGRESSION]),
    }


def failed_tests(flows):
    """Every failing test in the flow results, as {flow, id, kind, message}."""
    found = []

    def walk(flow, node):
        if not isinstance(node, dict):
            return
        found.extend({"flow": flow, **item} for item in node.get("failed_tests", []))
        for value in node.values():
            walk(flow, value)

    for flow, result in flows.items():
        walk(flow, result)
    return found


def report_failures(failures):
    """Put each failing test and its assertion in the job log (an annotation on GitHub)."""
    for item in failures:
        line = f"{item['id']} ({item['kind']}): {item['message']}"
        if os.environ.get("GITHUB_ACTIONS") == "true":
            escaped = line.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error title=V1 flow {item['flow']} test failed::{escaped}", file=sys.stderr)
        else:
            print(f"FAILED flow {item['flow']}: {line}", file=sys.stderr)


def browser_requested():
    return os.environ.get("V1_BROWSER") == "1"


def combine_coverage(output, run_id):
    """Merge every fragment of this run into one tier the CI coverage gate can consume."""
    from coverage import Coverage

    from scripts.dev.common import (
        V1_BOOTSTRAP_SOURCE,
        coverage_omit_patterns,
        fingerprint,
        packages,
    )

    fragments = sorted(
        str(path) for path in output.rglob(".coverage.*") if not path.name.endswith(".json")
    )
    if not fragments:
        return {"status": "NOT_COLLECTED", "reason": "No test fragment was produced"}
    target = ROOT / "artifacts/coverage/.coverage.v1-integration"
    target.parent.mkdir(parents=True, exist_ok=True)
    for stale in target.parent.glob(".coverage.v1-integration*"):
        stale.unlink()
    merged = Coverage(data_file=str(target), config_file=False, branch=True)
    merged.combine(data_paths=fragments, strict=True, keep=True)
    merged.save()
    target.with_suffix(target.suffix + ".json").write_text(
        json.dumps(
            {
                "fingerprint": fingerprint(),
                "tier": "v1-integration",
                "packages": packages(),
                "coverage_sources": [*packages(), V1_BOOTSTRAP_SOURCE],
                "omit": coverage_omit_patterns(),
            }
        )
        + "\n"
    )
    return {
        "status": "COLLECTED",
        "fragments": len(fragments),
        "tier": "v1-integration",
        "omit": coverage_omit_patterns(),
        "bootstrap_source": V1_BOOTSTRAP_SOURCE,
    }


def run_flow(name, data, phase):
    if name == "a":
        probe_id = uuid.uuid4()
        sql = asyncio.run(sql_probe(data, probe_id))
        objects = objects_and_encode(data, phase, probe_id)
        return {"status": "PASS", "scope": "dependency/engine seam only", **sql, **objects}
    if name == "b":
        # Publisher workflow always; the real browser only when explicitly requested, so a
        # machine without Chromium gets an honest NOT_RUN rather than a silent skip.
        publisher = selected_tests(
            ["tests/v1/test_workflow_acceptance.py"], phase, data, tag="publisher"
        )
        if not browser_requested():
            return {
                **publisher,
                "browser": "NOT_RUN: set V1_BROWSER=1 (make browser-install first)",
            }
        # Two tests of up to 300s each (their pytest timeout) plus start-up; the 180s default
        # killed the run before either test's own bounded waits could report anything.
        browser = selected_tests(
            ["tests/v1/test_browser_acceptance.py"], phase, data, tag="browser", timeout=660
        )
        statuses = {publisher["status"], browser["status"]}
        status = (
            "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "INCOMPLETE" in statuses else "PASS"
        )
        return {"status": status, "publisher": publisher, "browser": browser}
    session = selected_tests(
        ["tests/v1/test_session.py", "tests/v1/test_launcher_sql.py"], phase, data, tag="session"
    )
    required = selected_tests(
        ["tests/v1"],
        phase,
        data,
        tag="required-integration",
        pytest_options=REQUIRED_INTEGRATION_ARGS,
        timeout=900,
        require_integration=True,
        storage_mode="static",
    )
    bootstrap = selected_tests(
        ["tests/aws/v1/test_bootstrap.py"], phase, data, tag="bootstrap-coverage", timeout=180
    )
    release_path = ROOT / "tests/v1/test_release_acceptance.py"
    release = {
        "status": "INCOMPLETE",
        "reason": "Owning real SQL release acceptance is not integrated",
    }
    if release_path.exists():
        release = selected_tests(
            ["tests/v1/test_release_acceptance.py"], phase, data, tag="release"
        )
    statuses = {session["status"], required["status"], bootstrap["status"], release["status"]}
    status = "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "INCOMPLETE" in statuses else "PASS"
    return {
        "status": status,
        "sessions": session,
        "required_integration": required,
        "required_integration_counts": summarize_required_nodes(required),
        "bootstrap_coverage": bootstrap,
        "release": release,
        "suite_registry": {
            "audit_core_cases": AUDIT_CORE_CASES,
            "additional_recovery_cases": ADDITIONAL_RECOVERY_CASES,
            "real_password_regression": CREDENTIAL_ROTATION_REGRESSION,
            "optional_cases_deferred": 13,
            "optional_disposition": OPTIONAL_INTEGRATION_DISPOSITIONS[
                "tests/v1/test_short_encoder_sql.py"
            ],
        },
    }


def verify(run_id, flow):
    start = time.monotonic()
    data = load(run_id)
    if data["state"] != "running":
        raise ValueError("Start the unique V1 runtime first")
    output = directory(run_id) / ("evidence-" + uuid.uuid4().hex[:10])
    output.mkdir(mode=0o700)
    from scripts.dev import v1_provenance

    try:
        moto = moto_python()
    except ValueError:
        moto = sys.executable
    provenance = v1_provenance.collect(data, moto)
    manifest = {
        "run_id": run_id,
        # Flat copies keep older readers working; provenance holds the bound detail.
        "source_sha": provenance["source"]["sha"],
        "tracked_dirty": provenance["source"]["dirty"],
        **provenance,
        "browser_requested": browser_requested(),
        "integration_selection": {
            "scope": "pytest tests/v1 -m integration",
            "separate_flow_suites": list(EXISTING_INTEGRATION_SUITES),
            "optional_dispositions": OPTIONAL_INTEGRATION_DISPOSITIONS,
        },
        "flows": {},
    }
    for name in ["a", "b", "c"] if flow == "all" else [flow]:
        phase = output / name
        phase.mkdir()
        try:
            result = run_flow(name, data, phase)
        except Exception as error:
            # Keep DSNs, SDK URLs and transport stderr out of selected evidence.
            result = {
                "status": "FAIL",
                "error_type": type(error).__name__,
                "reason": "Local verification failed; inspect private runtime/test logs",
                "failed_tests": [
                    {
                        "id": f"flow {name} harness",
                        "kind": "run",
                        "message": f"{type(error).__name__} before any test result",
                    }
                ],
            }
        manifest["flows"][name] = result
        save(output / "manifest.json", manifest)
    statuses = [r["status"] for r in manifest["flows"].values()]
    manifest["status"] = (
        "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "INCOMPLETE" in statuses else "PASS"
    )
    browser_ran = manifest["flows"].get("b", {}).get("browser", {})
    # Complete local acceptance needs every flow and the real browser leg, and is still
    # an emulated-boundary result: it is never a cloud PASS.
    manifest["complete_v1_acceptance"] = (
        "PASS"
        if flow == "all"
        and manifest["status"] == "PASS"
        and isinstance(browser_ran, dict)
        and browser_ran.get("status") == "PASS"
        else "NOT_RUN"
    )
    manifest["cloud_acceptance"] = "NOT_RUN"
    manifest["failed_tests"] = failed_tests(manifest["flows"])
    report_failures(manifest["failed_tests"])
    if os.environ.get("V1_COVERAGE") == "1":
        manifest["coverage"] = combine_coverage(output, run_id)
    manifest["elapsed_seconds"] = round(time.monotonic() - start, 3)
    save(output / "manifest.json", manifest)
    return {
        "status": manifest["status"],
        "manifest": str(output / "manifest.json"),
        "complete_v1_acceptance": manifest["complete_v1_acceptance"],
        "failed_tests": [f"{item['flow']}: {item['id']}" for item in manifest["failed_tests"]],
    }
