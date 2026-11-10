# R1 - Lessons from the older architecture deck

Research date: 26 October 2026. Scope: visual comparison and source checks; no implementation or deployment. Current checkout HEAD is Main `76282d3b5a141f6548056f2506f9d5aff0742692`. System assertions below refer to this commit, not a fresh AWS inventory.

Reference: the 24-page **Flickpond - Architecture Presentation** PDF identified in [FEEDBACK.md](../FEEDBACK.md), attachment `69126276-ab16-47ff-8dce-05794f4b9464-37522de2-1c8e-4574-9753-f9ab31bd7d52-pdf.pdf`. **PDF p. N** always means the one-based PDF page, not a current-deck slide. The reference describes a different course/codebase; its performance figures, classes, infrastructure and claimed controls are not evidence for this project.

## Inspection record and a consequential asset/deck mismatch

- Rendered **all 24 PDF pages** with `pdftoppm -r 110 -png`, producing `old-01.png` through `old-24.png`, each 1467 x 825, in `/var/folders/g8/5_hq0kbs4499lmjhph03mvgc0000gn/T/dc2-r1-1uxcjb_o/`. Visually inspected every page, including pages without diagrams. `pdftotext -layout` supplemented, rather than replaced, image inspection.
- Rendered and visually inspected **all 11** `presentation/site/assets/img/*.svg` with T3's local Chromium HTML preview, embedding each actual SVG as an image. This preserves the Mermaid assets' XHTML `foreignObject` labels. Inspected the complete sequence at 1500 px width after a wider preview clipped its right edge. Also rendered current main slides **15, 16, 17, 22, 24 and 34**, and backup **65**, from their actual HTML/CSS.
- **Nine of the eleven SVG assets are not referenced by `deck.html`.** Only `views-er-media.svg` and `views-er-processing.svg` are embedded, both on backup **S65/B17**. Although its caption promises a next-click reveal, both opaque panels occupy the same absolute position; Processing covers Media in the inspected render, and the script has no schema-panel reveal handler. Most main-talk diagrams are inline HTML/SVG. S60 explicitly declines to show the portrait context-map asset; S68 names a full CI/CD figure without embedding it. Replacing these unused files alone will not repair the presentation. [Deck][deck], [navigation script][navigation], [S60][s60], [S65][s65], [S68][s68]

Reproduction of the PDF render, with all generated files outside the repository:

```sh
R1_RENDER="$(mktemp -d "${TMPDIR:-/tmp}/dc2-r1-pages.XXXXXX")"
pdftoppm -r 110 -png \
  /Users/speedpowermac/.t3/userdata/attachments/69126276-ab16-47ff-8dce-05794f4b9464-37522de2-1c8e-4574-9753-f9ab31bd7d52-pdf.pdf \
  "$R1_RENDER/old"
```

## 1. Reference PDF: page-by-page inventory

Tool attribution is **visual inference**, not established provenance: the PDF does not establish the source editor. PlantUML-like pages have its familiar compartmented classes, stereotype badges, package tabs, folded notes, sequence frames and deployment nodes. Table/typography pages look like a slide/HTML layout; PowerPoint versus HTML cannot be determined visually. None should be called an official tool export without the source.

