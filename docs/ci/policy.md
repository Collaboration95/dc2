# CI verification policy

Implements #160, #161, #163 and #164 under #159. This is local CI policy, not
cloud acceptance or deployment permission. Stable aggregate check names are
**Dev gate** (job `fast`) and **Full verification** (job `integration`). No branch
protection or ruleset is changed here; enforcing those checks in repository
settings is a separate action. A successful Dev gate never substitutes for Full
verification on a promotion candidate.

## Event and source contract

| Event / target | Mode | Selection / source |
| --- | --- | --- |
| PR into `dev/v1-integration` | dev, unless conservative fallback | Intended base SHA to the tested merge SHA; selected lanes below |
| PR into `Main` | full | Every lane, tested PR merge commit |
| PR into an unknown target, or unknown event | full | Every lane; do not assume dev semantics |
| Push into `Main` | full | Every lane at the pushed SHA; regression detection, not pre-promotion proof |
| CI manual dispatch | full | Dispatch on the candidate ref and supply its exact 40-character `candidate_sha` |
| CI weekly Sunday 03:00 UTC | full | Every lane on the default branch; not an unmerged candidate |
| Unavailable/unreadable PR diff, unknown path, workflow/dependency/policy change | full | Every lane; never interpret an error as an empty diff |
| Proven empty dev diff | dev | Policy tests only |

`classify` checks that checkout HEAD equals `GITHUB_SHA`. PR comparison uses
`git merge-base <event.base.sha> <tested-merge-sha>` followed by a NUL-delimited
diff to that tested SHA, with full history available. Changes already present in
the intended base are excluded. `--no-renames` includes both old and new paths,
so a rename across owners selects both; deletes select their former owner.
Missing merge bases or undecodable filenames conservatively select full mode.
The job summary and attempt-specific `ci-selection-N` artifact record the tested merge
SHA separately from the PR head, run/attempt identity, selected lanes and decision reasons.

For an explicit checkpoint, first put the desired candidate on the dispatched
branch, then dispatch **that branch** and pass the exact commit:

```sh
gh workflow run ci.yml --ref CANDIDATE_BRANCH -f candidate_sha=FULL_40_CHARACTER_SHA
```

Supplying an unrelated SHA while dispatching a different ref fails classification;
there is no alternate checkout hidden inside a reusable workflow. Use the full
Main-promotion PR run at its current merge SHA before merging. A default-branch
schedule or an earlier candidate's success cannot attest to the current PR.

## Lane selection

All dev selections include `policy-checks`, which runs only standard-library CI
policy tests. Plain worklog/evidence prose needs no dependencies or live services.
`planning` runs `scripts/planning/validate_v1_plan.py` with the system Python when
the staged backlog/map/price provenance or its validator changes. Full mode
selects it too.

