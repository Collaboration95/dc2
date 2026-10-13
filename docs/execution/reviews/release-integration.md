# V4 parent runtime wiring handoff

Implemented locally on `work/release-integration` in
`/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/release-integration`.
Base: `82631cd`. The provided runner cherry-pick is
`c503931952298db15632bbef7febadf4a7fe5ebf`; its three owned files match source
commit `6dc9b107e283c5153a69aa71f0f973dd631a27b5`.

Implementation commit: **`295f631b7c0840f137a25f0a68bfcd57e43265c3`**.
Clean source-index fingerprint observed at that commit:
`e5ba65f2ded87521a28fa78757fc9d105d8c5fa2a64038d3827c7211d420767d`.
This documentation is committed separately so it can name the implementation hash.
Builds always calculate the current HEAD and index fingerprint anew, including
after cherry-picking into the parent's final integrated tree.

Only `scripts/dev/runtime.py`, `tests/dev/test_runtime.py`, Compose **build
labels**, and this report changed. The release runner and its tests remain frozen.
No Make/CI dispatcher, service/environment/resource configuration, root/shared
worktree, GitHub, image build or running container was changed by this lane.

## Runtime behavior

- Ordinary Compose selection is base file, then run-private
  `release.override.json`, then any explicit `-f` candidate. The frozen runner's
  duplicate persisted file remains harmless; its explicit candidate wins.
- Builds omit persisted selection, reject explicit image-selection files, and
  require mutable Processing/Media/MinIO image tags. Configured `sha256:` IDs
  and digest references are rejected before invoking a build. `runtime.env`
  retains mutable tags; source labels are never written there.
- Normal `up` builds the configured mutable tags, then starts an existing
  persisted release with `--no-build --pull never`. Rebuilding a mutable
  Processing tag cannot replace the selected immutable release ID. Without a
  persisted release, the original startup arguments and initial infrastructure
  pull behavior remain available.
- Runtime `up`, `down`, and standalone `images` use the runner's same
  `<run>/releases/runner.lock` with nonblocking `flock`. The lock spans startup
  builds and smoke; a failed build closes the lock. `up` and `images` read the
  journal after acquiring it and refuse non-null `pending` recovery intent or
  unreadable journal state. `down` remains available without deleting volumes.
- Low-level `runtime.compose` deliberately does not acquire the lock or reject
  pending recovery: the release runner already owns the lock and must deploy a
  restore image while recovery intent is pending. Startup calls its internal
  image builder under the existing lock rather than locking twice.
- Processing and Media builds receive revision, source fingerprint and source
  state labels. The helper imports `release.PRODUCT_PATHS` and hashes exactly
  UTF-8 stdout from `git ls-files -s -- PRODUCT_PATHS`, including its final
  newline. Clean labels match the runner's current source contract. Modified,
  staged or untracked product paths produce `dirty:<HEAD>` and
  `dirty:<index-hash>`, with `dc2.release.source-state=dirty`; development builds
  still work and cannot pass as clean bootstrap source. Direct Compose builds
  without freshly supplied source labels default to `dirty-unverified`.
- The source-label helper reads Git and its nonsecret project root argument.
  Runtime continues removing project dotenv keys from ambient subprocess
  variables; fresh source-label variables override stale caller values. No
  credentials are copied into build labels.

The existing build still covers Processing, Media and pinned-source MinIO.
Verified cached MinIO still skips its compilation and builds Processing/Media.
The worker remains 2 CPU / 1536 MiB with 60s stop grace; all eight non-worker
long-running service CPU limits still total 2 CPU. No quota or service changes
were needed here. Make release/evidence dispatch belongs to the parent lane.

## Offline verification

Run from this worktree; no local virtualenv exists, so these commands use the
common-root environment:

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p scripts.dev.pytest_plugin --offline-fast \
  tests/dev -q
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p scripts.dev.pytest_plugin --offline-fast \
  tests/dev/test_release.py -q
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
  check scripts/dev/runtime.py tests/dev/test_runtime.py
git diff --check
```

Observed on 13 October 2026: **110 dev tests passed in 0.87s**, including runtime
and inherited foundation checks. The separate frozen runner suite passed
**51 tests in 0.49s**. Ruff and whitespace checks passed.

The complete Python fast suite also passed with the standard sanitized
`checks.fast_env()` and offline network guard:

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python - <<'PY'
import subprocess
import sys
from scripts.dev.checks import fast_env
subprocess.run([
    sys.executable, '-m', 'pytest', '-q', '-p', 'scripts.dev.pytest_plugin',
    '--offline-fast', 'tests', '--ignore=tests/integration', '--ignore=tests/e2e',
    '-m', 'not integration and not e2e',
], env=fast_env(), check=True)
PY
```

Result: **892 passed, 1 deselected in 4.97s**. One inherited authentication test
emitted its short HMAC fixture warning. No live services were contacted.

New tests cover persisted/candidate precedence, no-release defaults, build
exclusion and immutable-tag refusal, fresh labels without dotenv changes,
modified/staged/untracked source labels, pending/malformed journals, real OS
lock contention in both directions with the frozen runner, lock cleanup after
failure, runner restoration without double locking, and released startup flags.

## Parent live follow-up

**Live V4 acceptance remains open.** After all lanes are integrated and Main is
clean, bootstrap that final source and run the actual experiment from the parent
repository with its project environment:

```sh
.venv/bin/python scripts/dev/runtime.py up --run-id v4-local
.venv/bin/python scripts/dev/release.py evidence --run-id v4-local
```

Use `--additive-migrations` only after reviewing newly added Processing revisions
for compatibility with the retained image. If recovery remains pending, use
`release.py rollback --run-id v4-local` before runtime `up` or `images`.
The parent must retain actual good/bad deployment, scan, exact-image restoration,
Media-unchanged, smoke, drain and timing evidence under the runner contract.
These offline results do not claim measured release timing or live V4 PASS.
