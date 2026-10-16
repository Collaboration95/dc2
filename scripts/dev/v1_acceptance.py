"""Actual-domain local acceptance helpers; only Gateway/S3/SQS service legs emulate AWS."""

import asyncio
import http.client
import json
import os
import ssl
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from scripts.dev.v1_gateway import server
from scripts.dev.v1_runtime import ROOT, load
from scripts.dev.v1_verify import local_environment, provision_local_objects, sdk


@contextmanager
def app_runtime(run_id):
    """Real HTTPS clients, actual handlers, native SQL, Moto S3 reverse TLS leg."""
    data = load(run_id)
    data["resources"] = provision_local_objects(data, purge=True)
    env = local_environment(data)
    tls = Path(data["root"]) / ".cache/v1-runtime" / run_id / "tls"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls / "server.crt", tls / "server.key")
    upstream = urlsplit(data["endpoint_url"])
    observations = {"storage_cookie_headers": 0}

    class StorageProxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def invoke(self):
            if self.headers.get("Cookie"):
                observations["storage_cookie_headers"] += 1
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            connection = http.client.HTTPConnection(upstream.hostname, upstream.port, timeout=20)
            try:
                connection.request(self.command, self.path, body=body, headers=dict(self.headers))
                reply = connection.getresponse()
                payload = reply.read()
                self.send_response(reply.status)
                for key, value in reply.getheaders():
                    if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            finally:
                connection.close()

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_OPTIONS = invoke

    storage = ThreadingHTTPServer(("127.0.0.1", 0), StorageProxy)
    storage.socket = context.wrap_socket(storage.socket, server_side=True)
    storage_thread = threading.Thread(target=storage.serve_forever, daemon=True)
    storage_thread.start()
    env.update(
        MEDIA_MINIO_PUBLIC_ENDPOINT=f"127.0.0.1:{storage.server_port}",
        MEDIA_MINIO_PUBLIC_USE_SSL="true",
        PROCESSING_STORAGE_CREDENTIAL_MODE="static",
        PROCESSING_MINIO_ENDPOINT=upstream.netloc,
        PROCESSING_MINIO_USE_SSL="false",
        PROCESSING_MINIO_REGION="ap-southeast-1",
        PROCESSING_MINIO_ACCESS_KEY="testing",
        PROCESSING_MINIO_SECRET_KEY="testing",
        PROCESSING_MINIO_OUTPUT_BUCKET=data["resources"]["buckets"]["output"],
        PROCESSING_FFMPEG_PRESET="ultrafast",
        PROCESSING_HEARTBEAT_SECONDS="1",
        PROCESSING_LEASE_SECONDS="30",
    )
    for owner in ("media", "processing"):
        env[owner.upper() + "_MIGRATION_DSN"] = (
            f"postgresql+asyncpg://{owner}_migrator:local_v1_{owner}_migrate"
            f"@127.0.0.1:{data['postgres_port']}/{owner}_db"
        )
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(env)
    front = thread = None
    try:
        # Actual migration history, never metadata.create_all or runtime DDL.
        for owner in ("media", "processing"):
            migrate(owner, env)
        from media.config import get_settings as media_settings
        from processing.config import get_settings as processing_settings

        media_settings.cache_clear()
        processing_settings.cache_clear()
        # configured_gateway would replace the public TLS storage endpoint;
        # import handlers after the explicit env above instead.
        import importlib

        import media.authorizer
        import media.lambda_handler
        import processing.lambda_handler
        from scripts.dev.v1_gateway import Gateway

        # The handlers build their app (and storage client) at import. A second runtime in the
        # same process has a new storage endpoint, so rebuild them rather than reuse the first.
        for module in (media.authorizer, media.lambda_handler, processing.lambda_handler):
            importlib.reload(module)

        front = server(
            Gateway(
                media.lambda_handler.handler,
                processing.lambda_handler.handler,
                media.lambda_handler.authorizer,
            )
        )
        front.socket = context.wrap_socket(front.socket, server_side=True)
        thread = threading.Thread(target=front.serve_forever, daemon=True)
        thread.start()
        yield {
            "data": data,
            "env": env,
            "ca": str(tls / "server.crt"),
            "url": f"https://127.0.0.1:{front.server_port}",
            "observations": observations,
        }
    finally:
        if front:
            front.shutdown()
            front.server_close()
            thread.join(timeout=2)
        storage.shutdown()
        storage.server_close()
        storage_thread.join(timeout=2)
        os.environ.clear()
        os.environ.update(previous)


def migrate(owner, env):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", f"{owner}/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode:
        raise AssertionError(f"{owner} owning migration failed ({result.returncode})")


def alembic_command(owner, env, *arguments):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", f"{owner}/alembic.ini", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode:
        raise AssertionError(f"{owner} alembic {arguments[0]} failed ({result.returncode})")
    return result.stdout


