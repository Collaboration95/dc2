"""CLI for independent owner releases: python -m scripts.aws.v1.release ACTION ...

promote  Migrate the owner, publish its immutable Lambda versions, move the `live` alias,
         smoke-test through the public Gateway, and restore on failure (retained intent).
restore  Resume a failed promotion's alias restoration; never downgrades a schema.
abandon  Clear a pending release that provably changed nothing (e.g. its migration task failed,
         so restore refuses it): no alias moved, every `live` alias still on its prior version,
         the owner's schema still at the revision recorded before the release, owner quiescent.
         Published-but-unaliased versions are reported. Any failed check refuses and keeps the
         intent. The intent moves to `abandoned_releases` in the journal; --reason is recorded.
status   Read-only: the journal's release intent plus the live alias of each function.
schema   Read-only: each owner's Alembic revision and where the read came from.

The owning schema revision is read over verified TLS. With a `sql` station in the operator
config the CLI reads it directly; without one (V1 has no bastion, Aurora is private) it runs a
finite task in the VPC from the owner's migration task definition and parses its log line, and
the result records `schema_revision_source: in-vpc-task`.

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
from scripts.aws.v1.release import abandon, promote, restore, validate_inputs
from scripts.aws.v1.vpc_reader import VpcReader

SQL_SOURCE = "sql-station"


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


def pending_request(journal):
    """The pending release's owner and migration definition, for an `abandon` given neither."""
    with journal.locked() as state:
        request = (state.get("pending_release") or {}).get("v1_request") or {}
    return request.get("owner"), request.get("migration_definition")


def _peer(owner):
    return "processing" if owner == "media" else "media"


def hooks_for(config, data, transport, args, http, *, clock=time.monotonic, sleep=time.sleep):
    """Release hooks, the schema reader's source, and the reader itself (None for SQL)."""
    sql = data.get("sql") or {}
    if sql:
        if not sql.get("ca_file"):
            raise OperationError("Config sql.ca_file and per-owner DSN files are required")
        dsn_files = {k[:-9]: v for k, v in sql.items() if k.endswith("_dsn_file")}
        reader, source = schema_reader(dsn_files, sql["ca_file"]), SQL_SOURCE
        vpc = None
    else:
        vpc = reader = VpcReader(config, transport, clock=clock, sleep=sleep)
        source = vpc.source
        if args.owner and args.migration_definition:
            # The CLI's own pinned definition covers an older stack whose outputs lack one.
            vpc.definitions.setdefault(args.owner, args.migration_definition)
    smoke = None
    if args.smoke_url and args.smoke_credentials:
        smoke = PublicSmoke(
            args.smoke_url,
            load_credentials(args.smoke_credentials),
            http=http or urllib_http,
            reserve=not args.no_reserve,
        )
    hooks = {"schema_revision": reader, "quiescent": owner_quiescence(config, transport)}
    if smoke:
        hooks["public_smoke"] = smoke
    return hooks, smoke, source, vpc


def schema_receipt(source, vpc):
    """What the schema reads were: provenance for the evidence, no addresses or task ARNs."""
    receipt = {"schema_revision_source": source}
    if vpc:
        receipt["schema_reads"] = vpc.receipt()["reads"]
    return receipt


def plan_schema(config, data):
    """The calls a schema read makes; offline, so it states the source and runs nothing."""
    if data.get("sql"):
        return [{"step": "schema", "source": SQL_SOURCE, "operation": "SELECT version_num"}]
    return [
        {"step": "schema", "source": VpcReader.source, "owner": owner,
         "operation": "run-task", "taskDefinition": definition,
         "override": "command: python -c <vpc_probe.py>, env DC2_MODE=schema"}
        for owner, definition in (config.get("migration_definitions") or {}).items()
    ]


def read_schemas(config, data, vpc, deadline):
    """Both owners' revisions, read together; the first read also wakes a paused Aurora."""
    owners = ("media", "processing")
    if vpc is None:
        sql = data["sql"]
        files = {k[:-9]: v for k, v in sql.items() if k.endswith("_dsn_file")}
        read = schema_reader(files, sql["ca_file"])
        return {"schema": {o: read(o, deadline=deadline) for o in owners}}
    vpc.prefetch(owners, deadline=deadline)
    return {"schema": {o: vpc.schema(o, deadline=deadline) for o in owners}}


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
            "moved": sorted(pending.get("moved") or {}),
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


def main(argv=None, *, environ=None, transport_factory=None, stdout=None, http=None,
         clock=time.monotonic, sleep=time.sleep):
    environ = os.environ if environ is None else environ
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.release", description=__doc__)
    parser.add_argument("action", choices=["promote", "restore", "abandon", "status", "schema"])
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
    parser.add_argument("--reason", help="abandon: why the intent is cleared (journaled)")
    parser.add_argument("--no-reserve", action="store_true", help="skip the upload reservation")
    operations.add_scope_arguments(parser)
    args = parser.parse_args(argv)
    scope = operations.resolve_scope(parser, args, environ)
    if args.action == "promote":
        needed = ("owner", "bundle", "image_uri", "migration_definition", "target_revision")
        if any(getattr(args, n) is None for n in needed) or not args.compat_evidence:
            parser.error("promote needs --owner --bundle --image-uri --migration-definition "
                         "--target-revision --compat-evidence")
    if args.action in {"promote", "restore"} and not (args.smoke_url and args.smoke_credentials):
        parser.error("--smoke-url and --smoke-credentials are required")
    smoke = vpc = None
    source = None
    try:
        data, config, _, urls = operations.load_operator_config(args.config)
        deadline = clock() + args.deadline_seconds
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
            elif args.action == "schema":
                result["planned_calls"] = plan_schema(config, data)
            elif args.action == "abandon":
                result["planned_calls"] = [
                    {"step": "abandon", "operation": "get-alias", "expect": "prior version"},
                    *plan_schema(config, data),
                    {"step": "abandon", "operation": "quiescence reads"},
                    {"step": "abandon", "journal": "pending_release -> abandoned_releases"},
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
            elif args.action == "schema":
                _, _, source, vpc = hooks_for(config, data, transport, args, http,
                                              clock=clock, sleep=sleep)
                result = read_schemas(config, data, vpc, deadline)
            elif args.action == "abandon":
                if not args.owner or not args.migration_definition:
                    owner, definition = pending_request(journal)
                    args.owner = args.owner or owner
                    args.migration_definition = args.migration_definition or definition
                hooks, _, source, vpc = hooks_for(config, data, transport, args, http,
                                                  clock=clock, sleep=sleep)
                result = abandon(config, transport, journal, deadline=deadline,
                                 reason=args.reason, schema_revision=hooks["schema_revision"],
                                 quiescent=hooks["quiescent"])
            else:
                hooks, smoke, source, vpc = hooks_for(config, data, transport, args, http,
                                                      clock=clock, sleep=sleep)
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
            if source:
                result = {**result, **schema_receipt(source, vpc)}
    except (OperationError, OSError, ValueError, KeyError) as error:
        message = str(error) if isinstance(error, OperationError) else "Invalid release input"
        failure = {"ok": False, "error": message}
        if smoke is not None and smoke.receipt:
            failure["smoke"] = smoke.receipt  # check names and status codes only
        if source:
            failure.update(schema_receipt(source, vpc))
        print(json.dumps(failure), file=stdout)
        return 1
    finally:
        if vpc:
            vpc.abandon()  # a failed release must not leave a prefetched read task running
    mode = "dry-run" if args.dry_run else "live"
    print(json.dumps({"ok": True, "scope": {**scope, "mode": mode}, "result": result},
                     indent=2, default=str), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
