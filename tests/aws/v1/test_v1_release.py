"""Deterministic AWS protocol checks; these deliberately claim no cloud evidence."""

import copy
import time
from types import SimpleNamespace

import pytest

from scripts.aws.journal import Journal
from scripts.aws.transport import CLITransport, OperationError
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.release import PublicationUncertain, promote, restore
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
                result = {"tasks": [{"taskArn": "migration-task"}]}
            else:
                return {
                    "tasks": [
                        {
                            "taskArn": "migration-task",
                            "taskDefinitionArn": MIGRATION,
                            "lastStatus": "STOPPED",
                            "containers": [{"exitCode": 0}],
                        }
                    ]
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
        return "target" if any(c[1] == "run-task" for c in aws.calls) else "prior"

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
