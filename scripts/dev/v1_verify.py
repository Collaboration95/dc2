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
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

from scripts.dev.v1_runtime import ROOT, directory, load, run, save


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
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )


async def sql_probe(data, probe_id):
    import asyncpg

    port = data["postgres_port"]
    tables = []
    for owner in ("media", "processing"):
        params = {"host": "127.0.0.1", "port": port, "database": owner + "_db", "timeout": 5}
        connection = await asyncpg.connect(
            **params, user=owner + "_migrator", password=f"local_v1_{owner}_migrate"
        )
        try:
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
        "queued_rows": "retained",
    }


def objects_and_encode(data, output, probe_id):
    from media_engine.hls import build_ladder_command
    from media_engine.operations import build_edit_command

    s3, sqs = sdk(data, "s3"), sdk(data, "sqs")
    bucket = "dc2-v1-" + data["run_id"]
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        s3.create_bucket(
            Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"}
        )
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    queues = {
        name: sqs.create_queue(QueueName=f"{data['project']}-{name}")["QueueUrl"]
        for name in ("commands", "work", "results")
    }
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
    message = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=1, VisibilityTimeout=0)[
        "Messages"
    ][0]
    assert json.loads(message["Body"]) == payload
    duplicate = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=1)["Messages"][0]
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
    s3.put_object(Bucket=bucket, Key=f"outputs/{probe_id}.mp4", Body=encoded.read_bytes())
    ranged = s3.get_object(Bucket=bucket, Key=f"outputs/{probe_id}.mp4", Range="bytes=0-31")
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
        V1_RUNTIME_CONFIG=str(directory(data["run_id"]) / "runtime.json"),
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_SESSION_TOKEN="testing",
        AWS_REGION="ap-southeast-1",
        AWS_DEFAULT_REGION="ap-southeast-1",
        AWS_EC2_METADATA_DISABLED="true",
        AWS_CONFIG_FILE="/dev/null",
        AWS_SHARED_CREDENTIALS_FILE="/dev/null",
        AWS_ENDPOINT_URL=data["endpoint_url"],
        SQS_ENDPOINT_URL=data["endpoint_url"],
        S3_ENDPOINT_URL=data["endpoint_url"],
    )
    for owner in ("media", "processing"):
        env[owner.upper() + "_POSTGRES_DSN"] = (
            f"postgresql+asyncpg://{owner}_runtime:local_v1_{owner}"
            f"@127.0.0.1:{data['postgres_port']}/{owner}_db"
        )
    return env


def selected_tests(patterns, output, data):
    tests = sorted({str(p.relative_to(ROOT)) for pattern in patterns for p in ROOT.glob(pattern)})
    if not tests:
        return {"status": "INCOMPLETE", "reason": "Owning acceptance tests not integrated"}
    report = output / "tests.xml"
    env = local_environment(data)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q", "--junitxml", str(report)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    (output / "pytest-private.log").write_text(result.stdout + result.stderr)
    from xml.etree import ElementTree as ET

    if not report.exists():
        return {"status": "FAIL", "reason": "Test runner did not produce an execution report"}
    root = ET.parse(report).getroot()
    suites = list(root) if root.tag == "testsuites" else [root]
    counts = {
        k: sum(int(s.attrib.get(k, 0)) for s in suites)
        for k in ("tests", "errors", "failures", "skipped")
    }
    status = (
        "PASS"
        if (result.returncode == 0 and counts["tests"] > 0 and not counts["skipped"])
        else "INCOMPLETE"
        if result.returncode == 0
        else "FAIL"
    )
    return {"status": status, "counts": counts, "junit_sha256": digest(report), "tests": tests}


def verify(run_id, flow):
    start = time.monotonic()
    data = load(run_id)
    if data["state"] != "running":
        raise ValueError("Start the unique V1 runtime first")
    output = directory(run_id) / ("evidence-" + uuid.uuid4().hex[:10])
    output.mkdir(mode=0o700)
    manifest = {
        "run_id": run_id,
        "source_sha": run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip(),
        "tracked_dirty": bool(
            run(
                ["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True
            ).stdout.strip()
        ),
        "flows": {},
        "boundaries": {
            "sql_ffmpeg": "real",
            "s3_sqs": "Moto HTTP emulation",
            "gateway_lambda": "NOT_RUN",
            "AWS": "NOT_RUN",
        },
    }
    for name in ["a", "b", "c"] if flow == "all" else [flow]:
        phase = output / name
        phase.mkdir()
        try:
            if name == "a":
                probe_id = uuid.uuid4()
                sql = asyncio.run(sql_probe(data, probe_id))
                objects = objects_and_encode(data, phase, probe_id)
                result = {
                    "status": "PASS",
                    "scope": "dependency/engine seam only",
                    **sql,
                    **objects,
                }
            elif name == "b":
                # A dedicated marker-owned suite must cover browser AND Publisher;
                # do not infer full acceptance from generic route unit tests.
                result = selected_tests(["tests/v1/test_workflow_acceptance.py"], phase, data)
            else:
                session = selected_tests(["tests/v1/test_session.py"], phase, data)
                release_path = ROOT / "tests/v1/test_release_acceptance.py"
                result = {
                    "status": "INCOMPLETE",
                    "sessions": session,
                    "release": "NOT_RUN: owning real SQL release acceptance not integrated",
                }
                if release_path.exists():
                    release = selected_tests(["tests/v1/test_release_acceptance.py"], phase, data)
                    result.update(
                        release=release,
                        status="PASS"
                        if session["status"] == release["status"] == "PASS"
                        else "FAIL",
                    )
        except Exception as error:
            # Keep DSNs, SDK URLs and transport stderr out of selected evidence.
            result = {
                "status": "FAIL",
                "error_type": type(error).__name__,
                "reason": "Local verification failed; inspect private runtime/test logs",
            }
        manifest["flows"][name] = result
        save(output / "manifest.json", manifest)
    statuses = [r["status"] for r in manifest["flows"].values()]
    manifest["status"] = (
        "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "INCOMPLETE" in statuses else "PASS"
    )
    manifest["complete_v1_acceptance"] = (
        "NOT_RUN" if flow != "all" or manifest["status"] != "PASS" else "PASS"
    )
    manifest["elapsed_seconds"] = round(time.monotonic() - start, 3)
    save(output / "manifest.json", manifest)
    return {
        "status": manifest["status"],
        "manifest": str(output / "manifest.json"),
        "complete_v1_acceptance": manifest["complete_v1_acceptance"],
    }
