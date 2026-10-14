# Infrastructure/state implementation bundle

15 October2026. Assigned branch `work/aws2-infrastructure-state`, isolated worktree
`.worktrees/aws2-infrastructure-state`, baseline `0ffe052`. Issues50/51/52/53/62.
This report covers local implementation/preparation only. No AWS account/API/CLI,
provisioning, deployment, spend, GitHub access/mutation, Alibaba action, Docker/VM/
browser/emulator runtime or large experiment was performed. No issue was closed.
The coordinator owns integration and publication; the local commit SHA is returned
with this report, rather than self-referencing a commit containing its own SHA.

## Issue dispositions

| Issue | Local preparation delivered | Future/genuine-cloud boundary |
|---|---|---|
|50|Parameterized90-resource CloudFormation environment plus separate2-resource generator; oneVPC/AZ/publicsubnet/IGW/freeS3gateway/privateDNS/twoAPI registrations, stateonly t3a.small Standard16+8GiB, twoECR repositories, exact-role/SSM references, privateS3/TLS/BPA/AES256/lifecycle/CORS and scoped IAM/SG assertions. `CloudConfig` owns explicit shared input validation and refuses real actions.|Account/spend45 unresolved; actual IAM/endpoint/imagepull, quota, EC2/SSM/EBS and billing proof NOT_RUN. No live apply adapter exists. GeneratorAMI must contain the reviewed bounded client runtime and fit8GiB; its user-data schedules5–60min termination, with15min default, but actual termination/root deletion still needs receipts.|
|51|Dedicated state Compose/systemd/fstab/UUID guard and capacity checkpoint; existing owner PG bootstrap/role smoke reused. PG512MiB tuning/TCP health, Redis128MiB with48MiB maxmemory/noeviction/AOF rewrite headroom, capped logs/scratch, private listeners. Scoped fake SSM injection writes private600 fixtures and returns selected offline receipts only. Start refuses missing approvals, bad permissions or missing/wrong/root/readonly disks.|Authorized installation, first format, OS/Docker/Compose staging, root ownership, actual private SSM access, coldboot/TCP/schema/grants/data continuity and disk/memory/credit pressure NOT_RUN. No hidden package install/secret fetch/format in user-data. Capacity checkpoint is not continuous monitoring.|
|52|Exactly3zero-count Fargate services: Media1024/2048 essential API960+reconciler64CPU; API512/1024; independently alive recovery256/512 at15s. Standalone worker2048/4096 with1536-or4096 container cap, fixed real worker entrypoint, defaultdeadline0/operator-requiredname and60–3600s budget. Owner-only Alembic tasks, separate runtime/migration/task/execution identities, privateDNS/SG flows and readiness receipt plans.|Delivery bundle supplies the implemented `processing.worker --cloud-deadline <epoch> --name <unique-name> [--burst]` entrypoint in the selected Processing digest. No arbitrary command parameter bypass exists. Actual migration STOPPED/exit0/revision, owned readiness, recovery survival, DNS replacement, task memory/quota and zero-worker launch accounting NOT_RUN. No wrapper or worker service is invented here.|
|53|Disabled CloudFront generated viewerHTTPS, seven methods, all cookies/query/viewer headers, TTL0 at `/api` and `/api/*` plus default/error TTL0, no error SPA conversion. Separate prefix55 originSG, private nginx gate include, qualified DNS/re-resolution, externalHTTPS host, internal/MinIO denial, preserved frontend. Streaming100MiB+1MiB overhead with8API connections/128KiB buffers/16MiB scratch and60s inactivity limits.|OriginHTTP disposition46 remains BLOCKED. CloudFront contains no origin secret and cannot be enabled by this module. Private matched gate injection/current originDNS/propagation/negative ingress, owner cache/cookie isolation, slow uploads/HLS/Range/CORS/decode NOT_RUN. ViewerTLS is not originTLS.|
|62|Bounded offline hook rejects stale/wrong/common-writer proofs, exports both owned DBs plus four roles into private files, checks revisions/lengths/SHA256, publishes manifest after confirmed writes, validates committed retention manifests and keeps latest2 only in exact private backup prefix. Failure blocks all backup/destructive claims and preserves EBS. Private byte verifier and explicit isolated restore plan/CLI supplied.|Common lifecycle proof must come from issue61, not inferred from desiredCounts or health. Real dumps/storage transport and isolated owner/reference/denial restore proof NOT_RUN. OfflinePASS never authorizes backup or teardown. No EBS snapshot/PITR/daemon or live overwrite exists.|