| Changed input | Selected dev lanes in addition to policy tests |
| --- | --- |
| `frontend/**` | frontend, inherited browser/CLI, V1 offline + live (includes unmeasured SPA packaging tests) |
| `publisher/**`, `tests/publisher/**` | Python fast, Publisher HTTPS, inherited browser/CLI, V1 live |
| `media/**`, `tests/media/**` | Python fast, Media integration, Publisher HTTPS, inherited browser/CLI, V1 offline + live |
| `processing/**`, `tests/processing/**` | Python fast, Processing integration, inherited browser/CLI, V1 offline + live |
| Per-service lanes (#199), independent of the rows above: `media/**`, `tests/media/**`, the Media V1 recipe | `media-service` |
| `processing/**` (includes the finite worker), `media_engine/**`, their tests, the Processing and worker V1 recipes, `scripts/aws/v1/bootstrap.py` | `processing-service` |
| `contracts/**`, `delivery/**`, `runtime_support/**`, their tests, `deploy/v1/check_runtime.py`, `build_and_verify.py`, `global-bundle.pem`, any other `deploy/v1/**` file, `deploy/aws/v1/template.json` | both service lanes |
| Shared `media_engine`, `runtime_support`, `delivery`, `contracts` and their owned tests | Python fast, all three service integrations, Publisher HTTPS, inherited browser/CLI, V1 offline + live |
| `app/**`, root `migrations/**`, root Dockerfile/alembic config, other inherited Python tests | Python fast, legacy integration, inherited browser/CLI |
| `tests/integration/test_media_*` | Python fast, Media integration |
| `tests/integration/test_processing_*`, database ownership test | Python fast, Processing integration |
| Other `tests/integration/**` (including shared conftest) | Python fast, all three service integrations |
| `tests/contracts/**` including JSON fixtures | Python fast, Media + Processing integration, inherited browser/CLI, V1 offline + live |
| `tests/v1/**` including JSON fixtures | Python fast, V1 offline + live |
| `tests/aws/**`, `scripts/aws/**` | Python fast, V1 offline; worker bootstrap also selects V1 images |
| `scripts/dev/v1_*` | Python fast, V1 offline + live |
| Other `scripts/dev/**`, `tests/dev/**`, `tests/e2e/**`, `scripts/evidence/**` | Python fast, all three service integrations, Publisher HTTPS, inherited browser/CLI, V1 offline + live |
| `deploy/v1/**`, `deploy/v1-local/**`, `deploy/aws/**` | Python fast, V1 offline + live; V1 build inputs also select images |
| Other deploy/compose files, root compose files, nginx/env examples | Python fast, all three service integrations, Publisher HTTPS, inherited browser/CLI |
| Staged planning backlog/map/price provenance and raw price snapshots | Planning validation |
| `.github/**`, classifier/policy tests, dependency manifests/locks, Makefile, Python version, Docker context exclusions, Sonar config | Full mode |
| Known prose/media documents under docs, course documents, roadmap, root guidance | Policy tests only |
| Unknown files or executable/snapshot/config formats under docs | Full mode |

These are unions: a multi-component PR gets every applicable lane. Source changes
that affect image build inputs add image validation and the applicable legacy
scan matrix entries. Merely changing an owned test does not rebuild an image.
No global `.md` or `.json` exemption exists. The allowlist for prose suffixes is
restricted to documentation trees and named root guidance; fixtures and runtime
configuration are classified before it. Unrecognized roadmap HTML or other input
formats conservatively select full verification.

The Python fast lane runs retained lint and `coverage-fast`, plus the two
legacy-only offline AWS operator test files excluded from the no-legacy V1
environment (`test_cloud_worker.py`, `test_definitions.py`). Its fragment is
**partial test evidence**, not the full package coverage claim. Dev has no new
partial combined coverage threshold. Frontend retains its existing coverage gate.
Full mode retains all five mandatory exact-source backend fragments and every
existing package threshold: fast, legacy integration, Processing integration,
Media integration, V1 integration. Missing data, missing metadata, stale source
fingerprints and unmeasured production files remain errors in the existing
coverage validator. The full coverage job waits for `v1-local` completion before
reading its fragment. No production threshold is changed.

## Per-service lanes and the secret scan

`media-service` and `processing-service` are ordinary lanes (same selection output, `if:` and
aggregate rules as the others). Each runs that owner's fast tests (`make test-media`;
`make test-processing test-media-engine`), builds and verifies **only that owner's** V1 images
with `deploy/v1/build_and_verify.py --only` (Processing's release unit is the API image and the
finite worker image), then runs `deploy/v1/check_runtime.py` inside each built image. They do
not replace `v1-local`, whose all-three build proves the images stay isolated from each other.
The selection inputs are the owners' real Dockerfile COPY sources, and a test checks that. The
mapping of those directories to owners is `.github/CODEOWNERS`.

`secret-scan` (gitleaks over the full history, `.gitleaks.toml`) is not a lane: it runs on every
event, and `ALWAYS_JOBS` in `scripts/ci/policy.py` makes both aggregates require it to succeed,
so no path selection can skip it.

## Aggregate and reusable workflow interface

