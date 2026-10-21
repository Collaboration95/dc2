# DevOps and Development Lifecycle

## Source Control Strategy

**Repository strategy: one monorepo.** Everything lives in one public GitHub repository,
`Collaboration95/dc2`, with default branch `Main`: both services, both clients, the shared kernel,
infrastructure as code, pipelines, tests, evidence and documentation. One repository keeps a
contract change and both of its consumers in a single pull request, which the contract policy
requires. Service independence is enforced inside the repository by path-filtered CI lanes,
per-service images and CODEOWNERS, not by separate repositories.

| Path | Contents | Release unit |
|:------------------|:----------------------------------------------------------|:---------------|
| `media/` | Media Management service, its Alembic migrations | Media image |
| `processing/`, `media_engine/` | Processing service, finite worker, FFmpeg command builders | Processing and worker images |
| `contracts/`, `delivery/`, `runtime_support/` | Shared kernel: published language, outbox/inbox and SQS adapters, Lambda runtime | Copied into both images; a change releases both |
| `frontend/`, `publisher/` | The two clients | Frontend bucket; Publisher package |
| `deploy/`, `scripts/aws/` | Image recipes, CloudFormation generator and template, deploy, session, release and evidence CLIs | Stack and operator tooling |
| `.github/workflows/`, `scripts/ci/` | CI, CD, DAST, V1 verification and Pages workflows; CI policy and CD scripts | Pipeline |
| `tests/` | Unit, integration, contract, AWS-offline, CI-policy and browser tests (3,982 Python tests) | n/a |
| `docs/`, `project-documentation/` | Architecture, ADRs, runbooks, sanitized receipts, course documents, this report | n/a |
| `app/`, `legacy/`, `migrations/` | Inherited Project 1 application and retired peer-HTTP/Redis code, kept testable but excluded from images | Not deployed |

**Branching strategy: trunk plus short-lived integration branches.**

- `Main` is the trunk. A push to `Main` triggers full CI, and a green run deploys automatically.
- Feature and fix branches (`fix/*`, `docs/*`, `v1/*`, `v2/*`, `ci/*`, `release/*`) are
  short-lived. They merge by pull request into an **integration branch**: `dev/v1-integration`
  then `dev/v1` for the V1 build (16–17 October), and `dev/closeout` for close-out (17–21
  October).
- Each integration branch merges into `Main` through one release-style pull request that runs
  the full verification.
- Merge commits are used throughout, so each PR's history stays visible on `Main`
  (140 merge commits).
- Every PR body records its "Tech decisions".
- The only tag is `project2-v1`, which marks the V1 release (18 October). Later releases are
  identified by source SHA and image digest in sanitized receipts.

| Era | Branch flow | Example PRs |
|:-------------|:------------------------------------------------------|:------------|
| Local waves (12–14 Oct) | `wave/*`, `fix/*` → `Main` | #28–#30 (Processing, Media, clients) |
| AWS preparation (14–15 Oct) | `work/aws2-*` → `work/aws2-prep` → `Main` | #70 |
| V1 build (16–17 Oct) | `v1/*` → `dev/v1-integration` → `dev/v1` → `Main` | #112, #136, #194 |
| Close-out (17–21 Oct) | `fix/*`, `v2/*`, `docs/*` → `dev/closeout` → `Main` | #239, #264, #269, #274, #277 |
| Quality and hand-off (20–21 Oct) | `quality/*`, `docs/*` → `Main` | #278–#284 |

**Pull-request checks.** CI runs on every pull request:

- Into `dev/closeout`, it runs only the lanes whose inputs changed. The aggregate check is
  **Dev gate**.
- Into `Main`, it runs every lane. The aggregate check is **Full verification**.

Since 15 October, every first-parent commit on `Main` is a PR merge. Up to #284, 26 of the 27 PRs
into `Main` merged with all checks green. The exception, #194, merged with the advisory third-party
GitGuardian check failing.

**Authentication and access of developers.**

- The repository is owned by one personal GitHub account (`Collaboration95`), which is its only
  collaborator. All commits, PRs and issues were made through it, by the team and by the AI coding
  agents it ran.
