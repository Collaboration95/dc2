# Introduction

## Background

**FlickPond** began as a Project 1 video application. Users upload their own videos, FFmpeg
workers turn each upload into an MP4 and adaptive HLS streams (360p, 480p and 720p), and the owner
plays the result through an owner-checked link. Project 1 ran FastAPI, PostgreSQL, Redis with RQ,
MinIO, nginx and a browser frontend on one virtual machine as **one application**: a single API
handled identity, uploads, jobs and playback, and the jobs table had a foreign key to the users
table. Another product could not reuse the video workflow without importing FlickPond's code or
reading its database.

Team 17 was formed for this practice module with the special permission of Prof Boon Kui Heng
(22 September 2026), as a three-member team different from the Project 1 teams. The team chose the
frozen FlickPond code as its baseline because it already contained a real, CPU-heavy asynchronous
workload. The proposal names repository `Flickpond/Media_player`, commit `890c5ec`; the working
plan used the team's local checkout of the same frozen code, commit `8854537` (decision D-01,
9 October). Inherited capabilities are credited to FlickPond and are not claimed as Project 2 work.

The proposal (4 October 2026) set the goal: turn FlickPond into a **reusable media processing
platform**. Applications use one documented API for upload, processing, status and playback, and
processing runs as an independently owned and scaled service. The lecturer accepted the proposal
and asked the team to confirm the microservice choice through detailed domain analysis (feedback
F-01); section 3.1.4 records that analysis.

**Current status.** This is report version 1.1, submitted for **16 November 2026**. Team 17
presented on 26 October, and v1.1 incorporates the presentation feedback. The implementation is in
release freeze, and the persistent AWS environment `dc2-live` remains available until after
submission.

- **Media Management** and **Processing** own separate databases, images, IAM roles, CI lanes and
  release units. Their business commands and results use versioned asynchronous SQS messages.
  API Gateway uses Media's authorizer to establish trusted caller identity.
- The **web app** and the independent **Publisher CLI** use the published API. All seven scoped use
  cases are implemented, tested and backed by dated experiments (sections 4 and 6).
- The standard lane launches finite Fargate encoders within a three-slot cap; a separate Lambda
  lane handles eligible short clips. Each service has its own database cluster.

| Area | Inherited from FlickPond (Project 1) | Added by Team 17 (Project 2) |
|:------------|:-----------------------------|:------------------------------------------|
| Service structure | One FastAPI application; workers and recovery task share its job code | Two bounded contexts, Media Management and Processing, found through DDD; business commands and results use asynchronous, versioned contracts |
| Data ownership | One database; jobs reference users | `media_db` and `processing_db`, each on its own Aurora cluster, with separate migration histories and least-privilege roles; no cross-database keys |
| Reuse | One browser application | A second, independent client (Publisher CLI) built against the published API only |
| Runtime | One VM with nginx, Redis/RQ and MinIO | Serverless AWS: CloudFront, API Gateway, Lambda container images, SQS, Aurora Serverless v2, S3, finite ECS Fargate encoders that scale 0 → 3 → 0, and a Lambda lane for short clips |
| Security | Login, owner checks, TLS, signed output links, CI scans | Media-owned Gateway authorizer, trusted actor context, per-handler IAM roles, queue resource policies, bounded direct-to-S3 upload grants, pinned source versions, cloud negative tests |
| Delivery | Tests and scans in CI; manual deployment | Path-filtered per-service CI lanes, image scans and DAST; GitHub Actions CD over OIDC with per-owner release, smoke test and automatic restore |
| Evidence | Load tests that mostly read one completed video | Scaling, latency, recovery, release, security and reuse experiments with retained receipts |

## Business Needs

Small content teams, such as training providers, course teams, small studios and community
publishers, keep needing the same video capabilities:

- secure upload of videos they own;
- conversion into MP4 and best-effort HLS for supported browser playback;
- visibility of processing progress and failures;
- playback restricted to the owner.

Today each application rebuilds these capabilities or copies another team's code, which duplicates
effort and produces inconsistent security and operations. Transcoding is also CPU-heavy and bursty:
when it shares a deployment unit with the user-facing API, a backlog of uploads competes with
logins and status checks.

The business drivers follow from this:

1. **Reuse.** A new application gets upload, processing, status and owner-checked playback by
   calling one published API, with no copied code and no database access.
2. **Independent capacity.** Encoder capacity follows the backlog without scaling or redeploying
   the user-facing API.
3. **Repeatable, secure releases.** Each service is tested, scanned and released on its own from an
   immutable image, then verified by an automated upload-to-playback smoke test.
4. **Low idle cost.** The platform scales to zero, with a design target of about USD 3–5 a month at
   idle (AD-27).

In platform terms (section 3.1.4), the **seed** is an owned video asset and its processing job.
**Producers** are content owners submitting videos through the web app or the Publisher CLI.
**Consumers** are owners playing their processed output. **Integrators** build new clients
against the OpenAPI contract. **Operators** release and scale the platform.

## Stakeholders

The project has no external sponsor; it is team-proposed. Four planning personas, defined in week 1
(`project-roadmap/business-scope.json`), represent the business stakeholders. The
[persona cast illustration](assets/conduct-persona-cast.png) and its provenance are in
[the asset register](assets/README.md).

