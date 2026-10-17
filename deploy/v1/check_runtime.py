"""Execute inside the exact built image; retain output with its config ID.

Imports every owning executable graph with network access denied. This checks
packaging and importability, not database, SQS or deployed Lambda correctness.
"""

import importlib
import importlib.metadata
import importlib.util
import json
import platform
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

ENTRYPOINTS = {
    "media": {
        "media.lambda_handler": ("handler", "authorizer"),
        "media.handlers": ("result_handler", "repair_handler"),
    },
    "processing": {
        "processing.lambda_handler": ("handler",),
        "processing.handlers": (
            "command_handler",
            "repair_handler",
            "ecs_handler",
            "s3_handler",
            "launcher_handler",
        ),
    },
    "worker": {
        "processing.v1_worker": ("main",),
        "processing.worker.sqs": ("main", "run", "execute_message"),
        "processing.worker.source": ("SourceStore",),
        "processing.worker.tasks": ("pipeline",),
        # The opt-in Lambda short encoder (V2, #93) runs from this same image.
        "processing.handlers": ("short_encoder_handler",),
        "processing.short_encoder": ("invoke",),
    },
}


def no_network(*args, **kwargs):
    raise RuntimeError("Artifact import proof must not perform network I/O")


def check(kind, owner):
    assert kind in {"lambda-api", "finite-worker"}, "Unknown runtime kind"
    assert owner in ENTRYPOINTS, "Explicit owning image required"
    assert (owner == "worker") == (kind == "finite-worker"), "Wrong image owner/kind"
    installed = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
    }
    assert not {"redis", "rq"} & installed.keys(), "Redis/RQ must be absent from V1 images"
    assert all(importlib.util.find_spec(name) is None for name in ("redis", "rq")), (
        "Redis/RQ importable despite absent distribution"
    )
    assert bool(shutil.which("ffmpeg")) == (kind == "finite-worker"), "Wrong FFmpeg placement"
    assert bool(shutil.which("ffprobe")) == (kind == "finite-worker"), "Wrong FFprobe placement"
    assert "boto3" in installed
    # Every image is invoked by Lambda except the worker's primary role, which also is, opt-in.
    assert "awslambdaric" in installed
    ca = Path("/opt/rds/global-bundle.pem")
    assert ca.is_file(), "Verified RDS bundle missing"
    ssl.create_default_context(cafile=str(ca))  # Parse actual trusted bundle.
    # Source packages are deliberately copied, rather than pip-installing legacy app.
    sys.path.insert(0, str(Path.cwd()))
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    imports = {}
    for module_name, exports in ENTRYPOINTS[owner].items():
        module = importlib.import_module(module_name)
        assert Path(module.__file__).resolve().is_relative_to(Path("/app")), (
            "Executable graph must resolve to owning source in image"
        )
        for export in exports:
            assert callable(getattr(module, export)), f"Missing callable {module_name}.{export}"
        imports[module_name] = {"file": module.__file__, "callables": list(exports)}
    assert not any(n.split(".")[0] in {"redis", "rq"} for n in sys.modules), (
        "Executable graph imported Redis/RQ"
    )
    peer = "processing" if owner == "media" else "media"
    assert importlib.util.find_spec(peer) is None, "Opposite domain package present"
    binaries = {}
    if kind == "finite-worker":
        for binary in ("ffmpeg", "ffprobe"):
            result = subprocess.run(
                [binary, "-version"], capture_output=True, text=True, check=True, timeout=15
            )
            binaries[binary] = result.stdout.splitlines()[0]
    return {
        "runtime_kind": kind,
        "owner": owner,
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "runtime_contents": {"redis": False, "rq": False, "ffmpeg": kind == "finite-worker"},
        "imports": imports,
        "network_during_import": "denied",
        "rds_bundle": "parsed",
        "installed_packages": dict(sorted(installed.items())),
        "binaries": binaries,
    }


if __name__ == "__main__":
    print(json.dumps(check(sys.argv[1], sys.argv[2]), sort_keys=True))
