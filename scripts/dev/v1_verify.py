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


def local_environment(data):
    """Explicit local-only child environment; no inherited AWS profiles/credentials."""
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
    endpoint = urlsplit(data["endpoint_url"]).netloc
    env.update(
        MEDIA_RUNTIME_MODE="lambda",
        MEDIA_STORAGE_CREDENTIAL_MODE="lambda",
        MEDIA_MINIO_ENDPOINT=endpoint,
        MEDIA_MINIO_USE_SSL="false",
        MEDIA_MINIO_PUBLIC_ENDPOINT=endpoint,
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
    for owner in ("media", "processing"):
        env[owner.upper() + "_POSTGRES_DSN"] = (
            f"postgresql+asyncpg://{owner}_runtime:local_v1_{owner}"
            f"@127.0.0.1:{data['postgres_port']}/{owner}_db"
        )
    return env


COVERAGE_RC = """[run]
branch = True
parallel = True
relative_files = True
patch = subprocess
source =
{sources}
"""


def selected_tests(patterns, output, data, *, tag="tests", timeout=180):
    tests = sorted({str(p.relative_to(ROOT)) for pattern in patterns for p in ROOT.glob(pattern)})
    if not tests:
        return {"status": "INCOMPLETE", "reason": "Owning acceptance tests not integrated"}
    report = output / f"{tag}.xml"
    env = local_environment(data)
    # Tests that can capture a screenshot or page state on failure write it here. Only
    # redacted files are meant to leave the runtime directory (see the CI artifact step).
    env["V1_FAILURE_DIR"] = str(output / f"failure-{tag}")
    command = [sys.executable, "-m", "pytest", *tests, "-q", "--junitxml", str(report)]
    if os.environ.get("V1_COVERAGE") == "1":
        # The encoder, alembic and watchdog run as child processes, so measure those too
        # (patch = subprocess). Each invocation writes its own fragment for later combining.
        from scripts.dev.common import packages

        rc = output / f"coveragerc-{tag}"
        rc.write_text(COVERAGE_RC.format(sources="\n".join("    " + p for p in packages())))
        env["COVERAGE_FILE"] = str(output / f".coverage.{tag}")
        command += [f"--cov-config={rc}", "--cov-report=", "--cov-fail-under=0"]
        command += [f"--cov={name}" for name in packages()]
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
        # Counts alone cannot say which test flaked, so name the failing ones.
        "failed_tests": failed,
        "skipped_tests": skipped,
        **({"reason": reason} if reason else {}),
    }


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
        # classname "tests.v1.test_browser_acceptance" -> tests/v1/test_browser_acceptance.py
        identity = f"{case.get('classname', '').replace('.', '/')}.py::{case.get('name', '')}"
        for outcome in case:
            if outcome.tag in {"failure", "error"}:
                message = outcome.get("message") or outcome.text or ""
                failed.append(
                    {"id": identity, "kind": outcome.tag, "message": first_lines(message)}
                )
            elif outcome.tag == "skipped":
                skipped.append(identity)
    return counts, failed, skipped


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

    from scripts.dev.common import fingerprint, packages

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
        json.dumps({"fingerprint": fingerprint(), "tier": "v1-integration", "packages": packages()})
        + "\n"
    )
    return {"status": "COLLECTED", "fragments": len(fragments), "tier": "v1-integration"}


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
    session = selected_tests(["tests/v1/test_session.py"], phase, data, tag="session")
    release_path = ROOT / "tests/v1/test_release_acceptance.py"
    result = {
        "status": "INCOMPLETE",
        "sessions": session,
        "release": "NOT_RUN: owning real SQL release acceptance not integrated",
    }
    if release_path.exists():
        release = selected_tests(
            ["tests/v1/test_release_acceptance.py"], phase, data, tag="release"
        )
        result.update(
            release=release,
            status="PASS" if session["status"] == release["status"] == "PASS" else "FAIL",
        )
    return result


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