| Stakeholder | Type | Interest and need | Use cases |
|:----------------|:--------|:------------------------------------|:-----------|
| Content owners, e.g. course coordinator "Maya" (P-01) | Business: primary producer | Submit a folder of recordings once, see each result, retry failures and check playback | UC-1 to UC-5 |
| Independent trainers, e.g. "Arun" (P-02) | Business: secondary producer and viewer | Upload one video in the browser, follow its status, watch the result; nobody else can see it | UC-1 to UC-4 |
| Application developers, e.g. "Jules" (P-03) | Business/IT: integrator | Use the published API without copying service code or holding database credentials | UC-1, UC-3 to UC-5 |
| Platform operators, e.g. "Sam" (P-04) | IT: operations | Change processing capacity and release Processing without touching Media; see failures and recover | UC-6, UC-7 |
| Course lecturer and assessors (Prof Boon Kui Heng, NUS-ISS) | Academic sponsor and reviewer | Approved the team and the proposal; assesses the architecture, evidence and delivery | All |
| Team 17 members | Delivery team | Guruprasath Gopal (cloud and delivery), Ibrahim Mammadov (backend services), Nguyễn Kim Long (domain, contracts and verification) | All |
| FlickPond Project 1 team | Upstream code owner | Authors of the inherited baseline; credited for inherited capabilities | Baseline |
| Amazon Web Services | IT: cloud provider | Hosts the managed services in `ap-southeast-1` | Runtime |
| GitHub | IT: tooling provider | Source control, pull requests, Actions CI/CD, Pages for the study guide | Delivery |

## Project Scope

The scope is the proposal's seven use cases (UC-1 to UC-7), delivered as two services, two clients
and one AWS environment, at three levels:

- **Architected.** The two-context platform, its contracts, the AWS topology and the operating
  model.
- **Implemented.** The seven use cases, with three capabilities built behind flags (AD-22): an
  unattended encoder launcher, a Lambda short-encode lane (#93) and one database cluster per
  service (#94, AD-29). All three are enabled in the V2-live deployment.
- **Experimentally verified.** The results in section 4, each labelled with its environment: local,
  AWS V1 per-run stack, or the persistent V2-live environment.

The project ran in three phases.

| Phase | Dates | Delivered |
|:---------|:------------|:-----------------------------------------------------|
| 0. Baseline and design | 22 Sep – 9 Oct | Team approval, proposal (4 Oct), lecturer feedback, frozen baseline, personas and use cases, DDD model, contracts |
| 1. V1: two services on AWS, per-run stacks | 10 – 18 Oct | Processing extracted, Media and Publisher adapted, AWS template and pipeline, cloud proof runs; tag `project2-v1` (18 Oct) |
| 2. V2-live: one persistent environment | 18 Oct – 16 Nov | `dc2-live`, automatic in-place CD, unattended 0 → 3 → 0 encoders, security and rollback proofs, freeze (20 Oct), presentation (26 Oct), final report (16 Nov) |

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
exclusions. Three supporting capabilities reuse the same aggregates and appear as variants in the
use-case model: owner **edit** operations (clip, crop, scale, convert) that create a derived asset;
**delete**, recorded as a tombstone in both contexts and followed by source cleanup; and
operator-only **admin** routes.

### Functionality out of scope

These requirements are excluded, as recorded in the proposal (§3.5):

- The rest of the Project 1 feature list: profiles, password reset, titles and tags, sharing
  modes and external videos.
- Viewer identities other than the owner: public sharing, student or LMS access, shared team
  ownership, tenants and billing. The contract accepts a `viewer` role that nothing issues.
- Search, public discovery, moderation workflows and product analytics.
- Crop or clip editor UI, thumbnails, 4K output, and direct/resumable uploads above 100 MiB.
- Kubernetes, general-purpose autoscaling, and multi-AZ database or multi-region failover.
- Historical data migration, malware scanning and full key rotation.
- A third client, a developer portal, live streaming, and a separate staging environment.

One planning exclusion changed. The proposal excluded autoscaling; V2-live starts finite encoders
automatically from the SQL backlog, bounded by a hard cap of three (AD-27). This is bounded task
launching, not a general autoscaling service.

### User journey evidence

The presentation recordings illustrate the owner workflow. Figure {@fig:conduct-ui-playback}
shows a completed video in the library player. Other frames show the
[library with playback](assets/ui-library-playback.png),
[upload screen](assets/ui-upload.png), [accepted upload awaiting processing](assets/ui-processing.png),
[Publisher batch results](assets/ui-publisher-batch.png),
[foreign-owner and anonymous access denials](assets/ui-foreign-access-denied.png), and
[bounded encoder activity](assets/ui-bounded-capacity.png). The frames were captured on `dc2-live`
on 23 October; sources and timecodes are in [the asset register](assets/README.md).

![Figure {#fig:conduct-ui-playback}. Owner library with the processed video loaded in the player and the other items marked Done; D1 recording, 00:14.5, cropped.](assets/conduct-ui-playback.png){width=15cm}
