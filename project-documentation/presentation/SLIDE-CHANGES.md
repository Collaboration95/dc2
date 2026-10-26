# Slide changes for Guruprasath's sections (title, 1, 2, 5, 6, closing)

`site/deck.html` was refitted around `SCRIPT-guruprasath.md`. The untouched original is
`site/deck-before.html`; open both at <http://127.0.0.1:8766/> to compare. Nothing is committed.

The main deck went from 47 to 43 slides. Guruprasath's slides went from 25 to 21. Sections 3 and 4 are
unchanged apart from renumbering: old 10–31 are now 8–29, and the footers, `data-num` and note labels follow
the new numbers. Backup gains B21. Every changed slide got new speaker notes: short bullets with the
numbers and run IDs, no script sentences.

## Changes

| Old | New | What changed | Why (script beat) |
|---|---|---|---|
| 1 Title | 1 | The single name line became three name boxes with each person's specialism. Notes now say Guruprasath gives the intro. | Beat 1.0: the intro names the three people and their roles. |
| 2 "Teams keep rebuilding…" | 2 | The persona captions are shorter. The chip chain is now upload → convert → track → play privately "× every app", and a new orange chip reads "encoding: minutes of CPU per video, in bursts". | Beat 1a names the four needs and the capacity problem. The old slide did not show the burst. |
| 3 "Two clients, one public contract…" | 3 | The caption sentence was replaced by two chips: "seed: an owned video + its job" and "Publisher: 0 service imports · 0 DB credentials". The Owners box now says "produce + consume". | Beat 1b: seed, producers = consumers, and the second client as proof. |
| 4 "We kept the engine…" + 6 "Seven use cases in scope…" | 4 | Merged. The before/after stays. The worker box notes "FFmpeg · HLS, kept". The bottom row is now "In: 7 use cases" next to a dashed "Out: sharing · tenants · live streaming · multi-region". Old slide 6 was dropped. | Beat 1c covers inherited, added and in/out in 25 s, so one slide is enough. |
| 5 "Four things…" | 5 | Notes only. | Beat T. |
| 9 "All seven use cases done…" | 6 | Moved before the timeline (2a before 2b). The headline now says "live". The chips are plain-language issues instead of AISS IDs, with the latency number "45 s vs 20 s aim". Added "live since 18 Oct" and a CD-green footer link. | Beat 2a follows the guideline order and states the latency miss once. |
| 7 "Proposal to live platform in seventeen days" + 8 "Equal effort…" | 7 | Merged. The timeline is cropped to free space. Below it are four effort tiles: 11 pd for each member, plus an orange "33 pd vs 31 planned". The headline is now "…in under three weeks". | Beat 2b covers milestones and effort in 35 s. |
| 32 "One repository, three images…" | 30 | Added a branch row: feature → Dev gate → `dev/closeout` → Full verification → `Main` → green CI → dc2-live. Dropped the third alias box. New footer links: image runtime check and source strategy. | Beat 5a covers repo, artifacts and branching on one picture. |
| 33 "Changed lanes…" (job-name chip list) + 34 "Security scans and coverage…" | 31 | Merged and redrawn as four stage cards (laptop, PR → dev, PR → Main, merged commit), each with its gate and time. Three big numbers below: 25 jobs green · ≥80% per package · 0 silent skips. | Beat 5b-1. The old slides were lists of exact job names, unreadable over Zoom. |
| 35 "Promote exactly the scanned bytes…" | 32 | Added an orange miss chip, "release step 10.1–10.3 min · target 10", and a footer link to restore test 39271754470. | Beat 5b-2 states the miss and the proven restore. |
| 36 "Fixable findings block releases…" | backup B21 "Which scanners block a release?" | Moved out of the main deck. | Scanners are common practice, not unique. The script skips them; this backup answers the question. |
| 37 "Our security gate blocked its own fix" | 33 | Notes only. | Beat 5c-1. |
| 38 "Splitting the database also split the wake-up" | 34 | Notes only. | Beat 5c-2. |
| 39 "Cloud surprises became regression tests" (CUT-1) | 35 | The headline is now "Surprises became tests; ops hardening still open". Added an AISS-04 row of four orange chips: no branch protection, no staging, admin deploy role, alarms notify nobody. Footer links. Removed the cut mark. | Beat 5c-3 covers the findings and the open issues in one place. |
| 40 "Six clips…" | 36 | The headline is now "Three journeys, three qualities, on the live system". D6 reads "real CI → CD run". A footer receipt says "Recorded 23 Oct 2026 on dc2-live · only processing waits cut". | Beat 6.0. D6 is a walk-through, not a clip. |
| 41 D1 | 37 | The side sentence was replaced by a "Watch" ladder: Accepted → Complete → plays. | Beat 6a-D1 cues. |
| 42 D2 | 38 | The headline is now "D2 — A second client, same public contract" (fits one line). Side panel: big "3/3 done, one command" and two zero chips. | Beat 6a-D2. |
| 43 D3 | 39 | Side panel: "Same job ID" with owner A ✓, owner B ✗, anonymous 401. | Beat 6a-D3. |
| 44 D4 | 40 | Side panel: big "0→3→0", and the speed-up receipts 2 enc 1.45×/1.6× (orange) and 3 enc 2.35×/2.1× (green). | Beat 6b-D4 shows the kept miss right where the claim is made. |
| 45 D5 | 41 | Side panel: big 132 ms (status p90, target 700) and 0/795 errors, both read from the clip's own report, plus "10 users · 60 s". | Beat 6b-D5: the paused-clip line points at these numbers. |
| 46 D6 | 42 | The headline is now "D6 — A real change through CI and CD to production". The placeholder inside the clip box shows PR → CI → merge → CI on Main → CD → live and "D6 clip not recorded yet". The side panel has three clickable run boxes: CI 39733112331, CD 39733859422, and "Blocked by Trivy" 39532075705. The `.clip` markup and `data-clip="clips/D6.mp4"` are unchanged, so a recorded D6.mp4 replaces the placeholder automatically. | Beat 6b-D6: live walk-through. |
| 47 Closing | 43 | The headline is now "Four things, each shown on the live system". The tiles now match slide 5 (Reusable · Correct at boundaries · Pay for work · Receipts) and each carries its demo proof (D2, D3, D4, misses kept). | Close beat bookends slide 5. |
| B20 caption | B20 | "slide 35" is now "slide 32". | Numbering. |

