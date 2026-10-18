"""V2-live (#237): a work send wakes the encoder launcher at once, as a best-effort hint."""

import pytest

from processing import launcher_trigger


class Transport:
    def __init__(self):
        self.sent = []

    async def send(self, queue, envelope):
        self.sent.append(queue)
        return {"MessageId": "m"}

    def close(self):
        return "closed"


def recording():
    calls = []
    return calls, calls.append


async def test_the_first_work_send_wakes_the_launcher_once_per_invocation():
    calls, invoke = recording()
    transport = launcher_trigger.WakeOnWork(Transport(), "arn:launcher:live", invoke=invoke)
    await transport.send("media-results", {})
    assert calls == []  # results are not work
    for _ in range(3):
        assert await transport.send("processing-work", {}) == {"MessageId": "m"}
    assert calls == ["arn:launcher:live"]
    assert transport.transport.sent == ["media-results"] + ["processing-work"] * 3


async def test_a_failed_wake_never_fails_the_send_it_follows():
    def broken(_function):
        raise TimeoutError("lambda endpoint unreachable")

    transport = launcher_trigger.WakeOnWork(Transport(), "arn:launcher:live", invoke=broken)
    assert await transport.send("processing-work", {}) == {"MessageId": "m"}


async def test_a_failed_send_does_not_wake_the_launcher():
    calls, invoke = recording()

    class Down(Transport):
        async def send(self, queue, envelope):
            raise ConnectionError("SQS unavailable")

    transport = launcher_trigger.WakeOnWork(Down(), "arn:launcher:live", invoke=invoke)
    with pytest.raises(ConnectionError):
        await transport.send("processing-work", {})
    assert calls == []


def test_without_a_deployed_launcher_the_transport_is_left_alone():
    plain = Transport()
    assert launcher_trigger.wrap(plain, {}) is plain
    wrapped = launcher_trigger.wrap(plain, {"PROCESSING_LAUNCHER_FUNCTION": "arn:l"})
    assert wrapped.function == "arn:l" and wrapped.close() == "closed"


def test_the_wake_is_an_asynchronous_invoke_of_a_launcher_action(monkeypatch):
    seen = {}

    class Client:
        def invoke(self, **kwargs):
            seen.update(kwargs)

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Client())
    launcher_trigger.invoke_async("arn:launcher:live")
    assert seen["InvocationType"] == "Event" and seen["FunctionName"] == "arn:launcher:live"
    assert seen["Payload"] == b'{"dc2_operation": "launcher", "action": "wake"}'
