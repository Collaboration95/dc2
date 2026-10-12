"""Optional real TLS with a controlled public peer, never a production service."""

import json
import os
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from publisher.client import PublicClient, PublisherError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PUBLISHER_HTTPS_TEST") != "1",
        reason="Explicit opt-in for a loopback HTTPS peer",
    ),
]


def test_explicit_ca_secure_cookie_restart_and_untrusted_rejection(tmp_path):
    cert = tmp_path / "peer.crt"
    key = tmp_path / "peer.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    calls = []
    owner = "22222222-2222-4222-8222-222222222222"

    class Peer(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log cookies, credentials or signed URLs.

        def do_POST(self):
            calls.append((self.path, self.headers.get("Cookie")))
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert set(data) == {"email", "password"}
            self.send_response(200)
            self.send_header("Set-Cookie", "access_token=fixture-only; Path=/api; Secure; HttpOnly")
            self.end_headers()
            self.wfile.write(
                json.dumps({"id": owner, "email": data["email"], "role": "user"}).encode()
            )

        def do_GET(self):
            calls.append((self.path, self.headers.get("Cookie")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"id": owner}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Peer)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"https://localhost:{server.server_port}/api"
    try:
        first = PublicClient(base, tmp_path / "cookies", str(cert), timeout=2)
        try:
            first.authenticate("login", f"{owner}@example.com", "fixture-only")
        finally:
            first.close()
        second = PublicClient(base, tmp_path / "cookies", str(cert), timeout=2)
        try:
            assert second.identity() == owner
        finally:
            second.close()
        untrusted = PublicClient(base, tmp_path / "untrusted-cookies", timeout=2)
        try:
            with pytest.raises(PublisherError, match="Transport failed"):
                untrusted.identity()
        finally:
            untrusted.close()
        assert calls == [("/api/auth/login", None), ("/api/auth/me", "access_token=fixture-only")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
