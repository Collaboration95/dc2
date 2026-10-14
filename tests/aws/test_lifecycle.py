import pytest
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.lifecycle import close, open_session
from scripts.aws.transport import OperationError
from scripts.aws.workers import start


def close_args(config, fake, journal, clock):
    return {
        "config": config,
        "transport": fake,
        "journal": journal,
        "pause_intake": lambda *a: True,
        "observe": lambda *a: {"fresh": True, "claims_stopped": True, "claims": [], "outcomes": {}},
        "warm_shutdown": lambda *a: True,
        "quiesce_writers": lambda *a: True,
        "export_hook": lambda *a: {"status": "PASS"},
        "deadline": 1000,
        "clock": clock,
        "sleep": clock.sleep,
    }


def open_args(config, fake, journal, clock):
    return {
        "config": config,
        "transport": fake,
        "journal": journal,
        "state_readiness": lambda *a: dict.fromkeys(
            ["mount", "postgres_tcp", "media_schema", "processing_schema", "redis"], True
        ),
        "peer_readiness": lambda *a: True,
        "public_readiness": lambda *a: True,
        "resume_intake": lambda *a: True,
        "deadline": 1000,
        "clock": clock,
        "sleep": clock.sleep,
    }


def test_orphan_migration_generator_and_repeat_close(config, fake, journal, clock):
    orphan = fake.add_task("processing-migration:2")
    fake.instances["gen"] = {
        "InstanceId": "gen",
        "State": {"Name": "running"},
        "Tags": [{"Key": "Role", "Value": "generator"}],
        "BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-gen"}}],
    }
    fake.volumes["vol-gen"] = {"VolumeId": "vol-gen", "State": "available"}
    options = close_args(config, fake, journal, clock)

    def export(proof, deadline):
        assert proof["quiescent"] is True
        assert fake.instances["state"]["State"]["Name"] == "running"
        assert fake.tasks[orphan]["lastStatus"] == "STOPPED"
        assert fake.services["recovery-service"]["desiredCount"] == 1
        return {"status": "PASS", "private_export": "not persisted"}

    options["export_hook"] = export
    assert close(**options)["tasks_stopped"] is True
    assert fake.instances["gen"]["State"]["Name"] == "terminated"
    assert fake.volumes == {}
    assert all(s["desiredCount"] == 0 for s in fake.services.values())
    options["export_hook"] = lambda *a: {"status": "PASS"}
    assert close(**options)["state_stopped"] is True
    with journal.locked() as state:
        assert state["paused"] is True
        assert "private_export" not in state["export"]


@pytest.mark.parametrize("kind", ["unresolved", "export-failed", "stopping", "eip", "unknown-host"])
def test_incomplete_close_never_claims_zero(config, fake, journal, clock, kind):
    options = close_args(config, fake, journal, clock)
    if kind == "unresolved":
        fake.lost = True
        with pytest.raises(OperationError, match="reservation retained"):
            start(config, fake, journal, count=1, deadline=1000, clock=clock)
    elif kind == "export-failed":
        options["export_hook"] = lambda *a: {"status": "FAIL"}
    elif kind == "stopping":
        fake.stopping = True
        fake.add_task("media-migration:2", status="STOPPING")
    elif kind == "eip":
        fake.addresses = [{"InstanceId": "state", "AllocationId": "eip"}]
    else:
        fake.instances["unknown"] = {"InstanceId": "unknown", "State": {"Name": "running"}}
    with pytest.raises(OperationError):
        close(**options)
    assert fake.instances["state"]["State"]["Name"] == "running"
    with journal.locked() as state:
        assert state["session"] == "closing"
        assert state["paused"] is True
        assert not state.get("close_receipt")


def test_stale_known_task_absence_blocks_close(config, fake, journal, clock):
    arn = start(config, fake, journal, count=1, deadline=1000, clock=clock)[0]
    del fake.tasks[arn]
    fake.stale_list = True
    with pytest.raises(OperationError, match="missing"):
        close(**close_args(config, fake, journal, clock))


def test_wake_current_dns_etag_preserves_private_header_and_viewer(config, fake, journal, clock):
    close(**close_args(config, fake, journal, clock))
    original_header = fake.distribution["Origins"]["Items"][0]["CustomHeaders"]
    assert open_session(**open_args(config, fake, journal, clock))["status"] == "ready"
    origin = fake.distribution["Origins"]["Items"][0]
    assert origin["DomainName"] == "new.example"
    assert origin["CustomHeaders"] == original_header
    assert fake.distribution["ViewerCertificate"]["CloudFrontDefaultCertificate"] is True
    assert "PRIVATE-DUMMY" not in journal.path.read_text()
    with journal.locked() as state:
        assert state["session"] == "open"
        assert state["paused"] is False
        assert not state["launches"]


@pytest.mark.parametrize(
    "probe", ["mount", "postgres_tcp", "media_schema", "processing_schema", "redis"]
)
def test_wake_readiness_is_more_than_liveness(config, fake, journal, clock, probe):
    options = open_args(config, fake, journal, clock)
    options["state_readiness"] = lambda *a: {
        k: k != probe
        for k in ["mount", "postgres_tcp", "media_schema", "processing_schema", "redis"]
    }
    with pytest.raises(OperationError, match="deadline"):
        open_session(**options)
    assert not any(c[1] == "update-service" for c in fake.calls)
    with journal.locked() as state:
        assert state["paused"]


def test_http_origin_interpretation_unresolved(config, fake, journal, clock):
    config["origin_transport_accepted"] = False
    with pytest.raises(OperationError, match="gated"):
        open_session(**open_args(config, fake, journal, clock))
    assert not any(c[1] == "update-distribution" for c in fake.calls)
    with journal.locked() as state:
        assert state["paused"]


def test_late_ready_hook_cannot_reset_absolute_deadline(config, fake, journal, clock):
    options = open_args(config, fake, journal, clock)

    def late(deadline):
        clock.now = deadline + 1
        return dict.fromkeys(
            ["mount", "postgres_tcp", "media_schema", "processing_schema", "redis"], True
        )

    options["state_readiness"] = late
    with pytest.raises(OperationError, match="deadline"):
        open_session(**options)
    assert not any(c[1] == "update-service" for c in fake.calls)


def test_repeat_close_does_not_export_stopped_state(config, fake, journal, clock):
    options = close_args(config, fake, journal, clock)
    close(**options)
    options["pause_intake"] = lambda *a: pytest.fail("closed intake cannot be called")
    options["export_hook"] = lambda *a: pytest.fail("stopped state cannot be exported again")
    assert close(**options)["state_stopped"]


def test_orphan_generator_volume_is_removed(config, fake, journal, clock):
    fake.volumes["orphan"] = {"VolumeId": "orphan", "State": "available"}
    assert close(**close_args(config, fake, journal, clock))["generator_removed"]
    assert not fake.volumes


def test_previous_lost_ack_blocks_repeat_close(config, fake, journal, clock):
    arn = start(config, fake, journal, count=1, deadline=1000, clock=clock)[0]
    fake.tasks[arn]["lastStatus"] = "STOPPED"
    with journal.locked() as state:
        record = next(iter(state["launches"].values()))
        record.update(warm_sent=True, warm_ack=False)
        journal.save(state)
    with pytest.raises(OperationError, match="disposition"):
        close(**close_args(config, fake, journal, clock))
    assert fake.instances["state"]["State"]["Name"] == "running"
