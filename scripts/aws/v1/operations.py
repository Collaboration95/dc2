"""Operator CLI plumbing shared by the session and release entrypoints.

Importing this module performs no AWS call. A live transport exists only when an
operator runs a CLI without --dry-run, with an explicit --profile/--region/--account
(there is no default profile and no ambient credential), after a fresh STS check.
--dry-run executes the real Session/release logic against PlanTransport, a stateful
offline simulation, and prints the calls that would be made. It touches neither the
network nor the operator's journal.
"""

import copy
import json
import re
import tempfile
import time
from pathlib import Path

from scripts.aws.journal import Journal
from scripts.aws.transport import OperationError
from scripts.aws.v1.hooks import refuse_ambient_credentials
from scripts.aws.v1.transport import REGION, OperatorTransport

HANDLERS = (
    "MediaApi",
    "MediaAuthorizer",
    "ProcessingApi",
    "ProcessingCommands",
    "MediaResults",
    "MediaRepair",
    "ProcessingRepair",
    "ProcessingEcsEvents",
    "ProcessingS3Events",
)
# Present in the stack outputs only when it was deployed with UnattendedLaunch=true (#68).
LAUNCHER = "ProcessingLauncher"
INTAKE = ("MediaApi", "MediaAuthorizer")
MAPPINGS = ("ProcessingCommands", "MediaResults")
RULES = ("MediaRepair", "ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events")
# Present only when the stack was deployed with LambdaShortEncodes=true (#93). It runs the
# worker image, so it joins the session's mappings and functions but never an owner's release.
SHORT_ENCODER = "ProcessingShortEncoder"
# Default open throttle mirrors the previous template value; tune per session.
DEFAULT_EDGE_OPEN = {"rate": 5, "burst": 10}
QUEUES = ("ProcessingCommands", "ProcessingWork", "MediaResults")
SERVICES = ("lambda", "events", "apigatewayv2", "ecs", "logs")
PROFILE_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def normalize_outputs(outputs):
    """Accept either a mapping or the CloudFormation describe-stacks Outputs list."""
    if isinstance(outputs, list):
        outputs = {o["OutputKey"]: o["OutputValue"] for o in outputs}
    if not isinstance(outputs, dict) or not all(isinstance(v, str) for v in outputs.values()):
        raise OperationError("Stack outputs must map names to strings")
    return outputs


def config_from_outputs(
    outputs,
    *,
    station,
    environment,
    reservations=None,
    edge_open=None,
    worker_lifetime_seconds=1800,
):
    """Translate emitted stack outputs into the session configuration.

    reservations maps a handler name to a positive int to reserve it; the default is
    None (unreserved while open), the only choice an account limit of 10 permits.
    """
    outputs = normalize_outputs(outputs)
    reservations = reservations or {}
    if reservations.keys() - set(HANDLERS):
        raise OperationError("Unknown handler in reservations")
    try:
        names = {h: outputs[f"{h}FunctionName"] for h in HANDLERS}
        config = {
            "operator_station": station,
            "environment_id": environment,
            "functions": {names[h]: reservations.get(h) for h in HANDLERS},
            "intake_functions": [names[h] for h in INTAKE],
            # A release window serves the public API only: consumers and repair stay off.
            "window_functions": [names[h] for h in (*INTAKE, "ProcessingApi")],
            "mappings": [outputs[f"{h}MappingId"] for h in MAPPINGS],
            "schedules": [outputs[f"{h}RuleName"] for h in RULES],
            "gateway": {
                "api_id": outputs["HttpApiId"],
                "stage": "$default",
                "open": dict(edge_open or DEFAULT_EDGE_OPEN),
            },
            "zero_reservation": "off",
            "cluster": outputs["ClusterArn"],
            "task_definitions": {"worker": outputs["WorkerTaskDefinitionArn"]},
            "network": {
                "subnets": outputs["PublicTaskSubnetIds"].split(","),
                "security_groups": [outputs["WorkerSecurityGroupId"]],
                "assign_public_ip": "ENABLED",
            },
            "alias": "live",
            "task_networks": {
                f"{owner}_migration": {
                    "subnets": outputs["PublicTaskSubnetIds"].split(","),
                    "security_groups": [outputs["MigrationSecurityGroupId"]],
                    "assign_public_ip": "ENABLED",
                }
                for owner in ("media", "processing")
            },
            "max_worker_tasks": 3,
            "worker_lifetime_seconds": worker_lifetime_seconds,
            "owner_consumers": {
                "media": {
                    "mappings": [outputs["MediaResultsMappingId"]],
                    "schedules": [outputs["MediaRepairRuleName"]],
                },
                "processing": {
                    "mappings": [outputs["ProcessingCommandsMappingId"]],
                    "schedules": [
                        outputs[f"{h}RuleName"]
                        for h in ("ProcessingRepair", "ProcessingEcsEvents", "ProcessingS3Events")
                    ],
                },
            },
            "owner_functions": {
                "media": {h: names[h] for h in HANDLERS if h.startswith("Media")},
                "processing": {h: names[h] for h in HANDLERS if h.startswith("Processing")},
            },
        }
        hooks = {
            "processing_api": names["ProcessingApi"],
            "media_api": names["MediaApi"],
            "repairs": [names["MediaRepair"], names["ProcessingRepair"]],
        }
        if f"{LAUNCHER}FunctionName" in outputs:
            # The launcher joins Processing's releases and quiescence, but never `schedules`:
            # `session open` enables every schedule, and this one needs an explicit opt-in.
            launcher, rule = outputs[f"{LAUNCHER}FunctionName"], outputs[f"{LAUNCHER}RuleName"]
            config["launcher"] = {"function": launcher, "rule": rule}
            config["functions"][launcher] = reservations.get(LAUNCHER)
            config["owner_functions"]["processing"][LAUNCHER] = launcher
            config["owner_consumers"]["processing"]["schedules"].append(rule)
            hooks["launcher"] = launcher
        if f"{SHORT_ENCODER}FunctionName" in outputs:
            encoder = outputs[f"{SHORT_ENCODER}FunctionName"]
            mapping = outputs[f"{SHORT_ENCODER}MappingId"]
            config["functions"][encoder] = reservations.get(SHORT_ENCODER)
            # `session open` enables every mapping and `close` disables every mapping.
            config["mappings"].append(mapping)
            config["owner_consumers"]["processing"]["mappings"].append(mapping)
        # The in-VPC schema/count reader runs each owner's own deployed migration definition,
        # because that task already holds the owner's database role and CA. Optional: an older
        # stack's outputs lack them and the reader then says so instead of guessing.
        definitions = {
            owner: outputs[f"{owner.title()}MigrationTaskDefinitionArn"]
            for owner in ("media", "processing")
            if f"{owner.title()}MigrationTaskDefinitionArn" in outputs
        }
        if definitions:
            config["migration_definitions"] = definitions
        urls = {
            "gateway": outputs["HttpApiUrl"],
            "frontend": outputs.get("FrontendUrl"),
            "dlq": {
                q: {"url": outputs.get(f"{q}DlqUrl"), "arn": outputs.get(f"{q}DlqArn")}
                for q in QUEUES
            },
        }
    except KeyError:
        raise OperationError("Stack outputs are missing a required V1 value") from None
    return config, hooks, urls