Also updated: the slide numbers in `PRESENTING.md` §4–5 (demo 37–42, findings 33–34).

## Timing per section

Words are counted by a script over the spoken lines in `SCRIPT-guruprasath.md`. Talk is timed at
140 words a minute. Words spoken over a running clip add no time.

| Section | Talk words | Over-clip words | Clip time | Estimate | Target | Guideline (talk) |
|---|---|---|---|---|---|---|
| Title + 1 Overview | 247 | – | – | 1:45 | 1:45 | 2:00 |
| 2 Project conduct | 164 | – | – | 1:10 | 1:20 | 1:30 |
| 5 DevOps and lifecycle | 686 | – | – | 4:55 (≈ 5:10 with slide changes) | 5:15 | 6:00 |
| 6 Demo + close | 391 | 196 | 2:59 | 5:46 (≈ 6:35 with GitHub page loads and clip starts) | 7:00 | 8:00 |
| **Total** | **1,488** | **196** | **2:59** | **≈ 14:40** | 15:20 | 18:00 |

Narration over clips stays between 1.2 and 1.4 words a second, well under the 2.3 maximum. Each clip has
at most one planned pause: D4 at about 0:20, when the whole encoder log appears at once, and D5 at about
0:36, on the targets table.

## Checks run

- `node --check` on the extracted deck script: OK.
- `_check.py` on an rsync copy of `site/`: 11 pages and 345 local links checked, no errors. `deck-before.html` passes too.
- Headless screenshots at 1280×720 of slides 1–7, 30–43 and B21: no overflow or overlap. Two headlines
  still wrap onto two lines: slide 2 (unchanged) and slide 32 (unchanged).


## Round 3 (Guruprasath's review)

Applied on top of round 2. The main deck still has 43 slides, so the main slide numbers are unchanged.
The backups went from 21 to 9 (B01–B09). This is still local only.

### Changes

