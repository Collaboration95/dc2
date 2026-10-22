# Slide outline — Team 17, FlickPond (draft for Stage 3 cut)

Mon 26 Oct 2026, 2.35–3.15 pm, Zoom. The budget is 31.5 min of talk plus 8.5 min of Q&A
(`ROAD-TO-PRESENTATION.md`). This draft runs about **17% over** the talk budget on purpose. Slides marked
**CUT-1** go first and **CUT-2** go second; see the totals at the bottom.
Style rules: [`STYLE.md`](STYLE.md). Facts and sources: [`research/sections-1-4.md`](research/sections-1-4.md),
[`research/sections-5-6-demo.md`](research/sections-5-6-demo.md). All paths below are repository-relative.

## "Remember us for this" themes

| ID | Theme | Slides where it appears |
|---|---|---|
| **T1** | **A working app became a reusable platform.** We kept the inherited engine. A second, independent client (Publisher) proves the contract is reusable. | S03, S04, S05, S11, S20, S32, D2, S46 |
| **T2** | **Correctness lives at the boundaries.** Source pin, outbox/inbox, lease and version fences, and owner-checked playback. | S05, S13, S14, S17, S19, S26, S29, S30, D3, S46 |
| **T3** | **Pay for work, not for waiting.** No NAT, finite encoders, pausing databases and a bounded Lambda lane, with latency measured against cost. | S05, S21, S22, S23, S24, S25, D4, S46 |
| **T4** | **Every claim carries a receipt, including the misses.** Targets were kept unchanged, failures retained and gaps labelled NOT RUN. | S05, S09, S25, S34, S36, S37, D5, D6, S46 |

## Speaker proposal (PROPOSAL — agree in Stage 3)

This follows the report's split (`final-report/src/60-other.md`, §responsibilities):

- **Guruprasath** owns UC-6 (scale Processing), UC-7 (independent release) and DP-1 (bounded cloud capacity and safe per-owner release).
- **Ibrahim** owns UC-1 (upload), UC-2 (process), UC-4 (retry) and DP-2 (durable asynchronous handoff).
- **Long** owns UC-3 (status and play), UC-5 (bulk publish) and DP-3 (trusted owner identity and reusable public contract).

| Block | Slides | Speaker | Why | Talk (draft) |
|---|---|---|---|---|
| Title, §1 Overview | S01–S06 | **Long** | Platform/contract story (DP-3, UC-5 Publisher) | 175 s |
| §2 Conduct, §3a–b decisions and components | S07–S14 | **Ibrahim** | Backend extraction, DP-2 handoff | 355 s |
| §3 identity, DDD, producers/consumers | S15–S20 | **Long** | DDD/contracts lead, DP-3, UC-3/UC-5 | 260 s |
| §4a–b decisions, network, execution lanes | S21–S25 | **Guruprasath** | Cloud lead, UC-6, DP-1 | 260 s |
| §4c–d persistence and the detailed use case | S26–S31 | **Ibrahim** | UC-1/UC-2 path, DP-2 | 260 s |
| §5 DevOps | S32–S38 | **Guruprasath** | CI/CD lead, UC-7, DP-1 | 400 s |
| §6 Demo intro and voice-overs | S39–S45 | Long (S39, D2, D3, D5, D6) · Ibrahim (D1) · Guruprasath (D4) | Clip owner = use-case owner | 480 s |
| Closing | S46 | **Long** | Bookends the opening | 25 s |

**Per person (draft, before cuts):** Long ≈ 730 s (12.2 min) · Ibrahim ≈ 717 s (12.0 min) · Guruprasath ≈ 773 s (12.9 min); clip intros included.
There are five live hand-offs: L→I (S07), I→L (S15), L→G (S21), G→I (S26), I→G (S32), plus the clip voice-overs.

---

Format per slide: **ID · type · seconds · guideline bullet · theme · speaker**, then the headline,
what is on the slide (visual and ≤ 12 words), and the notes gist.

## S01 — Title (Long)

**S01 · Title · 15 s · — · — · Long**
- **Headline:** FlickPond: from video app to reusable media platform
- **On slide:** Logo (`final-report/figures/cover-logo.png`) · "Team 17 · Guruprasath · Ibrahim · Long · 26 Oct 2026"
- **Notes:** Introduce the three names and their roles: cloud/delivery, backend services, domain/contracts. Say that the demo is pre-recorded, and that questions are welcome after each section.

## §1 Overview — budget 120 s talk + 60 s Q&A (Long)

**S02 · Statement + persona strip · 35 s · 1a · — · Long**
- **Headline:** Teams keep rebuilding upload-to-playback; we made it reusable
- **On slide:** Four persona icons (Maya, Arun, Jules, Sam) → "upload once · process later · play privately"
- **Notes:**
  - Small training and content teams rebuild upload, conversion, status and protected playback each time. CPU-heavy bursts must not slow down interactive requests. Source: `final-report/src/10-introduction.md` §Business Needs.
  - Personas: P-01 course coordinator (batch producer), P-02 trainer, P-03 integrator, P-04 operator. Source: same file, stakeholder table.

