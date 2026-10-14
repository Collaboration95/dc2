"""Opt-in, experiment-only aggregate timings; never capture SQL, parameters or URLs.

Mounted into API containers via PYTHONPATH, identically in both paired profiles.
Pool timing includes pre-ping/connection creation, not just semaphore contention.
SQL timing includes server execution and driver/network wait; pg_stat_activity
sampling separately identifies observed server wait categories.
"""

import json
import os
import threading
import time
from pathlib import Path


def install():
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import Pool

    lock = threading.Lock()
    bins = (0.1, 0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000)
    counters = {}
    original = Pool.connect

    def observe(name, seconds):
        ms = seconds * 1000
        with lock:
            value = counters.setdefault(
                name, {"count": 0, "sum_ms": 0, "max_ms": 0, "histogram": [0] * (len(bins) + 1)}
            )
            value["count"] += 1
            value["sum_ms"] += ms
            value["max_ms"] = max(value["max_ms"], ms)
            bucket = next((i for i, ceiling in enumerate(bins) if ms <= ceiling), len(bins))
            value["histogram"][bucket] += 1

    def connect(self):
        start = time.perf_counter()
        try:
            return original(self)
        finally:
            observe("pool_connect", time.perf_counter() - start)

    Pool.connect = connect

    @event.listens_for(Engine, "before_cursor_execute")
    def before(_connection, _cursor, _statement, _parameters, context, _many):
        context._experiment_started = time.perf_counter()

    @event.listens_for(Engine, "after_cursor_execute")
    def after(_connection, _cursor, _statement, _parameters, context, _many):
        observe("sql_execute", time.perf_counter() - context._experiment_started)

    @event.listens_for(Engine, "handle_error")
    def failed(context):
        started = getattr(context.execution_context, "_experiment_started", None)
        if started is not None:
            observe("sql_error", time.perf_counter() - started)

    def flush():
        target = Path(f"/tmp/dc2-experiment-timings-{os.getpid()}.json")
        while True:
            with lock:
                data = json.dumps(
                    {
                        "pid": os.getpid(),
                        "monotonic": time.monotonic(),
                        "histogram_upper_ms": bins,
                        "counters": counters,
                    }
                )
            temporary = target.with_suffix(".tmp")
            temporary.write_text(data)
            temporary.replace(target)
            time.sleep(2)

    threading.Thread(target=flush, name="experiment-timings", daemon=True).start()


if os.environ.get("DC2_EXPERIMENT_TIMINGS") == "1" and os.getpid() == 1:
    install()
