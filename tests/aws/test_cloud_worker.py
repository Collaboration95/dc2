import signal

import pytest
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from processing.worker.cloud import supervise


class Process:
    pid = 99999

    def __init__(self, clock, done=None):
        self.clock, self.done = clock, done
        self.signals = []
        self.waited = False

    def poll(self):
        return 0 if self.done is not None and self.clock() >= self.done else None

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout):
        assert timeout <= 5
        self.waited = True
        return -9


@pytest.mark.parametrize("outage", ["redis-forever", "queue-forever", "operator-gone"])
def test_absolute_watchdog_bounded_despite_rq_retry(clock, outage):
    process = Process(clock)
    killed = []

    def popen(command, **kw):
        assert kw["start_new_session"] is True
        clock.now += 2  # startup counts in the deadline
        return process

    result = supervise(
        ["python"],
        end_epoch=110,
        popen=popen,
        clock=clock,
        sleep=clock.sleep,
        kill_group=lambda *a: killed.append(a),
        install_signals=False,
    )
    assert result == 124
    assert clock() <= 110
    assert process.signals == [signal.SIGTERM]
    assert killed == [(process.pid, signal.SIGKILL)]
    assert process.waited


def test_natural_burst_success_and_deadline_warm_exit_nonzero(clock):
    process = Process(clock, done=102)
    assert (
        supervise(
            ["python"],
            end_epoch=110,
            popen=lambda *a, **k: process,
            clock=clock,
            sleep=clock.sleep,
            install_signals=False,
        )
        == 0
    )
    process = Process(clock, done=109)
    assert (
        supervise(
            ["python"],
            end_epoch=110,
            popen=lambda *a, **k: process,
            clock=clock,
            sleep=clock.sleep,
            install_signals=False,
        )
        != 0
    )


@pytest.mark.parametrize("end", [float("inf"), float("nan"), 99, 4001])
def test_invalid_deadline_never_starts(end, clock):
    def forbidden(*a, **k):
        pytest.fail("expired/invalid cloud child started")

    assert (
        supervise(["python"], end_epoch=end, popen=forbidden, clock=clock, install_signals=False)
        == 124
    )


def test_repeated_signal_sends_only_one_warm_and_forces_before_120(clock, monkeypatch):
    handlers = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
    process = Process(clock)
    signalled = False

    def sleep(seconds):
        nonlocal signalled
        if not signalled:
            signalled = True
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        clock.sleep(seconds)

    assert (
        supervise(
            ["python"],
            end_epoch=1000,
            popen=lambda *a, **k: process,
            clock=clock,
            sleep=sleep,
            kill_group=lambda *a: None,
        )
        == 124
    )
    assert clock.now <= 210.2
    assert process.signals == [signal.SIGTERM]


def test_parent_never_repeats_rq_initiated_warm(clock):
    process = Process(clock)

    def notification():
        return True

    assert (
        supervise(
            ["python"],
            end_epoch=110,
            popen=lambda *a, **k: process,
            clock=clock,
            sleep=clock.sleep,
            install_signals=False,
            warm_notification=notification,
            kill_group=lambda *a: None,
        )
        == 124
    )
    assert process.signals == []


def test_rq_cold_second_handler_is_suppressed(monkeypatch):
    import os

    from rq import Worker

    from processing.worker.cloud import finite_worker_class

    read_fd, write_fd = os.pipe()
    called = []
    monkeypatch.setattr(Worker, "request_stop", lambda *a: called.append("warm"))
    monkeypatch.setattr(signal, "signal", lambda *a: None)
    try:
        cls = finite_worker_class(write_fd)
        worker = cls.__new__(cls)
        worker.request_stop(signal.SIGINT, None)
        worker.request_force_stop(signal.SIGTERM, None)
        worker.request_stop(signal.SIGINT, None)
        assert called == ["warm"]
        assert os.read(read_fd, 10) == b"w"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_local_constructor_original_signature(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from processing.worker import __main__ as entry

    worker = Mock()
    constructor = Mock(return_value=worker)
    target = SimpleNamespace(connection=object())
    monkeypatch.delenv("AWS_EXECUTION_ENV", raising=False)
    monkeypatch.delenv("PROCESSING_STORAGE_CREDENTIAL_MODE", raising=False)
    monkeypatch.setattr("rq.Worker", constructor)
    monkeypatch.setattr(entry, "get_settings", lambda: SimpleNamespace(require_worker=lambda: None))
    monkeypatch.setattr(entry, "get_queue", lambda: target)
    monkeypatch.setattr("sys.argv", ["processing.worker"])
    entry.main()
    constructor.assert_called_once_with([target], connection=target.connection)
    worker.work.assert_called_once_with(burst=False)


@pytest.mark.parametrize("indicator", ["PROCESSING_STORAGE_CREDENTIAL_MODE", "AWS_EXECUTION_ENV"])
def test_cloud_direct_unbounded_command_refused(monkeypatch, indicator):
    from processing.worker import __main__ as entry

    monkeypatch.setenv(
        indicator, "ecs" if indicator.startswith("PROCESSING") else "AWS_ECS_FARGATE"
    )
    monkeypatch.setattr("sys.argv", ["processing.worker"])
    monkeypatch.setattr(entry, "get_settings", lambda: pytest.fail("unbounded cloud settings used"))
    with pytest.raises(SystemExit) as result:
        entry.main()
    assert result.value.code == 2


def test_wall_clock_rollback_cannot_extend_lifetime(clock):
    process = Process(clock)

    def wall():
        return 100 if clock.now == 100 else 50

    assert (
        supervise(
            ["python"],
            end_epoch=110,
            popen=lambda *a, **k: process,
            clock=wall,
            monotonic=clock,
            sleep=clock.sleep,
            install_signals=False,
            kill_group=lambda *a: None,
        )
        == 124
    )
    assert clock.now <= 110.01
