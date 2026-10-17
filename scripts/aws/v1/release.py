"""Coherent per-owner Lambda image releases with private resumable CAS intent.

All hooks and transports are explicit. No CLI invokes live AWS. A pending record
blocks session launch. Schema rollback is never attempted; compatibility must
cover both current and prior images against the additive target revision.
"""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime

from scripts.aws.transport import OperationError, config_value, remaining
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.migration import migrate
from scripts.aws.workers import describe_tasks, inventory


class PublicationUncertain(OperationError):
    """Resume preparation to reconcile a PublishVersion response loss."""


def _prefetch(schema_revision, owners, deadline):
    """Start slow schema reads together when the reader supports it (the in-VPC task reader).

    A Fargate start dominates one read; sequential reads would count against the clocked
    release gates. A SQL reader has no such hook and is simply called when needed.
    """
    start = getattr(schema_revision, "prefetch", None)
    if start:
        start(owners, deadline=deadline)


def _call(transport, operation, payload, deadline):
    return transport.call("lambda", operation, payload, deadline=deadline)


def _function(transport, name, qualifier, deadline):
    payload = {"FunctionName": name}
    if qualifier:
        payload["Qualifier"] = qualifier
    result = _call(transport, "get-function", payload, deadline)
    config = result["Configuration"]
    image = result.get("Code", {}).get("ResolvedImageUri", "")
    if "@sha256:" not in image or config.get("PackageType") != "Image":
        raise OperationError("Immutable Lambda image receipt required")
    # Never persist environment values, URLs, logs or SDK response metadata.
    selected = {
        k: config.get(k)
        for k in (
            "Role",
            "Handler",
            "Runtime",
            "MemorySize",
            "Timeout",
            "VpcConfig",
            "Environment",
            "ImageConfigResponse",
            "Architectures",
            "Layers",
            "FileSystemConfigs",
            "EphemeralStorage",
            "KMSKeyArn",
        )
    }
    fingerprint = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
    return {
        "version": config["Version"],
        "revision": config["RevisionId"],
        "code_sha": config["CodeSha256"],
        "image": image,
        "config": fingerprint,
        "state": config.get("State"),
        "update": config.get("LastUpdateStatus"),
    }


def _alias(transport, name, alias, deadline):
    result = _call(transport, "get-alias", {"FunctionName": name, "Name": alias}, deadline)
    if result.get("RoutingConfig", {}).get("AdditionalVersionWeights"):
        raise OperationError("Weighted aliases are outside V1 release scope")
    if not result["FunctionVersion"].isdigit():
        raise OperationError("Existing immutable known-good alias required")
    return {"version": result["FunctionVersion"], "revision": result["RevisionId"]}


def snapshot(config, transport, owner, schema_revision, state, *, deadline):
    functions = {}
    for name in config["owner_functions"][owner].values():
        alias = _alias(transport, name, config.get("alias", "live"), deadline)
        functions[name] = {
            "alias": alias,
            "function": _function(transport, name, alias["version"], deadline),
        }
    return {
        "functions": functions,
        "schema": schema_revision(owner, deadline=deadline),
        "worker_definition": state.get("worker_definition") if owner == "processing" else None,
    }


