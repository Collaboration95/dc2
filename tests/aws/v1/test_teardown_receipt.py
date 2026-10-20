"""The teardown receipt confirms each tagging-API hit with its owning service (#147).

The Resource Groups Tagging API keeps listing a deleted resource for a while. The r1017a
teardown (2026-10-17) reported ITEMS_REMAIN for ten of them, and every one was already gone:
a VPC endpoint and two subnets (EC2 NotFound), an ECS cluster and six task definitions
(INACTIVE, which is free). All offline, against the deploy simulation.
"""

import json
import stat

import pytest
from test_deploy import ACCOUNT, Rig, no_disk_sync  # noqa: F401  (the autouse fixture)

from scripts.aws.v1 import deploy
from scripts.aws.v1.deploy import AwsError, DeployError

pytestmark = pytest.mark.unmeasured

TAGS = {"deploy-project": "dc2-v1", "owner-run": "t1"}
REGION = "ap-southeast-1"


def arn(service, resource):
    return f"arn:aws:{service}:{REGION}:{ACCOUNT}:{resource}"


def linger(rig, resource, state, service="ec2"):
    """List a resource in the (lagging) tagging API; `state` is what its service reports."""
    name = arn(service, resource)
    rig.sim.lingering[name] = {"state": state, "tags": dict(TAGS)}
    return name


@pytest.fixture
def rig(tmp_path):
    made = Rig(tmp_path, skip_final_snapshot=True, confirm_run_id="t1")
    made.sim.tag_lag = False  # each test lists exactly the leftovers it names
    made.deploy()
    return made


def observed_by_id(receipt):
    return {row["id"]: row for row in receipt["tagging_api_observed"]}


def test_the_r1017a_case_of_a_lingering_endpoint_subnets_cluster_and_task_definitions_is_clean(rig):
    ghosts = [
        linger(rig, "vpc-endpoint/vpce-0aaa", "NotFound"),
        linger(rig, "subnet/subnet-0aaa", "NotFound"),
        linger(rig, "subnet/subnet-0bbb", "NotFound"),
        linger(rig, "cluster/dc2-v1-t1", "INACTIVE", service="ecs"),
        *(
            linger(rig, f"task-definition/dc2-v1-t1-worker:{i}", "INACTIVE", service="ecs")
            for i in range(1, 7)
        ),
    ]
    assert len(ghosts) == 10
    receipt = rig.teardown().receipt
    assert receipt["status"] == "CLEAN" and receipt["resources_remaining"] == []
    rows = observed_by_id(receipt)
    assert set(rows) == set(ghosts) and all(row["gone"] for row in rows.values())
    assert {rows[g]["observed"] for g in ghosts[:3]} == {
        "InvalidVpcEndpointId.NotFound",
        "InvalidSubnetID.NotFound",
    }
    assert {rows[g]["observed"] for g in ghosts[3:]} == {"INACTIVE"}


def test_a_stack_deleted_by_the_pipeline_itself_leaves_a_clean_receipt_despite_tagging_lag(
    tmp_path,
):
    made = Rig(tmp_path, skip_final_snapshot=True, confirm_run_id="t1")  # lag is on by default
    made.deploy()
    receipt = made.teardown().receipt
    assert made.sim.lingering, "the simulation must leave the listing behind, as AWS does"
    assert receipt["status"] == "CLEAN" and receipt["resources_remaining"] == []
    assert receipt["tagging_api_observed"]
    assert all(row["gone"] for row in receipt["tagging_api_observed"])


def test_each_hit_records_the_state_its_owning_service_reported(rig):
    endpoint = linger(rig, "vpc-endpoint/vpce-0aaa", "deleted")
    cluster = linger(rig, "cluster/dc2-v1-t1", "INACTIVE", service="ecs")
    receipt = rig.teardown().receipt
    rows = observed_by_id(receipt)
    assert rows[endpoint]["observed"] == "deleted" and rows[endpoint]["gone"]
    assert rows[cluster]["observed"] == "INACTIVE" and rows[cluster]["gone"]
    assert rows[endpoint]["resource_type"] == "ec2:vpc-endpoint"
    assert receipt["status"] == "CLEAN"


def test_an_ec2_resource_that_still_exists_stays_with_its_observed_state(rig):
    survivor = linger(rig, "subnet/subnet-0live", "available")
    gone = linger(rig, "subnet/subnet-0gone", "NotFound")
    receipt = rig.teardown().receipt
    assert receipt["status"] == "ITEMS_REMAIN"
    (item,) = receipt["resources_remaining"]
    assert item["id"] == survivor and item["kind"] == "tagged-resource"
    assert item["observed"] == "available" and "available" in item["why"]
    assert observed_by_id(receipt)[gone]["gone"] is True


