"""Render one live generator run as a self-contained HTML report (demo clip D5).

    python3 -m scripts.demo.perf_report --run-dir RUN [--lane-receipt FILE] [--out FILE]

Input is the tee of `python3 -m scripts.aws.v1.proof.generator` (`RUN/generator.log`) and, if
present, `RUN/environment.json` written by the recording command (UTC window, target origin,
stage throttle, commit). The samples are decoded with the generator harness's own helpers, their
SHA-256 and length are checked against the DC2-RESULT line, and every figure is recomputed from
the rows; a mismatch stops the render. An optional short-lane receipt (the format of
docs/results/engineering-20261021/short-lane-sl1021.json) adds the lane comparison. Nothing in
the report is typed in: a second run gives different numbers from the same renderer.

Output is one HTML file with inline CSS and inline SVG: no script, no external resource.
"""

import argparse
import hashlib
import html
import json
import math
import sys
from pathlib import Path

from scripts.aws.v1.proof import generator
from scripts.aws.v1.proof.core import ProofError, sha256_text
from scripts.aws.v1.proof.latency import collect_samples, parse_samples, throttled
from scripts.aws.v1.proof.tasks import tagged

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/aws/v1/proof/generator.py"
# The in-region #66 run, shown only as a labelled historical row (not a repeat of this run).
REFERENCE = ROOT / "docs/execution/aws/v1/evidence/cloud-proof-r1017b.json"
# The gates latency.judge and scripts.aws.latency.summarize apply (#66), and the proposal's.
STATUS_P90_MS, LOGIN_P90_MS, ERROR_RATE = 700, 2000, 0.01
LOG, ENVIRONMENT = "generator.log", "environment.json"
ROUTE_ORDER = ("status", *(r.split("?")[0] for r in generator.OTHER_ROUTES), "login")


class ReportError(Exception):
    pass


# ---- input ------------------------------------------------------------------------------------
def load_run(text):
    """(result, sample CSV, rows) from the generator's output; refuses anything unverifiable."""
    lines = text.splitlines()
    results = tagged(lines, generator.RESULT)
    if not results:
        raise ReportError(f"No {generator.RESULT} line in the log")
    result = results[-1]
    if not result.get("ok"):
        raise ReportError(
            f"The generator stopped at stage {result.get('stage')!r} "
            f"(HTTP {result.get('status')}); warm the databases and rerun"
        )
    try:
        samples = collect_samples(lines)
    except (ProofError, ValueError) as error:
        raise ReportError(f"The sample chunks cannot be decoded: {error}") from None
    if sha256_text(samples) != result["samples_sha256"] or len(samples) != result.get(
        "samples_length"
    ):
        raise ReportError("The samples do not match the SHA-256 and length in DC2-RESULT")
    return result, samples, parse_samples(samples)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise ReportError(f"{Path(path).name} is unreadable: {error}") from None


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- analysis ---------------------------------------------------------------------------------
def agrees(mine, theirs):
    """Recomputed route figures against the generator's own (samples carry 3-decimal ms)."""
    if not theirs or mine["count"] != theirs["count"] or mine["errors"] != theirs["errors"]:
        return False
    keys = ("p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms")
    return all(abs(mine[k] - theirs[k]) <= 0.001 for k in keys if mine[k] is not None)


