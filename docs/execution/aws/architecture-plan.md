# dc2 AWS architecture and preparation plan

Prepared 14 October 2026 (Singapore). **Planning only; no resources, account access or live workload performed.** Read-only repository inspection plus unauthenticated public AWS documentation/price-list downloads. Astra produced the original design and cost worksheet; the coordinator is reviewing and integrating them. This plan is not a deployment approval.

## Decision

Use **one Linux On-Demand `c6a.2xlarge` EC2 host (8 vCPU, 16 GiB), Docker Compose, two private S3 buckets, and public HTTPS through nginx**, provisionally in `ap-southeast-1`. Keep PostgreSQL and Redis on encrypted EBS. Use a stable Elastic IP and an existing domain/subdomain. Prefer two private ECR repositories for immutable Media/Processing images; static frontend/configuration travel as a versioned release artifact.

Approve **100 host-hours planned, 120 maximum across 21 days**, with the host stopped between booked sessions. Current official Singapore compute rate is **$0.3528/hour**. The conservative 120-hour envelope is **$169.47 total**, including storage, snapshots, requests, 200 GB internet egress, a separate temporary load generator, registry, domain allowance, tax/FX reserve and contingency. Continuous 504-hour operation is **$304.95 with the same envelope** and is rejected. These are bounded estimates, not a guaranteed bill or permission to provision.

Do not add Kubernetes, autoscaling, OIDC, a credential broker, RDS, ElastiCache, ALB, NAT Gateway or CloudFront. Two independently released business services can share a host; host/AZ high availability is not claimed. A stopped host is intentionally unavailable. Existing course/proposal documents, roadmap design and historical evidence remain unchanged. Do not operate Alibaba.

## Evidence and pending decisions

The task's accepted source is Main `b913579` (PR37). Root AGENTS, the full worklog, execution handoff/plan/decisions/interfaces, active Compose, Media/Processing storage/settings, Publisher and release/evidence code were inspected. Worklog/handoff retain older checkpoints; the task's newer accepted context supersedes their pending-status language.