| PDF page and title | Diagram/view type | Visible notation | Likely drawing tool; question answered |
|---|---|---|---|
| **1 - Flickpond** | Cover; no architecture diagram | Course/team eyebrow, live-site statement, five named responsibility columns | Slide/HTML layout, unknown editor. What is the project and who presents it? The live-site statement is a claim of this PDF only. |
| **2 - The models we built, in the order we built them** | Model/agenda matrix; no UML | Numbered rows, Models/Course/Min columns, course-color legend | Slide/HTML table. Which artifacts and reasoning will the talk cover, and in what order? |
| **3 - Use case model** | UML use-case diagram | Named system boundary; Visitor/Member/Operator actors; hollow-triangle actor generalization; external `«system»` actors; use-case ellipses; dashed `«include»`/`«extend»` arrows | PlantUML-like. Who can do what, what behavior is mandatory/reused, and what extends a base use case? Right-hand text explains the notation. |
| **4 - Six requirements shaped the architecture** | Architecturally significant requirements matrix | IDs N1/N3/N4/N5/P1/P2; quality classifications; evidence and status columns; `Re-test due` distinguished from `Met` | Slide/HTML table. Which requirements drive the design, and what evidence is claimed? Not a diagram or independently checked result. |
| **5 - Utility tree: our four ranked scenarios** | Quality-attribute utility tree | Root, four attribute branches, subattributes, scenario leaves, `(H, M)`/`(H, H)`/`(M, M)` ranks | Custom vector/slide tree; tool unknown. Which quality scenarios matter? The meaning/order of each rank pair is not explained on this page. |
| **6 - Architecture overview: zones, tiers, subsystems** | Logical/layered architecture with trust zones | Nested packages; `«zone»`, `«tier»`, `«subsystem»`; presentation/control/rules/data-access layers; labeled HTTPS 443, TLS, enqueue/dequeue, repository access | PlantUML-like packages/components. Where are trust boundaries and responsibilities, and which interactions cross them? This mixes logical and physical information deliberately, but is not labeled C4. |
| **7 - Analysis class diagram** | UML boundary-control-entity analysis model | `«boundary»`, `«control»`, `«entity»` and B/C/E badges; typed attributes, operation compartments, visibility; `«create»`; multiplicities; composition diamond between Job and Rendition | PlantUML-like. Which objects collaborate on a use case, who creates a Job, and what does it own? Note explicitly limits the model to key attributes/operations. |
| **8 - Sequence: Upload video** | UML analysis/object interaction sequence | `:Member`, `:UploadPage`, `:UploadsController`, `:UploadSession`, `:Job`; numbered messages 1-22; activation bars, return arrows, creation messages, `alt`, `loop`, `par`, guards, folded notes | PlantUML-like. How does an accepted/rejected multipart upload proceed, and where do the bytes go? Commentary groups steps 1-10, 11-15 and 16-22. |
| **9 - Sequence: Process video across workers** | UML design/object-level sequence | Queue lifelines; `:process_job`, `:jobs.py «repository»`, `:Job`, `:FfmpegProcessor «ProcessingStep»`; numbered calls; conditional update; `alt` winner/duplicate; `opt` chunking; success/SIGTERM/error branches | PlantUML-like. How is work claimed, encoded, optionally distributed, completed or recovered? This is a legacy RQ/chunk-worker design, not our current encoder design. |
| **10 - Statechart of a Job** | UML composite state machine/process view | Outer Job; orthogonal Lifecycle and Retention regions divided by dashed line; initial/final symbols; Done composite containing HLS substates; transition `event [guard] / effect`; `entry` action | PlantUML-like. How do processing, HLS readiness and deletion/retention evolve independently? |
| **11 - Design classes: Strategy, Adapter, Observer, Repository** | UML design class/package diagram | Package nesting; `«Protocol»` interfaces; realization triangles; `«factory»`, `«repository»`, `«subject»`, `«registry»`, `«hook»`; fields, signatures, multiplicities, aggregation, dependency arrows and pattern callout notes | PlantUML-like. Which concrete abstractions implement extension, storage adaptation, hooks and persistence ownership? Names and relationships make the pattern claims inspectable. |
| **12 - Deployment: production on AWS** | UML deployment/physical view | Cloud/region and VPC boundaries; `«subnet»`, `«device»`, `«executionEnvironment»`; 3D nodes and artifact glyphs; Docker Compose nesting; spot group 0-4; cylinders; HTTPS 443, HTTP 8000, 5432/TLS, 6379/TLS, IAM/image/queue labels; security-group note | PlantUML-like deployment syntax. What runs where and how is it connected? **Generic UML nodes, not a set of branded AWS service icons.** A single core node is shown, not a load-balanced web tier. |
| **13 - Decision: upload bytes never pass through the API** | Architecture decision record table | Issue/Decision/Assumptions/Alternatives/Justification rows | Slide/HTML table. Why choose direct storage upload, and what alternatives/constraints led there? Multipart, 2 GB and host-capacity statements belong to the legacy design. |
| **14 - Bounded contexts and context map** | Strategic DDD context map with internal concepts | Identity & Access, Media Ingest, Media Processing, Library & Playback, Operations; core/supporting/generic classifications; internal named concepts; U/D labels; OHS/PL, Published Language, ACL, Conformist, Customer/Supplier; explanatory vocabulary note | PlantUML-like package/class map. Where do terms/models differ, which context supplies which model, and how do external models enter? Do not transplant these five contexts into our two-context implementation. |
| **15 - Aggregates and domain events** | Tactical DDD aggregate/command/event model | `«service»`, `«root entity»`, `«VO»`, `«command»`, `«domain event»`; attributes; UploadSession-Part composition with 1..*; Job-EditOperation aggregation; dashed `raises` and ID-only references; transaction/repository note | PlantUML-like. What is inside each aggregate, which identities cross boundaries, and which commands/state changes matter? The note distinguishes an actual RQ message from events represented as observed state changes. |
| **16 - Secure delivery pipeline** | UML activity diagram with responsibility swimlanes | Developer/GitHub Actions CI/Track owner/Operator/AWS partitions; initial/final symbols; parallel fork/join bars; decisions and yes/no branches; fix loop; SAST, Trivy, ZAP and test actions; approval, queue-empty check and instance refresh | PlantUML-like activity syntax. Who performs each gate, what runs concurrently, what blocks progression, and how does failure return to development? Legacy tool names/gate strengths are not evidence for our CI. |
| **17 - STRIDE across Flickpond, one control each** | Threat/control matrix | Six STRIDE categories, security objective, attack, control | Slide/HTML table. What threat is addressed by each named control? Controls are PDF assertions, not verified current behavior. |
| **18 - Where our downtime would come from** | Reliability block-style comparison plus equations | Serial EC2-RDS-Valkey chain; W1-W4 parallel-worker tiles; availability equations; explicit illustrative-input footnote | Custom vector/slide cards. Which dependencies create a single point of failure, and what does worker redundancy mean? Worker tiles are not a full formal parallel wiring diagram; independence is implicit. |
| **19 - Why login took 5.8 s at 50 users** | Queueing/performance argument; no UML diagram | `U = λS`, input units, local/production p90 comparison, `R = S/(1-U)`, explicit production `not re-measured` cell | Slide/HTML math/table. What saturates, what intervention is proposed, and where was it measured? The formula's steady-state assumptions are not developed on this page. |
| **20 - Amdahl on our numbers: the ladder is 87% parallel** | Capacity/scalability calculation; no topology diagram | Clip/workload description; seconds conversion; measured speedup; Amdahl equation, inferred P, theoretical ceiling; elasticity guidelines | Slide/HTML math/cards. Which fraction appears parallelizable and where might more workers stop helping? This is an inference from that legacy workload, not our Lambda/Fargate decision rule. |
| **21 - Alibaba to AWS on 19 October: an R per part** | Migration strategy matrix | Component/before/after/strategy columns; Rehost, Replatform, Rearchitect, Retain/Retire | Slide/HTML table. What changes for each component during that migration? No new physical diagram. |
| **22 - Past capacity, Flickpond does not fall over. It queues, and people wait.** | Thesis/conclusion; no diagram | Large statement and one explanation of queue/request separation | Slide/HTML typography. What design consequence should the audience remember? Not proof that all overload modes are safe. |
| **23 - What we would change next** | Limit/consequence/remedy matrix | Known limit/why it matters/next step; single core, live retest, anemic aggregate, logs, deletion race | Slide/HTML table. What remains weak? Explicitly proposes a load balancer/two cores/Multi-AZ RDS and admits rules live in a repository despite the richer DDD drawing. |
| **24 - Thank you. Questions?** | Closing; no diagram | Product/course label, site link, team names | Slide/HTML typography. Where can the audience follow up? |

**Coverage boundary:** there is no dedicated ER/data-schema diagram, no explicitly labeled C4 diagram and no slide declaring a complete 4+1 model in PDF pp. 1-24. The views are compatible with a 4+1-style reading: scenarios p. 3, logical pp. 7/11, process pp. 8-10, physical p. 12, implementation/package structure p. 11. That mapping is an interpretation, not the PDF's terminology.

## 2. What makes the reference look formal and credible

