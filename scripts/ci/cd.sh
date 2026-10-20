#!/usr/bin/env bash
# Steps of .github/workflows/cd.yml. Every command wraps an existing entry point
# (scripts.aws.v1.deploy / session / release / evidence, deploy/v1/build_and_verify.py); this file
# only supplies what an unattended runner lacks: a named AWS profile, a state directory that
# survives the runner, and the ordering the runbook asks an operator to follow by hand.
#
# It targets one persistent, always-on environment (V2-live, #234): `deploy` creates it once and
# afterwards updates it in place, then releases every owner whose image changed.
#
#   scripts/ci/cd.sh gate | state-pull | state-push | preflight | deploy | smoke | release |
#                    teardown
#
# Inputs arrive as CD_* environment variables set by the workflow (see its `env:` block).
# Nothing here prints a credential: the deploy tooling already screens its own output, and the
# only files copied to $CD_OUT/public (the workflow artifact) are the ones this script reduces
# to statuses and counts. The repository is public, so an artifact is public too.
set -euo pipefail

: "${CD_ENVIRONMENT:?}" "${CD_OPERATION:?}"
CD_REGION=ap-southeast-1
CD_ACCOUNT=866865534361
CD_PROFILE=dc2-gha
# The tooling refuses ambient credentials and the default profile on purpose (it must never act
# for a principal nobody named), so the OIDC session lives in a named profile and the
# environment is cleaned in every step.
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
# Any path works for the tooling (operator-config.json names its files relative to itself); a
# fixed one keeps the runner and the laptop handoff in the runbook easy to compare.
CD_STATE="$HOME/dc2-state/$CD_ENVIRONMENT"
CD_OUT="${RUNNER_TEMP:-/tmp}/cd-out"
PUBLIC="$CD_OUT/public"
SCOPE=(--profile "$CD_PROFILE" --region "$CD_REGION" --account "$CD_ACCOUNT")
PY=.venv/bin/python
ACCEPT_UNFIXED=docs/execution/aws/v1/scan-accepted-unfixed-20261017.json
export PYTHONPATH="$PWD"
mkdir -p "$PUBLIC"

fail() {
  echo "::error::$*"
  exit 1
}

summary() { # append a markdown line to the run summary
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "$*" >>"$GITHUB_STEP_SUMMARY"; fi
}

cost_flags() {
  COST=(--budget-usd "$CD_BUDGET_USD" --planned-hours "$CD_PLANNED_HOURS")
  if [ -n "${CD_FORECAST_USD:-}" ]; then COST+=(--forecast-usd "$CD_FORECAST_USD"); fi
}

deploy_cli() { # deploy.py with this environment's scope; prints its JSON, returns its exit code
  local email=()
  if [ -n "${CD_BUDGET_EMAIL:-}" ]; then email=(--budget-alert-email "$CD_BUDGET_EMAIL"); fi
  "$PY" -m scripts.aws.v1.deploy "$@" "${SCOPE[@]}" --environment "$CD_ENVIRONMENT" \
    ${email[@]+"${email[@]}"}
}

journal_value() { # one jq expression over the deploy journal, empty when there is none
  jq -r "$1 // empty" "$CD_STATE/deploy-journal.json" 2>/dev/null || true
}

session_state() { # what the session journal records: open, closed, window, ...
  jq -r '.session // empty' "$CD_STATE/session/journal.json" 2>/dev/null || true
}

operator_config() { echo "$CD_STATE/operator-config.json"; }

output_value() { # one stack output; outputs.json is either a mapping or the CloudFormation list
  jq -r --arg key "$1" \
    'if type == "array" then (map({(.OutputKey): .OutputValue}) | add) else . end | .[$key]' \
    "$CD_STATE/outputs.json"
}

require_state() {
  [ -f "$CD_STATE/deploy-journal.json" ] ||
    fail "No journal for environment '$CD_ENVIRONMENT' in the state bucket; deploy it first"
}