**S03 · Diagram · 40 s · 1b · T1 · Long**
- **Headline:** Two clients, one public contract, owned services behind
- **On slide:** Redrawn platform context (**NEW V1**). Caption: "Clients never touch databases or service internals."
- **Notes:**
  - Producers are owners uploading through the browser or Publisher. The same owners consume the result (there is no viewer-sharing product). Integrators build on the OpenAPI; operators handle capacity and releases. Source: `final-report/src/30-logical.md` §Platform Design.
  - Platform claim: Publisher has **0 service imports and 0 DB credentials** (491 lines in 6 files). Source: `final-report/src/40-quality.md` §Extensibility.
  - If asked: → B04 (why call it a platform).

**S04 · Before/after · 40 s · 1c · T1 · Long**
- **Headline:** We kept the engine; we changed ownership and runtime
- **On slide:** Left: inherited monolith (crop of `architecture-before-after.png` left). Right: as-built (**NEW V2**). Strip: "Inherited: FFmpeg · HLS · worker replicas · basic CI"
- **Notes:**
  - Inherited: accounts, upload/playback UI, FFmpeg, MP4, adaptive HLS, worker replicas, basic CI. Added: Media and Processing contexts with owned schemas and images, SQS outbox/inbox, S3 source pins, a serverless persistent environment, Lambda short lane, per-service Aurora, automated release/smoke/restore, and Publisher. Source: `final-report/src/10-introduction.md` scope table.
  - Team: 5-member inherited team, 3-member Project 2 team. Ibrahim came from FlickPond. Source: same, §Background.

**S05 · Statement (4 tiles) · 25 s · 1b · T1–T4 · Long**
- **Headline:** Four things we'd like you to remember
- **On slide:** Four tiles: "Reusable platform" · "Correct at boundaries" · "Pay for work" · "Receipts, including misses"
- **Notes:** This is the map for the talk. Every section points back to a tile, and the tile icon repeats in the slide corner when its theme appears.

**S06 · Diagram (scope strip) · 20 s · 1c · — · Long · CUT-1**
- **Headline:** Seven use cases in scope; sharing and tenants out
- **On slide:** UC-1…UC-7 icons in three groups (upload/process/play · retry/batch · scale/release); a greyed strip lists the exclusions
- **Notes:** Out of scope: public sharing, tenants, live streaming, regional failover. Source: `final-report/src/10-introduction.md` §Project Scope. Full table → B05.

## §2 Project conduct — budget 90 s talk + 30 s Q&A (Ibrahim)

**S07 · Diagram (timeline) · 40 s · 2b · — · Ibrahim**
- **Headline:** Proposal to live platform in seventeen days
- **On slide:** Milestone strip (**NEW V4**): 4 Oct proposal → 9 Oct DDD → 12–13 extraction → 17–18 AWS proof → 20 freeze → 21–22 lane + DB split
- **Notes:**
  - Baseline and design finished 2 days late. Extraction and AWS work still landed inside their planned windows. Source: `final-report/src/20-conduct.md` §Milestones.
  - The `project2-v1` tag is 18 Oct. CD has been green on Main since run 39733859422 (22 Oct). Source: `ROAD-TO-PRESENTATION.md` Stage 0.

**S08 · Big-number · 25 s · 2b · — · Ibrahim · CUT-2 (merge into S07 footer)**
- **Headline:** Equal effort, three different specialist leads
- **On slide:** 3 columns of "12 pd" (cloud/delivery · backend · domain/verification); footer "33 pd recorded vs 31 planned"
- **Notes:** These are team-agreed allocations, not timesheets. Recorded: 11 pd each through 20 Oct; the forecast is 36 pd (+16%). Source: `project-documentation/effort-ledger.md`; `final-report/src/20-conduct.md` §Effort. If asked: → B02.

**S09 · Status / honesty · 30 s · 2a · T4 · Ibrahim**
- **Headline:** All seven use cases done; five issue classes open
- **On slide:** Big "7/7 UCs" plus five chips: Latency (AISS-01) · Edge hardening · Schema rollback · Ops hardening · Missing evidence
- **Notes:**
  - The functional scope is complete. Remaining: the presentation, recordings and the post-26-Oct report update. Source: `final-report/src/20-conduct.md` §Project Status.
  - Each chip has one owner and one next step. The register is in `final-report/src/36-other-limitations.md`. If asked: → B01.

## §3 Logical architecture and design — budget 420 s talk + 120 s Q&A

**S10 · Statement (drivers) · 30 s · 3a · — · Ibrahim**
- **Headline:** Three drivers shaped every logical decision
- **On slide:** Three tiles: "Release and scale Processing alone" · "Survive duplicates and failures" · "Reuse without internals"
- **Notes:** This is the top-down step from requirements to design. Drivers map to UC-6/UC-7, DP-2 and DP-3/UC-5. Source: `final-report/src/30-logical.md` §Key Architectural Decisions.

