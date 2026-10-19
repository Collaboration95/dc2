# V2-live verification, 19 October 2026 (#238, #186 re-scoped to `dc2-live`)

Sanitized receipts of the in-place update, the scaling and backlog measurements, the Processing
release and the rollback proof on the persistent stack `dc2-live` (ap-southeast-1). The CD files
are copied **unmodified** from the runs' public artifacts (`cd-<operation>-live-<run id>`, 60 days
retention). No credentials, cookies, signed URLs or account IDs are in this folder; the test
account's password and cookie jar stayed in a private temp directory. The test account is an
ordinary user (`role: user`) created for this check.

## Claim to receipt

| Claim | Result | Receipt | Limits |
|---|---|---|---|
| Automatic CD after merging PR #264 updated `dc2-live` **in place** | PASS for the stack, **run FAILED later** at the release step | [`cd-39258304893-deploy-failed-release-plan/`](cd-39258304893-deploy-failed-release-plan/) | See "What the in-place update changed" and finding F1 |
| Processing release (image of source `79b5d12`, includes #241) promoted online, six aliases moved, own smoke PASS | PASS (release job 9m46s) | [`cd-39265004564-processing-release/release-processing.json`](cd-39265004564-processing-release/release-processing.json) | The job ended red at the adoption step (finding F2); the stack update that names the released images was finished by run 39268999121 |
| Stack names the released Processing image | PASS: `ProcessingApi` alias `live` serves digest `sha256:bcaf38b5...`, the one pushed as tag `g39265004564x1-processing` | `aws lambda get-function --qualifier live` (not a file; digest quoted here) | `GET /api/processing/health` still prints `"version":"v1-dev"`: the service does not report its release number, so "1.0.3" is visible only through the image tag and digest |
| Rollback proof: `release owner=processing bad_candidate=true` fails its smoke and restores itself | PASS: candidate smoke `processing-jobs:503`, outcome `restored`, aliases back to the good digest, **job green** (run 39271754470) | [`cd-39271754470-bad-candidate-rollback/`](cd-39271754470-bad-candidate-rollback/) | `Release` step 8m36s. The post-release upload-to-playback smoke in the same run passed (`seconds_to_terminal` 72.4); its #63 roll-up reads INCOMPLETE because only that one step is run |
| Media auto-release in the deploy | Promoted, own smoke PASS including `upload-reserve` | [`cd-39268999121-deploy-adopt/release-media.json`](cd-39268999121-deploy-adopt/release-media.json) | |
| Deploy smoke after the in-place update | **FAIL** (run 39268999121) | [`cd-39268999121-deploy-adopt/cloud-proof-smoke-39268999121-1.json`](cd-39268999121-deploy-adopt/cloud-proof-smoke-39268999121-1.json) | Refused to start: 10 stale messages in `ProcessingWork`, left by the 9-clip backlog run (finding F3). Not a product failure of the encode path, which passed in run 39271754470 |
| Scale 0 -> 3 -> 0 with the queue | PASS | [`scaling-and-backlog.json`](scaling-and-backlog.json) `three_clips_concurrent` | Queue-wait target of 20 s **not met** (about 37 s queued-to-processing, 25 s of it Fargate start) |
| Backlog: 9 clips drained at the fixed cap of 3 | 239 s submit to done, 9 tasks, peak 3, 2.26 jobs/min | [`scaling-and-backlog.json`](scaling-and-backlog.json) `backlog_nine_clips` | One run; cap fixed at 3 so no 1/2/3 comparison; the 2.5x speedup is against a calculated serial baseline, not a measured one |
| CloudWatch alarms | 13 of 13 `OK` at 14:57 UTC; description text updated to the new wording | `aws cloudwatch describe-alarms --alarm-name-prefix dc2-live` | Point-in-time read |
| Aurora pause after idle | **NOT OBSERVED** within about 75 minutes of mostly idle time | see "Aurora pause" | Open; re-check command below |

## What the in-place update changed (run 39258304893)

The stack went from `UPDATE_COMPLETE 2026-10-18T07:12Z` to `UPDATE_COMPLETE 2026-10-19T13:18:00Z`
as a change set on the same stack (no recreate; `foundation`, `images`, `db-bootstrap` and
`migrations` skipped). The change set was **not alarm-only**, because #244 is in the same range:

- 10 `AWS::CloudWatch::Alarm` descriptions (the new "a consumer was reading" wording);
- `ProcessingApi` (new `PROCESSING_ACTIVITY_*` environment, so its writers record activity),
  its `AWS::Lambda::Version` (replacement, the normal Lambda behaviour) and alias;
- `ProcessingActivityWriters` IAM policy (now also attached to `ProcessingApiRole`).

No stateful resource (Aurora, buckets, CloudFront, queues) was in the change set. The `applications`
step ended 13:18:37Z, the public smoke inside the deploy took 15 s, and the Deploy step ran
13:14:19 to 13:19:53Z including the image build and the failed release.

## Findings

- **F1: the first automatic release could not work.** `scripts/ci/cd.sh` called
  `jq ... --args FILTER "$build" names...`, so jq took the build file as a positional string and
  read an empty stdin; `release-plan` failed with "A build evidence file is unreadable JSON".
  Fixed by moving `--args` after the file (PR #265).
- **F2: the adopt step blanked the state.** The same ordering bug in the baseline merge wrote an
  empty `build-baseline.json` into the environment state after the Processing release had
  promoted. The release itself was fine, the stack update that follows failed. The baseline was
  rebuilt by hand from the previous S3 object version plus the released images, then fixed in
  PR #267 (also refuses an empty merge result). Lesson: the release path had never been run on
  `live` with `kept` images or adoption before this session.
- **F3: duplicate work messages and a stuck queue.** Nine concurrent uploads produced 21 sends to
  `ProcessingWork`; ten messages stayed visible after every job was `done`. The launcher decides
  from SQL, not queue depth, so it started nothing, and the deploy smoke's "queue must be empty"
  guard then failed the run. The queue was emptied with `sqs purge-queue` (all jobs were
  terminal). Cause of the duplicate sends is not established here: the 3-way run produced 3 sends
  for 3 jobs, so it appears only under heavier concurrency. Needs an owner (Track C/A).
- **F4: gating dispatches from `dev/closeout` costs a full CI run.** The environment allows
  `Main` and `dev/closeout`, but the gate wants a CI run for the exact SHA, so each fix needed a
  `workflow_dispatch` of `ci.yml` with `candidate_sha`. One of those runs failed once on
  `test_rehearsal_includes_the_short_encode_comparison` and passed on re-run (flake; not
  investigated).
- **F5: Publisher processes sharing a cookie jar run one at a time** (lock file). Parallel
  uploads need one jar per process; this is a client property, not a platform one.

## Aurora pause

`ServerlessDatabaseCapacity` stayed at 0.5 ACU from 13:00 to at least 14:57 UTC in every 1-minute
datapoint, including a 20-minute stretch (13:44 to 14:00) with no deploy, upload or release from
this session. `DatabaseConnections` fell to 1 and stayed there. The Media repair function ran an
SQL pass on most minutes: its `quiet` marker (`/dc2/dc2-live/activity/media/quiet`) held two
values 60 s apart, i.e. `next_due` always found a row due within a minute. The likely cause is
that `UploadReservation` rows from the session's own uploads (signed URL TTL 900 s) stay
unretired until `expires_at` and their cleanup pass; every upload of the session created one.
That is a hypothesis from the code (`media/recovery_v1.py: next_due`), not a measurement. Processing's marker was
quiet (30 minute horizon). So pausing was not observed; whether it happens once the last
reservation has been cleaned up is the open question.

Re-check (a paused cluster reports `0.0`; look for a datapoint of 0 after the last activity at
about 14:56 UTC):

```sh
aws cloudwatch get-metric-statistics --profile dc2-agent --region ap-southeast-1 \
  --namespace AWS/RDS --metric-name ServerlessDatabaseCapacity \
  --dimensions Name=DBClusterIdentifier,Value=dc2-live-databasecluster-eaegdwku2hhn \
  --start-time 2026-10-19T14:50:00Z --end-time <now> --period 60 --statistics Maximum
```

## Run index

| Run | What | Result |
|---|---|---|
| [39258304893](https://github.com/Collaboration95/dc2/actions/runs/39258304893) | Automatic CD after the #264 merge, source `acf6d49` | stack update PASS, job FAIL at `release-plan` (F1) |
| [39262620723](https://github.com/Collaboration95/dc2/actions/runs/39262620723) | Release dispatched from the fix branch | refused by environment protection (branch not allowed) |
| [39265004564](https://github.com/Collaboration95/dc2/actions/runs/39265004564) | Processing release, source `79b5d12` | promoted, smoke PASS; job FAIL at adoption (F2) |
| [39268999121](https://github.com/Collaboration95/dc2/actions/runs/39268999121) | `deploy` to finish adoption, source `7928b7c`; also auto-released Media | deploy step PASS, Media promoted, smoke FAIL (F3), job FAIL |
| [39271754470](https://github.com/Collaboration95/dc2/actions/runs/39271754470) | `release processing bad_candidate=true`, source `7928b7c` | outcome `restored`, job PASS |
