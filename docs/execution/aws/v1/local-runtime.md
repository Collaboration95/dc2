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
- `FLOW=b` runs `tests/v1/test_workflow_acceptance.py` (Publisher direct intake,
  login and owner denials, command/result projections, duplicate and reordered
  results, edit/cancel/delete, MP4 range and HLS reads, and a stored-source retry:
  attempt one fails after a real encode against an unwritable output bucket, the local
  file is deleted, and attempt two succeeds from the stored object). With `V1_BROWSER=1`
  it also runs `tests/v1/test_browser_acceptance.py`: the shipped frontend in headless
  Chromium over local HTTPS registers, signs out and in, uploads straight to the object
  store, waits for a real encode, plays the HLS ladder twice (hls.js with native HLS hidden, then the browser's
  own native HLS), reads the MP4 by range under CORS and deletes. The buckets get the CORS
  rules from `deploy/aws/v1/template.json`, not a permissive stand-in. Install the browser first (`make browser-install`
  or `playwright install chromium`). Without the flag the browser leg is recorded
  `NOT_RUN` and `complete_v1_acceptance` stays `NOT_RUN`; with the flag a missing browser
  fails.
  Native HLS: the facade 307-redirects each segment to a presigned URL on the object
  store, a different origin. Chromium demuxes native HLS in-process and rejects such a
  segment unless it passed CORS, failing with `MEDIA_ERR_SRC_NOT_SUPPORTED` (reproduced
  with a plain two-origin server, so it is not a bridge artefact). The player therefore
  sets `crossorigin="anonymous"` on the native path and the output bucket allows the site
  origin. Safari/iOS were not available here; that path is Chromium evidence only.
- `FLOW=c` runs the session contracts and `tests/v1/test_release_acceptance.py`: for each
  owner the schema is really stepped back one Alembic revision, a fake ECS task runs the
  owner's real migrator, promotion is checked for row preservation, peer isolation and
  alias moves, and a failed candidate restores aliases while the schema stays forward;
  a session close/wake with real SQL readiness, the actual repair handlers and SQL
  outcome counts keeps the queued message through close and then runs the exact finite
  encoder command the session issued. The Lambda/ECS control plane is an in-memory
  transport, so alias and RunTask behaviour is our state machine, not AWS.
- `FLOW=all` executes every flow and fails on any failed/incomplete gate. Skipped
  acceptance tests cannot satisfy the gate. Never label `FLOW=a` complete V1.

Re-running against the same runtime is supported. Each verification recreates the
run-owned queues (PurgeQueue is limited to once a minute and cannot drop invisible
messages), and every finite encoder gets a unique task name because
`attempt_tasks.task_name` is unique like a real task ARN. Repair re-stages every queued
attempt in the SQL volume, so a runtime that accumulated interrupted runs may deliver
another job's message to a finite task first; the session test therefore issues batches
until its own asset completes. Start from `make v1-down DELETE_DATA=1 && make v1-up` for
a pristine volume.

Child tests receive an explicit local AWS endpoint and dummy credentials,
metadata disabled, no inherited AWS profile, local owner DSNs and
`V1_RUNTIME_CONFIG`/`V1_RUN_ID`. Owners should open their own sessions and close
connections. Required migrations run through the owning migrator, never a
runtime role. The probe table `public.v1_runtime_probe` is separate from product
schema and preserves queued rows for restart checks.

Every invocation retains `.cache/v1-runtime/<id>/evidence-*/manifest.json`:

- `source`: commit SHA, dirty flag, untracked-file count and, when dirty, a hash of the
  uncommitted bytes. `source_sha` and `tracked_dirty` remain as flat copies.
- `images`: each V1 image is `BUILT` (config ID, revision label, whether it equals the
  source SHA; taken from a `make v1-images` receipt for this exact commit, otherwise from a
  local `:latest` tag) or `NOT_BUILT`. Every image has `exercised_by_this_run: false`:
  handlers run from source in-process. The PostgreSQL image actually running is recorded.
- `tools`: Python, FFmpeg and Moto versions.
- `boundaries`: what is `real`, what is `emulated` (API Gateway bridge, Moto S3/SQS,
  manual event-source delivery, in-process Lambda handlers, a local subprocess for
  Fargate, an in-memory release transport, a local certificate) and what is `not_run`
  (IAM, Aurora networking and pause, public DNS/TLS/CloudFront, registry images, billing).
