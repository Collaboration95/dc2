"""Every deployed Lambda and task environment must satisfy its owner's Settings class.

Both Settings classes use extra="ignore", so a misspelled variable is silently dropped and the
default applies. For database TLS the default is the system trust store, which cannot verify
the RDS chain: the failure would first appear inside AWS. Loading the rendered template makes
the variable names a tested contract instead of two strings that must happen to agree.
"""

import json
import os
import re
import ssl
from pathlib import Path

import pytest

from media.config import Settings as MediaSettings
from media.database import engine_options
from media.storage_credentials import LambdaProvider
from media.storage_credentials import credential_provider as media_credentials
from processing.config import Settings as ProcessingSettings
from processing.database import v1_connect_args
from processing.storage_credentials import credential_provider as processing_credentials
from runtime_support.settings import runtime_values

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy/aws/v1/template.json"
BUNDLE = "/opt/rds/global-bundle.pem"
ACCOUNT_ARN = "arn:aws:ssm:ap-southeast-1:123456789012:parameter/dc2/test/"
DSNS = {
    "MEDIA": "postgres://media_runtime:pw@db.example.test:5432/media_db",
    "PROCESSING": "postgres://processing_runtime:pw@db.example.test:5432/processing_db",
}
CLASSES = {"MEDIA": MediaSettings, "PROCESSING": ProcessingSettings}
LAMBDA_ENV = {
    "AWS_LAMBDA_FUNCTION_NAME": "fn",
    "AWS_ACCESS_KEY_ID": "AKIAFAKE",
    "AWS_SECRET_ACCESS_KEY": "fake",
    "AWS_SESSION_TOKEN": "fake",
    "AWS_REGION": "ap-southeast-1",
}


def resolve(value):
    """Reduce CloudFormation intrinsics to deterministic strings; only names matter here."""
    if isinstance(value, str):
        return value
    ((function, argument),) = value.items()
    if function == "Ref":
        # Parameter ARNs must stay well formed: the real loader validates them.
        return ACCOUNT_ARN + argument if argument.endswith("ParameterArn") else f"<{argument}>"
    if function == "Fn::Sub":
        return re.sub(r"\$\{[^}]+\}", "x", argument if isinstance(argument, str) else argument[0])
    return f"<{function}>"


def rendered_environments():
    resources = json.loads(TEMPLATE.read_text())["Resources"]
    found = []
    for name, resource in resources.items():
        properties = resource.get("Properties", {})
        if resource["Type"] == "AWS::Lambda::Function":
            variables = properties["Environment"]["Variables"]
            found.append((name, "lambda", {k: resolve(v) for k, v in variables.items()}, {}))
        elif resource["Type"] == "AWS::ECS::TaskDefinition":
            container = properties["ContainerDefinitions"][0]
            listed = container.get("Environment", [])
            env = {item["Name"]: resolve(item["Value"]) for item in listed}
            secrets = {item["Name"]: "injected" for item in container.get("Secrets", [])}
            found.append((name, "task", env, secrets))
    return found


ENVIRONMENTS = rendered_environments()
LAMBDAS = [entry for entry in ENVIRONMENTS if entry[1] == "lambda"]
TASKS = [entry for entry in ENVIRONMENTS if entry[1] == "task"]


def owner_of(env, secrets):
    owners = {
        owner
        for owner in DSNS
        if f"{owner}_POSTGRES_DSN_PARAMETER_ARN" in env or f"{owner}_POSTGRES_DSN" in secrets
    }
    assert len(owners) <= 1, "one deployed unit must never carry both owners' SQL credentials"
    return owners.pop() if owners else None


class FakeSsm:
    def get_parameter(self, Name, WithDecryption):  # noqa: N803 - boto3 keyword names
        value = DSNS["MEDIA"] if "Media" in Name else DSNS["PROCESSING"]
        if "JwtSecret" in Name:
            value = "jwt-secret-for-test"
        return {"Parameter": {"ARN": Name, "Type": "SecureString", "Value": value}}