@pytest.mark.parametrize("resource", ["cluster/dc2-v1-t1", "task-definition/dc2-v1-t1-worker:3"])
def test_an_ecs_resource_that_is_not_inactive_stays_reported(rig, resource):
    live = linger(rig, resource, "ACTIVE", service="ecs")
    receipt = rig.teardown().receipt
    assert receipt["status"] == "ITEMS_REMAIN"
    assert [(r["id"], r["observed"]) for r in receipt["resources_remaining"]] == [(live, "ACTIVE")]
    assert not rig.ops("delete-task-definitions"), "an ACTIVE definition must never be deleted"


def test_the_runs_inactive_task_definitions_are_deleted_so_they_disappear(rig):
    revisions = [
        linger(rig, f"task-definition/dc2-v1-t1-worker:{i}", "INACTIVE", service="ecs")
        for i in range(1, 4)
    ]
    receipt = rig.teardown().receipt
    (call,) = rig.ops("delete-task-definitions")
    assert call[2] == {"taskDefinitions": revisions}
    rows = observed_by_id(receipt)
    assert {rows[r]["deletion"] for r in revisions} == {"requested"}
    assert {rig.sim.lingering[r]["state"] for r in revisions} == {"DELETE_IN_PROGRESS"}
    assert receipt["status"] == "CLEAN"


def test_task_definitions_are_deleted_ten_at_a_time(rig):
    for i in range(1, 24):
        linger(rig, f"task-definition/dc2-v1-t1-worker:{i}", "INACTIVE", service="ecs")
    rig.teardown()
    sizes = [len(c[2]["taskDefinitions"]) for c in rig.ops("delete-task-definitions")]
    assert sizes == [10, 10, 3]


def test_a_failed_task_definition_delete_is_tolerated_and_recorded(rig):
    revision = linger(rig, "task-definition/dc2-v1-t1-worker:1", "INACTIVE", service="ecs")
    rig.sim.fail[("ecs", "delete-task-definitions")] = [
        AwsError("ecs", "delete-task-definitions", "AccessDeniedException")
    ]
    receipt = rig.teardown().receipt
    assert receipt["status"] == "CLEAN"  # INACTIVE is free; a refused delete is not a leftover
    assert observed_by_id(receipt)[revision]["deletion"] == (
        "requested but failed: AccessDeniedException"
    )


def test_a_per_item_delete_failure_in_the_reply_is_recorded_too(rig, monkeypatch):
    revision = linger(rig, "task-definition/dc2-v1-t1-worker:1", "INACTIVE", service="ecs")
    monkeypatch.setattr(
        rig.sim,
        "ecs_delete_task_definitions",
        lambda payload: {
            "taskDefinitions": [],
            "failures": [{"arn": revision, "reason": "ATTACHMENT_IN_USE"}],
        },
    )
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[revision]["deletion"] == (
        "requested but failed: ATTACHMENT_IN_USE"
    )
    assert receipt["status"] == "CLEAN"


def test_an_ecs_cluster_the_service_no_longer_knows_is_gone(rig):
    missing = linger(rig, "cluster/dc2-v1-t1", "MISSING", service="ecs")
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[missing]["gone"] is True
    assert observed_by_id(receipt)[missing]["observed"] == "MISSING"
    assert receipt["status"] == "CLEAN"


def test_a_fully_deleted_task_definition_is_gone_without_a_delete_call(rig):
    revision = linger(rig, "task-definition/dc2-v1-t1-worker:9", "NotFound", service="ecs")
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[revision]["gone"] is True
    assert not rig.ops("delete-task-definitions")


def answer_not_found(monkeypatch, rig, operation, identifier_key, ghost_id, code):
    """Make one RDS lookup fail with `code` for the ghost only, so the real teardown is unharmed."""
    handler = f"rds_{operation.replace('-', '_')}"
    original = getattr(rig.sim, handler)

    def answer(payload):
        if payload[identifier_key] == ghost_id:
            raise AwsError("rds", operation, code)
        return original(payload)

    monkeypatch.setattr(rig.sim, handler, answer)


@pytest.mark.parametrize("code", list(deploy.CLUSTER_NOT_FOUND))
def test_an_rds_cluster_not_found_is_gone_under_either_spelling(rig, monkeypatch, code):
    ghost = linger(rig, "cluster:dc2-v1-t1-ghost", "", service="rds")
    answer_not_found(
        monkeypatch, rig, "describe-db-clusters", "DBClusterIdentifier", "dc2-v1-t1-ghost", code
    )
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[ghost]["observed"] == code
    assert receipt["status"] == "CLEAN"


@pytest.mark.parametrize("code", list(deploy.INSTANCE_NOT_FOUND))
def test_an_rds_instance_not_found_is_gone_under_either_spelling(rig, monkeypatch, code):
    ghost = linger(rig, "db:dc2-v1-t1-ghost", "", service="rds")
    answer_not_found(
        monkeypatch, rig, "describe-db-instances", "DBInstanceIdentifier", "dc2-v1-t1-ghost", code
    )
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[ghost]["observed"] == code
    assert receipt["status"] == "CLEAN"


