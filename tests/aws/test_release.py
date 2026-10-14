import json

import pytest
from test_transport_fixtures import NEW, OLD, artifact
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.release import promote, restore_pending, snapshot
from scripts.aws.transport import OperationError


def args(config, fake, journal, clock, owner="processing"):
    defs = {k: v.replace(":1", ":2") for k, v in config["task_definitions"].items()}
    return {
        "config": config,
        "transport": fake,
        "journal": journal,
        "owner": owner,
        "artifact": artifact(owner, NEW),
        "prior_artifact": artifact(owner, OLD),
        "definitions": defs,
        "compatibility": {
            "additive_reviewed": True,
            "prior_image_tested": True,
            "prior_config_id": artifact(owner, OLD)["config_id"],
            "expected_revision": "head-owned",
        },
        "schema_revision": lambda owner: "head-owned",
        "readiness": lambda *a: True,
        "public_smoke": lambda *a: {"status": "PASS"},
        "deadline": 2000,
        "clock": clock,
        "sleep": clock.sleep,
    }


@pytest.mark.parametrize("owner", ["processing", "media"])
def test_owner_only_zero_worker_release(config, fake, journal, clock, owner):
    options = args(config, fake, journal, clock, owner)
    before = snapshot(config, fake, owner, options["schema_revision"], deadline=1000)
    result = promote(**options)
    assert result["status"] == "promoted"
    assert snapshot(config, fake, owner, options["schema_revision"], deadline=1000) == before
    updated = {c[2]["service"] for c in fake.calls if c[1] == "update-service"}
    assert updated == (
        {"api-service", "recovery-service"} if owner == "processing" else {"media-service"}
    )
    migrations = [c[2]["taskDefinition"] for c in fake.calls if c[1] == "run-task"]
    assert migrations == [options["definitions"][owner + "_migration"]]
    with journal.locked() as state:
        assert state["pending_release"] is None
        assert state["launches"] == {}
        assert state["paused"] is True  # operator resumes intake/launch explicitly


def test_pending_intent_before_mutation_and_real_bad_candidate_restore(
    config, fake, journal, clock
):
    fake.bad = True
    original = fake.call

    def call(service, operation, payload, **kw):
        if operation in {"run-task", "update-service"}:
            assert json.loads(journal.path.read_text())["pending_release"] is not None
        return original(service, operation, payload, **kw)

    fake.call = call
    result = promote(**args(config, fake, journal, clock))
    assert result["status"] == "failed-restored"
    assert result["candidate_failure"]["tasks"]
    assert 42 in result["candidate_failure"]["tasks"][0]["exit_codes"]
    assert all(s["taskDefinition"].endswith(":1") for s in fake.services.values())
    assert "PRIVATE-DUMMY" not in journal.path.read_text()


def test_waiter_cannot_pass_old_digest(config, fake, journal, clock):
    options = args(config, fake, journal, clock)
    original = fake.call

    def call(service, op, payload, **kw):
        result = original(service, op, payload, **kw)
        if op == "update-service" and payload.get("taskDefinition", "").endswith(":2"):
            for task in fake.tasks.values():
                if task["taskDefinitionArn"].endswith(":2") and task["lastStatus"] == "RUNNING":
                    for c in task["containers"]:
                        c["imageDigest"] = OLD
        return result

    fake.call = call
    result = promote(**options)
    assert result["status"] == "failed-restored"
    assert clock.now == 700  # one absolute 600s candidate timeout


@pytest.mark.parametrize(
    "failure", ["missing-exit", "wrong-revision", "not-additive", "bad-definition"]
)
def test_migration_and_compatibility_gates(config, fake, journal, clock, failure):
    options = args(config, fake, journal, clock)
    if failure == "wrong-revision":
        options["schema_revision"] = lambda owner: "wrong"
    elif failure == "not-additive":
        options["compatibility"]["additive_reviewed"] = False
    elif failure == "bad-definition":
        fake.definitions["processing-api:2"]["containerDefinitions"][0]["image"] = "repo@" + OLD
    else:
        original = fake.call

        def call(service, op, payload, **kw):
            result = original(service, op, payload, **kw)
            if op == "run-task":
                for task in fake.tasks.values():
                    if "migration" in task["taskDefinitionArn"]:
                        task["containers"][0].pop("exitCode", None)
            return result

        fake.call = call
    if failure in {"not-additive", "bad-definition"}:
        with pytest.raises(OperationError):
            promote(**options)
        assert not any(c[1] in {"update-service", "run-task"} for c in fake.calls)
    else:
        assert promote(**options)["status"] == "failed-restored"
        assert not any(
            c[1] == "update-service" and c[2].get("taskDefinition", "").endswith(":2")
            for c in fake.calls
        )


def test_failed_restore_retains_intent_and_explicit_resume(config, fake, journal, clock):
    options = args(config, fake, journal, clock)
    options["public_smoke"] = lambda *a: {"status": "FAIL"}
    with pytest.raises(OperationError, match="intent retained"):
        promote(**options)
    with journal.locked() as state:
        assert state["pending_release"]
    result = restore_pending(
        config,
        fake,
        journal,
        schema_revision=lambda *a: "head-owned",
        readiness=lambda *a: True,
        public_smoke=lambda *a: {"status": "PASS"},
        deadline=1000,
        clock=clock,
        sleep=clock.sleep,
    )
    assert result["status"] == "failed-restored"
    assert not any("worker" in c[2].get("service", "") for c in fake.calls)


