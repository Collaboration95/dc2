import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.aws.definitions import (
    environment_template,
    generator_template,
    private_edge_activation_plan,
    readiness_plan,
)

ROOT = Path(__file__).resolve().parents[2]


def statements(resources, name):
    return [
        s
        for p in resources[name]["Properties"].get("Policies", [])
        for s in p["PolicyDocument"]["Statement"]
    ]


def actions(resources, name):
    return {a for s in statements(resources, name) for a in s["Action"]}


def test_checked_in_templates_match_renderer():
    for name, template in [
        ("environment", environment_template()),
        ("generator", generator_template()),
    ]:
        assert json.loads((ROOT / f"deploy/aws/{name}.json").read_text()) == template


def test_topology_has_only_allowed_resources_and_state_sizes():
    resources = environment_template()["Resources"]
    kinds = [r["Type"] for r in resources.values()]
    for forbidden in [
        "NATGateway",
        "LoadBalancer",
        "EIP",
        "RDS",
        "ElastiCache",
        "Snapshot",
        "HostedZone",
    ]:
        assert not any(forbidden in k for k in kinds)
    assert kinds.count("AWS::EC2::Subnet") == kinds.count("AWS::EC2::VPC") == 1
    assert kinds.count("AWS::EC2::Instance") == 1
    assert resources["S3Gateway"]["Properties"]["VpcEndpointType"] == "Gateway"
    state = resources["StateInstance"]["Properties"]
    assert state["InstanceType"] == "t3a.small"
    assert state["CreditSpecification"]["CPUCredits"] == "standard"
    assert state["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"] == 16
    volume = resources["DataVolume"]
    assert volume["Properties"]["Size"] == 8 and volume["Properties"]["Encrypted"]
    assert volume["DeletionPolicy"] == volume["UpdateReplacePolicy"] == "Retain"
    assert "mkfs" not in json.dumps(state["UserData"])


def test_network_private_roles_and_cloudfront_weight_isolated():
    resources = environment_template()["Resources"]
    origin = resources["OriginIngress"]["Properties"]
    assert origin["SourcePrefixListId"] == {"Ref": "CloudFrontPrefixListId"}
    assert origin["GroupId"] == {"Ref": "OriginSG"} and origin["FromPort"] == 80
    for r in resources.values():
        if r["Type"] == "AWS::EC2::SecurityGroupIngress":
            assert "CidrIp" not in r["Properties"]
            assert r["Properties"]["FromPort"] != 22
    assert not any("MediaRedis" in name for name in resources)
    names = [
        r["Properties"]["Name"]
        for r in resources.values()
        if r["Type"] == "AWS::ServiceDiscovery::Service"
    ]
    assert names == ["media", "processing"]
    assert resources["GatewayMediaOut"]["Properties"]["DestinationSecurityGroupId"] == {
        "Ref": "MediaSG"
    }


def test_exact_iam_role_separation_and_presign_authority():
    resources = environment_template()["Resources"]
    assert actions(resources, "MediaTaskRole") == {
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
    }
    assert actions(resources, "WorkerTaskRole") == {"s3:PutObject", "s3:AbortMultipartUpload"}
    assert "SourceBucket" not in json.dumps(statements(resources, "WorkerTaskRole"))
    assert actions(resources, "RecoveryTaskRole") == {"s3:ListBucket", "s3:DeleteObject"}
    assert statements(resources, "RecoveryTaskRole")[0]["Condition"] == {
        "StringLike": {"s3:prefix": ["jobs/*"]}
    }
    for name in ["Api", "MediaMigration", "ProcessingMigration"]:
        assert actions(resources, name + "TaskRole") == set()
    assert not {"ecs:RunTask", "iam:PassRole"} & actions(resources, "RecoveryTaskRole")
    assert "private/${EnvironmentId}/exports/*" in json.dumps(statements(resources, "OperatorRole"))
    assert "BackupBucket" not in json.dumps(statements(resources, "MediaTaskRole"))
    for name in ["Media", "Api", "Recovery", "Worker"]:
        encoded = json.dumps(statements(resources, name + "ExecutionRole"))
        assert "MigrationDsnArn" not in encoded and "ssm:GetParameters" in encoded