**S11 · Decision card · 50 s · 3a · T1 · Ibrahim**
- **Headline:** Split where the rules change: the encoding lifecycle
- **On slide:** `AD-01 / AD-02`: Choice "Media + Processing, owned data" · Why "distinct rules, CPU profile" · Trade-off "more integration". Mini context sketch on the right.
- **Notes:**
  - Processing has its own job/attempt/lease rules and scaling profile. Identity and playback need account + Asset together, so they stay in Media. Source: `docs/architecture/ddd.md` §3; `docs/architecture/decisions.md` AD-01/02.
  - If asked "why not split identity or delivery too?": → B06.

**S12 · Diagram (build ×4) · 75 s · 3b · — · Ibrahim**
- **Headline:** Two services, each with its own layers and data
- **On slide:** Landscape logical-detail view (**NEW V7**): clients → edge/authorizer → Media stack | async seam | Processing stack → own SQL stores. Shared-kernel strip at the bottom.
- **Notes:**
  - Builds: (1) clients and edge, (2) Media API/domain/persistence, (3) Processing plus finite encoders as adapters, (4) the queue seam and shared kernel (`contracts/`, `delivery/`, `runtime_support/`). Source: `final-report/src/30-logical.md` §Tiers/Nodes.
  - Lambdas and encoders are roles inside a service, not extra services. If asked: → B07.

**S13 · Decision card · 45 s · 3a · T2 · Ibrahim**
- **Headline:** Commit locally, deliver asynchronously, deduplicate on arrival
- **On slide:** `AD-11`: Choice "SQL outbox → SQS → inbox" · Why "no lost intent" · Trade-off "at-least-once, eventual"
- **Notes:**
  - SQS is durable only after it receives a message. The outbox makes the intent atomic with the state. Source: `docs/architecture/ddd.md` §5; `delivery/sql.py`.
  - If asked "is this exactly-once?": → B08.

**S14 · Before/after (build ×2) · 60 s · 3a/3b · T2 · Ibrahim**
- **Headline:** No synchronous call between services on the business path
- **On slide:** Left (grey): HTTP SubmitJob + Redis. Right: local commit → outbox → SQS → inbox → local commit, with the result returning to the projection (**NEW V8**). Big callout: "consumer off 48 s → still 202"
- **Notes:**
  - Isolation receipt: command consumer disabled 48 s, Media still accepted (202), job done 58.9 s after re-enable. Source: `docs/results/actual-vs-target.md` AV-5 `[AWS]`.
  - 9/9 jobs done despite 18 work sends, with no manual purge (duplicates tolerated). Source: same, LV-11.
  - Hand-off: "Long takes us into the domain model."

**S15 · Before/after · 40 s · 3a · T2 · Long**
- **Headline:** Services receive a trusted owner, not a token
- **On slide:** Simplified `report-dp3-identity` (**NEW V9**): left "service token + owner header", right "Gateway → Media authorizer → trusted Actor"
- **Notes:**
  - AD-09/AD-20: Media authorizer supplies the Actor, and IAM authenticates queue principals. Source: `docs/architecture/decisions.md`.
  - Honest limit: protected Processing routes still depend on Media's user lookup (`media/authorizer.py`). If asked: → B11.

**S16 · Diagram · 50 s · 3c · — · Long**
- **Headline:** Media is the customer; Processing is the supplier
- **On slide:** Side-by-side context map (**NEW V10**): Asset context ↔ Job context; command/result arrows; labels "published language" and "small shared kernel"
- **Notes:**
  - Media translates Asset → command and result → local projection. Processing translates messages → its own job model. There are 5 message kinds: submit, retry, cancel, work, result. Source: `docs/architecture/ddd.md` §§6–7; `final-report/src/30-logical.md` message table.
  - 2 OpenAPI documents at 1.0.0, wire version 1, N/N-1 policy (tested, not yet exercised live). Full map: → B12.

**S17 · Diagram · 50 s · 3c · T2 · Long**
- **Headline:** Two aggregates, each guarding its own invariants
- **On slide:** Two cards (**NEW V11**): Asset (blue) "pinned source · one job per asset · tombstoned delete"; Job (amber) "current attempt · live lease · cancel-before-submit"
- **Notes:**
  - These are linked by identifier values, not shared ORM objects or foreign keys. Source: `docs/architecture/ddd.md` §§3–4.
  - If asked about retry states: → B13 (job state machine).

**S18 · Statement (glossary) · 25 s · 3c · — · Long · CUT-1**
- **Headline:** Six words the whole codebase agrees on
- **On slide:** Asset · Job · Attempt · Source revision · Lease · Projection (one line each)
- **Notes:** Definitions from `research/sections-1-4.md` §3 DDD table; source `docs/architecture/ddd.md`.

**S19 · Diagram · 45 s · 3c · T2 · Long · CUT-2**
- **Headline:** Late or duplicate results cannot overwrite newer truth
- **On slide:** `state_version` timeline (**NEW V12**): v3 applied, v2 ignored, a conflicting v3 rejected
- **Notes:** These are full snapshots ordered by `state_version` and attempt. It is event-carried state transfer, not event sourcing. Source: AD-21; `media/projections.py`. If asked "CQRS?": → B08.

