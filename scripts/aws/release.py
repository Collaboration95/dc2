"""Owner-only ECS promotion/restore with immutable image and peer verification.

Uses supplied task definitions and explicit SQL/readiness/public-smoke hooks.
No CLI default loads real credentials, and no schema downgrade is attempted.
"""

import time
import uuid

from scripts.aws.artifacts import validate
from scripts.aws.transport import OperationError, config_value, remaining
from scripts.aws.workers import _start_locked, describe_tasks, drain, inventory, worker_inventory

OWNER_SERVICES = {"processing": ("processing_api", "processing_recovery"), "media": ("media",)}


def services(config, transport, *, deadline):
    names = config_value(config, "services")
    result = transport.call(
        "ecs",
        "describe-services",
        {"cluster": config_value(config, "cluster"), "services": list(names.values())},
        deadline=deadline,
    )
    found = {s["serviceName"]: s for s in result.get("services", [])}
    if result.get("failures") or not set(names.values()) <= found.keys():
        raise OperationError("Incomplete service inventory")
    return {key: found[name] for key, name in names.items()}


def snapshot(config, transport, owner, schema_revision, *, deadline, worker_definition=None):
    peer = "media" if owner == "processing" else "processing"
    current = services(config, transport, deadline=deadline)
    tasks = inventory(config, transport, deadline=deadline)
    selected = []
    for key in OWNER_SERVICES[peer]:
        service = current[key]
        found_peer = False
        for arn, task in tasks.items():
            if (
                task.get("group") == "service:" + service["serviceName"]
                and task["lastStatus"] != "STOPPED"
            ):
                if task["lastStatus"] != "RUNNING":
                    raise OperationError("Peer task is not RUNNING")
                found_peer = True
                containers = [[c["name"], c.get("imageDigest")] for c in task.get("containers", [])]
                if (
                    not containers
                    or any(not digest for _, digest in containers)
                    or key == "media"
                    and len(containers) < 2
                ):
                    raise OperationError("Peer container digest missing")
                selected.append(
                    {
                        "task": arn,
                        "definition": task["taskDefinitionArn"],
                        "containers": sorted(containers),
                    }
                )
        if not found_peer:
            raise OperationError("Every peer service needs a complete task snapshot")
    selected_worker = worker_definition or config_value(config, "task_definitions")["worker"]
    if owner == "media":
        from scripts.aws.workers import family

        for arn, task in tasks.items():
            if (
                family(task["taskDefinitionArn"]) == family(selected_worker)
                and task["lastStatus"] != "STOPPED"
            ):
                selected.append(
                    {
                        "task": arn,
                        "definition": task["taskDefinitionArn"],
                        "containers": sorted(
                            [[c["name"], c.get("imageDigest")] for c in task.get("containers", [])]
                        ),
                    }
                )
    revision = schema_revision(peer)
    if not isinstance(revision, str) or not revision:
        raise OperationError("Peer schema revision must be observed")
    return {
        "tasks": sorted(selected, key=lambda t: t["task"]),
        "schema": revision,
        "worker_definition": selected_worker if owner == "media" else None,
    }


def validate_definitions(config, transport, owner, definitions, expected_digest, *, deadline):
    keys = (*OWNER_SERVICES[owner], "worker") if owner == "processing" else OWNER_SERVICES[owner]
    if owner + "_migration" in definitions:
        keys = (*keys, owner + "_migration")
    from scripts.aws.workers import family

    for key in keys:
        reference = definitions[key]
        if not reference.rsplit(":", 1)[-1].isdigit() or family(reference) != family(
            config_value(config, "task_definitions")[key]
        ):
            raise OperationError("Pinned owning family/revision required")
        result = transport.call(
            "ecs",
            "describe-task-definition",
            {"taskDefinition": definitions[key]},
            deadline=deadline,
        )["taskDefinition"]
        containers = result["containerDefinitions"]
        if not containers or any(
            c["image"].rsplit("@", 1)[-1] != expected_digest for c in containers
        ):
            raise OperationError("Candidate definition image differs from exact manifest")
        if key == "media" and (
            len(containers) < 2 or not all(c.get("essential") for c in containers)
        ):
            raise OperationError("Media API and reconciler must remain essential")
        if any(c.get("stopTimeout", 30) > 120 for c in containers):
            raise OperationError("Fargate stop timeout exceeds 120s")


