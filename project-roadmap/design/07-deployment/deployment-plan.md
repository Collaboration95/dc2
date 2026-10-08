# AWS deployment and delivery plan

Prepared 9 October 2026 · design only · runtime results NOT RUN.

## Accepted scope, planned defaults

Documentation only. Baseline 8854537 is selected locally; no upstream or AWS account access is required. All builds, releases, security tests and runtime measurements are NOT RUN.

Accepted proposal: two services, two owned databases/roles/migration histories on one PostgreSQL server, AWS containers, CLI plus existing web, private media, HTTPS, independent automated releases and 1/2/3 workers at 2 vCPU each. The proposal target table remains unchanged.

Recommended plan: one nonburstable x86 EC2 host with at least 8 vCPU, Compose, self-hosted PostgreSQL and Redis/RQ, managed S3, ECR, SSM and CloudWatch. Region ap-southeast-1 is a provisional Singapore assumption; SKU availability, memory sizing, account permission and budget remain unconfirmed.

Website choices and status clicks are personal review aids. They do not approve spending, deployment, or a proposal amendment.

## Physical architecture

Single-AZ demo: one EC2 host in a public subnet with an internet route and one public IPv4 address. Security-group ingress permits only TCP 443; no public SSH, API, PostgreSQL, Redis or administration ports. SSM Agent uses outbound HTTPS. This shared host is a single failure domain.

nginx terminates TLS, serves the inherited frontend and routes /api only to Media Management. Use DNS-01 certificate issuance/renewal with narrowly scoped DNS permission; port 80 stays closed. An ACM-capable ALB/CloudFront edge is an optional priced alternative, not an nginx certificate assumption.

Separate Compose projects/networks and version manifests per service: MM plus its submission/cleanup reconciler; Processing API, workers and recovery task. MM, the Processing API and source-fetching Processing workers join the private interservice bridge so workers can call MM source-access directly. Workers expose no public listener. Both service data paths reach the same PostgreSQL listener; networks cannot isolate logical databases there. Own roles/grants enforce logical database separation; Redis is Processing-only.

S3 source/output objects are private, encrypted and blocked from public access. Their HTTPS endpoints are internet reachable; authorised presigned GETs use those endpoints. This is object-access privacy, not a private-only network. Durable PostgreSQL/Redis volumes use encrypted EBS; FFmpeg scratch is disposable.

## Workload credentials and residual risk

Recommended demo compromise, requiring team confirmation: three restricted S3 workload credentials in SSM SecureString, injected by trusted host bootstrap into separate root-owned service files outside git/images. Mount only the matching secret read-only; no Docker socket, privileged container or host network. Host instance role has SSM, exact ECR pull/log and parameter-decryption permissions, but no S3 or AssumeRole workload permissions.

MM, worker and Processing cleanup receive separate secret mounts. A worker uses its local digest and successful upload/checksum acknowledgement to validate publication. If the storage adapter needs HeadObject/Get for remote verification, design a narrower verifier role and review the extra credential before implementation; do not silently give workers read/delete rights or call them write-only.

Block all container access to IMDS IPv4/IPv6 with host forwarding rules; require IMDSv2 for host use. Verify this from every container; hop limit alone is not the isolation proof. Host administrators and host compromise can still read all workload secrets. Separate files do not create a hard security boundary.

Rotate restricted demo keys before demonstrations and after exposure; revoke/delete them and their injected copies at teardown. No IAM console/password or account-wide S3 permissions. These are temporary demonstration credentials, not a full rotation platform.

Short-lived STS service credentials are the stronger credential default, but Compose needs a trusted broker that assumes separate roles, refreshes credentials before expiry, safely injects them and survives refresh failures. Giving the shared host both AssumeRole privileges does not isolate containers unless IMDS is blocked and the broker is protected. This added lifecycle is deferred for the demo.

If strict workload isolation is required, choose separate Fargate tasks with distinct task IAM roles; execution roles handle image pull/log delivery. Do not place MM and Processing in the same task. Budget and additional environment work must be confirmed.

