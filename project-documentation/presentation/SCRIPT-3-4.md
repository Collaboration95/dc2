# Script: sections 3 and 4 (Ibrahim, Long, Guruprasath)

Slides 8–29 of `site/deck.html` (<http://127.0.0.1:8766/deck.html>). Target **≈ 17:20**.
Other tabs: [1 and 2](script-1-2.html) · [5 and 6](script-5-6.html).

**Keys:** `→`/`D` next · `←`/`A` back · `N` notes · number + Enter to jump.

| Part | Slides | Speaker | Target |
|---|---|---|---|
| 3a/3b Drivers, services, messaging | 8–12 | Ibrahim | 4:20 |
| 3a/3c Identity, domain model, clients | 13–18 | Long | 4:20 |
| 4a/4b AWS deployment, lanes | 19–23 | **Guruprasath** | 4:20 |
| 4c/4d Data, storage, one request end to end | 24–29 | Ibrahim | 4:10 |

Each speaker ends with a hand-off line naming the next person. Whoever is sharing presses **→**.
If time is short, cut slides 16, 21, 25 and 26 (marked *cut candidate*). Each one is a single sentence in the neighbouring slide.

---

## 3 · Logical architecture

### Slide 8 · "Three drivers for the logical design" · 0:30 · Ibrahim · 3a

**Do:** touch the tiles 1, 2, 3.

> Thanks, Guruprasath. Three requirements shaped the logical design. One: release and scale Processing on its own,
> because encoding is heavy and bursty. Two: survive duplicate messages and failed workers without losing or
> corrupting a job. Three: let clients reuse the platform without knowing its internals. Every decision in this
> section maps back to one of these three.

**→**

### Slide 9 · "Why Processing is a separate service" · 0:50 · Ibrahim · 3a

**Do:** read the decision row (choice, why, trade-off), then point at the two boxes.

> Decisions AD-01 and AD-02. We split the system into two services, Media and Processing, and each owns its data.
>
> Why there? Processing has its own rules, jobs, attempts and leases, and a completely different CPU profile.
> Identity and playback stay in Media, because they need the account and the asset together. Splitting those out
> would turn database joins into network calls without adding any rules of their own.
>
> The trade-off is more integration work between the two, which the next slides cover.

**→**

### Slide 10 · "Two services, each with its own layers and data" · 1:15 · Ibrahim · 3b

**Do:** go top to bottom: clients, gateway, then down each service column, then the SQS link and the shared-kernel strip.

> Here is the logical view. Both clients, the browser app and the Publisher, go through the gateway and its authorizer.
>
> *(Media column)* Media has an API layer, the Asset domain, and persistence in its own database, media_db.
>
> *(Processing column)* Processing has its API, the Job, Attempt and lease model, and the encoders as adapters at the
> edge, with its own processing_db.
>
> *(SQS)* The two talk only through SQS.
>
> *(bottom strip)* What they share is deliberately small: the message contracts, the delivery library and some runtime
> support. The Lambdas and encoders you'll see later are roles inside a service, not extra services.

**→**

### Slide 11 · "Outbox → SQS → inbox: at-least-once, deduplicated" · 0:45 · Ibrahim · 3a

**Do:** follow the arrow left to right.

> Decision AD-11: how a message gets between them safely. SQS is only durable once it has received a message. So
> if we commit the state and then crash before sending, the intent is lost.
>
> We use an outbox. The state change and an outbox row are committed in one transaction. A relay sends the row to
> SQS. On the other side, an inbox deduplicates by message ID and commits in its own transaction.
>
> The trade-off: delivery is at-least-once and the result is eventually consistent, so every handler must tolerate
> duplicates.

**→**

### Slide 12 · "Media and Processing communicate only through SQS" · 1:00 · Ibrahim · 3a/3b

**Do:** grey "Before" row first, then the top row (command path), then the bottom row (result path), then the green chips.

> Before, Media called Processing over HTTP and shared Redis. If Processing was down, uploads failed.
>
> *(top row)* Now Media commits with an outbox, SQS carries the command, and Processing's inbox commits it.
> *(bottom row)* The result comes back the same way and lands in Media as a projection.
>
> *(chips)* We tested the isolation on AWS. We switched off the command consumer for 48 seconds, and Media still
> accepted uploads with a 202. The job completed 59 seconds after we turned it back on. In another run, 18 work
> messages were sent for 9 jobs, and all 9 finished once each, with no manual clean-up.
>
> Long takes us into the domain model.

**→**

### Slide 13 · "The gateway authorizer supplies the owner identity" · 0:40 · Long · 3a

**Do:** grey "Before" row, then the "As built" row.

> Thanks, Ibrahim. First, who is asking. Before, a client sent a service token and an owner header, and the service
> trusted that header.
>
> Now the client goes through the gateway, and Media's authorizer establishes who the caller is. A trusted Actor is
> handed to the service, so the service never reads identity from the request itself. Between services, queues are
> authenticated with IAM.
>
> One honest limit: Processing's protected routes still depend on Media's user lookup.

**→**

### Slide 14 · "Context map: Media customer, Processing supplier" · 0:50 · Long · 3c

**Do:** left box, the arrows in the middle, then the right box.

> The context map. Media, the Asset context, is the customer. Processing, the Job context, is the supplier.
>
> Media translates an Asset into a command and translates the result back into its own projection. Processing
> translates messages into its own job model, and that model owns the lease rules.
>
> Between them is a published language: five message kinds, which are submit, retry, cancel, work and result. Plus
> two OpenAPI documents at version 1.0.0. We follow an N and N-minus-1 policy, so each service accepts the current
> and the previous contract version. That is tested, but not yet exercised live.

**→**

### Slide 15 · "Aggregates: Asset in Media, Job in Processing" · 0:50 · Long · 3c

**Do:** left card's ticks, the link in the middle, then the right card's ticks.

> Two aggregates, each guarding its own rules.
>
> The Asset, in Media, pins the exact source, allows one job per asset, and is deleted as a tombstone so that late
> messages can't bring it back.
>
> The Job, in Processing, knows its current attempt, holds a live lease, and can be cancelled before it is submitted.
>
> *(middle)* They are linked by ID only: no shared objects and no foreign keys across the boundary.

**→**

### Slide 16 · "Ubiquitous language: six core terms" · 0:25 · Long · 3c · *cut candidate*

**Do:** sweep across the six tiles.

> The six words we use the same way in code, docs and conversation. An Asset is an owner's uploaded video. A Job is
> the processing of one Asset. An Attempt is one try at a Job. The Source revision is the exact S3 object version. A
> Lease is the right to write a result. And the Projection is Media's copy of the results.

**→**

### Slide 17 · "The projection applies only newer result versions" · 0:45 · Long · 3c

**Do:** go top to bottom: v3 applied, v2 ignored, v3 again rejected.

> Because messages can arrive late or twice, the projection is ordered. Each result carries a full snapshot and a
> state version.
>
> Version 3 arrives and is applied. Version 2 arrives late, it's older, so it's ignored. A different version 3
> arrives that conflicts with what we stored, and it is rejected. The stored state stays at version 3.
>
> This is event-carried state transfer, not event sourcing. We keep the current state, not the history.

**→**

### Slide 18 · "Both clients upload with the same three API calls" · 0:50 · Long · 3c

**Do:** the produce row 1-2-3, then the play row, then the two zero chips.

> Both clients produce the same way: one, reserve; two, upload directly to S3; three, finalize. Status, retry and
> delete go through the same public API.
>
> To play, Media reads its projection and returns a signed MP4, or an HLS playlist whose segments redirect to S3.
>
> *(chips)* The Publisher has zero imports of service code and zero database credentials, and a test fails the build
> if that changes. You'll see it in the demo.
>
> Guruprasath, over to you for how this runs on AWS.

**→**

---

## 4 · Physical architecture

### Slide 19 · "Serverless and finite tasks keep idle cost low" · 0:50 · Guruprasath · 4a

**Do:** read the decision row, then the big number.

> Thanks, Long. The physical design starts from cost. Decisions AD-10, AD-12 and AD-27: Lambda for the APIs, finite
> Fargate tasks for encoding, and Aurora that pauses when idle. Nothing runs when nobody is using it.
>
> Our model puts the idle cost at three to five dollars a month. That's a model, not a bill. It predates the second
> database cluster, and a budget alarm at 20 dollars watches the real spend.
>
> The trade-off is cold starts. The first database read after a pause takes about 4.7 seconds.

**→**

### Slide 20 · "AWS nodes: edge, private Lambdas, Fargate encoders" · 1:15 · Guruprasath · 4b

**Do:** go left to right: edge, VPC, private subnets, public subnet, then the services along the bottom.

> The deployment view. Clients reach CloudFront and an HTTP API, throttled at 20 requests a second with a burst
> of 50, then the authorizer.
>
> Inside one VPC in Singapore, across two availability zones: the private subnets hold Media's four functions and
> Processing's seven, including the short-clip Lambda, capped at two at a time. There are two Aurora clusters, one
> per service, each scaling from zero to two capacity units.
>
> The Fargate encoders run in a public subnet with no inbound rules. That's zero to three tasks, each with two
> vCPUs and four gigabytes, and each runs one attempt and exits.
>
> Along the bottom: four queues with dead-letter queues, S3 for the media, ECR for the images, thirteen alarms
> and the budget.

**→**

### Slide 21 · "IPv6 egress instead of a NAT gateway" · 0:30 · Guruprasath · 4a · *cut candidate*

**Do:** follow the arrow, then point at the crossed-out NAT.

> One cost decision worth a slide, AD-18. Private Lambdas still need to reach AWS APIs. A NAT gateway would be a
> fixed monthly cost, so we use egress-only IPv6 plus an S3 endpoint instead. The trade-off: we can only call
> services that have dual-stack endpoints.

**→**

### Slide 22 · "Short clips go to Lambda, the rest to Fargate" · 1:00 · Guruprasath · 4a/4b

**Do:** go left to right: the work message, the size filter, the two lanes, then the shared pipeline at the bottom.

> Two encoding lanes. When a work message arrives, the dispatcher knows only the file size.
>
> Small files go to the short Lambda. It claims the job, downloads the file and probes it. If it's at most 60
> seconds, 64 megabytes and 1080p, it encodes it. If not, it redirects the job to Fargate, and that redirect is
> fenced, so a job can't bounce back and forth.
>
> Large files go straight to the Fargate lane, zero to three finite encoders.
>
> *(bottom)* Both lanes use the same lease pipeline: claim, encode, commit.

**→**

### Slide 23 · "Short lane: queue wait met, end-to-end missed" · 0:45 · Guruprasath · 4a

**Do:** the three numbers left to right, then the orange "Next" line.

> Did the short lane pay off? Partly. Queue wait dropped from 32.6 seconds on Fargate to 0.26 seconds on Lambda,
> which meets the target. Each encode costs about three hundredths of a cent, against two tenths on Fargate.
>
> But end to end, warm, it still takes 45 seconds against our 20-second aim. That's a miss, and 35 to 80
> seconds per job are not yet explained. The next step is per-stage tracing.
>
> Ibrahim, over to you: where the data lives, and one request end to end.

**→**

### Slide 24 · "One Aurora cluster, schema and roles per service" · 1:00 · Ibrahim · 4c

**Do:** left database, right database, then the role chips.

> Thanks. Each service has its own Aurora cluster, schema and roles. media_db holds the Asset, its source pin, the
> projection, and its outbox and inbox. processing_db holds the Job, attempts, leases, and its own outbox and inbox.
>
> There are no foreign keys between them. The schema owner role can't log in. A migrator changes the schema, and the
> runtime role can only read and write rows.
>
> We split onto separate clusters live, using a snapshot and a clone so no data was lost. The honest limit is that
> each cluster is a single instance with no failover.

**→**

### Slide 25 · "S3: source pinned by version, output per attempt" · 0:30 · Ibrahim · 4c · *cut candidate*

**Do:** top key, then bottom key.

> In S3, an upload lands under staging, per owner and reservation, and the object's VersionId becomes the source pin.
> Output is written per job and per attempt, so a retry never overwrites an earlier attempt.

**→**

### Slide 26 · "Representative use case: upload to playback" · 0:20 · Ibrahim · 4d · *cut candidate*

**Do:** sweep the six steps.

> To tie it together, one request end to end: reserve, upload, hand-off, route, encode, play. The next three slides
> zoom into upload, encode and play.

**→**

### Slide 27 · "Upload: direct to S3, version pinned on finalize" · 0:50 · Ibrahim · 4d

**Do:** follow the sequence top to bottom.

> Upload. The client reserves, and gets a grant valid for 15 minutes. It posts the file, up to 100 megabytes,
> directly to S3, so the bytes never pass through our API.
>
> On finalize, Media checks the exact S3 version, the size and the hash. Then, in one transaction, it writes the Asset,
> the source pin and an outbox row. If someone replays the upload, that creates a new S3 version, and it cannot
> change the pin.

**→**

### Slide 28 · "Encode: a lease decides which worker may commit" · 1:00 · Ibrahim · 4d

**Do:** follow the sequence, then point at the redirect note.

> Encode. The command passes the inbox and its guard, and a work message is delivered to an encoder. The encoder claims
> a lease. To commit, it must hold the current attempt and a live lease, checked against the database clock. So an old
> or slow worker can never overwrite a newer result. Then the message is acknowledged.
>
> If a worker dies, the attempt is marked abandoned and the job failed. The owner can retry from the stored source. It
> is not re-queued automatically.

**→**

### Slide 29 · "Playback: owner check, then a signed URL" · 0:40 · Ibrahim · 4d

**Do:** the result snapshot on the left, then the play request on the right.

> Playback. Processing's result snapshot reaches Media, and only newer snapshots apply.
>
> When the owner presses play, Media checks ownership first, then returns a signed URL: an MP4 with range responses, or
> an HLS playlist whose segments redirect to S3. CloudFront does not cache the API or playback, so nothing private is
> held at the edge.
>
> Guruprasath: how a change gets here safely.

**→** Continue in the [5 and 6 script](script-5-6.html).

---

## If asked (sections 3 and 4)

- **Why not split identity or playback into services?** Playback and retry decisions need the owner and the asset
  together. Splitting would turn joins into service calls without adding any rules.
- **What happens on a duplicate message?** The inbox deduplicates by message ID, and the projection ignores older or
  conflicting versions (slide 17).
- **What happens if a worker dies mid-encode?** Its lease expires, the attempt is abandoned and the job fails. The owner
  retries on the pinned source (UC-4). Backup B07.
- **Why is Fargate in a public subnet?** It avoids a NAT gateway. The task has no inbound rules and only makes outbound
  calls. Backup B04.
- **What's the database layout?** Backup B05 has the ER diagrams. The job state machine is in B03.
- **What does it cost?** The idle model is 3–5 USD a month, before the second cluster. The actual bill is not
  established yet, and a budget alarm is set at 20 USD.
- **Is the combined encoder cap 3?** Fargate is capped at 3 and the short Lambda at 2, so up to 5 encodes can run at once.
