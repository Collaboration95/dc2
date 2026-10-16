"""Resolve owner-scoped Lambda secrets without a local-profile fallback."""

import os
import re
from collections.abc import Mapping
from contextlib import contextmanager

PARAMETER_ARN = re.compile(
    r"arn:(aws(?:-us-gov|-cn)?):ssm:([a-z0-9-]+):(\d{12}):parameter/[^\s]+\Z"
)
FIELDS = {
    "MEDIA": ("postgres_dsn", "jwt_secret"),
    "PROCESSING": ("postgres_dsn",),
}


# invalid_password and invalid_authorization_specification: what a rotated or revoked
# database credential looks like to a warm Lambda that cached the old DSN.
AUTHENTICATION_SQLSTATES = frozenset({"28P01", "28000"})


def credentials_rejected(error: BaseException) -> bool:
    """True when PostgreSQL itself refused the login, however the driver wrapped it."""
    seen, depth = error, 0
    while seen is not None and depth < 4:
        if getattr(seen, "sqlstate", None) in AUTHENTICATION_SQLSTATES:
            return True
        seen = getattr(seen, "orig", None) or getattr(seen, "__cause__", None)
        depth += 1
    return False


@contextmanager
def heal_on_rejection(settings_getter):
    """Forget the cached Settings when the database refuses the cached credentials.

    Handlers that build their own engine cannot rely on a session helper to do this.
    The invocation still fails (and is retried by SQS/EventBridge); the next one
    re-reads the rotated secret instead of replaying the stale DSN until recycle.
    """
    try:
        yield
    except Exception as error:
        if credentials_rejected(error):
            settings_getter.cache_clear()
        raise


class RuntimeConfigurationError(RuntimeError):
    """Safe to report: messages never contain parameter values or SDK errors."""


def _native_client(environ: Mapping[str, str], region: str):
    # Lambda supplies a complete temporary execution-role credential set. Passing
    # that set explicitly prevents discovery of a developer profile or EC2 role.
    names = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    if not environ.get("AWS_LAMBDA_FUNCTION_NAME") or not all(environ.get(n) for n in names):
        raise RuntimeConfigurationError("Secret references require a native Lambda execution role")
    if environ.get("AWS_REGION", region) != region:
        raise RuntimeConfigurationError("Secret reference region differs from the runtime region")
    import boto3
    from botocore.config import Config

    session = boto3.Session(
        aws_access_key_id=environ[names[0]],
        aws_secret_access_key=environ[names[1]],
        aws_session_token=environ[names[2]],
        region_name=region,
    )
    return session.client(
        "ssm",
        config=Config(
            use_dualstack_endpoint=True,
            connect_timeout=3,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 2},
        ),
    )


def runtime_values(
    service: str,
    *,
    environ: Mapping[str, str] | None = None,
    ssm_client=None,
) -> dict[str, str]:
    """Return BaseSettings overrides for this owner's configured SecureStrings.

    Local settings and ECS secrets injection do not configure parameter ARNs and
    therefore perform no AWS credential discovery or network call. An injected
    client is the explicit test seam; production uses only Lambda role credentials.
    """
    if service not in FIELDS:
        raise ValueError("Unknown settings owner")
    env = os.environ if environ is None else environ
    references = {
        field: env[f"{service}_{field.upper()}_PARAMETER_ARN"]
        for field in FIELDS[service]
        if env.get(f"{service}_{field.upper()}_PARAMETER_ARN")
    }
    if not references:
        return {}
    matches = [PARAMETER_ARN.fullmatch(arn) for arn in references.values()]
    if not all(matches):
        raise RuntimeConfigurationError("Secret references must be complete SSM parameter ARNs")
    locations = {match.group(1, 2, 3) for match in matches if match is not None}
    if len(locations) != 1:
        raise RuntimeConfigurationError("Owner secret references must share one account and region")
    region = next(iter(locations))[1]
    client = ssm_client if ssm_client is not None else _native_client(env, region)
    try:
        values = {}
        for field, arn in references.items():
            try:
                response = client.get_parameter(Name=arn, WithDecryption=True)
                parameter = response["Parameter"]
                value = parameter["Value"]
                if (
                    parameter.get("ARN") != arn
                    or parameter.get("Type") != "SecureString"
                    or not isinstance(value, str)
                    or not value.strip()
                ):
                    raise ValueError("Invalid secret response")
                values[field] = value
            except Exception:
                # SDK exceptions can contain URLs or response data. Keep them out
                # of application errors, tracebacks and public evidence.
                raise RuntimeConfigurationError(
                    "Unable to load owner runtime configuration"
                ) from None
        return values
    finally:
        if ssm_client is None:
            client.close()