| Slide | Change | Request |
|---|---|---|
| All main slides | Headlines rewritten in plain engineering language; see the table below. Chips and captions swept for slogans: "× every app" → "rebuilt in every app"; slide 3 chip → "Publisher CLI uses only the public API"; slide 18 caps → "service imports in Publisher" / "DB credentials in Publisher"; slide 31 dropped "0 silent skips", and "ticket to CD" → "triggers CD"; B08 "Promote / restore" → "Move alias / roll back". | General |
| 4 | Removed the "In: 7 use cases" and "Out" chips. Out-of-scope items stay in the notes and backup B02. | 1 |
| 5, 43 | Theme tiles are now plain: "One public API, two clients", "Checks at each service boundary", "Scale to zero when idle", "Results linked to real runs". On the closing slide each tile names where the demo showed it. | General |
| 6 | Reframed as "all planned use cases delivered". The right side now has two groups. "Added beyond the plan": edit/delete/admin routes, and the Lambda lane for short clips. "Remaining": end-to-end latency 45 s vs 20 s, and the final report revision on 16 Nov. The rollback, ops and "not yet measured" chips are gone. | 2 |
| 7 | New timeline with ten dated points: proposal 4 Oct · design done 9 Oct (+2 days) · Media and Processing split 12–13 Oct · AWS template and pipeline 15 Oct · first AWS deploy 17 Oct · dc2-live and CD 18–19 Oct · planned freeze 20 Oct (grey, dashed) · Lambda lane and DB split 21 Oct · code freeze 23 Oct · presentation 26 Oct. The effort tiles are kept. | 3 |
| 32 | New headline. Box text is now plain: "Check CI passed / same commit SHA", "AWS via OIDC / no stored keys", "Move alias / to that digest", "Smoke test / per service", "Upload test / public API", "Roll back". | 4 |
| 33 | Rebuilt as the Trivy story only: the real log line `media: FAIL: Trivy has 1 fixable HIGH/CRITICAL`, then blocked (CD 39532075705) → cause (running image had the certifi advisory) → fix (AD-28) → released (CD 39545554380). Footer links to both runs and the delivery record. | 5 |
| 34 | Now the full Aurora-pause story, which slide 33 used to share: login 503 (39542434067) → retry login → after the DB split, Processing 503 ×3 → retry the first call to each service → green (39733859422), with a one-line cause underneath. Footer links to the three runs. | 5 |
| 35 | Headline "Other findings from failed deliveries". Three plain finding tiles, each with its CD run ID; the ops-gap list is removed. | 6 |
| 37–42 | Native `<video controls>` player: scrub bar, click to pause; P still works; clicking never changes slides; arrow keys still change slides after the player is clicked. The custom play button and progress bar are hidden. The video is now 960×540 (D6 944×531) and the side panel is about 196 px, right-aligned. Side panels are plain: D1 lists its UCs and what is on screen; D2 shows "3/3, all videos uploaded and processed"; D3 shows owner A done / owner B not found / no login HTTP 401; D4 shows 0→3→0 and the speed-ups against target; D5 shows 132 ms and 0/795. | 7 |
| 37–41 | Clip labels are now 0:24 / 0:22 / 0:18 / 0:32 / 1:06. The notes have new cue times; the D4 pause is at about 0:17.5. | 8 |
| B01 | The "Next step" column is removed. "Owner" is replaced by "Area" (Platform, Backend, Delivery, Verification), and AISS-04 is one row: "closed, not planned". | 9 |
| Backups | Deleted old B02, B03, B04, B06, B07, B08, B09, B10, B11, B12, B14 and B16. The rest are renumbered: B01 open issues, B02 scope, B03 retry, B04 public subnet, B05 tables, B06 security alerts, B07 worker death, B08 CI/CD diagram, B09 scanners. Speaker-note references to deleted backups are removed and the remaining ones renumbered. | 10 |

`PRESENTING.md` is updated for the new clip lengths and descriptions, the D4 pause point, and the player controls.

### Headline rewrites (old → new)