# ---------------------------------------------------------------------------------- gate
cmd_gate() {
  : "${CD_SHA:?}" "${CD_REPO:?}" "${CD_EVENT:?}"
  [[ $CD_ENVIRONMENT =~ ^[a-z0-9]{2,16}$ ]] ||
    fail "environment must be 2-16 lowercase letters or digits"
  case "$CD_OPERATION" in
    preflight | deploy | release | teardown) ;;
    *) fail "Unknown operation '$CD_OPERATION'" ;;
  esac
  if [ "$CD_OPERATION" = release ]; then
    [[ ${CD_OWNER:-} =~ ^(media|processing)$ ]] || fail "release needs owner=media or processing"
  fi
  if [ "${CD_BAD_CANDIDATE:-false}" = true ]; then
    [ "$CD_OPERATION" = release ] && [ "${CD_EXECUTE:-false}" = true ] ||
      fail "bad_candidate only applies to a release with execute=true"
  fi
  [[ $CD_BUDGET_USD =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "budget_usd must be a number"
  [[ $CD_PLANNED_HOURS =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "planned_hours must be a number"
  [[ -z ${CD_FORECAST_USD:-} || $CD_FORECAST_USD =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
    fail "forecast_usd must be a number or empty"
  if [ "$CD_OPERATION" = teardown ] && [ "${CD_EXECUTE:-false}" = true ]; then
    # The environment is meant to outlive every deploy; deleting it takes its name, typed.
    [ "${CD_CONFIRM:-}" = "$CD_ENVIRONMENT" ] ||
      fail "teardown with execute needs confirm=$CD_ENVIRONMENT"
  fi
  case "$CD_EVENT" in
    workflow_dispatch) ;;
    # The automatic in-place update after green CI on Main (cd.yml filters the CI run).
    workflow_run) [ "$CD_OPERATION" = deploy ] || fail "A CI completion may only deploy" ;;
    *)
      # Anything else is held to the read-only preflight.
      [ "$CD_OPERATION" = preflight ] || fail "Only a dispatch may run '$CD_OPERATION'"
      echo "Non-dispatch trigger, read-only preflight: the CI gate applies to operations."
      return 0
      ;;
  esac
  # Recovery and read-only inspection remain available even when CI evidence has expired.
  case "$CD_OPERATION" in
    deploy | release) python3 -m scripts.ci.cd_gate ;;
  esac
}

# ---------------------------------------------------------------------------------- state
# The state directory holds the journal, stack outputs, the smoke account and (until the DSNs
# are published) the database role passwords. It goes to a private encrypted bucket, never to an
# artifact. Versioning on the bucket makes a mistaken --delete recoverable.
cmd_state_pull() {
  : "${CD_STATE_BUCKET:?}"
  mkdir -p "$CD_STATE"
  aws s3 sync "s3://$CD_STATE_BUCKET/envs/$CD_ENVIRONMENT/" "$CD_STATE/" \
    --profile "$CD_PROFILE" --region "$CD_REGION" --only-show-errors
  # S3 keeps no modes; the tooling insists on 0700 directories and 0600 files.
  chmod -R go-rwx "$CD_STATE"
  chmod 700 "$CD_STATE"
}

cmd_state_push() {
  : "${CD_STATE_BUCKET:?}"
  [ -d "$CD_STATE" ] || return 0
  aws s3 sync "$CD_STATE/" "s3://$CD_STATE_BUCKET/envs/$CD_ENVIRONMENT/" --delete \
    --exclude "frontend-dist/*" --exclude "*.run" --exclude "*.lock" \
    --profile "$CD_PROFILE" --region "$CD_REGION" --only-show-errors
}

# ---------------------------------------------------------------------------------- preflight
# Runbook step 0: reads only. A throwaway state directory, so it never touches the journal; a
# copy of the journal tells it whether this is an update of the established environment (whose
# routine updates the cost guard reports but does not block).
cmd_preflight() {
  cost_flags
  local state
  state=$(mktemp -d "$CD_OUT/preflight-XXXXXX")
  chmod 700 "$state"
  if [ -f "$CD_STATE/deploy-journal.json" ]; then
    install -m 600 "$CD_STATE/deploy-journal.json" "$state/deploy-journal.json"
  fi
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
scan_images() ( # receipt local|registry|resume image...; reports survive state sync
  set -euo pipefail
  local build="$1" mode="$2" name config_id reference image_src
  shift 2
  [ "$#" -gt 0 ] || fail "An explicit image set is required for the Trivy gate"
  local reports="$CD_STATE/scans/g${GITHUB_RUN_ID:-0}x${GITHUB_RUN_ATTEMPT:-1}/$(basename "$build" .json)-$mode"
  mkdir -p "$reports"
  local args=(--receipt "$build" --reports "$reports" --out "$reports/summary.json" --attach)
  if [ "$mode" = registry ] || [ "$mode" = resume ]; then
    # Always rescan retained/resumed immutable digests; never rebuild an old recipe.
    local docker_config
    docker_config=$(mktemp -d)
    export DOCKER_CONFIG="$docker_config"
    trap 'rm -rf "$docker_config"' EXIT
    aws ecr get-login-password --profile "$CD_PROFILE" --region "$CD_REGION" |
      docker login --username AWS --password-stdin \
        "$CD_ACCOUNT.dkr.ecr.$CD_REGION.amazonaws.com" >/dev/null
  fi
  if [ "$mode" = registry ]; then
    args+=(--sha "") # retained owner companions keep their original source
  elif [ "$mode" = local ] || [ "$mode" = resume ]; then
    args+=(--sha "$(git rev-parse HEAD)")
  else
    fail "Unknown scan image source '$mode'"
  fi
  # Invalidate previous acceptance before invoking a scanner. A process failure or a scanner
  # that writes no report must never leave a reusable PASS from an earlier attempt.
  jq 'reduce $ARGS.positional[] as $name (. ; .images[$name].trivy_scan = {status: "NOT_RUN"})' \
    "$build" --args "$@" >"$reports/build-pending.json"
  chmod 600 "$reports/build-pending.json"
  mv "$reports/build-pending.json" "$build"
  for name in "$@"; do
    config_id=$(jq -er --arg name "$name" '.images[$name].config_id' "$build")
    reference="$config_id"
    image_src=docker
    if [ "$mode" = registry ] ||
      { [ "$mode" = resume ] && [ -n "$(journal_value ".deploy.images.$name.digest")" ]; }; then
      reference=$(journal_value ".deploy.images.$name.uri")
      [[ "$reference" == *@sha256:* ]] || fail "No immutable deployed digest for $name"
      image_src=remote
    fi
    # A scanner-process failure exits before an old report can be admitted. Policy validation
    # requires both Debian and Python targets even when they contain no HIGH/CRITICAL rows.
    rm -f "$reports/trivy-$name.json"
    trivy image --image-src "$image_src" \
      --scanners vuln --pkg-types os,library --severity HIGH,CRITICAL --ignore-unfixed=false \
      --ignorefile /dev/null --exit-code 0 --format json --output "$reports/trivy-$name.json" \
      "$reference"
    args+=(--owner "$name")
  done
  "$PY" -m scripts.ci.v1_scan "${args[@]}"
  cp "$reports/summary.json" "$PUBLIC/scan-$(basename "$build" .json)-$mode.json"
)

# The first deploy creates the environment from this commit's images. Every later deploy is an
# in-place update: the stack is updated as a change set from this checkout (code untouched),
# then every owner whose image changed ships through its own release, smoke and restore.
cmd_deploy() {
  if [ "${CD_EVENT:-}" = workflow_run ] && [ "$(journal_value .deploy.established)" != true ]; then
    # The first deploy creates billable infrastructure and waits for a human (#238): only an
    # explicit dispatch may do it. A merge before then changes nothing in the account.
    echo "::notice::$CD_ENVIRONMENT is not established; the first deploy must be dispatched by hand"
    summary "Skipped: \`$CD_ENVIRONMENT\` is not established yet. Its first deploy is an explicit dispatch."
    return 0
  fi
  cost_flags
  cmd_preflight
  if [ "$CD_EXECUTE" != true ]; then
    # Review only: an offline rehearsal of the exact commands, no images, nothing mutated.
    deploy_cli deploy --dry-run --seed-email "$CD_SEED_EMAIL" "${COST[@]}" \
      >"$PUBLIC/deploy-plan.txt"
    summary "Deploy was a review only (execute=false). Plan: deploy-plan.txt in the artifact."
    return 0
  fi
  mkdir -p "$CD_STATE"
  chmod 700 "$CD_STATE"
  local baseline="$CD_STATE/build-baseline.json" images scan_mode=local
  if [ "$(journal_value .deploy.established)" = true ]; then
    # Built to compare with what runs; only a changed owner's images are ever pushed.
    images="$CD_OUT/build-candidate.json"
    python3 deploy/v1/build_and_verify.py --out "$images"
  elif [ -f "$baseline" ] &&
    [ "$(journal_value '[.deploy.images[] | select(.local_id)] | length')" -gt 0 ]; then
    # Keep even a partial push's evidence. Rescan pushed digests; an unpushed config must still
    # exist locally. Never rebuild over an immutable tag or erase its original source.
    echo "A first deploy already started publishing; keeping its original build evidence."
    images="$baseline"
    scan_mode=resume
  else
    # Native linux/amd64 on the runner, so no emulation. The evidence file is what --images takes.
    python3 deploy/v1/build_and_verify.py --out "$baseline"
    images="$baseline"
  fi
  if [ "$(journal_value .deploy.established)" != true ]; then
    scan_images "$images" "$scan_mode" media processing worker
  fi
  local code=0
  deploy_cli deploy --state-dir "$CD_STATE" --images "$images" --seed-email "$CD_SEED_EMAIL" \
    --accept-unfixed "$ACCEPT_UNFIXED" --assume-empty-counts "${COST[@]}" --execute \
    | tee "$CD_OUT/deploy-raw.json" || code=$?
  jq '{ok, mode, run_id, steps}' "$CD_OUT/deploy-raw.json" >"$PUBLIC/deploy.json" || true
  [ "$code" -eq 0 ] || return "$code"
  local owners
  owners=$(journal_value '.deploy.steps.images.detail.changed_owners | arrays | join(" ")')
  summary "Stack: $(journal_value '.deploy.steps.applications.detail
    | if .no_changes then "no changes" else "\(.change_kind) with \(.changes | length) change(s)" end'
  ); owners to release: ${owners:-none}"
  [ -n "$owners" ] || return 0
  if [ "$(session_state)" != open ]; then
    echo "::warning::The kill switch is on; the release of $owners waits until it is off"
    summary "Releases deferred (kill switch on): **$owners**. Turn it off, then dispatch a deploy."
    return 0
  fi
  release_changed_owners "$images" "$owners"
}

# A release whose migrations changed needs a human's word that the previous image works with the
# new schema (attest_additive); green CI does not show that. Others ship now. Everything is read
# from the journal before the first release: each release's adoption re-runs the deploy, which
# rewrites the images step and with it `migrations_changed`.
release_changed_owners() { # images-evidence owners
  local images="$1" owners="$2" owner name deferred=() rebuilt migrations
  rebuilt=$(journal_value '.deploy.steps.images.detail.changed_images | arrays | join(" ")')
  migrations=$(journal_value '.deploy.steps.images.detail.migrations_changed | arrays | join(" ")')
  for owner in $owners; do
    if [[ " $migrations " == *" $owner "* ]]; then
      deferred+=("$owner")
      continue
    fi
    local mine=()
    for name in $rebuilt; do
      case "$owner:$name" in
        media:media | processing:processing | processing:worker) mine+=("$name") ;;
      esac
    done
    release_owner "$owner" "$images" true "${mine[@]}"
  done
  if [ "${#deferred[@]}" -gt 0 ]; then
    summary "Not released: **${deferred[*]}** changed its migrations. Dispatch \`release\` with attest_additive."
    fail "${deferred[*]} changed migrations; release it by hand with attest_additive=true"
  fi
}

