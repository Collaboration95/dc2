"""Journaled, resumable first deployment and teardown of V1 (offline unless run by an operator).

    python -m scripts.aws.v1.deploy deploy   --profile P --region ap-southeast-1 --account A ...
    python -m scripts.aws.v1.deploy teardown --profile P --region ap-southeast-1 --account A ...
    python -m scripts.aws.v1.deploy rehearse ...   # deploy + teardown against a simulation only
    python -m scripts.aws.v1.deploy status   --state-dir D --run-id R

Nothing here discovers credentials. Every live call is an `aws` CLI invocation with the one
explicit profile (never `default`), a sanitized environment and a freshly verified STS account.
`--dry-run` replaces the transport with an offline simulation, writes to a throwaway journal
and prints the exact commands that would run; it proves ordering and request shape, not
account facts. Without `--execute` a live deploy stops at the first described change set and a
live teardown only inventories and prints its plan.

Ownership is established twice before anything is deleted: the physical id was recorded in the
run's journal when this pipeline's stack created it, AND the live resource still carries the
`deploy-project` and `owner-run` tags. A resource failing either test is reported, never touched.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from scripts.aws.journal import Journal
from scripts.aws.transport import SECRET_KEY, OperationError
from scripts.aws.v1 import bootstrap as db_bootstrap
from scripts.aws.v1 import config as render_config
from scripts.aws.v1 import credentials, operations, session_cli
from scripts.aws.v1 import frontend as spa
from scripts.aws.v1.definitions import SEPARATE, DatabaseOptions
from scripts.aws.v1.definitions import template as render_template
from scripts.aws.v1.hooks import refuse_ambient_credentials
from scripts.aws.v1.migration import migrate
from scripts.aws.v1.public_smoke import PublicSmoke, urllib_http, validate_base_url
from scripts.aws.v1.transport import REGION, validate_arguments
from scripts.aws.v1_operator import sanitized_environment
from scripts.ci import policy

ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_TEMPLATE = ROOT / "deploy/aws/v1-operator-bootstrap.json"
PROJECT_KEY, PROJECT_VALUE, RUN_KEY = "deploy-project", "dc2-v1", "owner-run"
# Observed 2026-10-16: ROLLBACK_COMPLETE, no resources (FlickPondRequireMFA denied CreateBucket).
LEGACY_BOOTSTRAP_STACK = "dc2-v1-20261015t1146-bootstrap"
DEFAULT_BUDGET_NAME = "flickpond-monthly"
FARGATE_VCPU_QUOTA_CODE = "L-3032A538"
HEALTHY = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
CAPABILITIES = ["CAPABILITY_NAMED_IAM"]
DEPLOY_STEPS = (
    "preflight",
    "bootstrap-stack",
    "foundation",
    "images",
    "applications",
    "frontend",
    "db-bootstrap",
    "migrations",
    "session-init",
    "session-window",
    "seed",
    "public-smoke",
    "session-close",
)
# The persistent environment (#235) opens once and stays open: the booked window/close pair
# becomes one `session-open` that runs on the first deploy only (#236).
PERSISTENT_STEPS = (
    *DEPLOY_STEPS[:DEPLOY_STEPS.index("session-window")],
    "session-open",
    "seed",
    "public-smoke",
)
# The launcher's SQL flag needs a session end even always on, where nothing enforces it.
ALWAYS_ON_OPEN_MINUTES = 60
INVOCATION_HISTORY = 20
TEARDOWN_STEPS = (
    "td-inventory",
    "td-session-close",
    "td-quiesce",
    "td-buckets-emptied",
    "td-images-deleted",
    "td-database",
    "td-parameters",
    "td-stack",
    "td-bootstrap-stack",
    "td-retained",
    "td-receipt",
)
# Re-sweeps before a bucket delete gives up; a 15-minute upload grant is the longest write source.
BUCKET_DELETE_ATTEMPTS, BUCKET_RETRY_SECONDS = 5, 10
# Consecutive MISSING answers before a task ECS does not report is taken as long stopped.
MISSING_LOOKS = 3
# Session close checks that cannot pass while an encoder task still runs.
DRAIN_CHECKS = {"drain", "outcomes", "inventory"}
AURORA_VERSION = "16.8" # the renderer's default; the observed orderable version
OWNERS = ("media", "processing")
DEFINITIVE_MIGRATION_FAILURES = {"Migration task failed", "Owning schema revision mismatch"}
# Prices: the receipt's cited ap-southeast-1 offer files (cloud-operator-20261015.md).
ACU_HOUR, FARGATE_VCPU_HOUR, FARGATE_GIB_HOUR, IPV4_HOUR = 0.20, 0.05056, 0.00553, 0.005
# Retained per month with the stack idle: master secret, ECR layers, Aurora storage, logs.
RETAINED_MONTH_USD = 0.40 + 0.15 + 0.11 + 0.10
# What one more cluster retains per month: its managed master secret and its Aurora storage.
EXTRA_CLUSTER_MONTH_USD = 0.40 + 0.11


# What FlickPondRequireMFA keys on, asked of the policy simulator with MFA absent: one action
# CloudFormation makes for the caller (s3:CreateBucket killed the 2026-10-15 bootstrap) and one
# direct call. A principal the deny does not cover is allowed both; one it covers is explicitly
# denied both.
MFA_PROBE_ACTIONS = ["s3:CreateBucket", "cloudformation:CreateStack"]
MFA_PROBE_CONTEXT = [
    {"ContextKeyName": "aws:MultiFactorAuthPresent", "ContextKeyValues": ["false"],
     "ContextKeyType": "boolean"},
    {"ContextKeyName": "aws:ViaAWSService", "ContextKeyValues": ["false"],
     "ContextKeyType": "boolean"},
    {"ContextKeyName": "aws:RequestedRegion", "ContextKeyValues": [REGION],
     "ContextKeyType": "string"},
]
IAM_USER_ARN = re.compile(r"arn:aws:iam::[0-9]{12}:user/(?:.*/)?([^/]+)")


class DeployError(OperationError):
    """Safe-to-print failure. Never carries a payload, DSN, credential or raw stderr."""


class AwaitingExecute(DeployError):
    """A change set was created and described; the operator has not passed --execute."""


class AwsError(DeployError):
    def __init__(self, service, operation, code, hint=""):
        super().__init__(f"aws {service} {operation} failed: {code}")
        self.code, self.hint = code, hint


# --------------------------------------------------------------------------- transport
ALLOWED = {
    "sts": {"get-caller-identity"},
    # simulate-principal-policy only evaluates policy text; it changes nothing in the account.
    "iam": {"list-mfa-devices", "simulate-principal-policy"},
    "lambda": {"get-account-settings"},
    "service-quotas": {"get-service-quota"},
    "budgets": {"describe-budgets"},
    "ce": {"get-cost-and-usage", "get-cost-forecast"},
    "resourcegroupstaggingapi": {"get-resources"},
    # Read-only existence checks the teardown receipt makes on tagging-API hits (#147).
    "ec2": {
        "describe-vpcs", "describe-subnets", "describe-security-groups", "describe-route-tables",
        "describe-internet-gateways", "describe-egress-only-internet-gateways",
        "describe-vpc-endpoints",
    },
    "cloudfront": {"create-invalidation", "get-invalidation"},
    "cloudformation": {
        "describe-stacks", "create-change-set", "describe-change-set", "execute-change-set",
        "describe-stack-events", "describe-stack-resources", "delete-stack",
    },
    "s3api": {
        "head-bucket", "put-object", "get-bucket-tagging", "list-object-versions",
        "list-objects-v2", "delete-objects", "list-multipart-uploads", "abort-multipart-upload",
        "delete-bucket",
    },
    "ecr": {
        "get-authorization-token", "describe-images", "describe-image-scan-findings",
        "list-images", "batch-delete-image", "delete-repository", "list-tags-for-resource",
    },
    "rds": {
        "describe-db-clusters", "describe-db-instances", "modify-db-cluster",
        "delete-db-instance", "delete-db-cluster", "list-tags-for-resource",
        "describe-db-engine-versions",
        "add-tags-to-resource", "describe-db-cluster-snapshots",
    },
    "ssm": {
        "describe-parameters", "put-parameter", "delete-parameter", "list-tags-for-resource",
        "get-parameters-by-path",
    },
    "secretsmanager": {"get-secret-value"},
    "logs": {"describe-log-groups", "delete-log-group", "list-tags-for-resource",
             "get-log-events", "filter-log-events"},
    "ecs": {"run-task", "describe-tasks", "list-tasks", "stop-task", "describe-task-definition",
            "register-task-definition", "deregister-task-definition",
            "describe-clusters", "delete-task-definitions"},
    # Read-only observations the cloud-proof harnesses make through this same transport.
    "cloudwatch": {"get-metric-statistics"},
    "apigatewayv2": {"get-stage"},
}
# RDS answers a missing instance with the wire code DBInstanceNotFound; only the SDK exception
# carries the Fault suffix (clusters do use DBClusterNotFoundFault). Seen on 2026-10-17.
INSTANCE_NOT_FOUND = ("DBInstanceNotFound", "DBInstanceNotFoundFault")
CLUSTER_NOT_FOUND = ("DBClusterNotFoundFault", "DBClusterNotFound")
SNAPSHOT_NOT_FOUND = ("DBClusterSnapshotNotFound", "DBClusterSnapshotNotFoundFault")
# The tagging API keeps listing a deleted resource for a while (the 2026-10-17 r1017a teardown
# reported ten that were all gone). Each hit is therefore asked of the service that owns it:
# ARN resource type -> (EC2 describe operation, request key). An unlisted type is never guessed.
EC2_CHECKS = {
    "vpc": ("describe-vpcs", "VpcIds"),
    "subnet": ("describe-subnets", "SubnetIds"),
    "security-group": ("describe-security-groups", "GroupIds"),
    "route-table": ("describe-route-tables", "RouteTableIds"),
    "internet-gateway": ("describe-internet-gateways", "InternetGatewayIds"),
    "egress-only-internet-gateway": (
        "describe-egress-only-internet-gateways", "EgressOnlyInternetGatewayIds"),
    "vpc-endpoint": ("describe-vpc-endpoints", "VpcEndpointIds"),
}
# A deregistered task definition stays listed as INACTIVE, costs nothing, and goes away once
# deleted (DELETE_IN_PROGRESS first). A cluster whose tasks and services are gone is INACTIVE.
ECS_GONE = {"INACTIVE", "DELETE_IN_PROGRESS"}
# `delete-task-definitions` accepts at most ten per call.
TASK_DEFINITION_DELETE_BATCH = 10
_ARN_RESOURCE = re.compile(r"([^/:]+)[/:](.+)", re.S)
_RESOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,299}")
READ_PREFIXES = ("describe", "get", "list", "head", "filter", "simulate-principal-policy")
SENSITIVE_RESULT = {("secretsmanager", "get-secret-value"), ("ecr", "get-authorization-token")}


def is_mutating(operation):
    return not operation.startswith(READ_PREFIXES)


def _id_list(low, high):
    return lambda v: (isinstance(v, list) and low <= len(v) <= high
                      and all(isinstance(i, str) and _RESOURCE_ID.fullmatch(i) for i in v))


# Operations only the teardown receipt makes. They are checked here and deliberately not added to
# the shared operator contract (scripts/aws/v1/transport.py), which the session and release
# transports also use and which must not gain a deletion it has no need for.
RECEIPT_CONTRACT = {
    ("ec2", op): ({key: _id_list(1, 1)}, {}) for op, key in EC2_CHECKS.values()
} | {
    ("ecs", "describe-clusters"): ({"clusters": _id_list(1, 100)}, {}),
    ("ecs", "delete-task-definitions"): (
        {"taskDefinitions": _id_list(1, TASK_DEFINITION_DELETE_BATCH)}, {}),
}


def check_operation(service, operation, payload):
    if operation not in ALLOWED.get(service, ()) or not isinstance(payload, dict):
        raise DeployError("Operation is outside the deploy pipeline's allowlist")
    contract = RECEIPT_CONTRACT.get((service, operation))
    if contract:
        required, _ = contract
        if payload.keys() != required.keys() or not all(
                required[k](v) for k, v in payload.items()):
            raise DeployError("Operation arguments do not match the deploy pipeline's contract")
    elif service == "ecs":  # reuse the session/release argument contract for task operations
        validate_arguments(service, operation, payload)


def redact(service, operation, payload):
    """Copy of payload that is safe to print, journal or show in a plan."""
    hidden = {("ssm", "put-parameter"): {"Value"}}.get((service, operation), set())

    def walk(value, key="", top=False):
        if (top and key in hidden) or (key and SECRET_KEY.search(key) and isinstance(value, str)):
            return "<redacted>"
        if isinstance(value, dict):
            return {k: walk(v, k, top=top and key == "") for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        return value

    return walk(payload, top=True)


def command_argv(scope, service, operation, payload, *, input_json):
    """The `aws` argv. `input_json` is a file:// reference live and the redacted JSON in plans."""
    argv = [
        "aws", "--profile", scope["profile"], "--region", scope["region"], "--no-cli-pager",
        "--output", "json", "--cli-connect-timeout", "10", "--cli-read-timeout", "60",
        service, operation,
    ]
    rest = {k: v for k, v in payload.items() if k != "Body"}
    if "Body" in payload:  # streaming blobs are file paths and cannot travel in input JSON
        argv += ["--body", str(payload["Body"])]
    if rest:
        argv += ["--cli-input-json", input_json]
    return argv


def display_command(scope, service, operation, payload):
    """What a plan shows. Template bodies are files live, so only their size and hash print."""
    safe = redact(service, operation, payload)
    if "TemplateBody" in safe:
        body = safe["TemplateBody"]
        digest = hashlib.sha256(body.encode()).hexdigest()[:12]
        safe["TemplateBody"] = f"<{len(body)} bytes sha256:{digest}>"
    text = json.dumps({k: v for k, v in safe.items() if k != "Body"}, sort_keys=True,
                      separators=(",", ":"))
    return shlex.join(command_argv(scope, service, operation, safe, input_json=text))


_ERROR = re.compile(r"An error occurred \(([A-Za-z0-9.]+)\)[^:]*:\s*(.*)", re.S)


