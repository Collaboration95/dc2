"""CLI for booked V1 sessions: python -m scripts.aws.v1.session ACTION --profile P --region R.

Actions: init (one-time private journal), open, window (public API only, for release
smoke tests), close, batch, status. `close --in-vpc-counts` reads the drain proof's attempt
counts with a finite task inside the VPC (the owner's migration definition), so it needs neither
a SQL station nor an attested counts file; Aurora must be awake or resumable (about 150 s).
`open --unattended` additionally opts the session into the V2 unattended launcher (#68) until
--minutes from now; `close` always switches it off first.
Live runs need an explicit --profile, --region and --account; --dry-run prints the calls
that would be made against an offline simulation and touches neither AWS nor the real journal.
"""

import argparse
import json
import os
import sys
import time

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1 import operations
from scripts.aws.v1.hooks import (
    AttemptCounts,
    LauncherHooks,
    OwnerHooks,
    file_reader,
    sql_reader,
)
from scripts.aws.v1.session import Session
from scripts.aws.v1.vpc_reader import VpcReader

ZERO = dict.fromkeys(("queued", "processing", "succeeded", "failed", "abandoned", "cancelled"), 0)


def build_hooks(data, hook_names, transport, *, dry_run, config=None, in_vpc=False,
                clock=time.monotonic, sleep=time.sleep):
    """Real hooks over the transport; dry-run swaps only the counts reader for zero counts."""
    owner = OwnerHooks(transport, **hook_names, clock=clock, sleep=sleep)
    if dry_run:
        reader = lambda _deadline: dict(ZERO)  # noqa: E731
    elif in_vpc:
        reader = VpcReader(config, transport, clock=clock, sleep=sleep).attempt_counts
    elif data.get("sql"):
        reader = sql_reader(data["sql"]["processing_dsn_file"], data["sql"]["ca_file"])
    elif data.get("counts_file"):
        reader = file_reader(data["counts_file"])
    else:
        reader = None
    return owner, AttemptCounts(reader, clock=clock, sleep=sleep) if reader else None


def run_action(args, session, data, hook_names, transport, deadline, *, clock=time.monotonic,
               sleep=time.sleep):
    owner, counts = build_hooks(
        data, hook_names, transport, dry_run=args.dry_run, config=session.config,
        in_vpc=args.in_vpc_counts, clock=clock, sleep=sleep)
    if args.action in {"open", "window"}:
        unattended = args.action == "open" and args.unattended
        return session.open(
            ready=owner.ready,
            repair=owner.repair,
            intake_ready=owner.intake_ready,
            deadline=deadline,
            window=args.action == "window",
            launcher=LauncherHooks(owner, clock=clock, sleep=sleep) if unattended else None,
            launcher_session_end=time.time() + 60 * args.minutes if unattended else None,
        )
    if args.action == "close":
        if counts is None:
            raise OperationError(
                "Close needs SQL or operator counts (config sql/counts_file), or --in-vpc-counts")
        return session.close(
            drain=counts.drain,
            outcomes=counts.outcomes,
            deadline=deadline,
            # Whenever the stack has a launcher, close disables its flag, not only its rule.
            launcher=(LauncherHooks(owner, clock=clock, sleep=sleep)
                      if session.config.get("launcher") else None),
        )
    if args.action == "status":
        return session.status(deadline=deadline)
    session.config["session_end_epoch"] = time.time() + 60 * args.minutes
    return {"tasks": session.batch(count=args.count, deadline=deadline)}


def run_dlq(args, urls, sqs_factory, scope):
    """Delegate to the shared delivery.dlq helper; never duplicate its inspect/redrive logic.

    Inspect prints identities only. Redrive moves messages back to their source queue and
    so needs an explicit confirmation and, like a live run, a verified identity.
    """
    from delivery import dlq

    if not args.queue:
        raise OperationError("dlq needs --queue")
    target = urls["dlq"][args.queue]
    needed = target["url"] if args.dlq_command == "inspect" else target["arn"]
    if not needed:
        raise OperationError("Stack outputs lack this DLQ; re-render the V1 template")
    if args.dlq_command == "redrive" and not args.confirm_redrive and not args.dry_run:
        raise OperationError("Redrive requires --confirm-redrive after inspecting the DLQ")
    if not 1 <= args.limit <= 50:
        raise OperationError("--limit must be 1..50")
    if args.dry_run:
        return {"would_run": f"delivery.dlq {args.dlq_command}", "queue": args.queue}
    client = sqs_factory(scope)
    if args.dlq_command == "inspect":
        return dlq.inspect(client, target["url"], limit=args.limit)
    if args.dlq_command == "redrive":
        return {"task_handle": dlq.redrive(client, target["arn"])}
    return dlq.status(client, target["arn"])


def main(argv=None, *, environ=None, transport_factory=None, sqs_factory=None, stdout=None,
         clock=time.monotonic, sleep=time.sleep):
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.session", description=__doc__)
    actions = ["init", "open", "window", "close", "batch", "status", "dlq"]
    parser.add_argument("action", choices=actions)
    parser.add_argument("--config", required=True)
    parser.add_argument("--count", type=int, default=1, help="batch: encoder tasks (1..3)")
    parser.add_argument(
        "--minutes", type=int, default=60, help="batch / open --unattended: session end horizon"
    )
    parser.add_argument(
        "--unattended", action="store_true", help="open: let the launcher start encoders (V2)"
    )
    parser.add_argument("--queue", choices=operations.QUEUES, help="dlq: which queue's DLQ")
    parser.add_argument("--dlq-command", choices=["inspect", "status", "redrive"], default="status")
    parser.add_argument("--limit", type=int, default=10, help="dlq inspect: messages (1..50)")
    parser.add_argument("--confirm-redrive", action="store_true", help="dlq redrive writes")
    parser.add_argument("--in-vpc-counts", action="store_true",
                        help="close: read attempt counts with a finite in-VPC task, not a "
                             "SQL station or an attested counts file")
    parser.add_argument("--confirm-empty", action="store_true", help="init: inventory is empty")
    parser.add_argument("--confirm-exclusive", action="store_true", help="init: sole station")
    operations.add_scope_arguments(parser)
    args = parser.parse_args(argv)
    if args.unattended and args.action != "open":
        parser.error("--unattended applies to `open` only")
    if args.in_vpc_counts and args.action != "close":
        parser.error("--in-vpc-counts applies to `close` only")
    scope = operations.resolve_scope(parser, args, environ)
    plan = holder = None
    try:
        data, config, hook_names, urls = operations.load_operator_config(args.config)
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
        if args.action == "dlq":
            result = run_dlq(args, urls, sqs_factory or operations.live_sqs_client, scope)
        elif args.action == "init":
            if not args.dry_run:
                journal.initialize(
                    verified_empty=args.confirm_empty, exclusive_station=args.confirm_exclusive
                )
            result = {"journal": "planned" if args.dry_run else "initialized"}
        else:
            session = Session(config, transport, journal, clock=clock, sleep=sleep)
            deadline = clock() + args.deadline_seconds
            result = run_action(args, session, data, hook_names, transport, deadline, clock=clock,
                                sleep=sleep)
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
