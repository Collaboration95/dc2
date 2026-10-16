"""Absolute process watchdog shared by finite worker entrypoints."""

import math
import os
import signal
import subprocess
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
    # The child handles one SIGTERM as warm shutdown.
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
