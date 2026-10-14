import json
import subprocess
from pathlib import Path

import pytest

from scripts.aws.definitions import prepare_private_state

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "PRIVATE_SENTINEL_" + "x" * 48
ARN = "arn:aws:ssm:ap-southeast-1:000000000000:parameter/demo/"
CONFIG = {
    "mode": "plan",
    "account_id": "000000000000",
    "region": "ap-southeast-1",
    "environment_id": "aws2-demo",
    "source_bucket": "",
    "output_bucket": "",
    "operator_station": "station-a",
    "public_url": "https://d123.cloudfront.net",
    "parameter_arns": {"state_secrets": ARN + "state", "origin_gate": ARN + "origin"},
}
PUBLIC = {
    "DC2_STATE_PRIVATE_IP": "10.42.0.10",
    "DC2_VPC_RESOLVER": "10.42.0.2",
    "DC2_MEDIA_FQDN": "media.aws2-demo.internal",
    "DC2_PUBLIC_HOST": "d123.cloudfront.net",
    **{
        f"DC2_{owner.upper()}_IMAGE": f"{owner}:test@sha256:" + "a" * 64
        for owner in ["postgres", "redis", "nginx"]
    },
}


class FakeSSM:
    evidence_kind = "offline"

    def __init__(self, fail=False, wrong_arn=False):
        self.fail = fail
        self.wrong_arn = wrong_arn
        self.calls = []

    def call(self, service, operation, payload, *, deadline):
        self.calls.append((service, operation, payload, deadline))
        if self.fail:
            raise RuntimeError(SENTINEL)
        passwords = {
            name: SENTINEL
            for name in [
                "POSTGRES_PASSWORD",
                "MEDIA_MIGRATION_PASSWORD",
                "MEDIA_RUNTIME_PASSWORD",
                "PROCESSING_MIGRATION_PASSWORD",
                "PROCESSING_RUNTIME_PASSWORD",
                "REDIS_PASSWORD",
            ]
        }
        return {
            "Parameters": [
                {
                    "ARN": ARN + ("wrong" if self.wrong_arn else "state"),
                    "Type": "SecureString",
                    "Value": json.dumps(passwords),
                },
                {"ARN": ARN + "origin", "Type": "SecureString", "Value": SENTINEL},
            ]
        }


def test_scoped_private_injection_never_echoes_values(tmp_path):
    transport = FakeSSM()
    directory = tmp_path / "private"
    result = prepare_private_state(
        CONFIG, transport, directory, PUBLIC, deadline=110, clock=lambda: 100
    )
    assert result == {
        "evidence_kind": "offline",
        "files_private": True,
        "activation_status": "NOT_RUN",
    }
    assert SENTINEL not in json.dumps(result) + json.dumps(transport.calls)
    assert transport.calls[0][0:2] == ("ssm", "GetParameters")
    assert transport.calls[0][2] == {
        "Names": [ARN + "state", ARN + "origin"],
        "WithDecryption": True,
    }
    assert directory.stat().st_mode & 0o077 == 0
    assert all(f.stat().st_mode & 0o077 == 0 for f in directory.iterdir())
    assert SENTINEL in (directory / "origin-gate.conf").read_text()


@pytest.mark.parametrize(
    "mode", ["failure", "wrong-arn", "bad-image", "bad-host", "expired", "aws"]
)
def test_private_injection_failure_closes_activation_without_secret_output(tmp_path, mode):
    transport = FakeSSM(fail=mode == "failure", wrong_arn=mode == "wrong-arn")
    public = PUBLIC.copy()
    if mode == "bad-image":
        public["DC2_POSTGRES_IMAGE"] = "media:latest"
    if mode == "bad-host":
        public["DC2_PUBLIC_HOST"] = "unapproved.example"
    if mode == "aws":
        transport.evidence_kind = "aws"
    with pytest.raises((ValueError, PermissionError)) as error:
        prepare_private_state(
            CONFIG,
            transport,
            tmp_path / "private",
            public,
            deadline=99 if mode == "expired" else 110,
            clock=lambda: 100,
        )
    assert SENTINEL not in str(error.value)
    assert not (tmp_path / "private/state.env").exists()


@pytest.mark.parametrize("permissions,expected", [("600", 0), ("644", 1)])
def test_start_fake_commands_private_permissions_and_no_secret_logging(
    tmp_path, permissions, expected
):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    for name in ["state.env", "origin-gate.conf"]:
        (config / name).write_text(SENTINEL)
    marker = tmp_path / "docker-invoked"
    fakes = {
        "mountpoint": "exit 0",
        "findmnt": """case "$5" in
UUID) case "$3" in /) echo root-uuid;; *) echo data-uuid;; esac;;
OPTIONS) echo rw,relatime;; esac""",
        "df": (
            "echo 'Filesystem 1024-blocks Used Available Capacity Mounted'; "
            "echo '/dev/fake 8000000 1000000 7000000 12% /fake'"
        ),
        "stat": f"""case "$2" in %a) echo {permissions};; %u) echo 0;; *) exit 1;; esac""",
        "docker": f"touch '{marker}'",
    }
    for name, content in fakes.items():
        file = binaries / name
        file.write_text("#!/bin/sh\n" + content + "\n")
        file.chmod(0o700)
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "deploy/aws/state/start.sh")],
        env={
            "PATH": str(binaries) + ":/usr/bin:/bin",
            "DC2_STATE_ASSET_ROOT": str(ROOT),
            "DC2_STATE_CONFIG_DIR": str(config),
            "DC2_DATA_MOUNT": str(tmp_path / "data"),
            "DC2_DATA_UUID": "data-uuid",
            "DC2_STATE_INSTALL_APPROVED": "true",
            "DC2_ORIGIN_HTTP_ACCEPTED": "true",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == expected
    assert marker.exists() is (expected == 0)
    assert SENTINEL not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "free,redis,expected", [(7000000, 100000, 0), (100, 100, 1), (7000000, 300000, 1)]
)
def test_capacity_fake_commands_keep_free_space_and_aof_headroom(tmp_path, free, redis, expected):
    data = tmp_path / "data"
    (data / "redis").mkdir(parents=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name, content in {
        "df": (
            "echo 'Filesystem 1024-blocks Used Available Capacity Mounted'; "
            f"echo '/dev/fake 8000000 1000000 {free} 12% /fake'"
        ),
        "du": f"echo '{redis} ignored'",
    }.items():
        file = binaries / name
        file.write_text("#!/bin/sh\n" + content + "\n")
        file.chmod(0o700)
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "deploy/aws/state/capacity-check.sh")],
        env={"PATH": str(binaries) + ":/usr/bin:/bin", "DC2_DATA_MOUNT": str(data)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == expected


@pytest.mark.parametrize(
    "approvals", [{}, {"DC2_STATE_INSTALL_APPROVED": "true"}, {"DC2_ORIGIN_HTTP_ACCEPTED": "true"}]
)
def test_unapproved_start_refuses_before_any_mount_or_docker(approvals):
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "deploy/aws/state/start.sh")],
        env={"PATH": "/usr/bin:/bin", **approvals},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert result.stdout == result.stderr == ""
