# V4 bounded active-work evidence handoff

13 October 2026. Lane: `work/release-active-work`.
Owned changes: `scripts/dev/release.py`, `tests/dev/test_release.py`, this report.
Read the parent's `docs/execution/reviews/release-rereview.md` (V4 PASS at
`f5ba469ca2a43b243b4806f9adfffa4daf7f7353`) and current worklog. The requested
`V4/release-rereview.md` path was absent; the existing review above is the source.

The full evidence experiment now requires real active work in the good
promotion. Ordinary release/rollback and their public smoke behavior remain
unchanged. There are no runtime service changes, artificial processing delays,
forced failure, or additional framework. This reuses the runner's existing
public HTTPS authentication/upload helper, bounded command runner, owned
Processing diagnostic SELECTs, drain and private atomic evidence files. Scenario
is not imported: its standalone fixture subprocess has a separate timeout and
would bypass this runner's shared promotion deadline and command evidence.

## Behavior

1. Complete baseline public smoke, candidate build, artifact/scan proof,
   migration policy and source recheck before introducing the evidence upload.
2. For the good evidence promotion only, generate one actual 30-second 1280x720
   24fps testsrc2 MP4, with one encoding thread and ultrafast fixture encoding.
   Its command timeout is at most 30 seconds, also capped by the remaining
   original 600-second promotion budget. The ordinary smoke keeps its 1-second
   fixture. Upload through public `/api/upload` with the existing Secure cookie,
   local CA validation, origin restrictions and idempotency key.
3. Persist Asset ID and fixture hash/parameters immediately after acceptance.
   Poll public status until processing, then confirm the current Processing Job
   and Attempt via its owned database. Persist both UUIDs and confirmation time.
   A clip that finishes before confirmation is a failed evidence preparation;
   it is never silently replaced or retried.
4. Persist normal pending recovery intent. The drain's actual pre-stop SELECT
   must contain that exact unfinished current processing Attempt and processing
   Job. Persist the captured row and timestamp immediately before the existing
   worker stop with 60-second grace. An empty snapshot or a different/superseded
   attempt rejects the evidence; rollback follows existing pending-intent rules.
5. Use the unchanged bounded drain to require visible terminal outcomes for all
   captured attempts, including final claims. Record the evidence Attempt's
   terminal row, then observe matching `done` or `failed` through the public Job
   endpoint. Failed public outcomes also require a visible error; record only
   that error's presence. Persist the outcome before owner deletion. Delete this
   upload before candidate deployment/smoke, so it leaves no unfinished work in
   either public smoke workflow. Only real queued/processing status polls wait.
6. Run existing candidate public smoke and promotion checks. Then run the
   unchanged bad-image experiment, including actual API startup exit 42 and
   marker capture before restoration. The experiment must also match the good
   upload's captured/terminal rows against its nonempty drain record and contain
   its public outcome/deletion. Idle drains cannot pass the full experiment.

A successful drain inside the 60-second grace is valid V4 evidence. A visible
failure is accepted if it happens naturally; the runner does not force one.
Existing V2 supplies worker-kill evidence. A 30-second clip is media duration,
not a claim about processing wall time: actual capture and completion still need
the deferred live run. If this host processes it before capture, the runner
fails honestly. No measured live V4 result is asserted by this report.

Preparation, capture, public outcome and deletion share the original 600-second
promotion deadline. The 300-second drain and separate 300-second automatic
recovery budgets are unchanged. Cookies/passwords/capability URLs stay in memory;
the returned request closure is never serialized. Failed preparation can leave
its synthetic upload behind, identified by the saved Asset ID, as with existing
failed smoke behavior.

## Offline validation

Executed exclusively in this worktree with network guard, disabled bytecode/test
cache writes, and a dummy Docker socket:

```sh
PYTHONDONTWRITEBYTECODE=1 \
  DC2_DOCKER_HOST=unix:///offline-review-do-not-connect.sock \
  /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p no:cacheprovider \
  -p scripts.dev.pytest_plugin --offline-fast tests/dev -q
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
  check --no-cache scripts/dev/release.py tests/dev/test_release.py
git diff --check
```

Result: **199 passed in 3.81s** (107 release cases, including 26 new cases).
Ruff and whitespace checks passed. New coverage includes real helper control
flow with mocked HTTP/fixture boundaries, durable public/owned IDs, baseline and
proof ordering, rejection before upload on scan failure, ordinary release
isolation, early completion, public processing without owned confirmation,
pre-stop attempt identity/currentness, successful and naturally failed drain
outcomes before deletion, visible failure error, preparation/outcome deadline
exhaustion, no unnecessary wait, experiment artifact contents, and rejection of
vacuous/incomplete good evidence. Existing injected API failure gates remain
green. No Docker commands, builds, scans, browser, live HTTP, FFmpeg workloads,
shared VM operations, cloud operations or GitHub access were performed.

## Parent action after full benchmark and latency finish

Integrate this lane into the clean PR31 source; retain CI/independent review as
the parent workflow requires. Run no VM operations while the full benchmark,
latency work or other protected integration work still owns it. When those
finish, use a dedicated release run ID, separate from scaling namespaces, with
the normal TLS/private state and bootstrap images labeled for that clean
integrated revision. Baseline source/image proof must match; do not relabel old
images to satisfy it. Prepare the existing pinned scanner/cache as usual.

From the parent integrated repository, run the complete existing entry point:

```sh
.venv/bin/python scripts/dev/release.py evidence --run-id v4-active
```

Use `--additive-migrations` only if the parent has reviewed newly added
backward-compatible migrations. Expect exit 0 only for both the good active
promotion and actual exit-42 bad API/restoration experiment. Inspect private
`.local/runs/v4-active/releases/experiment-*.json` and the referenced good/bad
operation JSON files. Retain source revision/fingerprint, exact image proof and
scan, `active_work` Asset/Job/Attempt IDs and fixture hash, processing/capture
timestamps, nonempty `good_drain.attempts_before`, matching terminal
`attempts_after`, public terminal outcome/deletion, unchanged Media identities
and revisions, actual bad API CID/image/marker/exit 42, restored good IDs and
replicas, public smokes, cleared pending intent, and measured promotion/drain/
recovery times. Report successful drain as successful drain; do not claim kill
or lease expiry if neither happened. Live acceptance remains parent-owned.