1. **The title names an artifact and a viewpoint.** Analysis class (p. 7), design class (p. 11), process/state (p. 10), physical/deployment (p. 12), context map (p. 14) and activity/pipeline (p. 16) promise different questions. Course/model/workflow eyebrows give context. These are consistent headings, not full engineering title blocks with revision/author/source fields; add those fields for our report figures.
2. **Shapes and edges carry semantics.** Actor generalization and include/extend differ on p. 3; analysis roles and composition differ on p. 7; interface realization differs from use/dependency on p. 11; node versus artifact versus execution environment differs on p. 12. Generic rounded rectangles cannot convey those distinctions by color alone.
3. **Abstraction levels are named and connected.** The overview p. 6, analysis objects p. 7, interactions pp. 8-9, design abstractions p. 11 and placement p. 12 deepen the explanation. They do not ask one diagram to serve as a context map, detailed design and deployment view simultaneously.
4. **Behavior is falsifiable.** Steps 1-22, object names, arguments, activation bars, guards and `alt`/`loop`/`par` on p. 8; conditional claim, duplicate loser and interruption branches on p. 9; guarded transitions/effects and orthogonal regions on p. 10. An audience can ask which exact object performs a step and what happens if it fails.
5. **DDD is drawn inside the boundary.** P. 14 contains named domain concepts and a U/D relationship explanation. P. 15 distinguishes roots, value objects, commands, events, composition, multiplicity and ID references. A service name plus three invariant checkmarks does not provide this evidence.
6. **Connections are named.** P. 6 names enqueue/dequeue and trust crossings; p. 12 names ports/protocols, TLS, queue direction, image selection and storage permissions. P. 16 names owners, decisions and control flow. Labeling an arrow only `token` or leaving its meaning implicit makes the diagram less inspectable.
7. **Local legends/callouts explain unfamiliar marks.** P. 3 explains include/extend/generalization; p. 7 explains Boundary/Control/Entity; p. 14 explains U/D and integration patterns; p. 11 ties pattern notes to concrete elements. The reference does not have one universal legend: copy the practice of explaining notation, not an imagined standardized legend.
8. **Layout signals discipline.** Thin consistent strokes, white diagram panels, common type hierarchy, package labels and restrained accent colors recur across pp. 3, 6-12 and 14-16. P. 12's credibility does not depend on official AWS icons: its deployment semantics and connections do the work.
9. **Limits are visible beside the argument.** P. 4 marks retesting due; p. 18 labels availability inputs illustrative; p. 19 separates local improvement from unmeasured production; p. 23 names the anemic model and single-node limitation. These qualifiers are stronger evidence discipline than polished graphics alone.

**Do not copy its weaknesses:** p. 3 has long crossing actor lines; pp. 6/7/11/12/14/15 shrink considerable detail into half/full slide panels; p. 9 is dense; p. 10 has long wraparound transitions; p. 15 has large empty areas and long dashed references. P. 5 leaves rank-pair semantics implicit. P. 23 acknowledges that the rich aggregate drawing did not make the implementation behavior-rich. Formal notation helps scrutiny; it does not establish correctness or readability.

## 3. Feedback-to-view mapping: what is missing, weak or merely hidden

| Feedback | Reference strength, with PDF pages | Current coverage and actual gap | Required replacement/addition |
|---|---|---|---|
| More perspectives, especially deployment; physical architecture/load balancing | Logical zones/layers p. 6; typed node/artifact deployment with ports p. 12; single-core weakness admitted p. 23 | Current S22 is already a physical summary, but has floating Authorizer/SQS boxes and collapsed AZ/subnet structure. The portrait physical asset is unused. Claiming the deck has no physical view would be inaccurate. [S22][s22], [physical asset][a-physical] | A readable AWS deployment view with region/VPC/AZ/subnet boundaries, API Gateway-authorizer integration, function groups, DB topology, task placement and protocol labels. Show actual concurrency/dispatch mechanisms. Template resource inspection found no load-balancer or Auto Scaling resource; do not add an ALB icon to imply an implemented component. [template][template], [definitions][infra] |
| How are jobs split between Lambda and Fargate, and where? | P. 9 explains the legacy worker collaboration; p. 20 connects capacity to mechanism. Neither describes our two-lane design | S24 already distinguishes size filtering from executor probing, but `Size filter` has no owning function/module or explicit queues. [S24][s24] | Show `emit_state -> short_lane.work_lane` while staging work, short/standard outbox lane, consumer, `check_probe` and fenced successor-attempt fallback. Dispatch knows size, not duration. Enabled flag, positive size <=64 MiB, prior Lambda attempt, <=60 s and <=1080 height belong at their actual decisions. [dispatch][dispatch], [routing][routing], [probe][probe], [redirect][redirect] |
| Detailed DDD with entities; contexts and aggregates | Strategic map p. 14; root/entity/VO/command/event model p. 15; multiplicities p. 7 | S16 names two contexts and integration terms; S17 contains root names and checkmarks without child entities, fields, multiplicities or transaction boundaries. Unused context asset lists children as prose. [S16][s16], [S17][s17], [context asset][a-ddd] | Separate strategic and tactical diagrams. Show two implemented contexts, actual root/child records, immutable source descriptor, Attempt lease fields, SubmissionGuard, ID-only references, projections and the transaction/service function enforcing each invariant. Do not turn every Lambda into a bounded context or import the reference's five contexts. [Asset][asset], [reservation/source pin][uploads], [Job/Attempt/guard][job], [projection][projection] |
| Class and sequence diagrams at class/object level for 1-2 critical use cases | Boundary/control/entity p. 7; typed design classes p. 11; upload and processing sequences pp. 8-9 | The full sequence asset is service/infrastructure-level and unused. No UML class diagram appears in the inspected asset set; S17's invariant cards are not class design. [sequence asset][a-sequence], [S17][s17] | Use case 1: finalize upload or edit a completed asset, including source verification/copy, transaction, pin and command outbox. Use case 2: claim/encode with short-lane redirect or worker failure. Name actual SQLAlchemy/Pydantic classes and service-module functions; do not invent Controller classes absent from Python. [finalize][finalize], [edit][edit], [claim][claim], [short executor][short-executor], [redirect][redirect] |
| Data schemas/models for data stores; why relational rather than MongoDB? | **No ER/schema view in PDF pp. 1-24.** Attributes in pp. 7/11/15 help, but do not specify a storage schema | Current ER assets already show table names and crow's-foot relations, but no columns/types/PK/FK/UK/checks. Both are backup S65 only. [S65][s65], [Media ER][a-er-media], [Processing ER][a-er-processing] | One schema view per owned database plus Source/Output/Envelope JSON shapes and S3 identity/key rules. Show actual composite keys, unique attempt numbering, deferred current-attempt FK, reservation pin CHECK and monotonic projection fields. Explain the joins/transactions/constraints these protect; JSONB fields do not by themselves establish that SQL is unnecessary. [Media][asset], [uploads][uploads], [Processing][job], [messages][messages], [source contract][source], [output contract][output] |
| Authorizer tied to API Gateway | P. 12 makes placement and connections explicit, but contains no counterpart to our Lambda authorizer | S15 has Client -> Gateway -> Media authorizer; S22 leaves Authorizer unconnected. Source configures a REQUEST authorizer with Cookie identity, zero cache TTL and protected-route AuthorizerId. [S15][s15], [S22][s22], [Gateway config][authorizer-config], [routes][routes] | Draw Gateway invoking the authorizer, authorizer reading `User`, returning trusted Actor context, and Gateway invoking the selected integration. Keep public login/health routes distinct. All generated Lambda functions have private-subnet VpcConfig, including MediaAuthorizer; its edge association is not its subnet placement. [authorizer code][authorizer], [function placement][function-placement] |
| Edited video does not go directly to SQS | P. 8 exposes individual object calls and completion steps; p. 15 names command handling | Old domain asset says SubmitJob/source URL; S16 also wrongly puts `work` on the cross-context command arrow. [domain asset][a-domain], [S16][s16] | Show owner/completed-parent check -> copy completed primary output into a new source -> new Asset/source pin/RequestKey plus `stage_submit` -> commit -> MediaRepair publishes command. `MediaApi` has no queue URL; Media's stage function writes its SQL outbox. [edit][edit], [Media messaging][media-messaging], [queue environment][queue-env] |
| SAST and DAST absent from pipeline explanation | P. 16 explicitly places named scans in parallel branches, owners and decisions | The unused pipeline asset only says `Security scans`; **main S34 already names SonarCloud SAST and exact-candidate DAST**. The feedback is not evidence that no such jobs exist. [pipeline asset][a-pipeline], [S34][s34] | A small activity/swimlane view showing required execution versus advisory findings, source/artifact identities, candidate checks, Main/CD gate and smoke/restore. Our DAST starts local PostgreSQL/Moto and runs authenticated ZAP; findings are report-only. Sonar analysis is conditional/advisory, including full mode. Do not copy p. 16's Sonar/ZAP blocking claims. [DAST][dast], [CI execution gate][ci-gate], [Sonar][sonar], [full Sonar][sonar-full], [CD gate][cd-gate] |

