import asyncio

import pytest

from scripts.aws.latency import Cycle, hash_cost, percentile90, summarize

HASH = "$2b$12$" + "a" * 53


def sample(user, ms=100, **kw):
    return {"user": user, "elapsed_ms": ms, "status_code": 200, "phase": "timed", **kw}


def test_p90_and_failures_not_dropped():
    assert percentile90(list(range(1, 11))) == 9
    samples = [sample(u % 50) for u in range(100)]
    samples[-1].update(status_code=500, elapsed_ms=3000, error="request_failed")
    result = summarize(samples, users=50, duration_seconds=180, measurement="status")
    assert result["eligible"] and result["error_rate"] == 0.01 and result["status"] == "FAIL"
    assert result["sample_count"] == 100


@pytest.mark.parametrize("change", ["warmup", "missing_user", "wrong_duration", "slow"])
def test_status_ineligible_or_missed_target(change):
    samples = [sample(u) for u in range(50)]
    duration = 180
    if change == "warmup":
        samples[0]["phase"] = "warmup"
    elif change == "missing_user":
        samples.pop()
    elif change == "wrong_duration":
        duration = 179
    else:
        samples = [sample(u, 701) for u in range(50)]
    assert (
        summarize(samples, users=50, duration_seconds=duration, measurement="status")["status"]
        == "FAIL"
    )


def test_login_strict_target_hash_cost_and_invalid_samples():
    assert hash_cost(HASH) == 12
    with pytest.raises(ValueError):
        hash_cost("private-value")
    samples = [sample(u, 2000) for u in range(20)]
    assert (
        summarize(samples, users=20, duration_seconds=0, measurement="login", actual_hash_cost=12)[
            "status"
        ]
        == "FAIL"
    )
    assert not summarize(samples, users=20, duration_seconds=0, measurement="login")["eligible"]
    with pytest.raises(ValueError):
        percentile90([float("nan")])


async def test_one_bounded_serial_cycle_on_fake_clock_and_no_repeat(tmp_path):
    now = [0.0]
    order = []

    async def sleep(seconds):
        now[0] += seconds
        await asyncio.sleep(0)

    async def request(kind, user, *, deadline):
        order.append(kind)
        assert deadline > now[0]
        return 200

    cycle = Cycle(
        tmp_path, generator_id="generator", state_id="state", clock=lambda: now[0], sleep=sleep
    )
    samples, result = await cycle.run(request, encoded_hash=HASH, configured_hash_cost=12)
    assert now[0] == 180 and len(samples["status"]) == 9000 and len(samples["login"]) == 20
    assert order == ["status"] * 9000 + ["login"] * 20
    assert result["status"]["status"] == result["login"]["status"] == "PASS"
    with pytest.raises(FileExistsError):
        await cycle.run(request, encoded_hash=HASH, configured_hash_cost=12)
    with pytest.raises(ValueError, match="independent"):
        Cycle(tmp_path, generator_id="state", state_id="state")


async def test_cost_mismatch_does_not_weaken_hash_or_claim_cycle(tmp_path):
    cycle = Cycle(tmp_path, generator_id="generator", state_id="state")
    with pytest.raises(ValueError, match="hash cost"):
        await cycle.run(None, encoded_hash=HASH, configured_hash_cost=10)
    assert not (tmp_path / "latency-cycle.claim").exists()
