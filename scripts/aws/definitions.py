"""Offline CloudFormation definitions and operational checks; no apply transport."""

import argparse
import ipaddress
import json
import os
import re
import time
from pathlib import Path

from scripts.aws.config import CloudConfig, validate_nonsecret

ROOT = Path(__file__).resolve().parents[2]
ARN_PATTERN = r"^arn:aws:ssm:[a-z]{2}-[a-z]+-[0-9]:[0-9]{12}:parameter/[A-Za-z0-9_/.-]+$"


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def attr(name, key):
    return {"Fn::GetAtt": [name, key]}


def allow(actions, resources, **extra):
    return {"Effect": "Allow", "Action": actions, "Resource": resources, **extra}


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def environment_template():
    """All counts zero and edge disabled. Installation/private injection are separate gates."""
    parameters = {
        "EnvironmentId": {"Type": "String", "AllowedPattern": "[a-z][a-z0-9-]{1,31}"},
        "AvailabilityZone": {"Type": "AWS::EC2::AvailabilityZone::Name"},
        "StateAmiId": {"Type": "AWS::EC2::Image::Id"},
        "CloudFrontPrefixListId": {"Type": "String", "AllowedPattern": "pl-[a-f0-9]+"},
        "VpcCidr": {"Type": "String", "Default": "10.42.0.0/16"},
        "SubnetCidr": {"Type": "String", "Default": "10.42.0.0/24"},
        "SourceBucketName": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"},
        "OutputBucketName": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"},
        "BackupBucketName": {"Type": "String", "AllowedPattern": "[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"},
        "MediaDigest": {"Type": "String", "AllowedPattern": "sha256:[a-f0-9]{64}"},
        "ProcessingDigest": {"Type": "String", "AllowedPattern": "sha256:[a-f0-9]{64}"},
        "OperatorPrincipalArn": {
            "Type": "String",
            "AllowedPattern": "arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+",
        },
        "WorkerLifetimeSeconds": {
            "Type": "Number",
            "Default": 1800,
            "MinValue": 60,
            "MaxValue": 3600,
        },
        "WorkerContainerMemory": {"Type": "Number", "Default": 1536, "AllowedValues": [1536, 4096]},
    }
    secret_names = (
        "MediaRuntimeDsnArn",
        "ProcessingRuntimeDsnArn",
        "MediaMigrationDsnArn",
        "ProcessingMigrationDsnArn",
        "JwtSecretArn",
        "PeerTokenArn",
        "SourceTokenArn",
        "RedisUrlArn",
        "OriginGateArn",
        "StateSecretsArn",
    )
    for name in secret_names:
        parameters[name] = {"Type": "String", "AllowedPattern": ARN_PATTERN}
    resources = {}

    def add(name, kind, props, **extra):
        resources[name] = {"Type": "AWS::" + kind, "Properties": props, **extra}

    add(
        "Vpc",
        "EC2::VPC",
        {"CidrBlock": ref("VpcCidr"), "EnableDnsSupport": True, "EnableDnsHostnames": True},
    )
    add(
        "Subnet",
        "EC2::Subnet",
        {
            "VpcId": ref("Vpc"),
            "AvailabilityZone": ref("AvailabilityZone"),
            "CidrBlock": ref("SubnetCidr"),
            "MapPublicIpOnLaunch": True,
        },
    )
    add("InternetGateway", "EC2::InternetGateway", {})
    add(
        "GatewayAttachment",
        "EC2::VPCGatewayAttachment",
        {"VpcId": ref("Vpc"), "InternetGatewayId": ref("InternetGateway")},
    )
    add("RouteTable", "EC2::RouteTable", {"VpcId": ref("Vpc")})
    add(
        "InternetRoute",
        "EC2::Route",
        {
            "RouteTableId": ref("RouteTable"),
            "DestinationCidrBlock": "0.0.0.0/0",
            "GatewayId": ref("InternetGateway"),
        },
        DependsOn="GatewayAttachment",
    )
    add(
        "RouteAssociation",
        "EC2::SubnetRouteTableAssociation",
        {"SubnetId": ref("Subnet"), "RouteTableId": ref("RouteTable")},
    )
    groups = [
        "State",
        "Origin",
        "Gateway",
        "Media",
        "Api",
        "Recovery",
        "Worker",
        "MediaMigration",
        "ProcessingMigration",
    ]
    for name in groups:
        # CloudFront prefix list consumes 55 rules. Origin gets a dedicated SG.
        add(
            name + "SG",
            "EC2::SecurityGroup",
            {
                "VpcId": ref("Vpc"),
                "GroupDescription": "dc2 " + name,
                "SecurityGroupEgress": [
                    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}
                ],
            },
        )

    def ingress(name, target, source, port):
        add(
            name,
            "EC2::SecurityGroupIngress",
            {
                "GroupId": ref(target + "SG"),
                "SourceSecurityGroupId": ref(source + "SG"),
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
            },
        )

    def egress(name, source, target, port):
        add(
            name,
            "EC2::SecurityGroupEgress",
            {
                "GroupId": ref(source + "SG"),
                "DestinationSecurityGroupId": ref(target + "SG"),
                "IpProtocol": "tcp",
                "FromPort": port,
                "ToPort": port,
            },
        )

    add(
        "OriginIngress",
        "EC2::SecurityGroupIngress",
        {
            "GroupId": ref("OriginSG"),
            "SourcePrefixListId": ref("CloudFrontPrefixListId"),
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
        },
    )
    for source in ["Media", "Api", "Recovery", "Worker", "MediaMigration", "ProcessingMigration"]:
        ingress(source + "DatabaseIn", "State", source, 5432)
        egress(source + "DatabaseOut", source, "State", 5432)
    for source in ["Api", "Recovery", "Worker"]:
        ingress(source + "RedisIn", "State", source, 6379)
        egress(source + "RedisOut", source, "State", 6379)
    for source in ["Gateway", "Worker"]:
        ingress(source + "MediaIn", "Media", source, 8000)
        egress(source + "MediaOut", source, "Media", 8000)
    ingress("MediaApiIn", "Api", "Media", 8000)
    egress("MediaApiOut", "Media", "Api", 8000)
    add(
        "Namespace",
        "ServiceDiscovery::PrivateDnsNamespace",
        {"Name": sub("${EnvironmentId}.internal"), "Vpc": ref("Vpc")},
    )
    for name in ["Media", "Processing"]:
        add(
            name + "Discovery",
            "ServiceDiscovery::Service",
            {
                "Name": name.lower(),
                "DnsConfig": {
                    "NamespaceId": ref("Namespace"),
                    "RoutingPolicy": "MULTIVALUE",
                    "DnsRecords": [{"Type": "A", "TTL": 5}],
                },
                "HealthCheckCustomConfig": {"FailureThreshold": 1},
            },
        )
    for name in ["Media", "Processing"]:
        add(
            name + "Repository",
            "ECR::Repository",
            {
                "RepositoryName": sub("${EnvironmentId}/" + name.lower()),
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
                "EncryptionConfiguration": {"EncryptionType": "AES256"},
            },
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
    bpa = dict.fromkeys(
        ["BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"], True
    )
    for name in ["Source", "Output", "Backup"]:
        props = {
            "BucketName": ref(name + "BucketName"),
            "PublicAccessBlockConfiguration": bpa,
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
            "LifecycleConfiguration": {
                "Rules": [
                    {
                        "Id": "abort-incomplete",
                        "Status": "Enabled",
                        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                    }
                ]
            },
        }
        if name == "Output":
            props["CorsConfiguration"] = {
                "CorsRules": [
                    {
                        "AllowedOrigins": [sub("https://${Distribution.DomainName}")],
                        "AllowedMethods": ["GET"],
                        "AllowedHeaders": ["Range"],
                        "ExposedHeaders": ["Content-Range", "Accept-Ranges", "ETag"],
                        "MaxAge": 300,
                    }
                ]
            }
        add(
            name + "Bucket",
            "S3::Bucket",
            props,
            DeletionPolicy="Retain",
            UpdateReplacePolicy="Retain",
        )
        add(
            name + "BucketPolicy",
            "S3::BucketPolicy",
            {
                "Bucket": ref(name + "Bucket"),
                "PolicyDocument": policy(
                    [
                        {
                            "Effect": "Deny",
                            "Principal": "*",
                            "Action": "s3:*",
                            "Resource": [
                                attr(name + "Bucket", "Arn"),
                                sub("${" + name + "Bucket.Arn}/*"),
                            ],
                            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                        }
                    ]
                ),
            },
        )
    add(
        "S3Gateway",
        "EC2::VPCEndpoint",
        {
            "VpcId": ref("Vpc"),
            "VpcEndpointType": "Gateway",
            "ServiceName": sub("com.amazonaws.${AWS::Region}.s3"),
            "RouteTableIds": [ref("RouteTable")],
            "PolicyDocument": policy(
                [
                    allow(
                        [
                            "s3:GetObject",
                            "s3:PutObject",
                            "s3:DeleteObject",
                            "s3:AbortMultipartUpload",
                            "s3:ListBucket",
                        ],
                        [attr(n + "Bucket", "Arn") for n in ["Source", "Output", "Backup"]]
                        + [sub("${" + n + "Bucket.Arn}/*") for n in ["Source", "Output", "Backup"]],
                        Principal="*",
                    ),
                    allow(
                        ["s3:GetObject"],
                        [
                            sub(
                                "arn:${AWS::Partition}:s3:::prod-${AWS::Region}-starport-layer-bucket/*"
                            )
                        ],
                        Principal="*",
                    ),
                ]
            ),
        },
    )

    def role(name, principal, statements):
        props = {
            "AssumeRolePolicyDocument": policy(
                [{"Effect": "Allow", "Principal": principal, "Action": ["sts:AssumeRole"]}]
            )
        }
        if statements:
            props["Policies"] = [{"PolicyName": name, "PolicyDocument": policy(statements)}]
        add(name, "IAM::Role", props)

    ecs_principal = {"Service": "ecs-tasks.amazonaws.com"}
    source_objects = sub("${SourceBucket.Arn}/*")
    output_objects = sub("${OutputBucket.Arn}/jobs/*")
    role(
        "MediaTaskRole",
        ecs_principal,
        [
            allow(
                ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
                [source_objects],
            ),
            allow(["s3:GetObject"], [sub("${OutputBucket.Arn}/*")]),
        ],
    )
    role(
        "WorkerTaskRole",
        ecs_principal,
        [allow(["s3:PutObject", "s3:AbortMultipartUpload"], [output_objects])],
    )
    role(
        "RecoveryTaskRole",
        ecs_principal,
        [
            allow(
                ["s3:ListBucket"],
                [attr("OutputBucket", "Arn")],
                Condition={"StringLike": {"s3:prefix": ["jobs/*"]}},
            ),
            allow(["s3:DeleteObject"], [output_objects]),
        ],
    )
    for name in ["Api", "MediaMigration", "ProcessingMigration"]:
        role(name + "TaskRole", ecs_principal, [])
    role(
        "StateRole",
        {"Service": "ec2.amazonaws.com"},
        [
            allow(["ssm:GetParameters"], [ref("StateSecretsArn"), ref("OriginGateArn")]),
            allow(
                [
                    "ssm:UpdateInstanceInformation",
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                ["*"],
            ),
        ],
    )
    add("StateProfile", "IAM::InstanceProfile", {"Roles": [ref("StateRole")]})
    add(
        "DataVolume",
        "EC2::Volume",
        {
            "AvailabilityZone": ref("AvailabilityZone"),
            "Encrypted": True,
            "Size": 8,
            "VolumeType": "gp3",
            "Tags": [{"Key": "dc2-state", "Value": ref("EnvironmentId")}],
        },
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )
    add(
        "StateInstance",
        "EC2::Instance",
        {
            "ImageId": ref("StateAmiId"),
            "InstanceType": "t3a.small",
            "Tags": [
                {"Key": "Environment", "Value": ref("EnvironmentId")},
                {"Key": "Role", "Value": "state"},
            ],
            "CreditSpecification": {"CPUCredits": "standard"},
            "IamInstanceProfile": ref("StateProfile"),
            "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"},
            "NetworkInterfaces": [
                {
                    "DeviceIndex": "0",
                    "SubnetId": ref("Subnet"),
                    "AssociatePublicIpAddress": True,
                    "GroupSet": [ref(n + "SG") for n in ["State", "Origin", "Gateway"]],
                }
            ],
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/xvda",
                    "Ebs": {
                        "VolumeSize": 16,
                        "VolumeType": "gp3",
                        "Encrypted": True,
                        "DeleteOnTermination": True,
                    },
                }
            ],
            "UserData": {
                "Fn::Base64": "#!/bin/sh\n# No implicit disk format or secret fetch.\n"
                "# Install reviewed state assets through the authorized operator workflow.\n"
                "install -d -m 0700 /etc/dc2-aws\n"
            },
        },
        DependsOn="GatewayAttachment",
    )
    add(
        "DataAttachment",
        "EC2::VolumeAttachment",
        {"InstanceId": ref("StateInstance"), "VolumeId": ref("DataVolume"), "Device": "/dev/sdf"},
    )
    # Managed caching-disabled policy; explicit origin policy forwards all viewer material.
    add(
        "ApiOriginPolicy",
        "CloudFront::OriginRequestPolicy",
        {
            "OriginRequestPolicyConfig": {
                "Name": sub("${EnvironmentId}-viewer"),
                "CookiesConfig": {"CookieBehavior": "all"},
                "QueryStringsConfig": {"QueryStringBehavior": "all"},
                "HeadersConfig": {"HeaderBehavior": "allViewer"},
            }
        },
    )
    add(
        "NoCache",
        "CloudFront::CachePolicy",
        {
            "CachePolicyConfig": {
                "Name": sub("${EnvironmentId}-no-cache"),
                "MinTTL": 0,
                "DefaultTTL": 0,
                "MaxTTL": 0,
                "ParametersInCacheKeyAndForwardedToOrigin": {
                    "EnableAcceptEncodingGzip": False,
                    "CookiesConfig": {"CookieBehavior": "none"},
                    "HeadersConfig": {"HeaderBehavior": "none"},
                    "QueryStringsConfig": {"QueryStringBehavior": "none"},
                },
            }
        },
    )
    behavior = {
        "TargetOriginId": "state",
        "ViewerProtocolPolicy": "https-only",
        "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
        "CachedMethods": ["GET", "HEAD"],
        "CachePolicyId": ref("NoCache"),
        "OriginRequestPolicyId": ref("ApiOriginPolicy"),
        "Compress": False,
    }
    add(
        "Distribution",
        "CloudFront::Distribution",
        {
            "DistributionConfig": {
                "Enabled": False,
                "Comment": "Restricted origin HTTP; private injection and owner approval required",
                "PriceClass": "PriceClass_All",
                "HttpVersion": "http2",
                "DefaultRootObject": "index.html",
                "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
                "Origins": [
                    {
                        "Id": "state",
                        "DomainName": attr("StateInstance", "PublicDnsName"),
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "OriginProtocolPolicy": "http-only",
                            "OriginReadTimeout": 60,
                            "OriginKeepaliveTimeout": 5,
                        },
                    }
                ],
                "DefaultCacheBehavior": behavior,
                "CacheBehaviors": [{**behavior, "PathPattern": p} for p in ["/api", "/api/*"]],
                "CustomErrorResponses": [
                    {"ErrorCode": code, "ErrorCachingMinTTL": 0}
                    for code in [400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504]
                ],
            }
        },
    )
    add("Cluster", "ECS::Cluster", {"ClusterName": ref("EnvironmentId")})
    for name in ["Media", "Api", "Recovery", "Worker", "MediaMigration", "ProcessingMigration"]:
        add(
            name + "Logs",
            "Logs::LogGroup",
            {"LogGroupName": sub("/dc2/${EnvironmentId}/" + name.lower()), "RetentionInDays": 14},
        )
    secret_sets = {
        "Media": {
            "MEDIA_POSTGRES_DSN": "MediaRuntimeDsnArn",
            "MEDIA_JWT_SECRET": "JwtSecretArn",
            "MEDIA_PROCESSING_SERVICE_TOKEN": "PeerTokenArn",
            "MEDIA_SOURCE_SERVICE_TOKEN": "SourceTokenArn",
        },
        "Api": {
            "PROCESSING_POSTGRES_DSN": "ProcessingRuntimeDsnArn",
            "PROCESSING_SERVICE_TOKEN": "PeerTokenArn",
            "PROCESSING_REDIS_URL": "RedisUrlArn",
        },
        "Recovery": {
            "PROCESSING_POSTGRES_DSN": "ProcessingRuntimeDsnArn",
            "PROCESSING_REDIS_URL": "RedisUrlArn",
        },
        "Worker": {
            "PROCESSING_POSTGRES_DSN": "ProcessingRuntimeDsnArn",
            "PROCESSING_REDIS_URL": "RedisUrlArn",
            "PROCESSING_SOURCE_SERVICE_TOKEN": "SourceTokenArn",
        },
        "MediaMigration": {"MEDIA_POSTGRES_DSN": "MediaMigrationDsnArn"},
        "ProcessingMigration": {"PROCESSING_POSTGRES_DSN": "ProcessingMigrationDsnArn"},
    }
    processing_env = {
        "PROCESSING_QUEUE_NAME": "processing",
        "PROCESSING_MEDIA_URL": sub("http://media.${EnvironmentId}.internal:8000"),
        "PROCESSING_STORAGE_CREDENTIAL_MODE": "ecs",
        "PROCESSING_MINIO_USE_SSL": "true",
        "PROCESSING_MINIO_REGION": ref("AWS::Region"),
        "PROCESSING_MINIO_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
        "PROCESSING_MINIO_OUTPUT_BUCKET": ref("OutputBucket"),
    }
    media_env = {
        "MEDIA_PROCESSING_URL": sub("http://processing.${EnvironmentId}.internal:8000"),
        "MEDIA_PUBLIC_URL": sub("https://${Distribution.DomainName}"),
        "MEDIA_STORAGE_CREDENTIAL_MODE": "ecs",
        "MEDIA_MINIO_USE_SSL": "true",
        "MEDIA_MINIO_PUBLIC_USE_SSL": "true",
        "MEDIA_MINIO_REGION": ref("AWS::Region"),
        "MEDIA_MINIO_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
        "MEDIA_MINIO_PUBLIC_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
        "MEDIA_MINIO_SOURCE_BUCKET": ref("SourceBucket"),
        "MEDIA_MINIO_OUTPUT_BUCKET": ref("OutputBucket"),
    }
    sizes = {
        "Media": (1024, 2048),
        "Api": (512, 1024),
        "Recovery": (256, 512),
        "Worker": (2048, 4096),
        "MediaMigration": (512, 1024),
        "ProcessingMigration": (512, 1024),
    }
    commands = {
        "Media": ["uvicorn", "media.main:app", "--host", "0.0.0.0", "--port", "8000"],
        "Api": ["uvicorn", "processing.main:app", "--host", "0.0.0.0", "--port", "8000"],
        "Recovery": ["python", "-m", "processing.recovery"],
        "Worker": [
            "python",
            "-m",
            "processing.worker",
            "--cloud-deadline",
            "0",
            "--name",
            "operator-override-required",
            "--burst",
        ],
        "MediaMigration": ["python", "-m", "alembic", "-c", "media/alembic.ini", "upgrade", "head"],
        "ProcessingMigration": [
            "python",
            "-m",
            "alembic",
            "-c",
            "processing/alembic.ini",
            "upgrade",
            "head",
        ],
    }
    for name, (cpu, memory) in sizes.items():
        owner = "Media" if name.startswith("Media") else "Processing"
        role(
            name + "ExecutionRole",
            ecs_principal,
            [
                allow(["ecr:GetAuthorizationToken"], ["*"]),
                allow(
                    [
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                    ],
                    [attr(owner + "Repository", "Arn")],
                ),
                allow(["logs:CreateLogStream", "logs:PutLogEvents"], [attr(name + "Logs", "Arn")]),
                allow(["ssm:GetParameters"], [ref(p) for p in secret_sets[name].values()]),
            ],
        )
        env = media_env.copy() if name == "Media" else processing_env.copy()
        if name.endswith("Migration"):
            env = {}
        elif name == "Api":
            env = {"PROCESSING_QUEUE_NAME": "processing"}
        elif name == "Recovery":
            env["PROCESSING_RECOVERY_INTERVAL_SECONDS"] = "15"
        elif name == "Worker":
            env["DC2_WORKER_LIFETIME_SECONDS"] = ref("WorkerLifetimeSeconds")
        container = {
            "Name": name.lower(),
            "Image": sub("${" + owner + "Repository.RepositoryUri}@${" + owner + "Digest}"),
            "Essential": True,
            "Cpu": cpu,
            "Memory": ref("WorkerContainerMemory") if name == "Worker" else memory,
            "Command": commands[name],
            "StopTimeout": 120,
            "Environment": [{"Name": k, "Value": v} for k, v in env.items()],
            "Secrets": [{"Name": k, "ValueFrom": ref(v)} for k, v in secret_sets[name].items()],
            "LogConfiguration": {
                "LogDriver": "awslogs",
                "Options": {
                    "awslogs-group": ref(name + "Logs"),
                    "awslogs-region": ref("AWS::Region"),
                    "awslogs-stream-prefix": "task",
                    "mode": "non-blocking",
                    "max-buffer-size": "1m",
                },
            },
        }
        containers = [container]
        if name in ["Media", "Api"]:
            container["PortMappings"] = [{"ContainerPort": 8000, "Protocol": "tcp"}]
            # Socket liveness is independent of peers/DB. Deployment needs separate probes.
            container["HealthCheck"] = {
                "Command": [
                    "CMD",
                    "python",
                    "-c",
                    "import socket; s=socket.create_connection(('127.0.0.1',8000),2); s.close()",
                ],
                "Interval": 15,
                "Timeout": 5,
                "Retries": 3,
                "StartPeriod": 30,
            }
        if name == "Media":
            container["Cpu"], container["Memory"] = 960, 1536
            reconciler = {
                **container,
                "Name": "media-reconciler",
                "Cpu": 64,
                "Memory": 512,
                "Command": ["python", "-m", "media.recovery"],
            }
            reconciler.pop("PortMappings")
            reconciler.pop("HealthCheck")
            containers.append(reconciler)
        add(
            name + "Task",
            "ECS::TaskDefinition",
            {
                "Family": sub("${EnvironmentId}-" + name.lower()),
                "RequiresCompatibilities": ["FARGATE"],
                "NetworkMode": "awsvpc",
                "Cpu": str(cpu),
                "Memory": str(memory),
                "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
                "TaskRoleArn": attr(name + "TaskRole", "Arn"),
                "ExecutionRoleArn": attr(name + "ExecutionRole", "Arn"),
                "ContainerDefinitions": containers,
            },
        )
    for name, discovery in [("Media", "Media"), ("Api", "Processing"), ("Recovery", None)]:
        props = {
            "Cluster": ref("Cluster"),
            "ServiceName": sub("${EnvironmentId}-" + name.lower()),
            "TaskDefinition": ref(name + "Task"),
            "DesiredCount": 0,
            "LaunchType": "FARGATE",
            "PlatformVersion": "1.4.0",
            "DeploymentConfiguration": {
                "MinimumHealthyPercent": 0,
                "MaximumPercent": 100,
                "DeploymentCircuitBreaker": {"Enable": True, "Rollback": True},
            },
            "NetworkConfiguration": {
                "AwsvpcConfiguration": {
                    "Subnets": [ref("Subnet")],
                    "SecurityGroups": [ref(name + "SG")],
                    "AssignPublicIp": "ENABLED",
                }
            },
        }
        if discovery:
            props["ServiceRegistries"] = [{"RegistryArn": attr(discovery + "Discovery", "Arn")}]
        add(name + "Service", "ECS::Service", props)
    task_role_names = [n + suffix for n in sizes for suffix in ["TaskRole", "ExecutionRole"]]
    role(
        "OperatorRole",
        {"AWS": ref("OperatorPrincipalArn")},
        [
            allow(
                ["s3:ListBucket"],
                [attr("BackupBucket", "Arn")],
                Condition={
                    "StringLike": {"s3:prefix": [sub("private/${EnvironmentId}/exports/*")]}
                },
            ),
            allow(
                ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
                [sub("${BackupBucket.Arn}/private/${EnvironmentId}/exports/*")],
            ),
            allow(
                ["ecs:RunTask"],
                [
                    sub(
                        "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:task-definition/${EnvironmentId}-"
                        + n.lower()
                        + ":*"
                    )
                    for n in sizes
                ],
                Condition={"ArnEquals": {"ecs:cluster": attr("Cluster", "Arn")}},
            ),
            allow(
                ["ecs:UpdateService"],
                [attr(n + "Service", "ServiceArn") for n in ["Media", "Api", "Recovery"]],
            ),
            allow(
                ["ecs:StopTask", "ecs:DescribeTasks"],
                [
                    sub(
                        "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:task/${Cluster}/*"
                    )
                ],
            ),
            allow(
                ["ecs:ListTasks", "ecs:DescribeServices"],
                ["*"],
                Condition={"ArnEquals": {"ecs:cluster": attr("Cluster", "Arn")}},
            ),
            allow(
                ["ecs:DescribeTaskDefinition"],
                [
                    sub(
                        "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:task-definition/${EnvironmentId}-"
                        + n.lower()
                        + ":*"
                    )
                    for n in sizes
                ],
            ),
            allow(
                ["iam:PassRole"],
                [attr(n, "Arn") for n in task_role_names],
                Condition={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            ),
            allow(["ssm:GetParameters"], [ref("OriginGateArn")]),
            allow(
                ["ec2:StartInstances", "ec2:StopInstances"],
                [
                    sub(
                        "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/${StateInstance}"
                    )
                ],
            ),
            allow(["ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeAddresses"], ["*"]),
            allow(
                ["ec2:TerminateInstances", "ec2:DeleteVolume"],
                [
                    sub("arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:instance/*"),
                    sub("arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:volume/*"),
                ],
                Condition={
                    "StringEquals": {
                        "ec2:ResourceTag/Environment": ref("EnvironmentId"),
                        "ec2:ResourceTag/Role": "generator",
                    }
                },
            ),
            allow(
                [
                    "cloudfront:GetDistribution",
                    "cloudfront:GetDistributionConfig",
                    "cloudfront:UpdateDistribution",
                ],
                [
                    sub(
                        "arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${Distribution}"
                    )
                ],
            ),
        ],
    )
    outputs = {
        "PublicUrl": {"Value": sub("https://${Distribution.DomainName}")},
        "DistributionId": {"Value": ref("Distribution")},
        "StateInstanceId": {"Value": ref("StateInstance")},
        "StatePrivateIp": {"Value": attr("StateInstance", "PrivateIp")},
        "DataVolumeId": {"Value": ref("DataVolume")},
        "Cluster": {"Value": ref("Cluster")},
        "SubnetId": {"Value": ref("Subnet")},
        "OperatorRoleArn": {"Value": attr("OperatorRole", "Arn")},
        "MediaFqdn": {"Value": sub("media.${EnvironmentId}.internal")},
        "ProcessingFqdn": {"Value": sub("processing.${EnvironmentId}.internal")},
    }
    for name in sizes:
        outputs[name + "TaskDefinition"] = {"Value": ref(name + "Task")}
        outputs[name + "SecurityGroup"] = {"Value": ref(name + "SG")}
    for name in ["Media", "Api", "Recovery"]:
        outputs[name + "ServiceName"] = {"Value": attr(name + "Service", "Name")}
    for name in ["Source", "Output", "Backup"]:
        outputs[name + "BucketName"] = {"Value": ref(name + "Bucket")}
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Preparation: single-AZ state, zero-count services; origin HTTP unresolved",
        "Metadata": {
            "PreparationGates": {
                "Apply": "NOT AUTHORIZED",
                "Origin": "owner disposition + private header injection",
                "Secrets": "SSM SecureString ARNs; AWS-managed SSM key; private edge injection",
                "Readiness": "liveness excludes schema, Redis and authenticated peer readiness",
            }
        },
        "Parameters": parameters,
        "Resources": resources,
        "Outputs": outputs,
    }


