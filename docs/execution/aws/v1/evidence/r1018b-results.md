# Cloud session r1018b: results (2026-10-17 UTC)

One AWS session for #186 (parent #179), deployed and torn down through the CD pipeline plus a laptop
operator. Redacted machine-readable receipts: [`cloud-proof-r1018b.json`](cloud-proof-r1018b.json) (#63,
#185, #196, #68, #67) and [`cloud-proof-r1018bmedia.json`](cloud-proof-r1018bmedia.json) (#65, Media).
A FAIL against a target is a result and is reported as one. Nothing was rerun to get a PASS without the
first attempt being recorded below.

## Runs

| Run | What | Result |
|---|---|---|
| r1018a, CD [39056733505](https://github.com/Collaboration95/dc2/actions/runs/39056733505) | first real deploy, `unattended_launch=true` | deploy step **ok in 25.0 min**; smoke step failed (`ffmpeg: command not found` on the runner, fixed in #213) |
| r1018a, laptop | `evidence gateway` | 6 steps PASS, `direct-upload-e2e` FAIL: the encoder exited 1, `missing setting: PROCESSING_WORK_QUEUE_URL` (the #200 environment narrowing took it out of the worker task definition, fixed in #214) |
| r1018a, CD [39060241042](https://github.com/Collaboration95/dc2/actions/runs/39060241042) | teardown | success in 32.6 min, receipt `CLEAN` |
| r1018b, CD [39062471021](https://github.com/Collaboration95/dc2/actions/runs/39062471021) | deploy `unattended_launch=true` | **success**: deploy step 26.5 min (includes the native image build), upload-to-playback smoke **PASS in 4.2 min** |
| r1018b, laptop | plain session, then unattended session | see the table below |
| r1018b, CD releases | Processing and Media, three rounds | each release step promoted; see "Independent releases" |
| r1018b, teardown | CD teardown failed twice at `td-session-close`, laptop teardown | see "Teardown" |

## Results

| Issue | Step | Result |
|---|---|---|
| #63 | anonymous denial, forged identity, CORS, queue direct send, cross-database denial | PASS (cross-database 55.8 s) |
| #63 | session round trip | first attempt FAIL (login HTTP 429, 0.13 s after `session open`: the Gateway still applied the closed 0/0 limit); rerun PASS |
| #63 | direct upload to HLS playback through CloudFront | PASS, 71.4 s (67.3 s to `done`, one encoder, exit 0) |
| #185 | backlog 6 x 36 MB clip, cap 1 / 2 / 3 | 0.483 / 0.700 / 1.134 jobs/min, 0 failures |
| #185 | speedup against target | cap 2 **1.449x, FAIL** (target 1.6x); cap 3 **2.347x, PASS** (target 2.1x); `backlog-compare` FAIL |
| #185 | median / p90 queue wait (s) | cap 1: 274 / 602; cap 2: 136 / 378; cap 3: 9.6 / 185 |
| #196 | Processing down (command consumer off 48 s) | first attempt FAIL in 1 s (`Insufficient request deadline`, harness bug, fixed in #218); rerun **PASS**: Media answered 202, job `accepted`, command held in outbox and queue, `done` 58.9 s after re-enable |
| #68 | IAM simulation of the launcher role | all allowed, `ecs:StopTask`, `sqs:ReceiveMessage`, `s3:GetObject` implicitDeny |
| #68 | launcher against the baseline (6 clips, cap 3) | first attempt FAIL (smoke login 429 right after open); rerun **PASS**: 0.787 jobs/min against 1.134 for operator batches (0.69x), median queue wait 110.5 s against 9.6 s, p90 293.9 s against 184.8 s, 6 encoders for 6 jobs, no start after the backlog emptied, peak 3, billed 871 s against 830 s |
| #65 | Media release on the stack, own run id `r1018bmedia` | **PASS**, all five steps: baseline 48.7 s, promote-good 246.8 s, rollback 251.8 s, **bad-candidate-restore 237.6 s** (candidate failed its smoke after 189.5 s, aliases restored in 47.0 s, peer unchanged), owner-isolation 47.7 s |
| #200 | alarms | 13 of 13 `OK` after the backlog and again after the unattended run, no transition to `ALARM` in the history |
| #67 | closed state, ACU pause | close-state PASS; pause **observed 5.8 min after the close** (min 0, max 2 ACU, no wake-up) |

Dashboard images (`ServicesDashboard`, 13 metric widgets, three times) stay in the private state
directory; they are not in git.

## Independent releases (UC-7, #182)

Each owner was released alone through `cd.yml operation=release`, three rounds each, always on a commit
that differed from the deployed one. Every `Release` step ended `promoted` with its own release smoke
(health, anonymous denial, login, jobs, and for Media the reservation) passing, and only the owner's
functions changed version (Processing 6 functions, Media 4); the peer's aliases did not move.

| Owner | `Release` step (build, push, scan, plan, promote, release smoke, close) |
|---|---|
| Processing | 10.3, 10.2, 10.1 min |
| Media | 8.0, 8.0, 8.2 min |

The target was 10 minutes for deploy plus smoke. Media meets it on the release step; Processing is at
10.1 to 10.3. The post-release upload-to-playback smoke added 2.7 to 4.4 min (18 min when it waited out
the 900 s job timeout) and **did not pass in any of the five runs that reached it**, for three different
reasons, so the CD smoke after a release is not yet green:

1. Gateway 429 straight after `session open` (Processing round 1, Media rounds 1 and 2; round 2 still
   hit it after #220's gate probe had succeeded). Fixed in #220 (wait for the gate) and #222 (one retry
   on a 429); no later green run exercised #222.
2. ECS purges a stopped task about an hour after it stops; the task inventory listed one and then could
   not describe it (`unresolved identities`). Fixed in #221.
3. The smoke starts its single encoder right after finalize. After a Processing release the command
   reached the work queue after the encoder had already exited without claiming (the repair then queued
   17 stale messages). Not fixed: #223. The last Media round was cancelled at its smoke start because the
   stale messages would have been claimed first; the earlier Media rounds had passed their release steps.

The bad-candidate rollback path is proven by the #65 receipt above, not by the pipeline.

## Teardown

Both CD teardown dispatches failed at `td-session-close` (`Partial close; retry from retained journal`;
the unresolved step differed, first `launcher:flag`, then a repair-rule disable). The same close from
the laptop succeeded, and the laptop `deploy teardown --execute --confirm-run-id r1018b
--skip-final-snapshot` then ran through. The cause is not found; the runner log keeps only the final
message. The older snapshot `dc2-v1-r1017b-final` was kept.

Laptop teardown took 29.4 min (23:35:12 to 00:04:37 UTC), receipt `CLEAN` with nothing remaining and
nothing skipped as not owned; r1018a's CD teardown (32.6 min) was `CLEAN` too. Checked afterwards with
the CLI, both run ids: no `dc2-v1-r1018*` stack (the old `dc2-v1-20261015t1146-bootstrap` rollback stub
and the OIDC stack are untouched), no Aurora cluster, only the snapshot above, no ECS cluster, no NAT
gateway, Elastic IP or network interface, no CloudFront distribution, and no Lambda function, bucket,
repository, log group, parameter, queue, alarm or dashboard for either run. The whole stack was up from
19:30 to 00:04 (4.6 h); r1018a was up from 18:08 to 19:29.

## Spend (#67)

Cost Explorer reports 0.00 USD for October through 2026-10-17 (credits apply, the data is flagged
estimated and lags about a day), also for r1017b, so the invoice is **PENDING**. From the pricing model
(Aurora 0.5 to 2 ACU awake for roughly 6 h across both runs, about 60 encoder tasks of 2 vCPU and 4 GiB for
2 to 3 minutes each, everything else pennies) the session cost an estimated 1.5 to 3 USD, well under the
15 USD ceiling and the 1.97 USD planned-window model. That figure is an estimate, not a measurement.

## Demo captures (private, not in git)

A browser recording of register, sign out, sign in, upload of `short.mp4`, status and HLS playback
through the CloudFront URL (player visible 134.8 s after the upload, video played to 5.96 s), and a
terminal transcript of `python -m publisher publish` of three clips (all `done`, 272 s). The Publisher
had to be fixed first: it did not know the `accepted` status (#219). The transcript has its presigned
query strings removed.
