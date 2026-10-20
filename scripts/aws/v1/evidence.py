"""Cloud-proof evidence harnesses for issues #63-#67, one subcommand each.

    python -m scripts.aws.v1.evidence gateway  ...   #63 workflow and boundaries
    python -m scripts.aws.v1.evidence capacity ...   #64 1/2/3 encoders, recovery, DLQ
    python -m scripts.aws.v1.evidence capacity --backlog N ...   #185 backlog jobs/min at cap 1/2/3
    python -m scripts.aws.v1.evidence isolation ...  #196 Media accepts uploads, Processing down
    python -m scripts.aws.v1.evidence security ...   #229 cross-owner, tampered URLs, size, ports
    python -m scripts.aws.v1.evidence unattended ... #68 (V2) launcher vs operator batches
    python -m scripts.aws.v1.evidence release  ...   #65 promote, roll back, peer untouched
    python -m scripts.aws.v1.evidence release-plan   write #65's plan.json for a deployed stack
    python -m scripts.aws.v1.evidence latency  ...   #66 Fargate generator, cold wake apart
    python -m scripts.aws.v1.evidence spend    ...   #67 closed state, ACU pause, spend
    python -m scripts.aws.v1.evidence short-encode   #93 (V2) Lambda short encodes vs Fargate
    python -m scripts.aws.v1.evidence db-topology    #94 (V2) shared vs separate Aurora clusters
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
from scripts.aws.v1.proof import (
    capacity,
    context,
    db_topology,
    gateway,
    isolation,
    latency,
    release,
    release_plan,
    security,
    short_encode,
    sim,
    spend,
    summary,
    unattended,
)
from scripts.aws.v1.proof.core import ProofError

REQUIRED = {
    "63": gateway.REQUIRED,
    "64": capacity.REQUIRED,
    "65": release.REQUIRED,
    "66": latency.REQUIRED,
    "67": spend.REQUIRED,
    "185": capacity.BACKLOG_REQUIRED,
    "196": isolation.REQUIRED,
    "68": unattended.REQUIRED,
    "229": security.REQUIRED,
}
# The session state each harness needs when it starts (latency opens its own window).
SESSION = {
    "gateway": "open",
    "capacity": "open",
    "capacity-backlog": "open",
    "isolation": "open",
    "unattended": "open",
    "security": "open",
    "release": "window",
    "latency": "closed",
    "release-plan": "closed",
    "spend": "closed",
    "short-encode": "open",
    "db-topology": "window",
}


def scope_arguments(parser):
    parser.add_argument(
        "--profile", required=True, help="e.g. dc2-agent or dc2-project2-mfa; never default"
    )
    parser.add_argument("--region", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--state-dir", type=Path, help="the deploy's private state directory")
    parser.add_argument("--config", help="operator config (default: <state-dir>/operator-config)")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="simulated account, throwaway receipts; proves nothing about AWS",
    )
    parser.add_argument("--only", help="comma-separated step names to run")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="latency (#66) and security (#229, with --only, never setup-job): "
        "rerun the steps selected by --only (all steps "
        "without it) as new "
        "attempts: the old receipt entry and intent are archived under "
        "`attempts` and a new task or request is minted. Without it PASS "
        "and NOT_RUN are final",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="scripts.aws.v1.evidence",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    c.add_argument(
        "--backlog",
        type=int,
        metavar="N",
        nargs="?",
        const=capacity.DEFAULT_BACKLOG,
        help="#185 instead of the 1/2/3 runs: submit N identical clips per cap and "
        "drain them at encoder cap 1, 2 and 3 (bare flag: "
        f"{capacity.DEFAULT_BACKLOG}); --fixture is the clip, receipt "
        "evidence-185",
    )
    c.add_argument(
        "--drain-timeout",
        type=int,
        default=capacity.DRAIN_TIMEOUT,
        help="--backlog only: seconds allowed per cap before the step stops its encoders and fails",
    )
    iso = sub.add_parser("isolation", help="#196: Media accepts uploads while Processing is down")
    scope_arguments(iso)
    iso.add_argument("--fixture", type=Path, required=True, help="a short mp4 for the one upload")
    iso.add_argument(
        "--job-timeout",
        type=int,
        default=900,
        help="the gate: seconds from re-enabling the consumer to the job being done",
    )
    iso.add_argument(
        "--hold-seconds",
        type=int,
        default=isolation.HOLD_SECONDS,
        help="longest the consumer stays off waiting for the command to reach the queue",
    )
    iso.add_argument("--minutes", type=int, default=60, help="session horizon for the encoder")
    sec = sub.add_parser("security", help="#229: cross-owner, tampered URLs, size, port scan")
    scope_arguments(sec)
    sec.add_argument("--fixture", type=Path, required=True, help="a short mp4 for user A's upload")
    sec.add_argument("--job-timeout", type=int, default=900)
    sec.add_argument("--minutes", type=int, default=45, help="session horizon for the encoder")
    sec.add_argument(
        "--max-expiry-wait",
        type=int,
        default=security.EXPIRY_WAIT,
        help="longest to wait for a signed URL or upload grant to expire; both live "
        "15 minutes, so the expiry steps are NOT_RUN unless this is about 930 "
        "or more",
    )
    sec.add_argument(
        "--full-size-limit",
        action="store_true",
        help="also upload 100 MiB plus one byte to storage (about 100 MiB of bandwidth)",
    )
    un = sub.add_parser("unattended", help="#68 (V2): the launcher against operator batches")
    scope_arguments(un)
    un.add_argument("--fixture", type=Path, required=True, help="the same clip as the baseline")
    un.add_argument(
        "--backlog",
        type=int,
        metavar="N",
        help="clips to upload (default: the #185 baseline's N, which it must equal)",
    )
    un.add_argument(
        "--drain-timeout",
        type=int,
        default=capacity.DRAIN_TIMEOUT,
        help="seconds allowed for every job to finish",
    )
    un.add_argument(
        "--settle-seconds",
        type=int,
        default=unattended.SETTLE_SECONDS,
        help="how long to watch for a start after the backlog emptied",
    )
    un.add_argument(
        "--iam-simulated",
        action="store_true",
        help="attest that `aws iam simulate-principal-policy` passed for the "
        "launcher role (runbook, 'Unattended launcher')",
    )
    r = sub.add_parser("release", help="#65")
    scope_arguments(r)
    r.add_argument("--plan", type=Path, required=True, help="nonsecret release plan JSON")
    rp = sub.add_parser("release-plan", help="#65: write plan.json and its bundles")
    scope_arguments(rp)
    rp.add_argument("--owner", choices=("media", "processing"))
    rp.add_argument(
        "--baseline-evidence",
        type=Path,
        help="build_and_verify evidence of the images the stack runs now",
    )
    rp.add_argument("--good-run-id", help="images pushed as <id>-media/-processing/-worker")
    rp.add_argument("--good-evidence", type=Path, help="build evidence of the good images")
    rp.add_argument("--bad-run-id", help="optional: images that must fail the public smoke")
    rp.add_argument("--bad-evidence", type=Path)
    rp.add_argument(
        "--tests-passed", type=int, help="source tests that passed for these builds (attested)"
    )
    rp.add_argument("--target-revision", help="the owner's schema head (default: this checkout)")
    rp.add_argument(
        "--attest-schema-unchanged",
        action="store_true",
        help="good/baseline/bad add no migration beyond --target-revision",
    )
    rp.add_argument(
        "--accept-unfixed",
        type=Path,
        metavar="FILE",
        help="audited JSON list of HIGH/CRITICAL CVE ids with no fix available",
    )
    rp.add_argument(
        "--out", type=Path, help="directory for plan.json (default: <state-dir>/release)"
    )
    rp.add_argument(
        "--deregister",
        type=Path,
        metavar="PLAN",
        help="instead: retire the definition revisions that plan registered",
    )
    lat = sub.add_parser("latency", help="#66")
    scope_arguments(lat)
    lat.add_argument("--cluster", help="Aurora cluster id (default: from the deploy journal)")
    lat.add_argument(
        "--pause-wait-minutes",
        type=int,
        default=latency.PAUSE_WAIT_SECONDS // 60,
        help="how long cold-wake waits for CloudWatch to show 0 ACU before NOT_RUN",
    )
    s = sub.add_parser("spend", help="#67")
    scope_arguments(s)
    s.add_argument("--closed-at", help="ISO time the session closed (pause is measured from it)")
    s.add_argument("--wait-minutes", type=int, default=30)
    s.add_argument("--since", help="YYYY-MM-DD for Cost Explorer (default: first of the month)")
    s.add_argument("--cluster")
    se = sub.add_parser("short-encode", help="#93 (V2): Lambda short encodes vs Fargate")
    scope_arguments(se)
    se.add_argument(
        "--arm",
        choices=("fargate", "lambda", "compare"),
        required=True,
        help="fargate on a stack WITHOUT the lane, lambda WITH it, then compare",
    )
    se.add_argument("--fixture", type=Path, help="the one short fixed mp4, same for both arms")
    se.add_argument("--fixture-seconds", type=float, help="that fixture's real duration")
    se.add_argument("--jobs", type=int, default=5, help="jobs per arm: 1 cold, the rest warm")
    se.add_argument(
        "--idle-minutes",
        type=int,
        default=20,
        help="idle time before the Lambda cold job (0 = no wait; coldness unlikely)",
    )
    se.add_argument("--job-timeout", type=int, default=900)
    se.add_argument("--minutes", type=int, default=60, help="session horizon for Fargate tasks")
    db = sub.add_parser("db-topology", help="#94 (V2): shared vs separate Aurora clusters")
    scope_arguments(db)
    db.add_argument(
        "--arm",
        choices=("shared", "separate", "compare"),
        required=True,
        help="the stack's own topology, then compare the two receipts",
    )
    db.add_argument("--samples", type=int, default=30, help="timed ready probes per domain")
    db.add_argument(
        "--pause-wait-minutes",
        type=int,
        default=30,
        help="how long to wait for CloudWatch to show 0 ACU (raised automatically "
        "for a longer auto-pause)",
    )
    db.add_argument("--resume-timeout", type=int, default=300, help="seconds allowed for a resume")
    db.add_argument("--load-seconds", type=int, default=60, help="peer load held for the wake test")
    db.add_argument("--load-concurrency", type=int, default=4, help="parallel Media probes")
    db.add_argument(
        "--tail-minutes",
        type=int,
        default=10,
        help="idle minutes kept inside the cost window so the pause tail is billed",
    )
    db.add_argument("--cluster", help="the shared cluster id (default: the deploy journal)")
    db.add_argument("--media-cluster")
    db.add_argument("--processing-cluster")
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
        if command == "db-topology" and world is None:
            # The simulation must be the layout the arm names, or the arm refuses it.
            world = sim.SimWorld(database="separate" if args.arm == "separate" else "shared")
        return sim.build(args, session=SESSION[command], world=world)
    if factory:
        return factory(args)
    return context.live(args)


def release_plan_command(args, *, world, factory):
    if args.dry_run:
        raise ProofError(
            "release-plan reads the deploy journal and the registry and has no "
            "simulation; `rehearse` exercises it against the simulated account"
        )
    ctx = make_context(args, "release-plan", world=world, factory=factory)
    if args.deregister:
        return release_plan.deregister(ctx, args.deregister)
    missing = [
        name
        for name in ("owner", "baseline_evidence", "good_run_id", "good_evidence", "tests_passed")
        if getattr(args, name) is None
    ]
    if missing or bool(args.bad_run_id) != bool(args.bad_evidence):
        raise ProofError(
            "release-plan needs --owner --baseline-evidence --good-run-id "
            "--good-evidence --tests-passed (and --bad-run-id with --bad-evidence)"
        )
    bad = None
    if args.bad_run_id:
        bad = {"run_id": args.bad_run_id, "evidence": args.bad_evidence}
    return release_plan.run(
        ctx,
        owner=args.owner,
        baseline_evidence=args.baseline_evidence,
        good={"run_id": args.good_run_id, "evidence": args.good_evidence},
        bad=bad,
        tests_passed=args.tests_passed,
        target_revision=args.target_revision,
        attest_schema_unchanged=args.attest_schema_unchanged,
        accept_unfixed=args.accept_unfixed,
        out=args.out or args.state_dir / "release",
    )


def execute(args, ctx):
    if args.command == "gateway":
        return gateway.run(
            ctx,
            fixture=args.fixture,
            skip_cross_database=args.skip_cross_database,
            job_timeout=args.job_timeout,
            minutes=args.minutes,
            only=only(args),
        )
    if args.command == "capacity":
        workers = {int(n) for n in args.workers.split(",")} if args.workers else None
        if workers and not workers <= {1, 2, 3}:
            raise ProofError("--workers takes 1, 2 and/or 3")
        if args.backlog is not None:
            if args.short_fixture or args.poison:
                raise ProofError("--backlog does not combine with --short-fixture or --poison")
            return capacity.run_backlog(
                ctx,
                fixture=args.fixture,
                backlog=args.backlog,
                workers=workers,
                minutes=args.minutes,
                drain_timeout=args.drain_timeout,
                only=only(args),
            )
        return capacity.run(
            ctx,
            fixture=args.fixture,
            workers=workers,
            short_fixture=args.short_fixture,
            poison=args.poison,
            job_timeout=args.job_timeout,
            minutes=args.minutes,
            only=only(args),
        )
    if args.command == "isolation":
        return isolation.run(
            ctx,
            fixture=args.fixture,
            job_timeout=args.job_timeout,
            minutes=args.minutes,
            hold=args.hold_seconds,
        )
    if args.command == "security":
        return security.run(
            ctx,
            fixture=args.fixture,
            job_timeout=args.job_timeout,
            minutes=args.minutes,
            only=only(args),
            max_expiry_wait=args.max_expiry_wait,
            full_size=args.full_size_limit,
        )
    if args.command == "unattended":
        return unattended.run(
            ctx,
            fixture=args.fixture,
            backlog=args.backlog,
            drain_timeout=args.drain_timeout,
            settle=args.settle_seconds,
            iam_simulated=args.iam_simulated,
            only=only(args),
        )
    if args.command == "release":
        return release.run(ctx, plan_path=args.plan)
    if args.command == "short-encode":
        if args.arm != "compare" and not (args.fixture and args.fixture_seconds):
            raise ProofError("--fixture and --fixture-seconds are required for an arm")
        return short_encode.run(
            ctx,
            arm=args.arm,
            fixture=args.fixture,
            fixture_seconds=args.fixture_seconds,
            jobs=args.jobs,
            minutes=args.minutes,
            job_timeout=args.job_timeout,
            idle_minutes=args.idle_minutes,
        )
    if args.command == "db-topology":
        return db_topology.run(
            ctx,
            arm_name=args.arm,
            samples=args.samples,
            pause_minutes=args.pause_wait_minutes,
            resume_timeout=args.resume_timeout,
            load_seconds=args.load_seconds,
            concurrency=args.load_concurrency,
            tail_minutes=args.tail_minutes,
            overrides={
                "shared": args.cluster,
                "media": args.media_cluster,
                "processing": args.processing_cluster,
            },
        )
    if args.command == "latency":
        return latency.run(
            ctx, only=only(args), cluster=args.cluster, pause_wait=60 * args.pause_wait_minutes
        )
    from datetime import date

    closed = None
    if args.closed_at:
        from scripts.aws.v1.proof.core import parse_time

        closed = parse_time(args.closed_at).timestamp()
    since = date.fromisoformat(args.since) if args.since else None
    return spend.run(
        ctx,
        only=only(args),
        closed_at=closed,
        wait_minutes=args.wait_minutes,
        cluster=args.cluster,
        since=since,
    )


def rehearse_short_encode(base, fixture, shared):
    """#93: the arms are different stack states, so two simulated worlds share one receipt."""
    import shutil

    first = sim.build(
        shared,
        session="open",
        world=sim.SimWorld(encode_seconds=40),
        tmp=base / "short-encode-fargate",
    )
    short_encode.run(first, arm="fargate", fixture=fixture, fixture_seconds=24.0, jobs=3)
    second = sim.build(
        shared,
        session="open",
        world=sim.SimWorld(lambda_lane=True),
        tmp=base / "short-encode-lambda",
    )
    second.evidence_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copy(first.evidence_dir / f"evidence-93-{shared.run_id}.json", second.evidence_dir)
    short_encode.run(
        second, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=3, idle_minutes=0
    )
    proof = short_encode.run(second, arm="compare")
    return proof.report(), bool(proof.failed_now())


