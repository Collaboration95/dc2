# dc2 pre AWS local delivery plan

Complete the approved reusable media platform locally, then leave an auditable
handoff for the team. The working target is three elapsed agentic days, with five
days maximum. This run is authorized to plan, implement, test, review, publish and
merge repository changes without human verification. It does not provision AWS
or operate the inherited Alibaba deployment.

Baseline: `b32d489566144202fbf6fc3887ce25d5321444fd`. The repository is already
flattened. Processing intake exists and passes tests, but has no worker dispatch.
The inherited web application/media engine and its tests are available to reuse.
The original proposal and course documents remain unchanged. The roadmap site's
visuals remain unchanged. The current issue contracts are in `backlog.json` and
`issues/`; GitHub identifiers are recorded in `github-map.json` after creation.

## Outcomes and personas

| Persona | Outcome | Use cases |
| --- | --- | --- |
| Maya, course coordinator | Batch-publish owned videos, see every outcome, retry stored sources, inspect output | UC-1–5 |
| Arun, independent trainer | Upload, track and play his own video in the existing browser | UC-1–4 |
| Jules, integrator | Reuse a documented API through an independent CLI; reproducible setup and checks | UC-1,3–5 |
| Sam, operator | Recover interruptions, change worker count and release/rollback Processing independently | UC-6–7 |

Personas are fictional planning devices from `project-roadmap/business-scope.json`.
They do not add roles, team ownership, learner sharing or new product features.

## Epics, waves and grouped pull requests

| Wave | Epic / issue keys | Grouped PR and outcome | Gate |
| --- | --- | --- | --- |
| 0 | E0: G1,G2 | Reviewed plan, GitHub execution board, contracts and review dispositions | Independent Sol xhigh planning PASS |
| 1 | E1: F1,F2,F3 | Reproducible setup, Make targets, deterministic test tiers, isolated local infrastructure | Fresh setup and infrastructure smoke; repeated fast checks; CI PASS |
| 2A | E2: P1,P2,P3 | Attempt-aware Processing, worker, retry/cancel and recovery | Processing tests + real DB/FFmpeg evidence |
| 2B | E3: M1,M2,M3 | Media ownership, HTTP Processing client, public compatibility and reconciliation | Media tests + real DB/contract evidence |
| 2C | E4: C1,C2 | Independent Publisher CLI and browser stored-source retry | CLI tests + browser unit/interaction tests |
| 3 | E5: V1,V2 | Integrated local workflows, contract cases and fault experiments | Real HTTPS clients, media output and recovery evidence |
| 4 | E5: V3,V4,V5 | Performance/scaling, separate release/rollback, final review and handoff | Recorded target results, clean Main and metadata reconciliation |

PRs group related issues, rather than one tiny PR per issue. Each issue still has
its own observable acceptance checklist. Related issues within a PR may be built
sequentially without prematurely marking downstream issues Ready. A group starts
only when its external dependencies are Done. The final PR may be split into two
multi-issue groups if independent experiment corrections would otherwise block
unrelated accepted work; record that change, do not hide open criteria.

Critical path: G1 → G2 → foundation → Processing/Media → clients integrated →
fault and contract checks → release/evidence → final review. CLI/browser coding
can proceed against the frozen contracts in parallel with backend work. Their
end-to-end acceptance waits for both backend lanes.

## Architecture and interface rules

Two live business services: Media Management and Processing. One PostgreSQL server
hosts separately owned databases and migration histories. Redis/RQ belongs to
Processing. Local S3-compatible object storage keeps source and output namespaces
private. Media owns source intake and playback signing; Processing owns attempts
and output writes. Both clients call Media's published API only.

Use the prepared public, Processing and reverse source-access OpenAPI contracts
in `project-roadmap/design/05-contracts/` as the interface baseline. Implement
changes only with explicit rationale in `decisions.md` and corresponding contract
tests. The current design documents are not runtime evidence.

- Public IDs are Asset IDs. Processing Job and Attempt IDs remain private.
- Durable submission intent and immutable request identity survive transport loss.
- Queue messages carry the already-reserved `(job_id, attempt_id)`.
- A current live attempt is required for claim, heartbeat and output publication.
- Processing renews expired source access through Media's owner/revision checks.
- Source/output URLs must resolve where used; browser HTTPS must not mix HTTP media.
- User retry retains source data; transport replay retains request identity.
- Submit and cancel serialize on the same stable asset guard. Deletion must also
  work after a lost submit response, before Media knows the internal Job ID.
- Keep inherited edit/delete/operator behavior. Add no editor features.

To minimize risky changes to the frozen baseline, new Media Management will live
in `media/` with its own metadata and migrations, while `app/` remains the tested
legacy reference. It must be the only public API in the final local topology.
Reuse existing authentication and media behavior with focused extraction rather
than importing legacy database/domain internals. Pure FFmpeg/probe helpers may
live in `media_engine/`, copied or extracted with provenance; neither live service
may import the other's ORM, repository or settings. This layout is the interface freeze for the backend lanes. Existing browser assets remain in `frontend/`.

