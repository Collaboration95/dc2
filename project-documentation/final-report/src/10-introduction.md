# Introduction

## Background

**FlickPond** began as a Project 1 video application. Users register and upload their own videos.
FFmpeg workers turn each upload into an MP4 and adaptive HLS streams (360p, 480p and 720p), and the
owner then plays the result through an owner-checked link. Project 1 was built by a five-member
FlickPond team. It ran FastAPI, PostgreSQL, Redis with RQ, MinIO object storage, nginx and a browser
frontend on one cloud virtual machine. It worked, but as **one application**: a single API handled
identity, uploads, jobs and playback; the API, the workers and the recovery task shared one job
model and one database; and the jobs table had a foreign key to the users table. Another product
could not reuse the video workflow without importing FlickPond's code or reading its database.

Team 17 was formed for this practice module from members of two Project 1 teams. Prof Boon Kui Heng
approved the three-member team on 22 September 2026. Ibrahim Mammadov was a member of the FlickPond
Project 1 team (track A: worker, queue and media-type checks). Guruprasath Gopal and Nguyễn Kim Long
come from a different Project 1 team. The team chose to carry the frozen FlickPond code forward as
its baseline, because it already contained a real, CPU-heavy asynchronous workload. The submitted
proposal names repository `Flickpond/Media_player`, commit `890c5ec`. The working plan used the
team's local checkout of the same frozen code, commit `8854537` (decision D-01, 9 October). No
Project 1 feature work was continued, and inherited capabilities are not claimed as Project 2 work.

The proposal (4 October 2026) set the goal: turn FlickPond into a **reusable media processing
platform**. Applications would use one documented API for upload, processing, status and playback,
with processing running as an independently owned and scaled service. The lecturer accepted the
proposal and asked the team to confirm the microservice choice through detailed domain analysis
(feedback F-01). Section 3.1.4 records that analysis.

**Report-review snapshot, 10 November 2026.** Team 17 presented on 26 October. The
implementation is in release freeze, with the persistent AWS demonstration environment
`dc2-live` retained through the report period. Version 1.1 addresses the presentation feedback;
the final report is due on **16 November 2026**.

- **Media Management** and **Processing** own separate databases, images, IAM roles, CI lanes and
  release units. Their business commands and results use versioned asynchronous SQS messages.
  API Gateway uses Media's authorizer to establish trusted caller identity.
- The **web app** and independent **Publisher CLI** use the published API. The seven scoped use
  cases have implementation, automated-test and dated experiment evidence (sections 4 and 6).
- `dc2-live` was established on 18 October. The 20 October demo freeze and later verified delivery
  addenda are recorded separately in `docs/release/demo-release-manifest.md`. The standard lane
  launches finite Fargate encoders within a three-slot cap; a separate Lambda lane handles eligible
  short clips. The retained deployment uses one database cluster per service. The 10 November availability
  observation and operational follow-up are recorded in Project Status.
- The feedback of 26 October is addressed through additional DDD, component, deployment, schema,
  analysis/design and pipeline views in v1.1. Section 2 gives the dated delivery status and
  remaining submission tasks. Teardown is planned once, after 16 November.

The table summarises what Team 17 inherited and what it added.

| Area | Inherited from FlickPond (Project 1) | Added by Team 17 (Project 2) |
|:------------|:-----------------------------|:------------------------------------------|
| Service structure | One FastAPI application; workers and recovery task share its job code | Two bounded contexts, Media Management and Processing, found through DDD; business commands and results use asynchronous, versioned contracts |
| Data ownership | One database; jobs reference users | `media_db` and `processing_db`, each on its own Aurora cluster, with separate migration histories and least-privilege roles; no cross-database keys |
| Reuse | One browser application | A second, independent client (Publisher CLI) built against the published API only |
| Runtime | One VM with nginx, Redis/RQ and MinIO | Serverless AWS: CloudFront, API Gateway, Lambda container images, SQS, Aurora Serverless v2, S3 and finite ECS Fargate encoders that scale 0 → 3 → 0, and a Lambda lane for short clips |
| Security | Login, owner checks, TLS, signed output links, CI scans | Media-owned Gateway authorizer, trusted actor context, per-handler IAM roles, queue resource policies, bounded direct-to-S3 upload grants, pinned source versions, cloud negative tests |
| Delivery | Tests and scans in CI; manual deployment | Path-filtered per-service CI lanes, image scans and DAST; GitHub Actions CD over OIDC with per-owner release, smoke test and automatic restore |
| Evidence | Load tests that mostly read one completed video | Scaling, latency, recovery, release, security and reuse experiments with retained receipts |