def generator_template():
    """A separate, explicitly invoked stack; never instantiated with the environment."""
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Gated short-lived c6a.large generator; terminate after timed check",
        "Parameters": {
            "EnvironmentId": {"Type": "String", "AllowedPattern": "[a-z][a-z0-9-]{1,31}"},
            "AmiId": {"Type": "AWS::EC2::Image::Id"},
            "SubnetId": {"Type": "AWS::EC2::Subnet::Id"},
            "VpcId": {"Type": "AWS::EC2::VPC::Id"},
            "SessionEndUtc": {"Type": "String"},
            "LifetimeMinutes": {"Type": "Number", "Default": 15, "MinValue": 5, "MaxValue": 60},
        },
        "Resources": {
            "GeneratorSG": {
                "Type": "AWS::EC2::SecurityGroup",
                "Properties": {
                    "GroupDescription": "No inbound generator",
                    "VpcId": ref("VpcId"),
                    "SecurityGroupEgress": [
                        {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}
                    ],
                },
            },
            "Generator": {
                "Type": "AWS::EC2::Instance",
                "Properties": {
                    "InstanceType": "c6a.large",
                    "PropagateTagsToVolumeOnCreation": True,
                    "ImageId": ref("AmiId"),
                    "InstanceInitiatedShutdownBehavior": "terminate",
                    "UserData": {
                        "Fn::Base64": sub(
                            "#!/bin/sh\n# Bound generator residency even if its operator is lost.\n"
                            "shutdown -h +${LifetimeMinutes}\n"
                        )
                    },
                    "MetadataOptions": {"HttpTokens": "required"},
                    "NetworkInterfaces": [
                        {
                            "DeviceIndex": "0",
                            "SubnetId": ref("SubnetId"),
                            "AssociatePublicIpAddress": True,
                            "GroupSet": [ref("GeneratorSG")],
                        }
                    ],
                    "BlockDeviceMappings": [
                        {
                            "DeviceName": "/dev/xvda",
                            "Ebs": {
                                "VolumeSize": 8,
                                "VolumeType": "gp3",
                                "Encrypted": True,
                                "DeleteOnTermination": True,
                            },
                        }
                    ],
                    "Tags": [
                        {"Key": "dc2-session-end", "Value": ref("SessionEndUtc")},
                        {"Key": "Environment", "Value": ref("EnvironmentId")},
                        {"Key": "Role", "Value": "generator"},
                    ],
                },
            },
        },
        "Outputs": {"GeneratorInstanceId": {"Value": ref("Generator")}},
    }