No OIDC, credential broker, Kubernetes, autoscaling, public sharing, search,
moderation, analytics, historical data migration or additional product services.
Retain simple service tokens, owner checks, private datastores and ignored secrets.

## Foundation and test strategy

First provide root Make targets: `help`, `setup`, `doctor`, `lint`, `test`,
`coverage`, `up`, `down`, `logs`, `smoke-infra`, focused domain tests, integration,
`e2e`, `verify-local`, evidence runners and local release/rollback. Targets added
by later waves must fail clearly until implemented, never return fake success.

Python dependencies are locked; frontend uses its existing lockfile. Setup is
repeatable and never overwrites configured secrets. Configuration checks show
missing prerequisites before expensive builds. Tool versions and commands are
recorded. Test fixture media is generated deterministically with FFmpeg.

Tests have three tiers:

1. Fast unit/schema/API/client tests: no external services, no network calls,
   deterministic clocks and bounded mocks. Warm local target ≤30 seconds; fast CI
   target ≤3 minutes excluding queue time. Run three consecutive passes initially.
2. Real integration: isolated PostgreSQL/Redis/storage, real concurrent sessions,
   migrations, ownership, attempt races and short FFmpeg fixtures. Bounded polling,
   no fixed multi-second sleeps, no retry-to-green masking. Target ≤5 minutes for
   routine integration on a warm runner, measured rather than asserted.
3. Full local and evidence: HTTPS browser/CLI workflows, interruption/retry,
   independent releases and measured workloads. Slow experiments do not run on
   every unit-test invocation. Every release still needs their relevant evidence.

Retain combined statement/branch coverage ≥80% separately for each live backend,
shared helper and CLI package, plus the inherited app regression gate and all four
frontend ≥90% thresholds. Report raw branch rates separately; the80% number is
not an independent branch-rate claim. Include unexecuted production files.
Product PRs must extend lint/coverage/CI package selection as new packages arrive.
Measure new service/client packages, not just the inherited application. Do not
inflate coverage with implementation-mirroring tests. Exact race, failure and
lifecycle behavior matters more than maximizing a percentage. CI posts stable
aggregate fast/integration checks even when selective execution is used, so an
unrelated path filter cannot leave a required check permanently pending.

Local TLS uses a project-generated CA/certificate and explicit trust settings for
CLI/tests. Real browser selection: pinned Playwright Firefox in a project-local
installation with its CA imported through NSS certutil into a project-local
temporary profile. The policy-based plan was replaced after an actual trust failure;
positive and negative verification now pass without changing system trust. The coordinator owns its launcher and pinned
tooling. `make browser-trust-smoke` must prove trusted HTTPS navigation and an
untrusted-certificate rejection before foundation acceptance; no certificate-error
bypass or insecure browser flags. SANs cover public API and media URL hostnames. Do not modify the system trust store or turn off
TLS verification. Ports, project names, volumes and test identities are isolated.

Wave 1's `make up` may expose infrastructure and the current Processing intake
only. Its HTTPS checks establish routing/trust; actual Secure-cookie login and
video workflow acceptance is V1 after the Media lane is integrated.

## Worktree and agent coordination

Use GPT-6.1 Sol high for implementers and xhigh for planning/complex integration
reviews. Keep at most three code writers plus one independent reviewer active.
Create worktrees under ignored `.worktrees/`, each with an explicit branch and
write scope. Agents commit locally and report hashes, changes and checks. Only the
coordinator publishes/creates/links PRs, integrates branches and updates GitHub.
All GitHub access goes through authenticated `gh`.

Foundation is serialized before product lanes. Then ownership is:

- Processing lane: `processing/`, `media_engine/`, its migrations/domain tests.
- Media lane: `media/`, its migrations/domain tests and source-access/public routes.
- Client lane: `publisher/`, `frontend/`, client tests.
- Coordinator: root Make/packaging/Compose/CI, integration harness, evidence and
  reconciliation. Shared-file changes are requested as a patch or explicit note;
  never concurrently rewrite these files in multiple lanes.

Each worktree gets a distinct Compose project/port range when it needs containers.
On constrained Docker resources, serialize integration runs while code/unit tests
remain parallel. Never run project-wide `docker system prune`, touch another
project's containers, delete unknown volumes or mutate global Docker settings.
Do not use worktree-wide destructive cleanup to resolve conflicts. Preserve and
inspect edits; rebase/cherry-pick or merge only reviewed commits.

## Review, merge and completion

Planning review occurs after the complete local/GitHub plan exists. The reviewer
checks scope, DAG, acceptance, interfaces, tests, resource realism and PR grouping.
Record verdict/findings, fix them, and obtain PASS before Wave 1 implementation.

