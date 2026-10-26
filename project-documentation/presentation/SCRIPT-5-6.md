# Script: sections 5 and 6 (Guruprasath)

Slides 30–43 of `site/deck.html`, presented from <http://127.0.0.1:8766/deck.html>. Mon 26 Oct 2026, 14:35.
These are the words to say. Each slide lists what is on screen, what to do, and what to say. The full
script for title, 1 and 2 is in `SCRIPT-guruprasath.md`.

**Keys:** `→`/`D` next · `←`/`A` back · `P` play or pause a clip (or click the video) · `N` notes ·
number + Enter jumps to that slide. Mouse clicks never change slides, so clicking a link or the player is safe.

**Before you start:** open the deck in Chrome and go full screen (`F`). Open GitHub in a second tab and sign in,
so that the D6 links load quickly. In Zoom, share the Chrome window with **Optimize for video clip** ticked.

| Part | Slides | Target | Running total |
|---|---|---|---|
| 5a Source and artifacts | 30 | 1:00 | 1:00 |
| 5b Pipeline | 31–32 | 2:15 | 3:15 |
| 5c Findings | 33–35 | 2:00 | 5:15 |
| 6 Demo intro | 36 | 0:15 | 5:30 |
| 6a Use cases D1–D3 | 37–39 | 1:45 | 7:15 |
| 6b Quality D4–D6 | 40–42 | 4:40 | 11:55 |
| Close | 43 | 0:20 | **≈ 12:15** |

If you run long, cut slide 35 down to one sentence, and in D6 show only the CI and CD runs, not the Trivy run.

---

## Hand-off · slide 29 (Ibrahim finishes)

Ibrahim ends with "Guruprasath: how a change gets here safely." When he hands over, press **→**.

---

## 5 · DevOps and development lifecycle

### Slide 30 · "One repository, three images, per-service releases" · 1:00 · 5a

**On screen:** the repo box on the left, three images and their aliases in the middle, the branch row along the bottom.
**Do:** point at the repo box, then the three images, then follow the branch row from left to right.

> Thanks, Ibrahim. Section five is how a change gets from a laptop into that environment.
>
> One repository holds both services, both clients, the infrastructure and the pipeline. We chose that so a
> contract change and both of its consumers land in one pull request. Separation is enforced inside the
> repository. Each service has its own CI lane and its own image, and an image build fails if it can import the
> other service's code.
>
> *(point at the images)* A release is identified by three things: the commit, the digest of the image we
> scanned, and the Lambda alias that serves it. CI and CD keep their scan reports, coverage and delivery records,
> and we commit the sanitized ones. The run IDs on the next slides come from those records.
>
> *(follow the branch row)* Feature branches merge into an integration branch, which merges into Main
> through one release pull request. A green build on Main deploys automatically.

**→**

### Slide 31 · "CI: changed lanes on pull requests, full run on Main" · 1:00 · 5b

**On screen:** four stage cards, numbered 1 to 4, and two numbers below them.
**Do:** touch each card in order, then the two numbers.

> The checks, from left to right.
>
> *(card 1)* On a laptop we run lint and unit tests, and the full stack locally if needed.
>
> *(card 2)* On a pull request into the integration branch, a policy script runs only the lanes whose files
> changed. If it can't classify a change, it runs everything.
>
> *(card 3)* Into Main, every lane runs: 25 jobs in about seven minutes, with real Postgres, a browser test,
> image scans and an 80 percent coverage floor for each package.
>
> *(card 4)* After the merge, full CI runs again on the merged commit. Only that run can trigger a
> deployment. The gate job also compares skipped jobs against the recorded plan, so a lane can't quietly
> disappear without failing the build.

**→**

### Slide 32 · "Release: the scanned image is the one deployed" · 1:15 · 5b

**On screen:** the top row runs from merge to the AWS sign-in; the bottom row runs from scan to upload test; a roll-back box; an orange miss chip.
**Do:** follow the top row, then the bottom row, then the roll-back box, then the orange chip.

> Deployment has no manual step.
>
> *(top row)* CD first checks that a full CI run passed on that exact commit. It signs in to AWS through
> OIDC, so no AWS keys are stored in GitHub. It updates the stack, then releases each changed service separately.
>
> *(bottom row)* For each service it builds the image, scans it with Trivy, pushes it, and checks that the
> digest in the registry is the one it scanned. Then it moves the alias and runs a smoke test.
>
> *(roll-back box)* If the smoke test fails, CD moves the alias back to the previous version. We tested this
> with a deliberately broken release. Then an upload-to-playback test runs through the public API.
>
> *(orange chip)* Merge to serving takes about 15 minutes with no image change, and about half an hour when both
> services release. Rollback restores the image, not the database schema, so migrations are additive only.
> We missed one target: a Processing release step took 10.1 to 10.3 minutes against a 10-minute target.

**→**

### Slide 33 · "Trivy blocked a release over the running image" · 0:50 · 5c

**On screen:** the red log line at the top, four circles below it (✗ blocked, ? cause, fix, ✓ released).
**Do:** read the log line out loud, then touch each circle in turn.