| Principal | Allowed scope | Boundary |
| --- | --- | --- |
| MM S3 principal | Source Get/Put/Delete within owned source prefixes; output Get only | Can sign source and output reads; cannot write/delete outputs |
| Worker S3 principal | Output PutObject only under owned attempt prefixes; minimal multipart permissions if needed | No source, Get/Head, List or Delete. Validate upload response/checksum and local digest before publishing; no claim of remote HeadObject verification. |
| Processing cleanup S3 principal | Output prefix-scoped ListBucket and DeleteObject only | Separate cleanup/recovery mount, never worker mount; no source access. |
| Runtime database roles | media_runtime → media_db; processing_runtime → processing_db | Revoke PUBLIC CONNECT/TEMP and schema defaults; no cross-role membership |
| Migration credentials | Separate owner credentials, mounted only for one-off own-service migration | Never mount in runtime API/workers |
| Service tokens | Different MM→P and P→MM tokens, separate mounts | Owner checks stay mandatory; never log tokens or signed URL queries |

## Fair worker capacity and persistence

Reserve 6 vCPU for the three 2-vCPU workers and at least 2 vCPU headroom for APIs, database, queue, nginx and recovery. CPU quota is not reservation: assign worker cpusets/host controls so they cannot consume the headroom; verify effective cgroup limits and actual CPU contention before experiments. Record x86 architecture, SMT topology, memory, disk I/O and FFmpeg settings; 8 vCPU is a minimum, not a performance guarantee.

Keep the same host, fixture hashes, CPU/memory limits and encoder settings for the 1/2/3-worker comparison. Measure and tune scratch/memory limits before final tests; do not compare burst-credit or architecture changes. No SKU or regional capacity is asserted.

PostgreSQL owns durable state; RQ is delivery, not authority. Redis persistence helps restart recovery but the step-06 reconcilers must repair missing queue entries from committed attempts. Back up both databases and retain source/output objects with documented lifecycle rules. A backup restore is planned and NOT RUN; host failure may lose recent writes since the last backup.

Processing-only deployment drains/quiesces new claims, gives active work a bounded finish interval, then relies on step-06 leases/attempt fencing for interruptions. Durable winning outputs survive image rollback. Changing worker count must not restart MM.

Step-06 alignment: fence completion with the current attempt ID, without an extra nonce. Durable pending submission continues with bounded tick/backoff; alert at 5 minutes and escalate at 30 minutes. No new pause/resume operator command is introduced.

## Automated per-service releases

Planned triggers: every PR gets lint, unit/frontend, integration, contract and boundary checks without deployment credentials. A reviewed merge builds/scans changed-service images; shared-contract changes test both. Pin action/tool versions, retain reports, publish version plus commit and immutable digest to separate ECR repositories.

Mandatory blockers: failed tests; exposed secrets; fixable HIGH/CRITICAL image findings. The inherited known fixable HIGH finding must be resolved and a clean scan attached before release; no resolution is claimed here. Sonar currently skips without configuration and continues on findings; ZAP findings are report-only while scan execution errors fail.

Recommended explicit triage policy: configure and retain Sonar/ZAP reports, block promotion for untriaged findings and confirmed high-risk boundary flaws; every remaining finding gets owner, disposition, rationale and due date. A skipped required scan needs an explicit recorded exception. This is a proposed promotion policy, not an existing gate.

Recommended manual promotion gate authorises the exact candidate digest in the deployment environment. After promotion, OIDC obtains a short-lived deployment role and SSM runs the bounded release routine automatically: pull digest, own migration, service replacement, readiness and CLI smoke. Manual promotion does not mean manual deployment.

OIDC trust must pin audience sts.amazonaws.com and the actual team repository/environment subject once D-02 is resolved. Separate build/push and deploy roles. Scope deployment to the tagged demo host and approved SSM document; no arbitrary shell/document execution, S3 workload access or bootstrap admin permissions. Serialize deployments on the shared host.

Record service/commit/digest, migration revision, start/end timestamps, MM digest before/after and checks. Measure UC-7 against the unchanged ≤10-minute target; start the clock at the first automated release action AFTER promotion approval and gated artifact readiness, BEFORE OIDC/SSM dispatch, pull or migration; stop at smoke pass. Exclude manual-gate wait and report it separately; include any automation queue wait after that start. No measured time exists.

## Release and rollback runbook