- per-flow outcomes and test counts, `browser_requested`, `complete_v1_acceptance`
  (needs every flow and the browser leg) and `cloud_acceptance`, always `NOT_RUN`.
- `failed_tests`: every failing or erroring test as `{flow, id, kind, message}` (also nested
  under the flow's `failed_tests`), plus `skipped_tests` per flow. `kind: run` means the
  runner was killed at its time budget or crashed before reporting. Messages are cut to a few
  lines and redacted.

Private raw test logs are not published by CI. Keep failed manifests.

Failure detail. Each failing test is printed to stderr as `FAILED flow b: <id> (<kind>):
<assertion>`, and as a `::error` annotation in GitHub Actions. Beside the junit report the
runner writes `junit-<tag>.redacted.xml`, and the browser leg writes `failure-browser/<hlsjs|native>/`
with `page.png` (a screenshot) and `state.json` (visible status text, video state, the last
responses as method/path/status, console messages, work-pump errors). On failure CI uploads those
as `v1-local-failure-<sha>-<attempt>`. All of it passes through `scripts/dev/v1_redact.py`, which
removes cookie values, JWTs, bearer tokens and URL query strings (a presigned URL keeps its path
only). The raw junit and `pytest-private-*.log` stay in the private runtime directory. No
Playwright trace is kept, because a trace embeds headers and presigned URLs verbatim.

Browser-leg timing. Every wait polls observable state under a bounded deadline: the job's
status (150s, aborted at once when the work pump is stuck), the player's `currentSrc`, the
playlist and segment requests, and the media clock (60s each). The work pump forgives a single
failed iteration, for example one Moto call that exceeds its timeout on a loaded runner, and
fails the test only after six in a row or when it is still failing at the end (it gets one last
pass first). The runner's own budget for the browser tests is 660s; an earlier 180s limit
killed the run and left only a bare "FAIL".

The native leg's "redirected segment read" is judged from the two server-side logs, not from
Playwright's request and response events: the Gateway bridge's `redirects` (paths of its 307s)
and the storage proxy's `segment_reads` (path, `Origin`, whether a cookie arrived). Under load
Playwright can report the redirect hop after the response that followed it, filed under the
first request's URL (CI run 38988347791, attempt 1), so the events can lag what happened.

`V1_COVERAGE=1` additionally measures the test processes and their children (encoder,
Alembic) and writes `artifacts/coverage/.coverage.v1-integration`, the tier that
`ci.yml`'s combined gate merges with the fast and legacy tiers.

## CI and local gates

`.github/workflows/v1.yml` is a reusable workflow that `ci.yml` calls on every pull
request, defaulting to `FLOW=all` with `V1_BROWSER=1` and `V1_COVERAGE=1`. It lints the
rendered template (`make lint-cfn CFN_LINT_ARGS=--require`, cfn-lint pinned and installed
outside `uv.lock`), runs `make test-aws` and `make test-v1` (both under the same
offline network guard as `make test`), starts a unique runtime, verifies all flows,
requires `complete_v1_acceptance == PASS`, uploads the manifest and the coverage
fragment, and tears down only its namespace. A manual dispatch can set `images` to run
`make v1-images` (native amd64 builds and Runtime Interface Emulator handler runs). The
job also runs by itself when a pull request or push changes `deploy/v1/**`,
`deploy/aws/v1/**`, `media/handlers.py`, `processing/handlers.py`, `*/lambda_handler.py`,
`processing/worker/**`, `runtime_support/**`, `pyproject.toml` or `uv.lock`. A green run is a local-emulation
result and does not close #92 or establish a cloud PASS.

## Local VM resources

V1 verification needs only Docker and uses no VM. The optional project Lima VM
(`make capacity-start`) defaults to 2 vCPU / 2 GiB with a 2 hour lease; `--benchmark`
(`CAPACITY_ARGS=--benchmark`) is the only way to ask for 8 / 8 and prints the cost first.
Requests are validated, an existing instance keeps its persisted size, and `status` never
starts anything. `make capacity-reap` stops a VM whose lease lapsed, `capacity-renew`
extends one, `--keep-alive` allows an intentional demo up to 24 hours, and a task that
started the VM stops it when it finishes (`capacity.py run -- COMMAND`). Another task's
unexpired lease is never overridden without `--force`.

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
