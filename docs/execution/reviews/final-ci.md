# Bounded full client acceptance in CI

Scope: `.github/workflows/ci.yml` and offline workflow regressions only. Starting
commit: `4a71f67` on `work/final-ci`. No runtime or product code changes.

The existing `browser-trust` job now invokes the complete
`scripts.dev.e2e` module after infrastructure and trusted/untrusted TLS smoke.
It retains its job ID/name and remains a dependency of `Integration checks`.
All existing test, coverage, security and aggregate gates remain in place.
FFmpeg (including ffprobe) is installed alongside NSS prerequisites on the
disposable Linux runner.

Full acceptance covers public ownership/idempotency/edit/delete/playback,
Publisher registration/login, a 30-good/1-rejected file batch and stored-source
retry, plus browser registration/login/upload, worker interruption, retry,
decoded HLS and MP4 playback and owner deletion. The workflow additionally
requires a PASS result with full scope, both CT-18 client cases and both decoded
playback events. A public-only result cannot satisfy the job.

Bounds: 35 minutes for the job, 10 minutes for stack startup, and a 15-minute
GNU timeout for e2e with TERM followed by KILL after 30 seconds (16-minute step).
Artifact upload and scoped shutdown each have a two-minute step bound;
failure log collection has one minute. There are no acceptance retries or
continue-on-error allowances. The runner uses the existing single-worker Compose
topology; full performance/scaling experiments are not added to routine CI.

Uploads run with `always()` and seven-day retention. The allowlist contains only
runner capacity JSON, browser trust JSON/PNG, the e2e latest pointer, scenario
result JSON and browser screenshots. It retains available failure results and
screenshots without selecting `.local` runtime configuration, TLS private keys,
cookie jars, browser profiles, traces, raw CLI output, or fixture/output media.
The scenario report already omits credentials and signed playback links; browser
screenshots are captured after login, during failed-attempt/playback views.
Missing artifacts warn so an earlier setup failure keeps its original cause.
A hard job termination may prevent upload/cleanup; an ordinary e2e timeout leaves
time for those steps. Runner-owned resources are then disposable.

## Capacity assessment

Static Compose inspection finds nine long-lived services with aggregate limits
of 4.0 vCPU and 3840 MiB (3.75 GiB) for one worker. The worker alone is capped at
2.0 vCPU and 1536 MiB. Migration/bootstrap jobs are transient and have no fixed
limits in that file. Builds complete before client acceptance starts.

On the assumed 4-CPU/16-GiB hosted runner, the service CPU quota sum matches the
runner CPUs and the service memory limits leave room for Firefox, host clients
and the OS. CPU quotas are ceilings, not reservations: host/browser CPU can
contend with services, so actual completion time still needs a hosted run.
The runner's actual host CPU count, Docker CPU count and Docker memory are saved
as safe metrics; its advertised size was not independently verified here.
`runtime.py up` reports capacity without enforcing an 8-CPU minimum. No capacity
VM startup or 8-CPU gate is introduced. Fair 1/2/3-worker scaling at 2 vCPU each
still needs its separate capacity/evidence path and cannot be inferred from CI.

## Offline verification and limitations

Using the root `.venv` from this worktree:

- Workflow regressions: seven passed. The actual embedded result validation
  accepts complete reports and rejects failed, public-only, missing-client and
  missing-MP4 reports. Artifact glob checks retain success/failure screenshots
  and results while excluding representative private files. The integration
  aggregate still requires the browser job to succeed.
- Ruff lint and format checks passed for the new tests; `git diff --check` passed.
- YAML parsed; all 43 workflow shell blocks passed `bash -n`, and all four
  embedded Python blocks parsed with `ast.parse`. None were executed against
  Docker or services.
- Compose resource totals were calculated from YAML without Compose execution.

No Docker command, live service, browser, build, VM operation or GitHub operation
was run locally. The integration worktree was not accessed. `actionlint` was not
installed; no tooling was downloaded. Hosted Linux e2e, cold-build timing, Firefox
codecs and timeout adequacy remain unverified until the parent integrates this
commit and the normal CI workflow runs. Existing acceptance scripts are consumed
as-is; changes the parent makes to those scripts require the integrated head's
CI run. This report claims offline validation of CI wiring, not live acceptance.
