"""Shared offline fixtures for the V1 operator tests."""

from scripts.aws.v1 import operations
from scripts.aws.v1.operations import HANDLERS

MAPPING_IDS = {
    "ProcessingCommands": "11111111-1111-4111-8111-111111111111",
    "MediaResults": "22222222-2222-4222-8222-222222222222",
}


def outputs():
    values = {f"{h}FunctionName": f"fn-{h}" for h in HANDLERS}
    values |= {f"{h}MappingId": uuid for h, uuid in MAPPING_IDS.items()}
    values |= {f"{h}RuleName": f"rule-{h}" for h in operations.RULES}
    for queue in operations.QUEUES:
        values[f"{queue}DlqUrl"] = f"https://sqs.example.invalid/1/{queue}-dlq"
        values[f"{queue}DlqArn"] = f"arn:aws:sqs:ap-southeast-1:123456789012:{queue}-dlq"
    values |= {
        "HttpApiId": "abc123def",
        "HttpApiUrl": "https://abc123def.execute-api.ap-southeast-1.amazonaws.com",
        "ClusterArn": "arn:aws:ecs:ap-southeast-1:123456789012:cluster/c",
        "WorkerTaskDefinitionArn": "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/w:1",
        "PublicTaskSubnetIds": "subnet-a,subnet-b",
        "WorkerSecurityGroupId": "sg-worker",
        "MigrationSecurityGroupId": "sg-migration",
    }
    return values