def readiness_plan(owner):
    if owner not in ("media", "processing"):
        raise ValueError("Select an owning service")
    return {
        "owner": owner,
        "liveness": "private socket only",
        "required_receipts": [
            "postgres_tcp",
            "owned_runtime_dml",
            "runtime_ddl_denied",
            "runtime_and_migrator_cross_db_denied",
            "owned_alembic_revision",
            "private_dns_current",
            "authenticated_peer_owner_contract",
        ]
        + (["redis_authenticated_ping"] if owner == "processing" else []),
        "migration": {
            "command": ["python", "-m", "alembic", "-c", owner + "/alembic.ini", "upgrade", "head"],
            "required": ["STOPPED", "exit_code_0", "owned_revision"],
            "peer_migration": False,
        },
        "status": "NOT_RUN",
    }


def private_edge_activation_plan(config):
    if isinstance(config, dict):
        config = CloudConfig.from_dict(config)
    return {
        "status": "BLOCKED",
        "execute": False,
        "origin_protocol": "http-only",
        "owner_disposition_recorded": config.origin_transport_accepted,
        "required": [
            "account/spend approval",
            "written requirement-owner origin HTTP disposition",
            "private SSM OriginGateArn resolution",
            "matching nginx private gate injection",
            "CloudFront custom X-DC2-Origin-Gate injection through private transport",
            "current state public DNS and deployed distribution receipt",
            "negative origin gate probe",
        ],
        "note": "No CloudFront SecureString dynamic references or gate values in plans",
    }


