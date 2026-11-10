# A3 — Code, tests and CI gap audit

Date: 10 November 2026, Singapore time. Repository: `dc2-report`, branch `dev/report-v1.1`, HEAD `a8c8072b667a039923563ac2612dedc7e7a54ce8`. Remote Main was `76282d3b5a141f6548056f2506f9d5aff0742692` when checked. All 467 changed paths between that Main commit and this HEAD are under `project-documentation/presentation/`; application code, tests and workflows match Main. Line citations below refer to the audited HEAD, not an assumed live deployment.

Scope: read-only audit, with this requested findings file as the sole repository output. No checkout, switch, commit, push, workflow dispatch, GitHub-setting mutation, AWS access or deployment. GitHub configuration and run metadata were read through authenticated `gh` CLI. Existing Python dependencies were reused without installation. Started with `README.md` and `docs/architecture/`; treated the feedback and change plan as questions to verify, not implementation evidence.

## 1. Decision summary

Most assessor remarks can already be answered truthfully from existing implementation. The important corrections are:

- **API Gateway has a Media-owned Lambda REQUEST authorizer.** JWT verification occurs inside that separate authorizer Lambda; Media additionally revalidates identity inside its API. This is neither an API-only authentication scheme nor a managed Gateway JWT authorizer.
- **Edit and upload acceptance stage durable SQL outbox intent.** A separate repair/relay publishes to SQS. Processing then stages its own result/work outboxes.
- **There is no ALB.** Gateway integrates directly with Lambda aliases, and finite Fargate workers consume queues. Explain HTTP invocation distribution separately from queue dispatch and capacity control.
- **PostgreSQL with JSONB is the business authority; S3 holds video objects.** No active DynamoDB or MongoDB implementation was found. A migration is not a report fix.
- **Ruff security rules, independent managed CodeQL, npm audit, gitleaks, Trivy, cfn-lint and local-stack ZAP already exist.** Adding gitleaks, coverage collection, or a second local ZAP workflow would duplicate existing controls.
- **Workflow gates are not merge enforcement.** Main is unprotected, repository rulesets are empty, and the `aws` environment has branch restrictions but no reviewer approval rule. This is the largest governance gap.
- **1,316 offline cases passed in this audit**, across two runs; two additional cases were explicitly skipped, and integration/e2e cases were deselected. This is not full-suite, frontend, coverage, hosted CI or AWS acceptance.

The consolidated plan already anticipates many of these distinctions: `project-documentation/presentation/feedback-20261026/REPORT-CHANGES.md:110`, `:118`, `:208`, `:220`, `:360`, `:372`. The actual criticisms are in `project-documentation/presentation/feedback-20261026/FEEDBACK.md:6–42`. Small code/CI additions remain proposals below; none was implemented in this audit.

## 2. Remarks (a)–(f): as-is implementation

### (a) “Authorizer tied to API Gateway”

**As-is: yes, a Lambda authorizer is attached to Gateway.** The generator creates `GatewayAuthorizer` as `ApiGatewayV2::Authorizer`, type `REQUEST`, payload format `2.0`, simple responses enabled, Cookie identity source and cache TTL zero. Its URI invokes `MediaAuthorizerAlias`. Protected proxy/root routes use `AuthorizationType: CUSTOM` plus `AuthorizerId`; health and Media register/login/logout use `NONE`. See `scripts/aws/v1/definitions.py:1530–1556`, `:1602–1621`.

The deployment handler map points `MediaAuthorizer` at `media.lambda_handler.authorizer` (`scripts/aws/v1/definitions.py:284–286`), which reexports `media.authorizer.handler` (`media/lambda_handler.py:3–4`). `authorize()` decodes the session JWT, reads the current Media `User`, maps the current role to the contract Actor, and fails closed (`media/authorizer.py:13–20`, `:40–61`). Gateway invocation permission is scoped to the API authorizer ARN, with source account restrictions (`scripts/aws/v1/definitions.py:1547–1556`).

The API is a separate invocation. The adapter removes caller-provided owner/role/cookie headers and reconstructs cookies from the Gateway event (`contracts/gateway.py:48–67`). Media checks the cookie/current User again and compares it to Actor (`media/api/deps.py:16–39`); Processing accepts only adapter-injected Actor context (`processing/auth.py:6–17`). Processing therefore has a synchronous authentication dependency on Media's authorizer and User lookup, even though business commands/results are asynchronous.

**Report wording:** “API Gateway invokes a Media-owned Lambda REQUEST authorizer before protected API integrations. The authorizer verifies the session JWT and current user; Media also revalidates the request identity.” Do not call this a native Gateway JWT authorizer. TTL zero does not revoke a request already executing. Existing tests cover current role/deleted users and repeated authorization decisions (`tests/media/test_lambda_boundary.py:145–176`). No auth architecture change is needed.

### (b) “We don't directly go to SQS when the video is edited”

**Correct: API acceptance writes local SQL intent; publication is separate.** The edit route delegates to `v1_lifecycle.edit()` (`media/api/v1_jobs.py:55–66`). The implementation:

1. Checks replay, ownership and completed parent output (`media/services/v1_lifecycle.py:105–116`).
2. Reserves a staged source key, copies the parent's primary output, and records the copy outcome (`:120–143`).
3. In the adoption transaction, inserts the derived Asset, pins the immutable source, records any request key, stages submit intent, and removes the stage ledger (`:145–169`).
4. `stage_submit()` builds a stable submit identity; `stage_command()` writes `MediaOutbox` for `processing-commands` (`media/services/v1_lifecycle.py:17–47`; `media/messaging.py:9–13`).
5. `MediaRepair` constructs the SQS transport and calls `publish_commands()` (`media/handlers.py:58–73`; `media/messaging.py:27–28`). Shared `publish_due()` reserves and commits a SQL claim, sends outside that transaction, then fences its acknowledgement in a new transaction (`delivery/sql.py:58–116`). The actual native send is `client.send_message` (`delivery/sqs.py:61–70`).

Direct upload follows **reserve → client S3 upload → finalize verification → Asset + outbox commit**, not an S3 event directly creating the encode job. Finalize verifies the uploaded version outside the adoption transaction, rechecks the reservation under lock, and stages enqueue within adoption (`media/services/direct_intake.py:149–203`). Processing consumes the command in an owned transaction and stages result/work intent (`processing/messaging.py:232–305`, `:102–122`); its relay uses the same publisher (`:446–447`). Processing may publish immediately after its command transaction commits, within the same Lambda invocation; an outage leaves the outbox for repair (`processing/handlers.py:52–63`). Do not draw this as an SQS send inside the SQL transaction.

