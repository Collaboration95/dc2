"""V2-live: releases on the always-on environment keep it serving (online mode)."""

import time

import pytest
from v1_support import outputs

from scripts.aws.v1.definitions import LAUNCHER
from scripts.aws.v1.hooks import owner_online
from scripts.aws.v1.operations import PlanTransport, config_from_outputs

OUTPUTS = outputs() | {f"{LAUNCHER}FunctionName": "fn-launcher",
                       f"{LAUNCHER}RuleName": "rule-launcher"}


def environment(*, enabled=True):
    config, _, _ = config_from_outputs(OUTPUTS, station="s", environment="dc2-live")
    state = ("Enabled", "ENABLED") if enabled else ("Disabled", "DISABLED")
    mappings = {m: state[0] for c in config["owner_consumers"].values() for m in c["mappings"]}
    rules = {r: state[1] for c in config["owner_consumers"].values() for r in c["schedules"]}
    return config, PlanTransport(mappings=mappings, rules=rules)


def deadline():
    return time.monotonic() + 600


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_an_environment_running_as_recorded_open_is_ready_for_an_online_release(owner):
    config, transport = environment()
    # Three running encoders do not block it: the 30 vCPU quota has room for the migration.
    for name in ("a", "b", "c"):
        transport.tasks[name] = {"taskArn": name, "lastStatus": "RUNNING"}
    assert owner_online(config, transport)(owner, deadline=deadline()) is True


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_a_kill_switch_that_is_on_refuses_an_online_release_instead_of_undoing_it(owner):
    config, transport = environment(enabled=False)
    assert owner_online(config, transport)(owner, deadline=deadline()) is False


def test_the_launcher_rule_counts_among_processing_consumers():
    config, transport = environment()
    transport.rules["rule-launcher"] = "DISABLED"
    assert owner_online(config, transport)("processing", deadline=deadline()) is False
    assert owner_online(config, transport)("media", deadline=deadline()) is True


def test_online_promotes_only_by_flag_and_closed_releases_keep_quiescence(monkeypatch):
    from scripts.aws.v1 import release_cli

    args = type("Args", (), {"online": True, "owner": None, "migration_definition": None,
                             "smoke_url": None, "smoke_credentials": None,
                             "no_reserve": False})()
    data = {"sql": {"ca_file": "ca", "media_dsn_file": "m", "processing_dsn_file": "p"}}
    config, transport = environment()
    online, *_ = release_cli.hooks_for(config, data, transport, args, None)
    args.online = False
    closed, *_ = release_cli.hooks_for(config, data, transport, args, None)
    # Consumers on: online is ready, the closed release's quiescence is not.
    assert online["quiescent"]("media", deadline=deadline()) is True
    assert closed["quiescent"]("media", deadline=deadline()) is False
