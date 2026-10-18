"""Nonsecret V1 rendering inputs. No SDK, profile, network or credential discovery."""

import argparse
import json
import re
from pathlib import Path

from scripts.aws.config import validate_nonsecret
from scripts.aws.v1.definitions import DatabaseOptions, template

FIELDS = {
    "database_topology",
    "database_auto_pause_seconds",
    "database_max_capacity",
    "schema_version",
    "environment_id",
    "account_id",
    "region",
    "source_cors_origin",
    "deploy_applications",
    "images",
    "parameter_arns",
    "handlers",
    "aurora_engine_version",
    "worker_lifetime_seconds",
    "unattended_launch",
    "lambda_short_encodes",
    "always_on",
    "stage_rate_limit",
    "stage_burst_limit",
    "monthly_budget_usd",
    "budget_alert_email",
}
# V2-live (#236): the persistent environment's render inputs -> CloudFormation parameters.
ALWAYS_ON_PARAMETERS = {
    "stage_rate_limit": "StageRateLimit",
    "stage_burst_limit": "StageBurstLimit",
    "monthly_budget_usd": "MonthlyBudgetUsd",
    "budget_alert_email": "BudgetAlertEmail",
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
    "parameter_arns",
}


def database_options(config):
    """The opt-in V2 database layout (#94); absent keys are V1's single cluster, 300 s, 2 ACU.

    These are render-time choices, not CloudFormation parameters, so they never appear in the
    list `parameters` returns: a different layout is a different template.
    """
    defaults = DatabaseOptions()
    try:
        return DatabaseOptions(
            config.get("database_topology", defaults.topology),
            config.get("database_auto_pause_seconds", defaults.auto_pause_seconds),
            config.get("database_max_capacity", defaults.max_capacity),
        )
    except ValueError as error:
        raise ValueError(f"V1 database configuration rejected: {error}") from None


def parameters(config):
    """Return safe CFN parameters, rejecting missing activation artifacts up front."""
    validate_nonsecret(config)
    if not isinstance(config, dict) or config.keys() - FIELDS or REQUIRED - config.keys():
        raise ValueError("V1 configuration has missing or unsupported fields")
    database_options(config)
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ValueError("V1 configuration requires schema_version 1")
    # There is deliberately no session_open: the template is always closed and the
    # session API is the single runtime authority that opens it.
    if type(config["deploy_applications"]) is not bool:
        raise ValueError("V1 application flag must be a JSON boolean")
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
        "AuroraEngineVersion": config.get("aurora_engine_version", "16.8"),
        "WorkerLifetimeSeconds": config.get("worker_lifetime_seconds", 1800),
    }
    if "unattended_launch" in config:
        # Absent means the template default (false): V1 behaviour, no launcher resources.
        if type(config["unattended_launch"]) is not bool:
            raise ValueError("Unattended launch flag must be a JSON boolean")
        result["UnattendedLaunch"] = str(config["unattended_launch"]).lower()
    if "lambda_short_encodes" in config:
        # Absent means the template default (false): no short queue, function or mapping.
        if type(config["lambda_short_encodes"]) is not bool:
            raise ValueError("Lambda short-encode flag must be a JSON boolean")
        result["LambdaShortEncodes"] = str(config["lambda_short_encodes"]).lower()
    if "always_on" in config:
        # Absent means the template default (false): V1's closed-by-default stack.
        if type(config["always_on"]) is not bool:
            raise ValueError("Always-on flag must be a JSON boolean")
        result["AlwaysOn"] = str(config["always_on"]).lower()
    result.update({name: config[key] for key, name in ALWAYS_ON_PARAMETERS.items()
                   if key in config})
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
        config = json.loads(args.config.read_text())
        params = parameters(config)
        database = database_options(config)
    except (ValueError, TypeError):
        parser.exit(2, "V1 config rejected; check nonsecret fields against config.schema.json\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "template.json").write_text(json.dumps(template(database), indent=2) + "\n")
    (args.output_dir / "parameters.json").write_text(json.dumps(params, indent=2) + "\n")
    print("Rendered inert V1 template and nonsecret parameter references; no AWS calls")


if __name__ == "__main__":
    main()
