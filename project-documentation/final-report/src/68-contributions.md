## Member Contributions and Lessons Learned

### What Team 17 Contributed beyond the Inherited Baseline

Project 2 changed how FlickPond is structured, deployed and reused. FFmpeg processing, HLS
output, worker replicas and basic CI came from Project 1. Team 17's contribution is the platform
built around those capabilities:

- **Two bounded contexts with owned data.** Media Management and Processing have separate
  domain models, databases, migration histories, runtime roles, images and release units
  (Logical Architecture & Design; Platform Design).
- **Durable asynchronous integration.** Local outbox/inbox transactions, SQS, version-fenced
  projections and SQL-driven repair let Media accept work while Processing consumption is
  unavailable (Availability; DP-2).
- **An independent second client.** Publisher uses the public HTTP contract without service
  imports or database credentials (Extensibility and Maintainability; UC-5).
- **Managed cloud execution with bounded capacity.** Domain handlers run on Lambda, standard
  encoders run as finite Fargate tasks and eligible short encodes use a separate Lambda lane.
  Idle compute can return to zero (Physical Architecture & Design; UC-6).
- **Per-owner delivery and recovery.** Immutable image evidence, candidate and retained-image
  scans, owner readiness checks and a durable release journal support independent promotion
  and checked restore (Continuous Delivery; UC-7; DP-1).
- **Reproducible engineering evidence.** Tests, CI artifacts and sanitized cloud receipts connect
  design claims to dated results and retain the proposal's original targets (Quality Attributes;
  Evidence and How to Reproduce It below).

### Per-Member Contribution Summary

The summaries follow the proposal's work packages and the team-agreed specialisms in
`project-documentation/effort-ledger.md`. Each member led one area and reviewed the other two.
The use-case and design-problem allocations state responsibility for analysis and design;
Project Plan and the Design Problems and Patterns introduction record the complete allocation.

#### Guruprasath Gopal

Guruprasath led cloud and delivery, taking the reproducible baseline through AWS deployment,
CI quality gates, per-owner releases and release freeze. His work connects the proposal's
independent-capacity and repeatable-release goals to the deployed runtime and its operator tools.
He is responsible for the analysis and design of UC-6, UC-7 and DP-1.

- Led work packages 1 and 7: baseline reproducibility, the inherited scan repair, CloudFormation,
  Lambda, Fargate, Aurora, S3, CloudFront, image scanning and the deploy/release/restore workflow.
- Led delivery and Aurora-pause repairs during integration, and coordinated the release freeze
  and its recorded image/runtime identities.
- Developed the capacity and release analysis for **UC-6 Scale processing capacity independently**,
  **UC-7 Release Processing on its own and demonstrate rollback**, and **DP-1 Bounded cloud
  capacity and safe per-owner release**.
- Contributed to the progress report, presentation and final report, with cloud/delivery review
  of the other specialisms.

#### Ibrahim Mammadov

Ibrahim led the backend service work: extracting Processing's execution model and persistence,
adapting Media's owned-asset workflow, and enforcing security at the service and storage
boundaries. His work turns the proposal's service split into durable acceptance, execution and
retry behavior. He is responsible for the analysis and design of UC-1, UC-2, UC-4 and DP-2.

- Led work packages 3 and 4: Processing's database, migrations, worker and recovery; Media's
  asset records, integration, web routes and retry flow.
- Led the boundary-security implementation recorded in the effort ledger, including owner
  checks, database-role separation, presigned storage access and negative tests.
- Developed the analysis and design of **UC-1 Register, log in and upload an owned video**,
  **UC-2 Process the video into playable outputs**, **UC-4 Retry from the stored source**, and
  **DP-2 Durable asynchronous Processing handoff**.
- Contributed backend integration, design explanations and verification evidence to the
  progress report, presentation and final report, and reviewed the other specialisms.

#### Nguyễn Kim Long

Long led domain analysis, contracts and verification. He defined the service vocabulary and
public interfaces, built the independent Publisher client and organized experiments that connect
the proposal's goals to observed outcomes. He is responsible for the analysis and design of
UC-3, UC-5 and DP-3.

- Led work packages 2 and 6: DDD, service contracts, OpenAPI documents, Publisher and its
  contract tests.
- Led work package 8: scaling, load, recovery and playback experiments and their raw results;
  contributed the queue-drain re-test during integration.
