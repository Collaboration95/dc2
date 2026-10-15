> Historical AWS2 readiness assignment, completed and superseded for execution.
> Current authority: [V1/V2 architecture](docs/execution/aws/architecture-plan.md)
> and [dependency-ordered V1 handoff](docs/execution/aws/v1/README.md).
> Preserve the older findings/evidence; do not execute this swarm brief again.

# Handoff to GPT-6.1 Sol: swarm the AWS readiness gaps, build the backlog, audit it

You are the lead **GPT-6.1 Sol** agent for this repository. Execute this assignment;
do not merely propose a plan. Use multiple delegated research agents to identify
what must be retained, adapted, replaced, or refactored for the accepted lean AWS
architecture. Create the resulting GitHub epics and issues, then have a **fresh,
standard GPT-6.1 Sol agent independently audit the final findings and remote backlog**.

This run is **readiness analysis and backlog creation**, not implementation of all
those issues. Deliver a concrete, dependency-ordered implementation handoff.

## Authorization and boundaries

The user approved the revised architecture and explicitly requested this swarm,
GitHub epics/issues, and final Sol audit. Proceed with that work without asking
for permission again. This instruction supersedes the older HANDOFF.md statement
that forbids launching agents merely to reconsider the plan.

You may inspect the repository, run cheap offline checks, write analysis/backlog
artifacts, and create/update the relevant GitHub issues and Project metadata.
Do not begin product refactoring, run live experiments, change the existing demo,
provision AWS, incur cloud spend, operate Alibaba, or use another project's AWS
credentials. No application implementation is needed to complete this assignment.
Do not reopen completed local issues just to represent new cloud adaptation work.

Work from `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2`.
For **all GitHub access use authenticated `gh` exclusively**. No GitHub connectors,
direct HTTP clients, or browser access. Use structured CLI inputs/body files for
multiline content. Never print credentials, environment dumps, cookies or signed URLs.

## Read first and establish provenance

1. `AGENTS.md` and the latest dated entry in `docs/project2-worklog.txt`.
2. **Authoritative current plan:** `docs/execution/aws/README.md` and
   `docs/execution/aws/architecture-plan.md`.
3. `docs/execution/aws/cost-worksheet.json`, `calculate-costs.py`,
   `pricing-20261015.json`, and `job-inputs.template.json`.
4. `HANDOFF.md` for implementation/evidence context, with its new notice taking
   precedence over the historical body. The `*-20261014.*` AWS documents are archives.
5. `docs/execution/interfaces.md`, `docs/execution/handoff.md`, the current code,
   active `compose/local/docker-compose.yml`, and `docs/execution/experiments-20261014/`.
6. `project-documentation/Team17-Proposal.docx`, especially §§1.3–1.4, 2.2–2.5,
   3.3–3.5, when tracing the contract. Leave original course/proposal documents intact.

Record `git status --short`, branch, exact HEAD and relevant file hashes. The
implementation baseline before the planning commit was `485edac`; discover the
actual current planning revision rather than treating this older SHA as HEAD.
Use `git log -1 --format='%H %s' -- handoff-temp.md` to locate this handoff's commit.
Preserve user changes, frozen worktrees, local volumes and historical evidence.

Use the `init-project` skill for backlog creation if available; the local copy is
`/Users/speedpowermac/.codex/skills/init-project/SKILL.md`. Read its GitHub operations
reference before remote mutations. Apply mode is authorized by this handoff.
Current repository, plan and intended existing Project are identified below;
do not create a redundant clarification gate. If an input is genuinely missing,
continue independent analysis and mark only its dependent work blocked.

## Accepted architecture and budget constraints

- Two business services: **Media Management** and **Processing**. Separate owned
  databases/roles/migrations, HTTP contracts, images and releases. Helpers, queue,
  workers and nginx are not extra business microservices.
- Media: ECS Fargate, initial 1 vCPU / 2 GiB, API plus its reconciler.
- Processing API: separate ECS Fargate service, initial 0.5 vCPU / 1 GiB.
- Processing recovery: separate task/service, initial 0.25 vCPU / 0.5 GiB.
- Disposable Processing workers: 2 vCPU / 4 GiB each, zero when idle, at most three.
  The existing `python -m processing.worker --burst` drains and exits.
- Default first demo: explicit bounded batch starts. Unattended demand-based starts
  are **optional**, not a required new controller, table or scheduler service.
