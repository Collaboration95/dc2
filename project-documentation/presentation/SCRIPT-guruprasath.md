# Spoken script: Guruprasath (sections 1, 2, 5, 6)

FlickPond, Team 17, Zoom, Mon 26 Oct 2026, 14:35. These are the words to say, not words to read off the
slides. Slide numbers refer to `site/deck.html` (43 main slides, backups B01–B09). The changes are listed in
`SLIDE-CHANGES.md`.

> **For sections 5 and 6, use `SCRIPT-5-6.md` (updated 26 Oct for the re-recorded clips).** It has the same words, set out slide by slide with actions and cue times.

Pace: about 140 words a minute for talk. Clips run at their own length. Over a clip, at most about 2.3
words per second. The clips use the browser's own player: click the video or press P to pause, and drag the
bar to scrub. Arrow keys still change slides. `→` means next slide.

| Section | Covers | Talk words | Over-clip words | Clip time | Estimated time | Target | Guideline (talk) |
|---|---|---|---|---|---|---|---|
| Title + 1 Overview | 1a, 1b, 1c | 249 | – | – | 1:46 | 1:45 | 2:00 |
| 2 Project conduct | 2a, 2b | 178 | – | – | 1:16 | 1:20 | 1:30 |
| 5 DevOps and lifecycle | 5a, 5b, 5c | 660 | – | – | 4:42 (≈ 5:00 with slide changes) | 5:15 | 6:00 |
| 6 Demo + close | 6a; 6b scalability, performance, maintainability | 392 | 172 | 2:42 | 5:30 (≈ 6:15 with GitHub page loads and clip starts) | 7:00 | 8:00 |
| **Total (mine)** | | **1,479** | **172** | **2:42** | **≈ 14:15** | 15:20 | 18:00 |

Words over a clip are spoken while it plays, so they add no time. Lines said while a clip is paused count as
talk.

---

## Title and 1 · Overview (target 1:45)

Covers **1a** business problem, **1b** platform thinking, **1c** scope.

### Beat 1.0 · Slide 1 "FlickPond: a video upload and processing platform on AWS" (≈ 20 s)
Point at the three name boxes.

> Hi, I'm Guruprasath. We're Team 17: Ibrahim, Long and me. I led cloud and delivery, Ibrahim the backend
> services, and Long the domain model and contracts. I'll cover sections one, two, five and six; my teammates cover the architecture.

### Beat 1a · Slide 2 "Every video app rebuilds upload, encoding and private playback" (≈ 30 s)
Point at the four people, then the chain, then the orange chip.

> The problem. Course teams, trainers and small studios all need the same four things for video: upload
> what they own, convert it so it plays on any device, see whether that worked, and keep playback private.
> Each application builds this again. And conversion is heavy: minutes of CPU per video, competing with logins on the same machine.

### Beat 1b · Slide 3 "Two clients use one public API; two services sit behind it" (≈ 30 s)
Point left to right along the arrows, then at the two green chips.

> Our answer is a platform. The workflow is offered through one public API. The unit it manages is an owned
> video and its processing job. Owners upload and the same owners watch. Integrators build new clients on
> the API, and operators manage capacity and releases. A second client, the Publisher command-line tool, uses only that API; a test fails the build if it imports service code.

### Beat 1c · Slide 4 "Inherited from Project 1, rebuilt in Project 2" (≈ 25 s)
Grey left panel, then the coloured right panel.

> Scope. We inherited FlickPond: one application on one machine, with FFmpeg encoding. We kept the
> encoding and credit it to that team. We rebuilt the rest: two services with their own data, queues
> between them, and a serverless deployment on AWS. Seven use cases are in scope. Sharing with other
> viewers and multi-region are out.

### Beat T · Slide 5 "Four design themes" (≈ 15 s)
Touch each tile once.

> Four themes run through the talk. One public API with two clients. Checks at each service boundary.
> Scale to zero when idle. And every number links to a real run, misses included.

→ straight into section 2.

---

## 2 · Project conduct (target 1:20)

Covers **2a** status, **2b** milestones and effort per member.

### Beat 2a · Slide 6 "Status: all planned use cases delivered and running" (≈ 35 s)
Point at 7/7, then the two groups of chips.

> Status. All seven planned use cases are delivered and running on the live AWS environment. It has been
> up since 18 October and redeploys after every green build on Main. We also added a few things beyond the
> plan: edit, delete and admin routes, and a Lambda lane for short clips. What remains: end-to-end latency
> is about 45 seconds against a 20-second aim, and the final report revision is due on 16 November.

### Beat 2b · Slide 7 "Milestones: proposal 4 Oct, code freeze 23 Oct" (≈ 40 s)
Follow the timeline left to right; stop at the orange dot and the grey dot; then the effort tiles.

