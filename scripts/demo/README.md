# Demo recording tools

Helpers for recording the section 6 demo clips against the live `dc2-live` stack. They read or
drive the real public endpoints and mock nothing. The clip plan is
`project-documentation/presentation/site/6-demo.html`.

| Script | What it does | Touches AWS |
|---|---|---|
| `warmup.py` | Wakes both auto-paused Aurora clusters. It runs the release smoke's read-only checks (login, Media job list, Processing job batch, both health routes, anonymous denial) and retries while they answer 502/503/504. | Read-only public API calls |
| `fixtures.py` | Makes N distinct copies of a short MP4 in folders `<lane>-1..N`. For `--lane standard`, each copy gets a 70 MiB `free` box appended, like the sl1021 fixture, so its size is above 64 MiB and below 100 MiB and the job goes to Fargate. For `--lane short`, each copy gets a 64-byte tagged `free` box. | None (local files) |
| `perf_report.py` | Turns a `generator.log` tee into one self-contained `report.html`. It checks the samples' SHA-256 against `DC2-RESULT` and recomputes every figure from the raw rows. It adds an optional lane comparison from a short-lane receipt. | None (local files) |

Run everything from the repository root. The scripts use only the standard library, so the
system `python3` works. The Publisher needs the locked venv (`$DEMO_PY`).

## Session variables (from the private recording notes, never committed)

```bash
export DEMO_PRIVATE="$HOME/dc2-demo-private"   # outside Git; chmod 700
export DEMO_SITE=SITE.cloudfront.net            # CloudFront host of the live site
export DEMO_API_BASE=https://API_ID.execute-api.ap-southeast-1.amazonaws.com
export DEMO_API_ID=API_ID
export DEMO_EMAIL_A=owner-a@EXAMPLE
mkdir -p "$DEMO_PRIVATE" && chmod 700 "$DEMO_PRIVATE"
```

## 1. Fixtures (off-camera, once)

```bash
ffmpeg -y -loglevel error -f lavfi -i 'testsrc2=duration=24:size=640x360:rate=30' \
  -f lavfi -i 'sine=frequency=440:duration=24' -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest \
  "$DEMO_PRIVATE/short24.mp4"
python3 -m scripts.demo.fixtures "$DEMO_PRIVATE/short24.mp4" "$DEMO_PRIVATE" --lane standard --count 5
python3 -m scripts.demo.fixtures "$DEMO_PRIVATE/short24.mp4" "$DEMO_PRIVATE" --lane short --count 4
```

This writes `standard-1..5/short24-standard-N.mp4` (about 72.4 MiB each) and
`short-1..4/short24-short-N.mp4`. The helper checks the MP4 box structure and the size window.
It cannot check duration or height, so the source must be a clip of 60 s or less at 1080p or
less (the command above makes one).

## 2. Warm-up (before every take; record within about ten minutes)

```bash
DEMO_EMAIL="$DEMO_EMAIL_A" python3 -m scripts.demo.warmup --base-url "https://$DEMO_SITE"
```

The password is read at a hidden prompt. `DEMO_PASSWORD` also works, but do not type it inline,
because that puts it in the shell history. Exit code 0 means every check answered. The output
shows only check names and status codes, for example `login [503, 200]` while a cluster wakes.

## 3. D5 performance run and report

```bash
RUN=perf-$(date -u +%Y%m%dT%H%M%SZ); D="$DEMO_PRIVATE/$RUN"; mkdir -p "$D"
aws apigatewayv2 get-stage --api-id "$DEMO_API_ID" --stage-name '$default' \
  --query DefaultRouteSettings --output json > "$D/stage.json"
START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DC2_BASE_URL="$DEMO_API_BASE" DC2_USERS=10 DC2_SECONDS=60 DC2_WARMUP=5 DC2_OTHER_SECONDS=5 DC2_LOGINS=5 \
  python3 -m scripts.aws.v1.proof.generator | tee "$D/generator.log" \
  | sed -n 's/^DC2-RESULT //p' | jq '{ok,users,routes}'
jq -n --arg started_utc "$START" --arg ended_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg base_url "$DEMO_API_BASE" --arg network_path "recorder to API Gateway over the internet" \
  --arg commit "$(git rev-parse HEAD)" --slurpfile stage "$D/stage.json" \
  '{started_utc:$started_utc,ended_utc:$ended_utc,base_url:$base_url,network_path:$network_path,commit:$commit,stage_throttle:$stage[0]}' \
  > "$D/environment.json"
python3 -m scripts.demo.perf_report --run-dir "$D" \
  --lane-receipt docs/results/engineering-20261021/short-lane-sl1021.json
(cd "$D" && python3 -m http.server 8765 --bind 127.0.0.1)   # open http://127.0.0.1:8765/report.html
```

The generator registers one throwaway account in the live Media database. Its sample clock is
monotonic, so the UTC window, target, throttle and commit come from `environment.json`. Without
that file the report says "not recorded". The report refuses a log whose samples do not match
their hash, or whose result line shows a failed `register` or `login` stage (a sleeping
database: warm up and rerun). The lane section is shown only with `--lane-receipt`. The
in-region r1017b row is read from
`docs/execution/aws/v1/evidence/cloud-proof-r1017b.json` and is labelled as reference.

## Tests

```bash
PYTHONPATH=. python -m pytest tests/dev/test_demo_tools.py -q -p scripts.dev.pytest_plugin --offline-fast
```
