"""V1 CloudFormation builder. Pure data only: never imports an AWS SDK."""

import argparse
import dataclasses
import hashlib
import json
import re
from pathlib import Path

from processing import short_lane

RDS_CA_BUNDLE = "/opt/rds/global-bundle.pem"
# Opt-in V2 experiment (#68). Every resource whose name starts with this exists only when the
# stack is deployed with UnattendedLaunch=true, so the default V1 stack gains nothing.
LAUNCHER = "ProcessingLauncher"
# Opt-in V2 experiment (#93). Same rule: with LambdaShortEncodes=false none of these exist, and
# the only trace in the default stack is an environment value that resolves to nothing.
SHORT_ENCODER = "ProcessingShortEncoder"
SHORT_QUEUE = "ProcessingShortWork"
OPTIONAL_FUNCTIONS = (LAUNCHER, SHORT_ENCODER)
# Who reads and writes each domain's idle markers (runtime_support.activity, AD-27): writers
# record a request before committing it; the repair schedule reads both and writes `quiet`; the
# launcher only reads.
ACTIVITY_ROLES = {
    "Media": {"writers": ("MediaApi", "MediaResults"), "repair": "MediaRepair"},
    "Processing": {"writers": ("ProcessingCommands",), "repair": "ProcessingRepair"},
}
# The Processing functions that publish work onto processing-work, and so wake the launcher.
WORK_PUBLISHERS = ("ProcessingCommands", "ProcessingRepair", "ProcessingEcsEvents",
                   "ProcessingS3Events")


# Opt-in V2 experiment (#94). The database layout is chosen when the template is rendered, not by
# a CloudFormation parameter: CloudFormation cannot make one resource set appear and another
# disappear under a single name without conditions on every output, rule and reference, and a
# parameter would change the bytes of every V1 template. Rendered with the defaults below, the
# template is byte-for-byte the one V1 shipped (`tests/aws/v1/test_database_topology.py`).
SHARED, SEPARATE = "shared", "separate"
DOMAINS = ("Media", "Processing")
# Aurora Serverless v2 accepts auto-pause after 300 s to 24 h, and a maximum of 1 to 256 ACU in
# half steps (with a minimum of 0 the maximum must be at least 1).
AUTO_PAUSE_SECONDS_RANGE = (300, 86_400)
MAX_CAPACITY_RANGE = (1, 256)
DEFAULT_AUTO_PAUSE_SECONDS, DEFAULT_MAX_CAPACITY = 300, 2
# Who may open a connection to each cluster. A Fargate encoder belongs to Processing only, so
# in the separate layout Media's cluster does not admit it. Lambda and the migration task are
# shared by both domains today, so both clusters admit them.
SHARED_DATABASE_SOURCES = ("Lambda", "Worker", "Migration")
SEPARATE_DATABASE_SOURCES = {
    "Media": ("Lambda", "Migration"),
    "Processing": ("Lambda", "Worker", "Migration"),
}


@dataclasses.dataclass(frozen=True)
class DatabaseOptions:
    """How Aurora is laid out and when it pauses. The defaults are V1."""

    topology: str = SHARED
    auto_pause_seconds: int = DEFAULT_AUTO_PAUSE_SECONDS
    max_capacity: float = DEFAULT_MAX_CAPACITY

    def __post_init__(self):
        if self.topology not in (SHARED, SEPARATE):
            raise ValueError("Database topology is shared or separate")
        low, high = AUTO_PAUSE_SECONDS_RANGE
        if type(self.auto_pause_seconds) is not int or not low <= self.auto_pause_seconds <= high:
            raise ValueError(f"Auto-pause is {low} to {high} seconds")
        low, high = MAX_CAPACITY_RANGE
        capacity = self.max_capacity
        if (type(capacity) not in (int, float) or not low <= capacity <= high
                or capacity * 2 != int(capacity * 2)):
            raise ValueError(f"Maximum capacity is {low} to {high} ACU in steps of 0.5")
        if type(capacity) is float and capacity == int(capacity):
            object.__setattr__(self, "max_capacity", int(capacity))  # 2.0 renders as 2

    @property
    def clusters(self):
        return 1 if self.topology == SHARED else len(DOMAINS)

    def as_dict(self):
        return dataclasses.asdict(self)