- One `t3a.small` (2 vCPU / 2 GiB, Standard CPU credits) for PostgreSQL, Redis and
  nginx only. No Media/Processing API or FFmpeg on that machine. Shared database,
  gateway and AZ failure boundaries are acknowledged.
- One VPC, one AZ, one public subnet, ordinary narrow security groups, Internet
  Gateway and **free S3 gateway endpoint**. No paid interface endpoints, NAT,
  ALB, private/public subnet pair, service mesh, Kubernetes, RDS or ElastiCache.
- Private same-region S3 sources/outputs. Internal object traffic uses the gateway;
  signed external playback still incurs egress. S3 is not physically inside a VPC.
- Public browser access through an AWS-generated CloudFront HTTPS URL. No purchased
  domain and no Tailscale installation on viewers. The proposed CloudFront-origin
  HTTP leg is an explicit unresolved interpretation of the proposal's HTTPS rule;
  assess it honestly rather than assuming compliance or silently adding paid services.
- **Downtime:** three ECS services desiredCount=0, no standalone worker tasks,
  EC2 stopped, no reserved Elastic IP. Update CloudFront's origin to the new EC2
  public DNS on wake; slower warmup is acceptable. Keep zero active compute.
- 16-GiB root + 8-GiB data EBS are initial sizing envelopes, not measured minima.
  Tiny quiescent metadata exports; no default EBS snapshots. Retain basic login,
  ownership, private stores and secrets outside Git/images. Native task roles are
  appropriate; no credential broker, OIDC programme or elaborate security platform.
- **At most 14 days remain from the 15 October planning checkpoint. Do not reset
  this into a fresh two-week implementation schedule if execution starts later.**
  Expected 20 billed core-hours / 2 cumulative worker-task-hours; larger scenario
  40 / 8. These include startup and drain, not only visible presentation time.
- Expected AWS usage **$6.03**, **$13.03 including reserves**; larger scenario
  **$13.27 / $28.27**. Working targets **$15 / $30 USD**. Retained storage/internal
  DNS baseline about **$1.73 across 14 days**, already included. These are assumptions,
  not hard bill caps. Actual account, region/currency and paid authorization are pending.
- **Small fixtures:** six ~21-MB long submissions total for 1/2/3-worker capacity
  demonstrations, plus short workflow checks, about 0.25 GB total uploads. Reuse
  assets for polling/playback/ownership and stored sources for retry. No 300-clip
  cloud replay, hours of new local trials, or new large performance experiment.
- Full original scaling targets and accepted local evidence remain unchanged.
  The small AWS demonstration does not prove the full throughput targets. Both
  issue 38/39 experimental candidates remain rejected.
- Preserve the existing frontend/roadmap design and illustrations. Reuse the engine,
  Redis/RQ, clients and proven boundaries. Every new component needs a concrete benefit.

## Swarm organization

Call `orchestrator_capabilities` at the start and use the live catalog. On 15 October,
T3 exposed provider instance **`codex`**, model **`gpt-6.1-sol`**, with
`reasoningEffort` and `serviceTier` options. Recheck these identifiers; do not guess
or silently substitute a different model if Sol is unavailable.

Use four bounded, disjoint research lanes, normally at most four active children.
Use standard service tier and ordinary high reasoning for substantive analysis;
no priority tier, ultra/max fleet, recursive subagents or top-level conversations.
The final auditor is a separate single Sol agent, not a member of this discovery swarm.

Prefer native child tools only if they support the selected model. Otherwise use
T3 `delegate_task` with that provider/model, `mode: async`, a unique stable
`clientRequestId` per task and `role: research`. Retain every `taskId`. Do not use
`t3_thread_launch` or `create_threads`: these would create unrelated top-level work.
Each prompt must carry the constraints and exact lane brief because children do
not inherit the whole conversation. Use completion notifications, with bounded
`task_status` calls when a result is needed; do not launch duplicates or poll continuously.

If T3 tools are initially absent, make the documented direct capabilities attempt.
If this is an ACP session with `T3_ACP_MCP_NODE`, use the supported `acp-mcp-call`
transport fallback. Report a real capability failure rather than inventing a swarm.

Only the coordinator mutates GitHub or the shared backlog/architecture documents.
Children inspect code and may write only their own lane report under
`docs/execution/aws/readiness/lanes/`. No child commits, pushes, edits application
code, starts Docker/cloud resources, or spawns more agents. These read-only lanes
do not need separate worktrees. Do not disturb `.worktrees/final-measurements`.