# ---------------------------------------------------------------------------------- smoke
# Upload -> processing -> playback through the public URLs, on the always-on environment as any
# user meets it: no session is opened or closed, and the launcher starts the encoder on enqueue.
# The evidence harness is the smoke because it also checks HLS playback through CloudFront.
# A release reopens the session just before its smoke, and `session open` returns once the stage
# reports the new throttle while the data plane applies it a little later, so the first request
# after an open can still meet the closed 0/0 gate and get a
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
  if [ "$(journal_value .deploy.established)" != true ]; then
    echo "::notice::$CD_ENVIRONMENT is not established; nothing to smoke-test"
    return 0
  fi
  require_state
  local label fixture rc=0
  if [ "$(session_state)" != open ]; then
    echo "::warning::The kill switch is on (session $(session_state)); the smoke is skipped"
    summary "Smoke skipped: the kill switch is on. Turn it off with \`session open --unattended\`."
    return 0
  fi
  label="smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
  fixture="$CD_OUT/smoke.mp4"
  ffmpeg -y -loglevel error -f lavfi -i "testsrc=duration=3:size=320x240:rate=15" \
    -f lavfi -i "sine=frequency=440:duration=3" -c:v libx264 -pix_fmt yuv420p -c:a aac \
    -shortest "$fixture"
  wait_gate_open
  local attempt
  for attempt in 1 2; do
    rc=0
    "$PY" -m scripts.aws.v1.evidence gateway "${SCOPE[@]}" --state-dir "$CD_STATE" --run-id "$label" \
      --fixture "$fixture" --only direct-upload-e2e --minutes 45 --job-timeout 900 \
      --skip-cross-database "not part of the CD smoke" >"$CD_OUT/smoke-raw.json" || rc=$?
    [ "$rc" -ne 0 ] || break
    # A probe that got through does not prove every Gateway node has the new limit; one that
    # did not still answers 429 for a while (r1018b: HTTP 429 on the first reservation after a
    # probe had succeeded). Retry once, and keep the first answer next to the second.
    if [ "$attempt" -eq 1 ] && grep -q "HTTP 429" "$CD_OUT/smoke-raw.json"; then
      cp "$CD_OUT/smoke-raw.json" "$CD_OUT/smoke-raw-attempt1.json"
      echo "::warning::smoke attempt 1 was throttled (HTTP 429); retrying once after 30 s"
      summary "Smoke attempt 1 was throttled by the Gateway (HTTP 429) and was retried once."
      sleep 30
      continue
    fi
    break
  done
  "$PY" -m scripts.aws.v1.evidence summary --state-dir "$CD_STATE" --run-id "$label" \
    --out "$PUBLIC" >/dev/null || true
  local status
  status=$(jq -r '.issues["#63"].steps["direct-upload-e2e"].status // "MISSING"' \
    "$PUBLIC/cloud-proof-$label.json" 2>/dev/null || echo MISSING)
  summary "Upload to playback smoke: **$status**"
  [ "$rc" -eq 0 ] && [ "$status" = PASS ] || fail "Upload-to-playback smoke did not pass ($status)"
}