| Slide | Old | New |
|---|---|---|
| 1 | FlickPond: from video app to reusable media platform | FlickPond: a video processing platform on AWS |
| 2 | Teams keep rebuilding upload-to-playback; we made it reusable | Every video app rebuilds upload, encoding, playback |
| 3 | Two clients, one public contract, owned services behind | Two clients use one public API; two services sit behind it |
| 4 | We kept the engine; we changed ownership and runtime | Inherited from Project 1, rebuilt in Project 2 |
| 5 | Four things we’d like you to remember | Four design themes |
| 6 | All seven use cases live; five issue classes open | Status: all planned use cases delivered and running |
| 7 | Proposal to live platform in under three weeks | Milestones: proposal 4 Oct, code freeze 23 Oct |
| 8 | Three drivers shaped every logical decision | Three drivers for the logical design |
| 9 | Split where the rules change: the encoding lifecycle | Why Processing is a separate service |
| 11 | Commit locally, deliver asynchronously, deduplicate on arrival | Outbox → SQS → inbox: at-least-once, deduplicated |
| 12 | No synchronous call between services on the business path | Media and Processing communicate only through SQS |
| 13 | Services receive a trusted owner, not a token | The gateway authorizer supplies the owner identity |
| 14 | Media is the customer; Processing is the supplier | Context map: Media customer, Processing supplier |
| 15 | Two aggregates, each guarding its own invariants | Aggregates: Asset in Media, Job in Processing |
| 16 | Six words the whole codebase agrees on | Ubiquitous language: six core terms |
| 17 | Late or duplicate results cannot overwrite newer truth | The projection applies only newer result versions |
| 18 | Browser and Publisher use the same three calls | Both clients upload with the same three API calls |
| 19 | Pay for work, not for waiting | Serverless and finite tasks keep idle cost low |
| 20 | Managed edge, private compute, finite encoders | AWS nodes: edge, private Lambdas, Fargate encoders |
| 22 | Short clips to Lambda; everything else to Fargate | Short clips go to Lambda, the rest to Fargate |
| 23 | Queue wait solved; end-to-end latency still misses | Short lane: queue wait met, end-to-end missed |
| 24 | Each context owns its cluster, schema and roles | One Aurora cluster, schema and roles per service |
| 25 | Sources pinned by version; outputs scoped by attempt | S3: source pinned by version, output per attempt |
| 26 | One use case crosses every boundary: upload to play | Representative use case: upload to playback |
| 27 | Bytes go straight to S3; the version is pinned | Upload: direct to S3, version pinned on finalize |
| 28 | Leases fence stale workers; fallback cannot loop | Encode: a lease decides which worker may commit |
| 29 | Playback checks the owner, then grants temporary access | Playback: owner check, then a signed URL |
| 30 | One repository, three images, independent releases | One repository, three images, per-service releases |
| 31 | Changed lanes on pull requests; everything before Main | CI: changed lanes on pull requests, full run on Main |
| 32 | Promote exactly the scanned bytes, with automatic restore | Release: the scanned image is the one deployed |
| 33 | Our security gate blocked its own fix | Trivy blocked a release over the running image |
| 34 | Splitting the database also split the wake-up | Paused Aurora made the deploy smoke test fail |
| 35 | Surprises became tests; ops hardening still open | Other findings from failed deliveries |
| 36 | Three journeys, three qualities, on the live system | Demo: three use cases, three quality attributes |
| 37 | D1 — An owner uploads once and plays it back | D1 — Upload, processing and playback in the web app |
| 38 | D2 — A second client, same public contract | D2 — Batch upload with the Publisher CLI |
| 39 | D3 — Knowing an ID is not enough | D3 — Access is checked per owner |
| 40 | D4 — Capacity follows work: 0 → 3 → 0 | D4 — Fargate encoders scale 0 → 3 → 0 |
| 41 | D5 — A repeatable scripted load test | D5 — Scripted load test against the live API |
| 42 | D6 — A real change through CI and CD to production | D6 — CI and CD runs for a change on Main |
| 43 | Four things, each shown on the live system | Summary |

### Timing after round 3

| Section | Talk words | Over-clip words | Clip time | Estimate | Target | Guideline (talk) |
|---|---|---|---|---|---|---|
| Title + 1 Overview | 249 | – | – | 1:46 | 1:45 | 2:00 |
| 2 Project conduct | 178 | – | – | 1:16 | 1:20 | 1:30 |
| 5 DevOps and lifecycle | 660 | – | – | 4:42 (≈ 5:00 with slide changes) | 5:15 | 6:00 |
| 6 Demo + close | 392 | 172 | 2:42 | 5:30 (≈ 6:15 with GitHub loads and clip starts) | 7:00 | 8:00 |
| **Total** | **1,479** | **172** | **2:42** | **≈ 14:15** | 15:20 | 18:00 |

### Checks

- `node --check` on the deck script: OK.
- `_check.py` on an rsync copy of `site/`: 11 pages, 345 local links, no errors.
- Screenshots at 1280×720 of slides 1–7, 11, 14, 18, 20, 27, 30–43, B01 and B09: no overflow, and every round-3 headline fits on one line.
