"""#94 (V2): one Aurora cluster for both domains against one cluster per domain.

    python -m scripts.aws.v1.evidence db-topology --arm shared   ...   a stack rendered shared
    python -m scripts.aws.v1.evidence db-topology --arm separate ...   a stack rendered separate
    python -m scripts.aws.v1.evidence db-topology --arm compare  ...   no AWS call; reads both

The two arms are different stacks (`deploy --database-topology shared|separate`, which cannot be
changed on a live stack), so each is deployed under its own run id and the second arm's receipt
is copied beside the first before `compare`, exactly as the #93 arms are. The harness refuses an
arm that does not match the stack it finds.

It needs `session window`, not `session open`: an open session enables the repair schedules,
which touch the database every minute and keep Aurora from ever pausing, so a pause could not be
confirmed and nothing cold could be measured.

Per cluster it records (all from the operator's station, so every latency includes the network
path to Lambda; the receipt says so):

* cold resume: after CloudWatch `ServerlessDatabaseCapacity` shows 0, the time from the first
  ready probe to the first successful one. A cluster that never shows 0 inside the wait is
  recorded as not measured, never as fast.
* warm latency: p50 and p95 of ready probes, a fresh connection plus `SELECT 1` through the
  owner's own Lambda (the one deliberate database touch), for each domain the cluster serves.
* isolation: with every cluster paused, load on Media alone; did Processing's cluster leave 0
  ACU (CloudWatch), and how much slower is Processing's probe under that load than without it.
* ACU-hours and cost over the arm's window, and the notes on migration and restore.

`compare` applies a rule written before any measurement. It records a verdict and never changes
the default: V1's single cluster stays unless every part of the rule holds in a live run.
"""

import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor

from scripts.aws.transport import OperationError
from scripts.aws.v1 import deploy
from scripts.aws.v1.proof import spend
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, percentile, stamp

ARMS = ("shared", "separate")
REQUIRED = ("shared", "separate", "compare")
DOMAINS = ("media", "processing")
WARMUP_PROBES = 3
SETTLE_SECONDS = 300  # longer than any resume seen (15 to 60 s) plus a failed attempt
# CloudWatch publishes a minute late at best, so a window needs a margin on both sides.
METRIC_LAG_SECONDS = 150
MONTH_HOURS = 730
CAPACITY_PERIOD = 60
PROBE_BUDGET_SECONDS = 70  # a synchronous invoke may wait out an Aurora resume
# The rule below was fixed before the first measurement. Change it only with new reasoning.
MAX_PEER_SLOWDOWN = 1.25  # p95 of the peer's probe under load, over its p95 without
MAX_COLD_EXTRA_SECONDS = 15.0  # a separate cluster may resume this much slower than shared
MAX_WARM_P95_RATIO = 1.2
MAX_EXTRA_USD_PER_MONTH = 2.0  # 1% of the $200 planning envelope
NOTES = {
    "migration": (
        "Each owner's migration task reads its own domain's connection parameter, so with one "
        "cluster per domain a migration wakes and holds only that domain's cluster; with one "
        "shared cluster it wakes the cluster both domains use. The schema, roles and "
        "migrations are identical in both layouts. Not measured by this harness."),
    "restore": (
        "Teardown takes one final snapshot per cluster. A shared cluster restores both "
        "databases to one point in time together; separate clusters restore independently. "
        "Neither restore was timed; this is design, not evidence."),
}


# ---- topology and clusters --------------------------------------------------------------------
def topology_of(ctx):
    """What the deployed stack is, read from its outputs and never from the operator's wish."""
    separate = (ctx.outputs.get("DatabaseTopology") == "separate"
                or "ProcessingDatabaseEndpoint" in ctx.outputs)
    return "separate" if separate else "shared"


def cluster_ids(ctx, *, shared=None, media=None, processing=None):
    """{label: cluster id}. 'cluster' when shared, 'media' and 'processing' when separate.

    From the deploy journal, which recorded each cluster's logical name; an override names a
    cluster when a journal predates that record.
    """
    journal = deploy.DeployJournal(
        ctx.state_dir / "deploy-journal.json", station=ctx.data["operator_station"],
        environment=ctx.data["environment_id"])
    if not journal.exists():
        raise ProofError("No deploy journal in the state directory; pass the cluster ids")
    resources = journal.view()["resources"]
    found, logical = resources.get("db_clusters", []), resources.get("db_logical", {})
    if topology_of(ctx) == "shared":
        chosen = shared or (found[0] if len(found) == 1 else None)
        if not chosen:
            raise ProofError("Expected exactly one Aurora cluster in the deploy journal; "
                             "pass --cluster")
        return {"cluster": chosen}
    by_name = {name: cid for cid, name in logical.items()}
    chosen = {"media": media or by_name.get("MediaDatabaseCluster"),
              "processing": processing or by_name.get("ProcessingDatabaseCluster")}
    if not all(chosen.values()) or chosen["media"] == chosen["processing"]:
        raise ProofError("Cannot tell the two clusters apart; pass --media-cluster and "
                         "--processing-cluster")
    return chosen