## 4. Current SVG weaknesses: one entry per file

Dimensions are the SVG `viewBox` width x height, rounded to whole pixels. Usage was checked against `deck.html`. These are diagram/readability findings, not a claim that all source documentation is absent.

### `architecture-before-after.svg` - 1000 x 500; unused

- The right half is explicitly **proposed**, with Media -> Processing `token`, Redis/RQ and persistent worker/recovery boxes. It is stale as an as-built architecture: V1 packaging excludes peer-HTTP/RQ and the actual native-message lanes are commands/work/results. Keep it only as a dated proposal comparison or redraw the implemented delta. [asset][a-before], [retired runtime][legacy], [lanes][lanes]
- Tiny labels and unlabeled arrows mix call, data ownership, persistence and execution. `processing_db` breaks awkwardly across lines; dashed service boxes have no notation legend. It demonstrates separation, not the asynchronous handoff or deployment.
- Take the layered-responsibility discipline of **PDF p. 6** and the typed implementation/deployment distinction of **pp. 11-12**; do not reproduce the reference's old AWS/RQ runtime.

### `ddd-context-map.svg` - 717 x 1721; unused

- A portrait wiring map consumes over twice its width in height. At a 500 px slide-body height its scale is about 0.29; normal labels become a few pixels high. Long orthogonal edges, grey label blocks, bright unrelated group colors and prose-filled boxes defeat scanning. Current S60 explicitly acknowledges that it is unreadable and substitutes a message table. [asset][a-ddd], [S60][s60]
- Context map, aggregate inventory, queue topology, execution role and schema names occupy one view. Entities are comma-separated text inside a box, not a tactical model with identity, attributes, relationships or invariants. It also shows only the finite standard encoder; an as-built two-lane view needs the short lane or an explicit baseline label. [routing][routing], [lanes][lanes]
- Split strategic relationships from aggregate detail, as **PDF pp. 14-15** do. Use a small context map with explicit U/D/model relationship semantics, then one readable root/child model per context.

### `deployment-pipeline.svg` - 1000 x 340; unused

- Five generic rounded cards conceal every significant gate/branch. `Security scans / code and images` cannot answer the named-SAST/DAST question. The runtime panel below is not a deployment model: it gives no function/node/subnet placement and depicts a service `token` call plus workers `1 -> 3`. Actual packaging rejects that legacy peer boundary; the lane design has different executor caps. [asset][a-pipeline], [legacy][legacy], [routing][routing]
- The `Processing internal API` label is misleading for current V1: API Gateway creates protected Processing routes as well as Media routes. `PostgreSQL` collapses database ownership, while object storage floats without data-path edges. [routes][routes]
- Replace it with separate activity and deployment views, following the responsibility/decision structure of **PDF p. 16** and node placement of **p. 12**. Preserve our conditional/advisory scanner semantics rather than that page's legacy gating story. [DAST][dast], [Sonar][sonar]

### `domain-model.svg` - 1000 x 430; unused

- **Not a detailed domain/class model.** Owner/Asset/ProcessingJob/Output are summary cards; there are no typed identifiers, multiplicities, child Attempt model, lease fields, command-envelope identity or transaction boundaries. `uploaded -> submitted` is not the persisted Asset submission-state vocabulary (`pending/submitted/error`). [asset][a-domain], [Asset schema][asset], [Job/Attempt][job]
- `SubmitJob / source URL` contradicts the current immutable Source contract (`bucket/key/version_id/sha256/size_bytes/content_type`); message validation forbids URLs. Result snapshots carry output descriptors; public signed URLs are a delivery concern. [Source][source], [URL rejection][no-url], [Output][output]
- The four-state lifecycle omits cancellation/deletion and short-lane successor attempts. The fixed `360p / 480p / 720p` output list overstates the ladder: rungs taller than the source are omitted, and a source below 360 uses its own height. [projection][projection], [redirect][redirect], [ladder][ladder]
- Retain any source-supported invariants, but draw roots/children/value objects and typed links with enforcement notes, as **PDF pp. 7/15** do; borrow interface/operation specificity from **p. 11**. Do not pretend the ORM classes themselves implement all service-layer rules.