def gate_of(name):
    """The stack condition a resource named `name` lives under."""
    if name.startswith(LAUNCHER):
        return "Unattended"
    if name.startswith((SHORT_ENCODER, SHORT_QUEUE)):
        return "ShortEncodes"
    return "Applications"


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def attr(name, key="Arn"):
    return {"Fn::GetAtt": [name, key]}


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def allow(actions, resources, condition=None):
    statement = {"Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        statement["Condition"] = condition
    return statement


def prefixes(*values):
    """Limit a bucket-level list call to keys under the owner's own prefixes."""
    return {"StringLike": {"s3:prefix": list(values)}}


def db_ca_env(domain):
    """Each owner's Settings class names its CA variable differently; the name is load-bearing.

    A misspelled name is silently ignored (extra="ignore"), so TLS verification would fall
    back to the system trust store and fail only inside AWS.
    """
    if domain.upper() == "MEDIA":
        return {"MEDIA_POSTGRES_SSL_CA": RDS_CA_BUNDLE}
    return {"PROCESSING_DATABASE_TLS": "true", "PROCESSING_DATABASE_CA_FILE": RDS_CA_BUNDLE}


# Parameters a function refers to whose value is fixed by the environment's name, so they cannot
# change under a live alias; the image is named separately, by its digest.
FIXED_PARAMETERS = ("EnvironmentId",)


def references(value, found, conditions):
    """Every Ref/GetAtt/Sub target and Fn::If condition inside a property tree."""
    if isinstance(value, list):
        for item in value:
            references(item, found, conditions)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "Ref":
                found.add(item)
            elif key == "Fn::GetAtt":
                found.add(item[0])
            elif key == "Fn::Sub":
                text = item if isinstance(item, str) else item[0]
                found.update(m.split(".")[0] for m in re.findall(r"\$\{([^}!]+)\}", text))
                if not isinstance(item, str):
                    references(item[1], found, conditions)
            elif key == "Fn::If":
                conditions.add(item[0])
                references(item[1:], found, conditions)
            else:
                references(item, found, conditions)


def version_description(domain, image, properties, parameters, resources):
    """What a function's published version runs, resolved at deploy time.

    An alias moves only when its Version resource is replaced, and that happens only when the
    Version's own properties change. This description changes whenever the function's image,
    its definition, a parameter or condition it reads, or a task definition it names changes,
    even though the function's template text names those only by reference (#235).
    """
    found, conditions = set(), set()
    references(properties, found, conditions)
    digest = hashlib.sha256(json.dumps(properties, sort_keys=True).encode()).hexdigest()[:12]
    parts = [domain, {"Fn::Select": [1, {"Fn::Split": ["@", ref(f"{image}ImageUri")]}]}, digest]
    for name in sorted(found):
        if name in parameters and name not in FIXED_PARAMETERS and not name.endswith(
                ("ImageUri", "ParameterArn")):
            parts.append(ref(name))
        elif resources.get(name, {}).get("Type") == "AWS::ECS::TaskDefinition":
            # family:revision, which a replacement always changes
            parts.append({"Fn::Select": [1, {"Fn::Split": ["/", ref(name)]}]})
    parts += [{"Fn::If": [name, f"{name}=1", f"{name}=0"]} for name in sorted(conditions)]
    return {"Fn::Join": [" ", parts]}


def template(database=None):
    """Closed-by-default two-phase stack; resources retained where data is durable."""
    database = database or DatabaseOptions()
    # Logical stem of each cluster -> the domains whose database it holds. The shared layout
    # keeps V1's names so that nothing about it changes.
    if database.topology == SHARED:
        stems = {"Database": SHARED_DATABASE_SOURCES}
    else:
        stems = {f"{domain}Database": SEPARATE_DATABASE_SOURCES[domain] for domain in DOMAINS}
    parameters = {
        "EnvironmentId": {"Type": "String", "AllowedPattern": "[a-z][a-z0-9-]{2,23}"},
        "DeployApplications": {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["true", "false"],
        },
        "AuroraEngineVersion": {"Type": "String", "Default": "16.8"},
        "WorkerLifetimeSeconds": {
            "Type": "Number",
            "Default": 1800,
            "MinValue": 60,
            "MaxValue": 3600,
        },
        "SourceCorsOrigin": {"Type": "String", "AllowedPattern": "https://[a-zA-Z0-9.-]+"},
        "UnattendedLaunch": {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["true", "false"],
        },
        "LambdaShortEncodes": {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["true", "false"],
        },
        # V2-live (#236): the persistent environment deploys open. False keeps V1's closed
        # template, where only a booked session opens the API, consumers and schedules.
        "AlwaysOn": {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["true", "false"],
        },
        # The gates (stage throttle, consumers, schedules) of an always-on environment. False
        # while the kill switch is on, so a stack update keeps closed gates closed.
        "GatesOpen": {
            "Type": "String",
            "Default": "true",
            "AllowedValues": ["true", "false"],
        },
        "StageRateLimit": {"Type": "Number", "Default": 20, "MinValue": 1, "MaxValue": 1000},
        "StageBurstLimit": {"Type": "Number", "Default": 50, "MinValue": 1, "MaxValue": 2000},
        "MonthlyBudgetUsd": {"Type": "Number", "Default": 20, "MinValue": 1, "MaxValue": 1000},
        # Empty means the alerts reach only the SNS topic; anyone can subscribe to it later.
        "BudgetAlertEmail": {
            "Type": "String",
            "Default": "",
            "AllowedPattern": r"^$|^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$",
        },
    }
    for domain in ("Media", "Processing", "Worker"):
        parameters[f"{domain}ImageUri"] = {
            "Type": "String",
            "Default": "",
            "AllowedPattern": (
                r"^$|^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/"
                r"[a-z0-9/_-]+@sha256:[a-f0-9]{64}$"
            ),
        }
    for name in (
        "MediaRuntimeDsn",
        "ProcessingRuntimeDsn",
        "MediaMigrationDsn",
        "ProcessingMigrationDsn",
        "JwtSecret",
    ):
        parameters[f"{name}ParameterArn"] = {
            "Type": "String",
            "AllowedPattern": r"^arn:aws:ssm:[a-z0-9-]+:[0-9]{12}:parameter/[a-zA-Z0-9_/.-]+$",
        }
    handlers = {
        "MediaApi": "media.lambda_handler.handler",
        "MediaAuthorizer": "media.lambda_handler.authorizer",
        "ProcessingApi": "processing.lambda_handler.handler",
        "ProcessingCommands": "processing.handlers.command_handler",
        "MediaResults": "media.handlers.result_handler",
        "MediaRepair": "media.handlers.repair_handler",
        "ProcessingRepair": "processing.handlers.repair_handler",
        "ProcessingEcsEvents": "processing.handlers.ecs_handler",
        "ProcessingS3Events": "processing.handlers.s3_handler",
        LAUNCHER: "processing.handlers.launcher_handler",
        SHORT_ENCODER: "processing.handlers.short_encoder_handler",
    }
    for name, handler in handlers.items():
        parameters[f"{name}Handler"] = {"Type": "String", "Default": handler}
    resources = {}

    def add(name, kind, properties, *, app=False, retain=False, depends=None, gate=None):
        resource = {"Type": f"AWS::{kind}", "Properties": properties}
        if gate:
            resource["Condition"] = gate
        elif app:
            resource["Condition"] = gate_of(name)
        if retain:
            resource.update(DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
        if depends:
            resource["DependsOn"] = depends
        resources[name] = resource

    tags = [
        {"Key": "Project", "Value": "dc2"},
        {"Key": "Environment", "Value": ref("EnvironmentId")},
    ]
    add(
        "Vpc",
        "EC2::VPC",
        {
            "CidrBlock": "10.62.0.0/16",
            "EnableDnsSupport": True,
            "EnableDnsHostnames": True,
            "Tags": tags,
        },
    )
    add("VpcIpv6", "EC2::VPCCidrBlock", {"VpcId": ref("Vpc"), "AmazonProvidedIpv6CidrBlock": True})
    add("InternetGateway", "EC2::InternetGateway", {"Tags": tags})
    add(
        "GatewayAttachment",
        "EC2::VPCGatewayAttachment",
        {"VpcId": ref("Vpc"), "InternetGatewayId": ref("InternetGateway")},
    )
    add("EgressOnlyGateway", "EC2::EgressOnlyInternetGateway", {"VpcId": ref("Vpc")})
    for index, suffix in enumerate(("A", "B")):
        for public in (False, True):
            name = ("Public" if public else "Private") + suffix
            block = index + (2 if public else 0)
            add(
                f"{name}Subnet",
                "EC2::Subnet",
                {
                    "VpcId": ref("Vpc"),
                    "CidrBlock": f"10.62.{block}.0/24",
                    "AvailabilityZone": {"Fn::Select": [index, {"Fn::GetAZs": ""}]},
                    "Ipv6CidrBlock": {
                        "Fn::Select": [
                            block,
                            {
                                "Fn::Cidr": [
                                    {"Fn::Select": [0, attr("Vpc", "Ipv6CidrBlocks")]},
                                    4,
                                    64,
                                ]
                            },
                        ]
                    },
                    "AssignIpv6AddressOnCreation": True,
                    "MapPublicIpOnLaunch": False,
                    "Tags": tags,
                },
                depends="VpcIpv6",
            )
            add(f"{name}RouteTable", "EC2::RouteTable", {"VpcId": ref("Vpc"), "Tags": tags})
            add(
                f"{name}RouteAssociation",
                "EC2::SubnetRouteTableAssociation",
                {"SubnetId": ref(f"{name}Subnet"), "RouteTableId": ref(f"{name}RouteTable")},
            )
            add(
                f"{name}Ipv6Route",
                "EC2::Route",
                {
                    "RouteTableId": ref(f"{name}RouteTable"),
                    "DestinationIpv6CidrBlock": "::/0",
                    ("GatewayId" if public else "EgressOnlyInternetGatewayId"): ref(
                        "InternetGateway" if public else "EgressOnlyGateway"
                    ),
                },
                depends="GatewayAttachment" if public else None,
            )
            if public:
                add(
                    f"{name}Ipv4Route",
                    "EC2::Route",
                    {
                        "RouteTableId": ref(f"{name}RouteTable"),
                        "DestinationCidrBlock": "0.0.0.0/0",
                        "GatewayId": ref("InternetGateway"),
                    },
                    depends="GatewayAttachment",
                )
    add(
        "S3Gateway",
        "EC2::VPCEndpoint",
        {
            "VpcId": ref("Vpc"),
            "VpcEndpointType": "Gateway",
            "ServiceName": sub("com.amazonaws.${AWS::Region}.s3"),
            "RouteTableIds": [
                ref(f"{kind}{suffix}RouteTable")
                for kind in ("Private", "Public")
                for suffix in ("A", "B")
            ],
            "PolicyDocument": policy(
                [
                    {
                        "Principal": "*",
                        **allow(
                            ["s3:*"],
                            [
                                attr("SourceBucket"),
                                sub("${SourceBucket.Arn}/*"),
                                attr("OutputBucket"),
                                sub("${OutputBucket.Arn}/*"),
                            ],
                        ),
                    },
                    # Public task subnets also have this gateway route. ECR's
                    # presigned image-layer downloads need the regional starport bucket.
                    {
                        "Principal": "*",
                        **allow(
                            ["s3:GetObject"],
                            [
                                sub(
                                    "arn:${AWS::Partition}:s3:::prod-${AWS::Region}-starport-layer-bucket/*"
                                )
                            ],
                        ),
                    },
                ]
            ),
        },
    )
    for name in ("Lambda", "Worker", "Migration", *stems):
        egress = (
            [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIpv6": "::/0"}]
            if name == "Lambda"
            else [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}]
        )
        if name in stems:
            egress = [{"IpProtocol": "tcp", "FromPort": 1, "ToPort": 1, "CidrIp": "127.0.0.1/32"}]
        else:
            egress.extend(
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "DestinationSecurityGroupId": ref(f"{stem}SecurityGroup"),
                }
                for stem, sources in stems.items()
                if name in sources
            )
        if name == "Lambda":
            # S3 gateway routes are IPv4. PrefixList ID is not exposed by CFN;
            # the route table narrows this CIDR rule to S3 on private subnets.
            egress.append(
                {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}
            )
        add(
            f"{name}SecurityGroup",
            "EC2::SecurityGroup",
            {
                "GroupDescription": f"DC2 V1 {name}",
                "VpcId": ref("Vpc"),
                "SecurityGroupEgress": egress,
                "Tags": tags,
            },
        )
    for stem, sources in stems.items():
        for name in sources:
            add(
                f"{stem}From{name}",
                "EC2::SecurityGroupIngress",
                {
                    "GroupId": ref(f"{stem}SecurityGroup"),
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "SourceSecurityGroupId": ref(f"{name}SecurityGroup"),
                },
            )
    add(
        "DbSubnets",
        "RDS::DBSubnetGroup",
        {
            "DBSubnetGroupDescription": "Two private dual-stack AZs",
            "SubnetIds": [ref("PrivateASubnet"), ref("PrivateBSubnet")],
            "Tags": tags,
        },
    )
    add(
        "DbParameters",
        "RDS::DBClusterParameterGroup",
        {
            "Description": "Require verified TLS",
            "Family": "aurora-postgresql16",
            "Parameters": {"rds.force_ssl": "1"},
        },
    )
    for stem in stems:
        add(
            f"{stem}Cluster",
            "RDS::DBCluster",
            {
                "Engine": "aurora-postgresql",
                "EngineVersion": ref("AuroraEngineVersion"),
                "EngineMode": "provisioned",
                "MasterUsername": "dc2bootstrap",
                "ManageMasterUserPassword": True,
                "DBSubnetGroupName": ref("DbSubnets"),
                "DBClusterParameterGroupName": ref("DbParameters"),
                "VpcSecurityGroupIds": [ref(f"{stem}SecurityGroup")],
                "StorageEncrypted": True,
                "BackupRetentionPeriod": 1,
                "DeletionProtection": True,
                "NetworkType": "DUAL",
                "ServerlessV2ScalingConfiguration": {
                    "MinCapacity": 0,
                    "MaxCapacity": database.max_capacity,
                    "SecondsUntilAutoPause": database.auto_pause_seconds,
                },
                "Tags": tags,
            },
            retain=True,
        )
        add(
            f"{stem}Instance",
            "RDS::DBInstance",
            {
                "DBClusterIdentifier": ref(f"{stem}Cluster"),
                "DBInstanceClass": "db.serverless",
                "Engine": "aurora-postgresql",
                "PubliclyAccessible": False,
                "DBSubnetGroupName": ref("DbSubnets"),
                "Tags": tags,
            },
            retain=True,
        )
    for name in ("Source", "Output", "Frontend"):
        props = {
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "VersioningConfiguration": {"Status": "Enabled"},
            "Tags": tags,
        }
        if name == "Source":
            props["CorsConfiguration"] = {
                "CorsRules": [
                    {
                        "AllowedOrigins": [ref("SourceCorsOrigin")],
                        "AllowedMethods": ["POST"],
                        "AllowedHeaders": ["content-type", "x-amz-*"],
                        "ExposedHeaders": ["ETag", "x-amz-version-id"],
                        "MaxAge": 300,
                    }
                ]
            }
        if name == "Output":
            props["NotificationConfiguration"] = {
                "EventBridgeConfiguration": {"EventBridgeEnabled": True}
            }
            props["CorsConfiguration"] = {
                "CorsRules": [
                    {
                        "AllowedOrigins": [ref("SourceCorsOrigin")],
                        "AllowedMethods": ["GET", "HEAD"],
                        # Native HLS reads segments in CORS mode (the player sets
                        # crossorigin) after the API's 307. Range is the browser's;
                        # AVFoundation also tags its requests with X-Playback-Session-Id,
                        # which would otherwise force a preflight that S3 rejects.
                        "AllowedHeaders": ["Range", "X-Playback-Session-Id"],
                        "ExposedHeaders": ["Accept-Ranges", "Content-Length", "Content-Range"],
                        "MaxAge": 300,
                    }
                ]
            }
        add(f"{name}Bucket", "S3::Bucket", props, retain=True)
    for name in ("ProcessingCommands", "ProcessingWork", "MediaResults"):
        add(
            f"{name}Dlq",
            "SQS::Queue",
            {"MessageRetentionPeriod": 1209600, "SqsManagedSseEnabled": True, "Tags": tags},
        )
        add(
            f"{name}Queue",
            "SQS::Queue",
            {
                "MessageRetentionPeriod": 604800,
                "ReceiveMessageWaitTimeSeconds": 20,
                "VisibilityTimeout": 420,
                "SqsManagedSseEnabled": True,
                "RedrivePolicy": {"deadLetterTargetArn": attr(f"{name}Dlq"), "maxReceiveCount": 5},
                "Tags": tags,
            },
        )
        add(
            f"{name}DlqPolicy",
            "SQS::QueuePolicy",
            {
                "Queues": [ref(f"{name}Dlq")],
                "PolicyDocument": policy(
                    [
                        {
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "sqs:*",
                            "Resource": attr(f"{name}Dlq"),
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ]
                ),
            },
        )
    # The short lane's own queue and dead-letter queue (V2, #93). Its visibility timeout is
    # the function timeout plus a minute: SQS refuses a mapping below the timeout, and the
    # message must not reappear while its invocation could still be running.
    add(
        f"{SHORT_QUEUE}Dlq",
        "SQS::Queue",
        {"MessageRetentionPeriod": 1209600, "SqsManagedSseEnabled": True, "Tags": tags},
        gate="ShortEncodes",
    )
    add(
        f"{SHORT_QUEUE}Queue",
        "SQS::Queue",
        {
            "MessageRetentionPeriod": 604800,
            "ReceiveMessageWaitTimeSeconds": 20,
            "VisibilityTimeout": short_lane.QUEUE_VISIBILITY_SECONDS,
            "SqsManagedSseEnabled": True,
            "RedrivePolicy": {
                "deadLetterTargetArn": attr(f"{SHORT_QUEUE}Dlq"),
                "maxReceiveCount": 5,
            },
            "Tags": tags,
        },
        gate="ShortEncodes",
    )
    add(
        f"{SHORT_QUEUE}DlqPolicy",
        "SQS::QueuePolicy",
        {
            "Queues": [ref(f"{SHORT_QUEUE}Dlq")],
            "PolicyDocument": policy(
                [
                    {
                        "Effect": "Deny",
                        "Principal": "*",
                        "Action": "sqs:*",
                        "Resource": attr(f"{SHORT_QUEUE}Dlq"),
                        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    }
                ]
            ),
        },
        gate="ShortEncodes",
    )
    for domain in ("Media", "Processing", "Worker"):
        add(
            f"{domain}Repository",
            "ECR::Repository",
            {
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
                "EncryptionConfiguration": {"EncryptionType": "AES256"},
                "Tags": tags,
            },
            retain=True,
        )
    add(
        "Cluster",
        "ECS::Cluster",
        {"ClusterSettings": [{"Name": "containerInsights", "Value": "disabled"}], "Tags": tags},
    )

    # IAM roles are per handler. No credential can read its peer's DB parameters.
    receive = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility",
    ]
    source_objects = sub("${SourceBucket.Arn}/*")
    output_objects = sub("${OutputBucket.Arn}/*")

    def queue_arn(name):
        return attr(f"{name}Queue")

    # Each grant below is the S3 surface that role's code actually reaches; the mapping
    # from code path to action is asserted in tests/aws/v1/test_infrastructure.py. Version
    # cleanup needs ListBucketVersions (ListObjectVersions) and DeleteObjectVersion: a plain
    # DeleteObject only adds a delete marker and leaves the stored bytes.
    output_jobs = sub("${OutputBucket.Arn}/jobs/*")
    source_read = allow(["s3:GetObject", "s3:GetObjectVersion"], [source_objects])
    output_write = allow(["s3:PutObject", "s3:AbortMultipartUpload"], [output_objects])
    source_versions = [
        allow(
            ["s3:ListBucketVersions"],
            [attr("SourceBucket")],
            prefixes("sources/*", "staging/*"),
        ),
        allow(["s3:DeleteObjectVersion"], [source_objects]),
    ]
    media_api_storage = [
        allow(
            [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:PutObject",
                # A failed multipart copy of an output into a source must be abortable.
                "s3:AbortMultipartUpload",
            ],
            [source_objects],
        ),
        # Media reads outputs (playlists, signed GETs) but never writes or deletes them.
        allow(["s3:GetObject", "s3:GetObjectVersion"], [output_objects]),
        allow(["s3:ListBucket"], [attr("SourceBucket"), attr("OutputBucket")]),
        *source_versions,
    ]
    # Processing's three cleanup entrypoints (repair, ECS stop, S3 hint) all run the same
    # late-output cleanup, which lists and deletes versions under owned attempt prefixes.
    output_cleanup = [
        allow(["s3:ListBucketVersions"], [attr("OutputBucket")], prefixes("jobs/*")),
        allow(["s3:DeleteObjectVersion"], [output_jobs]),
    ]
    privileges = {
        "MediaApi": media_api_storage,
        "MediaAuthorizer": [],
        "ProcessingApi": [],
        "ProcessingCommands": [
            allow(receive, [queue_arn("ProcessingCommands")]),
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
        ],
        "MediaResults": [allow(receive, [queue_arn("MediaResults")])],
        # Repair only deletes source versions (tombstones, expired grants, staged orphans).
        "MediaRepair": source_versions
        + [allow(["sqs:SendMessage"], [queue_arn("ProcessingCommands")])],
        "ProcessingRepair": [
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
            *output_cleanup,
        ],
        "ProcessingEcsEvents": [
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
            *output_cleanup,
        ],
        # The S3 hint runs the same pass as repair, including the outbox publish.
        "ProcessingS3Events": [
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
            *output_cleanup,
        ],
        # Starts finite workers only: RunTask on the worker task definition family, the two
        # roles that task passes to ECS, and read-only views of this cluster's tasks. It has
        # no queue send/receive, no S3 and no stop/update, so a bug cannot reach beyond a
        # bounded number of finite tasks.
        LAUNCHER: [
            allow(
                ["ecs:RunTask"],
                [
                    sub(
                        "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:"
                        "task-definition/${EnvironmentId}-worker:*"
                    )
                ],
                {"ArnEquals": {"ecs:cluster": attr("Cluster")}},
            ),
            allow(
                ["iam:PassRole"],
                [attr("WorkerRole"), attr("WorkerExecutionRole")],
                {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            ),
            allow(["ecs:ListTasks"], ["*"], {"ArnEquals": {"ecs:cluster": attr("Cluster")}}),
            allow(
                ["ecs:DescribeTasks"],
                [
                    sub(
                        "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:"
                        "task/${Cluster}/*"
                    )
                ],
                {"ArnEquals": {"ecs:cluster": attr("Cluster")}},
            ),
            allow(["sqs:GetQueueAttributes"], [queue_arn("ProcessingWork")]),
        ],
        "Worker": [
            source_read,
            output_write,
            allow(receive, [queue_arn("ProcessingWork")]),
        ],
        # The Lambda twin of "Worker": the same two S3 grants and the same queue verbs, on the
        # short queue instead. It cannot send, list, delete outputs, or reach any other queue,
        # and its DSN parameter is the Processing runtime one added below like every handler's.
        SHORT_ENCODER: [
            source_read,
            output_write,
            allow(receive, [queue_arn(SHORT_QUEUE)]),
        ],
        "MediaMigration": [],
        "ProcessingMigration": [],
    }
    for name, statements in privileges.items():
        domain = "Media" if name.startswith("Media") else "Processing"
        secret_names = [
            f"{domain}{'Migration' if name.endswith('Migration') else 'Runtime'}DsnParameterArn"
        ]
        if name in ("MediaApi", "MediaAuthorizer"):
            secret_names.append("JwtSecretParameterArn")
        statements = list(statements) + [
            allow(["ssm:GetParameter", "ssm:GetParameters"], [ref(k) for k in secret_names])
        ]
        if name in handlers:
            log_name = f"{name}LogGroup"
            add(
                log_name,
                "Logs::LogGroup",
                {"LogGroupName": sub(f"/dc2/${{EnvironmentId}}/{name}"), "RetentionInDays": 7},
                app=True,
            )
            statements.append(
                allow(["logs:CreateLogStream", "logs:PutLogEvents"], [attr(log_name)])
            )
            statements += [
                allow(
                    [
                        "ec2:CreateNetworkInterface",
                        "ec2:DescribeNetworkInterfaces",
                        "ec2:DescribeSubnets",
                        "ec2:DeleteNetworkInterface",
                        "ec2:AssignPrivateIpAddresses",
                        "ec2:UnassignPrivateIpAddresses",
                    ],
                    ["*"],
                )
            ]
        service = "lambda.amazonaws.com" if name in handlers else "ecs-tasks.amazonaws.com"
        add(
            f"{name}Role",
            "IAM::Role",
            {
                "AssumeRolePolicyDocument": policy(
                    [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": service},
                            "Action": "sts:AssumeRole",
                        }
                    ]
                ),
                "Policies": [{"PolicyName": "owned-runtime", "PolicyDocument": policy(statements)}],
                "Tags": tags,
            },
            app=True,
        )
    # Queue resource policy enforces producer boundaries even if another identity
    # accidentally receives an identity-based SendMessage grant.
    producers = {
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
        # Same four publishers as the standard work lane, and only the Lambda executor reads it.
        SHORT_QUEUE: [
            "ProcessingCommands",
            "ProcessingRepair",
            "ProcessingEcsEvents",
            "ProcessingS3Events",
        ],
    }
    # Only the work publishers may invoke the launcher, and only its alias (#237).
    add(
        f"{LAUNCHER}Invokers",
        "IAM::Policy",
        {
            "PolicyName": "launcher-wake",
            "Roles": [ref(f"{role}Role") for role in WORK_PUBLISHERS],
            "PolicyDocument": policy([allow(["lambda:InvokeFunction"], [ref(f"{LAUNCHER}Alias")])]),
        },
        app=True,
    )
    # Idle markers (AD-27). String parameters, so no KMS; "0" reads as "not quiet".
    for domain, roles in ACTIVITY_ROLES.items():

        def marker(kind, domain=domain):
            return sub(
                "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter"
                f"${{{domain}Activity{kind}}}"
            )

        for kind in ("Touched", "Quiet"):
            add(
                f"{domain}Activity{kind}",
                "SSM::Parameter",
                {
                    "Name": sub(
                        f"/dc2/${{EnvironmentId}}/activity/{domain.lower()}/{kind.lower()}"
                    ),
                    "Type": "String",
                    "Value": "0",
                },
                gate="AlwaysOnEnv",
            )
        add(
            f"{domain}ActivityWriters",
            "IAM::Policy",
            {
                "PolicyName": "activity-touch",
                "Roles": [ref(f"{role}Role") for role in roles["writers"]],
                "PolicyDocument": policy([allow(["ssm:PutParameter"], [marker("Touched")])]),
            },
            gate="AlwaysOnEnv",
        )
        add(
            f"{domain}ActivityRepair",
            "IAM::Policy",
            {
                "PolicyName": "activity-quiet",
                "Roles": [ref(f"{roles['repair']}Role")],
                "PolicyDocument": policy([
                    allow(["ssm:GetParameter"], [marker("Touched"), marker("Quiet")]),
                    allow(["ssm:PutParameter"], [marker("Quiet")]),
                ]),
            },
            gate="AlwaysOnEnv",
        )
    add(
        "ProcessingActivityLauncherRead",
        "IAM::Policy",
        {
            "PolicyName": "activity-read",
            "Roles": [ref(f"{LAUNCHER}Role")],
            "PolicyDocument": policy([allow(["ssm:GetParameter"], [
                sub("arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter"
                    "${ProcessingActivityTouched}"),
                sub("arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter"
                    "${ProcessingActivityQuiet}"),
            ])]),
        },
        gate="AlwaysOnLauncher",
    )
    # The cost safety net of an always-on environment (#236): alerts at 50, 80 and 100 % of a
    # small monthly amount, on top of the per-service alarms. Account-wide, since the account
    # holds only this project.
    add("BudgetAlertTopic", "SNS::Topic", {"Tags": tags}, gate="AlwaysOnEnv")
    add(
        "BudgetAlertTopicPolicy",
        "SNS::TopicPolicy",
        {
            "Topics": [ref("BudgetAlertTopic")],
            "PolicyDocument": policy(
                [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "budgets.amazonaws.com"},
                        "Action": "sns:Publish",
                        "Resource": ref("BudgetAlertTopic"),
                        "Condition": {"StringEquals": {"aws:SourceAccount": ref("AWS::AccountId")}},
                    }
                ]
            ),
        },
        gate="AlwaysOnEnv",
    )
    add(
        "BudgetAlertSubscription",
        "SNS::Subscription",
        {"TopicArn": ref("BudgetAlertTopic"), "Protocol": "email",
         "Endpoint": ref("BudgetAlertEmail")},
        gate="BudgetEmail",
    )
    add(
        "MonthlyBudget",
        "Budgets::Budget",
        {
            "Budget": {
                "BudgetName": sub("${EnvironmentId}-monthly"),
                "BudgetType": "COST",
                "TimeUnit": "MONTHLY",
                "BudgetLimit": {"Amount": ref("MonthlyBudgetUsd"), "Unit": "USD"},
            },
            "NotificationsWithSubscribers": [
                {
                    "Notification": {
                        "NotificationType": "ACTUAL",
                        "ComparisonOperator": "GREATER_THAN",
                        "Threshold": percent,
                        "ThresholdType": "PERCENTAGE",
                    },
                    "Subscribers": [
                        {"SubscriptionType": "SNS", "Address": ref("BudgetAlertTopic")}
                    ],
                }
                for percent in (50, 80, 100)
            ],
        },
        gate="AlwaysOnEnv",
        depends=["BudgetAlertTopicPolicy"],
    )
    consumers = {
        "ProcessingCommands": ["ProcessingCommands"],
        "ProcessingWork": ["Worker"],
        "MediaResults": ["MediaResults"],
        SHORT_QUEUE: [SHORT_ENCODER],
    }
    for name in producers:
        statements = [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "sqs:*",
                "Resource": queue_arn(name),
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ]
        for sid, actions, roles in (
            ("DenyUnlistedProducers", ["sqs:SendMessage"], producers[name]),
            (
                "DenyUnlistedConsumers",
                [a for a in receive if a != "sqs:GetQueueAttributes"],
                consumers[name],
            ),
        ):
            condition = {
                "ArnNotEquals": {"aws:PrincipalArn": [attr(f"{role}Role") for role in roles]}
            }
            if actions == ["sqs:SendMessage"]:
                # Operator exception, SendMessage only. A native DLQ redrive
                # (StartMessageMoveTask) and a poison-message injection both need
                # SendMessage on the source queue, and neither principal is a handler
                # role. Only this account's IAM users qualify (the operator's MFA
                # session keeps the user ARN); every Lambda or task role, the public
                # API roles included, and every foreign principal stay denied. The SQS
                # service name covers the case where the move task presents itself
                # instead of the caller. Receive/delete stay consumer-only.
                account_users = sub("arn:${AWS::Partition}:iam::${AWS::AccountId}:user/*")
                condition |= {
                    "ArnNotLike": {"aws:PrincipalArn": account_users},
                    "StringNotEquals": {"aws:PrincipalServiceName": "sqs.amazonaws.com"},
                }
            statements.append(
                {
                    "Sid": sid,
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": actions,
                    "Resource": queue_arn(name),
                    "Condition": condition,
                }
            )
        add(
            f"{name}QueuePolicy",
            "SQS::QueuePolicy",
            {"Queues": [ref(f"{name}Queue")], "PolicyDocument": policy(statements)},
            gate=gate_of(name),
        )
    # The four publishers may send to the short queue only when it exists. A separate policy
    # resource keeps their default roles byte-for-byte what V1 reviewed.
    add(
        f"{SHORT_QUEUE}Senders",
        "IAM::Policy",
        {
            "PolicyName": "short-lane-send",
            "Roles": [ref(f"{role}Role") for role in producers[SHORT_QUEUE]],
            "PolicyDocument": policy([allow(["sqs:SendMessage"], [queue_arn(SHORT_QUEUE)])]),
        },
        gate="ShortEncodes",
    )
    common_env = {
        "AWS_USE_DUALSTACK_ENDPOINT": "true",
        "AWS_RETRY_MODE": "standard",
        "AWS_MAX_ATTEMPTS": "3",
        "DC2_RUNTIME": "v1",
        "DB_SSL_CA_FILE": RDS_CA_BUNDLE,
    }
    # A function is given the URL of a queue only if its code calls that queue: the publishers
    # send, the launcher reads the work queue's depth. A consumer reads from its event source
    # mapping, and the API functions and the short encoder touch no queue at all. The IAM role
    # and the queue policy already deny the rest; this keeps the environment (and with it what a
    # misconfigured log line or a dumped environment could reveal) to the same narrow surface,
    # so the template reads as the service graph: Media sends commands, Processing sends work
    # and results, nobody sends to a queue it does not own a message kind for.
    queue_env = {
        "ProcessingCommands": ("PROCESSING_WORK_QUEUE_URL", "MEDIA_RESULTS_QUEUE_URL"),
        "ProcessingRepair": ("PROCESSING_WORK_QUEUE_URL", "MEDIA_RESULTS_QUEUE_URL"),
        "ProcessingEcsEvents": ("PROCESSING_WORK_QUEUE_URL", "MEDIA_RESULTS_QUEUE_URL"),
        "ProcessingS3Events": ("PROCESSING_WORK_QUEUE_URL", "MEDIA_RESULTS_QUEUE_URL"),
        "MediaRepair": ("PROCESSING_COMMANDS_QUEUE_URL",),
        LAUNCHER: ("PROCESSING_WORK_QUEUE_URL",),
    }
    queue_of = {
        "PROCESSING_COMMANDS_QUEUE_URL": "ProcessingCommands",
        "PROCESSING_WORK_QUEUE_URL": "ProcessingWork",
        "MEDIA_RESULTS_QUEUE_URL": "MediaResults",
    }
    for name in handlers:
        domain = "Media" if name.startswith("Media") else "Processing"
        prefix = domain.upper()
        queues = {v: ref(f"{queue_of[v]}Queue") for v in queue_env.get(name, ())}
        env = common_env | queues | {
            f"{prefix}_POSTGRES_DSN_PARAMETER_ARN": ref(f"{domain}RuntimeDsnParameterArn"),
            f"{prefix}_STORAGE_CREDENTIAL_MODE": "lambda",
            f"{prefix}_RUNTIME_MODE": "lambda",
            **db_ca_env(domain),
            f"{prefix}_MINIO_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
            f"{prefix}_MINIO_USE_SSL": "true",
            f"{prefix}_MINIO_REGION": ref("AWS::Region"),
            f"{prefix}_MINIO_OUTPUT_BUCKET": ref("OutputBucket"),
        }
        if name == LAUNCHER:
            env |= {
                "PROCESSING_LAUNCHER_CLUSTER": attr("Cluster"),
                "PROCESSING_LAUNCHER_TASK_DEFINITION": ref("WorkerTaskDefinition"),
                "PROCESSING_LAUNCHER_SUBNETS": {
                    "Fn::Join": [",", [ref("PublicASubnet"), ref("PublicBSubnet")]]
                },
                "PROCESSING_LAUNCHER_SECURITY_GROUPS": ref("WorkerSecurityGroup"),
                "PROCESSING_LAUNCHER_LIFETIME_SECONDS": {"Fn::Sub": "${WorkerLifetimeSeconds}"},
                "PROCESSING_LAUNCHER_CAP": "3",
                # Always on, the launcher has no session end to stop at (#237).
                "PROCESSING_LAUNCHER_ALWAYS_ON": {
                    "Fn::If": ["AlwaysOnEnv", "true", ref("AWS::NoValue")]
                },
            }
        activity = ACTIVITY_ROLES[domain]
        if name in (*activity["writers"], activity["repair"], LAUNCHER):
            for kind in ("Touched", "Quiet"):
                env[f"{prefix}_ACTIVITY_{kind.upper()}_PARAMETER"] = {
                    "Fn::If": ["AlwaysOnEnv", ref(f"{domain}Activity{kind}"), ref("AWS::NoValue")]
                }
        if name in WORK_PUBLISHERS:
            # A work send wakes the launcher at once (#237); the minute schedule stays the net.
            env["PROCESSING_LAUNCHER_FUNCTION"] = {
                "Fn::If": ["Unattended", ref(f"{LAUNCHER}Alias"), ref("AWS::NoValue")]
            }
        if domain == "Processing" and name not in (LAUNCHER, SHORT_ENCODER):
            # Every publisher routes work by lane. The values resolve to nothing, so the
            # variables are absent, unless LambdaShortEncodes=true.
            none = ref("AWS::NoValue")
            env |= {
                "PROCESSING_SHORT_LANE": {"Fn::If": ["ShortEncodes", "true", none]},
                "PROCESSING_WORK_SHORT_QUEUE_URL": {
                    "Fn::If": ["ShortEncodes", ref(f"{SHORT_QUEUE}Queue"), none]
                },
            }
        if name == SHORT_ENCODER:
            env |= {
                "PROCESSING_SHORT_LANE": "true",
                "PROCESSING_WORK_SHORT_QUEUE_URL": ref(f"{SHORT_QUEUE}Queue"),
                # The durable attempt deadline; the handler also bounds it by what is left.
                "PROCESSING_ATTEMPT_TIMEOUT_SECONDS": str(short_lane.PIPELINE_DEADLINE_SECONDS),
            }
        if domain == "Media":
            env |= {
                "MEDIA_MINIO_SOURCE_BUCKET": ref("SourceBucket"),
                "MEDIA_PUBLIC_URL": sub("https://${Distribution.DomainName}"),
                "MEDIA_MINIO_PUBLIC_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
                "MEDIA_MINIO_PUBLIC_USE_SSL": "true",
                "MEDIA_API_PUBLIC_PREFIX": "/api/media",
            }
        if name in ("MediaApi", "MediaAuthorizer"):
            env["MEDIA_JWT_SECRET_PARAMETER_ARN"] = ref("JwtSecretParameterArn")
        image = "Worker" if name == SHORT_ENCODER else domain
        image_config = {"Command": [ref(f"{name}Handler")]}
        if name == SHORT_ENCODER:
            # The worker image's own ENTRYPOINT is the finite Fargate encoder; Lambda needs the
            # runtime client instead. One artifact therefore serves both executors.
            image_config["EntryPoint"] = ["python", "-m", "awslambdaric"]
        add(
            name,
            "Lambda::Function",
            {
                "PackageType": "Image",
                "Code": {"ImageUri": ref(f"{image}ImageUri")},
                "ImageConfig": image_config,
                "Role": attr(f"{name}Role"),
                # The launcher fires every minute; a timeout below that means a tick can never
                # overlap itself, so it adds at most one to the shared Lambda concurrency.
                "Timeout": {
                    "MediaAuthorizer": 10,
                    LAUNCHER: 30,
                    SHORT_ENCODER: short_lane.LAMBDA_TIMEOUT_SECONDS,
                }.get(name, 60),
                "MemorySize": (
                    short_lane.MEMORY_MB
                    if name == SHORT_ENCODER
                    else 2048
                    if name.endswith("Api")
                    else 512
                ),
                **(
                    {"EphemeralStorage": {"Size": short_lane.EPHEMERAL_STORAGE_MB}}
                    if name == SHORT_ENCODER
                    else {}
                ),
                "Architectures": ["x86_64"],
                "Environment": {"Variables": env},
                "VpcConfig": {
                    "SubnetIds": [ref("PrivateASubnet"), ref("PrivateBSubnet")],
                    "SecurityGroupIds": [ref("LambdaSecurityGroup")],
                    "Ipv6AllowedForDualStack": True,
                },
                "LoggingConfig": {"LogGroup": ref(f"{name}LogGroup")},
                "Tags": tags,
            },
            app=True,
        )
        # An alias moves only when its Version is replaced, and a Version is replaced only when
        # its own properties change. Naming the image and a digest of the function's definition
        # here makes an in-place stack update (#235) publish a new version, and repoint the
        # alias, exactly when the function's image or configuration changed. Retained, because
        # Lambda answers an unchanged publish with the existing version, which a replaced
        # resource must then not delete; the versions go with the function itself.
        add(
            f"{name}Version",
            "Lambda::Version",
            # The description is filled in once every resource it may name exists (below).
            {"FunctionName": ref(name), "Description": (domain, image)},
            app=True,
            retain=True,
        )
        add(
            f"{name}Alias",
            "Lambda::Alias",
            {
                "FunctionName": ref(name),
                "FunctionVersion": attr(f"{name}Version", "Version"),
                "Name": "live",
            },
            app=True,
        )
    for name, queue in (
        ("ProcessingCommands", "ProcessingCommands"),
        ("MediaResults", "MediaResults"),
    ):
        add(
            f"{name}Mapping",
            "Lambda::EventSourceMapping",
            {
                "EventSourceArn": queue_arn(queue),
                "FunctionName": ref(f"{name}Alias"),
                "BatchSize": 10,
                "MaximumBatchingWindowInSeconds": 1,
                "FunctionResponseTypes": ["ReportBatchItemFailures"],
                # Without reservations this is the consumer bound; 2 is the SQS minimum.
                "ScalingConfig": {"MaximumConcurrency": 2},
                "Enabled": {"Fn::If": ["AlwaysOpen", True, False]},
            },
            app=True,
        )
    add(
        f"{SHORT_ENCODER}Mapping",
        "Lambda::EventSourceMapping",
        {
            "EventSourceArn": queue_arn(SHORT_QUEUE),
            "FunctionName": ref(f"{SHORT_ENCODER}Alias"),
            # One encode per invocation: a second message would share the first one's deadline.
            "BatchSize": 1,
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
            # Nothing is reservable at an account limit of 10, so this is the executor bound.
            # 2 is the SQS minimum. Closed until a session opens, like every other mapping.
            "ScalingConfig": {"MaximumConcurrency": short_lane.ENCODER_MAX_CONCURRENCY},
            "Enabled": {"Fn::If": ["AlwaysOpen", True, False]},
        },
        app=True,
    )
    # Per-service observability (#200). No SNS topic or pager: the alarms are state the operator
    # reads on the dashboard and in the console, and they are deleted with the stack.
    # A queue's dead-letter queue belongs to the service that consumes the queue, because
    # that service's code is what failed to process the message.
    dead_letter_owner = {
        "ProcessingCommands": "Processing",
        "ProcessingWork": "Processing",
        "MediaResults": "Media",
        SHORT_QUEUE: "Processing",
    }
    for name, owner in dead_letter_owner.items():
        add(
            f"{name}DlqAlarm",
            "CloudWatch::Alarm",
            {
                "AlarmName": sub(f"${{EnvironmentId}}-{name}-dlq-not-empty"),
                "AlarmDescription": (
                    f"{owner}: a message exhausted its receives and sits in the {name} "
                    "dead-letter queue. Inspect it, then redrive or purge "
                    "(docs/execution/aws/v1/dlq-runbook.md)."
                ),
                "Namespace": "AWS/SQS",
                "MetricName": "ApproximateNumberOfMessagesVisible",
                "Dimensions": [{"Name": "QueueName", "Value": attr(f"{name}Dlq", "QueueName")}],
                "Statistic": "Maximum",
                "Period": 300,
                "EvaluationPeriods": 1,
                "Threshold": 0,
                "ComparisonOperator": "GreaterThanThreshold",
                # An idle queue publishes no datapoints, which is the healthy state.
                "TreatMissingData": "notBreaching",
                "Tags": [*tags, {"Key": "Service", "Value": owner.lower()}],
            },
            # The three standard queues exist from the foundation phase; the short lane's only
            # with LambdaShortEncodes.
            app=name == SHORT_QUEUE,
        )
    for name in handlers:
        owner = "Media" if name.startswith("Media") else "Processing"
        add(
            f"{name}ErrorsAlarm",
            "CloudWatch::Alarm",
            {
                "AlarmName": sub(f"${{EnvironmentId}}-{name}-errors"),
                "AlarmDescription": (
                    f"{owner}: the {name} function returned an error (unhandled exception, "
                    "timeout or out-of-memory). A message batch it was reading is retried "
                    "and, after five receives, lands in its dead-letter queue."
                ),
                "Namespace": "AWS/Lambda",
                "MetricName": "Errors",
                # The bare function name aggregates every version and alias.
                "Dimensions": [{"Name": "FunctionName", "Value": ref(name)}],
                "Statistic": "Sum",
                "Period": 300,
                "EvaluationPeriods": 1,
                "Threshold": 0,
                "ComparisonOperator": "GreaterThanThreshold",
                "TreatMissingData": "notBreaching",
                "Tags": [*tags, {"Key": "Service", "Value": owner.lower()}],
            },
            app=True,
        )
    # One dashboard, a section per service. The optional V2 functions (launcher, short encoder)
    # exist only under their own conditions, so the dashboard shows the V1 functions; their
    # alarms still exist whenever they do.
    sections = {
        "Media": {
            "title": "Media Management",
            "functions": [n for n in handlers if n.startswith("Media")],
            "queues": ["MediaResults"],
            "encoders": None,
        },
        "Processing": {
            "title": "Processing",
            "functions": [
                n for n in handlers if n.startswith("Processing") and n not in OPTIONAL_FUNCTIONS
            ],
            "queues": ["ProcessingCommands", "ProcessingWork"],
            "encoders": "ProcessingWork",
        },
    }

    def lambda_series(metric, functions):
        return [
            ["AWS/Lambda", metric, "FunctionName", f"${{{function}}}", {"label": function}]
            for function in functions
        ]

    def sqs_series(metric, queues, suffix="Queue"):
        return [
            [
                "AWS/SQS",
                metric,
                "QueueName",
                f"${{{queue}{suffix}.QueueName}}",
                {"label": f"{queue}{'' if suffix == 'Queue' else ' DLQ'}"},
            ]
            for queue in queues
        ]

    widgets, top = [], 0

    def panel(title, metrics, *, stat, x, width, y, period=300):
        widgets.append(
            {
                "type": "metric",
                "x": x,
                "y": y,
                "width": width,
                "height": 6,
                "properties": {
                    "title": title,
                    "region": "${AWS::Region}",
                    "view": "timeSeries",
                    "stat": stat,
                    "period": period,
                    "metrics": metrics,
                },
            }
        )

    for section in sections.values():
        widgets.append(
            {
                "type": "text",
                "x": 0,
                "y": top,
                "width": 24,
                "height": 1,
                "properties": {"markdown": f"# {section['title']}"},
            }
        )
        top += 1
        functions = section["functions"]
        for column, (title, metric, stat) in enumerate(
            (
                ("Invocations", "Invocations", "Sum"),
                ("Errors", "Errors", "Sum"),
                ("Duration p90 (ms)", "Duration", "p90"),
            )
        ):
            panel(
                f"{section['title']}: {title}",
                lambda_series(metric, functions),
                stat=stat,
                x=column * 8,
                width=8,
                y=top,
            )
        top += 6
        queues = section["queues"]
        panels = [
            ("Queue depth", sqs_series("ApproximateNumberOfMessagesVisible", queues), "Maximum"),
            (
                "Oldest message age (s)",
                sqs_series("ApproximateAgeOfOldestMessage", queues),
                "Maximum",
            ),
            (
                "Dead-letter depth (alarm above 0)",
                sqs_series("ApproximateNumberOfMessagesVisible", queues, "Dlq"),
                "Maximum",
            ),
        ]
        if section["encoders"]:
            # Container Insights is off (its per-task metrics cost more than the encoders), so
            # ECS publishes no running-task count for standalone tasks. Every running encoder
            # holds exactly one work message in flight, so that is the closest direct metric.
            panels.append(
                (
                    "Encodes in flight (running encoders)",
                    sqs_series("ApproximateNumberOfMessagesNotVisible", [section["encoders"]]),
                    "Maximum",
                )
            )
        width = 24 // len(panels)
        for column, (title, metrics, stat) in enumerate(panels):
            panel(
                f"{section['title']}: {title}",
                metrics,
                stat=stat,
                x=column * width,
                width=width,
                y=top,
            )
        top += 6
    add(
        "ServicesDashboard",
        "CloudWatch::Dashboard",
        {
            "DashboardName": sub("${EnvironmentId}-v1-services"),
            # Fn::Sub resolves the function and queue names, so the body stays one JSON text.
            "DashboardBody": sub(json.dumps({"widgets": widgets}, separators=(",", ":"))),
        },
        app=True,
    )
    add(
        "HttpApi",
        "ApiGatewayV2::Api",
        {"Name": sub("${EnvironmentId}-v1"), "ProtocolType": "HTTP"},
        app=True,
    )
    add(
        "HttpStage",
        "ApiGatewayV2::Stage",
        {
            "ApiId": ref("HttpApi"),
            "StageName": "$default",
            "AutoDeploy": True,
            # Closed by default (account limit 10 forbids Lambda reservations, so this and
            # the disabled mappings/rules are the gates); the session API opens it. An
            # always-on environment (#236) deploys with its sane limit instead.
            "DefaultRouteSettings": {
                "Fn::If": [
                    "AlwaysOpen",
                    {
                        "ThrottlingBurstLimit": ref("StageBurstLimit"),
                        "ThrottlingRateLimit": ref("StageRateLimit"),
                    },
                    {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0},
                ]
            },
        },
        app=True,
    )
    add(
        "GatewayAuthorizer",
        "ApiGatewayV2::Authorizer",
        {
            "ApiId": ref("HttpApi"),
            "Name": "MediaIdentity",
            "AuthorizerType": "REQUEST",
            "AuthorizerPayloadFormatVersion": "2.0",
            "EnableSimpleResponses": True,
            "AuthorizerResultTtlInSeconds": 0,
            "IdentitySource": ["$request.header.Cookie"],
            "AuthorizerUri": sub(
                "arn:${AWS::Partition}:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${MediaAuthorizerAlias}/invocations"
            ),
        },
        app=True,
    )
    add(
        "AuthorizerPermission",
        "Lambda::Permission",
        {
            "FunctionName": ref("MediaAuthorizerAlias"),
            "Action": "lambda:InvokeFunction",
            "Principal": "apigateway.amazonaws.com",
            "SourceArn": sub(
                "arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${HttpApi}/authorizers/${GatewayAuthorizer}"
            ),
            "SourceAccount": ref("AWS::AccountId"),
        },
        app=True,
    )
    for domain in ("Media", "Processing"):
        add(
            f"{domain}Integration",
            "ApiGatewayV2::Integration",
            {
                "ApiId": ref("HttpApi"),
                "IntegrationType": "AWS_PROXY",
                "IntegrationUri": ref(f"{domain}ApiAlias"),
                "PayloadFormatVersion": "2.0",
                "TimeoutInMillis": 29000,
            },
            app=True,
        )
        add(
            f"{domain}InvokePermission",
            "Lambda::Permission",
            {
                "FunctionName": ref(f"{domain}ApiAlias"),
                "Action": "lambda:InvokeFunction",
                "Principal": "apigateway.amazonaws.com",
                "SourceArn": sub(
                    f"arn:${{AWS::Partition}}:execute-api:${{AWS::Region}}:${{AWS::AccountId}}:${{HttpApi}}/*/*/api/{domain.lower()}/*"
                ),
                "SourceAccount": ref("AWS::AccountId"),
            },
            app=True,
        )
        add(
            f"{domain}RootInvokePermission",
            "Lambda::Permission",
            {
                "FunctionName": ref(f"{domain}ApiAlias"),
                "Action": "lambda:InvokeFunction",
                "Principal": "apigateway.amazonaws.com",
                "SourceArn": sub(
                    f"arn:${{AWS::Partition}}:execute-api:${{AWS::Region}}:${{AWS::AccountId}}:"
                    f"${{HttpApi}}/*/*/api/{domain.lower()}"
                ),
                "SourceAccount": ref("AWS::AccountId"),
            },
            app=True,
        )
        paths = [
            ("Owned", f"ANY /api/{domain.lower()}/{{proxy+}}", True),
            ("Root", f"ANY /api/{domain.lower()}", True),
            ("Health", f"GET /api/{domain.lower()}/health", False),
        ]
        if domain == "Media":
            paths += [
                (action.title(), f"POST /api/media/auth/{action}", False)
                for action in ("register", "login", "logout")
            ]
        for suffix, route, authenticated in paths:
            props = {
                "ApiId": ref("HttpApi"),
                "RouteKey": route,
                "Target": {"Fn::Join": ["/", ["integrations", ref(f"{domain}Integration")]]},
                "AuthorizationType": "CUSTOM" if authenticated else "NONE",
            }
            if authenticated:
                props["AuthorizerId"] = ref("GatewayAuthorizer")
            add(f"{domain}{suffix}Route", "ApiGatewayV2::Route", props, app=True)
    add(
        "FrontendOac",
        "CloudFront::OriginAccessControl",
        {
            "OriginAccessControlConfig": {
                "Name": sub("${EnvironmentId}-frontend"),
                "OriginAccessControlOriginType": "s3",
                "SigningBehavior": "always",
                "SigningProtocol": "sigv4",
            }
        },
    )
    default_cache = {
        "AllowedMethods": ["GET", "HEAD"],
        "CachedMethods": ["GET", "HEAD"],
        "Compress": True,
        "TargetOriginId": "frontend",
        "ViewerProtocolPolicy": "redirect-to-https",
        "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
    }
    add(
        "Distribution",
        "CloudFront::Distribution",
        {
            "DistributionConfig": {
                "Enabled": True,
                "IPV6Enabled": True,
                "HttpVersion": "http2and3",
                "DefaultRootObject": "index.html",
                "PriceClass": "PriceClass_200",
                "Origins": [
                    {
                        "Id": "frontend",
                        "DomainName": attr("FrontendBucket", "RegionalDomainName"),
                        "S3OriginConfig": {"OriginAccessIdentity": ""},
                        "OriginAccessControlId": ref("FrontendOac"),
                    },
                    {
                        "Fn::If": [
                            "Applications",
                            {
                                "Id": "gateway",
                                "DomainName": sub(
                                    "${HttpApi}.execute-api.${AWS::Region}.${AWS::URLSuffix}"
                                ),
                                "CustomOriginConfig": {
                                    "HTTPSPort": 443,
                                    "OriginProtocolPolicy": "https-only",
                                    "OriginSSLProtocols": ["TLSv1.2"],
                                },
                            },
                            ref("AWS::NoValue"),
                        ]
                    },
                ],
                "DefaultCacheBehavior": default_cache,
                "CacheBehaviors": [
                    {
                        "Fn::If": [
                            "Applications",
                            {
                                "PathPattern": "/api/*",
                                "TargetOriginId": "gateway",
                                "ViewerProtocolPolicy": "https-only",
                                "AllowedMethods": [
                                    "DELETE",
                                    "GET",
                                    "HEAD",
                                    "OPTIONS",
                                    "PATCH",
                                    "POST",
                                    "PUT",
                                ],
                                "CachedMethods": ["GET", "HEAD"],
                                "Compress": True,
                                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                                "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",
                            },
                            ref("AWS::NoValue"),
                        ]
                    }
                ],
            },
            "Tags": tags,
        },
    )
    for name in ("Source", "Output", "Frontend"):
        statements = [
            {
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [attr(f"{name}Bucket"), sub(f"${{{name}Bucket.Arn}}/*")],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ]
        if name == "Frontend":
            statements.append(
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "cloudfront.amazonaws.com"},
                    "Action": "s3:GetObject",
                    "Resource": sub("${FrontendBucket.Arn}/*"),
                    "Condition": {
                        "StringEquals": {
                            "AWS:SourceArn": sub(
                                "arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}"
                            )
                        }
                    },
                }
            )
        add(
            f"{name}BucketPolicy",
            "S3::BucketPolicy",
            {"Bucket": ref(f"{name}Bucket"), "PolicyDocument": policy(statements)},
        )
    for name in (
        "MediaRepair",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
        LAUNCHER,
    ):
        props = {
            "State": {"Fn::If": ["AlwaysOpen", "ENABLED", "DISABLED"]},
            "Targets": [
                {
                    "Arn": ref(f"{name}Alias"),
                    "Id": name,
                    "RetryPolicy": {"MaximumEventAgeInSeconds": 300, "MaximumRetryAttempts": 2},
                }
            ],
        }
        if name == LAUNCHER:
            # A late retry would only repeat work the next tick does anyway, and it could
            # run beside that tick. Closed, only a session open with --unattended enables
            # it; always on, it is the safety net behind the enqueue trigger. Session close
            # disables it first either way.
            props["Targets"][0]["RetryPolicy"] = {
                "MaximumEventAgeInSeconds": 60,
                "MaximumRetryAttempts": 0,
            }
        if name.endswith("Repair") or name == LAUNCHER:
            props["ScheduleExpression"] = "rate(1 minute)"
        elif name == "ProcessingEcsEvents":
            props["EventPattern"] = {
                "source": ["aws.ecs"],
                "detail-type": ["ECS Task State Change"],
                "detail": {"clusterArn": [attr("Cluster")], "lastStatus": ["STOPPED"]},
            }
        else:
            props["EventPattern"] = {
                "source": ["aws.s3"],
                "detail-type": ["Object Created"],
                "detail": {"bucket": {"name": [ref("OutputBucket")]}},
            }
        add(f"{name}Rule", "Events::Rule", props, app=True)
        add(
            f"{name}EventPermission",
            "Lambda::Permission",
            {
                "FunctionName": ref(f"{name}Alias"),
                "Principal": "events.amazonaws.com",
                "Action": "lambda:InvokeFunction",
                "SourceArn": attr(f"{name}Rule"),
                "SourceAccount": ref("AWS::AccountId"),
            },
            app=True,
        )
    add(
        "TaskLogGroup",
        "Logs::LogGroup",
        {"LogGroupName": sub("/dc2/${EnvironmentId}/tasks"), "RetentionInDays": 7},
    )
    for name in ("Worker", "MediaMigration", "ProcessingMigration"):
        domain = "Media" if name.startswith("Media") else "Processing"
        is_worker = name == "Worker"
        secret = f"{domain}{'Runtime' if is_worker else 'Migration'}DsnParameterArn"
        execution_statements = [
            allow(["ecr:GetAuthorizationToken"], ["*"]),
            allow(
                [
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                ],
                [attr(f"{'Worker' if is_worker else domain}Repository")],
            ),
            allow(["logs:CreateLogStream", "logs:PutLogEvents"], [attr("TaskLogGroup")]),
            allow(["ssm:GetParameters"], [ref(secret)]),
        ]
        add(
            f"{name}ExecutionRole",
            "IAM::Role",
            {
                "AssumeRolePolicyDocument": policy(
                    [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ]
                ),
                "Policies": [
                    {
                        "PolicyName": "image-logs-owned-secret",
                        "PolicyDocument": policy(execution_statements),
                    }
                ],
            },
            app=True,
        )
        env = common_env | {
            f"{domain.upper()}_MINIO_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
            f"{domain.upper()}_MINIO_USE_SSL": "true",
            f"{domain.upper()}_MINIO_REGION": ref("AWS::Region"),
            f"{domain.upper()}_STORAGE_CREDENTIAL_MODE": "ecs",
            f"{domain.upper()}_MINIO_OUTPUT_BUCKET": ref("OutputBucket"),
            "WORKER_LIFETIME_SECONDS": {"Fn::Sub": "${WorkerLifetimeSeconds}"},
            **db_ca_env(domain),
            "DC2_WORKER_CAP": "3",
            "PGSSLMODE": "verify-full",
            "PGSSLROOTCERT": RDS_CA_BUNDLE,
        }
        if is_worker:
            # The encoder long-polls the work queue itself (processing/worker/sqs.py exits with
            # "missing setting" without this URL). Narrowing the queue environments in #200 took
            # it out of the shared block along with the Lambda-only URLs; r1018a's first encoder
            # died on it. Only the work queue: the worker sends and reads nothing else.
            env["PROCESSING_WORK_QUEUE_URL"] = ref("ProcessingWorkQueue")
        command = (
            ["python", "-m", "processing.v1_worker", "--max-empty-polls", "2"]
            if is_worker
            else [
                "python",
                "-m",
                "alembic",
                "-c",
                f"{domain.lower()}/alembic.ini",
                "upgrade",
                "head",
            ]
        )
        add(
            f"{name}TaskDefinition",
            "ECS::TaskDefinition",
            {
                "Family": sub(f"${{EnvironmentId}}-{name.lower()}"),
                "Cpu": "2048" if is_worker else "256",
                "Memory": "4096" if is_worker else "512",
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
                "ExecutionRoleArn": attr(f"{name}ExecutionRole"),
                "TaskRoleArn": attr(f"{name}Role"),
                "ContainerDefinitions": [
                    {
                        "Name": "worker" if is_worker else "migration",
                        "Image": ref(f"{'Worker' if is_worker else domain}ImageUri"),
                        "Essential": True,
                        "EntryPoint": ["/usr/bin/env"],
                        "Command": command,
                        "Environment": [{"Name": k, "Value": v} for k, v in env.items()],
                        "Secrets": [
                            {"Name": f"{domain.upper()}_POSTGRES_DSN", "ValueFrom": ref(secret)},
                            *(
                                []
                                if is_worker
                                else [
                                    {
                                        "Name": f"{domain.upper()}_MIGRATION_DSN",
                                        "ValueFrom": ref(secret),
                                    }
                                ]
                            ),
                        ],
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": ref("TaskLogGroup"),
                                "awslogs-region": ref("AWS::Region"),
                                "awslogs-stream-prefix": name,
                            },
                        },
                    }
                ],
                "Tags": tags,
            },
            app=True,
        )
    # A one-off privileged DB bootstrap is separate from owner migrations.
    # Input is temporary SSM JSON; no master credential reaches app task roles.
    bootstrap_input = sub(
        "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:"
        "parameter/dc2/${EnvironmentId}/bootstrap-input"
    )
    add(
        "BootstrapRole",
        "IAM::Role",
        {
            "AssumeRolePolicyDocument": policy(
                [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ]
            ),
            "Tags": tags,
        },
        app=True,
    )
    add(
        "BootstrapExecutionRole",
        "IAM::Role",
        {
            "AssumeRolePolicyDocument": policy(
                [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ]
            ),
            "Policies": [
                {
                    "PolicyName": "temporary-bootstrap-input",
                    "PolicyDocument": policy(
                        [
                            allow(["ecr:GetAuthorizationToken"], ["*"]),
                            allow(
                                [
                                    "ecr:BatchCheckLayerAvailability",
                                    "ecr:GetDownloadUrlForLayer",
                                    "ecr:BatchGetImage",
                                ],
                                [attr("WorkerRepository")],
                            ),
                            allow(
                                ["logs:CreateLogStream", "logs:PutLogEvents"],
                                [attr("TaskLogGroup")],
                            ),
                            allow(["ssm:GetParameters"], [bootstrap_input]),
                        ]
                    ),
                }
            ],
        },
        app=True,
    )
    add(
        "BootstrapTaskDefinition",
        "ECS::TaskDefinition",
        {
            "Family": sub("${EnvironmentId}-bootstrap"),
            "Cpu": "256",
            "Memory": "512",
            "NetworkMode": "awsvpc",
            "RequiresCompatibilities": ["FARGATE"],
            "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
            "ExecutionRoleArn": attr("BootstrapExecutionRole"),
            "TaskRoleArn": attr("BootstrapRole"),
            "ContainerDefinitions": [
                {
                    "Name": "bootstrap",
                    "Image": ref("WorkerImageUri"),
                    "Essential": True,
                    "EntryPoint": ["python", "/opt/db-bootstrap.py"],
                    "Command": [],
                    "Secrets": [{"Name": "DC2_BOOTSTRAP_INPUT_JSON", "ValueFrom": bootstrap_input}],
                    "LogConfiguration": {
                        "LogDriver": "awslogs",
                        "Options": {
                            "awslogs-group": ref("TaskLogGroup"),
                            "awslogs-region": ref("AWS::Region"),
                            "awslogs-stream-prefix": "bootstrap",
                        },
                    },
                }
            ],
            "Tags": tags,
        },
        app=True,
    )
    # The shared layout keeps V1's output names. A separate layout names each domain's endpoint
    # and master secret, so nothing can read the wrong cluster through a name that fits both.
    database_outputs = {}
    for stem in stems:
        prefix = "" if database.topology == SHARED else stem.removesuffix("Database")
        database_outputs[f"{prefix}DatabaseEndpoint"] = attr(f"{stem}Cluster", "Endpoint.Address")
        database_outputs[f"{prefix}BootstrapSecretArn"] = attr(
            f"{stem}Cluster", "MasterUserSecret.SecretArn"
        )
    if database.topology == SEPARATE:
        database_outputs["DatabaseTopology"] = SEPARATE
    outputs = {
        "VpcId": ref("Vpc"),
        "PrivateSubnetIds": {"Fn::Join": [",", [ref("PrivateASubnet"), ref("PrivateBSubnet")]]},
        "PublicTaskSubnetIds": {"Fn::Join": [",", [ref("PublicASubnet"), ref("PublicBSubnet")]]},
        "WorkerSecurityGroupId": ref("WorkerSecurityGroup"),
        "MigrationSecurityGroupId": ref("MigrationSecurityGroup"),
        **database_outputs,
        "FrontendUrl": sub("https://${Distribution.DomainName}"),
        "DistributionId": ref("Distribution"),
        "ClusterArn": attr("Cluster"),
    }
    for name in ("Source", "Output", "Frontend"):
        outputs[f"{name}BucketName"] = ref(f"{name}Bucket")
    for name in ("Media", "Processing", "Worker"):
        outputs[f"{name}RepositoryUri"] = attr(f"{name}Repository", "RepositoryUri")
    for name in ("ProcessingCommands", "ProcessingWork", "MediaResults"):
        outputs[f"{name}QueueUrl"] = ref(f"{name}Queue")
        outputs[f"{name}QueueArn"] = queue_arn(name)
        outputs[f"{name}DlqUrl"] = ref(f"{name}Dlq")
        outputs[f"{name}DlqArn"] = attr(f"{name}Dlq")
    for name in handlers:
        version = resources[f"{name}Version"]["Properties"]
        domain, image = version["Description"]
        version["Description"] = version_description(
            domain, image, resources[name]["Properties"], parameters, resources
        )
    result = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "DC2 V1 managed two-domain stack. Operator applies explicitly.",
        "Parameters": parameters,
        "Conditions": {
            "Applications": {"Fn::Equals": [ref("DeployApplications"), "true"]},
            "Unattended": {
                "Fn::And": [
                    {"Condition": "Applications"},
                    {"Fn::Equals": [ref("UnattendedLaunch"), "true"]},
                ]
            },
            "ShortEncodes": {
                "Fn::And": [
                    {"Condition": "Applications"},
                    {"Fn::Equals": [ref("LambdaShortEncodes"), "true"]},
                ]
            },
            "AlwaysOnEnv": {
                "Fn::And": [
                    {"Condition": "Applications"},
                    {"Fn::Equals": [ref("AlwaysOn"), "true"]},
                ]
            },
            "AlwaysOpen": {
                "Fn::And": [
                    {"Condition": "AlwaysOnEnv"},
                    {"Fn::Equals": [ref("GatesOpen"), "true"]},
                ]
            },
            "AlwaysOnLauncher": {
                "Fn::And": [{"Condition": "AlwaysOnEnv"}, {"Condition": "Unattended"}]
            },
            "BudgetEmail": {
                "Fn::And": [
                    {"Condition": "AlwaysOnEnv"},
                    {"Fn::Not": [{"Fn::Equals": [ref("BudgetAlertEmail"), ""]}]},
                ]
            },
        },
        "Rules": {
            "ExplicitApplicationImages": {
                "RuleCondition": {"Fn::Equals": [ref("DeployApplications"), "true"]},
                "Assertions": [
                    {
                        "Assert": {"Fn::Not": [{"Fn::Equals": [ref(f"{d}ImageUri"), ""]}]},
                        "AssertDescription": f"{d} digest image must be explicit before activation",
                    }
                    for d in ("Media", "Processing", "Worker")
                ],
            },
        },
        "Resources": resources,
        "Outputs": {name: {"Value": value} for name, value in outputs.items()},
    }
    for name in handlers:
        gate = gate_of(name)
        result["Outputs"][f"{name}FunctionName"] = {"Condition": gate, "Value": ref(name)}
        result["Outputs"][f"{name}AliasArn"] = {
            "Condition": gate,
            "Value": ref(f"{name}Alias"),
        }
    for name in ("Worker", "MediaMigration", "ProcessingMigration", "Bootstrap"):
        result["Outputs"][f"{name}TaskDefinitionArn"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}TaskDefinition"),
        }
    for name in ("ProcessingCommands", "MediaResults"):
        result["Outputs"][f"{name}MappingId"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}Mapping"),
        }
    result["Outputs"][f"{SHORT_ENCODER}MappingId"] = {
        "Condition": "ShortEncodes",
        "Value": ref(f"{SHORT_ENCODER}Mapping"),
    }
    for kind, value in (
        ("QueueUrl", ref(f"{SHORT_QUEUE}Queue")),
        ("QueueArn", attr(f"{SHORT_QUEUE}Queue")),
        ("DlqUrl", ref(f"{SHORT_QUEUE}Dlq")),
        ("DlqArn", attr(f"{SHORT_QUEUE}Dlq")),
    ):
        result["Outputs"][f"{SHORT_QUEUE}{kind}"] = {"Condition": "ShortEncodes", "Value": value}
    for name in (
        "MediaRepair",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
        LAUNCHER,
    ):
        result["Outputs"][f"{name}RuleName"] = {
            "Condition": "Unattended" if name == LAUNCHER else "Applications",
            "Value": ref(f"{name}Rule"),
        }
    result["Outputs"]["ServicesDashboardName"] = {
        "Condition": "Applications",
        "Value": sub("${EnvironmentId}-v1-services"),
    }
    result["Outputs"]["HttpApiId"] = {"Condition": "Applications", "Value": ref("HttpApi")}
    result["Outputs"]["HttpApiUrl"] = {
        "Condition": "Applications",
        "Value": attr("HttpApi", "ApiEndpoint"),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-topology", choices=(SHARED, SEPARATE), default=SHARED)
    parser.add_argument("--database-auto-pause-seconds", type=int,
                        default=DEFAULT_AUTO_PAUSE_SECONDS)
    parser.add_argument("--database-max-capacity", type=float, default=DEFAULT_MAX_CAPACITY)
    args = parser.parse_args()
    try:
        database = DatabaseOptions(args.database_topology, args.database_auto_pause_seconds,
                                   args.database_max_capacity)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template(database), indent=2) + "\n")


if __name__ == "__main__":
    main()
