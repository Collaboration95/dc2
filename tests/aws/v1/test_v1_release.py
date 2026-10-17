"""Deterministic AWS protocol checks; these deliberately claim no cloud evidence."""

import copy
import time
from types import SimpleNamespace

import pytest

from scripts.aws.journal import Journal
from scripts.aws.transport import CLITransport, OperationError
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.release import PublicationUncertain, abandon, promote, restore
from scripts.aws.v1.transport import OperatorTransport

OLD = "repo@sha256:" + "a" * 64
NEW = "repo@sha256:" + "b" * 64
ACCOUNT = "123456789012"
WORKER = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/worker:2"
MIGRATION = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/migration:2"


def proof(owner, kind):
    config = "sha256:" + ("8" if kind == "finite-worker" else "c") * 64
    source = "d" * 40
    gate = {"status": "PASS", "config_id": config, "source_sha": source}
    return {
        "owner": owner,
        "platform": "linux/amd64",
        "source_sha": source,
        "config_id": config,
        "manifest_config_id": config,
        "manifest_digest": ("sha256:" + "9" * 64) if kind == "finite-worker" else NEW.split("@")[1],
        "tests": {**gate, "passed": 1},
        "artifact_test": {**gate, "kind": "executed"},
        "scan": {**gate, "fixable_high_critical": 0, "report_sha256": "sha256:" + "e" * 64},
        "runtime_kind": kind,
        "runtime_contents": {"redis": False, "rq": False, "ffmpeg": kind == "finite-worker"},
    }


class AWS:
    def __init__(self):
        self.functions = {}
        self.aliases = {}
        self.descriptions = {}
        self.lost = set()
        self.calls = []
        self.peer_drift = False
        self.migration_exit = 0
        self.tasks = {}
        for name in ("media-api", "media-result", "processing-api", "processing-command"):
            self.functions[name] = {
                "1": self.function(name, "1", OLD),
                "$LATEST": self.function(name, "$LATEST", OLD),
            }
            self.aliases[name] = {"FunctionVersion": "1", "RevisionId": "r1"}

    @staticmethod
    def function(name, version, image):
        return {
            "Configuration": {
                "Version": version,
                "RevisionId": "v" + version,
                "CodeSha256": image,
                "PackageType": "Image",
                "State": "Active",
                "LastUpdateStatus": "Successful",
                "Role": "role-" + name,
                "Environment": {"Variables": {"PRIVATE": "never-write-this-value"}},
            },
            "Code": {"ResolvedImageUri": image},
        }

    def call(self, service, op, payload, *, deadline):
        assert deadline > time.monotonic()
        self.calls.append((service, op, copy.deepcopy(payload)))
        if service == "ecs":
            if op == "describe-task-definition":
                return {
                    "taskDefinition": {
                        "taskDefinitionArn": payload["taskDefinition"],
                        "containerDefinitions": [
                            {
                                "image": ("repo@sha256:" + "9" * 64)
                                if payload["taskDefinition"] == WORKER
                                else NEW
                            }
                        ],
                    }
                }
            if op == "run-task":
                self.tasks["migration-task"] = {
                    "taskArn": "migration-task",
                    "taskDefinitionArn": MIGRATION,
                    "startedBy": payload["startedBy"],
                    "lastStatus": "STOPPED",
                    "containers": [{"exitCode": self.migration_exit}],
                }
                result = {"tasks": [{"taskArn": "migration-task"}]}
            elif op == "list-tasks":
                return {
                    "taskArns": [
                        a
                        for a, t in self.tasks.items()
                        if (t["lastStatus"] == "STOPPED") == (payload["desiredStatus"] == "STOPPED")
                    ]
                }
            else:
                wanted = payload["tasks"]
                return {
                    "tasks": [copy.deepcopy(self.tasks[a]) for a in wanted if a in self.tasks],
                    "failures": [
                        {"arn": a, "reason": "MISSING"} for a in wanted if a not in self.tasks
                    ],
                }
        else:
            name = payload["FunctionName"]
            if op == "get-alias":
                return copy.deepcopy(self.aliases[name])
            if op == "get-function":
                return copy.deepcopy(self.functions[name][payload.get("Qualifier", "$LATEST")])
            if op == "list-versions-by-function":
                return {
                    "Versions": [
                        {"Version": v, "Description": d}
                        for (n, v), d in self.descriptions.items()
                        if n == name
                    ]
                }
            if op == "update-function-code":
                assert (
                    payload["RevisionId"]
                    == self.functions[name]["$LATEST"]["Configuration"]["RevisionId"]
                )
                self.functions[name]["$LATEST"] = self.function(
                    name, "$LATEST", payload["ImageUri"]
                )
                result = {}
            elif op == "publish-version":
                result = {"Version": "2"}
                self.functions[name]["2"] = self.function(name, "2", NEW)
                self.descriptions[name, "2"] = payload["Description"]
            elif op == "update-alias":
                assert payload["RevisionId"] == self.aliases[name]["RevisionId"]
                current = self.aliases[name]
                self.aliases[name] = {
                    "FunctionVersion": payload["FunctionVersion"],
                    "RevisionId": current["RevisionId"] + "x",
                }
                result = copy.deepcopy(self.aliases[name])
            else:
                raise AssertionError(op)
        if op in self.lost:
            self.lost.remove(op)
            raise OperationError("simulated response loss")
        return result