### `platform-context.svg` - 1000 x 420; unused

- Understandable product overview, weak formal context diagram: it mixes actors, applications, internal services, storage and operations, with mostly unlabeled arrows. `Viewers` implies a separate consuming role without an ownership qualifier. Current authorizer never issues the reserved viewer role; V1 has no sharing/read-only account. [asset][a-platform], [role implementation][authorizer]
- `Clients use only the published API` is misleading unless scoped to control operations: clients send bytes by presigned POST directly to S3 and fetch presigned media. A thick system box hides this material data path. [finalization/intake][finalize], [current producer slide][s20]
- Keep one context zoom level with labeled actor goals, and separate control-plane/API from signed storage data transfer. **PDF p. 3** names actor privileges/system boundaries; **p. 8** shows direct bytes transfer. Its legacy generalized actors are a notation example, not roles to add here.

### `views-er-media.svg` - 1220 x 521; embedded on S65/B17

- **An entity-name relationship sketch, not a database schema.** No columns, types, PK/FK/UK, nullability, indexes or CHECKs are rendered. Unexplained per-table colors add no schema meaning. Message tables/staged ledger are isolated without explaining their keys. [asset][a-er-media], [S65][s65]
- `assets ||--o| upload_reservations` implies every reservation belongs to exactly one existing Asset. Reservations exist before adoption, and `UploadReservation.asset_id` is a unique UUID **without a database FK**. Draw an optional logical association and label it as such, not a physical identifying FK. [reservation schema][uploads]
- Its embedding also hides the Media diagram under the opaque Processing panel; the promised reveal is not implemented. Give each schema its own slide or implement an explicit view switch. [S65][s65], [navigation][navigation]
- Add owner/idempotency composite keys, version pin/check, source lineage UUID, projection attempt/state version and storage descriptor shapes; separate declared constraints from application invariants. [Asset/RequestKey][asset], [uploads/source pin][uploads], [projection][projection]
- **PDF pp. 7/15** illustrate readable fields and identity semantics; **the PDF supplies no ER-schema exemplar**. This is a place to exceed the reference, not imitate it.

### `views-er-processing.svg` - 1228 x 481; embedded on S65/B17

- Again, no attributes or physical constraints. It misses the most explanatory relationship: `jobs.current_attempt_id -> attempts.id`, the deferred FK that coexists with `attempts.job_id -> jobs.id`. `retry_requests.attempt_id` and `cleanup_intents.job_id` are also omitted. [asset][a-er-processing], [Job/Attempt/retry/cleanup schema][job]
- A guard can exist before a Job (`job_id` nullable), but the drawn `jobs ||--o| submission_guards` presents every guard as attached to a Job. Conversely its at-most-one guard per Job is not a unique constraint on `job_id`; the schema keys guards by `asset_id`. Distinguish stored FK cardinality from application-level one-job-per-asset behavior. [guard schema][job]
- Explain launcher tables as optional launcher state rather than unexplained peers of jobs. Show the unique attempt number, task binding and state-version counter. [launcher schema][launcher-models], [message/task schema][messages]
- Use the field/relationship precision of **PDF pp. 7/11/15**, while adding the database-level detail absent from that reference.

### `views-job-states.svg` - 644 x 665; unused

- Reasonable high-level lifecycle, but `cancelled` is not a legal stored `jobs.status`: Job allows four values; Attempt has six states; the outgoing result exposes `cancelled` when `Job.deleted_at` is set. Label the model as the externally projected job lifecycle, or draw Job/Attempt/deletion separately. [asset][a-states], [Job/Attempt schema][job], [snapshot][snapshot]
- Missing `failed -> cancelled`; cancellation tombstones a Job regardless of its four-state status. Missing `processing -> queued` for a short-lane redirect, which abandons the old Attempt and creates a successor. `finish with error, lease/deadline expired, task STOPPED` collapses worker finish and recovery triggers into one unowned action. [cancel implementation][cancel], [redirect][redirect]
- Add transition owner/event, guard and effect; differentiate retry from fallback and independent retention/deletion. **PDF p. 10** is the useful reference for composite/orthogonal state and `event [guard] / effect`, not for importing its HLS substate model.

### `views-logical.svg` - 713 x 2133; unused

- Nearly 3:1 portrait layout; around 0.23 scale at 500 px height. The rendered order is Client, Edge, Execution, Application, Data: the arrows force execution above application despite the conceptual tier ordering. Long crossing edges and unrelated pastel groups obscure ownership. [asset][a-logical]
- One diagram mixes deployment executables (Lambda/Fargate), source packages, domain layers, shared libraries and physical stores. An Aurora cylinder merges two logical databases and does not identify shared versus separate-cluster configuration. Only standard Fargate execution is visible. Source supports both DB topologies and optional short execution, so the figure needs an explicit configuration label. [DB topology generator][db-topology], [function placement][function-placement], [routing][routing]
- Use a small container/logical view and a separate per-service component/package view; make dependency edges distinct from runtime messages. **PDF p. 6** separates zones/tiers/subsystems, **p. 11** expands implementation structure and **p. 12** places executables.

### `views-physical.svg` - 1411 x 2879; unused

- A tall flowchart, not a slide-sized AWS deployment view: about 0.17 scale at 500 px height. Many routes travel the full page, while ECR/SSM/event/queue relations compete with request/data transfer. Colors distinguish groups arbitrarily; AZs A and B are collapsed rather than drawn. [asset][a-physical]
- **Authorizer placement is wrong for this source snapshot:** MediaAuthorizer appears in the public-edge group and is excluded from the private Media function list, but the generator assigns private-subnet VpcConfig to every function. API Gateway's authorizer association must be drawn separately from the Lambda's physical placement. [function placement][function-placement], [authorizer integration][authorizer-config]
- It combines two DB clusters with baseline counts of three queues/three DLQs and no short encoder/launcher. Those settings can be configured independently, so this is not intrinsically an impossible topology; it is an **unidentified configuration**, unsuitable as an unqualified current deployment claim. The source has shared/separate DB modes and conditional extra executors/queues. [DB modes][db-topology], [lanes][lanes], [routing][routing]
- There is no explicit load balancer to explain. State how Gateway integrations and queue/executor admission distribute work, and state HA limitations rather than inventing an ALB. **PDF p. 12** gives the node/artifact/protocol example; **p. 23** shows how to admit the single-node/HA limitation. [template][template], [routes][routes]

