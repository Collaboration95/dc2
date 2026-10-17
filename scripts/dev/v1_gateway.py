"""Loopback HTTP API Gateway v2 bridge to actual synchronous Lambda handlers.

This is emulation, not API Gateway/IAM/TLS evidence. It constructs authorizer
context only from Media's actual authorizer; public headers never supply it.
Import handlers only after configuring the explicit local runtime environment.
"""

import argparse
import base64
import importlib
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from scripts.dev.v1_runtime import load
from scripts.dev.v1_verify import local_environment


class Gateway:
    def __init__(self, media, processing, authorizer):
        self.handlers = {"media": media, "processing": processing}
        self.authorizer = authorizer
        # Paths (never queries, which carry signed URLs) of every 307 the Gateway answered.
        # A test reads this instead of waiting on the browser's own report of the redirect.
        self.redirects = []

    def invoke(self, method, target, headers, body=b""):
        parsed = urlsplit(target)
        parts = parsed.path.split("/")
        if len(parts) < 4 or parts[1] != "api" or parts[2] not in self.handlers:
            return {"statusCode": 404, "body": '{"detail":"unknown API route"}'}
        owner = parts[2]
        path = "/" + "/".join(parts[3:])
        lowered = {
            k.lower(): v
            for k, v in headers.items()
            if k.lower() not in {"x-owner-id", "x-role", "x-authorizer-context"}
        }
        context = {
            "accountId": "000000000000",
            "apiId": "local-v1",
            "domainName": "127.0.0.1",
            "stage": "$default",
            "requestId": str(uuid.uuid4()),
            "timeEpoch": int(time.time() * 1000),
            "http": {
                "method": method,
                "path": parsed.path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": lowered.get("user-agent", ""),
            },
        }
        event = {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": parsed.path,
            "rawQueryString": parsed.query,
            "headers": lowered,
            "requestContext": context,
            "body": base64.b64encode(body).decode(),
            "isBase64Encoded": True,
        }
        if lowered.get("cookie"):
            event["cookies"] = [c.strip() for c in lowered["cookie"].split(";") if c.strip()]
        public = (method == "GET" and path == "/health") or (
            owner == "media"
            and method == "POST"
            and path in {"/auth/register", "/auth/login", "/auth/logout"}
        )
        if not public:
            decision = self.authorizer(
                {
                    **event,
                    "type": "REQUEST",
                    "identitySource": [lowered.get("cookie", "")],
                    "routeArn": "arn:aws:execute-api:local:local:local/$default",
                },
                None,
            )
            if decision.get("isAuthorized") is not True:
                return {"statusCode": 401, "body": '{"detail":"not authenticated"}'}
            actor = decision.get("context")
            if not isinstance(actor, dict):
                return {"statusCode": 401, "body": '{"detail":"invalid authorizer context"}'}
            context["authorizer"] = {"lambda": actor}
        reply = self.handlers[owner](event, None)
        if reply.get("statusCode") == 307:
            self.redirects.append(parsed.path)
        return reply


def server(gateway, *, port=0):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            # Request lines may contain credentials or signed URLs. Never log them.
            pass

        def respond(self):
            try:
                size = int(self.headers.get("Content-Length", 0))
                if size < 0 or size > 2 * 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                    reply = {"statusCode": 413, "body": '{"detail":"bounded JSON API only"}'}
                    self.close_connection = True
                else:
                    reply = gateway.invoke(
                        self.command, self.path, dict(self.headers), self.rfile.read(size)
                    )
                body = reply.get("body", "")
                if reply.get("isBase64Encoded"):
                    payload = base64.b64decode(body, validate=True)
                else:
                    payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(int(reply.get("statusCode", 502)))
                for key, value in reply.get("headers", {}).items():
                    if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
                        self.send_header(key, str(value))
                for cookie in reply.get("cookies", []):
                    self.send_header("Set-Cookie", cookie)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except Exception:
                self.close_connection = True
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = respond

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def configured_gateway(run_id):
    data = load(run_id)
    if data["state"] != "running":
        raise ValueError("Start the exact V1 dependency namespace first")
    # Replace inherited AWS variables before loading SDK clients or settings.
    for key in list(os.environ):
        if key.startswith("AWS_"):
            del os.environ[key]
    os.environ.update(local_environment(data))
    media = importlib.import_module("media.lambda_handler")
    processing = importlib.import_module("processing.lambda_handler")
    return Gateway(media.handler, processing.handler, media.authorizer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    http = server(configured_gateway(args.run_id), port=args.port)
    print(
        json.dumps(
            {
                "endpoint": f"http://127.0.0.1:{http.server_port}",
                "mode": "emulated Gateway",
                "public_tls_iam": "NOT_RUN",
            }
        ),
        flush=True,
    )
    try:
        http.serve_forever()
    finally:
        http.server_close()


if __name__ == "__main__":
    main()