@pytest.fixture
def setup(tmp_path):
    tmp_path.chmod(0o700)
    journal = Journal(tmp_path / "state.json", station="station", environment="test")
    journal.initialize(verified_empty=True, exclusive_station=True)
    config = {
        "operator_station": "station",
        "environment_id": "test",
        "cluster": "cluster",
        "owner_functions": {
            "media": {"api": "media-api", "result": "media-result"},
            "processing": {"api": "processing-api", "command": "processing-command"},
        },
        "task_networks": {
            o + "_migration": {
                "subnets": ["subnet"],
                "security_groups": ["sg"],
                "assign_public_ip": "ENABLED",
            }
            for o in ("media", "processing")
        },
    }
    aws = AWS()

    def schema(owner, **kwargs):
        migrated = any(c[1] == "run-task" for c in aws.calls) and not aws.migration_exit
        return "target" if migrated else "prior"

    # Peer schemas have independent ownership: the peer never follows owner migrations.
    def args(owner="processing"):
        bundle = {"api": proof(owner, "lambda-api")}
        if owner == "processing":
            bundle["worker"] = proof(owner, "finite-worker")
        return dict(
            owner=owner,
            bundle=bundle,
            image_uri=NEW,
            migration_definition=MIGRATION,
            target_revision="target",
            compatibility=lambda *a, **k: True,
            schema_revision=lambda o, **k: schema(o) if o == owner else "peer",
            quiescent=lambda *a, **k: True,
            public_smoke=lambda *a, **k: True,
            deadline=time.monotonic() + 30,
            worker_definition=WORKER if owner == "processing" else None,
        )

    return config, aws, journal, args


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_promotes_every_owner_handler_and_preserves_peer(setup, owner):
    config, aws, journal, args = setup
    peer = "processing" if owner == "media" else "media"
    before = {n: copy.deepcopy(aws.aliases[n]) for n in config["owner_functions"][peer].values()}
    result = promote(config, aws, journal, **args(owner))
    assert result["status"] == "promoted"
    assert len(result["versions"]) == 2
    assert {n: aws.aliases[n] for n in before} == before
    assert all(aws.aliases[n]["FunctionVersion"] == "2" for n in result["versions"])
    assert "never-write-this-value" not in journal.path.read_text()


@pytest.mark.parametrize("op", ["update-function-code", "update-alias", "run-task"])
def test_lost_write_response_reconciles_without_duplicate_launch(setup, op):
    config, aws, journal, args = setup
    aws.lost.add(op)
    if op == "run-task":
        with pytest.raises(OperationError):
            promote(config, aws, journal, **args())
    assert promote(config, aws, journal, **args())["status"] == "promoted"
    tokens = [p["clientToken"] for _, operation, p in aws.calls if operation == "run-task"]
    assert len(set(tokens)) == 1


def test_lost_publication_is_reconciled_by_persisted_description(setup):
    config, aws, journal, args = setup
    aws.lost.add("publish-version")
    with pytest.raises(PublicationUncertain):
        promote(config, aws, journal, **args())
    assert promote(config, aws, journal, **args())["status"] == "promoted"
    assert sum(op == "publish-version" for _, op, _ in aws.calls) == 2


