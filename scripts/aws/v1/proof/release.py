"""#65: promote a second image for one owner, roll back, and prove the other owner never moved.

This drives the real `scripts.aws.v1.release` CLI (migration task, published versions, alias
move, public smoke, peer-unchanged check) and clocks it; it adds no release logic of its own.

Rollback of a *good* promotion is a second promotion of the known-good baseline image: the V1
release code only restores the aliases of a promotion that failed its smoke, and it never
reverses a schema. The optional bad-candidate step exercises that real restore path with an
image the operator expects to fail the smoke. An image rollback is not evidence that a
destructive migration can be undone, and the receipt says so.

Needs `session window` (public API open, consumers and workers off) because the release code
requires a quiescent owner, and private SQL access in the operator config for schema reads.
"""

import io
import json
from pathlib import Path

from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError

REQUIRED = ("baseline", "promote-good", "rollback", "owner-isolation")
GOOD_GATE_SECONDS = 600
BAD_GATE_SECONDS = 300
PLAN_KEYS = {"owner", "migration_definition", "target_revision", "good", "baseline", "bad"}
IMAGE_KEYS = {"bundle", "image_uri", "compat_evidence", "worker_definition"}


def load_plan(path):
    try:
        plan = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ProofError("The release plan is unreadable JSON") from None
    if not isinstance(plan, dict) or plan.keys() - PLAN_KEYS or not {
            "owner", "migration_definition", "target_revision", "good", "baseline"} <= plan.keys():
        raise ProofError("The release plan has missing or unsupported fields")
    if plan["owner"] not in {"media", "processing"}:
        raise ProofError("The release plan owner must be media or processing")
    for name in ("good", "baseline", "bad"):
        item = plan.get(name)
        if item is None and name == "bad":
            continue
        if not isinstance(item, dict) or item.keys() - IMAGE_KEYS or not {
                "bundle", "image_uri", "compat_evidence"} <= item.keys():
            raise ProofError(f"The release plan's {name} image is incomplete")
        if (plan["owner"] == "processing") != bool(item.get("worker_definition")):
            raise ProofError("Only a Processing release carries a worker definition")
    return plan


def call(ctx, argv):
    """One release CLI invocation with the live transport; (exit code, parsed JSON, seconds)."""
    out = io.StringIO()
    started = ctx.clock()
    code = ctx.release_main(argv, environ={}, transport_factory=ctx.sdk, stdout=out,
                            http=ctx.http)
    seconds = round(ctx.clock() - started, 1)
    try:
        return code, json.loads(out.getvalue()), seconds
    except ValueError:
        raise ProofError("The release CLI returned unparseable output") from None


def base_args(ctx, action):
    scope = ctx.scope
    return [action, "--config", str(ctx.state_dir / "operator-config.json"),
            "--profile", scope["profile"], "--region", scope["region"],
            "--account", scope["account"], "--deadline-seconds", "900"]


def promote_args(ctx, plan, image):
    smoke = ["--smoke-url", ctx.gateway_url,
             "--smoke-credentials", str(ctx.state_dir / "smoke-credentials.json")]
    args = [*base_args(ctx, "promote"), "--owner", plan["owner"], "--bundle", image["bundle"],
            "--image-uri", image["image_uri"], "--migration-definition",
            plan["migration_definition"], "--target-revision", plan["target_revision"],
            "--compat-evidence", image["compat_evidence"], *smoke]
    if image.get("worker_definition"):
        args += ["--worker-definition", image["worker_definition"]]
    return args


def status_args(ctx):
    return base_args(ctx, "status")


def aliases(ctx):
    code, out, _ = call(ctx, status_args(ctx))
    if code or not out.get("ok"):
        raise ProofError("Could not read the live aliases; " + str(out.get("error", ""))[:100])
    return out["result"]["aliases"], out["result"]["pending_release"]


def split(table, owner):
    return ({n: a["version"] for n, a in table.items() if a["owner"] == owner},
            {n: a["version"] for n, a in table.items() if a["owner"] != owner})


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def smoke_summary(receipt):
    checks = (receipt or {}).get("checks", {})
    return {"checks": checks, "all_passed": bool(checks) and all(
        v == "PASS" for v in checks.values())}


def baseline(ctx, proof, plan):
    table, pending = aliases(ctx)
    own, peer = split(table, plan["owner"])
    proof.intent("snapshots")["baseline"] = {"own": own, "peer": peer}
    proof.save()
    return verdict(pending is None and bool(own) and bool(peer), {
        "owner": plan["owner"], "owner_functions": len(own), "peer_functions": len(peer),
        "pending_release": pending is not None})