def update_owner(config, transport, owner, definitions, *, deadline):
    for key in OWNER_SERVICES[owner]:
        transport.call(
            "ecs",
            "update-service",
            {
                "cluster": config_value(config, "cluster"),
                "service": config_value(config, "services")[key],
                "taskDefinition": definitions[key],
                "desiredCount": 1,
            },
            deadline=deadline,
        )


def wait_owner(
    config,
    transport,
    owner,
    definitions,
    expected_digest,
    *,
    readiness,
    deadline,
    clock=time.monotonic,
    sleep=time.sleep,
):
    while True:
        remaining(deadline, clock)
        current = services(config, transport, deadline=deadline)
        tasks = inventory(config, transport, deadline=deadline)
        complete = True
        failures = []
        for key in OWNER_SERVICES[owner]:
            service = current[key]
            owned = [
                t for t in tasks.values() if t.get("group") == "service:" + service["serviceName"]
            ]
            active = [t for t in owned if t["lastStatus"] != "STOPPED"]
            failures.extend(
                {
                    "task": t["taskArn"],
                    "exit_codes": [c.get("exitCode") for c in t.get("containers", [])],
                }
                for t in owned
                if t["lastStatus"] == "STOPPED"
                and t["taskDefinitionArn"] == definitions[key]
                and any(c.get("exitCode", 0) != 0 for c in t.get("containers", []))
            )
            complete &= (
                service.get("desiredCount") == 1
                and service.get("pendingCount") == 0
                and service.get("runningCount") == 1
                and len(active) == 1
                and all(
                    t["lastStatus"] == "RUNNING"
                    and t["taskDefinitionArn"] == definitions[key]
                    and t.get("containers")
                    and all(c.get("imageDigest") == expected_digest for c in t["containers"])
                    for t in active
                )
                and all(
                    d.get("taskDefinition") == definitions[key]
                    or d.get("runningCount", 0) + d.get("pendingCount", 0) == 0
                    for d in service.get("deployments", [])
                )
            )
        if failures:
            error = OperationError("Candidate task exited unsuccessfully")
            error.failures = failures
            raise error
        if complete and readiness(owner, deadline) is True:
            remaining(deadline, clock)
            return {"digest": expected_digest, "definitions": definitions}
        sleep(min(1, remaining(deadline, clock)))


def _migration(
    config,
    transport,
    journal,
    state,
    owner,
    definition,
    expected_revision,
    schema_revision,
    *,
    deadline,
    clock,
    sleep,
):
    pending = state["pending_release"]
    token = uuid.uuid4().hex
    payload = {
        "cluster": config_value(config, "cluster"),
        "taskDefinition": definition,
        "launchType": "FARGATE",
        "count": 1,
        "clientToken": token,
        "startedBy": "migration-" + token[:26],
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": config_value(config, "network")["subnets"],
                "securityGroups": config_value(config, "network")["security_groups"],
                "assignPublicIp": config_value(config, "network")["assign_public_ip"],
            }
        },
    }
    pending["migration_request"] = payload
    pending["migration_replay_before_epoch"] = time.time() + 3600
    journal.save(state)
    result = transport.call("ecs", "run-task", payload, deadline=deadline)
    if result.get("failures") or len(result.get("tasks", [])) != 1:
        raise OperationError("Migration launch unresolved")
    arn = result["tasks"][0]["taskArn"]
    pending["migration_task"] = arn
    journal.save(state)
    while True:
        task = describe_tasks(config, transport, [arn], deadline=deadline)[arn]
        if task["lastStatus"] == "STOPPED":
            if (
                not task.get("containers")
                or any(c.get("exitCode") != 0 for c in task["containers"])
                or schema_revision(owner) != expected_revision
            ):
                raise OperationError("Owning migration exit/revision gate failed")
            pending["migration_complete"] = True
            journal.save(state)
            return
        sleep(min(1, remaining(deadline, clock)))