> Milestones. Proposal on 4 October. Design finished on the 9th, two days late, because we completed the
> domain analysis before changing code. Media and Processing were split into two services on the 12th and
> 13th. First deploy to AWS on the 17th, the live environment and CD on the 18th and 19th. We had planned
> to freeze on the 20th. The Lambda lane and the database split went live on the 21st, and the code froze
> on the 23rd. Effort was split equally: 11 person-days each, 33 against 31 planned. The extra went into
> the delivery pipeline.
>
> Ibrahim, over to you for the logical architecture.

---

## 5 · DevOps and development lifecycle (target 5:15)

Covers **5a** source code and artifacts, **5b** pipeline and procedures, **5c** findings and issues.

### Beat 5a · Slide 30 "One repository, three images, per-service releases" (≈ 60 s)
Repository box, the three images, the aliases; then the branch row left to right.

> Thanks, Ibrahim. Section five: how a change gets from a laptop into that environment.
>
> One repository holds both services, both clients, the infrastructure and the pipeline. We chose that so
> a contract change and both of its consumers land in one pull request. Separation is enforced inside the
> repository: each service has its own CI lane and its own image, and an image build fails if it can
> import the other service's code.
>
> A release is identified by the commit, the digest of the image we scanned, and the Lambda alias that
> serves it. CI and CD keep their scan reports, coverage and delivery records, and we commit the sanitized
> records. That is where the run IDs on these slides come from.
>
> Feature branches merge into an integration branch, which merges into Main through one release pull
> request. A green build on Main deploys automatically.

### Beat 5b-1 · Slide 31 "CI: changed lanes on pull requests, full run on Main" (≈ 55 s)
Stages 1 to 4, then the two numbers.

> The checks, left to right. On a laptop: lint, unit tests, and the full stack locally if needed. On a pull
> request into the integration branch, a policy script runs only the lanes whose files changed. If it
> can't classify a change, it runs everything. Into Main, every lane runs: 25 jobs in about seven minutes,
> with real Postgres, a browser test, image scans and an 80 percent coverage floor per package.
>
> The gate job also checks skipped jobs against the recorded plan, so a lane can't disappear without
> failing the build. After the merge, full CI runs again on the merged commit, and only that run can
> trigger a deployment.

### Beat 5b-2 · Slide 32 "Release: the scanned image is the one deployed" (≈ 75 s)
Top row, bottom row, the roll-back box, then the orange chip.

> Deployment has no manual step. CD first checks that a full CI run passed on that exact commit. It signs
> in to AWS through OIDC, so no AWS keys are stored in GitHub. It updates the stack, then releases each
> changed service separately.
>
> For each service it builds the image, scans it with Trivy, pushes it, and checks that the digest in the
> registry is the one it scanned. Then it moves the alias and runs a smoke test. If the smoke test fails,
> it moves the alias back to the previous version. We tested that with a deliberately broken release.
> Finally an upload-to-playback test runs through the public API.
>
> Merge to serving takes about 15 minutes with no image change, about half an hour when both services
> release. Rollback restores the image, not the database schema, so migrations are additive only. One
> miss: a Processing release step took 10.1 to 10.3 minutes against a 10-minute target.

### Beat 5c-1 · Slide 33 "Trivy blocked a release over the running image" (≈ 50 s)
The log line, then the four circles.

> Two findings came from failed deliveries. On 21 October CD stopped with this line: Trivy found one
> fixable high or critical vulnerability. Production kept running the previous release. The new image was
> clean. CD also rescans the image it is about to replace, because that is the rollback target, and an
> advisory against that image had been published the evening before. So the check blocked the release
> that removed the vulnerable image. We kept the strict scan for the new image and for every image we
> keep. For the image being replaced, the finding is now recorded in the release report instead of
> blocking. The next delivery released it.

### Beat 5c-2 · Slide 34 "Paused Aurora made the deploy smoke test fail" (≈ 45 s)
Left to right.

> The second finding. Aurora pauses after five idle minutes. When a deploy changed no migration, nothing
> woke the database, and the smoke test's login got a 503. We added a retry on that first call: 5, 10 and
> 15 seconds, at most three minutes, every attempt logged. Then we split the database per service, and
> three deliveries failed again, this time on Processing. Its cluster pauses separately. Now the first
> call to each service is retried, and delivery has been green since.

### Beat 5c-3 · Slide 35 "Other findings from failed deliveries" (≈ 25 s)
One tile each.