`fast` waits for `classify`, `policy-checks`, `planning`, `lint-and-unit`, `frontend`,
`legacy-integration`, `processing-intake`, `media-integration`, `media-service`,
`processing-service`, `publisher-https`, `browser-trust`, `v1-local` and `secret-scan`. It deliberately excludes advisory scans and full
combined coverage. For every job in its scope, a selected job must be `success`
and a deselected job must be `skipped`. Failure, cancellation, missing results,
unknown statuses, and an unexpected skip fail. Docs-only skips cannot hide a
failed policy/planning validator. Classification errors fail the aggregates.

`integration` runs in full mode and additionally waits for `coverage-gate`,
`security` and `dast`. It checks every requested lane, including frontend and
policy validation, not just the older integration subset. Sonar remains advisory
and is outside both aggregate scopes. Both aggregate validators use `always()`
and inspect job conclusions; neither treats arbitrary skips as successful work.
Existing superseded-run concurrency cancellation is retained. The reusable DAST
concurrency group has its own prefix so it cannot cancel its CI caller.

`classify.outputs` are `mode` (`dev`/`full`), `plan` (JSON manifest), `source_sha`,
`security_matrix` (JSON `include` matrix), `v1`, and the boolean strings
`policy_checks`, `planning`, `lint_and_unit`, `frontend`, `legacy_integration`,
`processing_intake`, `media_integration`, `media_service`, `processing_service`, `publisher_https`, `browser_trust`,
`v1_offline`, `v1_live`, `images`, `coverage_gate`, `security`, `dast`.
`v1` is true if any V1 lane is selected. Manifest lane keys use real job IDs
(with hyphens), apart from V1's three internal request flags.

The `v1-local` reusable call always passes `flow: all`, `auto_images: false`,
`run_offline: <v1_offline>`, `run_live: <v1_live>`, and `images: <images>`, converting
output strings to booleans. Full mode passes true for all three requests.
`run_offline` covers control-plane, template and offline contracts; `run_live`
covers every local flow, browser and V1 coverage; `images` validates the three V1
artifacts. The reusable V1 requested checks aggregate fails for **any requested internal job**
that fails, cancels or skips.
The caller and reusable input contract are checked together by the workflow tests.

## Inherited assertion inventory and retention

Conceptual overlap does not retire a topology. No inherited suite is deleted or
relabeled as a cheap smoke. Full/manual/scheduled verification retains all rows.
Inherited runtime changes still select the complete inherited browser/CLI suite;
unrelated dev PRs (for example AWS operator-only tests) do not wait for it.

| Suite / source | Assertions retained | Relationship to V1 / selective risk |
| --- | --- | --- |
| `browser-trust`: `scripts/dev/browser.py:trust_smoke` | Trusted page and live HTTPS endpoint, secure context, explicit unrelated-CA rejection, scoped browser trust | Controlled positive/negative TLS pair is unique; V1 Chromium trusts its generated peer but does not replace this Firefox control |
| `scripts/dev/e2e.py` public cases | CT-01/02 replay/conflict; CT-07 retry rejection; CT-10 owner isolation; CT-17 derived playback after parent delete; CT-21 deleted-key tombstone; CT-23 prepared response schemas; real FFprobe/HLS traversal | Some domain assertions overlap V1; inherited public route/HTTP peer/Redis composition remains distinct |
| `scripts/dev/e2e_clients.py:browser_workflow` | Real UI registration/logout/login; worker-kill visible failure; stored-source retry with zero new upload bytes; separately selected HLS and MP4 decoded-frame progression; owner deletion and public 404 | V1 tests direct S3 POST, Gateway handlers, hls.js and native HLS redirects/CORS; that is not the inherited byte-upload/Redis worker path or the same explicit decoded-frame assertion pair |
| `scripts/dev/e2e_clients.py:cli_workflow` | CT-18-cli: credential stdin, private persisted cookie jar, 30 good files + one rejected file, exit/status behavior, playable result, interruption and stored-source retry | V1 Publisher tests direct POST, projection, owner isolation and retry. The inherited CLI batch/byte-upload path remains unique |
| `legacy-integration`: root `tests/integration` excluding Media/Processing owned files | Actual inherited PostgreSQL repositories/auth/jobs/reaper plus MinIO and FFmpeg | V1 has different persistence and delivery boundaries; retain the legacy coverage fragment in full mode |
| `processing-intake`: `scripts/dev/owned_checks.py`, `test_processing_*`, `test_database_ownership.py` | Durable intake/replay, leases/cancel races, DB isolation, real FFmpeg/storage, RQ loss/backoff/repair, killed worker recovery and cleanup | V1 SQS/outbox/recovery is different. Cheap selected service validation remains; RQ behavior is unique |
| `media-integration`: `test_media_persistence.py` | Media SQL durability, ambiguous acknowledgements, staging/orphan cleanup, owner/role boundaries, derived source lifetime, HLS authorization, DDL/opposite database denial | Shared domain logic has overlap; inherited HTTP composition and staging failure contracts are not retired |
| `publisher-https`: `tests/publisher/test_https.py` | Explicit CA, actual Secure cookie persisted across client instances, unrelated/untrusted certificate rejection | Cheap independent transport invariant retained for Publisher/Media/shared runtime changes and every full run |

