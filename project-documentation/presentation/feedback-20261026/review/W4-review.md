# W4 independent review — 26 October 2026

**PASS after fixes.** Reviewed the W4 fragments against Main `76282d3b5a141f6548056f2506f9d5aff0742692`, with migrations as the schema authority. All 22 application tables were checked, exceeding the requested eight-table backup sample. Final coverage is **172 columns, 61 PK/FK/UK/CHECK constraints and 12 explicit indexes**, plus implicit PK/UK index coverage. W4 remains **four main slides and 22 backup slides**.

Read FEEDBACK.md and WORKPLAN.md first. Work was confined to W4 documentation, figures and review evidence in the dc2-rescue worktree. No application, migration, infrastructure, workflow, other workstream or `site/deck.html` source was edited. No commit was made.

## Findings and fixes

### W4-R1 — P2 — Physical sequence default omitted; ORM parity overstated

**Location:** `report-notes/W4-dictionary.md`, `processing_db.public.launcher_control`; the embedded dictionary and Reconstruction / ORM cross-check in `report-notes/W4.md`; `site/assets/uml/W4-processing-launcher.puml/.svg`; launcher speaker notes.

The dictionary originally gave `launcher_control.id` an absent server default and claimed all ORM server defaults matched migration-head DDL. Offline compilation of the real Alembic upgrade emits `id SERIAL NOT NULL`. PostgreSQL implements SERIAL as INTEGER plus a sequence-backed default. The ORM instead supplies a Python default of 1, which suppresses SERIAL when compiling model-created tables. Inspecting only `Column.server_default` concealed this difference.