class CliTransport:
    """Runs allowlisted `aws` CLI calls. Request JSON goes through a private 0600 file.

    A file, not an argument, so a secret never appears in `ps` output; the file is removed
    as soon as the call returns.
    """

    simulated = False

    def __init__(self, scope, *, runner=subprocess.run, environ=None, timeout=300):
        refuse_ambient_credentials(os.environ if environ is None else environ)
        self.scope, self.runner, self.timeout = scope, runner, timeout
        self.env = sanitized_environment()

    def call(self, service, operation, payload, *, deadline=None):
        check_operation(service, operation, payload)
        with tempfile.TemporaryDirectory(prefix="dc2-deploy-") as directory:
            Path(directory).chmod(0o700)
            path = Path(directory) / "request.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump({k: v for k, v in payload.items() if k != "Body"}, handle)
            argv = command_argv(
                self.scope, service, operation, payload, input_json=f"file://{path}"
            )
            try:
                done = self.runner(
                    argv, env=self.env, capture_output=True, text=True, timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise AwsError(service, operation, "ClientTimeout") from None
        if done.returncode:
            match = _ERROR.search(done.stderr or "")
            code = match.group(1) if match else "CliError"
            hint = match.group(2).strip()[:200] if match else ""
            raise AwsError(service, operation, code, hint)
        try:
            return json.loads(done.stdout) if done.stdout.strip() else {}
        except ValueError:
            raise AwsError(service, operation, "UnparseableResponse") from None


class DockerCli:
    """`docker` with a private DOCKER_CONFIG so a registry login never reaches ~/.docker."""

    simulated = False

    def __init__(self, runner=subprocess.run):
        self.runner, self.config_dir = runner, tempfile.mkdtemp(prefix="dc2-docker-")
        Path(self.config_dir).chmod(0o700)

    def __call__(self, argv, *, stdin=None):
        env = dict(sanitized_environment(), DOCKER_CONFIG=self.config_dir)
        done = self.runner(
            ["docker", *argv], env=env, input=stdin, capture_output=True, text=True,
            timeout=3600, check=False,
        )
        if done.returncode:
            raise DeployError(f"docker {argv[0]} failed (exit {done.returncode})")
        return done.stdout

    def close(self):
        import shutil

        shutil.rmtree(self.config_dir, ignore_errors=True)


# ------------------------------------------------------------------------------ journal
class DeployJournal(Journal):
    """The shared private atomic journal, carrying this pipeline's state under `deploy`.

    Only names and identifiers are stored. The shared secret screen runs on every save, so a
    value that looks like a DSN, key or credential fails loudly instead of persisting.
    """

    def exists(self):
        return self.path.exists()

    def create(self, meta):
        self._directory()
        with self._lock():
            if self.path.exists():
                raise DeployError("A journal already exists for this run")
            self.save({
                "version": 1, "station": self.station, "environment": self.environment,
                "launches": {}, "paused": True, "pending_release": None, "session": "closed",
                "deploy": meta,
            })

    def view(self):
        with self.locked() as state:
            return copy.deepcopy(state["deploy"])

    def mutate(self, change):
        with self.locked() as state:
            change(state["deploy"])
            self.save(state)

    @contextlib.contextmanager
    def run_lock(self):
        """One deploy/teardown process per run, held for its whole duration."""
        import fcntl

        self._directory()
        fd = os.open(str(self.path) + ".run", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeployError("Another deploy process holds this run") from None
            yield
        finally:
            os.close(fd)


def simulated_session(_profile):
    return {"kind": "session", "expires_at": None, "remaining_seconds": None}


def in_flight(status):
    # REVIEW_IN_PROGRESS is a stack holding only an unexecuted change set: nothing is running.
    return status.endswith("_IN_PROGRESS") and status != "REVIEW_IN_PROGRESS"


def remember(resources, key, value):
    items = resources.setdefault(key, [])
    if value not in items:
        items.append(value)


def append_event(deploy, entry):
    deploy["events"].append(entry)
    del deploy["events"][:-500]  # a bounded audit trail; the step records carry the detail


def now():
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------- settings
@dataclasses.dataclass
class Settings:
    profile: str
    region: str
    account: str
    run_id: str
    state_dir: Path
    budget_usd: float = 30.0
    budget_name: str = DEFAULT_BUDGET_NAME
    forecast_usd: float | None = None
    planned_hours: float = 3.0
    execute: bool = False
    dry_run: bool = False
    images_file: Path | None = None
    adopt_bootstrap: str | None = None
    allow_replacement: bool = False
    skip_final_snapshot: bool = False
    confirm_run_id: str | None = None
    seed_email: str | None = None
    counts_file: Path | None = None
    assume_empty_counts: bool = False
    sql_config: Path | None = None
    station: str = "dc2-deploy-station"
    # The opt-in V2 database layout (#94); the defaults are V1's one cluster.
    database: DatabaseOptions = dataclasses.field(default_factory=DatabaseOptions)
    # The opt-in V2 launcher (#68): renders UnattendedLaunch=true; off keeps the V1 template.
    unattended_launch: bool = False
    # V2-live (#235): `run_id` names a long-lived environment (stack dc2-<name>) that every
    # deploy updates in place, deployed always on (#236) with the launcher (#237).
    persistent: bool = False
    stage_rate_limit: int = 20
    stage_burst_limit: int = 50
    monthly_budget_usd: int = 20
    budget_alert_email: str = ""

    def __post_init__(self):
        if self.profile == "default" or not operations.PROFILE_PATTERN.fullmatch(self.profile):
            raise DeployError("An explicit non-default AWS profile is required")
        if self.region != REGION:
            raise DeployError(f"V1 deploys only to {REGION}")
        if not re.fullmatch(r"[0-9]{12}", self.account or ""):
            raise DeployError("An explicit 12-digit account is required")
        # EnvironmentId allows 24 characters and 'dc2-v1-' takes seven of them.
        if not re.fullmatch(r"[a-z0-9]{2,16}", self.run_id or ""):
            raise DeployError("--run-id must be 2-16 lowercase letters or digits")
        if not 0 < self.budget_usd <= 1000:
            raise DeployError("--budget-usd must be positive")
        self.state_dir = Path(self.state_dir)
        if self.persistent:
            self.unattended_launch = True  # encoders start from the queue, never by hand

    @property
    def env(self):
        return env_name(self.run_id, persistent=self.persistent)

    @property
    def scope(self):
        return {"profile": self.profile, "region": self.region, "account": self.account}

    @property
    def tags(self):
        return [{"Key": PROJECT_KEY, "Value": PROJECT_VALUE},
                {"Key": RUN_KEY, "Value": self.run_id}]

    @property
    def bootstrap_stack(self):
        return f"{self.env}-bootstrap"

    @property
    def artifacts_bucket(self):
        return f"{self.env}-artifacts-{self.account}"


def env_name(name, *, persistent=False):
    return f"dc2-{name}" if persistent else f"dc2-v1-{name}"


def owned(tags, run_id):
    """Tag half of the ownership test. `tags` is a Key/Value list or a mapping."""
    if isinstance(tags, list):
        tags = {t["Key"]: t["Value"] for t in tags}
    return tags.get(PROJECT_KEY) == PROJECT_VALUE and tags.get(RUN_KEY) == run_id


def remember_snapshot(deploy_state, name):
    """Add a final snapshot to the journal. `final_snapshot` stays the first, as in V1."""
    known = deploy_state.get("final_snapshots") or (
        [deploy_state["final_snapshot"]] if deploy_state.get("final_snapshot") else [])
    if name not in known:
        known.append(name)
    deploy_state["final_snapshots"], deploy_state["final_snapshot"] = known, known[0]


def planned_cost(hours, database=None):
    """Worst-case spend of one deploy window: every cluster at its ACU ceiling throughout.

    Finite 0.25 vCPU / 0.5 GiB bootstrap and migration tasks (about six minutes each, three
    of them) and a month of retained storage are added. Encoders do not run in a first deploy.
    A separate layout (#94) adds a second cluster's ceiling and its retained secret and storage.
    """
    database = database or DatabaseOptions()
    task_hour = 0.25 * FARGATE_VCPU_HOUR + 0.5 * FARGATE_GIB_HOUR + IPV4_HOUR
    retained = RETAINED_MONTH_USD + (database.clusters - 1) * EXTRA_CLUSTER_MONTH_USD
    compute = database.clusters * database.max_capacity * ACU_HOUR * hours
    return round(compute + 3 * 0.1 * task_hour + retained, 2)


# ---------------------------------------------------------------------------- pipeline
class Pipeline:
    def __init__(
        self, settings, aws, journal, *, docker=None, http=None, session_main=None,
        clock=time.monotonic, sleep=time.sleep, stderr=None, today=None, credential_probe=None,
    ):
        self.s, self.aws_transport, self.journal = settings, aws, journal
        self.docker, self.http = docker, http or urllib_http
        self.session_main = session_main or session_cli.main
        self.clock, self.sleep = clock, sleep
        self.stderr = stderr or sys.stderr
        self.today = today or (lambda: dt.datetime.now(dt.UTC).date())
        self.plan, self.step = [], "init"
        self.mfa_answers = {}  # principal ARN -> mfa_required() answer, simulated once per run
        self.deferred, self.journal_held, self.receipt = [], False, None
        self.simulated = bool(getattr(aws, "simulated", False))
        # A simulation has no credentials to classify; it answers like an MFA session.
        self.credential_probe = credential_probe or (
            simulated_session if self.simulated else credentials.probe)

    # ---- plumbing --------------------------------------------------------------
    def say(self, message):
        print(message, file=self.stderr)

    def aws(self, service, operation, payload=None, *, tolerate=()):
        """One CLI call, recorded in the plan. `tolerate` names error codes meaning 'absent'."""
        payload = payload or {}
        self.plan.append({
            "step": self.step, "mutating": is_mutating(operation),
            "command": display_command(self.s.scope, service, operation, payload),
        })
        if is_mutating(operation):
            self.event(service, operation, payload)
        try:
            return self.aws_transport.call(service, operation, payload, deadline=self.clock() + 300)
        except AwsError as error:
            if error.code in tolerate:
                return None
            raise

    def call(self, service, operation, payload, *, deadline=None):
        """The transport interface `migrate` expects, so its calls join the plan and journal."""
        return self.aws(service, operation, payload)

    def run_docker(self, argv, *, stdin=None):
        shown = shlex.join(["docker", *argv]) + (" # password on stdin" if stdin else "")
        entry = {"step": self.step, "mutating": argv[0] in {"push", "login", "tag"},
                 "command": shown}
        self.plan.append(entry)
        answer = self.docker(argv, stdin=stdin)
        # Only a simulated Docker says where an answer came from (observed vs simulated).
        if getattr(self.docker, "basis", None):
            entry["basis"] = self.docker.basis
        return answer

    def event(self, service, operation, payload):
        keys = ("StackName", "Bucket", "repositoryName", "DBClusterIdentifier", "Name",
                "logGroupName", "LogGroupName", "cluster", "DBInstanceIdentifier")
        target = next((str(payload[k]) for k in keys if k in payload), "")
        entry = {"at": now(), "step": self.step, "call": f"{service}.{operation}", "target": target}
        if self.journal_held:  # a caller holds the journal lock; write once it is released
            self.deferred.append(entry)
        else:
            self.journal.mutate(lambda d: append_event(d, entry))

    def flush_events(self):
        pending, self.deferred = self.deferred, []
        for entry in pending:
            self.journal.mutate(lambda d, e=entry: append_event(d, e))

    def meta(self):
        return self.journal.view()

    def mark(self, name, state, **detail):
        def change(d):
            current = d["steps"].setdefault(name, {})
            if "seq" not in current:  # saved JSON is key-sorted; this keeps the real order
                d["seq"] = d.get("seq", 0) + 1
                current["seq"] = d["seq"]
            current.update(status=state, at=now())
            current.setdefault("detail", {}).update(detail)

        self.journal.mutate(change)

    def detail(self, name):
        return self.meta()["steps"].get(name, {}).get("detail", {})

    def established(self):
        """A persistent environment whose first deploy finished: from now on it is updated."""
        return self.s.persistent and bool(self.meta().get("established"))

    def begin_invocation(self):
        """Give this deploy of an established environment its own step log.

        The journal's resources, outputs and images describe the environment and are kept; its
        steps describe one deploy, so the last ones are archived and every step runs again.
        That is what makes a second deploy re-run `applications` as an UPDATE change set
        instead of skipping it as done. A first deploy that failed still resumes as before.
        """
        def change(d):
            if not d.get("established"):
                return
            if d["steps"]:
                history = d.setdefault("invocations", [])
                history.append({"archived_at": now(), "steps": ordered_steps(d)})
                del history[:-INVOCATION_HISTORY]
            d["steps"] = {}

        self.journal.mutate(change)

    def run_step(self, name, action, *, always=False):
        self.step = name
        record = self.meta()["steps"].get(name, {})
        if record.get("status") == "done" and not always:
            self.say(f"[{name}] already done; skipping")
            return record.get("detail", {})
        self.say(f"[{name}] start")
        self.mark(name, "started")
        try:
            result = action() or {}
        except AwaitingExecute as waiting:
            self.mark(name, "awaiting-execute")
            self.say(f"[{name}] {waiting}")
            raise
        except Exception as error:
            try:
                self.mark(name, "failed", error=str(error)[:300])
            except OperationError:  # the secret screen refused the text; record that instead
                self.mark(name, "failed", error="failure text withheld by the secret screen")
            raise
        self.mark(name, "done", **result)
        self.say(f"[{name}] done")
        return result

    def poll(self, check, *, what, timeout, interval=15):
        """check() returns (finished, value). Bounded; the injected clock keeps tests instant."""
        end = self.clock() + timeout
        while True:
            finished, value = check()
            if finished:
                return value
            if self.clock() >= end:
                raise DeployError(f"Timed out waiting for {what}")
            self.sleep(interval)

    # ---- preflight ---------------------------------------------------------------
    def stack(self, name):
        found = self.aws(
            "cloudformation", "describe-stacks", {"StackName": name}, tolerate=("ValidationError",)
        )
        stacks = (found or {}).get("Stacks", [])
        return stacks[0] if stacks else None

    def cost_guard(self):
        """Refuse when month-to-date + forecast + this deploy's worst case exceeds the budget."""
        today = self.today()
        first = today.replace(day=1)
        month_end = (first + dt.timedelta(days=32)).replace(day=1)
        spend = self.aws("ce", "get-cost-and-usage", {
            "TimePeriod": {"Start": first.isoformat(),
                           "End": (today + dt.timedelta(days=1)).isoformat()},
            "Granularity": "MONTHLY", "Metrics": ["UnblendedCost"],
        })
        mtd = sum(
            float(r["Total"]["UnblendedCost"]["Amount"]) for r in spend.get("ResultsByTime", [])
        )
        source = "cost-explorer"
        if self.s.forecast_usd is not None:
            forecast, source = self.s.forecast_usd, "operator-supplied"
        elif today >= month_end - dt.timedelta(days=1):
            forecast = 0.0  # no remaining days to forecast
        else:
            result = self.aws("ce", "get-cost-forecast", {
                "TimePeriod": {"Start": today.isoformat(), "End": month_end.isoformat()},
                "Metric": "UNBLENDED_COST", "Granularity": "MONTHLY",
            }, tolerate=("DataUnavailableException", "AccessDeniedException"))
            if result is None:
                raise DeployError(
                    "Cost forecast unavailable; refusing (fail closed). Pass --forecast-usd "
                    "with the operator's own estimate if Cost Explorer has too little history"
                )
            forecast = float(result["Total"]["Amount"])
        # Updating an environment that already runs adds nothing it does not already cost.
        planned = 0.0 if self.established() else planned_cost(
            self.s.planned_hours, self.s.database)
        total = round(mtd + forecast + planned, 2)
        report = {
            "month_to_date_usd": round(mtd, 2), "forecast_usd": round(forecast, 2),
            "forecast_source": source, "planned_deploy_usd": planned, "total_usd": total,
            "budget_usd": self.s.budget_usd,
        }
        if total > self.s.budget_usd:
            raise DeployError(
                f"Cost guard: ${total} (month-to-date + forecast + planned) exceeds "
                f"--budget-usd ${self.s.budget_usd}"
            )
        return report

    def preflight(self):
        checks, blockers = [], []

        def record(name, status, **detail):
            checks.append({"check": name, "status": status, **detail})
            if status == "blocker":
                blockers.append(name)

        identity = self.aws("sts", "get-caller-identity")
        if identity.get("Account") != self.s.account:
            raise DeployError("STS account differs from --account; no further calls")
        arn = identity.get("Arn", "")
        record("identity", "pass", arn=arn, simulated=self.simulated)
        self._credentials(record, arn)
        user = IAM_USER_ARN.fullmatch(arn)
        if user:
            devices = self.aws("iam", "list-mfa-devices", {"UserName": user.group(1)},
                               tolerate=("AccessDenied", "AccessDeniedException"))
            if devices is not None and not devices.get("MFADevices"):
                # No device is only a problem for a principal the MFA deny applies to.
                required = self.mfa_required(arn)
                if required is False:
                    record("mfa", "pass", detail="no MFA device, and the principal is not "
                           "subject to an MFA deny (simulated)")
                else:
                    record("mfa", "blocker", detail="no MFA device: FlickPondRequireMFA denied "
                           "s3:CreateBucket on 2026-10-15; use a profile that carries an MFA "
                           "session" + ("" if required else " (whether a deny applies could not "
                                        "be simulated, so it is assumed to)"))
            else:
                record("mfa", "pass" if devices else "warn")
        else:
            record("mfa", "info", detail="assumed role or session; MFA state not inspectable")

        limits = self.aws("lambda", "get-account-settings")["AccountLimit"]
        record("lambda-concurrency",
               "pass" if limits.get("ConcurrentExecutions", 0) >= 10 else "blocker",
               limit=limits.get("ConcurrentExecutions"),
               unreserved=limits.get("UnreservedConcurrentExecutions"),
               note="nothing is reserved: the account keeps 10 unreserved")
        quota = self.aws("service-quotas", "get-service-quota", {
            "ServiceCode": "fargate", "QuotaCode": FARGATE_VCPU_QUOTA_CODE})["Quota"]["Value"]
        record("fargate-vcpu", "pass" if quota >= 6 else ("warn" if quota >= 2 else "blocker"),
               quota=quota, note="three 2-vCPU encoders need 6; migration tasks must not overlap")

        engine = self.aws("rds", "describe-db-engine-versions", {
            "Engine": "aurora-postgresql", "EngineVersion": AURORA_VERSION},
            tolerate=("InvalidParameterValue",))
        versions = (engine or {}).get("DBEngineVersions", [])
        support = versions[0].get("ServerlessV2FeaturesSupport", {}) if versions else {}
        record("aurora-engine",
               "pass" if versions and support.get("MinCapacity") == 0 else "blocker",
               version=AURORA_VERSION, min_acu=support.get("MinCapacity"),
               max_acu=support.get("MaxCapacity"),
               note="16.6 was unavailable on 2026-10-15; minimum 0 ACU is what allows pause")

        budgets = self.aws("budgets", "describe-budgets", {"AccountId": self.s.account})
        budget = next((b for b in budgets.get("Budgets", [])
                       if b["BudgetName"] == self.s.budget_name), None)
        if budget is None:
            record("budget", "blocker", detail=f"no budget named {self.s.budget_name}")
        else:
            limit = float(budget["BudgetLimit"]["Amount"])
            ok = budget["BudgetLimit"]["Unit"] == "USD" and limit >= self.s.budget_usd
            record("budget", "pass" if ok else "blocker", limit_usd=limit,
                   detail="" if ok else "budget must be USD and not below --budget-usd")
        try:
            record("cost-guard", "pass", **self.cost_guard())
        except DeployError as error:
            # Routine updates of the persistent environment are never held back by spend: its
            # AWS Budget alerts at 50/80/100 % instead (#235, #236).
            record("cost-guard", "info" if self.established() else "blocker", detail=str(error))

        self._collisions(record)
        proof = ("sql" if self.s.sql_config else "counts-file" if self.s.counts_file
                 else "attested-empty" if self.s.assume_empty_counts else None)
        record("close-proof", "pass" if proof else "blocker", method=proof,
               detail="" if proof else "pass --sql-config, --counts-file or --assume-empty-counts "
               "now; discovering it at the session step would waste an hour of spend")
        if self.s.images_file:
            try:
                load_images(self.s.images_file)
                record("images-input", "pass")
            except DeployError as error:
                record("images-input", "blocker", detail=str(error))
        else:
            record("images-input", "warn", detail="--images is needed from the images step on")
        legacy = self.stack(LEGACY_BOOTSTRAP_STACK)
        if legacy:
            record("legacy-bootstrap-stack", "info", stack_status=legacy["StackStatus"],
                   decision="not reused, not touched",
                   why="a ROLLBACK_COMPLETE stack cannot be updated and its template pins the "
                       "old namespace; this run stages templates in its own bootstrap stack")
        if blockers:
            raise DeployError("Preflight blockers: " + ", ".join(blockers))
        return {"checks": checks}

    def mfa_required(self, principal_arn):
        """True if an MFA deny applies to the IAM user, False if not, None if unknown.

        Asks the policy simulator what the principal may do with no MFA in the request, through
        the same transport as every other call. Anything but a clear answer is None, which every
        caller treats as 'required': AccessDenied, an error, a non-user ARN, no results, or a
        mix of allowed and implicitDeny that no MFA condition explains.
        """
        if principal_arn in self.mfa_answers:
            return self.mfa_answers[principal_arn]
        answer = None
        if IAM_USER_ARN.fullmatch(principal_arn or ""):
            try:
                result = self.aws("iam", "simulate-principal-policy", {
                    "PolicySourceArn": principal_arn, "ActionNames": MFA_PROBE_ACTIONS,
                    "ContextEntries": MFA_PROBE_CONTEXT})
            except AwsError:
                result = None
            decisions = [r.get("EvalDecision") for r in (result or {}).get("EvaluationResults", [])
                         if isinstance(r, dict)]
            if "explicitDeny" in decisions:
                answer = True
            elif decisions and all(d == "allowed" for d in decisions):
                answer = False
        self.mfa_answers[principal_arn] = answer
        return answer

    def _mfa_answer_for(self, info, principal_arn):
        """The simulation matters only to a long-term key; sessions keep their own rules."""
        return self.mfa_required(principal_arn) if info["kind"] == "long-term" else None

    def _credentials(self, record, principal_arn):
        """Long-term keys pass STS but fail every call CloudFormation makes for them."""
        info = self.credential_probe(self.s.profile)
        status, detail = credentials.assess(
            self.s.profile, info, self._mfa_answer_for(info, principal_arn))
        record("credentials", status, kind=info["kind"], expires_at=info["expires_at"],
               simulated=self.simulated, **({"detail": detail} if detail else {}))

    def _collisions(self, record):
        names = [self.s.env, self.s.bootstrap_stack]
        foreign = []
        for name in names:
            found = self.stack(name)
            if found and not owned(found.get("Tags", []), self.s.run_id):
                foreign.append(name)
        prefix = f"/dc2/{self.s.env}/"
        params = self.aws("ssm", "get-parameters-by-path", {"Path": prefix, "Recursive": True})
        for param in params.get("Parameters", []):
            tags = self.aws("ssm", "list-tags-for-resource", {
                "ResourceType": "Parameter", "ResourceId": param["Name"]})
            if not owned(tags.get("TagList", []), self.s.run_id):
                foreign.append(param["Name"])
        groups = self.aws("logs", "describe-log-groups", {"logGroupNamePrefix": prefix})
        for group in groups.get("logGroups", []):
            name = group["logGroupName"]
            if not self._log_group_owned(group):
                foreign.append(name)
        if self.bucket_state(self.s.artifacts_bucket) != "absent" and not self.stack(
                self.s.bootstrap_stack):
            foreign.append(self.s.artifacts_bucket)
        record("name-collisions", "blocker" if foreign else "pass", foreign=foreign)

    def bucket_state(self, name):
        """absent | exists | forbidden (a 403 means the name belongs to another account)."""
        try:
            found = self.aws("s3api", "head-bucket", {"Bucket": name},
                             tolerate=("404", "NotFound", "NoSuchBucket"))
        except AwsError as error:
            if error.code in {"403", "Forbidden"}:
                return "forbidden"
            raise
        return "absent" if found is None else "exists"

    def _log_group_owned(self, group):
        arn = group["arn"].removesuffix(":*")
        tags = self.aws("logs", "list-tags-for-resource", {"resourceArn": arn}).get("tags", {})
        return owned(tags, self.s.run_id)

    # ---- CloudFormation ---------------------------------------------------------
    def apply_stack(self, label, stack, body, parameters, *, files=None):
        """create-change-set -> describe -> (only with --execute) execute -> wait.

        Resumable: the change set is named for the template+parameter hash, a stack already
        mid-flight is only waited on, and an identical applied change set is a no-op.
        """
        digest = hashlib.sha256(
            (body + json.dumps(parameters, sort_keys=True)).encode()
        ).hexdigest()
        change_set = f"{label}-{digest[:12]}"
        current = self.stack(stack)
        if current and in_flight(current["StackStatus"]):
            self.say(f"stack {stack} is {current['StackStatus']}; waiting")
            self._wait_stack(stack)
            return self._finish_stack(stack)
        kind = "UPDATE" if current and current["StackStatus"] in HEALTHY else "CREATE"
        if current and current["StackStatus"] not in HEALTHY | {"REVIEW_IN_PROGRESS"}:
            raise DeployError(f"Stack {stack} is {current['StackStatus']}; resolve before resuming")
        applied = self.detail(self.step).get("applied")
        if kind == "UPDATE" and applied == change_set:
            return self._finish_stack(stack)
        request = {
            "StackName": stack, "ChangeSetName": change_set, "ChangeSetType": kind,
            "Parameters": parameters, "Capabilities": CAPABILITIES, "Tags": self.s.tags,
            "Description": f"dc2-v1 {label} {digest[:12]}",
        }
        request.update(files or {"TemplateBody": body})
        # With no stack there is no change set to find, and AWS answers that describe with a
        # ValidationError ("Stack ... does not exist"), not ChangeSetNotFound (2026-10-17 run).
        existing = None if current is None else self.aws(
            "cloudformation", "describe-change-set",
            {"StackName": stack, "ChangeSetName": change_set},
            tolerate=("ChangeSetNotFound", "ChangeSetNotFoundException"))
        if existing is None:
            self.aws("cloudformation", "create-change-set", request)
            # Recorded at once: even a stack that later fails belongs to this run's teardown.
            self.journal.mutate(lambda d: remember(d["resources"], "stacks", stack))
        elif existing.get("Status") == "FAILED" and no_changes(existing):
            # An earlier deploy of these exact bytes found nothing to change; so does this one.
            self.mark(self.step, "started", change_set=change_set, no_changes=True)
            return self._finish_stack(stack)
        elif existing.get("ExecutionStatus") == "EXECUTE_COMPLETE":
            # A previous attempt executed this exact change set and died before journaling it.
            self.mark(self.step, "started", applied=change_set)
            return self._finish_stack(stack)
        elif existing.get("ExecutionStatus") not in {None, "AVAILABLE"}:
            raise DeployError(f"Change set {change_set} is {existing['ExecutionStatus']}")
        description = self.poll(
            lambda: self._change_set_ready(stack, change_set), what=f"change set {change_set}",
            timeout=300, interval=5)
        if description is None:
            self.mark(self.step, "started", change_set=change_set, no_changes=True)
            return self._finish_stack(stack)
        changes = review_changes(
            description.get("Changes", []), kind, allow_replacement=self.s.allow_replacement)
        self.mark(self.step, "started", change_set=change_set, change_kind=kind,
                  template_sha256=digest, changes=summarize(changes))
        for row in changes:
            self.say("  {Action:7} {LogicalResourceId} ({ResourceType}) replace={Replacement}"
                     .format(**row))
        if not self.s.execute and not self.s.dry_run:
            raise AwaitingExecute(
                f"change set {change_set} described ({len(changes)} changes); re-run with "
                "--execute to apply it")
        if not self.established():
            self.cost_guard()
        self.aws("cloudformation", "execute-change-set", {
            "StackName": stack, "ChangeSetName": change_set,
            "ClientRequestToken": f"exec-{digest[:24]}"})
        self._wait_stack(stack)
        self.mark(self.step, "started", applied=change_set)
        return self._finish_stack(stack)

    def _change_set_ready(self, stack, change_set):
        described = self.aws("cloudformation", "describe-change-set", {
            "StackName": stack, "ChangeSetName": change_set})
        status = described["Status"]
        if status == "CREATE_COMPLETE":
            return True, described
        if status == "FAILED":
            if no_changes(described):
                return True, None
            raise DeployError(f"Change set failed: {described.get('StatusReason', '')[:200]}")
        return False, None

    def _wait_stack(self, stack):
        def check():
            current = self.stack(stack)
            status = current["StackStatus"] if current else "MISSING"
            if status in HEALTHY:
                return True, current
            if in_flight(status):
                return False, None
            self.record_partial(stack)
            raise DeployError(f"Stack {stack} ended {status}: {self._failure_reasons(stack)}")

        return self.poll(check, what=f"stack {stack}", timeout=3600)

    def record_partial(self, stack):
        """A rolled-back stack may still hold Retain resources; teardown must know their ids."""
        found = self.aws("cloudformation", "describe-stack-resources", {"StackName": stack},
                         tolerate=("ValidationError",)) or {}
        rows = [(r["ResourceType"], r["PhysicalResourceId"], r["LogicalResourceId"])
                for r in found.get("StackResources", []) if r.get("PhysicalResourceId")]
        self.record_resources(stack, rows, {})

    def _failure_reasons(self, stack):
        events = self.aws("cloudformation", "describe-stack-events", {"StackName": stack},
                          tolerate=("ValidationError",)) or {}
        reasons = [
            f"{e['LogicalResourceId']}: {e.get('ResourceStatusReason', '')[:160]}"
            for e in events.get("StackEvents", [])
            if e.get("ResourceStatus", "").endswith("FAILED")
        ]
        return "; ".join(reasons[:5]) or "no failed events listed"

    def _finish_stack(self, stack):
        current = self.stack(stack)
        outputs = {o["OutputKey"]: o["OutputValue"] for o in current.get("Outputs", [])}
        resources = self.aws("cloudformation", "describe-stack-resources", {"StackName": stack})
        return outputs, [(r["ResourceType"], r["PhysicalResourceId"], r["LogicalResourceId"])
                         for r in resources.get("StackResources", [])]

    def record_resources(self, stack, rows, outputs):
        kinds = {
            "AWS::S3::Bucket": "buckets", "AWS::ECR::Repository": "repositories",
            "AWS::RDS::DBCluster": "db_clusters", "AWS::RDS::DBInstance": "db_instances",
            "AWS::Logs::LogGroup": "log_groups",
        }

        def change(d):
            for resource_type, physical, logical in rows:
                if resource_type in kinds:
                    bucket = d["resources"].setdefault(kinds[resource_type], [])
                    if physical not in bucket:
                        bucket.append(physical)
                if resource_type == "AWS::RDS::DBCluster":
                    # The physical id carries no domain; teardown names a final snapshot per
                    # cluster and the harnesses pick a cluster by domain from this.
                    d["resources"].setdefault("db_logical", {})[physical] = logical
            stacks = d["resources"].setdefault("stacks", [])
            if stack not in stacks:
                stacks.append(stack)
            d["outputs"].update({k: v for k, v in outputs.items() if not SECRET_KEY.search(k)})

        self.journal.mutate(change)

    # ---- steps ---------------------------------------------------------------------
    def step_bootstrap_stack(self):
        adopt = self.s.adopt_bootstrap
        if adopt:
            found = self.stack(adopt)
            bucket = {o["OutputKey"]: o["OutputValue"] for o in (found or {}).get("Outputs", [])
                      }.get("ArtifactsBucket")
            if not found or found["StackStatus"] not in HEALTHY or not bucket:
                raise DeployError(
                    f"{adopt} is not adoptable: it needs a healthy status and an "
                    "ArtifactsBucket output")
            self.journal.mutate(lambda d: d["resources"].update(
                staging_bucket=bucket, bootstrap_adopted=adopt))
            return {"decision": "adopted", "stack": adopt, "bucket": bucket, "owned": False}
        template = json.loads(BOOTSTRAP_TEMPLATE.read_text())
        # The staging template pins one old namespace; this run's namespace replaces it.
        template["Parameters"]["Namespace"]["AllowedValues"] = [self.s.env]
        body = json.dumps(template, sort_keys=True, separators=(",", ":"))
        outputs, rows = self.apply_stack(
            "bootstrap", self.s.bootstrap_stack, body,
            [{"ParameterKey": "Namespace", "ParameterValue": self.s.env}])
        self.record_resources(self.s.bootstrap_stack, rows, outputs)
        self.journal.mutate(
            lambda d: d["resources"].update(staging_bucket=outputs["ArtifactsBucket"]))
        return {"decision": "created", "stack": self.s.bootstrap_stack, "owned": True,
                "bucket": outputs["ArtifactsBucket"]}

    def render(self, *, apps, images=None, cors="https://example.invalid"):
        prefix = f"arn:aws:ssm:{self.s.region}:{self.s.account}:parameter/dc2/{self.s.env}/"
        arns = {key: prefix + key for key in render_config.PARAMETERS}
        parameters = render_config.parameters({
            "schema_version": 1, "environment_id": self.s.env, "account_id": self.s.account,
            "region": self.s.region, "source_cors_origin": cors, "deploy_applications": apps,
            "parameter_arns": arns, "images": images or {},
            **({"unattended_launch": True} if self.s.unattended_launch else {}),
            **({"always_on": True, "gates_open": not self.kill_switch_on(),
                "stage_rate_limit": self.s.stage_rate_limit,
                "stage_burst_limit": self.s.stage_burst_limit,
                "monthly_budget_usd": self.s.monthly_budget_usd,
                "budget_alert_email": self.s.budget_alert_email} if self.s.persistent else {}),
        })
        body = json.dumps(render_template(self.s.database), sort_keys=True,
                          separators=(",", ":"))
        return body, parameters

    def stage_template(self, body):
        """Oversize templates go to the private staging bucket (CloudFormation's inline limit)."""
        bucket = self.meta()["resources"]["staging_bucket"]
        digest = hashlib.sha256(body.encode()).hexdigest()
        # The run id is part of the key: two runs sharing an adopted bucket stage byte-identical
        # templates, and a content-only key would make their objects indistinguishable.
        key = f"templates/{self.s.run_id}/{digest}.json"
        with tempfile.TemporaryDirectory(prefix="dc2-template-") as directory:
            Path(directory).chmod(0o700)
            path = Path(directory) / "template.json"
            path.write_text(body)
            made = self.aws("s3api", "put-object", {
                "Bucket": bucket, "Key": key, "Body": str(path),
                "ServerSideEncryption": "AES256",
                "Tagging": f"{PROJECT_KEY}={PROJECT_VALUE}&{RUN_KEY}={self.s.run_id}"}) or {}
        # Each put of a versioned bucket creates a version; teardown removes exactly these.
        staged = {"bucket": bucket, "key": key, "version_id": made.get("VersionId")}
        self.journal.mutate(lambda d: remember(d["resources"], "staged_objects", staged))
        return {"TemplateURL": f"https://{bucket}.s3.{self.s.region}.amazonaws.com/{key}"}

    def step_foundation(self):
        if self.established():
            # Rendering without applications would ask CloudFormation to remove them.
            return {"skipped": "established environment; `applications` updates the stack"}
        body, parameters = self.render(apps=False)
        outputs, rows = self.apply_stack(
            "foundation", self.s.env, body, parameters, files=self.stage_template(body))
        self.record_resources(self.s.env, rows, outputs)
        return {"stack": self.s.env, "outputs": len(outputs),
                "repositories": [outputs[k] for k in (
                    "MediaRepositoryUri", "ProcessingRepositoryUri", "WorkerRepositoryUri")]}

    def step_images(self):
        if self.established():
            return self.changed_owners()
        if not self.s.images_file:
            raise DeployError("--images is required to push the three amd64 images")
        sources = load_images(self.s.images_file)
        outputs = self.meta()["outputs"]
        # Which commit each image was built from: what later deploys diff against (AD-27).
        self.journal.mutate(lambda d: [d["images"].setdefault(o, {}).update(
            source_sha=sources[o]["source_sha"]) for o in sources if sources[o].get("source_sha")])
        registry = f"{self.s.account}.dkr.ecr.{self.s.region}.amazonaws.com"
        token = self.aws("ecr", "get-authorization-token", {})["authorizationData"][0]
        password = base64.b64decode(token["authorizationToken"]).decode().split(":", 1)[1]
        self.run_docker(["login", "--username", "AWS", "--password-stdin", registry],
                        stdin=password)
        pushed = {}
        for owner in ("media", "processing", "worker"):
            uri = outputs[f"{owner.title()}RepositoryUri"]
            repository = uri.split("/", 1)[1]
            tag = f"{self.s.run_id}-{owner}"
            source = sources[owner]
            platform, local_id = self.run_docker([
                "image", "inspect", "--format", "{{.Os}}/{{.Architecture}} {{.Id}}",
                source["source"]]).split()
            if platform != "linux/amd64":
                raise DeployError(f"{owner} image is {platform}; V1 runs linux/amd64 only")
            verified = source.get("local_id")
            if verified and verified != local_id:
                raise DeployError(f"{owner} image is not the one the build evidence verified")
            recorded = self.meta()["images"].get(owner, {}).get("local_id")
            if recorded and recorded != local_id:
                # Tags are immutable, so a resume would otherwise deploy the older push silently.
                raise DeployError(f"{owner} image changed since it was pushed; use a new --run-id")
            self.journal.mutate(lambda d, o=owner, i=local_id: d["images"].setdefault(
                o, {}).update(local_id=i))
            existing = self.aws("ecr", "describe-images", {
                "repositoryName": repository, "imageIds": [{"imageTag": tag}]},
                tolerate=("ImageNotFoundException",))
            if existing is None:  # repositories are immutable-tag: only ever pushed once
                self.run_docker(["tag", source["source"], f"{uri}:{tag}"])
                self.run_docker(["push", f"{uri}:{tag}"])
                existing = self.aws("ecr", "describe-images", {
                    "repositoryName": repository, "imageIds": [{"imageTag": tag}]})
            digest = existing["imageDetails"][0]["imageDigest"]
            expected = source.get("expected_digest")
            if expected and expected != digest:
                raise DeployError(f"{owner} registry digest differs from expected_digest")
            scan = self.aws("ecr", "describe-image-scan-findings", {
                "repositoryName": repository, "imageId": {"imageDigest": digest}},
                tolerate=("ScanNotFoundException", "ImageNotFoundException",
                          "AccessDeniedException")) or {}
            counts = scan.get("imageScanFindings", {}).get("findingSeverityCounts")
            pushed[owner] = {"uri": f"{uri}@{digest}", "digest": digest, "tag": tag,
                             "scan_severity_counts": counts or "PENDING"}
        self.journal.mutate(lambda d: [d["images"][o].update(v) for o, v in pushed.items()])
        return {"images": {k: v["digest"] for k, v in pushed.items()}}

    def changed_owners(self):
        """Owners whose images' build inputs changed since the commit each image runs from.

        Nothing is pushed: on an established environment code ships through each changed
        owner's release (aliases, migration, smoke, automatic restore), never through the
        stack, so `applications` keeps rendering the images the environment already runs.
        The image id is no signal (every image carries its commit SHA as a label); the diff of
        each image's Dockerfile inputs (scripts/ci/policy.py) is. An image whose commit is
        unknown or not in this checkout counts as changed. `migrations_changed` names owners
        whose Alembic history moved too: their release needs an explicit attestation.
        """
        if not self.s.images_file:
            return {"pushed": False, "changed_owners": "not compared (no --images)"}
        built = load_images(self.s.images_file)
        running = self.meta()["images"]
        changed, migrations = set(), []
        for name in ("media", "processing", "worker"):
            old, new = running.get(name, {}).get("source_sha"), built[name].get("source_sha")
            paths = changed_paths(old, new)
            if paths is None or name in policy.changed_images(paths):
                changed.add(name)
        owners = [owner for owner, names in (("media", {"media"}),
                                             ("processing", {"processing", "worker"}))
                  if changed & names]
        for owner in owners:
            paths = changed_paths(running.get(owner, {}).get("source_sha"),
                                  built[owner].get("source_sha"))
            if paths is None or any(p.startswith(f"{owner}/migrations/") for p in paths):
                migrations.append(owner)
        return {"pushed": False, "changed_owners": owners, "changed_images": sorted(changed),
                "migrations_changed": migrations}

    def step_applications(self):
        meta = self.meta()
        images = {o: meta["images"][o]["uri"] for o in ("media", "processing", "worker")}
        cors = meta["outputs"]["FrontendUrl"]
        body, parameters = self.render(apps=True, images=images, cors=cors)
        outputs, rows = self.apply_stack(
            "applications", self.s.env, body, parameters, files=self.stage_template(body))
        self.record_resources(self.s.env, rows, outputs)
        self.write_private(self.s.state_dir / "outputs.json", json.dumps(outputs, indent=2))
        return {"stack": self.s.env, "outputs": len(outputs), "gateway": outputs["HttpApiUrl"]}

    def step_frontend(self):
        """Build the SPA, sync it to the private frontend bucket, then invalidate CloudFront.

        Runs after `applications` so the distribution already routes /api/* to the Gateway and
        the Source bucket's CORS origin is this distribution. Reruns are no-ops for unchanged
        bytes (the bucket is versioned; an identical upload would still add a version).
        """
        outputs = self.outputs()
        bucket, distribution = outputs["FrontendBucketName"], outputs["DistributionId"]
        manifest = spa.build(spa.SOURCE, self.s.state_dir / "frontend-dist")
        existing, token = {}, None
        for _ in range(100):  # a listing is bounded: this bucket holds a few dozen objects
            request = {"Bucket": bucket, **({"ContinuationToken": token} if token else {})}
            page = self.aws("s3api", "list-objects-v2", request) or {}
            existing.update({o["Key"]: o["ETag"].strip('"') for o in page.get("Contents", [])})
            token = page.get("NextContinuationToken")
            if not token:
                break
        todo = spa.changed(manifest, existing)
        for item in todo:
            self.aws("s3api", "put-object", {
                "Bucket": bucket, "Key": item["key"], "Body": item["path"],
                "ContentType": item["content_type"], "CacheControl": item["cache_control"],
                "ServerSideEncryption": "AES256",
                "Tagging": f"{PROJECT_KEY}={PROJECT_VALUE}&{RUN_KEY}={self.s.run_id}"})
        made = self.aws("cloudfront", "create-invalidation",
                        spa.invalidation(distribution, manifest))
        invalidation = made["Invalidation"]["Id"]
        self.poll(lambda: (self.aws("cloudfront", "get-invalidation", {
            "DistributionId": distribution, "Id": invalidation,
        })["Invalidation"]["Status"] == "Completed", None),
            what=f"CloudFront invalidation {invalidation}", timeout=900)
        served = "NOT_CHECKED (dry run)"
        if not self.s.dry_run:
            served = self.verify_frontend(outputs["FrontendUrl"], manifest)
        return {"bucket": bucket, "files": len(manifest["files"]), "uploaded": len(todo),
                "manifest_sha256": manifest["sha256"], "invalidation": invalidation,
                "served_through_cloudfront": served, "api_base": "same-origin /api/media"}

    def verify_frontend(self, url, manifest):
        """Ask the distribution, not the bucket: the page it serves must name the new assets."""
        status, headers, body = self.http("GET", validate_base_url(url) + "/", {}, None, 15)
        names = [name for name in manifest["hashed"].values() if name.endswith(".js")]
        kind = (headers.get("content-type") or [""])[0]
        if status != 200 or not kind.startswith("text/html") or not all(
                n.encode() in body for n in names):
            raise DeployError("CloudFront does not serve the freshly uploaded index.html")
        return "PASS"

    def outputs(self):
        path = self.s.state_dir / "outputs.json"
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            raise DeployError("Stack outputs file missing; re-run the applications step") from None

    @staticmethod
    def write_private(path, text):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)

    # -- ECS ---------------------------------------------------------------------------
    def started_by(self, label):
        return f"dc2-deploy-{self.s.run_id}-{label}"[:128]

    def clear_task(self, label):
        """Forget a launch: its token, task and journaled verdict."""
        self.mark(self.step, "started", **{
            f"{label}_token": None, f"{label}_task": None, f"{label}_done": None,
            f"{label}_retiring": None})

    def stop_unfinished(self, label, arn):
        """Stop every unfinished task of this label and wait (bounded) until all are STOPPED.

        Covers the recorded task and any task this pipeline launched under the label's
        `startedBy` whose ARN was never journaled (the run-task reply was lost). ListTasks
        filters on the *desired* status, so a task leaves that listing the moment StopTask is
        accepted, while it is still running. Every matching ARN is therefore journaled
        (`<label>_retiring`) before it is stopped and described directly, round after round and
        across resumes, until ECS reports it STOPPED. Nothing is relaunched, and no credential
        replaced, before then: a second task next to a live one could reset the roles after
        the new DSNs are published.

        An ARN that DescribeTasks reports MISSING counts as stopped only after
        `MISSING_LOOKS` consecutive rounds, the same reconciliation `finite_task` applies: ECS
        keeps stopped tasks visible for at least an hour, so a task that stays unknown was
        stopped long ago, but a single empty answer may be launch-time lag.
        """
        cluster, marker = self.outputs()["ClusterArn"], self.started_by(label)
        key = f"{label}_retiring"
        retained = list(self.detail(self.step).get(key) or [])
        requested, missing = set(), {}

        def retain(arns):
            fresh = [a for a in arns if a not in retained]
            if fresh:  # durable before any StopTask names these ARNs
                retained.extend(fresh)
                self.mark(self.step, "started", **{key: list(retained)})

        def listed():
            arns, token = [], None
            for _ in range(10):  # a project cluster holds a handful of tasks
                page = self.aws("ecs", "list-tasks", {
                    "cluster": cluster, "desiredStatus": "RUNNING",
                    **({"nextToken": token} if token else {})},
                    tolerate=("ClusterNotFoundException",))
                if page is None:
                    return None
                arns += page.get("taskArns", [])
                token = page.get("nextToken")
                if not token:
                    return arns
            raise DeployError("Too many running tasks to reconcile")

        def check():
            running = listed()
            if running is None:
                return True, None  # the cluster is gone, and every task with it
            if arn:
                retain([arn])
            described = {}
            candidates = list(dict.fromkeys([*retained, *running]))
            for start in range(0, len(candidates), 100):
                answer = self.aws("ecs", "describe-tasks", {
                    "cluster": cluster, "tasks": candidates[start:start + 100]})
                for failure in answer.get("failures", []):
                    if failure.get("reason") != "MISSING":
                        raise DeployError(f"Cannot confirm the {label} task stopped")
                described.update({t["taskArn"]: t for t in answer.get("tasks", [])})
            retain([a for a, t in described.items() if t.get("startedBy") == marker])
            # Unknown to ECS, by a MISSING failure or an empty answer alike.
            for a in retained:
                if a in described:
                    missing.pop(a, None)
                else:
                    missing[a] = missing.get(a, 0) + 1
            for a in retained:
                task = described.get(a)
                if task and task["lastStatus"] != "STOPPED" and a not in requested:
                    self.aws("ecs", "stop-task", {
                        "cluster": cluster, "task": a,
                        "reason": f"dc2-v1 deploy: replacing the {label} task"})
                    requested.add(a)
            unresolved = [a for a in retained
                          if not (described.get(a) and described[a]["lastStatus"] == "STOPPED")
                          and missing.get(a, 0) < MISSING_LOOKS]
            return not unresolved, None

        self.poll(check, what=f"the previous {label} task to reach STOPPED", timeout=300,
                  interval=10)
        return retained

    def retire_task(self, label):
        """Make sure no earlier launch of this label can still run, then forget it.

        A journaled verdict means the task was seen STOPPED; otherwise it is stopped first.
        """
        saved = self.detail(self.step)
        if not saved.get(f"{label}_done") and (
                saved.get(f"{label}_task") or saved.get(f"{label}_token")
                or saved.get(f"{label}_retiring")):
            self.stop_unfinished(label, saved.get(f"{label}_task"))
        self.clear_task(label)

    def finite_task(self, label, definition, security_group, *, relaunched=False):
        """Run one finite task to completion. Intent (token) is journaled before launch.

        A successful verdict is journaled at once, so a resume never has to describe the task
        again (ECS forgets stopped tasks after about an hour). A task ECS no longer knows
        and that never reported a verdict is retired and relaunched once.
        """
        outputs = self.outputs()
        if self.detail(self.step).get(f"{label}_retiring"):
            self.retire_task(label)  # an earlier replacement stopped part-way: finish it first
        saved = self.detail(self.step)
        if saved.get(f"{label}_done") and saved.get(f"{label}_task"):
            return {"task": saved[f"{label}_task"], "exit_codes": saved[f"{label}_done"]}
        token = saved.get(f"{label}_token")
        if not token:
            token = uuid.uuid4().hex
            self.mark(self.step, "started", **{f"{label}_token": token})
        arn = saved.get(f"{label}_task")
        if not arn:
            result = self.aws("ecs", "run-task", {
                "cluster": outputs["ClusterArn"], "taskDefinition": definition,
                "launchType": "FARGATE", "count": 1, "clientToken": token,
                "startedBy": self.started_by(label),
                "networkConfiguration": {"awsvpcConfiguration": {
                    "subnets": outputs["PublicTaskSubnetIds"].split(","),
                    "securityGroups": [security_group], "assignPublicIp": "ENABLED"}}})
            if result.get("failures") or len(result.get("tasks", [])) != 1:
                raise DeployError(f"{label} task launch unresolved")
            arn = result["tasks"][0]["taskArn"]
            self.mark(self.step, "started", **{f"{label}_task": arn})
        misses = []

        def check():
            described = self.aws("ecs", "describe-tasks", {
                "cluster": outputs["ClusterArn"], "tasks": [arn]}).get("tasks", [])
            if not described:  # MISSING: a few looks absorb launch-time lag, then give up
                misses.append(1)
                return len(misses) >= MISSING_LOOKS, None
            misses.clear()
            return described[0]["lastStatus"] == "STOPPED", described[0]

        task = self.poll(check, what=f"{label} task", timeout=900, interval=10)
        if task is None:
            if relaunched:
                raise DeployError(f"{label} task vanished again after a relaunch")
            self.retire_task(label)
            return self.finite_task(label, definition, security_group, relaunched=True)
        codes = [c.get("exitCode") for c in task.get("containers", [])]
        if not codes or any(code != 0 for code in codes):
            # Forget the finished attempt so a rerun launches a fresh task, not this verdict.
            self.clear_task(label)
            raise DeployError(f"{label} task failed (exit codes {codes})")
        self.mark(self.step, "started", **{f"{label}_done": codes})
        return {"task": arn, "exit_codes": codes}

    def put_parameter(self, name, value):
        existing = self.aws("ssm", "describe-parameters", {
            "ParameterFilters": [{"Key": "Name", "Option": "Equals", "Values": [name]}]})
        request = {"Name": name, "Value": value, "Type": "SecureString"}
        if existing.get("Parameters"):
            tags = self.aws("ssm", "list-tags-for-resource", {
                "ResourceType": "Parameter", "ResourceId": name})
            if not owned(tags.get("TagList", []), self.s.run_id):
                raise DeployError(f"Parameter {name} exists and is not owned by this run")
            request["Overwrite"] = True  # tags cannot be sent with an overwrite
        else:
            request["Tags"] = self.s.tags
        self.aws("ssm", "put-parameter", request)

    def parameter_exists(self, name):
        found = self.aws("ssm", "describe-parameters", {
            "ParameterFilters": [{"Key": "Name", "Option": "Equals", "Values": [name]}]})
        return bool(found.get("Parameters"))

    def passwords_path(self):
        return self.s.state_dir / "db-bootstrap-passwords.json"

    def bootstrap_passwords(self):
        """The role passwords the bootstrap task applies, kept across an interrupted resume.

        The task is finite and its completion is journaled, so a resume reuses a finished task
        instead of launching another. Passwords regenerated on that resume would then never be
        applied to PostgreSQL, yet would be published to SSM. They are therefore written to a
        private (0600) file in the state directory, never logged or journaled, before any task
        can use them, and read back on every attempt. Without the file (first run, or the
        operator lost the state) fresh passwords are generated and the recorded task is
        forgotten so a new bootstrap applies exactly those.
        """
        path = self.passwords_path()
        with contextlib.suppress(OSError, ValueError):
            saved = json.loads(path.read_text())
            if set(saved) == set(db_bootstrap.CREDENTIAL_ROLES) and all(
                    isinstance(v, str) and v for v in saved.values()):
                return saved
        # Retire the old launch first: a task still running could reset the roles to its own
        # passwords after the new ones are published. Forgetting it before the file is written
        # means a crash between the two costs a fresh bootstrap, never a finished task paired
        # with passwords it did not apply.
        self.retire_task("bootstrap")
        passwords = {role: secrets.token_urlsafe(32) for role in db_bootstrap.CREDENTIAL_ROLES}
        self.write_private(path, json.dumps(passwords))
        return passwords

    def database_endpoints(self, outputs):
        """{domain: (endpoint host, master secret ARN)} from the stack outputs."""
        try:
            if self.s.database.topology == SEPARATE:
                return {domain: (outputs[f"{domain.title()}DatabaseEndpoint"],
                                 outputs[f"{domain.title()}BootstrapSecretArn"])
                        for domain in OWNERS}
            pair = (outputs["DatabaseEndpoint"], outputs["BootstrapSecretArn"])
        except KeyError as error:
            raise DeployError(
                f"The stack outputs lack {error.args[0]}: the stack was not rendered with "
                f"database topology {self.s.database.topology}") from None
        return dict.fromkeys(OWNERS, pair)

    def step_db_bootstrap(self):
        """Privileged role/database bootstrap, then the five runtime/migration parameters.

        The four role passwords come from `bootstrap_passwords`, so a resume that finds the
        bootstrap task already finished publishes exactly the passwords it applied. A failed
        task is relaunched with the same passwords (it resets the roles to them) and every DSN
        is rewritten together, so an interrupted attempt never leaves the roles and the
        parameters disagreeing. The file is removed once everything is published.
        """
        if self.established():
            # A rerun would rotate every role password under the running functions.
            return {"skipped": "established environment; role passwords and DSNs are kept"}
        outputs = self.outputs()
        base = f"/dc2/{self.s.env}/"
        endpoints = self.database_endpoints(outputs)
        masters = {}
        for secret_arn in dict.fromkeys(arn for _, arn in endpoints.values()):
            secret = self.aws("secretsmanager", "get-secret-value", {"SecretId": secret_arn})
            masters[secret_arn] = json.loads(secret["SecretString"])
        passwords = self.bootstrap_passwords()
        connections = {
            domain: {"host": host, "port": 5432, "user": masters[arn]["username"],
                     "password": masters[arn]["password"]}
            for domain, (host, arn) in endpoints.items()}
        if self.s.database.topology == SEPARATE:
            payload = {"databases": connections, "role_passwords": passwords}
        else:  # V1's input, unchanged: one connection serves both domains
            payload = {**connections["media"], "role_passwords": passwords}
        db_bootstrap.validate_input(payload)
        self.put_parameter(base + "bootstrap-input", json.dumps(payload))
        result = {}
        try:
            result = self.finite_task(
                "bootstrap", outputs["BootstrapTaskDefinitionArn"],
                outputs["MigrationSecurityGroupId"])
        finally:
            self.aws("ssm", "delete-parameter", {"Name": base + "bootstrap-input"},
                     tolerate=("ParameterNotFound",))
        for key, (role, database) in {
            "media_runtime_dsn": ("media_runtime", "media_db"),
            "media_migration_dsn": ("media_migrator", "media_db"),
            "processing_runtime_dsn": ("processing_runtime", "processing_db"),
            "processing_migration_dsn": ("processing_migrator", "processing_db"),
        }.items():
            # Each DSN names its own domain's cluster, so the migration tasks and the
            # runtime handlers that read these parameters need no topology knowledge.
            host = endpoints[database.removesuffix("_db")][0]
            dsn = f"postgresql://{quote(role, safe='')}:{quote(passwords[role], safe='')}" \
                  f"@{host}:5432/{database}"
            self.put_parameter(base + key, dsn)
        # The signing key is stable across reruns: rotating it would end every session.
        if not self.parameter_exists(base + "jwt_secret"):
            self.put_parameter(base + "jwt_secret", secrets.token_urlsafe(48))
        # Only now, with every DSN in SSM, are the local copies unnecessary.
        self.passwords_path().unlink(missing_ok=True)
        return {"bootstrap_task": result.get("task"),
                "parameters": sorted(render_config.PARAMETERS),
                "temporary_input_removed": True}

    def target_revision(self, owner, override):
        if override:
            return override
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(ROOT / owner / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / owner / "migrations"))
        heads = ScriptDirectory.from_config(cfg).get_heads()
        if len(heads) != 1:
            raise DeployError(f"{owner} migrations must have exactly one head")
        return heads[0]

    def step_migrations(self, revisions=None):
        """Per-owner migration tasks through the shared `migrate`, one owner at a time."""
        if self.established():
            return {"skipped": "established environment; a changed owner migrates in its release"}
        revisions = revisions or {}
        outputs = self.outputs()
        _, config, _, _ = operations.load_operator_config(self.write_ops_config())
        targets = {o: self.target_revision(o, revisions.get(o)) for o in OWNERS}
        reader, mode = self.schema_reader(targets)
        done = list(self.detail(self.step).get("owners_done", []))
        for owner in OWNERS:
            if owner in done:
                continue
            definition = outputs[f"{owner.title()}MigrationTaskDefinitionArn"]
            self.plan.append({
                "step": self.step, "mutating": True,
                "command": f"# scripts.aws.v1.migration.migrate owner={owner} "
                           f"revision={targets[owner]} (ecs run-task, describe-tasks)"})
            # migrate() journals through the shared state object, so the lock is held for its
            # duration; this pipeline's own audit events are written once it is released.
            self.journal_held = True
            try:
                with self.journal.locked() as state:
                    if not state.get("pending_release"):
                        state["pending_release"] = {}
                        self.journal.save(state)
                    try:
                        migrate(
                            config, self, self.journal, state, owner=owner, definition=definition,
                            revision=targets[owner], schema_revision=reader,
                            deadline=self.clock() + 1800, clock=self.clock, sleep=self.sleep)
                    except OperationError as error:
                        # A task that ran and failed is a verdict, not an ambiguous launch:
                        # forget it so a corrected rerun launches a fresh one. Anything else
                        # (an unresolved launch) keeps its retained intent.
                        if str(error) in DEFINITIVE_MIGRATION_FAILURES:
                            state["pending_release"] = None
                            self.journal.save(state)
                        raise
                    state["pending_release"] = None
                    self.journal.save(state)
            finally:
                self.journal_held = False
                self.flush_events()
            done.append(owner)
            self.mark(self.step, "started", owners_done=done,
                      **{f"{owner}_revision": targets[owner]})
        return {"owners_done": done, "schema_check": mode}

    def schema_reader(self, targets):
        """(hook, evidence label). SQL when this station can reach the private database."""
        from scripts.aws.v1.hooks import schema_reader

        sql = self.sql_settings()
        if sql.get("ca_file"):
            files = {k[: -len("_dsn_file")]: v for k, v in sql.items() if k.endswith("_dsn_file")}
            return schema_reader(files, sql["ca_file"]), "alembic_version-over-verified-tls"
        # The database is private: without a station inside the VPC the migration task's own
        # `alembic upgrade head` exit status is the only evidence. It is labelled as such.
        return (lambda owner, deadline=None: targets[owner]), "task-exit-code-only"

    def sql_settings(self):
        if not self.s.sql_config:
            return {}
        data = json.loads(Path(self.s.sql_config).read_text())
        if data.keys() - {"ca_file", "media_dsn_file", "processing_dsn_file"}:
            raise DeployError("--sql-config has unsupported fields")
        return data

    # -- operator config for the session/release CLIs --------------------------------------
    def write_ops_config(self, *, teardown=False):
        """The session CLI's config. A teardown gets its own file and attested zero counts.

        Teardown deletes the data, so a drain proof gates nothing; and a real drain wait
        would spend the close's whole deadline before the mappings and rules were disabled.
        """
        path = self.s.state_dir / (
            "operator-config-teardown.json" if teardown else "operator-config.json")
        data = {"operator_station": self.s.station, "environment_id": self.s.env,
                "journal": "session/journal.json", "outputs_file": "outputs.json"}
        if self.s.persistent:
            # `session open` (the kill switch off) and `status` must agree with the template.
            data["edge_open"] = {"rate": self.s.stage_rate_limit,
                                 "burst": self.s.stage_burst_limit}
        sql = {} if teardown else self.sql_settings()
        counts = None if teardown else self.s.counts_file
        if sql:
            data["sql"] = sql
        elif counts:
            data["counts_file"] = self.state_relative(counts)
        elif self.s.assume_empty_counts or teardown:
            zero = self.s.state_dir / "attested-zero-counts.json"
            self.write_private(zero, json.dumps(dict.fromkeys(
                ("queued", "processing", "succeeded", "failed", "abandoned", "cancelled"), 0)))
            data["counts_file"] = self.state_relative(zero)
        self.write_private(path, json.dumps(data, indent=2))
        return path

    def state_relative(self, path):
        """Relative to the state directory when inside it: the state is read on other machines."""
        path = Path(path)
        return str(path.relative_to(self.s.state_dir)) if path.is_relative_to(
            self.s.state_dir) else str(path)

    def run_session(self, action, *extra, teardown=False):
        ops = self.write_ops_config(teardown=teardown)
        argv = [action, "--config", str(ops), "--profile", self.s.profile,
                "--region", self.s.region, "--account", self.s.account, *extra]
        if self.s.dry_run:
            argv.append("--dry-run")
        buffer = io.StringIO()
        (self.session_dir()).mkdir(parents=True, exist_ok=True, mode=0o700)
        code = self.session_main(argv, environ={}, stdout=buffer)
        try:
            payload = json.loads(buffer.getvalue())
        except ValueError:
            raise DeployError(f"session {action} returned unparseable output") from None
        for call in payload.get("planned_calls", []):
            self.plan.append({"step": self.step, "mutating": call.get("operation", "").startswith(
                ("update", "put", "enable", "disable", "run", "stop", "delete")),
                "command": "# sdk " + json.dumps(call, sort_keys=True)})
        if code or not payload.get("ok"):
            raise DeployError(f"session {action} failed: {str(payload.get('error', ''))[:700]}")
        return payload.get("result", {})

    def session_dir(self):
        return self.s.state_dir / "session"

    def step_session_init(self):
        journal = self.session_dir() / "journal.json"
        # An established environment's journal is never re-initialised: init attests "empty".
        if self.established() or (journal.exists() and not self.s.dry_run):
            return {"session_journal": "exists"}
        if not (self.s.sql_config or self.s.counts_file or self.s.assume_empty_counts):
            raise DeployError(
                "Close needs attempt counts: pass --sql-config, --counts-file or "
                "--assume-empty-counts (a first deploy has launched no worker). Refusing to "
                "open a window that could not be closed")
        self.run_session("init", "--confirm-empty", "--confirm-exclusive")
        return {"session_journal": "initialized"}

    def session_recorded(self):
        """What the session journal says (open, closed, ...); None before it exists."""
        path = self.session_dir() / "journal.json"
        if self.s.dry_run or not path.exists():
            return None
        journal = Journal(path, station=self.s.station, environment=self.s.env)
        with journal.locked() as state:
            return state.get("session")

    def kill_switch_on(self):
        return self.s.persistent and bool(self.meta().get("session_opened")) and (
            self.session_recorded() not in (None, "open"))

    def step_session_open(self):
        """Open the persistent environment once; afterwards an operator's close is respected.

        The template already deploys it open, so this records the open session (which `status`
        compares against) and switches the launcher's SQL flag on, after the same readiness and
        repair checks a booked open makes. A later `session close` is the emergency kill
        switch, and a routine deploy must not quietly undo it.
        """
        if self.meta().get("session_opened"):
            recorded = self.session_recorded()
            return {"session": recorded or "unknown", "opened": "earlier",
                    "kill_switch": "on" if self.kill_switch_on() else "off"}
        result = self.run_session("open", "--unattended", "--minutes",
                                  str(ALWAYS_ON_OPEN_MINUTES))
        if not self.s.dry_run:
            self.journal.mutate(lambda d: d.update(session_opened=True))
        return {"session": result.get("session", "open"), "launcher": "enabled"}

    def step_session_window(self):
        result = self.run_session("window")
        return {"session": "window", "result_keys": sorted(result)}

    def credentials_path(self):
        return self.s.state_dir / "smoke-credentials.json"

    def step_seed(self):
        """Register the smoke account through the public endpoint (always role 'user')."""
        if self.established():
            # Registered by the first deploy; with the kill switch on the API would answer 429.
            return {"registered": "earlier"}
        if not self.s.seed_email:
            raise DeployError("--seed-email is required to register the smoke account")
        base = validate_base_url(self.outputs()["HttpApiUrl"])
        path = self.credentials_path()
        if path.exists():
            creds = json.loads(path.read_text())
        else:
            creds = {"email": self.s.seed_email, "password": secrets.token_urlsafe(24)}
            self.write_private(path, json.dumps(creds))
        if self.s.dry_run:
            self.plan.append({"step": self.step, "mutating": True, "command":
                              f"# POST {base}/api/media/auth/register (smoke account)"})
            return {"registered": "planned", "role": "user"}
        status, _, _ = self.http(
            "POST", f"{base}/api/media/auth/register",
            {"accept": "application/json", "content-type": "application/json"},
            json.dumps(creds).encode(), 15)
        if status not in {201, 409}:
            raise DeployError(f"register returned HTTP {status}")
        # 409 means the address exists; with our own saved password the login check decides.
        return {"registered": "created" if status == 201 else "already-exists", "role": "user",
                "email_sha256": hashlib.sha256(creds["email"].encode()).hexdigest()[:12]}

    def step_public_smoke(self):
        if self.kill_switch_on():
            return {"checks": "skipped: the kill switch is on (`session open --unattended`)"}
        base = self.outputs()["HttpApiUrl"]
        if self.s.dry_run:
            checks = ["media-health", "processing-health", "anonymous-denied", "login",
                      "media-jobs", "processing-jobs", "upload-reserve"]
            self.plan.append({"step": self.step, "mutating": False, "command":
                              f"# PublicSmoke {base}: {', '.join(checks)}"})
            return {"checks": dict.fromkeys(checks, "PLANNED")}
        creds = json.loads(self.credentials_path().read_text())
        smoke = PublicSmoke(base, creds, http=self.http, clock=self.clock)
        ok = smoke("media", {}, None, deadline=self.clock() + 120)
        if not ok:
            raise DeployError("PublicSmoke failed: " + ", ".join(smoke.receipt["failures"]))
        return {"checks": smoke.receipt["checks"]}

    def step_session_close(self):
        result = self.run_session("close")
        return {"session": result.get("session", "closed"),
                "database_pause": result.get("database_pause", "NOT_OBSERVED")}

    # ---- orchestration -------------------------------------------------------------------
    def deploy(self, *, stop_after=None, revisions=None):
        if self.s.persistent:
            return self.deploy_persistent(stop_after=stop_after, revisions=revisions)
        actions = {
            "preflight": self.preflight, "bootstrap-stack": self.step_bootstrap_stack,
            "foundation": self.step_foundation, "images": self.step_images,
            "applications": self.step_applications, "frontend": self.step_frontend,
            "db-bootstrap": self.step_db_bootstrap,
            "migrations": lambda: self.step_migrations(revisions),
            "session-init": self.step_session_init, "session-window": self.step_session_window,
            "seed": self.step_seed, "public-smoke": self.step_public_smoke,
            "session-close": self.step_session_close,
        }
        results = {}
        opened = False
        try:
            for name in DEPLOY_STEPS:
                opened = opened or name == "session-window"  # even a partial open must close
                results[name] = self.run_step(name, actions[name], always=name == "preflight")
                if name == stop_after:
                    break
        except Exception:
            if opened and self.meta()["steps"].get("session-close", {}).get("status") != "done":
                self.say("closing the session window after a failure")
                try:
                    self.run_step("session-close", actions["session-close"])
                except Exception:
                    pass  # window stays journaled as open; the next run closes it first
                else:
                    # Closed again: a rerun must reopen the window before it can seed or smoke.
                    self.journal.mutate(lambda d: [d["steps"].pop(n, None) for n in (
                        "session-window", "session-close")])
            raise
        return results

    def deploy_persistent(self, *, stop_after=None, revisions=None):
        """Create the environment, or update it in place once it is established (#235)."""
        self.begin_invocation()
        actions = {
            "preflight": self.preflight, "bootstrap-stack": self.step_bootstrap_stack,
            "foundation": self.step_foundation, "images": self.step_images,
            "applications": self.step_applications, "frontend": self.step_frontend,
            "db-bootstrap": self.step_db_bootstrap,
            "migrations": lambda: self.step_migrations(revisions),
            "session-init": self.step_session_init, "session-open": self.step_session_open,
            "seed": self.step_seed, "public-smoke": self.step_public_smoke,
        }
        results = {}
        for name in PERSISTENT_STEPS:
            results[name] = self.run_step(name, actions[name], always=name == "preflight")
            if name == stop_after:
                return results
        if not self.s.dry_run:
            self.journal.mutate(lambda d: d.update(established=True))
        return results

    # ---- teardown ---------------------------------------------------------------------
    def tags_of(self, kind, name):
        """(present, tags). Absent resources are not an error: teardown is idempotent."""
        region, account = self.s.region, self.s.account
        if kind == "stack":
            found = self.stack(name)
            return (True, found.get("Tags", [])) if found else (False, [])
        if kind == "bucket":
            result = self.aws("s3api", "get-bucket-tagging", {"Bucket": name},
                              tolerate=("NoSuchBucket", "NoSuchTagSet"))
            if result is not None:
                return True, result.get("TagSet", [])
            gone = self.aws("s3api", "head-bucket", {"Bucket": name}, tolerate=("404", "NotFound"))
            return (gone is not None), []
        if kind == "repository":
            result = self.aws("ecr", "list-tags-for-resource", {
                "resourceArn": f"arn:aws:ecr:{region}:{account}:repository/{name}"},
                tolerate=("RepositoryNotFoundException",))
            return (result is not None), (result or {}).get("tags", [])
        if kind in {"db_cluster", "db_instance"}:
            suffix = "cluster" if kind == "db_cluster" else "db"
            result = self.aws("rds", "list-tags-for-resource", {
                "ResourceName": f"arn:aws:rds:{region}:{account}:{suffix}:{name}"},
                tolerate=("DBClusterNotFoundFault", *INSTANCE_NOT_FOUND))
            return (result is not None), (result or {}).get("TagList", [])
        if kind == "log_group":
            result = self.aws("logs", "list-tags-for-resource", {
                "resourceArn": f"arn:aws:logs:{region}:{account}:log-group:{name}"},
                tolerate=("ResourceNotFoundException",))
            return (result is not None), (result or {}).get("tags", {})
        raise DeployError(f"Unknown resource kind {kind}")

    def td_inventory(self):
        resources = self.meta()["resources"]
        plural = {"stack": "stacks", "bucket": "buckets", "repository": "repositories",
                  "db_cluster": "db_clusters", "db_instance": "db_instances",
                  "log_group": "log_groups"}
        mine, skipped, absent = {kind: [] for kind in plural}, [], []
        for kind, key in plural.items():
            for name in resources.get(key, []):
                present, tags = self.tags_of(kind, name)
                if not present:
                    absent.append({"kind": kind, "id": name})
                elif owned(tags, self.s.run_id):
                    mine[kind].append(name)
                else:
                    skipped.append({"kind": kind, "id": name,
                                    "why": "recorded by this run but tags no longer match"})
        if resources.get("bootstrap_adopted"):
            skipped.append({"kind": "stack", "id": resources["bootstrap_adopted"],
                            "why": "adopted pre-existing stack; never owned by this run"})
        self.journal.mutate(lambda d: d.update(ownership={"owned": mine, "skipped": skipped}))
        return {"owned": {k: len(v) for k, v in mine.items()}, "skipped": len(skipped),
                "already_absent": len(absent)}

    def owned_ids(self, kind):
        return self.meta().get("ownership", {}).get("owned", {}).get(kind, [])

    def session_failures(self):
        """Close steps the session journal recorded as failed by the last close attempt."""
        journal = Journal(self.session_dir() / "journal.json", station=self.s.station,
                          environment=self.s.env)
        with journal.locked() as state:
            return list(state.get("session_failures", []))

    def td_session_close(self):
        """Shut every writer's front door first: intake, queue consumers and schedules.

        Anything left open could accept an upload or start a worker after the buckets were
        emptied. This is the session close the deploy ends with (stage throttle 0/0, mappings
        and rules disabled), run again because a session may have been opened since. Its drain
        and inventory checks cannot pass while an encoder runs, and the next step stops those,
        so a close that failed only on them is accepted; any other failure stops the teardown.
        """
        meta = self.meta()
        if not meta["outputs"].get("HttpApiUrl") or self.s.env not in self.owned_ids("stack"):
            return {"session": "nothing-deployed"}
        initialised = meta["steps"].get("session-init", {}).get("status") == "done"
        if not initialised and not self.s.dry_run:
            return {"session": "never-initialised"}
        outputs = self.s.state_dir / "outputs.json"
        if not outputs.exists():  # the config reads it; the journal kept every non-secret output
            self.write_private(outputs, json.dumps(meta["outputs"], indent=2))
        try:
            self.run_session("close", teardown=True)
        except DeployError:
            try:
                deferred = self.session_failures()
            except OperationError:  # no readable session journal: nothing proves a safe close
                deferred = []
            if not deferred or not set(deferred) <= DRAIN_CHECKS:
                raise
            return {"session": "closed", "deferred_to_task_stop": sorted(deferred)}
        return {"session": "closed", "deferred_to_task_stop": []}

    def td_quiesce(self):
        """Stop every task in the project cluster, then wait (bounded) until all are STOPPED.

        Re-listing each round catches a task that started between the list and the stop; the
        step finishes only on a round that found nothing new and left nothing running.
        """
        cluster = self.meta()["outputs"].get("ClusterArn")
        if not (cluster and self.owned_ids("stack")):
            return {"tasks_stopped": 0, "all_stopped": True}
        stopped = []

        def check():
            listed = self.aws("ecs", "list-tasks", {"cluster": cluster, "desiredStatus": "RUNNING"},
                              tolerate=("ClusterNotFoundException",))
            if listed is None:
                return True, None  # the cluster is already gone
            new = [t for t in listed.get("taskArns", []) if t not in stopped]
            for task in new:
                self.aws("ecs", "stop-task", {
                    "cluster": cluster, "task": task, "reason": "dc2-v1 teardown"})
                stopped.append(task)
            running = []
            for start in range(0, len(stopped), 100):
                described = self.aws("ecs", "describe-tasks", {
                    "cluster": cluster, "tasks": stopped[start:start + 100]})
                running += [t for t in described.get("tasks", []) if t["lastStatus"] != "STOPPED"]
            return not new and not running, None

        self.poll(check, what="encoder tasks to reach STOPPED", timeout=900, interval=10)
        return {"tasks_stopped": len(stopped), "all_stopped": True}

    def empty_bucket(self, bucket):
        """Delete every version and delete marker (the buckets are versioned) and abort uploads."""
        removed = 0
        for _ in range(1000):
            listing = self.aws("s3api", "list-object-versions", {"Bucket": bucket},
                               tolerate=("NoSuchBucket",))
            if listing is None:
                return removed
            objects = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                       for v in listing.get("Versions", []) + listing.get("DeleteMarkers", [])]
            if not objects:
                break
            for start in range(0, len(objects), 1000):
                self.aws("s3api", "delete-objects", {
                    "Bucket": bucket,
                    "Delete": {"Objects": objects[start:start + 1000], "Quiet": True}})
            removed += len(objects)
        else:
            raise DeployError(f"Bucket {bucket} did not empty within the bounded passes")
        uploads = self.aws("s3api", "list-multipart-uploads", {"Bucket": bucket},
                           tolerate=("NoSuchBucket",)) or {}
        for upload in uploads.get("Uploads", []):
            self.aws("s3api", "abort-multipart-upload", {
                "Bucket": bucket, "Key": upload["Key"], "UploadId": upload["UploadId"]})
        return removed

    def td_buckets(self):
        counts = {bucket: self.empty_bucket(bucket) for bucket in self.owned_ids("bucket")}
        return {"versions_deleted": sum(counts.values()), "buckets": len(counts)}

    def td_images(self):
        deleted = 0
        for repository in self.owned_ids("repository"):
            listed = self.aws("ecr", "list-images", {"repositoryName": repository},
                              tolerate=("RepositoryNotFoundException",)) or {}
            ids = listed.get("imageIds", [])
            for start in range(0, len(ids), 100):
                self.aws("ecr", "batch-delete-image", {
                    "repositoryName": repository, "imageIds": ids[start:start + 100]})
            deleted += len(ids)
        return {"images_deleted": deleted}

    def snapshot_name(self, cluster):
        """The final snapshot's id. V1's single cluster keeps `<env>-final`; each cluster of a
        separate layout needs its own, since a snapshot identifier is unique in the account."""
        logical = self.meta()["resources"].get("db_logical", {}).get(cluster, "")
        domain = {"MediaDatabaseCluster": "media", "ProcessingDatabaseCluster": "processing"}
        return (f"{self.s.env}-{domain[logical]}-final" if logical in domain
                else f"{self.s.env}-final")

    def td_database(self):
        """Instances first, then the clusters with deletion protection lifted.

        The cluster and instance are Retain resources and live in the VPC the stack deletes, so
        they must be gone before the stack is. A final snapshot is the default; skipping it is
        an explicit, journaled decision. With two clusters (#94) every deletion is requested
        before any is waited on, so the second does not queue behind the first.
        """
        instances = self.owned_ids("db_instance")
        for instance in instances:
            self.aws("rds", "delete-db-instance", {"DBInstanceIdentifier": instance},
                     tolerate=INSTANCE_NOT_FOUND)
        for instance in instances:
            self.poll(lambda i=instance: self._gone(
                "rds", "describe-db-instances", {"DBInstanceIdentifier": i},
                *INSTANCE_NOT_FOUND), what=f"instance {instance} deletion", timeout=1800)
        deleting = []
        for cluster in self.owned_ids("db_cluster"):
            found = self.aws("rds", "describe-db-clusters", {"DBClusterIdentifier": cluster},
                             tolerate=CLUSTER_NOT_FOUND)
            if found is None:
                continue
            if found["DBClusters"][0].get("Status") != "deleting":
                self.aws("rds", "modify-db-cluster", {
                    "DBClusterIdentifier": cluster, "DeletionProtection": False,
                    "ApplyImmediately": True})
                request = {"DBClusterIdentifier": cluster,
                           "SkipFinalSnapshot": self.s.skip_final_snapshot}
                if not self.s.skip_final_snapshot:
                    request["FinalDBSnapshotIdentifier"] = self.snapshot_name(cluster)
                self.aws("rds", "delete-db-cluster", request)
                if not self.s.skip_final_snapshot:
                    # At once, so a failure while the other cluster is handled loses no name.
                    name = request["FinalDBSnapshotIdentifier"]
                    self.journal.mutate(lambda d, n=name: remember_snapshot(d, n))
            deleting.append(cluster)
        for cluster in deleting:
            self.poll(lambda c=cluster: self._gone(
                "rds", "describe-db-clusters", {"DBClusterIdentifier": c},
                *CLUSTER_NOT_FOUND), what=f"cluster {cluster} deletion", timeout=3600)
        # Every snapshot any attempt requested, so a resume tags the earlier attempt's too.
        snapshots = self.meta().get("final_snapshots") or []
        for snapshot in snapshots:
            self.tag_snapshot(snapshot)
        return {"final_snapshot": snapshots[0] if snapshots else None,
                "final_snapshots": snapshots, "skip_final_snapshot": self.s.skip_final_snapshot}

    def tag_snapshot(self, snapshot):
        def available():
            found = self.aws("rds", "describe-db-cluster-snapshots", {
                "DBClusterSnapshotIdentifier": snapshot}, tolerate=SNAPSHOT_NOT_FOUND)
            if found is None:  # the operator already deleted it; a resume has nothing to tag
                return True, "gone"
            return found["DBClusterSnapshots"][0]["Status"] == "available", None

        if self.poll(available, what="final snapshot", timeout=1800) == "gone":
            return
        arn = f"arn:aws:rds:{self.s.region}:{self.s.account}:cluster-snapshot:{snapshot}"
        self.aws("rds", "add-tags-to-resource", {"ResourceName": arn, "Tags": self.s.tags})

    def _gone(self, service, operation, payload, *codes):
        return self.aws(service, operation, payload, tolerate=codes) is None, None

    def td_parameters(self):
        base = f"/dc2/{self.s.env}/"
        found = self.aws("ssm", "get-parameters-by-path", {"Path": base, "Recursive": True})
        deleted, kept = [], []
        for param in found.get("Parameters", []):
            tags = self.aws("ssm", "list-tags-for-resource", {
                "ResourceType": "Parameter", "ResourceId": param["Name"]})
            if owned(tags.get("TagList", []), self.s.run_id):
                self.aws("ssm", "delete-parameter", {"Name": param["Name"]},
                         tolerate=("ParameterNotFound",))
                deleted.append(param["Name"])
            else:
                kept.append(param["Name"])
        # An interrupted db-bootstrap leaves its local password copy; the roles are going too.
        self.passwords_path().unlink(missing_ok=True)
        return {"parameters_deleted": len(deleted), "parameters_kept": kept}

    def delete_stack(self, stack):
        current = self.stack(stack)
        if current is None:
            return
        if current["StackStatus"] != "DELETE_IN_PROGRESS":
            self.aws("cloudformation", "delete-stack", {"StackName": stack})

        def check():
            latest = self.stack(stack)
            if latest is None or latest["StackStatus"] == "DELETE_COMPLETE":
                return True, None
            if latest["StackStatus"] == "DELETE_FAILED":
                raise DeployError(f"Stack {stack} DELETE_FAILED: {self._failure_reasons(stack)}")
            return False, None

        self.poll(check, what=f"stack {stack} deletion", timeout=3600)

    def td_stack(self):
        if self.s.env in self.owned_ids("stack"):
            self.delete_stack(self.s.env)
        return {"stack": self.s.env}

    def td_bootstrap_stack(self):
        if self.s.bootstrap_stack in self.owned_ids("stack"):
            self.delete_stack(self.s.bootstrap_stack)
        removed, kept = 0, []
        # An adopted staging bucket is kept; only the object versions this run uploaded (each
        # VersionId was journaled by its put) are removed, never a sibling run's identical
        # template. Without an owned bucket to empty, nothing else would remove them.
        if self.meta()["resources"].get("bootstrap_adopted"):
            by_bucket = {}
            for staged in self.meta()["resources"].get("staged_objects", []):
                if staged.get("version_id"):
                    by_bucket.setdefault(staged["bucket"], []).append(
                        {"Key": staged["key"], "VersionId": staged["version_id"]})
                else:
                    kept.append(staged["key"])
            for bucket, objects in by_bucket.items():
                removed += self.delete_object_versions(bucket, objects)
        return {"stack": self.s.bootstrap_stack, "staged_versions_removed": removed,
                "staged_without_version_id_kept": sorted(set(kept))}

    def delete_object_versions(self, bucket, objects):
        """Delete exactly the named (key, version) pairs; S3 treats an absent version as done."""
        for start in range(0, len(objects), 1000):
            result = self.aws("s3api", "delete-objects", {
                "Bucket": bucket, "Delete": {"Objects": objects[start:start + 1000],
                                             "Quiet": True}}, tolerate=("NoSuchBucket",))
            if result and result.get("Errors"):
                raise DeployError(f"Could not delete {len(result['Errors'])} staged versions")
        return len(objects)

    def delete_bucket(self, bucket):
        """Empty the bucket again right before deleting it, and retry if a write slipped in.

        The first sweep (`td-buckets-emptied`) ran long before this, and an upload grant issued
        before the session closed stays valid for 15 minutes, as does any request an active
        Lambda was serving. Re-sweeping here, on every attempt and every resume, closes that
        window without making every teardown wait out the grant lifetime. A bucket that is
        still being written to after the bounded attempts fails the step instead.
        """
        for attempt in range(1, BUCKET_DELETE_ATTEMPTS + 1):
            self.empty_bucket(bucket)
            try:
                self.aws("s3api", "delete-bucket", {"Bucket": bucket}, tolerate=("NoSuchBucket",))
                return attempt
            except AwsError as error:
                if error.code != "BucketNotEmpty":
                    raise
            self.sleep(BUCKET_RETRY_SECONDS)
        raise DeployError(
            f"Bucket {bucket} kept receiving writes through {BUCKET_DELETE_ATTEMPTS} sweeps")

    def td_retained(self):
        """Retain-policy resources the stacks deliberately left behind, deleted by ownership."""
        deleted = {"buckets": [], "repositories": [], "log_groups": []}
        for bucket in self.owned_ids("bucket"):
            self.delete_bucket(bucket)
            deleted["buckets"].append(bucket)
        for repository in self.owned_ids("repository"):
            self.aws("ecr", "delete-repository", {"repositoryName": repository, "force": True},
                     tolerate=("RepositoryNotFoundException",))
            deleted["repositories"].append(repository)
        groups = self.aws("logs", "describe-log-groups",
                          {"logGroupNamePrefix": f"/dc2/{self.s.env}/"})
        for group in groups.get("logGroups", []):
            if self._log_group_owned(group):
                self.aws("logs", "delete-log-group", {"logGroupName": group["logGroupName"]},
                         tolerate=("ResourceNotFoundException",))
                deleted["log_groups"].append(group["logGroupName"])
        return {k: len(v) for k, v in deleted.items()}

    def td_receipt(self):
        """Observe what is left from the services, not from the deletion calls' success."""
        meta = self.meta()
        found = []

        def left(kind, name, why):
            found.append({"kind": kind, "id": name, "why": why})

        resources = meta["resources"]
        for stack in resources.get("stacks", []):
            current = self.stack(stack)
            if current:
                left("cloudformation-stack", stack, current["StackStatus"])
        for kind, key, label in (
            ("bucket", "buckets", "s3-bucket"), ("repository", "repositories", "ecr-repository"),
            ("db_cluster", "db_clusters", "aurora-cluster"),
            ("db_instance", "db_instances", "aurora-instance"),
        ):
            for name in resources.get(key, []):
                if self.tags_of(kind, name)[0]:
                    left(label, name, "still exists")
        params = self.aws("ssm", "get-parameters-by-path", {
            "Path": f"/dc2/{self.s.env}/", "Recursive": True})
        for param in params.get("Parameters", []):
            left("ssm-parameter", param["Name"], "still exists")
        groups = self.aws("logs", "describe-log-groups", {
            "logGroupNamePrefix": f"/dc2/{self.s.env}/"})
        for group in groups.get("logGroups", []):
            left("log-group", group["logGroupName"], "still exists")
        # One final snapshot per cluster; journals written before the separate topology hold one.
        snapshots = meta.get("final_snapshots") or (
            [meta["final_snapshot"]] if meta.get("final_snapshot") else [])
        for snapshot in snapshots:
            left("aurora-snapshot", snapshot,
                 "final snapshot kept by default; delete it once the data is not needed")
        tagged = self.aws("resourcegroupstaggingapi", "get-resources", {
            "TagFilters": [{"Key": RUN_KEY, "Values": [self.s.run_id]}]})
        known = {item["id"] for item in found}
        # The tagging API is eventually consistent, so a hit is a question for the owning
        # service and not a verdict: only what that service still reports is "remaining".
        observed = []
        for mapping in tagged.get("ResourceTagMappingList", []):
            arn = mapping["ResourceARN"]
            if any(name in arn for name in known):
                continue
            row = self.confirm_tagged(arn)
            observed.append(row)
            if not row["gone"]:
                left("tagged-resource", arn,
                     f"listed by the tagging API and not confirmed gone: {row['observed']}")
                found[-1].update(resource_type=row["resource_type"], observed=row["observed"])
        self.delete_inactive_task_definitions(observed)
        legacy = self.stack(LEGACY_BOOTSTRAP_STACK)
        untouched = [{"kind": "cloudformation-stack", "id": LEGACY_BOOTSTRAP_STACK,
                      "status": legacy["StackStatus"]}] if legacy else []
        receipt = {
            "issue": "#67", "run_id": self.s.run_id, "environment": self.s.env,
            "account": self.s.account, "region": self.s.region, "generated_at": now(),
            "simulated": self.simulated,
            "status": "CLEAN" if not found else "ITEMS_REMAIN",
            "resources_remaining": found,
            # Every tagging-API hit with the state its owning service reported, the ones
            # confirmed gone included: the evidence that a lagging listing was not ignored.
            "tagging_api_observed": observed,
            "skipped_not_owned": meta.get("ownership", {}).get("skipped", []),
            "pre_existing_untouched": untouched,
            # `final_snapshot` keeps its single-cluster meaning (the first snapshot).
            "final_snapshot": (snapshots[0] if snapshots else (
                "skipped by operator" if self.s.skip_final_snapshot else None)),
            "final_snapshots": snapshots,
            "billing_note": "Deleting stops new charges only; reconcile actual usage against "
                            "Cost Explorer before closing #67.",
            "journal_steps": {k: v["status"] for k, v in meta["steps"].items()},
        }
        self.write_private(self.s.state_dir / f"teardown-receipt-{self.s.run_id}.json",
                           json.dumps(receipt, indent=2))
        self.receipt = receipt
        return {"status": receipt["status"], "remaining": len(found)}

    @staticmethod
    def arn_parts(arn):
        """(service, resource type, resource id). A bucket ARN has no type; its id is the name."""
        parts = arn.split(":", 5)
        if len(parts) < 6:
            return "", "", arn
        found = _ARN_RESOURCE.fullmatch(parts[5])
        if parts[2] == "s3" and "/" not in parts[5]:
            return "s3", "bucket", parts[5]
        return (parts[2], found[1], found[2]) if found else (parts[2], "", parts[5])

    def confirm_tagged(self, arn):
        """Ask the owning service whether one tagging-API hit still exists.

        Returns {resource_type, id, observed, gone}. Gone means the service itself said so:
        EC2 `*.NotFound`, an ECS cluster or task definition that is INACTIVE (free, and listed
        until deleted), an RDS or S3 not-found. Anything else, including a check that could not
        be made, stays reported with what was observed, so a wrong guess can only add a line to
        the receipt and never hide a resource that costs money.
        """
        service, kind, ident = self.arn_parts(arn)
        row = {"resource_type": f"{service}:{kind}", "id": arn, "observed": "unchecked",
               "gone": False}

        def gone(state):
            row.update(observed=state, gone=True)
            return row

        def seen(state):
            row.update(observed=str(state or "exists"))
            return row

        def first_item(described):
            return next((v[0] for v in described.values()
                         if isinstance(v, list) and v and isinstance(v[0], dict)), {})

        try:
            if service == "ec2" and kind in EC2_CHECKS:
                operation, key = EC2_CHECKS[kind]
                try:
                    described = self.aws("ec2", operation, {key: [ident]})
                except AwsError as error:
                    if error.code.endswith(".NotFound"):
                        return gone(error.code)
                    raise
                state = first_item(described).get("State")
                # A deleted endpoint is listed as `deleted` before its NotFound arrives.
                if kind == "vpc-endpoint" and state == "deleted":
                    return gone("deleted")
                return seen(state)
            if service == "ecs" and kind == "cluster":
                described = self.aws("ecs", "describe-clusters", {"clusters": [arn]})
                clusters = described.get("clusters", [])
                if not clusters:
                    return gone("MISSING")
                state = clusters[0].get("status")
                return gone(state) if state in ECS_GONE else seen(state)
            if service == "ecs" and kind == "task-definition":
                try:
                    described = self.aws("ecs", "describe-task-definition", {"taskDefinition": arn})
                except AwsError as error:
                    if "Unable to describe task definition" in error.hint:
                        return gone("NotFound")
                    raise
                state = described["taskDefinition"].get("status")
                return gone(state) if state in ECS_GONE else seen(state)
            if service == "rds" and kind in {"cluster", "db", "cluster-snapshot"}:
                operation, request, codes = {
                    "cluster": ("describe-db-clusters", "DBClusterIdentifier", CLUSTER_NOT_FOUND),
                    "db": ("describe-db-instances", "DBInstanceIdentifier", INSTANCE_NOT_FOUND),
                    "cluster-snapshot": ("describe-db-cluster-snapshots",
                                         "DBClusterSnapshotIdentifier", SNAPSHOT_NOT_FOUND),
                }[kind]
                try:
                    described = self.aws("rds", operation, {request: ident})
                except AwsError as error:
                    if error.code in codes:
                        return gone(error.code)
                    raise
                item = first_item(described)
                return seen(item.get("Status") or item.get("DBInstanceStatus"))
            if service == "s3" and kind == "bucket":
                state = self.bucket_state(ident)
                return gone("NoSuchBucket") if state == "absent" else seen(state)
        except AwsError as error:
            return seen(f"unconfirmed ({error.code})")
        return row

    def delete_inactive_task_definitions(self, observed):
        """Delete this run's INACTIVE task definitions so they stop being listed at all.

        Only revisions the tagging API attributed to this run and ECS itself reports INACTIVE.
        Errors are tolerated and recorded: an INACTIVE definition is free, and a failed delete
        must not turn a clean teardown into a failed one.
        """
        wanted = [row for row in observed if row["resource_type"] == "ecs:task-definition"
                  and row["observed"] == "INACTIVE"]
        for start in range(0, len(wanted), TASK_DEFINITION_DELETE_BATCH):
            batch = wanted[start:start + TASK_DEFINITION_DELETE_BATCH]
            try:
                reply = self.aws("ecs", "delete-task-definitions",
                                 {"taskDefinitions": [row["id"] for row in batch]}) or {}
            except AwsError as error:
                reply = {"failures": [{"arn": row["id"], "reason": error.code} for row in batch]}
            failed = {f.get("arn"): f.get("reason", "failed") for f in reply.get("failures", [])}
            for row in batch:
                row["deletion"] = (f"requested but failed: {failed[row['id']]}"
                                   if row["id"] in failed else "requested")

    def teardown(self):
        if self.s.execute and not self.s.dry_run and self.s.confirm_run_id != self.s.run_id:
            raise DeployError("Destructive teardown needs --confirm-run-id equal to --run-id")
        if self.s.execute:  # deleting the stack is CloudFormation-driven too
            try:
                info = self.credential_probe(self.s.profile)
                arn = None
                if info["kind"] == "long-term":  # only then does the simulation matter
                    arn = self.aws("sts", "get-caller-identity").get("Arn", "")
                credentials.require_mfa_session(
                    self.s.profile, info, mfa_required=self._mfa_answer_for(info, arn))
            except OperationError as error:
                raise DeployError(str(error)) from None
        actions = {
            "td-inventory": self.td_inventory, "td-session-close": self.td_session_close,
            "td-quiesce": self.td_quiesce,
            "td-buckets-emptied": self.td_buckets, "td-images-deleted": self.td_images,
            "td-database": self.td_database, "td-parameters": self.td_parameters,
            "td-stack": self.td_stack, "td-bootstrap-stack": self.td_bootstrap_stack,
            "td-retained": self.td_retained, "td-receipt": self.td_receipt,
        }
        results = {}
        for name in TEARDOWN_STEPS:
            if name != "td-inventory" and not (self.s.execute or self.s.dry_run):
                counts = {k: len(v) for k, v in self.meta()["ownership"]["owned"].items()}
                raise AwaitingExecute(
                    f"inventory complete (owned {counts}); nothing deleted. Re-run with "
                    f"--execute --confirm-run-id {self.s.run_id} to run: "
                    + " -> ".join(TEARDOWN_STEPS[1:]))
            results[name] = self.run_step(name, actions[name], always=name == "td-inventory")
        return results