> Two findings came from failed deliveries. On 21 October, CD stopped with this line: *"Trivy has 1 fixable
> HIGH/CRITICAL."* Production kept running the previous release.
>
> *(question mark)* The new image was clean. But CD also rescans the image it is about to replace, because
> that image is the rollback target. An advisory against it had been published the evening before. So the
> check blocked the very release that removed the vulnerable image.
>
> *(fix, tick)* We kept the strict scan for the new image and for every image we keep. For the image being
> replaced, the finding is now written into the release report instead of blocking. The next delivery released it.

**→**

### Slide 34 · "Paused Aurora made the deploy smoke test fail" · 0:45 · 5c

**On screen:** two red ✗ steps, each with a fix, ending in a green ✓.
**Do:** move from left to right.

> The second finding. Aurora pauses after five idle minutes. When a deploy changed no migration, nothing woke
> the database, and the smoke test's login got a 503.
>
> We added a retry on that first call: after 5, 10 and 15 seconds, at most three minutes, and every attempt is logged.
>
> Then we split the database per service, and three deliveries failed again, this time on Processing, because its
> cluster pauses separately. Now the first call to each service is retried, and delivery has been green since.

**→**

### Slide 35 · "Other findings from failed deliveries" · 0:25 · 5c

**On screen:** three tiles, each with a CD run link.
**Do:** touch each tile once.

> Three smaller findings. This AWS account caps Lambda memory at 3008 megabytes, below what we designed for. Our
> deploy tool refused a stack that had rolled back, even though AWS accepts it. And a formatting change altered a
> migration that was already released; the compatibility check held that release. Each fix now has a test.
>
> Now the demo.

**→**

---

## 6 · Demo

All clips play on their slide. Press **P** (or click the video) to start, pause and resume. They have no sound. The
times below are read from the player's clock.

### Slide 36 · "Demo: three use cases, three quality attributes" · 0:15

**On screen:** two groups. 6a has D1, D2 and D3; 6b has D4, D5 and D6.

> Six parts: three use cases, then three quality attributes. They are recordings against the live AWS system. The
> terminal ones I recorded today in a real terminal, with long waits cut or sped up, and labelled where they are.
> The pipeline I'll show live on GitHub.

**→**

### Slide 37 · D1 "Upload, processing and playback in the web app" · clip 0:24 · 0:30

> First, the web app. Owner A is already signed in. **[P]**

| Clip | Say |
|---|---|
| 0:02 | She uploads a lecture. |
| 0:04 | Accepted. The file went straight to S3, and processing runs in the background. |
| 0:08 | Processing complete. |
| 0:12 | Her library. |
| 0:16 | And it plays, only for her. |

**→** once the clip ends.

### Slide 38 · D2 "Batch upload with the Publisher CLI" · clip 0:31 · 0:35

> Now the Publisher, our second client. It's a command-line tool that uses only the public API. **[P]**

| Clip | Say |
|---|---|
| 0:02 | Three lecture files in a folder. |
| 0:06 | One publish command uploads all three and returns three job IDs. |
| 0:18 | *(we cut the encoding wait)* Then a status check on each. |
| 0:24 | All three done, through the same public API. |

**→**

### Slide 39 · D3 "Access is checked per owner" · clip 0:27 · 0:35

> What happens if someone else gets hold of a job ID? **[P]**

| Clip | Say |
|---|---|
| 0:03 | Owner A asks for her video: done. |
| 0:11 | Owner B asks for the same ID: "absent or unavailable". The API doesn't even confirm it exists. |
| 0:19 | And with no login at all: HTTP 401. |

After the clip:

> The check runs at the API on every request, not only in the user interface.

**→**

### Slide 40 · D4 "Fargate encoders scale 0 → 3 → 0" · clip 1:00 · 1:25

> Scalability. Five 72-megabyte recordings. They're too big for the Lambda lane, so they go to Fargate.
> Watch the encoder count. **[P]**

| Clip | Say |
|---|---|
| 0:03 | Five files, 72 megabytes each. |
| 0:10 | Published in the background. |
| 0:12 | The watcher starts. Zero encoders: nothing is running and nothing is billed. |
| 0:25 | The blue label: from here the wait plays at 16 times speed. |
| ≈ 0:36 | **[P] pause** |

While paused, trace the log from top to bottom:

> Three encoders. That's the cap, and there is never a fourth. Then the count drops while jobs are still waiting,
> because each encoder is a task that runs one job and exits, and the launcher starts new ones on its next
> one-minute tick. About five minutes of real time in all. **[P]**

| Clip | Say |
|---|---|
| ≈ 0:44 | Back at normal speed: capacity is back to zero. |
| ≈ 0:50 | And all five jobs are done. |

After the clip, point at the side panel:

> We measured the speed-up separately. With two encoders we got 1.45 times against a 1.6 target, a miss. With
> three we got 2.35 against 2.1, a pass.

**→**

### Slide 41 · D5 "Scripted load test against the live API" · clip 1:18 · 1:35

> Performance. A scripted load test against the live public API: ten users for sixty seconds. **[P]**

