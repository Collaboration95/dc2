"""Explicit environment sessions; failed close keeps state and intake paused."""

import copy
import time
from datetime import UTC, datetime

from scripts.aws.release import services
from scripts.aws.transport import OperationError, config_value, remaining
from scripts.aws.workers import drain, inventory, worker_inventory


def _instances(config, transport, deadline):
    result = transport.call(
        "ec2",
        "describe-instances",
        {
            "Filters": [
                {"Name": "tag:Environment", "Values": [config_value(config, "environment_id")]}
            ]
        },
        deadline=deadline,
    )
    return {i["InstanceId"]: i for r in result.get("Reservations", []) for i in r["Instances"]}


def _wait(check, deadline, clock, sleep):
    while True:
        remaining(deadline, clock)
        value = check()
        remaining(deadline, clock)
        if value:
            return value
        sleep(min(1, remaining(deadline, clock)))


def _zero_tasks(config, transport, known, deadline):
    current = services(config, transport, deadline=deadline)
    if any(
        s.get("desiredCount") != 0
        or s.get("runningCount", 0)
        or s.get("pendingCount", 0)
        or any(
            d.get("runningCount", 0) or d.get("pendingCount", 0) for d in s.get("deployments", [])
        )
        for s in current.values()
    ):
        return False
    tasks = inventory(config, transport, deadline=deadline, known=known)
    return all(t["lastStatus"] == "STOPPED" for t in tasks.values())


