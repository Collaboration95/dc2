# DevOps and Development Lifecycle

## Source Control Strategy

FlickPond uses the `Collaboration95/dc2` GitHub monorepo, with `Main` as the default branch.
A contract change and its consumer tests can be reviewed together, while service images,
CODEOWNERS and path-selected CI preserve ownership boundaries.

| Path | Responsibility / release unit |
|:---------------------------------------|:-------------------------------------------------------|
| `media/` | Media API, application services, persistence and migrations; Media image |
| `processing/`, `media_engine/` | Processing API, orchestration and encode pipeline; Processing and Worker images |
| `contracts/`, `delivery/`, `runtime_support/` | Shared contracts and technical libraries copied into service images |
| `frontend/`, `publisher/` | Browser client and independent Publisher CLI |
| `deploy/`, `scripts/aws/` | Image recipes, CloudFormation generation, deploy/release/operator tooling |
| `.github/workflows/`, `scripts/ci/` | CI selection, verification, security, delivery and publication |
| `tests/` | Unit, contract, integration, infrastructure, pipeline and browser checks |
| `docs/`, `project-documentation/` | Architecture decisions, runbooks, sanitized evidence and report sources |
| `app/`, `legacy/`, `migrations/` | Inherited/regression paths, excluded from V1 runtime images |

**Branches and pull requests.** Feature/fix branches such as `fix/*`, `v2/*`, `ci/*` and `docs/*`
merge by PR into `dev/closeout`, then an integration PR promotes the combined change to `Main`.
The earlier V1 build used `dev/v1-integration` → `dev/v1` → `Main`. A PR records the problem,
technical decisions and verification; CODEOWNERS identifies the relevant reviewer. Commit messages
use short action-oriented descriptions, with `feat:` and `fix:` prefixes where appropriate.
Source SHAs and image digests identify releases in receipts; `project2-v1` marks the V1 release.

A PR into `dev/closeout` normally uses changed-input selection and **Dev gate**. Workflow,
dependency or unknown inputs can escalate it to full verification. PRs into other bases,
including `Main`, run **Full verification**. **Main branch protection will require a pull request
and the “Full verification” check.** PR review into Main is the approval point for promotion.
The merged source is tested again by Main push CI before automatic CD.

**Developer authentication and protected secrets.** Developers authenticate to GitHub with their
GitHub accounts and use SSH keys or authenticated HTTPS credentials for Git transport.
Repository credentials grant source access; AWS delivery uses a separate OIDC trust boundary.
Secrets belong in protected GitHub Actions secrets or scoped AWS parameter/secret storage,
with sanitized evidence committed to the repository. Push protection and full-history gitleaks
provide secret checks; `.gitleaks.toml` holds the reviewed allowlist. Scanner publication and
finding policies are listed in section 5.2.

## Continuous Integration

`.github/workflows/ci.yml` selects and verifies the candidate source. It calls `v1.yml` for V1
verification and `dast.yml` for authenticated local-stack DAST. Figure {@fig:devops-ci} places
security tools inside the verification pipeline and distinguishes independent advisory workflows.