def _version(transport, name, image, description, deadline, clock, sleep, journal, state):
    latest = _function(transport, name, None, deadline)
    if latest["image"] != image:
        try:
            _call(
                transport,
                "update-function-code",
                {
                    "FunctionName": name,
                    "ImageUri": image,
                    "RevisionId": latest["revision"],
                    "Publish": False,
                },
                deadline,
            )
        except OperationError:
            # Lost response is safe only when subsequent GET proves exact image.
            if _function(transport, name, None, deadline)["image"] != image:
                raise
    while True:
        latest = _function(transport, name, None, deadline)
        if latest["image"] != image:
            raise OperationError("Concurrent owner code update")
        if latest["state"] == "Failed" or latest["update"] == "Failed":
            raise OperationError("Candidate Lambda update failed")
        if latest["state"] == "Active" and latest["update"] == "Successful":
            break
        sleep(min(1, remaining(deadline, clock)))
    # A publication retry must first find the unique persisted release description.
    marker = None
    matches = []
    while True:
        payload = {"FunctionName": name}
        if marker:
            payload["Marker"] = marker
        page = _call(transport, "list-versions-by-function", payload, deadline)
        matches.extend(
            v["Version"]
            for v in page.get("Versions", [])
            if v.get("Description") == description and v["Version"].isdigit()
        )
        marker = page.get("NextMarker")
        if not marker:
            break
    if len(matches) > 1:
        raise OperationError("Ambiguous published version; explicit reconciliation required")
    if not matches:
        started = state["pending_release"].setdefault("publication_started", {})
        if started.get(name):
            raise PublicationUncertain("Publication not yet visible; do not repeat publish")
        started[name] = True
        journal.save(state)
        try:
            result = _call(
                transport,
                "publish-version",
                {
                    "FunctionName": name,
                    "Description": description,
                    "RevisionId": latest["revision"],
                    "CodeSha256": latest["code_sha"],
                },
                deadline,
            )
            matches = [result["Version"]]
        except OperationError:
            # Do not blindly repeat PublishVersion: it has no idempotency key.
            raise PublicationUncertain(
                "Publication uncertain; resume to reconcile versions"
            ) from None
    version = matches[0]
    observed = _function(transport, name, version, deadline)
    if observed["image"] != image or observed["config"] != latest["config"]:
        raise OperationError("Published image/config mismatch")
    return version


def _move(transport, name, alias, *, before, target, journal, state, deadline):
    observed = _alias(transport, name, alias, deadline)
    if observed["version"] == target:
        return  # Reconcile lost successful response, never overwrite another release.
    if observed != before:
        raise OperationError("Concurrent alias change; refusing overwrite")
    try:
        _call(
            transport,
            "update-alias",
            {
                "FunctionName": name,
                "Name": alias,
                "FunctionVersion": target,
                "RevisionId": observed["revision"],
            },
            deadline,
        )
    except OperationError:
        if _alias(transport, name, alias, deadline)["version"] != target:
            raise
    journal.save(state)


def _validate_definition(transport, reference, digest, deadline):
    if not reference.rsplit(":", 1)[-1].isdigit():
        raise OperationError("Pinned task definition revision required")
    definition = transport.call(
        "ecs", "describe-task-definition", {"taskDefinition": reference}, deadline=deadline
    )["taskDefinition"]
    containers = definition.get("containerDefinitions", [])
    if (
        definition.get("taskDefinitionArn") != reference
        or not containers
        or any(c["image"].rsplit("@", 1)[-1] != digest for c in containers)
    ):
        raise OperationError("Task definition must use exact owning artifact")


def validate_inputs(config, *, owner, bundle, image_uri, worker_definition):
    """Offline release-input gates shared by promote and its --dry-run. Returns the digest."""
    validate_bundle(bundle, owner=owner)
    owners = config.get("owner_functions", {})
    if set(owners) != {"media", "processing"} or any(not v for v in owners.values()):
        raise OperationError("Both complete owner function maps are required")
    names = [name for functions in owners.values() for name in functions.values()]
    if len(names) != len(set(names)):
        raise OperationError("Owner function maps must be disjoint without duplicates")
    digest = bundle["api"]["manifest_digest"]
    if "@" not in image_uri or image_uri.rsplit("@", 1)[-1] != digest:
        raise OperationError("Image URI must pin tested registry manifest")
    if owner == "processing" and not worker_definition:
        raise OperationError("Processing finite worker definition required")
    if owner == "media" and worker_definition is not None:
        raise OperationError("Media cannot change Processing worker")
    return digest


