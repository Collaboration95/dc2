"""#67: closed state, Aurora pause, Cost Explorer by service, and the teardown receipt.

Four separate observations, none inferred from another:

* close-state: a read-only `Session.status` plus a task inventory after `session close`.
* pause: CloudWatch `ServerlessDatabaseCapacity` reaching 0, found by watching the metric, with
  every later non-zero datapoint counted (maintenance or a request waking the database is
  reported, not hidden). Engine support for minimum 0 ACU is not proof the cluster pauses.
* cost-explorer: month-to-date by service. It lags about a day and is flagged estimated; it is a
  reconciliation input, not an invoice.
* teardown-receipt: the pipeline's own `resources_remaining` receipt, read back.

Nothing here writes to AWS.
"""

import datetime as dt
import json

from scripts.aws.v1 import deploy
from scripts.aws.v1.proof import workflow
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, parse_time, stamp

REQUIRED = ("close-state", "pause", "cost-explorer", "teardown-receipt")
BUDGET_ALERT_USD, PLANNING_ENVELOPE_USD, TRIAL_ALLOWANCE_USD = 30.0, 200.0, 5.0
# Cost Explorer service names -> the V1 cost model's line items.
CATEGORIES = (
    ("Relational Database", "aurora"), ("Lambda", "lambda"),
    ("Elastic Container Service", "fargate"), ("Container Registry", "ecr"),
    ("Simple Storage", "s3"), ("CloudFront", "cloudfront"), ("Queue", "sqs"),
    ("API Gateway", "api_gateway"), ("Secrets Manager", "managed_credentials"),
    ("CloudWatch", "logs_and_metrics"), ("EC2 - Other", "ipv4_and_network"),
    ("Virtual Private Cloud", "ipv4_and_network"), ("Systems Manager", "ssm"),
    ("Key Management", "kms"),
)
ALLOWED_REMAINING = {"aurora-snapshot"}


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def cluster_id(ctx, override=None):
    """The Aurora cluster this run created, from the deploy journal (never guessed)."""
    if override:
        return override
    path = ctx.state_dir / "deploy-journal.json"
    journal = deploy.DeployJournal(path, station=ctx.data["operator_station"],
                                   environment=ctx.data["environment_id"])
    if not journal.exists():
        raise ProofError("No deploy journal in the state directory; pass --cluster")
    found = journal.view()["resources"].get("db_clusters", [])
    if len(found) != 1:
        raise ProofError("Expected exactly one Aurora cluster in the deploy journal")
    return found[0]


def capacity_series(ctx, cluster, *, since_epoch):
    """ServerlessDatabaseCapacity datapoints at one-minute resolution, oldest first."""
    reply = ctx.aws.call("cloudwatch", "get-metric-statistics", {
        "Namespace": "AWS/RDS", "MetricName": "ServerlessDatabaseCapacity",
        "Dimensions": [{"Name": "DBClusterIdentifier", "Value": cluster}],
        "StartTime": stamp(since_epoch), "EndTime": stamp(ctx.wall() + 60), "Period": 60,
        "Statistics": ["Minimum", "Maximum"]}, deadline=ctx.deadline(60))
    points = [(parse_time(p["Timestamp"]), p["Minimum"], p["Maximum"])
              for p in reply.get("Datapoints", [])]
    return sorted(points)


def paused_now(ctx, cluster, *, minutes=10):
    """True only if the newest datapoint says capacity 0; None when there are no datapoints."""
    series = capacity_series(ctx, cluster, since_epoch=ctx.wall() - 60 * minutes)
    return None if not series else series[-1][2] == 0


def paused_since(series):
    """When the trailing run of zero-capacity datapoints began; None if capacity is above 0."""
    if not series or series[-1][2] != 0:
        return None
    start = series[-1][0]
    for moment, _, high in reversed(series):
        if high != 0:
            break
        start = moment
    return start


def close_state(ctx):
    from scripts.aws.v1.session import Session

    transport = ctx.sdk(ctx.scope)
    session = Session(ctx.config, transport, ctx.journal, clock=ctx.clock, sleep=ctx.sleep)
    status = session.status(deadline=ctx.deadline(120))
    live = workflow.live_tasks(ctx)
    observed = status["observed"]
    mappings = sorted(set(observed["mappings"].values()))
    rules = sorted(set(observed["schedules"].values()))
    edge = observed.get("edge_throttle") or {}
    reserved = [n for n, v in observed["functions"].items() if v not in {"unreserved", 0}]
    public = {
        "journal_session": status["journal_session"], "drift": len(status["drift"]),
        "mappings": mappings, "schedules": rules,
        "edge_rate": edge.get("ThrottlingRateLimit"),
        "edge_burst": edge.get("ThrottlingBurstLimit"),
        "functions_with_reservation": len(reserved), "tasks_running": len(live),
        "database_pause": status["database_pause"],
    }
    ok = (status["journal_session"] == "closed" and not status["drift"]
          and mappings in ([], ["Disabled"]) and rules in ([], ["DISABLED"])
          and not edge.get("ThrottlingRateLimit") and not live)
    return verdict(ok, public)