def script_revisions(owner):
    """(previous, head) from the owner's migration scripts, not from the database."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / owner / "alembic.ini")))
    head = script.get_current_head()
    return script.get_revision(head).down_revision, head


def step_back(owner, env):
    """Really undo the newest owner migration so a later upgrade has work to do."""
    alembic_command(owner, env, "downgrade", "-1")


def sql_fetch(runtime, owner, query, *arguments):
    """One short runtime-role read; connections never outlive the call."""

    async def read():
        import asyncpg

        connection = await asyncpg.connect(
            host="127.0.0.1",
            port=runtime["data"]["postgres_port"],
            user=owner + "_runtime",
            password="local_v1_" + owner,
            database=owner + "_db",
            ssl=ssl.create_default_context(cafile=runtime["ca"]),
            timeout=5,
        )
        try:
            return await connection.fetch(query, *arguments)
        finally:
            await connection.close()

    return asyncio.run(read())


def short_video(path, seconds=1):
    """A tiny audiovisual MP4 the inherited engine can encode in about a second."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=160x90:rate=10:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return path


async def factory_for(owner):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if owner == "media":
        from media.config import get_settings

        settings = get_settings()
        ca = settings.postgres_ssl_ca
    else:
        from processing.config import get_settings

        settings = get_settings()
        ca = settings.database_ca_file
    engine = create_async_engine(
        settings.postgres_dsn, connect_args={"ssl": ssl.create_default_context(cafile=ca)}
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def pump(runtime, *, results=True, reverse=False):
    """Execute actual durable publishers/consumers; emulate only SQS mapping ACK."""

    async def invoke():
        from delivery.runtime import queue_urls
        from delivery.sqs import SQS
        from media.handlers import consume_results
        from media.messaging import publish_commands
        from processing.messaging import consume_commands, publish_outbox

        media_engine, media_factory = await factory_for("media")
        engine, factory = await factory_for("processing")
        client = sdk(runtime["data"], "sqs")
        queues = runtime["data"]["resources"]["queues"]
        media_transport = SQS(queue_urls(), producer="media", client=client)
        processing_transport = SQS(queue_urls(), producer="processing", client=client)
        try:
            await publish_commands(
                media_factory, media_transport, limit=100, deadline=time.monotonic() + 20
            )
            messages = client.receive_message(
                QueueUrl=queues["commands"], MaxNumberOfMessages=10, WaitTimeSeconds=0
            ).get("Messages", [])
            if messages:
                event = {
                    "Records": [{"messageId": m["MessageId"], "body": m["Body"]} for m in messages]
                }
                # Duplicate delivery in same batch proves the real SQL inbox path.
                event["Records"] += event["Records"][:1]
                reply = await consume_commands(event, factory)
                assert not reply["batchItemFailures"], "Actual command handler rejected delivery"
                for message in messages:
                    client.delete_message(
                        QueueUrl=queues["commands"], ReceiptHandle=message["ReceiptHandle"]
                    )
            await publish_outbox(
                factory, processing_transport, limit=100, deadline=time.monotonic() + 20
            )
            if results:
                messages = client.receive_message(
                    QueueUrl=queues["results"], MaxNumberOfMessages=10, WaitTimeSeconds=0
                ).get("Messages", [])
                if reverse:
                    messages.sort(
                        key=lambda m: json.loads(m["Body"])["state_version"], reverse=True
                    )
                if messages:
                    event = {
                        "Records": [
                            {"messageId": m["MessageId"], "body": m["Body"]} for m in messages
                        ]
                    }
                    event["Records"] += event["Records"][:1]
                    reply = await consume_results(event, media_factory)
                    assert not reply["batchItemFailures"], "Actual result handler rejected delivery"
                    for message in messages:
                        client.delete_message(
                            QueueUrl=queues["results"], ReceiptHandle=message["ReceiptHandle"]
                        )
        finally:
            await engine.dispose()
            await media_engine.dispose()

    asyncio.run(invoke())


def encode_one(runtime, *, expect=0, **environment):
    """Run the actual essential watchdog and finite SQS subprocess, one encode.

    ``environment`` overrides the child's variables, to inject a transient fault such as an
    unwritable output bucket without touching the persisted runtime.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "processing.v1_worker",
            "--deadline-epoch",
            str(time.time() + 60),
            "--name",
            # attempt_tasks.task_name is unique because a real task ARN never repeats. A fixed
            # name made every second run against the same SQL volume fail as "already bound".
            f"local-acceptance-{uuid4().hex[:12]}",
            "--max-empty-polls",
            "1",
        ],
        cwd=ROOT,
        env={**runtime["env"], **environment},
        capture_output=True,
        text=True,
        timeout=70,
    )
    # The private pytest log keeps the child's tail so a failed run is diagnosable.
    assert result.returncode == expect, (
        f"Actual finite encoder exited {result.returncode}\n{result.stderr[-3000:]}"
    )
