#!/usr/bin/env bash
# Steps of .github/workflows/cd.yml. Every command wraps an existing entry point
# (scripts.aws.v1.deploy / session / release / evidence, deploy/v1/build_and_verify.py); this file
# only supplies what an unattended runner lacks: a named AWS profile, a state directory that
# survives the runner, and the ordering the runbook asks an operator to follow by hand.
#
#   scripts/ci/cd.sh gate | state-pull | state-push | preflight | deploy | smoke | release |
#                    teardown
#
# Inputs arrive as CD_* environment variables set by the workflow (see its `env:` block).
# Nothing here prints a credential: the deploy tooling already screens its own output, and the
# only files copied to $CD_OUT/public (the workflow artifact) are the ones this script reduces
# to statuses and counts. The repository is public, so an artifact is public too.
set -euo pipefail

: "${CD_RUN_ID:?}" "${CD_OPERATION:?}"
CD_REGION=ap-southeast-1
CD_ACCOUNT=866865534361
CD_PROFILE=dc2-gha
# The tooling refuses ambient credentials and the default profile on purpose (it must never act
# for a principal nobody named), so the OIDC session lives in a named profile and the
# environment is cleaned in every step.
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
# Any path works for the tooling (operator-config.json names its files relative to itself); a
# fixed one keeps the runner and the laptop handoff in the runbook easy to compare.
CD_STATE="$HOME/dc2-state/$CD_RUN_ID"
CD_OUT="${RUNNER_TEMP:-/tmp}/cd-out"
PUBLIC="$CD_OUT/public"
SCOPE=(--profile "$CD_PROFILE" --region "$CD_REGION" --account "$CD_ACCOUNT")
PY=.venv/bin/python
export PYTHONPATH="$PWD"
mkdir -p "$PUBLIC"

fail() {
  echo "::error::$*"
  exit 1
}

summary() { # append a markdown line to the run summary
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "$*" >>"$GITHUB_STEP_SUMMARY"; fi
}

launch_flags() { # deploy-only options that change the stack's shape
  LAUNCH=()
  if [ "${CD_UNATTENDED_LAUNCH:-false}" = true ]; then LAUNCH+=(--unattended-launch); fi
}

cost_flags() {
  COST=(--budget-usd "$CD_BUDGET_USD" --planned-hours "$CD_PLANNED_HOURS")
  if [ -n "${CD_FORECAST_USD:-}" ]; then COST+=(--forecast-usd "$CD_FORECAST_USD"); fi
}

deploy_cli() { # deploy.py with this run's scope; prints the tool's JSON, returns its exit code
  "$PY" -m scripts.aws.v1.deploy "$@" "${SCOPE[@]}" --run-id "$CD_RUN_ID"
}

operator_config() { echo "$CD_STATE/operator-config.json"; }

output_value() { # one stack output; outputs.json is either a mapping or the CloudFormation list
  jq -r --arg key "$1" \
    'if type == "array" then (map({(.OutputKey): .OutputValue}) | add) else . end | .[$key]' \
    "$CD_STATE/outputs.json"
}

require_state() {
  [ -f "$CD_STATE/deploy-journal.json" ] ||
    fail "No journal for run '$CD_RUN_ID' in the state bucket; deploy it with this workflow first"
}