- Preflight: identify changed service, previous digest and own schema revision; verify all gates/reports and backward compatibility with the still-running peer. Snapshot/backup own database before a risky migration.
- Expand first: apply additive own-service migration using its migration credential. Never run media_db migrations for a Processing-only release. Defer destructive contraction until the rollback window closes; prove old image works with new schema.
- Deploy via SSM: validate an allowlisted digest, pull it, stop new claims if Processing, drain bounded active jobs, replace only that project’s API/worker/recovery containers. Preserve volumes and record transition events.
- Readiness then smoke: test internal authenticated/owner-filtered boundary, register/login with HTTPS CLI cookie jar, upload a fresh fixture with stable key, poll to completion, retrieve authorised MP4 and HLS when available, retry/list/delete compatibility and verify cross-owner denial. Capture redacted logs and clean the demo asset.
- On failure: prevent promotion success, revert only changed-service image digests, restart its dependents and repeat readiness/smoke. Keep additive schema; do not blindly downgrade migrations or restore the shared server. A non-backward-compatible migration requires a tested restore/forward-fix plan and explicit interruption decision.
- Capture failures honestly: smoke timeout, job failure, readiness failure and rollback outcome are separate evidence. Stop further releases if recovery fails; do not write successful deployment evidence from a website status.

## Local/cloud configuration and secret inventory

| Concern | Planned local / cloud setting | Rule |
| --- | --- | --- |
| Local HTTPS / cloud HTTPS | Trusted development CA / DNS-01 certificate on nginx | Keep Secure HttpOnly session cookie and CLI HTTPS cookie jar; do not disable TLS verification |
| Public and internal origins | Local TLS host / confirmed cloud DNS; private MM/P service names | Only /api public; configured storage-origin allowlist rejects arbitrary source URLs/redirects |
| Object stores | Source-built MinIO, two stores/three principals / two private S3 buckets | Separate source/output endpoints, signing region, path-style setting and read/write privileges |
| DB and queue | Own database DSNs, separate migration DSNs; Processing Redis URL | Distinct mounts; same schema ownership locally/cloud; no CLI DB credentials |
| Identity and service secrets | MM JWT signing key; two directional service tokens; three scoped S3 keys (MM / worker / cleanup) | SSM SecureString in cloud; ignored permission-limited files locally; injected only where needed |
| Release configuration | Per-service digest, migration revision, worker count, limits, recovery policy | Nonsecret version manifest; record configuration hash excluding secret values |
| Management | Host SSM role, CI OIDC build/deploy roles, CloudWatch retention | No static AWS deployment key in CI; logs redact user data, cookies and URL queries |

## Reproducible local build preparation

Reuse the existing pinned-source MinIO recipe at Media_player/deploy/dast/minio.Dockerfile (release RELEASE.2024-06-13T22-53-53Z; expected commit 20960b6a2ddb9594ee418035b3c7c7fe92ae6a12). CI already references this recipe; the inherited Compose image has a documented fresh-pull problem. No build or pull was attempted.

During implementation, use an explicit local override referencing the built image digest; build/reuse the same pinned recipe in CI. GitHub source retrieval must use authenticated gh exclusively: adapt the recipe’s current git-fetch step to consume a gh-fetched archive or an authenticated gh-staged checkout, verify its revision/hash and retain source provenance. Do not execute the inherited network-fetch recipe unchanged under this project rule.

The source-built image contains the server, not the mc client expected by inherited Compose health checks. Use its HTTP /minio/health/live endpoint with a provided probe; readiness must also exercise authenticated bucket access. Verify a fresh-volume boot, three restricted storage principals, upload-to-playback, DB role denial and restart recovery before claiming reproducibility.

Use a trusted local TLS certificate and HTTPS frontend/CLI. Signed source URLs must resolve inside workers; playback URLs must resolve in browser/CLI. Use configured hostnames or split DNS and correct endpoint signing; an internal minio hostname alone is not a browser playback endpoint. Match cloud origin allowlists and secure-cookie behavior. All these checks remain NOT RUN.

## Infrastructure bootstrap plan — no execution

- Confirm account owner, region, service permissions/quotas, spend cap and teardown date. Check nonburstable x86 ≥8-vCPU availability and memory/disk sizing; create fresh demonstration data only.
- Plan VPC/subnet/route/security group, encrypted EBS and OS patching. Permit ingress 443 only; install trusted container runtime, Compose and SSM Agent; validate outbound SSM/ECR/S3/CloudWatch/DNS connectivity.
- Create private encrypted source/output stores, three scoped demo workload credentials, SecureString parameters, ECR repositories and bounded CloudWatch retention. Plan backups and redacted audit records; lock IMDS away from containers.
- Bootstrap two databases and runtime/migration roles with negative cross-database grants tests; initialize Processing Redis and own-service volumes/networks. Keep bootstrap admin credentials away from application containers.
- Confirm DNS ownership and DNS-01 renewal automation; configure nginx HTTPS and service-only routing. Establish host-side release routine and restricted OIDC/SSM authorization after the team remote is chosen.
- Run planned readiness, storage-role, IMDS-denial, port, backup-restore and local/cloud smoke checks before measuring. Record failures and costs. Teardown revokes keys, removes resources/retained IPv4 and checks remaining storage/log charges.