**S20 · Diagram + big-number · 50 s · 3c · T1 · Long**
- **Headline:** Browser and Publisher use the same three calls
- **On slide:** reserve → direct S3 POST → finalize; play = signed MP4 / HLS (**NEW V13**). Callouts: "0 service imports · 0 DB credentials"
- **Notes:**
  - Producer flow: reserve → S3 POST → finalize. Status, retry and delete go through the public API, and a Publisher batch keeps per-file outcomes. Consumer flow: Media projection read → signed MP4 (206) / HLS playlist plus 307 segment redirect. Source: `final-report/src/30-logical.md` platform-role table.
  - This sets up D2. Hand-off: "Guruprasath: how this runs on AWS."

## §4 Physical architecture and design — budget 420 s talk + 120 s Q&A

**S21 · Decision card + big-number · 50 s · 4a · T3 · Guruprasath**
- **Headline:** Pay for work, not for waiting
- **On slide:** `AD-10 / AD-12 / AD-27`: Choice "Lambda, finite tasks, pausing Aurora" · Why "idle cost ≈ 0" · Trade-off "cold starts". Callout "USD 3–5 / month idle (model)"
- **Notes:**
  - The estimate is a model, not a bill. It predates the second cluster, and the actual bill is not established (AISS-05). The budget alarm is USD 20/month at 50/80/100%. Source: `docs/architecture/decisions.md` AD-27.
  - The first DB read takes 4.7 s after a pause. Source: AD-12. If asked about cost: → B14.

**S22 · Diagram (build ×4) · 75 s · 4b · T3 · Guruprasath**
- **Headline:** Managed edge, private compute, finite encoders
- **On slide:** `showcase-prep/assets/aws-topology.svg`, built in 4 frames (**NEW V14** frames)
- **Notes:**
  - The edge is CloudFront → HTTP API (20 rps, burst 50) → authorizer. The region is `ap-southeast-1`, with a VPC across 2 AZs. Media runs 4 functions and Processing runs 7 (both private, dual-stack). Source: `final-report/src/32-physical.md`.
  - Fargate tasks run with 2 vCPU / 4 GiB, a 0–3 cap and one attempt each, in a public subnet with no inbound rules. The short Lambda has 3008 MB and a mapping cap of 2. Aurora PG16 Serverless v2 runs as 2 clusters at 0–2 ACU. From config, not a live inventory: 11 functions and 4 queues + 4 DLQs (`scripts/aws/v1/definitions.py`).
  - If asked "why a public subnet?": → B15.

**S23 · Decision card · 30 s · 4a · T3 · Guruprasath · CUT-1 (fold into S22 frame 2)**
- **Headline:** IPv6 egress instead of a NAT gateway
- **On slide:** `AD-18`: Choice "egress-only IPv6 + S3 endpoint" · Why "no fixed NAT cost" · Trade-off "dual-stack endpoints only"
- **Notes:** Source: `docs/architecture/decisions.md` AD-18; `docs/architecture/views.md` §3.1.

**S24 · Diagram · 60 s · 4a/4b · T3 · Guruprasath**
- **Headline:** Short clips to Lambda; everything else to Fargate
- **On slide:** Two-lane diagram (**NEW V15**): size filter → Lambda (probe ≤60 s, ≤64 MiB, ≤1080 px) → encode **or** fenced redirect → Fargate 0–3. Footer: "same lease pipeline"
- **Notes:**
  - Dispatch knows only the size. The Lambda claims, downloads and probes the clip, then encodes it or performs `redirect_to_long_lane`, which cannot ping-pong. Source: `processing/short_lane.py`; `processing/messaging.py`.
  - The configured combined encoder ceiling is 5 (3 Fargate + 2 Lambda). It is not a global cap of 3.

**S25 · Big-number · 45 s · 4a · T3 T4 · Guruprasath**
- **Headline:** Queue wait solved; end-to-end latency still misses
- **On slide:** "0.26 s vs 32.6 s queue wait" (green) · "45.2 s vs 20 s aim end-to-end" (orange) · "$0.0003 vs $0.0021 per encode". Chip: `AWS · 21 Oct · sl1021 · n=5/arm`
- **Notes:**
  - The 45.2 s figure is a reported nearest-rank p50 (warm). Cold was 92.0 s (n=1) and Fargate 87.7 s. Between 35 and 80 s are unattributed, and the next step is per-stage tracing. `meets_keep_rule=false`; the lane stays enabled under a documented exception. Source: `docs/results/engineering-20261021/short-lane-sl1021.json`.
  - The Fargate arm used padded 72 MB files, so this is not an equal-byte benchmark. Cost covers compute only. If asked: → B09.
  - Hand-off: "Ibrahim: where the data lives, and one request end to end."

