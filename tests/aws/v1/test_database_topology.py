"""Opt-in V2 database layout (#94): shared (V1) or one Aurora cluster per domain.

Offline throughout. What is proved: the shared layout renders exactly the template V1 shipped;
the separate layout is complete and self-consistent (no dangling reference, one cluster,
instance and security group per domain, each domain's endpoint and credential named apart);
the bootstrap, DSN publication, migrations, teardown and cost model follow the layout. What is
not: that CloudFormation accepts it, how fast a second cluster resumes, or what it costs. Those
are the measurement plan in docs/execution/aws/v2/database-topology.md.
"""

import argparse
import copy
import io
import json
import ssl
import sys
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

# no_disk_sync is an autouse fixture.
from test_deploy import ACCOUNT, ARGS, TODAY, Rig, iter_clock, no_disk_sync  # noqa: F401

from scripts.aws.v1 import bootstrap as db_bootstrap
from scripts.aws.v1 import config as render_config
from scripts.aws.v1 import definitions, deploy, lint
from scripts.aws.v1.definitions import SEPARATE, SHARED, DatabaseOptions, template
from scripts.aws.v1.deploy import DeployError, DeployJournal

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unmeasured
SEPARATE_OPTIONS = DatabaseOptions(SEPARATE)
SPLIT_OPTIONS = DatabaseOptions(SEPARATE, clone_processing=True)
# Media keeps V1's logical ids in the separate layout, so a shared stack can be split in place.
STEM = {"Media": "Database", "Processing": "ProcessingDatabase"}


def rendered(options=None):
    return (json.dumps(template(options), indent=2) + "\n").encode()


def database_resources(built):
    return {
        name: res
        for name, res in built["Resources"].items()
        if res["Type"].startswith("AWS::RDS::DB")
        and res["Type"] not in {"AWS::RDS::DBSubnetGroup", "AWS::RDS::DBClusterParameterGroup"}
    }


# ---- the shared layout is V1, byte for byte ---------------------------------------------------
def test_the_shared_layout_renders_the_exact_bytes_v1_shipped():
    committed = (ROOT / "deploy/aws/v1/template.json").read_bytes()
    assert rendered() == committed
    assert rendered(DatabaseOptions()) == committed
    assert rendered(DatabaseOptions(SHARED, 300, 2)) == committed
    assert rendered(DatabaseOptions(SHARED, 300, 2.0)) == committed  # 2.0 renders as 2


def test_the_shared_template_gains_no_parameter_condition_output_or_resource():
    built = template(DatabaseOptions())
    assert not [k for k in built["Parameters"] if "Database" in k and "Handler" not in k]
    assert not [k for k in built["Conditions"] if "Database" in k]
    assert "DatabaseTopology" not in built["Outputs"]
    assert sorted(database_resources(built)) == ["DatabaseCluster", "DatabaseInstance"]


def test_the_default_options_are_v1s_values():
    options = DatabaseOptions()
    assert (options.topology, options.auto_pause_seconds, options.max_capacity) == (SHARED, 300, 2)
    scaling = template()["Resources"]["DatabaseCluster"]["Properties"][
        "ServerlessV2ScalingConfiguration"
    ]
    assert scaling == {"MinCapacity": 0, "MaxCapacity": 2, "SecondsUntilAutoPause": 300}


# ---- pause and capacity -----------------------------------------------------------------------
@pytest.mark.parametrize("seconds,capacity", [(300, 1), (900, 2), (86_400, 256), (3600, 0.5 * 5)])
def test_pause_and_capacity_inside_aurora_limits_are_rendered(seconds, capacity):
    built = template(DatabaseOptions(SHARED, seconds, capacity))
    scaling = built["Resources"]["DatabaseCluster"]["Properties"][
        "ServerlessV2ScalingConfiguration"
    ]
    assert scaling == {"MinCapacity": 0, "MaxCapacity": capacity, "SecondsUntilAutoPause": seconds}


@pytest.mark.parametrize(
    "seconds,capacity",
    [
        (299, 2),
        (86_401, 2),
        (300.5, 2),
        (True, 2),
        ("300", 2),
        (300, 0.5),
        (300, 0),
        (300, 257),
        (300, 1.25),
        (300, True),
        (300, "2"),
        (300, float("nan")),
    ],
)
def test_pause_and_capacity_outside_aurora_limits_are_refused(seconds, capacity):
    with pytest.raises(ValueError):
        DatabaseOptions(SHARED, seconds, capacity)


def test_an_unknown_topology_is_refused():
    with pytest.raises(ValueError, match="shared or separate"):
        DatabaseOptions("sharded")


def test_changing_only_pause_and_capacity_changes_only_those_two_values():
    base, tuned = template(), template(DatabaseOptions(SHARED, 900, 4))
    tuned["Resources"]["DatabaseCluster"]["Properties"]["ServerlessV2ScalingConfiguration"] = base[
        "Resources"
    ]["DatabaseCluster"]["Properties"]["ServerlessV2ScalingConfiguration"]
    assert tuned == base


# ---- the separate layout ----------------------------------------------------------------------
def test_the_separate_layout_has_a_cluster_instance_and_security_group_per_domain():
    built = template(SEPARATE_OPTIONS)
    assert sorted(database_resources(built)) == [
        "DatabaseCluster",
        "DatabaseInstance",
        "ProcessingDatabaseCluster",
        "ProcessingDatabaseInstance",
    ]
    resources = built["Resources"]
    assert "MediaDatabaseCluster" not in resources
    for stem in STEM.values():
        cluster = resources[f"{stem}Cluster"]
        assert cluster["Properties"]["VpcSecurityGroupIds"] == [{"Ref": f"{stem}SecurityGroup"}]
        assert resources[f"{stem}Instance"]["Properties"]["DBClusterIdentifier"] == {
            "Ref": f"{stem}Cluster"
        }


