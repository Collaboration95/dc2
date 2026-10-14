"""Offline interval aggregates; retain observed sampling spans and counter resets."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from scripts.experiments.followups import parse_counters


def lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def pressure_totals(value):
    return {
        line.split()[0]: int(
            next(field.split("=")[1] for field in line.split()[1:] if field.startswith("total="))
        )
        for line in value.splitlines()
    }


def interval_aggregate(rows, start, end):
    selected = [r for r in rows if start <= r["monotonic"] <= end]
    by_container = defaultdict(list)
    for row in selected:
        for container in row["containers"]:
            by_container[(container["container"]["service"], container["container"]["id"])].append(
                (row["monotonic"], container["cgroup"])
            )
    output = []
    for (service, identity), samples in by_container.items():
        first, last = samples[0][1], samples[-1][1]
        a, b = parse_counters(first["cpu.stat"]), parse_counters(last["cpu.stat"])
        deltas = {key: b[key] - a[key] for key in a}
        if any(value < 0 for value in deltas.values()):
            raise ValueError("Counter reset inside immutable container interval")
        item = {
            "service": service,
            "container_id": identity,
            "samples": len(samples),
            "observed_span_seconds": samples[-1][0] - samples[0][0],
            "cpu_delta": deltas,
            "cpu_max": last["cpu.max"],
            "memory_max": last["memory.max"],
            "memory_peak_bytes": max(int(s[1]["memory.peak"]) for s in samples),
            "maximum_sampled_memory_current_bytes": max(
                int(s[1]["memory.current"]) for s in samples
            ),
            "memory_events_delta": {
                k: parse_counters(last["memory.events"])[k] - v
                for k, v in parse_counters(first["memory.events"]).items()
            },
        }
        for kind in ("cpu.pressure", "memory.pressure", "io.pressure"):
            aa, bb = pressure_totals(first[kind]), pressure_totals(last[kind])
            item[kind + "_total_delta_us"] = {k: bb[k] - v for k, v in aa.items()}
        if first.get("timings") and last.get("timings"):
            aa, bb = json.loads(first["timings"]), json.loads(last["timings"])
            if aa["pid"] != bb["pid"]:
                raise ValueError("API timing process changed during interval")
            item["api_timings_delta"] = {}
            for key in set(aa["counters"]) | set(bb["counters"]):
                left, right = aa["counters"].get(key, {}), bb["counters"].get(key, {})
                count = right.get("count", 0) - left.get("count", 0)
                elapsed = right.get("sum_ms", 0) - left.get("sum_ms", 0)
                item["api_timings_delta"][key] = {
                    "count": count,
                    "sum_ms": elapsed,
                    "mean_ms": elapsed / count if count else None,
                }
        output.append(item)
    waits = defaultdict(int)
    for row in selected:
        for wait in row["server_waits"]:
            if wait["state"] == "active":
                waits[str((wait["datname"], wait["wait_event_type"], wait["wait_event"]))] += wait[
                    "sessions"
                ]
    return {
        "containers": output,
        "active_server_wait_sample_counts": dict(waits),
        "samples": len(selected),
        "planned_span_seconds": end - start,
    }


def analyze(source):
    source = Path(source)
    telemetry = lines(source / "telemetry.jsonl")
    intervals = lines(source / "intervals.jsonl")
    result = []
    for interval in intervals:
        if not interval["timed"]:
            continue
        start = interval["start_monotonic"]
        end = start + interval["planned_duration_seconds"]
        result.append(
            {
                "phase": interval["repeat"],
                "topic": interval["topic"],
                **interval_aggregate(telemetry, start, end),
            }
        )
    target = source / "interval-aggregates.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    return len(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    args = parser.parse_args()
    print("Analyzed", analyze(args.source), "timed intervals")


if __name__ == "__main__":
    main()