def rehearse_db_topology(base, shared):
    """#94: the arms are different stacks, so two simulated worlds share one receipt."""
    import shutil

    first = sim.build(
        shared,
        session="window",
        world=sim.SimWorld(database="shared"),
        tmp=base / "db-topology-shared",
    )
    db_topology.run(first, arm_name="shared", samples=5, tail_minutes=0)
    second = sim.build(
        shared,
        session="window",
        world=sim.SimWorld(database="separate"),
        tmp=base / "db-topology-separate",
    )
    second.evidence_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copy(first.evidence_dir / f"evidence-94-{shared.run_id}.json", second.evidence_dir)
    db_topology.run(second, arm_name="separate", samples=5, tail_minutes=0)
    proof = db_topology.run(second, arm_name="compare")
    return proof.report(), bool(proof.failed_now())


def rehearse_unattended(base, fixture, shared):
    """#68: the operator-batch baseline and then the launcher, on one simulated stack."""
    world = sim.SimWorld(encode_seconds=240, launcher=True)
    ctx = sim.build(shared, session="open", world=world, tmp=base / "unattended")
    capacity.run_backlog(ctx, fixture=fixture, minutes=30)
    sim.opt_in_launcher(ctx)  # close, then `session open --unattended`
    proof = unattended.run(ctx, fixture=fixture, iam_simulated=True)
    return proof.report(), bool(proof.failed_now())