def load_settings(monkeypatch, owner, kind, env, secrets):
    for key in list(os.environ):
        if key.startswith(("MEDIA_", "PROCESSING_")):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in secrets:  # ECS injects the secret value under the declared name.
        monkeypatch.setenv(key, DSNS[owner])
    overrides = {}
    if kind == "lambda":
        overrides = runtime_values(owner, environ=LAMBDA_ENV | env, ssm_client=FakeSsm())
    return CLASSES[owner](**overrides)


def test_template_declares_every_expected_deployed_unit():
    names = {name for name, *_ in ENVIRONMENTS}
    assert {"MediaApi", "MediaAuthorizer", "ProcessingApi", "WorkerTaskDefinition"} <= names
    assert len(LAMBDAS) >= 9 and len(TASKS) >= 4


@pytest.mark.parametrize(
    "name,kind,env,secrets", ENVIRONMENTS, ids=[entry[0] for entry in ENVIRONMENTS]
)
def test_rendered_environment_resolves_owner_database_tls_and_dsn(
    monkeypatch, name, kind, env, secrets
):
    owner = owner_of(env, secrets)
    if owner is None:
        pytest.skip(f"{name} holds no owner SQL credential (privileged bootstrap)")
    settings = load_settings(monkeypatch, owner, kind, env, secrets)

    assert settings.postgres_dsn == "postgresql+asyncpg://" + DSNS[owner].split("://", 1)[1]
    assert ("processing_db" if owner == "MEDIA" else "media_db") not in settings.postgres_dsn

    captured = []

    def record(*args, **kwargs):
        captured.append(kwargs.get("cafile"))
        return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    monkeypatch.setattr(ssl, "create_default_context", record)
    if owner == "MEDIA":
        assert settings.postgres_ssl_ca == BUNDLE
        engine_options(settings, invocation=True)
    else:
        assert settings.database_tls is True
        assert settings.database_ca_file == BUNDLE
        v1_connect_args(settings)
    assert captured == [BUNDLE], "TLS must verify against the installed RDS bundle"


@pytest.mark.parametrize("name,kind,env,secrets", LAMBDAS, ids=[entry[0] for entry in LAMBDAS])
def test_every_lambda_selects_a_storage_mode_its_settings_accept(
    monkeypatch, name, kind, env, secrets
):
    owner = owner_of(env, secrets)
    settings = load_settings(monkeypatch, owner, kind, env, secrets)
    assert settings.storage_credential_mode == "lambda"
    if owner == "MEDIA":
        assert isinstance(media_credentials(settings), LambdaProvider)
        assert settings.runtime_mode == "lambda"
    else:
        # Processing Lambdas use boto3's native chain; the MinIO provider is never built there.
        with pytest.raises(ValueError):
            processing_credentials(settings)


@pytest.mark.parametrize("name,kind,env,secrets", TASKS, ids=[entry[0] for entry in TASKS])
def test_every_task_selects_an_accepted_storage_mode_when_it_has_one(
    monkeypatch, name, kind, env, secrets
):
    owner = owner_of(env, secrets)
    if owner is None or f"{owner}_STORAGE_CREDENTIAL_MODE" not in env:
        pytest.skip("task has no storage credential mode to validate")
    settings = load_settings(monkeypatch, owner, kind, env, secrets)
    assert settings.storage_credential_mode == "ecs"


def test_the_old_processing_ca_spelling_is_silently_ignored(monkeypatch):
    # Guards the guard: this is why the rendered-template tests above are needed at all.
    monkeypatch.setenv("PROCESSING_POSTGRES_SSL_CA", BUNDLE)
    monkeypatch.delenv("PROCESSING_DATABASE_CA_FILE", raising=False)
    settings = ProcessingSettings(postgres_dsn=DSNS["PROCESSING"])
    assert settings.database_ca_file is None
