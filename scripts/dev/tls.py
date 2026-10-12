"""Generate a development CA and localhost server certificate inside this checkout."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_directory(run_id):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", run_id):
        raise ValueError("Run ID must contain 1–64 letters, numbers, dots, dashes or underscores.")
    return ROOT / ".local/runs" / run_id


def ensure_tls(run_id, renew=False):
    folder = run_directory(run_id) / "tls"
    folder.mkdir(parents=True, exist_ok=True)
    required = [folder / name for name in ("ca.crt", "ca.key", "server.crt", "server.key")]
    if all(p.exists() for p in required) and not renew:
        for name in ("ca.crt", "server.crt"):
            subprocess.run(
                ["openssl", "x509", "-in", str(folder / name), "-checkend", "0", "-noout"],
                check=True,
                capture_output=True,
            )
        return folder
    if any(p.exists() for p in required) and not renew:
        raise RuntimeError(f"Incomplete local TLS identity at {folder}; use --renew to regenerate")
    config = folder / "ca.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\nprompt=no\n"
        "[dn]\nCN=dc2 local development CA\n[v3_ca]\n"
        "basicConstraints=critical,CA:TRUE\n"
        "keyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n"
    )
    extension = folder / "server.ext"
    extension.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid,issuer\n"
        "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1\n"
    )
    commands = [
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-days",
            "7",
            "-config",
            str(config),
            "-keyout",
            str(folder / "ca.key"),
            "-out",
            str(folder / "ca.crt"),
        ],
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(folder / "server.key"),
            "-out",
            str(folder / "server.csr"),
        ],
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(folder / "server.csr"),
            "-CA",
            str(folder / "ca.crt"),
            "-CAkey",
            str(folder / "ca.key"),
            "-CAcreateserial",
            "-days",
            "7",
            "-sha256",
            "-extfile",
            str(extension),
            "-out",
            str(folder / "server.crt"),
        ],
    ]
    previous = os.umask(0o077)
    try:
        for command in commands:
            subprocess.run(command, check=True, capture_output=True)
    finally:
        os.umask(previous)
    for path in required:
        path.chmod(0o600 if path.suffix == ".key" else 0o644)
    subprocess.run(
        ["openssl", "verify", "-CAfile", str(folder / "ca.crt"), str(folder / "server.crt")],
        check=True,
        capture_output=True,
    )
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dc2")
    parser.add_argument("--renew", action="store_true")
    args = parser.parse_args()
    folder = ensure_tls(args.run_id, args.renew)
    print(
        json.dumps(
            {"ca_file": str(folder / "ca.crt"), "server_certificate": str(folder / "server.crt")}
        )
    )


if __name__ == "__main__":
    main()