- **Branch protection and rulesets are not configured.** "Dev gate" and "Full verification" are
  stable, enforceable check names, but nothing in the repository settings requires them, and no
  reviewer approval is required. Pull-request discipline was a team practice, not a setting.
- Secret scanning with push protection is enabled, gitleaks runs in CI, and Dependabot alerts are on.
- Scanner results reach GitHub code scanning as SARIF, so the Security tab is the single place to
  triage them: CodeQL default setup (Python, JavaScript/TypeScript, GitHub Actions), Trivy per image,
  authenticated OWASP ZAP, Ruff security rules (Bandit) and gitleaks. Triage on 22 October dismissed
  12 High CodeQL alerts with reasons; all were in test, proof or developer-script code, none in
  deployed code (`docs/ci/policy.md`). CVE-2025-52290 (`ffmpeg`, no Debian 13 fix) is accepted unfixed
  for a finite worker with no inbound network.
- Cloud access is separate from repository access:
  - Human operators use IAM users with an MFA session helper (`make aws-mfa-session`).
  - The automation agent uses a dedicated IAM user (`flickpond-agent`, profile `dc2-agent`).
  - GitHub Actions uses **OIDC only**. No AWS key is stored in GitHub. The deploy role trusts only
    the immutable subject of this repository's `aws` environment, and that environment admits only
    `Main` and `dev/closeout`.

The missing protection is recorded as AISS-04. For a multi-account team, the next steps are:

- add the members as collaborators;
- require "Full verification" and one review on `Main` and `dev/closeout` through a ruleset;
- require reviewers on the `aws` environment.

## Continuous Integration

`.github/workflows/ci.yml` is the integration pipeline. Its reusable parts are `v1.yml` (V1 local
verification) and `dast.yml`.

**Triggers.**

| Trigger | Mode | Purpose |
|:----------------|:---------|:----------------------------------------------------------|
| Pull request into `dev/closeout` or another integration branch | dev (selected) | Fast feedback: only lanes whose path inputs changed; aggregate check **Dev gate** |
| Pull request into `Main` | full | Every lane before integration; aggregate check **Full verification** |
| Push to `Main` | full | Verifies the exact merged source; a green run is CD's admission ticket |
| Manual dispatch (`candidate_sha`) | full | Verify an exact candidate |
| Weekly schedule (Sunday 03:00 UTC) | full | Catches drift: new advisories, dependency and tool changes |

`scripts/ci/policy.py classify` decides the mode and the selected lanes, and writes them to a
`ci-selection` artifact. It has its own offline tests. The final gate job requires every selected
check to pass and validates every intentional skip, so a lane cannot silently disappear.

**Jobs.**

| Job | What it runs |
|:----------------------------|:--------------------------------------------------------------------|
| Select verification policy; CI policy offline tests; planning validation | Lane selection and its tests |
| Lint and Python unit tests | Locked `uv` environment; Ruff lint and security rules; format check; the fast pytest tier with coverage |
| Frontend tests | `npm audit --audit-level=high`; Vitest with V8 coverage (90 % floors) |
| Legacy real integration | PostgreSQL 16, MinIO and FFmpeg integration of the inherited app |
| Processing worker, recovery and database ownership | Owned PostgreSQL and storage acceptance in Docker |
| Media owned persistence and boundary contracts | Media migrations and integration tests on PostgreSQL |
| Media service; Processing service | Per-service tests, then **build the exact service image** and verify its runtime (no opposite domain, no legacy modules, handlers start) |
| Independent Publisher HTTPS and cookie persistence | The Publisher against real TLS |
| Local HTTPS and browser trust | Playwright and Chromium against the local HTTPS stack: browser, public API and Publisher acceptance |
| V1 local verification (`v1.yml`) | cfn-lint (required); offline control-plane tests (template, IAM, release, launcher); V1 flows on PostgreSQL, Moto and FFmpeg with a browser leg; build of all three images, then **Trivy on the exact images**, failing on any fixable HIGH/CRITICAL |
| Combined backend package coverage | Merges five coverage tiers; at least 80 % per package |
| Scan container image (app / media / processing) | Trivy image scan matrix; reports kept 60 days and published as SARIF |
| Secret scan (gitleaks) | Full history with an allow-list; SARIF to code scanning |
| CodeQL (default setup) | Python, JavaScript/TypeScript and GitHub Actions; results in the Security tab |
| Exact-candidate DAST (`dast.yml`) | Authenticated OWASP ZAP against the local Media and Processing APIs; findings report-only, published as SARIF |
| SonarCloud SAST (advisory) | Skipped while Sonar is unconfigured |
| Dev gate / Full verification | Policy gate over the selected checks |