# ------------------------------------------------------------------ change-set review
STATEFUL = {
    "AWS::RDS::DBCluster", "AWS::RDS::DBInstance", "AWS::S3::Bucket", "AWS::ECR::Repository",
    "AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::SQS::Queue", "AWS::ECS::Cluster",
    "AWS::CloudFront::Distribution",
}


def changed_paths(old, new):
    """Files that differ between two commits of this checkout; None if that cannot be told."""
    if not (old and new and re.fullmatch(r"[0-9a-f]{40}", old)
            and re.fullmatch(r"[0-9a-f]{40}", new)):
        return None
    if old == new:
        return []
    done = subprocess.run(["git", "diff", "--name-only", old, new], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    return done.stdout.split() if done.returncode == 0 else None


def no_changes(described):
    reason = described.get("StatusReason", "")
    return "didn't contain changes" in reason or "No updates" in reason


def summarize(rows):
    keys = ("Action", "LogicalResourceId", "ResourceType", "Replacement")
    return [{k: row[k] for k in keys} for row in rows][:200]


def review_changes(changes, kind, *, allow_replacement=False):
    """Flatten and vet a change set: creates add only, updates never remove or replace state."""
    rows = []
    for change in changes:
        item = change.get("ResourceChange", {})
        rows.append({
            "Action": item.get("Action", "?"), "LogicalResourceId": item.get("LogicalResourceId"),
            "ResourceType": item.get("ResourceType"),
            "Replacement": item.get("Replacement", "False"),
        })
    if not rows:
        raise DeployError("Change set contains no changes")
    if kind == "CREATE" and any(r["Action"] != "Add" for r in rows):
        raise DeployError("An initial stack may only Add resources")
    for row in rows:
        if row["Action"] == "Remove":
            raise DeployError(f"Change set removes {row['LogicalResourceId']}; refusing")
        replaced = row["Replacement"] in {"True", "Conditional"}
        if replaced and row["ResourceType"] in STATEFUL and not allow_replacement:
            raise DeployError(
                f"Change set may replace stateful {row['LogicalResourceId']} "
                f"({row['ResourceType']}); pass --allow-replacement only after review")
    return rows


def load_images(path):
    """Image inputs for the push step.

    Either the evidence file `deploy/v1/build_and_verify.py --out` writes (accepted only when
    its status is LOCAL_ARTIFACT_PASS, and each image must still have the verified config id),
    or a hand-written {"media": ref | {"source": ref, "expected_digest": "sha256:.."}, ...}.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise DeployError("--images is unreadable JSON") from None
    if isinstance(data, dict) and "images" in data and "status" in data:
        if data["status"] != "LOCAL_ARTIFACT_PASS":
            raise DeployError("The build evidence did not pass; refusing to push its images")
        try:
            data = {owner: {"source": image["tag"], "local_id": image["config_id"],
                            **({"source_sha": image["source_sha"]}
                               if image.get("source_sha") else {})}
                    for owner, image in data["images"].items()}
        except (KeyError, TypeError):
            raise DeployError("Build evidence lacks image tags or config ids") from None
    if not isinstance(data, dict) or set(data) != {"media", "processing", "worker"}:
        raise DeployError("--images needs exactly media, processing and worker")
    result = {}
    for owner, value in data.items():
        entry = {"source": value} if isinstance(value, str) else dict(value)
        if set(entry) - {"source", "expected_digest", "local_id", "source_sha"} or not entry.get(
                "source"):
            raise DeployError(f"--images entry for {owner} needs 'source' (and optional digest)")
        if re.search(r"[\s;|&$`]", entry["source"]):
            raise DeployError(f"--images source for {owner} is not a plain image reference")
        digest = entry.get("expected_digest")
        if digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise DeployError(f"expected_digest for {owner} must be sha256:<64 hex>")
        result[owner] = entry
    return result


# ------------------------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(prog="scripts.aws.v1.deploy", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action",
                   choices=["deploy", "teardown", "rehearse", "status", "adopt-release"])
    p.add_argument("--profile", required=True,
                   help="explicit AWS profile, e.g. dc2-agent or dc2-project2-mfa; never 'default'")
    p.add_argument("--region", required=True, help="must be " + REGION)
    p.add_argument("--account", required=True, help="12-digit account; STS must agree")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-id", help="2-16 lowercase alphanumerics: one per-run stack "
                        "dc2-v1-<id> (V1, historical)")
    target.add_argument("--environment", help="2-16 lowercase alphanumerics: the persistent "
                        "always-on stack dc2-<name> that every deploy updates in place (V2-live)")
    p.add_argument("--state-dir", type=Path,
                   help="private 0700 directory outside the repository (journal, outputs, receipt)")
    p.add_argument("--dry-run", action="store_true", help="offline simulation; print the commands")
    p.add_argument("--execute", action="store_true", help="apply change sets / delete resources")
    p.add_argument("--budget-usd", type=float, default=30.0)
    p.add_argument("--budget-name", default=DEFAULT_BUDGET_NAME)
    p.add_argument("--forecast-usd", type=float, help="when Cost Explorer has no forecast")
    p.add_argument("--planned-hours", type=float, default=3.0, help="window used for the estimate")
    p.add_argument("--images", type=Path, help="JSON of the three local amd64 image references")
    p.add_argument("--adopt-bootstrap-stack",
                   help="reuse a healthy staging stack (it is kept on teardown)")
    p.add_argument("--allow-replacement", action="store_true")
    p.add_argument("--skip-final-snapshot", action="store_true",
                   help="teardown: delete Aurora without a final snapshot (default takes one)")
    p.add_argument("--confirm-run-id",
                   help="teardown --execute: repeat the run id (or the environment name)")
    p.add_argument("--seed-email", help="smoke account address (registered via the public API)")
    p.add_argument("--counts-file", type=Path, help="private 0600 attempt-count JSON for close")
    p.add_argument("--assume-empty-counts", action="store_true",
                   help="attest zero attempts (a first deploy launched no worker)")
    p.add_argument("--sql-config", type=Path, help="ca_file/media_dsn_file/processing_dsn_file")
    p.add_argument("--media-revision")
    p.add_argument("--processing-revision")
    p.add_argument("--stop-after", choices=list(dict.fromkeys(DEPLOY_STEPS + PERSISTENT_STEPS)))
    p.add_argument("--stage-rate-limit", type=int, default=20,
                   help="--environment: the Gateway's steady requests per second")
    p.add_argument("--stage-burst-limit", type=int, default=50,
                   help="--environment: the Gateway's burst")
    p.add_argument("--monthly-budget-usd", type=int, default=20,
                   help="--environment: the AWS Budget alerting at 50/80/100 %%")
    p.add_argument("--budget-alert-email", default="",
                   help="--environment: subscribe this address to the budget alerts (optional)")
    p.add_argument("--owner", choices=OWNERS, help="adopt-release: the released owner")
    p.add_argument("--release-dir", type=Path,
                   help="adopt-release: the release plan's directory (plan.json, bundles)")
    p.add_argument("--release-tag", help="adopt-release: the release id its images were tagged")
    p.add_argument("--database-topology", choices=("shared", "separate"), default="shared",
                   help="V2 experiment (#94): one Aurora cluster for both databases (V1, default) "
                        "or one per domain. Fixed for the run: a resume must repeat it")
    p.add_argument("--database-auto-pause-seconds", type=int, default=300,
                   help="idle seconds before Aurora pauses (300 to 86400; V1 uses 300)")
    p.add_argument("--database-max-capacity", type=float, default=2,
                   help="ACU ceiling of each cluster (1 to 256 in steps of 0.5; V1 uses 2)")
    p.add_argument("--unattended-launch", action="store_true",
                   help="V2 (#68): deploy the opt-in launcher (UnattendedLaunch=true); it stays "
                        "off until `session open --unattended`")
    p.add_argument("--station", default="dc2-deploy-station")
    p.add_argument("--plan-detail", choices=["mutating", "all"], default="mutating")
    p.add_argument("--json", action="store_true", help="include the full plan in JSON")
    return p


def ordered_steps(meta):
    steps = sorted(meta["steps"].items(), key=lambda item: item[1]["seq"])
    return {name: record["status"] for name, record in steps}


def format_plan(plan, detail):
    lines, current = [], None
    for entry in plan:
        if detail == "mutating" and not entry["mutating"] and not entry["command"].startswith("#"):
            continue
        if entry["step"] != current:
            current = entry["step"]
            lines.append(f"\n## {current}")
        lines.append(entry["command"])
    return "\n".join(lines).strip()


def prepare_state(args, dry):
    """(state_dir, temp). A dry run never touches a real state directory."""
    if dry:
        temp = tempfile.TemporaryDirectory(prefix="dc2-deploy-state-")
        Path(temp.name).chmod(0o700)
        return Path(temp.name), temp
    if args.state_dir is None:
        raise DeployError("--state-dir is required for a live run")
    state = args.state_dir
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(state.stat().st_mode) & 0o077 or state.resolve().is_relative_to(ROOT):
        raise DeployError("--state-dir must be private (0700) and outside the repository")
    return state, None


def main(argv=None, *, environ=None, transport=None, docker=None, http=None, session_main=None,
         stdout=None, stderr=None, clock=time.monotonic, sleep=time.sleep, today=None):
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    temp = None
    try:
        if args.dry_run and args.execute:
            raise DeployError("--dry-run and --execute are mutually exclusive")
        rehearse = args.action == "rehearse"
        dry = args.dry_run or rehearse
        state, temp = prepare_state(args, dry)
        try:
            database = DatabaseOptions(args.database_topology, args.database_auto_pause_seconds,
                                       args.database_max_capacity)
        except ValueError as error:
            raise DeployError(str(error)) from None
        persistent = args.environment is not None
        settings = Settings(
            profile=args.profile, region=args.region, account=args.account,
            run_id=args.environment if persistent else args.run_id, persistent=persistent,
            stage_rate_limit=args.stage_rate_limit, stage_burst_limit=args.stage_burst_limit,
            monthly_budget_usd=args.monthly_budget_usd,
            budget_alert_email=args.budget_alert_email,
            state_dir=state, budget_usd=args.budget_usd, budget_name=args.budget_name,
            forecast_usd=args.forecast_usd, planned_hours=args.planned_hours,
            execute=args.execute or rehearse, dry_run=dry, images_file=args.images,
            adopt_bootstrap=args.adopt_bootstrap_stack, allow_replacement=args.allow_replacement,
            skip_final_snapshot=args.skip_final_snapshot, confirm_run_id=args.confirm_run_id,
            seed_email=args.seed_email, counts_file=args.counts_file,
            assume_empty_counts=args.assume_empty_counts or dry, sql_config=args.sql_config,
            station=args.station, database=database, unattended_launch=args.unattended_launch)
        journal = DeployJournal(state / "deploy-journal.json", station=settings.station,
                                environment=settings.env)
        if args.action == "status":
            print(json.dumps(journal.view(), indent=2, sort_keys=True), file=stdout)
            return 0
        if args.action == "adopt-release":
            if dry or not persistent:
                raise DeployError("adopt-release applies to a live --environment only")
            with journal.run_lock():
                adopted = adopt_release(journal, args.owner, args.release_dir, args.release_tag)
            print(json.dumps({"ok": True, "adopted": adopted}, indent=2), file=stdout)
            return 0
        seed = None
        if dry:
            from scripts.aws.v1 import deploy_sim

            seed = recorded_state(args) if args.action == "teardown" else None
            aws = transport or deploy_sim.SimulatedAws(settings, seed=seed)
            http = http or deploy_sim.simulated_http
            if sleep is time.sleep:  # the simulation completes without waiting
                sleep = lambda _seconds: None  # noqa: E731
            settings.seed_email = settings.seed_email or "smoke@example.com"
            if not settings.images_file:
                settings.images_file = state / "rehearsal-images.json"
                settings.images_file.write_text(json.dumps({
                    o: f"dc2-v1-{o}:rehearsal" for o in ("media", "processing", "worker")}))
            if not docker:
                docker = (deploy_sim.ObservingDocker(aws, verified_ids(settings.images_file))
                          if not rehearse else deploy_sim.SimulatedDocker(aws))
        else:
            aws = transport or CliTransport(settings.scope, environ=environ)
            docker = docker or (DockerCli() if args.action == "deploy" else None)
        return execute(settings, aws, journal, docker, http, session_main, args, seed, stdout,
                       stderr, clock, sleep, today)
    except AwaitingExecute as waiting:
        print(json.dumps({"ok": True, "awaiting_execute": str(waiting)}), file=stdout)
        return 3
    except OperationError as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=stdout)
        return 1
    finally:
        if hasattr(docker, "close"):
            docker.close()
        if temp:
            temp.cleanup()


def verified_ids(path):
    """{image reference: config id} for images that build evidence verified, else empty.

    A hand-written images file carries no id to compare, so a dry run has nothing to observe
    for it and stays entirely simulated. An unreadable file is the images step's error to
    report, not this lookup's.
    """
    try:
        return {entry["source"]: entry["local_id"]
                for entry in load_images(path).values() if entry.get("local_id")}
    except DeployError:
        return {}


def recorded_state(args):
    """Read-only view of a real run's journal, used to rehearse its teardown offline."""
    if not args.state_dir:
        raise DeployError("teardown --dry-run needs --state-dir to read the run's journal; "
                          "use 'rehearse' for a self-contained deploy+teardown simulation")
    path = args.state_dir / "deploy-journal.json"
    persistent = args.environment is not None
    environment = env_name(args.environment if persistent else args.run_id, persistent=persistent)
    journal = DeployJournal(path, station=args.station, environment=environment)
    if not journal.exists():
        raise DeployError("No journal for this run; nothing recorded to tear down")
    return journal.view()


def adopt_release(journal, owner, release_dir, tag):
    """Make a promoted release's images the ones the persistent environment's stack renders.

    After `release promote` the aliases run the new images, while the journal (and so the
    next `applications` render, the stack's task definitions and the launcher's worker) still
    name the old ones. Recording them here, then updating the stack, keeps the stack the
    single description of what runs, and makes this release the next one's baseline.
    """
    if not (owner and release_dir and tag and re.fullmatch(r"[a-z0-9]{1,24}", tag)):
        raise DeployError("adopt-release needs --owner, --release-dir and a plain --release-tag")
    try:
        plan = json.loads((Path(release_dir) / "plan.json").read_text())
        bundle = json.loads((Path(release_dir) / plan["good"]["bundle"]).read_text())
    except (OSError, ValueError, KeyError, TypeError):
        raise DeployError("The release plan or its good bundle is unreadable") from None
    if plan.get("owner") != owner:
        raise DeployError(f"The release plan is for {plan.get('owner')}, not {owner}")
    names = {"api": owner, "worker": "worker"}
    adopted = {}

    def change(d):
        for kind, image in bundle.items():
            name = names[kind]
            repository = d["outputs"][f"{name.title()}RepositoryUri"]
            digest = image["manifest_digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise DeployError(f"The {name} digest in the release bundle is malformed")
            d["images"].setdefault(name, {}).update(
                tag=f"{tag}-{name}", digest=digest, uri=f"{repository}@{digest}",
                local_id=image["config_id"], source_sha=image["source_sha"],
                scan_severity_counts="see the release plan")
            adopted[name] = digest

    journal.mutate(change)
    return adopted


def check_database_layout(journal, wanted):
    """A run's database topology is fixed when it is created.

    The topology decides which resources and outputs exist; flipping it on a live stack would
    add a cluster without moving data, or ask CloudFormation to remove a database. Auto-pause
    and the ACU ceiling are in-place cluster settings and may be changed on a resume. A
    journal written before this option existed is V1's layout.
    """
    created = DatabaseOptions(**journal.view().get("database", {}))
    if created.topology != wanted.topology:
        raise DeployError(
            f"This run was created with database topology {created.topology}; use a new "
            "--run-id for another layout (a live stack's topology cannot be changed)")
    if created != wanted:
        journal.mutate(lambda d: d.update(database=wanted.as_dict()))


def execute(settings, aws, journal, docker, http, session_main, args, seed, stdout, stderr,
            clock, sleep, today):
    meta = {"run_id": settings.run_id, "env": settings.env, "account": settings.account,
            "region": settings.region, "created_at": now(), "steps": {}, "resources": {},
            "outputs": {}, "images": {}, "events": [], "database": settings.database.as_dict()}
    if seed:  # rehearsing a real run's teardown: start from what that run recorded
        meta.update({k: copy.deepcopy(seed[k])
                     for k in ("resources", "outputs", "images", "database") if k in seed})
    if not journal.exists():
        if args.action == "teardown" and not settings.dry_run:
            raise DeployError("No journal for this run; nothing recorded to tear down")
        journal.create(meta)
    elif journal.view()["account"] != settings.account:
        raise DeployError("Journal belongs to a different account")
    elif args.action in {"deploy", "rehearse"}:
        check_database_layout(journal, settings.database)
    revisions = {"media": args.media_revision, "processing": args.processing_revision}
    plans, receipt = [], None

    def pipeline():
        return Pipeline(settings, aws, journal, docker=docker, http=http,
                        session_main=session_main, clock=clock, sleep=sleep, stderr=stderr,
                        today=today)

    with journal.run_lock():
        if args.action in {"deploy", "rehearse"}:
            deploy = pipeline()
            try:
                deploy.deploy(stop_after=args.stop_after, revisions=revisions)
            finally:
                plans += deploy.plan
        if args.action in {"teardown", "rehearse"}:
            down = pipeline()
            try:
                down.teardown()
            finally:
                plans += down.plan
            receipt = down.receipt
    out = {"ok": True, "mode": "dry-run" if settings.dry_run else "live",
           "scope": settings.scope, "run_id": settings.run_id,
           "steps": ordered_steps(journal.view())}
    if settings.dry_run:
        out["simulated"] = ("offline simulation: ordering and request shape, not account facts; "
                               "image ids may be observed from the local Docker daemon, "
                               "see image_inspect")
        out["plan_calls"] = len(plans)
        out["mutating_calls"] = sum(1 for p in plans if p["mutating"])
        by_step = {}
        for entry in plans:
            counts = by_step.setdefault(entry["step"], {"read": 0, "mutating": 0})
            counts["mutating" if entry["mutating"] else "read"] += 1
        out["calls_by_step"] = by_step
        inspected = {e["command"].split()[-1]: e["basis"] for e in plans if e.get("basis")}
        if inspected:
            out["image_inspect"] = inspected
        if args.json:
            out["plan"] = plans
    if receipt:
        out["resources_remaining_receipt"] = receipt
    print(json.dumps(out, indent=2), file=stdout)
    if settings.dry_run and not args.json:
        print("\n" + format_plan(plans, args.plan_detail), file=stdout)
    return 0


if __name__ == "__main__":
    # Re-import under the package name: running as __main__ would give the simulation (which
    # imports this module) a second, distinct AwsError class that the pipeline cannot catch.
    from scripts.aws.v1.deploy import main as package_main

    raise SystemExit(package_main())
