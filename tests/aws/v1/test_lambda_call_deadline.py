"""The proof harness gives a Lambda call enough deadline for the transport's 70 s allowance.

r1018b: the first live isolation run failed in one second with "Insufficient request deadline"
because the mapping calls asked for 60 s and the production Lambda client reserves 70 s.
"""

import time
from types import SimpleNamespace

from scripts.aws.v1.proof import isolation
from scripts.aws.v1.proof.context import LAMBDA_CALL_SECONDS
from scripts.aws.v1.transport import OperatorTransport

ACCOUNT = "123456789012"
UUID = "11111111-2222-3333-4444-555555555555"


def production_shaped_transport(calls):
    # Same timeouts and budget as scripts.aws.v1.operations builds for the real account.
    config = SimpleNamespace(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=65)
    meta = SimpleNamespace(region_name="ap-southeast-1", config=config)

    def get_event_source_mapping(**arguments):
        calls.append(arguments)
        return {"State": "Enabled"}

    client = SimpleNamespace(meta=meta, get_event_source_mapping=get_event_source_mapping)
    return OperatorTransport(
        {"lambda": client},
        identity={"Account": ACCOUNT},
        account=ACCOUNT,
        region="ap-southeast-1",
        budgets={"lambda": 70},
    )


def test_a_mapping_read_is_not_refused_for_want_of_deadline():
    calls = []
    ctx = SimpleNamespace(deadline=lambda seconds: time.monotonic() + seconds)
    transport = production_shaped_transport(calls)
    assert isolation.mapping_state(ctx, transport, UUID) == "Enabled"
    assert calls == [{"UUID": UUID}]


def test_the_lambda_call_deadline_exceeds_the_transport_allowance():
    assert LAMBDA_CALL_SECONDS > 70