## Cost model, not a live quote

Planning date: 9 October 2026; provisional region ap-southeast-1; USD; Linux On-Demand; example 80 running hours in a 730-hour month. No free-tier/credit assumption, tax or approved budget. Account spending hard cap is unknown; alerts are notifications, not a hard cap.

C = h × compute_rate + retained_IP_hours × 0.005 + EBS_GB_month × EBS_rate + snapshot_GB_month × snapshot_rate + source/output_GB_month × S3_rate + PUT/GET_volume × request_rates + internet_egress_GB × egress_rate + ECR_GB_month × registry_rate + logs_ingested/stored × log_rates + metrics/alarms + DNS/certificate/parameter/KMS charges where applicable. Include transfer-path charges and cleanup retention; stopping compute leaves storage and possibly IP charges.

Illustrative allowance only: suppose compute is $0.50/hour (invented planning input, not an EC2 price). 80 hours gives $40; one IPv4 retained all 730 hours gives $3.65 at the published rate; assume $25 combined storage/requests/egress/registry/log/DNS contingency → $68.65. The same invented rate at 730 compute hours gives $393.65. This is neither a quote nor a proposed approved cap; replace every assumption with official regional pricing and workload volumes before cloud approval.

Managed alternative adds Fargate vCPU/memory-hours, one RDS PostgreSQL server, managed Redis, ALB and outbound NAT or private-endpoint charges; it reduces host/credential operations but may cost more and needs more setup. Compare exact same worker quotas and uptime. No exact SKU, instance price or regional availability is claimed.

## Team decisions for cloud; documentation ready for local build

Cloud decisions required: account/owner and permissions; actual region/SKU capacity; memory/disk sizing; spend cap and hours/retention/teardown; DNS and certificate operator; accepted shared-host credential risk or Fargate; restricted-key rotation owner; team repository/OIDC subject; promotion reviewers and Sonar/ZAP triage policy.

Accepted proposal decisions need no new scope approval: two services/databases, AWS containers, CLI/web compatibility, security/recovery/scaling targets and separate releases. RDS may replace the shared server host while retaining one server/two databases; multiple DB servers or a non-AWS provider need a recorded scope amendment.

These documents are ready to guide the local implementation/build phase. Cloud confirmations do not prevent preparing the first local workflow. Actual local build, security/recovery behavior and cloud bootstrap remain NOT RUN; reconcile step-06 timing rules before implementation and hand release evidence definitions to step 08. Review the step-06 recovery/source-access compatibility diagram at project-roadmap/design/06-security-recovery/diagram-manifest.json (shared-board page:team17-recovery).

## Source notes

Proposal/contract statements follow [1–4]; inherited setup and gate observations follow [5–9]. AWS capability references [10–17] support the proposed architecture; pricing references [18–23] are inputs to future estimates, not measured costs.

