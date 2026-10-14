> **Latest replanning, 15 October:** [Lean Fargate plan](docs/execution/aws/architecture-plan.md).
> User clarified **14 days maximum**, minimal cloud fixtures, and cost levers with
> zero running compute during downtime. Expected allowance **$13.03 USD**, larger
> scenario **$28.27**, including reserves. No retained EIP; accept origin warmup.
> About $1.73 of storage/internal DNS remains over 14 days. Public browser access
> is required. The HTTP origin tradeoff is explicit; no deployment is approved.
> No application changes, provisioning or new performance evidence occurred.
> Historical brief below retains its original budget/time assumptions; these are
> superseded. Full local evidence stays local; no bulk cloud replay is planned.

# Handoff: reconsider the AWS microservices deployment

Prepared: 15 October 2026. Evidence and merge receipts were checked on 14 October 2026.
Repository: `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2`.
Verified implementation baseline: Main `485edacff62bae0db7fddf81d15f4d4dcea5915b`.

## 1. Read this instruction before the previous AWS plan

The user requests a fresh architecture review by a more capable planning agent.
The central objective is the transition from a monolith to reusable microservices.
The AWS deployment must demonstrate independent deployment and processing capacity.

The user challenges the previous recommendation to place both services on one EC2 host.
The user also challenges the proposed 128 GiB EBS allocation and EBS snapshots.
Do not treat those choices as approved requirements.
Do not defend them merely because earlier agents recorded them as defaults.

The latest user instruction takes precedence over the shared-host defaults in older notes.
Preserve the completed service implementation and its evidence.
Reconsider the cloud topology, storage quantities, backup policy, and cost assumptions.

This handoff requests planning. It does not authorize provisioning or spending.
Do not launch another agent fleet or repeat the completed local experiments.

## 2. What the original proposal actually commits to

The authoritative team proposal is
[Team17-Proposal.docx](project-documentation/Team17-Proposal.docx).
Read its sections 1.3, 1.4, 2.2–2.5, and 3.3–3.5.

Its explicit commitments include:

- Separate Media Management and Processing services.
- Separate domain models, data ownership, database roles, and migration histories.
- Communication through an authenticated API contract.
- Processing capacity changes without scaling or redeploying the user-facing API.
- Each service can deploy independently from versioned container images.
- The web application and an independent Publisher CLI use the published API.
- APIs and workers are stateless. Databases and object storage hold durable state.
- Disposable workers reconcile interrupted jobs. Retry uses the stored source.
- Independent Processing release, smoke test, and rollback.

Relevant proposal locations:

- **Section 1.3:** independent capacity and separate service releases.
- **Section 1.4:** the new service and data boundaries, compared with Project 1.
- **Section 2.2, Figure 2:** separately owned and separately deployed services.
- **AD-01:** extract Processing from the inherited application.
- **AD-02:** two service databases on one PostgreSQL server, with separate roles and migrations.
- **AD-07:** AWS containers in one small environment. Exact AWS products were deferred.
- **Section 2.5:** both services and workers run as containers. Each service can deploy independently.
- **UC-6:** change worker capacity without touching Media Management.
- **UC-7:** release Processing while Media Management and its migrations remain unchanged.
- **Section 3.3:** stateless compute, durable external state, disposable workers, and per-service releases.

“One small environment” does not require one EC2 instance.
The proposal explicitly permits one PostgreSQL server for the two owned databases.
It does not require a separate database server for every service.
It contains no EBS sizing or snapshot commitment.
It does not specify 128 GiB, 32 GiB root, or 96 GiB data volumes.

The general course briefing allows different technologies.
That flexibility does not remove this team's specific service-extraction commitments.
Use [briefing-requirements.txt](project-documentation/briefing-requirements.txt) for course context.
Use the Team 17 proposal for this team's scope.
The legacy `docs/proposal.md` and Project 1 sprint documents are not the current proposal.

### Logical services and physical placement

Microservices depend on service boundaries, owned state, contracts, independent releases, and scaling.
A separate virtual machine for every process is not a defining requirement.
Co-hosted independent services do not automatically become a monolith.

However, a shared compute host preserves shared CPU, memory, disk, shutdown, and host-failure boundaries.
The user wants the cloud plan to demonstrate meaningful operational independence.
Explain that distinction without dismissing the user's deployment objective.
Evaluate separate service placements and separate processing capacity as the preferred direction.
State exactly which dependencies and failures remain shared in each option.

Earlier [AD-07](project-roadmap/design/04-architecture/AD-07.md) describes a shared-host logical reference deployment.
The October deployment design later recommended a consolidated EC2/Compose host.
The previous AWS planner also received that topology as a selected default.
These assumptions influenced its recommendation.
The current user instruction reopens that choice.