@pytest.mark.parametrize("owner", ["processing", "media"])
def test_failed_candidate_restores_prior_aliases_without_schema_downgrade(setup, owner):
    config, aws, journal, args = setup
    options = args(owner)
    options["public_smoke"] = lambda *a, **k: False
    with pytest.raises(OperationError, match="private intent retained"):
        promote(config, aws, journal, **options)
    receipt = restore(
        config,
        aws,
        journal,
        schema_revision=options["schema_revision"],
        quiescent=options["quiescent"],
        public_smoke=lambda *a, **k: True,
        deadline=options["deadline"],
    )
    assert receipt["status"] == "restored"
    assert receipt["schema"] == "target"
    assert receipt["schema_rollback"] is False
    assert all(x["FunctionVersion"] == "1" for x in aws.aliases.values())


def test_concurrent_alias_change_is_not_overwritten_during_restore(setup):
    config, aws, journal, args = setup
    options = args()

    def smoke(*a, **k):
        aws.aliases["processing-api"] = {"FunctionVersion": "99", "RevisionId": "external"}
        return False

    options["public_smoke"] = smoke
    with pytest.raises(OperationError):
        promote(config, aws, journal, **options)
    with pytest.raises(OperationError, match="Concurrent alias change"):
        restore(
            config,
            aws,
            journal,
            schema_revision=options["schema_revision"],
            quiescent=options["quiescent"],
            public_smoke=lambda *a, **k: True,
            deadline=options["deadline"],
        )
    assert aws.aliases["processing-api"]["FunctionVersion"] == "99"
    assert journal.path.read_text().find("pending_release") >= 0


def test_peer_config_drift_blocks_certification(setup):
    config, aws, journal, args = setup
    options = args()

    def smoke(*a, **k):
        aws.functions["media-api"]["1"]["Configuration"]["Role"] = "changed"
        return True

    options["public_smoke"] = smoke
    with pytest.raises(OperationError):
        promote(config, aws, journal, **options)
    assert "restoring" in journal.path.read_text()


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("api", "redis", True),
        ("api", "ffmpeg", True),
        ("worker", "rq", True),
        ("worker", "ffmpeg", False),
    ],
)
def test_bad_runtime_artifacts_rejected(setup, kind, field, value):
    _, _, _, args = setup
    bundle = args()["bundle"]
    bundle[kind]["runtime_contents"][field] = value
    with pytest.raises(OperationError):
        validate_bundle(bundle, owner="processing")


def test_migration_compatibility_rejection_precedes_mutations(setup):
    config, aws, journal, args = setup
    options = args()
    options["compatibility"] = lambda *a, **k: False
    with pytest.raises(OperationError, match="compatibility"):
        promote(config, aws, journal, **options)
    assert not any(
        op in {"run-task", "update-alias", "update-function-code"} for _, op, _ in aws.calls
    )


def test_legacy_transport_remains_offline():
    with pytest.raises(OperationError, match="Production execution disabled"):
        CLITransport({"mode": "live"}).call("ecs", "list-tasks", {}, deadline=time.monotonic() + 5)


def test_operator_transport_requires_project_identity_and_bounded_clients():
    with pytest.raises(OperationError, match="identity"):
        OperatorTransport(
            {}, identity={"Account": "other"}, account=ACCOUNT, region="ap-southeast-1"
        )
    client = SimpleNamespace(
        meta=SimpleNamespace(
            region_name="ap-southeast-1",
            config=SimpleNamespace(
                retries={"total_max_attempts": 1}, connect_timeout=2, read_timeout=3
            ),
        )
    )
    calls = []
    client.get_alias = lambda **payload: calls.append(payload) or {"FunctionVersion": "1"}
    transport = OperatorTransport(
        {"lambda": client},
        identity={"Account": ACCOUNT},
        account=ACCOUNT,
        region="ap-southeast-1",
    )
    assert (
        transport.call(
            "lambda",
            "get-alias",
            {"FunctionName": "f", "Name": "live"},
            deadline=time.monotonic() + 10,
        )["FunctionVersion"]
        == "1"
    )
    with pytest.raises(OperationError, match="deadline"):
        transport.call(
            "lambda",
            "get-alias",
            {"FunctionName": "f", "Name": "live"},
            deadline=time.monotonic() + 1,
        )
    assert len(calls) == 1


