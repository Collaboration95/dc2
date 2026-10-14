"""Cloud-only process watchdog; includes startup and Redis's unlimited retry loop."""

import math
import os
import signal
import subprocess
import sys
import time


def supervise(
    command,
    *,
    end_epoch,
    popen=subprocess.Popen,
    clock=time.time,
    sleep=time.sleep,
    kill_group=os.killpg,
    install_signals=True,
    warm_notification=None,
    monotonic=time.monotonic,
):
    if not math.isfinite(end_epoch) or end_epoch <= clock() or end_epoch > clock() + 3600:
        return 124
    budget = end_epoch - clock()
    mono_end = monotonic() + budget
    # RQ handles one SIGTERM as warm shutdown; its horse shares this session.
    # The existing FFmpeg supervisor owns separate encoder process groups. The
    # cloud wrapper must be the essential container command so container exit
    # also collects remaining encoder descendants; real ECS proof stays future.
    process = popen(command, start_new_session=True)
    reap_reserve = min(5, budget / 4)
    warm_budget = min(300, budget / 4)
    warm_at = end_epoch - reap_reserve - warm_budget
    mono_warm_at = mono_end - reap_reserve - warm_budget
    stop_by = end_epoch
    mono_stop_by = mono_end
    warm_sent = False
    interrupted = False

    def warm(signum=None, frame=None):
        nonlocal warm_sent, interrupted, stop_by, mono_stop_by
        if signum is not None:
            interrupted = True
            mono_stop_by = min(mono_stop_by, monotonic() + 110)
            stop_by = min(stop_by, clock() + 110)  # Fargate stopTimeout <=120s.
        if not warm_sent:
            warm_sent = True
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    previous = {}
    if install_signals:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, warm)
    try:
        while True:
            if warm_notification is not None and warm_notification():
                warm_sent = True
            result = process.poll()
            if result is not None:
                return result if not interrupted else 128 + signal.SIGTERM
            now = clock()
            if now >= warm_at or monotonic() >= mono_warm_at:
                interrupted = True
                warm()
            if now >= stop_by - reap_reserve or monotonic() >= mono_stop_by - reap_reserve:
                try:
                    kill_group(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(
                        timeout=max(
                            0, min(reap_reserve, stop_by - clock(), mono_stop_by - monotonic())
                        )
                    )
                except subprocess.TimeoutExpired:
                    pass
                return 124
            sleep(
                min(
                    0.2,
                    max(0, stop_by - reap_reserve - now),
                    max(0, mono_stop_by - reap_reserve - monotonic()),
                )
            )
    finally:
        if install_signals:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def finite_worker_class(warm_fd):
    from rq import Worker

    class FiniteWorker(Worker):
        _warm_requested = False

        def request_force_stop(self, signum, frame):
            # RQ may install this handler during its first signal callback.
            return self.request_stop(signum, frame)

        def request_stop(self, signum, frame):
            if self._warm_requested:
                return
            self._warm_requested = True
            try:
                os.write(warm_fd, b"w")
            except OSError:
                pass  # Parent watchdog still forces at the absolute deadline.
            try:
                super().request_stop(signum, frame)
            finally:
                # RQ installs a cold second-signal handler. Cloud shutdown must
                # remain warm exactly once; only the parent deadline forces exit.
                signal.signal(signal.SIGINT, self.request_stop)
                signal.signal(signal.SIGTERM, self.request_stop)

    return FiniteWorker


def run(end_epoch, *, name, burst):
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    command = [
        sys.executable,
        "-m",
        "processing.worker",
        "--name",
        name,
        "--cloud-warm-fd",
        str(write_fd),
    ]
    if burst:
        command.append("--burst")

    def notification():
        try:
            return bool(os.read(read_fd, 1))
        except BlockingIOError:
            return False

    def spawn(command, **kwargs):
        return subprocess.Popen(command, pass_fds=(write_fd,), **kwargs)

    try:
        return supervise(command, end_epoch=end_epoch, popen=spawn, warm_notification=notification)
    finally:
        os.close(read_fd)
        os.close(write_fd)