**S26 · Diagram · 60 s · 4c · T2 · Ibrahim**
- **Headline:** Each context owns its cluster, schema and roles
- **On slide:** Two DB cylinders (**NEW V17**): `media_db` (Asset, pin, projection, outbox/inbox) · `processing_db` (Job, Attempt, lease, outbox/inbox). Footer: "owner · migrator · runtime roles"
- **Notes:**
  - There are no foreign keys across contexts. Runtime roles are DML-only, and the owner role cannot log in. Source: `final-report/src/34-persistence-detailed.md` §Persistence Design.
  - The split was made live with snapshot → clone → credential switch → smoke → peer cleanup (AD-29). Honest limit: each cluster is still a single instance with no failover. If asked: → B16; ERs → B17.

**S27 · Diagram · 30 s · 4c · — · Ibrahim · CUT-1**
- **Headline:** Sources pinned by version; outputs scoped by attempt
- **On slide:** S3 key layout: `staging/{owner}/{reservation}/source` + VersionId · `jobs/{job}/attempts/{n}/primary.*`
- **Notes:** Retention: upload grant 15 min, signed output ≤ 900 s, queues 7 days / DLQs 14 days, logs 7 days, DB backups 1 day. No restore drill has been run (AISS-05). Source: `final-report/src/34-persistence-detailed.md` retention table.

**S28 · Diagram (phase strip) · 20 s · 4d · — · Ibrahim · CUT-2 (merge into S29)**
- **Headline:** One use case crosses every boundary: upload → play
- **On slide:** Six-phase strip (**NEW V18a**): Reserve · Upload · Handoff · Route · Encode · Play
- **Notes:** UC-1 to UC-3 cover trust, bytes, transactions, messaging, scheduling, execution and the read model. Source: `final-report/src/34-persistence-detailed.md` Case 1.

**S29 · Diagram (sequence, phase 1–2) · 50 s · 4d · T2 · Ibrahim**
- **Headline:** Bytes go straight to S3; the version is pinned
- **On slide:** Redrawn intake sequence (**NEW V18b**): reserve → S3 POST → verify → one transaction: Asset + pin + outbox
- **Notes:**
  - Finalize verifies the exact S3 VersionId, size and hash outside row locks. A replayed upload creates a new version and cannot change the pin. Source: `media/services/storage.py:verify_direct_upload`; `media/services/direct_intake.py`.
  - Limits: 100 MiB maximum; the grant lasts 15 min.

**S30 · Diagram (sequence, phase 3–5) · 60 s · 4d · T2 · Ibrahim**
- **Headline:** Leases fence stale workers; fallback cannot loop
- **On slide:** Redrawn encode sequence (**NEW V18c**): inbox + SubmissionGuard → work queue → claim with DB-clock lease → encode → commit, then ACK
- **Notes:**
  - Completion requires the current attempt and a live lease token. An old worker cannot commit. Source: `processing/lifecycle.py`.
  - A worker death marks the attempt abandoned and the job failed, and the owner retries on the stored source (UC-4). It does not auto-requeue. Source: `processing/recovery.py`.

**S31 · Diagram (sequence, phase 6) · 40 s · 4d · — · Ibrahim**
- **Headline:** Playback checks the owner, then grants temporary access
- **On slide:** Redrawn play sequence (**NEW V18d**): result → projection; owner read → signed MP4 (206) / HLS playlist → segment 307
- **Notes:**
  - Only newer valid snapshots apply. Owner, source and output namespaces are checked. CloudFront does not cache the API or playback. Source: `media/api/v1_hls.py`; AD-15.
  - Hand-off: "Guruprasath: how a change gets here safely."

## §5 DevOps and lifecycle — budget 360 s talk + 60 s Q&A (Guruprasath)

**S32 · Diagram · 60 s · 5a · T1 · Guruprasath**
- **Headline:** One repository, three images, independent releases
- **On slide:** Monorepo tree → 3 image repos (Media · Processing · worker) → per-owner Lambda aliases (**NEW V19**)
- **Notes:**
  - A contract change and its consumers ship in one PR. Independence is enforced by image-import checks (`deploy/v1/check_runtime.py`), owner lanes and release identity. The short encoder runs the **worker** image. Source: `final-report/src/50-devops.md`; `docs/execution/aws/v2/lambda-short-encodes.md`.
  - Honest limit: one shared lockfile and stack, and no branch protection or staging (AISS-04).

**S33 · Diagram · 55 s · 5b · — · Guruprasath**
- **Headline:** Changed lanes on pull requests; everything before Main
- **On slide:** CI flow (**NEW V20**, from `showcase-prep/content/delivery.json` "CI: decide and verify"). Callouts: "25 jobs · 7 min" · "≥80% / 90% coverage"
- **Notes:**
  - PRs to `dev/closeout` select the changed-owner lanes. Shared or unknown inputs trigger full verification. Main always runs full. Source: `docs/ci/policy.md`; `scripts/ci/policy.py`.
  - Latest green CI run 39733112331: 25 passed / 3 intentional skips. The historical full run took 7m09s. Source: `research/sections-5-6-demo.md` snapshot.