Every implementation PR lists covered issue numbers and uses closing keywords
only for issues whose full acceptance is satisfied,
concrete behavior changes, commands and results, and remaining limitations.
Register every PR with the thread's `link_pull_request` tool immediately.
Independent review returns PASS/REVISE with issue-by-issue evidence. The author
fixes substantive findings; reviewer rechecks the changed paths. Existing Trivy gates must cover every distinct
live Media/Processing/worker image digest, not merely the legacy image. Promotion
requires passing build/tests and zero fixable HIGH/CRITICAL findings for the exact
candidate; identical API/worker digests need only one scan. Tests must run
against the exact reviewed head. Merge only after required checks and review PASS;
user authorization already permits this local/GitHub release process.

Done means merged into Main plus acceptance evidence. A closed issue or passing
unit test alone is not Done. Parent epics complete only when all required children
are complete. Project status follows actual evidence, not optimistic dates.

## Quality targets and evidence

Keep the proposal's initial targets visible:

- Status: 50 users polling for3min, p90≤700ms, errors<1%.
- Login measured separately: 20 concurrent users, p90<2s.
- Scaling: 30 identical60s720p clips, 1/2/3 workers, each capped at2vCPU;
  two-worker throughput≥1.6× and three-worker≥2.1× one worker, decreasing median
  queue wait and zero failed jobs. Record processing time, CPU and memory too.
- Worker kill: visible failure or requeue≤5min, retry succeeds, no duplicate output.
- Lost queue entry: re-enqueue≤2min, including surviving queue metadata.
- Independent Processing release plus smoke≤10min; MM and media migrations unchanged.
- CLI uses no service imports/DB credentials; record actual effort against2person-days.

Current Docker Desktop allocation is2CPU/2GiB. The host has10CPUs/32GiB. This
allocation cannot fairly run3×2vCPU encoders plus services. Investigate a separately
scoped project-local runtime or host harness if necessary, without global setting
changes. Record architecture/quotas and any difference from the proposal. A
thread-count-only limit is not proof of a hard2vCPU quota. F3 owns the bounded project-local capacity investigation and records feasibility
before this evidence wave. If sufficient local capacity cannot be made available
within scope, finish the reproducible runner
and pilot, record the specific blocker and keep full-scaling acceptance open.
Never silently reduce the workload/targets or classify oversubscription as success.
Any revised target requires recorded baseline rationale before final runs; report
both original and revised results rather than rewriting evidence after a failure.

Evidence stores exact Git SHA, timestamps, configuration excluding secrets,
fixture hash, resources, command, raw data and evaluated targets. Mark local
results as local. Do not call them AWS results. Synthetic intake is not processing.

## Morning handoff and scope boundary

`docs/execution/handoff.md` will state what works, exact start/stop/test commands,
local URLs, where local credentials live (never values), all PR/issue links,
measured results, outstanding limitations and the next AWS prerequisites.
`progress.json` is the machine-readable issue/PR/check ledger. `decisions.md`
records all additions and deviations. `reviews/` retains independent findings.
Preserve an evidence source pack for report/presentation work; original academic
materials and scheduled deliverables remain unchanged.

Remaining AWS prerequisites are account/region, budget, domain, credentials and
adequate compute. Do not provision, log into AWS, or use another project's AWS
configuration during this goal. A locally prepared deployment script may describe
future inputs, but it must not call AWS during tests or this run.

## Planning inspection findings incorporated

The Processing inspection requires a responsive lease supervisor across download,
encoding and upload; lease loss must stop the process group and stale success or
failure cannot publish. Inherited HLS fallback must not swallow lease cancellation.
Budget the whole attempt rather than assigning the old900s RQ limit to multiple
870s media stages. Nonempty operations means edit; Processing stores normal upload
operations as an empty list. Regenerate source access if the originally stored
URL expires, even when Submit replay supplied a newer URL.

Queued recovery must inspect runnable membership, not merely the existence of an
RQ hash. Output cleanup must account for late uploads after cancellation and
never delete Media-owned sources. Retain guards for the demonstration lifetime.
Preserve served HLS playlist bodies, external /api prefixes and owner checks.

Foundation isolation includes unique image tags and queues/buckets as well as
Compose names, ports and volumes. Builds/live suites are serialized on the current
small Docker allocation. The old jsdom live test is not credible browser evidence:
its cookie handling and copy-job assumptions must be replaced by a real-browser
flow. Existing baseline tests still run; synthetic intake stays a separately
controlled tier after worker dispatch is connected.

## Conditional scaling and handoff gate

V5 depends natively on V2 and V4. V3 has an additional assessed-result prerequisite,
not an unconditional Done edge: either full fair-capacity scaling evidence exists,
or the reproducible runner/pilot and exact capacity blocker are documented.
If capacity is still unavailable, V3 and parent E5 remain open/Blocked; accepted
scripts and handoff may merge, using closing keywords only for satisfied issues.
V5 explicitly distinguishes completed local implementation from outstanding UC-6
scaling acceptance. It must not call the entire proposal complete in that case.

The browser proves actual MP4/HLS playback and owner deletion. The CLI proves
registration/login, mixed-success folder publishing, each file's outcome, status,
authorised output access and stored-source retry. C1 merges against controlled
public-contract responses plus import/credential checks. V1 owns the live CLI
batch proof after backend integration; no CLI player or delete command is added.