def analyse(result, rows):
    timed = [r for r in rows if r["phase"] == "timed"]
    rank = {label: i for i, label in enumerate(ROUTE_ORDER)}
    labels = sorted({r["route"] for r in timed}, key=lambda x: (rank.get(x, len(rank)), x))
    routes = {
        label: generator.describe([r for r in timed if r["route"] == label])
        | {"throttled": throttled(timed, label)}
        for label in labels
    }
    windows = result["windows"]["status"]
    errors = sum(1 for r in timed if r["status_code"] != 200 or r["error"])
    return {
        "routes": routes,
        "agree": all(agrees(routes[k], result["routes"].get(k)) for k in routes)
        and set(routes) == set(result["routes"]),
        "timed_count": len(timed),
        "errors": errors,
        "error_rate": errors / len(timed) if timed else 1.0,
        "throttled": throttled(timed),
        "workload": {
            "users": result["users"],
            "seconds": round(windows["ended_at"] - windows["started_at"]),
            "warmup": round(windows["warmup_ended_at"] - windows["warmup_started_at"]),
            "logins": len([r for r in rows if r["route"] == "login"]),
        },
        "status_ms": [r["elapsed_ms"] for r in timed if r["route"] == "status"],
    }


def lane_figures(receipt):
    """Per-arm figures from a short-encode receipt's compare step (flattened or as recorded)."""
    step = (receipt.get("steps") or {}).get("compare") or {}
    step = step.get("public", step)
    arms = {arm: step.get(arm) for arm in ("lambda", "fargate") if step.get(arm)}
    if not arms:
        raise ReportError("The lane receipt has no compare step with both arms")
    return arms, step.get("queue_wait_target_seconds")


def reference_cycle(path):
    try:
        doc = json.loads(Path(path).read_text())
        return doc["issues"]["#66"]["steps"]["generator"]["public"]["status_cycle"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---- rendering helpers ------------------------------------------------------------------------
def esc(value):
    return html.escape(str(value), quote=True)


def ms(value):
    return "-" if value is None else f"{value:.1f}"


def secs(value):
    return "-" if value is None else f"{value:.2f} s" if value < 10 else f"{value:.1f} s"


def mark(passed):
    return '<td class="pass">PASS</td>' if passed else '<td class="miss">MISS</td>'


def table(head, rows, cls=""):
    cells = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{cells}</tr></thead><tbody>{body}</tbody></table>'


def td(value, cls="num"):
    return f'<td class="{cls}">{esc(value)}</td>'


def nice_step(span, parts):
    raw = max(span / parts, 1e-9)
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 5, 10) if m * power >= raw)


