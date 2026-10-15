"""Execute inside the exact built image; retain output with its config ID."""

import importlib.metadata
import json
import shutil
import sys

kind = sys.argv[1]
installed = {
    d.metadata["Name"].lower().replace("_", "-") for d in importlib.metadata.distributions()
}
assert not {"redis", "rq"} & installed, "Redis/RQ must be absent from V1 images"
assert bool(shutil.which("ffmpeg")) == (kind == "finite-worker"), "Wrong FFmpeg placement"
assert "boto3" in installed
if kind == "lambda-api":
    assert "awslambdaric" in installed
print(
    json.dumps(
        {
            "runtime_kind": kind,
            "runtime_contents": {"redis": False, "rq": False, "ffmpeg": kind == "finite-worker"},
        }
    )
)