- Original pre-AWS delivery: 18 stories/six epics, V1–V5 accepted. Historical scaling at `f46599f`: 270/270 MP4/HLS successes; 2.337/4.749/6.743 jobs/min, 2.032×/2.885× speedup, queue medians 375/176/120 s. Separate status p90 605/580/544 ms; login 1.873/1.888/1.899 s. Those are local results on the same Mac as the generator, not cloud proof.
- Recovery: worker failure visible 69.2 s; queue-entry repair 23.5 s **with surviving metadata**. Historical release: good 101.2 s, active drain 34.1 s, injected bad startup plus automatic exact-image restoration 125.6 s. Shared-host failure and complete Redis loss need their own evidence.
- PR37: 1,107 Python tests, all 15 PR/all 14 Main checks and fresh review passed per parent context. Login releases its SQL connection before bcrypt; output hashing removes one file pass; Publisher hashing allocation falls ~2.1 MB→0.27 MB. End-to-end gain remains unmeasured; older demo images were not rebuilt. Sonar job success did **not** mean completed analysis. Historical login results do not cover existing cost-12 accounts or direct measured image/account hash provenance.
- Both local experimental follow-ups are now complete with **REJECT** decisions. No quota or worker-policy default is adopted. See [#38 disposition](../experiments-20261014/EXP38.md), [#39 disposition](../experiments-20261014/EXP39.md), and their indexed raw evidence. Coordinator integration preserves measured commits `08ec06c` (#38) and `60f244c` (#39); the local result pack is committed at `f7e039b`. [Fresh independent review](../reviews/experiments-20261014-review.md) PASS at `632cac5`, no substantive findings. Exact PR/Main checks and accepted publication remain coordinator-owned and are recorded in GitHub.
- #38 completed three rotated pairs and 180/180 fresh long-job successes. PostgreSQL `.125→.25` CPU (Processing API `.5→.375`) reduced isolated status p90 to 252–264ms, with supporting throttle/SQL evidence. Every isolated login arm exceeded 2s and mixed status was 2.60–2.84s, so the complete-workload gates fail; baseline quotas remain. Preparation-only 401s remain unexplained and are retained. These opt-in diagnostic workloads do not replace the original accepted measurements.
- #39 completed 48 eligible windows and 504/504 scheduled successes at baseline quotas. Advance-planned manual worker windows reduced residency by 13.28/14.80/14.58%, below the predeclared 20% threshold; sustained status latency also failed. No manual/reactive controller or policy is adopted. Queue-age, short-wait and safe-drain bounds passed. The disk stop, excluded work and full-arm continuation remain explicit.
- Repeated worker loss, queue-list loss, full Redis reconstruction and durable backlog restart passed. A real 180s source processed for 70.823s and safely drained for 70.589s without a forced kill. Processing promotion passed in 118.568s; bad-candidate exact-image restoration in 145.357s; active rollback in 72.669s, with Media unchanged. These are local namespace proofs, not cloud-host availability or billing evidence.
- The original nine-container demo was restored on its exact saved `f10bf04` images at `https://localhost:54440`, with public workflow smoke. Experiment namespaces were stopped and historical volumes/evidence preserved. Restoration does not claim that the demo was rebuilt to PR37.

**Configuration for the AWS job:** keep the baseline per-service quotas and explicitly selected fixed 1/2/3 workers. Neither experiment supports adopting its candidate. Lower worker count on a running EC2 host still provides no hourly-bill saving. Whole-host stop/restart and availability must be validated separately in AWS.

Measured local cost inputs, with exact scopes: each 60s input is 21,050,412 bytes; output is 60,959,567 bytes in 29 objects, including all HLS playlists/renditions/segments. Each 2s output is 1,921,301 bytes in eight objects. The 504 eligible scheduled jobs produced 22,222,111,464 bytes in 11,592 objects. Three decoded 60s playback **starts** transferred 5,174,856 / 4,158,152 / 4,158,152 bytes over 13/12/12 recorded browser requests. They do not measure entire viewing sessions or every internal S3/multipart request. The cost worksheet retains conservative usage ceilings; fresh cloud smoke must measure actual x86 output/request/viewing volume.

## Topology, capacity and storage access

```text
Browser + independent Publisher -- HTTPS --> nginx:443 (frontend + /api)
                                               |
                                           Media API
                                      /        |         \
                             media_db    private HTTP    S3 sources + output reads
                                             |
                                       Processing API
                                      /       |       \
                            processing_db   Redis/RQ   workers (1/2/3)
                                                        |       |
                                reverse Media source grant     S3 output PUT

Media reconciliation and Processing recovery are commands of their own service.
Processing recovery owns output List/Delete. PostgreSQL hosts two separate DBs.
All application containers are on ONE EC2 host; S3 is outside that failure domain.
```

One project VPC/public subnet/Internet Gateway, one host security group. Public ingress 443; port 80 only ACME HTTP-01/HTTPS redirect. SSH 22 only from the approved operator CIDR. No public PostgreSQL, Redis, Processing or Docker API ports. Keep container data networks private; attach **only S3-using Media, worker and recovery containers** to an outbound-capable Docker bridge. Current worker/recovery networks are all `internal: true`, so changing endpoints alone will not work. An ordinary public-subnet host supplies egress without a paid NAT Gateway. A free S3 gateway endpoint is optional, not required; do not impose a bucket `aws:SourceVpce` restriction that breaks external presigned playback. [AWS VPC pricing](https://aws.amazon.com/vpc/pricing/).

Use Ubuntu LTS x86_64 without a paid AMI/software subscription. c6a has sustained CPU capacity without T-family CPU credits. Its 8 vCPU are not equivalent to eight Apple physical cores; benchmark again. [C6a specifications](https://aws.amazon.com/ec2/instance-types/c6a/), [regional availability](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-regions.html).

Baseline persistent nonworkers locally total **2 CPU / 2,304 MiB**; each worker stays **2 CPU / 1,536 MiB**, making 4/6/8 CPU and up to 6,912 MiB configured ceilings. Removing MinIO for AWS removes 0.125 CPU/512 MiB: remaining nonworkers total **1.875 CPU / 1,792 MiB**, three-worker ceiling **7.875 CPU / 6,400 MiB**. Preserve the remaining baseline quotas unless #38 supports a reviewed change; record this AWS topology difference. These are ceilings, not reservations. Startup, migrations, OS, Docker and release tools still consume resources. Do not build/scan/run generators alongside timed three-worker batches; collect host and cgroup pressure/throttling. If CPU contention invalidates fairness, retain the failure and reprice a larger host before rerunning; do not weaken targets or claim an eight-core reservation. Routine demos may use one/two workers. 16 GiB gives working headroom; historical sampled RSS does not justify downsizing.

EBS: **32 GiB root + 96 GiB data**, gp3 default performance, encryption with the AWS-managed EBS key. Mount data at `/srv/dc2` by UUID and require it before startup. Bind PostgreSQL, Redis AOF, private release journal/config, backups and Docker data to known persistent locations; allocate worker temporary disk explicitly. Do not place worker temp files in a memory-backed tmpfs by default. Check free space before batches; refuse new work below 20% free. No paid extra IOPS/throughput. Snapshot allowance is **128 GiB of billed snapshot data total**, including incremental changed blocks—not 128 GiB per snapshot. Retain only the last useful recovery points within that allowance.

Private S3 Standard buckets: unique lowercase names without dots, e.g. `dc2-team17-<account>-<suffix>-sources` and `...-outputs`, same region as EC2. Enable Block Public Access, bucket-owner-enforced ownership (ACLs disabled), SSE-S3 and deny non-TLS access. No S3 website endpoint, public policy, custom KMS key, versioning or automatic media expiry by default. Add incomplete multipart abort lifecycle after one day; complete objects are deleted through ownership/recovery or final teardown. [Object ownership](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ensure-object-ownership.html), [encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/default-bucket-encryption.html).

### Service credentials without a new identity platform

Use three dedicated, non-console IAM principals with project-bucket-only policies and one active access key each, fitting the existing explicit access-key/secret settings. This is a limited three-week demo choice; delete keys at teardown. The account owner must permit this mechanism. If account policy forbids keys, return that concrete constraint for a small credential-provider change; never fall back to a shared administrator key. No broad S3 instance role accessible to all containers. Operator provisioning/ECR credentials stay separate and are never passed into application containers.

| Principal | Bucket permissions | Object permissions |
|---|---|---|
| Media (API + Media recovery) | source `ListBucket`; `GetBucketLocation` for both buckets if needed | source `GetObject`, `PutObject`, `DeleteObject`, `AbortMultipartUpload`, `ListMultipartUploadParts`; output `GetObject` only |
| Processing worker | none for source; explicit configured region avoids discovery | output `PutObject`, `AbortMultipartUpload`, `ListMultipartUploadParts` only |
| Processing recovery | output `ListBucket` | output `DeleteObject` only |

Scope bucket actions to bucket ARNs and object actions to `bucket/*`. No wildcard account-wide policy. Source multipart permissions are needed for ordinary larger uploads even though the local bootstrap's Media policy lists only basic Get/Put/Delete. Worker must fail unsigned source Get and output Get/HEAD/List/Delete; cleanup must fail source access and output Get/Put; Media must fail output Put/Delete. Test positive multipart completion/abort and actual negative permissions, not policy text alone. [S3 operation/permission mapping](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html).

Keep private runtime configuration under `/etc/dc2` (directory 0700/files 0600); pass only each service's explicit variables as Compose already does. Protect copied credentials and backups; never print `docker compose config`, environment dumps, passwords, cookie jars or full signed URLs into evidence. No secrets in Git, image layers, user-data, CI logs or the deliverable.

### Endpoint, HLS, CORS and TLS configuration

The current MinIO Python SDK already constructs S3-compatible requests; first attempt a configuration-only S3 transition and prove it with real S3 tests. Do not pre-emptively rewrite storage. Keep the existing `MINIO` setting names for this demo:

```text
MEDIA_PUBLIC_URL=https://<approved-demo-hostname>
MEDIA_PROCESSING_URL=http://processing:8000
PROCESSING_MEDIA_URL=http://media:8000
MEDIA_MINIO_ENDPOINT=s3.ap-southeast-1.amazonaws.com
MEDIA_MINIO_PUBLIC_ENDPOINT=s3.ap-southeast-1.amazonaws.com
PROCESSING_MINIO_ENDPOINT=s3.ap-southeast-1.amazonaws.com
MEDIA_MINIO_USE_SSL=true
MEDIA_MINIO_PUBLIC_USE_SSL=true
PROCESSING_MINIO_USE_SSL=true
MEDIA_MINIO_REGION=ap-southeast-1
PROCESSING_MINIO_REGION=ap-southeast-1
MEDIA_MINIO_SOURCE_BUCKET=<private-source-bucket>
MEDIA_MINIO_OUTPUT_BUCKET=<private-output-bucket>
PROCESSING_MINIO_OUTPUT_BUCKET=<private-output-bucket>
# Existing DSNs, forward/reverse tokens and three scoped key pairs: private input.
# PROCESSING_MINIO_* credentials in recovery must come from CLEANUP_MINIO_*.
```

Endpoints contain hostnames, not schemes or bucket paths. SDK-generated public URLs should use the bucket's regional HTTPS REST endpoint. Do not sign the nginx hostname then rewrite it to S3: SigV4 signs the host. Avoid region redirects; the worker's HTTP download path does not enable redirect following. Dotted bucket names complicate wildcard TLS validation. [S3 virtual hosting](https://docs.aws.amazon.com/AmazonS3/latest/userguide/VirtualHosting.html).

Keep Media's current owner-checked HLS behavior: `/api/jobs/<asset>/hls/*.m3u8` returns playlist bodies; relative variant/segment paths stay on that route. Segment requests recheck ownership and 307 redirect to short-lived signed S3 output URLs. MP4 uses a signed S3 URL directly. Worker source grants come from reverse Media HTTP, are renewed on claim/expiry, and use S3 HTTPS; workers still hold no source-store key. Retain the existing 900-second signed URL default and one-hour login; document MP4 URL refresh after expiry instead of silently extending lifetimes. A previously issued URL is a bearer capability until expiry or object deletion. [Presigned URL behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).

Output bucket CORS preparation (replace origin; CORS does not authorize objects):

```json
[{"AllowedOrigins":["https://<approved-demo-hostname>"],
  "AllowedMethods":["GET","HEAD"],
  "AllowedHeaders":["Range"],
  "ExposeHeaders":["ETag","Accept-Ranges","Content-Range","Content-Length"],
  "MaxAgeSeconds":300}]
```

Source bucket needs no browser CORS for the current upload-through-Media flow. Browser cookies remain on the application origin; S3 uses query signatures. Check actual HLS redirects/preflights and MP4 range/seek playback in the cloud. Expand headers only if the observed request requires it. A signed GET URL is not automatically a valid signed HEAD URL. [CORS elements](https://docs.aws.amazon.com/AmazonS3/latest/userguide/ManageCorsUsing.html).

Use a public ACME certificate on nginx, existing DNS A record to the Elastic IP, and normal browser/Publisher system trust. Keep HTTP-01 challenge handling and certificate reload/renewal on the host; expiry must cover presentation dates despite stopped intervals. Certificate purchase cost is zero for this chosen ACME approach; DNS/registration is a separate input. Remove MinIO proxy/health routes. Preserve dynamic Docker DNS resolution for Media, `/internal/` denial, 101 MB upload ceiling and API forwarding. No need to change the frontend design or public API.

## Exact preparation gaps

These are future implementation tasks, not completed changes or commands already available.

| Gap and inspected source | Concrete preparation and acceptance |
|---|---|
| `compose/local/docker-compose.yml` is local-only | Add a dedicated AWS Compose file derived from it, not an overlay that accidentally preserves services/dependencies. Remove MinIO/bootstrap and dependencies, public-bind only nginx, retain DB separation, outbound S3 network, encrypted-data mounts, explicit worker count, restart policies and bounded log rotation. Keep DB/Processing diagnostic ports loopback-only if the harness needs them. Pin all live image digests. |
| `scripts/dev/runtime.py` hardcodes local state/Compose, generates MinIO defaults, fetches/builds MinIO and smokes `/minio/health/live` | Add a small AWS configuration/backend adapter with explicit project identity, public origin, system trust, Compose path and persistent state. It must not call local `configure()` and silently generate a new namespace/credentials or choose Lima. Fresh deployment fails closed on missing input. |
| `media/config.py`, `media/services/storage.py`, `processing/config.py`, `processing/worker/storage.py`, `processing/recovery.py`; `deploy/minio/bootstrap.py` | Supply regional endpoints and scoped IAM policies/CORS; replace MinIOAdmin bootstrap with operator-side S3/IAM setup plus bounded S3 smoke. Verify multipart, digest/size, denied operations, grant renewal, output cleanup including late writes. Session-token/provider support is currently absent; do not claim IAM role support. |
| `deploy/nginx/local.conf.template` binds localhost TLS; frontend is a host bind mount | Add AWS nginx template for domain/ACME, remove storage proxy routes, package frontend/config into a checksummed versioned directory mounted read-only. Preserve localhost container health and dynamic upstream DNS. Prove external trusted HTTPS, host-only auth cookies, upload, MP4/HLS decoding and deletion. |
| `deploy/media.Dockerfile`, `deploy/processing.Dockerfile`, image provenance | Produce **linux/amd64** images from the accepted SHA, preferably on native x86 CI/build host. The existing Mac arm64 image is not deployable evidence for x86. Verify pinned base digest includes target platform, dependencies/FFmpeg codecs and exact image architecture; tests and Trivy apply to those actual digests. Native ARM c7g is an alternative only after a fresh complete ARM artifact proof. |
| `scripts/dev/release.py` uses local runtime, local Unix Docker and explicitly rejects non-local public smoke URLs | Run control on EC2's local Unix Docker socket, adapt configuration/smoke to an allowlisted approved AWS HTTPS origin with system trust. Add promotion of an already-tested immutable image, preserving source/image proof, active drain, deadline, migration compatibility, pending journal and exact rollback. Do not merely remove safety checks or run the unchanged local target. |
| `scripts/evidence/performance.py` directly combines HTTP client and local Docker controls; recovery/E2E have local state assumptions | Split remote public client from lightweight host-side quota/SQL/fault collector. Pass approved origin and backend explicitly; external generator gets no database/service credentials. Adapt bounded recovery/browser/CLI workflow, sanitizer and manifest fields. Existing Make evidence commands alone are not AWS-ready. |
| Persistent startup/stop/backup behavior is not a cloud runbook implementation | Add one systemd-controlled start/drain/stop procedure, mount guard, stable Compose name/volumes, worker count restore, private journal/config backup and restore verification. Existing Compose has no general `restart:` policy. Never use `down -v` as shutdown. |
| Accounting and #38/#39 acceptance | Freeze accepted config or baseline; collect bytes/object/request counts, queue age, resource pressure, exact hash cost and runtime-hour ledger. Implement manual activation only if #39 is accepted; no automatic scheduler/controller. |

Existing `app/` remains regression reference, not a third live service. Use existing tests/scan gates and relevant new deployment-adapter tests; do not reopen missing Project1 scope. Build and scan outside timed runs. ECR is practical but optional: if omitted, transport checksummed `docker save` artifacts and verify loaded image IDs; preserve exact-image rollback. Never pull an unverified mutable `latest` at restart.

## Current official pricing and bounded budget

**USD, checked 14 October 2026, no credits/free-tier deductions, no commitments/Spot.** EC2/EBS prices were read from the official Singapore CSV published **12 October 2026 19:39:25Z**, effective 1 October. S3 JSON published 12 October 23:11:02Z; Data Transfer 16 September; ECR 11 September. Current catalogs are mutable: refresh before approval and retain the matching price rows/version in the eventual evidence. Public list prices do not prove account quota, AZ capacity or access.

| Compute option, all 8 vCPU / 16 GiB | USD/hour | 120 hours | 504 hours | Decision |
|---|---:|---:|---:|---|
| c6a.2xlarge, AMD x86 | 0.3528 | 42.34 | 177.81 | Default: nonburstable, conventional x86; sufficient nominal worker envelope |
| c6i.2xlarge, Intel x86 | 0.3920 | 47.04 | 197.57 | Availability fallback after reprice/config record |
| c7i.2xlarge, Intel x86 | 0.4116 | 49.39 | 207.45 | No measured need for extra spend |
| c7g.2xlarge, ARM | 0.3332 | 39.98 | 167.93 | Saves only $2.35 over 120h; choose only with accepted ARM artifact/verification plan |

[Official EC2/EBS regional price CSV](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-southeast-1/index.csv). Selected c6a SKU `DYD6FC9AUENHNE2A`; c6i `558MXFSRZMHVCBQR`; c7i `3XYMP49R4PHJEXJV`; c7g `4JR4QBYT9QCS66T6`. Filters: OnDemand, Linux, Shared tenancy, Used capacity, preinstalled software NA, Singapore; exclude reservations, Dedicated, Spot and paid operating systems.

The worksheet deliberately charges **one full GB-month** for every retained storage allowance despite only 21 days' retention. This is a conservative cap, not a statement that AWS rounds all storage to a month. Daily deletion/proration should lower actual cost. 128 GiB main EBS includes root and data; the generator disk is separate. Internet egress counts S3 playback/downloads plus EC2 responses/evidence exports, including repeated range fetches. Charge every GB at the paid Singapore first-tier rate even if an account-wide allowance happens to exist.

| Cost item / ceiling over entire project | Rate | Budget USD |
|---|---:|---:|
| Main host 120 total running hours, including setup/build/release/recovery | $0.3528/h | 42.3360 |
| Main EBS 128 GiB, one full month, baseline gp3 performance | $0.096/GB-month | 12.2880 |
| Snapshot retained billed blocks, total 128 GiB-month | $0.05/GB-month | 6.4000 |
| One Elastic IP retained all 504h, including stopped periods | $0.005/h | 2.5200 |
| All S3 source/output/evidence storage, maximum 100 GB-month | $0.025/GB-month | 2.5000 |
| S3 PUT/COPY/POST/LIST including multipart/reconciliation, 1 million | $0.005/1,000 | 5.0000 |
| S3 GET/other Tier2 requests, 1 million | $0.0004/1,000 | 0.4000 |
| Combined paid internet output/playback/evidence transfer, 200 GB | $0.12/GB | 24.0000 |
| Private ECR retained image layers, 10 GB-month | $0.10/GB-month | 1.0000 |
| Separate c6a.large (2 vCPU/4 GiB) HTTP generator, 16h | $0.0882/h | 1.4112 |
| Generator public IPv4, released on termination, 16h | $0.005/h | 0.0800 |
| Generator gp3 root, 16 GiB, conservative full month | $0.096/GB-month | 1.5360 |
| Logs: Docker/journal rotated within EBS, selected exports within S3 allowance | Included above | 0 additional |
| **Service subtotal at 120h** | | **99.4712** |
| Domain/DNS allowance (existing subdomain preferred; actual vendor price UNKNOWN) | Spending allowance, not a quoted rate | 20.00 |
| Tax/FX/payment reserve (actual billing country/currency/tax UNKNOWN) | Reserve, not a tax calculation | 25.00 |
| Contingency for approved corrections/unbilled usage | Reserve | 25.00 |
| **Total envelope** | | **169.47** |
| **Unallocated margin below $200** | | **30.53** |

Sources: [S3 Singapore offer](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/ap-southeast-1/index.json), [Data Transfer Singapore offer](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/ap-southeast-1/index.json), [ECR Singapore offer](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECR/current/ap-southeast-1/index.json), [EBS pricing/billing](https://aws.amazon.com/ebs/pricing/), [public IPv4 pricing](https://aws.amazon.com/vpc/pricing/). S3 storage SKU `M6MTARCQFUQBQ2V3`, Tier1 `VHRJWKRHEA6VHEFY`, Tier2 `T469UNPYX78434EG`; paid internet transfer SKU `SDHP4R7WGBVJPQPY` in **AWSDataTransfer**. The zero-dollar transfer placeholder in the AmazonS3 catalog is not a reason to budget zero internet egress. ECR SKU `7V2YHG7PQ82BEXNB`; gp3 `X8SY8CJFS8WV7VQN`; snapshot `5JKF9WXGUTYXYKXH`; generator `9C3E5J54K6P8KBCA`.

Use local rotated logs/basic EC2 monitoring; no CloudWatch Logs agent, paid detailed metrics, data-event trails, enhanced ECR Inspector scanning or log-query service in this default. Existing Trivy scans remain required. If centralized logs become necessary, the current Singapore catalog quotes $0.70/GB ingested and $0.03/GB-month stored; 2 GB of each adds $1.46 before reserve/tax. Add the real quantity explicitly. [CloudWatch regional offer](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-southeast-1/index.json). AWS Budgets monitoring/notifications are free; do not configure paid budget actions. [Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/).

| Main run hours | Main compute | All service ceilings | Including the same $70 allowances/reserves |
|---:|---:|---:|---:|
| 80 | 28.22 | 85.36 | **155.36** |
| 100 planned | 35.28 | 92.42 | **162.42** |
| 120 maximum | 42.34 | 99.47 | **169.47** |
| 504 continuous | 177.81 | 234.95 | **304.95 — reject** |

Formula: `0.3528 × main_hours + 57.1352 + domain/DNS + tax/FX + contingency`, with the exact quantities/rates above held constant. These generous storage/traffic/request ceilings are **planning assumptions**, not measured #39 outcomes. S3 request/storage limits are not automatically enforced hard caps. Track them and close intake/playback before exceeding the allowance.

### Fill the cost worksheet before deployment

Required user/account inputs: actual project account ID and billing owner; explicit permission for this project; approved region; **currency of the $200 ceiling** (this estimate assumes USD); billing/tax currency; project start/end dates and required demo windows; controlled hostname/DNS operator; operator access method and permitted CIDR; whether scoped service access keys are permitted; permission to delete demo resources/data on the teardown date. Provide profile/role names and nonsecret identifiers, never paste credentials into chat.

Unknown-price lookup: for a new region, open the official EC2 regional CSV above with the region code replaced, apply the listed Linux/Shared/Used/NA filters, and match the selected SKU plus gp3/snapshot usage rows; use the corresponding S3/DataTransfer/ECR regional JSONs. For DNS, ask its owner whether the existing subdomain has an incremental charge; otherwise obtain the exact registration and hosted-zone/query quote from the chosen provider before purchase (AWS option: [Route 53 pricing](https://aws.amazon.com/route53/pricing/)). For tax/FX, the billing owner supplies the actual invoicing jurisdiction and payment conversion/fee; reprice the reserve if insufficient. An unresolved quote is not zero cost.

Operator defaults can be chosen without new product discussion: c6a.2xlarge, Linux x86, same-AZ generator, 32+96 GiB gp3, two S3 Standard buckets, three scoped service keys, ECR 10 GB ceiling, one EIP, ACME, no managed database, baseline quotas unless experiments are accepted. If currency is SGD or another currency, convert using the actual billing/payment rate and reapprove hours/ceilings; $200 USD is not $200 SGD. If DNS/domain actual cost exceeds $20, reprice; do not describe the allowance as a purchased domain.

Insert measured #39/first-cloud-smoke values: job counts by fixture/profile `N`; mean and maximum source/MP4/HLS bytes; HLS object count; source retention; failed/cancelled/retried object bytes; multipart part count; source grant/read, playlist/segment GETs and cleanup LIST counts; playback sessions, seeks, repeated segment transfers; ECR layer bytes; total log/snapshot changed blocks. Estimate:

```text
S3 GB-month = integral(retained source + output + failed-attempt + evidence bytes over time) / billing GB-month
Tier1 = source PUT parts + output PUT parts + multipart control + LIST/recovery + evidence writes
Tier2 = worker source GETs + Media playlist/copy GETs + playback segment/MP4 GETs + other reads
Internet GB = measured external S3 response bytes + EC2 response/export bytes (avoid counting internal S3 reads twice)
Cost = storage integral*0.025 + Tier1*0.000005 + Tier2*0.0000004 + internet_GB*0.12
```

270 jobs alone does not determine egress; encoding output size and actual playback sessions do. Same-region EC2↔S3 transfer has no transfer charge, while requests/storage still apply; keep both buckets local to the host region. [AWS transfer example](https://aws.amazon.com/vpc/pricing/).

## Ordered preparation, deployment, validation and teardown

### 1. Prepare now, without AWS or competing workloads

Parent reviews and publishes the completed #38/#39 rejection decisions. Preserve immutable baselines and all failures. The worksheet now carries the measured local output/transfer inputs; retain baseline quotas and fixed workers. Implement the small deployment adapters/configuration listed above in a separately authorized coding task, with offline checks and public documentation only until account approval. No need for more architecture agents. Budget roughly one focused preparation day plus one bounded cloud verification day; this is a task estimate, not a new three-week implementation project.

User can supply the nonsecret account/budget/region/domain/window information now, arrange access through the account owner's normal secure login process, arrange an existing subdomain, identify the demo dataset and designate a cost/teardown owner. Do not use another project's AWS profile or ask for root credentials. Do not sign in/provision until the project account and this priced plan are approved.

### 2. Gate before first paid resource

Future AWS agent verifies the **explicit project profile's** account ID against the approved account, permissions/region, at least 10 On-Demand standard-instance vCPU quota (8 main + 2 generator), instance availability, actual tax/currency and latest public prices. Check any account-wide existing charges that the $200 ceiling must include. Create a dated resource/expiry manifest and a 21-day cost budget; set actual/forecast alerts at $80/$120/$150. Alerts are delayed and are not a spending cap. [Budget timing limitation](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

Approval covers concrete resource list, quantities, image/config identities, run windows and teardown/data deletion. If any prerequisite is missing, prepare files and stop before provisioning; no substitute account. At every later start, require `spent + unbilled estimate + planned session + remaining storage/egress + reserves <= $200` and the stricter operational thresholds below.

### 3. Provision the minimal inventory and install release

Create/tag only the approved VPC/subnet/IGW/security group, two S3 buckets and their policies/CORS, three scoped service principals, ECR repositories (if selected), main EC2/EBS/EIP. Tag resources `Project=dc2`, `Team=17`, `ExpiresAt=<UTC cutoff>` and record all IDs. Reuse account-managed networking only with explicit project scope. No Spot/Savings Plan purchase or capacity reservation.

Attach/mount encrypted data volume and install Docker/Compose with recorded versions. Transfer private config securely; application containers never receive operator credentials. Produce/scan/test exact amd64 artifacts off the timed deployment path. Upload images, frontend bundle and nginx configuration; record source SHA, digests, FFmpeg/build versions and configuration hash. Map DNS, obtain/verify ACME certificate, then start only PostgreSQL/Redis, bootstrap roles and apply Media/Processing migrations separately. Reuse the corrected TCP PostgreSQL readiness probe. Start APIs/reconcilers, one worker, then nginx; verify permissions and external workflow before scaling. Cloud Compose/start/stop command names must be supplied by the adapter implementation, not guessed from unchanged `make up`.

### 4. Validate in increasing cost order

1. Trusted external TLS; unsigned S3 denied; scoped IAM positive/negative/multipart tests; DB runtime DDL and cross-service connection denial; no public private-service ports. Validate endpoint region, CORS and source grant renewal after expiry.
2. Browser actual login/upload/status, decoded HLS **and** MP4/range seeking, derived-copy/edit, retry from stored source, ownership and deletion. Independent installed Publisher uses only `https://<host>/api`, system trust and its private cookie jar; prove 30-good/one-rejected folder outcomes. Record real output bytes and requests. Inspect only bcrypt cost/provenance metadata, never hashes/passwords.
3. Worker loss ≤300 s, lost queue-entry repair ≤120 s, Processing outage/restart intent convergence and no duplicate accepted output. Exercise complete Redis loss separately; do not extrapolate the queue-entry result. Stop/restart with durable queued backlog; old running attempts must converge through leases/retry rather than duplicate success. Record whole-host downtime separately—there is no healthy API during host failure.
4. Full scaling only after smoke/capacity preflight: immutable same fixtures, 30×60-second 720p clips, three rotated repeats at 1/2/3 hard-2-CPU workers, zero failed/missing MP4/HLS, ≥1.6× and ≥2.1× speedup and decreasing median queue wait. Status 50 users/180 s/p90≤700 ms/errors<1%; separate login 20 users/p90<2 s, three repeats. Warmups and session renewal outside timed intervals. Preserve hash-cost and exact image provenance.
5. If accepted #38/#39 changes are deployed, validate their cloud behavior as additional comparisons, not transplanted local claims. Predeclare mixed-load and queue-age bounds, preserve quality/correctness/recovery gates; reject policy/config regression.
6. Independent Processing good promotion/public smoke ≤600 s with nonempty active drain; actual bad-start candidate and automatic exact tested-image restoration within the existing recovery bound; Media container/image/DB revision unchanged. Preserve journal/digests through host restart. Repeat analogous Media-only deployment smoke to establish its packaging boundary; do not invent historic timed Media-release evidence.

Run HTTP load from a temporary **same-AZ c6a.large**, maximum 16 total hours, using a prebuilt fixture bundle. It is a test client, not a third business service. Resolve the application hostname to the main host's private IP on this generator while preserving the real TLS hostname/SNI; label results as in-region private-network client measurements. Browser public-network smoke runs from a separate client/Mac after Sol releases it. Publish public-path observations separately; no promise that an external internet path meets the in-region latency result. Record generator CPU/memory/event-loop delay and request schedule; abort invalid measurements if the generator saturates. Do not generate FFmpeg fixtures, build images or render browsers on the application host during timing. Host-side metric/fault collectors must remain lightweight and their overhead recorded. Terminate generator and release its dynamic IPv4/disk immediately after the booked block.

A failed AWS measurement is a failed AWS measurement, not a reason to erase accepted local results. Preserve full runs, denominators, scope, source/image/config/fixture identities, raw timings/pressure/queue ages, cost ledger and sanitized hash-indexed artifacts. Do not splice passing portions or weaken thresholds after observing results.

### 5. Run windows and durable stop/restart

Default 21-day schedule: days 1–3 up to 32h for installation/cloud verification; days 4–10 up to 24h for fixes/rehearsals; days 11–14 up to 24h for presentation/recovery recording; days 15–21 up to 20h for selected sessions/export. Total planned **100h**, plus at most **20h correction allowance** within the same budget. Actual dates are user inputs; if started 14 October, reserve the known 26 October presentation window and teardown by **4 November at the same Singapore start time**. Any service needed until the 16 November report deadline requires repricing; keep evidence/recordings offline after teardown. Each session has an owner and explicit UTC stop deadline, at most 8h except a separately booked presentation window.

Prepare a local systemd deadline timer using normal OS shutdown with instance-initiated shutdown behavior **stop** (not terminate). It is a cost backstop, not an autoscaler. Verify behavior in the first stop/restart exercise. The operator independently checks EC2 reaches `stopped`; stopping Compose alone does not stop billing. If graceful drain fails, close intake and stop within the booked deadline, record interrupted attempts for lease/retry recovery; do not let the timer extend itself indefinitely. [EC2 stop/start and OS shutdown behavior](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html).

Normal stop sequence:

1. Close public intake and announce maintenance; capture accepted worker count, queue/backlog/active attempts, source/image/config identities and migrations. Check pending release journal; resolve unfinished rollback first.
2. Stop reconciliation from creating new work; suspend new worker dequeues using the accepted drain mechanism and wait boundedly for active attempts. Queued intents may remain durable. Gracefully stop Media/Processing writers and recoverers once active writes finish.
3. With application writes quiescent, create private logical dumps of **both** databases plus required role/config recovery material; verify dump readability and record migration revisions. Preserve Redis AOF/metadata on EBS; gracefully stop Redis/PostgreSQL and flush filesystems. Keep secrets/hashes out of evidence exports.
4. Take a consistent encrypted data-volume snapshot at first install, before risky release and after substantial new durable data—not an unlimited snapshot every stop. Monitor total retained snapshot blocks; prune only approved superseded recovery points. Export sanitized evidence/recordings to the team's chosen durable location.
5. Stop EC2 gracefully, verify `stopped`, update runtime-hours/cost ledger. EBS, snapshots, EIP, ECR and S3 continue billing while stopped. Never prune volumes or release the stable EIP between booked sessions.

Restart: mount-check first; keep ingress closed and workers paused; read private journal and image/config pins, recover interrupted release if needed; start PostgreSQL/Redis with TCP readiness; verify both revisions; start APIs/reconcilers and prove durable backlog/lease convergence; restore the explicit accepted worker count; run public smoke then open intake. URLs can expire during downtime and must be renewed; don't alter source descriptors or grant worker source keys. Perform one restore rehearsal using a temporary volume within remaining storage/hours allowance; snapshot existence alone is not restore evidence.

### 6. Spend stop and final teardown

Maintain a project ledger at every start/stop, refreshed against billed cost daily while active. Count overlapping generator hours separately; use the full paid egress rate. At **100 main hours** review remaining demo needs. At **120 hours**, **21 days**, **150 dollars of accrued/estimated total spend**, or any worksheet usage ceiling, stop starting new experiments/windows and re-evaluate; none is permission to spend the remaining balance. At **175 dollars projected/accrued including known commitments**, close intake, stop compute and bring teardown forward, preserving the remaining $25 for lag/tax/deletion/export. AWS Budgets alone cannot enforce these rules. No unapproved extension or automatic restart. A forecast above $200 blocks deployment/continuation even before these thresholds.

On the approved teardown deadline, export and verify the required sanitized evidence/recordings and any user-approved data backup outside resources being deleted. Then stop intake/drain, terminate both instances, delete approved EBS volumes/snapshots, remove ECR images/repos, abort multipart uploads and empty/delete both buckets (including versions/delete markers if someone enabled versioning), release Elastic IPs, remove project-only network resources, delete service access keys/principals/policies and the DNS record. Remove any deadline timer/schedules, log groups or paid monitoring created by exception. Do not delete unrelated account resources. Inspect the manifest for leftovers and check billing again after reporting delay; retain only explicitly approved priced resources. A stopped instance alone is not teardown.

## Acceptance checklist for the parent

- [x] #38 and #39 rejection decisions/evidence inserted; baseline quotas and fixed worker counts retained.
- [x] Fresh independent review PASS at `632cac5`; accepted PR merge and exact Main checks remain coordinator-owned and are recorded in GitHub.
- [ ] Actual project account, region, USD/currency/billing inputs, access method, hostname/DNS, dates and $200 total approval supplied; no unrelated AWS credentials used.
- [ ] Current rates rechecked; request/byte worksheet filled or conservative ceilings retained; 100h plan/120h cap and teardown approved.
- [ ] AWS Compose/config/release/evidence adapters implemented and reviewed; x86 artifacts tested/scanned; mutable local images not reused as proof.
- [ ] S3 scoped IAM/multipart/renewal/CORS/TLS/decoded playback and DB ownership pass on AWS.
- [ ] Fair generator/capacity proof, complete cloud runs and recovery/rollback results recorded honestly; local results remain attributed to original sources.
- [ ] Durable-stop/backlog restart and actual backup restore pass; deadline stop reaches EC2 stopped; no HA claim.
- [ ] Offline evidence/recording retained; manifests and final teardown/billing follow-up assigned. Academic report/slides remain separate work.

## Paste-ready brief for the eventual AWS agent

> Work on dc2 from `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2`. Read root AGENTS, full worklog, execution handoff/plan/decisions/interfaces and this AWS plan. Baseline accepted Main is b913579; parent will supply any later accepted #38/#39 SHA, evidence and config. Historical roadmap security/deployment suggestions are superseded. Two live business services only: Media and Processing; reuse engine/frontend/Publisher. Preserve owner checks, bcrypt, separate DB roles/stores, service tokens, private objects and existing test/scan gates. No OIDC, credential broker, Kubernetes, autoscaling, managed database/cache, Alibaba or other project's AWS account.
>
> Inputs to fill before provisioning: PROJECT_ACCOUNT_ID=___; PROJECT_PROFILE_OR_ROLE=___; REGION=___ (provisional ap-southeast-1); APPROVED_TOTAL_BUDGET/CURRENCY=___ (plan assumes USD200); BILLING/TAX_CURRENCY=___; DOMAIN/DNS_OWNER=___; OPERATOR_CIDR=___; START/TEARDOWN_UTC=___; REQUIRED_DEMO_WINDOWS=___; SERVICE_KEY_POLICY_ALLOWED=___; CONFIG=baseline quotas, fixed 1/2/3 workers (both experimental candidates rejected); DEPLOY_SHA=___; PLAN/TEARDOWN_APPROVAL=___. Obtain credentials through normal secure local authentication, never chat; verify the explicit project account identity before any change. Missing approval/account blocks paid actions, not offline preparation.
>
> Implement/review the small AWS adapters before deployment: dedicated Compose without MinIO; outbound S3 networking; regional HTTPS SDK endpoints; three bucket-scoped service principals; output CORS; domain/ACME nginx; persistent EBS/systemd startup/drain/deadline stop; exact-image release/rollback; separate HTTP generator and host metrics/fault control. Current runtime/release/evidence scripts assume localhost/MinIO and cannot be passed off as AWS-ready unchanged. Build native linux/amd64 from the accepted source, test/scan actual digests; package frontend/config without redesign. Keep Media and Processing independently promotable with separate migrations and exact-image rollback.
>
> Revalidate official current Singapore prices and the attached worksheet. Proposed main host: On-Demand Linux c6a.2xlarge, 8vCPU/16GiB, 32+96GiB encrypted gp3, private S3 sources/outputs, one retained Elastic IP, optional private ECR. 100 main running hours planned, 120 maximum in 21 days; temporary same-AZ c6a.large HTTP generator ≤16h. Baseline worker hard limits 2CPU/1536MiB; fixed 1/2/3 unless #39 accepted. Preserve #38 baseline on rejection. Cost envelope $169.47 at120h with listed traffic/storage/request allowances and reserves; continuous504h is rejected. Budget is total, not monthly compute. Do not credit lower replicas as EC2 savings. Stop between booked windows and tear down by the approved date.
>
> Validate progressively: private storage/DB permission and TLS tests; real web+independent CLI, HLS/MP4 decoding/CORS/seek and expiry renewal; bounded worker/queue/Redis/backlog recovery; fair complete1/2/3 scaling and isolated latency; conditional accepted experiment policy; active Processing promotion/injected failure/exact rollback with Media unchanged; durable EC2 stop/restart and backup restore. Keep AWS claims separate from local f46599f evidence and PR37 unmeasured end-to-end gains. Record failures, exact image/config/fixture identities, bytes/requests/egress, runtime-hours and raw sanitized evidence; don't claim Sonar analysis ran when skipped. At150 estimated total dollars or120h/21days stop new windows; at175 projected/accrued dollars bring teardown forward. Export/verify evidence and finish resource-manifest teardown plus delayed billing check.
>
> All GitHub access uses authenticated gh exclusively. Parent controls integration/review and any publication; follow its explicit authorization. The local experiment runtime was released and the original demo restored; still inspect current ownership before any future workload. This planning document did not provision or validate AWS.