- Developed the analysis and design of **UC-3 Track status and play the result**, **UC-5
  Bulk-publish a folder and report results**, and **DP-3 Trusted owner identity and reusable
  public contract**.
- Maintained the evidence index and release-freeze documentation; contributed to the progress
  report, presentation and final report, and reviewed the other specialisms.

### Lessons Learned

1. **Commit intent before external effects.** Adopting the outbox/inbox early made the SQL-to-SQS
   boundary explicit. Treat response loss, duplicate delivery and repair as normal protocol paths.
2. **Measure startup separately from execution.** Scale-to-zero reduces idle compute but adds
   database resume, image initialization and task-start latency. Separate these stages before
   choosing an encoding lane or changing capacity.
3. **Verify idle behavior.** Activity markers and cleanup backoff allow Aurora to pause without
   routine repair waking it unnecessarily. Returning to zero is an observable requirement.
4. **Test delivery as application logic.** Durable intent, immutable identities, additive
   migrations and focused smoke checks make interrupted releases recoverable. A separate
   upload-to-playback smoke verifies the completed workflow after owner readiness.
5. **Retain evidence through change.** Rescan candidates and rollback targets, bind reports to
   their source and scope, and keep original acceptance targets so later fixes remain comparable.

### Evidence and How to Reproduce It

The repository retains the inputs and receipts behind the report. Local runs exercise code and
emulated cloud ports; dated AWS receipts record the cloud scenarios. The deployment endpoints
below identify the demonstration environment; its planned teardown is after 16 November 2026.

| Evidence | Location or reproduction command |
|:---------|:---------------------------------|
| Architecture decisions, domain model, views and use-case catalogue | `docs/architecture/decisions.md`, `docs/architecture/ddd.md`, `docs/architecture/views.md`, `docs/architecture/use-case-design.md` |
| Proposal and work-package allocation | `project-documentation/Team17-Proposal.docx`; `project-documentation/effort-ledger.md` |
| Results against original targets | `docs/results/actual-vs-target.md`; regenerate the summary with `python scripts/dev/results_summary.py` |
| Scenario-by-scenario evidence index | `docs/evidence-index.md` |
| Sanitized cloud receipts | `docs/execution/aws/v1/evidence/`, `docs/results/engineering-20261020/`, `docs/results/engineering-20261021/` |
| Release identity and engineering handoff | `docs/release/demo-release-manifest.md`, `docs/release/engineering-handoff.md` |
| Deployment and DLQ procedures | `docs/execution/aws/v1/deploy-runbook.md`, `docs/execution/aws/v1/dlq-runbook.md` |
| Public study guide | <https://collaboration95.github.io/dc2/> |
| Local demonstration | `make setup-v1`, then `make v1-up V1_RUN_ID=demo1`, then `make v1-demo V1_RUN_ID=demo1 OPEN=1` |
| Static checks and fast tests | `make lint`, `make format-check`, `make test`; frontend: `cd frontend && npm ci && npm test` |
| Real-dependency V1 flows | With the local namespace running: `make verify-v1 V1_RUN_ID=demo1 FLOW=all` |
| Added native-recovery and launcher unit suites | PR #327: `tests/media/test_native_recovery.py`, `tests/processing/test_launcher_tick.py`; test inventory in Extensibility and Maintainability |
| Added advisory scanner workflow and summaries | PR #328: `.github/workflows/security-scans.yml`, `scripts/ci/SECURITY_SCANS.md`; pip-audit runtime-dependency audit and Checkov rendered-template scan |
| Demonstration deployment addresses | Frontend: `https://d1e1dpefd6hp9x.cloudfront.net`; API: `https://nqxf2hclhi.execute-api.ap-southeast-1.amazonaws.com` |
| Report sources and build instructions | `project-documentation/final-report/src/`; `project-documentation/final-report/README.md` |

### AI Tool Declaration

The team used AI coding and writing assistants: Anthropic Claude models through Claude Code,
and OpenAI GPT models for independent review. They supported code and test generation,
refactoring, pull-request review, documentation drafting and proofreading, diagram production,
and execution and recording of verification steps under the team's direction.

Engineering results in this report come from retained tests, CI artifacts and cloud receipts.
The team reviewed the outputs and is responsible for the content and quality of the submitted work.