### `views-sequence.svg` - 4664 x 2394; unused

- **41 messages across 15 lifelines**, from reserve through HLS segment download, cannot function as one slide. It is a useful report overview; at 1180 px width ordinary text shrinks to roughly one quarter of its source size. Numbering and phase bands are strengths worth retaining. [asset][a-sequence]
- Lifelines are browser/Gateway/Lambdas/SQL stores/S3/SQS/operator, not the service-module objects requested by the assessor. Happy-path-only presentation lacks `alt` branches for expired reservation, duplicate command, stale lease, failed encode and fallback. Split upload/adoption, execution/redirect and playback; use the first two for detailed design. **PDF pp. 8-9** demonstrate object calls and guarded branches.
- Operator RunTask, one standard work queue and Fargate encoding describe a baseline flow; do not present it as the complete optional two-lane runtime. The short executor probes after claim and may create a successor Attempt on the standard lane. [short executor][short-executor], [redirect][redirect]
- The arrow from **Output bucket** to the repair/event Lambda bundles `Object Created, or repair tick, or ECS STOPPED` onto one message, attributing three trigger types to one lifeline. Separate the S3 event, EventBridge timer and ECS stop event. Playback requests to Gateway also omit repeated Gateway-to-Media dispatch, so later responses appear from an uninvoked API. Model these as an explicit repeated `ref`/interaction rather than unexplained gaps. [sequence source][sequence-source]

### Material issues in the actual inline main slides

These matter because nine asset edits would otherwise leave them untouched:

- **S16:** cross-context outgoing label is `submit · retry · cancel · work`. **`work` is Processing -> Processing**, not Media -> Processing; the same deck's backup S60 gets this right. Move it inside the Processing boundary. [S16][s16], [S60][s60], [producer/consumer definitions][lanes]
- **S17:** two invariant cards are not an entity/aggregate diagram. `one job per asset` is enforced by Processing's unique `Job.asset_id`/guard, not by a rich Asset method; the caption must distinguish invariant from enforcement location. [S17][s17], [Job schema][job], [dispatch][dispatch]
- **S22:** Authorizer and SQS are unconnected inventory boxes; the diagram does not show the authorization return/context handoff or which functions consume/publish which queue. MediaAuthorizer's placement is unclear despite source VpcConfig. [S22][s22], [authorizer][authorizer], [queue environment][queue-env], [function placement][function-placement]
- **S24:** the two-stage concept is already present and broadly source-consistent. Improve it by naming `emit_state/work_lane`, showing both queues, flag/prior-attempt conditions and the **new Attempt** created by redirect. Do not claim all three bounds are known before Lambda executes. [S24][s24], [routing][routing], [dispatch][dispatch], [redirect][redirect]
- **S34:** SAST/DAST names already appear, but rows of badges do not show gate flow, conditional execution, findings disposition or the local scan environment. A pipeline swimlane should expose these distinctions, following **PDF p. 16** with our actual semantics. [S34][s34], [DAST][dast], [CI gate][ci-gate], [Sonar][sonar]

## 5. Recommended local diagram toolchain and verified render

### Primary choice: PlantUML sources, bundled C4/AWS libraries, SVG output