def test_storage_cors_endpoint_and_abort_eligibility():
    resources = environment_template()["Resources"]
    for name in ["Source", "Output", "Backup"]:
        bucket = resources[name + "Bucket"]["Properties"]
        assert all(bucket["PublicAccessBlockConfiguration"].values())
        assert (
            bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"][0][
                "ServerSideEncryptionByDefault"
            ]["SSEAlgorithm"]
            == "AES256"
        )
        assert (
            bucket["LifecycleConfiguration"]["Rules"][0]["AbortIncompleteMultipartUpload"][
                "DaysAfterInitiation"
            ]
            == 1
        )
        assert "Expiration" not in json.dumps(bucket["LifecycleConfiguration"])
    cors = resources["OutputBucket"]["Properties"]["CorsConfiguration"]["CorsRules"][0]
    assert cors["AllowedOrigins"] == [{"Fn::Sub": "https://${Distribution.DomainName}"}]
    assert cors["AllowedHeaders"] == ["Range"] and cors["AllowedMethods"] == ["GET"]
    endpoint = json.dumps(resources["S3Gateway"])
    assert "starport-layer-bucket" in endpoint
    assert "SourceVpce" not in json.dumps(resources)


def test_three_services_exact_sizes_zero_idle_and_owner_migrations():
    resources = environment_template()["Resources"]
    services = [r["Properties"] for r in resources.values() if r["Type"] == "AWS::ECS::Service"]
    assert len(services) == 3 and all(s["DesiredCount"] == 0 for s in services)
    for name, expected in [
        ("Media", ("1024", "2048")),
        ("Api", ("512", "1024")),
        ("Recovery", ("256", "512")),
        ("Worker", ("2048", "4096")),
    ]:
        task = resources[name + "Task"]["Properties"]
        assert (task["Cpu"], task["Memory"]) == expected
        assert all(c["Essential"] for c in task["ContainerDefinitions"])
        assert all(c["StopTimeout"] <= 120 for c in task["ContainerDefinitions"])
    media = resources["MediaTask"]["Properties"]["ContainerDefinitions"]
    assert sum(c["Cpu"] for c in media) == 1024
    assert media[1]["Command"] == ["python", "-m", "media.recovery"]
    assert "HealthCheck" not in media[1]
    worker = resources["WorkerTask"]["Properties"]["ContainerDefinitions"][0]
    assert worker["Command"] == {"Ref": "WorkerCommand"}
    assert worker["Memory"] == {"Ref": "WorkerContainerMemory"}
    assert "DC2_WORKER_LIFETIME_SECONDS" in json.dumps(worker["Environment"])
    for owner in ["Media", "Processing"]:
        migration = resources[owner + "MigrationTask"]["Properties"]["ContainerDefinitions"][0]
        assert owner.lower() + "/alembic.ini" in migration["Command"]
        assert migration["Secrets"] == [
            {
                "Name": owner.upper() + "_POSTGRES_DSN",
                "ValueFrom": {"Ref": owner + "MigrationDsnArn"},
            }
        ]
    recovery = resources["RecoveryTask"]["Properties"]["ContainerDefinitions"][0]
    assert {"Name": "PROCESSING_RECOVERY_INTERVAL_SECONDS", "Value": "15"} in recovery[
        "Environment"
    ]


def test_edge_cache_cookies_methods_error_ttls_and_private_activation():
    resources = environment_template()["Resources"]
    edge = resources["Distribution"]["Properties"]["DistributionConfig"]
    assert edge["Enabled"] is False
    assert edge["ViewerCertificate"] == {"CloudFrontDefaultCertificate": True}
    assert edge["Origins"][0]["CustomOriginConfig"]["OriginProtocolPolicy"] == "http-only"
    assert "OriginCustomHeaders" not in edge["Origins"][0]  # Private later injection.
    assert [b["PathPattern"] for b in edge["CacheBehaviors"]] == ["/api", "/api/*"]
    for behavior in [edge["DefaultCacheBehavior"], *edge["CacheBehaviors"]]:
        assert len(behavior["AllowedMethods"]) == 7
        assert behavior["ViewerProtocolPolicy"] == "https-only"
        assert behavior["CachePolicyId"] == {"Ref": "NoCache"}
    cache = resources["NoCache"]["Properties"]["CachePolicyConfig"]
    assert cache["MinTTL"] == cache["DefaultTTL"] == cache["MaxTTL"] == 0
    policy = resources["ApiOriginPolicy"]["Properties"]["OriginRequestPolicyConfig"]
    assert policy["HeadersConfig"]["HeaderBehavior"] == "allViewer"
    assert policy["CookiesConfig"]["CookieBehavior"] == "all"
    assert policy["QueryStringsConfig"]["QueryStringBehavior"] == "all"
    assert all(
        e["ErrorCachingMinTTL"] == 0 and "ResponsePagePath" not in e
        for e in edge["CustomErrorResponses"]
    )
    plan = private_edge_activation_plan(
        {
            "mode": "plan",
            "region": "",
            "account_id": "",
            "environment_id": "aws2-demo",
            "source_bucket": "",
            "output_bucket": "",
            "operator_station": "",
            "public_url": "",
        }
    )
    assert plan["status"] == "BLOCKED" and plan["execute"] is False