![Figure {#fig:devops-ci}. CI triggers, parallel verification lanes, security stages and aggregates. CodeQL and advisory scans execute independently of Full verification.](figures/devops-ci.png){width=15cm}

| Trigger | Selection / purpose |
|:------------------------------------------|:-------------------------------------------------------|
| PR into `dev/closeout` | Changed-input dev selection, with conservative full escalation |
| PR into any other base, including Main | Full verification of the PR merge source |
| Push to Main | Full verification of the exact merged source; eligible for automatic CD |
| Manual CI dispatch with `candidate_sha` | Full verification; exact SHA must match the dispatched ref |
| Sunday 03:00 UTC | Full scheduled regression on the default branch |

`scripts/ci/policy.py` emits a source-bound `ci-selection` artifact. Both aggregates validate job
results and intentional skips. Dev gate requires the selected dev checks and unconditional secret
scan. Full verification additionally requires selected image security, DAST execution and combined
coverage. Failed, cancelled or unexpectedly skipped required checks fail the aggregate. CodeQL,
SonarCloud and PR #328's separate advisory workflow are outside its dependency list.

**Verification and security stages.** “Selected/full” below means the lane is selected by policy
and always included in full mode. Independent workflows have their own triggers.

| Stage | Tool | What it checks | Trigger | Blocking or advisory |
|:-------------------|:----------------|:-----------------------------------------|:--------------------|:--------------------------|
| Selection and policy | Python policy/planning tests | Changed inputs, full/dev selection and aggregate rules | Every CI event | Blocking |
| Lint and source security (SAST) | Ruff, format check, explicit Ruff S rules | Maintained Python code and bootstrap; S rules are Bandit-derived | Lint selected/full | Blocking findings |
| Fast unit tests | pytest | Service/module behavior; fast coverage fragment | Lint/unit selected/full | Blocking |
| Frontend and dependency SCA | Vitest, npm audit | UI behavior/coverage and locked frontend test-tool dependencies | Frontend selected/full | Blocking; audit HIGH/CRITICAL |
| Real integration and public flows | pytest, PostgreSQL, storage, FFmpeg, Publisher HTTPS, browser trust | Owned persistence/recovery, migrations, TLS/cookies and browser/client acceptance; service image/runtime checks | Relevant lane selected/full | Blocking |
| V1 infrastructure validation | cfn-lint and offline tests | Generated shared/separate/split template schema, freshness, IAM and control-plane rules | V1 offline selected/full; manual V1 | Blocking |
| V1 local flows | V1 harness, PostgreSQL, Moto, FFmpeg, browser | Current intake, processing, recovery and playback behavior | V1 live selected/full; manual V1 | Blocking |
| Image security | Trivy; V1 scan validator | Inherited app/Media/Processing matrix and exact V1 Media/Processing/Worker images; source/config identity | Image lanes selected/full; manual V1 `images=true` | Blocking: zero fixable HIGH/CRITICAL; malformed/wrong-image reports fail |
| Secrets | gitleaks | Full Git history against the reviewed allowlist | Every CI event | Blocking; required by both aggregates |
| Dynamic security (DAST) | OWASP ZAP | Authenticated seven-route scan of the disposable local V1 stack | DAST selected/full; `dast.yml` exact-SHA dispatch; Monday 03:00 UTC | Execution, coverage and cleanup block; findings advisory |
| Combined coverage | coverage.py, Vitest | Five source-matched backend tiers; 80% package floor, Media/Processing 90/85 and recovery 80/75; frontend 90% | Backend coverage selected/full; frontend lane | Blocking; exact gates in section 4.4 |
| Managed source security (SAST) | CodeQL default setup | Python, JavaScript/TypeScript and GitHub Actions | GitHub-managed push/PR analysis and weekly schedule | Independent; outside Full verification |
| Source/coverage analysis | SonarCloud | Conditional source-only or full-coverage analysis | Configured dev/full analysis jobs | Advisory; skipped in audited runs |
| Python runtime dependency SCA | pip-audit 2.10.1 | Frozen lockfile export: union of V1 Media/Processing/Worker runtime extras | `security-scans.yml`: PR, Main push, dispatch, Monday 03:30 UTC | Advisory findings; execution/report errors fail its job |
| Static infrastructure security | Checkov 3.4.3 | Disposable shared/separate/split CloudFormation renders plus OIDC template | Same advisory workflow | Advisory findings; execution/report errors fail its job |
| Aggregate | Dev gate / Full verification | Required selected job results and permitted skips | After dependencies complete | Blocking workflow verdict |

Ruff and npm audit are invoked by the lint/frontend jobs; image validation follows build in
`v1.yml`. The five backend fragments come from fast, legacy, Processing, Media and V1 integration
jobs before `coverage-gate`. Full verification then checks their results alongside the other lanes
(`ci.yml:568–625`, `scripts/dev/checks.py`, `scripts/dev/coverage.py`).

PR #328 (`ci/report-security-tools`) adds `.github/workflows/security-scans.yml` with the exact job
names **“Python runtime dependency SCA (advisory)”** and **“Static CloudFormation security
(advisory)”**. Its local scanner evidence reports **40 applicable packages, 0 pip-audit findings**.
Checkov reports failed-check counts **shared 26 / separate 31 / split 31 / OIDC 1**, advisory and
being triaged. These are overlapping policy-check occurrences across templates. Both jobs retain
JSON, source/lock/tool identity and scanner inputs for 14 days, with no AWS credentials.

ZAP uses the actual API handlers and authorizer through a disposable HTTPS loopback bridge on the
Actions runner, with PostgreSQL and Moto S3/SQS; the seven selected GETs are listed in section 4.3.
The workflow retains sanitized findings/disposition for 14 days. Backend coverage and image
receipts are retained for 60 days. Supported SARIF uploads publish results to code scanning;
npm uses logs, while preparation/CD use receipts. Publication is separate from scan execution.
Sonar source submission is advisory; the full-coverage job also treats its quality result as
advisory (`ci.yml`, `dast.yml`, `v1.yml`).

**Dated verification evidence.** The 21 October full Main run 39531399249 (`4ae6a0b`) passed
25 selected jobs with three intentional skips in 7 min 9 s; browser trust took 405 s.
The reviewed source-matched outcomes below preserve later results.

| Run / date | Source and event | Outcome |
|:---------------------------------|:---------------------------|:------------------------------------------------|
| CI 39931072197, 23 October | `76282d3`, Main push | Full CI passed |
| CI 40174362164, 25 October | `76282d3`, schedule | Inherited app/Processing Trivy and Full verification failed; V1 images and local ZAP passed |
| CodeQL 40189407647, 25 October | `76282d3`, managed analysis | Python, JavaScript/TypeScript and Actions analyses completed |
| CI 41294802851, 1 November | `76282d3`, Main push | Full verification, coverage, secrets, images and CI-called local DAST passed |
| CI 42468024855, 8 November | `76282d3`, schedule | Failed after setup/download HTTP 504s; coverage skipped |

The two October ZAP receipts recorded seven routes, 16 findings, 146 out-of-scope requests blocked
and successful cleanup. Source-matched run and policy evidence is recorded in
`feedback-20261026/report-notes/W5.md` and `rev-1.1/A3-CODE-GAPS.md` §§2–3.

## Continuous Delivery

`.github/workflows/cd.yml` invokes `scripts/ci/cd.sh`, which uses the existing deploy and
per-owner release tools, including `scripts/aws/v1/release.py`. Figure {@fig:devops-cd} shows the
automatic path and owner-release recovery boundary.

![Figure {#fig:devops-cd}. Delivery from Main review and exact-source CI admission through OIDC, image admission, journaled owner release, smoke/restore and playback verification.](figures/devops-cd.png){width=15cm}

| Environment | Purpose and lifecycle |
|:--------------------------|:---------------------------------------------------------------|
| Local V1 | Developer and CI disposable PostgreSQL/Moto/FFmpeg stack; fast and full public flows (`make setup-v1`, `make v1-up`, `make v1-demo`) |
| Per-run AWS V1 proof stacks | Disposable `r1017b`, `r1018b`, `r1019a` deployments for bounded cloud proofs, followed by teardown (AD-19) |
| Persistent `dc2-live` | Production-demo stack, updated in place after eligible Main CI (AD-27) |

**Promotion approval.** PR review into Main approves the change. After merge, a successful
**Full verification** on that exact Main push source starts automatic CD. The admission job binds
the triggering repository, source SHA, run and attempt; PR and scheduled CI runs cannot admit this
automatic path (`scripts/ci/cd_gate.py`). The `run` job checks out the admitted SHA and assumes the
AWS role through GitHub OIDC in the branch-restricted **`aws` environment** (Main and
`dev/closeout`). That environment supplies branch control; no second human deployment approval is
configured. A concurrency group serializes deliveries. Manual deploy/release can instead use an
eligible exact-source full CI dispatch.

**Deployment verification.**

1. **Admission and preflight.** Retain the exact-source CI admission record, read stack/journal
   state and inspect the CloudFormation change set. Reject replacement of retained Aurora,
   buckets or the distribution. Updates apply the live configuration in place.
2. **Image admission.** Release only owners whose image build inputs changed. Build and scan the
   promoted bytes, bind config/source identity to immutable registry digests, and require completed
   matching ECR scans. Candidate and kept-running image sets require zero fixable HIGH/CRITICAL
   Trivy findings. ECR separately rejects unaccepted HIGH/CRITICAL findings
   (`scripts/aws/v1/artifacts.py`, `scripts/aws/v1/proof/release_plan.py`).
3. **Journaled owner release.** Record prior owner and peer state, quiesce the owning work,
   verify compatibility, run the migration task, publish Lambda versions and move live aliases.
   The Processing release also records its worker definition. Persist each step for resumption
   and verify the peer is unchanged (`scripts/aws/v1/release.py:240–394`).
4. **Owner smoke and automatic restore.** The public owner smoke checks the candidate's contracts,
   including health/authentication and quiescence. On promotion failure, `cd.sh` invokes restore
   of the prior aliases/worker and smoke-tests the restored state. The journal records
   `restored`, `abandoned` when nothing changed, or `restore-failed`. Schema migrations are
   additive and are not downgraded (`scripts/ci/cd.sh:608–665`, `release.py:397–462`).
5. **Upload-to-playback smoke.** After deploy/release, upload a real clip through the public API,
   wait for `done`, then read MP4, HLS playlist and segment. Failure fails CD; this later smoke
   is outside the owner restore boundary (`cd.yml:230–251`).
6. **Receipts.** Retain sanitized admission, scan, release and playback results for 60 days.
   Save resumable private journal state to versioned S3, including after failed runs.

The Trivy-only `RETAINED_FIXABLE` exception applies to a replaced image held solely as a restore
target (AD-28). It records findings without blocking remediation of that baseline; new candidates
and kept-running companions stay strict. Every image set still needs completed matching ECR
validation. Wrong-image reports and scanner errors remain blocking. Manual `aws-prep.yml` scans
selected inherited-owner images under the same fixable-image threshold and retains preparation
artifacts for 14 days; it is separate from automatic Main CI/CD.

**Recorded deliveries.**

| Run | Source | Outcome |
|:----------------------|:--------|:-------------------------------------------------------------------------|
| 39085599276 / 39087966647 / 39089615147 (`r1019a`) | `0b491e1`, `358d169` | V1 deploy with smoke PASS; Processing release 9 m 39 s with post-release smoke PASS; teardown `CLEAN` |
| 39105817431 | `d2070db` | First persistent `dc2-live` deploy; smoke PASS |
| 39271754470 | `7928b7c` | Deliberate bad Processing candidate: smoke failed (503) and the previous aliases were **restored** automatically |
| 39286933644 | `daee44b` | Deploy of the team-accepted frozen demo release |
| 39416747925 | `629119c` | Both owners promoted, deployed-image scans clean, upload-to-playback smoke passed, read-back of 3 images, 10 aliases and the worker definition |
| 39532075705 | `4ae6a0b` | **Failed**: the scan of the retained Media rollback image found 1 fixable HIGH/CRITICAL (see below) |
| 39542434067 | `6155951` | **Failed**: the stack-level public smoke met a paused Aurora cluster; login answered 503 (see below) |
| 39545554380 | `c7c489c` | **Success**: both owners promoted, with the old images' advisory recorded; zero fixable HIGH/CRITICAL in the deployed images; upload-to-playback smoke PASS, job `done` in 101.2 s; 3 images, 10 aliases and the worker definition read back (`docs/results/engineering-20261021/delivery-c7c489c.json`) |

On 21 October, retained-image rescanning blocked the replacement of a baseline carrying the
new `certifi` advisory, even though the candidate fixed it. AD-28 introduced the recorded
restore-target exception above. A subsequent stack smoke met a resuming Aurora cluster and
received `login:503`; bounded login-only wake retries were added for 502/503/504 or transport
failure within 180 s. The later `c7c489c` delivery was admitted by CI 39544952625: Deploy took
22 min 56 s, playback smoke 2 min 27 s, and the job reached `done` in 101.2 s. Read-back matched
three image digests, ten live aliases and `dc2-live-worker:12`
(`docs/results/engineering-20261021/delivery-c7c489c.json`).
