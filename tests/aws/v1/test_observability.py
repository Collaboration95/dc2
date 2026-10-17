"""Per-service alarms, the services dashboard and the narrowed Lambda environments (#200).

Offline: these prove what the generated template declares. That CloudWatch evaluates the
alarms and draws the dashboard is shown live (#186), with a screenshot for the report.
"""

import json
import re

import pytest

from scripts.aws.v1.definitions import LAUNCHER, SHORT_ENCODER, SHORT_QUEUE, template

BUILT = template()
RESOURCES = BUILT["Resources"]
FUNCTIONS = {k: v for k, v in RESOURCES.items() if v["Type"] == "AWS::Lambda::Function"}
ALARMS = {k: v for k, v in RESOURCES.items() if v["Type"] == "AWS::CloudWatch::Alarm"}
DASHBOARD = RESOURCES["ServicesDashboard"]
DLQS = {k.removesuffix("Dlq") for k, v in RESOURCES.items() if k.endswith("Dlq")}
MEDIA = {name for name in FUNCTIONS if name.startswith("Media")}
PROCESSING = set(FUNCTIONS) - MEDIA
QUEUE_VARIABLES = {
    "PROCESSING_COMMANDS_QUEUE_URL": "ProcessingCommands",
    "PROCESSING_WORK_QUEUE_URL": "ProcessingWork",
    "MEDIA_RESULTS_QUEUE_URL": "MediaResults",
}


def properties(name):
    return RESOURCES[name]["Properties"]


def dimension(alarm):
    (found,) = properties(alarm)["Dimensions"]
    return found


# --- Dead-letter queue alarms: one per DLQ, owned by the consuming service -----------------


def test_every_dead_letter_queue_has_an_alarm_that_fires_on_any_visible_message():
    assert DLQS == {"ProcessingCommands", "ProcessingWork", "MediaResults", SHORT_QUEUE}
    for queue in DLQS:
        alarm = properties(f"{queue}DlqAlarm")
        assert alarm["Namespace"] == "AWS/SQS"
        assert alarm["MetricName"] == "ApproximateNumberOfMessagesVisible"
        assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
        assert alarm["Threshold"] == 0
        assert alarm["Statistic"] == "Maximum"
        assert dimension(f"{queue}DlqAlarm") == {
            "Name": "QueueName",
            "Value": {"Fn::GetAtt": [f"{queue}Dlq", "QueueName"]},
        }
        # An idle queue publishes nothing; that is healthy, not missing data.
        assert alarm["TreatMissingData"] == "notBreaching"


def test_a_dead_letter_alarm_is_tagged_with_and_describes_the_service_that_owns_it():
    owners = {"MediaResults": "media"}
    for queue in DLQS:
        alarm = properties(f"{queue}DlqAlarm")
        owner = owners.get(queue, "processing")
        assert {"Key": "Service", "Value": owner} in alarm["Tags"]
        assert alarm["AlarmDescription"].startswith(owner.title() + ":")


def test_the_short_lane_alarm_exists_only_with_its_queue():
    for queue in DLQS:
        gate = RESOURCES[f"{queue}Dlq"].get("Condition")
        assert RESOURCES[f"{queue}DlqAlarm"].get("Condition") == gate
    assert RESOURCES[f"{SHORT_QUEUE}DlqAlarm"]["Condition"] == "ShortEncodes"
    assert "Condition" not in RESOURCES["MediaResultsDlqAlarm"]


# --- Lambda error alarms: one per function, in the function's own condition -----------------


def test_every_function_of_every_service_has_an_errors_alarm_on_its_own_metric():
    assert {f"{name}ErrorsAlarm" for name in FUNCTIONS} <= set(ALARMS)
    assert MEDIA == {"MediaApi", "MediaAuthorizer", "MediaResults", "MediaRepair"}
    for name in FUNCTIONS:
        alarm = properties(f"{name}ErrorsAlarm")
        assert (alarm["Namespace"], alarm["MetricName"]) == ("AWS/Lambda", "Errors")
        assert alarm["Statistic"] == "Sum" and alarm["Threshold"] == 0
        assert alarm["ComparisonOperator"] == "GreaterThanThreshold"
        # The bare function name aggregates every version and alias the traffic arrives on.
        assert dimension(f"{name}ErrorsAlarm") == {"Name": "FunctionName", "Value": {"Ref": name}}
        owner = "media" if name in MEDIA else "processing"
        assert {"Key": "Service", "Value": owner} in alarm["Tags"]
        assert RESOURCES[f"{name}ErrorsAlarm"].get("Condition") == FUNCTIONS[name].get("Condition")


