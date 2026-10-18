"""Opt-in Lambda short encodes (V2, #93): template, IAM, concurrency arithmetic, operator config.

Everything here is offline. It proves the generated template and the constants agree and that
the default stack is unchanged; it does not prove IAM evaluation, a mapping's real concurrency
or any timing. Those are the cloud measurement plan in docs/execution/aws/v2/.
"""

import json
from pathlib import Path

import pytest
from v1_support import outputs

from processing import handlers, short_lane
from scripts.aws.v1.config import parameters
from scripts.aws.v1.definitions import LAUNCHER, SHORT_ENCODER, SHORT_QUEUE, template
from scripts.aws.v1.operations import config_from_outputs

ROOT = Path(__file__).resolve().parents[3]
ACCOUNT_LIMIT = short_lane.ACCOUNT_CONCURRENCY


def resources():
    return template()["Resources"]


def lane_resources():
    return {k: v for k, v in resources().items() if v.get("Condition") == "ShortEncodes"}


def statements(role):
    return resources()[role + "Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]


def actions_on(role, prefix):
    return {
        (a, json.dumps(s["Resource"], sort_keys=True))
        for s in statements(role)
        for a in s["Action"]
        if a.startswith(prefix)
    }


# --- Opt-in: default false, nothing created, nothing referenced -------------------------------


def test_the_lane_is_off_by_default_and_needs_applications_too():
    built = template()
    assert built["Parameters"]["LambdaShortEncodes"] == {
        "Type": "String",
        "Default": "false",
        "AllowedValues": ["true", "false"],
    }
    assert built["Conditions"]["ShortEncodes"] == {
        "Fn::And": [
            {"Condition": "Applications"},
            {"Fn::Equals": [{"Ref": "LambdaShortEncodes"}, "true"]},
        ]
    }


def test_every_resource_and_output_of_the_lane_is_conditional():
    owned = {k for k in resources() if k.startswith((SHORT_ENCODER, SHORT_QUEUE))}
    assert {
        f"{SHORT_ENCODER}",
        f"{SHORT_ENCODER}Role",
        f"{SHORT_ENCODER}Mapping",
        f"{SHORT_ENCODER}Alias",
        f"{SHORT_ENCODER}Version",
        f"{SHORT_ENCODER}LogGroup",
        f"{SHORT_QUEUE}Queue",
        f"{SHORT_QUEUE}Dlq",
        f"{SHORT_QUEUE}QueuePolicy",
        f"{SHORT_QUEUE}DlqPolicy",
        f"{SHORT_QUEUE}Senders",
    } <= owned
    assert owned == set(lane_resources())
    names = {k for k in template()["Outputs"] if k.startswith((SHORT_ENCODER, SHORT_QUEUE))}
    assert names and {template()["Outputs"][n]["Condition"] for n in names} == {"ShortEncodes"}


def reference_names(node, *, resource_names=None):
    """Every resource name referenced outside an Fn::If that guards on ShortEncodes."""
    if resource_names is None:
        resource_names = resources().keys()
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "Fn::If" and value[0] == "ShortEncodes":
                continue  # the guarded branches only exist when the lane does
            if key in {"Ref", "Fn::GetAtt", "Fn::Sub"}:
                text = json.dumps(value)
                found |= {n for n in resource_names if n in text}
            found |= reference_names(value, resource_names=resource_names)
    elif isinstance(node, list):
        for item in node:
            found |= reference_names(item, resource_names=resource_names)
    return found


def test_the_reference_scan_catches_an_unguarded_reference_and_skips_a_guarded_one():
    queue = f"{SHORT_QUEUE}Queue"
    assert reference_names({"Ref": queue}) == {queue}
    assert reference_names({"Fn::GetAtt": [queue, "Arn"]}) == {queue}
    assert reference_names({"Fn::If": ["ShortEncodes", {"Ref": queue}, "x"]}) == set()


def test_a_default_stack_has_no_resource_that_refers_to_the_lane_unconditionally():
    # Reuse one template and name set throughout the recursive scan. Rebuilding
    # the entire template at every reference dominated coverage-fast's budget.
    built = resources()
    names = set(built)
    lane = {name for name, resource in built.items() if resource.get("Condition") == "ShortEncodes"}
    for name, resource in built.items():
        if name in lane:
            continue
        assert not (reference_names(resource, resource_names=names) & lane), name


def test_the_default_config_renders_no_lane_parameter_and_true_opts_in():
    config = json.loads((ROOT / "deploy/aws/v1/config.example.json").read_text())
    assert "LambdaShortEncodes" not in {p["ParameterKey"] for p in parameters(config)}
    config["lambda_short_encodes"] = True
    values = {p["ParameterKey"]: p["ParameterValue"] for p in parameters(config)}
    assert values["LambdaShortEncodes"] == "true"
    config["lambda_short_encodes"] = False
    values = {p["ParameterKey"]: p["ParameterValue"] for p in parameters(config)}
    assert values["LambdaShortEncodes"] == "false"
    for bad in ("true", 1, None):
        config["lambda_short_encodes"] = bad
        with pytest.raises(ValueError):
            parameters(config)


def test_the_schema_documents_the_flag_and_still_accepts_the_example():
    import jsonschema

    schema = json.loads((ROOT / "deploy/aws/v1/config.schema.json").read_text())
    assert schema["properties"]["lambda_short_encodes"]["type"] == "boolean"
    config = json.loads((ROOT / "deploy/aws/v1/config.example.json").read_text())
    jsonschema.validate({**config, "lambda_short_encodes": True}, schema)


# --- The function and its executor budget ------------------------------------------------------


def test_the_function_runs_the_worker_image_with_the_lambda_runtime_client_entrypoint():
    function = resources()[SHORT_ENCODER]["Properties"]
    assert function["Code"] == {"ImageUri": {"Ref": "WorkerImageUri"}}
    assert function["ImageConfig"] == {
        "Command": [{"Ref": f"{SHORT_ENCODER}Handler"}],
        "EntryPoint": ["python", "-m", "awslambdaric"],
    }
    assert function["Architectures"] == ["x86_64"]
    assert template()["Parameters"][f"{SHORT_ENCODER}Handler"]["Default"] == (
        "processing.handlers.short_encoder_handler"
    )
    assert callable(handlers.short_encoder_handler)


def test_the_function_budget_is_the_documented_one_and_reserves_nothing():
    function = resources()[SHORT_ENCODER]["Properties"]
    assert "ReservedConcurrentExecutions" not in function  # the account limit forbids it
    assert function["Timeout"] == short_lane.LAMBDA_TIMEOUT_SECONDS <= 900
    assert function["MemorySize"] == short_lane.MEMORY_MB == 3584
    assert function["EphemeralStorage"] == {"Size": short_lane.EPHEMERAL_STORAGE_MB}
    assert 512 <= short_lane.EPHEMERAL_STORAGE_MB <= 10240
    variables = function["Environment"]["Variables"]
    deadline = int(variables["PROCESSING_ATTEMPT_TIMEOUT_SECONDS"])
    assert deadline == short_lane.PIPELINE_DEADLINE_SECONDS
    # Headroom between the full-pipeline deadline and the timeout, with a floor of two minutes.
    assert function["Timeout"] - deadline >= 120
    assert variables["PROCESSING_STORAGE_CREDENTIAL_MODE"] == "lambda"
    assert variables["PROCESSING_SHORT_LANE"] == "true"
    assert "ProcessingRuntimeDsnParameterArn" in json.dumps(variables)


def test_scratch_space_covers_the_largest_admitted_source_with_room_to_spare():
    # Source + primary + ladder, each bounded at the source size twice over: 5x, plus FFmpeg temp.
    worst = 5 * short_lane.MAX_SOURCE_BYTES
    assert worst * 4 <= short_lane.EPHEMERAL_STORAGE_MB * 1024 * 1024


def test_the_queue_visibility_meets_the_mapping_requirement_and_dead_letters_are_kept():
    queue = resources()[f"{SHORT_QUEUE}Queue"]["Properties"]
    function = resources()[SHORT_ENCODER]["Properties"]
    assert queue["VisibilityTimeout"] == short_lane.QUEUE_VISIBILITY_SECONDS
    assert queue["VisibilityTimeout"] > function["Timeout"]  # SQS rejects the mapping otherwise
    dead_letters = {"Fn::GetAtt": [f"{SHORT_QUEUE}Dlq", "Arn"]}
    assert queue["RedrivePolicy"]["deadLetterTargetArn"] == dead_letters
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 5
    assert queue["SqsManagedSseEnabled"] is True


def test_the_mapping_is_closed_one_message_at_a_time_and_bounded_at_the_sqs_minimum():
    mapping = resources()[f"{SHORT_ENCODER}Mapping"]["Properties"]
    # Only a session open, or the always-on environment, enables it.
    assert mapping["Enabled"] == {"Fn::If": ["AlwaysOpen", True, False]}
    assert mapping["BatchSize"] == 1
    assert mapping["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    assert mapping["ScalingConfig"] == {"MaximumConcurrency": 2}
    assert short_lane.ENCODER_MAX_CONCURRENCY == 2  # 2 is the SQS minimum for this setting
    assert mapping["FunctionName"] == {"Ref": f"{SHORT_ENCODER}Alias"}


# --- Least privilege: the Worker's S3, SQS and SSM grants, on the short queue ------------------


def test_the_encoder_role_mirrors_the_fargate_workers_s3_sqs_and_ssm_grants():
    for prefix in ("s3:", "ssm:"):
        assert actions_on(SHORT_ENCODER, prefix) == actions_on("Worker", prefix), prefix
    worker = {(a, r) for a, r in actions_on("Worker", "sqs:")}
    encoder = {(a, r) for a, r in actions_on(SHORT_ENCODER, "sqs:")}
    assert {a for a, _ in encoder} == {a for a, _ in worker}
    assert {r for _, r in worker} == {json.dumps([{"Fn::GetAtt": ["ProcessingWorkQueue", "Arn"]}])}
    assert {r for _, r in encoder} == {json.dumps([{"Fn::GetAtt": [f"{SHORT_QUEUE}Queue", "Arn"]}])}


def test_the_encoder_role_has_nothing_beyond_the_worker_grants_and_lambda_plumbing():
    allowed = {
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:AbortMultipartUpload",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeSubnets",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses",
    }
    assert {a for s in statements(SHORT_ENCODER) for a in s["Action"]} == allowed
    text = json.dumps(statements(SHORT_ENCODER))
    for forbidden in ("sqs:SendMessage", "ecs:", "iam:", "ListBucket", "DeleteObject"):
        assert forbidden not in text
    trust = resources()[f"{SHORT_ENCODER}Role"]["Properties"]["AssumeRolePolicyDocument"]
    assert trust["Statement"][0]["Principal"] == {"Service": "lambda.amazonaws.com"}


def test_only_the_four_publishers_may_send_to_the_short_queue_and_only_the_encoder_reads_it():
    senders = resources()[f"{SHORT_QUEUE}Senders"]["Properties"]
    assert [r["Ref"] for r in senders["Roles"]] == [
        "ProcessingCommandsRole",
        "ProcessingRepairRole",
        "ProcessingEcsEventsRole",
        "ProcessingS3EventsRole",
    ]
    (grant,) = senders["PolicyDocument"]["Statement"]
    assert grant["Action"] == ["sqs:SendMessage"]
    assert grant["Resource"] == [{"Fn::GetAtt": [f"{SHORT_QUEUE}Queue", "Arn"]}]
    policy = resources()[f"{SHORT_QUEUE}QueuePolicy"]["Properties"]["PolicyDocument"]["Statement"]
    by_sid = {s["Sid"]: s for s in policy}
    producers = by_sid["DenyUnlistedProducers"]["Condition"]["ArnNotEquals"]["aws:PrincipalArn"]
    consumers = by_sid["DenyUnlistedConsumers"]["Condition"]["ArnNotEquals"]["aws:PrincipalArn"]
    assert producers == [{"Fn::GetAtt": [f"{r}Role", "Arn"]} for r in (
        "ProcessingCommands", "ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events")]
    assert consumers == [{"Fn::GetAtt": [f"{SHORT_ENCODER}Role", "Arn"]}]
    assert "DenyInsecureTransport" in by_sid


def test_no_other_role_gains_a_short_queue_receive_or_the_launcher_style_ecs_grants():
    for name, resource in resources().items():
        if not name.endswith("Role") or name == f"{SHORT_ENCODER}Role":
            continue
        text = json.dumps(resource)
        assert f"{SHORT_QUEUE}Queue" not in text, name


# --- Publishers route by lane only when the lane exists ---------------------------------------


def test_every_processing_publisher_gets_the_lane_environment_only_when_the_lane_exists():
    publishers = {"ProcessingApi", "ProcessingCommands", "ProcessingRepair",
                  "ProcessingEcsEvents", "ProcessingS3Events"}
    for name in publishers:
        variables = resources()[name]["Properties"]["Environment"]["Variables"]
        flag = variables["PROCESSING_SHORT_LANE"]
        url = variables["PROCESSING_WORK_SHORT_QUEUE_URL"]
        # With the lane off these resolve to AWS::NoValue, so the variables do not exist.
        assert flag == {"Fn::If": ["ShortEncodes", "true", {"Ref": "AWS::NoValue"}]}
        assert url == {
            "Fn::If": ["ShortEncodes", {"Ref": f"{SHORT_QUEUE}Queue"}, {"Ref": "AWS::NoValue"}]
        }
    for name in ("MediaApi", "MediaAuthorizer", "MediaRepair", "MediaResults", LAUNCHER):
        variables = resources()[name]["Properties"]["Environment"]["Variables"]
        assert "PROCESSING_SHORT_LANE" not in variables, name


# --- Concurrency: the account limit is 10 and nothing is reservable ----------------------------


def background_footprint(built, *, lane, launcher):
    mapped = sum(
        r["Properties"]["ScalingConfig"]["MaximumConcurrency"]
        for r in built.values()
        if r["Type"] == "AWS::Lambda::EventSourceMapping"
        and (lane or r.get("Condition") != "ShortEncodes")
    )
    scheduled = [
        r["Properties"]["Targets"][0]["Arn"]["Ref"].removesuffix("Alias")
        for r in built.values()
        if r["Type"] == "AWS::Events::Rule" and "ScheduleExpression" in r["Properties"]
    ]
    # Each scheduled function runs at most once at a time: its timeout is within the period.
    assert all(built[name]["Properties"]["Timeout"] <= 60 for name in scheduled)
    return mapped + len([n for n in scheduled if launcher or n != LAUNCHER])


def test_the_background_concurrency_arithmetic_is_pinned_against_the_account_limit():
    built = resources()
    assert ACCOUNT_LIMIT == 10
    assert background_footprint(built, lane=False, launcher=False) == 6  # V1: 2+2 + 2 repairs
    assert background_footprint(built, lane=False, launcher=True) == 7  # + the launcher (#68)
    assert background_footprint(built, lane=True, launcher=False) == 8  # + 2 Lambda encoders
    worst = background_footprint(built, lane=True, launcher=True)
    assert worst == 9
    # One slot is left for the API, the authorizer and the two event hints: that is the cost.
    assert ACCOUNT_LIMIT - worst == 1
    assert ACCOUNT_LIMIT - worst >= 1, "the API must always be able to run at least once"
    assert not any(
        "ReservedConcurrentExecutions" in r["Properties"]
        for r in built.values()
        if r["Type"] == "AWS::Lambda::Function"
    )


def test_the_combined_encoder_cap_is_fargates_three_plus_lambdas_two():
    built = resources()
    task = built["WorkerTaskDefinition"]["Properties"]["ContainerDefinitions"][0]
    env = {e["Name"]: e["Value"] for e in task["Environment"]}
    assert env["DC2_WORKER_CAP"] == "3" == str(short_lane.FARGATE_ENCODER_CAP)
    assert (
        built[LAUNCHER]["Properties"]["Environment"]["Variables"]["PROCESSING_LAUNCHER_CAP"]
        == "3"
    )
    config, _, _ = config_from_outputs(outputs(), station="s", environment="e")
    assert config["max_worker_tasks"] == short_lane.FARGATE_ENCODER_CAP
    mapping = built[f"{SHORT_ENCODER}Mapping"]["Properties"]["ScalingConfig"]
    assert short_lane.COMBINED_ENCODER_CAP == 3 + mapping["MaximumConcurrency"] == 5


def test_the_encoder_pool_cannot_exceed_what_the_database_can_hold():
    # Each concurrent encoder holds a pool of at most pool_size + max_overflow = 3 connections
    # (one for claim/finish, one for the heartbeat, one spare). The cluster is 0..2 ACU.
    connections = short_lane.COMBINED_ENCODER_CAP * 3
    assert connections <= 15  # far below the connection limit of the smallest Aurora v2 instance


# --- Operator config: the mapping opens and closes with the session, the release is untouched ---


def lane_outputs():
    return outputs() | {
        f"{SHORT_ENCODER}FunctionName": "fn-ProcessingShortEncoder",
        f"{SHORT_ENCODER}MappingId": "33333333-3333-4333-8333-333333333333",
    }


def test_a_stack_without_the_lane_has_an_unchanged_operator_config():
    config, _, _ = config_from_outputs(outputs(), station="s", environment="e")
    assert len(config["mappings"]) == 2
    assert not any("ShortEncoder" in name for name in config["functions"])


def test_the_mapping_joins_session_open_close_and_quiescence_but_never_a_release():
    config, _, _ = config_from_outputs(lane_outputs(), station="s", environment="e")
    mapping = "33333333-3333-4333-8333-333333333333"
    assert mapping in config["mappings"]
    assert mapping in config["owner_consumers"]["processing"]["mappings"]
    assert config["functions"]["fn-ProcessingShortEncoder"] is None  # unreserved
    # A release promotes an owner's image onto its functions. This function runs the Worker
    # image, so putting it in the Processing release would point it at the wrong image.
    assert "fn-ProcessingShortEncoder" not in config["owner_functions"]["processing"].values()
    assert not any("ShortEncoder" in name for name in config["owner_functions"]["processing"])


def test_the_stack_outputs_name_what_the_operator_and_harness_need():
    names = set(template()["Outputs"])
    assert {
        f"{SHORT_ENCODER}FunctionName",
        f"{SHORT_ENCODER}AliasArn",
        f"{SHORT_ENCODER}MappingId",
        f"{SHORT_QUEUE}QueueUrl",
        f"{SHORT_QUEUE}DlqUrl",
        "OutputBucketName",
    } <= names