**Report wording:** “Edit acceptance atomically adopts the derived source and command outbox row. A later Media relay publishes to the Processing command queue; Processing commits job state and its own work/result outboxes.” This is at-least-once delivery with deduplication/fences, not a SQL/SQS transaction or exactly-once transport. Existing atomic-adoption/replay and lost-copy tests: `tests/media/test_direct_intake.py:104`, `:320`; `tests/media/test_v1_projection.py:191`, `:249`, `:264`. Real-SQL rollback/lost-send tests exist separately (`tests/v1/test_media_messaging_sql.py:44`; `tests/v1/test_messaging_sql.py:196`). Fix the sequence explanation; preserve the implementation.

### (c) “Physical architecture doesn't do load balancing”

**As-is: no ALB or ECS HTTP target group.** CloudFront serves the frontend from S3 and forwards `/api/*` to the HTTP API (`scripts/aws/v1/definitions.py:1642–1698`). Gateway has route throttles and two `AWS_PROXY` integrations targeting Media/Processing Lambda aliases (`:1506–1525`, `:1560–1584`). The template does not create an ECS HTTP service or load balancer; the standard encoder is a finite task launched through `ecs.run_task()` (`processing/launcher_aws.py:81–93`), then long-polls SQS (`delivery/sqs.py:73–85`; `processing/worker/sqs.py:233–378`).

There are three mechanisms to explain:

- **HTTP:** Gateway selects the service integration, and Lambda handles concurrent invocations. CloudFront supplies edge delivery; it is not a depicted ALB distributing requests across encoder containers. `/api/*` uses the API cache policy configured at `scripts/aws/v1/definitions.py:1695–1698`; do not imply per-user API results are served from a shared video cache.
- **Message consumption:** command/result Lambda mappings have bounded concurrency and partial batch failures (`scripts/aws/v1/definitions.py:1270–1283`). The short-encoder mapping has batch size one and maximum concurrency two (`:1286–1298`).
- **Standard encoding capacity:** the custom launcher reconciles SQL backlog, visible queue demand, live tasks and pending reservations, then reserves capacity under a lock before RunTask (`processing/launcher.py:238–334`, `:379–407`). Standard cap is three; short Lambda has a separate cap of two (`processing/short_lane.py:65–70`). Database connections, account limits, queue age and cold/resume latency still constrain throughput.

**Assessment:** primarily an explanation/diagram issue. An ALB would be relevant to a different design with HTTP-serving ECS tasks. It would not replace the encoder's queue capacity policy. Keep “no ALB” explicit and avoid claiming a measured load-balancer comparison or unbounded scaling. The execute-api endpoint is not disabled in the API declaration (`scripts/aws/v1/definitions.py:1500–1504`), so CloudFront is the normal entry, not an enforced sole entry. No topology change is a low-risk quick win.

### (d) “You might as well use NoSQL like Mongo”

**As-is: Aurora PostgreSQL Serverless v2, SQLAlchemy models and owned migrations.** The renderer supports shared, separate and cloned/split database layouts; the cluster is `aurora-postgresql` with serverless capacity settings (`scripts/aws/v1/definitions.py:490–546`). Live CD selects the split-database feature for environment `live` (`.github/workflows/cd.yml:105–107`). This is source configuration, not verification of today's AWS inventory.

Media has User/Asset/RequestKey relationships and uniqueness; variable edit operations are JSONB (`media/models.py:26–69`). Processing stores source/operations/outputs as JSONB while retaining Job/Attempt foreign keys, unique attempt numbers and state checks (`processing/models.py:15–71`). Inbox/outbox identity, due-time indexing and publication claims are relational (`media/messaging_models.py:13–33`; `delivery/sql.py:18–55`, `:77–115`). Lease decisions use database time and row locks (`processing/lifecycle.py:136–150`; `processing/messaging.py:421–442`). Video bytes remain object-store data.

A case-insensitive search of active service/shared packages, AWS scripts/templates and all six workflows found **no DynamoDB/MongoDB client, resource or persistence implementation**. Do not confuse historical/proposed discussion with use of either store.

**Report response:** document access patterns and consistency requirements: atomic domain/inbox/outbox changes, duplicate identity rejection, owner filtering, DB-clock leases, due-work queries and flexible JSONB descriptors. MongoDB/DynamoDB are alternatives to evaluate, not incapable of implementing reliable workflows. No comparative database benchmark was found or performed. Retain PostgreSQL for v1.1; migration, dual-write or a new read projection needs a separate design and recovery plan.

### (e) “I didn't see your SAST and DAST in your pipeline”

#### Actual tool inventory

“Blocking” below means a workflow job/aggregate fails when selected. **None is an enforced Main merge prerequisite under the GitHub settings observed in section 3.** SARIF upload actions are publication, not CodeQL analysis or evidence that findings are clean.

