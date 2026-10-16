# V1 local runtime and operator session controls

This runtime contains PostgreSQL 16 in a uniquely named Compose project and a
loopback-only Moto 5.2.4 server for S3/SQS. It never starts Redis/RQ or modifies
another Compose project, Docker context, container or volume. PostgreSQL roles,
SQL transactions, FFmpeg, MP4/HLS bytes and HTTP range reads execute locally.
Moto does not prove AWS IAM, Gateway integration, Lambda cold starts, Fargate,
Aurora networking/pause, normal public TLS or billing.

## Commands

Run from the implementation checkout. Use the locked environment installed by
the coordinator; a worker may use `PYTHON=/absolute/shared/.venv/bin/python`
without installing or editing shared dependencies. Every target exports this
checkout as `PYTHONPATH`. Set `V1_MOTO_PYTHON` to a Python environment containing
`moto[server]==5.2.4`, or use the existing `.cache/aws-test-tools/bin/python` in
the primary repository (automatically located through the shared Git directory).
Docker Compose and FFmpeg/FFprobe must be installed.

```sh
make test-v1
make v1-up V1_RUN_ID=v1-demo-20261015
make verify-v1 V1_RUN_ID=v1-demo-20261015 FLOW=a
make verify-v1 V1_RUN_ID=v1-demo-20261015 FLOW=all
make v1-status V1_RUN_ID=v1-demo-20261015
make v1-down V1_RUN_ID=v1-demo-20261015
# Restart the same isolated SQL volume, with fresh ephemeral Moto state:
make v1-up V1_RUN_ID=v1-demo-20261015
# Optional destruction of ONLY this namespace's SQL volume:
make v1-down V1_RUN_ID=v1-demo-20261015 DELETE_DATA=1
```

Use a distinct run ID per independent runtime. `up` refuses an already running
or partially started ID; inspect/down that exact ID before retrying. Its private
config records allocated loopback ports, project name, Docker context and Moto
process identity. Partial startup preserves this config so teardown is possible.
There is no blanket container stop, prune, shared port assumption or AWS call.
Only Lead C starts the shared integration stack during parallel implementation.

`v1-down` retains the PostgreSQL volume, private logs, fixtures and evidence.
Moto S3/SQS are **ephemeral** and discarded when its process stops. This is a
local dependency teardown, not proof that an AWS session close retains objects
and messages. Session `close` below neither tears down dependencies nor purges
queues; it preserves queued work. Local fake bootstrap credentials are fixed in
`deploy/v1-local/compose.yml`; never use these for a reachable deployment.

## Opt-in integration tests against this runtime

`make test-v1` skips every `integration` test. After `make v1-up`, read the loopback ports
from `.cache/v1-runtime/<id>/runtime.json` and run, for example:

```sh
V1_TEST_S3_ENDPOINT=http://127.0.0.1:<moto_port> \
V1_TEST_MEDIA_DSN=postgresql+asyncpg://postgres:local_v1_admin@127.0.0.1:<postgres_port>/media_db \
AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing AWS_EC2_METADATA_DISABLED=true \
  .venv/bin/python -m pytest tests/v1/test_direct_intake_s3.py tests/v1/test_credential_rotation.py -q
```

The admin DSN is for schema-per-test fixtures only; each test creates and drops its own
schema and bucket. Docker Desktop's VM disk can fill; PostgreSQL then fails with
`DiskFullError`, which is an environment fault, not a test failure.

## Verification and honest gates

- `FLOW=a` checks both real SQL ownership boundaries, runtime DML/DDL denial,
  cross-database runtime/migrator denials, versioned source bytes after a late
  overwrite, actual SQS HTTP redelivery, a one-second audiovisual fixture encoded
  with the inherited engine to MP4/HLS and a ranged object read. This is a
  dependency/engine seam, not a complete product workflow.
- `FLOW=b` requires `tests/v1/test_workflow_acceptance.py`, owned by integration.
  It must exercise browser and Publisher direct intake, login/owner denials,
  command/result SQL projections, edit/retry/cancel/delete and playback with the
  integrated handlers. Missing tests produce `INCOMPLETE` and exit 1.
- `FLOW=c` runs the session failure contracts and requires
  `tests/v1/test_release_acceptance.py` for independent owner promotion, failed
  restoration and actual SQL migration/peer isolation. Fake adapter tests alone
  leave this gate `INCOMPLETE` and exit 1.
- `FLOW=all` executes every flow and fails on any failed/incomplete gate. Skipped
  acceptance tests cannot satisfy the gate. Never label `FLOW=a` complete V1.

Child tests receive an explicit local AWS endpoint and dummy credentials,
metadata disabled, no inherited AWS profile, local owner DSNs and
`V1_RUNTIME_CONFIG`/`V1_RUN_ID`. Owners should open their own sessions and close
connections. Required migrations run through the owning migrator, never a
runtime role. The probe table `public.v1_runtime_probe` is separate from product
schema and preserves queued rows for restart checks.

Every invocation retains `.cache/v1-runtime/<id>/evidence-*/manifest.json` with
Git SHA, dirty-source flag, outcome per flow, hashes/lengths and explicit
emulation boundaries. Private raw test logs are not published by CI. Keep failed
manifests. The V1 CI workflow runs operational contracts and `FLOW=a` by default;
manual `flow=all` adds the full integration gate. This default CI pass does not
close #92 or establish a cloud PASS.

## Booked session module

`scripts.aws.v1.session.Session(config, transport, journal)` accepts a designated
private `scripts.aws.journal.Journal` and an injected bounded adapter. It does not
instantiate an SDK or discover credentials. The inherited
`scripts.aws.transport.CLITransport` production execution guard is unchanged.
Only the authorized AWS operator may supply a live adapter.