**Evidence:** [migration column and singleton CHECK](https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0007_launch_reservations.py#L18-L28), [ORM Python default](https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_models.py#L18-L28), [PostgreSQL 16 SERIAL semantics](https://www.postgresql.org/docs/16/datatype-numeric.html#DATATYPE-SERIAL), and the independently emitted [Processing DDL](W4-qa/processing-head.sql). This is compiled-schema evidence, not a live catalog observation.

**Fix applied:** documented `nextval('launcher_control_id_seq'::regclass)` in both dictionary copies; retained INTEGER as the storage type; annotated SERIAL and the ORM default on the launcher figure and notes. Updated `W4-generate.py` to detect implicit physical defaults, report the ORM difference and synchronize the embedded dictionary. Corrected the blanket parity claim and made clear that migrations remain the authority. The existing two migration-only recovery indexes remain documented in the CODE backlog; no model change was made.

### W4-R2 — P2 — Evidence links pointed at unrelated code

**Location:** source links throughout `slides/W4.html` and `report-notes/W4.md`, especially the envelope, JSON descriptors, operations, store configuration and ADR evidence; matching manual citations in `W4-author.py`.

Examples: `processing/schemas.py#L111` pointed to `RetryJob`, not Output; `contracts/v1.py#L151` pointed inside payload traversal, not Envelope; `processing/messaging.py#L35` was a repair-scheduling constant, not operation validation. Other targets were blank lines, a different configuration constant, or the line preceding the named CHECK/index. Existing URLs resolved, but resolution alone did not establish that they supported their labels.

**Evidence:** [actual Output declaration](https://github.com/Collaboration95/dc2/blob/76282d3/processing/schemas.py#L90-L95), [actual Envelope declaration and validation](https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L158-L218), [actual operation-set validation](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L260-L271), [configurable database topology](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L63-L78), [cleanup partial index](https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0006_cleanup_retirement.py#L23-L29).

**Fix applied:** repointed 22 previously cited manual targets to the relevant declarations or implementation ranges, including Source versus the legacy DTO, payload filtering, cancellation acknowledgement, jobs.status CHECK, recovery and owner/projection reads. Updated the authoring source so regeneration preserves the repairs. The [correction inventory](W4-qa/anchor-corrections.json) and [final permalink checks](W4-qa/permalinks-final.json) record the ranges. All deliverable GitHub links remain pinned to `76282d3`; every path and line range was checked against that commit, followed by semantic inspection. GitHub repository access used authenticated `gh repo view` only; source verification used local `git show` at the pinned commit.

### W4-R3 — P3 — No direct main-talk entry to the ADR

**Location:** `slides/W4.html`, `w4-stores` and `w4-adr` footers; matching slide generation in `W4-author.py`.

The ADR was present at the end of the 22-slide appendix, reachable through sequential/overview navigation, but had no direct entry from the main data narrative. Adding an ordinary section-ID hash alone would not work with the existing deck router, which accepts numeric slide hashes.

**Evidence:** [numeric hash routing](https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L300-L303), [slide activation and numeric history](https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L284-L292). The W4 fragments are uncommitted integration inputs; their local locations above are not fabricated `76282d3` permalinks.

**Fix applied:** added a visible “Why PostgreSQL? · backup” link to stores and “Return to stores” to the ADR. Each resolves the stable W4 section ID to its current numeric position at click time, so coordinator renumbering is supported without editing the deck script. Clicked both links in the standalone W4 preview: `#1 / w4-stores → #26 / w4-adr → #1 / w4-stores`. The ADR remains backup.

## Schema and ER verification

The independent [verifier](W4-qa/verify.py) does not import the author's reconstruction/generator. It executes the ordered migration `upgrade()` functions through Alembic's **offline PostgreSQL SQL compiler**, parses the emitted DDL, and compares it with both dictionary copies and every W4 PlantUML entity. It separately compiles ORM metadata. It performs no database connection or migration execution.

| Database / head | Tables | Columns | Constraints | Explicit indexes |
|---|---:|---:|---:|---:|
| Media / `media_0008` | 11 | 94 | 31 | 7 |
| Processing / `processing_0007` | 11 | 78 | 30 | 5 |

**Main ERs exhaustively checked:** all displayed fields, types, nullability, PK/FK/UK markers, composite UK membership and every relationship endpoint in `W4-media-main` and `W4-processing-main`; the complete schemas of their nine tables were also checked through the dictionary/full figures. Main figures explicitly label their selected-column scope.

**Backup minimum exceeded:** all 22 tables and every column in their full figures were checked, including these eight exhaustive samples: Media `users`, `assets`, `upload_reservations`, `processing_projections`, `message_outbox`; Processing `attempts`, `cleanup_intents`, `launch_reservations`. Checks include types/lengths, nullability, complete PK/FK/UK/CHECK definitions and names, FK delete/update actions and deferred behavior, defaults, explicit index column order and partial predicates. CHECKs/defaults/indexes are intentionally in the dictionary, as each figure legend states.

**Notation PASS:** crow's-foot endpoints agree with SQL FK nullability and child PK/UK constraints. `submission_guards.job_id` permits zero/one Job per guard and zero/many guards per Job; `jobs.current_attempt_id` is required, deferred and not unique. SQL does not enforce same-Job membership of its current Attempt; code checks it. Both retry FKs and both Processing cleanup FKs are represented. Unique-but-non-FK reservation asset IDs and cross-context UUIDs have no fabricated FK arrows. [Processing base FKs](https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0001_intake.py#L35-L66), [retry/cleanup FKs](https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0002_lifecycle.py#L33-L63), [membership fence](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L28-L35), [reservation uniqueness without an Asset FK](https://github.com/Collaboration95/dc2/blob/76282d3/media/migrations/versions/0004_direct_uploads.py#L23-L45).

Final independent [schema results](W4-qa/schema-verification.json): **zero document/figure mismatches**. The ORM differences are the two previously documented absent recovery-index declarations and the newly documented SERIAL/default difference. They do not establish drift in a deployed database.

## S3, stores and message verification

**PASS.** Direct uploads stay at `staging/{owner}/{reservation}/source`; edit copies use `sources/{owner}/{asset}/source`. Finalized reservations and derived-source rows retain the actual source VersionId. Storage verification reads that version and checks size/hash; source deletion enumerates exact object versions. [Reservation/finalization](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L99-L204), [versioned verification/deletion](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/storage.py#L62-L136), [edit copy/adoption](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L105-L170).

Output prefixes use **Attempt UUID**, not attempt_number. Primary extensions, HLS master/variant/segment names, empty-operation HLS selection and master-last upload agree with the worker. Output descriptors have no output VersionId. [Prefix](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L20-L21), [worker publication paths](https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/tasks.py#L16-L81), [HLS filenames](https://github.com/Collaboration95/dc2/blob/76282d3/media_engine/hls.py#L108-L117).

The stores overview correctly distinguishes SQL authority, versioned object storage, queue transit and supporting operational stores. The three base queue/DLQ pairs plus conditional short-lane pair, seven-/14-day retention, receive threshold, private/versioned buckets and one-day SQL backups agree with the provisioner. This is configuration evidence, not a live inventory. [Aurora/buckets](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L501-L595), [queues and short-lane gate](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L596-L662).

The ten required Envelope keys, six Source fields, five kinds, lane mapping, payload validation boundaries and no-Job cancellation exception agree with contracts and producers/consumers. A cancellation result is not a sixth kind; cancelled is derived for snapshots rather than allowed in jobs.status. [Contract](https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L100-L218), [work/result producer](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L78-L129), [command consumer](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L232-L305), [Media command producer](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L17-L35).

Nine bounded [contract/path checks](W4-qa/contract-checks.json) passed, including actual work/result producer bodies, required nullable keys, exact cancellation payload keys, UUID output prefix and actual HLS command paths. These checks did not send SQS messages, access S3 or execute FFmpeg.

## NoSQL ADR verification — official documents opened

**PASS.** The original ADR did not claim NoSQL lacks transactions. The recommendation remains tied to preserving the implemented state/inbox/outbox transaction, uniqueness and execution fences, with no unsupported cost/performance superiority claim. Capability and deployment qualifications were made explicit in the report and ADR speaker notes:

- MongoDB supports single-document atomicity and multi-document ACID transactions on replica sets and sharded clusters; standalone deployment differs. [Transactions](https://www.mongodb.com/docs/manual/core/transactions/), [production requirements](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/).
- MongoDB supports single/compound unique indexes. Shard-key-prefix restrictions and the per-shard `_id` exception matter when sharding. [Unique indexes](https://www.mongodb.com/docs/manual/core/index-unique/), [compound uniqueness](https://www.mongodb.com/docs/manual/core/index-unique/create-compound/).
- DynamoDB `TransactWriteItems` supports up to 100 actions on distinct items and 4 MB total in one account/Region. Conditions can attach to writes; two actions cannot target the same item in one transaction. [API limits](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_TransactWriteItems.html), [transaction behavior](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html), [conditional writes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html).
- DynamoDB GSI keys can repeat; race-safe secondary identities need an explicit design. Neither database makes a database mutation plus an arbitrary external SQS send atomic by itself. [GSI semantics](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html), [transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).

Also opened the cited AWS database-selection, DynamoDB modeling and Lambda/DynamoDB pages. The proposed read-store/CDC variants remain labeled future work, with reconciliation and deletion requirements.

## Main/backup placement and visual verification

Main sections, in order: `w4-stores` (REPLACES s26), `w4-media-main` and `w4-processing-main` (NEW after s26), `w4-keys` (REPLACES s27). All remaining 22 sections are `data-kind="back"`; all carry `<!-- NEW backup -->` except the preserved `<!-- REPLACES s65 -->` before `w4-media-assets`. IDs are unique and the ADR is reachable through the verified link.

Re-rendered affected PlantUML sources with the specified headless Java/1.2026.9 jar: `W4-media-main`, `W4-processing-main`, `W4-processing-attempts`, `W4-processing-launcher`. Independently rasterized **all 16 SVGs** with `npx -y @resvg/resvg-js-cli@2.6.2-beta.1` at the 1180×520 figure-fit bound and inspected every PNG. No ER notation or main-slide legibility defect remained. Main ER minimum text: **Media ≈13.7px; Processing ≈14.2px**. [Fit-size measurements](W4-qa/figure-legibility.json); PNGs are beside that file.

Rendered and inspected the four complete main slides and ADR with the deck CSS at 1280×720 through `html_preview`. Browser inspection confirmed all 26 sections, all image loads, four main sections, and no horizontal overflow or header/footer overlap. [DOM layout evidence](W4-qa/browser-layout.json). T3 `preview_snapshot` twice returned `Preview automation snapshot timed out after 15000ms.`; visual inspection therefore used resvg PNGs and the separate successful HTML renderer. No screenshot success is inferred from those failed calls. Prior `W4-preview/*.png` files are author snapshots, not the final independent evidence.

## Remaining scope and evidence limits

No unresolved W4 documentation defect was found after these fixes. The two ORM index omissions and SERIAL/model-created-DDL difference remain tracked for any future model-driven schema-creation requirement; application changes are outside this pass. No live Aurora catalog, deployed migrations, AWS resource census, alternate database implementation, benchmark or coordinator-integrated deck was verified. Current source hashes confirm the protected application/IaC files and `site/deck.html` were unchanged by this review.
