import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.local_bindings import LocalBindings
from scripts.aws.protocols import capacity
from scripts.aws.smoke import Ledger
from scripts.aws.transport import OperationError


def test_concrete_capacity_drain_receipts_compose_across_all_three_batches(config, fake, journal):
    binding = LocalBindings.__new__(LocalBindings)
    binding.config, binding.transport, binding.journal = config, fake, journal
    config["session_end_epoch"] = time.time() + 1000

    def warm(task, name, **kw):
        fake.tasks[task]["lastStatus"] = "STOPPED"
        return True

    binding.data = SimpleNamespace(
        observe_worker=lambda *a, **kw: {
            "fresh": True,
            "claims_stopped": True,
            "claims": [],
            "outcomes": {},
        },
        warm_shutdown=warm,
    )
    binding.submit = lambda fixture, **kw: fixture["id"]
    binding.wait_jobs = lambda jobs, **kw: [{"id": j, "status": "succeeded"} for j in jobs]
    batches = capacity(
        binding,
        [{"id": str(n), "payload": b"offline"} for n in range(6)],
        Ledger(),
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    assert [b["count"] for b in batches] == [1, 2, 3]
    assert len([c for c in fake.calls if c[1] == "run-task"]) == 6
    # A missing describe for a launch never seen STOPPED is uncertainty, never a complete
    # empty receipt. (One the journal already saw STOPPED may vanish: ECS forgets it.)
    del fake.tasks[next(iter(fake.tasks))]
    with journal.locked() as state:
        record = next(iter(state["launches"].values()))
        record["status"] = "acknowledged"
        journal.save(state)
        fake.tasks.pop(record["task"], None)
    with pytest.raises(OperationError):
        binding.drain(deadline=time.monotonic() + 30)