**S34 · Diagram (build ×2) · 75 s · 5b · T4 · Guruprasath**
- **Headline:** Promote exactly the scanned bytes, with automatic restore
- **On slide:** CD flow (**NEW V21**): exact-source admission → OIDC → stack update → scan → promote alias → owner smoke → restore on fail → upload-to-play smoke
- **Notes:**
  - Builds: (1) admission and identity (source SHA → config ID → manifest digest → alias), (2) release, smoke and restore. There are no stored AWS keys. Source: `scripts/ci/cd.sh`; `scripts/aws/v1/proof/release_plan.py`.
  - The release-time target was missed: 10.1–10.3 min vs 10 min; a later run took 9m39s, or 15m38s with the upload smoke. Source: `docs/results/actual-vs-target.md` DP-1. Chart: → B10.

**S35 · Diagram (tool row) · 40 s · 5b · T4 · Guruprasath · CUT-2 (to backup)**
- **Headline:** Fixable findings block releases; accepted ones stay visible
- **On slide:** A row of 6 gates: CodeQL · Trivy · ECR scan · ZAP (local) · gitleaks · Ruff S. Each has a one-word role.
- **Notes:** CodeQL: 12 High dismissed with reasons, 0 fixed. ZAP: 8 Low + 8 informational, local only. CVE-2025-52290 (FFmpeg) is accepted-unfixed with a rationale. Source: `docs/ci/policy.md`; `docs/execution/aws/v1/scan-accepted-unfixed-20261017.json`. Detail: → B18.

**S36 · Diagram (finding timeline) · 80 s · 5c · T4 · Guruprasath**
- **Headline:** Our security gate blocked its own fix
- **On slide:** Timeline (**NEW V22**): run ✗ (rollback image CVE) → rule "replaced baseline = retained" → run ✗ (login 503, cold DB) → wake retry → run ✓
- **Notes:**
  - CD 39532075705: the candidate was clean, but the running rollback image failed on certifi (GHSA-6q48-6c7w-9gw2) because the advisory arrived after it shipped. Fix: a replaced baseline is marked `RETAINED_FIXABLE`, while candidates and kept images stay strict. Source: `docs/results/engineering-20261021/delivery-c7c489c.json`.
  - CD 39542434067 then failed with `login:503`, because no migration had woken Aurora. The retry was scoped to the DB-wake login. 39545554380 went green, with the job done 101.2 s after acceptance.

**S37 · Diagram (finding timeline) · 45 s · 5c · T4 · Guruprasath**
- **Headline:** Splitting the database also split the wake-up
- **On slide:** Three ✗ runs (`processing-jobs:503`) → both services retried → ✓ 39733859422
- **Notes:** After AD-29, waking Media no longer wakes Processing. The smoke now retries the first call of each service on 5/10/15 s backoff within 180 s, and records every attempt. Source: `scripts/aws/v1/public_smoke.py`; runs 39728501166 / 39729654137 / 39731426830. A green run alone does not prove the retry fired.

**S38 · Statement (3 chips) · 45 s · 5c · — · Guruprasath · CUT-1**
- **Headline:** Cloud surprises became regression tests
- **On slide:** Three chips: "Lambda capped at 3008 MB" · "Resume after rollback" · "Released migrations frozen"
- **Notes:** Runs 39596145564 and 39600906024 (21 Oct); 39412315002 (20 Oct, migration bytes guard). Source: `research/sections-5-6-demo.md` §5(c) table.

## §6 Demo — budget 480 s talk + 120 s Q&A (pre-recorded clips)

Clip timings come from `research/sections-5-6-demo.md` §6. Total: 460 s footage + 20 s intros = 480 s.

**S39 · Diagram (demo map) · 10 s · 6a/6b · — · Long**
- **Headline:** Six clips: three journeys, three qualities
- **On slide:** Grid (**NEW V24**): D1 upload/play · D2 Publisher · D3 ownership | D4 scaling · D5 performance · D6 pipeline
- **Notes:** Say "All recorded on dc2-live; trimmed waits are captioned with real times."

**S40 · Clip D1 · 100 s (+2 s intro) · 6a · — · Ibrahim (voice-over)**
- **Headline:** D1 — An owner uploads once and plays it back
- **On slide:** Video `clips/D1.mp4` · "UC-1 · UC-2 · UC-3"
- **Notes:** Intro: "Watch the status change, then real playback." Keep the job ID for D2/D3.

**S41 · Clip D2 · 70 s (+2 s) · 6a · T1 · Long**
- **Headline:** D2 — A second application publishes through the contract
- **On slide:** Video `clips/D2.mp4` · "UC-5 · 0 imports · 0 DB credentials"
- **Notes:** Intro: "Publisher is a separate client and needs no backend access."

**S42 · Clip D3 · 45 s (+2 s) · 6a · T2 · Long**
- **Headline:** D3 — Knowing an ID is not enough
- **On slide:** Video `clips/D3.mp4` · "owner ✓ · other user ✗ · anonymous ✗"
- **Notes:** The expected results were 404 for a foreign user and 401 for an anonymous request (historical LV-6). Show the captured codes.