def domains_of(label):
    return DOMAINS if label == "cluster" else (label,)


def cluster_for(clusters, domain):
    return clusters["cluster"] if "cluster" in clusters else clusters[domain]


def describe_scaling(ctx, cluster):
    reply = ctx.aws.call("rds", "describe-db-clusters", {"DBClusterIdentifier": cluster},
                         deadline=ctx.deadline(60))
    scaling = reply["DBClusters"][0].get("ServerlessV2ScalingConfiguration", {})
    return {"min_acu": scaling.get("MinCapacity"), "max_acu": scaling.get("MaxCapacity"),
            "seconds_until_auto_pause": scaling.get("SecondsUntilAutoPause")}


# ---- one probe --------------------------------------------------------------------------------
def probe(ctx, transport, domain):
    """One ready invocation of the owner's API: (ok, milliseconds)."""
    function = ctx.hooks["media_api" if domain == "media" else "processing_api"]
    started = ctx.clock()
    try:
        result = transport.call("lambda", "invoke", {
            "FunctionName": function, "Qualifier": ctx.config.get("alias", "live"),
            "InvocationType": "RequestResponse", "Payload": {"dc2_operation": "ready"}},
            deadline=ctx.deadline(PROBE_BUDGET_SECONDS))
    except OperationError:
        return False, round((ctx.clock() - started) * 1000, 1)
    reply = result.get("Payload")
    ok = (not result.get("FunctionError") and result.get("StatusCode") == 200
          and isinstance(reply, dict) and reply.get("service") == domain
          and reply.get("ready") is True)
    return ok, round((ctx.clock() - started) * 1000, 1)


def latency_stats(samples):
    """p50/p95 over the probes that succeeded; failures stay counted and are never dropped."""
    good = [ms for ok, ms in samples if ok]
    return {"count": len(samples), "failures": len(samples) - len(good),
            "p50_ms": percentile(good, 0.5), "p95_ms": percentile(good, 0.95),
            "max_ms": max(good) if good else None}


def settle(ctx, transport, domain, *, timeout=SETTLE_SECONDS):
    """Probe until one succeeds, so a cluster still resuming is not timed as a warm one."""
    end = ctx.clock() + timeout
    while ctx.clock() < end:
        if probe(ctx, transport, domain)[0]:
            return True
        ctx.sleep(2)
    return False


def measure_warm(ctx, transport, domain, samples):
    settle(ctx, transport, domain)
    for _ in range(WARMUP_PROBES):
        probe(ctx, transport, domain)
    return latency_stats([probe(ctx, transport, domain) for _ in range(samples)])


# ---- pause and wake ---------------------------------------------------------------------------
def wait_paused(ctx, clusters, *, minutes, checkpoint):
    """Block until every named cluster shows 0 ACU; the labels still awake when time ran out."""
    end = ctx.clock() + 60 * minutes
    awake = list(clusters.values())
    while True:
        checkpoint("window")
        awake = [c for c in awake if spend.paused_now(ctx, c) is not True]
        if not awake or ctx.clock() >= end:
            return [label for label, c in clusters.items() if c in awake]
        ctx.sleep(30)


def cold_resume(ctx, transport, domain, *, timeout):
    """First probe to first success, starting from a cluster CloudWatch already shows paused."""
    started, attempts = ctx.clock(), []
    while True:
        ok, ms = probe(ctx, transport, domain)
        attempts.append(ms)
        if ok or ctx.clock() - started >= timeout:
            break
        ctx.sleep(2)
    return {"measured": True, "probe_domain": domain, "succeeded": ok,
            "resume_seconds": round(ctx.clock() - started, 1) if ok else None,
            "attempts": len(attempts), "first_attempt_ms": attempts[0],
            "paused_confirmed_by": "ServerlessDatabaseCapacity == 0"}


