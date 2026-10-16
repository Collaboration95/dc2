"""No-service rules for stable work IDs, repair timing bounds and owner-scoped sources."""

import ast
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from processing import messaging
from processing.config import Settings
from processing.recovery import CLEANUP_CAP_SECONDS, cleanup_delay

ROOT = Path(__file__).resolve().parents[2]
V1_ENTRYPOINTS = [
    "media.lambda_handler",
    "media.handlers",
    "media.main",
    "processing.lambda_handler",
    "processing.handlers",
    "processing.worker.sqs",
    "processing.v1_worker",
    "processing.recovery_v1",
    "media.recovery_v1",
]
# Modules that import (or build) the Redis/RQ or HTTP-peer machinery.
FORBIDDEN = [
    "redis",
    "rq",
    "processing.queue",
    "processing.main",
    "processing.worker.cloud",
    "media.api.jobs",
    "media.api.hls",
    "media.api.source_access",
    "media.recovery",
]


def source(owner, asset, *, key=None):
    return {
        "bucket": "sources",
        "key": key or f"sources/{owner}/{asset}/source",
        "version_id": "v1",
        "sha256": "a" * 64,
        "size_bytes": 10,
        "content_type": "video/mp4",
    }


def test_work_message_id_is_stable_per_attempt_and_version():
    attempt = uuid4()
    assert messaging.work_message_id(attempt, 3) == messaging.work_message_id(attempt, 3)
    assert messaging.work_message_id(attempt, 3) != messaging.work_message_id(attempt, 4)
    assert messaging.work_message_id(attempt, 3) != messaging.work_message_id(uuid4(), 3)


def test_first_repair_resend_falls_inside_the_120_second_lost_work_gate():
    # The grace before the first look plus one repair tick must stay within 120s.
    assert messaging.REPAIR_BASE_SECONDS + 60 <= 120
    assert messaging.repair_delay(0) == messaging.REPAIR_BASE_SECONDS


def test_repair_backoff_grows_and_is_capped_so_an_idle_attempt_does_not_flood():
    delays = [messaging.repair_delay(count) for count in range(12)]
    assert delays == sorted(delays)
    assert delays[-1] == messaging.REPAIR_CAP_SECONDS
    # An hour of idling costs well under the old one-per-minute rate.
    elapsed, sends = 0, 0
    while elapsed < 3600:
        elapsed += messaging.repair_delay(sends)
        sends += 1
    assert sends <= 8


def test_cleanup_backoff_grows_to_an_hourly_cap():
    assert [cleanup_delay(n) for n in (1, 2, 3)] == [60, 120, 240]
    assert cleanup_delay(50) == CLEANUP_CAP_SECONDS


def test_lease_ceiling_keeps_interrupted_work_inside_300_seconds():
    field = Settings.model_fields["lease_seconds"]
    ceiling = next(m.le for m in field.metadata if hasattr(m, "le"))
    # Worst case: lease expires, then one 60s repair tick marks it failed.
    assert ceiling + 60 <= 300


@pytest.mark.parametrize("prefix", ["sources", "staging"])
def test_owner_scoped_source_keys_are_accepted(prefix):
    owner, asset = str(uuid4()), str(uuid4())
    messaging.assert_owned_source(
        {"owner_id": owner, "source": source(owner, asset, key=f"{prefix}/{owner}/{asset}/source")}
    )
    messaging.assert_owned_source({"owner_id": owner, "source": None})


@pytest.mark.parametrize(
    "key",
    [
        "owned/source",
        "sources/{other}/{asset}/source",
        "sources/{owner}/../{other}/{asset}/source",
        "outputs/{owner}/{asset}/source",
        "sources/{owner}x/{asset}/source",
        "sources\\{owner}/{asset}/source",
    ],
)
def test_source_outside_the_owner_prefix_is_rejected(key):
    owner, other, asset = str(uuid4()), str(uuid4()), str(uuid4())
    with pytest.raises(ValueError, match="owner's prefix"):
        messaging.assert_owned_source(
            {
                "owner_id": owner,
                "source": source(
                    owner, asset, key=key.format(owner=owner, other=other, asset=asset)
                ),
            }
        )


@pytest.mark.parametrize("module", V1_ENTRYPOINTS)
def test_v1_entrypoints_never_import_redis_rq_or_legacy_peer_wiring(module):
    code = (
        f"import sys; import {module}; "
        f"bad = [m for m in {FORBIDDEN!r} if m in sys.modules]; "
        "assert not bad, bad"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": ""},
    )
    assert result.returncode == 0, result.stderr


def test_v1_runtime_modules_never_reach_the_redis_only_settings_gates():
    # require_worker/require_recovery demand a Redis URL. V1 uses require_storage only,
    # and no V1 module may read the Redis or peer-token settings.
    files = [
        "processing/worker/sqs.py",
        "processing/worker/finite.py",
        "processing/v1_worker.py",
        "processing/handlers.py",
        "processing/recovery_v1.py",
        "processing/messaging.py",
        "processing/v1_api.py",
        "media/handlers.py",
        "media/recovery_v1.py",
    ]
    banned = {"require_worker", "require_recovery", "redis_url", "source_service_token"}
    for name in files:
        tree = ast.parse((ROOT / name).read_text())
        used = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute | ast.Name)
        }
        assert not banned & used, (name, banned & used)
    # The V1 worker entry validates storage credentials only.
    assert "require_storage" in (ROOT / "processing/worker/sqs.py").read_text()