def test_the_optional_functions_alarm_only_when_they_exist():
    assert RESOURCES[f"{LAUNCHER}ErrorsAlarm"]["Condition"] == "Unattended"
    assert RESOURCES[f"{SHORT_ENCODER}ErrorsAlarm"]["Condition"] == "ShortEncodes"
    assert RESOURCES["MediaApiErrorsAlarm"]["Condition"] == "Applications"


def test_alarms_page_nobody_and_are_deleted_with_the_stack():
    assert not [k for k, v in RESOURCES.items() if v["Type"].startswith("AWS::SNS::")]
    for name, resource in {**ALARMS, "ServicesDashboard": DASHBOARD}.items():
        assert "DeletionPolicy" not in resource, name
        for hook in ("AlarmActions", "OKActions", "InsufficientDataActions"):
            assert hook not in resource["Properties"], name


def test_teardown_has_nothing_to_clean_up_beyond_deleting_the_stack():
    from scripts.aws.v1 import deploy

    types = {resource["Type"] for resource in (*ALARMS.values(), DASHBOARD)}
    assert types == {"AWS::CloudWatch::Alarm", "AWS::CloudWatch::Dashboard"}
    # Neither is stateful (a change set that replaces one is not blocked) and neither is a
    # kind teardown tracks for explicit deletion, as a log group's retention is.
    assert not types & deploy.STATEFUL


def test_the_default_application_stack_adds_a_dozen_alarms_a_few_cents_for_a_session():
    def alarms(*enabled):
        return {
            k for k, v in ALARMS.items() if v.get("Condition") in (None, "Applications", *enabled)
        }

    default = alarms()
    # Standard-resolution alarms bill about $0.10 per alarm-month, pro-rated by the hour. The
    # first three dashboards (up to 50 metrics each) are free. The cost model needs no line.
    assert len(default) == 12
    assert len(alarms("Unattended", "ShortEncodes")) == 15


# --- The dashboard: a section per service ---------------------------------------------------


def dashboard():
    body = DASHBOARD["Properties"]["DashboardBody"]["Fn::Sub"]
    return json.loads(body), body


def sections():
    widgets, _ = dashboard()
    texts = [w for w in widgets["widgets"] if w["type"] == "text"]
    ranges, ordered = {}, sorted(widgets["widgets"], key=lambda w: (w["y"], w["x"]))
    for text in texts:
        ranges[text["properties"]["markdown"].lstrip("# ")] = text["y"]
    names = list(ranges)
    result = {}
    for index, name in enumerate(names):
        top = ranges[name]
        bottom = ranges[names[index + 1]] if index + 1 < len(names) else float("inf")
        result[name] = [w for w in ordered if w["type"] == "metric" and top <= w["y"] < bottom]
    return result


def test_the_dashboard_has_one_section_per_service():
    assert list(sections()) == ["Media Management", "Processing"]
    assert DASHBOARD["Condition"] == "Applications"
    assert DASHBOARD["Properties"]["DashboardName"] == {"Fn::Sub": "${EnvironmentId}-v1-services"}


@pytest.mark.parametrize(
    ("section", "functions", "queues"),
    [
        ("Media Management", MEDIA, {"MediaResults"}),
        (
            "Processing",
            PROCESSING - {LAUNCHER, SHORT_ENCODER},
            {"ProcessingCommands", "ProcessingWork"},
        ),
    ],
)
def test_each_section_shows_its_functions_and_queues_with_the_agreed_panels(
    section, functions, queues
):
    widgets = sections()[section]
    by_title = {w["properties"]["title"].split(": ", 1)[1]: w["properties"] for w in widgets}
    for title, metric, stat in (
        ("Invocations", "Invocations", "Sum"),
        ("Errors", "Errors", "Sum"),
        ("Duration p90 (ms)", "Duration", "p90"),
    ):
        panel = by_title[title]
        assert panel["stat"] == stat
        assert {m[1] for m in panel["metrics"]} == {metric}
        assert {m[3] for m in panel["metrics"]} == {f"${{{f}}}" for f in functions}
    depth = by_title["Queue depth"]
    assert {m[1] for m in depth["metrics"]} == {"ApproximateNumberOfMessagesVisible"}
    assert {m[3] for m in depth["metrics"]} == {f"${{{q}Queue.QueueName}}" for q in queues}
    assert {m[1] for m in by_title["Oldest message age (s)"]["metrics"]} == {
        "ApproximateAgeOfOldestMessage"
    }
    dead = by_title["Dead-letter depth (alarm above 0)"]
    assert {m[3] for m in dead["metrics"]} == {f"${{{q}Dlq.QueueName}}" for q in queues}