@contextlib.contextmanager
def load(ctx, transport, domain, concurrency):
    """Sustained ready probes against one domain. Yields counters for what the load did.

    Live, each worker invokes in a loop from its own thread. The simulation has one virtual
    clock and no threads, so it is told to model the load instead; both are the same
    measurement from the harness's side.
    """
    stats = {"requests": 0, "ok": 0}
    if ctx.simulated:
        ctx.world.begin_load(domain, concurrency)
        try:
            yield stats
        finally:
            ctx.world.end_load(domain)
        return
    stop, lock = threading.Event(), threading.Lock()

    def worker():
        while not stop.is_set():
            ok, _ = probe(ctx, transport, domain)
            with lock:
                stats["requests"] += 1
                stats["ok"] += int(ok)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(worker) for _ in range(concurrency)]
        try:
            yield stats
        finally:
            stop.set()
            for future in futures:
                future.result()


def peer_wake(ctx, transport, clusters, *, load_seconds, concurrency, pause_minutes, checkpoint):
    """With everything paused, load Media alone and watch Processing's cluster."""
    still = wait_paused(ctx, clusters, minutes=pause_minutes, checkpoint=checkpoint)
    if still:
        return {"measured": False, "reason": "a cluster never showed 0 ACU within the wait: "
                + ", ".join(sorted(still))}
    peer = cluster_for(clusters, "processing")
    started = ctx.wall()
    with load(ctx, transport, "media", concurrency) as stats:
        ctx.sleep(load_seconds)
    ctx.sleep(METRIC_LAG_SECONDS)  # let the minute that held the load reach CloudWatch
    series = spend.capacity_series(ctx, peer, since_epoch=started - CAPACITY_PERIOD)
    peak = max((high for _, _, high in series), default=None)
    return {"measured": peak is not None, "load_domain": "media",
            "observed_cluster_domain": "processing",
            "same_cluster": peer == cluster_for(clusters, "media"),
            "peer_woken": bool(peak), "peer_max_acu": peak,
            "load_concurrency": concurrency, "load_seconds": load_seconds,
            "load_requests": stats["requests"], "load_ok": stats["ok"]}


def peer_slowdown(ctx, transport, *, samples, concurrency):
    """Processing's probe latency without, then with, sustained Media load."""
    alone = measure_warm(ctx, transport, "processing", samples)
    with load(ctx, transport, "media", concurrency):
        ctx.sleep(5)  # let the load reach its steady rate before the first timed probe
        loaded = measure_warm(ctx, transport, "processing", samples)

    def ratio(key):
        return (round(loaded[key] / alone[key], 3)
                if alone[key] and loaded[key] is not None else None)

    return {"measured": alone["p95_ms"] is not None and loaded["p95_ms"] is not None,
            "alone": alone, "under_media_load": loaded,
            "slowdown_p50": ratio("p50_ms"), "slowdown_p95": ratio("p95_ms")}


# ---- ACU-hours and cost -----------------------------------------------------------------------
def acu_hours(ctx, cluster, *, since, until):
    """Average ACU per minute, summed, from CloudWatch; the coverage is reported with it."""
    reply = ctx.aws.call("cloudwatch", "get-metric-statistics", {
        "Namespace": "AWS/RDS", "MetricName": "ServerlessDatabaseCapacity",
        "Dimensions": [{"Name": "DBClusterIdentifier", "Value": cluster}],
        "StartTime": stamp(since), "EndTime": stamp(until),
        "Period": CAPACITY_PERIOD, "Statistics": ["Average", "Maximum"]},
        deadline=ctx.deadline(60))
    points = reply.get("Datapoints", [])
    total = sum(p["Average"] for p in points) * CAPACITY_PERIOD / 3600
    return {"acu_hours": round(total, 4), "datapoints": len(points),
            "window_minutes": round((until - since) / 60, 1),
            "max_acu": max((p["Maximum"] for p in points), default=None)}


def cost_section(ctx, clusters, *, since, until):
    """Compute at the captured ACU rate plus each cluster's fixed share of the window.

    A cluster's fixed cost is its managed master credential and its storage, prorated from
    the monthly figure the deploy cost guard already uses. Cost Explorer lags a day and cannot
    split one Aurora service line between two clusters, so this is a model on measured ACU
    hours and is labelled as one.
    """
    window_hours = (until - since) / 3600
    rows, total = {}, 0.0
    for label, cluster in clusters.items():
        measured = acu_hours(ctx, cluster, since=since, until=until)
        compute = measured["acu_hours"] * deploy.ACU_HOUR
        fixed = deploy.EXTRA_CLUSTER_MONTH_USD * window_hours / MONTH_HOURS
        rows[label] = {**measured, "compute_usd": round(compute, 4), "fixed_usd": round(fixed, 4)}
        total += compute + fixed
    return {"clusters": rows, "total_usd": round(total, 4),
            "window_hours": round(window_hours, 3),
            "fixed_month_usd_per_cluster": deploy.EXTRA_CLUSTER_MONTH_USD,
            "acu_hour_usd": deploy.ACU_HOUR,
            "basis": "model on CloudWatch average ACU per minute at the captured ACU rate; "
                     "Cost Explorer lags a day and cannot split one Aurora line between "
                     "clusters"}