| Tool/control | Workflow and job | Actual scope and failure policy | Evidence |
|---|---|---|---|
| Ruff + Ruff S rules | `ci.yml` → `lint-and-unit` | General lint/format; separate `--select S` over current runtime packages except inherited `app`, plus bootstrap. Findings fail lint. S is Bandit-derived rules, not a standalone Bandit run. | `.github/workflows/ci.yml:96–140`; `scripts/dev/checks.py:188–218` |
| CodeQL default setup | GitHub-managed **CodeQL**, outside the six checked-in workflows | Independent Python, JavaScript/TypeScript and Actions analysis. Not a `needs` dependency of Full verification, and no severity-based code-scanning merge rule was present. A `codeql-action/upload-sarif` step alone is not this analyzer. | Managed configuration and current run checked through `gh`; section 3 |
| SonarCloud | `ci.yml` → `sonar-config`, `sast`, `sast-full` | Conditional on token/project/org configuration. Source-only dev analysis; full analysis consumes coverage. Advisory submission, `qualitygate.wait=false`; not in Full verification. Both analysis jobs were skipped in the audited successful 1 November full run. | `.github/workflows/ci.yml:763–817`, `:846–877`; section 3 |
| npm audit | `ci.yml` → `frontend` | Locked frontend test-tool dependencies; `npm audit --audit-level=high` fails the selected job at high/critical severity. Frontend has devDependencies and ships plain JS; do not describe every scanned package as shipped runtime code. | `.github/workflows/ci.yml:143–160`; `frontend/package.json:6–21` |
| Python source dependency audit | **No standalone pip-audit invocation** | No Semgrep, Bandit or pip-audit invocation found in the workflow/dev/CI runners searched. Python packages are scanned in built images by Trivy, so this is a source-level SCA visibility/feedback gap, not zero Python dependency scanning. | `.github/workflows/ci.yml:638–707`; `.github/workflows/v1.yml:211–242`; `pyproject.toml:11–77` |
| gitleaks | `ci.yml` → `secret-scan` | Unconditional full-history scan, pinned binary and checksum, `.gitleaks.toml` allowlist; redacted log/SARIF. Findings fail; both aggregates require it. Already implemented. | `.github/workflows/ci.yml:722–761`; `scripts/ci/policy.py:32`, `:406–416` |
| Trivy, inherited images | `ci.yml` → `security` matrix | Builds inherited app, Media and Processing images according to selection. Fixable HIGH/CRITICAL fail (`ignore-unfixed: true`). Does not attest the separate Lambda/finite-worker artifacts. | `.github/workflows/ci.yml:638–720` |
| Trivy, current V1 images | `v1.yml` → `images`, called by `ci.yml` → `v1-local` | Scans exact Media, Processing and Worker images. Scan steps use exit zero so reports survive; **the following `scripts.ci.v1_scan` step enforces zero fixable HIGH/CRITICAL and source/config-ID matching**. Unfixed findings remain reported. | `.github/workflows/v1.yml:194–258`; `scripts/ci/v1_scan.py:1–12`, `:72–90`, `:146–191` |
| Trivy, selected-owner preparation | `aws-prep.yml` → `prepare` | Manual workflow for inherited owner Dockerfiles; exact config-ID hard gate on fixable HIGH/CRITICAL. Offline artifact execution, not live deployment and not an automatic Main CI job. | `.github/workflows/aws-prep.yml:3–10`, `:45–68`, `:97–101` |
| Trivy + ECR policy, CD | `cd.yml` → `run`, through `scripts/ci/cd.sh` | Separate release/deploy admission: scan candidate config IDs and retained/resumed image digests. Trivy process/report validation plus strict candidate findings policy; a narrow retained-baseline exception exists only for replaced images. ECR completed-scan policy is another admission check. Not run in this audit. | `.github/workflows/cd.yml:189–194`; `scripts/ci/cd.sh:175–230`, `:471–490`; `scripts/aws/v1/artifacts.py:60–135` |
| cfn-lint | `v1.yml` → `v1-offline` | Required structural/resource-schema lint of generated shared/separate/split CloudFormation, plus snapshot freshness. Genuine IaC lint, but no dedicated Checkov/tfsec/cfn-nag security policy scan found. | `.github/workflows/v1.yml:62–73`; `scripts/aws/v1/lint.py:35–73` |
| OWASP ZAP | `ci.yml` → `dast` → `dast.yml` → `dast` | Authenticated scan of disposable local V1 stack on the hosted Actions runner. Selected/full CI, weekly Monday schedule, or exact-source dispatch. Scanner execution, route coverage and cleanup failures fail; vulnerability findings are report-only. Already CI-integrated. | `.github/workflows/ci.yml:627–636`; `.github/workflows/dast.yml:3–18`, `:42–101`; `scripts/dev/v1_dast.py:611–629`, `:765–767` |
| Showcase validation | `showcase-pages.yml` → `build` / `deploy` | Static study-guide link/exclusion validation and GitHub Pages publication. No application SAST/SCA/DAST security scanner in this workflow. | `.github/workflows/showcase-pages.yml:22–62` |

#### CI selection and the meaning of a green gate

`ci.yml` triggers Main pushes, PRs, exact-source dispatch and a weekly full run (`.github/workflows/ci.yml:3–15`). PRs targeting `dev/closeout` may use selective dev policy; other PR bases, Main pushes and schedules use full verification (`scripts/ci/policy.py:387–403`). Workflow/lock/dependency changes force full selection (`:213–220`); full mode selects every lane (`:352–354`).

`Dev gate` requires selected dev jobs plus gitleaks (`.github/workflows/ci.yml:171–183`); the dev aggregate excludes security, DAST and combined coverage (`scripts/ci/policy.py:417–419`). Those selected jobs may still make the overall workflow fail independently. `Full verification` depends on security, DAST, V1 and coverage and validates selected checks (`.github/workflows/ci.yml:596–625`). CodeQL and Sonar are outside that custom aggregate.

#### DAST target and limits

This is **GitHub-hosted execution against a locally started stack**, not “DAST only run manually on a laptop.” The workflow starts PostgreSQL and Moto S3/SQS and scans the actual API handlers through the loopback Gateway/authorizer bridge (`.github/workflows/dast.yml:58–79`). It explicitly records cloud scan `NOT_RUN`.

The active subset is seven GET operations: Media `/api/media/auth/me`, `/api/media/health`, `/api/media/jobs`, `/api/media/jobs/{job_id}`; Processing `/api/processing/health`, `/api/processing/jobs`, `/api/processing/jobs/{job_id}`. The inventory excludes auth lifecycle POSTs, upload grants/adoption, HLS, admin and other mutation routes (`scripts/dev/v1_dast.py:34–88`). Limits: 1,600 forwarded requests, two fixture users/uploads, zero worker invocations, bounded scanner runtime (`:34–48`). Every imported route must have a successful response; in-scope auth denials or request-cap exhaustion fail (`:611–629`). Findings are sanitized and retained for 14 days, with best-effort code-scanning publication (`.github/workflows/dast.yml:80–101`). Direct ownership-negative fixture tests are not active-scan coverage of excluded operations.

**Report wording:** “CI includes source security lint, independent managed CodeQL, dependency/secret/image checks and authenticated ZAP against an isolated local stack. Findings and execution gates differ; deployed Gateway/CloudFront/IAM DAST remains unverified.” Do not write “Sonar passed,” “all scanner findings block merge,” “all endpoints scanned,” or “AWS DAST passed.”

### (f) “How do we decide Lambda or Fargate; where is the decision made?”

**The choice is Processing code, in two stages; it is not an API Gateway routing rule.**