**S43 · Clip D4 · 110 s (+3 s) · 6b scalability · T3 · Guruprasath**
- **Headline:** D4 — Capacity follows work: 0 → 3 → 0
- **On slide:** Video `clips/D4.mp4` · "Fargate cap 3 · Lambda cap 2"
- **Notes:** Intro: "Watch the task count rise and return to zero." Large clips are padded above 64 MiB to force the Fargate lane. The historical inset shows 1.449× at 2 workers (miss, target 1.6×) and 2.347× at 3 (pass, target 2.1×). If asked: → B09.

**S44 · Clip D5 · 65 s (+3 s) · 6b performance · T4 · Long**
- **Headline:** D5 — A repeatable scripted load test
- **On slide:** Video `clips/D5.mp4` · "this run vs historical: p90 58.2 ms / 700 ms"
- **Notes:** The workload is 10 users × 60 s from a laptop through the public edge. That is not the in-region benchmark (9,000 req, 50 users, 0 errors; PF-1). Show the actual count, p90 and errors.

**S45 · Clip D6 · 70 s (+3 s) · 6b maintainability · T4 · Long**
- **Headline:** D6 — Every change carries test and artifact evidence
- **On slide:** Video `clips/D6.mp4` · "CI 39733112331 → CD 39733859422"
- **Notes:** Show the same SHA, the admission, the deploy and the upload smoke, plus a Security-tab capture with its date (or a "footage missing" label).

## Closing

**S46 · Statement (4 tiles recap) · 25 s · — · T1–T4 · Long**
- **Headline:** Reusable, correct at boundaries, cheap idle, honestly measured
- **On slide:** The four S05 tiles, each with one proof: "Publisher" · "outbox/lease" · "0→3→0" · "kept misses"
- **Notes:** Close with "Questions?" and leave this slide up during Q&A. Jump to backups by number.

---

## BACKUP appendix (Q&A; not timed)

| ID | Question it answers | Visual / content | Source |
|---|---|---|---|
| B01 | "What is still open?" | AISS-01..05 table: impact · owner · next step | `final-report/src/36-other-limitations.md` |
| B02 | "Are these hours real?" | Effort ledger table (11/12 pd each, 33 vs 31 pd) | `project-documentation/effort-ledger.md` |
| B03 | "What evidence is missing?" | NOT RUN list: lost-entry timing, duplicate-output after a kill, restore drill, actual bill | AISS-05 |
| B04 | "Why call it a platform?" | Publisher numbers + "no external adoption claimed" | `final-report/src/40-quality.md` |
| B05 | "What exactly is in scope?" | `final-report/figures/report-use-cases.png` | `10-introduction.md` |
| B06 | "Why not split identity or delivery?" | Account + Asset join stays local | `docs/architecture/ddd.md` §3; AD-01 |
| B07 | "Are all these Lambdas microservices?" | Service = rules + data + release unit; 2 services, 11 functions | `30-logical.md` §Nodes |
| B08 | "Exactly-once? CQRS? Event sourcing?" | At-least-once + inbox + fences; snapshot projection | `docs/architecture/use-case-design.md`; AD-21 |
| B09 | "Did scaling and the short lane meet targets?" | `actual-vs-target.png` panel A + sl1021 numbers, `meets_keep_rule=false` | `docs/results/actual-vs-target.md`; `short-lane-sl1021.json` |
| B10 | "How long does a release take?" | `actual-vs-target.png` panel B | DP-1..DP-4 |
| B11 | "Do separate DBs remove all coupling?" | Remaining coupling: authorizer, contracts, shared stack/VPC | `media/authorizer.py`; AD-23/29 |
| B12 | "Show the full context map" | `docs/architecture/img/ddd-context-map.svg` | `ddd.md` §7 |
| B13 | "What happens on retry?" | `docs/architecture/img/views-job-states.svg` (cancel = projection state) | `views.md` §5 |
| B14 | "What does it cost?" | Idle model USD 3–5/mo, budget alarms, per-encode compute; "bill not established" | AD-27; `docs/execution/aws/v1/cost-inputs.json` |
| B15 | "Is a public-subnet encoder safe?" "No NAT?" | No inbound SG rules; IPv6 egress + S3 endpoint | `views.md` §§3.1/3.4; AD-18 |
| B16 | "Is the DB highly available? Rollback of schema?" | Single instance per cluster; additive migrations only (AISS-03) | AD-29; `deploy-runbook.md` |
| B17 | "Show the tables" | `views-er-media.svg`, `views-er-processing.svg` | `docs/architecture/views.md` §4 |
| B18 | "Are security alerts resolved?" | Gate table + 12 High dismissals + accepted-unfixed file | `docs/ci/policy.md` |
| B19 | "What if a worker dies or SQS loses a message?" | Lease expiry → failed → owner retry; SQL repair rebuilds work (bound unmeasured) | `processing/recovery.py`; AD-27 |
| B20 | "Full CI/CD diagram" | `final-report/figures/report-cicd.png` | `report-cicd.mmd` |

## Visuals that do not exist yet (to make in Stage 4)

All are Mermaid or SVG in `presentation/deck/diagrams/`, using the STYLE §3 palette, landscape, with ≤ 12 nodes per frame.