def test_state_configuration_only_and_bounded_streaming():
    compose = yaml.safe_load((ROOT / "deploy/aws/state/compose.yml").read_text())
    assert set(compose["services"]) == {"postgres", "redis", "nginx"}
    assert "127.0.0.1" in str(compose["services"]["postgres"]["healthcheck"])
    assert all(
        "DC2_STATE_PRIVATE_IP" in p
        for name in ["postgres", "redis"]
        for p in compose["services"][name]["ports"]
    )
    redis = (ROOT / "deploy/aws/state/redis.conf").read_text()
    assert "maxmemory 48mb" in redis and "maxmemory-policy noeviction" in redis
    nginx = (ROOT / "deploy/aws/nginx.conf.template").read_text()
    for expected in [
        "proxy_request_buffering off",
        "client_max_body_size 101m",
        "valid=5s",
        "DC2_VPC_RESOLVER",
        "X-Forwarded-Proto https",
        "origin-gate.conf",
        "location = /api",
        "location ^~ /internal/",
        "proxy_intercept_errors off",
    ]:
        assert expected in nginx
    assert "proxy_pass http://minio" not in nginx
    assert "access_log off" in nginx and "try_files $uri $uri/ =404" in nginx


@pytest.mark.parametrize(
    "present,uuid,root,options,expected",
    [
        (False, "data-uuid", "root-uuid", "rw,relatime", 1),
        (True, "wrong-uuid", "root-uuid", "rw,relatime", 1),
        (True, "data-uuid", "data-uuid", "rw,relatime", 1),
        (True, "data-uuid", "root-uuid", "ro,relatime", 1),
        (True, "data-uuid", "root-uuid", "rw,relatime", 0),
    ],
)
def test_mount_guard_fake_commands_only(tmp_path, present, uuid, root, options, expected):
    mountpoint = tmp_path / "mountpoint"
    mountpoint.write_text("#!/bin/sh\nexit " + ("0" if present else "1") + "\n")
    findmnt = tmp_path / "findmnt"
    findmnt.write_text(f"""#!/bin/sh
case "$5" in
UUID) case "$3" in /) printf '%s\\n' '{root}';; *) printf '%s\\n' '{uuid}';; esac;;
OPTIONS) printf '%s\\n' '{options}';;
*) exit 1;;
esac
""")
    mountpoint.chmod(0o700)
    findmnt.chmod(0o700)
    result = subprocess.run(
        ["/bin/sh", str(ROOT / "deploy/aws/state/mount-guard.sh")],
        env={
            "PATH": str(tmp_path) + ":/usr/bin:/bin",
            "DC2_DATA_UUID": "data-uuid",
            "DC2_DATA_MOUNT": "/srv/dc2-data",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == expected
    commands = "\n".join(
        line
        for line in (ROOT / "deploy/aws/state/mount-guard.sh").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "mkfs" not in commands


def test_readiness_distinguishes_liveness_from_owner_and_peer_receipts():
    for owner in ["media", "processing"]:
        plan = readiness_plan(owner)
        assert plan["status"] == "NOT_RUN" and plan["migration"]["peer_migration"] is False
        assert "owned_alembic_revision" in plan["required_receipts"]
        assert "authenticated_peer_owner_contract" in plan["required_receipts"]
    with pytest.raises(ValueError):
        readiness_plan("legacy")


def test_generator_is_separate_ephemeral_and_without_inbound():
    generator = generator_template()["Resources"]
    instance = generator["Generator"]["Properties"]
    assert instance["InstanceType"] == "c6a.large"
    assert instance["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"] == 8
    assert instance["BlockDeviceMappings"][0]["Ebs"]["DeleteOnTermination"]
    assert "SecurityGroupIngress" not in generator["GeneratorSG"]["Properties"]
    assert "Generator" not in environment_template()["Resources"]