| Lane | Inspect | Required output |
|---|---|---|
| A — Storage, credentials and ownership | `media/config.py`, `media/services/storage.py`, `processing/config.py`, `processing/worker/storage.py`, recovery stores, database roles/migrations | Exact static-key assumptions; ECS temporary-token refresh; source grants; multipart/CORS/expiry behavior; role boundaries; smallest safe adapters |
| B — ECS placement, networking and state | Dockerfiles, active Compose, nginx config, PostgreSQL bootstrap, existing deployment files, current AWS plan | Task/container roles and sizing, readiness, DNS replacement, dynamic public-IP wakeup, CloudFront routing/caching/headers/TLS interpretation, S3 gateway policy, state persistence and full shutdown gaps |
| C — Processing lifecycle and capacity | Worker entrypoint/supervisor/tasks, Redis/RQ publication, SQL leases/fencing, recovery, release/drain paths | Burst-task suitability, empty-queue exit, bounded manual starts, interruption/retry semantics, safe drain and rollback, how to avoid charged orphan tasks; optional automation clearly separated |
| D — Delivery, clients and evidence | `.github/workflows/`, Make/runtime scripts, `scripts/dev/release.py`, smoke/evidence helpers, frontend and Publisher, current reports | Localhost/Compose/MinIO coupling, cloud endpoint/trust adapters, independent image/migration release evidence, limited smoke coverage, secret-safe logs and cost/teardown evidence |

Keep a small task ledger with provider/model/options, task ID, source SHA, lane,
status and report path. Each lane returns an evidence table:

- Stable finding ID, severity and category: **retain / configure / adapt / refactor /
  replace / optional / blocked**.
- Exact file and line/symbol, current behavior, and why it does or does not fit.
- Smallest proposed change, preserved invariants, owning service and interfaces.
- Observable acceptance check, a credible verification method, dependencies and risks.
- Cost/idle-compute impact and any unresolved question.
- Distinguish code observation, documentation claim, inference and untested behavior.

A finding without code evidence is a question/spike, not an invented refactoring need.
Explicitly record components that already fit so the backlog does not rebuild them.

## Coordinator synthesis and GitHub application

Repository: **`Collaboration95/dc2`**; default branch historically **`Main`**.
The existing course Project is historically **Project 14** for this repository.
Verify its owner, identity, fields and current items through `gh`. Reuse it when
it still serves this work; do not reset completed local-delivery statuses or create
a new Project by default. Old metadata files are context, not fresh remote truth.

Inspect open and closed issues, matching stable keys, labels, relevant open PRs and
Project state before creating anything. Resolve cross-lane disagreements by reading
the implicated code. The accepted topology is the target, but audit its assumptions:
record a narrowly justified correction when necessary, with cost and scope impact.
Do not convert every possible improvement into mandatory work.

Create a compact readiness matrix and a dependency-ordered backlog, then apply the
GitHub changes. Show a short summary of what will be created/reused and continue;
the user has already authorized creation, so do not stop for another approval.

Aim for roughly four outcome epics, with focused implementation issues and only
necessary spikes. Grouping suggestions, not predetermined findings:

1. Cloud service configuration, credentials and owned storage.
2. Minimal infrastructure, public access, state and zero-compute downtime.
3. Independent release, bounded worker execution and recovery.
4. Small cloud acceptance, cost evidence, operational handoff and teardown.

Use a separate optional lane for unattended starts, Spot, ARM, extra backups or
further component consolidation. Do not make these dependencies of the first demo.
The origin-TLS question and any unresolved account policy belong in explicit spikes
or blocked deployment prerequisites, not hidden assumptions in Ready issues.

Every epic and child needs a stable marker, for example:
`<!-- agent-orchestration:issue-key=aws2-runtime-task-credentials -->`.
Search for this key across open/closed issues before creating. Reuse/update an existing
matching object; never duplicate it because a title changed. Keep a new AWS-specific
issue map; preserve the historical `docs/execution/github-map.json` ledger.

Each child issue must include:

- Problem, evidence references, current behavior and desired observable outcome.
- In scope, out of scope, files/interfaces/owner and preserved invariants.
- Checkable acceptance criteria and commands/manual checks clearly labeled **future**
  where they have not been executed. No fake results or copied local results labeled AWS.