def pause(ctx, *, closed_at, wait_minutes, override=None):
    cluster = cluster_id(ctx, override)
    described = ctx.aws.call("rds", "describe-db-clusters", {"DBClusterIdentifier": cluster},
                             deadline=ctx.deadline(60))["DBClusters"][0]
    scaling = described.get("ServerlessV2ScalingConfiguration", {})
    since = closed_at if closed_at is not None else ctx.wall() - 3600
    end = ctx.clock() + 60 * wait_minutes
    while True:
        series = capacity_series(ctx, cluster, since_epoch=since)
        first = paused_since(series)
        if first is not None or ctx.clock() >= end:
            break
        ctx.sleep(60)
    wakeups = sum(1 for (_, _, before), (_, _, now) in zip(series, series[1:], strict=False)
                  if before == 0 and now > 0)
    public = {
        "configured_min_acu": scaling.get("MinCapacity"),
        "configured_max_acu": scaling.get("MaxCapacity"),
        "seconds_until_auto_pause": scaling.get("SecondsUntilAutoPause"),
        "pause_observed": first is not None, "datapoints": len(series),
        "max_acu_since_close": max((h for _, _, h in series), default=None),
        "wakeups_in_window": wakeups,
        "minutes_from_close_to_zero": round((first.timestamp() - since) / 60, 1)
        if first and closed_at is not None else None,
        "database_pause": "OBSERVED" if first else "NOT_OBSERVED",
    }
    return verdict(first is not None and scaling.get("MinCapacity") == 0, public)


def category(service):
    for needle, name in CATEGORIES:
        if needle in service:
            return name
    return "other"


def cost_explorer(ctx, *, since):
    today = dt.datetime.fromtimestamp(ctx.wall(), dt.UTC).date()
    start = since or today.replace(day=1)
    reply = ctx.aws.call("ce", "get-cost-and-usage", {
        "TimePeriod": {"Start": start.isoformat(), "End": (today + dt.timedelta(days=1)
                                                           ).isoformat()},
        "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}]}, deadline=ctx.deadline(60))
    by_service, units, estimated = {}, set(), False
    for period in reply.get("ResultsByTime", []):
        estimated = estimated or bool(period.get("Estimated"))
        for group in period.get("Groups", []):
            cost = group["Metrics"]["UnblendedCost"]
            units.add(cost["Unit"])
            by_service[group["Keys"][0]] = by_service.get(group["Keys"][0], 0.0) + float(
                cost["Amount"])
    totals = {}
    for service, amount in by_service.items():
        totals[category(service)] = round(totals.get(category(service), 0.0) + amount, 4)
    total = round(sum(by_service.values()), 2)
    public = {
        "currency": sorted(units)[0] if len(units) == 1 else "MIXED",
        "from": start.isoformat(), "through_inclusive": today.isoformat(),
        "complete_through": (today - dt.timedelta(days=1)).isoformat(),
        "estimated": True, "cost_explorer_flagged_estimated": estimated, "final": False,
        "total": total, "by_model_line": dict(sorted(totals.items())),
        "services": len(by_service),
        "within_monthly_alert": total <= BUDGET_ALERT_USD,
        "within_planning_envelope": total <= PLANNING_ENVELOPE_USD,
        "within_trial_allowance": total <= TRIAL_ALLOWANCE_USD,
        "planned_deploy_window_model": deploy.planned_cost(3),
        "invoice": "NOT_RUN: Cost Explorer lags ~24 h; attach invoice lines by hand",
    }
    return verdict(len(units) <= 1 and bool(reply.get("ResultsByTime")), public,
                   # Pairs, not a mapping: a service name such as "Secrets Manager" would trip
                   # the receipt's secret-key screen if used as a key.
                   {"by_service": [[k, round(v, 4)] for k, v in sorted(by_service.items())]})


def teardown_receipt(ctx):
    path = ctx.state_dir / f"teardown-receipt-{ctx.run_id}.json"
    if not path.exists():
        return {"status": NOT_RUN, "public": {"reason": "teardown has not run for this run id"}}
    receipt = json.loads(path.read_text())
    remaining = receipt.get("resources_remaining", [])
    kinds = {}
    for item in remaining:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    explained = all(item.get("why") for item in remaining)
    public = {
        "receipt_status": receipt.get("status"), "remaining_by_kind": dict(sorted(kinds.items())),
        "all_remaining_explained": explained,
        "skipped_not_owned": len(receipt.get("skipped_not_owned", [])),
        "pre_existing_untouched": len(receipt.get("pre_existing_untouched", [])),
        "final_snapshot_kept": bool(receipt.get("final_snapshot")),
        "from_simulation": bool(receipt.get("simulated")),
    }
    ok = (not receipt.get("simulated") and explained and set(kinds) <= ALLOWED_REMAINING
          and receipt.get("status") in {"CLEAN", "ITEMS_REMAIN"})
    return verdict(ok, public)


def run(ctx, *, only=None, closed_at=None, wait_minutes=30, cluster=None, since=None):
    proof = ctx.proof(67, REQUIRED)
    steps = (
        ("close-state", "closed", lambda i: close_state(ctx)),
        ("pause", "closed", lambda i: pause(ctx, closed_at=closed_at, wait_minutes=wait_minutes,
                                            override=cluster)),
        ("cost-explorer", None, lambda i: cost_explorer(ctx, since=since)),
        ("teardown-receipt", None, lambda i: teardown_receipt(ctx)),
    )
    for name, kind, action in steps:
        if only and name not in only:
            continue
        # Cost data is refreshed on demand: a later day has more usage in it.
        proof.step(name, action, session=kind, rerun=name == "cost-explorer")
    return proof
