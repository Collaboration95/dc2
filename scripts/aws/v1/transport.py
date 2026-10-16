"""Explicit operator-only SDK bridge. Importing this module performs no AWS calls.

The legacy scripts.aws.transport remains offline-only. Pass already scoped SDK
clients here; there is deliberately no implicit boto3 session/profile discovery.
"""

import time

from scripts.aws.transport import OperationError, remaining, safe_record

OPERATIONS = {
    "lambda": {
        "get-alias",
        "update-alias",
        "get-function",
        "get-function-configuration",
        "update-function-code",
        "publish-version",
        "list-versions-by-function",
    },
    "ecs": {"describe-task-definition", "run-task", "describe-tasks"},
}


class OperatorTransport:
    def __init__(self, clients, *, identity, account, region, clock=time.monotonic):
        if account != "866865534361" or region != "ap-southeast-1":
            raise OperationError("V1 project account/region required")
        if identity.get("Account") != account:
            raise OperationError("Operator must supply freshly verified STS identity")
        if not clients or any(c.meta.region_name != region for c in clients.values()):
            raise OperationError("Explicit regional clients required")
        for client in clients.values():
            config = client.meta.config
            if (config.retries or {}).get("total_max_attempts") != 1:
                raise OperationError("SDK retries must be disabled; reconcile writes explicitly")
            if config.connect_timeout + config.read_timeout > 15:
                raise OperationError("SDK network timeouts must total at most fifteen seconds")
        self.clients, self.clock = clients, clock

    def call(self, service, operation, payload, *, deadline):
        if operation not in OPERATIONS.get(service, set()) or service not in self.clients:
            raise OperationError("Unsupported V1 release operation")
        safe_record(payload)
        # Reserve a full bounded SDK request. No request begins with insufficient budget.
        config = self.clients[service].meta.config
        if remaining(deadline, self.clock) < config.connect_timeout + config.read_timeout:
            raise OperationError("Insufficient request deadline")
        try:
            return getattr(self.clients[service], operation.replace("-", "_"))(**payload)
        except Exception:
            # SDK messages can contain private request/response values.
            raise OperationError("V1 operator request failed; reconcile persisted intent") from None
