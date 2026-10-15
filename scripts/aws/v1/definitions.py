"""V1 CloudFormation builder. Pure data only: never imports an AWS SDK."""

import argparse
import json
from pathlib import Path


def ref(name):
    return {"Ref": name}


def sub(value):
    return {"Fn::Sub": value}


def attr(name, key="Arn"):
    return {"Fn::GetAtt": [name, key]}


def policy(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def allow(actions, resources):
    return {"Effect": "Allow", "Action": actions, "Resource": resources}


def template():
    """Closed-by-default two-phase stack; resources retained where data is durable."""
    parameters = {
        "EnvironmentId": {"Type": "String", "AllowedPattern": "[a-z][a-z0-9-]{2,23}"},
        "DeployApplications": {
            "Type": "String",
            "Default": "false",
            "AllowedValues": ["true", "false"],
        },
        "SessionOpen": {"Type": "String", "Default": "false", "AllowedValues": ["true", "false"]},
        "AuroraEngineVersion": {"Type": "String", "Default": "16.8"},
        "WorkerLifetimeSeconds": {
            "Type": "Number",
            "Default": 1800,
            "MinValue": 60,
            "MaxValue": 3600,
        },
        "SourceCorsOrigin": {"Type": "String", "AllowedPattern": "https://[a-zA-Z0-9.-]+"},
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
    }
    for name, handler in handlers.items():
        parameters[f"{name}Handler"] = {"Type": "String", "Default": handler}
    resources = {}

    def add(name, kind, properties, *, app=False, retain=False, depends=None):
        resource = {"Type": f"AWS::{kind}", "Properties": properties}
        if app:
            resource["Condition"] = "Applications"
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
                    allow(
                        ["s3:*"],
                        [
                            attr("SourceBucket"),
                            sub("${SourceBucket.Arn}/*"),
                            attr("OutputBucket"),
                            sub("${OutputBucket.Arn}/*"),
                        ],
                    )
                ]
            ),
        },
    )
    for name in ("Lambda", "Worker", "Migration", "Database"):
        egress = (
            [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIpv6": "::/0"}]
            if name == "Lambda"
            else [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}]
        )
        if name == "Database":
            egress = [{"IpProtocol": "tcp", "FromPort": 1, "ToPort": 1, "CidrIp": "127.0.0.1/32"}]
        else:
            egress.append(
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "DestinationSecurityGroupId": ref("DatabaseSecurityGroup"),
                }
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
    for name in ("Lambda", "Worker", "Migration"):
        add(
            f"DatabaseFrom{name}",
            "EC2::SecurityGroupIngress",
            {
                "GroupId": ref("DatabaseSecurityGroup"),
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
    add(
        "DatabaseCluster",
        "RDS::DBCluster",
        {
            "Engine": "aurora-postgresql",
            "EngineVersion": ref("AuroraEngineVersion"),
            "EngineMode": "provisioned",
            "MasterUsername": "dc2bootstrap",
            "ManageMasterUserPassword": True,
            "DBSubnetGroupName": ref("DbSubnets"),
            "DBClusterParameterGroupName": ref("DbParameters"),
            "VpcSecurityGroupIds": [ref("DatabaseSecurityGroup")],
            "StorageEncrypted": True,
            "BackupRetentionPeriod": 1,
            "DeletionProtection": True,
            "NetworkType": "DUAL",
            "ServerlessV2ScalingConfiguration": {
                "MinCapacity": 0,
                "MaxCapacity": 2,
                "SecondsUntilAutoPause": 300,
            },
            "Tags": tags,
        },
        retain=True,
    )
    add(
        "DatabaseInstance",
        "RDS::DBInstance",
        {
            "DBClusterIdentifier": ref("DatabaseCluster"),
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
                        "AllowedHeaders": ["Range"],
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

    source_read = allow(["s3:GetObject", "s3:GetObjectVersion"], [source_objects])
    output_write = allow(["s3:PutObject", "s3:AbortMultipartUpload"], [output_objects])
    media_storage = [
        allow(
            [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:DeleteObjectVersion",
            ],
            [source_objects],
        ),
        allow(
            ["s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject", "s3:DeleteObjectVersion"],
            [output_objects],
        ),
        allow(
            ["s3:ListBucket", "s3:ListBucketVersions"], [attr("SourceBucket"), attr("OutputBucket")]
        ),
    ]
    privileges = {
        "MediaApi": media_storage,
        "MediaAuthorizer": [],
        "ProcessingApi": [],
        "ProcessingCommands": [
            allow(receive, [queue_arn("ProcessingCommands")]),
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
        ],
        "MediaResults": [allow(receive, [queue_arn("MediaResults")])],
        "MediaRepair": media_storage
        + [allow(["sqs:SendMessage"], [queue_arn("ProcessingCommands")])],
        "ProcessingRepair": [
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")]),
            allow(["s3:DeleteObject", "s3:DeleteObjectVersion"], [output_objects]),
        ],
        "ProcessingEcsEvents": [
            allow(["sqs:SendMessage"], [queue_arn("ProcessingWork"), queue_arn("MediaResults")])
        ],
        "ProcessingS3Events": [
            allow(
                [
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:DeleteObject",
                    "s3:DeleteObjectVersion",
                ],
                [output_objects],
            )
        ],
        "Worker": [
            source_read,
            output_write,
            allow(receive, [queue_arn("ProcessingWork")]),
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
        "ProcessingWork": ["ProcessingCommands", "ProcessingRepair", "ProcessingEcsEvents"],
        "MediaResults": ["ProcessingCommands", "ProcessingRepair", "ProcessingEcsEvents"],
    }
    consumers = {
        "ProcessingCommands": ["ProcessingCommands"],
        "ProcessingWork": ["Worker"],
        "MediaResults": ["MediaResults"],
    }
    for name in producers:
        statements = [
            {
                "Effect": "Deny",
                "Principal": "*",
                "Action": "sqs:*",
                "Resource": queue_arn(name),
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ]
        for actions, roles in (
            (["sqs:SendMessage"], producers[name]),
            ([a for a in receive if a != "sqs:GetQueueAttributes"], consumers[name]),
        ):
            statements.append(
                {
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": actions,
                    "Resource": queue_arn(name),
                    "Condition": {
                        "ArnNotEquals": {
                            "aws:PrincipalArn": [attr(f"{role}Role") for role in roles]
                        }
                    },
                }
            )
        add(
            f"{name}QueuePolicy",
            "SQS::QueuePolicy",
            {"Queues": [ref(f"{name}Queue")], "PolicyDocument": policy(statements)},
            app=True,
        )
    common_env = {
        "AWS_USE_DUALSTACK_ENDPOINT": "true",
        "AWS_RETRY_MODE": "standard",
        "AWS_MAX_ATTEMPTS": "3",
        "PROCESSING_COMMANDS_QUEUE_URL": ref("ProcessingCommandsQueue"),
        "PROCESSING_WORK_QUEUE_URL": ref("ProcessingWorkQueue"),
        "MEDIA_RESULTS_QUEUE_URL": ref("MediaResultsQueue"),
        "DC2_RUNTIME": "v1",
        "DB_SSL_CA_FILE": "/opt/rds/global-bundle.pem",
    }
    for name in handlers:
        domain = "Media" if name.startswith("Media") else "Processing"
        prefix = domain.upper()
        env = common_env | {
            f"{prefix}_POSTGRES_DSN_PARAMETER_ARN": ref(f"{domain}RuntimeDsnParameterArn"),
            f"{prefix}_STORAGE_CREDENTIAL_MODE": "lambda",
            f"{prefix}_RUNTIME_MODE": "lambda",
            f"{prefix}_POSTGRES_SSL_CA": "/opt/rds/global-bundle.pem",
            f"{prefix}_MINIO_ENDPOINT": sub("s3.${AWS::Region}.amazonaws.com"),
            f"{prefix}_MINIO_USE_SSL": "true",
            f"{prefix}_MINIO_REGION": ref("AWS::Region"),
            f"{prefix}_MINIO_OUTPUT_BUCKET": ref("OutputBucket"),
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
        add(
            name,
            "Lambda::Function",
            {
                "PackageType": "Image",
                "Code": {"ImageUri": ref(f"{domain}ImageUri")},
                "ImageConfig": {"Command": [ref(f"{name}Handler")]},
                "Role": attr(f"{name}Role"),
                "Timeout": 10 if name == "MediaAuthorizer" else 60,
                "MemorySize": 2048 if name.endswith("Api") else 512,
                "Architectures": ["x86_64"],
                "ReservedConcurrentExecutions": {
                    "Fn::If": ["Open", 2 if name.endswith("Api") else 1, 0]
                },
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
        add(
            f"{name}Version",
            "Lambda::Version",
            {"FunctionName": ref(name), "Description": f"V1 initial {domain} artifact"},
            app=True,
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
                "Enabled": {"Fn::If": ["Open", True, False]},
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
            "DefaultRouteSettings": {"ThrottlingBurstLimit": 10, "ThrottlingRateLimit": 5},
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
    for name in ("MediaRepair", "ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events"):
        props = {
            "State": {"Fn::If": ["Open", "ENABLED", "DISABLED"]},
            "Targets": [
                {
                    "Arn": ref(f"{name}Alias"),
                    "Id": name,
                    "RetryPolicy": {"MaximumEventAgeInSeconds": 300, "MaximumRetryAttempts": 2},
                }
            ],
        }
        if name.endswith("Repair"):
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
            f"{domain.upper()}_POSTGRES_SSL_CA": "/opt/rds/global-bundle.pem",
            "DC2_WORKER_CAP": "3",
        }
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
                            {
                                "Name": (
                                    f"{domain.upper()}_POSTGRES_DSN"
                                    if is_worker
                                    else f"{domain.upper()}_MIGRATION_DSN"
                                ),
                                "ValueFrom": ref(secret),
                            }
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
    outputs = {
        "VpcId": ref("Vpc"),
        "PrivateSubnetIds": {"Fn::Join": [",", [ref("PrivateASubnet"), ref("PrivateBSubnet")]]},
        "PublicTaskSubnetIds": {"Fn::Join": [",", [ref("PublicASubnet"), ref("PublicBSubnet")]]},
        "WorkerSecurityGroupId": ref("WorkerSecurityGroup"),
        "MigrationSecurityGroupId": ref("MigrationSecurityGroup"),
        "DatabaseEndpoint": attr("DatabaseCluster", "Endpoint.Address"),
        "BootstrapSecretArn": attr("DatabaseCluster", "MasterUserSecret.SecretArn"),
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
    result = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "DC2 V1 managed two-domain stack. Operator applies explicitly.",
        "Parameters": parameters,
        "Conditions": {
            "Applications": {"Fn::Equals": [ref("DeployApplications"), "true"]},
            "Open": {
                "Fn::And": [
                    {"Fn::Equals": [ref("SessionOpen"), "true"]},
                    {"Fn::Equals": [ref("DeployApplications"), "true"]},
                ]
            },
        },
        "Resources": resources,
        "Outputs": {name: {"Value": value} for name, value in outputs.items()},
    }
    for name in handlers:
        result["Outputs"][f"{name}FunctionName"] = {"Condition": "Applications", "Value": ref(name)}
        result["Outputs"][f"{name}AliasArn"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}Alias"),
        }
    for name in ("Worker", "MediaMigration", "ProcessingMigration"):
        result["Outputs"][f"{name}TaskDefinitionArn"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}TaskDefinition"),
        }
    for name in ("ProcessingCommands", "MediaResults"):
        result["Outputs"][f"{name}MappingId"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}Mapping"),
        }
    for name in ("MediaRepair", "ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events"):
        result["Outputs"][f"{name}RuleName"] = {
            "Condition": "Applications",
            "Value": ref(f"{name}Rule"),
        }
    result["Outputs"]["HttpApiUrl"] = {
        "Condition": "Applications",
        "Value": attr("HttpApi", "ApiEndpoint"),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template(), indent=2) + "\n")


if __name__ == "__main__":
    main()