def rehearse_release(base, shared, plan_path):
    """#65: plan.json written by release-plan from simulated facts, then the harness's steps.

    The stack has no SQL station, so the schema reads go through the simulated in-VPC task.
    """
    world = sim.SimWorld()
    ctx = sim.build(shared, session="window", world=world, tmp=base / "release", sql=False)
    if plan_path is None:
        digits = {"good": "456", "bad": "789"}
        builds = {}
        for role, sha in (("baseline", "a"), ("good", "b"), ("bad", "c")):
            ids = (
                None
                if role == "baseline"
                else {
                    owner: "sha256:" + digit * 64
                    for owner, digit in zip(
                        ("media", "processing", "worker"), digits[role], strict=True
                    )
                }
            )
            builds[role] = sim.build_evidence(
                base / f"build-{role}.json", source_sha=sha * 40, config_ids=ids
            )
            if role != "baseline":
                world.register_build(f"rehearsal-{role}", builds[role])
        release_plan.run(
            ctx,
            owner="processing",
            baseline_evidence=builds["baseline"],
            good={"run_id": "rehearsal-good", "evidence": builds["good"]},
            bad={"run_id": "rehearsal-bad", "evidence": builds["bad"]},
            tests_passed=1,
            target_revision=world.schema["processing"],
            attest_schema_unchanged=True,
            out=base / "release-plan",
        )
        plan_path = base / "release-plan" / "plan.json"
    proof = release.run(ctx, plan_path=plan_path)
    return proof.report(), bool(proof.failed_now())