def test_missing_uncertain_publication_is_never_blindly_repeated(setup):
    config, aws, journal, args = setup
    aws.lost.add("publish-version")
    with pytest.raises(PublicationUncertain):
        promote(config, aws, journal, **args())
    # Model an eventually consistent list, or an intent persisted immediately
    # before process death: absence is not permission for a duplicate publish.
    aws.descriptions.clear()
    with pytest.raises(PublicationUncertain, match="do not repeat"):
        promote(config, aws, journal, **args())
    assert sum(op == "publish-version" for _, op, _ in aws.calls) == 1


def test_failed_owning_revision_gate_moves_no_alias(setup):
    config, aws, journal, args = setup
    options = args()
    options["schema_revision"] = lambda *a, **k: "wrong-revision"
    with pytest.raises(OperationError, match="schema revision mismatch"):
        promote(config, aws, journal, **options)
    assert not any(op == "update-alias" for _, op, _ in aws.calls)
    assert journal.path.read_text().find("migration_task") >= 0


def test_failed_restore_smoke_retains_intent_for_retry(setup):
    config, aws, journal, args = setup
    options = args()
    options["public_smoke"] = lambda *a, **k: False
    with pytest.raises(OperationError):
        promote(config, aws, journal, **options)
    with pytest.raises(OperationError, match="Restored public smoke failed"):
        restore(
            config,
            aws,
            journal,
            schema_revision=options["schema_revision"],
            quiescent=options["quiescent"],
            public_smoke=lambda *a, **k: False,
            deadline=options["deadline"],
        )
    with journal.locked() as state:
        assert state["pending_release"]["phase"] == "restoring"
    receipt = restore(
        config,
        aws,
        journal,
        schema_revision=options["schema_revision"],
        quiescent=options["quiescent"],
        public_smoke=lambda *a, **k: True,
        deadline=options["deadline"],
    )
    assert receipt["status"] == "restored"


def test_tampered_worker_definition_cannot_launch_or_update_lambda(setup):
    config, aws, journal, args = setup
    call = aws.call

    def tamper(service, op, payload, **kwargs):
        result = call(service, op, payload, **kwargs)
        if op == "describe-task-definition" and payload["taskDefinition"] == WORKER:
            result["taskDefinition"]["containerDefinitions"][0]["image"] = "repo:mutable"
        return result

    aws.call = tamper
    with pytest.raises(OperationError, match="exact owning artifact"):
        promote(config, aws, journal, **args())
    assert not any(
        op in {"run-task", "update-alias", "update-function-code"} for _, op, _ in aws.calls
    )


def test_alias_revision_aba_is_not_overwritten(setup):
    config, aws, journal, args = setup
    options = args()

    def smoke(*a, **k):
        # Another actor touched the same candidate version: revision proves drift.
        aws.aliases["processing-api"]["RevisionId"] += "external"
        return False

    options["public_smoke"] = smoke
    with pytest.raises(OperationError):
        promote(config, aws, journal, **options)
    with pytest.raises(OperationError, match="Concurrent alias revision"):
        restore(
            config,
            aws,
            journal,
            schema_revision=options["schema_revision"],
            quiescent=options["quiescent"],
            public_smoke=lambda *a, **k: True,
            deadline=options["deadline"],
        )
    assert aws.aliases["processing-api"]["FunctionVersion"] == "2"


class Prefetching:
    """A schema reader with the in-VPC reader's prefetch hook, recording the call order."""

    def __init__(self, aws, owner, log):
        self.aws, self.owner, self.log = aws, owner, log

    def prefetch(self, owners, *, deadline):
        self.log.append(("prefetch", tuple(owners)))

    def __call__(self, owner, **kwargs):
        self.log.append(("read", owner))
        if owner != self.owner:
            return "peer"
        return "target" if any(c[1] == "run-task" for c in self.aws.calls) else "prior"


def test_promote_starts_the_owner_and_peer_schema_reads_together_before_the_first_snapshot(setup):
    config, aws, journal, args = setup
    options = args("media")
    log = []
    options["schema_revision"] = Prefetching(aws, "media", log)
    assert promote(config, aws, journal, **options)["status"] == "promoted"
    assert log[0] == ("prefetch", ("media", "processing"))
    assert log[1:3] == [("read", "media"), ("read", "processing")]