def prepare_private_state(
    config, transport, directory, public_inputs, *, deadline, clock=time.time
):
    """Resolve two scoped references through a fake transport; write private sentinel fixtures.

    No production transport is provided. Real state installation requires the later
    authorized private adapter; this returns only selected offline receipt fields.
    """
    if not isinstance(config, CloudConfig):
        config = CloudConfig.from_dict(config)
    if config.mode != "plan" or getattr(transport, "evidence_kind", None) != "offline":
        raise PermissionError("State injection accepts offline fake transport only")
    if not 0 < deadline - clock() <= 60:
        raise ValueError("State injection requires an absolute deadline within sixty seconds")
    references = [config.parameter_arns.get(n) for n in ["state_secrets", "origin_gate"]]
    if not all(references):
        raise ValueError("State injection needs both exact private SSM references")
    directory = Path(directory).absolute()
    if directory.resolve().is_relative_to(ROOT) or directory.is_symlink():
        raise ValueError("Private injection must be outside the repository and not a symlink")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Private injection directory requires mode 0700")
    validate_nonsecret(public_inputs)
    expected_public = {
        "DC2_POSTGRES_IMAGE",
        "DC2_REDIS_IMAGE",
        "DC2_NGINX_IMAGE",
        "DC2_STATE_PRIVATE_IP",
        "DC2_VPC_RESOLVER",
        "DC2_MEDIA_FQDN",
        "DC2_PUBLIC_HOST",
    }
    if set(public_inputs) != expected_public:
        raise ValueError("State injection requires the complete state-only public input map")
    for owner in ["POSTGRES", "REDIS", "NGINX"]:
        if not re.fullmatch(
            owner.lower() + r":[A-Za-z0-9.-]+@sha256:[a-f0-9]{64}",
            public_inputs["DC2_" + owner + "_IMAGE"],
        ):
            raise ValueError("Only immutable state image references are accepted")
    for name in ["DC2_STATE_PRIVATE_IP", "DC2_VPC_RESOLVER"]:
        if not ipaddress.ip_address(public_inputs[name]).is_private:
            raise ValueError("State listener and VPC resolver must be private addresses")
    if public_inputs[
        "DC2_MEDIA_FQDN"
    ] != f"media.{config.environment_id}.internal" or public_inputs[
        "DC2_PUBLIC_HOST"
    ] != config.public_url.removeprefix("https://").rstrip("/"):
        raise ValueError("Private peer and public host must match the selected environment")
    passwords = {
        "POSTGRES_PASSWORD",
        "MEDIA_MIGRATION_PASSWORD",
        "MEDIA_RUNTIME_PASSWORD",
        "PROCESSING_MIGRATION_PASSWORD",
        "PROCESSING_RUNTIME_PASSWORD",
        "REDIS_PASSWORD",
    }
    try:
        reply = transport.call(
            "ssm", "GetParameters", {"Names": references, "WithDecryption": True}, deadline=deadline
        )
        values = {p["ARN"]: p["Value"] for p in reply["Parameters"] if p["Type"] == "SecureString"}
        if set(values) != set(references) or reply.get("InvalidParameters") or clock() >= deadline:
            raise ValueError
        secrets = json.loads(values[references[0]])
        gate = values[references[1]]
        if set(secrets) != passwords or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", v) for v in secrets.values()
        ):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{48,128}", gate):
            raise ValueError
        env = "".join(f"{k}='{v}'\n" for k, v in sorted({**public_inputs, **secrets}.items()))
        origin = (
            'map $http_x_dc2_origin_gate $dc2_origin_allowed { default 0; "' + gate + '" 1; }\n'
        )
        for filename, content in [("state.env", env), ("origin-gate.conf", origin)]:
            fd = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
    except Exception:
        raise ValueError("Private state injection failed; no activation receipt") from None
    return {"evidence_kind": "offline", "files_private": True, "activation_status": "NOT_RUN"}


def main():
    parser = argparse.ArgumentParser(description="Render offline templates; no apply command")
    parser.add_argument(
        "kind", choices=["environment", "generator", "readiness-media", "readiness-processing"]
    )
    args = parser.parse_args()
    if args.kind.startswith("readiness-"):
        value = readiness_plan(args.kind.removeprefix("readiness-"))
    else:
        value = environment_template() if args.kind == "environment" else generator_template()
    print(json.dumps(value, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