def test_lost_migration_launch_cannot_fake_restore_completion(config, fake, journal, clock):
    fake.lost = True
    with pytest.raises(OperationError, match="incomplete"):
        promote(**args(config, fake, journal, clock))
    with journal.locked() as state:
        assert state["pending_release"]["migration_request"]
        assert not state["pending_release"].get("migration_task")


def test_peer_identity_change_blocks_completion(config, fake, journal, clock):
    options = args(config, fake, journal, clock)

    def smoke(*a):
        fake.add_task("media:1", group="service:media-service")
        return {"status": "PASS"}

    options["public_smoke"] = smoke
    with pytest.raises(OperationError, match="incomplete"):
        promote(**options)
    with journal.locked() as state:
        assert state["pending_release"]["failure"]["kind"] == "OperationError"


def test_migration_restart_replay_uses_original_token(config, fake, journal, clock):
    fake.lost = True
    with pytest.raises(OperationError):
        promote(**args(config, fake, journal, clock))
    request = next(c[2] for c in fake.calls if c[1] == "run-task")
    restored = restore_pending(
        config,
        fake,
        journal,
        schema_revision=lambda *a: "head-owned",
        readiness=lambda *a: True,
        public_smoke=lambda *a: {"status": "PASS"},
        deadline=1000,
        clock=clock,
        sleep=clock.sleep,
    )
    assert restored["status"] == "failed-restored"
    assert [c[2] for c in fake.calls if c[1] == "run-task"] == [request, request]
    assert len(fake.tokens) == 1


def test_restore_deadline_not_reset_after_restart(config, fake, journal, clock):
    options = args(config, fake, journal, clock)
    options["public_smoke"] = lambda *a: {"status": "FAIL"}
    with pytest.raises(OperationError):
        promote(**options)
    clock.now = 401
    before = len(fake.calls)
    with pytest.raises(OperationError, match="deadline"):
        restore_pending(
            config,
            fake,
            journal,
            schema_revision=lambda *a: "head-owned",
            readiness=lambda *a: True,
            public_smoke=lambda *a: {"status": "PASS"},
            deadline=1000,
            clock=clock,
            sleep=clock.sleep,
        )
    assert len(fake.calls) == before


def test_media_preserves_future_worker_revision_and_active_tasks(config, fake, journal, clock):
    with journal.locked() as state:
        state["worker_definition"] = "worker:2"
        journal.save(state)
    active = fake.add_task("worker:2")
    result = promote(**args(config, fake, journal, clock, "media"))
    assert result["status"] == "promoted"
    assert fake.tasks[active]["lastStatus"] == "RUNNING"
    with journal.locked() as state:
        assert state["worker_definition"] == "worker:2"


def test_cross_owner_family_cannot_be_substituted(config, fake, journal, clock):
    options = args(config, fake, journal, clock)
    options["definitions"]["worker"] = "processing-api:2"
    with pytest.raises(OperationError, match="family"):
        promote(**options)
    assert not any(c[1] in {"run-task", "update-service"} for c in fake.calls)


def test_release_smoke_launches_candidate_and_prior_via_held_station_lock(
    config, fake, journal, clock
):
    import time

    config["session_end_epoch"] = time.time() + 2000
    options = args(config, fake, journal, clock)
    names = []

    def workflow(owner, deadline, operations):
        arns = operations["launch_workers"](count=1)
        names.extend(arns)
        # This represents genuine public candidate failure, not a successful waiter.
        return {"status": "FAIL" if len(names) == 1 else "PASS"}

    def observe(arn, name):
        record = next(
            r
            for r in __import__("json").loads(journal.path.read_text())["launches"].values()
            if r.get("task") == arn
        )
        stopped = record.get("warm_sent")
        if stopped:
            fake.tasks[arn]["lastStatus"] = "STOPPED"
        return {
            "fresh": True,
            "claims_stopped": bool(stopped),
            "claims": ["claim-" + arn],
            "outcomes": {"claim-" + arn: "succeeded"} if stopped else {},
        }

    options.update(smoke_workflow=workflow, observe=observe, warm_shutdown=lambda *a: True)
    result = promote(**options)
    assert result["status"] == "failed-restored"
    requests = [
        c[2] for c in fake.calls if c[1] == "run-task" and "worker" in c[2]["taskDefinition"]
    ]
    assert [r["taskDefinition"] for r in requests] == ["worker:2", "worker:1"]
    assert all(r["count"] == 1 for r in requests)
    assert requests[0]["clientToken"] != requests[1]["clientToken"]
    with journal.locked() as state:
        assert all(
            r["status"] == "stopped" and r["drain"] == "complete"
            for r in state["launches"].values()
        )


def test_media_smoke_cannot_launch_processing_workers(config, fake, journal, clock):
    options = args(config, fake, journal, clock, "media")

    def workflow(owner, deadline, operations):
        with pytest.raises(OperationError, match="peer workers"):
            operations["launch_workers"]()
        return {"status": "PASS"}

    options["smoke_workflow"] = workflow
    assert promote(**options)["status"] == "promoted"
    assert not any(c[1] == "run-task" and "worker" in c[2]["taskDefinition"] for c in fake.calls)
