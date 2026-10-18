"""V2-live: releases on the always-on environment keep it serving (online mode)."""

import time

import pytest
from v1_support import outputs

from processing.launcher import LauncherConfig, effective
from scripts.aws.transport import OperationError
from scripts.aws.v1 import release_cli
from scripts.aws.v1.definitions import LAUNCHER
from scripts.aws.v1.hooks import RELEASE_CAP, owner_online
from scripts.aws.v1.operations import PlanTransport, config_from_outputs

OUTPUTS = outputs() | {f"{LAUNCHER}FunctionName": "fn-launcher",
                       f"{LAUNCHER}RuleName": "rule-launcher"}


def environment(*, enabled=True):
    config, _, _ = config_from_outputs(OUTPUTS, station="s", environment="dc2-live")
    state = ("Enabled", "ENABLED") if enabled else ("Disabled", "DISABLED")
    mappings = {m: state[0] for c in config["owner_consumers"].values() for m in c["mappings"]}
    rules = {r: state[1] for c in config["owner_consumers"].values() for r in c["schedules"]}
    return config, PlanTransport(mappings=mappings, rules=rules)


def encoder(transport, name, cpu="2048", status="RUNNING"):
    transport.tasks[name] = {"taskArn": name, "taskDefinitionArn": "arn:td/dc2-live-worker:1",
                             "lastStatus": status, "cpu": cpu}


def deadline(seconds=600):
    return time.monotonic() + seconds


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_an_open_environment_with_room_for_one_more_task_is_ready_for_an_online_release(owner):
    config, transport = environment()
    encoder(transport, "a")
    encoder(transport, "b")
    assert owner_online(config, transport, sleep=lambda _s: None)(owner, deadline=deadline())


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_a_kill_switch_that_is_on_refuses_an_online_release_instead_of_undoing_it(owner):
    config, transport = environment(enabled=False)
    assert owner_online(config, transport)(owner, deadline=deadline()) is False


def test_the_launcher_rule_counts_among_processing_consumers():
    config, transport = environment()
    transport.rules["rule-launcher"] = "DISABLED"
    assert owner_online(config, transport)("processing", deadline=deadline()) is False
    assert owner_online(config, transport)("media", deadline=deadline()) is True


def test_three_running_encoders_are_waited_out_for_the_release_tasks_headroom():
    config, transport = environment()
    for name in ("a", "b", "c"):  # 6 vCPU: the whole Fargate quota
        encoder(transport, name)
    waits = []

    def finish_one(_seconds):
        waits.append(1)
        transport.tasks["c"]["lastStatus"] = "STOPPED"

    assert owner_online(config, transport, sleep=finish_one)("media", deadline=deadline())
    assert waits == [1]


def test_headroom_that_never_frees_fails_within_the_deadline():
    config, transport = environment()
    for name in ("a", "b", "c"):
        encoder(transport, name)
    ready = owner_online(config, transport, sleep=time.sleep, poll_seconds=0.05)
    try:
        assert ready("processing", deadline=deadline(0.3)) is False
    except OperationError:
        pass  # the deadline ran out inside a read: refused all the same


class Launcher:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def release_controls(self, *, deadline, **fields):
        self.calls.append(fields)
        return not (set(fields) & self.fail)


def test_an_online_promotion_caps_the_launcher_then_points_it_at_the_released_worker():
    launcher = Launcher()
    result = release_cli.online(launcher, lambda: {"status": "promoted"},
                                worker_of=lambda _r: "arn:td/dc2-live-worker:7")
    assert result == {"status": "promoted"}
    assert launcher.calls == [{"cap_limit": RELEASE_CAP},
                              {"worker_definition": "arn:td/dc2-live-worker:7"},
                              {"cap_limit": None}]


def test_a_failed_online_step_restores_the_cap_keeps_the_prior_worker_and_reports_its_error():
    launcher = Launcher()

    def fail():
        raise OperationError("Candidate public V1 smoke failed")

    with pytest.raises(OperationError, match="smoke failed"):
        release_cli.online(launcher, fail, worker_of=lambda _r: "arn:td/new:1")
    assert launcher.calls == [{"cap_limit": RELEASE_CAP}, {"cap_limit": None}]


def test_an_online_step_never_starts_without_a_confirmed_cap():
    ran = []
    with pytest.raises(OperationError, match="did not confirm"):
        release_cli.online(Launcher(fail={"cap_limit"}), lambda: ran.append(1),
                           worker_of=lambda _r: False)
    assert ran == []


def test_launcher_default_is_an_online_only_action(capsys):
    with pytest.raises(SystemExit):
        release_cli.main(["launcher-default", "--config", "x", "--profile", "p", "--region",
                          "ap-southeast-1", "--account", "123456789012"])
    assert "--online" in capsys.readouterr().err


# ---- the launcher honours the controls ------------------------------------------------
WORKER = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/dc2-live-worker:3"


class Control:
    def __init__(self, cap_limit=None, worker_definition=None):
        self.cap_limit, self.worker_definition = cap_limit, worker_definition


def test_a_release_cap_lowers_but_never_raises_the_launchers_cap():
    config = LauncherConfig(cluster="c", task_definition=WORKER, subnets=("s",),
                            security_groups=("g",))
    assert effective(config, Control(cap_limit=2)).slots == 2
    assert effective(config, Control(cap_limit=9)).slots == 3
    assert effective(config, None) is config


def test_only_a_worker_of_the_stacks_own_family_can_be_selected():
    config = LauncherConfig(cluster="c", task_definition=WORKER, subnets=("s",),
                            security_groups=("g",))
    released = WORKER.replace(":3", ":8")
    assert effective(config, Control(worker_definition=released)).task_definition == released
    foreign = WORKER.replace("dc2-live-worker", "other-family")
    assert effective(config, Control(worker_definition=foreign)).task_definition == WORKER