`browser-trust` still requires a full `PASS` report, CT-18-cli and CT-18-browser,
and both `browser-hls-decoded` / `browser-mp4-decoded` events. Evidence uploads keep
only explicit sanitized JSON and screenshots, never raw CLI output, cookies,
private runtime files, traces or browser profiles. Existing bounded timeouts and
complete acceptance assertions are unchanged. Scheduled failures stay visible as
failed Full verification; they are never attributed to an unmerged candidate.

## Security execution and evidence

DAST remains Monday 03:00 UTC and manually runnable. CI selects relevant dev
API/auth/shared runtime/contracts and edge/stack inputs and calls the scanner once;
there is no duplicate standalone PR trigger. Dev scan results are advisory to Dev gate. Every full CI run calls the
reusable DAST workflow at the **same tested source**, including Main promotion,
Main regression, explicit checkpoints and conservative full fallbacks. Full
verification requires successful DAST execution. ZAP findings remain report-only
at every tier (exit codes 0/1/2 are accepted findings outcomes); execution errors
or a missing report fail the scan. This introduces no new vulnerability finding
threshold. The disposition includes source SHA/event and the offline-only private
contract scope. Sanitized alert identifiers/risk/counts remain uploaded; auth
headers, raw reports/logs and signed URLs remain private and are removed.

Manual standalone DAST uses the same exact-source rule:

```sh
gh workflow run dast.yml --ref CANDIDATE_BRANCH -f candidate_sha=FULL_40_CHARACTER_SHA
```

Legacy image scans are advisory to the dev aggregate and required by Full
verification. Dev builds/scans only affected legacy artifacts; full builds/scans
all three. Every scan retains its exact loaded image ID and source SHA plus the
Trivy report. The existing severity policy is unchanged: fixed HIGH/CRITICAL
vulnerabilities fail (`exit-code: 1`, `ignore-unfixed: true`). Build or scanner
execution failures fail the scan job. A green dev aggregate with an advisory
scan failure is not clean-scan evidence.

Image selection follows audited Dockerfile inputs:

- Legacy app: `app`, `migrations`, root Dockerfile and alembic configuration.
- Legacy Media: `media`, `contracts`, `delivery`, `runtime_support`, Media recipe.
- Legacy Processing: `processing`, `media_engine`, `contracts`, `delivery`,
  `runtime_support`, Processing recipe.
- V1: both domains, engine, contracts, delivery, runtime_support, all `deploy/v1`
  recipes/build tools/CA/checks, and `scripts/aws/v1/bootstrap.py` copied into the
  finite worker. Dependencies/lock/context exclusions conservatively select full.

