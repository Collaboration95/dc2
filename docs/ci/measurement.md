# CI timing and verification receipts (#159, #162, #165)

This is the local tooling and baseline portion of #165. **After evidence is NOT_RUN.**
The coordinator must integrate the sibling changes, confirm the final dev/full gate names,
and collect hosted evidence before closing #162/#165. No speedup is claimed here. The
2–3 minute warm dev feedback goal excludes initial runner/start delay; it is a target.
Local PostgreSQL/Moto/FFmpeg/browser success is not real AWS acceptance.

## V1 reusable workflow contract

`.github/workflows/v1.yml` exposes these `workflow_call` inputs:

| Input | Type/default | Meaning |
| --- | --- | --- |
| `run_offline` | boolean, `true` | Untraced control-plane and operational checks |
| `run_live` | boolean, `true` | PostgreSQL/Moto/FFmpeg/browser flows and live coverage |
| `images` | boolean, `false` | Force all three amd64 image builds and verification |
| `auto_images` | boolean, `true` | Select images from build inputs when not forced |
| `flow` | string, `all` | `a`, `b`, `c`, or `all`; full mode requires `all` |

The full caller must explicitly supply:

```yaml
with:
  run_offline: true
  run_live: true
  images: true
  auto_images: false
  flow: all
```

Selective callers supply both lane booleans and their image decision with
`auto_images: false`. This prevents a second classifier from overriding an intentional
skip. `images: true` always builds, even when the internal image classifier is skipped.
For other callers, automatic image selection covers every source tree copied by the
three Dockerfiles (`contracts`, `delivery`, `media`, `processing`, `media_engine`,
`runtime_support`), deployment/verifier/bootstrap inputs, dependency locks, `.dockerignore`,
workflows and Makefile. PRs use a common-ancestor diff; deletions/renames retain both path
sides. Unknown/missing bases, failed diffs or a failed automatic classifier select images
conservatively. This internal fallback does not replace the caller's broader lane policy.

Manual V1 dispatch defaults to **both offline and live lanes, every flow**. Images remain
an explicit user choice (`false` by default); a full candidate must request them. Selecting
one flow is diagnostic and cannot attest to complete V1 acceptance. The manual input set
defaults both lane switches to `true`; disabling either is diagnostic only. Standalone
dispatch has no `auto_images` input, so images remain explicit. A reusable caller's flags
are honored even when that caller is itself manually dispatched.

The independent child jobs are `v1-offline` (display name
`V1 offline control-plane and operational checks`) and `v1-local` (display name
`V1 local flows, browser leg and coverage`). They have no dependency on one another.
GitHub propagates either selected child's failure through the reusable workflow to its
caller; the full aggregate must require that caller and all other selected full suites.
Keep missing/cancelled/unexpectedly skipped selected results as failures in the caller.

Offline setup uses locked `dev` dependencies without the legacy or browser extras;
cfn-lint 1.57.2 has a separate environment so its PyYAML does not leak into the suite.
Its executable is added to PATH so the existing real-linter regression still executes.
It retains required render/snapshot/cfn-lint validation, script/test lint,
`make test-aws-v1` and `make test-v1` with their network guard. These invocations are
untraced: `coverage-fast` excludes `unmeasured` tests and cannot replace them. The explicit
CLI skeleton test remains separate because its integration marker excludes it from the
offline make target. A missing CLI or skipped skeleton test now fails this selected step.

Only the live lane installs browsers/FFmpeg/Moto and starts services. It keeps
`V1_BROWSER=1`, `V1_COVERAGE=1`, the selected flows, `complete_v1_acceptance: PASS` for
`flow=all`, `cloud_acceptance: NOT_RUN`, job-owned namespace cleanup, redacted failure
evidence and the existing source-bound coverage producer/manifests. Artifact
`v1-coverage-data` still contains `.coverage.v1-integration*` including its manifest;
missing files fail upload. There is one live producer, so no duplicate namespace or
fragment is introduced. Flow/database sharding is not part of this change.

## Observed baseline (read on 2026-10-17)

