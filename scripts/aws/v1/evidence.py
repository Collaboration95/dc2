"""Cloud-proof evidence harnesses for issues #63-#67, one subcommand each.

    python -m scripts.aws.v1.evidence gateway  ...   #63 workflow and boundaries
    python -m scripts.aws.v1.evidence capacity ...   #64 1/2/3 encoders, recovery, DLQ
    python -m scripts.aws.v1.evidence release  ...   #65 promote, roll back, peer untouched
    python -m scripts.aws.v1.evidence latency  ...   #66 Fargate generator, cold wake apart
    python -m scripts.aws.v1.evidence spend    ...   #67 closed state, ACU pause, spend
    python -m scripts.aws.v1.evidence rehearse       offline: every harness vs the simulation
    python -m scripts.aws.v1.evidence counts         close-proof counts derived from receipts
    python -m scripts.aws.v1.evidence summary        redacted summary for docs/.../evidence/

Every harness writes a private JSON receipt (mode 0600) under `<state-dir>/evidence/`, skips a
step that already passed, refuses to start while the session journal says closed, and under
`--dry-run` runs against a simulated account whose receipts are marked SIMULATED and can never
be summarized. Run with the profile the deploy used (`dc2-project2-mfa`, or `dc2-agent` for the
dedicated agent IAM user) and the same `--state-dir`.
Exit code: 1 if a step run just now failed, else 0 (read `overall` for the full verdict).
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from scripts.aws.transport import OperationError
from scripts.aws.v1.proof import capacity, context, gateway, latency, release, sim, spend, summary
from scripts.aws.v1.proof.core import ProofError

REQUIRED = {"63": gateway.REQUIRED, "64": capacity.REQUIRED, "65": release.REQUIRED,
            "66": latency.REQUIRED, "67": spend.REQUIRED}
# The session state each harness needs when it starts (latency opens its own window).
SESSION = {"gateway": "open", "capacity": "open", "release": "window", "latency": "closed",
           "spend": "closed"}


def scope_arguments(parser):
    parser.add_argument("--profile", required=True,
                        help="e.g. dc2-agent or dc2-project2-mfa; never default")
    parser.add_argument("--region", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--state-dir", type=Path, help="the deploy's private state directory")
    parser.add_argument("--config", help="operator config (default: <state-dir>/operator-config)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="simulated account, throwaway receipts; proves nothing about AWS")
    parser.add_argument("--only", help="comma-separated step names to run")


def build_parser():
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.evidence", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gateway", help="#63")
    scope_arguments(g)
    g.add_argument("--fixture", type=Path, required=True, help="a short mp4 for the e2e job")
    g.add_argument("--skip-cross-database", metavar="REASON")
    g.add_argument("--job-timeout", type=int, default=900)
    g.add_argument("--minutes", type=int, default=45, help="session horizon for the encoder")
    c = sub.add_parser("capacity", help="#64")
    scope_arguments(c)
    c.add_argument("--fixture", type=Path, required=True, help="the long fixture (1+2+3 uploads)")
    c.add_argument("--short-fixture", type=Path, help="stored short source for the recovery step")
    c.add_argument("--workers", help="comma list of 1,2,3 (default all three)")
    c.add_argument("--poison", action="store_true", help="provoke one DLQ message (about 35 min)")
    c.add_argument("--job-timeout", type=int, default=1500)
    c.add_argument("--minutes", type=int, default=60)
    r = sub.add_parser("release", help="#65")
    scope_arguments(r)
    r.add_argument("--plan", type=Path, required=True, help="nonsecret release plan JSON")
    lat = sub.add_parser("latency", help="#66")
    scope_arguments(lat)
    lat.add_argument("--cluster", help="Aurora cluster id (default: from the deploy journal)")
    s = sub.add_parser("spend", help="#67")
    scope_arguments(s)
    s.add_argument("--closed-at", help="ISO time the session closed (pause is measured from it)")
    s.add_argument("--wait-minutes", type=int, default=30)
    s.add_argument("--since", help="YYYY-MM-DD for Cost Explorer (default: first of the month)")
    s.add_argument("--cluster")
    rh = sub.add_parser("rehearse", help="every harness against the simulation")
    rh.add_argument("--run-id", default="rehearsal")
    rh.add_argument("--release-plan", type=Path)
    for name in ("counts", "summary"):
        extra = sub.add_parser(name)
        extra.add_argument("--state-dir", type=Path, required=True)
        extra.add_argument("--run-id", required=True)
        if name == "summary":
            extra.add_argument("--out", type=Path, default=summary.EVIDENCE_DIR)
    return parser


def only(args):
    return set(args.only.split(",")) if getattr(args, "only", None) else None


def make_context(args, command, *, world, factory):
    if args.dry_run:
        return sim.build(args, session=SESSION[command], world=world)
    if factory:
        return factory(args)
    return context.live(args)



def execute(args, ctx):
    if args.command == "gateway":
        return gateway.run(ctx, fixture=args.fixture, skip_cross_database=args.skip_cross_database,
                           job_timeout=args.job_timeout, minutes=args.minutes, only=only(args))
    if args.command == "capacity":
        workers = {int(n) for n in args.workers.split(",")} if args.workers else None
        if workers and not workers <= {1, 2, 3}:
            raise ProofError("--workers takes 1, 2 and/or 3")
        return capacity.run(ctx, fixture=args.fixture, workers=workers,
                            short_fixture=args.short_fixture, poison=args.poison,
                            job_timeout=args.job_timeout, minutes=args.minutes, only=only(args))
    if args.command == "release":
        return release.run(ctx, plan_path=args.plan)
    if args.command == "latency":
        return latency.run(ctx, only=only(args), cluster=args.cluster)
    from datetime import date

    closed = None
    if args.closed_at:
        from scripts.aws.v1.proof.core import parse_time

        closed = parse_time(args.closed_at).timestamp()
    since = date.fromisoformat(args.since) if args.since else None
    return spend.run(ctx, only=only(args), closed_at=closed, wait_minutes=args.wait_minutes,
                     cluster=args.cluster, since=since)


def rehearse(args, stdout):
    """Every harness against fresh simulated worlds; nothing leaves the temp directory."""
    base = Path(tempfile.mkdtemp(prefix="dc2-rehearsal-"))
    base.chmod(0o700)
    fixture = base / "fixture.mp4"
    fixture.write_bytes(b"\0" * 4096)
    shared = argparse.Namespace(run_id=args.run_id, dry_run=True)
    reports, failed = {}, False
    runs = {
        "gateway": lambda ctx: gateway.run(ctx, fixture=fixture, minutes=30),
        "capacity": lambda ctx: capacity.run(ctx, fixture=fixture, short_fixture=fixture,
                                             minutes=30),
        "latency": lambda ctx: latency.run(ctx),
        "spend": lambda ctx: spend.run(ctx, wait_minutes=10),
    }
    if args.release_plan:
        runs["release"] = lambda ctx: release.run(ctx, plan_path=args.release_plan)
    for name, run in runs.items():
        world = sim.SimWorld(encode_seconds=240 if name == "capacity" else 45)
        ctx = sim.build(shared, session=SESSION[name], world=world, tmp=base / name)
        proof = run(ctx)
        reports[name] = proof.report()
        failed = failed or bool(proof.failed_now())
    note = ("simulated: nothing here is AWS evidence; receipts are SIMULATED and "
            "the summary writer refuses them")
    print(json.dumps({"mode": "simulated", "note": note, "harnesses": {
        k: {"overall": v["overall"], "steps": {n: s["status"] for n, s in v["steps"].items()}}
        for k, v in reports.items()}}, indent=2), file=stdout)
    return 1 if failed else 0


def main(argv=None, *, stdout=None, world=None, factory=None):
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.command == "rehearse":
            return rehearse(args, stdout)
        if args.command in {"counts", "summary"}:
            return post_process(args, stdout)
        if not args.dry_run and not args.state_dir:
            raise ProofError("--state-dir is required for a live run")
        ctx = make_context(args, args.command, world=world, factory=factory)
        proof = execute(args, ctx)
    except (OperationError, OSError, ValueError, KeyError) as error:
        message = str(error) if isinstance(error, OperationError) else type(error).__name__
        print(json.dumps({"ok": False, "error": message}), file=stdout)
        return 1
    print(json.dumps(proof.report(), indent=2), file=stdout)
    return 1 if proof.failed_now() else 0


def post_process(args, stdout):
    docs = summary.load(args.state_dir / "evidence", args.run_id)
    if args.command == "counts":
        path = summary.write_counts(args.state_dir, docs)
        print(json.dumps({"counts_file": str(path), "counts": summary.counts(docs),
                          "attestation": "derived from the receipts' terminal outcomes; the "
                                         "operator attests no other attempt ran on this stack"},
                         indent=2), file=stdout)
        return 0
    import time

    built = summary.build(docs, REQUIRED, args.run_id, wall=time.time)
    path = summary.write(built, args.out)
    print(json.dumps({"summary": str(path), "overall": {
        k: v["overall"] for k, v in built["issues"].items()}}, indent=2), file=stdout)
    return 0


if __name__ == "__main__":
    # Re-import under the package name so the harnesses share one set of module objects.
    from scripts.aws.v1.evidence import main as package_main

    raise SystemExit(package_main())