## Checks and retained failure notes

All repo commands used the assigned absolute workdir. Python used
`PYTHONPATH=/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/aws2-infrastructure-state`
and the read-only `.venv/bin/python`; `scripts.aws.__file__` was checked once and
resolved to this worktree. No dependency install/sync or shared init edit occurred.

- Final owned suite: `.venv/bin/python -m pytest -p scripts.dev.pytest_plugin --offline-fast tests/aws/test_config.py tests/aws/test_definitions.py tests/aws/test_definitions_state.py tests/aws/test_exports.py -q`: **102passed**, no skips. Includes fake Linux command paths only; no real mount/Docker/SSM/metadata access.
- Scoped `.venv/bin/ruff check` and `ruff format --check` on the3owned modules/4test files: PASS. Shell `sh -n` on mount/start/capacity scripts: PASS.
- `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.cache/aws-test-tools/bin/cfn-lint deploy/aws/environment.json deploy/aws/generator.json`, version1.57.2: PASS, **zero errors/warnings**, no validate-template/account call.
- Renderer/check-in equality covered by tests. Offline CLI checks for environment/generator/readiness-media and exports plan returned valid JSON; environment90resources, generator2resources.
- Staged `git diff --cached --check`: PASS. Owned JSON/YAML/policy/SG assertions are structural checks, not live policy evaluation or a deployment PASS.

The first cfn-lint invocation returnedW2001 for unused `OriginTransportAccepted`.
Removed that redundant CloudFormation parameter; the disposition stays in shared
config/activation gates and CloudFront stays disabled. Final cfn-lint is clean.
The first combined78-test suite recorded73passed/5failed: all five fake mount
behaviors had the correct exit status, but the additional static assertion matched
`mkfs` in a comment. Fixed the assertion to inspect executable lines; did not
weaken missing/wrong/root/readonly checks. Intermediate90 and92tests passed before
adding five fence/approval/retention negatives. Initial scoped Ruff also reported
line-length/import findings; formatted/fixed them with no ignored rules.

## Shared interfaces and integration dependencies

`CloudConfig.from_dict`, `to_dict`, `load_config(path)` implement the audited fields.
Missing account/resource/approval inputs remain valid plans. Modes are `plan` and
explicit dummy-account loopback `emulator`; real actions always raise. No implicit
profile/SDK/provider fetch exists. Inputs reject private DSNs, tokens, credentials,
cookies, capability query strings and cross-account/region or wildcard SSM ARNs.
Worker cap<=3 and finite60–3600s lifetime are enforced. The14day calendar envelope
uses the original Singapore checkpoint:15October00:00 through29October00:00SG
(UTC14October16:00 through28October16:00), not a new account-receipt clock.

CloudFormation output names: `PublicUrl`, `DistributionId`, `StateInstanceId`,
`StatePrivateIp`, `DataVolumeId`, `Cluster`, `SubnetId`, `OperatorRoleArn`,
`MediaFqdn`, `ProcessingFqdn`; `<Media|Api|Recovery>ServiceName`;
`<Media|Api|Recovery|Worker|MediaMigration|ProcessingMigration>TaskDefinition` and
`SecurityGroup`; `<Source|Output|Backup>BucketName`. Coordinator maps these to the
shared lower-case service/task-definition keys. SSM ARN parameter names and exact
environment injection are in the definitions. Native service credential modes
are `MEDIA_STORAGE_CREDENTIAL_MODE=ecs`, `PROCESSING_STORAGE_CREDENTIAL_MODE=ecs`.
No static credential env injection is added to service tasks.

Worker base command is fixed to `python -m processing.worker --cloud-deadline 0
--name operator-override-required --burst`. No `WorkerCommand` parameter can bypass
the bounded entrypoint. Defaultdeadline0 is fail-closed. Operations launches
count1per request and overrides the absolute epoch deadline and unique
journal-correlated name; optional`--burst` permits bounded normal/prewarm modes.
`WorkerLifetimeSeconds` and shared config have max3600s; its environment field
`DC2_WORKER_LIFETIME_SECONDS` is budget metadata, not a substitute for the mandatory
absolute `--cloud-deadline`. `cloud.py` is a helper, not a moduleCLI. The selected
Processing digest must include the delivery implementation. The coordinator owns
artifact/dependency integration; inherited Dockerfiles are untouched here.