def promote(
    config,
    transport,
    journal,
    *,
    owner,
    bundle,
    image_uri,
    migration_definition,
    target_revision,
    compatibility,
    schema_revision,
    quiescent,
    public_smoke,
    deadline,
    worker_definition=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Resume the same intent by calling again with identical release inputs.

    Hooks must return True after real checks. public_smoke(owner, versions,
    worker_definition, deadline=...) exercises the public V1 contracts; it must
    stop/drain any finite test workers before returning. No fixture is AWS proof.
    """
    digest = validate_inputs(
        config,
        owner=owner,
        bundle=bundle,
        image_uri=image_uri,
        worker_definition=worker_definition,
    )
    journal.check_context(config)
    with journal.locked() as state:
        remaining(deadline, clock)
        if quiescent(owner, deadline=deadline) is not True:
            raise OperationError("Owning intake/consumers and workers must be quiescent")
        _validate_definition(transport, migration_definition, digest, deadline)
        if owner == "processing":
            _validate_definition(
                transport, worker_definition, bundle["worker"]["manifest_digest"], deadline
            )
        request = {
            "owner": owner,
            "bundle": bundle,
            "image": image_uri,
            "migration_definition": migration_definition,
            "target_revision": target_revision,
            "worker_definition": worker_definition,
        }
        pending = state.get("pending_release")
        peer = "media" if owner == "processing" else "processing"
        if pending:
            if pending.get("v1_request") != request:
                raise OperationError("Another release intent is unresolved")
            if pending.get("phase") == "restoring":
                raise OperationError("Restore pending release before another promotion")
        else:
            _prefetch(schema_revision, (owner, peer), deadline)
            prior = snapshot(config, transport, owner, schema_revision, state, deadline=deadline)
            if compatibility(owner, prior, bundle, target_revision, deadline=deadline) is not True:
                raise OperationError("Current/rollback artifact schema compatibility required")
            pending = {
                "v1_request": request,
                "id": uuid.uuid4().hex,
                "prior": prior,
                "peer": snapshot(
                    config, transport, peer, schema_revision, state, deadline=deadline
                ),
                "versions": {},
                "moved": {},
                "phase": "preparing",
            }
            state["pending_release"] = pending
            journal.save(state)
        # Resume a lost RunTask using the persisted token before moving any alias.
        if not pending.get("migration_complete"):
            migrate(
                config,
                transport,
                journal,
                state,
                owner=owner,
                definition=migration_definition,
                revision=target_revision,
                schema_revision=schema_revision,
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
        try:
            for name, prior in pending["prior"]["functions"].items():
                if name not in pending["versions"]:
                    pending["versions"][name] = _version(
                        transport,
                        name,
                        image_uri,
                        "dc2-v1-" + pending["id"],
                        deadline,
                        clock,
                        sleep,
                        journal,
                        state,
                    )
                    journal.save(state)
                version = pending["versions"][name]
                candidate = _function(transport, name, version, deadline)
                if candidate["config"] != prior["function"]["config"]:
                    raise OperationError("Owner role/config drift during code release")
                _move(
                    transport,
                    name,
                    config.get("alias", "live"),
                    before=prior["alias"],
                    target=version,
                    journal=journal,
                    state=state,
                    deadline=deadline,
                )
                pending["moved"][name] = _alias(
                    transport, name, config.get("alias", "live"), deadline
                )
                journal.save(state)
            if (
                public_smoke(owner, pending["versions"], worker_definition, deadline=deadline)
                is not True
            ):
                raise OperationError("Candidate public V1 smoke failed")
            if quiescent(owner, deadline=deadline) is not True:
                raise OperationError("Candidate smoke left active workers/consumers")
            if (
                snapshot(config, transport, peer, schema_revision, state, deadline=deadline)
                != pending["peer"]
            ):
                raise OperationError("Peer changed during owner release")
        except PublicationUncertain:
            raise
        except Exception:
            # Keep intent; caller invokes restore with a separate bounded rollback budget.
            pending["phase"] = "restoring"
            journal.save(state)
            raise OperationError(
                "Release incomplete; private intent retained for restore"
            ) from None
        if owner == "processing":
            state["worker_definition"] = worker_definition
        receipt = {
            "owner": owner,
            "status": "promoted",
            "versions": pending["versions"],
            "worker_definition": worker_definition,
            "schema": target_revision,
            "peer_unchanged": True,
            "artifacts": bundle,
        }
        state["last_release"] = receipt
        state["pending_release"] = None
        journal.save(state)
        return receipt


def restore(config, transport, journal, *, schema_revision, quiescent, public_smoke, deadline):
    """Restore prior aliases/worker selection only; never downgrade an owned schema."""
    journal.check_context(config)
    with journal.locked() as state:
        pending = state.get("pending_release")
        if not pending or "v1_request" not in pending:
            raise OperationError("No V1 release to restore")
        request = pending["v1_request"]
        owner = request["owner"]
        if not pending.get("migration_complete"):
            raise OperationError("Reconcile/finish migration before restoration")
        if quiescent(owner, deadline=deadline) is not True:
            raise OperationError("Restore requires quiescent owner")
        pending["phase"] = "restoring"
        journal.save(state)
        versions = {}
        for name, prior in pending["prior"]["functions"].items():
            current = _alias(transport, name, config.get("alias", "live"), deadline)
            candidate = pending["versions"].get(name)
            if current["version"] != prior["alias"]["version"]:
                if current["version"] != candidate:
                    raise OperationError("Concurrent alias change blocks restoration")
                expected = pending["moved"].get(name)
                if expected and expected != current:
                    raise OperationError("Concurrent alias revision blocks restoration")
                _move(
                    transport,
                    name,
                    config.get("alias", "live"),
                    before=current,
                    target=prior["alias"]["version"],
                    journal=journal,
                    state=state,
                    deadline=deadline,
                )
            if _function(transport, name, prior["alias"]["version"], deadline) != prior["function"]:
                raise OperationError("Prior immutable Lambda receipt changed")
            versions[name] = prior["alias"]["version"]
        worker = pending["prior"]["worker_definition"]
        if public_smoke(owner, versions, worker, deadline=deadline) is not True:
            raise OperationError("Restored public smoke failed; intent retained")
        peer = "media" if owner == "processing" else "processing"
        _prefetch(schema_revision, (peer, owner), deadline)
        if (
            snapshot(config, transport, peer, schema_revision, state, deadline=deadline)
            != pending["peer"]
        ):
            raise OperationError("Peer changed; restoration cannot be certified")
        # Read before the quiescence check: an in-VPC read is an ECS task in the same cluster.
        schema = schema_revision(owner, deadline=deadline)
        if quiescent(owner, deadline=deadline) is not True:
            raise OperationError("Restored smoke left active workers/consumers")
        if owner == "processing":
            state["worker_definition"] = worker
        receipt = {
            "owner": owner,
            "status": "restored",
            "versions": versions,
            "worker_definition": worker,
            "schema": schema,
            "schema_rollback": False,
            "peer_unchanged": True,
        }
        state["last_release"] = receipt
        state["pending_release"] = None
        journal.save(state)
        return receipt


def _migration_settled(config, transport, pending, deadline):
    """Refuse unless the owner's migration task is provably STOPPED (any exit code) or never ran.

    A migration still running can commit after abandon read the old revision, and quiescence
    does not cover it (Media's checks ECS nothing). With the persisted task ARN the task is
    described. A task ECS has forgotten (it forgets STOPPED tasks about an hour after they
    stop) is accepted as settled only when it is both absent from the cluster's RUNNING list
    and MISSING from describe-tasks: ECS lists a task as RUNNING for as long as it runs, so
    that combination means it stopped. Anything else about a forgotten task stays refused.
    With only the persisted request (RunTask response lost, or launch refused) the cluster
    inventory is searched for its `startedBy`; finding nothing proves nothing until the
    RunTask client-token replay window has passed, so the intent is kept until then. No
    request means no launch.
    """
    request = pending.get("migration_request")
    if not request:
        return None
    arn = pending.get("migration_task")
    if arn:
        tasks = _describe_or_forgotten(config, transport, arn, deadline)
        if tasks is None:
            return "absent-from-running"
        mine = [tasks[arn]]
        if mine[0].get("taskDefinitionArn") != request["taskDefinition"]:
            raise OperationError("Migration task definition mismatch; cannot prove it stopped")
    else:
        tasks = inventory(config, transport, deadline=deadline)
        mine = [t for t in tasks.values() if t.get("startedBy") == request["startedBy"]]
        if not mine and time.time() < pending.get("migration_replay_before_epoch", float("inf")):
            raise OperationError(
                "Migration launch unresolved; retry after the RunTask replay window"
            )
    if any(t["lastStatus"] != "STOPPED" for t in mine):
        raise OperationError("Migration task is not stopped; wait for it before abandoning")
    return None


def _running_arns(config, transport, deadline):
    arns, token, seen = set(), None, set()
    while True:
        payload = {"cluster": config_value(config, "cluster"), "desiredStatus": "RUNNING"}
        if token:
            payload["nextToken"] = token
        result = transport.call("ecs", "list-tasks", payload, deadline=deadline)
        arns.update(result.get("taskArns", []))
        token = result.get("nextToken")
        if not token:
            return arns
        if token in seen:
            raise OperationError("Repeated inventory pagination token")
        seen.add(token)


def _describe_or_forgotten(config, transport, arn, deadline):
    """Describe the recorded task, or return None when ECS has provably forgotten it.

    Forgotten means absent from the RUNNING list *and* reported MISSING by describe-tasks.
    Any other failure reason, or a MISSING task that is still listed, stays unresolved.
    """
    listed = arn in _running_arns(config, transport, deadline)
    result = transport.call(
        "ecs",
        "describe-tasks",
        {"cluster": config_value(config, "cluster"), "tasks": [arn]},
        deadline=deadline,
    )
    failures = result.get("failures") or []
    if failures and not listed and all(f.get("reason") == "MISSING" for f in failures):
        if not result.get("tasks"):
            return None
    if failures:
        raise OperationError("Task inventory contains unresolved identities")
    return describe_tasks(config, transport, [arn], deadline=deadline)


def abandon(
    config, transport, journal, *, schema_revision, quiescent, deadline, reason=None
):
    """Clear a pending release that provably changed nothing; restore would refuse it.

    A candidate whose migration task fails leaves `migration_complete` false and no alias
    moved, and `restore` refuses that state on purpose (the schema is unreconciled). Nothing
    else clears it, and any pending intent blocks `session open` and a new promote. Every
    precondition is re-read live rather than trusted from the journal, because the journal's
    `moved` record is written after the alias update and could miss a lost step.

    Published-but-unaliased versions are immutable and harmless, so they are reported, not
    refused. The schema must still be the revision `snapshot()` recorded as `prior` before the
    release started (that is always recorded; if it is missing the intent is refused), so a
    migration that applied is never abandoned over: restore, which never downgrades, owns it.

    The owner's migration task must also be provably stopped first (see `_migration_settled`),
    and each alias must match its full prior receipt (version and revision id).
    """
    journal.check_context(config)
    with journal.locked() as state:
        pending = state.get("pending_release")
        if not pending or "v1_request" not in pending:
            raise OperationError("No V1 release to abandon")
        owner = pending["v1_request"]["owner"]
        if pending.get("moved"):
            raise OperationError("An alias already moved; restore the release instead")
        alias_name = config.get("alias", "live")
        versions = pending.get("versions") or {}
        for name, prior in pending["prior"]["functions"].items():
            current = _alias(transport, name, alias_name, deadline)
            if current["version"] != prior["alias"]["version"]:
                raise OperationError(
                    "Live alias no longer points at its prior version; restore or reconcile"
                )
            # The revision id changes on every update-alias, so an alias that moved away and
            # back (its `moved` record lost in a crash) is caught here. snapshot() always
            # records it; an intent without one cannot prove the alias never moved.
            if current["revision"] != prior["alias"].get("revision"):
                raise OperationError(
                    "Live alias revision differs from the one recorded before the release; "
                    "it was updated, so restore or reconcile"
                )
            if versions.get(name) == current["version"]:
                raise OperationError("A published version is aliased; restore the release instead")
        settled_by = _migration_settled(config, transport, pending, deadline)
        recorded = pending["prior"].get("schema")
        if not isinstance(recorded, str) or not recorded:
            raise OperationError("Prior schema revision was not recorded; cannot prove no change")
        # Read before the quiescence check: an in-VPC read is an ECS task in the same cluster.
        live_schema = schema_revision(owner, deadline=deadline)
        if live_schema != recorded:
            raise OperationError("Owner schema changed since the release began; restore instead")
        if quiescent(owner, deadline=deadline) is not True:
            raise OperationError("Abandon requires quiescent owner")
        unaliased = sorted(versions.values())
        state.setdefault("abandoned_releases", []).append(
            {
                "id": pending.get("id"),
                "owner": owner,
                "phase": pending.get("phase"),
                "reason": reason or "operator abandoned a release that changed nothing",
                "versions_published_unaliased": unaliased,
                "abandoned_at": datetime.now(UTC).isoformat(timespec="seconds"),
                **({"migration_settled_by": settled_by} if settled_by else {}),
            }
        )
        state["pending_release"] = None
        journal.save(state)
        return {
            "owner": owner,
            "status": "abandoned",
            "versions_published_unaliased": unaliased,
            "schema": live_schema,
        }


if __name__ == "__main__":
    # Lazy: the CLI module imports promote/restore from here.
    from scripts.aws.v1.release_cli import main

    raise SystemExit(main())
