"""CLI for independent owner releases: python -m scripts.aws.v1.release ACTION ...

promote  Migrate the owner, publish its immutable Lambda versions, move the `live` alias,
         smoke-test through the public Gateway, and restore on failure (retained intent).
restore  Resume a failed promotion's alias restoration; never downgrades a schema.
status   Read-only: the journal's release intent plus the live alias of each function.

Run `session window` first so the public API is reachable while every consumer, repair
rule and worker stays disabled. Live runs need an explicit --profile/--region/--account;
--dry-run validates the artifact and digest gates offline and prints the planned calls
without any AWS access or journal write.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1 import operations
from scripts.aws.v1.hooks import compatibility_from_evidence, owner_quiescence, schema_reader
from scripts.aws.v1.public_smoke import PublicSmoke, load_credentials, urllib_http
from scripts.aws.v1.release import promote, restore, validate_inputs


def plan_promote(config, args):
    """Static, ordered description of the AWS calls promote performs (no state simulated)."""
    owner = args.owner
    functions = list(config["owner_functions"][owner].values())
    alias = config.get("alias", "live")
    steps = [
        {"step": "snapshot", "operation": op, "functions": functions}
        for op in ("get-alias", "get-function")
    ]
    steps.append(
        {"step": "peer-snapshot", "operation": "get-alias", "owner": _peer(owner)},
    )
    for definition in filter(None, (args.migration_definition, args.worker_definition)):
        steps.append(
            {"step": "validate-definition", "operation": "describe-task-definition",
             "taskDefinition": definition}
        )
    steps.append(
        {"step": "migrate", "operation": "run-task", "taskDefinition": args.migration_definition,
         "clientToken": "<generated and journaled before launch>"}
    )
    steps.append({"step": "migrate", "operation": "describe-tasks", "until": "STOPPED exit 0"})
    for name in functions:
        steps += [
            {"step": "publish", "operation": "update-function-code", "function": name,
             "ImageUri": args.image_uri, "Publish": False},
            {"step": "publish", "operation": "list-versions-by-function", "function": name},
            {"step": "publish", "operation": "publish-version", "function": name,
             "Description": "dc2-v1-<release id>"},
            {"step": "promote", "operation": "update-alias", "function": name, "Name": alias,
             "FunctionVersion": "<published version>", "RevisionId": "<observed alias revision>"},
        ]
    steps.append(
        {"step": "public-smoke", "base_url": args.smoke_url,
         "requests": ["GET /api/media/health", "GET /api/processing/health",
                      "GET /api/media/jobs (anonymous, expect 401/403)",
                      "POST /api/media/auth/login", "GET /api/media/jobs",
                      "GET /api/processing/jobs?asset_ids=<random>"]
         + (["POST /api/media/uploads/reservations (never finalized)"]
            if owner == "media" and not args.no_reserve else [])}
    )
    steps.append({"step": "peer-unchanged", "operation": "get-alias", "owner": _peer(owner)})
    return steps


def _peer(owner):
    return "processing" if owner == "media" else "media"


def hooks_for(config, data, transport, args, http):
    sql = data.get("sql") or {}
    if not sql.get("ca_file"):
        raise OperationError("Config sql.ca_file and per-owner DSN files are required")
    dsn_files = {k[:-9]: v for k, v in sql.items() if k.endswith("_dsn_file")}
    smoke = PublicSmoke(
        args.smoke_url,
        load_credentials(args.smoke_credentials),
        http=http or urllib_http,
        reserve=not args.no_reserve,
    )
    return {
        "schema_revision": schema_reader(dsn_files, sql["ca_file"]),
        "quiescent": owner_quiescence(config, transport),
        "public_smoke": smoke,
    }, smoke


def release_status(config, journal, transport, deadline):
    aliases = {}
    for owner, functions in config["owner_functions"].items():
        for name in functions.values():
            alias = transport.call(
                "lambda",
                "get-alias",
                {"FunctionName": name, "Name": config.get("alias", "live")},
                deadline=deadline,
            )
            aliases[name] = {"owner": owner, "version": alias["FunctionVersion"]}
    with journal.locked() as state:
        pending = state.get("pending_release")
        last = state.get("last_release")
    summary = None
    if pending:
        request = pending.get("v1_request", {})
        summary = {
            "owner": request.get("owner"),
            "phase": pending.get("phase"),
            "migration_complete": bool(pending.get("migration_complete")),
            "versions": pending.get("versions"),
            "image": request.get("image"),
        }
    return {
        "pending_release": summary,
        "last_release": {k: last[k] for k in ("owner", "status", "versions", "schema")}
        if last
        else None,
        "aliases": aliases,
    }


def main(argv=None, *, environ=None, transport_factory=None, stdout=None, http=None):
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.release", description=__doc__)
    parser.add_argument("action", choices=["promote", "restore", "status"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--owner", choices=["media", "processing"])
    parser.add_argument("--bundle", help="JSON artifact receipts: {api[, worker]}")
    parser.add_argument("--image-uri")
    parser.add_argument("--migration-definition")
    parser.add_argument("--worker-definition")
    parser.add_argument("--target-revision")
    parser.add_argument("--compat-evidence")
    parser.add_argument("--smoke-url", help="Gateway origin, e.g. the HttpApiUrl output")
    parser.add_argument("--smoke-credentials", help="private 0600 JSON {email,password}")
    parser.add_argument("--no-reserve", action="store_true", help="skip the upload reservation")
    operations.add_scope_arguments(parser)
    args = parser.parse_args(argv)
    scope = operations.resolve_scope(parser, args, environ)
    if args.action == "promote":
        needed = ("owner", "bundle", "image_uri", "migration_definition", "target_revision")
        if any(getattr(args, n) is None for n in needed) or not args.compat_evidence:
            parser.error("promote needs --owner --bundle --image-uri --migration-definition "
                         "--target-revision --compat-evidence")
    if args.action != "status" and not (args.smoke_url and args.smoke_credentials):
        parser.error("--smoke-url and --smoke-credentials are required")
    smoke = None
    try:
        data, config, _, urls = operations.load_operator_config(args.config)
        deadline = time.monotonic() + args.deadline_seconds
        if args.dry_run:
            result = {"validated": "offline gates only; no AWS access"}
            if args.action == "promote":
                bundle = json.loads(Path(args.bundle).read_text())
                digest = validate_inputs(
                    config,
                    owner=args.owner,
                    bundle=bundle,
                    image_uri=args.image_uri,
                    worker_definition=args.worker_definition,
                )
                result.update(digest=digest, planned_calls=plan_promote(config, args))
            elif args.action == "restore":
                result["planned_calls"] = [
                    {"step": "restore", "operation": op}
                    for op in ("get-alias", "update-alias (prior version)", "get-function",
                               "public-smoke", "peer snapshot")
                ]
            else:
                result["planned_calls"] = [
                    {"operation": "get-alias", "functions": [
                        n for fs in config["owner_functions"].values() for n in fs.values()]}
                ]
        else:
            transport = (transport_factory or operations.live_transport)(scope)
            journal = Journal(
                data["journal"],
                station=data["operator_station"],
                environment=data["environment_id"],
            )
            if args.action == "status":
                result = release_status(config, journal, transport, deadline)
            else:
                hooks, smoke = hooks_for(config, data, transport, args, http)
                if args.action == "promote":
                    bundle = json.loads(Path(args.bundle).read_text())
                    result = promote(
                        config,
                        transport,
                        journal,
                        owner=args.owner,
                        bundle=bundle,
                        image_uri=args.image_uri,
                        migration_definition=args.migration_definition,
                        target_revision=args.target_revision,
                        compatibility=compatibility_from_evidence(args.compat_evidence),
                        worker_definition=args.worker_definition,
                        deadline=deadline,
                        **hooks,
                    )
                else:
                    result = restore(config, transport, journal, deadline=deadline, **hooks)
                result = {**result, "smoke": smoke.receipt}
    except (OperationError, OSError, ValueError, KeyError) as error:
        message = str(error) if isinstance(error, OperationError) else "Invalid release input"
        failure = {"ok": False, "error": message}
        if smoke is not None and smoke.receipt:
            failure["smoke"] = smoke.receipt  # check names and status codes only
        print(json.dumps(failure), file=stdout)
        return 1
    mode = "dry-run" if args.dry_run else "live"
    print(json.dumps({"ok": True, "scope": {**scope, "mode": mode}, "result": result},
                     indent=2, default=str), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