| Clip | Say |
|---|---|
| 0:03 | This is our load generator, running from this laptop over the internet through the public endpoint. |
| 0:17 | The run itself, at 16 times speed. |
| ≈ 0:23 | The result: 600 status requests and zero errors. |
| ≈ 0:30 | Now we build the report from the run's own raw samples. |
| ≈ 0:45 | **[P] pause** on the targets table. |

While paused, point at the table (the same numbers are on the right of the slide):

> Status p90 is 143 milliseconds against a 700 target. Zero errors out of 805 requests. Login p90 is about 370
> milliseconds against two seconds. All pass. **[P]**

| Clip | Say |
|---|---|
| ≈ 0:52 | Latency per route. |
| ≈ 0:58 | The distribution for the status call that the browser polls. |
| ≈ 1:04 | Throughput stays under the gateway limit of 20 requests a second. That limit is why we ran ten users, not more. |
| ≈ 1:10 | And the lane comparison: a median queue wait of 0.26 seconds on Lambda, 33 on Fargate. |

After the clip:

> Ten users over the internet is a smaller test than our earlier in-region benchmark, which was fifty users and
> 9,000 requests with a p90 of 58 milliseconds, using the same tool.

**→**

### Slide 42 · D6 "CI and CD runs for a change on Main" · live on GitHub · 1:40

**On screen:** the pipeline strip (PR → CI → merge → CI on Main → CD → live), and three clickable run boxes on the right.
**Do:** click a box, which opens GitHub in a new tab; walk through the run; close the tab or press ⌘W to come back.

> Maintainability. Here's the path every change takes, from a pull request all the way to live, and these are the
> actual runs for one change on 22 October. Let's follow that commit through.

Click **CI on Main 39733112331**:

> CI on Main for commit f07b5e6: 25 jobs passed, and three were skipped, which the gate confirmed were planned.
> Note the commit.

⌘W, then click **CD to live 39733859422**:

> CD started about two seconds after CI finished, on the same commit. The first job, "Refuse a commit without
> green CI", checks that CI passed. Then the deploy and the upload-to-playback test. All green, with no manual step.

⌘W, then click **Blocked by Trivy 39532075705**. Open the failed **Deploy** step and search for `fixable`:

> And this is the blocked release from earlier: "media: FAIL: Trivy has 1 fixable HIGH/CRITICAL". The deploy
> stopped, and production stayed on the previous version.

⌘W to go back to the deck. **→**

*If GitHub is slow or Zoom stutters, don't open the links. Point at the three boxes and say:* "These are the CI run,
the CD run on the same commit, and the blocked release from slide 33. All the links are in the deck."

### Slide 43 · "Summary" · 0:20

**Do:** touch each of the four tiles.

> To sum up: one public API with two clients, shown in D2. Checks at each service boundary, shown in D3. Encoders
> that scale from zero to three and back, shown in D4. And a pipeline that only deploys what it has tested, with
> every result recorded, including the misses. Thank you. We're happy to take questions.

Leave slide 43 up during Q&A. For a backup slide, type its number and press Enter, or press `O`.

---

## If asked (sections 5 and 6)

- **Why separate services in one repository?** Separation means each service owns its data, its release and its
  failures. Lanes, image import checks, IAM roles and per-service releases enforce that. One lockfile and one stack
  are still shared.
- **Why run CI again after the merge?** A pull-request run tests a preview merge. CD trusts only the push run on the
  exact commit that landed.
- **How do you know production runs the scanned image?** CD scans the local image, pushes it, and checks that the
  registry digest matches. The Lambda version records the digest.
- **Why not block on the old image's finding?** Blocking kept the vulnerable image in production. New and kept images
  are still scanned strictly, and the finding is written into the release record.
- **Does the smoke-test retry hide failures?** It covers only the first database call to each service, only on
  502/503/504, at most three retries within 180 s, and every attempt is logged. The release smoke test that runs after a
  migration is never retried.
- **Which scanners block a release?** Backup B09.
- **Is D4 ECS auto-scaling?** No. A launcher starts finite tasks from the backlog, capped at 3 by a database check,
  with a one-minute safety net. Nothing idle is billed.
- **Is the 72 MiB padding staging?** It's an MP4 free box. The video and audio streams are real and fully encoded;
  the padding only pushes the file over the 64 MiB lane limit.
- **What are the "bash: child setpgid" lines in D4?** Bash job-control noise from running the publish in the background.
  It doesn't affect the run, and all five jobs end `done`.
- **Why only 10 users in D5?** The API stage throttles at 20 requests a second, with a burst of 50. More users would
  only measure the throttle.
- **Are the clips real?** Yes. D1 is a browser recording from 23 Oct. D2–D5 are screen recordings of a real terminal
  against the live system, made on 26 Oct. Waits are cut (D2) or shown at 16× with a label (D4, D5). D5's report
  recomputes every figure from the raw samples.
- **Why "not found" for owner B rather than 403?** A 403 would confirm that the asset exists.
- **Why no live push today?** We don't change production right before a demo. The runs on slide 42 come from a real
  change on 22 October.