def _release_smoke(
    config,
    transport,
    journal,
    state,
    *,
    owner,
    definition,
    public_smoke,
    smoke_workflow,
    observe,
    warm_shutdown,
    deadline,
    clock,
    sleep,
):
    def launch_workers(count=1):
        if owner != "processing":
            raise OperationError("Media release cannot launch peer workers")
        if observe is None or warm_shutdown is None:
            raise OperationError("Smoke workers require SQL/RQ warm-drain hooks")
        return _start_locked(
            config,
            transport,
            journal,
            state,
            count=count,
            deadline=deadline,
            definition=definition,
            end_epoch=time.time() + remaining(deadline, clock),
        )

    operations = {"launch_workers": launch_workers}
    result = (
        smoke_workflow(owner, deadline, operations)
        if smoke_workflow is not None
        else public_smoke(owner, deadline)
    )
    remaining(deadline, clock)
    if owner == "processing":
        _, occupied = worker_inventory(config, transport, state, deadline=deadline)
        if occupied:
            if observe is None or warm_shutdown is None:
                raise OperationError("Smoke left workers without drain hooks")
            drain(
                config,
                transport,
                journal,
                state,
                observe=observe,
                warm_shutdown=warm_shutdown,
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
        _, occupied = worker_inventory(config, transport, state, deadline=deadline)
        if occupied:
            raise OperationError("Smoke did not return to zero workers/reservations")
    return result


def _restore(
    config,
    transport,
    journal,
    state,
    *,
    schema_revision,
    readiness,
    public_smoke,
    deadline,
    clock,
    sleep,
    observe=None,
    warm_shutdown=None,
    smoke_workflow=None,
):
    pending = state["pending_release"]
    if "rollback_end" not in pending:
        pending["rollback_end"] = min(pending["restore_end"], clock() + 300)
        pending["rollback_end_epoch"] = time.time() + max(0, pending["rollback_end"] - clock())
        journal.save(state)
    deadline = min(
        deadline,
        pending["rollback_end"],
        clock() + max(0, pending["rollback_end_epoch"] - time.time()),
    )
    deadline = min(deadline, clock() + max(0, pending["restore_end_epoch"] - time.time()))
    remaining(deadline, clock)
    owner = pending["owner"]
    if pending.get("migration_request") and not pending.get("migration_task"):
        raise OperationError("Unresolved migration launch blocks restore completion")
    if pending.get("migration_task"):
        arn = pending["migration_task"]
        task = describe_tasks(config, transport, [arn], deadline=deadline)[arn]
        if task["lastStatus"] != "STOPPED":
            transport.call(
                "ecs",
                "stop-task",
                {
                    "cluster": config_value(config, "cluster"),
                    "task": arn,
                    "reason": "release-restore",
                },
                deadline=deadline,
            )
            while (
                describe_tasks(config, transport, [arn], deadline=deadline)[arn]["lastStatus"]
                != "STOPPED"
            ):
                sleep(min(1, remaining(deadline, clock)))
    validate(pending["prior_artifact"], owner=owner)
    update_owner(config, transport, owner, pending["prior_definitions"], deadline=deadline)
    receipt = wait_owner(
        config,
        transport,
        owner,
        pending["prior_definitions"],
        pending["prior_artifact"]["manifest_digest"],
        readiness=readiness,
        deadline=deadline,
        clock=clock,
        sleep=sleep,
    )
    if (
        _release_smoke(
            config,
            transport,
            journal,
            state,
            owner=owner,
            definition=pending["prior_definitions"].get("worker"),
            public_smoke=public_smoke,
            smoke_workflow=smoke_workflow,
            observe=observe,
            warm_shutdown=warm_shutdown,
            deadline=deadline,
            clock=clock,
            sleep=sleep,
        ).get("status")
        != "PASS"
    ):
        raise OperationError("Restored public smoke failed")
    remaining(deadline, clock)
    if (
        snapshot(
            config,
            transport,
            owner,
            schema_revision,
            deadline=deadline,
            worker_definition=state.get("worker_definition"),
        )
        != pending["peer"]
    ):
        raise OperationError("Peer changed during restore")
    if owner == "processing":
        _, occupied = worker_inventory(config, transport, state, deadline=deadline)
        if occupied:
            raise OperationError("Restore leaves nonzero workers/reservations")
        state["worker_definition"] = pending["prior_definitions"]["worker"]
    state["last_release"] = {
        "owner": owner,
        "status": "failed-restored",
        "candidate_failure": pending.get("failure", "interrupted"),
        "failed_candidate": {
            k: pending["candidate_artifact"][k]
            for k in ("source_sha", "config_id", "manifest_digest")
        },
        "restore": receipt,
    }
    state["pending_release"] = None
    journal.save(state)
    return state["last_release"]


def promote(
    config,
    transport,
    journal,
    *,
    owner,
    artifact,
    prior_artifact,
    definitions,
    compatibility,
    schema_revision,
    readiness,
    public_smoke,
    deadline,
    observe=None,
    warm_shutdown=None,
    smoke_workflow=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    if owner not in OWNER_SERVICES:
        raise OperationError("Select one business owner")
    validate(artifact, owner=owner)
    validate(prior_artifact, owner=owner)
    if (
        compatibility.get("additive_reviewed") is not True
        or compatibility.get("prior_config_id") != prior_artifact["config_id"]
        or compatibility.get("prior_image_tested") is not True
        or not compatibility.get("expected_revision")
    ):
        raise OperationError("Reviewed additive migration and prior-image compatibility required")
    journal.check_context(config)
    with journal.locked() as state:
        if state.get("pending_release") or state.get("session") != "open":
            raise OperationError("Pending release/session requires explicit restoration")
        state["paused"] = True
        journal.save(state)
        if any(
            r.get("drain") == "interrupted" or r.get("warm_sent") and r.get("drain") != "complete"
            for r in state["launches"].values()
        ):
            raise OperationError("Previous drain uncertainty blocks promotion")
        begin = clock()
        candidate_end = min(deadline, begin + 600)
        restore_end = min(deadline, begin + 900)
        if owner == "processing":
            _, occupied = worker_inventory(config, transport, state, deadline=candidate_end)
            if occupied:
                if observe is None or warm_shutdown is None:
                    raise OperationError("Active workers require warm drain hooks")
                drain(
                    config,
                    transport,
                    journal,
                    state,
                    observe=observe,
                    warm_shutdown=warm_shutdown,
                    deadline=candidate_end,
                    clock=clock,
                    sleep=sleep,
                )
                _, occupied = worker_inventory(config, transport, state, deadline=candidate_end)
                if occupied:
                    raise OperationError("Zero-worker baseline required")
        current = services(config, transport, deadline=candidate_end)
        prior = {key: current[key]["taskDefinition"] for key in OWNER_SERVICES[owner]}
        if owner == "processing":
            prior["worker"] = (
                state.get("worker_definition") or config_value(config, "task_definitions")["worker"]
            )
        validate_definitions(
            config,
            transport,
            owner,
            prior,
            prior_artifact["manifest_digest"],
            deadline=candidate_end,
        )
        validate_definitions(
            config,
            transport,
            owner,
            definitions,
            artifact["manifest_digest"],
            deadline=candidate_end,
        )
        wait_owner(
            config,
            transport,
            owner,
            prior,
            prior_artifact["manifest_digest"],
            readiness=readiness,
            deadline=candidate_end,
            clock=clock,
            sleep=sleep,
        )
        state["pending_release"] = {
            "owner": owner,
            "prior_definitions": prior,
            "prior_artifact": prior_artifact,
            "candidate_definitions": definitions,
            "candidate_artifact": artifact,
            "restore_end": restore_end,
            "restore_end_epoch": time.time() + max(0, restore_end - clock()),
            "peer": snapshot(
                config,
                transport,
                owner,
                schema_revision,
                deadline=candidate_end,
                worker_definition=state.get("worker_definition"),
            ),
        }
        journal.save(state)  # Before first migration/service mutation.
        try:
            _migration(
                config,
                transport,
                journal,
                state,
                owner,
                definitions[owner + "_migration"],
                compatibility["expected_revision"],
                schema_revision,
                deadline=candidate_end,
                clock=clock,
                sleep=sleep,
            )
            update_owner(config, transport, owner, definitions, deadline=candidate_end)
            receipt = wait_owner(
                config,
                transport,
                owner,
                definitions,
                artifact["manifest_digest"],
                readiness=readiness,
                deadline=candidate_end,
                clock=clock,
                sleep=sleep,
            )
            if (
                _release_smoke(
                    config,
                    transport,
                    journal,
                    state,
                    owner=owner,
                    definition=definitions.get("worker"),
                    public_smoke=public_smoke,
                    smoke_workflow=smoke_workflow,
                    observe=observe,
                    warm_shutdown=warm_shutdown,
                    deadline=candidate_end,
                    clock=clock,
                    sleep=sleep,
                ).get("status")
                != "PASS"
            ):
                raise OperationError("Candidate public smoke failed")
            remaining(candidate_end, clock)
            if (
                snapshot(
                    config,
                    transport,
                    owner,
                    schema_revision,
                    deadline=candidate_end,
                    worker_definition=state.get("worker_definition"),
                )
                != state["pending_release"]["peer"]
            ):
                raise OperationError("Peer changed during owner release")
            if owner == "processing":
                state["worker_definition"] = definitions["worker"]
            state["last_release"] = {"owner": owner, "status": "promoted", "candidate": receipt}
            state["pending_release"] = None
            journal.save(state)
            return state["last_release"]
        except Exception as exc:
            # Deliberately do not persist raw transport errors/logs.
            state["pending_release"]["failure"] = {
                "kind": type(exc).__name__,
                "tasks": getattr(exc, "failures", []),
            }
            journal.save(state)
            try:
                return _restore(
                    config,
                    transport,
                    journal,
                    state,
                    schema_revision=schema_revision,
                    readiness=readiness,
                    public_smoke=public_smoke,
                    observe=observe,
                    warm_shutdown=warm_shutdown,
                    smoke_workflow=smoke_workflow,
                    deadline=min(restore_end, clock() + 300),
                    clock=clock,
                    sleep=sleep,
                )
            except Exception:
                raise OperationError(
                    "Release failed; restoration incomplete, private intent retained"
                ) from None


def restore_pending(
    config,
    transport,
    journal,
    *,
    schema_revision,
    readiness,
    public_smoke,
    deadline,
    observe=None,
    warm_shutdown=None,
    smoke_workflow=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    journal.check_context(config)
    with journal.locked() as state:
        if not state.get("pending_release"):
            raise OperationError("No pending owner release")
        pending = state["pending_release"]
        deadline = min(
            deadline,
            pending.get("rollback_end", pending["restore_end"]),
            clock()
            + max(0, pending.get("rollback_end_epoch", pending["restore_end_epoch"]) - time.time()),
        )
        remaining(deadline, clock)
        if pending.get("migration_request") and not pending.get("migration_task"):
            if time.time() >= pending["migration_replay_before_epoch"]:
                raise OperationError(
                    "Migration token expired; explicit task reconciliation required"
                )
            result = transport.call(
                "ecs", "run-task", pending["migration_request"], deadline=deadline
            )
            if result.get("failures") or len(result.get("tasks", [])) != 1:
                raise OperationError("Migration replay unresolved")
            pending["migration_task"] = result["tasks"][0]["taskArn"]
            journal.save(state)
        return _restore(
            config,
            transport,
            journal,
            state,
            schema_revision=schema_revision,
            readiness=readiness,
            public_smoke=public_smoke,
            observe=observe,
            warm_shutdown=warm_shutdown,
            smoke_workflow=smoke_workflow,
            deadline=min(deadline, state["pending_release"]["restore_end"], clock() + 300),
            clock=clock,
            sleep=sleep,
        )


def preparation_plan(owner, proof):
    from scripts.aws.artifacts import validate_prepublication

    validate_prepublication(proof, owner=owner)
    return {
        "owner": owner,
        "config_id": proof["config_id"],
        "production_apply": "DISABLED",
        "production_publish": "DISABLED",
        "ordered_gates": [
            "approved project identity/window/origin decision",
            "publish SAME tested config; verify amd64 registry manifest/config relation",
            "reviewed prior image/additive schema compatibility",
            "designated private journal; Processing zero-worker baseline",
            owner + " owning migration STOPPED/exit0/revision",
            "exact candidate digest in every owning container",
            "bounded public smoke and unchanged peer snapshot",
            "failed candidate restore prior definitions; zero permanent workers",
        ],
        "selected_services": list(OWNER_SERVICES[owner]),
        "future_worker_definition_only": owner == "processing",
        "apply_entrypoint": "scripts.aws.release.promote(config, transport, journal, owner=...)",
    }


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Selected owner preparation; no publish/apply execution"
    )
    parser.add_argument("--owner", required=True, choices=tuple(OWNER_SERVICES))
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(preparation_plan(args.owner, json.loads(args.artifact.read_text())), indent=2))


if __name__ == "__main__":
    main()