def promote(ctx, proof, plan, name, image, *, expect_own_change=True):
    snaps = proof.intent("snapshots")
    code, out, seconds = call(ctx, promote_args(ctx, plan, image))
    table, pending = aliases(ctx)
    own, peer = split(table, plan["owner"])
    snaps[name] = {"own": own, "peer": peer}
    proof.save()
    result = out.get("result", {})
    previous = snaps.get("rollback-from") or snaps["baseline"]
    public = {
        "operation": name, "exit_code": code, "seconds": seconds,
        "gate_seconds": GOOD_GATE_SECONDS, "within_gate": seconds <= GOOD_GATE_SECONDS,
        "status": result.get("status"), "owner_versions_moved": own != previous["own"],
        "peer_unchanged": peer == snaps["baseline"]["peer"],
        "pending_release_after": pending is not None,
        "schema_rollback_attempted": False,
        "smoke": smoke_summary(result.get("smoke") or out.get("smoke")),
    }
    ok = (code == 0 and out.get("ok") and result.get("status") == "promoted"
          and public["within_gate"] and public["peer_unchanged"] and public["smoke"]["all_passed"]
          and (public["owner_versions_moved"] or not expect_own_change) and not pending)
    private = {"versions": result.get("versions"), "error": out.get("error")}
    if name == "promote-good":
        snaps["rollback-from"] = snaps[name]
        proof.save()
    return verdict(bool(ok), public, private)


def isolation(proof):
    """The peer's aliases at every snapshot must equal the baseline's."""
    snaps = proof.intent("snapshots")
    base = snaps["baseline"]["peer"]
    seen = {k: v["peer"] == base for k, v in snaps.items() if isinstance(v, dict) and "peer" in v}
    return verdict(len(seen) >= 3 and all(seen.values()), {
        "snapshots_compared": len(seen), "peer_unchanged_at_every_snapshot": all(seen.values())})


def bad_candidate(ctx, proof, plan):
    if not plan.get("bad"):
        return {"status": NOT_RUN, "public": {
            "reason": "no failing candidate was supplied in the release plan"}}
    snaps = proof.intent("snapshots")
    before_table, _ = aliases(ctx)
    before_own, _ = split(before_table, plan["owner"])
    code, out, failed_after = call(ctx, promote_args(ctx, plan, plan["bad"]))
    restored_code, restored, restore_seconds = call(ctx, [
        *base_args(ctx, "restore"), "--smoke-url", ctx.gateway_url, "--smoke-credentials",
        str(ctx.state_dir / "smoke-credentials.json")])
    table, pending = aliases(ctx)
    own, peer = split(table, plan["owner"])
    total = round(failed_after + restore_seconds, 1)
    public = {
        "candidate_failed_as_expected": code != 0, "failed_after_seconds": failed_after,
        "restore_seconds": restore_seconds, "total_seconds": total,
        "gate_seconds": BAD_GATE_SECONDS, "within_gate": total <= BAD_GATE_SECONDS,
        "aliases_restored": own == before_own, "peer_unchanged": peer == snaps["baseline"]["peer"],
        "pending_release_after": pending is not None, "schema_rollback_attempted": False,
        "restored_smoke": smoke_summary(restored.get("result", {}).get("smoke")),
    }
    ok = (code != 0 and restored_code == 0 and public["within_gate"]
          and public["aliases_restored"] and public["peer_unchanged"] and not pending
          and public["restored_smoke"]["all_passed"])
    return verdict(ok, public)


def offline_gates(ctx, proof, plan):
    """Simulated account: only the release CLI's own offline gates (bundle, digest) can run.

    No alias, migration or smoke is simulated, so nothing here says a release works.
    """
    def gate(image):
        code, out, _ = call(ctx, [*promote_args(ctx, plan, image), "--dry-run"])
        calls = out.get("result", {}).get("planned_calls", [])
        return verdict(code == 0 and out.get("ok") and bool(calls), {
            "validated_offline": code == 0, "planned_calls": len(calls)})

    steps = (("baseline", lambda i: {"status": NOT_RUN, "public": {
        "reason": "live aliases are not simulated"}}),
        ("promote-good", lambda i: gate(plan["good"])),
        ("rollback", lambda i: gate(plan["baseline"])),
        ("owner-isolation", lambda i: {"status": NOT_RUN, "public": {
            "reason": "peer aliases are not simulated"}}))
    for name, action in steps:
        proof.step(name, action, session="window")
    if plan.get("bad"):
        proof.step("bad-candidate-restore", lambda i: gate(plan["bad"]), session="window")
    return proof


def run(ctx, *, plan_path):
    plan = load_plan(plan_path)
    proof = ctx.proof(65, REQUIRED)
    if ctx.simulated:
        return offline_gates(ctx, proof, plan)
    if not ctx.data.get("sql"):
        reason = ("Releases read the owning schema revision over TLS, which needs a station "
                  "inside the VPC (config `sql`); none is configured")
        for name in REQUIRED:
            proof.step(name, lambda i: {"status": NOT_RUN, "public": {"reason": reason}},
                       session="window")
        return proof
    steps = (
        ("baseline", lambda i: baseline(ctx, proof, plan)),
        ("promote-good", lambda i: promote(ctx, proof, plan, "promote-good", plan["good"])),
        ("rollback", lambda i: promote(ctx, proof, plan, "rollback", plan["baseline"],
                                       expect_own_change=True)),
        ("owner-isolation", lambda i: isolation(proof)),
        ("bad-candidate-restore", lambda i: bad_candidate(ctx, proof, plan)),
    )
    for name, action in steps:
        proof.step(name, action, session="window")
    return proof