- Dependencies, risk, rough focused-session size and cost impact.
- Whether it is Ready, waiting for another issue, optional, or blocked on actual
  account/currency/spending approval. Local adapter work need not wait on credentials.
- Stop conditions for scope expansion or paid actions, and its stable key.

Use one-reviewable-change scope. Add real parent/sub-issue and blocking relationships
where supported by the authenticated CLI; if a relation cannot be applied, preserve
explicit reciprocal links and report the limitation. Reuse existing Project field
values; avoid gratuitous labels/views or a new process framework. Only dependency-free,
well-specified work is Ready. Do not close an implementation issue because its plan
exists, and do not mark the cloud architecture implemented.

After applying, fetch the created/updated issues and Project entries again through
`gh`. Save the exact URLs, statuses, relationships and stable-key mapping. If a
permission fails, keep the complete local backlog, name the failed operation, and
continue all work that does not depend on it; do not claim remote creation succeeded.

## Required final independent audit: one normal GPT-6.1 Sol

After the findings and actual GitHub backlog are complete, delegate a **new** task
with `role: review`, model **`gpt-6.1-sol`**, **standard service tier**, and normal
high reasoning. No priority tier, ultra/max mode, recursive swarm, or self-review.
This agent must not be one of the discovery workers and must not spawn children.

Give it the original assignment and constraints, inspected source SHA, complete
readiness matrix, all lane reports, local backlog, exact issue/Project URLs and
remote-state evidence, assumptions, disagreements and unresolved objections.
Do not send only the coordinator's conclusions. The auditor must independently
inspect critical code and use `gh` to verify a sample of issues/relationships and
all proposed blockers. It writes a separate report, not implementation changes.

Ask for **PASS / REVISE / BLOCKED**, with evidence and severity, checking:

1. Coverage of the actual cloud-adaptation gaps and explicit reuse of existing code.
2. Separate releases/data ownership, worker capacity, and honest shared failures.
3. No forbidden large host, paid domain, NAT/ALB, unnecessary AWS service or live work.
4. True zero compute/IP residency during downtime, bounded starts, no orphan billing,
   and correct wakeup/drain/teardown dependencies.
5. Native temporary credentials, signed S3 behavior, private DB/queue access and
   CloudFront cache/cookie/CORS/origin-TLS constraints without a security rewrite.
6. A 14-day maximum anchored to the original college window, small fixtures,
   accurate cost arithmetic and no unnecessary bulk measurements.
7. Useful, deduplicated, actionable epics/issues; correct dependencies/Ready states;
   optional work excluded from the critical path; no false remote/validation claims.
8. A concrete next implementation issue that can start with the available inputs.

Fix substantive findings in the analysis and issue bodies. Each rereview must be
another fresh `delegate_task`, with a new round-specific request ID, carrying the
original brief, prior findings, responses and remaining objections. Do not continue
an audit by messaging `childThreadId`. Normally allow at most two correction rounds;
if substantive blockers remain, report them honestly with non-Ready dependent work.
An auditor may PASS the backlog while identifying deployment blockers—it is not
certifying cloud implementation or approving expenditure.

## Deliverables and finish criteria

Write these under `docs/execution/aws/readiness/` (create the directory as needed):

- `README.md`: current decision, critical path, blockers, links and next concrete issue.
- `task-ledger.json` and the four `lanes/*.md` reports.
- `gap-analysis.md`: evidence-backed retain/change matrix, disagreements and decisions.
- `backlog.json`: stable-key epics/issues, dependencies, acceptance and readiness.
- `github-map.json`: actual remote IDs/URLs and verified Project relationships.
- `audit-sol.md`: independent auditor identity/configuration, reviewed source,
  findings, final verdict, remaining objections and correction receipts.

Update the dated worklog with what actually happened. Keep planning snapshots
separate from implementation evidence. Commit/publish only the scoped planning
artifacts if authorized by the active session's repository workflow; do not sweep
unrelated changes into that commit. If you work on a PR, register it with T3's
`link_pull_request` and reconcile thread PR links before finishing. Do not use
T3 linking to fetch GitHub content; all GitHub operations still go through `gh`.

The final user response must include the Project and epic/issue links, the small
set of required changes, what stays intact, optional cuts, dependency order, exact
next issue, audit verdict, unresolved blockers and a statement of what was actually
created/updated. Do not stop at a plan-only answer when GitHub creation is authorized
and available. Do not start implementing the full backlog as a surprise next phase.
