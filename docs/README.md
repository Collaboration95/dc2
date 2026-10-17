# Documentation index

Start at the [root README](../README.md). Current documents first; everything under "Historical" is kept
for provenance, begins with a "Historical" banner (or sits under `docs/history/`), and is not a description
of V1.

## Current (as-built V1)

| Document | What it is |
|---|---|
| [`architecture/`](architecture/README.md) | DDD model, ADR register, deviations from the proposal, limitations, logical and physical views, persistence, upload-to-play sequence |
| [`api/`](api/) | OpenAPI documents of the Media and Processing public APIs |
| [`../contracts/README.md`](../contracts/README.md) | Queue message contracts and the versioning policy |
| [`execution/aws/architecture-plan.md`](execution/aws/architecture-plan.md) | The accepted V1 target and the optional V2 gate |
| [`execution/aws/v1/README.md`](execution/aws/v1/README.md) | V1 status, local runtime, runbooks |
| [`execution/aws/v1/deploy-runbook.md`](execution/aws/v1/deploy-runbook.md) | Deploy, session, release, teardown, CD workflow, operator handoff |
| [`execution/aws/v1/evidence/`](execution/aws/v1/evidence/) | Redacted live receipts (run `r1017b`) and image receipts |
| [`execution/aws/v2/`](execution/aws/v2/) | Opt-in V2 experiments, off by default, cloud evidence NOT_RUN |
| [`ci/`](ci/) | CI policy and measurements |
| [`project2-worklog.txt`](project2-worklog.txt) | Running log of decisions and status |
| `evidence-index.md` | Quality scenarios against targets (in progress, pending the `r1018a` session) |

## Historical

| Document or folder | Superseded by |
|---|---|
| [`history/`](history/) | Old root README, root hand-off briefs |
| `sprint1-*`, `sprint2-*`, `a-worker.md`, `c-recovery-input-safety.md`, `contract.md`, `known-traps.md`, `proposal.md`, `s2-03-auth-design.md`, `scaling-notes.md` (Project 1) | [`architecture/`](architecture/README.md) |
| `processing-intake.txt`, `lean-aws-microservices.drawio` | [`architecture/`](architecture/README.md) |
| [`execution/`](execution/) top level (`plan.md`, `handoff.md`, `decisions.md`, `interfaces.md`, `issue-map.md`, `backlog.json`, `progress.json`, `issues/`, `reviews/`, `evidence/`, `performance-20261013/`, `experiments-20261014/`) | Pre-AWS local delivery record; [`execution/aws/v1/`](execution/aws/v1/README.md) |
| [`execution/aws/prep/`](execution/aws/prep/README.md), [`execution/aws/readiness/`](execution/aws/readiness/README.md) | AWS2 preparation and readiness packets; [`execution/aws/v1/`](execution/aws/v1/README.md) |
| `execution/aws/architecture-plan-20261014.md`, `architecture-plan-aws2-prep-20261015.md`, `README-20261014.md`, `cost-worksheet-20261014.json`, `pricing-*.json`, `job-inputs-20261014.template.json` | [`execution/aws/architecture-plan.md`](execution/aws/architecture-plan.md) |