def test_an_rds_cluster_that_still_answers_stays_with_its_status(rig):
    live = linger(rig, "cluster:dc2-v1-t1-other", "", service="rds")
    rig.sim.clusters["dc2-v1-t1-other"] = {
        "status": "available",
        "protected": False,
        "tags": dict(TAGS),
    }
    receipt = rig.teardown().receipt
    (item,) = receipt["resources_remaining"]
    assert item["id"] == live and item["observed"] == "available"


def test_an_s3_bucket_that_no_longer_exists_is_gone(rig):
    bucket = "arn:aws:s3:::dc2-v1-t1-vanished"
    rig.sim.lingering[bucket] = {"state": "", "tags": dict(TAGS)}
    receipt = rig.teardown().receipt
    assert observed_by_id(receipt)[bucket]["gone"] is True
    assert observed_by_id(receipt)[bucket]["observed"] == "NoSuchBucket"
    assert receipt["status"] == "CLEAN"


def test_an_s3_bucket_that_still_exists_stays_reported(rig):
    rig.sim.buckets["dc2-v1-t1-stray"] = {
        "tags": dict(TAGS),
        "versions": [],
        "markers": [],
        "uploads": [],
    }
    receipt = rig.teardown().receipt
    (item,) = receipt["resources_remaining"]
    assert item["id"] == "arn:aws:s3:::dc2-v1-t1-stray" and item["observed"] == "exists"


def test_a_resource_type_with_no_existence_check_stays_and_says_so(rig):
    queue = linger(rig, "dc2-v1-t1-queue", "", service="sqs")
    receipt = rig.teardown().receipt
    (item,) = receipt["resources_remaining"]
    assert item["id"] == queue and item["observed"] == "unchecked"
    assert receipt["status"] == "ITEMS_REMAIN"


def test_a_check_that_cannot_be_made_keeps_the_item_instead_of_guessing(rig):
    subnet = linger(rig, "subnet/subnet-0aaa", "NotFound")
    rig.sim.fail[("ec2", "describe-subnets")] = [
        AwsError("ec2", "describe-subnets", "UnauthorizedOperation")
    ]
    receipt = rig.teardown().receipt
    (item,) = receipt["resources_remaining"]
    assert item["id"] == subnet and item["observed"] == "unconfirmed (UnauthorizedOperation)"


def test_the_receipt_is_written_private_with_the_observed_states(rig):
    linger(rig, "subnet/subnet-0aaa", "NotFound")
    rig.teardown()
    path = rig.s.state_dir / "teardown-receipt-t1.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["tagging_api_observed"][0]["observed"] == (
        "InvalidSubnetID.NotFound"
    )


# ---- the new read and delete operations stay inside the allowlist -----------------------------
@pytest.mark.parametrize(
    "service,operation,payload",
    [
        ("ec2", "describe-subnets", {"SubnetIds": ["subnet-0aaa"]}),
        ("ec2", "describe-vpc-endpoints", {"VpcEndpointIds": ["vpce-0aaa"]}),
        ("ecs", "describe-clusters", {"clusters": [arn("ecs", "cluster/c")]}),
        (
            "ecs",
            "delete-task-definitions",
            {"taskDefinitions": [arn("ecs", "task-definition/w:1")]},
        ),
    ],
)
def test_the_receipts_operations_are_allowed(service, operation, payload):
    deploy.check_operation(service, operation, payload)


@pytest.mark.parametrize(
    "service,operation,payload",
    [
        ("ec2", "delete-subnet", {"SubnetId": "subnet-0aaa"}),
        ("ec2", "describe-subnets", {"SubnetIds": ["subnet-0aaa", "subnet-0bbb"]}),
        ("ec2", "describe-subnets", {"SubnetIds": ["subnet-0aaa"], "DryRun": True}),
        ("ec2", "describe-instances", {"InstanceIds": ["i-0aaa"]}),
        ("ecs", "delete-cluster", {"cluster": "c"}),
        (
            "ecs",
            "delete-task-definitions",
            {"taskDefinitions": [arn("ecs", f"task-definition/w:{i}") for i in range(11)]},
        ),
        ("ecs", "delete-task-definitions", {"taskDefinitions": []}),
        ("ecs", "delete-task-definitions", {"taskDefinitions": ["x; rm -rf /"]}),
        ("ecs", "describe-clusters", {"clusters": [], "include": ["TAGS"]}),
    ],
)
def test_anything_beyond_the_receipts_exact_calls_is_refused(service, operation, payload):
    with pytest.raises(DeployError):
        deploy.check_operation(service, operation, payload)