Tests enumerate every actual Dockerfile COPY source and reject selection gaps.
Routine CI disables V1's automatic path guessing and passes this authoritative
image decision. The reusable standalone `auto_images` implementation uses `scripts.ci.v1 images`
and the same classifier, including conservative unknown-path fallback. There is no
second path allowlist. The template snapshot is an image-verifier input too. V1 image validation builds all three as one
isolation contract.
The legacy matrix **does not scan V1 Lambda/Fargate images**. The V1 image job
(`v1.yml`, same job, no extra build) runs Trivy on the three just-built images with the
same policy (zero fixable HIGH/CRITICAL; unfixed findings are counted, not failing),
then `scripts/ci/v1_scan.py` ties each report to the receipt's source SHA, Dockerfile and
local image config ID, and fails the job if any image has fixable findings, a missing
report or a mismatched image ID. Reports and `v1-scan-summary.json` upload with
`if: always()` as `v1-image-scans-<sha>`. The config ID is a local Docker image ID, never a
registry digest. The build receipt's `scan` stays `NOT_RUN` because it is written before
and by a different step; the CI artifact is the scan record. This is candidate CI evidence:
release acceptance still needs the scan of each exact promoted ECR digest, attributable to
its source, under its existing policy. A green job does not mean the system is
vulnerability-free.

Sonar configuration is checked immediately, independently of coverage setup.
Missing token/project/organization produces **NOT_RUN / not configured** in the
summary and a sanitized configuration artifact; no scanner or artifact downloads
run. If configured, relevant dev analysis is source-only and advisory, does not
await a quality gate, and retains scanner task/dashboard metadata. A successful
submission is not a completed analysis claim. Full advisory analysis retains
exact-source backend/frontend coverage downloads and `qualitygate.wait=true`.
Its existing `continue-on-error` policy is retained; no new mandatory hosted
service or subscription is enabled. Disposition artifacts distinguish not-run,
submission, completed execution and errors. Manual `aws-prep.yml` stays manual.

## Maintained tooling and source security lint

The `python-tools` local composite keeps the Python version file, uv version and
download-cache settings together. Each caller still runs its explicit locked
dependency installation; the V1 environment remains separate from legacy,
browser and emulator tools. CD retains its independent pinned setup. Image
verification runs `check_runtime` as both the image user and a Lambda uid under
read-only, reduced-capability container settings; service jobs do not repeat a
weaker invocation afterward.

All external workflow and composite-action references use immutable commit SHAs.
Version comments identify the intended release. Update a pin through the
authenticated `gh` CLI, resolve the selected upstream release to a commit in a
local checkout, review it, and run the workflow contracts before merging. Do not
replace a pin with a moving major tag. Runner and container base tags remain
separate moving inputs; action pinning alone does not make builds reproducible.

The required lint job also runs Ruff's `S` security rules over Media, Processing,
the media engine, contracts, delivery, runtime support, Publisher and the database
bootstrap copied into the worker image. This is
local security lint, not whole-program data-flow SAST. The one fixed emulator
credential exception is documented at its restricted local endpoint call. Run
the identical check with:

```sh
.venv/bin/ruff check --select S media processing media_engine contracts delivery runtime_support publisher scripts/aws/v1/bootstrap.py
```

## Verification and timing limits

Run policy tests without an application environment:

```sh
python3 -m unittest discover -s tests/ci -v
```

They cover path ownership, real Dockerfile inputs, rename/delete, updated PR base
and tested merge source, missing diff, exact manual source, schema/selection
wiring, failures/cancellations/unexpected skips, docs validator failure, and each
missing mandatory coverage fragment or metadata file. Existing browser acceptance
and V1 workflow regression assertions remain intact.

The warm 2–3 minute routine dev target is **not a measured result**. Changes that
affect inherited runtime or V1 images deliberately request longer checks. Compare
hosted before/after evidence at exact SHAs; separate initial queue time (creation
to first job start), required-gate latency (first job start to Dev gate or Full
verification completion), total workflow elapsed time, and summed job execution
time. Record end-to-end gate time including queue separately if used. Short scan
savings can reduce runner usage without reducing the gate's critical path. Local
offline tests cannot demonstrate hosted integration, image or browser timings.
Agent wait behavior and measured hosted receipts are owned by #165.

Measured hosted results and limitations: [results-20261017.md](results-20261017.md).