def test_restore_reads_the_schema_before_it_checks_quiescence(setup):
    config, aws, journal, args = setup
    options = args("processing")
    log = []
    options["schema_revision"] = Prefetching(aws, "processing", log)
    options["public_smoke"] = lambda *a, **k: False
    with pytest.raises(OperationError, match="private intent retained"):
        promote(config, aws, journal, **options)
    log.clear()

    def quiescent(owner, **kwargs):
        log.append(("quiescent", owner))
        return True

    receipt = restore(
        config, aws, journal, schema_revision=options["schema_revision"], quiescent=quiescent,
        public_smoke=lambda *a, **k: True, deadline=options["deadline"])
    assert receipt["status"] == "restored"
    # An in-VPC read is an ECS task in the same cluster, so it must finish before the check.
    assert log == [("quiescent", "processing"), ("prefetch", ("media", "processing")),
                   ("read", "media"), ("read", "processing"), ("quiescent", "processing")]


def test_a_plain_schema_reader_without_prefetch_is_still_accepted(setup):
    config, aws, journal, args = setup
    assert promote(config, aws, journal, **args("media"))["status"] == "promoted"


# ---- abandon: an intent that provably changed nothing ----------------------------------------
def failed_migration(setup, owner="processing"):
    """The live 2026-10-17 state: the migration task failed before any version or alias."""
    config, aws, journal, args = setup
    aws.migration_exit = 1
    options = args(owner)
    with pytest.raises(OperationError, match="Migration task failed"):
        promote(config, aws, journal, **options)
    return config, aws, journal, options


def abandon_args(options, **changes):
    return {
        "schema_revision": options["schema_revision"],
        "quiescent": options["quiescent"],
        "deadline": options["deadline"],
        **changes,
    }


def pending_of(journal):
    with journal.locked() as state:
        return state["pending_release"]


def test_restore_refuses_a_failed_migration_and_abandon_clears_it(setup):
    config, aws, journal, options = failed_migration(setup)
    intent = pending_of(journal)
    assert intent["phase"] == "preparing" and not intent.get("migration_complete")
    assert intent["versions"] == {} and intent["moved"] == {}
    with pytest.raises(OperationError, match="Reconcile/finish migration"):
        restore(config, aws, journal, public_smoke=lambda *a, **k: True,
                **abandon_args(options))
    writes = [op for _, op, _ in aws.calls if op in {"update-alias", "publish-version"}]
    receipt = abandon(config, aws, journal, reason="migration failed",
                      **abandon_args(options))
    assert receipt == {"owner": "processing", "status": "abandoned",
                       "versions_published_unaliased": [], "schema": "prior"}
    with journal.locked() as state:
        assert state["pending_release"] is None
        (record,) = state["abandoned_releases"]
    assert record["id"] == intent["id"] and record["owner"] == "processing"
    assert record["phase"] == "preparing" and record["reason"] == "migration failed"
    assert record["abandoned_at"]
    assert writes == [op for _, op, _ in aws.calls if op in {"update-alias", "publish-version"}]
    # The released journal lets the next promotion start again.
    aws.migration_exit = 0
    assert promote(config, aws, journal, **options)["status"] == "promoted"


def test_abandon_lists_published_but_unaliased_versions(setup):
    config, aws, journal, options = failed_migration(setup)
    with journal.locked() as state:
        state["pending_release"]["versions"] = {"processing-api": "2", "processing-command": "3"}
        journal.save(state)
    receipt = abandon(config, aws, journal, **abandon_args(options))
    assert receipt["versions_published_unaliased"] == ["2", "3"]
    with journal.locked() as state:
        assert state["abandoned_releases"][0]["versions_published_unaliased"] == ["2", "3"]


def refused(setup, match, *, mutate=None, **changes):
    config, aws, journal, options = failed_migration(setup)
    if mutate:
        mutate(aws, journal)
    before = pending_of(journal)
    with pytest.raises(OperationError, match=match):
        abandon(config, aws, journal, **abandon_args(options, **changes))
    assert pending_of(journal) == before  # a refusal keeps the intent
    with journal.locked() as state:
        assert "abandoned_releases" not in state


def test_abandon_refuses_when_the_journal_recorded_a_moved_alias(setup):
    def mutate(aws, journal):
        with journal.locked() as state:
            state["pending_release"]["moved"] = {"processing-api": {"version": "2"}}
            journal.save(state)

    refused(setup, "alias already moved", mutate=mutate)


