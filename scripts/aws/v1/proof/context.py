"""Everything a harness needs, built once: scope, outputs, journal, transports and clocks.

A live context talks to AWS through the same sanitized `aws` CLI transport the deploy pipeline
uses (explicit profile, never `default`, ambient credentials refused) after a fresh STS check.
A simulated context swaps in the in-memory world from `sim.py`; nothing it does is evidence.
"""

import dataclasses
import json
import re
import time
from pathlib import Path

from scripts.aws.journal import Journal
from scripts.aws.v1 import operations, release_cli
from scripts.aws.v1.deploy import CliTransport
from scripts.aws.v1.proof.core import Api, Proof, ProofError, SessionGuard
from scripts.aws.v1.public_smoke import load_credentials, urllib_http
from scripts.aws.v1.transport import REGION


@dataclasses.dataclass
class Context:
    scope: dict
    state_dir: Path
    run_id: str
    simulated: bool
    outputs: dict
    config: dict
    hooks: dict
    urls: dict
    data: dict
    journal: object
    aws: object
    http: object
    clock: object = time.monotonic
    sleep: object = time.sleep
    wall: object = time.time
    credentials: object = None
    sqs: object = None
    sdk: object = None  # scope -> OperatorTransport (lambda/events/gateway/ecs), for Session reads
    release_main: object = None
    world: object = None
    fresh: object = None  # None | True | set of step names: archive and rerun (see Proof)

    @property
    def evidence_dir(self):
        return self.state_dir / "evidence"

    @property
    def gateway_url(self):
        return self.outputs["HttpApiUrl"]

    @property
    def frontend_url(self):
        return self.outputs["FrontendUrl"]

    def api(self, origin="frontend"):
        base = self.frontend_url if origin == "frontend" else self.gateway_url
        return Api(base, self.http, self.clock)

    def proof(self, issue, required, *, guarded=True):
        guard = SessionGuard(self.journal, self.aws, self.config) if guarded else None
        # The scope (including the account id) stays in the private receipt only.
        return Proof(
            issue,
            directory=self.evidence_dir,
            run_id=self.run_id,
            simulated=self.simulated,
            scope=dict(self.scope),
            required=required,
            guard=guard,
            wall=self.wall,
            fresh=self.fresh,
        )

    def deadline(self, seconds):
        return self.clock() + seconds


# The operator transport gives Lambda calls a 70 s network allowance (connect 5 + read 65, see
# operations.py) and refuses to start one with less budget left, so a Lambda call's deadline must
# exceed that. 60 s, right for the quick services, made the first live isolation run fail with
# "Insufficient request deadline" before it sent anything (r1018b).
LAMBDA_CALL_SECONDS = 90


def check_scope(profile, region, account):
    if (
        not profile
        or profile == "default"
        or not operations.PROFILE_PATTERN.fullmatch(profile)
        or region != REGION
        or not re.fullmatch(r"[0-9]{12}", account or "")
    ):
        raise ProofError(
            f"An explicit non-default profile, {REGION} and a 12-digit account are required"
        )
    return {"profile": profile, "region": region, "account": account}


def load_state(state_dir, config_path=None):
    """The deploy pipeline's operator config plus the stack outputs it points at."""
    path = Path(config_path) if config_path else Path(state_dir) / "operator-config.json"
    data, config, hooks, urls = operations.load_operator_config(path)
    outputs = operations.normalize_outputs(json.loads(Path(data["outputs_file"]).read_text()))
    journal = Journal(
        data["journal"], station=data["operator_station"], environment=data["environment_id"]
    )
    return data, config, hooks, urls, outputs, journal


def live(
    args,
    *,
    aws=None,
    http=None,
    sqs=None,
    sdk=None,
    release_main=None,
    clock=time.monotonic,
    sleep=time.sleep,
    wall=time.time,
):
    """Build a live context. `aws`/`http`/`sqs` are injectable so tests never reach the network."""
    scope = check_scope(args.profile, args.region, args.account)
    state = Path(args.state_dir)
    if not state.is_dir():
        raise ProofError("--state-dir must be the private directory the deploy used")
    data, config, hooks, urls, outputs, journal = load_state(state, args.config)
    aws = aws or CliTransport(scope)
    identity = aws.call("sts", "get-caller-identity", {})
    if identity.get("Account") != scope["account"]:
        raise ProofError("STS account differs from --account; no further calls")
    smoke = state / "smoke-credentials.json"
    return Context(
        scope=scope,
        state_dir=state,
        run_id=args.run_id,
        simulated=False,
        outputs=outputs,
        config=config,
        hooks=hooks,
        urls=urls,
        data=data,
        journal=journal,
        aws=aws,
        http=http or urllib_http,
        clock=clock,
        sleep=sleep,
        wall=wall,
        credentials=lambda: load_credentials(smoke),
        sqs=sqs or (lambda: operations.live_sqs_client(scope)),
        sdk=sdk or operations.live_transport,
        release_main=release_main or release_cli.main,
    )