1. **Dispatch:** `processing.messaging.emit_state()` stages queued work to the return value of `short_lane.work_lane()` inside Processing's transaction (`processing/messaging.py:102–122`). `work_lane()` chooses standard unless the feature flag is true, source size is a positive integer ≤64 MiB, and the job has not previously run on Lambda (`processing/short_lane.py:81–130`). Queue names are `processing-work` and `processing-work-short` (`:23–24`). At this point duration/height have not been probed.
2. **Executor admission:** short Lambda passes `check_probe` into the worker pipeline (`processing/short_encoder.py:54–101`). The pipeline downloads and probes before invoking admission (`processing/worker/tasks.py:16–27`). The bounds are duration ≤60 s, finite/positive, and height ≤1080 (`processing/short_lane.py:37–45`, `:94–100`).
3. **Fallback:** a rejected probe causes a fenced redirect: abandon the claimed short attempt, record cleanup intent, create a successor, and emit new work. The prior `lambda-` attempt binding makes the successor stick to the standard lane (`processing/messaging.py:412–443`; `processing/short_lane.py:103–130`). Lambda failure/retry also stays on standard. There is a transport fallback if a short queue is removed (`delivery/sqs.py:30–32`, `:61–70`).
4. **Execution/capacity:** the short queue's event mapping invokes the short encoder; the standard queue is read by finite Fargate tasks. The custom launcher decides how many standard tasks to reserve, not which lane a new video qualifies for (`scripts/aws/v1/definitions.py:1286–1298`; `processing/launcher.py:255–305`, `:379–407`).

The feature defaults off in code and is conditional in infrastructure. Inspecting source does not prove the deployed flag is on. Existing unit tests exercise inclusive size/duration/height limits, disabled routing and sticky fallback (`tests/processing/test_short_lane.py:34–94`, `:126–159`); short execution/redirect/lease-loss unit tests are in `tests/processing/test_short_encoder.py:92–216`. Real-SQL handoff/concurrency tests are explicitly integration-marked (`tests/v1/test_short_encoder_sql.py:42`, `:159–343`). Expose this existing decision in the report; do not move it or change thresholds.

## 3. Merge/deployment enforcement and dated hosted evidence

Read-only GitHub observations made during this audit:

| Check | Observed result | How checked |
|---|---|---|
| Main classic branch protection | HTTP 404 “Branch not protected”; branch metadata also `protected:false` | `gh api repos/Collaboration95/dc2/branches/Main/protection`; `gh api repos/Collaboration95/dc2/branches/Main` |
| Repository rulesets | Empty list | `gh api repos/Collaboration95/dc2/rulesets` |
| `aws` environment | `protection_rules` contains only branch policy; no required reviewers or wait timer; admins can bypass | `gh api repos/Collaboration95/dc2/environments/aws` |
| Allowed AWS deployment branches | `Main`, `dev/closeout` | `gh api repos/Collaboration95/dc2/environments/aws/deployment-branch-policies` |
| CodeQL default setup | Configured; default suite, remote threat model, weekly schedule; Actions and Python plus JS/TS language identifiers | `gh api repos/Collaboration95/dc2/code-scanning/default-setup` |

Therefore scanner job failures **do not by themselves stop direct Main pushes or enforce PR merging**. CD separately refuses an unsuccessful/non-full/wrong-source CI attempt and requires a successful `Full verification` job (`scripts/ci/cd_gate.py:16–48`). `environment: aws` in YAML is a reference to settings, not evidence of human approval (`.github/workflows/cd.yml:163–168`).

Useful dated receipts, read using `gh run list/view`:

