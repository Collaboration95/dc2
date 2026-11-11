"""Tick control flow with offline ports; reservation SQL has its own integration suite."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from processing import launcher


@pytest.fixture
def tick_ports(monkeypatch):
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(enabled=True)
    session.execute.return_value = Mock(all=Mock(return_value=[]))
    context = AsyncMock()
    context.__aenter__.return_value = session
    backlog = AsyncMock(return_value=3)
    observation = launcher.Observation({}, set())
    observe = AsyncMock(return_value=observation)
    reserve = AsyncMock(return_value={"tokens": [], "backlog": 3, "ambiguous": 0})
    send = AsyncMock(return_value="launched")
    for name, double in (
        ("queued_backlog", backlog),
        ("observe", observe),
        ("_reserve", reserve),
        ("_send", send),
    ):
        monkeypatch.setattr(launcher, name, double)
    queue = AsyncMock()
    queue.visible.return_value = 3
    return SimpleNamespace(
        factory=Mock(return_value=context),
        session=session,
        backlog=backlog,
        observation=observation,
        observe=observe,
        reserve=reserve,
        send=send,
        ecs=AsyncMock(),
        queue=queue,
        config=launcher.LauncherConfig("cluster", "worker:1", ("subnet",), ("sg",)),
    )


async def run_tick(ports, **kwargs):
    return await launcher.tick(ports.factory, ports.ecs, ports.queue, ports.config, **kwargs)


@pytest.mark.parametrize("idle_reason", ["no_backlog", "disabled", "no_control", "settling"])
async def test_idle_performs_no_ecs_or_queue_io(tick_ports, idle_reason):
    ports = tick_ports
    if idle_reason == "no_backlog":
        ports.backlog.return_value = 0
    elif idle_reason == "disabled":
        ports.session.get.return_value.enabled = False
    elif idle_reason == "no_control":
        ports.session.get.return_value = None

    result = await run_tick(ports, launching=idle_reason != "settling")

    assert result == {
        "outcome": "idle",
        "launched": 0,
        "backlog": ports.backlog.return_value,
        "ambiguous": 0,
    }
    ports.observe.assert_not_awaited()
    ports.reserve.assert_not_awaited()
    ports.send.assert_not_awaited()
    assert ports.ecs.mock_calls == []
    assert ports.queue.mock_calls == []


async def test_unreadable_queue_passes_unknown_demand_to_reservation(tick_ports):
    ports = tick_ports
    ports.queue.visible.side_effect = TimeoutError("queue unavailable")

    result = await run_tick(ports)

    ports.queue.visible.assert_awaited_once_with()
    ports.reserve.assert_awaited_once_with(
        ports.factory, ports.config, ports.observation, None, launching=True
    )
    ports.send.assert_not_awaited()
    assert result["outcome"] == "ran"
    assert result["launched"] == 0


@pytest.mark.parametrize("outcome", ["refused", "ambiguous"])
@pytest.mark.parametrize("already_launched", [0, 1])
async def test_unhealthy_send_stops_the_pass(tick_ports, outcome, already_launched):
    ports = tick_ports
    ports.reserve.return_value["tokens"] = ["first", "second", "third"]
    ports.send.side_effect = ["launched"] * already_launched + [outcome, "launched", "launched"]

    result = await run_tick(ports)

    assert ports.send.await_args_list == [
        call(ports.factory, ports.ecs, token, ports.config)
        for token in ["first", "second"][: already_launched + 1]
    ]
    assert result == {
        "outcome": "ran",
        "backlog": 3,
        "ambiguous": 0,
        "launched": already_launched,
        "refused": int(outcome == "refused"),
        "unconfirmed": int(outcome == "ambiguous"),
        "closed": 0,
        "skipped": 0,
    }


async def test_healthy_pass_sends_each_reserved_token_and_counts_results(tick_ports):
    ports = tick_ports
    ports.reserve.return_value["tokens"] = ["first", "second", "third"]
    ports.send.side_effect = ["launched", "skipped", "closed"]

    result = await run_tick(ports)

    ports.observe.assert_awaited_once_with(ports.ecs, ports.config, [])
    ports.reserve.assert_awaited_once_with(
        ports.factory, ports.config, ports.observation, 3, launching=True
    )
    assert ports.send.await_args_list == [
        call(ports.factory, ports.ecs, token, ports.config)
        for token in ("first", "second", "third")
    ]
    assert result == {
        "outcome": "ran",
        "backlog": 3,
        "ambiguous": 0,
        "launched": 1,
        "refused": 0,
        "unconfirmed": 0,
        "closed": 1,
        "skipped": 1,
    }


@pytest.mark.parametrize("launching", [False, True])
async def test_open_reservations_reconcile_without_queue_demand(tick_ports, launching):
    ports = tick_ports
    ports.session.get.return_value.enabled = False
    ports.session.execute.return_value.all.return_value = [("known-task",), (None,)]

    result = await run_tick(ports, launching=launching)

    ports.observe.assert_awaited_once_with(ports.ecs, ports.config, ["known-task"])
    ports.reserve.assert_awaited_once_with(
        ports.factory, ports.config, ports.observation, None, launching=launching
    )
    ports.queue.visible.assert_not_awaited()
    assert result["outcome"] == "ran"
