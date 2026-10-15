"""Actual-domain local acceptance helpers; only Gateway/S3/SQS service legs emulate AWS."""

import asyncio
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

from scripts.dev.v1_gateway import server
from scripts.dev.v1_runtime import ROOT, load
from scripts.dev.v1_verify import local_environment, provision_local_objects, sdk


@contextmanager
def app_runtime(run_id):
    """Real HTTPS clients, actual handlers, native SQL, Moto S3 reverse TLS leg."""
    data = load(run_id)
    data["resources"] = provision_local_objects(data)
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
    http = thread = None
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
        import media.lambda_handler
        import processing.lambda_handler

        from scripts.dev.v1_gateway import Gateway

        http = server(
            Gateway(
                media.lambda_handler.handler,
                processing.lambda_handler.handler,
                media.lambda_handler.authorizer,
            )
        )
        http.socket = context.wrap_socket(http.socket, server_side=True)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        yield {
            "data": data,
            "env": env,
            "ca": str(tls / "server.crt"),
            "url": f"https://127.0.0.1:{http.server_port}",
            "observations": observations,
        }
    finally:
        if http:
            http.shutdown()
            http.server_close()
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


def encode_one(runtime):
    """Run the actual essential watchdog and finite SQS subprocess, one encode."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "processing.v1_worker",
            "--deadline-epoch",
            str(time.time() + 60),
            "--name",
            "local-acceptance",
            "--max-empty-polls",
            "1",
        ],
        cwd=ROOT,
        env=runtime["env"],
        capture_output=True,
        text=True,
        timeout=70,
    )
    assert result.returncode == 0, f"Actual finite encoder exited {result.returncode}"