def test_abandon_refuses_when_a_live_alias_left_its_prior_version(setup):
    def mutate(aws, journal):  # an update-alias whose journal record was lost
        aws.aliases["processing-command"] = {"FunctionVersion": "2", "RevisionId": "r2"}

    refused(setup, "no longer points at its prior version", mutate=mutate)


def test_abandon_refuses_when_the_owner_schema_changed(setup):
    refused(setup, "schema changed", schema_revision=lambda *a, **k: "target")


def test_abandon_refuses_when_the_prior_schema_was_never_recorded(setup):
    def mutate(aws, journal):
        with journal.locked() as state:
            del state["pending_release"]["prior"]["schema"]
            journal.save(state)

    refused(setup, "Prior schema revision was not recorded", mutate=mutate)


def test_abandon_refuses_when_the_owner_is_not_quiescent(setup):
    refused(setup, "quiescent owner", quiescent=lambda *a, **k: False)


def test_abandon_refuses_without_a_pending_release(setup):
    config, aws, journal, args = setup
    options = args()
    with pytest.raises(OperationError, match="No V1 release to abandon"):
        abandon(config, aws, journal, **abandon_args(options))
    assert not aws.calls


def test_abandon_reads_the_schema_before_it_checks_quiescence(setup):
    order = []
    config, aws, journal, options = failed_migration(setup)

    def read(owner, **kwargs):
        order.append("schema")
        return "prior"

    def quiet(owner, **kwargs):
        order.append("quiescent")
        return True

    abandon(config, aws, journal, **abandon_args(options, schema_revision=read, quiescent=quiet))
    assert order == ["schema", "quiescent"]


def test_abandon_takes_the_operator_station_lock(setup):
    config, aws, journal, options = failed_migration(setup)
    with journal._lock(), pytest.raises(OperationError, match="already busy"):
        abandon(config, aws, journal, **abandon_args(options))
    assert pending_of(journal) is not None


# ---- abandon: the migration task must be settled, and the alias receipt complete --------------
def edit_intent(journal, **changes):
    with journal.locked() as state:
        for key, value in changes.items():
            if value is None:
                state["pending_release"].pop(key, None)
            else:
                state["pending_release"][key] = value
        journal.save(state)


def test_abandon_refuses_while_the_migration_task_is_still_running(setup):
    def mutate(aws, journal):
        aws.tasks["migration-task"]["lastStatus"] = "RUNNING"

    refused(setup, "not stopped", mutate=mutate)


def test_abandon_accepts_a_migration_task_absent_from_running_and_missing_from_describe(setup):
    config, aws, journal, options = failed_migration(setup)
    aws.tasks.clear()
    result = abandon(config, aws, journal, **abandon_args(options))
    assert result["status"] == "abandoned"
    with journal.locked() as state:
        assert state["abandoned_releases"][-1]["migration_settled_by"] == "absent-from-running"


def test_abandon_refuses_a_forgotten_task_that_is_still_listed_as_running(setup):
    config, aws, journal, options = failed_migration(setup)
    arn = pending_of(journal)["migration_task"]
    real_call = aws.call

    def call(service, op, payload, **kwargs):
        if op == "list-tasks" and payload.get("desiredStatus") == "RUNNING":
            return {"taskArns": [arn]}
        if op == "describe-tasks":
            return {"tasks": [], "failures": [{"arn": arn, "reason": "MISSING"}]}
        return real_call(service, op, payload, **kwargs)

    aws.call = call
    with pytest.raises(OperationError, match="unresolved identities"):
        abandon(config, aws, journal, **abandon_args(options))
    assert pending_of(journal) is not None


def test_abandon_refuses_a_task_that_describe_fails_for_a_reason_other_than_missing(setup):
    config, aws, journal, options = failed_migration(setup)
    arn = pending_of(journal)["migration_task"]
    real_call = aws.call

    def call(service, op, payload, **kwargs):
        if op == "describe-tasks":
            return {"tasks": [], "failures": [{"arn": arn, "reason": "ACCESS_DENIED"}]}
        return real_call(service, op, payload, **kwargs)

    aws.call = call
    with pytest.raises(OperationError, match="unresolved identities"):
        abandon(config, aws, journal, **abandon_args(options))