[1] [project-documentation/Team17-Proposal.docx](../../../project-documentation/Team17-Proposal.docx) — AD-02, AD-05–07; §§2.5, 3.3–3.5, 4.1. Accepted scope; targets unchanged. Read via /tmp/team17-review/Team17-Proposal.txt.
[2] [project-roadmap/records/project-decisions.txt](../../../project-roadmap/records/project-decisions.txt) — F-01, D-01, D-02. Proposal accepted; local baseline 8854537; future team remote unspecified.
[3] [project-roadmap/design/05-contracts/content.json](../../../project-roadmap/design/05-contracts/content.json) — storage, privileges, public-routes, transactions. Design contracts; not implemented evidence.
[4] [project-roadmap/roadmap-data.json](../../../project-roadmap/roadmap-data.json) — steps 06–08. Recovery dependency, deployment outputs and evidence handoff.
[5] [Media_player/docker-compose.yml](../../../Media_player/docker-compose.yml) — minio service comment and ports. Inherited image pull problem is documented, not freshly reproduced.
[6] [Media_player/deploy/dast/minio.Dockerfile](../../../Media_player/deploy/dast/minio.Dockerfile) — MINIO_VERSION, MINIO_COMMIT, base-image digests. Existing CI source-build recipe; no build run here.
[7] [Media_player/.github/workflows/ci.yml](../../../Media_player/.github/workflows/ci.yml) — sast, integration, image scan. Sonar optional/continue-on-error; Trivy gates fixable HIGH/CRITICAL.
[8] [Media_player/.github/workflows/dast.yml](../../../Media_player/.github/workflows/dast.yml) — authenticated scan exit-code handling. ZAP findings report-only; execution errors fail.
[9] [Media_player/app/api/auth.py](../../../Media_player/app/api/auth.py) — _set_cookie. Secure HttpOnly SameSite=Strict cookie; local HTTPS required.
[10] [https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html) — Important; task vs execution role. Task IAM and Fargate isolation; EC2 shared-host limitation. Official AWS source checked 9 October 2026.
[11] [https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html) — Configuring a role for GitHub OIDC identity provider. Restrict audience and subject to the eventual team repository/environment. Official AWS source checked 9 October 2026.
[12] [https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html](https://docs.aws.amazon.com/systems-manager/latest/userguide/running-commands.html) — Run Command. Host management over Systems Manager; avoid secrets in command text. Official AWS source checked 9 October 2026.
[13] [https://docs.aws.amazon.com/systems-manager/latest/userguide/ssm-agent.html](https://docs.aws.amazon.com/systems-manager/latest/userguide/ssm-agent.html) — Working with SSM Agent. Agent on managed node; plan outbound service connectivity. Official AWS source checked 9 October 2026.
[14] [https://docs.aws.amazon.com/systems-manager/latest/userguide/secure-string-parameter-kms-encryption.html](https://docs.aws.amazon.com/systems-manager/latest/userguide/secure-string-parameter-kms-encryption.html) — SecureString encryption. Encrypted secret storage; runtime injection remains our responsibility. Official AWS source checked 9 October 2026.
[15] [https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html) — Block Public Access. Private objects; public HTTPS endpoint does not imply anonymous access. Official AWS source checked 9 October 2026.
[16] [https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html) — Presigned URLs. Time-limited capability constrained by signing credentials. Official AWS source checked 9 October 2026.
[17] [https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html](https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html) — Immutable tags. Protect release tags; deployment selects exact digest. Official AWS source checked 9 October 2026.
[18] [https://aws.amazon.com/ec2/pricing/on-demand/](https://aws.amazon.com/ec2/pricing/on-demand/) — On-Demand pricing. No regional compute quote extracted. Official AWS source checked 9 October 2026.
[19] [https://aws.amazon.com/ebs/pricing/](https://aws.amazon.com/ebs/pricing/) — Storage and snapshots. Use current regional rates before cloud approval. Official AWS source checked 9 October 2026.
[20] [https://aws.amazon.com/vpc/pricing/](https://aws.amazon.com/vpc/pricing/) — Public IPv4 Address. Published USD 0.005 per address-hour, checked 9 October 2026. Official AWS source checked 9 October 2026.
[21] [https://aws.amazon.com/s3/pricing/](https://aws.amazon.com/s3/pricing/) — Storage, requests, transfer. Include source/output bytes, request volume and internet egress. Official AWS source checked 9 October 2026.
[22] [https://aws.amazon.com/ecr/pricing/](https://aws.amazon.com/ecr/pricing/) — Storage and transfer. Include retained image bytes and transfer. Official AWS source checked 9 October 2026.
[23] [https://aws.amazon.com/cloudwatch/pricing/](https://aws.amazon.com/cloudwatch/pricing/) — Logs and metrics. Include ingestion, retention and alarms. Official AWS source checked 9 October 2026.
[24] [project-roadmap/design/06-security-recovery/content.json](../../../project-roadmap/design/06-security-recovery/content.json) — source access, worker output writes and separate Processing cleanup authority. Step-06 integration dependency: preserve worker→MM source-access reachability and review its trust diagram. Design only; runtime compatibility NOT RUN.
[25] [project-roadmap/design/06-security-recovery/diagram-manifest.json](../../../project-roadmap/design/06-security-recovery/diagram-manifest.json) — recovery.mmd / page:team17-recovery. Editable recovery/source-access integration reference; step-07 workers share the private MM bridge.
