# Evidence index

Every quality scenario in proposal section 3.4 and every security control in section 3.3, with the
result against the target as written. Targets were not revised. A FAIL is reported as a FAIL. Nothing
was rerun to turn a FAIL into a PASS; where a first attempt failed and a rerun passed, both are stated.

Last updated 18 October 2026. Section numbers 3.3 and 3.4 are the **Team17 proposal's** ("How the
implementation demonstrates the course areas" and "Quality scenarios and initial targets"). The original
course report template discusses quality attributes in its section 4 (4.1 Performance, 4.2 Availability,
4.3 Security, 4.4 Extensibility and Maintainability) and architectural limitations in its 3.4; when the
report is written, map these rows to the template, not to the proposal numbers. Backs the evidence slides.

Newer successful receipts (`r1019a`, the V2-live smoke and the exact-source CI run of 18 October) are
archived with hashes and source SHAs in
[`execution/aws/v1/evidence/archive-20261018/`](execution/aws/v1/evidence/archive-20261018/README.md),
and a compact actual-versus-target table with a figure is in
[`results/actual-vs-target.md`](results/actual-vs-target.md). They are added below as new rows; the
older rows and their FAIL and NOT_RUN outcomes are unchanged.

## How to read this

| Environment | Meaning |
|---|---|
| **AWS r1017b** | Live run on 17 October, ap-southeast-1, operator CLI. Receipts: [`cloud-proof-r1017b.json`](execution/aws/v1/evidence/cloud-proof-r1017b.json), [`cloud-proof-r1017bmedia.json`](execution/aws/v1/evidence/cloud-proof-r1017bmedia.json). |
| **AWS r1018b** | Live run on 17 to 18 October, same account and region, CD deploy plus laptop operator. Receipts: [`cloud-proof-r1018b.json`](execution/aws/v1/evidence/cloud-proof-r1018b.json), [`cloud-proof-r1018bmedia.json`](execution/aws/v1/evidence/cloud-proof-r1018bmedia.json), narrative [`r1018b-results.md`](execution/aws/v1/evidence/r1018b-results.md). `r1018a` was an earlier partial attempt, described under "Runs that did not count". |
| **Local pre-V1** | The Redis/RQ design (before the V1 rebuild) on a local Lima VM, full runs on 12 and 13 October. Real PostgreSQL, FFmpeg and Redis. Not the shipped architecture. |
| **Local V1 emulated** | The shipped V1 code on real PostgreSQL 16 and FFmpeg, with Moto for S3/SQS, an in-process Gateway bridge and (for recovery tests) a simulated clock. No IAM, Gateway, Lambda, Fargate or Aurora. |
| **Code** | Read from source or the rendered template. No runtime evidence. |
| **NOT_RUN** | Implemented, never run in that environment. |

Local results are never AWS results. Both live receipts carry their own `not_proven` list: Cost Explorer
is an estimate, latency came from a Fargate generator in the same region (not from users), and fakes
and CI are not AWS evidence.

## Summary against targets

| Scenario | AWS verdict | Note |
|---|---|---|
| Scalability, 2 workers at least 1.6x | **FAIL** (1.449x) | 6-clip backlog, not 30. Local pre-V1 passed at 2.03x. |
| Scalability, 3 workers at least 2.1x | PASS (2.347x) | Same 6-clip backlog. |
| Status p90 at most 700 ms | PASS (58.2 ms) | In-region generator. |
| Login p90 under 2 s | PASS (178.0 ms) | 20 samples, one per user. |
| Worker kill within 5 min | PASS (reaction 5.8 s) | Duplicate-output check not in the receipt. |
| Lost queue entry within 2 min | NOT_RUN on AWS | Local only, simulated clock. |
| Processing outage (failure case 3) | PASS for the consumer only | Not a full Processing outage. |
| Deployability, Processing at most 10 min | **FAIL, marginal** (10.1 to 10.3 min in CD) | Media 8.0 to 8.2 min. Post-release smoke never passed. |
| Security negatives, 100% rejected | PASS on every AWS check run | S2, S5c, S6 and S7 have no AWS run. |
| 0 fixable HIGH/CRITICAL image findings | PASS | 14 unfixed findings accepted, one CRITICAL. |
| Reuse, 0 imports and 0 DB credentials | PASS | Effort in person-days not measured. |
| Spend | PENDING | Cost Explorer shows 0.00 USD (credits). |
| CD pipeline green end to end | **PASS in `r1019a`** (deploy, Processing release with upload smoke, teardown `CLEAN`), after the `r1018b` failures | See Q7i and "Pipeline runs on AWS". The deliberate bad-candidate dispatch was cancelled; #229 and #238 acceptance are incomplete. |

## Quality scenarios (proposal section 3.4)