def close(
    config,
    transport,
    journal,
    *,
    pause_intake,
    observe,
    warm_shutdown,
    quiesce_writers,
    export_hook,
    deadline,
    clock=time.monotonic,
    sleep=time.sleep,
):
    journal.check_context(config)
    with journal.locked() as state:
        if state.get("session") == "closed" and state.get("close_receipt"):
            known = state.get("shutdown_tasks", [])
            instances = _instances(config, transport, deadline)
            current = instances.get(config_value(config, "state_instance_id"), {})
            addresses = transport.call("ec2", "describe-addresses", {}, deadline=deadline).get(
                "Addresses", []
            )
            generator_volumes = transport.call(
                "ec2",
                "describe-volumes",
                {
                    "Filters": [
                        {
                            "Name": "tag:Environment",
                            "Values": [config_value(config, "environment_id")],
                        },
                        {"Name": "tag:Role", "Values": ["generator"]},
                    ]
                },
                deadline=deadline,
            ).get("Volumes", [])
            if (
                generator_volumes
                or not _zero_tasks(config, transport, known, deadline)
                or any(r["status"] != "stopped" for r in state["launches"].values())
                or current.get("State", {}).get("Name") != "stopped"
                or current.get("PublicIpAddress")
                or current.get("PublicDnsName")
                or any(
                    i["State"]["Name"] != "terminated"
                    for iid, i in instances.items()
                    if iid != config_value(config, "state_instance_id")
                )
                or any(
                    a.get("InstanceId") in instances
                    or any(
                        t.get("Key") == "Environment"
                        and t.get("Value") == config_value(config, "environment_id")
                        for t in a.get("Tags", [])
                    )
                    for a in addresses
                )
            ):
                raise OperationError("Closed inventory inconsistent; explicit recovery required")
            return state["close_receipt"]
        state.pop("close_receipt", None)
        state.update(paused=True, session="closing")
        journal.save(state)
        if pause_intake(deadline) is not True:
            raise OperationError("Intake pause unacknowledged")
        if state.get("pending_release"):
            raise OperationError("Pending owner release must be restored before close")
        workers, occupied = worker_inventory(config, transport, state, deadline=deadline)
        if any(r["status"] != "stopped" and not r.get("task") for r in state["launches"].values()):
            raise OperationError("Unresolved launch blocks zero-compute claim")
        if occupied or any(
            r.get("drain") == "interrupted" or r.get("warm_sent") and r.get("drain") != "complete"
            for r in state["launches"].values()
        ):
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
        tasks = inventory(
            config,
            transport,
            deadline=deadline,
            known=[r["task"] for r in state["launches"].values() if r.get("task")],
        )
        known = set(tasks) | set(state.get("shutdown_tasks", []))
        state["shutdown_tasks"] = sorted(known)
        journal.save(state)
        # Before export, stop standalone migrations/candidates/generators, but hold
        # Media/recovery/SQL/Redis alive for worker terminal outcomes.
        standalone = {
            arn: t for arn, t in tasks.items() if not t.get("group", "").startswith("service:")
        }
        for arn, task in standalone.items():
            if task["lastStatus"] != "STOPPED":
                transport.call(
                    "ecs",
                    "stop-task",
                    {
                        "cluster": config_value(config, "cluster"),
                        "task": arn,
                        "reason": "session-close",
                    },
                    deadline=deadline,
                )
        _wait(
            lambda: all(
                t["lastStatus"] == "STOPPED"
                for arn, t in inventory(
                    config, transport, deadline=deadline, known=standalone
                ).items()
                if arn in standalone
            ),
            deadline,
            clock,
            sleep,
        )
        if quiesce_writers(deadline) is not True:
            raise OperationError("Owner writers not quiescent; state kept online")
        proof = {
            "environment_id": config_value(config, "environment_id"),
            "quiescent": True,
            "intake_paused": True,
            "launches_paused": True,
            "writers_stopped": True,
            "worker_tasks_stopped": True,
            "observed_at_utc": datetime.now(UTC).isoformat(),
        }
        # Hook owns private DB/roles manifest. Retain selected confirmation only.
        exported = export_hook(proof, deadline)
        if not isinstance(exported, dict) or exported.get("status") != "PASS":
            raise OperationError("Export failed; no state stop or backup claim")
        state["export"] = {"status": "PASS", "quiescent_at_utc": proof["observed_at_utc"]}
        journal.save(state)
        for name in config_value(config, "services").values():
            transport.call(
                "ecs",
                "update-service",
                {"cluster": config_value(config, "cluster"), "service": name, "desiredCount": 0},
                deadline=deadline,
            )
        _wait(lambda: _zero_tasks(config, transport, known, deadline), deadline, clock, sleep)
        instances = _instances(config, transport, deadline)
        state_id = config_value(config, "state_instance_id")
        if state_id not in instances:
            raise OperationError("State instance missing from environment inventory")
        generators = []
        volumes = set(state.get("generator_volumes", []))
        for iid, instance in instances.items():
            if iid == state_id or instance["State"]["Name"] == "terminated":
                continue
            tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
            if tags.get("Role") != "generator":
                raise OperationError("Unexpected EC2 instance blocks close")
            generators.append(iid)
            volumes.update(
                b["Ebs"]["VolumeId"] for b in instance.get("BlockDeviceMappings", []) if "Ebs" in b
            )
        orphan_volumes = transport.call(
            "ec2",
            "describe-volumes",
            {
                "Filters": [
                    {"Name": "tag:Environment", "Values": [config_value(config, "environment_id")]},
                    {"Name": "tag:Role", "Values": ["generator"]},
                ]
            },
            deadline=deadline,
        ).get("Volumes", [])
        volumes.update(v["VolumeId"] for v in orphan_volumes)
        state["generator_volumes"] = sorted(volumes)
        journal.save(state)
        if generators:
            transport.call(
                "ec2", "terminate-instances", {"InstanceIds": generators}, deadline=deadline
            )
            _wait(
                lambda: all(
                    _instances(config, transport, deadline).get(i, {}).get("State", {}).get("Name")
                    == "terminated"
                    for i in generators
                ),
                deadline,
                clock,
                sleep,
            )
        if volumes:

            def remove_volumes():
                found = transport.call(
                    "ec2",
                    "describe-volumes",
                    {"Filters": [{"Name": "volume-id", "Values": sorted(volumes)}]},
                    deadline=deadline,
                ).get("Volumes", [])
                for volume in found:
                    if volume["State"] == "available":
                        transport.call(
                            "ec2",
                            "delete-volume",
                            {"VolumeId": volume["VolumeId"]},
                            deadline=deadline,
                        )
                return not found

            _wait(remove_volumes, deadline, clock, sleep)
        addresses = transport.call("ec2", "describe-addresses", {}, deadline=deadline).get(
            "Addresses", []
        )
        if any(
            a.get("InstanceId") in {state_id, *generators}
            or any(
                t.get("Key") == "Environment"
                and t.get("Value") == config_value(config, "environment_id")
                for t in a.get("Tags", [])
            )
            for a in addresses
        ):
            raise OperationError("Retained Elastic IP blocks zero-IP receipt")
        transport.call("ec2", "stop-instances", {"InstanceIds": [state_id]}, deadline=deadline)
        _wait(
            lambda: (
                lambda i: (
                    i.get("State", {}).get("Name") == "stopped"
                    and not i.get("PublicIpAddress")
                    and not i.get("PublicDnsName")
                )
            )(_instances(config, transport, deadline)[state_id]),
            deadline,
            clock,
            sleep,
        )
        # Catch late orphans/deployments before declaring zero; journal stays paused.
        if not _zero_tasks(config, transport, known, deadline):
            raise OperationError("Late task blocks complete close")
        state.update(
            session="closed",
            close_receipt={
                "tasks_stopped": True,
                "state_stopped": True,
                "public_ip_released": True,
                "generator_removed": True,
            },
        )
        journal.save(state)
        return state["close_receipt"]


