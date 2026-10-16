"""Owning ECS migrations: credentials stay in task secret references, not receipts."""

import time
import uuid

from scripts.aws.transport import OperationError, remaining


def migrate(
    config,
    transport,
    journal,
    state,
    *,
    owner,
    definition,
    revision,
    schema_revision,
    deadline,
    clock=time.monotonic,
    sleep=time.sleep,
):
    pending = state["pending_release"]
    if not pending.get("migration_request"):
        network = config["task_networks"][owner + "_migration"]
        token = uuid.uuid4().hex
        pending["migration_request"] = {
            "cluster": config["cluster"],
            "taskDefinition": definition,
            "launchType": "FARGATE",
            "count": 1,
            "clientToken": token,
            "startedBy": "v1-migration-" + token[:23],
            "networkConfiguration": {
                "awsvpcConfiguration": {
                    "subnets": network["subnets"],
                    "securityGroups": network["security_groups"],
                    "assignPublicIp": network["assign_public_ip"],
                }
            },
        }
        pending["migration_replay_before_epoch"] = time.time() + 3600
        journal.save(state)
    if pending["migration_request"]["taskDefinition"] != definition:
        raise OperationError("Cannot replace an unresolved migration intent")
    if not pending.get("migration_task"):
        if time.time() >= pending["migration_replay_before_epoch"]:
            raise OperationError(
                "Migration replay window expired; explicit reconciliation required"
            )
        result = transport.call("ecs", "run-task", pending["migration_request"], deadline=deadline)
        if result.get("failures") or len(result.get("tasks", [])) != 1:
            raise OperationError("Migration launch unresolved")
        pending["migration_task"] = result["tasks"][0]["taskArn"]
        journal.save(state)
    while True:
        result = transport.call(
            "ecs",
            "describe-tasks",
            {"cluster": config["cluster"], "tasks": [pending["migration_task"]]},
            deadline=deadline,
        )
        if result.get("failures") or len(result.get("tasks", [])) != 1:
            raise OperationError("Migration inventory unresolved")
        task = result["tasks"][0]
        if task["taskDefinitionArn"] != definition:
            raise OperationError("Migration task definition mismatch")
        if task["lastStatus"] == "STOPPED":
            if not task.get("containers") or any(
                c.get("exitCode") != 0 for c in task["containers"]
            ):
                raise OperationError("Migration task failed")
            if schema_revision(owner, deadline=deadline) != revision:
                raise OperationError("Owning schema revision mismatch")
            pending["migration_complete"] = True
            journal.save(state)
            return
        sleep(min(1, remaining(deadline, clock)))