These are three successful attempt-1 `pull_request` runs of the old broad policy, not
post-change routine dev samples. Each had 17 job entries, including one skipped optional
V1 image build. Its skip has synthetic reversed timestamps and contributes no duration.
The comparison below uses the observed **Integration checks** aggregate, not the future
dev/full gate. All durations are seconds.

| Run | Initial start delay | Integration gate from creation | Gate after first job start | Whole workflow | Sum executed job durations | Old V1 job |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [39023128839](https://github.com/Collaboration95/dc2/actions/runs/39023128839) | 3 | 427 | 424 | 431 | 1461 | 386 |
| [39023908155](https://github.com/Collaboration95/dc2/actions/runs/39023908155) | 67 | 463 | 396 | 467 | 1324 | 365 |
| [39022470853](https://github.com/Collaboration95/dc2/actions/runs/39022470853) | 62 | 449 | 387 | 455 | 1360 | 358 |

All three target `dev/v1-integration`, confirmed with `gh pr list --state all --head ...`
and exact head SHA matches: run 39023128839 / PR #154 /
`7c3977629fbca34f5298b4ab83ae6e1e85e4d101`; run 39023908155 / PR #155 /
`189fa87cb8fd55035d0310c130eedbbfa8230aa1`; run 39022470853 / PR #153 /
`335e65e6ff75d3400dc31e26bfcf955c0e3dc92e`. The run API itself returned empty
`pull_requests` arrays, so the script correctly reports unknown base branches for those
receipts rather than inferring them from head names.

| Run | Created UTC | First job start UTC | Integration gate end UTC | Workflow updated UTC |
| --- | --- | --- | --- | --- |
| 39023128839 | 09:58:34 | 09:58:37 | 10:05:41 | 10:05:45 |
| 39023908155 | 10:10:48 | 10:11:55 | 10:18:31 | 10:18:35 |
| 39022470853 | 09:47:40 | 09:48:42 | 09:55:09 | 09:55:15 |

Whole-workflow elapsed uses REST `updated_at` as an explicitly labelled completion proxy:
REST has no dedicated workflow completion timestamp. It may differ from the final job end.
The job sum is concurrent job wall time, **not elapsed feedback latency or a billing invoice**.
This small sample does not establish cache warmth or a routine dev distribution.

Read-only enforcement check on 2026-10-17: authenticated
`gh api repos/Collaboration95/dc2/branches/dev/v1-integration/protection` returned
`Branch not protected` (404), and `gh api repos/Collaboration95/dc2/rulesets` returned `[]`.
No settings changed. Recheck at final evidence collection; workflow aggregate semantics
alone do not establish repository enforcement.

Local implementation checks (not hosted after evidence): 182 focused timing/workflow/
template/image-contract tests passed; `make test-aws-v1` passed 1183 tests with the
isolated linter on PATH and no RQ/PyYAML/Playwright in the main environment;
`make test-v1` passed 377 with three existing skips (one unattached real-Media SQL test
and two inapplicable task credential variants). The separately required offline CLI
skeleton test passed. Required cfn-lint passed both layouts, Ruff passed, and actionlint
1.7.12 validated `v1.yml` (`-shellcheck=`; no ShellCheck claim). No live stack or hosted
workflow was started for these checks.

## Reproduce the measurements

Use Python 3.12+ from this checkout and authenticated `gh`. The script uses only
`gh api` for GitHub reads, with an exact-attempt paginated jobs endpoint. It starts no runs
and modifies no GitHub objects. JSON fixtures need neither network nor `gh`.

```sh
python -m scripts.dev.ci_timings \
  --baseline-run 39023128839 --baseline-run 39023908155 --baseline-run 39022470853 \
  --gate 'Integration checks' --tier pending-after \
  --save-receipts .cache/ci-baseline \
  --output .cache/ci-baseline-report.json
```

A receipt has `{"run": <REST workflow run>, "jobs": [<REST job>, ...]}`. Repeat
`--fixture` / `--baseline-fixture` to compare saved receipts offline. For example, after
the coordinator confirms the final name and obtains a natural successful dev run:

```sh
: "${DEV_GATE_NAME:?set the exact integrated dev aggregate job name}"
: "${AFTER_RUN_ID:?set an actual hosted run ID}"
python -m scripts.dev.ci_timings \
  --baseline-fixture .cache/ci-baseline/39023128839-attempt-1.json \
  --baseline-fixture .cache/ci-baseline/39023908155-attempt-1.json \
  --baseline-fixture .cache/ci-baseline/39022470853-attempt-1.json \
  --baseline-gate 'Integration checks' \
  --run "$AFTER_RUN_ID" --gate "$DEV_GATE_NAME" --tier dev \
  --save-receipts .cache/ci-after --output .cache/ci-comparison.json
```

Do not compare the old full gate and the new dev gate as equivalent acceptance scopes.
The script labels the operator-supplied tier and retains all observed job results so that
the selection can be checked against the classifier summary. It does not infer policy from
job names. Empty base-branch metadata stays unknown; reconcile it with the matching PR.

The report includes URL, SHA, event/head/base branches, attempt, tier label, selected
(observed non-skipped)/skipped job names, all job start/end timestamps and conclusions,
initial queue/start delay, required gate latency from creation and from first job start,
whole-workflow elapsed, summed completed job execution and immediate failed-job names.
Repeat `--gate` for multiple required jobs: latency ends when all finish. Names must match
exactly; absent/ambiguous/skipped/pending gates produce no passing result or gate latency.
Completed failed gates retain their latency and failure conclusion. Running jobs are not
credited zero-duration successes; incomplete sums are labelled partial. Rerun timing starts
at that attempt's `run_started_at`, with the original `created_at` and attempt retained.
Comparison medians use only complete successful receipts with successful required gates.

## Coordinator evidence and agent wait policy (pending integration)

The coordinator must publish the final stable **dev aggregate** and **full aggregate**
check names from #160 here; neither name is invented by this subagent. Discover the exact
names and classifier decisions with read-only commands:

```sh
gh pr checks "$PR_NUMBER" --repo Collaboration95/dc2
gh run view "$RUN_ID" --repo Collaboration95/dc2 --json headSha,event,jobs,url
gh workflow view ci.yml --repo Collaboration95/dc2 --ref "$CANDIDATE_REF" --yaml
```

On routine dev work, react to a failed selected check immediately; do not wait for unrelated
advisory jobs or workflow completion before fixing it. Passing the dev aggregate proves
only its selected tier. Use full candidate verification before Main promotion/release and
at explicit integration checkpoints. A scheduled default-branch run cannot attest to an
unmerged candidate. Read the exact source SHA and both aggregate/artifact outcomes.

Proposed coordinator-only dispatch commands (documented here, not executed):

```sh
# Standalone complete V1 local acceptance including optional images:
gh workflow run v1.yml --repo Collaboration95/dc2 --ref "$CANDIDATE_REF" \
  -f flow=all -F images=true
# Complete CI, once #160's integrated manual tier input name is confirmed:
: "${FULL_MODE_INPUT:?read the final ci.yml input name before dispatch}"
gh workflow run ci.yml --repo Collaboration95/dc2 --ref "$CANDIDATE_REF" \
  -f "$FULL_MODE_INPUT=full"
```

The standalone V1 run does not replace retained legacy acceptance, combined package
coverage, browser/CLI requirements and candidate-image/security checks in full CI.

Remaining evidence for #162/#165:

- At least three representative successful natural routine dev runs when available,
  plus docs-only and shared/workflow cases; identify component changes and cache/cold effects.
- Actual overlap of V1 offline/live start/end intervals and both lanes' conclusions.
- Selected failure/cancellation/unexpected skip propagation and conservative diff fixtures,
  plus a bounded coordinator-owned hosted validation. Do not inject failures in another agent's branch.
- Exact-candidate full verification retaining source-bound mandatory coverage fragments,
  complete browser/CLI assertions and all required image/security evidence.
- Final event/base/tier selection matrix, actual stable gate names, fresh enforcement reads,
  source SHAs, run URLs, selected/skipped jobs and per-job timing receipts.

If warm feedback misses the target, report its longest required dependency chain; do not
remove tests, weaken assertions or enlarge timeouts to manufacture success. Separating
V1 lanes alone does not prove a whole-gate speedup while another browser suite dominates.
