# Script: title, sections 1 and 2 (Guruprasath)

Slides 1–7 of `site/deck.html` (<http://127.0.0.1:8766/deck.html>). Target **≈ 3:05**, then hand over to Ibrahim.
Other tabs: [3 and 4](script-3-4.html) · [5 and 6](script-5-6.html).

**Keys:** `→`/`D` next · `←`/`A` back · `N` notes · number + Enter to jump · `F` full screen.

| Part | Slides | Target |
|---|---|---|
| Title + 1 Overview | 1–5 | 1:45 |
| 2 Project conduct | 6–7 | 1:20 |

**Before you start:** open the deck in Chrome, go full screen, and share that window in Zoom.

---

## Title and 1 · Overview (target 1:45)

Covers **1a** business problem, **1b** platform thinking, **1c** scope.

### Slide 1 "FlickPond: a video processing platform on AWS" (≈ 20 s)
Point at the three name boxes.

> Hi, I'm Guruprasath. We're Team 17: Ibrahim, Long and me. I led cloud and delivery, Ibrahim the backend
> services, and Long the domain model and contracts. I'll cover the overview, project conduct, the AWS deployment, DevOps and the demo; my teammates cover the logical and physical architecture.

### Slide 2 "Every video app rebuilds upload, encoding, playback" (≈ 30 s)
Point at the four people, then the chain, then the orange chip.

> The problem. Course teams, trainers and small studios all need the same four things for video: upload
> what they own, convert it so it plays on any device, see whether that worked, and keep playback private.
> Each application builds this again. And conversion is heavy: minutes of CPU per video, competing with logins on the same machine.

### Slide 3 "Two clients use one public API; two services sit behind it" (≈ 30 s)
Point left to right along the arrows, then at the two green chips.

> Our answer is a platform. The workflow is offered through one public API. The unit it manages is an owned
> video and its processing job. Owners upload and the same owners watch. Integrators build new clients on
> the API, and operators manage capacity and releases. A second client, the Publisher command-line tool, uses only that API; a test fails the build if it imports service code.

### Slide 4 "Inherited from Project 1, rebuilt in Project 2" (≈ 25 s)
Grey left panel, then the coloured right panel.

> Scope. We inherited FlickPond: one application on one machine, with FFmpeg encoding. We kept the
> encoding and credit it to that team. We rebuilt the rest: two services with their own data, queues
> between them, and a serverless deployment on AWS. Seven use cases are in scope. Sharing with other
> viewers and multi-region are out.

### Slide 5 "Four design themes" (≈ 15 s)
Touch each tile once.

> Four themes run through the talk. One public API with two clients. Checks at each service boundary.
> Scale to zero when idle. And every number links to a real run, misses included.

→ straight into section 2.

---

## 2 · Project conduct (target 1:20)

Covers **2a** status, **2b** milestones and effort per member.

### Slide 6 "Status: all planned use cases delivered and running" (≈ 35 s)
Point at 7/7, then the two groups of chips.

> Status. All seven planned use cases are delivered and running on the live AWS environment. It has been
> up since 18 October and redeploys after every green build on Main. We also added a few things beyond the
> plan: edit, delete and admin routes, and a Lambda lane for short clips. What remains: end-to-end latency
> is about 45 seconds against a 20-second aim, and the final report revision is due on 16 November.

### Slide 7 "Milestones: proposal 4 Oct, code freeze 23 Oct" (≈ 40 s)
Follow the timeline left to right; stop at the orange dot and the grey dot; then the effort tiles.

> Milestones. Proposal on 4 October. Design finished on the 9th, two days late, because we completed the
> domain analysis before changing code. Media and Processing were split into two services on the 12th and
> 13th. First deploy to AWS on the 17th, the live environment and CD on the 18th and 19th. We had planned
> to freeze on the 20th. The Lambda lane and the database split went live on the 21st, and the code froze
> on the 23rd. Effort was split equally: 11 person-days each, 33 against 31 planned. The extra went into
> the delivery pipeline.
>
> Ibrahim, over to you for the logical architecture.

**Hand over to Ibrahim** and let him take the clicker from slide 8 (or keep pressing → for him).

---

## If asked (sections 1 and 2)

#### Section 1
- **Why call it a platform?** Two independent clients use one public API, and capacity belongs to the platform rather than the client. Both clients are ours, so we claim reuse, not adoption.
- **Why build on someone else's Project 1?** It already had a real CPU-heavy, asynchronous workload, so the change could be measured. The inherited parts are credited by name.
- **Why not split identity or playback into services?** Playback and retry decisions need the owner and the asset together. Splitting them would turn database joins into service calls without adding rules of their own.
- **Can a lecturer share a video with students?** No, sharing is out of scope. The contract reserves a viewer role, but nothing issues it. (B02)

#### Section 2
- **Are the person-days timesheets?** No. They are a team-agreed equal allocation of the proposal's work packages. Everything was committed through one account, so git history cannot attribute work.
- **Why did effort overrun?** One planned deployment became three proof runs, a persistent environment and a CD pipeline. The AWS and delivery package went from 4 to 6 person-days.
- **What is the biggest open issue?** End-to-end latency: 35 to 80 seconds per job are not explained yet. The next step is per-stage timestamps. (B01)
- **Why waves, not sprints?** It was four weeks with three people and hard dependencies, so issues were grouped by dependency.
