import asyncio

import pytest

from scripts.aws.latency import Cycle, hash_cost, percentile90, summarize

HASH = "$2b$12$" + "a" * 53
WINDOW = {
    "started_at": 0,
    "ended_at": 180,
    "warmup_started_at": 0,
    "warmup_ended_at": 0,
    "booked_deadline": 210,
}


def sample(user, ms=100, *, at=0, **kw):
    return {
        "user": user,
        "elapsed_ms": ms,
        "status_code": 200,
        "phase": "timed",
        "started_at": at,
        "ended_at": at + ms / 1000,
        **kw,
    }


def test_p90_and_failures_not_dropped():
    assert percentile90(list(range(1, 11))) == 9
    samples = [sample(u, at=t) for t in range(180) for u in range(50)]
    for row in samples[-90:]:
        row.update(status_code=500, error="request_failed")
    result = summarize(samples, users=50, duration_seconds=180, measurement="status", window=WINDOW)
    assert result["eligible"] and result["error_rate"] == 0.01 and result["status"] == "FAIL"
    assert result["sample_count"] == 9000


@pytest.mark.parametrize("change", ["warmup", "missing_user", "wrong_duration", "slow"])
def test_status_ineligible_or_missed_target(change):
    samples = [sample(u, at=t) for t in range(180) for u in range(50)]
    duration = 180
    if change == "warmup":
        samples[0]["phase"] = "warmup"
    elif change == "missing_user":
        samples = [s for s in samples if s["user"] != 49]
    elif change == "wrong_duration":
        duration = 179
    else:
        samples = [sample(u, 701, at=t) for t in range(180) for u in range(50)]
    assert (
        summarize(
            samples, users=50, duration_seconds=duration, measurement="status", window=WINDOW
        )["status"]
        == "FAIL"
    )


@pytest.mark.parametrize(("overshoot", "eligible"), [(1e-7, True), (0.0005, True), (0.01, False)])
def test_a_180_second_window_may_overshoot_by_float_noise_but_not_by_more(overshoot, eligible):
    # A monotonic clock near 1e5 s has ulps around 1e-11; subtracting two such sums can leave
    # a 1e-7 residue, which must not make an honestly booked 180 s window ineligible.
    window = {**WINDOW, "ended_at": 180 + overshoot}
    samples = [sample(u, at=t) for t in range(180) for u in range(50)]
    result = summarize(
        samples, users=50, duration_seconds=180, measurement="status", window=window
    )
    assert result["eligible"] is eligible


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
    samples, result = await cycle.run(
        request, encoded_hash=HASH, configured_hash_cost=12, deadline=215
    )
    assert now[0] == 185 and len(samples["status"]) == 9000 and len(samples["login"]) == 20
    assert order == ["status"] * 9050 + ["login"] * 20
    assert result["status"]["status"] == result["login"]["status"] == "PASS"
    with pytest.raises(FileExistsError):
        await cycle.run(request, encoded_hash=HASH, configured_hash_cost=12, deadline=215)
    with pytest.raises(ValueError, match="independent"):
        Cycle(tmp_path, generator_id="state", state_id="state")


async def test_cost_mismatch_does_not_weaken_hash_or_claim_cycle(tmp_path):
    cycle = Cycle(tmp_path, generator_id="generator", state_id="state")
    with pytest.raises(ValueError, match="hash cost"):
        await cycle.run(None, encoded_hash=HASH, configured_hash_cost=10)
    assert not (tmp_path / "latency-cycle.claim").exists()
