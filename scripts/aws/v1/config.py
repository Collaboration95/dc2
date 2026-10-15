"""Nonsecret V1 rendering inputs. No SDK, profile, network or credential discovery."""

import argparse
import json
import re
from pathlib import Path

from scripts.aws.config import validate_nonsecret
from scripts.aws.v1.definitions import template

FIELDS = {
    "schema_version",
    "environment_id",
    "account_id",
    "region",
    "source_cors_origin",
    "deploy_applications",
    "session_open",
    "images",
    "parameter_arns",
    "handlers",
    "aurora_engine_version",
    "worker_lifetime_seconds",
}
PARAMETERS = {
    "media_runtime_dsn": "MediaRuntimeDsnParameterArn",
    "processing_runtime_dsn": "ProcessingRuntimeDsnParameterArn",
    "media_migration_dsn": "MediaMigrationDsnParameterArn",
    "processing_migration_dsn": "ProcessingMigrationDsnParameterArn",
    "jwt_secret": "JwtSecretParameterArn",
}
REQUIRED = {
    "schema_version",
    "environment_id",
    "account_id",
    "region",
    "source_cors_origin",
    "deploy_applications",
    "session_open",
    "parameter_arns",
}


def parameters(config):
    """Return safe CFN parameters, rejecting missing activation artifacts up front."""
    validate_nonsecret(config)
    if not isinstance(config, dict) or config.keys() - FIELDS or REQUIRED - config.keys():
        raise ValueError("V1 configuration has missing or unsupported fields")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("V1 configuration requires schema_version 1")
    for key in ("deploy_applications", "session_open"):
        if type(config[key]) is not bool:
            raise ValueError("V1 session/application flags must be JSON booleans")
    if config["session_open"] and not config["deploy_applications"]:
        raise ValueError("Cannot open an infrastructure-only stack")
    account, region = config["account_id"], config["region"]
    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("Explicit account_id is required")
    if region != "ap-southeast-1":
        raise ValueError("V1 initial target is ap-southeast-1")
    arns = config["parameter_arns"]
    if not isinstance(arns, dict) or arns.keys() != PARAMETERS.keys():
        raise ValueError("Exactly five owned SSM parameter references are required")
    if len(set(arns.values())) != len(arns):
        raise ValueError("Runtime/migration/domain parameter identities must be distinct")
    prefix = f"arn:aws:ssm:{region}:{account}:parameter/dc2/{config['environment_id']}/"
    if not all(isinstance(arn, str) and arn.startswith(prefix) for arn in arns.values()):
        raise ValueError("SSM references must match the explicit project/account/region")
    images = config.get("images", {})
    if not isinstance(images, dict) or images.keys() - {"media", "processing", "worker"}:
        raise ValueError("Unsupported image fields")
    if config["deploy_applications"] and images.keys() != {"media", "processing", "worker"}:
        raise ValueError("Application activation requires all three immutable images")
    image_prefix = f"{account}.dkr.ecr.{region}.amazonaws.com/"
    if not all(isinstance(uri, str) and uri.startswith(image_prefix) for uri in images.values()):
        raise ValueError("Images must belong to the explicit account and region")
    result = {
        "EnvironmentId": config["environment_id"],
        "SourceCorsOrigin": config["source_cors_origin"],
        "DeployApplications": str(config["deploy_applications"]).lower(),
        "SessionOpen": str(config["session_open"]).lower(),
        "AuroraEngineVersion": config.get("aurora_engine_version", "16.8"),
        "WorkerLifetimeSeconds": config.get("worker_lifetime_seconds", 1800),
    }
    result.update({name: arns[key] for key, name in PARAMETERS.items()})
    result.update({f"{key.title()}ImageUri": uri for key, uri in images.items()})
    handler_config = config.get("handlers", {})
    if not isinstance(handler_config, dict):
        raise ValueError("Handler overrides must be an object")
    spec = template()["Parameters"]
    for name, handler in handler_config.items():
        key = f"{name}Handler"
        if key not in spec or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]*\.[A-Za-z_][A-Za-z0-9_]*", handler
        ):
            raise ValueError("Unsupported Lambda handler override")
        result[key] = handler
    for name, value in result.items():
        definition = spec[name]
        if definition["Type"] == "String":
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            if "AllowedPattern" in definition and not re.fullmatch(
                definition["AllowedPattern"], value
            ):
                raise ValueError(f"{name} violates its CloudFormation constraint")
        elif (
            type(value) is not int or not definition["MinValue"] <= value <= definition["MaxValue"]
        ):
            raise ValueError(f"{name} is outside its bounded range")
    # The selected parameter group is PostgreSQL 16 and min=0 requires >=16.3.
    if not re.fullmatch(r"16\.(?:[3-9]|[1-9][0-9])", result["AuroraEngineVersion"]):
        raise ValueError("Aurora version must support auto-pause and the PostgreSQL16 family")
    return [
        {"ParameterKey": key, "ParameterValue": str(value)} for key, value in sorted(result.items())
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        params = parameters(json.loads(args.config.read_text()))
    except (ValueError, TypeError):
        parser.exit(2, "V1 config rejected; check nonsecret fields against config.schema.json\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "template.json").write_text(json.dumps(template(), indent=2) + "\n")
    (args.output_dir / "parameters.json").write_text(json.dumps(params, indent=2) + "\n")
    print("Rendered inert V1 template and nonsecret parameter references; no AWS calls")


if __name__ == "__main__":
    main()