def rehearse_latency(ctx):
    """Cold wake opens and closes its own window; the operator then opens the session for the
    generator, as the runbook says."""
    latency.run(ctx, only={"cold-wake"})
    sim.reopen(ctx, "open")
    return latency.run(ctx, only={"generator"})


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
        "capacity": lambda ctx: capacity.run(
            ctx, fixture=fixture, short_fixture=fixture, minutes=30
        ),
        "capacity-backlog": lambda ctx: capacity.run_backlog(ctx, fixture=fixture, minutes=30),
        "isolation": lambda ctx: isolation.run(ctx, fixture=fixture, minutes=30),
        "security": lambda ctx: security.run(ctx, fixture=fixture, minutes=30),
        "latency": rehearse_latency,
        "spend": lambda ctx: spend.run(ctx, wait_minutes=10),
    }
    for name, run in runs.items():
        world = sim.SimWorld(encode_seconds=240 if name.startswith("capacity") else 45)
        ctx = sim.build(shared, session=SESSION[name], world=world, tmp=base / name)
        proof = run(ctx)
        reports[name] = proof.report()
        failed = failed or bool(proof.failed_now())
    reports["release"], bad = rehearse_release(base, shared, args.release_plan)
    failed = failed or bad
    reports["unattended"], bad = rehearse_unattended(base, fixture, shared)
    failed = failed or bad
    reports["short-encode"], bad = rehearse_short_encode(base, fixture, shared)
    failed = failed or bad
    reports["db-topology"], bad = rehearse_db_topology(base, shared)
    failed = failed or bad
    note = (
        "simulated: nothing here is AWS evidence; receipts are SIMULATED and "
        "the summary writer refuses them"
    )
    print(
        json.dumps(
            {
                "mode": "simulated",
                "note": note,
                "harnesses": {
                    k: {
                        "overall": v["overall"],
                        "steps": {n: s["status"] for n, s in v["steps"].items()},
                    }
                    for k, v in reports.items()
                },
            },
            indent=2,
        ),
        file=stdout,
    )
    return 1 if failed else 0