The config explicitly supplies `functions` (name to positive concurrency, at
most 20 each), `intake_functions` (Media and Processing public mutation APIs),
`mappings` (SQS UUIDs), `schedules` (EventBridge rule names), and the existing
`environment_id`, `operator_station`, `cluster`, `task_definitions.worker`,
`network`, `worker_lifetime_seconds` and `session_end_epoch`. Include application,
authorizer and control functions so close sets **every** function to zero.
C1 outputs `LambdaFunctionNames`, `QueueMappingIds` and `RepairRuleNames` supply
the resource identities; never infer them from another account/environment.

1. Initialize a mode-0600 Journal in a mode-0700 directory only after verified
   empty inventory and exclusive operator handover. All starts/releases/session
   operations share this one station. This file lock is not distributed consensus.
2. `open(ready=..., repair=..., deadline=...)` quiesces intake, restores bounded
   control/authorizer concurrency, checks owned SQL readiness and runs bounded
   repair, confirms mappings/rules, then restores intake. Hooks accept the same
   absolute monotonic deadline and return exactly `True`. No worker starts.
3. `batch(count=1|2|3, deadline=...)` requires an open, unpaused session with no
   pending release. It inventories ECS and reserves each request **before**
   RunTask. Active workers plus unknown/lost-response reservations count toward
   cap three. Each worker runs `processing.v1_worker --deadline-epoch <epoch> --name
   <binding> --max-empty-polls 2`, one finite encode with its own bounded poll/deadline rules. Late
   work remains queued until another explicit batch.
4. `replay(token, deadline=...)` retries the exact saved request/token within its
   original finite lifetime. It never rebuilds payloads from changed releases.
   An expired/ambiguous launch retains its slot until positive ECS reconciliation
   or an explicit audited operator disposition; elapsed time is not STOPPED proof.
5. `close(drain=..., outcomes=..., deadline=...)` immediately pauses starts,
   quiesces intake, calls the owning drain hook, records safe SQL outcome counts,
   and checks inventory. It disables every mapping/rule and zeros all configured
   functions even after a drain failure while the deadline remains. The drain
   hook returns exactly `True` only after task STOPPED and owning SQL completion
   or fencing; forced stop alone does not prove successful drain. Outcomes are
   nonnegative counts of queued/succeeded/failed/cancelled/abandoned jobs.

Partial open/close persists intent, completed steps and failures, remains paused
and must be retried deliberately. A transport timeout cannot become a successful
close. Keep enough deadline reserve for disabling controls; an expired deadline
leaves failure receipts that require operator retry. No queue purge, source
deletion, database destruction or claim of observed Aurora pause occurs here.
Actual Lambda/mapping/rule state, all migration/generator/worker task receipts,
SQL outcomes, Aurora pause and later charges remain operator evidence #63–#67.

## Cost and retained data handoff

`python -m scripts.aws.v1.cost --ledger <private-measured-ledger.json>` uses
captured rates, actual ACU-hours (including wake/maintenance/pause tails), Lambda
GB-seconds and requests (including authorizer/repair), Gateway requests, SQS
request units (including polling/redelivery/visibility), secret reads/months and
selected retained S3/ECR/log/CDN/transfer/snapshot charges. It accounts separately
for worker, migration and generator pull-to-stop durations, Fargate's minimum
minute and allocated IPv4 lifetimes. Missing task timestamps or bills remain
`PENDING`. It performs no AWS billing or price lookup and is not an account cap.

Keep the approximately $200 planning envelope and actual billing currency
separate. The captured V1 forecast remains reproducible in `cost-model.json`;
it is not a bill. A close receipt does not eliminate storage, maintenance,
request, snapshot or delayed billing charges. Restore is `NOT_RUN` unless an
isolated authorized target is restored and owning SQL references/source versions
are checked together. Retain previous owner artifacts; image rollback does not
undo destructive schema changes. Exact live deletion scope belongs to the
operator; this local runbook authorizes no destructive cloud action.

## Integrated handler bridge and shared-stack attachment

`make v1-serve V1_RUN_ID=<id> V1_PORT=0` starts a foreground loopback HTTP bridge
to `media.lambda_handler.handler`, `processing.lambda_handler.handler` and Media's
actual authorizer. It prints its allocated endpoint. Gateway v2 bodies, query
strings, cookie arrays, response cookies and binary responses are preserved;
identity context comes only from the authorizer. No public trust/TLS claim is
made for this local HTTP endpoint. Basic bridge tests use injected handlers;
product acceptance still requires the integrated actual handler suite.

PostgreSQL uses a generated private test certificate with SANs for `127.0.0.1`
and `postgres`. The runtime passes this CA explicitly to Media/Processing and
verifies TLS in the real SQL probe. It installs no system trust. Runtime `up`
creates two versioned Moto buckets and three queues plus DLQs. The child
environment selects those exact queue/store endpoints and local fake native
credentials; no inherited AWS profile or metadata fallback is used.

After cherry-pick, the coordinator can attach tests/serve from its integration
checkout to Lead C's existing dependencies without starting another stack:

```sh
export V1_RUNTIME_CONFIG=/absolute/lead-c-checkout/.cache/v1-runtime/<id>/runtime.json
make verify-v1 V1_RUN_ID=<id> FLOW=all
make v1-serve V1_RUN_ID=<id>
```

This explicit manifest attachment reads the owning runtime config and uses its
TLS CA. Evidence still writes to the calling checkout. Teardown must run in the
owning runtime checkout; never duplicate startup using the same run ID in a
second checkout. Run owning migrations through their local migrator DSNs before
actual handlers, using the release lane's migration adapter. Probe-table success
does not imply product migrations or full client workflow have run.