def open_session(
    config,
    transport,
    journal,
    *,
    state_readiness,
    peer_readiness,
    public_readiness,
    resume_intake,
    deadline,
    clock=time.monotonic,
    sleep=time.sleep,
):
    journal.check_context(config)
    with journal.locked() as state:
        if state.get("pending_release"):
            raise OperationError("Pending release blocks wake")
        state["paused"] = True
        journal.save(state)
        if config_value(config, "origin_transport_accepted", False) is not True:
            raise OperationError("Origin transport interpretation remains gated")
        state.pop("close_receipt", None)
        state.update(paused=True, session="opening")
        journal.save(state)
        _, occupied = worker_inventory(config, transport, state, deadline=deadline)
        if occupied:
            raise OperationError("Wake requires zero workers/reservations")
        iid = config_value(config, "state_instance_id")
        transport.call("ec2", "start-instances", {"InstanceIds": [iid]}, deadline=deadline)
        instance = _wait(
            lambda: (
                lambda i: (
                    i
                    if i.get("State", {}).get("Name") == "running" and i.get("PublicDnsName")
                    else None
                )
            )(_instances(config, transport, deadline).get(iid, {})),
            deadline,
            clock,
            sleep,
        )
        # Mount, TCP, both schemas and Redis are explicit prerequisites, not liveness.
        required = {"mount", "postgres_tcp", "media_schema", "processing_schema", "redis"}

        def ready_state():
            probes = state_readiness(deadline)
            return all(probes.get(k) is True for k in required)

        _wait(ready_state, deadline, clock, sleep)
        for name in config_value(config, "services").values():
            transport.call(
                "ecs",
                "update-service",
                {"cluster": config_value(config, "cluster"), "service": name, "desiredCount": 1},
                deadline=deadline,
            )
        _wait(lambda: peer_readiness(deadline) is True, deadline, clock, sleep)
        distribution = config_value(config, "cloudfront_distribution_id")
        current = transport.call(
            "cloudfront", "get-distribution-config", {"Id": distribution}, deadline=deadline
        )
        settings = copy.deepcopy(current["DistributionConfig"])
        origin_id = config_value(config, "cloudfront_origin_id", "state-origin")
        origins = [o for o in settings["Origins"]["Items"] if o["Id"] == origin_id]
        if len(origins) != 1 or not current.get("ETag"):
            raise OperationError("Known origin and config ETag required")
        if origins[0].get("CustomOriginConfig", {}).get("OriginProtocolPolicy") == "http-only":
            if config_value(config, "origin_transport_accepted", False) is not True:
                raise OperationError("Origin HTTP interpretation remains gated")
        origins[0]["DomainName"] = instance["PublicDnsName"]
        # This response includes a PRIVATE origin-header value. Pass directly through
        # injected transport, never through journal/evidence/CLI planner log output.
        transport.call(
            "cloudfront",
            "update-distribution",
            {"Id": distribution, "IfMatch": current["ETag"], "DistributionConfig": settings},
            deadline=deadline,
        )
        _wait(
            lambda: (
                transport.call(
                    "cloudfront", "get-distribution", {"Id": distribution}, deadline=deadline
                )
                .get("Distribution", {})
                .get("Status")
                == "Deployed"
            ),
            deadline,
            clock,
            sleep,
        )
        _wait(lambda: public_readiness(deadline) is True, deadline, clock, sleep)
        if resume_intake(deadline) is not True:
            raise OperationError("Intake resume unacknowledged")
        state.update(session="open", paused=False)
        journal.save(state)
        return {"status": "ready", "viewer_url": config_value(config, "public_url")}
