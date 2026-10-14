# Preparation interfaces and bundle boundaries

Source intent: audited readiness contracts plus the user’s15October preparation-only goal. Small helpers, plain dict/dataclass values, existing service SDKs. No shared business settings/models or generic infrastructure framework. All compatibility choices remain reviewable; unresolved inputs fail closed rather than fabricating approval.

## Shared configuration — infrastructure/state bundle

`scripts.aws.config` owns `CloudConfig` and `load_config(path)` (JSON, nonsecret). Provide a `from_dict` constructor and `to_dict`; use string/dict fields so planned tools can share explicit fixtures. Required fields: `mode` (`plan` or `emulator`, future real execution independently gated), `region`, `account_id`, `environment_id`, `public_url`, `source_bucket`, `output_bucket`, `operator_station`. Further fields: `endpoint_url`, `cluster`, `services` (keys`media`, `processing_api`, `processing_recovery`), `task_definitions` (keys`worker`, `media_migration`, `processing_migration` plus API/recovery families), `network` (`subnets`, `security_groups`, `assign_public_ip`), `state_instance_id`, `cloudfront_distribution_id`, `image_digests`, `parameter_arns`, `session_end_utc`, `max_worker_tasks` (≤3), `worker_lifetime_seconds`, `origin_transport_accepted` (defaultfalse), and a nonsecret `approval` record. Empty/unapproved deployment inputs can render plans, never execute real operations.

Config validation must reject embedded credentials/DSNs/signatures/cookies and arbitrary emulator endpoints. Emulator mode accepts loopback only with dummy identities; no implicit local profile or task credential discovery for emulator control-plane calls. Do not resolve a requirement-owner TLS decision in code; the HTTP-origin variant remains explicitly gated. Real-cloud actions are excluded from this run.

Credential settings used in both service task definitions: `MEDIA_STORAGE_CREDENTIAL_MODE=ecs`, `PROCESSING_STORAGE_CREDENTIAL_MODE=ecs`. Service implementations choose `static` default with existing local MinIO fields. Use native container provider only in explicit ECS mode, with no static constructor override or fallback identity. Media snapshot signing/expiry belongs to the storage bundle. Agree any changed name in the bundle report for coordinator integration before deployment definitions are treated as verified.

## Control plane — delivery/operations bundle

An injectable transport interface `call(service, operation, payload, *, deadline=None) -> dict` represents control-plane requests. Fake transport tests drive all lifecycle states. A production AWS CLI command planner may be built for later use, but this cycle must never execute real AWS. Emulator execution requires explicit loopback endpoint plus dummy credentials/config/metadata disable; no implicit real credentials, AWS profile or fallback endpoint. Do not add boto3 to application images. CLI subprocess deadlines are absolute/finite; redact failures and journal selected fields only.

All manual, smoke and release worker launch paths use one designated station/interlock/private journal. Count all nonterminal workers plus unresolved requests before cap≤3. `RunTask` token/request/reservation exists before mutation; pagination, partial results, lost responses and restart are covered. Fixed test non-burst prewarm is allowed only with finite lifetime. A private operator journal is sufficient; no default controller/launch DB table.

Provide worker start/inventory/drain, owner migration/promote/restore and environment open/close operations accepting config+transport. Use task/RQ identity, a cloud-only finite wrapper, one warm shutdown before StopTask, captured/last claim terminal outcomes, and all-task shutdown accounting. State/recovery remain available until outcomes/quiescence. Release owner selection never changes peer tasks/schema. All default counts after smoke/rollback are zero; migration/generator/candidate/restore work is included.

## Client/evidence — storage/evidence bundle

`scripts.aws.context`, `smoke`, `evidence`, `protocols`, `latency`, `cost` own explicit HTTPS API context, normal trust, isolated capability downloader, selected-field artifact safety and runnable preparation protocols. Preserve signed query bytes and prevent API cookies/tokens reaching object hosts. Public production API and regional bucket HTTPS hosts are explicit; local test contexts require explicit loopback/CA fixtures and never become production trust defaults. Existing frontend/Publisher remain unchanged unless a proven compatibility defect requires a focused fix.

Evidence methods accept plain records/dicts and private artifacts, not whole AWS responses/directories. Schema distinguishes `offline`, `emulator`, `local-services`, `aws` and PASS/FAIL/NOT_RUN. No emulator outcome becomes an AWS PASS. Source/digest/task/fixture IDs, limits, exact commands, hashes and failures are selected; no signed URLs, DSNs, cookies, auth headers, SSM values or private exports are published.

Capacity/recovery/release/latency/cost-closeout issues63–67 receive runnable protocols, offline validation and local checks in this cycle; their original genuine-cloud acceptance is never asserted from those tests. Six long uploads reserved for actual prewarmed1/2/3capacity later; current local validation uses short fixtures and no bulk replay.

## State exports — infrastructure/state bundle

Export/restore accepts an explicit quiescence proof supplied by the lifecycle operation and injectable bounded command/storage boundaries. Stop intake/launches, drain and then quiesce all owner/reconciler/recovery writers before both DBs/roles are exported under one private hash/schema manifest. Failed export blocks backup/destructive-teardown claims and never deletes EBS. No snapshots/PITR/newbackup daemon. Test missing mounts, failed export, stale/nonquiescent proof and private-prefix permission. Actual restore proof is separate from a tested export plan.

## Integration ownership

Coordinator alone owns root Makefile/dependency/test-tier integration, shared documentation/issue ledgers, all GitHub operations and Docker/emulator/browser runtimes. Children own only their assigned modules/tests and their bundle report. No inherited local/frozen namespace is stopped/pruned or rewritten. No cloud actions are permitted by the integration branch or by issue closure.