## 3. What already exists in code

The inherited monolith had one `app/` package, shared job models, and a shared database.
Separate worker containers already existed before Project 2.
Their presence alone was not the new service contribution.

The current implementation has two business services:

- **Media Management:** `media/`, built with `deploy/media.Dockerfile`.
  It owns users, Assets, sources, ownership, signing, edits, deletion, and submission reconciliation.
- **Processing:** `processing/`, built with `deploy/processing.Dockerfile`.
  It owns Jobs, Attempts, output records, Redis/RQ, FFmpeg workers, leases, and recovery.

Media calls Processing over HTTP.
Processing renews source grants through Media's internal HTTP API.
Neither service imports the other's ORM, repositories, or settings.
Cross-service owner and asset identifiers are plain references.
There are no cross-service user/Asset foreign keys.

One local PostgreSQL server hosts `media_db` and `processing_db`.
Runtime and migration roles enforce separate ownership.
Separate migration histories permit independent service migrations.
Database roles cannot access the other service's database.

The shared `media_engine/` package contains reusable media helpers, not shared service state.
The standalone `publisher/` client uses the public HTTPS API only.
It has no service imports or database credentials.
The inherited frontend remains in `frontend/`.

The legacy `app/` package and root Dockerfile remain regression references.
They are not a third live business service.
Do not deploy the inherited root Compose application as the new platform.

The integrated local topology is [compose/local/docker-compose.yml](compose/local/docker-compose.yml).
Local Compose is a development and evidence environment.
It does not settle the correct AWS placement.
Its loopback URLs, local TLS, MinIO configuration, and internal networks require cloud adapters.

Read:

- [Logical architecture](project-roadmap/design/04-architecture/logical-architecture.md)
- [Service-boundary decision](project-roadmap/design/04-architecture/AD-01.md)
- [Data ownership decision](project-roadmap/design/04-architecture/AD-02.md)
- [Integration interfaces](docs/execution/interfaces.md)
- [Execution plan](docs/execution/plan.md)
- [Current local handoff](docs/execution/handoff.md)

## 4. What the evidence establishes

PR40 merged at `485edac` after all 16 PR checks passed on `f234ff6`.
Exact Main CI38578589312 passed all 14 jobs.
The working tree was clean before creation of this handoff.
All 30 tracked Project 14 items are Done. No issues remain open.
Those statuses describe completed local work and resolved experiments, not an approved AWS topology.

PR links:

- [PR37: resource improvements](https://github.com/Collaboration95/dc2/pull/37)
- [PR40: experiments and previous AWS preparation](https://github.com/Collaboration95/dc2/pull/40)
- [Verified Main CI](https://github.com/Collaboration95/dc2/actions/runs/38578589312)

All GitHub access must use authenticated `gh` exclusively.
Do not use GitHub connectors, direct HTTP API access, or browser access.

### Accepted historical local results

- Full web and CLI workflow, including decoded HLS/MP4 and stored-source retry, passed.
- Nine scaling batches processed 270 identical 60-second 720p clips successfully.
- At hard 2-vCPU worker limits, 2/3 workers delivered 2.032×/2.885× baseline throughput.
- Historical isolated status p90 was 544–605 ms. Isolated login p90 was 1.873–1.899 s.
- Worker failure became visible in 69.2 s. Queue-entry repair took 23.5 s.
- Independent Processing promotion, active drain, failed candidate, and automatic rollback passed.
- Media container/image identity and its database revision remained unchanged during Processing release.

The original proposal's targets remain relevant:

- Three worker counts, with each worker capped at 2 vCPU.
- Thirty identical 60-second 720p clips per scaling batch.
- Two workers at least 1.6× throughput. Three workers at least 2.1×.
- Falling queue wait and zero failed measured jobs.
- Fifty status clients for 180 seconds, p90 at most 700 ms, errors below 1%.
- Twenty separate login clients, p90 below 2 seconds.
- Worker failure visible within 300 seconds. Queue repair within 120 seconds.
- Independent Processing promotion and smoke within 600 seconds.

These are local measurements with recorded source identities.
They do not establish AWS performance, whole-host recovery, or cloud savings.
The local generator and VM shared one physical Mac.
Historical login results cover the cost-10 configuration, not existing cost-12 accounts.
Sonar analysis was skipped despite a successful wrapper job.

### Later experiments: both candidates rejected

**Issue 38:** three rotated pairs and 180 successful long jobs.
Extra PostgreSQL quota improved isolated status latency.
Isolated login and mixed status missed their gates.
The quota candidate was rejected. Baseline quotas remain.
Preparation-only 401 causes remain unresolved.

**Issue 39:** 48 eligible windows and 504 successful scheduled jobs.
Advance-planned manual windows reduced worker residency by 13.28%, 14.80%, and 14.58%.
These results missed the declared 20% requirement. Sustained status latency also failed.
The scheduling policy was rejected. Fixed worker counts remain the supported default.
Failed runs, a disk stop, and complete-arm continuations remain recorded.

Repeated worker loss, queue loss, full Redis reconstruction, and durable namespace restart passed.
A real 180-second source safely drained after more than 60 seconds of processing.
Promotion, failed-candidate restoration, and active rollback passed.
These results do not require adopting the rejected scheduling policy.

The original demo was restored at `https://localhost:54440` on saved `f10bf04` images.
Its images were not rebuilt to the latest Main.
Experiment namespaces stopped. Historical volumes and evidence were preserved.

Read [the experiment reports](docs/execution/experiments-20261014/README.md) and their raw indexes.
Preserve `.worktrees/final-measurements` and earlier failed evidence.
Do not repeat hours of local trials merely to plan AWS placement.

## 5. Reconsider EBS, snapshots, and the previous estimate

### The 128 GiB choice

The previous plan selected 32 GiB root plus 96 GiB data on a consolidated host.
It proposed storing database files, Redis AOF, Docker images, scratch files, logs, and backups there.
That quantity was a planning allowance. No measured capacity requirement justified the exact allocation.
It was not an original proposal requirement.

Recalculate storage after selecting the new topology.
Identify each state's owner, location, lifetime, and required durability.
Separate boot/image storage, active FFmpeg scratch, database metadata, queue transport, and media objects.
Source videos and completed outputs belong in private object storage.
Do not budget an additional local copy of the complete S3 corpus without a concrete reason.

The local VM retained MinIO data, old experiments, images, and failed runs.
Its disk usage does not determine AWS EBS requirements.
Price actual storage quantities and actual retention periods.

Measured fixture inputs:

- A 60-second source contains 21,050,412 bytes.
- Its combined outputs contain 60,959,567 bytes across 29 objects.
- A 2-second fixture's outputs contain 1,921,301 bytes across eight objects.
- The 504 scheduled jobs produced 22,222,111,464 output bytes across 11,592 objects.

These figures describe this fixture and encoding build.
They do not require keeping all experiment outputs on an EC2 disk.
Measure scratch concurrency and image sizes before selecting disk capacity.

### Retry, persistence, and backup serve different failures

Retry handles a failed processing attempt when authoritative state and the stored source survive.
For example, killing a worker should permit another attempt from the same source.
That failure does not require a volume snapshot.

Persistence retains accounts, ownership, Assets, Jobs, Attempts, and source references across process restarts.
Retry alone cannot recreate erased database ownership or missing source objects.
Redis is transport. The owned database ledger supports queue reconstruction.

A snapshot protects volume contents against volume loss or corruption.
The previous plan intended to protect database and host state, not restart an individual encoding job.
It also added snapshot retention and restore exercises beyond the proposal's three processing-failure scenarios.

Reconsider that additional scope.
Do not prescribe snapshots without stating the failure they address and the tolerated data loss.
If the demo accepts dataset recreation after catastrophic database loss, state that limitation explicitly.
If a small database export is sufficient, compare it with snapshots.
If durable data needs backups, explain the minimum policy and its cost.
Do not claim retries replace all durability. Do not treat snapshots as mandatory for retryable workers.

### Previous cost assumptions are under review

The old 100-host-hour worksheet total was USD162.42:

- USD35.28 main EC2 compute.
- Approximately USD57.14 in other AWS usage assumptions.
- USD20 domain/DNS allowance.
- USD25 tax/FX allowance.
- USD25 contingency.

It assumed 128 GB-month of EBS storage and another 128 GB-month of snapshot blocks.
It also assumed 100 GB-month of S3 storage, two million S3 requests, and 200 GB internet transfer.
A temporary load generator was another allowance.
These quantities were conservative ceilings, not a forecast from actual demo demand.
Verified rates do not validate those quantities or the selected architecture.

Read the [old worksheet](docs/execution/aws/cost-worksheet.json) as a historical input.
Build the replacement estimate from justified quantities.
Separate expected usage, optional resources, uncertainty, tax, and contingency.
The USD denomination and Singapore region were assumptions requiring confirmation.

## 6. Constraints that remain valid

- The budget ceiling is $200 total over approximately three weeks.
  It covers all cloud resources, retained storage, requests, transfer, and ancillary costs.
  Confirm the currency. Do not assume credits or free-tier eligibility.
- The actual project account, region, access, domain, and demo dates remain unconfirmed.
  Do not use another project's AWS account or credentials.
- No AWS resources were provisioned in this work. No AWS spending was recorded.
- Do not operate the inherited Alibaba deployment.
- Retain basic login, ownership, private data stores, HTTPS, and secrets outside Git/images.
- Security sophistication is not the grading priority.
  Do not add OIDC, a credential broker, or an elaborate identity platform.
  Ordinary scoped AWS permissions or native task roles can support the chosen design.
- Keep the existing test and fixable HIGH/CRITICAL image-scan gates.
- Kubernetes, autoscaling, and multi-zone/multi-region failover are outside the approved proposal scope.
  Managed containers or manually changed worker counts do not require those additions.
- The previous planner's blanket exclusions of managed databases and other AWS products are not user requirements.
  Evaluate suitable services when they simplify the design and fit the budget.
- Reuse the existing engine, frontend, contracts, Redis/RQ integration, and service implementation where practical.
  Do not replace the queue or rebuild the platform without a demonstrated need.
- Preserve original course/proposal documents and roadmap design/illustrations.
- The earlier target was three elapsed implementation days, five maximum.
  The proposal's 31 person-days is an effort allocation, not 31 elapsed coding days.
  State the remaining effort honestly. Do not invent a new implementation deadline.
- Use a capable model for architectural decisions.
  Use scripts or cheaper tool-capable execution for routine commands and waiting.
  Do not continuously spend high-reasoning model calls supervising unattended trials.

## 7. Required output from the next planning agent

1. Explain the original commitments and current implementation with source references.
   Distinguish logical service boundaries from physical resource and failure boundaries.
2. Recommend a cloud topology that demonstrates the intended service independence.
   Evaluate separate EC2 placements and managed container services where suitable.
   Select one recommendation based on the project evidence and budget.
   Do not restore the disputed shared-host default without resolving the user's objection.
3. Show logical and physical diagrams.
   Identify service images, private APIs, compute placement, database owners, queue ownership, and object storage.
4. Explain deployment, scaling, and fault isolation for each service.
   Processing deployment or worker changes must not rebuild or redeploy Media.
   Disclose shared database, network, or infrastructure failure boundaries.
5. Provide a state and storage inventory.
   Give every disk and backup a workload calculation and failure rationale.
   Remove unsupported capacities and optional backup scope from the default estimate.
6. Provide expected costs and a separate conservative ceiling.
   Use current official regional prices and realistic running hours, bytes, requests, and retention.
   Check supported compute CPU/memory combinations and image architecture.
   Include transfer, IPv4, network, registry, logs, and teardown costs when applicable.
   Keep reserves visible and separate. Staying below $200 is a constraint, not a spending target.
7. List the minimum code/configuration changes.
   Existing local tooling assumes localhost, MinIO, and local Docker control.
   Identify cloud endpoints, credential providers, service discovery, egress, TLS/CORS, release, and smoke adapters.
8. Define a focused AWS demonstration and acceptance plan.
   Trace independent release/scaling, durable source retry, ownership, and failure recovery to proposal scenarios.
   Preserve original numeric targets. Keep cloud measurements separate from local evidence.
9. Give the user a short list of required nonsecret inputs and a concrete implementation order.
   Obtain authorization for the actual account and priced resource plan before paid actions.

The desired result is a lean, defensible microservices deployment for this project.
It is not a production disaster-recovery programme or a plan to consume the budget.

## 8. Reference order and cautions

Read these sources in order:

1. This handoff and the latest user instruction.
2. [Team 17 proposal](project-documentation/Team17-Proposal.docx).
3. [Course briefing](project-documentation/briefing-requirements.txt) and
   [requirements/scope analysis](project-documentation/project-2-requirements-and-scope.txt).
4. [Root instructions](AGENTS.md) and [dated worklog](docs/project2-worklog.txt).
   Their older shared-host defaults are subject to the current replanning request.
5. [Architecture decisions](project-roadmap/design/04-architecture/README.md), contracts, current code, and local Compose.
6. [Local handoff](docs/execution/handoff.md), original acceptance packs, and the rejected experiment reports.
7. [Previous AWS plan](docs/execution/aws/architecture-plan.md),
   [preparation pack](docs/execution/aws/README.md), and old cost worksheet.
   Treat their hosting, storage, snapshot, hour, and blanket product choices as disputed assumptions.

Technical references:

- [AWS microservices guidance](https://docs.aws.amazon.com/whitepapers/latest/microservices-on-aws/microservices-on-aws.html)
- [AWS container deployment options](https://docs.aws.amazon.com/prescriptive-guidance/latest/modernization-net-applications/refactor-linux-micro.html)
- [EBS snapshot semantics](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-snapshots.html)

Historical design pages can still say “not implemented.”
Read those statements with their dates and compare them with current code and evidence.
Technical review PASS confirmed the reviewed source and calculations.
It did not approve the AWS plan on the user's behalf.

Do not provision, launch experiments, modify infrastructure, or hire more agents merely to read this handoff.