def bar_chart(counts, *, width_unit, unit, caption, lines=(), shade=None):
    """Vertical bars on a 0-based axis. `lines` are (x value, label, css class) markers;
    `shade` is an (x0, x1, label) band. x values are in the same unit as the bar edges."""
    w, h, left, bottom, top = 760, 240, 48, 30, 14
    plot_w, plot_h = w - left - 12, h - bottom - top
    n = max(len(counts), 1)
    peak = max([*counts, *(v for v, _, c in lines if c == "limit-y")], default=0) or 1
    y_step = nice_step(peak, 4)
    y_max = y_step * math.ceil(peak / y_step)
    bw = plot_w / n

    def x_of(value):
        return left + value / width_unit * bw

    def y_of(value):
        return top + plot_h - value / y_max * plot_h

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(caption)}">']
    if shade:
        x0, x1 = x_of(shade[0]), x_of(shade[1])
        parts.append(
            f'<rect class="band" x="{x0:.1f}" y="{top}" width="{max(x1 - x0, 1):.1f}" '
            f'height="{plot_h}"/><text class="lbl" x="{x0 + 4:.1f}" y="{top + 12}">'
            f"{esc(shade[2])}</text>"
        )
    tick = 0
    while tick <= y_max:
        y = y_of(tick)
        parts.append(
            f'<line class="grid" x1="{left}" x2="{w - 12}" y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<text class="ax" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{tick:g}</text>'
        )
        tick += y_step
    for i, count in enumerate(counts):
        if count:
            y = y_of(count)
            parts.append(
                f'<rect class="bar" x="{left + i * bw + 0.5:.1f}" y="{y:.1f}" '
                f'width="{max(bw - 1, 0.5):.1f}" height="{top + plot_h - y:.1f}"/>'
            )
    for i in range(0, n + 1, max(1, n // 8)):
        parts.append(
            f'<text class="ax" x="{left + i * bw:.1f}" y="{h - 10}" text-anchor="middle">'
            f"{i * width_unit:g}</text>"
        )
    for index, (value, label, cls) in enumerate(lines):
        if cls == "limit-y":
            y = y_of(value)
            parts.append(
                f'<line class="limit" x1="{left}" x2="{w - 12}" y1="{y:.1f}" y2="{y:.1f}"/>'
                f'<text class="lbl" x="{w - 16}" y="{y - 4:.1f}" text-anchor="end">'
                f"{esc(label)}</text>"
            )
            continue
        x = x_of(value)
        if left <= x <= w - 12:
            # Labels near the right edge sit left of their line so they are not clipped.
            near_edge = x > w - 120
            anchor = ' text-anchor="end"' if near_edge else ""
            lx = x - 3 if near_edge else x + 3
            parts.append(
                f'<line class="{cls}" x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top + plot_h}"/>'
                f'<text class="lbl" x="{lx:.1f}" y="{top + 24 + 12 * (index % 4)}"{anchor}>'
                f"{esc(label)}</text>"
            )
    parts.append(f'<text class="ax" x="{left}" y="{top - 3}">x axis: {esc(unit)}</text>')
    parts.append("</svg>")
    return f"<figure>{''.join(parts)}<figcaption>{esc(caption)}</figcaption></figure>"


def histogram(values, stats):
    """Status-route latency in fixed-width bins up to the p99, the rest in one overflow bin."""
    upper = max(stats["p99_ms"], 1.0)
    width = nice_step(upper, 30)
    bins = math.ceil(upper / width) + 1
    counts = [0] * bins
    for value in values:
        counts[min(int(value // width), bins - 1)] += 1
    lines = [
        (stats["p50_ms"], f"p50 {ms(stats['p50_ms'])}", "pct"),
        (stats["p90_ms"], f"p90 {ms(stats['p90_ms'])}", "pct"),
        (stats["p99_ms"], f"p99 {ms(stats['p99_ms'])}", "pct"),
        (STATUS_P90_MS, f"target p90 {STATUS_P90_MS}", "target"),
    ]
    return bar_chart(
        counts,
        width_unit=width,
        unit="ms",
        caption=(
            f"Status route, {len(values)} timed requests, bins of {width:g} ms; the last bin "
            f"holds everything at or above {(bins - 1) * width:g} ms"
        ),
        lines=lines,
    )


def percentile_bars(stats):
    keys = ("p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms")
    top = max([STATUS_P90_MS, *(stats[k] or 0 for k in keys)])
    w, row = 760, 26
    h = row * len(keys) + 26
    scale = (w - 120) / top
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Status route percentiles">']
    for i, key in enumerate(keys):
        y, value = 6 + i * row, stats[key] or 0
        parts.append(
            f'<text class="ax" x="44" y="{y + 15}" text-anchor="end">{key[:-3]}</text>'
            f'<rect class="bar" x="52" y="{y}" width="{max(value * scale, 1):.1f}" height="18"/>'
            f'<text class="ax" x="{58 + value * scale:.1f}" y="{y + 14}">{ms(value)} ms</text>'
        )
    x = 52 + STATUS_P90_MS * scale
    parts.append(
        f'<line class="target" x1="{x:.1f}" x2="{x:.1f}" y1="2" y2="{h - 18}"/>'
        f'<text class="lbl" x="{x:.1f}" y="{h - 4}" text-anchor="end">'
        f"target p90 {STATUS_P90_MS} ms</text></svg>"
    )
    caption = "Status route percentiles against the p90 target"
    return f"<figure>{''.join(parts)}<figcaption>{caption}</figcaption></figure>"


def throughput(rows, result, limit):
    t0 = min(r["started_at"] for r in rows)
    end = max(r["ended_at"] for r in rows)
    counts = [0] * (int(end - t0) + 1)
    for r in rows:
        counts[int(r["started_at"] - t0)] += 1
    window = result["windows"]["status"]
    lines = [(limit, f"stage limit {limit:g} req/s", "limit-y")] if limit else []
    return bar_chart(
        counts,
        width_unit=1,
        unit="s from first request",
        caption=(
            "Requests started per 1 s bucket over the whole run (warm-up, status window, other "
            "routes, login burst)"
            + ("" if limit else "; stage limit not recorded in environment.json")
        ),
        lines=lines,
        shade=(window["started_at"] - t0, window["ended_at"] - t0, "timed status window"),
    )


# ---- the report -------------------------------------------------------------------------------
STYLE = """
body{font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;background:#f6f7f9;
color:#1d2330}main{max-width:900px;margin:0 auto;padding:28px 24px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 10px;padding-bottom:4px;
border-bottom:1px solid #d6dae2}.sub{color:#596273;margin:0 0 14px}
table{border-collapse:collapse;width:100%;background:#fff;margin:6px 0 4px;font-size:14px}
th,td{border:1px solid #d6dae2;padding:5px 8px;text-align:left}th{background:#eef0f4}
td.num{text-align:right;font-variant-numeric:tabular-nums}td.pass{color:#0b6b2f;font-weight:700}
td.miss{color:#a3111b;font-weight:700}tr.ref td{color:#596273;font-style:italic}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}dt{color:#596273}
dd{margin:0;word-break:break-all}figure{margin:10px 0;background:#fff;border:1px solid #d6dae2;
padding:8px}figcaption{color:#596273;font-size:13px;margin-top:4px}svg{width:100%;height:auto}
.bar{fill:#3b6fb6}.grid{stroke:#e3e6ec}.ax{font-size:11px;fill:#596273}.lbl{font-size:11px;
fill:#1d2330}.pct{stroke:#1d2330;stroke-dasharray:3 3}.target{stroke:#a3111b;stroke-width:2}
.limit{stroke:#a3111b;stroke-width:2;stroke-dasharray:6 4}.band{fill:#e9f0fa}
.note{color:#596273;font-size:13px}code{font-size:13px}
"""


def render(run_id, result, samples, rows, *, env=None, inputs=None, lanes=None, reference=None):
    data = analyse(result, rows)
    env, inputs = env or {}, inputs or {}
    routes, wl = data["routes"], data["workload"]
    status, login = routes.get("status"), routes.get("login")
    throttle = env.get("stage_throttle") or {}
    limit = throttle.get("ThrottlingRateLimit")

    header = [
        ("Run", run_id),
        (
            "UTC window",
            f"{env['started_utc']} to {env.get('ended_utc', '?')}"
            if env.get("started_utc")
            else "not recorded (no environment.json)",
        ),
        ("Target", env.get("base_url", "not recorded")),
        ("Network path", env.get("network_path", "not recorded")),
        (
            "Workload",
            f"{wl['users']} virtual users reading the status route once a second for "
            f"{wl['seconds']} s after a {wl['warmup']} s warm-up; four other read routes; "
            f"{wl['logins']} concurrent logins",
        ),
        (
            "Stage throttle",
            f"{throttle.get('ThrottlingRateLimit', '?')} req/s, burst "
            f"{throttle.get('ThrottlingBurstLimit', '?')}"
            if throttle
            else "not recorded",
        ),
        ("Commit", env.get("commit", "not recorded")),
    ]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>FlickPond performance run {esc(run_id)}</title><style>{STYLE}</style></head>",
        "<body><main><h1>FlickPond performance run</h1>",
        "<p class='sub'>Scripted load on the live public API, rendered from the run's own "
        "output. Every figure below is recomputed from the raw samples.</p>",
        "<h2>1. Run</h2><dl>",
        *(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in header),
        "</dl>",
    ]

    target_rows = []
    if status:
        target_rows.append(
            [
                td("Status route p90", "l"),
                td(f"<= {STATUS_P90_MS} ms"),
                td(f"{ms(status['p90_ms'])} ms"),
                mark(status["p90_ms"] is not None and status["p90_ms"] <= STATUS_P90_MS),
            ]
        )
    target_rows.append(
        [
            td("Error rate, all timed requests (429 included)", "l"),
            td(f"< {ERROR_RATE:.0%}"),
            td(f"{data['error_rate']:.2%} ({data['errors']} of {data['timed_count']})"),
            mark(data["error_rate"] < ERROR_RATE),
        ]
    )
    if login:
        target_rows.append(
            [
                td("Login p90", "l"),
                td(f"< {LOGIN_P90_MS / 1000:g} s"),
                td(f"{ms(login['p90_ms'])} ms"),
                mark(login["p90_ms"] is not None and login["p90_ms"] < LOGIN_P90_MS),
            ]
        )
    if lanes and lanes[1] is not None and "lambda" in lanes[0]:
        wait = ((lanes[0]["lambda"].get("queue_wait") or {}).get("all") or {}).get("median_seconds")
        target_rows.append(
            [
                td("Short-lane median queue wait (lane receipt)", "l"),
                td(f"<= {lanes[1]:g} s"),
                td(secs(wait)),
                mark(wait is not None and wait <= lanes[1]),
            ]
        )
    if reference:
        target_rows.append(
            [
                td(
                    f"Reference only: in-region run r1017b, status p90 ({reference['users']} "
                    f"users, {reference['duration_seconds']} s, {reference['sample_count']} "
                    "requests, Fargate generator in the same region; not a repeat of this run)",
                    "l",
                ),
                td(f"<= {STATUS_P90_MS} ms"),
                td(f"{ms(reference['p90_ms'])} ms"),
                td(reference["status"], "l"),
            ]
        )
    out += [
        "<h2>2. Targets against actuals</h2>",
        table(("Measure", "Target", "Actual", "Result"), target_rows, "targets"),
    ]
    if data["throttled"]:
        out.append(
            f"<p class='note'>{data['throttled']} requests were answered 429 by the stage "
            "throttle; they count as errors.</p>"
        )

    route_rows = [
        [
            td(label, "l"),
            td(s["count"]),
            td(s["errors"]),
            td(s["throttled"]),
            *(td(ms(s[k])) for k in ("p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms")),
        ]
        for label, s in routes.items()
    ]
    out += [
        "<h2>3. Latency per route (ms, timed phase)</h2>",
        table(
            ("Route", "Count", "Errors", "429", "p50", "p90", "p95", "p99", "max"),
            route_rows,
            "routes",
        ),
        "<p class='note'>Nearest-rank percentiles, the generator's own rule. Every failure stays "
        "in the denominator; nothing is retried.</p>",
    ]
    if status:
        out += [
            "<h2>4. Status route latency distribution</h2>",
            histogram(data["status_ms"], status),
            percentile_bars(status),
        ]
    out += ["<h2>5. Throughput over time</h2>", throughput(rows, result, limit)]

    if lanes:
        arms, target = lanes
        names = {"lambda": "Short lane (Lambda)", "fargate": "Standard lane (Fargate)"}

        def qw(arm, key):
            return ((arm.get("queue_wait") or {}).get("all") or {}).get(key)

        lane_rows = [
            [
                td(names[k], "l"),
                td(f"{arm.get('successes', '?')} / {arm.get('failures', '?')}"),
                td(secs(qw(arm, "median_seconds"))),
                td(secs(qw(arm, "max_seconds"))),
                td(secs((arm.get("cold") or {}).get("median_seconds"))),
                td(secs((arm.get("warm") or {}).get("median_seconds"))),
                td(
                    "-"
                    if arm.get("cost_usd_per_success") is None
                    else f"${arm['cost_usd_per_success']:.6f}"
                ),
            ]
            for k, arm in arms.items()
        ]
        meta = inputs.get("lane receipt", {})
        out += [
            "<h2>6. Lane comparison (from the short-lane receipt)</h2>",
            table(
                (
                    "Lane",
                    "Jobs ok / failed",
                    "Queue wait median",
                    "Queue wait max",
                    "Submit to done, cold median",
                    "Warm median",
                    "Compute cost / success",
                ),
                lane_rows,
                "lanes",
            ),
            f"<p class='note'>Receipt {esc(meta.get('name', ''))}, run "
            f"{esc(meta.get('date', '?'))} on {esc(meta.get('environment', '?'))}. Serial jobs "
            "per arm: this shows queue wait and end-to-end time per lane, not concurrency. Queue "
            "wait is the Processing API's own queued-to-started stamps"
            + (f"; target {target:g} s." if target is not None else ".")
            + "</p>",
        ]

    prov = [
        ("Samples", f"{len(rows)} rows, {result['chunks']} chunk(s), {len(samples)} bytes of CSV"),
        ("Samples SHA-256", f"{result['samples_sha256']} (verified against DC2-RESULT)"),
        (
            "Recomputed figures",
            "agree with the DC2-RESULT summary"
            if data["agree"]
            else "DIFFER from the DC2-RESULT summary; the table shows the recomputed values",
        ),
        ("Generator", f"python {result.get('python', '?')}, {result.get('cpus', '?')} CPUs"),
        ("generator.py SHA-256 at render", file_sha256(GENERATOR)),
        *((f"Input {k}", f"{v['name']} sha256 {v['sha256']}") for k, v in inputs.items()),
    ]
    out += [
        f"<h2>{7 if lanes else 6}. Provenance</h2><dl>",
        *(f"<dt>{esc(k)}</dt><dd><code>{esc(v)}</code></dd>" for k, v in prov),
        "</dl></main></body></html>",
    ]
    return "\n".join(out) + "\n", data


def build(run_dir, *, lane_receipt=None, reference=REFERENCE):
    run_dir = Path(run_dir)
    log = run_dir / LOG
    if not log.is_file():
        raise ReportError(f"{log} does not exist")
    result, samples, rows = load_run(log.read_text())
    inputs = {"log": {"name": LOG, "sha256": file_sha256(log)}}
    env = None
    if (run_dir / ENVIRONMENT).is_file():
        env = read_json(run_dir / ENVIRONMENT)
        inputs["environment"] = {"name": ENVIRONMENT, "sha256": file_sha256(run_dir / ENVIRONMENT)}
    lanes = None
    if lane_receipt:
        receipt = read_json(lane_receipt)
        lanes = lane_figures(receipt)
        inputs["lane receipt"] = {
            "name": Path(lane_receipt).name,
            "sha256": file_sha256(lane_receipt),
            "date": receipt.get("date"),
            "environment": receipt.get("environment"),
        }
    ref = reference_cycle(reference) if reference else None
    return render(
        run_dir.name, result, samples, rows, env=env, inputs=inputs, lanes=lanes, reference=ref
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--run-dir", required=True, type=Path, help=f"holds {LOG}")
    parser.add_argument("--lane-receipt", type=Path, help="short-lane receipt JSON (optional)")
    parser.add_argument("--out", type=Path, help="default RUN/report.html")
    args = parser.parse_args(argv)
    try:
        page, data = build(args.run_dir, lane_receipt=args.lane_receipt)
    except ReportError as error:
        print(f"perf_report: {error}", file=sys.stderr)
        return 2
    out = args.out or args.run_dir / "report.html"
    out.write_text(page)
    status = data["routes"].get("status") or {}
    print(
        f"wrote {out}: {data['timed_count']} timed requests, status p90 "
        f"{ms(status.get('p90_ms'))} ms, error rate {data['error_rate']:.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