FFmpeg encoding, HLS output, worker replicas and the basic CI workflow are inherited capabilities.
Team 17 reshaped and reused them, but does not count them as its own contribution.

## Business Needs

Small content teams keep needing the same video capabilities. Training providers, course teams,
small studios and community publishers are examples. They need:

- secure upload of videos they own;
- conversion into MP4 and best-effort HLS for supported browser playback;
- visibility of processing progress and failures;
- playback restricted to the owner.

Today each application rebuilds these capabilities or copies another team's code. That duplicates
effort and produces inconsistent security and operations. There is also a capacity problem:
transcoding is CPU-heavy and bursty. When it shares a deployment unit with the user-facing API, a
backlog of uploads competes with logins and status checks.

The business drivers for the platform follow from this:

1. **Reuse.** A new application gets authenticated upload, processing, status and owner-checked
   playback by calling one published API, with no copied code and no database access.
2. **Independent capacity.** Processing is its own service. Encoder capacity follows the backlog
   without scaling or redeploying the user-facing API.
3. **Repeatable, secure releases.** Every change passes automated tests and security gates. Each
   service is then released on its own from an immutable image and verified by an automated
   upload-to-playback smoke test.
4. **Low idle cost.** A small team's platform is idle most of the time, so it should cost almost
   nothing when idle. The design target became scale-to-zero: about USD 3–5 a month at idle
   (AD-27).

In platform terms (section 3.1.4), the **seed** is an owned video asset and its processing job.
**Producers** are content owners submitting videos through the web app or the Publisher CLI.
**Consumers** are owners playing their processed output. **Integrators** build new clients
against the OpenAPI contract. **Operators** release and scale the platform.

## Stakeholders

The project has no external sponsor; it is team-proposed. Business stakeholders are represented by
four planning personas defined in week 1 (`project-roadmap/business-scope.json`). They are
fictional design assumptions, not interviewed customers. Their goals and boundaries come from
`project-roadmap/business-scope.html` and its structured JSON register. The original generated
[persona cast illustration](assets/conduct-persona-cast.png) is retained with its provenance in
[the asset register](assets/README.md).

| Stakeholder | Type | Interest and need | Use cases |
|:----------------|:--------|:------------------------------------|:-----------|
| Content owners, e.g. course coordinator "Maya" (P-01) | Business: primary producer | Submit a folder of recordings once, see each result, retry failures and check playback | UC-1 to UC-5 |
| Independent trainers, e.g. "Arun" (P-02) | Business: secondary producer and viewer | Upload one video in the browser, follow its status, watch the result; nobody else can see it | UC-1 to UC-4 |
| Application developers, e.g. "Jules" (P-03) | Business/IT: integrator | Use the published API without copying service code or holding database credentials | UC-1, UC-3 to UC-5 |
| Platform operators, e.g. "Sam" (P-04) | IT: operations | Change processing capacity and release Processing without touching Media; see failures and recover | UC-6, UC-7 |
| Course lecturer and assessors (Prof Boon Kui Heng, NUS-ISS) | Academic sponsor and reviewer | Approved the three-member team and the proposal; assesses the architecture, evidence and delivery | All |
| Team 17 members | Delivery team | Guruprasath Gopal (cloud and delivery), Ibrahim Mammadov (backend services), Nguyễn Kim Long (domain, contracts and verification) | All |
| FlickPond Project 1 team | Upstream code owner | Authors of the inherited baseline; credited for inherited capabilities | Baseline |
| Amazon Web Services | IT: cloud provider | Hosts the managed services in `ap-southeast-1` | Runtime |
| GitHub | IT: tooling provider | Source control, pull requests, Actions CI/CD, Pages for the study guide | Delivery |

## Project Scope

The scope is the proposal's seven use cases (UC-1 to UC-7), delivered as two services, two clients
and one AWS environment. There are three levels of scope:

- **Architected.** The two-context platform, its contracts, the AWS topology and the operating
  model.
