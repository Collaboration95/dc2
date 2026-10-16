"""CLI for booked V1 sessions: python -m scripts.aws.v1.session ACTION --profile P --region R.

Actions: init (one-time private journal), open, close, batch, status. Live runs need an
explicit --profile, --region and --account; --dry-run prints the calls that would be
made against an offline simulation and touches neither AWS nor the real journal.
"""

import argparse
import json
import os
import sys
import time

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1 import operations
from scripts.aws.v1.hooks import AttemptCounts, OwnerHooks, file_reader, sql_reader
from scripts.aws.v1.session import Session

ZERO = dict.fromkeys(("queued", "processing", "succeeded", "failed", "abandoned", "cancelled"), 0)


def build_hooks(data, hook_names, transport, *, dry_run):
    """Real hooks over the transport; dry-run swaps only the SQL reader for zero counts."""
    owner = OwnerHooks(transport, **hook_names)
    if dry_run:
        reader = lambda _deadline: dict(ZERO)  # noqa: E731
    elif data.get("sql"):
        reader = sql_reader(data["sql"]["dsn_file"], data["sql"]["ca_file"])
    elif data.get("counts_file"):
        reader = file_reader(data["counts_file"])
    else:
        reader = None
    return owner, AttemptCounts(reader) if reader else None


def run_action(args, session, data, hook_names, transport, deadline):
    owner, counts = build_hooks(data, hook_names, transport, dry_run=args.dry_run)
    if args.action == "open":
        return session.open(ready=owner.ready, repair=owner.repair, deadline=deadline)
    if args.action == "close":
        if counts is None:
            raise OperationError("Close needs SQL or operator counts (config sql/counts_file)")
        return session.close(drain=counts.drain, outcomes=counts.outcomes, deadline=deadline)
    if args.action == "status":
        return session.status(deadline=deadline)
    session.config["session_end_epoch"] = time.time() + 60 * args.minutes
    return {"tasks": session.batch(count=args.count, deadline=deadline)}


def main(argv=None, *, environ=None, transport_factory=None, stdout=None):
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.session", description=__doc__)
    parser.add_argument("action", choices=["init", "open", "close", "batch", "status"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--count", type=int, default=1, help="batch: encoder tasks (1..3)")
    parser.add_argument("--minutes", type=int, default=60, help="batch: session end horizon")
    parser.add_argument("--confirm-empty", action="store_true", help="init: inventory is empty")
    parser.add_argument("--confirm-exclusive", action="store_true", help="init: sole station")
    operations.add_scope_arguments(parser)
    args = parser.parse_args(argv)
    scope = operations.resolve_scope(parser, args, environ)
    plan = holder = None
    try:
        data, config, hook_names, _ = operations.load_operator_config(args.config)
        if args.dry_run:
            plan = operations.PlanTransport()
            holder = operations.PlanJournal(
                config, session="open" if args.action == "batch" else "closed"
            )
            transport, journal = plan, holder.journal
        else:
            transport = (transport_factory or operations.live_transport)(scope)
            journal = Journal(
                data["journal"],
                station=data["operator_station"],
                environment=data["environment_id"],
            )
        if args.action == "init":
            if not args.dry_run:
                journal.initialize(
                    verified_empty=args.confirm_empty, exclusive_station=args.confirm_exclusive
                )
            result = {"journal": "planned" if args.dry_run else "initialized"}
        else:
            session = Session(config, transport, journal)
            deadline = time.monotonic() + args.deadline_seconds
            result = run_action(args, session, data, hook_names, transport, deadline)
    except OperationError as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=stdout)
        return 1
    finally:
        if holder:
            holder.cleanup()
    output = {"ok": True, "scope": {**scope, "mode": "dry-run" if args.dry_run else "live"}}
    if plan:
        output["simulated"] = "offline state; quota, readiness and SQL results are assumed"
        output["planned_calls"] = plan.calls
    output["result"] = result
    print(json.dumps(output, indent=2, default=str), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
