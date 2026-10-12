# V4 release review R1–R3 corrections

13 October 2026, Singapore. Reviewed base:
`fcb0bf656363229c548e7770c2dd8a7a1c343156`.
Implementation: `5418bf6b07bd058f6c9b38be182270b329bfd98c`.
Validated source/test content is byte-identical to that implementation commit.

Only `scripts/dev/release.py`, `tests/dev/test_release.py` and this report are
changed. The supplied `release-review.md` remains unchanged (SHA-256
`4bb86cd8b97f90c65a0f29a27fc1860fd76a6f2bc0f113e25b49ec17e30ebd00`).

## Corrections

- **R1:** Synthetic bad builds tag the retained immutable ID with a unique,
  operation-owned local parent tag. The retained ID is inspected, and the tag
  binding is checked immediately before and after build. The Dockerfile uses
  that supported named reference with `--pull=false` and no build networking.
  Journals retain the parent tag, immutable ID, verification times and
  `build.derived_from`. Deployment, artifact tests, scan, promotion and rollback
  continue selecting immutable IDs. Injected releases must derive from the
  tested running baseline. A tag mismatch rejects the build.
- **R2:** `candidate-migration` and `candidate-startup` are separate timestamped
  steps. A startup failure captures `candidate_failure` before restoration:
  API CID, exact image ID, injection label, status, exit code, OOM/runtime-error
  flags, start/finish times, and presence of the generated startup fault marker.
  Docker log output is hashed; raw output is not journaled. The experiment
  requires a distinct injected API image, successful migration, failed startup,
  an actually started/exited container with exit 42 and its declared marker,
  no promotion deadline exhaustion, and successful exact-image recovery.
  Migration, scan, missing-image/pre-start, unrelated Compose, wrong-image/exit,
  missing marker/label, OOM, runtime error and evidence-capture failures cannot
  substitute for injected deployment failure. Recovery still proceeds when
  failure evidence cannot be collected.
- **R3:** Both attempt queries include the attempt's durable error and Job's
  `current_attempt_id`. A finished failed/abandoned attempt with its own error
  remains terminal after an authorized retry selects a different attempt.
  A still-current failed attempt must retain visible Job failure/error;
  unfinished or requeued interrupted attempts remain unacceptable. The same
  rule applies to initial drain, final claims around stop and rollback drain.

Migration compatibility, exact-ID scan and artifact gates, real public smoke,
Media identity/image/revision comparisons, replica counts and the original
600-second promotion / 300-second drain and automatic recovery limits remain
enforced. Failed promotion and successful recovery retain distinct results.

## Regression evidence

Using the common-root `.venv` with bytecode writes and pytest cache disabled:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p no:cacheprovider \
  -p scripts.dev.pytest_plugin --offline-fast tests/dev/test_release.py -q
PYTHONDONTWRITEBYTECODE=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p no:cacheprovider \
  -p scripts.dev.pytest_plugin --offline-fast tests/dev -q
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
  check --no-cache scripts/dev/release.py tests/dev/test_release.py
git diff --check
```

Results: **81 release tests passed in 1.28s; 140 dev tests passed in 1.66s**.
Ruff and whitespace checks passed. The original 51 release / 110 dev cases remain
included. Thirty added cases cover parent binding, failure attribution,
concurrent retry, final claim, rollback drain and diagnostic/log recording.

For a red/green check, temporarily substituted only the original runner from
`git show fcb0bf6:scripts/dev/release.py`, preserving and restoring the fixed
bytes in `finally`, then selected:

```text
bad_build_rejects_parent_binding_mismatch or
bad_experiment_rejects_other_failures or
retry_during_stop_and_final_claim_finish_drain
```

**All 18 selected tests failed on the original** (3 parent binding cases,
13 real-apply/evidence negative cases, 2 release/rollback retry races).
All pass with the corrections. R2 tests execute the real `Runner.apply`, failure
capture, restoration and `Runner.evidence`, mocking external Docker/HTTP/source
boundaries. Positive coverage asserts the bad API record is durable before good
startup and retained in the experiment. R3 race tests execute the real drain and
release/rollback, include a final claim, and fail immediately if terminal old
attempts cause waiting. The original same-attempt requeue and late DB reply
five-minute rejection tests remain in place. These are offline code evidence.

## Actual R1 daemon compatibility check

Read-only inspection selected the existing project Lima Unix socket, without
changing global context: Docker Engine **29.9.0**, default Docker builder,
BuildKit **0.34.0**, containerd executor. Called the corrected real
`Runner.build(source, bad_from=parent_id)` in an empty temporary context with a
120-second budget and a unique scratch project name. This built the actual
synthetic API-module alteration, rather than a mocked Dockerfile.

- Parent: `sha256:647c02742b4f697327c9bc16f211c92ef0c1106caeaf2cbbf71de3f9965e47a5`.
- Parent tag:
  `dc2-release:r1-scratch-b11f79a5-c5dad9c8a9ae4319bd0d42ad2940cc25-parent`.
- Binding verified before: `2026-10-12T18:56:33.475187+00:00`;
  after: `2026-10-12T18:56:34.064063+00:00`.
- Built: `sha256:d5bf8fad8ed90f6266ee5816c7a9931b946e11129d9981f283f14b23decd5114`.
- Output tag: `dc2-release:r1-scratch-b11f79a5-c5dad9c8a9ae4319bd0d42ad2940cc25`.
- Completed at `2026-10-12T18:56:34.125297+00:00`; elapsed **0.911s**.
- Inspected output was distinct from parent, with
  `dc2.release.injection=uvicorn-startup-exit42` and matching parent provenance.

Scratch output inherited base revision `0b24c9da4007bd44db9671f07924571d98e68e5b`
and fingerprint `a272c746c5bb2b4358645e77207edd5f721672d8b5e35480f4a5fedf26e0056d`.
Those labels do not claim this fix's clean-source/artifact/scan acceptance.
The two unique scratch tags/images were retained; no existing tags were moved
and no image pruning was performed. No existing services or volumes were
started, stopped, replaced or released. No GitHub, other agents, shared runtime,
Compose, Make, root files, AWS or Alibaba operations occurred.

## Parent follow-up

**Full live V4 acceptance remains pending.** The scratch build establishes R1
compatibility only. On clean combined root, the parent must run the full good/bad
experiment and retain exact source labels, distinct image IDs, passing artifact
and Trivy gates, actual bad API CID/image/declared startup exit record before
restoration, unchanged Media snapshots/revisions, replica restoration, real
public workflow smoke and separately measured promotion/recovery/drain times.
Nonempty interrupted work remains required for live drain evidence. No human
verification or AWS prerequisite is added by these corrections.