def load_operator_config(path):
    """Nonsecret operator file: station, environment, journal path and outputs file."""
    try:
        data = json.loads(Path(path).read_text())
        outputs = json.loads(Path(data["outputs_file"]).read_text())
    except (OSError, ValueError, KeyError, TypeError):
        raise OperationError("Operator config or stack outputs unreadable") from None
    allowed = {
        "operator_station",
        "environment_id",
        "journal",
        "outputs_file",
        "reservations",
        "edge_open",
        "worker_lifetime_seconds",
        "sql",
        "counts_file",
        "smoke",
    }
    if not isinstance(data, dict) or data.keys() - allowed:
        raise OperationError("Operator config has unsupported fields")
    config, hooks, urls = config_from_outputs(
        outputs,
        station=data["operator_station"],
        environment=data["environment_id"],
        reservations=data.get("reservations"),
        edge_open=data.get("edge_open"),
        worker_lifetime_seconds=data.get("worker_lifetime_seconds", 1800),
    )
    return data, config, hooks, urls


def add_scope_arguments(parser):
    parser.add_argument("--profile", required=True,
                        help="explicit AWS profile, e.g. dc2-agent; never default")
    parser.add_argument("--region", required=True, help="must be " + REGION)
    parser.add_argument("--account", help="12-digit account (or DC2_AWS_ACCOUNT)")
    parser.add_argument("--dry-run", action="store_true", help="print planned calls; no AWS")
    parser.add_argument("--deadline-seconds", type=int, default=600)


def resolve_scope(parser, args, environ):
    account = args.account or environ.get("DC2_AWS_ACCOUNT", "")
    if (
        args.profile == "default"
        or not PROFILE_PATTERN.fullmatch(args.profile)
        or args.region != REGION
        or not re.fullmatch(r"[0-9]{12}", account or "")
    ):
        parser.error(f"An explicit non-default profile, {REGION} and a 12-digit account required")
    if not 30 <= args.deadline_seconds <= 3600:
        parser.error("--deadline-seconds must be 30..3600")
    return {"profile": args.profile, "region": args.region, "account": account}


def _verified_session(scope, boto3_module):
    """One explicit profile, ambient credentials refused, STS account proven first."""
    refuse_ambient_credentials()
    if boto3_module is None:
        import boto3 as boto3_module
    from botocore.config import Config

    quick = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=10)
    session = boto3_module.Session(profile_name=scope["profile"], region_name=scope["region"])
    try:
        identity = session.client("sts", config=quick).get_caller_identity()
    except Exception:
        # An expired MFA session is the commonest cause on a long cloud-proof day.
        hint = ": an MFA session may have expired; run scripts.aws.v1.mfa_session" if (
            scope["profile"].endswith("-mfa")) else ""
        raise OperationError("STS identity verification failed" + hint) from None
    if identity.get("Account") != scope["account"]:
        raise OperationError("Profile resolves to a different account; no calls made")
    return session, identity, quick


