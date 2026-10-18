"""Offline V1 contract checks: deployment safety and ownership boundaries."""

import asyncio
import copy
import fnmatch
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    for role in (
        "ProcessingCommands",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
    ):
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


def test_output_bucket_cors_serves_cors_mode_hls_segments_to_the_site_origin():
    resources = template()["Resources"]
    rule = resources["OutputBucket"]["Properties"]["CorsConfiguration"]["CorsRules"][0]
    # Native HLS follows the API's 307 to this bucket in CORS mode; any other origin or
    # method, or a missing Range allowance, turns the redirect into MEDIA_ERR_SRC_NOT_SUPPORTED.
    assert rule["AllowedOrigins"] == [{"Ref": "SourceCorsOrigin"}]
    assert rule["AllowedMethods"] == ["GET", "HEAD"]
    assert {"Range", "X-Playback-Session-Id"} <= set(rule["AllowedHeaders"])
    assert {"Content-Range", "Accept-Ranges", "Content-Length"} <= set(rule["ExposedHeaders"])


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
        # Closed unless the persistent environment deploys always on (#236).
        assert mapping["Enabled"] == {"Fn::If": ["AlwaysOpen", True, False]}
    for resource in resources.values():
        if resource["Type"] == "AWS::Lambda::Function":
            assert "ReservedConcurrentExecutions" not in resource["Properties"]
            assert resource["Properties"]["VpcConfig"]["Ipv6AllowedForDualStack"] is True
            # The opt-in launcher (#68) and short encoder (#93) are the only functions the
            # default stack omits.
            variables = resource["Properties"]["Environment"]["Variables"]
            assert resource["Condition"] == (
                "Unattended"
                if variables.get("PROCESSING_LAUNCHER_CLUSTER")
                else "ShortEncodes"
                if variables.get("PROCESSING_ATTEMPT_TIMEOUT_SECONDS")
                else "Applications"
            )
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
    functions = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    assert functions
    assert all("ReservedConcurrentExecutions" not in r["Properties"] for r in functions)
    # Without per-function reservations the SQS consumers carry the explicit bound.
    for name in ("ProcessingCommandsMapping", "MediaResultsMapping"):
        assert resources[name]["Properties"]["ScalingConfig"] == {"MaximumConcurrency": 2}
    rules = [r for r in resources.values() if r["Type"] == "AWS::Events::Rule"]
    # Every gate opens only under AlwaysOpen, which the per-run V1 stack never sets (#236).
    assert built["Parameters"]["AlwaysOn"]["Default"] == "false"
    assert rules and all(
        r["Properties"]["State"] == {"Fn::If": ["AlwaysOpen", "ENABLED", "DISABLED"]}
        for r in rules
    )
    stage = resources["HttpStage"]["Properties"]["DefaultRouteSettings"]["Fn::If"]
    assert stage[0] == "AlwaysOpen"
    assert stage[2] == {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
    assert built["Outputs"]["HttpApiId"]["Condition"] == "Applications"
    assert all(
        resources[n]["Properties"]["Enabled"] == {"Fn::If": ["AlwaysOpen", True, False]}
        for n in ("ProcessingCommandsMapping", "MediaResultsMapping")
    )


# --- IAM follows the code paths (#115) ---------------------------------------------------------
#
# Each S3 call a handler or task makes is recorded from the real implementation, mapped to the
# IAM action AWS evaluates for it, and required of exactly the roles whose entrypoint reaches
# it. A missing grant makes cleanup fail silently in the cloud (the old ListBucketVersions
# gap), so this is the guard that keeps the roles and the code in step.

ACCOUNT = "111111111111"
ATTEMPT_PREFIX = (
    "jobs/11111111-1111-4111-8111-111111111111/attempts/22222222-2222-4222-8222-222222222222/"
)
QUEUES = ("ProcessingCommands", "ProcessingWork", "MediaResults")


def flat(value):
    """A template intrinsic as a comparable string: buckets read ``<SourceBucket>``."""
    if isinstance(value, dict) and "Fn::GetAtt" in value:
        return "<" + value["Fn::GetAtt"][0] + ">"
    if isinstance(value, dict) and "Fn::Sub" in value:
        text = re.sub(r"\$\{(\w+)\.Arn\}", r"<\1>", value["Fn::Sub"])
        return text.replace("${AWS::Partition}", "aws").replace("${AWS::AccountId}", ACCOUNT)
    return value


def as_list(value):
    return value if isinstance(value, list) else [value]


def grants(resources, role, action, resource, prefix=None):
    """Does an Allow in the role's policy cover this action on this resource (and prefix)?"""
    for statement in statements(resources, role):
        if statement["Effect"] != "Allow" or action not in as_list(statement["Action"]):
            continue
        patterns = [flat(pattern) for pattern in as_list(statement["Resource"])]
        if not any(fnmatch.fnmatchcase(resource, pattern) for pattern in patterns):
            continue
        like = statement.get("Condition", {}).get("StringLike", {}).get("s3:prefix")
        if like is None or (
            prefix is not None and any(fnmatch.fnmatchcase(prefix, p) for p in like)
        ):
            return True
    return False


def s3_actions(resources, role):
    return {
        action
        for statement in statements(resources, role)
        for action in as_list(statement["Action"])
        if action.startswith("s3:")
    }


class RecordingS3:
    """boto3 stand-in that records the calls NativeCleanupStore makes."""

    def __init__(self, keys):
        self.calls, self.keys = [], keys

    def get_paginator(self, name):
        outer = self

        class Paginator:
            def paginate(self, **kwargs):
                outer.calls.append((name, kwargs))
                return iter(
                    [
                        {
                            "Versions": [{"Key": k, "VersionId": "v1"} for k in outer.keys],
                            "DeleteMarkers": [{"Key": outer.keys[0], "VersionId": "marker"}],
                        }
                    ]
                )

        return Paginator()

    def delete_objects(self, **kwargs):
        self.calls.append(("delete_objects", kwargs))
        return {}


def processing_cleanup_requirements():
    """(action, resource, prefix) the late-output cleanup needs, from its real S3 calls."""
    from processing.recovery_v1 import NativeCleanupStore

    keys = [ATTEMPT_PREFIX + "primary.mp4", ATTEMPT_PREFIX + "hls/index.m3u8"]
    client = RecordingS3(keys)
    store = NativeCleanupStore(SimpleNamespace(minio_output_bucket="out"), client=client)
    asyncio.run(store.delete_prefix(ATTEMPT_PREFIX))
    required = set()
    for name, kwargs in client.calls:
        if name == "list_object_versions":
            required.add(("s3:ListBucketVersions", "<OutputBucket>", kwargs["Prefix"]))
        elif name == "delete_objects":
            for item in kwargs["Delete"]["Objects"]:
                assert item.get("VersionId"), "an unversioned delete only adds a delete marker"
                required.add(("s3:DeleteObjectVersion", "<OutputBucket>/" + item["Key"], None))
        else:  # pragma: no cover - a new S3 call must be mapped to its IAM action here
            raise AssertionError(f"unmapped S3 operation {name}")
    return required


def reaches_cleanup(monkeypatch, function_path):
    """Run the real Processing entrypoint with I/O stubbed; did it run the cleanup pass?"""
    import importlib

    from processing.config import get_settings

    module_name, function_name = function_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    monkeypatch.setenv("PROCESSING_POSTGRES_DSN", "postgresql://processing_runtime:pw@db/p")
    monkeypatch.delenv("PROCESSING_DATABASE_CA_FILE", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    for variable, lane in (
        ("PROCESSING_COMMANDS_QUEUE_URL", "commands"),
        ("PROCESSING_WORK_QUEUE_URL", "work"),
        ("MEDIA_RESULTS_QUEUE_URL", "results"),
    ):
        monkeypatch.setenv(variable, f"https://sqs.ap-southeast-1.amazonaws.com/{ACCOUNT}/{lane}")
    get_settings.cache_clear()
    monkeypatch.setattr(
        module, "create_async_engine", lambda *a, **k: SimpleNamespace(dispose=AsyncMock())
    )
    monkeypatch.setattr(module, "async_sessionmaker", lambda *a, **k: object())
    monkeypatch.setattr(module, "SQS", lambda *a, **k: SimpleNamespace(client=None))
    cleanup = AsyncMock(return_value={})
    monkeypatch.setattr(module, "run_once", cleanup)
    monkeypatch.setattr(module, "terminal_event", AsyncMock(return_value=0))
    monkeypatch.setattr(module, "consume_commands", AsyncMock(return_value={}))
    monkeypatch.setattr(module, "publish_outbox", AsyncMock(return_value=0))
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 60000)
    getattr(module, function_name)({"Records": []}, context)
    get_settings.cache_clear()
    return cleanup.await_count > 0


def role_handlers(domain):
    return {
        name[: -len("Handler")]: parameter["Default"]
        for name, parameter in template()["Parameters"].items()
        if name.endswith("Handler") and name.startswith(domain)
    }


def test_every_processing_role_that_reaches_output_cleanup_can_list_and_delete_versions(
    monkeypatch,
):
    resources = template()["Resources"]
    required = processing_cleanup_requirements()
    assert {action for action, _, _ in required} == {
        "s3:ListBucketVersions",
        "s3:DeleteObjectVersion",
    }
    handlers = role_handlers("Processing")
    reaching = {
        role
        for role, path in handlers.items()
        if path.startswith("processing.handlers.")
        and role != "ProcessingLauncher"  # never touches S3; test_unattended_launch pins that
        and role != "ProcessingShortEncoder"  # encodes, so it has the Worker's S3 grants
        and reaches_cleanup(monkeypatch, path)
    }
    # The ASGI API entrypoint never imports the cleanup machinery at all.
    api = (ROOT / "processing/lambda_handler.py").read_text() + (
        ROOT / "processing/v1_api.py"
    ).read_text()
    assert not {"recovery", "NativeCleanupStore", "cleanup_outputs"} & set(re.findall(r"\w+", api))
    # Repair, the ECS stop hint and the S3 hint all run the same pass; the rest never do.
    assert reaching == {"ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events"}
    for role in reaching:
        for action, resource, prefix in required:
            assert grants(resources, role, action, resource, prefix), (role, action, resource)
    for role in set(handlers) - reaching - {"ProcessingShortEncoder"}:
        assert not s3_actions(resources, role), f"{role} reaches no S3 call but is granted some"


def test_processing_cleanup_grants_are_scoped_to_owned_attempt_prefixes_and_versioned_only():
    resources = template()["Resources"]
    for role in ("ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events"):
        assert s3_actions(resources, role) == {"s3:ListBucketVersions", "s3:DeleteObjectVersion"}
        assert not grants(resources, role, "s3:ListBucketVersions", "<OutputBucket>", "other/")
        assert not grants(resources, role, "s3:ListBucketVersions", "<SourceBucket>", "jobs/x/")
        assert not grants(resources, role, "s3:DeleteObjectVersion", "<OutputBucket>/other/key")
        assert not grants(resources, role, "s3:DeleteObjectVersion", "<SourceBucket>/jobs/x")


class RecordingMinio:
    def __init__(self, keys):
        self.keys, self.calls = keys, []

    def list_objects(self, bucket, **kwargs):
        self.calls.append(("list_objects", kwargs))
        return [SimpleNamespace(object_name=k, version_id="v1") for k in self.keys]

    def remove_objects(self, bucket, deletes):
        self.calls.append(("remove_objects", [(d.name, d.version_id) for d in deletes]))
        return []


def test_media_source_version_cleanup_is_granted_to_its_roles_only_on_the_source_bucket():
    from media.config import Settings
    from media.services.storage import Storage

    resources = template()["Resources"]
    key = "sources/o/a/source"
    storage = Storage(
        Settings(postgres_dsn="postgresql+asyncpg://u:p@db/m", minio_source_bucket="s")
    )
    storage.internal = RecordingMinio([key])
    asyncio.run(storage.remove_source_versions("s", key))
    required = set()
    for name, detail in storage.internal.calls:
        if name == "list_objects":
            assert detail["include_version"] is True
            required.add(("s3:ListBucketVersions", "<SourceBucket>", detail["prefix"]))
        else:
            required |= {("s3:DeleteObjectVersion", "<SourceBucket>/" + k, None) for k, _ in detail}
    assert required
    # MediaApi discards failed edits inline; MediaRepair recovers them (tombstones, expired
    # grants and staged orphans) on the schedule.
    for role in ("MediaApi", "MediaRepair"):
        for action, resource, prefix in required:
            assert grants(resources, role, action, resource, prefix), (role, action)
        for action in ("s3:ListBucketVersions", "s3:DeleteObjectVersion"):
            assert not grants(resources, role, action, "<OutputBucket>/jobs/x/p.mp4", "jobs/")
    # Repair deletes versions and nothing else in S3.
    assert s3_actions(resources, "MediaRepair") == {
        "s3:ListBucketVersions",
        "s3:DeleteObjectVersion",
    }
    for role in ("MediaAuthorizer", "MediaResults", "MediaMigration"):
        assert not s3_actions(resources, role)


def test_media_api_keeps_every_other_s3_action_its_storage_layer_issues():
    resources = template()["Resources"]
    source, output = "<SourceBucket>/sources/o/a/source", "<OutputBucket>/jobs/j/attempts/a/x.mp4"
    # stat/get (pinned and unpinned), the direct-upload POST policy and the output copy,
    # whose multipart upload must be abortable when it fails.
    writes = ("s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:AbortMultipartUpload")
    for action in writes:
        assert grants(resources, "MediaApi", action, source), action
    for action in ("s3:GetObject", "s3:GetObjectVersion"):
        assert grants(resources, "MediaApi", action, output), action
    # Media reads outputs; it never writes or deletes them.
    for action in ("s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"):
        assert not grants(resources, "MediaApi", action, output), action


def test_the_finite_worker_reads_sources_and_writes_outputs_but_cannot_delete_or_list():
    resources = template()["Resources"]
    # processing/worker/source.py get_object(version_id=...); worker/storage.py put_object.
    assert s3_actions(resources, "Worker") == {
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:AbortMultipartUpload",
    }
    # Late-output cleanup belongs to Processing's Lambdas, never the task that wrote it.
    assert not grants(resources, "Worker", "s3:DeleteObjectVersion", "<OutputBucket>/jobs/x")
    assert not grants(resources, "Worker", "s3:ListBucketVersions", "<OutputBucket>", "jobs/")


# --- Queue policies: operator redrive and injection (#116) ---------------------------------

OPERATOR = f"arn:aws:iam::{ACCOUNT}:user/operator"
PRODUCERS = {
    "ProcessingCommands": ["MediaRepair"],
    "ProcessingWork": [
        "ProcessingCommands",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
    ],
    "MediaResults": [
        "ProcessingCommands",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
    ],
}


def denies(document, action, *, principal, service=None, secure=True):
    """Evaluate the rendered Deny statements for one request (an explicit deny wins)."""
    context = {"aws:PrincipalArn": principal, "aws:PrincipalServiceName": service}
    for statement in document["Statement"]:
        if statement["Effect"] != "Deny" or not any(
            fnmatch.fnmatchcase(action, pattern) for pattern in as_list(statement["Action"])
        ):
            continue
        matched = True
        for operator, keys in statement["Condition"].items():
            for key, values in keys.items():
                if operator == "Bool":
                    matched &= str(secure).lower() == as_list(values)[0]
                    continue
                actual = context.get(key)
                listed = [flat(v) for v in as_list(values)]
                if operator in ("ArnNotEquals", "StringNotEquals"):
                    matched &= actual is None or actual not in listed
                elif operator == "ArnNotLike":
                    matched &= actual is None or not any(
                        fnmatch.fnmatchcase(actual, pattern) for pattern in listed
                    )
                else:  # pragma: no cover - extend the evaluator with the template
                    raise AssertionError(f"unsupported operator {operator}")
        if matched:
            return True
    return False


def queue_policy(name):
    return template()["Resources"][name + "QueuePolicy"]["Properties"]["PolicyDocument"]


@pytest.mark.parametrize("queue", QUEUES)
def test_an_operator_session_can_redrive_and_inject_poison_into_each_source_queue(queue):
    document = queue_policy(queue)
    # StartMessageMoveTask moves each message with SendMessage on the destination queue.
    assert not denies(document, "sqs:SendMessage", principal=OPERATOR)
    # Whether SQS presents the caller or itself for the move, neither is refused.
    assert not denies(document, "sqs:SendMessage", principal=None, service="sqs.amazonaws.com")


@pytest.mark.parametrize("queue", QUEUES)
def test_the_operator_exception_is_narrow_and_other_principals_stay_denied(queue):
    document = queue_policy(queue)
    producers = PRODUCERS[queue]
    for role in producers:
        assert not denies(document, "sqs:SendMessage", principal=f"<{role}Role>")
    # Every other handler, the public API roles included, remains refused.
    everyone = set(role_handlers("Media")) | set(role_handlers("Processing")) | {"Worker"}
    for role in everyone - set(producers):
        assert denies(document, "sqs:SendMessage", principal=f"<{role}Role>"), role
    # Foreign accounts, roles and sessions named like users, the root and other services.
    for principal in (
        "arn:aws:iam::999999999999:user/operator",
        f"arn:aws:iam::{ACCOUNT}:role/operator",
        f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/session",
        f"arn:aws:iam::{ACCOUNT}:root",
    ):
        assert denies(document, "sqs:SendMessage", principal=principal), principal
    assert denies(document, "sqs:SendMessage", principal=None, service="lambda.amazonaws.com")
    assert denies(document, "sqs:SendMessage", principal=None)


@pytest.mark.parametrize("queue", QUEUES)
def test_the_operator_exception_does_not_open_receive_delete_or_plain_transport(queue):
    document = queue_policy(queue)
    for action in ("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility"):
        assert denies(document, action, principal=OPERATOR), action
        assert denies(document, action, principal=None, service="sqs.amazonaws.com"), action
    assert denies(document, "sqs:SendMessage", principal=OPERATOR, secure=False)


@pytest.mark.parametrize("queue", QUEUES)
def test_dlqs_stay_readable_to_the_operator_for_inspection_and_as_a_redrive_source(queue):
    document = template()["Resources"][queue + "DlqPolicy"]["Properties"]["PolicyDocument"]
    assert not denies(document, "sqs:ReceiveMessage", principal=OPERATOR)
    assert not denies(document, "sqs:DeleteMessage", principal=OPERATOR)
    assert denies(document, "sqs:ReceiveMessage", principal=OPERATOR, secure=False)