On a representative full `Main` run (39531399249, source `4ae6a0b`, 21 October), all 25 selected
jobs passed and the 3 skips were intentional. Wall-clock time was 7 min 9 s, because the jobs run in parallel; the
longest job, the browser trust suite, took 405 s. By the morning of 21 October, CI had run 246 times. Artifacts
are bound to their source SHA: coverage fragments, image scan reports, DAST findings and selection
records.

## Continuous Delivery

`.github/workflows/cd.yml` and `scripts/ci/cd.sh` automate delivery.

![Figure {#fig:cicd}. CI/CD pipeline: pull-request lanes, full verification on Main, exact-source admission, in-place stack update, per-owner release with scan, smoke and restore, and the receipts it retains.](figures/report-cicd.png){width=12cm}

**Environments.**

| Environment | Purpose | How it is created |
|:-------------|:-------------------------------------------------------|:-----------------------------|
| Developer machine | Fast checks; the full local V1 stack on PostgreSQL, Moto and FFmpeg, with the same images | `make setup-v1`, `make v1-up`, `make v1-demo` |
| CI (ephemeral) | Exact-source verification, image builds and scans, DAST | Every pull request and push |
| AWS V1 per-run stacks (historical) | The proof runs `r1017b`, `r1018b`, `r1019a`, each deleted afterwards | Dispatched deploy and teardown (AD-19) |
| **AWS `dc2-live` (production demo)** | The one persistent environment, updated in place | First deploy by a human dispatch; then automatically after every green CI run on `Main` (AD-27) |

There is no separate staging environment (AISS-04). Two things stand in for it: the local V1 stack
and CI's exact-image verification exercise the same images before promotion, and every release
smoke-tests production with an automatic restore on failure.

**Promotion and who approves it.**

- Promotion **into `Main` is the approval**. The person merging the release PR is the approver; in
  this project that was the repository owner, Guruprasath Gopal, the cloud and delivery lead.
- After that, promotion to `dc2-live` is automatic, with no manual gate:
  1. CI on `Main` completes and triggers CD (`workflow_run`).
  2. The **admission gate** job refuses the commit unless that exact SHA had a successful push CI
     run in this repository, then retains an admission record.
  3. The `deploy` job assumes the AWS role through OIDC, only from the `aws` environment.
- Manual dispatch remains available for `preflight`, `deploy`, `release` (including a deliberate
  `bad_candidate`), and `teardown`. `teardown` requires `confirm=live`.
- A concurrency group prevents two deliveries running at once.

**Deployment steps and verification.**

1. **Preflight** (reads only): account and region, stack state, a change set that must not
   replace Aurora, a bucket or the distribution, and the release journal.
2. **Stack update**: a CloudFormation `UPDATE` change set from the checked-out template. For the `live` environment this step also applies the Lambda short-encode lane and the per-service database split (AD-29: snapshot, clone, smoke, then cleanup); run 39644028238 delivered both.
3. **Per-owner release**, only for owners whose image build inputs changed:
   - build the image;
   - scan the candidate, and scan the retained rollback image (AD-28);
   - push it, and bind the registry manifest to the scanned config;
   - run the migration task if attested;
   - publish versions and move the `live` aliases;
   - run the owner's health and authentication smoke;
   - **restore the previous versions** if anything fails;
   - adopt the images into the stack.
4. **Upload-to-playback smoke**: a real clip is uploaded through the public API. The job must
   reach `done`, and the MP4, HLS playlist and segment must be playable.
5. **Receipts**: redacted results are uploaded as an artifact. Run state is saved to a private,
   versioned S3 bucket. Sanitized delivery receipts are then committed (for example
   `docs/results/engineering-20261020/delivery-629119c.json`).

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

**The 21 October scan incident.** This was the only time the release gate blocked a correct
release. The handling shows how the pipeline is meant to be operated.

1. **Detection.** CD run 39532075705, for `Main` at `4ae6a0b` (which bumped `certifi` for a new
   advisory), failed in `Deploy` with `media: FAIL: Trivy has 1 fixable HIGH/CRITICAL`. The
   upload-to-playback smoke was skipped. The live environment kept running the previous verified
   release, `629119c`, untouched.
2. **Root cause, from the run log and the saved reports.** The candidate image passed its scan.
   The failing scan was the rescan of the image running at the time, the rollback baseline
   (`sha256:24bd78a8…`, built from `629119c`). It carried GHSA-6q48-6c7w-9gw2 in `certifi
   2026.7.22`: emSign root CAs with compromised intermediate keys. The advisory was published on
   20 October at 19:35 UTC, after that image shipped. The candidate's `certifi 2026.10.19` fixes
   it. So the gate refused to replace a vulnerable image *because* it was vulnerable, and the fix
   could never ship.
3. **Fix without weakening the gate (AD-28, PR #285 into `dev/closeout`, PR #286 into `Main`).**
   The rules are now:
   - The candidate must still scan clean first.
   - Images that the release **keeps** are rescanned strictly.
   - Images that the release **replaces** are rescanned in a *retained* mode. A fixable finding
     there becomes `RETAINED_FIXABLE`: it is listed in the release receipt, annotated on the run
     and shown in the job summary, and it does not block.
   - Only the baseline role accepts that status. Promotion, publication and the good and bad
     image sets still require `PASS`.
   - Scanner errors and wrong-image reports fail in both modes.
   - Tests pin each rule. The real failing report, replayed through the scanner, fails in strict
     mode and is recorded in retained mode.
4. **A second, latent defect.** With the scan fixed, CD run 39542434067 (`6155951`) reached the
   stack-level public smoke and failed with `login:503`. The update changed no migration, so
   nothing had touched the database before the smoke. Aurora had auto-paused at 0 ACU. The login
   is the smoke's first database-backed call, and it met a cluster that was still resuming:
   MediaApi gave up after about 10.7 s and answered 503, and capacity read 1.0 ACU moments later.
   PRs #287 and #288 let the deploy's smoke retry **only the login**, only on 502/503/504 or a
   transport failure, after 5, 10 and 15 s, within a 180 s deadline. Every attempt is recorded.
   Any other status, or a 503 that outlasts the pauses, still fails. The release smoke, which
   runs after its migration has woken the database, is not retried.
5. **Redelivery.** CD run 39545554380, on `c7c489c` and admitted by `Main` CI 39544952625,
   succeeded:
   - gate job 7 s; Deploy step, including both owner releases and stack adoption, 22 min 56 s;
     upload-to-playback smoke 2 min 27 s;
   - the smoke job reached `done` 101.2 s after acceptance, with MP4 and HLS served;
   - the release receipts list the certifi advisory against the three *replaced* images;
   - read-back confirmed the deployed digests: Media `sha256:dafbb19d…`, Processing
     `sha256:3c83e4ba…` and worker `sha256:eed6fbbb…`, with the ten `live` aliases and
     `dc2-live-worker:12` matching.

   The receipt is `docs/results/engineering-20261021/delivery-c7c489c.json`. The documentation
   follow-up (#289, #290) redeployed with no releases, and its smoke passed in 116.1 s. Two things
   remain unexercised: the wake retry did not fire in the live run, and the replaced image's
   rollback was not run. The receipt records both.

A scheduled weekly rescan of retained images would surface such advisories before a release meets
them.

