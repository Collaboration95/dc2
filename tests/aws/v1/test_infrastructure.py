"""Offline V1 contract checks: deployment safety and ownership boundaries."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.aws.v1.config import parameters
from scripts.aws.v1.definitions import template

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def config():
    return json.loads((ROOT / "deploy/aws/v1/config.example.json").read_text())


def statements(resources, role):
    return resources[role + "Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]


def permitted(resources, role, action):
    return [s["Resource"] for s in statements(resources, role) if action in s["Action"]]


def test_template_snapshot_is_current():
    assert template() == json.loads((ROOT / "deploy/aws/v1/template.json").read_text())


def test_example_matches_schema_and_is_inert(config):
    schema = json.loads((ROOT / "deploy/aws/v1/config.schema.json").read_text())
    jsonschema.validate(config, schema)
    values = {p["ParameterKey"]: p["ParameterValue"] for p in parameters(config)}
    assert values["DeployApplications"] == "false"
    assert "SessionOpen" not in values
    assert "MediaImageUri" not in values


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "123"),
        ("region", "us-east-1"),
        ("deploy_applications", "false"),
        ("session_open", False),  # removed: the session API is the only runtime authority
        ("worker_lifetime_seconds", 3601),
        ("aurora_engine_version", "16.2"),
        ("environment_id", "../../other"),
        ("source_cors_origin", "http://example.invalid"),
        ("password", "private"),
        ("schema_version", True),
    ],
)
def test_reject_invalid_inputs(config, field, value):
    config[field] = value
    with pytest.raises(ValueError):
        parameters(config)


def test_activation_requires_explicit_digest_images(config):
    config["deploy_applications"] = True
    with pytest.raises(ValueError):
        parameters(config)
    config["images"] = {
        d: f"000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/{d}@sha256:" + "a" * 64
        for d in ("media", "processing", "worker")
    }
    assert len(parameters(config)) == 13
    config["images"]["worker"] = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/worker:latest"
    with pytest.raises(ValueError):
        parameters(config)


def test_cross_account_and_shared_secret_rejected(config):
    config["parameter_arns"]["processing_runtime_dsn"] = config["parameter_arns"][
        "media_runtime_dsn"
    ]
    with pytest.raises(ValueError):
        parameters(config)
    config["parameter_arns"]["processing_runtime_dsn"] = (
        "arn:aws:ssm:ap-southeast-1:111111111111:parameter/dc2/dc2-v1-local/processing"
    )
    with pytest.raises(ValueError):
        parameters(config)


def test_no_legacy_or_paid_network_topology():
    resources = template()["Resources"]
    types = {r["Type"] for r in resources.values()}
    assert types.isdisjoint(
        {
            "AWS::EC2::Instance",
            "AWS::EC2::NatGateway",
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "AWS::ElastiCache::CacheCluster",
            "AWS::ECS::Service",
            "AWS::Batch::ComputeEnvironment",
        }
    )
    endpoints = [
        r["Properties"] for r in resources.values() if r["Type"] == "AWS::EC2::VPCEndpoint"
    ]
    assert len(endpoints) == 1
    assert endpoints[0]["VpcEndpointType"] == "Gateway"
    assert len(endpoints[0]["RouteTableIds"]) == 4
    for name in ("PrivateA", "PrivateB"):
        assert name + "Ipv4Route" not in resources
        assert resources[name + "Ipv6Route"]["Properties"]["EgressOnlyInternetGatewayId"]
    assert resources["DatabaseCluster"]["Properties"]["NetworkType"] == "DUAL"
    assert resources["DatabaseCluster"]["Properties"]["ServerlessV2ScalingConfiguration"] == {
        "MinCapacity": 0,
        "MaxCapacity": 2,
        "SecondsUntilAutoPause": 300,
    }


def test_owned_roles_never_get_peer_database_or_runtime_ddl():
    resources = template()["Resources"]
    for name, resource in resources.items():
        if resource["Type"] != "AWS::IAM::Role" or not name.endswith("Role"):
            continue
        encoded = json.dumps(resource)
        if name.startswith("Media"):
            assert "ProcessingRuntimeDsnParameterArn" not in encoded
            assert "ProcessingMigrationDsnParameterArn" not in encoded
        elif name.startswith(("Processing", "Worker")):
            assert "MediaRuntimeDsnParameterArn" not in encoded
            assert "MediaMigrationDsnParameterArn" not in encoded
        if "Migration" not in name:
            assert "MigrationDsnParameterArn" not in encoded
        assert "secretsmanager:GetSecretValue" not in encoded


def test_queue_producers_and_worker_source_are_scoped():
    resources = template()["Resources"]
    for role in ("MediaApi", "ProcessingApi", "MediaAuthorizer", "MediaResults", "Worker"):
        assert not permitted(resources, role, "sqs:SendMessage")
    assert permitted(resources, "MediaRepair", "sqs:SendMessage") == [
        [{"Fn::GetAtt": ["ProcessingCommandsQueue", "Arn"]}]
    ]
    for role in ("ProcessingCommands", "ProcessingRepair", "ProcessingEcsEvents"):
        assert permitted(resources, role, "sqs:SendMessage") == [
            [
                {"Fn::GetAtt": ["ProcessingWorkQueue", "Arn"]},
                {"Fn::GetAtt": ["MediaResultsQueue", "Arn"]},
            ]
        ]
    assert permitted(resources, "Worker", "s3:GetObjectVersion") == [
        [{"Fn::Sub": "${SourceBucket.Arn}/*"}]
    ]
    for action in ("s3:DeleteObject", "s3:PutObject"):
        assert [{"Fn::Sub": "${SourceBucket.Arn}/*"}] not in permitted(resources, "Worker", action)
    for q in ("ProcessingCommands", "ProcessingWork", "MediaResults"):
        queue = resources[q + "Queue"]["Properties"]
        assert queue["MessageRetentionPeriod"] == 604800
        assert resources[q + "Dlq"]["Properties"]["MessageRetentionPeriod"] == 1209600
        denies = resources[q + "QueuePolicy"]["Properties"]["PolicyDocument"]["Statement"]
        assert any(
            "ArnNotEquals" in d["Condition"] and "sqs:SendMessage" in d["Action"] for d in denies
        )


def test_gateway_auth_routes_cookie_and_https_origin():
    resources = template()["Resources"]
    authorizer = resources["GatewayAuthorizer"]["Properties"]
    assert authorizer["AuthorizerResultTtlInSeconds"] == 0
    assert authorizer["IdentitySource"] == ["$request.header.Cookie"]
    for domain in ("Media", "Processing"):
        assert resources[domain + "Integration"]["Properties"]["PayloadFormatVersion"] == "2.0"
        assert resources[domain + "OwnedRoute"]["Properties"]["AuthorizationType"] == "CUSTOM"
        assert resources[domain + "HealthRoute"]["Properties"]["AuthorizationType"] == "NONE"
    for action in ("Register", "Login", "Logout"):
        assert resources["Media" + action + "Route"]["Properties"]["AuthorizationType"] == "NONE"
    distribution = resources["Distribution"]["Properties"]["DistributionConfig"]
    origin = distribution["Origins"][1]["Fn::If"][1]
    assert origin["CustomOriginConfig"]["OriginProtocolPolicy"] == "https-only"
    api_behavior = distribution["CacheBehaviors"][0]["Fn::If"][1]
    assert api_behavior["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    # AllViewerExceptHostHeader forwards cookies/query/auth without the CloudFront Host.
    assert api_behavior["OriginRequestPolicyId"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"


def test_closed_defaults_finite_worker_and_partial_batches():
    built = template()
    resources = built["Resources"]
    assert built["Parameters"]["DeployApplications"]["Default"] == "false"
    assert "SessionOpen" not in built["Parameters"] and "Open" not in built["Conditions"]
    assert resources["WorkerTaskDefinition"]["Properties"]["Cpu"] == "2048"
    assert resources["WorkerTaskDefinition"]["Properties"]["Memory"] == "4096"
    assert not any(r["Type"] == "AWS::ECS::Service" for r in resources.values())
    for domain in ("ProcessingCommands", "MediaResults"):
        mapping = resources[domain + "Mapping"]["Properties"]
        assert mapping["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
        assert mapping["Enabled"] is False
    for resource in resources.values():
        if resource["Type"] == "AWS::Lambda::Function":
            assert resource["Properties"]["ReservedConcurrentExecutions"] == 0
            assert resource["Properties"]["VpcConfig"]["Ipv6AllowedForDualStack"] is True
            assert resource["Condition"] == "Applications"
    worker = resources["WorkerTaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    assert "processing.v1_worker" in worker["Command"]
    assert "--max-empty-polls" in worker["Command"]


def test_handler_override_cannot_inject_a_command(config):
    config["handlers"] = {"MediaApi": "media.lambda_handler.handler"}
    assert parameters(config)
    bad = copy.deepcopy(config)
    bad["handlers"]["MediaApi"] = "python -c unsafe"
    with pytest.raises(ValueError):
        parameters(bad)


def test_migration_tasks_only_inject_own_migration_credentials():
    resources = template()["Resources"]
    for domain in ("Media", "Processing"):
        definition = resources[domain + "MigrationTaskDefinition"]["Properties"]
        container = definition["ContainerDefinitions"][0]
        assert {s["Name"] for s in container["Secrets"]} == {
            domain.upper() + "_POSTGRES_DSN",
            domain.upper() + "_MIGRATION_DSN",
        }
        assert all(
            s["ValueFrom"] == {"Ref": domain + "MigrationDsnParameterArn"}
            for s in container["Secrets"]
        )
        environment = {e["Name"]: e["Value"] for e in container["Environment"]}
        assert environment["PGSSLMODE"] == "verify-full"
        assert environment["PGSSLROOTCERT"] == "/opt/rds/global-bundle.pem"
        assert container["EntryPoint"] == ["/usr/bin/env"]
        assert "alembic" in container["Command"]


def test_privileged_bootstrap_input_never_reaches_app_or_owner_migrations():
    resources = template()["Resources"]
    bootstrap = resources["BootstrapTaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    assert bootstrap["EntryPoint"] == ["python", "/opt/db-bootstrap.py"]
    assert bootstrap["Secrets"][0]["Name"] == "DC2_BOOTSTRAP_INPUT_JSON"
    assert "Policies" not in resources["BootstrapRole"]["Properties"]
    allowed = permitted(resources, "BootstrapExecution", "ssm:GetParameters")
    assert len(allowed) == 1
    assert "bootstrap-input" in json.dumps(allowed)
    for name, resource in resources.items():
        if name not in ("BootstrapTaskDefinition", "BootstrapExecutionRole"):
            assert "bootstrap-input" not in json.dumps(resource)


def test_s3_gateway_allows_project_data_and_ecr_image_layers():
    endpoint = template()["Resources"]["S3Gateway"]["Properties"]
    statements = endpoint["PolicyDocument"]["Statement"]
    assert all(s["Principal"] == "*" for s in statements)
    assert statements[1]["Action"] == ["s3:GetObject"]
    assert statements[1]["Resource"] == [
        {"Fn::Sub": ("arn:${AWS::Partition}:s3:::prod-${AWS::Region}-starport-layer-bucket/*")}
    ]
    # No endpoint-wide Resource=* escape hatch for S3 data.
    assert all("*" not in s["Resource"] for s in statements)


def test_template_is_closed_safe_and_never_requires_positive_reservations():
    """Account limit 10 leaves nothing reservable; only the session API may open the stack."""
    built = template()
    resources = built["Resources"]
    assert "Fn::If" not in json.dumps(
        [r["Properties"].get("ReservedConcurrentExecutions") for r in resources.values()]
    )
    functions = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    assert functions
    assert {r["Properties"]["ReservedConcurrentExecutions"] for r in functions} == {0}
    # Without per-function reservations the SQS consumers carry the explicit bound.
    for name in ("ProcessingCommandsMapping", "MediaResultsMapping"):
        assert resources[name]["Properties"]["ScalingConfig"] == {"MaximumConcurrency": 2}
    rules = [r for r in resources.values() if r["Type"] == "AWS::Events::Rule"]
    assert rules and {r["Properties"]["State"] for r in rules} == {"DISABLED"}
    stage = resources["HttpStage"]["Properties"]["DefaultRouteSettings"]
    assert stage == {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    assert built["Outputs"]["HttpApiId"]["Condition"] == "Applications"
    assert all(
        resources[n]["Properties"]["Enabled"] is False
        for n in ("ProcessingCommandsMapping", "MediaResultsMapping")
    )