- **Implemented.** The seven use cases, with three experiments built behind flags
  (AD-22): an unattended encoder launcher, a Lambda short-encode lane (#93) and one database
  cluster per service (#94, AD-29). All three are enabled in the retained V2-live deployment; the last
  two were enabled and delivered on 21–22 October.
- **Experimentally verified.** The results in section 4. Each result is labelled with the
  environment that produced it: local, AWS V1 per-run stack, or the persistent V2-live
  environment.

The project ran in three phases.

| Phase | Dates | Delivered |
|:---------|:------------|:-----------------------------------------------------|
| 0. Baseline and design | 22 Sep – 9 Oct | Team approval, proposal (4 Oct), lecturer feedback, frozen baseline, personas and use cases, DDD model, contracts, build preparation |
| 1. V1: two services on AWS, per-run stacks | 10 – 18 Oct | Processing extracted (12 Oct), Media and Publisher adapted (13 Oct), AWS template and pipeline (15 Oct), cloud proof runs `r1017b`, `r1018b`, `r1019a`; tag `project2-v1` (18 Oct) |
| 2. V2-live: one persistent environment | 18 Oct – 16 Nov | `dc2-live` deployed (18 Oct), automatic in-place CD, unattended 0 → 3 → 0 encoders, security negatives, rollback proof, freeze (20 Oct), engineering hardening, presentation (26 Oct), final report due 16 Nov |

The detailed scope sources are the proposal (§3), the use-case catalogue
(`docs/architecture/use-case-design.md`) and the proposal-to-as-built deviation table
(`docs/architecture/decisions.md` §4). Section 3 explains each deviation.

### Functionality in scope

| ID | Use case | Clients | Status |
|:----|:------------------------------------|:-----------|:------------------------------------------|
| UC-1 | Register, log in and upload an owned video | Web app, CLI | Implemented. At most 100 MiB; a 15-minute owner-scoped direct-to-S3 grant, byte verification and pinned source version |
| UC-2 | Process the video into playable outputs | Platform for the owner | Implemented. MP4 plus best-effort HLS (360p/480p/720p, without upscaling); standard finite Fargate encoders and a Lambda short-clip lane |
| UC-3 | Track status and play the result | Web app, CLI | Implemented. Owner-filtered Media projection and expiring MP4/HLS playback access |
| UC-4 | Retry from the stored source | Web app, CLI | Implemented. A new fenced attempt uses the same pinned source without re-upload |
| UC-5 | Bulk-publish a folder and report results | CLI | Implemented. One public-API workflow and retained outcome per file |
| UC-6 | Scale processing capacity independently | Operator / platform | Implemented. V1 operator batches of 1–3; V2-live automatic finite Fargate launching within three reserved slots; short-lane admission is separate |
| UC-7 | Release Processing on its own and demonstrate rollback | Operator / pipeline | Implemented. Per-owner image/alias promotion, smoke and restore of the previous runtime; schema migrations are not reversed |

Section 6.2, Figure {@fig:ucm-scope}, shows the actors, the seven scoped goals and the grouped
exclusions. Edit, delete and operator routes are supporting capabilities of those goals.

The as-built platform also retains three supporting capabilities. They reuse the same aggregates
and are covered as variants in the use-case model:

- Owner **edit** operations (clip, crop, scale, convert) that create a derived asset.
- **Delete**, recorded as a tombstone in both contexts and followed by source cleanup.
- Operator-only **admin** routes.

### Functionality out of scope

These requirements are excluded, as recorded in the proposal (§3.5) and the briefing
interpretation:

- The rest of the Project 1 feature list: profiles, password reset, titles and tags, sharing
  modes and external videos.
- Viewer identities other than the owner: public sharing, student or LMS access, shared team
  ownership, tenants and billing. The contract accepts a `viewer` role that nothing issues.
- Search, public discovery, moderation workflows and product analytics.
- Crop or clip editor UI, thumbnails, 4K output, and direct/resumable uploads above 100 MiB.
- Kubernetes, general-purpose autoscaling, and multi-AZ database or multi-region failover.
- Historical data migration, malware scanning and full key rotation.
- A third client, a developer portal, live streaming, and a separate staging environment.

One earlier planning exclusion was superseded. The proposal excluded autoscaling, but V2-live
**does** start finite encoders automatically from the SQL backlog, bounded by a hard cap of three
(AD-27). This is bounded task launching, not a general autoscaling service.

### User journey evidence

The presentation recordings illustrate the owner workflow. Figure {@fig:conduct-ui-playback}
shows a completed video playing in the library. Other extracted frames show the
[upload screen](assets/ui-upload.png), [accepted upload awaiting processing](assets/ui-processing.png),
[Publisher batch results](assets/ui-publisher-batch.png),
[foreign-owner and anonymous access denials](assets/ui-foreign-access-denied.png), and
[bounded encoder activity](assets/ui-bounded-capacity.png). These are frames from the retained
presentation clips, documented as captured on `dc2-live` on 23 October; they are separate from
the automated acceptance results. Sources and exact timecodes are in [the asset register](assets/README.md).

![Figure {#fig:conduct-ui-playback}. Owner library with a processed video playing; D1 recording, 00:18.](assets/ui-library-playback.png){width=15cm}