# ---------------------------------------------------------------------------------- release
# One owner at a time, as the runbook's "Release proof on an existing stack": build the commit's
# images, push them with a fresh tag, let `evidence release-plan` verify digest, scan and bundle,
# then run the release CLI. A failed promotion is restored (UC-7) before the job fails.
# Deliberate fault for the rollback proof (bad_candidate=true): commit, on the runner only, a
# Lambda handler that points database TLS at a CA bundle that is not RDS's. The image still
# builds, passes its offline checks and migrates, then fails the release smoke (login and the
# job calls), which is the path that must trigger the automatic restore. Nothing is pushed.
inject_bad_candidate() { # owner
  local file var
  case "$1" in
    media) file=media/lambda_handler.py var=MEDIA_POSTGRES_SSL_CA ;;
    processing) file=processing/lambda_handler.py var=PROCESSING_DATABASE_CA_FILE ;;
    *) fail "No bad candidate for owner '$1'" ;;
  esac
  [ -f "$file" ] || fail "$file not found"
  {
    printf 'import os\nimport certifi\n\nos.environ["%s"] = certifi.where()\n\n' "$var"
    cat "$file"
  } >"$file.new" && mv "$file.new" "$file"
  git -c user.name=cd-fault-injection -c user.email=cd@invalid commit -q -am \
    "release proof: Lambda-only non-RDS CA bundle (migrates, must fail the smoke)"
}