def test_both_clusters_keep_every_v1_safeguard_and_the_requested_scaling():
    built = template(DatabaseOptions(SEPARATE, 600, 3))
    shared = template()["Resources"]["DatabaseCluster"]
    for stem in STEM.values():
        cluster = built["Resources"][f"{stem}Cluster"]
        expected = copy.deepcopy(shared)
        expected["Properties"]["VpcSecurityGroupIds"] = [{"Ref": f"{stem}SecurityGroup"}]
        expected["Properties"]["ServerlessV2ScalingConfiguration"] = {
            "MinCapacity": 0,
            "MaxCapacity": 3,
            "SecondsUntilAutoPause": 600,
        }
        assert cluster == expected  # encryption, deletion protection, Retain, TLS group, tags
        assert (
            cluster["DeletionPolicy"] == "Retain"
            and cluster["Properties"]["DeletionProtection"] is True
        )
        assert built["Resources"][f"{stem}Instance"]["DeletionPolicy"] == "Retain"


def test_each_domains_endpoint_and_credential_are_named_apart():
    outputs = template(SEPARATE_OPTIONS)["Outputs"]
    assert {"DatabaseEndpoint", "BootstrapSecretArn"}.isdisjoint(outputs)
    for domain, stem in STEM.items():
        assert outputs[f"{domain}DatabaseEndpoint"] == {
            "Value": {"Fn::GetAtt": [f"{stem}Cluster", "Endpoint.Address"]}
        }
        assert outputs[f"{domain}BootstrapSecretArn"] == {
            "Value": {"Fn::GetAtt": [f"{stem}Cluster", "MasterUserSecret.SecretArn"]}
        }
    assert outputs["DatabaseTopology"] == {"Value": "separate"}


def test_the_encoder_network_cannot_reach_medias_cluster_but_lambda_and_migrations_reach_both():
    resources = template(SEPARATE_OPTIONS)["Resources"]
    ingress = {
        name: res["Properties"]
        for name, res in resources.items()
        if res["Type"] == "AWS::EC2::SecurityGroupIngress"
    }
    sources = {}
    for props in ingress.values():
        sources.setdefault(props["GroupId"]["Ref"], set()).add(
            props["SourceSecurityGroupId"]["Ref"]
        )
    assert sources == {
        "DatabaseSecurityGroup": {"LambdaSecurityGroup", "MigrationSecurityGroup"},
        "ProcessingDatabaseSecurityGroup": {
            "LambdaSecurityGroup",
            "WorkerSecurityGroup",
            "MigrationSecurityGroup",
        },
    }

    def database_egress(group):
        return {
            rule["DestinationSecurityGroupId"]["Ref"]
            for rule in resources[group]["Properties"]["SecurityGroupEgress"]
            if "DestinationSecurityGroupId" in rule
        }

    assert database_egress("WorkerSecurityGroup") == {"ProcessingDatabaseSecurityGroup"}
    both = {"DatabaseSecurityGroup", "ProcessingDatabaseSecurityGroup"}
    assert database_egress("LambdaSecurityGroup") == both
    assert database_egress("MigrationSecurityGroup") == both


def test_the_database_security_groups_open_no_egress_of_their_own():
    resources = template(SEPARATE_OPTIONS)["Resources"]
    for stem in STEM.values():
        egress = resources[f"{stem}SecurityGroup"]["Properties"]["SecurityGroupEgress"]
        assert egress == [
            {"IpProtocol": "tcp", "FromPort": 1, "ToPort": 1, "CidrIp": "127.0.0.1/32"}
        ]