Explicit emulator mode accepts HTTPS loopback origins on random ports with its
dummy account and loopback control endpoint. External emulator origins are rejected;
plan/production inputs stay generatedCloudFront/443. This enables isolated trusted
HTTPS fixtures without introducing production trust bypass or real execution.

`prepare_private_state(config, transport, directory, public_inputs, deadline, clock)`
uses `transport.call(service, operation, payload, deadline=...)`, restricted to
`evidence_kind="offline"`. It requests only `parameter_arns.state_secrets` and
`.origin_gate` with decryption. Dummy SecureString responses exercise the actual
private transformation. Password fixture keys are the five existing PG/admin/
owner passwords plus Redis; future generated private values must be24–128URL-safe
characters and origin gate48–128, avoiding env/nginx quoting ambiguity. Public
inputs include only immutable PG/Redis/nginx images, current private IP, resolver,
qualified MediaFQDN and matching generated viewer host. Directory must be outside
the worktree and700; created files600. Later installation must make them root-owned
and install reviewed root-owned600 `mount.env` with both future disposition flags.
No ordinary output/receipt contains the returned secret values.

`export_state(config, proof, commands, storage, private_directory, deadline, clock,
max_bytes=64MiB)` uses offline adapters only. `commands.dump(owner, deadline,
max_bytes)->bytes`, with owners`media`/`processing`/`roles`, and
`commands.revision(owner, deadline)->revision`; adapters must bound subprocess
output as it is produced, not collect an unbounded dump first.
`storage.put(key, bytes, deadline)->True`, `list_sets(prefix, deadline)->committed
manifest dictionaries`, `delete_set(prefix, deadline)->True`. Lost/false replies
fail closed. Secrets/libpq passwords never appear in command arguments; role SQL
exports only the four existing roles. Private exports must stay outside Git.

The proof dictionary requires `environment_id`, `operator_station`, safe8–64char
`boundary_id`, UTC-aware `issued_at`/`expires_at`, boolean `intake_closed`,
`launches_closed`, `workers_drained`, integer-zero `active_claims`,
`nonterminal_tasks`, `unresolved_launches`, and `writers_quiesced` with exactly
`media_api`, `media_reconciler`, `processing_api`, `processing_recovery`,
`migrations`, allTrue. Freshness<=90s, proof covers the <=300s absolute deadline;
the hook rechecks every phase. All task categories/candidates belong in those
lifecycle counters. No proof of quiescence is fabricated from these dictionaries.

Export manifest includes schema version, boundary/environment/station identity,
creation time, two exact Alembic revisions, all3file lengths/SHA256, bounded total
bytes and private prefix. Even returned offlinePASS has `backup_claim=false`,
`destructive_teardown_allowed=false`, `restore_status=NOT_RUN`, `ebs_deleted=false`.
`verify_private_export` checks modes/hashes/lengths without restoring.
`restore_plan` requires an approved isolated `restore-*` target, private manifest
and ownership/revision/hash checks; actual restore/reference verification and
cleanup remain explicit steps. Failed/partial private sets are preserved for
diagnosis and must not be mistaken for committed latest2 backups.

## Limits and remaining risks

Templates are not permission to apply: EC2 would run if an operator applied them.
SSM managed-key assumptions, regional CloudFront prefix list quota, real IAM action/
condition evaluation, task credential refresh, image packaging, data host pressure,
large-request streaming semantics and browser delivery all need authentic checks.
CloudFront SecureString dynamic references are deliberately absent; no unsupported
dynamic-reference or NoEcho secrecy claim is used. The configured generator's
termination schedule and state/systemd guards have not run on EC2.

Only two business services and owned data/migration roles are preserved. Shared
state/gateway/AZ failure, loss since last export, slow DNS/origin propagation,
retained EBS/S3/ECR/log/DNS charges and Standard-credit throttling remain disclosed.
No realAWS acceptance, full restore, secure-originTLS, billing cap, measured memory
minimum, HA or speedup is inferred from102offline tests. Original local defaults,
frontend/engine/Publisher, roadmap/course documents, worklog/readiness ledgers,
rootMakefile/pyproject/uv.lock and frozen evidence are untouched.
