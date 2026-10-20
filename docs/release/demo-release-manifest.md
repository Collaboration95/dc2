# Demo release manifest: persistent V2-live (`dc2-live`)

**Status: FROZEN, team-accepted on 20 October 2026.** Guruprasath Gopal accepted the freeze on behalf of
Team 17. The freeze covers the code and images built from `daee44b`. Later commits that change only
documentation do not reopen it. The manifest was populated on 19 October 2026 from read-only queries
of the running environment and from the retained receipts. On 20 October the `live` alias of all ten
functions (Media version 5; ProcessingApi version 7; the other Processing functions version 6) and
the worker task definition (`dc2-live-worker:6`) were re-read, and both still match this file.
The manifest grants no permission to retag or deploy. `project2-v1`
(`f33b2a899fe2a1b7f1dab8480e03904d80838701`) stays immutable. Issue: #255.

Secret values, signed URLs, cookies, account IDs and private deployment-state files are not in this
file. The AWS account ID is written `ACCT`. A value shown as **unknown** was not read.

## Release identity

| Field | Value |
|---|---|
| Release identifier | `v2live-daee44b` (a label for this document, not a git tag) |
| Date populated | 2026-10-19 (UTC) |
| Mode | Persistent V2-live (AD-27), not the booked-session V1 |
| Source SHA | `daee44b61a6e8eef3f62505df69f8bfd076d68b8` (`origin/Main` and `origin/dev/closeout` at population time; PR #274) |
| Frontend | https://d1e1dpefd6hp9x.cloudfront.net |
| API | https://nqxf2hclhi.execute-api.ap-southeast-1.amazonaws.com (`/api/media/*`, `/api/processing/*`) |
| Environment / region | Stack `dc2-live`, `ap-southeast-1`, account `ACCT`; `UPDATE_COMPLETE` at 2026-10-19T17:00:49Z |
| Runtime flag | `DC2_RUNTIME=v1` on the worker task definition. Other feature flags: **unknown** (not enumerated) |
| Planned end of life | Teardown once, after 16 Nov 2026 (`cd.yml teardown`, `confirm=live`) |

## Images actually deployed

Read on 2026-10-19 from `aws lambda get-function --qualifier live` (the `live` alias of every
`dc2-live` function), `aws ecs describe-task-definition` and `aws ecr describe-images` (for the tag).
All three images carry the tag of CD run 39286933644, so they were built by that run from `daee44b`;
the build evidence is in that run's artifact `cd-deploy-live-39286933644` (not re-opened for this manifest).

| Owner | Image (the digest is the identity; the tag is only a label) | Used by |
|---|---|---|
| Media | `sha256:e06c14f7cc1e39e9f89f82f325281de196ee6b987c16db507d1076ab41533d1b`, tag `g39286933644x1-media` | 4 Lambdas at version 5: MediaApi, MediaAuthorizer, MediaResults, MediaRepair; also task definition `dc2-live-mediamigration:5` |
| Processing | `sha256:d1909533252d9e06a1b846bdd901d3ba1c5e2e61f9bead9c964dc61eb97ab756`, tag `g39286933644x1-processing` | ProcessingApi (version 7); ProcessingRepair, ProcessingLauncher, ProcessingS3Events, ProcessingEcsEvents, ProcessingCommands (version 6); also `dc2-live-processingmigration:6` |
| Finite encoder worker | `sha256:f865336630e1453a72bf94b33b2c90390d1e8bf01baa18d88944e5959daaa3d5`, tag `g39286933644x1-worker` | ECS task definition `dc2-live-worker:6` |

All ten Lambdas resolve to one Media or one Processing digest. Local compose IDs and mutable tags are
not part of this identity. The Processing service does not report its release number
(`/api/processing/health` prints `"version":"v1-dev"`), so these digests are the only reliable identity.

## Schema, migrations, contract

Heads are read from the migration directories at `daee44b`. The revision applied to the live Aurora
databases was **not** read for this manifest; the migration tasks in the table above ran during CD run
39286933644.

| Owner | Source head | Directory |
|---|---|---|
| Media (`media_db`) | `media_0008` (upload cleanup schedule) | `media/migrations/versions/` |
| Processing (`processing_db`) | `processing_0007` (launch reservations) | `processing/migrations/versions/` |
| Inherited Project 1 | `20260918_03` (not part of V2-live) | `migrations/versions/` |

Contract: `contracts/v1.py` `SCHEMA_VERSION = 1`, `EMIT_VERSION = 1`. Consumers accept N and N-1; the
policy is in `contracts/README.md`. Both databases are on one Aurora Serverless v2 cluster.

## Worker cap, resources, limits

| Item | Value |
|---|---|
| Encoder task | Fargate, 2 vCPU (`cpu` 2048) and 4 GiB (`memory` 4096) |
| Cap | `DC2_WORKER_CAP=3` (the deploy README calls it documentary process input; peak 3 tasks observed in #268 and in the #270 re-test) |
| Task lifetime | `WORKER_LIFETIME_SECONDS=1800` |
| Upload size cap | 100 MiB per file (`contracts/v1.py` `MAX_UPLOAD_BYTES`). Enforced at four points: the web app refuses larger files before uploading (`frontend/app.js`); Media refuses a larger declared `size_bytes` when it issues the upload grant; S3 refuses a body larger than the size the grant allows; the Publisher CLI reports the limit on 413. #229 verified the refusal on `dc2-live` |
| Scaling | 0 to N to 0 from SQL backlog (launcher), not queue depth |
| Per-stage limits, Lambda memory and timeouts, reserved concurrency | **unknown** (not read; see `deploy/aws/v1/template.json`) |
| Fixtures | The #270 burst used a synthetic 20 s 640x360 clip, 303,113 bytes, sha256 `d71114c2384828ef7f70af372aa383d4e694ae74e7005f6364b7ada5b1d36987`. The #268 clips (`clip400/500/600`) are not hashed in their receipt: **unknown**. #229 used its own probes |

## Source verification

| Check | Run | Result |
|---|---|---|
| CI on Main, exact SHA `daee44b` | [39278870533](https://github.com/Collaboration95/dc2/actions/runs/39278870533) (push, attempt 2) | **success on rerun**. The failure of attempt 1 was not investigated here (the v2live README finding F4 records one earlier flake in `test_rehearsal_includes_the_short_encode_comparison`) |
| CD deploy to `dc2-live` | [39286933644](https://github.com/Collaboration95/dc2/actions/runs/39286933644) (workflow_run of that CI) | **success**: gate job 6 s, `deploy live` 23m33s |
| Image scan (zero fixable HIGH/CRITICAL) | CI image scans (#251) | Part of the CI above; the per-image report was not re-read: **unknown** |

## Acceptance rows

| Item | Result | Source and receipt | Limits |
|---|---|---|---|
| #229 AWS security negatives | **PASS** | PR #266; [`s229-live-results.md`](../execution/aws/v1/evidence/s229-live-results.md), [`cloud-proof-s229live.json`](../execution/aws/v1/evidence/cloud-proof-s229live.json); evidence-index S11 | Run on `dc2-live` before the final deploy of `daee44b`; not repeated on this exact SHA |
| #238 scale 0 to 3 to 0 | **PASS** | PR #268; evidence-index Q7m; [`scaling-and-backlog.json`](../execution/aws/v1/evidence/v2live-verify-20261019/scaling-and-backlog.json) | Measured on earlier sources (before #272 and #273), not on `daee44b` |
| #237 queue wait target of 20 s | **FAIL (honest miss)** | Same receipt: queued to processing about 37 s, of which Fargate start 25.6 s median (n=12) | Target not revised |
| #238 Aurora auto-pause | **PASS** | Before #273 the cluster sat at 0.5 ACU for about 2 h (Q7n). On `daee44b`, `ServerlessDatabaseCapacity` (1-min max) read 0.0 at 18:07Z on 19 Oct, about 56 min after the #270 burst's last upload, as the first-hour rescan backoff predicts | Coordinator's CloudWatch poll every 3 min. New uploads keep it awake for about an hour after their grants expire; the few mid-backoff rescans after that (64 min, 128 min, 256 min) still wake it briefly before the 6 h grid (#273) takes over |
| #186 backlog scaling | PASS at cap 3 only | 9 clips, 239 s, 2.26 jobs/min, peak 3 (Q7m) | One run, fixed cap, no 1/2/3 comparison; the 2.5x speedup is against a calculated serial baseline. The V1 2-worker FAIL (1.449x against 1.6x) is unchanged |
| #186 rollback proof | **PASS (restored)** | CD run [39271754470](https://github.com/Collaboration95/dc2/actions/runs/39271754470), `bad_candidate=true`, outcome `restored`; [receipt](../execution/aws/v1/evidence/v2live-verify-20261019/cd-39271754470-bad-candidate-rollback/release-processing.json) (Q7l) | Proven on source `7928b7c`, **not** on `daee44b` |
| #270 stale duplicate work messages | **PASS** | PR #272 fix; re-test on `daee44b`: 9 of 9 done, 18 sends, ProcessingWork 0 visible and 0 in flight at 17:11:01Z with no purge (Q7o); [`burst-270-recheck.json`](../execution/aws/v1/evidence/v2live-verify-20261019/burst-270-recheck.json) | One run; duplicates are still sent, now deleted; the worker writes no log lines; the deploy smoke's empty-queue guard was not re-run |
| Deploy upload-to-playback smoke on `daee44b` | Inside CD run 39286933644 (job green); the smoke JSON was not re-read: **unknown** | | |
| CloudWatch alarms | 13 of 13 `OK` at 14:57Z on 19 Oct (earlier source); not re-read on `daee44b`: **unknown** | | |

## Rollback reference

- Pipeline path: `.github/workflows/cd.yml` operation `release` with `owner=media` or `owner=processing`.
  With `bad_candidate=true` the runner ships a deliberately failing candidate and restores the previous
  aliases when its smoke fails. Runbook: `docs/execution/aws/v1/deploy-runbook.md`, sections "CD
  workflow", "Release proof on an existing stack" and "Release CLI actions" (manual alias rollback).
- What was tested: restore after a bad Processing candidate (run 39271754470, source `7928b7c`). A
  restore on the `daee44b` candidate was **not** tested.
- Previous images: Processing before the 19 Oct releases was the image of source `79b5d12`
  (digest prefix `sha256:bcaf38b5...`, per the v2live-verify README). Media's previous digest:
  **unknown**.
- Owner or operator for a rollback: the cloud operator (profile `dc2-agent`) or the CD OIDC role. A
  named individual is **unknown** (not decided in the repository).

## Known limitations and open issues

- #271 (open, accepted as a known limitation on 20 Oct): Media finalize returns 503 when S3 refused an
  oversized upload; it should be a 4xx. The 100 MiB cap still holds: the oversized upload is refused and
  never adopted (#229), and the web app refuses such a file before it uploads. Not fixed, because a fix
  would reopen the freeze.
- Queue wait (about 37 s) misses the 20 s target; Aurora pauses about an hour after the last upload (above).
- Backlog scaling has one measurement at a fixed cap of 3.
- Duplicate `ProcessingWork` sends (repair cadence 45 s) are expected under load; they are now drained.
- Parallel Publisher processes need one cookie jar each (client property).
- Whether `dc2-live` is up at any later moment is not recorded by this file.
- Demo and recording material (#254) is **not** attached: no recording identifier exists here, and a
  recording must state the source it was made from.
- V1 evidence (`project2-v1`, r1017b, r1018b, r1019a) belongs to the booked-session mode and is not
  carried over silently; two V1 FAILs (1.449x scaling, 10.1 to 10.3 min Processing release) stand.

## Freeze checklist

Accepted on 20 October 2026 by Guruprasath Gopal on behalf of Team 17. Steps 4 and 5 are recorded as follows.

| # | Step | State |
|---|---|---|
| 1 | #243 and #244 resolved; relevant regressions verified | Both issues are closed; regression runs are in the CI above |
| 2 | One integrated candidate (`daee44b`) with exact-source CI and CD | Done (runs above) |
| 3 | #229 and #238 acceptance, or an explicit limitation | #229 PASS; #238 PASS except the queue-wait miss (#237) |
| 4 | Demo playback and fallback confirmed; manifest, images, config and fixture agree | Manifest, images and config re-read on 20 Oct and they agree. The recorded fallback (#254) is deferred; it will be captured from this frozen release |
| 5 | Team release acceptance recorded; any extra tag through the normal authorized path | **Done** (20 Oct, on behalf of the team). No new tag |
| 6 | After freeze, only blocker repairs with affected verification and an updated manifest | **In force** from 20 Oct |

The freeze reopens if any of these change: the `live` alias of any function, the worker task definition
revision, a non-documentation change on Main, a migration head, the contract version, or the worker cap.