Use PlantUML for UML class/sequence/state/activity/deployment and tactical DDD models. Use its bundled C4 library only for context/container/component views; use AWS icons for the deployment view. C4 explicitly separates structural zoom levels and supporting dynamic/deployment views; it does not replace object-level UML or physical schemas. [C4 diagram types](https://c4model.com/diagrams), [PlantUML class notation](https://plantuml.com/class-diagram)

**Why this choice:** the reference's most useful visual vocabulary is PlantUML-like (PDF pp. 7-12, 14-16). It gives typed symbols, compartments, multiplicities, guards, autonumbered interactions and activity partitions without hand-positioning every rectangle. Bundled AWS sprites/C4 includes avoid remote `!includeurl` dependencies; icon version is tied to the chosen JAR, not necessarily the newest AWS icon pack. [PlantUML standard library](https://plantuml.com/stdlib), [AWS official icon source](https://aws.amazon.com/architecture/icons/)

**Verified on this machine:** Java 25.0.4 was already installed; neither `plantuml` nor `dot` was on PATH. Downloaded **PlantUML 1.2026.9** using authenticated `gh`; rendered all three examples below with Smetana, without installing Graphviz. Smetana is PlantUML's embedded Java layout engine. `-version` printed a missing-dot diagnostic, but the actual `-tsvg` render command exited **0**. [Smetana documentation](https://plantuml.com/smetana02), [command-line documentation](https://plantuml.com/command-line)

Exact minimal setup/render, writing outside the repository:

```sh
R1_TOOLS="$(mktemp -d "${TMPDIR:-/tmp}/dc2-diagrams.XXXXXX")"
gh release download v1.2026.9 --repo plantuml/plantuml \
  --pattern plantuml-1.2026.9.jar --dir "$R1_TOOLS"

cat > "$R1_TOOLS/tiny.puml" <<'PUML'
@startuml
!pragma layout smetana
hide empty members
class Asset <<aggregate root>> {
  +id: UUID
}
class Job <<aggregate root>> {
  +asset_id: UUID
}
Asset ..> Job : submit command (by ID)
@enduml
PUML

java -Djava.awt.headless=true -jar "$R1_TOOLS/plantuml-1.2026.9.jar" \
  -tsvg "$R1_TOOLS/tiny.puml"
```

The example is a **synthetic syntax smoke test**, not a complete system/DDD claim. Tested JAR SHA-256: `aa4a1d06f8911c4b842beff4828dd955be431692b631a312d04c0e9fab9581de`. Result: `tiny.svg`, **3875 bytes, 234 x 213**, parsed as XML/SVG with no PlantUML error page; rendered to PNG and visually inspected.

The following two additional smoke tests also actually rendered with that JAR; no separate icon/C4 installation is required:

```sh
cat > "$R1_TOOLS/tiny-aws.puml" <<'PUML'
@startuml
!pragma layout smetana
!include <awslib/AWSCommon>
!include <awslib/Compute/Lambda>
!include <awslib/ApplicationIntegration/SimpleQueueService>
left to right direction
Lambda(fn, "Consumer", "Lambda")
SimpleQueueService(q, "Commands", "SQS")
q --> fn : event source mapping
@enduml
PUML

cat > "$R1_TOOLS/tiny-c4.puml" <<'PUML'
@startuml
!pragma layout smetana
!include <C4/C4_Container>
LAYOUT_LEFT_RIGHT()
Person(owner, "Owner")
System_Boundary(platform, "Synthetic example") {
 Container(api, "Media API", "Python", "Accept requests")
}
Rel(owner, api, "Reserve upload", "HTTPS/JSON")
SHOW_LEGEND()
@enduml
PUML

java -Djava.awt.headless=true -jar "$R1_TOOLS/plantuml-1.2026.9.jar" \
  -tsvg "$R1_TOOLS/tiny-aws.puml" "$R1_TOOLS/tiny-c4.puml"

# Optional PNG inspection of a plain PlantUML SVG:
npx -y @resvg/resvg-js-cli@2.6.2-beta.1 --background white --fit-width 900 \
  "$R1_TOOLS/tiny-aws.svg" "$R1_TOOLS/tiny-aws.png"
```

Verified outputs: AWS **8704 bytes, 447 x 159**, with SQS/Lambda sprites and a labeled arrow; C4 **7931 bytes, 386 x 293**, with a person/container/system boundary and legend. Both parsed as SVG and were visually inspected as PNGs. These establish local rendering capability only, not correctness of future architecture figures.

### Optional installed path and alternatives

If native Graphviz layout is preferred for larger package/node diagrams, the exact macOS installed path is:

```sh
brew install plantuml graphviz
plantuml -version
dot -V
plantuml -tsvg /absolute/path/to/diagram.puml
```

This Homebrew installation was **not run** in this research. The formula declares Graphviz as a dependency; explicit naming makes the required tools clear. For the downloaded JAR after Graphviz installation, use `java -jar "$R1_TOOLS/plantuml-1.2026.9.jar" -tsvg /absolute/path/to/diagram.puml`; remove the Smetana pragma if choosing default Graphviz layout. [PlantUML formula](https://formulae.brew.sh/formula/plantuml), [Graphviz formula](https://formulae.brew.sh/formula/graphviz)

- **Mermaid:** retain for concise state/ER models where it is already useful; add typed attribute blocks and PK/FK/UK labels rather than just table names. It already supports them. Generic flowchart syntax is not a substitute for choosing the correct viewpoint. Optional CLI installation/render: `npm install -g @mermaid-js/mermaid-cli`, then `mmdc -i /absolute/path/to/schema.mmd -o /absolute/path/to/schema.svg`. These installation/render commands were documentation-checked, not executed here. [ER syntax](https://mermaid.js.org/syntax/entityRelationshipDiagram.html), [official CLI README](https://github.com/mermaid-js/mermaid-cli#usage)
- **draw.io Desktop:** reasonable fallback for manually routing an AWS deployment diagram when auto-layout remains unreadable. Keep the editable `.drawio` source and export SVG, retaining embedded diagram data when appropriate. No draw.io installation or export was tested here. Prefer the verified PlantUML path for this repair rather than introducing a second mandatory authoring system. [SVG export](https://www.drawio.com/docs/manual/export/export-to-svg/)

### Authoring rules for the replacement figures

- One viewpoint and one question per figure. Title strip: **view name | use case/configuration | source SHA | as-built/proposed | notation legend**. Keep the semantic headers demonstrated in PDF pp. 6-12/14-16; add configuration/provenance that the reference lacks.
- Same service color across views; symbol/edge semantics explained independently of color. Label dependency, synchronous call, asynchronous message, SQL transaction, and object transfer differently. PDF pp. 7-12/14-16 supply the useful distinctions.
- For Python detail, represent actual modules as `«module»`/service components with real functions, alongside actual model classes. Do not fabricate OO controllers to resemble PDF p. 11.
- For the talk, aim for a wide figure with readable labels at the actual 1280 x 720 slide size. Split a tall model instead of shrinking it. The density problems in PDF pp. 6/9/11/12 and our portrait assets show why a correct export is insufficient.
- Keep full schema/interaction versions in the report; place a readable selected view in the main talk and link/cross-reference the full figure. Source identifiers belong beside the figure, not only in hidden presenter notes.

## 6. Recommended slide-level architecture structure

Recommended **architecture segment**, not a copied 24-page course agenda. Ten slides can replace/merge several existing architecture summaries; this is not a request to append ten more slides. Runtime/implementation names below are specified by the linked `76282d3` sources in sections 3-4. Full ERs, full sequences, HA/capacity evidence and detailed pipeline remain report/backup material with explicit main-talk pointers.

| Slide | Question and figure | Minimum content; reference strength borrowed |
|---|---|---|
| **A1 - Scope and architecture drivers** | What are the boundaries and the 2-3 decisions the audience must understand? Small context/container overview plus driver-to-decision rows | Owner/browser/CLI, platform boundary and external storage access; independent ownership, durable async handoff, bounded execution. Borrow requirements-to-design traceability from **PDF pp. 3-5**, not its course agenda or old actor roles. |
| **A2 - Strategic DDD context map** | Why exactly these two contexts? | Media and Processing ownership, translation points, commands one direction/results the other, `work` inside Processing, small shared contract/kernel. Explain relationship labels. Borrow **PDF p. 14**; preserve our implemented two-context boundary. [lanes][lanes], [Media command staging][media-messaging] |
| **A3 - Tactical DDD aggregates** | What is an aggregate here, and where are its invariants enforced? | Root/child/value-object notation; Asset/source pin/reservation and Job/Attempt/guard; selected attributes, multiplicities, ID references and commit boundaries. One invariant callout per aggregate naming its service function or constraint. Borrow **PDF pp. 7/15**. [Asset][asset], [uploads][uploads], [Job][job], [edit][edit] |
| **A4 - Detailed design: source adoption/edit** | What concrete objects/functions turn an owned source into durable work? | Small companion class/module model and numbered sequence: API -> service -> storage verifier/copy -> SQL models/outbox -> later publisher. Include owner/invalid-parent or expiry `alt`, pin and transaction boundary. This directly answers the edited-video/SQS objection. Borrow **PDF pp. 7-8/11**. [finalize][finalize], [edit][edit], [queue separation][queue-env] |
| **A5 - Detailed design: dispatch and claim** | Who chooses an executor and what facts can it know? | `emit_state/work_lane` owns routing while staging work; standard/short queues; enabled/size/prior-Lambda guards; short executor claims, downloads, probes. Name actual functions and annotate <=64 MiB, <=60 s, <=1080 height at the relevant stage. Borrow message/guard specificity from **PDF p. 9**, not its chunk-worker algorithm. [dispatch][dispatch], [routing][routing], [probe][probe] |
| **A6 - Execution failure and redirect** | What prevents stale completion and repeated Lambda fallback? | Object-level `alt` sequence plus compact Job/Attempt state inset: live lease check, abandoned Attempt, successor Attempt, standard work. Separate deletion from Job.status. Borrow failure branches/composite-state precision from **PDF pp. 9-10**. [claim][claim], [redirect][redirect], [cancel][cancel] |
| **A7 - Physical deployment** | What runs where, what invokes what, and how does work distribute? | AWS/UML deployment view: region/VPC/two AZs, public/private subnets, Gateway request authorizer association and private Lambda placement, function groups, actual DB configuration, SQS/S3, Fargate tasks. Differentiate managed request routing, queue consumption and finite-task launch; no fictional ALB. Borrow **PDF p. 12**, with explicit limitations like **p. 23**. [placement][function-placement], [routes][routes], [DB configuration][db-topology], [template][template] |
| **A8 - Data model and storage contracts** | Why are these data stores modeled this way? | Selected columns/PK/FK/UK/CHECKs in two owned schema panels, including current-attempt FK, request identity and pin constraint; adjacent Source/Output JSON shapes and S3 version/attempt identity. Give the concrete relational-integrity/transaction rationale; link full schemas. Borrow typed fields from **PDF pp. 7/15**, while adding its missing schema view. [models][job], [reservation CHECK][uploads], [contracts][source], [outputs][output] |
| **A9 - Secure delivery as control flow** | Which checks execute, what blocks, and which findings are advisory? | Developer/CI/release/AWS swimlanes; source -> scan/test/build artifacts -> candidate gate -> Main/CD -> smoke/restore; explicit Sonar advisory, local authenticated ZAP findings report-only, mandatory execution, image/commit identity. Borrow **PDF p. 16**; show our actual policy, not its legacy one. [CI][ci-gate], [DAST][dast], [Sonar][sonar], [CD][cd-gate] |
| **A10 - Decisions, trade-offs and limitations** | What did this design buy and what does it still not guarantee? | Driver -> mechanism -> evidence -> remaining limit table; compare only source/receipt-supported claims. Explain any HA/load-balancing gap directly. Keep measured/local/configured/proposed distinct. Borrow ADR form **p. 13**, qualified capacity/reliability evidence **pp. 18-20**, and explicit shortcomings **p. 23**. Do not reuse their measurements. |

Main-talk legibility takes priority over displaying a complete model. The report must carry the full class/function collaboration, both database schemas and configuration-specific deployment; slide A4/A6 cannot be replaced by another infrastructure-only end-to-end sequence. The reference's reusable strength is its separation of questions, semantic notation and visible evidence limits (PDF pp. 6-16/18-23).

## Source links for current-system checks

All repository links are pinned to the required Main commit. GitHub reads/downloads for tool research used authenticated `gh`; no repository/cloud state was changed.

[deck]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L109-L261
[navigation]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L284-L317
[s15]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L155-L158
[s16]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L159-L160
[s17]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L161-L162
[s20]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L166-L169
[s22]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L171-L172
[s24]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L173-L174
[s34]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L189-L193
[s60]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L252
[s65]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L257
[s68]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L260
[a-before]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/architecture-before-after.svg#L58-L120
[a-ddd]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/ddd-context-map.svg#L1
[a-pipeline]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/deployment-pipeline.svg#L16-L67
[a-domain]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/domain-model.svg#L20-L90
[a-platform]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/platform-context.svg#L20-L67
[a-er-media]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-er-media.svg#L1
[a-er-processing]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-er-processing.svg#L1
[a-states]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-job-states.svg#L1
[a-logical]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-logical.svg#L1
[a-physical]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-physical.svg#L1
[a-sequence]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/assets/img/views-sequence.svg#L1
[legacy]: https://github.com/Collaboration95/dc2/blob/76282d3/deploy/v1/check_runtime.py#L46-L88
[lanes]: https://github.com/Collaboration95/dc2/blob/76282d3/delivery/sqs.py#L12-L32
[asset]: https://github.com/Collaboration95/dc2/blob/76282d3/media/models.py#L26-L103
[uploads]: https://github.com/Collaboration95/dc2/blob/76282d3/media/upload_models.py#L25-L74
[projection]: https://github.com/Collaboration95/dc2/blob/76282d3/media/projection_models.py#L12-L29
[job]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/models.py#L15-L107
[messages]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging_models.py#L13-L47
[launcher-models]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_models.py#L18-L60
[source]: https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L99-L129
[no-url]: https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L132-L154
[output]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/schemas.py#L90-L95
[ladder]: https://github.com/Collaboration95/dc2/blob/76282d3/media_engine/hls.py#L5-L30
[finalize]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L99-L203
[edit]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L105-L179
[media-messaging]: https://github.com/Collaboration95/dc2/blob/76282d3/media/messaging.py#L9-L51
[dispatch]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L102-L128
[routing]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_lane.py#L1-L130
[probe]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_lane.py#L87-L100
[redirect]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L412-L443
[short-executor]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_encoder.py#L54-L100
[claim]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L136-L168
[snapshot]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L60-L95
[cancel]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L186-L229
[authorizer]: https://github.com/Collaboration95/dc2/blob/76282d3/media/authorizer.py#L13-L57
[infra]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L208-L221
[template]: https://github.com/Collaboration95/dc2/blob/76282d3/deploy/aws/v1/template.json#L1
[db-topology]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L208-L221
[queue-env]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1107-L1125
[function-placement]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1196-L1240
[authorizer-config]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1529-L1558
[routes]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1602-L1621
[sequence-source]: https://github.com/Collaboration95/dc2/blob/76282d3/docs/architecture/views.md#L435-L459
[dast]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/dast.yml#L68-L101
[ci-gate]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L599-L636
[sonar]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L794-L817
[sonar-full]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L848-L880
[cd-gate]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/cd.yml#L130-L148