- [CodeQL run 42836019562](https://github.com/Collaboration95/dc2/actions/runs/42836019562), 10 November, audited HEAD `a8c8072…`: successful `Analyze (python)`, `Analyze (javascript-typescript)` and `Analyze (actions)`. Analyzer completion does not establish zero open alerts; alerts were not enumerated.
- [DAST run 42602649917](https://github.com/Collaboration95/dc2/actions/runs/42602649917), 9 November, Main `76282d3…`: scheduled local-API DAST job succeeded. This supports hosted scanner execution, not AWS-edge coverage or a clean findings policy.
- [CI run 41294802851](https://github.com/Collaboration95/dc2/actions/runs/41294802851), 1 November, Main `76282d3…`: full verification, coverage, gitleaks, inherited image scans and CI-invoked DAST succeeded; both Sonar analysis jobs were skipped.
- [CI run 42468024855](https://github.com/Collaboration95/dc2/actions/runs/42468024855), 8 November, the same Main SHA: **failed**. Job/log inspection showed repeated HTTP 504 setup/download failures, including pinned gitleaks installation and Python setup. Missing built images then caused additional V1 scan failures; combined coverage was skipped. Do not re-label this as an application test failure, vulnerability finding, or a clean scan. It is a real failed CI receipt.
- [CI run 42836023834](https://github.com/Collaboration95/dc2/actions/runs/42836023834), audited report HEAD: still unfinished in the metadata snapshot taken during research. No final result is claimed here. The separate Showcase failure on that HEAD was outside this code audit's scope.

These are snapshots, not monitoring. No hosted workflow was started or rerun. No current AWS state, deployed image identity, playback, scaling, or remediation success was checked.

## 4. Complex modules/classes and unit-test evidence (g)

### Method

Prioritized active runtime modules by an AST decision-site heuristic: count `if`, loops, exception handlers, conditional expressions, comprehensions and Boolean operators, excluding migrations. This identifies review hotspots; it is **not a formal cyclomatic complexity or maintainability score**. Media's top modules were projections, direct intake, Storage and native recovery; Processing's were launcher, messaging, SQS worker and lifecycle. Many complex behaviors are module functions, while ORM/DTO classes mainly represent state. Do not invent large domain classes to satisfy the wording “complex classes.”

| Owner / hotspot | What is complex | Unit evidence and material limit |
|---|---|---|
| Media `projections.py` (270 lines, 86 decision sites); `ProjectedJob` | Projection identity/version/attempt fences and cancellation (`media/projections.py:21`, `:36`, `:69`, `:139`) | Direct unit tests for reordering, terminal fences, ownership and edit adoption (`tests/media/test_v1_projection.py:84–130`, `:191–264`). Model shape alone is not the complex behavior. |
| Media `direct_intake.py` (297 lines, 41 sites); Reserve/Finalize request models | Reservation replay, version verification, atomic adoption, late-write cleanup (`media/services/direct_intake.py:22`, `:99`, `:149`, `:234`) | 26 test definitions; expiry race, lost commit reply, invalid source version, storage failure and cleanup backoff (`tests/media/test_direct_intake.py:104`, `:153`, `:207`, `:320`, `:416–500`). Uses storage/session doubles; SQL integration remains separate. |
| Media `Storage` (253 lines, 40 sites) | Streaming verification, signing, copy, version-scoped removal (`media/services/storage.py:23`, `:62`, `:145`, `:209`) | Unit coverage in `tests/media/test_media_storage.py:21`, `:64`, `:119–139` and native-source tests at `tests/media/test_direct_intake.py:199–252`. These are not live IAM/S3 evidence. |
| Media native recovery (241 lines, 34 sites) | Tombstone and staged-object cleanup, due-time authority (`media/recovery_v1.py:39`, `:119`, `:181`, `:218`) | Strong **integration** cases exist (`tests/v1/test_media_cleanup_sql.py:29`, `:178`, `:431`, `:565–677`); no dedicated direct unit suite for native cleanup orchestration was found. `tests/media/test_api_recovery.py:12–15` imports legacy recovery routes; do not cite it as proof of all native recovery branches. Good targeted quick win. |
| Media `v1_lifecycle.edit` | Copy/adoption/replay error ordering (`media/services/v1_lifecycle.py:105–179`) | Native edit unit cases in `tests/media/test_v1_projection.py:191`, `:249`, `:264`. Some `test_media_lifecycle.py` cases exercise the legacy peer path; distinguish that provenance. |
| Processing launcher (462 lines, 87 sites); `LauncherConfig`, `Observation`, reservations | Lock-protected cap/demand decisions and ambiguous ECS outcomes (`processing/launcher.py:47`, `:128`, `:238`, `:337`) | Offline config, IAM-shape, observe, ECS adapter and queue-depth tests already exist (`tests/aws/v1/test_unattended_launch.py:451–617`); 44 cases passed in this audit. SQL cap/concurrency/restart tests are **integration** (`tests/v1/test_launcher_sql.py:28`, `:261–294`, `:567–604`). Do not say “launcher has no unit tests.” A narrow `tick()` orchestration unit suite could improve fast failure-path visibility. |
| Processing messaging (460 lines, 82 sites) | Command dedupe, durable identity, claim/finish/redirect and staged result/work (`processing/messaging.py:102`, `:232`, `:325`, `:412`) | Pure identity/routing rules in `tests/processing/test_v1_delivery_rules.py:53`, `:101`; core transaction semantics in **integration** `tests/v1/test_messaging_sql.py:29`, `:68`, `:150`, `:196`, `:274`, `:322`. Not every complex handler is directly unit-tested. Preserve real PostgreSQL tests. |
| Processing SQS worker (516 lines, 77 sites) | Bounded polling, claim/disposition/ack, lease/visibility loss (`processing/worker/sqs.py:109`, `:233`) | 32 focused test definitions in `tests/processing/test_v1_worker.py`; examples: finite polling `:28`, no ack after lease loss `:58`, stale draining `:181`, visibility revocation `:338`, completion fencing `:371–425`. Direct unit evidence exists. |
| Processing lifecycle / `Claim` (221 lines, 44 sites) | Claim/heartbeat/finish fences and cleanup (`processing/lifecycle.py:124`, `:136`, `:184`) | Direct unit tests call active `processing.lifecycle` (`tests/processing/test_lifecycle.py:11`, `:21–55`). Some submission tests in the same file use legacy service code (`:9–10`), so a whole-file count is not exclusively current service behavior. |
| Processing native recovery / `NativeCleanupStore` | Repair, bounded rescans, result re-emission and ECS terminal hints (`processing/recovery_v1.py:25`, `:84`, `:166`, `:252`) | Expiry/output cleanup has unit tests against shared active recovery (`tests/processing/test_recovery.py:11`, `:24`); much native orchestration is integration (`tests/v1/test_delivery_recovery_sql.py:37`, `:115–209`, `:264–489`; `tests/v1/test_sqs_emulator.py:46`). Avoid treating legacy RQ repair cases as the native repair suite. |
| Processing short encoder / admission | Deadline bounds, fallback and partial-batch acknowledgement (`processing/short_encoder.py:54`, `:104`; `processing/short_lane.py:88–130`) | 16 definitions each in short-lane/short-encoder files; direct unit tests for bounds, redirect and lost fence (`tests/processing/test_short_lane.py:58–94`, `:126–159`; `tests/processing/test_short_encoder.py:175–230`). SQL handoff has a separate integration suite. |
| Media engine validation, operations, HLS, `SourceProbe` | Source-dependent crop/clip checks and safe FFmpeg command construction (`media_engine/validation.py:14`, `:44`; `media_engine/operations.py:10`; `media_engine/hls.py:43`; `media_engine/probe.py:10`, `:31`) | Direct tests for expression/type/nonfinite rejection, command order, probing and HLS dimensions/audio (`tests/media_engine/test_validation.py:23–114`; `tests/media_engine/test_commands.py:21–63`; `tests/media_engine/test_hls.py:15–91`). Unit command checks are not real encoding evidence. |
| Publisher `PublicClient`, `Intents`, CLI | Cookie persistence, request safety, upload/hash identity and CLI outcomes (`publisher/client.py:49`, `:83`, `:122`; `publisher/state.py:11`; `publisher/cli.py:98`) | Mock HTTP contract tests and direct-upload/file-identity tests (`tests/publisher/test_publisher.py:28–65`; `tests/publisher/test_direct_upload.py:1`; `tests/publisher/test_file_identity.py:1`). HTTPS integration test is separately selected; not run here. |
| Shared `Actor`/`Source`/`Envelope`, `GatewayAdapter`, `SQS`, SQL relay | Boundary validation, trusted identity, partial failures, dedupe/publication (`contracts/v1.py:70`, `:100`, `:158`; `contracts/gateway.py:48`, `:185`; `delivery/sql.py:18`, `:58`; `delivery/sqs.py:35`) | Prepared-contract tests and V1 frozen fixtures (`tests/contracts/test_prepared_contracts.py:15–70`; `tests/v1/test_contract_fixtures.py:361`, `:393`, `:482`); protocol/poison unit tests (`tests/v1/test_delivery.py:67–159`). SQL relay atomicity is integration (`tests/v1/test_messaging_sql.py:196`). No `tests/delivery/` directory does **not** mean delivery is untested. |

### Static test-definition counts

Counted `FunctionDef`/`AsyncFunctionDef` names beginning `test_` in `test_*.py` under each listed directory, including class methods, once per definition. Parameterized cases count once here. Counts include legacy/regression tests wherever those reside; they are not exclusively deployed V1 behavior. Counts do not establish coverage or passing status.

| Test directory / owner | Files | Test definitions | Expanded cases passed in first audit run |
|---|---:|---:|---:|
| `tests/media` | 16 | 150 | 288 |
| `tests/processing` | 18 | 167 | 325 |
| `tests/media_engine` | 3 | 25 | 105 |
| `tests/publisher` | 4 | 34 | 70 |
| `tests/contracts` | 1 | 7 | 16 |
| `tests/runtime_support` | 1 | 3 | 16 |
| Total for these six directories | 43 | 386 | 820 |

Additional inventories, not added to the service totals above: `tests/v1`: 37 files / 360 definitions; `tests/integration`: 16 / 103; `tests/aws`: 55 / 1,102; `tests/dev`: 17 / 272; `tests/ci`: 5 / 58. Entire `tests/` tree: 2,564 definitions. Cross-service suites intentionally sit outside service directories.

Frontend has three non-live test files (`app.test.js`, `app.direct-upload.test.js`, `app.player.integration.test.js`) with 151 ordinary `it`/`test` declarations plus nine `.each` declarations, and four further declarations in `app.live.test.js`. This is a textual declaration inventory, not a collected Vitest case count. Frontend execution was not attempted because this checkout has no installed `frontend/node_modules` and installation would exceed the read-only audit's dependency scope.

Reproduce the Python definition inventory without importing application code:

```python
import ast
from pathlib import Path
for name in ("media", "processing", "media_engine", "publisher", "contracts", "runtime_support"):
    files = list((Path("tests") / name).rglob("test_*.py"))
    count = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for path in files for node in ast.walk(ast.parse(path.read_text()))
    )
    print(name, len(files), count)
```

### Tests actually executed

This checkout has no `.venv`. Used `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python` (Python 3.12.11) with imports resolving from this checkout. No `uv sync`, package installation or lockfile mutation was performed; this is reuse of an existing environment, not a newly provisioned exact-lock environment.

Used direct documented pytest equivalents because the Make wrapper writes `artifacts/tooling/timings.jsonl` and hardcodes the checkout's interpreter (`scripts/dev/common.py:11–12`, `:54–73`). Focused test targets and offline selection are documented at `Makefile:44–63` and implemented at `scripts/dev/checks.py:93–114`; V1's command is at `Makefile:138–140`.

Both runs used `-B`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, `--no-cov`, temporary `--basetemp`/JUnit files, and removed inherited service/AWS configuration. Metadata credential discovery was disabled. The repository's `--offline-fast` plugin forbids network connections during each test (`scripts/dev/pytest_plugin.py:8–25`). No real AWS dependency was selected.

```text
python -B -m pytest tests/media tests/processing tests/media_engine tests/publisher
  tests/contracts tests/runtime_support -m 'not integration and not e2e' -q
  -p scripts.dev.pytest_plugin --offline-fast -p no:cacheprovider --no-cov
  --basetemp=<temporary-directory> --junitxml=<temporary-file>
Result: 820 passed, 1 deselected, 1 warning in 9.46s; exit 0.

python -B -m pytest tests/v1 tests/aws/v1/test_unattended_launch.py
  -m 'not integration and not e2e' -q -p scripts.dev.pytest_plugin --offline-fast
  -p no:cacheprovider --no-cov --basetemp=<temporary-directory>
  --junitxml=<temporary-file>
Result: 496 passed, 2 skipped, 150 deselected in 2.57s; exit 0.
```

First run's warning: MinIO dependency uses deprecated `datetime.utcnow()` in a credentials test. The two skips in the second run explicitly exclude privileged `BootstrapTaskDefinition` from owner SQL/storage-mode assertions; they are not failed dependency setup or quietly skipped integration. Of the second run's passing cases, 452 were V1 and 44 were unattended-launch tests. No full `make test`, frontend suite, real PostgreSQL/Moto acceptance, coverage percentage, image build or DAST scan was run locally in this audit.

### Existing coverage gates: do not propose them as missing

CI combines five current, fingerprint-matched fast/real-integration/V1 fragments and retains XML, JSON and `gate.json` for 60 days (`.github/workflows/ci.yml:568–594`). Every measured backend package has an 80% combined statement/branch floor and missing production files fail (`scripts/dev/coverage.py:97–156`). With the complete five-tier set, Media/Processing additionally require 90% combined and 85% raw branch coverage; native recovery modules require 80% combined/75% raw branch (`:19–39`, `:196–202`). Frontend requires 90% for statements, branches, functions and lines (`frontend/package.json:12–14`).

Do not infer that all goals are enforced in a unit-only run or that default `pyproject.toml` source settings describe the complete CI gate. `coverage.py` supplies the actual package/source set. Current percentages were not recomputed; the dated successful hosted gate is section 3's evidence. A human-readable summary is a useful enhancement; a new coverage system is unnecessary.

## 5. Typical course DevOps checklist: present, partial and missing

This is a practical checklist, not an assertion that the course mandates a particular scanner vendor. Item evidence is in sections 2–4.

| Checklist item | As-is conclusion | Remaining gap |
|---|---|---|
| SAST | Present: enforced Ruff S when selected; independent managed CodeQL; optional Sonar | Explain tool ownership/gate scope. Sonar is not a completed clean analysis. No need to add Semgrep/Bandit just to name another tool. |
| Dependency/SCA | npm audit and OS/Python library scans in images exist | No dedicated Python lock/runtime-set audit before image builds; useful quick win. |
| Secret scan | Present: unconditional gitleaks | Preserve allowlist discipline; transient download failure and durable report visibility can improve. |
| Container scan | Present: inherited and V1 image sets; extra CD admission | Keep exact-artifact provenance and unfixed/retained findings explicit. |
| IaC validation/security | cfn-lint, freshness checks, IAM-shape unit tests exist | Dedicated CloudFormation misconfiguration/security policy scanner absent. |
| DAST | Present in hosted CI and scheduled workflow against local isolated APIs | Findings do not fail by severity; excluded routes and AWS edge are untested by active scan. |
| Lint/format | Ruff and format-check, cfn-lint exist | No missing basic lint gate identified. |
| Unit tests | Large, passing focused offline suites; complex active logic exercised | Some native recovery/launcher orchestration relies on integration; counts mix legacy/current behavior. |
| Integration/acceptance | PostgreSQL, storage, Publisher HTTPS, browser trust and V1 local flows in full CI | Not rerun here; local emulation is not AWS proof. See `.github/workflows/ci.yml:185–245`, `:551–566`; `.github/workflows/v1.yml:86–141`. |
| Coverage gate | Present, source-matched multi-tier gates and frontend thresholds | Make exact-source results easy to read in job summary/report; do not lower thresholds. |
| Merge enforcement | **Missing on Main** in settings observed | Existing workflow failure is not a required status check. Settings change requires a deliberate release-process decision. |
| Production approval | Branch-constrained OIDC environment; automatic Main CD | **No human approval rule** on `aws`. Adding one changes automatic deployment behavior and must be coordinated. |

## 6. Ranked quick wins — proposals only, each ≤ about two hours

All times estimate agent implementation plus focused verification, not waiting for full hosted CI. All runtime/deploy risk estimates assume the proposal stays within the files and approach listed. **A green Main push is still an automatic CD trigger even for documentation, tests or workflow-only changes** (`.github/workflows/cd.yml:21–26`, `:101–109`, `:134–138`). “No runtime code change” therefore does not mean “cannot initiate CD.” Validate on the report/PR branch; do not dispatch CD or merge as part of this audit.

### 1. Correct the report using mechanisms already implemented — 60–120 minutes

- **Files:** `project-documentation/final-report/src/30-logical.md`, `32-physical.md`, `34-persistence-detailed.md`, `40-quality.md`, `50-devops.md`; adopt the reviewed subset described by `project-documentation/presentation/feedback-20261026/REPORT-CHANGES.md:110–120`, `:208–229`, `:372–387`.
- **Exact approach:** add the authorizer/API separation; replace edit-to-SQS arrows with copy/adoption/outbox/relay; name the two-stage Processing lane decision; explain direct Gateway/Lambda plus queue workers and no ALB; justify SQL/JSONB by current transactions and access patterns. Include the security inventory with “job failure,” “findings report-only” and “Main merge enforcement absent” separately. Prefer reviewed existing figures; do not regenerate all presentation assets.
- **Risk:** low; report-only. Current AWS state and historical run identities can still be overstated if qualifiers are dropped. Main merging still triggers CD.
- **Verify:** resolve every path/line against the pinned tree; inspect each selected diagram's arrows and labels against sections 2(a–f); render only the changed report and inspect at printed size. This audit did not perform report layout QA.
- **Truth enabled:** the report can already answer all six architecture/security remarks without changing deployed behavior.

### 2. Add explicit Python runtime dependency SCA — 60–120 minutes

- **Files:** new `.github/workflows/report-security.yml`, new `scripts/ci/python_audit.py`, focused `tests/ci/test_python_audit.py`; optionally document it in `50-devops.md`. Do not edit `uv.lock`, runtime dependency versions or Dockerfiles for the first evidence-only addition.
- **Exact approach:** standalone PR/manual/scheduled workflow with `contents: read`, no OIDC or environment credentials, pinned scanner version and a separate tooling environment. Export fully pinned requirements from the existing lock for the union of `v1-media`, `v1-processing`, `v1-worker` runtime extras, excluding dev and the project itself; label the output as that union, not an exact per-image inventory. Audit with `pip-audit -r <export> --no-deps --disable-pip -f json -o <report>`. Retain source SHA, lock hash, package count, scanner version, exit status and JSON. Initially advisory to the existing CI/CD aggregate; distinguish findings from tool/API failure. Never use automatic `--fix`. Official usage: [pip-audit documentation](https://pypa.github.io/pip-audit/).
- **Risk:** low runtime risk; network/advisory availability and marker/export handling need attention. A union is broader than any one image. Findings can require a later, separately reviewed dependency fix.
- **Verify:** lock export is pinned/nonempty with no editable/local project requirement; test clean, vulnerable and scanner-error fixtures without network; run one real hosted branch audit and retain its result. Confirm runtime files and image input hashes are unchanged. Claim “Python SCA executed/advisory,” not “no vulnerable dependencies” unless the report supports it.

### 3. Add static CloudFormation security analysis — 60–120 minutes

- **Files:** extend the new `.github/workflows/report-security.yml`; new `scripts/ci/iac_security.py` and `tests/ci/test_iac_security.py` if a wrapper is needed; `50-devops.md` for scope.
- **Exact approach:** pinned Checkov in an isolated tooling environment. Render the same shared, separate and cloned/split variants used by `scripts/aws/v1/lint.py:51–59` into `$RUNNER_TEMP`; scan those and the OIDC template as CloudFormation. Example invocation per input: `checkov -f <template> --framework cloudformation --skip-download --skip-results-upload -o json -o sarif --output-file-path <temporary-report-directory>`. No API key, deployment, Terraform apply or cloud lookup. Retain all findings and exact source/tool identity; start advisory outside the existing Full verification dependencies. Validate execution/report completeness separately from failed policy checks; do not hide all errors behind `|| true` or blanket exceptions. Official options: [Checkov CLI reference](https://www.checkov.io/2.Basics/CLI%20Command%20Reference.html).
- **Risk:** low runtime risk; generated conditions can produce false positives or untested branches. Finding remediation may be high risk, so the initial change adds evidence only. Use a CloudFormation scanner, not a Terraform-only job against this codebase.
- **Verify:** no snapshots are rewritten; scan a disposable insecure CloudFormation fixture and confirm its expected finding; ensure a missing/malformed report is reported as error; confirm all three variants are represented. Keep existing `cfn-lint --require` intact. Do not claim live infrastructure compliance.

### 4. Surface existing coverage and unit-test results in a concise CI summary — 45–90 minutes

- **Files:** `.github/workflows/ci.yml` (`lint-and-unit`, `coverage-gate` publication steps), optionally `scripts/dev/checks.py`, new small `scripts/ci/quality_summary.py` and `tests/ci/test_quality_summary.py`.
- **Exact approach:** add JUnit output to the existing fast test invocation and retain it on failure; summarize actual pass/fail/skip counts. Read the already-produced `artifacts/coverage/gate.json` for package combined/raw-branch rates, native recovery goals and source/tier identity, and append a compact Markdown table to `$GITHUB_STEP_SUMMARY`. Existing XML/JSON remain authoritative. Label unavailable fragments `NOT_MEASURED`; a failing test command must still fail. Do not add a second coverage run or change gates/omits.
- **Risk:** low; publication changes can accidentally affect job outcome or fabricate success if missing reports become empty tables. Avoid touching measurement or thresholds.
- **Verify:** fixture inputs for complete/missing/failed reports; compare displayed values to raw `gate.json`; the existing policy and coverage tests still pass; retain 90/85 and 80/75 goals. Use branch CI only. This addresses assessor visibility more directly than another scanner.

### 5. Add direct unit tests for native Media recovery orchestration — 60–120 minutes

- **Files:** new `tests/media/test_native_recovery.py`; production target `media/recovery_v1.py:218–241` stays unchanged.
- **Exact approach:** monkeypatch clock and cleanup collaborators with async doubles. Check that expired deadlines prevent further work, a deadline reached between cleanup phases prevents later storage calls, and a failure in an earlier phase does not perform later destructive cleanup. Verify batch bounds and returned counters. These are safety invariants, not a line-by-line mirror of implementation. Keep the existing PostgreSQL lock/race tests.
- **Risk:** very low; test-only. Do not replace SQL authority/fencing tests with mocks or cite this as proof of concurrent transactions.
- **Verify:** focused `make test-media` equivalent with `--offline-fast`; show the relevant negative cases fail under a temporary local mutation of the deadline/ordering condition, without committing that mutation. The normal focused run must remain green. A real coverage collection can subsequently show which branches improved; no percentage is promised here.

### 6. Add a small launcher `tick()` failure-path unit suite — 60–120 minutes

- **Files:** new `tests/processing/test_launcher_tick.py`; production target `processing/launcher.py:379–407` stays unchanged.
- **Exact approach:** use fake factory results, fake ECS/queue ports and patched reservation/send seams. Check idle state performs no ECS/SQS I/O; unreadable queue visibility passes “unknown/no demand” to the reservation logic; a refusal or ambiguous send stops additional sends in the pass. Do not duplicate the 44 existing launcher tests or move `_reserve` into a new abstraction solely for tests.
- **Risk:** very low; test-only. These tests validate orchestration boundaries, not SQL serialization or the global cap under concurrency.
- **Verify:** focused offline Processing tests and existing `test_unattended_launch.py`; preserve real `test_launcher_sql.py` integration cases as the cap/restart evidence. No ECS client or AWS profile may be used.

### 7. Make ZAP severity disposition explicit without changing the live release gate — 45–90 minutes

- **Files:** new `scripts/ci/zap_policy.py`, `tests/ci/test_zap_policy.py`; a publication/evaluation step in `.github/workflows/dast.yml`; optional `40-quality.md`/`50-devops.md` update.
- **Exact approach:** read the existing sanitized finding and scan-disposition JSON; output counts by severity and a separately labelled proposed HIGH/CRITICAL policy verdict. Keep execution/coverage/cleanup checks mandatory and current findings report-only by default. Record scan scope and excluded operations next to the verdict. An incomplete or failed scan must never produce a clean policy verdict. Retain the raw sanitized finding inventory. This prepares a reviewable baseline for any later severity gate; it does not make DAST blocking by severity.
- **Risk:** low while advisory. Turning the proposed verdict into a required check is a release-policy change, not part of this quick win. Do not active-scan dc2-live or expand mutation/HLS/admin scope casually.
- **Verify:** fixtures for zero/high findings, failed/unexecuted scan, missing reports and unexpected severity; preserve existing `tests/dev/test_v1_dast.py` results. A future branch CI execution can show disposition and scope together. Report “severity evaluation advisory,” not “DAST vulnerabilities block merge.”

### 8. Harden secret-scan evidence against transient download failures — 30–90 minutes

- **Files:** `.github/workflows/ci.yml:739–751`; optional `scripts/ci/install_gitleaks.py` and focused `tests/ci/test_install_gitleaks.py`; add an artifact-retention step after the scan if desired.
- **Exact approach:** retain the exact gitleaks version/checksum and full-history command. Add a small bounded retry for transient download failures (the 8 November receipt contains HTTP 504), never for scanner findings or checksum failures. Prefer authenticated `gh release download` if changing GitHub download transport. Retain redacted SARIF plus install/scan disposition as a workflow artifact even when code-scanning publication fails; publish no secret values. Keep installation failure and finding failure distinguishable.
- **Risk:** low runtime risk; a bad retry wrapper can mask security failure. Existing checksum verification and nonzero scanner outcome must remain decisive. This mitigates one observed failure mode; it does not fix the concurrent hosted Python/Trivy download failures.
- **Verify:** simulated transient-then-success, exhausted attempts and checksum mismatch; a known synthetic secret fixture must still fail and be redacted. Run on the branch, not by rerunning a successful Main push. Claim “more reliable evidence/installation,” not “all CI infrastructure failures solved.”

## 7. Decisions to defer / changes that should NOT be made for v1.1

- **Do not add an ALB, ECS HTTP service, MongoDB or DynamoDB simply to match a remark.** These change topology, persistence/recovery, credentials, operational cost and deployment; the report can address the choices using current source.
- **Do not change lane bounds, queue visibility, cap three/two, leases, source pinning, outbox transaction boundaries, consumer dedupe, schema migrations or image composition to make diagrams easier.** They affect live correctness and require deeper acceptance. Preserve historical misses and immutable V1 evidence.
- **Do not turn `cd.yml` into an experiment or bypass exact-source CI/image admission.** It updates the persistent stack after a successful Main push, with deploy enabled (`.github/workflows/cd.yml:101–109`). Standalone scanner additions must not be mistaken for new CD-required gates.
- **Do not dispatch/re-run Main-push CI to obtain a fresh screenshot without coordinating deployment.** Successful push-run completion can trigger CD. Exact-source manual CI dispatch has a different event; automatic CD explicitly accepts push events only (`.github/workflows/cd.yml:134–138`), but any later manual CD is outside this audit.
- **Do not lower coverage thresholds, add blanket scan ignores, silently accept unfixed/new baseline issues, weaken artifact identity checks, or relabel NOT_RUN as PASS.** Existing V1 Trivy policy has a narrowly documented retained rollback-target exception; do not broaden it (`scripts/ci/v1_scan.py:9–12`).
- **Do not add a duplicate gitleaks, coverage framework, or second local-stack ZAP job.** Those controls exist. Sonar should be described as conditional/advisory rather than making secrets/settings changes just for a screenshot.
- **Do not scan the deployed AWS endpoints in this task.** A live ZAP extension would need explicit target ownership, credential handling, request/load bounds and mutation exclusions. The current local harness intentionally refuses that scope.
- **Main protection and production approval are real owner decisions.** A narrowly scoped Main rule requiring the existing Full verification check and PR review would improve merge enforcement. An `aws` required-reviewer rule would introduce human deployment approval. Prepare exact settings and expected behavior for review, but do not enable either silently: reviewer availability/admin bypass/branch targeting matter, and an AWS approval rule changes the intentional automatic deployment workflow. They are not source-only, risk-free report edits.

Recommended initial bundle: report corrections, source-level Python SCA, static CloudFormation security evidence, and publication of the coverage results that already exist. Add focused recovery/launcher unit tests if the report specifically claims unit evidence for those native orchestration paths. Capture branch results honestly before adopting any stronger claim.