def main(argv=None, *, stdout=None, world=None, factory=None):
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        if args.command == "rehearse":
            return rehearse(args, stdout)
        if args.command in {"counts", "summary"}:
            return post_process(args, stdout)
        if getattr(args, "fresh", False) and args.command not in {"latency", "security"}:
            raise ProofError(
                f"--fresh is not supported for `{args.command}`: its drain counts and release "
                "snapshots are cumulative across attempts, so archiving a step would undercount "
                "or corrupt them. Only `latency` (#66) and `security` (#229) can be rerun as a "
                "fresh attempt"
            )
        if not args.dry_run and not args.state_dir:
            raise ProofError("--state-dir is required for a live run")
        if args.command == "release-plan":
            result = release_plan_command(args, world=world, factory=factory)
            print(json.dumps(result, indent=2), file=stdout)
            return 0
        ctx = make_context(args, args.command, world=world, factory=factory)
        if getattr(args, "fresh", False):
            ctx.fresh = only(args) or True
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
        print(
            json.dumps(
                {
                    "counts_file": str(path),
                    "counts": summary.counts(docs),
                    "attestation": "derived from the receipts' terminal outcomes; the "
                    "operator attests no other attempt ran on this stack",
                },
                indent=2,
            ),
            file=stdout,
        )
        return 0
    import time

    built = summary.build(docs, REQUIRED, args.run_id, wall=time.time)
    path = summary.write(built, args.out)
    print(
        json.dumps(
            {
                "summary": str(path),
                "overall": {k: v["overall"] for k, v in built["issues"].items()},
            },
            indent=2,
        ),
        file=stdout,
    )
    return 0


if __name__ == "__main__":
    # Re-import under the package name so the harnesses share one set of module objects.
    from scripts.aws.v1.evidence import main as package_main

    raise SystemExit(package_main())