def live_sqs_client(scope, *, boto3_module=None):
    """SQS client for the shared delivery.dlq helper, under the same identity checks."""
    session, _, quick = _verified_session(scope, boto3_module)
    return session.client("sqs", config=quick)


def live_transport(scope, *, boto3_module=None):
    """Explicit-profile SDK clients, one attempt each, after a fresh STS identity check."""
    session, identity, quick = _verified_session(scope, boto3_module)
    from botocore.config import Config

    # Synchronous owner invocations may wait on an Aurora resume (function timeout 60 s).
    long = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=65)
    clients = {
        service: session.client(service, config=long if service == "lambda" else quick)
        for service in SERVICES
    }
    return OperatorTransport(
        clients,
        identity=identity,
        account=scope["account"],
        region=scope["region"],
        budgets={"lambda": 70},
    )


class PlanTransport:
    """Stateful offline stand-in that records each call a command would issue."""

    def __init__(self, *, concurrency=None, rules=None, mappings=None):
        self.calls = []
        self.functions = dict(concurrency or {})
        self.mappings = dict(mappings or {})
        self.rules = dict(rules or {})
        self.stage = {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}
        self.tasks = {}
        self.launcher = {"enabled": False}  # simulated control row

    def call(self, service, operation, payload, *, deadline):
        if deadline <= time.monotonic():
            raise OperationError("A live finite deadline is required")
        self.calls.append(
            {"service": service, "operation": operation, "payload": copy.deepcopy(payload)}
        )
        name = payload.get("FunctionName")
        if operation == "put-function-concurrency":
            self.functions[name] = payload["ReservedConcurrentExecutions"]
        elif operation == "delete-function-concurrency":
            self.functions[name] = None
        elif operation == "get-function-concurrency":
            value = self.functions.get(name)
            return {} if value is None else {"ReservedConcurrentExecutions": value}
        elif operation == "get-account-settings":
            return {"AccountLimit": {"ConcurrentExecutions": 1000}}  # simulated, not observed
        elif operation == "update-event-source-mapping":
            self.mappings[payload["UUID"]] = "Enabled" if payload["Enabled"] else "Disabled"
        elif operation == "get-event-source-mapping":
            return {"State": self.mappings.get(payload["UUID"], "Disabled")}
        elif operation in {"enable-rule", "disable-rule"}:
            self.rules[payload["Name"]] = "ENABLED" if operation == "enable-rule" else "DISABLED"
        elif operation == "describe-rule":
            return {"State": self.rules.get(payload["Name"], "DISABLED")}
        elif operation == "update-stage":
            self.stage = dict(payload["DefaultRouteSettings"])
        elif operation == "get-stage":
            return {"DefaultRouteSettings": dict(self.stage)}
        elif operation == "invoke":
            if payload["Payload"].get("dc2_operation") == "launcher":
                action = payload["Payload"].get("action")
                self.launcher = {**self.launcher, "enabled": action == "enable"} if (
                    action in {"enable", "disable"}
                ) else self.launcher
                reply = {"service": "processing-launcher", "action": action, "ambiguous": 0,
                         **self.launcher}
            elif payload["Payload"].get("dc2_operation") == "ready":
                service = "media" if "Media" in payload["FunctionName"] else "processing"
                reply = {"service": service, "ready": True}
            else:
                reply = {"published": 0}
            return {"StatusCode": 200, "FunctionError": False, "Payload": reply}
        elif operation == "run-task":
            arn = "arn:simulated:task/" + payload["clientToken"]
            self.tasks[arn] = {
                "taskArn": arn,
                "taskDefinitionArn": payload["taskDefinition"],
                "lastStatus": "RUNNING",
            }
            return {"tasks": [self.tasks[arn]]}
        elif operation == "list-tasks":
            return {"taskArns": list(self.tasks)}
        elif operation == "describe-tasks":
            return {"tasks": [self.tasks[a] for a in payload["tasks"] if a in self.tasks]}
        return {}


class PlanJournal:
    """Throwaway private journal: dry-run must never read or write the real one."""

    def __init__(self, config, *, session="closed"):
        self.directory = tempfile.TemporaryDirectory(prefix="dc2-dry-run-")
        Path(self.directory.name).chmod(0o700)
        self.journal = Journal(
            Path(self.directory.name) / "session.json",
            station=config["operator_station"],
            environment=config["environment_id"],
        )
        self.journal.initialize(verified_empty=True, exclusive_station=True)
        if session != "closed":
            with self.journal.locked() as state:
                state.update(session=session, paused=False)
                self.journal.save(state)

    def cleanup(self):
        self.directory.cleanup()
