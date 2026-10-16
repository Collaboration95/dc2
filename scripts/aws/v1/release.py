"""Coherent per-owner Lambda image releases with private resumable CAS intent.

All hooks and transports are explicit. No CLI invokes live AWS. A pending record
blocks session launch. Schema rollback is never attempted; compatibility must
cover both current and prior images against the additive target revision.
"""

import hashlib
import json
import time
import uuid

from scripts.aws.transport import OperationError, remaining
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.migration import migrate


class PublicationUncertain(OperationError):
    """Resume preparation to reconcile a PublishVersion response loss."""


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
    validate_bundle(bundle, owner=owner)
    owners = config.get("owner_functions", {})
    if set(owners) != {"media", "processing"} or any(not v for v in owners.values()):
        raise OperationError("Both complete owner function maps are required")
    names = [name for functions in owners.values() for name in functions.values()]
    if len(names) != len(set(names)):
        raise OperationError("Owner function maps must be disjoint without duplicates")
    digest = bundle["api"]["manifest_digest"]
    if image_uri.rsplit("@", 1)[-1] != digest or "@" not in image_uri:
        raise OperationError("Image URI must pin tested registry manifest")
    if owner == "processing" and not worker_definition:
        raise OperationError("Processing finite worker definition required")
    if owner == "media" and worker_definition is not None:
        raise OperationError("Media cannot change Processing worker")
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
        if (
            snapshot(config, transport, peer, schema_revision, state, deadline=deadline)
            != pending["peer"]
        ):
            raise OperationError("Peer changed; restoration cannot be certified")
        if quiescent(owner, deadline=deadline) is not True:
            raise OperationError("Restored smoke left active workers/consumers")
        if owner == "processing":
            state["worker_definition"] = worker
        receipt = {
            "owner": owner,
            "status": "restored",
            "versions": versions,
            "worker_definition": worker,
            "schema": schema_revision(owner, deadline=deadline),
            "schema_rollback": False,
            "peer_unchanged": True,
        }
        state["last_release"] = receipt
        state["pending_release"] = None
        journal.save(state)
        return receipt