# ---- the arm ----------------------------------------------------------------------------------
def once(proof, intent, key, action):
    """Run one section of the arm at most once across reruns of an interrupted arm."""
    done = intent.setdefault("sections", {})
    if key not in done:
        done[key] = action()
        proof.save()
    return done[key]


def arm(ctx, proof, intent, *, name, samples, pause_minutes, resume_timeout, load_seconds,
        concurrency, tail_minutes, overrides):
    if topology_of(ctx) != name:
        raise ProofError(
            f"This stack is {topology_of(ctx)}; the {name} arm needs a stack deployed with "
            f"--database-topology {name} (the topology cannot be changed on a live stack)")
    clusters = cluster_ids(ctx, **overrides)
    transport = ctx.sdk(ctx.scope)
    intent.setdefault("window_start", ctx.wall())
    proof.save()
    checkpoint = proof.checkpoint
    configured = {label: describe_scaling(ctx, c) for label, c in clusters.items()}
    # A cluster that pauses after N seconds cannot be seen paused sooner: wait N plus the
    # CloudWatch lag, however short the operator's default was.
    longest = max((c["seconds_until_auto_pause"] or 300) for c in configured.values())
    pause_minutes = max(pause_minutes, int(longest / 60) + 10)

    def cold():
        out = {}
        for label, cluster in clusters.items():
            still = wait_paused(ctx, {label: cluster}, minutes=pause_minutes,
                                checkpoint=checkpoint)
            if still:
                out[label] = {"measured": False,
                              "reason": "CloudWatch never showed 0 ACU within the wait"}
                continue
            domain = "processing" if label == "cluster" else label
            out[label] = cold_resume(ctx, transport, domain, timeout=resume_timeout)
        return out

    def warm():
        return {domain: measure_warm(ctx, transport, domain, samples) for domain in DOMAINS}

    cold_result = once(proof, intent, "cold_resume", cold)
    warm_result = once(proof, intent, "warm", warm)
    wake = once(proof, intent, "peer_wake", lambda: peer_wake(
        ctx, transport, clusters, load_seconds=load_seconds, concurrency=concurrency,
        pause_minutes=pause_minutes, checkpoint=checkpoint))
    slowdown = once(proof, intent, "peer_slowdown", lambda: peer_slowdown(
        ctx, transport, samples=samples, concurrency=concurrency))
    if tail_minutes and not intent.get("tail_done"):
        # The pause tail is billed; leave it inside the window so the cost is not flattered.
        end = ctx.clock() + 60 * tail_minutes
        while ctx.clock() < end:
            checkpoint("window")
            ctx.sleep(min(30, max(0.0, end - ctx.clock())))
        intent["tail_done"] = True
        proof.save()
    until = ctx.wall()
    cost = once(proof, intent, "cost", lambda: cost_section(
        ctx, clusters, since=intent["window_start"], until=until))
    measured = [r.get("measured") for r in cold_result.values()] + [
        wake.get("measured"), slowdown.get("measured")]
    public = {
        "arm": name, "clusters": len(clusters), "configured": configured,
        "cold_resume": cold_result, "warm": warm_result,
        "isolation": {"peer_wake": wake, "peer_slowdown": slowdown},
        "cost": cost, "notes": NOTES, "probe_path": "operator station -> Lambda invoke of the "
        "owner's ready probe (fresh connection, SELECT 1); includes the network path",
        "samples": samples,
    }
    failed = [d for d, s in warm_result.items() if s["failures"]]
    return {"status": PASS if all(measured) and not failed else (
        FAIL if failed else NOT_RUN), "public": public,
        "private": {"clusters": clusters}}


