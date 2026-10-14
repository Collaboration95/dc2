# Offline AWS definitions

These definitions are preparation, with no apply command or production transport.
Do not apply while account/spend approval (#45) or requirement-owner restricted
origin HTTP disposition (#46) is unresolved. No test in this bundle establishes
an AWS PASS. All three ECS services have desired count zero; CloudFront is disabled.
State EC2 would start on a future apply, so zero ECS counts are not permission to
apply this template. There is no EIP, NAT, load balancer, purchased zone, paid
endpoint, resident worker, automatic starter, snapshot or backup daemon.

Render using `python -m scripts.aws.definitions environment` or `generator`.
The checked-in JSON must match that renderer. Validate it offline with cfn-lint;
do not use AWS validate-template. The separate generator stack is exclusively
for later approved timed checks and must be terminated with its 8GiB root deleted.
No compute or test generator belongs on the state host.

## Private inputs and edge activation

All ECS secrets are exact existing standard SSM SecureString parameter ARNs,
using the AWS-managed SSM key. Runtime, migrator and execution identities are
separate. Do not replace references with plaintext/dynamic DSNs. The state host
may read only `StateSecretsArn` and `OriginGateArn`. Scope operator backup access
to `private/<environment>/exports/` in the separate private backup bucket.

CloudFront does not support the SecureString dynamic reference needed for its
custom origin header. This template therefore contains no header value and does
not invent a NoEcho secrecy guarantee. An approved operator must privately read
`OriginGateArn`, inject the same gate into nginx's root-owned0600 include and the
distribution's `X-DC2-Origin-Gate` custom origin header, set the current EC2 public
DNS origin, and enable the distribution only after disposition and negative gate
checks. Do not write that value into CloudFormation, source, plans, CLI arguments,
logs or evidence. Future CloudFront configuration reads contain it and must remain
private. `private_edge_activation_plan()` remains BLOCKED even with a disposition
boolean; there is no automatic approval/action path here.

CloudFront allows seven application methods, forwards all viewer headers/cookies/
query strings, uses zero TTL at `/api` and `/api/*` and the default behavior, and
sets error TTL zero without replacing API errors with a SPA. Default static assets
also revalidate. Viewer policy is HTTPS-only and uses the generated hostname.
This does **not** encrypt the restricted HTTP origin leg. CloudFront prefix-list
ingress uses a separate security group because the managed list consumes55rules.

nginx overwrites the public Host/forwarded HTTPS fields, removes the origin secret
before proxying, resolves the qualified Media name with the VPC resolver every5s,
rejects `/internal` and local MinIO paths, and keeps the existing frontend.
Its `/api` exact path is404; `/api/` preserves the existing prefix stripping.
Cookies, Set-Cookie, authentication, query and Range pass through normally; no
intercepted error, cached redirect or SPA conversion is added. Access logs are off
and error logging is critical only to avoid bearer query/header leakage.

## State installation and disk limits

User data only creates a private configuration directory. Installation is an
explicit future authorized operator step, not hidden provisioning in this bundle.
Stage the reviewed repository artifact at `/opt/dc2`; existing frontend and
`deploy/postgres/{bootstrap,smoke}.sh` are reused. Install Docker/Compose and pinned
state image digests through that later workflow, without application images,
FFmpeg, generators or builds on this host. Do not assume the AMI has these tools.

The 8GiB retained encrypted data volume must already have a reviewed filesystem
UUID before installing the fstab entry. First formatting is a distinct destructive
operator decision; bootstrap/restart never formats or guesses a device. Install
the service only after the mount exists. The guard checks exact mount, UUID,
non-root UUID and writable options, refusing missing/wrong/root-backed storage.
The 16GiB root is rebuildable and deleted on instance termination; data is retained
on stack deletion/replacement. Keep state EBS until successful authorized exports
and explicit deletion approval, regardless of export failure.

Privately inject root-owned0600 `mount.env` (UUID/mount) and `state.env`.
Record both future dispositions `DC2_STATE_INSTALL_APPROVED=true` and
`DC2_ORIGIN_HTTP_ACCEPTED=true` in `mount.env` only after their authorized decisions;
the state start script refuses either missing disposition.
Install root-owned0600 `origin-gate.conf` under `/etc/dc2-aws`.
`state.env` contains immutable state image
identities, the current private listener IP, VPC resolver/FQDN/generated viewer
host, five owner/admin DB passwords and Redis password. Reuse PostgreSQL bootstrap
and its own DML/deniedDDL/cross-DB role checks; socket readiness is insufficient.
TCP health is explicit. Never put a migration DSN into a resident service.

PG has a512MiB container cap, bounded connections/work memory/WAL/temp files.
Redis has a128MiB container cap and48MiB maxmemory/noeviction, leaving80MiB for
allocator/process/fork headroom. AOF rewrite starts at32MiB; rewrite overhead and
disk pressure must be measured later. nginx has128MiB and capped scratch/logs.
Host Standard CPU credits can throttle. These are configured budgets, not measured
memory/disk/CPU minima; archive/pressure monitoring remains an operational check.

Uploads stream (`proxy_request_buffering off`, HTTP1.1) with a101MiB body ceiling
for a100MiB file plus1MiB multipart overhead. Eight concurrent API connections,
128KiB body buffers and16MiB tmpfs bound nginx scratch; no full upload is staged
on the state EBS. API spooling remains in Media's Fargate ephemeral storage.
Read/send/body inactivity timeouts are60s; CloudFront origin read timeout is60s.
Future short slow-upload/multipart checks must prove this path; no large boundary
upload or measured streaming guarantee is claimed. The edge policy cannot enforce
an absolute end-to-end upload duration; the booked lifecycle deadline remains
the independent environment bound.

## Task and operational contracts

Media1024/2048 contains essential API960CPU/1536MiB and reconciler64CPU/512MiB.
API512/1024 and recovery256/512 are separate services; recovery runs every15s and
has no RunTask/PassRole. Workers2048/4096 are standalone and normally absent.
`WorkerContainerMemory`1536(default) or4096 is distinct from billed task memory.
Worker base command is fixed to `python -m processing.worker --cloud-deadline 0
--name operator-override-required --burst`. Deadline0 fails closed: directRunTask
without bounded command overrides cannot start an infinite resident worker.
No arbitrary `WorkerCommand` parameter exists, and `cloud.py` is not a moduleCLI.
The operator starts exactly1task per journal-correlated request, overriding the
command with a unique name and future absolute epoch deadline; `--burst` is
optional for explicit fixed-capacity prewarming. Shared config and template
`WorkerLifetimeSeconds` enforce60–3600s. `DC2_WORKER_LIFETIME_SECONDS` records that
budget in the task environment; it does not replace the required absolute
`--cloud-deadline` argument or authorize a launch. Selected Processing image must
contain the delivery bundle's implemented worker entrypoint.

Services are socket-live independently of peer state. `readiness_plan(owner)`
requires owned TCP/schema/DML/denial/revision/DNS/authenticated-peer receipts and
Processing Redis connectivity. Liveness and `worker_dispatch_connected` are not
deployment readiness. Each one-off migration uses its owner image/isolated DSN;
later releases require taskSTOPPED/exit0/expected revision. Private DNS names are
`media.<env>.internal`, `processing.<env>.internal`; recovery registers neither.
ECS replaces API IPs, so future release tests must prove DNS re-resolution.

Media can sign/read/write/delete/abort sources and read outputs. Workers can
only put/abort `jobs/*` outputs; they have no source or output-read/list/delete
IAM. Source GET uses Media grants and its signer authority. Recovery may list
`jobs/*` and delete there only. API/migrations have no S3 task policy. Private
backup permissions belong to operator only. S3 BlockPublicAccess/AES256/TLS and
one-day incomplete-MPU eligibility retain completed retryable sources. Output
CORS allows exactly the generated HTTPS origin and GET/Range. The free gateway
endpoint allows app signer flows and regional ECR starport layers; no endpoint
blanket deny breaks externally presigned playback.

## Export boundary

`scripts.aws.exports.export_state` accepts explicit config/proof, bounded command
and storage adapters, a private directory, absolute deadline and clock. During
this preparation it accepts only adapters declaring `evidence_kind="offline"`;
there is no live executor. Both owner dumps and the four-role export belong to one
quiescent set with private hashes/lengths/revisions. Manifest publication follows
confirmed data writes; incomplete sets are not committed backups. Retention
deletes only older committed sets in the exact private prefix and keeps latest2.
Failure preserves partial private files/EBS and blocks backup/teardown claims.

The lifecycle proof requires environment/station/boundary identity, intake and
launches closed, workers drained, zero active claims/nonterminal tasks/unresolved
launches, all five writer categories quiesced, and fresh issued/expiry times
covering a <=300s absolute deadline. Freshness is90s; operators must use a short
export or renew the proof through the common lifecycle boundary. Refer to the
bundle report for exact adapter/proof fields. A bounded64MiB total fails closed
rather than expanding disks/allowances automatically.

`restore_plan` requires a separate explicit approval and `restore-*` isolated
target. `verify_private_export` checks private file modes/lengths/hashes first.
Actual restore must recreate only the four owner roles, both owned databases,
validate revisions/references and role denials, then clean only throwaway compute
and storage. Offline export PASS never becomes AWS backup or restore PASS.