> Three smaller ones. This AWS account caps Lambda memory at 3008 megabytes, below what we designed for.
> Our deploy tool refused a stack that had rolled back, although AWS accepts it. And a formatting change
> altered a migration that was already released; the compatibility check held that release. Each fix has
> a test. Now the demo.

---

## 6 · Demo (target 7:00 including clips and close)

Covers **6a** use cases (D1 upload and play, D2 Publisher, D3 access per owner) and **6b** quality
attributes: scalability D4, performance D5, maintainability D6. Cue times are the player's clock.

### Beat 6.0 · Slide 36 "Demo: three use cases, three quality attributes" (≈ 15 s)

> The demo. Recordings on the live AWS system: the web app from 23 October, the terminal runs recorded
> today in a real terminal, with long waits cut or sped up. Three use
> cases first, then the three quality attributes. The pipeline I'll show live on GitHub.

### Beat 6a-D1 · Slide 37 "D1 — Upload, processing and playback in the web app" (clip 0:24; beat ≈ 30 s)

> First, the web app. Owner A is already signed in. **[play]**

| Clip time | Say |
|---|---|
| 0:02 | She uploads a lecture. |
| 0:04 | Accepted. The file went straight to S3, and processing runs in the background. |
| 0:08 | Processing complete. |
| 0:12 | Her library. |
| 0:16 | And it plays, only for her. |

### Beat 6a-D2 · Slide 38 "D2 — Batch upload with the Publisher CLI" (clip 0:31; beat ≈ 36 s)

> Now the Publisher, the second client. **[play]**

| Clip time | Say |
|---|---|
| 0:02 | Three lecture files in a folder. |
| 0:06 | One publish command uploads all three and returns three job IDs. |
| 0:18 | Then a status check on each. |
| 0:24 | All three done, through the same public API. |

### Beat 6a-D3 · Slide 39 "D3 — Access is checked per owner" (clip 0:27; beat ≈ 32 s)

> Next, what happens if someone else has a job ID. **[play]**

| Clip time | Say |
|---|---|
| 0:03 | Owner A asks for her video: done. |
| 0:11 | Owner B asks for the same ID: not found. The API doesn't confirm it exists. |
| 0:19 | Without a login: HTTP 401. |

After the clip:

> The check runs at the API on every request.

### Beat 6b-D4 · Slide 40 "D4 — Fargate encoders scale 0 → 3 → 0" (clip 1:00; beat ≈ 85 s)

> Scalability. Five 72-megabyte recordings. They are too big for the Lambda lane, so they go to Fargate.
> Watch the encoder count. **[play]**

| Clip time | Say |
|---|---|
| 0:03 | Five files, 72 megabytes each. |
| 0:10 | Published in the background. |
| 0:12 | The watcher starts at zero encoders. |
| 0:25 | The blue label: the wait now plays at 16 times speed. |
| ≈ 0:36 | Three encoders, then back down. **[pause]** |

While paused, trace the log from top to bottom:

> Three encoders: that's the cap, never a fourth. Then the count drops to zero while jobs are still
> waiting. Each encoder is a task that runs one job and exits. The launcher starts new tasks on its next
> one-minute tick. About five minutes of real time in total. **[play]**

| Clip time | Say |
|---|---|
| ≈ 0:44 | Back at normal speed: capacity is back to zero. |
| ≈ 0:50 | All five jobs done. |

After the clip, point at the speed-up numbers:

> The speed-up test: with two encoders we got 1.45 times against a target of 1.6, a miss. With three,
> 2.35 against 2.1, a pass.

### Beat 6b-D5 · Slide 41 "D5 — Scripted load test against the live API" (clip 1:18; beat ≈ 95 s)

> Performance. A scripted test against the live public API: ten users for sixty seconds. **[play]**

| Clip time | Say |
|---|---|
| 0:03 | Our load generator, run from a laptop through the public endpoint. |
| 0:17 | The 80-second run, at 16 times speed. |
| ≈ 0:23 | The result: 600 status requests, zero errors. |
| ≈ 0:30 | Now the report, generated from the run's raw samples. |
| ≈ 0:45 | Targets against actuals. **[pause]** |

While paused, point at the numbers on the right:

> Status p90 is 143 milliseconds against a 700 target. Zero errors out of 805 requests. Login p90 is about
> 370 milliseconds against two seconds. All pass. **[play]**

| Clip time | Say |
|---|---|
| ≈ 0:58 | The latency distribution for the status call the browser polls. |
| ≈ 1:04 | Throughput stays under the gateway limit of 20 requests a second. |
| ≈ 1:10 | And the lane comparison: queue wait 0.26 seconds on Lambda, 33 on Fargate. |

After the clip:

> Ten users over the internet is smaller than our earlier in-region benchmark. That one was fifty users
> and 9,000 requests, with a p90 of 58 milliseconds, using the same tool.

### Beat 6b-D6 · Slide 42 "D6 — CI and CD runs for a change on Main" (≈ 100 s)

> **If `clips/D6.mp4` has been recorded:** it plays in the box on this slide. Replace this beat with one
> lead-in ("Maintainability: one small change pushed to production, the same commit through every
> stage.") and narrate push, pull-request checks, merge, CI on Main, CD and the reload of the live page.
> Skip the link walk.

Live walk-through. Share the whole Chrome window; each box opens GitHub in a new tab.

> Maintainability. A real change takes about 24 minutes from push to production, so here are the runs
> from 22 October.

Click **CI on Main 39733112331**:

> CI on Main: 25 jobs passed, and three skips the gate confirmed were planned. Note the commit.

Back, click **CD to live 39733859422**:

> CD started two seconds after CI finished, on the same commit. The first job checks that CI passed. Then
> deploy, then the upload-to-playback test. All green, no manual step.

Back, click **Blocked by Trivy 39532075705**, open the failed Deploy step:

> And this is the blocked release from earlier: "media: FAIL: Trivy has 1 fixable HIGH/CRITICAL". The
> deploy stopped and production stayed on the previous version.

Return to the deck tab.

### Close · Slide 43 "Summary" (≈ 20 s)

> To summarise: one public API with two clients, checks at each service boundary, encoders that scale from
> zero to three and back, and a pipeline that only deploys what it has tested, with the results recorded,
> including the misses. Thank you. We're happy to take questions.

Leave slide 43 up during Q&A. Backups: type the number and press Enter (slide 44 onwards), or press O.

---

## If asked

### Section 1
- **Why call it a platform?** Two independent clients use one public API, and capacity belongs to the platform rather than the client. Both clients are ours, so we claim reuse, not adoption.
- **Why build on someone else's Project 1?** It already had a real CPU-heavy, asynchronous workload, so the change could be measured. The inherited parts are credited by name.
- **Why not split identity or playback into services?** Playback and retry decisions need the owner and the asset together. Splitting them would turn database joins into service calls without adding rules of their own.
- **Can a lecturer share a video with students?** No, sharing is out of scope. The contract reserves a viewer role, but nothing issues it. (B02)

### Section 2
- **Are the person-days timesheets?** No. They are a team-agreed equal allocation of the proposal's work packages. Everything was committed through one account, so git history cannot attribute work.
- **Why did effort overrun?** One planned deployment became three proof runs, a persistent environment and a CD pipeline. The AWS and delivery package went from 4 to 6 person-days.
- **What is the biggest open issue?** End-to-end latency: 35 to 80 seconds per job are not explained yet. The next step is per-stage timestamps. (B01)
- **Why waves, not sprints?** It was four weeks with three people and hard dependencies, so issues were grouped by dependency.

### Section 5
- **Separate services in one repository?** Separation means each service owns its data, its release and its failures. Lanes, image import checks, IAM roles and per-service releases enforce it. One lockfile and one stack are still shared.
- **Why run CI again after the merge?** A pull-request run tests a preview merge. CD trusts only the push run on the exact commit that landed.
- **How do you know production runs the scanned image?** CD scans the local image, pushes it, and checks that the registry digest matches. The Lambda version records the digest.
- **Why not block on the old image's finding?** Blocking kept the vulnerable image in production. New and kept images are still scanned strictly, and the finding is written into the release record.
- **Does the smoke-test retry hide failures?** It covers only the first database call per service, only on 502/503/504, at most three retries within 180 s, and all attempts are logged. The release smoke test after a migration is never retried.
- **Which scanners block a release?** See B09.

### Section 6
- **Is D4 ECS auto-scaling?** No. A launcher starts finite tasks from the backlog, capped at 3 by a database check, with a one-minute safety net. Nothing idle is billed.
- **Is the 72 MiB padding staging?** It is an MP4 free box. The video and audio streams are real and fully encoded; the padding only pushes the file over the 64 MiB lane limit.
- **Why only 10 users in D5?** The API stage throttles at 20 requests a second, burst 50. More users would measure the throttle.
- **Are the clips real?** Yes. D1 is a browser recording from 23 Oct; D2–D5 are screen recordings of a real iTerm window against the live system on 26 Oct. Waits are cut (D2) or shown at 16× with a label (D4, D5). D5's report recomputes every figure from raw samples.
- **What are the "bash: child setpgid" lines in D4?** Bash job-control noise from running the publish in the background; it doesn't affect the run. All five jobs end `done`.
- **Why "not found" for owner B rather than 403?** A 403 would confirm that the asset exists.
