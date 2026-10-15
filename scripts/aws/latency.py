"""One serial cycle on an independent generator; all errors stay in the denominator."""

import asyncio
import math
import os
import re
import time
from pathlib import Path


def hash_cost(encoded_hash):
    match = re.match(r"^\$2[aby]\$(\d\d)\$[./A-Za-z0-9]{53}$", encoded_hash)
    if not match:
        raise ValueError("Actual bcrypt hash receipt required")
    return int(match[1])


def percentile90(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Invalid latency samples")
    return sorted(values)[math.ceil(len(values) * 0.9) - 1]


def timing_eligible(samples, *, users, duration_seconds, measurement, window):
    if not isinstance(window, dict) or not samples:
        return False
    keys = ("started_at", "ended_at", "warmup_started_at", "warmup_ended_at", "booked_deadline")
    if any(
        not isinstance(window.get(k), (int, float)) or not math.isfinite(window[k]) for k in keys
    ):
        return False
    start, end = window["started_at"], window["ended_at"]
    if not window["warmup_started_at"] <= window["warmup_ended_at"] <= start <= end:
        return False
    if end > window["booked_deadline"] or end - start > 180:
        return False
    if measurement == "status" and abs(end - start - duration_seconds) > 0.001:
        return False
    for sample in samples:
        before, after = sample.get("started_at"), sample.get("ended_at")
        if (
            not isinstance(before, (int, float))
            or not isinstance(after, (int, float))
            or not math.isfinite(before)
            or not math.isfinite(after)
            or not start <= before <= after <= end + 0.1
            or abs((after - before) * 1000 - sample["elapsed_ms"]) > 1
        ):
            return False
    if measurement == "status":
        # One-second sampling cadence: every client must cover the actual window.
        for user in range(users):
            rows = [s for s in samples if s["user"] == user]
            if (
                not rows
                or min(s["started_at"] for s in rows) > start + 1
                or max(s["ended_at"] for s in rows) < end - 1
                or len(rows) < 10
            ):
                return False
            ordered = sorted(rows, key=lambda s: s["started_at"])
            if any(
                b["started_at"] - a["ended_at"] > 12
                for a, b in zip(ordered, ordered[1:], strict=False)
            ):
                return False
    return True


def summarize(samples, *, users, duration_seconds, measurement, actual_hash_cost=None, window=None):
    if measurement not in {"status", "login"}:
        raise ValueError("Unknown measurement")
    if any(
        s.get("user") not in range(users)
        or not math.isfinite(s.get("elapsed_ms", -1))
        or s.get("elapsed_ms", -1) < 0
        for s in samples
    ):
        raise ValueError("Invalid timed sample")
    eligible = bool(samples) and {s["user"] for s in samples} == set(range(users))
    eligible &= users == (50 if measurement == "status" else 20)
    eligible &= duration_seconds == (180 if measurement == "status" else 0)
    eligible &= all(s.get("phase") == "timed" for s in samples)
    eligible &= timing_eligible(
        samples,
        users=users,
        duration_seconds=duration_seconds,
        measurement=measurement,
        window=window,
    )
    if measurement == "login":
        eligible &= len(samples) == 20 and actual_hash_cost is not None
    errors = sum(s.get("status_code") != 200 or bool(s.get("error")) for s in samples)
    rate = errors / len(samples) if samples else 1
    p90 = percentile90([s["elapsed_ms"] for s in samples]) if samples else None
    passed = (
        eligible
        and rate < 0.01
        and p90 is not None
        and (p90 <= 700 if measurement == "status" else p90 < 2000)
    )
    return {
        "measurement": measurement,
        "users": users,
        "duration_seconds": duration_seconds,
        "eligible": eligible,
        "sample_count": len(samples),
        "p90_ms": p90,
        "error_rate": rate,
        "hash_cost": actual_hash_cost,
        "status": "PASS" if passed else "FAIL",
    }


class Cycle:
    def __init__(
        self,
        receipt_directory,
        *,
        generator_id,
        state_id,
        core_task_ids=(),
        evidence=None,
        mode="offline",
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ):
        if not generator_id or generator_id in {state_id, *core_task_ids}:
            raise ValueError("Generator must be independent of state and service tasks")
        self.directory = Path(receipt_directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clock, self.sleep = clock, sleep
        self.generator_id = generator_id
        if mode not in {"offline", "emulator", "local-services"}:
            raise ValueError("Preparation latency cannot claim AWS execution")
        self.mode = mode
        self.evidence = evidence

    async def run(self, request, *, encoded_hash, configured_hash_cost, deadline=None):
        if (self.directory / "latency-cycle.claim").exists():
            raise FileExistsError("Latency cycle is already claimed")
        cost = hash_cost(encoded_hash)
        if cost != configured_hash_cost:
            raise ValueError("New account hash cost differs from configured cost")
        if deadline is None or not math.isfinite(deadline) or deadline < self.clock() + 215:
            raise ValueError("One booked absolute deadline must cover status and login windows")
        # Durable once-only reservation survives interruption; failure never unlocks a rerun.
        fd = os.open(
            self.directory / "latency-cycle.claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        os.close(fd)
        samples = {"status": [], "login": []}
        start = self.clock()
        end = start + 180

        async def one(kind, user, deadline, window, phase="timed"):
            before = self.clock()
            code, error = None, None
            try:
                code = await asyncio.wait_for(
                    request(kind, user, deadline=deadline),
                    timeout=max(0.001, min(10, deadline - before)),
                )
            except Exception:
                error = "request_failed"
            after = self.clock()
            sample = {
                "user": user,
                "phase": phase,
                "status_code": code,
                "error": error,
                "elapsed_ms": max(0, (after - before) * 1000),
                "started_at": before,
                "ended_at": after,
                "window_started_at": window["started_at"],
                "window_ended_at": window["ended_at"],
                "warmup_started_at": window["warmup_started_at"],
                "warmup_ended_at": window["warmup_ended_at"],
                "booked_deadline": window["booked_deadline"],
            }
            if self.evidence:
                self.evidence.write(
                    "samples.jsonl", {**sample, "mode": self.mode, "measurement": kind}
                )
            return sample

        warmup_start = self.clock()
        warmup_end = warmup_start + 5
        warmup_window = {
            "started_at": warmup_start,
            "ended_at": warmup_end,
            "warmup_started_at": warmup_start,
            "warmup_ended_at": warmup_end,
            "booked_deadline": deadline,
        }
        await asyncio.gather(
            *(one("status", u, warmup_end, warmup_window, "warmup") for u in range(50))
        )
        if self.clock() < warmup_end:
            await self.sleep(warmup_end - self.clock())
        start = self.clock()
        end = start + 180
        status_window = {
            "started_at": start,
            "ended_at": end,
            "warmup_started_at": warmup_start,
            "warmup_ended_at": start,
            "booked_deadline": deadline,
        }
        while self.clock() < end:
            samples["status"].extend(
                await asyncio.gather(*(one("status", u, end, status_window) for u in range(50)))
            )
            remaining = end - self.clock()
            if remaining > 0:
                await self.sleep(min(1, remaining))
        # Separate login window, one request per user; no concurrent status generation.
        login_start = self.clock()
        login_end = min(deadline, login_start + 30)
        login_window = {
            "started_at": login_start,
            "ended_at": login_end,
            "warmup_started_at": login_start,
            "warmup_ended_at": login_start,
            "booked_deadline": deadline,
        }
        samples["login"] = await asyncio.gather(
            *(one("login", u, login_end, login_window) for u in range(20))
        )
        return samples, {
            "status": summarize(
                samples["status"],
                users=50,
                duration_seconds=180,
                measurement="status",
                window=status_window,
            ),
            "login": summarize(
                samples["login"],
                users=20,
                duration_seconds=0,
                measurement="login",
                actual_hash_cost=cost,
                window=login_window,
            ),
        }


def main():
    """Offline arithmetic over selected JSONL; never starts a generator or requests."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--hash-cost", type=int)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.samples.read_text().splitlines()]
    results = []
    windows = {}
    for measurement, users, duration in [("status", 50, 180), ("login", 20, 0)]:
        samples = [
            r for r in records if r.get("measurement") == measurement and r.get("phase") != "warmup"
        ]
        names = (
            "started_at",
            "ended_at",
            "warmup_started_at",
            "warmup_ended_at",
            "booked_deadline",
        )
        window = None
        if samples:
            window = {
                k: samples[0].get("window_" + k if k in {"started_at", "ended_at"} else k)
                for k in names
            }
            if any(
                s.get("window_" + k if k in {"started_at", "ended_at"} else k) != window[k]
                for s in samples
                for k in names
            ):
                window = None
        windows[measurement] = window
        results.append(
            {
                "mode": "offline",
                **summarize(
                    samples,
                    users=users,
                    duration_seconds=duration,
                    measurement=measurement,
                    actual_hash_cost=args.hash_cost if measurement == "login" else None,
                    window=window,
                ),
            }
        )
    if (
        windows.get("status")
        and windows.get("login")
        and windows["login"]["started_at"] < windows["status"]["ended_at"]
    ):
        for result in results:
            result.update(eligible=False, status="FAIL")
    print(json.dumps(results, indent=2, allow_nan=False))
    if any(r["status"] == "FAIL" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