| ID | Slide | What it must show | Start from |
|---|---|---|---|
| V1 | S03 | Platform context: people → 2 clients → public API → Media/Processing (async arrow) → S3; operators. "Viewers" relabelled as owners. | `final-report/figures/platform-context.png` (layout only) |
| V2 | S04 | As-built right panel: 2 clients → Gateway/authorizer → Media (blue) ⇢ SQS ⇢ Processing (amber); 2 Aurora; S3; Lambda + Fargate encoders | `report-logical.mmd`; left half of `architecture-before-after.png` |
| V3 | S05/S46 | Four theme tiles with icons, reused as a corner badge | new (CSS) |
| V4 | S07 | Milestone strip, 4–22 Oct plus 26 Oct marker, with one slip marked | `report-schedule.mmd` (simplify) |
| V6 | S10 | Three driver tiles | new (CSS) |
| V7 | S12 | Landscape logical detail with 4 build frames, separate DB per context, shared-kernel strip | `figures/src/report-logical.mmd` |
| V8 | S14 | Horizontal outbox → SQS → inbox chain with a result/projection return path; greyed "before" mini-panel | `figures/src/report-dp2-handoff.mmd` |
| V9 | S15 | Identity before/after, 2 panels, ≤ 5 nodes each | `figures/src/report-dp3-identity.mmd` |
| V10 | S16 | Side-by-side context map: Asset context ↔ Job context, 5 message kinds, published language + shared kernel | `figures/src/report-context-map.mmd` |
| V11 | S17 | Two aggregate cards with 3 invariants each | `docs/architecture/ddd.md` §§3–4 |
| V12 | S19 | Projection version timeline: applied / ignored / rejected | `media/projections.py` |
| V13 | S20 | Producer 3-step + consumer 2-path flow, both clients highlighted | `figures/src/use-case-design-06-*.mmd` (subset) |
| V14 | S22 | 4 build frames of `aws-topology.svg` (layer opacity) | `showcase-prep/assets/aws-topology.svg` |
| V15 | S24 | Two execution lanes: size filter, Lambda probe, fenced redirect, Fargate 0–3, shared lease pipeline | `figures/src/report-seq-encode.mmd` (yellow note made explicit) |
| V16 | S25 | Big-number card styling (pass/miss colours, receipt chip) | new (CSS) |
| V17 | S26 | Two DB cylinders with key tables + roles; optional S3 key layout for S27 | `views-er-*.svg` (summarised) |
| V18a–d | S28–S31 | Phase strip + 3 phase-split sequences (intake, handoff/encode, project/play), ≤ 6 lifelines each | `figures/src/report-seq-intake.mmd`, `report-seq-encode.mmd`, `report-seq-play.mmd` |
| V19 | S32 | Monorepo → 3 image repos → aliases per owner | `deploy/v1/*.Dockerfile`; `definitions.py` |
| V20 | S33 | CI: decide → lanes → full verification → artifacts | `showcase-prep/content/delivery.json` "CI: decide and verify" |
| V21 | S34 | CD: admission → identity chain → release → smoke → restore → upload smoke (2 builds) | `delivery.json` "CD: deploy and promote"; `report-cicd.mmd` |
| V22 | S36/S37 | Run timelines (✗/✓ with run IDs) for both findings | `delivery-c7c489c.json`; Actions snapshot |
| V24 | S39 | Demo map grid D1–D6 → UC / quality | new (CSS) |
| Clips | S40–S45 | D1–D6 MP4s plus poster JPGs | `research/sections-5-6-demo.md` §6 shot list |

(V5 has been dropped: S08 is a plain big-number slide built in CSS.)

## Totals vs budget

| Section | Slides (main) | Draft talk | Budget talk | Over | After CUT-1 | After CUT-2 |
|---|---|---|---|---|---|---|
| Title (S01) | 1 | 15 s | (from §1) | — | 15 | 15 |
| 1 Overview (S02–S06) | 5 | 160 s | 120 s | +33% | 140 (−S06) | 140 |
| 2 Conduct (S07–S09) | 3 | 95 s | 90 s | +6% | 95 | 70 (−S08) |
| 3 Logical (S10–S20) | 11 | 520 s | 420 s | +24% | 495 (−S18) | 450 (−S19) |
| 4 Physical (S21–S31) | 11 | 520 s | 420 s | +24% | 460 (−S23, −S27) | 440 (−S28) |
| 5 DevOps (S32–S38) | 7 | 400 s | 360 s | +11% | 355 (−S38) | 315 (−S35) |
| 6 Demo (S39–S45) | 7 | 480 s | 480 s | 0% | 480 | 480 |
| Closing (S46) | 1 | 25 s | (from Q&A) | — | 25 | 25 |
| **Total** | **46** | **2215 s = 36.9 min** | **1890 s = 31.5 min** | **+17%** | **2065 s = 34.4 min** | **1935 s = 32.3 min** |

After CUT-2, trim about 45 s more inside the notes, mostly in §3 and §4 narration. Q&A stays at 8.5 min, and the backup appendix has 20 slides.
