"""Cloud-only process watchdog; includes startup and Redis's unlimited retry loop."""

import json
import os
import signal
import subprocess
import sys

from processing.worker.watchdog import supervise


def finite_worker_class(warm_fd):
    from rq import Worker

    class FiniteWorker(Worker):
        _warm_requested = False

        def execute_job(self, job, queue):
            # SQL attempt IDs equal RQ job IDs. Retain every claim for this finite
            # worker before execution, including the last/racing claim at shutdown.
            claims = json.loads(self.connection.hget(self.key, "dc2_claims") or b"[]")
            if job.id not in claims:
                if len(claims) >= 64:
                    raise RuntimeError("Finite worker claim observation bound exceeded")
                claims.append(job.id)
                self.connection.hset(self.key, "dc2_claims", json.dumps(claims))
            return super().execute_job(job, queue)

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
                try:
                    seconds, micros = self.connection.time()
                    self.connection.hset(self.key, "dc2_warm_ack", str(seconds + micros / 1e6))
                except Exception:
                    pass  # No positive Redis receipt means drain must fail closed.
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
        "legacy.processing_rq.worker",
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