def references(value):
    """Every name a template fragment refers to through Ref, GetAtt, Fn::Sub or DependsOn."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "Ref":
                found.add(item)
            elif key == "Fn::GetAtt":
                found.add(item[0])
            elif key == "Fn::Sub":
                text = item if isinstance(item, str) else item[0]
                found.update(
                    part.split("}")[0].split(".")[0]
                    for part in text.split("${")[1:]
                    if not part.startswith("!")
                )
            elif key == "DependsOn":
                found.update([item] if isinstance(item, str) else item)
            found |= references(item)
    elif isinstance(value, list):
        for item in value:
            found |= references(item)
    return found


@pytest.mark.parametrize(
    "options",
    [DatabaseOptions(), SEPARATE_OPTIONS, SPLIT_OPTIONS, DatabaseOptions(SEPARATE, 3600, 8)],
)
def test_no_reference_in_the_template_dangles(options):
    built = template(options)
    known = (
        set(built["Resources"])
        | set(built["Parameters"])
        | set(built["Conditions"])
        | {name for name in references(built) if name.startswith("AWS::")}
    )
    pseudo = {name for name in references(built) if name.startswith("AWS::")}
    missing = references(built) - known - pseudo
    assert not missing, missing


def test_the_two_layouts_differ_only_in_the_database_resources_groups_and_outputs():
    shared, separate = template(), template(SEPARATE_OPTIONS)
    changed = set(shared["Resources"]) ^ set(separate["Resources"])
    assert changed == {
        "DatabaseFromWorker",  # the encoder's network no longer reaches Media's cluster
        "ProcessingDatabaseSecurityGroup",
        "ProcessingDatabaseFromLambda",
        "ProcessingDatabaseFromWorker",
        "ProcessingDatabaseFromMigration",
        "ProcessingDatabaseCluster",
        "ProcessingDatabaseInstance",
    }
    unchanged = {k for k in shared["Resources"] if k not in changed}
    different = {k for k in unchanged if shared["Resources"][k] != separate["Resources"][k]}
    assert different == {"LambdaSecurityGroup", "WorkerSecurityGroup", "MigrationSecurityGroup"}
    assert shared["Parameters"] == separate["Parameters"]
    assert shared["Conditions"] == separate["Conditions"]


def test_a_shared_stack_keeps_its_cluster_instance_and_group_when_it_is_split():
    # The in-place split relies on this: Media's resources render exactly as V1 shipped them, so
    # the change set does not touch the cluster that holds the data.
    shared, split = template(), template(SPLIT_OPTIONS)
    for name in (
        "DatabaseCluster",
        "DatabaseInstance",
        "DatabaseSecurityGroup",
        "DatabaseFromLambda",
        "DatabaseFromMigration",
    ):
        assert split["Resources"][name] == shared["Resources"][name], name


def test_processing_gets_a_copy_on_write_clone_of_medias_cluster_only_when_asked():
    plain = template(SEPARATE_OPTIONS)["Resources"]["ProcessingDatabaseCluster"]["Properties"]
    clone = template(SPLIT_OPTIONS)["Resources"]["ProcessingDatabaseCluster"]
    assert not {"SourceDBClusterIdentifier", "RestoreType", "UseLatestRestorableTime"} & set(plain)
    properties = clone["Properties"]
    assert properties["SourceDBClusterIdentifier"] == {"Ref": "DatabaseCluster"}
    assert properties["RestoreType"] == "copy-on-write"
    assert properties["UseLatestRestorableTime"] is True
    # What a clone inherits is not repeated (CloudFormation refuses it beside a source).
    assert not {"MasterUsername", "StorageEncrypted", "EngineVersion"} & set(properties)
    # Everything else is the plain cluster's: own group, own scaling, managed credential, retain.
    for key, value in properties.items():
        if key not in {"SourceDBClusterIdentifier", "RestoreType", "UseLatestRestorableTime"}:
            assert plain[key] == value, key
    assert clone["DeletionPolicy"] == "Retain" and properties["DeletionProtection"] is True
    media = template(SPLIT_OPTIONS)["Resources"]["DatabaseCluster"]["Properties"]
    assert "SourceDBClusterIdentifier" not in media


def test_cloning_needs_the_separate_layout_and_a_real_boolean():
    with pytest.raises(ValueError, match="separate"):
        DatabaseOptions(SHARED, clone_processing=True)
    with pytest.raises(ValueError):
        DatabaseOptions(SEPARATE, clone_processing="yes")
    assert DatabaseOptions(**SPLIT_OPTIONS.as_dict()) == SPLIT_OPTIONS


def test_the_application_database_model_is_unchanged_each_service_keeps_its_own_database():
    # Nothing in the template names a database: the DSN parameters do, and they are written by
    # the pipeline per domain. The functions still get exactly the parameters they had.
    shared, separate = template(), template(SEPARATE_OPTIONS)
    for name in ("MediaApi", "ProcessingApi", "ProcessingCommands", "MediaResults"):
        assert shared["Resources"][name] == separate["Resources"][name]


def test_cfn_lint_runs_on_both_layouts(tmp_path):
    seen = []

    def runner(command, **kwargs):
        body = json.loads(Path(command[1]).read_text())
        seen.append(("ProcessingDatabaseCluster" in body["Resources"], Path(command[1]).name))
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    out = io.StringIO()
    assert lint.run(which=lambda name: "/bin/cfn-lint", runner=runner, stdout=out) == 0
    assert seen == [
        (False, "template-shared.json"),
        (True, "template-separate.json"),
        (True, "template-split.json"),
    ]
    assert "shared, separate and split" in out.getvalue()


def test_a_failure_in_the_separate_layout_is_reported_with_its_name():
    def runner(command, **kwargs):
        failing = "separate" in command[1]
        return type(
            "Done", (), {"returncode": 1 if failing else 0, "stdout": "E3003", "stderr": ""}
        )()

    out = io.StringIO()
    assert lint.run(which=lambda name: "/bin/cfn-lint", runner=runner, stdout=out) == 1
    assert out.getvalue().startswith("[separate] E3003")


# ---- configuration ----------------------------------------------------------------------------
@pytest.fixture
def config():
    return json.loads((ROOT / "deploy/aws/v1/config.example.json").read_text())


def test_the_example_config_is_still_v1s_layout(config):
    assert render_config.database_options(config) == DatabaseOptions()


def test_database_choices_are_render_inputs_and_never_cloudformation_parameters(config):
    before = render_config.parameters(config)
    config |= {
        "database_topology": "separate",
        "database_auto_pause_seconds": 900,
        "database_max_capacity": 4,
    }
    assert render_config.parameters(config) == before
    assert render_config.database_options(config) == DatabaseOptions(SEPARATE, 900, 4)
    config["database_clone_processing"] = True
    assert render_config.database_options(config) == DatabaseOptions(SEPARATE, 900, 4, True)


def test_the_schema_documents_the_database_choices(config):
    schema = json.loads((ROOT / "deploy/aws/v1/config.schema.json").read_text())
    config |= {
        "database_topology": "separate",
        "database_auto_pause_seconds": 900,
        "database_max_capacity": 2.5,
        "database_clone_processing": True,
    }
    jsonschema.validate(config, schema)
    for key, value in (
        ("database_topology", "sharded"),
        ("database_auto_pause_seconds", 299),
        ("database_max_capacity", 0.5),
        ("database_max_capacity", 1.25),
        ("database_clone_processing", "yes"),
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**config, key: value}, schema)


@pytest.mark.parametrize(
    "key,value",
    [
        ("database_topology", "sharded"),
        ("database_auto_pause_seconds", 10),
        ("database_max_capacity", 1000),
        ("database_max_capacity", "2"),
        ("database_clone_processing", True),  # the shared layout cannot clone
    ],
)
def test_the_renderer_rejects_a_bad_database_choice(config, key, value):
    with pytest.raises(ValueError):
        render_config.parameters({**config, key: value})


def test_the_renderer_cli_writes_the_requested_layout(config, tmp_path):
    source = tmp_path / "config.json"
    source.write_text(json.dumps(config | {"database_topology": "separate"}))
    argv = ["config", "--config", str(source), "--output-dir", str(tmp_path / "out")]
    with mock.patch.object(sys, "argv", argv):
        render_config.main()
    body = json.loads((tmp_path / "out" / "template.json").read_text())
    assert "ProcessingDatabaseCluster" in body["Resources"]
    source.write_text(
        json.dumps(config | {"database_topology": "separate", "database_clone_processing": True})
    )
    with mock.patch.object(sys, "argv", argv):
        render_config.main()
    cloned = json.loads((tmp_path / "out" / "template.json").read_text())
    assert cloned["Resources"]["ProcessingDatabaseCluster"]["Properties"]["RestoreType"]


def test_the_template_generator_cli_defaults_to_the_committed_bytes(tmp_path):
    out = tmp_path / "t.json"
    with mock.patch.object(sys, "argv", ["definitions", "--output", str(out)]):
        definitions.main()
    assert out.read_bytes() == (ROOT / "deploy/aws/v1/template.json").read_bytes()
    with mock.patch.object(
        sys,
        "argv",
        [
            "definitions",
            "--output",
            str(out),
            "--database-topology",
            "separate",
            "--database-auto-pause-seconds",
            "600",
            "--database-max-capacity",
            "1.5",
        ],
    ):
        definitions.main()
    scaling = json.loads(out.read_text())["Resources"]["DatabaseCluster"]["Properties"][
        "ServerlessV2ScalingConfiguration"
    ]
    assert scaling == {"MinCapacity": 0, "MaxCapacity": 1.5, "SecondsUntilAutoPause": 600}
    with mock.patch.object(
        sys,
        "argv",
        [
            "definitions",
            "--output",
            str(out),
            "--database-topology",
            "separate",
            "--database-clone-processing",
        ],
    ):
        definitions.main()
    assert (
        "RestoreType"
        in json.loads(out.read_text())["Resources"]["ProcessingDatabaseCluster"]["Properties"]
    )
    with mock.patch.object(
        sys, "argv", ["definitions", "--output", str(out), "--database-auto-pause-seconds", "5"]
    ):
        with pytest.raises(SystemExit):
            definitions.main()


# ---- the bootstrap, a host per domain ---------------------------------------------------------
def role_passwords():
    return {
        f"{d}_{r}": (d + r) * 4 for d in ("media", "processing") for r in ("migrator", "runtime")
    }


def master(name):
    # Derived, not a literal, so a secret scanner has nothing credential-shaped to flag.
    return "-".join(("master", name, "x"))


def legacy_input():
    return {
        "host": "one.example.invalid",
        "port": 5432,
        "user": "dc2bootstrap",
        "password": master("one"),
        "role_passwords": role_passwords(),
    }


def per_domain_input():
    return {
        "databases": {
            "media": {
                "host": "media.example.invalid",
                "port": 5432,
                "user": "dc2bootstrap",
                "password": master("media"),
            },
            "processing": {
                "host": "processing.example.invalid",
                "port": 5432,
                "user": "dc2bootstrap",
                "password": master("processing"),
            },
        },
        "role_passwords": role_passwords(),
    }


class Recorder:
    def __init__(self):
        self.created = {"roles": set(), "databases": {}}
        self.connections = []

    async def connect(self, **kwargs):
        recorder = self

        class Connection:
            def __init__(self):
                self.options, self.sql = kwargs, []
                recorder.connections.append(self)

            async def fetchval(self, statement, value=None):
                if "rolsuper" in statement:
                    return False
                if "pg_roles" in statement:
                    return value in recorder.created["roles"]
                if "pg_get_userbyid" in statement:
                    return recorder.created["databases"].get(value)
                if "pg_database" in statement:
                    return value in recorder.created["databases"]
                return "'" + value + "'"

            async def execute(self, statement):
                self.sql.append(statement)
                fields = statement.split()
                if fields[:2] == ["CREATE", "ROLE"]:
                    recorder.created["roles"].add(fields[2])
                if fields[:2] == ["CREATE", "DATABASE"]:
                    recorder.created["databases"][fields[2]] = fields[4]

            async def close(self):
                pass

        return Connection()


@pytest.mark.asyncio
async def test_a_host_per_domain_gives_each_cluster_only_its_own_domain():
    recorder = Recorder()
    await db_bootstrap.bootstrap(
        per_domain_input(), ssl.get_default_verify_paths().cafile, connect=recorder.connect
    )
    seen = [
        (c.options["host"], c.options["database"], c.options["password"])
        for c in recorder.connections
    ]
    assert seen == [
        ("media.example.invalid", "postgres", master("media")),
        ("media.example.invalid", "media_db", master("media")),
        ("processing.example.invalid", "postgres", master("processing")),
        ("processing.example.invalid", "processing_db", master("processing")),
    ]
    by_host = {}
    for connection in recorder.connections:
        by_host.setdefault(connection.options["host"], []).extend(connection.sql)
    for host, domain, peer in (
        ("media.example.invalid", "media", "processing"),
        ("processing.example.invalid", "processing", "media"),
    ):
        text = "\n".join(by_host[host])
        assert f"CREATE DATABASE {domain}_db OWNER {domain}_owner" in text
        assert f"CREATE ROLE {domain}_runtime NOLOGIN" in text
        assert peer not in text, "a cluster must never learn of the peer's roles or database"
        assert f"REVOKE {domain}_owner FROM {domain}_runtime" in text


@pytest.mark.asyncio
async def test_a_per_domain_input_naming_one_host_twice_is_the_single_cluster_bootstrap():
    same = per_domain_input()
    same["databases"]["processing"] = dict(same["databases"]["media"])
    one, two = Recorder(), Recorder()
    cafile = ssl.get_default_verify_paths().cafile
    await db_bootstrap.bootstrap(same, cafile, connect=one.connect)
    legacy = legacy_input() | {"host": "media.example.invalid", "password": master("media")}
    await db_bootstrap.bootstrap(legacy, cafile, connect=two.connect)
    assert [c.sql for c in one.connections] == [c.sql for c in two.connections]
    assert [c.options["database"] for c in one.connections] == [
        "postgres",
        "media_db",
        "processing_db",
    ]


def test_v1s_single_connection_input_stays_valid_and_per_domain_input_is_accepted():
    assert db_bootstrap.validate_input(legacy_input())
    assert db_bootstrap.validate_input(per_domain_input())
    assert set(db_bootstrap.targets(legacy_input())) == {"media", "processing"}
    assert db_bootstrap.targets(per_domain_input())["processing"]["host"] == (
        "processing.example.invalid"
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_domain",
        "extra_domain",
        "extra_field",
        "url_host",
        "bad_port",
        "empty_user",
        "top_level_host_beside_databases",
        "duplicate_role_values",
        "not_an_object",
    ],
)
def test_a_malformed_per_domain_input_is_refused(change):
    data = per_domain_input()
    if change == "missing_domain":
        del data["databases"]["media"]
    elif change == "extra_domain":
        data["databases"]["other"] = dict(data["databases"]["media"])
    elif change == "extra_field":
        data["databases"]["media"]["extra"] = 1
    elif change == "url_host":
        data["databases"]["media"]["host"] = "postgres://user@example.invalid"
    elif change == "bad_port":
        data["databases"]["media"]["port"] = 0
    elif change == "empty_user":
        data["databases"]["processing"]["user"] = ""
    elif change == "top_level_host_beside_databases":
        data["host"] = "x.example.invalid"
    elif change == "duplicate_role_values":
        data["role_passwords"]["media_runtime"] = data["role_passwords"]["processing_runtime"]
    else:
        data["databases"] = ["media", "processing"]
    with pytest.raises(ValueError):
        db_bootstrap.validate_input(data)


# ---- the bootstrap while a shared stack is split, and its cleanup -----------------------------
def processing_only_input(host="processing.example.invalid"):
    full = per_domain_input()
    return {
        "databases": {"processing": {**full["databases"]["processing"], "host": host}},
        "role_passwords": {
            k: v for k, v in role_passwords().items() if k.startswith("processing_")
        },
    }


def cleanup_input(media_host="media.example.invalid", processing_host="processing.example.invalid"):
    full = per_domain_input()
    full["databases"]["media"]["host"] = media_host
    full["databases"]["processing"]["host"] = processing_host
    return {"databases": full["databases"], "action": "drop-peers"}


@pytest.mark.asyncio
async def test_a_split_reconciles_one_domain_on_the_named_cluster_and_nothing_else():
    recorder = Recorder()
    await db_bootstrap.bootstrap(
        processing_only_input(), ssl.get_default_verify_paths().cafile, connect=recorder.connect
    )
    assert [c.options["database"] for c in recorder.connections] == ["postgres", "processing_db"]
    assert {c.options["host"] for c in recorder.connections} == {"processing.example.invalid"}
    text = "\n".join(sql for c in recorder.connections for sql in c.sql)
    assert "media" not in text, "a cluster being split must not learn of the other domain"
    assert "ALTER ROLE processing_runtime LOGIN INHERIT PASSWORD" in text
    assert "ALTER ROLE processing_migrator LOGIN INHERIT PASSWORD" in text


def test_a_partial_input_must_carry_exactly_its_own_domains_logins():
    assert db_bootstrap.validate_input(processing_only_input())
    assert db_bootstrap.credential_roles(("processing",)) == (
        "processing_migrator",
        "processing_runtime",
    )
    wrong = processing_only_input()
    wrong["role_passwords"] = role_passwords()  # all four beside a Processing-only connection
    with pytest.raises(ValueError, match="exactly 2"):
        db_bootstrap.validate_input(wrong)
    wrong = processing_only_input()
    wrong["role_passwords"]["media_runtime"] = wrong["role_passwords"].pop("processing_runtime")
    with pytest.raises(ValueError):
        db_bootstrap.validate_input(wrong)
    twin = processing_only_input()
    twin["role_passwords"]["processing_runtime"] = twin["role_passwords"]["processing_migrator"]
    with pytest.raises(ValueError, match="distinct"):
        db_bootstrap.validate_input(twin)


class PeerClusters:
    """Two clusters, each holding both databases, as a freshly cloned pair does."""

    def __init__(self, *, missing=()):
        self.databases = {
            host: {"media_db", "processing_db"} - set(gone)
            for host, gone in (
                ("media.example.invalid", ()),
                ("processing.example.invalid", missing),
            )
        }
        self.sql = {host: [] for host in self.databases}

    async def connect(self, **kwargs):
        cluster = self

        class Connection:
            async def fetchval(self, statement, value=None):
                return value in cluster.databases[kwargs["host"]]

            async def execute(self, statement):
                cluster.sql[kwargs["host"]].append(statement)

            async def close(self):
                pass

        return Connection()


@pytest.mark.asyncio
async def test_the_cleanup_drops_each_clusters_copy_of_its_peers_database_only():
    clusters = PeerClusters()
    await db_bootstrap.bootstrap(
        cleanup_input(), ssl.get_default_verify_paths().cafile, connect=clusters.connect
    )
    media, processing = (
        clusters.sql["media.example.invalid"],
        clusters.sql["processing.example.invalid"],
    )
    assert media == [
        "GRANT processing_owner TO CURRENT_USER",
        "DROP DATABASE IF EXISTS processing_db WITH (FORCE)",
        "DROP ROLE IF EXISTS processing_runtime",
        "DROP ROLE IF EXISTS processing_migrator",
        "DROP ROLE IF EXISTS processing_owner",
    ]
    assert processing == [s.replace("processing", "media") for s in media]


@pytest.mark.asyncio
async def test_the_cleanup_drops_nothing_unless_every_cluster_holds_its_own_database():
    clusters = PeerClusters(missing=("processing_db",))
    with pytest.raises(ValueError, match="dropping nothing"):
        await db_bootstrap.bootstrap(
            cleanup_input(), ssl.get_default_verify_paths().cafile, connect=clusters.connect
        )
    assert clusters.sql == {host: [] for host in clusters.sql}


@pytest.mark.parametrize(
    "change", ["one_cluster", "missing_domain", "with_passwords", "other_action", "extra_field"]
)
def test_a_malformed_cleanup_is_refused(change):
    data = cleanup_input()
    if change == "one_cluster":
        data = cleanup_input(processing_host="media.example.invalid")  # one cluster holds both
    elif change == "missing_domain":
        del data["databases"]["media"]
    elif change == "with_passwords":
        data["role_passwords"] = role_passwords()
    elif change == "other_action":
        data["action"] = "drop-everything"
    else:
        data["databases"]["media"]["extra"] = 1
    with pytest.raises(ValueError):
        db_bootstrap.validate_input(data)


# ---- the pipeline, rehearsed against the simulation -------------------------------------------
@pytest.fixture
def separate_rig(tmp_path):
    rig = Rig(tmp_path, database=SEPARATE_OPTIONS, skip_final_snapshot=True, confirm_run_id="t1")
    rig.deploy()
    return rig


def test_the_separate_stack_has_two_clusters_and_each_domain_gets_its_own_endpoint(separate_rig):
    sim = separate_rig.sim
    assert len(sim.clusters) == 2 and len(sim.instances) == 2
    outputs = json.loads((separate_rig.s.state_dir / "outputs.json").read_text())
    assert "DatabaseEndpoint" not in outputs
    assert outputs["MediaDatabaseEndpoint"] != outputs["ProcessingDatabaseEndpoint"]
    assert outputs["MediaBootstrapSecretArn"] != outputs["ProcessingBootstrapSecretArn"]


def test_the_bootstrap_input_names_a_cluster_and_master_credential_per_domain(separate_rig):
    sent = separate_rig.sim.bootstrap_input
    assert set(sent) == {"databases", "role_passwords"}
    media, processing = sent["databases"]["media"], sent["databases"]["processing"]
    assert media["host"] != processing["host"] and processing["host"].startswith(
        separate_rig.s.env + "-processing"
    )
    assert media["password"] != processing["password"]
    # One read per cluster's own master credential (the simulation redacts the id it logs).
    assert len(separate_rig.ops("get-secret-value")) == 2


def test_each_domains_dsns_point_at_its_own_cluster(separate_rig):
    values = separate_rig.sim.param_values
    prefix = f"/dc2/{separate_rig.s.env}/"
    outputs = json.loads((separate_rig.s.state_dir / "outputs.json").read_text())
    for domain in ("media", "processing"):
        host = outputs[f"{domain.title()}DatabaseEndpoint"]
        for kind in ("runtime", "migration"):
            dsn = values[prefix + f"{domain}_{kind}_dsn"]
            assert f"@{host}:5432/{domain}_db" in dsn
            assert dsn.split("//")[1].startswith(f"{domain}_")  # its own domain's login
    assert (
        len({values[prefix + f"{d}_runtime_dsn"].split("@")[1] for d in ("media", "processing")})
        == 2
    )


def test_migrations_run_per_domain_against_that_domains_connection(separate_rig):
    started = [p["taskDefinition"] for _, op, p in separate_rig.sim.calls if op == "run-task"]
    assert any("mediamigration" in d for d in started)
    assert any("processingmigration" in d for d in started)
    steps = separate_rig.steps()
    assert steps["db-bootstrap"] == "done" and steps["migrations"] == "done"


def test_the_shared_stack_still_sends_the_single_connection_input(tmp_path):
    rig = Rig(tmp_path)
    rig.deploy()
    sent = rig.sim.bootstrap_input
    assert set(sent) == {"host", "port", "user", "password", "role_passwords"}
    prefix = f"/dc2/{rig.s.env}/"
    hosts = {
        rig.sim.param_values[prefix + f"{d}_runtime_dsn"].split("@")[1].split(":")[0]
        for d in ("media", "processing")
    }
    assert len(hosts) == 1 and len(rig.sim.clusters) == 1


def test_teardown_deletes_both_clusters_with_a_final_snapshot_each(tmp_path):
    rig = Rig(tmp_path, database=SEPARATE_OPTIONS, confirm_run_id="t1")
    rig.deploy()
    receipt = rig.teardown().receipt
    instance_deletes = [i for i, c in enumerate(rig.sim.calls) if c[1] == "delete-db-instance"]
    cluster_deletes = rig.ops("delete-db-cluster")
    assert len(instance_deletes) == 2 and len(cluster_deletes) == 2
    names = sorted(c[2]["FinalDBSnapshotIdentifier"] for c in cluster_deletes)
    assert names == [f"{rig.s.env}-media-final", f"{rig.s.env}-processing-final"]
    assert set(rig.sim.snapshots) == set(names)
    assert all(
        s["tags"] == {"deploy-project": "dc2-v1", "owner-run": "t1"}
        for s in rig.sim.snapshots.values()
    )
    assert rig.sim.clusters == {} and rig.sim.instances == {}
    assert receipt["final_snapshots"] == names or sorted(receipt["final_snapshots"]) == names
    assert [r["kind"] for r in receipt["resources_remaining"]] == ["aurora-snapshot"] * 2
    assert receipt["final_snapshot"] == receipt["final_snapshots"][0]


def test_both_instances_are_deleted_before_either_cluster_is_waited_on(tmp_path):
    rig = Rig(tmp_path, database=SEPARATE_OPTIONS, skip_final_snapshot=True, confirm_run_id="t1")
    rig.deploy()
    rig.teardown()
    ops = [c[1] for c in rig.sim.calls]
    first_cluster_delete = ops.index("delete-db-cluster")
    assert ops.count("delete-db-instance") == 2
    assert max(i for i, op in enumerate(ops) if op == "delete-db-instance") < first_cluster_delete
    deletes = [i for i, op in enumerate(ops) if op == "delete-db-cluster"]
    # Only each cluster's own pre-check may precede the second deletion; a wait on the first
    # (another describe) would mean the second queued behind it.
    assert ops[: deletes[1]].count("describe-db-clusters") == 2


def test_skipping_the_snapshot_leaves_a_clean_receipt_for_two_clusters(separate_rig):
    receipt = separate_rig.teardown().receipt
    assert receipt["status"] == "CLEAN" and receipt["final_snapshots"] == []
    assert receipt["final_snapshot"] == "skipped by operator"
    assert all(
        "FinalDBSnapshotIdentifier" not in c[2] for c in separate_rig.ops("delete-db-cluster")
    )


def test_a_resumed_teardown_keeps_the_snapshots_an_earlier_attempt_journaled(tmp_path):
    rig = Rig(tmp_path, database=SEPARATE_OPTIONS, confirm_run_id="t1")
    rig.deploy()
    rig.sim.fail[("rds", "describe-db-clusters")] = [
        None,
        deploy.AwsError("rds", "describe-db-clusters", "Throttling"),
    ]
    with pytest.raises(deploy.AwsError):
        rig.teardown()
    receipt = rig.teardown().receipt
    assert sorted(receipt["final_snapshots"]) == [
        f"{rig.s.env}-media-final",
        f"{rig.s.env}-processing-final",
    ]


def start_run(rig, journal):
    """`deploy.execute` as the CLI calls it, stopped after preflight."""
    args = argparse.Namespace(
        action="deploy",
        stop_after="preflight",
        media_revision=None,
        processing_revision=None,
        json=False,
        plan_detail="mutating",
    )
    return deploy.execute(
        rig.s,
        rig.sim,
        journal,
        rig.docker,
        rig.gateway,
        rig.session,
        args,
        None,
        io.StringIO(),
        io.StringIO(),
        iter_clock(),
        lambda _s: None,
        lambda: TODAY,
    )


def test_the_journal_records_the_layout_and_each_clusters_domain(separate_rig, tmp_path):
    fresh = DeployJournal(
        tmp_path / "fresh.json", station=separate_rig.s.station, environment=separate_rig.s.env
    )
    start_run(separate_rig, fresh)
    assert fresh.view()["database"] == {
        "topology": "separate",
        "auto_pause_seconds": 300,
        "max_capacity": 2,
        "clone_processing": False,
    }
    view = separate_rig.journal.view()
    assert sorted(view["resources"]["db_logical"].values()) == [
        "DatabaseCluster",
        "ProcessingDatabaseCluster",
    ]


def test_a_live_stacks_topology_cannot_be_flipped_on_a_resume(separate_rig, tmp_path):
    journal = DeployJournal(
        tmp_path / "fresh.json", station=separate_rig.s.station, environment=separate_rig.s.env
    )
    start_run(separate_rig, journal)
    separate_rig.s.database = DatabaseOptions()
    with pytest.raises(DeployError, match="database topology separate"):
        start_run(separate_rig, journal)
    separate_rig.s.database = DatabaseOptions(SEPARATE, 900, 4)  # in-place settings may change
    start_run(separate_rig, journal)
    assert journal.view()["database"]["auto_pause_seconds"] == 900


def test_a_journal_from_before_this_option_is_v1s_layout(tmp_path):
    rig = Rig(tmp_path)  # Rig's journal has no "database" key, like one written by V1
    assert "database" not in rig.journal.view()
    deploy.check_database_layout(rig.journal, DatabaseOptions())
    with pytest.raises(DeployError, match="database topology shared"):
        deploy.check_database_layout(rig.journal, SEPARATE_OPTIONS)


def test_pause_and_capacity_may_change_on_a_resume_and_are_rejournaled(tmp_path):
    rig = Rig(tmp_path)
    tuned = DatabaseOptions(SHARED, 900, 4)
    deploy.check_database_layout(rig.journal, tuned)
    assert rig.journal.view()["database"] == tuned.as_dict()


def test_a_stack_rendered_for_the_other_layout_is_reported_not_guessed(tmp_path):
    shared = Rig(tmp_path / "a").pipeline()
    with pytest.raises(DeployError, match="lack DatabaseEndpoint.*database topology shared"):
        shared.database_endpoints({"MediaDatabaseEndpoint": "x"})
    separate = Rig(tmp_path / "b", database=SEPARATE_OPTIONS).pipeline()
    with pytest.raises(DeployError, match="lack MediaDatabaseEndpoint"):
        separate.database_endpoints({"DatabaseEndpoint": "x", "BootstrapSecretArn": "y"})


def test_the_rendered_deploy_template_follows_the_pipelines_layout(tmp_path):
    shared = Rig(tmp_path / "a").pipeline().render(apps=False)[0]
    separate = Rig(tmp_path / "b", database=SEPARATE_OPTIONS).pipeline().render(apps=False)[0]
    assert "ProcessingDatabaseCluster" not in shared and "DatabaseCluster" in shared
    assert "DatabaseCluster" in separate and "ProcessingDatabaseCluster" in separate
    # the change-set name hashes the body, so V1's resume of an existing stack is unaffected
    assert json.loads(shared) == template()


# ---- cost model and guard ---------------------------------------------------------------------
def test_v1s_planned_cost_is_unchanged():
    task_hour = 0.25 * deploy.FARGATE_VCPU_HOUR + 0.5 * deploy.FARGATE_GIB_HOUR + deploy.IPV4_HOUR
    original = round(2 * deploy.ACU_HOUR * 3 + 3 * 0.1 * task_hour + (0.40 + 0.15 + 0.11 + 0.10), 2)
    assert deploy.planned_cost(3) == original == deploy.planned_cost(3, DatabaseOptions())


def test_the_second_cluster_adds_its_ceiling_and_its_retained_cost_to_the_guard():
    base, both = deploy.planned_cost(3), deploy.planned_cost(3, SEPARATE_OPTIONS)
    assert both - base == pytest.approx(
        2 * deploy.ACU_HOUR * 3 + deploy.EXTRA_CLUSTER_MONTH_USD, abs=0.01
    )
    assert deploy.EXTRA_CLUSTER_MONTH_USD == pytest.approx(0.51)
    assert round(both - base, 2) == 1.71  # the figure quoted in the design document


def test_the_guard_scales_with_the_ceiling_and_the_window():
    one = deploy.planned_cost(3, DatabaseOptions(SHARED, 300, 1))
    four = deploy.planned_cost(3, DatabaseOptions(SHARED, 300, 4))
    assert four - one == pytest.approx(3 * deploy.ACU_HOUR * 3, abs=0.01)
    both = deploy.planned_cost(6, SEPARATE_OPTIONS) - deploy.planned_cost(3, SEPARATE_OPTIONS)
    assert both == pytest.approx(3 * 2 * 2 * deploy.ACU_HOUR, abs=0.01)


def test_preflight_charges_the_layout_it_will_deploy(tmp_path):
    shared = Rig(tmp_path / "a").pipeline().cost_guard()
    separate = Rig(tmp_path / "b", database=SEPARATE_OPTIONS).pipeline().cost_guard()
    assert separate["planned_deploy_usd"] - shared["planned_deploy_usd"] == pytest.approx(
        1.71, abs=0.01
    )


def test_the_guard_refuses_a_budget_the_second_cluster_would_exceed(tmp_path):
    base = deploy.planned_cost(3)
    budget = base + 0.5  # enough for V1, not for the second cluster
    Rig(tmp_path / "a", budget_usd=budget).pipeline().cost_guard()
    with pytest.raises(DeployError, match="Cost guard"):
        Rig(tmp_path / "b", budget_usd=budget, database=SEPARATE_OPTIONS).pipeline().cost_guard()


# ---- the command line -------------------------------------------------------------------------
def run_cli(*extra, action="rehearse"):
    out = io.StringIO()
    code = deploy.main(
        [action, *ARGS, "--run-id", "dbtopo", *extra], stdout=out, stderr=io.StringIO()
    )
    return code, out.getvalue()


@pytest.mark.parametrize("topology", ["shared", "separate"])
def test_a_rehearsal_and_a_dry_run_pass_for_both_layouts(topology):
    code, text = run_cli("--database-topology", topology)
    assert code == 0, text
    body = json.loads(text[: text.index("\n## ")] if "\n## " in text else text)
    assert body["ok"] is True and all(v == "done" for v in body["steps"].values())
    remaining = body["resources_remaining_receipt"]
    expected_snapshots = 1 if topology == "shared" else 2
    assert [r["kind"] for r in remaining["resources_remaining"]] == [
        "aurora-snapshot"
    ] * expected_snapshots
    code, text = run_cli(
        "--database-topology", topology, "--stop-after", "migrations", "--dry-run", action="deploy"
    )
    assert code == 0, text


def test_the_cli_refuses_out_of_range_database_flags():
    for flag, value in (
        ("--database-auto-pause-seconds", "100"),
        ("--database-max-capacity", "0.5"),
        ("--database-max-capacity", "1.1"),
    ):
        code, text = run_cli(flag, value, "--dry-run", action="deploy")
        assert code == 1 and json.loads(text)["ok"] is False


def test_the_defaults_on_the_cli_are_v1s():
    args = deploy.build_parser().parse_args(["deploy", *ARGS, "--run-id", "x"])
    assert (
        args.database_topology,
        args.database_auto_pause_seconds,
        args.database_max_capacity,
    ) == ("shared", 300, 2)
    assert ACCOUNT in ARGS