# ---------------------------------------------------------------------------------- gate
cmd_gate() {
  : "${CD_SHA:?}" "${CD_REPO:?}" "${CD_EVENT:?}"
  [[ $CD_RUN_ID =~ ^[a-z0-9]{2,16}$ ]] || fail "run_id must be 2-16 lowercase letters or digits"
  case "$CD_OPERATION" in
    preflight | deploy | release | teardown) ;;
    *) fail "Unknown operation '$CD_OPERATION'" ;;
  esac
  if [ "$CD_OPERATION" = release ]; then
    [[ ${CD_OWNER:-} =~ ^(media|processing)$ ]] || fail "release needs owner=media or processing"
  fi
  [[ $CD_BUDGET_USD =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "budget_usd must be a number"
  [[ $CD_PLANNED_HOURS =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "planned_hours must be a number"
  [[ -z ${CD_FORECAST_USD:-} || $CD_FORECAST_USD =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
    fail "forecast_usd must be a number or empty"
  if [ "$CD_EVENT" != workflow_dispatch ]; then
    # Only a dispatch is expected; anything else is held to the read-only preflight.
    [ "$CD_OPERATION" = preflight ] || fail "Only a dispatch may run '$CD_OPERATION'"
    echo "Non-dispatch trigger, read-only preflight: the CI gate applies to dispatched operations."
    return 0
  fi
  local runs total running latest
  runs=$(gh api "repos/$CD_REPO/actions/workflows/ci.yml/runs?head_sha=$CD_SHA&per_page=100" \
    --jq '.workflow_runs | sort_by(.created_at)
          | map({id, status, conclusion, event, url: .html_url})')
  total=$(jq length <<<"$runs")
  [ "$total" -gt 0 ] || fail "No CI run exists for $CD_SHA; push it through a pull request first"
  running=$(jq '[.[] | select(.status != "completed")] | length' <<<"$runs")
  [ "$running" -eq 0 ] || fail "CI is still running for $CD_SHA"
  latest=$(jq -c 'last' <<<"$runs")
  [ "$(jq -r .conclusion <<<"$latest")" = success ] ||
    fail "The latest CI run for $CD_SHA is $(jq -r .conclusion <<<"$latest"): $(jq -r .url <<<"$latest")"
  echo "CI is green for $CD_SHA: $(jq -r .url <<<"$latest")"
  summary "CI gate passed: $(jq -r .url <<<"$latest")"
}

# ---------------------------------------------------------------------------------- state
# The state directory holds the journal, stack outputs, the smoke account and (until the DSNs
# are published) the database role passwords. It goes to a private encrypted bucket, never to an
# artifact. Versioning on the bucket makes a mistaken --delete recoverable.
cmd_state_pull() {
  : "${CD_STATE_BUCKET:?}"
  mkdir -p "$CD_STATE"
  aws s3 sync "s3://$CD_STATE_BUCKET/runs/$CD_RUN_ID/" "$CD_STATE/" \
    --profile "$CD_PROFILE" --region "$CD_REGION" --only-show-errors
  # S3 keeps no modes; the tooling insists on 0700 directories and 0600 files.
  chmod -R go-rwx "$CD_STATE"
  chmod 700 "$CD_STATE"
}

cmd_state_push() {
  : "${CD_STATE_BUCKET:?}"
  [ -d "$CD_STATE" ] || return 0
  aws s3 sync "$CD_STATE/" "s3://$CD_STATE_BUCKET/runs/$CD_RUN_ID/" --delete \
    --exclude "frontend-dist/*" --exclude "*.run" --exclude "*.lock" \
    --profile "$CD_PROFILE" --region "$CD_REGION" --only-show-errors
}

# ---------------------------------------------------------------------------------- preflight
# Runbook step 0: reads only. A throwaway state directory, so it never touches a run's journal.
cmd_preflight() {
  cost_flags
  local state
  state=$(mktemp -d "$CD_OUT/preflight-XXXXXX")
  chmod 700 "$state"
  deploy_cli deploy --state-dir "$state" --assume-empty-counts "${COST[@]}" \
    --stop-after preflight | tee "$CD_OUT/preflight-raw.json"
  jq '{ok, mode, run_id, steps}' "$CD_OUT/preflight-raw.json" >"$PUBLIC/preflight.json"
  jq '[.deploy.steps.preflight.detail.checks[] | {check, status, detail}]' \
    "$state/deploy-journal.json" >"$PUBLIC/preflight-checks.json"
  jq -r '.[] | "| \(.check) | \(.status) | \(.detail // "") |"' \
    "$PUBLIC/preflight-checks.json" | {
    summary "| check | status | detail |"
    summary "|---|---|---|"
    while read -r line; do summary "$line"; done
  }
}

# ---------------------------------------------------------------------------------- deploy
cmd_deploy() {
  cost_flags
  launch_flags
  cmd_preflight
  if [ "$CD_EXECUTE" != true ]; then
    # Review only: an offline rehearsal of the exact commands, no images, nothing mutated.
    deploy_cli deploy --dry-run --seed-email "$CD_SEED_EMAIL" "${COST[@]}" ${LAUNCH[@]+"${LAUNCH[@]}"} \
      >"$PUBLIC/deploy-plan.txt"
    summary "Deploy was a review only (execute=false). Plan: deploy-plan.txt in the artifact."
    return 0
  fi
  mkdir -p "$CD_STATE"
  chmod 700 "$CD_STATE"
  local baseline="$CD_STATE/build-baseline.json"
  # Rebuilding after the images step pushed would change the local image id and the deploy
  # refuses that (ECR tags are immutable), so a resume reuses the recorded build.
  if [ -f "$baseline" ] &&
    jq -e '.deploy.steps.images.status == "done"' "$CD_STATE/deploy-journal.json" >/dev/null 2>&1; then
    echo "The images step already finished in an earlier attempt; keeping its build evidence."
  else
    # Native linux/amd64 on the runner, so no emulation. The evidence file is what --images takes.
    python3 deploy/v1/build_and_verify.py --out "$baseline"
  fi
  local code=0
  deploy_cli deploy --state-dir "$CD_STATE" --images "$baseline" --seed-email "$CD_SEED_EMAIL" \
    --assume-empty-counts "${COST[@]}" ${LAUNCH[@]+"${LAUNCH[@]}"} --execute | tee "$CD_OUT/deploy-raw.json" || code=$?
  jq '{ok, mode, run_id, steps}' "$CD_OUT/deploy-raw.json" >"$PUBLIC/deploy.json" || true
  return "$code"
}

# ---------------------------------------------------------------------------------- smoke
# Upload -> processing -> playback through the public URLs. V1 starts its finite encoder from the
# operator session (the unattended launcher is a V2 option), so the Publisher CLI alone would
# queue a job nothing encodes; the evidence harness starts the encoder and also checks HLS
# playback through CloudFront, so it is the smoke. The window is always closed again.
# `session open` returns once the stage reports the new throttle, but the data plane applies it a
# little later, so the first request after an open can still meet the closed 0/0 gate and get a
# 429 (seen after both the r1018b release smoke and the first laptop harness runs). Probe a cheap
# unauthenticated route until it stops answering 429; bounded, and a miss only warns because the
# smoke itself then reports the failure with its own evidence.
wait_gate_open() {
  local url code i
  url="$(output_value HttpApiUrl)/api/media/health"
  for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)
    if [ "$code" != 429 ]; then
      echo "Gateway gate open after $i probe(s) (HTTP $code)."
      return 0
    fi
    sleep 2
  done
  echo "::warning::The Gateway still answered 429 after 60 s"
}

cmd_smoke() {
  require_state
  local config label fixture rc=0 close_rc=0
  config=$(operator_config)
  label="smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
  fixture="$CD_OUT/smoke.mp4"
  ffmpeg -y -loglevel error -f lavfi -i "testsrc=duration=3:size=320x240:rate=15" \
    -f lavfi -i "sine=frequency=440:duration=3" -c:v libx264 -pix_fmt yuv420p -c:a aac \
    -shortest "$fixture"
  "$PY" -m scripts.aws.v1.session open --config "$config" "${SCOPE[@]}" >"$CD_OUT/session-open.json" ||
    fail "session open failed: $(jq -r '.error // empty' "$CD_OUT/session-open.json" 2>/dev/null)"
  wait_gate_open
  "$PY" -m scripts.aws.v1.evidence gateway "${SCOPE[@]}" --state-dir "$CD_STATE" --run-id "$label" \
    --fixture "$fixture" --only direct-upload-e2e --minutes 45 --job-timeout 900 \
    --skip-cross-database "not part of the CD smoke" >"$CD_OUT/smoke-raw.json" || rc=$?
  "$PY" -m scripts.aws.v1.session close --config "$config" "${SCOPE[@]}" --in-vpc-counts \
    >"$CD_OUT/session-close.json" || close_rc=$?
  "$PY" -m scripts.aws.v1.evidence summary --state-dir "$CD_STATE" --run-id "$label" \
    --out "$PUBLIC" >/dev/null || true
  local status
  status=$(jq -r '.issues["#63"].steps["direct-upload-e2e"].status // "MISSING"' \
    "$PUBLIC/cloud-proof-$label.json" 2>/dev/null || echo MISSING)
  summary "Upload to playback smoke: **$status** (session closed again: $([ "$close_rc" -eq 0 ] && echo yes || echo NO))"
  [ "$close_rc" -eq 0 ] || fail "session close failed; the public window may still be open"
  [ "$rc" -eq 0 ] && [ "$status" = PASS ] || fail "Upload-to-playback smoke did not pass ($status)"
}

# ---------------------------------------------------------------------------------- release
# One owner at a time, as the runbook's "Release proof on an existing stack": build the commit's
# images, push them with a fresh tag, let `evidence release-plan` verify digest, scan and bundle,
# then run the release CLI. A failed promotion is restored (UC-7) before the job fails.
cmd_release() {
  require_state
  cost_flags
  local owner="$CD_OWNER" rel="g${GITHUB_RUN_ID:-0}x${GITHUB_RUN_ATTEMPT:-1}"
  local baseline="$CD_STATE/build-baseline.json"
  [ -f "$baseline" ] || fail "No baseline build evidence in the state; was this run deployed by CD?"
  local only=(--only media)
  local names=(media)
  if [ "$owner" = processing ]; then
    only=(--only processing --only worker)
    names=(processing worker)
  fi
  mkdir -m 700 -p "$CD_STATE/release"
  local build="$CD_STATE/release/build-$rel.json"
  python3 deploy/v1/build_and_verify.py "${only[@]}" --out "$build"
  if [ "$CD_EXECUTE" != true ]; then
    summary "Release built and verified the $owner images only (execute=false); nothing was pushed."
    return 0
  fi
  [ "$CD_ATTEST_ADDITIVE" = true ] ||
    fail "Set attest_additive: the release plan records that the baseline and candidate images both work with this checkout's schema head"
  local sha docker_config uri_key
  sha=$(jq -r .source_sha "$build" | cut -c1-12)
  docker_config=$(mktemp -d)
  export DOCKER_CONFIG="$docker_config"
  local repo name
  for name in "${names[@]}"; do
    case "$name" in
      media) uri_key=MediaRepositoryUri ;;
      processing) uri_key=ProcessingRepositoryUri ;;
      worker) uri_key=WorkerRepositoryUri ;;
    esac
    repo=$(jq -r --arg k "$uri_key" '.deploy.outputs[$k]' "$CD_STATE/deploy-journal.json")
    aws ecr get-login-password --profile "$CD_PROFILE" --region "$CD_REGION" |
      docker login --username AWS --password-stdin "${repo%%/*}" >/dev/null
    docker tag "dc2-v1-$name:local-$sha" "$repo:$rel-$name"
    docker push --quiet "$repo:$rel-$name"
  done
  rm -rf "$docker_config"
  unset DOCKER_CONFIG

  # Attested by the green CI gate; the number is what the bundle records.
  local tests
  tests=$("$PY" -m pytest tests/v1 -m "not integration" -q -p scripts.dev.pytest_plugin \
    --offline-fast 2>&1 | tee "$CD_OUT/tests-v1.log" | grep -Eo '[0-9]+ passed' | head -1 | cut -d' ' -f1)
  [ -n "$tests" ] || fail "tests/v1 did not report a passed count"
  local attempt planned=1
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "$PY" -m scripts.aws.v1.evidence release-plan "${SCOPE[@]}" --state-dir "$CD_STATE" \
      --run-id "$CD_RUN_ID" --owner "$owner" --baseline-evidence "$baseline" \
      --good-run-id "$rel" --good-evidence "$build" --tests-passed "$tests" \
      --attest-schema-unchanged \
      --accept-unfixed docs/execution/aws/v1/scan-accepted-unfixed-20261017.json \
      --out "$CD_STATE/release" >"$CD_OUT/release-plan.json"; then
      planned=0
      break
    fi
    # ECR scans on push and the plan refuses an unfinished scan; anything else is final.
    grep -q "not COMPLETE yet" "$CD_OUT/release-plan.json" ||
      fail "release-plan failed: $(jq -r '.error // empty' "$CD_OUT/release-plan.json")"
    echo "Image scan still running (attempt $attempt); waiting 30 s."
    sleep 30
  done
  [ "$planned" -eq 0 ] || fail "ECR scan did not finish in time"

  local plan="$CD_STATE/release/plan.json" config gateway
  config=$(operator_config)
  gateway=$(output_value HttpApiUrl)
  local promote=(--config "$config" "${SCOPE[@]}" --deadline-seconds 1800 --owner "$owner"
    --bundle "$CD_STATE/release/$(jq -r .good.bundle "$plan")" --image-uri "$(jq -r .good.image_uri "$plan")"
    --migration-definition "$(jq -r '.good.migration_definition // .migration_definition' "$plan")"
    --target-revision "$(jq -r .target_revision "$plan")"
    --compat-evidence "$CD_STATE/release/$(jq -r .good.compat_evidence "$plan")"
    --smoke-url "$gateway" --smoke-credentials "$CD_STATE/smoke-credentials.json")
  if [ "$owner" = processing ]; then
    promote+=(--worker-definition "$(jq -r .good.worker_definition "$plan")")
  fi
  local restore=(--config "$config" "${SCOPE[@]}" --deadline-seconds 900
    --smoke-url "$gateway" --smoke-credentials "$CD_STATE/smoke-credentials.json")

  "$PY" -m scripts.aws.v1.session window --config "$config" "${SCOPE[@]}" >"$CD_OUT/session-window.json" ||
    fail "session window failed: $(jq -r '.error // empty' "$CD_OUT/session-window.json" 2>/dev/null)"
  local rc=0 outcome=promoted
  "$PY" -m scripts.aws.v1.release promote "${promote[@]}" >"$CD_OUT/release-promote.json" || rc=$?
  if [ "$rc" -ne 0 ]; then
    outcome=failed
    echo "::warning::promote failed; restoring the previous aliases (UC-7)"
    if "$PY" -m scripts.aws.v1.release restore "${restore[@]}" >"$CD_OUT/release-restore.json"; then
      outcome=restored
    else
      # A candidate that failed in its migration task has nothing to restore; abandon clears
      # the intent only when it can prove nothing moved.
      "$PY" -m scripts.aws.v1.release abandon --config "$config" "${SCOPE[@]}" --owner "$owner" \
        --reason "cd run ${GITHUB_RUN_ID:-local}" >"$CD_OUT/release-abandon.json" &&
        outcome=abandoned || outcome=restore-failed
    fi
    # The new definitions are unused after a failed promotion; a good one stays (the worker uses it).
    "$PY" -m scripts.aws.v1.evidence release-plan "${SCOPE[@]}" --state-dir "$CD_STATE" \
      --run-id "$CD_RUN_ID" --deregister "$plan" >/dev/null || true
  fi
  local close_rc=0
  "$PY" -m scripts.aws.v1.session close --config "$config" "${SCOPE[@]}" --in-vpc-counts \
    >"$CD_OUT/session-close.json" || close_rc=$?
  jq -n --arg outcome "$outcome" --arg owner "$owner" --arg release "$rel" \
    --slurpfile result "$CD_OUT/release-promote.json" \
    '{owner: $owner, release: $release, outcome: $outcome,
      smoke: ($result[0].result.smoke // $result[0].smoke // null),
      versions: ($result[0].result.versions // null)}' >"$PUBLIC/release.json" || true
  summary "Release of **$owner**: **$outcome** (window closed: $([ "$close_rc" -eq 0 ] && echo yes || echo NO))"
  [ "$close_rc" -eq 0 ] || fail "session close failed; the public window may still be open"
  [ "$outcome" = promoted ] || fail "Release did not complete: $outcome"
}

# ---------------------------------------------------------------------------------- teardown
cmd_teardown() {
  require_state
  # Plan first (inventory only, exit 3 = nothing deleted), exactly as the runbook orders it.
  local code=0
  deploy_cli teardown --state-dir "$CD_STATE" >"$CD_OUT/teardown-plan.json" || code=$?
  [ "$code" -eq 0 ] || [ "$code" -eq 3 ] || fail "teardown plan failed: $(cat "$CD_OUT/teardown-plan.json")"
  jq -r '.awaiting_execute // "plan complete"' "$CD_OUT/teardown-plan.json"
  if [ "$CD_EXECUTE" != true ]; then
    summary "Teardown was a plan only (execute=false)."
    return 0
  fi
  local extra=()
  if [ "${CD_SKIP_FINAL_SNAPSHOT:-false}" = true ]; then extra+=(--skip-final-snapshot); fi
  deploy_cli teardown --state-dir "$CD_STATE" --execute --confirm-run-id "$CD_RUN_ID" \
    "${extra[@]}" | tee "$CD_OUT/teardown-raw.json"
  jq '{ok, mode, run_id, steps,
       receipt: (.resources_remaining_receipt | {status, journal_steps})}' \
    "$CD_OUT/teardown-raw.json" >"$PUBLIC/teardown.json"
  summary "Teardown receipt: $(jq -r .receipt.status "$PUBLIC/teardown.json")"
}

command="${1:?usage: cd.sh <gate|state-pull|state-push|preflight|deploy|smoke|release|teardown>}"
case "$command" in
  gate) cmd_gate ;;
  state-pull) cmd_state_pull ;;
  state-push) cmd_state_push ;;
  preflight) cmd_preflight ;;
  deploy) cmd_deploy ;;
  smoke) cmd_smoke ;;
  release) cmd_release ;;
  teardown) cmd_teardown ;;
  *) fail "Unknown command '$command'" ;;
esac