cmd_release() {
  require_state
  local owner="$CD_OWNER" rel="g${GITHUB_RUN_ID:-0}x${GITHUB_RUN_ATTEMPT:-1}"
  local only=(--only media)
  if [ "$owner" = processing ]; then only=(--only processing --only worker); fi
  mkdir -m 700 -p "$CD_STATE/release"
  local build="$CD_STATE/release/build-$rel.json"
  if [ "${CD_BAD_CANDIDATE:-false}" = true ]; then
    inject_bad_candidate "$owner"
    summary "bad_candidate: the $owner candidate was built with a non-RDS database CA on purpose."
  fi
  python3 deploy/v1/build_and_verify.py "${only[@]}" --out "$build"
  if [ "$CD_EXECUTE" != true ]; then
    summary "Release built and verified the $owner images only (execute=false); nothing was pushed."
    return 0
  fi
  [ "$CD_ATTEST_ADDITIVE" = true ] ||
    fail "Set attest_additive: the release plan records that the baseline and candidate images both work with this checkout's schema head"
  local rebuilt=(media)
  if [ "$owner" = processing ]; then rebuilt=(processing worker); fi
  release_owner "$owner" "$build" false "${rebuilt[@]}"
}

# One owner's release on the always-on environment, online: nothing is closed. The release CLI's
# --online mode holds the online invariant instead of quiescence (consumers and schedules on as
# recorded). A promoted release is then adopted: its images become the journal's and the stack
# is updated to name them, which is also what moves the launcher's WorkerTaskDefinition to the
# released worker; until then the launcher keeps starting the previous one, which is fine
# because a release is additive. The environment is never left closed by a failure here,
# because it is never closed. `automatic` is the deploy's own
# release of a changed owner whose migrations did not change (cmd_deploy decides that); a
# manual dispatch still requires attest_additive. Remaining arguments name the owner's images
# that were rebuilt; the others are kept exactly as they run (their build inputs did not change).
release_owner() { # owner build-evidence automatic rebuilt-image...
  local owner="$1" build="$2" automatic="$3" rel="g${GITHUB_RUN_ID:-0}x${GITHUB_RUN_ATTEMPT:-1}"
  shift 3
  local rebuilt=("$@")
  local baseline="$CD_STATE/build-baseline.json"
  [ -f "$baseline" ] || fail "No baseline build evidence in the state; was this environment deployed by CD?"
  [ "$(session_state)" = open ] ||
    fail "The kill switch is on (session $(session_state)): releases wait until \`session open --unattended\`"
  cost_flags
  local names=(media)
  if [ "$owner" = processing ]; then names=(processing worker); fi
  mkdir -m 700 -p "$CD_STATE/release"
  if [ "$automatic" = true ]; then summary "Releasing **$owner**: rebuilt ${rebuilt[*]}."; fi
  scan_images "$build" local "${rebuilt[@]}"
  scan_images "$baseline" registry "${names[@]}"
  local docker_config uri_key repo name kept=()
  docker_config=$(mktemp -d)
  export DOCKER_CONFIG="$docker_config"
  for name in "${names[@]}"; do
    case "$name" in
      media) uri_key=MediaRepositoryUri ;;
      processing) uri_key=ProcessingRepositoryUri ;;
      worker) uri_key=WorkerRepositoryUri ;;
    esac
    repo=$(jq -r --arg k "$uri_key" '.deploy.outputs[$k]' "$CD_STATE/deploy-journal.json")
    if [[ " ${rebuilt[*]} " == *" $name "* ]]; then
      aws ecr get-login-password --profile "$CD_PROFILE" --region "$CD_REGION" |
        docker login --username AWS --password-stdin "${repo%%/*}" >/dev/null
      # Publish the accepted config itself; a mutable local tag cannot substitute a rebuild.
      docker tag "$(jq -er --arg name "$name" '.images[$name].config_id' "$build")" "$repo:$rel-$name"
      docker push --quiet "$repo:$rel-$name"
    else
      # Kept as it runs: the running manifest gains this release's tag, nothing is rebuilt.
      kept+=("$name")
      local reply
      reply=$(aws ecr batch-get-image --repository-name "${repo#*/}" --profile "$CD_PROFILE" \
        --region "$CD_REGION" --output json \
        --image-ids "imageDigest=$(journal_value ".deploy.images.$name.digest")")
      aws ecr put-image --repository-name "${repo#*/}" --image-tag "$rel-$name" \
        --image-manifest "$(jq -r '.images[0].imageManifest' <<<"$reply")" \
        --image-manifest-media-type "$(jq -r '.images[0].imageManifestMediaType' <<<"$reply")" \
        --profile "$CD_PROFILE" --region "$CD_REGION" >/dev/null
    fi
  done
  rm -rf "$docker_config"
  unset DOCKER_CONFIG
  # The release's evidence: the rebuilt images from this build, the kept ones as they were built.
  local good="$CD_STATE/release/good-$rel-$owner.json"
  # `--args` goes after the file: before it, jq takes the file as one more positional string and
  # reads an empty stdin, which release-plan then rejects as unreadable JSON.
  jq --slurpfile base "$baseline" '.images += ($base[0].images
      | with_entries(select(.key as $k | $ARGS.positional | index($k))))' \
    "$build" --args ${kept[@]+"${kept[@]}"} >"$good"
  chmod 600 "$good"

  # Attested by the green CI gate; the number is what the bundle records.
  local tests
  tests=$("$PY" -m pytest tests/v1 -m "not integration" -q -p scripts.dev.pytest_plugin \
    --offline-fast 2>&1 | tee "$CD_OUT/tests-v1.log" | grep -Eo '[0-9]+ passed' | head -1 | cut -d' ' -f1)
  [ -n "$tests" ] || fail "tests/v1 did not report a passed count"
  local attempt planned=1
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if "$PY" -m scripts.aws.v1.evidence release-plan "${SCOPE[@]}" --state-dir "$CD_STATE" \
      --run-id "$CD_ENVIRONMENT" --owner "$owner" --baseline-evidence "$baseline" \
      --good-run-id "$rel" --good-evidence "$good" --tests-passed "$tests" \
      --attest-schema-unchanged \
      --accept-unfixed "$ACCEPT_UNFIXED" \
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
  local promote=(--config "$config" "${SCOPE[@]}" --online --deadline-seconds 1800 --owner "$owner"
    --bundle "$CD_STATE/release/$(jq -r .good.bundle "$plan")" --image-uri "$(jq -r .good.image_uri "$plan")"
    --migration-definition "$(jq -r '.good.migration_definition // .migration_definition' "$plan")"
    --target-revision "$(jq -r .target_revision "$plan")"
    --compat-evidence "$CD_STATE/release/$(jq -r .good.compat_evidence "$plan")"
    --smoke-url "$gateway" --smoke-credentials "$CD_STATE/smoke-credentials.json")
  if [ "$owner" = processing ]; then
    promote+=(--worker-definition "$(jq -r .good.worker_definition "$plan")")
  fi
  local restore=(--config "$config" "${SCOPE[@]}" --online --deadline-seconds 900
    --smoke-url "$gateway" --smoke-credentials "$CD_STATE/smoke-credentials.json")

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
      "$PY" -m scripts.aws.v1.release abandon --config "$config" "${SCOPE[@]}" --online \
        --owner "$owner" --reason "cd run ${GITHUB_RUN_ID:-local}" \
        >"$CD_OUT/release-abandon.json" && outcome=abandoned || outcome=restore-failed
    fi
    # The plan's task definition revisions stay registered: they cost nothing, and a revision
    # another record still names must never disappear.
  fi
  jq -n --arg outcome "$outcome" --arg owner "$owner" --arg release "$rel" \
    --slurpfile result "$CD_OUT/release-promote.json" \
    '{owner: $owner, release: $release, outcome: $outcome,
      smoke: ($result[0].result.smoke // $result[0].smoke // null),
      versions: ($result[0].result.versions // null)}' >"$PUBLIC/release-$owner.json" || true
  summary "Release of **$owner**: **$outcome** (online; kept as running: ${kept[*]:-none})"
  if [ "${CD_BAD_CANDIDATE:-false}" = true ]; then
    # The proof passes only when the bad candidate was caught and rolled back. A promotion would
    # mean the smoke let a broken release through; anything else means the restore did not work.
    [ "$outcome" = restored ] || fail "The deliberately bad candidate ended '$outcome', not restored"
    summary "Rollback verified: the bad $owner candidate failed its smoke and the previous aliases were restored."
    return 0
  fi
  [ "$outcome" = promoted ] || fail "Release did not complete: $outcome"
  # Adopt: the journal, the baseline and then the stack name the released images. A failure here
  # leaves the Lambdas on the release and the launcher on the previous worker, both of which
  # work; rerunning the deploy finishes the adoption.
  deploy_cli adopt-release --state-dir "$CD_STATE" --owner "$owner" \
    --release-dir "$CD_STATE/release" --release-tag "$rel" >"$CD_OUT/adopt-$owner.json" ||
    fail "Adopting the $owner release failed: $(jq -r '.error // empty' "$CD_OUT/adopt-$owner.json")"
  local merged="$CD_STATE/build-baseline.next.json"
  # Same `--args` ordering as the good-evidence merge above: the baseline file comes first.
  jq --slurpfile built "$good" '.images += ($built[0].images
      | with_entries(select(.key as $k | $ARGS.positional | index($k))))' \
    "$baseline" --args "${names[@]}" >"$merged"
  [ -s "$merged" ] || fail "The merged baseline is empty; keeping the previous one"
  chmod 600 "$merged"
  mv "$merged" "$baseline"
  deploy_cli deploy --state-dir "$CD_STATE" --images "$baseline" --seed-email "$CD_SEED_EMAIL" \
    --assume-empty-counts "${COST[@]}" --stop-after applications --execute \
    >"$CD_OUT/adopt-stack-$owner.json" ||
    fail "The stack update naming the released $owner images failed; the release itself serves. See adopt-stack-$owner.json"
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
  deploy_cli teardown --state-dir "$CD_STATE" --execute --confirm-run-id "$CD_ENVIRONMENT" \
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
  inject-bad-candidate) inject_bad_candidate "${2:?owner}" ;;
  *) fail "Unknown command '$command'" ;;
esac