def test_abandon_still_refuses_a_lost_runtask_inside_its_replay_window_when_ecs_lists_nothing(
        setup):
    config, aws, journal, options = failed_migration(setup)
    lost_launch(aws, journal)
    aws.tasks.clear()
    edit_intent(journal, migration_replay_before_epoch=time.time() + 3600)
    with pytest.raises(OperationError, match="launch unresolved"):
        abandon(config, aws, journal, **abandon_args(options))
    assert pending_of(journal) is not None


def test_abandon_refuses_a_migration_task_of_another_definition(setup):
    def mutate(aws, journal):
        aws.tasks["migration-task"]["taskDefinitionArn"] = WORKER

    refused(setup, "definition mismatch", mutate=mutate)


def test_abandon_accepts_a_stopped_task_with_a_nonzero_exit(setup):
    config, aws, journal, options = failed_migration(setup)
    assert aws.tasks["migration-task"]["containers"][0]["exitCode"] == 1
    assert abandon(config, aws, journal, **abandon_args(options))["status"] == "abandoned"


def test_abandon_accepts_a_release_whose_migration_never_started(setup):
    config, aws, journal, options = failed_migration(setup)
    edit_intent(journal, migration_request=None, migration_task=None)
    aws.tasks.clear()
    assert abandon(config, aws, journal, **abandon_args(options))["status"] == "abandoned"


def lost_launch(aws, journal):
    """RunTask response lost: the request is journaled, the task ARN never was."""
    edit_intent(journal, migration_task=None)


def test_abandon_after_a_lost_runtask_response_finds_the_task_by_its_started_by(setup):
    config, aws, journal, options = failed_migration(setup)
    lost_launch(aws, journal)
    assert abandon(config, aws, journal, **abandon_args(options))["status"] == "abandoned"


def test_abandon_after_a_lost_runtask_response_refuses_a_task_still_running(setup):
    def mutate(aws, journal):
        lost_launch(aws, journal)
        aws.tasks["migration-task"]["lastStatus"] = "RUNNING"

    refused(setup, "not stopped", mutate=mutate)


def test_abandon_refuses_an_unresolved_launch_until_the_replay_window_has_passed(setup):
    def mutate(aws, journal):
        lost_launch(aws, journal)
        aws.tasks.clear()
        edit_intent(journal, migration_replay_before_epoch=time.time() + 3600)

    refused(setup, "launch unresolved", mutate=mutate)


def test_abandon_after_the_replay_window_accepts_a_launch_that_left_no_task(setup):
    config, aws, journal, options = failed_migration(setup)
    lost_launch(aws, journal)
    aws.tasks.clear()
    edit_intent(journal, migration_replay_before_epoch=time.time() - 1)
    assert abandon(config, aws, journal, **abandon_args(options))["status"] == "abandoned"


def test_the_live_intent_shape_records_a_full_alias_receipt_and_is_accepted(setup):
    config, aws, journal, options = failed_migration(setup)
    for prior in pending_of(journal)["prior"]["functions"].values():
        assert set(prior["alias"]) == {"version", "revision"}
    assert abandon(config, aws, journal, **abandon_args(options))["status"] == "abandoned"


def test_abandon_refuses_an_alias_that_moved_away_and_back_with_its_record_lost(setup):
    def mutate(aws, journal):
        # update-alias to the candidate succeeded, the crash lost `moved`, then it was moved
        # back to version 1: the version matches again but the revision id does not.
        aws.aliases["processing-api"] = {"FunctionVersion": "1", "RevisionId": "r1xx"}

    refused(setup, "revision differs", mutate=mutate)


def test_abandon_refuses_an_intent_whose_prior_alias_has_no_revision_recorded(setup):
    def mutate(aws, journal):
        with journal.locked() as state:
            for prior in state["pending_release"]["prior"]["functions"].values():
                del prior["alias"]["revision"]
            journal.save(state)

    refused(setup, "revision differs", mutate=mutate)


def test_abandon_refuses_a_running_media_migration_even_though_media_quiescence_ignores_ecs(
        setup):
    config, aws, journal, options = failed_migration(setup, "media")
    aws.tasks["migration-task"]["lastStatus"] = "RUNNING"
    with pytest.raises(OperationError, match="not stopped"):
        abandon(config, aws, journal, **abandon_args(options))
    assert pending_of(journal) is not None
