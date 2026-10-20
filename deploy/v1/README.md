# V1 owner images and releases

These recipes consume owner-specific frozen extras `v1-media`, `v1-processing`,
and `v1-worker` from `pyproject.toml`; `uv.lock` supplies resolved versions and
hashes. Redis/RQ and the inherited app's multipart/auth dependencies stay in the
explicit `legacy` extra. No Mangum is needed: the owning handlers use GatewayAdapter.
The two API extras include Alembic because their migration tasks run from those
images. The worker uses the shared `asyncpg` dependency for its standalone bootstrap
task and does not install Alembic.
`contracts`, `delivery` and `runtime_support` must be integrated before building.

The retired peer-HTTP Media client, the Redis/RQ Processing worker and their settings live
in the top-level `legacy/` package, which no V1 recipe copies. `check_runtime.py` fails the
build if `legacy` or any of its former `media`/`processing` module paths is importable in an
image, so the two services' only coupling in V1 is SQS plus the outbox/inbox.

The coordinator supplies the verified RDS bundle at `deploy/v1/global-bundle.pem`.
It is copied to `/opt/rds/global-bundle.pem`. No substitute bundle is generated.
The current recipes use the same pinned Python base as the reviewed AWS2 images;
execute the retained exact-image scan gate before any promotion. A base pin is
provenance, not a claim that the image currently has zero fixable findings.

Lead C coordinates Docker use; do not run concurrent stacks or heavy encodes.
From integrated frozen source (replace SOURCE_SHA with that full commit):

```sh
docker build --platform linux/amd64 --build-arg SOURCE_SHA=SOURCE_SHA -f deploy/v1/media.Dockerfile -t dc2-v1-media .
docker build --platform linux/amd64 --build-arg SOURCE_SHA=SOURCE_SHA -f deploy/v1/processing.Dockerfile -t dc2-v1-processing .
docker build --platform linux/amd64 --build-arg SOURCE_SHA=SOURCE_SHA -f deploy/v1/worker.Dockerfile -t dc2-v1-worker .
docker run --rm --entrypoint python dc2-v1-media /opt/check_runtime.py lambda-api media
docker run --rm --entrypoint python dc2-v1-processing /opt/check_runtime.py lambda-api processing
docker run --rm --entrypoint python dc2-v1-worker /opt/check_runtime.py finite-worker worker
```

The checks execute at image build and can be rerun against its exact config ID.
Retain source tests, runtime-content output and scan bound to that config ID;
use `scripts.aws.artifacts.registry_receipt` to bind registry manifest bytes.
Add `runtime_kind` and `runtime_contents` from the executed check to each proof.
`validate_bundle` requires distinct API and worker artifacts and common source.
Do not rebuild after scanning or equate local config IDs with registry digests.

API default commands are `media.lambda_handler.handler` and
`processing.lambda_handler.handler`. Every authorizer/control handler is another
Lambda function with the SAME owning image and its own ImageConfig.Command.
C1 confirms Media authorizer `media.lambda_handler.authorizer`; other handlers
come from the integrated messaging/recovery lane. The worker image also carries `/opt/db-bootstrap.py` for the template's bootstrap task. The finite worker entrypoint is
`python -m processing.v1_worker --deadline-epoch EPOCH --name TASK --max-empty-polls 2`.
Migration task definitions use the owning API image with ECS **entryPoint**
`["python", "-m", "alembic"]` and command
`["-c", "media/alembic.ini", "upgrade", "head"]` (or Processing). A command
alone does not override the image's Lambda RIC entrypoint. Only the owning
migration role receives its DSN via task secret injection; do not put it in
artifacts, release input, command overrides or journals.

`promote` in `scripts.aws.v1.release` takes an injected transport, private existing
`Journal`, complete `owner_functions` maps (logical key -> physical function name),
`alias` (default live), `cluster`, owning `task_networks`, bundle, pinned image URI,
pinned migration task definition/revision and pinned finite worker definition.
The first deployment must bootstrap a known-good immutable alias; this adapter
intentionally does not invent a rollback version for an untested first install.
Media's map includes API, authorizer, result and repair handlers. Processing's map
includes API, command, repair, ECS and S3 handlers. The operator must supply ALL
functions from the deployed stack, including handlers with disabled triggers.

Required executable hooks:

- `schema_revision(owner, deadline=...)`: observe the owner's SQL revision with
  owner-scoped read credentials. Peer revisions are observed independently. The release
  CLI uses a `sql` station when configured and otherwise `scripts/aws/v1/vpc_reader.py`,
  which runs a finite task in the VPC from the owner's migration task definition (command
  override `scripts/aws/v1/vpc_probe.py`; no secret in the override) and records
  `schema_revision_source: in-vpc-task`. A reader may expose `prefetch(owners, deadline=...)`
  to start several slow reads together.
- `compatibility(owner, prior_snapshot, bundle, target_revision, deadline=...)`:
  execute/check current AND rollback image compatibility with the additive target.
- `quiescent(owner, deadline=...)`: assert the owner's intake and consumers are
  paused and finite tasks drained; include worker reservations in Processing.
- `public_smoke(owner, versions, worker_definition, deadline=...)`: exercise public
  V1 routes/client behavior, then drain any finite test workers before returning.