# ---- the verdict ------------------------------------------------------------------------------
def compare(proof):
    """The rule fixed in advance, applied to both arms. It never changes the default."""
    steps = proof.doc["steps"]
    for name in ARMS:
        if name not in steps:
            raise ProofError(f"The {name} arm has not been run for this run id")
    one, two = steps["shared"]["public"], steps["separate"]["public"]

    def number(value):
        return value if isinstance(value, (int, float)) else None

    shared_cold = number(one["cold_resume"].get("cluster", {}).get("resume_seconds"))
    separate_colds = [number(v.get("resume_seconds")) for v in two["cold_resume"].values()]
    shared_wake = one["isolation"]["peer_wake"]
    separate_wake = two["isolation"]["peer_wake"]
    shared_slow = number(one["isolation"]["peer_slowdown"].get("slowdown_p95"))
    separate_slow = number(two["isolation"]["peer_slowdown"].get("slowdown_p95"))
    warm_ratios = {}
    for domain in DOMAINS:
        a, b = number(one["warm"][domain]["p95_ms"]), number(two["warm"][domain]["p95_ms"])
        warm_ratios[domain] = round(b / a, 3) if a and b is not None else None
    delta_window = round(two["cost"]["total_usd"] - one["cost"]["total_usd"], 4)
    extra_compute = sum(r["compute_usd"] for r in two["cost"]["clusters"].values()) - sum(
        r["compute_usd"] for r in one["cost"]["clusters"].values())
    projected = round(deploy.EXTRA_CLUSTER_MONTH_USD + max(0.0, extra_compute), 4)
    rule = {
        "both_arms_fully_measured": all(
            v.get("measured") for arm_public in (one, two)
            for v in (*arm_public["cold_resume"].values(), arm_public["isolation"]["peer_wake"],
                      arm_public["isolation"]["peer_slowdown"])),
        "coupling_observed_when_shared": bool(shared_wake.get("peer_woken")) or (
            shared_slow is not None and shared_slow > MAX_PEER_SLOWDOWN),
        "separate_does_not_wake_the_peer": separate_wake.get("measured") is True
        and not separate_wake.get("peer_woken") and not separate_wake.get("same_cluster"),
        "separate_peer_slowdown_within_limit": separate_slow is not None
        and separate_slow <= MAX_PEER_SLOWDOWN,
        "separate_cold_resume_not_slower": shared_cold is not None and all(
            c is not None and c <= shared_cold + MAX_COLD_EXTRA_SECONDS for c in separate_colds),
        "separate_warm_p95_not_slower": all(
            r is not None and r <= MAX_WARM_P95_RATIO for r in warm_ratios.values()),
        "separate_extra_cost_within_limit": projected <= MAX_EXTRA_USD_PER_MONTH,
    }
    return {"public": {
        "shared": {"cold_resume_seconds": shared_cold, "warm_p95_ms": {
            d: one["warm"][d]["p95_ms"] for d in DOMAINS}, "peer_woken": shared_wake.get(
                "peer_woken"), "peer_slowdown_p95": shared_slow,
            "window_cost_usd": one["cost"]["total_usd"]},
        "separate": {"cold_resume_seconds": separate_colds, "warm_p95_ms": {
            d: two["warm"][d]["p95_ms"] for d in DOMAINS}, "peer_woken": separate_wake.get(
                "peer_woken"), "peer_slowdown_p95": separate_slow,
            "window_cost_usd": two["cost"]["total_usd"]},
        "warm_p95_ratio_separate_over_shared": warm_ratios,
        "window_cost_delta_usd": delta_window,
        "projected_extra_usd_per_month": projected,
        "projection_basis": "one more cluster's fixed monthly cost plus the measured extra ACU "
                            "compute of one such window; scale the window to the real usage",
        "decision_rule": rule,
        "limits": {"peer_slowdown": MAX_PEER_SLOWDOWN, "cold_extra_seconds":
                   MAX_COLD_EXTRA_SECONDS, "warm_p95_ratio": MAX_WARM_P95_RATIO,
                   "extra_usd_per_month": MAX_EXTRA_USD_PER_MONTH},
        "warrants_change": all(rule.values()),
        "default": "shared (V1) unless every rule above holds in a live run",
        "merge_decision": "pending",
    }}


def run(ctx, *, arm_name, samples=30, pause_minutes=30, resume_timeout=300, load_seconds=60,
        concurrency=4, tail_minutes=10, overrides=None):
    proof = ctx.proof(94, REQUIRED)
    if arm_name == "compare":
        proof.step("compare", lambda _intent: compare(proof), session=None)
        return proof
    if arm_name not in ARMS:
        raise ProofError("--arm is shared, separate or compare")
    if not 5 <= samples <= 200:
        raise ProofError("--samples is 5..200")
    if not 1 <= concurrency <= 8:
        raise ProofError("--load-concurrency is 1..8 (the account has 10 Lambda slots)")
    proof.step(arm_name, lambda intent: arm(
        ctx, proof, intent, name=arm_name, samples=samples, pause_minutes=pause_minutes,
        resume_timeout=resume_timeout, load_seconds=load_seconds, concurrency=concurrency,
        tail_minutes=tail_minutes, overrides=overrides or {}), session="window")
    return proof
