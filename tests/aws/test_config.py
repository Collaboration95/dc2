import json
from datetime import UTC, datetime

import pytest

from scripts.aws.config import CloudConfig, load_config, validate_nonsecret


def config_dict(**changes):
    data = {
        "mode": "plan",
        "region": "ap-southeast-1",
        "account_id": "",
        "environment_id": "aws2-demo",
        "public_url": "",
        "source_bucket": "demo-source",
        "output_bucket": "demo-output",
        "operator_station": "station-a",
    }
    data.update(changes)
    return data


def test_roundtrip_missing_approval_is_a_plan(tmp_path):
    data = config_dict(network={"subnets": ["subnet-offline"], "assign_public_ip": "ENABLED"})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    config = load_config(path)
    assert config.approval == {} and config.origin_transport_accepted is False
    assert CloudConfig.from_dict(config.to_dict()) == config
    copy = config.to_dict()
    copy["network"]["subnets"].append("other")
    assert config.network["subnets"] == ["subnet-offline"]
    with pytest.raises(PermissionError, match="excluded"):
        config.require_real_action("apply")


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "aws"},
        {"max_worker_tasks": 4},
        {"max_worker_tasks": True},
        {"worker_lifetime_seconds": 0},
        {"worker_lifetime_seconds": 14401},
        {"origin_transport_accepted": "yes"},
        {"source_bucket": "bad/bucket"},
        {"source_bucket": "demo-output"},
        {"public_url": "http://d123.cloudfront.net"},
        {"public_url": "https://unapproved.example"},
        {"public_url": "https://d123.cloudfront.net/api"},
        {"endpoint_url": "http://169.254.169.254:80"},
        {"endpoint_url": "http://example.test:5000"},
        {"endpoint_url": "http://127.0.0.1"},
        {"endpoint_url": "http://127.0.0.1:5000/path"},
        {"endpoint_url": "https://127.0.0.1:5000"},
        {"network": {"assign_public_ip": "yes"}},
        {"session_end_utc": "2026-10-30T00:00:00Z"},
        {"session_end_utc": "2026-10-20T00:00:00"},
        {"image_digests": {"media": "latest"}},
        {"parameter_arns": {"dsn": "arn:aws:ssm:ap-southeast-1:000000000000:parameter/demo/*"}},
        {"parameter_arns": {"dsn": "arn:aws:ssm:us-east-1:000000000000:parameter/demo/dsn"}},
    ],
)
def test_invalid_controls_fail_closed(change):
    with pytest.raises(ValueError):
        CloudConfig.from_dict(config_dict(**change))


@pytest.mark.parametrize(
    "private",
    [
        {"password": "PRIVATE-SENTINEL"},
        {"dsn": "PRIVATE-SENTINEL"},
        {"extra": "postgresql://user:PRIVATE-SENTINEL@host/db"},
        {"extra": "https://host/?X-Amz-Signature=PRIVATE-SENTINEL"},
        {"cookie": "PRIVATE-SENTINEL"},
        {"authorization": "Bearer PRIVATE-SENTINEL"},
        {"profile": "PRIVATE-SENTINEL"},
        {"aws_secret_access_key": "PRIVATE-SENTINEL"},
        {"MEDIA_JWT_SECRET": "PRIVATE-SENTINEL"},
    ],
)
def test_nested_private_material_rejected_without_echo(private):
    with pytest.raises(ValueError) as error:
        validate_nonsecret({"nested": [private]})
    assert "PRIVATE-SENTINEL" not in str(error.value)


def test_emulator_requires_explicit_dummy_identity_and_no_implicit_credentials():
    with pytest.raises(ValueError):
        CloudConfig.from_dict(config_dict(mode="emulator", endpoint_url="http://127.0.0.1:5000"))
    config = CloudConfig.from_dict(
        config_dict(
            mode="emulator",
            account_id="000000000000",
            endpoint_url="http://[::1]:5000",
            public_url="https://localhost",
        )
    )
    assert config.endpoint_url == "http://[::1]:5000"
    with pytest.raises(PermissionError):
        config.require_real_action()


def test_references_are_nonsecret_and_anchored_deadline_is_preserved():
    config = CloudConfig.from_dict(
        config_dict(
            account_id="000000000000",
            parameter_arns={"dsn": "arn:aws:ssm:ap-southeast-1:000000000000:parameter/demo/dsn"},
            session_end_utc="2026-10-28T15:00:00Z",
            public_url="https://d123.cloudfront.net",
        )
    )
    assert datetime.fromisoformat(config.session_end_utc.replace("Z", "+00:00")).tzinfo == UTC
    with pytest.raises(ValueError):
        CloudConfig.from_dict({"mode": "plan"})
    with pytest.raises(ValueError):
        CloudConfig.from_dict(config_dict(unexpected="ignored inputs are dangerous"))