def test_only_processing_shows_running_encoders_through_the_work_queue_in_flight():
    processing = {w["properties"]["title"].split(": ", 1)[1]: w for w in sections()["Processing"]}
    inflight = processing["Encodes in flight (running encoders)"]["properties"]["metrics"]
    assert [m[1:4] for m in inflight] == [
        ["ApproximateNumberOfMessagesNotVisible", "QueueName", "${ProcessingWorkQueue.QueueName}"]
    ]
    media = {w["properties"]["title"] for w in sections()["Media Management"]}
    assert not [title for title in media if "encoder" in title.lower()]
    # Container Insights stays off, so there is no ECS running-task metric to chart instead.
    cluster = RESOURCES["Cluster"]["Properties"]["ClusterSettings"]
    assert {"Name": "containerInsights", "Value": "disabled"} in cluster


def test_every_name_the_dashboard_substitutes_is_a_resource_that_exists_whenever_it_does():
    _, body = dashboard()
    names = set(re.findall(r"\$\{([A-Za-z0-9:]+)(?:\.QueueName)?\}", body))
    names.discard("AWS::Region")
    assert names
    for name in names:
        assert name in RESOURCES, name
        # The dashboard exists under Applications; nothing it points at may need more.
        assert RESOURCES[name].get("Condition") in (None, "Applications"), name
    assert DASHBOARD["Condition"] == "Applications"


def test_the_dashboard_widgets_fit_the_24_column_grid():
    widgets, _ = dashboard()
    for widget in widgets["widgets"]:
        assert widget["x"] + widget["width"] <= 24
    assert len(widgets["widgets"]) <= 500


# --- Least-privilege environment: only the queue URLs a function calls ----------------------


def queue_environment(name):
    variables = FUNCTIONS[name]["Properties"]["Environment"]["Variables"]
    return {QUEUE_VARIABLES[v]: variables[v] for v in QUEUE_VARIABLES if v in variables}


def granted_queues(name, verbs):
    role = RESOURCES[f"{name}Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    found = set()
    for statement in role:
        if verbs & set(statement["Action"]):
            resource = statement["Resource"]
            found |= {
                r["Fn::GetAtt"][0].removesuffix("Queue")
                for r in (resource if isinstance(resource, list) else [resource])
                if isinstance(r, dict) and r.get("Fn::GetAtt", [""])[0].endswith("Queue")
            }
    return found - {SHORT_QUEUE}


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_a_function_gets_the_url_of_exactly_the_queues_it_may_send_to_or_inspect(name):
    given = queue_environment(name)
    # Consuming needs no URL (the event source mapping delivers the batch), so a queue the role
    # only receives from is not named. Reading a depth without receiving does need the URL.
    sends = granted_queues(name, {"sqs:SendMessage"})
    inspects = granted_queues(name, {"sqs:GetQueueAttributes"})
    allowed = sends | (inspects - granted_queues(name, {"sqs:ReceiveMessage"}))
    assert set(given) == allowed, name
    for queue, value in given.items():
        assert value == {"Ref": f"{queue}Queue"}


def test_the_environments_are_what_each_service_actually_calls():
    environments = {name: set(queue_environment(name)) for name in FUNCTIONS}
    assert environments["MediaRepair"] == {"ProcessingCommands"}
    for name in (
        "ProcessingCommands",
        "ProcessingRepair",
        "ProcessingEcsEvents",
        "ProcessingS3Events",
    ):
        assert environments[name] == {"ProcessingWork", "MediaResults"}
    assert environments[LAUNCHER] == {"ProcessingWork"}
    for name in ("MediaApi", "MediaAuthorizer", "MediaResults", "ProcessingApi", SHORT_ENCODER):
        assert environments[name] == set(), name
    # Media can reach no queue but the one it publishes to; Processing none of Media's input.
    assert all(q == "ProcessingCommands" for n in MEDIA for q in environments[n])
    assert not any("ProcessingCommands" in environments[n] for n in PROCESSING)


def test_no_function_is_handed_all_three_queues():
    assert not [n for n in FUNCTIONS if len(queue_environment(n)) == 3]


def test_the_encoder_task_is_told_its_work_queue_and_no_other_task_is_told_any_queue():
    # r1018a: the narrowed environments dropped the URL the encoder reads, and its first task
    # exited with "missing setting: PROCESSING_WORK_QUEUE_URL".
    tasks = {k: v for k, v in RESOURCES.items() if v["Type"] == "AWS::ECS::TaskDefinition"}
    seen = {
        name: {
            e["Name"]: e["Value"]
            for e in properties(name)["ContainerDefinitions"][0].get("Environment", [])
            if e["Name"].endswith("_QUEUE_URL")
        }
        for name in tasks
    }
    assert seen["WorkerTaskDefinition"] == {
        "PROCESSING_WORK_QUEUE_URL": {"Ref": "ProcessingWorkQueue"}
    }
    assert all(not urls for name, urls in seen.items() if name != "WorkerTaskDefinition")