Hooks return exactly True after checking real state. Never replace these with
unconditional success in an AWS evidence run. The release journals migration
RunTask tokens before sending, waits for STOPPED/exit zero and the owning revision,
prepares immutable versions, then uses revision-checked aliases across the owner.
Multiple aliases cannot move atomically: consumers remain quiescent until the
whole release succeeds. Peer aliases/images/config hashes/schema/worker selection
must remain identical. Function environment values are hashed, never persisted.

A lost PublishVersion response raises `PublicationUncertain`. Call `promote` again
with identical inputs: it reconciles a unique retained release description. If
not yet visible, it refuses to republish; retain intent for explicit reconciliation.
A failed candidate retains `phase=restoring`; call `restore` with a separate bounded
rollback deadline and the same schema/quiescence/public-smoke hooks. It restores
prior aliases and worker selection, proves unchanged peer and never downgrades
schema. An unresolved/failed migration remains blocked for explicit reconciliation;
there is no automatic downgrade or duplicate migration launch with a new token.

The legacy CLITransport production guard is unchanged. The new operator-only
`OperatorTransport` accepts explicit regional SDK clients and freshly supplied STS
identity for an explicit 12-digit account (operator input, never source) in ap-southeast-1. Only the sole AWS operator creates
these clients from the approved session; configure retries `total_max_attempts=1`
and network timeouts totaling at most 15 seconds. No default session, credential
lookup, live CLI or AWS call runs on import. Deadline budgets must cover a complete
bounded request. Session operations use the same bridge; its allowlist now carries per-operation argument contracts.

Local protocol checks:

```sh
PYTHONPATH="$PWD" /path/to/shared/.venv/bin/pytest -q tests/aws/v1/test_release.py
```

These deterministic checks certify adapter behavior only. Docker builds, real SQL
migration/compatibility/public workflow and actual AWS aliases/versions/timing are
separate evidence; #65 remains open until executed by the authorized operator.

The runtime check imports every owning API/authorizer/control or worker/native-source
graph, checks executable exports and denies socket connections during imports. It
rejects importable Redis/RQ modules as well as installed distributions, checks the
opposite domain is absent and parses the actual RDS CA bundle. For workers it runs
FFmpeg/FFprobe version checks. Final artifact checks should run by immutable config
ID with `--platform linux/amd64 --network none --read-only --cap-drop ALL` and the
image default non-root user. API bootstrap import and worker CLI `--help` are
separate entrypoint checks. These are packaging checks, not service I/O acceptance.

## Reproducible local build and verification

```sh
python3 deploy/v1/build_and_verify.py          # clean committed tree; add --no-cache for cold layers
```

One command builds the three images for `linux/amd64` from `HEAD` (the image label is the
commit, so a dirty tree is refused), then verifies, per image:

- `check_runtime.py` passes under the README flags and again as a Lambda-style foreign uid;
- installed distributions: no Redis/RQ, test/dev tooling or the legacy `uvicorn[standard]`
  stack anywhere; `awslambdaric` in every image (the worker's is for the opt-in Lambda short encoder, V2 #93, which overrides the
  entrypoint; Fargate keeps `processing.v1_worker`); FFmpeg only in the worker; `/app`
  carries exactly the owning source;
- every Lambda handler in `deploy/aws/v1/template.json` is invoked inside its own image under
  the AWS Lambda Runtime Interface Emulator (RIE binary copied out of the public
  `public.ecr.aws/lambda/python:3.12` image) with the function's `MemorySize`, using
  payload-v2 health and protected-route events, authorizer events, SQS batches and the
  Processing `{"dc2_operation": "ready"}` direct invoke (false without a database, true against
  a throwaway PostgreSQL container the script creates and removes);
- the short encoder handler (`processing.handlers.short_encoder_handler`) is invoked from the worker image under the RIE
  (empty batch is a no-op, a malformed record is a `batchItemFailures` entry, valid work with no database is
  `database_down`), and FFmpeg/FFprobe encode a clip under Lambda constraints (read-only root, `/tmp` only, a non-root uid);
- the ECS `entryPoint`/`command` shapes of the worker, both owner migrations (run to `head`
  on the throwaway PostgreSQL) and the DB bootstrap task execute from the owning image;
- the worker entrypoint exits fast and finitely with no configuration, with no queue and with
  an expired deadline.

It writes `docs/execution/aws/v1/evidence/local-images-<sha12>.json` (source SHA, input hashes,
config IDs, layer digests, sizes, every check) and exits non-zero on any failure. It never
calls AWS and never pushes. Config IDs embed the build time, so compare `layers_sha256`
between rebuilds, not config IDs. Evidence is LOCAL: no registry receipt, scan or cloud run.

Current run: [local-images-7149324f99bf.json](../../docs/execution/aws/v1/evidence/local-images-7149324f99bf.json)
(64/64 checks; amd64 images 262 MB Media, 262 MB Processing, 675 MB worker).

The 2026-10-15 frozen-source manifest [local-images-f549435.json](../../docs/execution/aws/v1/evidence/local-images-f549435.json)
predates the pruned dependency set, bootstrap script and RIE checks and is retained as history.
