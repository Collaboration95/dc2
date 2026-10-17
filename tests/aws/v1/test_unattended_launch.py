"""Opt-in unattended launcher (V2, #68): template, operator interlocks and pure launcher parts.

Everything here is offline. The SQL reservation behaviour (cap, tokens, concurrency, restart,
close interlock) is in tests/v1/test_launcher_sql.py against real PostgreSQL.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from v1_support import outputs

from processing import launcher, launcher_aws
from processing.launcher import HARD_CAP, LauncherConfig, RunTaskRefused
from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1.config import parameters
from scripts.aws.v1.definitions import LAUNCHER, template
from scripts.aws.v1.hooks import ATTEMPT_STATES, AttemptCounts, LauncherHooks, OwnerHooks
from scripts.aws.v1.operations import PlanTransport, config_from_outputs
from scripts.aws.v1.session import Session

ROOT = Path(__file__).resolve().parents[3]
FUNCTION, RULE = "fn-ProcessingLauncher", "rule-ProcessingLauncher"


def launcher_outputs():
    return outputs() | {f"{LAUNCHER}FunctionName": FUNCTION, f"{LAUNCHER}RuleName": RULE}


def resources_of(built=None):
    return (built or template())["Resources"]


def launcher_resources():
    return {k: v for k, v in resources_of().items() if k.startswith(LAUNCHER)}


# --- Template: opt-in, disabled, least privilege, inside the Lambda budget --------------------


def test_the_launcher_is_off_by_default_and_every_resource_of_it_is_conditional():
    built = template()
    assert built["Parameters"]["UnattendedLaunch"]["Default"] == "false"
    assert built["Parameters"]["UnattendedLaunch"]["AllowedValues"] == ["true", "false"]
    owned = launcher_resources()
    assert {"ProcessingLauncher", "ProcessingLauncherRole", "ProcessingLauncherRule"} <= set(owned)
    assert {r["Condition"] for r in owned.values()} == {"Unattended"}
    # Only both flags together create it: it can never exist in a stack without applications.
    assert built["Conditions"]["Unattended"] == {
        "Fn::And": [
            {"Condition": "Applications"},
            {"Fn::Equals": [{"Ref": "UnattendedLaunch"}, "true"]},
        ]
    }
    outs = {k: v for k, v in built["Outputs"].items() if k.startswith(LAUNCHER)}
    assert outs and {o["Condition"] for o in outs.values()} == {"Unattended"}


def test_the_default_config_renders_no_unattended_parameter_and_true_opts_in(tmp_path):
    config = json.loads((ROOT / "deploy/aws/v1/config.example.json").read_text())
    assert "UnattendedLaunch" not in {p["ParameterKey"] for p in parameters(config)}
    config["unattended_launch"] = True
    values = {p["ParameterKey"]: p["ParameterValue"] for p in parameters(config)}
    assert values["UnattendedLaunch"] == "true"
    for bad in ("true", 1, None):
        config["unattended_launch"] = bad
        with pytest.raises(ValueError):
            parameters(config)


def test_the_launcher_schedule_rule_is_disabled_by_default_and_never_retried():
    rule = resources_of()["ProcessingLauncherRule"]["Properties"]
    assert rule["State"] == "DISABLED"
    assert rule["ScheduleExpression"] == "rate(1 minute)"
    assert rule["Targets"][0]["RetryPolicy"]["MaximumRetryAttempts"] == 0
    assert rule["Targets"][0]["Arn"] == {"Ref": "ProcessingLauncherAlias"}
    # No rule in the stack starts enabled: only the session API turns any of them on.
    states = {
        r["Properties"]["State"]
        for r in resources_of().values()
        if r["Type"] == "AWS::Events::Rule"
    }
    assert states == {"DISABLED"}


def role_statements():
    role = resources_of()["ProcessingLauncherRole"]["Properties"]
    return role["Policies"][0]["PolicyDocument"]["Statement"]


def grants(action):
    return [s for s in role_statements() if action in s["Action"]]


def test_the_launcher_may_only_run_the_worker_family_in_this_cluster():
    (run,) = grants("ecs:RunTask")
    assert run["Resource"] == [
        {
            "Fn::Sub": "arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:"
            "task-definition/${EnvironmentId}-worker:*"
        }
    ]
    assert run["Condition"] == {"ArnEquals": {"ecs:cluster": {"Fn::GetAtt": ["Cluster", "Arn"]}}}
    family = resources_of()["WorkerTaskDefinition"]["Properties"]["Family"]
    assert family == {"Fn::Sub": "${EnvironmentId}-worker"}


def test_the_launcher_may_pass_only_the_workers_two_roles_and_only_to_ecs_tasks():
    (passed,) = grants("iam:PassRole")
    assert passed["Resource"] == [
        {"Fn::GetAtt": ["WorkerRole", "Arn"]},
        {"Fn::GetAtt": ["WorkerExecutionRole", "Arn"]},
    ]
    assert passed["Condition"] == {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
    }
    task = resources_of()["WorkerTaskDefinition"]["Properties"]
    assert task["TaskRoleArn"] == {"Fn::GetAtt": ["WorkerRole", "Arn"]}
    assert task["ExecutionRoleArn"] == {"Fn::GetAtt": ["WorkerExecutionRole", "Arn"]}


def test_the_launcher_reads_only_this_clusters_tasks_and_one_queues_depth():
    cluster = {"ArnEquals": {"ecs:cluster": {"Fn::GetAtt": ["Cluster", "Arn"]}}}
    assert [s["Condition"] for s in grants("ecs:ListTasks")] == [cluster]
    (describe,) = grants("ecs:DescribeTasks")
    assert describe["Condition"] == cluster
    assert "task/${Cluster}/*" in describe["Resource"][0]["Fn::Sub"]
    (depth,) = grants("sqs:GetQueueAttributes")
    assert depth["Resource"] == [{"Fn::GetAtt": ["ProcessingWorkQueue", "Arn"]}]


def test_the_launcher_has_no_other_privilege_than_starting_and_observing_workers():
    allowed = {
        "ecs:RunTask",
        "iam:PassRole",
        "ecs:ListTasks",
        "ecs:DescribeTasks",
        "sqs:GetQueueAttributes",
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
    actions = {a for s in role_statements() for a in s["Action"]}
    assert actions == allowed
    # The database parameter is its own domain's runtime DSN, never a peer's or a migrator's.
    (ssm,) = grants("ssm:GetParameter")
    assert ssm["Resource"] == [{"Ref": "ProcessingRuntimeDsnParameterArn"}]


def test_no_other_role_gains_ecs_or_pass_role_from_the_launcher():
    for name, resource in resources_of().items():
        if not name.endswith("Role") or name == "ProcessingLauncherRole":
            continue
        text = json.dumps(resource)
        assert "ecs:RunTask" not in text and "iam:PassRole" not in text, name


def test_the_launcher_function_reserves_nothing_and_cannot_overlap_its_own_schedule():
    function = resources_of()["ProcessingLauncher"]["Properties"]
    assert "ReservedConcurrentExecutions" not in function
    assert function["Timeout"] < 60  # shorter than the rule's period
    assert function["ImageConfig"]["Command"] == [{"Ref": "ProcessingLauncherHandler"}]
    assert template()["Parameters"]["ProcessingLauncherHandler"]["Default"] == (
        "processing.handlers.launcher_handler"
    )
    variables = function["Environment"]["Variables"]
    assert variables["PROCESSING_LAUNCHER_CAP"] == "3"
    assert variables["PROCESSING_LAUNCHER_TASK_DEFINITION"] == {"Ref": "WorkerTaskDefinition"}
    assert variables["PROCESSING_LAUNCHER_SECURITY_GROUPS"] == {"Ref": "WorkerSecurityGroup"}
    # It reads the Processing database like the repair function, never the Media one.
    assert "PROCESSING_POSTGRES_DSN_PARAMETER_ARN" in variables
    assert not any(k.startswith("MEDIA_") and "DSN" in k for k in variables)


def test_concurrency_accounting_includes_the_launcher_and_stays_inside_the_account_limit():
    """The account limit is 10 with nothing reservable, so every background source is counted."""
    account_limit = 10
    built = resources_of()

    def footprint(include):
        # The opt-in short encoder's mapping (#93) is counted in test_short_encodes.
        mapped = sum(
            r["Properties"]["ScalingConfig"]["MaximumConcurrency"]
            for r in built.values()
            if r["Type"] == "AWS::Lambda::EventSourceMapping"
            and r.get("Condition") != "ShortEncodes"
        )
        scheduled = [
            r["Properties"]["Targets"][0]["Arn"]["Ref"].removesuffix("Alias")
            for r in built.values()
            if r["Type"] == "AWS::Events::Rule" and "ScheduleExpression" in r["Properties"]
        ]
        # Each scheduled function runs at most once at a time: its timeout is not above the
        # one-minute period (the launcher's is well below it).
        assert all(built[name]["Properties"]["Timeout"] <= 60 for name in scheduled)
        return mapped + len([n for n in scheduled if include or n != LAUNCHER])

    assert footprint(include=False) == 6  # two consumers x 2, plus the two repair schedules
    assert footprint(include=True) == 7  # the launcher adds exactly one
    assert footprint(include=True) < account_limit  # leaving three for the API and event hints


# --- Operator: opt-in at open, first off at close ---------------------------------------------


class Cloud(PlanTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ambiguous = 0

    def call(self, service, operation, payload, *, deadline):
        result = super().call(service, operation, payload, deadline=deadline)
        if operation == "invoke" and payload["Payload"].get("action") == "settle":
            # The simulated control row reports ambiguity until the test clears it.
            result["Payload"]["ambiguous"] = self.ambiguous
            self.ambiguous = max(0, self.ambiguous - 1)
        return result

    def log(self):
        events = []
        for c in self.calls:
            if c["operation"] == "invoke" and c["payload"]["FunctionName"] == FUNCTION:
                events.append("flag:" + c["payload"]["Payload"]["action"])
            elif c["operation"] in {"enable-rule", "disable-rule"} and c["payload"]["Name"] == RULE:
                events.append(c["operation"])
        return events


@pytest.fixture
def rig(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    config, hooks, _ = config_from_outputs(launcher_outputs(), station="s", environment="e2e")
    journal = Journal(directory / "session.json", station="s", environment="e2e")
    journal.initialize(verified_empty=True, exclusive_station=True)
    cloud = Cloud()
    session = Session(config, cloud, journal)
    owner = OwnerHooks(cloud, **hooks, sleep=lambda s: None)
    return session, cloud, journal, owner, config, LauncherHooks(owner, sleep=lambda s: None)


def deadline():
    return time.monotonic() + 30


def zero_counts():
    return AttemptCounts(lambda _d: dict.fromkeys(ATTEMPT_STATES, 0))


def open_unattended(rig, minutes=60):
    session, _, _, owner, _, hooks = rig
    return session.open(
        ready=owner.ready,
        repair=owner.repair,
        deadline=deadline(),
        launcher=hooks,
        launcher_session_end=time.time() + 60 * minutes,
    )


def test_a_stack_without_the_launcher_has_no_launcher_in_the_operator_config():
    config, hooks, _ = config_from_outputs(outputs(), station="s", environment="e")
    assert "launcher" not in config and "launcher" not in hooks
    with pytest.raises(OperationError, match="UnattendedLaunch"):
        LauncherHooks(OwnerHooks(PlanTransport(), **hooks))


def test_the_launcher_rule_is_never_among_the_schedules_that_open_enables():
    config, hooks, _ = config_from_outputs(launcher_outputs(), station="s", environment="e")
    assert RULE not in config["schedules"]
    assert config["launcher"] == {"function": FUNCTION, "rule": RULE}
    assert hooks["launcher"] == FUNCTION
    # But releases and quiescence checks treat it as a Processing consumer.
    assert RULE in config["owner_consumers"]["processing"]["schedules"]
    assert config["owner_functions"]["processing"][LAUNCHER] == FUNCTION
    assert FUNCTION in config["functions"]


def test_a_plain_open_leaves_the_launcher_off(rig):
    session, cloud, journal, owner, _, _ = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    assert cloud.log() == [] and RULE not in cloud.rules
    assert json.loads(journal.path.read_text())["unattended"] is False
    assert session.status(deadline=deadline())["drift"] == []


def test_open_unattended_sets_the_flag_before_enabling_the_rule(rig):
    session, cloud, journal, _, _, _ = rig
    open_unattended(rig)
    assert cloud.log() == ["flag:enable", "enable-rule"]
    enable = next(
        c for c in cloud.calls if c["payload"].get("Payload", {}).get("action") == "enable"
    )
    assert enable["payload"]["Qualifier"] == "live"
    assert enable["payload"]["Payload"]["session_end_epoch"] > time.time()
    assert cloud.rules[RULE] == "ENABLED"
    assert json.loads(journal.path.read_text())["unattended"] is True
    assert session.status(deadline=deadline())["drift"] == []


def test_operator_batches_are_refused_while_the_launcher_owns_worker_starts(rig):
    session, cloud, *_ = rig
    open_unattended(rig)
    with pytest.raises(OperationError, match="Unattended launcher owns"):
        session.batch(count=1, deadline=deadline())
    assert not [c for c in cloud.calls if c["operation"] == "run-task"]


def test_unattended_open_needs_a_launcher_stack_a_full_open_and_a_session_end(rig, tmp_path):
    session, cloud, journal, owner, _, hooks = rig
    with pytest.raises(OperationError, match="full open"):
        session.open(
            ready=owner.ready, repair=owner.repair, deadline=deadline(), launcher=hooks
        )
    with pytest.raises(OperationError, match="full open"):
        session.open(
            ready=owner.ready,
            repair=owner.repair,
            deadline=deadline(),
            window=True,
            launcher=hooks,
            launcher_session_end=time.time() + 60,
        )
    assert cloud.calls == []  # refused before any change
    plain, _, _ = config_from_outputs(outputs(), station="s", environment="e2e")
    other = Session(plain, cloud, journal)
    with pytest.raises(OperationError, match="full open"):
        other.open(
            ready=owner.ready,
            repair=owner.repair,
            deadline=deadline(),
            launcher=hooks,
            launcher_session_end=time.time() + 60,
        )


def test_close_switches_the_launcher_off_before_anything_else_and_settles_before_inventory(rig):
    session, cloud, *_ = rig
    open_unattended(rig)
    cloud.calls.clear()
    reader = zero_counts()
    hooks = rig[5]
    session.close(drain=reader.drain, outcomes=reader.outcomes, deadline=deadline(), launcher=hooks)
    operations_in_order = [
        (c["operation"], c["payload"].get("Name") or c["payload"].get("Payload", {}).get("action"))
        for c in cloud.calls
    ]
    first_intake = next(i for i, (op, _) in enumerate(operations_in_order) if op == "update-stage")
    assert operations_in_order[0] == ("disable-rule", RULE)
    assert operations_in_order[1] == ("describe-rule", RULE)  # the disable is confirmed
    assert operations_in_order[2] == ("invoke", "disable")
    assert operations_in_order.index(("invoke", "settle")) > 1
    assert operations_in_order.index(("disable-rule", RULE)) < first_intake
    assert cloud.rules[RULE] == "DISABLED"
    assert not any(c["operation"] == "run-task" for c in cloud.calls)


def test_close_does_not_succeed_while_a_launch_is_still_ambiguous(rig):
    session, cloud, journal, *_ = rig
    open_unattended(rig)
    cloud.ambiguous = 10**6
    reader = zero_counts()
    hooks = LauncherHooks(rig[3], sleep=lambda s: None, clock=iter(range(0, 1000)).__next__)
    with pytest.raises(OperationError, match="Partial close"):
        session.close(
            drain=reader.drain,
            outcomes=reader.outcomes,
            deadline=time.monotonic() + 0.5,
            launcher=hooks,
        )
    saved = json.loads(journal.path.read_text())
    assert "launcher:settle" in saved["session_failures"] and saved["session"] == "closing"
    # The rule and the flag were already off, so a retry cannot be racing a new launch.
    assert cloud.rules[RULE] == "DISABLED"


def test_a_failed_flag_disable_fails_close_and_skips_the_drain(rig):
    session, cloud, journal, owner, *_ = rig
    open_unattended(rig)

    class Broken(LauncherHooks):
        def disable(self, *, deadline):
            raise OperationError("launcher unreachable")

    reader = zero_counts()
    with pytest.raises(OperationError, match="Partial close"):
        session.close(
            drain=reader.drain,
            outcomes=reader.outcomes,
            deadline=deadline(),
            launcher=Broken(owner),
        )
    saved = json.loads(journal.path.read_text())
    assert saved["session_failures"] == ["launcher:flag"]
    assert "drain" not in saved["session_completed"]
    assert cloud.rules[RULE] == "DISABLED"  # every other wake source still closed


def test_status_reports_a_launcher_rule_that_drifted_on_underneath_a_plain_session(rig):
    session, cloud, _, owner, *_ = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    cloud.rules[RULE] = "ENABLED"
    assert session.status(deadline=deadline())["drift"] == ["launcher-rule:ENABLED"]


def test_launcher_hooks_refuse_an_unconfirmed_reply(rig):
    _, cloud, _, _, _, hooks = rig
    assert hooks.enable(session_end_epoch=time.time() + 60, deadline=deadline()) is True
    assert hooks.disable(deadline=deadline()) is True
    cloud.call = lambda *a, **k: {"StatusCode": 200, "FunctionError": True, "Payload": {}}
    with pytest.raises(OperationError, match="did not confirm"):
        hooks.disable(deadline=deadline())


# --- Migration ---------------------------------------------------------------------------------


def test_the_launcher_migration_is_the_next_revision_and_only_adds():
    source = (ROOT / "processing/migrations/versions/0007_launch_reservations.py").read_text()
    assert 'revision = "processing_0007"' in source
    assert 'down_revision = "processing_0006"' in source
    upgrade = source.split("def upgrade")[1].split("def downgrade")[0]
    assert "drop_" not in upgrade and "alter_column" not in upgrade
    assert upgrade.count("create_table") == 2
    versions = sorted(p.name for p in (ROOT / "processing/migrations/versions").glob("*.py"))
    assert versions[-1] == "0007_launch_reservations.py"


# --- Pure launcher parts -----------------------------------------------------------------------


def config(**overrides):
    values = {
        "cluster": "arn:aws:ecs:ap-southeast-1:1:cluster/c",
        "task_definition": "arn:aws:ecs:ap-southeast-1:1:task-definition/env-worker:7",
        "subnets": ("subnet-a", "subnet-b"),
        "security_groups": ("sg-1",),
    }
    return LauncherConfig(**(values | overrides))


def test_the_cap_can_be_lowered_but_never_raised_above_three():
    assert config(cap=10).slots == HARD_CAP == 3
    assert config(cap=2).slots == 2
    assert config(cap=0).slots == 0
    assert config(cap=-5).slots == 0


def test_launch_requests_match_the_operator_batch_shape_and_fit_ecs_limits():
    token = "a" * 32
    payload = launcher.run_payload(config(), token, 1_800_000_000.7)
    assert payload["clientToken"] == token and len(payload["clientToken"]) <= 64
    assert payload["startedBy"] == "v1-u" + token and len(payload["startedBy"]) == 36
    assert payload["launchType"] == "FARGATE" and payload["count"] == 1
    assert payload["networkConfiguration"]["awsvpcConfiguration"] == {
        "subnets": ["subnet-a", "subnet-b"],
        "securityGroups": ["sg-1"],
        "assignPublicIp": "ENABLED",
    }
    (override,) = payload["overrides"]["containerOverrides"]
    assert override["name"] == "worker"
    assert override["command"] == [
        "python", "-m", "processing.v1_worker", "--deadline-epoch", "1800000000",
        "--name", payload["startedBy"], "--max-empty-polls", "2",
    ]  # fmt: skip
    assert config().family == "env-worker"


def test_a_launch_request_has_exactly_the_shape_of_an_operator_batch_request(rig):
    session, cloud, _, owner, built, _ = rig
    session.open(ready=owner.ready, repair=owner.repair, deadline=deadline())
    built["session_end_epoch"] = time.time() + 600
    session.batch(count=1, deadline=deadline())
    (batch,) = [c["payload"] for c in cloud.calls if c["operation"] == "run-task"]
    mine = launcher.run_payload(
        config(
            cluster=built["cluster"],
            task_definition=built["task_definitions"]["worker"],
            subnets=tuple(built["network"]["subnets"]),
            security_groups=tuple(built["network"]["security_groups"]),
        ),
        "b" * 32,
        time.time() + 600,
    )

    def skeleton(payload):
        override = payload["overrides"]["containerOverrides"][0]
        flags = [part for part in override["command"] if part.startswith("-")]
        return {k: v for k, v in payload.items() if k not in {"clientToken", "startedBy"}} | {
            "overrides": (override["name"], override["command"][:3], flags)
        }

    assert skeleton(mine) == skeleton(batch)


def test_the_launcher_names_workers_the_way_terminal_events_bind_them():
    task = {"taskArn": "arn:aws:ecs:r:1:task/c/abc123", "startedBy": "v1-uX"}
    assert launcher.task_names(task) == {"v1-uX", task["taskArn"], "abc123"}
    assert launcher.task_names({}) == set()


class Ecs:
    def __init__(self, pages=None, tasks=None, failures=None):
        self.pages, self.tasks, self.failures = pages or {}, tasks or [], failures or []
        self.described = []

    async def list_tasks(self, desired):
        return self.pages.get(desired, [])

    async def describe_tasks(self, arns):
        self.described.append(list(arns))
        return {"tasks": [t for t in self.tasks if t["taskArn"] in arns], "failures": self.failures}


def task(arn, family="env-worker", status="RUNNING"):
    return {
        "taskArn": arn,
        "taskDefinitionArn": f"arn:aws:ecs:r:1:task-definition/{family}:1",
        "lastStatus": status,
    }


async def test_observation_keeps_only_worker_family_tasks_and_batches_describe_calls():
    arns = [f"arn:t/{i:03}" for i in range(250)]
    tasks = [task(a) for a in arns] + [task("arn:other", family="env-migration")]
    ecs = Ecs({"RUNNING": arns[:200], "STOPPED": arns[200:] + ["arn:other"]}, tasks)
    seen = await launcher.observe(ecs, config())
    assert set(seen.workers) == set(arns) and "arn:other" not in seen.workers
    assert [len(batch) for batch in ecs.described] == [100, 100, 51]


async def test_observation_treats_missing_as_gone_but_any_other_failure_as_fatal():
    ecs = Ecs({}, [], [{"arn": "arn:gone", "reason": "MISSING"}])
    seen = await launcher.observe(ecs, config(), ["arn:gone"])
    assert seen.missing == {"arn:gone"} and seen.workers == {}
    broken = Ecs({}, [], [{"arn": "arn:x", "reason": "ACCESS_DENIED"}])
    with pytest.raises(RuntimeError):
        await launcher.observe(broken, config(), ["arn:x"])


class ClientError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code},
        }


class Client:
    def __init__(self, error=None, pages=()):
        self.error, self.pages, self.calls = error, list(pages), []

    def run_task(self, **payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return {"tasks": [{"taskArn": "arn:t"}]}

    def list_tasks(self, **request):
        self.calls.append(request)
        return self.pages.pop(0)

    def describe_tasks(self, **request):
        return {"tasks": [], "failures": []}

    def get_queue_attributes(self, **request):
        self.calls.append(request)
        return {"Attributes": {"ApproximateNumberOfMessages": "7"}}


@pytest.mark.parametrize(
    "error,refused",
    [
        (ClientError(400, "InvalidParameterException"), True),
        (ClientError(403, "AccessDeniedException"), True),
        (ClientError(409, "ConflictException"), False),
        (ClientError(503, "ServiceUnavailableException"), False),
        (TimeoutError("read timeout"), False),
    ],
)
async def test_only_a_definite_ecs_rejection_releases_a_slot_everything_else_stays_ambiguous(
    error, refused
):
    port = launcher_aws.EcsPort("c", client=Client(error))
    if refused:
        with pytest.raises(RunTaskRefused):
            await port.run_task({"clientToken": "t"})
    else:
        with pytest.raises(type(error)):
            await port.run_task({"clientToken": "t"})


async def test_the_ecs_port_pages_listings_and_bounds_a_runaway_token():
    pages = [{"taskArns": ["a"], "nextToken": "n"}, {"taskArns": ["b"]}]
    port = launcher_aws.EcsPort("c", client=Client(pages=pages))
    assert await port.list_tasks("RUNNING") == ["a", "b"]
    forever = Client(pages=[{"taskArns": [], "nextToken": "n"}] * launcher.LIST_PAGES)
    with pytest.raises(RuntimeError, match="terminate"):
        await launcher_aws.EcsPort("c", client=forever).list_tasks("STOPPED")


async def test_queue_depth_reads_only_the_visible_message_count():
    client = Client()
    assert await launcher_aws.QueueDepth("https://q", client=client).visible() == 7
    assert client.calls == [
        {"QueueUrl": "https://q", "AttributeNames": ["ApproximateNumberOfMessages"]}
    ]


def test_runtime_configuration_comes_from_the_stack_environment():
    environ = {
        "PROCESSING_LAUNCHER_CLUSTER": "arn:cluster",
        "PROCESSING_LAUNCHER_TASK_DEFINITION": "arn:def",
        "PROCESSING_LAUNCHER_SUBNETS": "s1,s2",
        "PROCESSING_LAUNCHER_SECURITY_GROUPS": "sg",
        "PROCESSING_LAUNCHER_LIFETIME_SECONDS": "900",
    }
    built = launcher_aws.config_from_environ(environ)
    assert built.subnets == ("s1", "s2") and built.lifetime_seconds == 900 and built.slots == 3
    environ["PROCESSING_LAUNCHER_CAP"] = "9"
    assert launcher_aws.config_from_environ(environ).slots == 3


async def test_control_events_dispatch_to_the_matching_sql_action(monkeypatch):
    seen = []

    async def set_enabled(factory, enabled, **kwargs):
        seen.append(("enabled", enabled, kwargs))
        return {"enabled": enabled}

    async def settle(factory, ecs, cfg):
        seen.append("settle")
        return {"ambiguous": 0}

    async def status(factory):
        seen.append("status")
        return {"enabled": False}

    async def tick(factory, ecs, queue, cfg):
        seen.append("tick")
        return {"launched": 0}

    monkeypatch.setattr(launcher, "set_enabled", set_enabled)
    monkeypatch.setattr(launcher, "settle", settle)
    monkeypatch.setattr(launcher, "status", status)
    monkeypatch.setattr(launcher, "tick", tick)
    dispatch = launcher_aws._dispatch
    control = {"dc2_operation": "launcher"}
    enabled = await dispatch({**control, "action": "enable", "session_end_epoch": 5}, 1, 2, 3, 4)
    assert enabled == {"service": "processing-launcher", "action": "enable", "enabled": True}
    await dispatch({**control, "action": "disable"}, 1, 2, 3, 4)
    await dispatch({**control, "action": "settle"}, 1, 2, 3, 4)
    await dispatch({**control, "action": "status"}, 1, 2, 3, 4)
    with pytest.raises(ValueError):
        await dispatch({**control, "action": "purge"}, 1, 2, 3, 4)
    # A scheduled EventBridge event (or any other shape) is a plain tick, never a control.
    scheduled = {"source": "aws.events", "detail-type": "Scheduled Event"}
    result = await dispatch(scheduled, 1, 2, SimpleNamespace(), 4)
    assert result["action"] == "tick" and seen[-1] == "tick"
    assert seen[:4] == [
        ("enabled", True, {"session_end_epoch": 5}),
        ("enabled", False, {}),
        "settle",
        "status",
    ]


def test_the_lambda_entrypoint_is_sanitized_and_lives_where_the_template_says():
    from processing import handlers

    assert template()["Parameters"]["ProcessingLauncherHandler"]["Default"].endswith(
        "handlers.launcher_handler"
    )
    assert handlers.launcher_handler.__wrapped__.__name__ == "launcher_handler"


# --- CLI -----------------------------------------------------------------------------------------

SCOPE = ("--profile", "operator", "--region", "ap-southeast-1", "--account", "123456789012")


def operator_config(tmp_path, stack_outputs):
    directory = tmp_path / "ops"
    directory.mkdir(mode=0o700, exist_ok=True)
    (directory / "outputs.json").write_text(json.dumps(stack_outputs))
    config = {
        "operator_station": "s",
        "environment_id": "e2e",
        "journal": str(directory / "session.json"),
        "outputs_file": str(directory / "outputs.json"),
    }
    (directory / "config.json").write_text(json.dumps(config))
    return str(directory / "config.json")


def cli(*argv):
    import io

    from scripts.aws.v1.session_cli import main

    out = io.StringIO()
    code = main(list(argv), stdout=out)
    return code, json.loads(out.getvalue())


def launcher_calls(out):
    return [
        c
        for c in out["planned_calls"]
        if c["payload"].get("FunctionName") == FUNCTION or c["payload"].get("Name") == RULE
    ]


def test_dry_run_open_unattended_plans_the_flag_then_the_rule(tmp_path):
    config = operator_config(tmp_path, launcher_outputs())
    code, out = cli("open", "--config", config, *SCOPE, "--dry-run", "--unattended")
    assert code == 0
    steps = [
        c["payload"]["Payload"]["action"] if c["operation"] == "invoke" else c["operation"]
        for c in launcher_calls(out)
    ]
    assert steps[0] == "enable" and "enable-rule" in steps


def test_open_unattended_on_a_stack_without_the_launcher_is_refused_before_any_call(tmp_path):
    config = operator_config(tmp_path, outputs())
    code, out = cli("open", "--config", config, *SCOPE, "--dry-run", "--unattended")
    assert code == 1 and "UnattendedLaunch" in out["error"]


def test_a_plain_dry_run_open_never_touches_the_launcher(tmp_path):
    config = operator_config(tmp_path, launcher_outputs())
    code, out = cli("open", "--config", config, *SCOPE, "--dry-run")
    assert code == 0 and not launcher_calls(out)


def test_unattended_is_an_open_only_flag(tmp_path):
    config = operator_config(tmp_path, launcher_outputs())
    with pytest.raises(SystemExit):
        cli("close", "--config", config, *SCOPE, "--dry-run", "--unattended")