| # | Target | Result | PASS/FAIL | Environment | Receipt |
|---|---|---|---|---|---|
| Q1a | Scalability: 30 identical 60 s 720p clips, 1/2/3 workers at 2 vCPU. 2 workers at least 1.6x | 4.749 jobs/min against 2.337 for one worker: **2.032x** (median of three batches per worker count) | PASS | Local pre-V1 | [`scaling-validation.md`](execution/reviews/scaling-validation.md), [`scaling-f46599f/index.json`](execution/evidence/scaling-f46599f/index.json) |
| Q1b | 3 workers at least 2.1x | 6.743 jobs/min: **2.885x** | PASS | Local pre-V1 | same |
| Q1c | Median queue wait falls at each step; 0 failed jobs | Pooled median queue wait 375.4 / 176.0 / 120.4 s; 270 of 270 jobs succeeded | PASS | Local pre-V1 | same |
| Q1d | Same targets on AWS, cap 1/2/3, backlog of **6** clips (36 MB fixture) | 0.483 / 0.700 / 1.134 jobs/min; 0 failures; median queue wait 274.3 / 135.7 / 9.6 s | see next two rows; queue wait PASS | AWS r1018b | [`cloud-proof-r1018b.json`](execution/aws/v1/evidence/cloud-proof-r1018b.json) `#185` |
| Q1e | 2 workers at least 1.6x (AWS) | **1.449x** | **FAIL** | AWS r1018b | `backlog-compare`, `speedup.2` |
| Q1f | 3 workers at least 2.1x (AWS) | **2.347x** | PASS | AWS r1018b | `backlog-compare`, `speedup.3` |
| Q1g | Scaling on the V1 design, local | Not measured. Local V1 has no 30-clip run; the V1 capacity logic is simulated only | NOT_RUN | Local V1 emulated | `tests/aws/v1/test_capacity_backlog.py` (simulation, not a result) |
| Q2 | Performance: 50 users poll status for 3 min, p90 at most 700 ms, under 1% errors | p90 605.0 / 580.2 / 544.0 ms over three repeats; 8,999 / 8,999 / 9,000 requests; 0 errors | PASS | Local pre-V1 | [`performance-validation.md`](execution/reviews/performance-validation.md), [`performance-f46599f/index.json`](execution/evidence/performance-f46599f/index.json) |
| Q2 | same | p90 **58.2 ms**; 9,000 requests; 0 errors; 0 throttled; max 2,786 ms | PASS | AWS r1017b | `cloud-proof-r1017b.json` `#66` `generator.status_cycle` |
| Q3 | 20 concurrent logins, p90 under 2 s | p90 1,873.0 / 1,888.1 / 1,898.5 ms; 2,468 / 2,387 / 2,374 requests; 0 errors. The margin is 101 to 127 ms | PASS | Local pre-V1 | `performance-validation.md` |
| Q3 | same | p90 **178.0 ms** from **20** samples (one per user); 0 errors. Hash cost 10 is configured in source, not read back from the deployed service | PASS | AWS r1017b | `#66` `generator.login_cycle` |
| Q4a | Availability: worker killed mid-encode; re-queued or failed within 5 min; retry succeeds; no duplicate outputs | Visibility of the kill 69.2 s; whole recovery run 190.6 s | PASS | Local pre-V1 | [`recovery.json`](execution/evidence/local-workflow-422609b/recovery.json), [`handoff.md`](execution/handoff.md) V2 row |
| Q4b | same | Encoder task stopped mid-encode; reaction **5.8 s** against the 300 s gate; job ended `done` with 1 interrupted attempt; step took 93.5 s. `stop_to_done_seconds` is null (not recorded). The receipt does not check for duplicate outputs | PASS for the time gate; duplicate-output check not evidenced | AWS r1017b | `#64` `recovery` |
| Q4c | same | Stopped ECS task fails its live attempt before the lease expires; interrupted work resolved within 300 s at lease 60 s and 240 s (simulated clock) | PASS | Local V1 emulated | `tests/v1/test_delivery_recovery_sql.py::test_interrupted_work_is_resolved_within_300_seconds`, `::test_a_stopped_task_fails_its_live_attempt_before_the_lease_expires` |
| Q5a | Queue entry lost after the job is committed; re-enqueued within 2 min | Queue repair 23.5 s | PASS | Local pre-V1 | `recovery.json`, `handoff.md` V2 row |
| Q5b | same | Lost work message re-sent after 45 to 120 s in 15 s simulated steps; repair interval never grows. Worst case by construction: interval plus one 60 s tick plus slack, asserted at most 120 s | PASS (simulated) | Local V1 emulated | `tests/v1/test_delivery_recovery_sql.py::test_lost_committed_work_is_requeued_within_120_seconds`, `::test_repair_interval_never_grows_so_a_late_loss_is_still_found_inside_120_seconds` |
| Q5c | same | No AWS receipt removes a queue message and times the repair. The 120 s figure on AWS is a design bound, not a measurement | NOT_RUN | AWS | `processing/messaging.py:REPAIR_INTERVAL_SECONDS` (Code) |
| Q5d | Always-on idle gate (AD-27) and the 120 s target | The 120 s / 300 s targets are unchanged and apply while the idle markers are healthy. Four cases differ: (1) healthy markers: the next minute tick sees pending work; (2) SSM read failure: the tick fails open to SQL; (3) a lost marker write followed by a healthy read of the old quiet snapshot: ticks may skip SQL until the snapshot is 30 min old, so discovery is bounded by `MAX_QUIET_SECONDS` plus tick alignment and invocation time, not by 120 s; (4) the missing `ProcessingApi` writer (#244), fixed separately, needs no SSM failure. Fixing (4) does not prove an unconditional 120 s guarantee | PASS (local, simulated clock and fake SSM; not AWS timing) | Local V1 emulated; AWS failure injection NOT_RUN | `tests/v1/test_activity_gate.py::test_a_lost_touch_leaves_early_ticks_skipping_until_the_snapshot_ages_out`, `::test_a_direct_processing_mutation_touches_before_it_commits_and_repair_then_runs_sql` |
| Q5d | Poison messages end in the DLQ, not in a loop | A provoked poison message reached the DLQ after 2,101 s and was removed; all three queues empty afterwards. This is not the lost-entry scenario | PASS | AWS r1017b | `#64` `dlq` |
| Q6a | Availability failure case 3 (section 3.3): temporary Processing outage while Media accepts uploads (#196) | Command consumer off for 48 s. Media answered 202, job status `accepted`, command held in outbox and queue, job `done` 58.9 s after re-enable. First attempt FAIL in 1 s (`Insufficient request deadline`, a harness bug fixed in #218); rerun PASS | PASS on rerun. **Consumer only**: the Processing API stayed up, so this is not a full Processing outage | AWS r1018b | `cloud-proof-r1018b.json` `#196` `processing-down` |
| Q6b | same | Media never calls Processing; the images lack the opposite domain package; the Processing-down harness runs against the simulated account | PASS (structure) | Local V1 emulated / Code | `deploy/v1/check_runtime.py`, `tests/aws/v1/test_isolation_unattended.py` |
| Q6c | same, earlier design | Redis/RQ restart convergence with surviving queue metadata and no duplicate primary | PASS | Local pre-V1 | `handoff.md` V2 row |
| Q7a | Deployability: release a new Processing version alone, deployed and smoke-tested in at most 10 min; Media container and `media_db` migrations unchanged | `Release` step (build, push, scan, plan, promote, release smoke, close) **10.3, 10.2, 10.1 min** in three CD rounds. Peer aliases did not move | **FAIL, marginal** (0.1 to 0.3 min over) | AWS r1018b | [`r1018b-results.md`](execution/aws/v1/evidence/r1018b-results.md) "Independent releases" |
| Q7b | same | Operator-CLI `promote-good` **322.5 s** (gate 600 s), peer unchanged at all four snapshots, schema read in-VPC. The image build ran before this step and is not in the 322.5 s | PASS for the promote step only | AWS r1017b | `#65` `promote-good`, `owner-isolation` |
| Q7c | Same scenario for Media (not in the proposal target, which names Processing) | `Release` step **8.0, 8.0, 8.2 min**; only Media's 4 functions changed | PASS | AWS r1018b | `r1018b-results.md` |
| Q7d | Upload-to-playback smoke after a release | **Did not pass in any of the five runs that reached it** (three different causes: Gateway 429 after `session open`, a purged ECS task, and a stale command reaching the queue after the encoder had exited). Fixes #220, #221, #222 merged; #223 not fixed. Adds 2.7 to 4.4 min (18 min when it waited out the 900 s timeout) | **FAIL** | AWS r1018b | `r1018b-results.md` |
| Q7e | Rollback of a good promotion (Processing) | `rollback` 250.7 s (gate 600 s), peer unchanged, schema not reversed | PASS | AWS r1017b | `#65` `rollback` |
| Q7f | Bad candidate restore, Processing | Candidate failed its smoke after 205.7 s, aliases restored in 54.8 s, total 260.5 s (gate 300 s), peer unchanged | PASS | AWS r1017b | `#65` `bad-candidate-restore` |
| Q7g | Rollback and bad-candidate restore, Media | Baseline 48.7 s, promote-good 246.8 s, `rollback` 251.8 s; bad candidate failed its smoke after 189.5 s, aliases restored in 47.0 s, peer unchanged; owner isolation 47.7 s | PASS | AWS r1018b (`r1018bmedia`) | [`cloud-proof-r1018bmedia.json`](execution/aws/v1/evidence/cloud-proof-r1018bmedia.json) `#65`; the earlier `r1017bmedia` receipt has `bad-candidate-restore` NOT_RUN |
| Q7h | The bad-candidate path inside the CD pipeline | Proven by the operator-run receipts above, not by a pipeline run. A CD dispatch with `bad_candidate=true` ([39089045496](https://github.com/Collaboration95/dc2/actions/runs/39089045496), source `784318636b690aac6ca64f0f8817ae7a15b6cae7`, 18 October) was **cancelled** during its `Release` step and produced no result | NOT_RUN in CD | | `r1018b-results.md` |
| Q7i | Processing release through CD, later run (added 18 October; does not replace Q7a or Q7d) | `r1019a`, run [39087966647](https://github.com/Collaboration95/dc2/actions/runs/39087966647), source `358d169d6b0d0fc0f1e5ce809ffc8f1ad02fc592`: `Release` step **9m39s**, promoted, post-release checks (health, anonymous-denied, login, jobs) PASS; the separate upload-to-playback smoke step took **5m59s** and PASSED (`seconds_to_terminal` 150.0). The two steps ran back to back (15m38s). The 322.5 s operator-CLI figure (Q7b), the `Release` step and the whole upload-smoked sequence are different timing boundaries | `Release` step PASS under 10 min; **an upload-smoked release inside 10 min is not shown**; Q7a stays FAIL; Q7d (smoke never passed in r1018b) stays FAIL and was fixed afterwards | AWS r1019a (CD) | [archive](execution/aws/v1/evidence/archive-20261018/README.md), [`release.json`](execution/aws/v1/evidence/archive-20261018/r1019a-release-39087966647/release.json) |
| Q7j | Persistent environment (V2-live, AD-27) deploy and upload-to-playback smoke from Main (added 18 October) | Run [39105817431](https://github.com/Collaboration95/dc2/actions/runs/39105817431), source `d2070db68c6b3545881eb948046b8e57f47e078e`: deploy steps all done; smoke PASS, `seconds_to_terminal` 123.8. Basic live evidence. Not completion of every #238 acceptance item (in-place update, scaling, pause, idle cost). Whether the environment is still running now is unverified | PASS (smoke only) | AWS V2-live | [archive](execution/aws/v1/evidence/archive-20261018/live-deploy-39105817431/cloud-proof-smoke-39105817431-1.json) |
| Q8 | Security: negative tests in section 3.3 all rejected; 0 fixable HIGH/CRITICAL image findings at release | Detail in the next table | see below | | |
| Q9 | Reusability: Publisher CLI against the published API, 0 imports from service code, 0 database credentials, within 2 person-days | See "Reuse" below | PASS on imports and credentials; effort NOT MEASURED | Code / Local / AWS | below |

## Security controls (proposal section 3.3)

| # | Control | Verified by (proposal) | Result | PASS/FAIL | Environment | Receipt |
|---|---|---|---|---|---|---|
| S1a | Public routes require a valid session; uploader becomes owner | Unauthenticated requests rejected | All six probed job routes (frontend and Gateway; Media, Processing, admin) returned 401 | PASS | AWS r1017b and r1018b | `#63` `anonymous-denied` |
| S1b | same | Session cookie properties | Cookie is host-only, HttpOnly, Secure, SameSite=Strict, served through CloudFront; `/me` 401 when anonymous, 200 after login. **r1018b first attempt FAIL**: login HTTP 429 0.13 s after `session open` (the Gateway still applied the closed 0/0 limit); rerun PASS | PASS on rerun (r1017b first time) | AWS | `#63` `session-roundtrip` |
| S1c | same | Tampered or expired token rejected | Cookie token tampering, expiry and password byte limit tests | PASS | Local V1 emulated | `tests/media/test_contract_security.py::test_cookie_token_tampering_expiry_and_password_byte_limit` |
| S2 | Owner checks in Media Management and Processing | User A cannot read, retry or play User B's assets | No two-user cross-read on AWS. The AWS `owner-isolation` step is about release isolation between services, not users. Local tests: cross-owner submit rejected before mutation; wrong owner source, job and output rejected; cross-owner edit stops before copy; wrong owner cannot finalize a reservation; owner in the SQL predicate. Processing's job lookup filters by owner | PASS (local) | **AWS NOT_RUN** | `tests/v1/test_messaging_sql.py::test_cross_owner_submit_rejected_before_mutation`, `tests/media/test_v1_projection.py::test_wrong_owner_source_job_and_output_rejected`, `::test_cross_owner_edit_stops_before_copy`, `tests/v1/test_direct_intake_s3.py::test_wrong_owner_cannot_finalize_or_observe_a_reservation`, `tests/processing/test_lifecycle.py::test_get_missing_owner_filtered` |
| S3a | Internal API requires a service token and is not publicly routed (V1: no internal HTTP API; queues and a Gateway-injected actor replace it, AD-06) | Forged and token-less calls rejected | Forged identity headers changed nothing (anonymous admin 401, authenticated admin 403, forged headers on jobs gave the same 200 as plain) | PASS | AWS r1017b and r1018b | `#63` `forged-identity` |
| S3b | same | Direct queue send rejected | Direct `SendMessage` to `MediaResults`, `ProcessingCommands`, `ProcessingWork`: 403 on all three, 0 messages accepted | PASS | AWS r1017b and r1018b | `#63` `sqs-direct-send` |
| S4 | Separate database roles | Each service's credentials refused on the other's database | Connecting to the other database: `InsufficientPrivilegeError`; DDL on own database as runtime role denied. 55.8 s in r1018b | PASS | AWS r1017b and r1018b | `#63` `cross-database` |
| S5a | Presigned, time-limited storage URLs; private storage | Expired and tampered URLs fail; no public listing | Foreign origin to S3 returns 403; the frontend origin is allowed for POST. Buckets: public access blocked, TLS-only policy | PASS (CORS); listing and URL expiry not probed | AWS (CORS); Code (buckets) | `#63` `cors-preflight`; `deploy/aws/v1/template.json` |
| S5b | same | Grant binds key, type, size and a 15-minute expiry; expired reservation refused and its bytes reclaimed; same-size different bytes fail the checksum | Tests pass | PASS | Local V1 emulated | `tests/v1/test_direct_intake_s3.py::test_grant_binds_key_type_size_and_a_short_expiry`, `::test_expired_reservation_is_refused_and_its_bytes_are_reclaimed`, `::test_same_size_different_bytes_fail_the_checksum` |
| S5c | same | Expired or tampered presigned GET against S3 | Not probed on AWS | NOT_RUN | AWS | none |
| S6 | Input checks on type and 100 MiB size | Invalid and oversized uploads rejected | Oversized and truncated objects refused at finalize (HTTP 422, no Asset and no outbox row created); the POST policy limits key, type and size. **Moto does not enforce `content-length-range`**, so the S3-side limit is not tested end to end | PASS (local, finalize check) | Local V1 emulated; AWS NOT_RUN | `tests/v1/test_direct_intake_s3.py::test_oversized_and_truncated_objects_are_refused_at_finalize`, `tests/media/test_direct_intake.py::test_post_policy_limits_key_type_and_size` |
| S7 | Only HTTPS is public; databases, queue and storage are private | External port scan | **No port scan was run.** The structure: CloudFront redirects HTTP to HTTPS; Aurora is `PubliclyAccessible: false`; no inbound rules on Fargate; SQS is IAM-gated. The `execute-api` URL is reachable directly, with no WAF | NOT_RUN (scan) | Code | [`views.md`](architecture/views.md) section 3.4; `deploy/aws/v1/template.json` |
| S8 | Secrets kept out of git and images | Secret scanning in the pipeline | gitleaks job green on the latest full run (allowlist `.gitleaks.toml`). Receipts are redacted; presigned query strings are stripped from captures | PASS | CI | run [39075571439](https://github.com/Collaboration95/dc2/actions/runs/39075571439) "Secret scan (gitleaks)" |
| S9 | Pipeline: failed tests and fixable HIGH/CRITICAL image findings block a release | Trivy on three images; ECR scan in each release | Three distinct scans: (1) CI Trivy (severity CRITICAL,HIGH, `ignore-unfixed: true`, exit code 1) passed on the **inherited** app, media and processing images, not the V1 artifacts; (2) from the #251 change on, the V1 image job also scans the three exact V1 images (media, processing, worker) with the same policy, retained as `v1-image-scans-<sha>` with source SHA and local image config ID (not a registry digest); runs before that change have no such scan; (3) release-time ECR scan of the promoted digest. Each `Release` step promoted, so the ECR scan gate passed against the allow list below | PASS | CI; AWS r1018b | run 39075571439; `r1018b-results.md` |
| S10 | Dynamic scan (OWASP ZAP) | Findings report-only | DAST job ran and finished; findings are **report-only**, they do not block | NOT a gate | CI | run 39075571439 "Exact-candidate DAST execution" |
| S11 | Rerun of the S2, S5a, S5c, S6 and S7 negatives on AWS (`evidence security`, #229): cross-user read/retry/playback, tampered and expired presigned URLs, 100 MiB limit against real S3 bytes, unsigned S3 access, external port scan, execute-api without CloudFront | Section 3.3 as above | **NOT_RUN**: the `r1019a` and live smoke receipts list #229 as NOT_RUN; the acceptance stays open under #229 | NOT_RUN | AWS | `evidence-229-<run>.json`, to be committed as `cloud-proof-<run>.json` `#229` when run |

### Image findings

| Item | Value |
|---|---|
| Fixable HIGH/CRITICAL | 0 at release (Trivy with `ignore-unfixed`; ECR gate in each release) |
| Accepted as unfixed | **14** ids, listed in [`scan-accepted-unfixed-20261017.json`](execution/aws/v1/scan-accepted-unfixed-20261017.json): libxml2 7, cjson 3, glibc 2, zlib 1, tiff 1 |
| Severity of the accepted set | One is **CRITICAL** (`CVE-2026-52490`, tiff). The file does not give the severity of the other 13 |
| Why accepted | No fixed version in Debian 13 (trixie) for the pinned `python:3.12-slim` base on 17 October; checked with an empty `apt list --upgradable` and the ECR basic scan |
| What the target says | "0 fixable HIGH/CRITICAL". The target is met by definition: these are unfixable today. They are still in the shipped images |
| Not in the retained receipts | The ids the ECR scan reported per release. The runbook says the release receipt records them; the committed `r1018b` receipts do not |
| Local packaging proof | [`local-images-7149324f99bf.json`](execution/aws/v1/evidence/local-images-7149324f99bf.json), [`local-images-f549435.json`](execution/aws/v1/evidence/local-images-f549435.json): non-root user, no ffmpeg in the API image, only the owning source in `/app`, no legacy modules. This is a packaging check, not a vulnerability scan; the receipt's `scan` stays `NOT_RUN` and the CI scan is a separate artifact |

## Scaling in detail

### Local pre-V1, 30 clips (Redis/RQ design)

Source `f46599f`, 13 October. Nine batches, three rotated repeats per worker count, each of 30 fresh
Assets from one 60 s 1280x720 H264/AAC fixture. Workers capped at 2 CPU and 1,536 MiB. The load
generator shared the Mac with the VM. 270 of 270 jobs succeeded with HLS.

| Workers | Median throughput, jobs/min | Range | Speedup | Target | Pooled median queue wait, s | Pooled median processing, s |
|---:|---:|---|---:|---|---:|---:|
| 1 | 2.337 | 2.309 to 2.347 | 1.000x | | 375.4 | 24.1 |
| 2 | 4.749 | 4.534 to 4.755 | **2.032x** | at least 1.6x, PASS | 176.0 | 22.9 |
| 3 | 6.743 | 6.659 to 6.836 | **2.885x** | at least 2.1x, PASS | 120.4 | 22.8 |

A first full invocation at `621c03a` FAILED (session expired at the eighth batch); its seven completed
batches were not spliced into the result ([`failed-scaling-621c03a`](execution/evidence/failed-scaling-621c03a/index.json)).

### AWS r1018b, 6 clips (V1 design)

One run per cap, one fixture (36,035,343 bytes), each encoder a 2 vCPU / 4 GiB Fargate task, backlog of
**6** (not 30). Cap 3 is the ceiling: the account's Fargate on-demand quota is 6 vCPU.

| Cap | Jobs/min | Speedup | Ideal | Target | Result | Drain speedup (from first encoder launch) | Median / p90 queue wait, s | Median / p90 processing, s | Billed encoder seconds | Launch waves |
|---:|---:|---:|---:|---|---|---:|---|---|---:|---:|
| 1 | 0.483 | 1.000x | 1.0 | | | 1.000x | 274.3 / 602.2 | 62.1 / 80.5 | 657.3 | 6 |
| 2 | 0.700 | **1.449x** | 2.0 | at least 1.6x | **FAIL** | 1.475x | 135.7 / 377.5 | 105.7 / 125.8 | 897.5 | 5 |
| 3 | 1.134 | **2.347x** | 3.0 | at least 2.1x | PASS | 2.448x | 9.6 / 184.8 | 80.5 / 128.1 | 830.3 | 4 |

0 failures, 0 non-zero encoder exits, 0 encoders left running in all three. Median queue wait fell at
each step (PASS). The harness verdict `backlog-compare` is FAIL.

**Likely cause of the cap-2 miss, from the receipt data.** This is an inference from the numbers; no
per-task CPU data was captured, so it is not proven.

| Observation | Number | What it rules in or out |
|---|---|---|
| Upload and ramp overhead | `elapsed_seconds` minus `drain_seconds` is 18.9 / 21.6 / 20.8 s at cap 1/2/3 | Small and similar across caps. The ramp is **not** the cause. Using the drain basis (which excludes it) cap 2 is still 1.475x, still below 1.6x |
| Per-task start overhead | Mean billed seconds per task minus median in-attempt time is about 47 s (cap 1), 44 s (cap 2), 58 s (cap 3) | A fixed cost of roughly 45 to 60 s per task (image pull, start, claim, upload) is paid by every task. It parallelises, so it does not explain the miss either, but it means a 6-job backlog gives little amplification |
| In-attempt time per job | Median 62.1 s (cap 1), **105.7 s (cap 2)**, 80.5 s (cap 3) | The same fixture and task size took 70% longer per job at cap 2 than at cap 1. This is where the speedup was lost |
| Not monotonic in concurrency | Cap 3 runs more tasks at once than cap 2 but its per-job time is lower (80.5 s) | Contention among concurrent tasks alone does not explain it |
| Spread of billed seconds | Cap 1: 97 to 118 s (tight). Cap 2: 99 to 171 s, five of six tasks above 144 s. Cap 3: 98 to 172 s, three above 160 s and three below 121 s | The cap-1 baseline was uniformly fast. If the baseline had been as variable as the other two, its throughput would probably have been lower and the ratios higher |
| Run-to-run variance of one task | r1017b `run-1`, one encoder, same fixture and size: 153.7 s billed. r1018b cap 1: 97 to 118 s | A single task's billed time varied by about 1.3x to 1.6x between runs. That alone can move a two-way ratio across the 1.6x line |
| Sample size | 6 jobs per cap, one run per cap | One slow pair of tasks changes cap 2 by a large fraction. The proposal's scalability scenario specifies a backlog of 30 clips; that was not run on AWS. Three rotated repeats per worker count were the team's local pre-V1 protocol, not an explicit proposal commitment, and one run per cap was done on AWS |

Reading: the most probable explanation is uncontrolled variation in how fast individual Fargate tasks
ran, combined with a 6-job backlog that is too small to average it out and a cap-1 baseline that
happened to be fast. This does not excuse the result. The target was 1.6x at two workers, the measured
value is 1.449x, and the proposal's 30-clip backlog (with repeats, as in the local protocol) that would have tested
it properly was not run on AWS. The local pre-V1 pass (2.03x) is a different design and does not substitute.

### Unattended launcher (#68), measured, no target

The opt-in launcher starts encoders without an operator. Same 6-clip backlog and fixture as the cap-3
operator batch. The proposal has no target for this; the figures are as measured.

| Metric | Operator batch, cap 3 | Unattended launcher | Ratio or delta |
|---|---:|---:|---|
| Jobs/min | 1.134 | 0.787 | **0.69x** throughput |
| Median queue wait, s | 9.6 | 110.5 | +100.9 |
| p90 queue wait, s | 184.8 | 293.9 | +109.1 |
| Billed encoder seconds | 830.3 | 870.6 | +40.3 |
| Encoders started for 6 jobs | 6 | 6 | 0 |
| Peak concurrent | 3 | 3 | 0 |
| Starts after the backlog emptied | | 0 | |

Start offsets were 84.0 to 84.8 s for the first three and 266.3 to 267.3 s for the next three, so the
launcher started work in two waves with a gap. First attempt FAIL (smoke login 429 right after open);
rerun PASS. IAM simulation of the launcher role: all required actions allowed, `ecs:StopTask`,
`sqs:ReceiveMessage` and `s3:GetObject` implicitly denied (the simulation was attested by the operator,
not verified by the harness).
Receipt: `cloud-proof-r1018b.json` `#68`; design in [`v2/unattended-launch.md`](execution/aws/v2/unattended-launch.md).

## Observability and cost

| Item | Result | PASS/FAIL | Environment | Receipt |
|---|---|---|---|---|
| Alarms | 13 of 13 alarms `OK` after the backlog and again after the unattended run; no transition to `ALARM` in the history. The stack was deployed with `unattended_launch=true`; the template at default flags defines 12 (the extra one comes from an optional feature on this stack; which one was not checked). **No alarm was seen firing**, so the alarm action itself is untested | PASS (state only) | AWS r1018b | `r1018b-results.md` (#200) |
| Dashboard | `ServicesDashboard`, 13 metric widgets, captured three times. Images are kept in the private state directory, **not in git** | Evidence not in repo | AWS r1018b | `r1018b-results.md` |
| Alarm and dashboard definitions | Per-service DLQ and error alarms plus one dashboard in the template | Code | Local V1 emulated | `tests/aws/v1/test_observability.py` |
| Closed state and ACU pause | Close-state PASS (0 reservations, edge burst 0, mappings off). Database pause observed 5.8 min after the close (min 0, max 2 ACU, no wake-up). In r1017b the first read after a cold start took 4.7 s | PASS | AWS r1017b and r1018b | `#67` `close-state`, `pause`; r1017b `#66` `cold-wake` |
| Spend | Cost Explorer reports 0.00 USD for October through 17 October (credits apply, data flagged estimated, lags about a day), for r1017b as well. **PENDING**. The pricing model estimates 1.5 to 3 USD for the r1018 sessions against a 15 USD ceiling; that is an estimate, not a measurement | **PENDING** | AWS | `#67` `cost-explorer`; `r1018b-results.md` "Spend" |
| Teardown | Laptop teardown 29.4 min, receipt `CLEAN`. r1018a CD teardown 32.6 min, `CLEAN`. Afterwards no stack, cluster, NAT, bucket, function, queue or alarm remained for either run id; the snapshot `dc2-v1-r1017b-final` was kept. r1018b CD teardown **failed twice** at `td-session-close` and was completed from the laptop; cause not found | PASS by laptop; CD teardown FAIL | AWS | `r1018b-results.md` "Teardown" |

## Reuse (Q9)

| Check | Result | How to reproduce |
|---|---|---|
| Imports from service code | **0**. The Publisher imports only the standard library and `httpx` | `grep -rnE "^\s*(from\|import)\s+(app\|media\|processing\|delivery\|contracts\|runtime_support\|media_engine\|sqlalchemy\|asyncpg\|psycopg\|boto3)\b" publisher \| wc -l` prints 0 |
| Enforced by a test | AST walk over `publisher/*.py` rejects `app`, `media`, `processing`, `sqlalchemy`, `asyncpg` | `tests/publisher/test_publisher.py::test_module_entry_and_import_boundary` |
| Database credentials | **0**. The only password in the package is the end user's own login password, sent to the public API | `grep -rniE "database\|dsn\|postgres\|aws_\|secret" publisher/*.py` finds only a docstring |
| Size | 491 lines of Python in 6 files: `cli.py` 197, `client.py` 241, `state.py` 49, `__init__.py` 1, `__main__.py` 3 (plus `pyproject.toml` and a README) | `wc -l publisher/*.py` |
| Effort | **Not measured.** The git history shows first commit on 13 October with later changes on 15 and 18 October. No effort log records person-days, so the "within 2 person-days" target is neither confirmed nor refuted | `git log --format=%ad -- publisher` |
| Bulk publish, live | `python -m publisher publish` of **3 clips**, all `done`, **272 s**. The Publisher first had to be fixed because it did not know the `accepted` status (#219). The terminal transcript is private and not in git | `r1018b-results.md` "Demo captures" |
| Contract conformance | The Publisher validates against the published OpenAPI document in CI | `tests/publisher/test_publisher.py::test_public_schema_conformance_and_explicit_ca` |
| Real HTTPS and cookie persistence | CI job "Independent Publisher HTTPS and cookie persistence" green | run 39075571439 |

## CI and coverage

Latest full CI run (all lanes, including coverage gate, secret scan, three image scans, DAST): run
[39075571439](https://github.com/Collaboration95/dc2/actions/runs/39075571439) on `f5ae434` (`dev/closeout`,
17 October), **success**; the "Dev gate" and "Full verification" jobs both passed. Commits after it on
`dev/closeout` are documentation and repository-hygiene changes. Lane selection means documentation-only
pull requests run a shorter policy; the full run above is the reference.

Combined backend coverage (statements plus branches, gate: at least 80% per package):

| Package | Combined % | Covered statements / total | Covered branches / total |
|---|---:|---|---|
| `app` (legacy Project 1 code, still in the repo) | 93.16 | 1,255 / 1,333 | 188 / 216 |
| `processing` | 87.66 | 2,019 / 2,250 | 425 / 538 |
| `media` | 91.09 | 1,636 / 1,750 | 348 / 428 |
| `media_engine` | 99.42 | 122 / 122 | 49 / 50 |
| `publisher` | 97.57 | 296 / 301 | 66 / 70 |
| `contracts` | 97.12 | 203 / 208 | 67 / 70 |
| `delivery` | 93.45 | 290 / 303 | 81 / 94 |
| `runtime_support` | 97.24 | 139 / 141 | 37 / 40 |

Source: the `python-coverage` artifact of run 39075571439 (`gate.json`). SonarCloud analyses are
advisory and were skipped in that run; DAST findings are report-only.

CI timing and selection evidence: [`docs/ci/results-20261017.md`](ci/results-20261017.md) (full
verification 462 s to its gate, 464 s whole workflow; the selected gates took 22 to 232 s).

### Pipeline runs on AWS

| Run | What | Result |
|---|---|---|
| [39056733505](https://github.com/Collaboration95/dc2/actions/runs/39056733505) | r1018a CD deploy | Deploy step OK in 25.0 min; the smoke step failed (`ffmpeg: command not found` on the runner, fixed in #213) |
| [39060241042](https://github.com/Collaboration95/dc2/actions/runs/39060241042) | r1018a CD teardown | success in 32.6 min, `CLEAN` |
| [39062471021](https://github.com/Collaboration95/dc2/actions/runs/39062471021) | r1018b CD deploy | **success**: deploy 26.5 min, upload-to-playback smoke PASS in 4.2 min |
| Processing and Media releases, three rounds each | r1018b CD `release` | Every `Release` step promoted; the post-release smoke never passed (see Q7d) |
| r1018b CD teardown | two dispatches | Both failed at `td-session-close`; completed from the laptop |
| [39085599276](https://github.com/Collaboration95/dc2/actions/runs/39085599276) | r1019a CD deploy, source `0b491e1712a9e4423e7f53bc2c813191d25669e8` (18 October) | **success**: `Deploy` step 23m47s, upload-to-playback smoke PASS in 4m53s (`seconds_to_terminal` 108.5) |
| [39087966647](https://github.com/Collaboration95/dc2/actions/runs/39087966647) | r1019a CD Processing release, source `358d169d6b0d0fc0f1e5ce809ffc8f1ad02fc592` | **success**: `Release` step 9m39s, post-release upload-to-playback smoke PASS in 5m59s (see Q7i for what this does and does not show) |
| [39089615147](https://github.com/Collaboration95/dc2/actions/runs/39089615147) | r1019a CD teardown, source `0b491e1712a9e4423e7f53bc2c813191d25669e8` | **success**, receipt `CLEAN` |
| [39089045496](https://github.com/Collaboration95/dc2/actions/runs/39089045496) | r1019a CD release with `bad_candidate=true`, source `784318636b690aac6ca64f0f8817ae7a15b6cae7` | **cancelled** in the `Release` step; no rollback result |
| [39105817431](https://github.com/Collaboration95/dc2/actions/runs/39105817431) | V2-live persistent deploy from Main, source `d2070db68c6b3545881eb948046b8e57f47e078e` | **success**, smoke PASS (Q7j) |
| [39107762106](https://github.com/Collaboration95/dc2/actions/runs/39107762106) | Full CI (scheduled full verification) on `d2070db68c6b3545881eb948046b8e57f47e078e` | **success**: every lane selected; "Full verification" and "Dev gate" passed; SonarCloud jobs skipped (advisory); DAST findings report-only. Coverage percentage for this run is not recorded here (unverified); the figures in the table above are from run 39075571439 |

### Runs that did not count

`r1018a` also had a laptop `evidence gateway` run: six steps PASS and `direct-upload-e2e` FAIL, because the
encoder exited 1 with `missing setting: PROCESSING_WORK_QUEUE_URL` (the #200 environment narrowing removed
it from the worker task definition; fixed in #214). It was torn down and its numbers are not used above.

## Pending

| Item | Status |
|---|---|
| CD pipeline end to end green (deploy, release smoke, teardown, all through `cd.yml`) | **Done for `r1019a` (#182, #223, #225): deploy 39085599276, Processing release with upload smoke 39087966647, teardown `CLEAN` 39089615147** (rows in "Pipeline runs on AWS"). The earlier `r1018b` post-release smoke failures and teardown failures are unchanged. The deliberate bad-candidate dispatch was cancelled (Q7h) |
| Invoice | PENDING (Cost Explorer 0.00 USD because of credits) |
| 30-clip, three-repeat scaling on AWS | Not run. The AWS figures above are 6 clips, one run per cap |
| Two-user cross-read test on AWS (S2), expired and tampered presigned URL (S5c), external port scan (S7), S3-side 100 MiB limit end to end (S6) | NOT_RUN |
| Lost queue entry timed on AWS (Q5c) | NOT_RUN |
| Duplicate-output check after a worker kill on AWS (Q4b) | Not in the receipt |
