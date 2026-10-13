# Clients performance evidence — 13 October 2026

Issue [#36](https://github.com/Collaboration95/dc2/issues/36), parent
[#33](https://github.com/Collaboration95/dc2/issues/33).
Baseline: `87389d178a822f92882e04bf4a0109613b844ffb`.
Tested implementation head: `6ccccb2680ddd0f1f6da56c21d374567fd140b20`.
Branch: `perf/clients-20261013`; worktree: `.worktrees/perf-clients-20261013`.
This report is a subsequent documentation-only commit; implementation and test
files remain those of the tested head. Independent review, secret-gist publication,
remote tracking and CI belong to the coordinator and remain pending here.

## Decision and source evidence

Use `hashlib.file_digest(stream, "sha256")` for Publisher upload identities.
`publisher/cli.py:129` hashes every file before reserving its durable upload intent.
The baseline `publisher/state.py:45` reads fresh 1 MiB bytes objects repeatedly;
during the next read, the previous chunk is still referenced. The standard-library
helper reuses a bounded buffer in the measured CPython implementation. Full-file
SHA-256, filename, size and the identity's list shape remain identical. Replays
still hash current file contents; no cache or reduced hashing was introduced.

[Python 3.12 documentation](https://docs.python.org/3.12/library/hashlib.html#hashlib.file_digest)
specifies binary-file hashing and caller-owned closure, and dates the helper to
Python 3.11. The project's supported Python range starts at 3.12. The `with`
statement still closes the stream on success or error; upload separately reopens
it at byte zero. Authentication, owner scope, journal writes, request contracts,
TLS checks, UI and roadmap files are untouched.

## Measured result and limits

macOS, CPython 3.12.11; an isolated temporary 8 MiB zero-filled file; fixture
creation outside tracing. No shared VM, Docker, browser or cloud workload.

| Operation | Three peak Python allocation measurements, bytes |
|---|---|
| Exact baseline function | 2,102,230 / 2,102,230 / 2,102,230 |
| Actual worktree function | 267,553 / 267,553 / 267,553 |

All six identities were exactly `['clip.mp4', 8388608,
'2daeb1f36095b44b318410b3f4e8b5d989dcc7bb023d1426c492dab0a3053e74']`.
These are `tracemalloc` peak allocations for one hashing call, not process RSS,
whole-publish memory, throughput, CPU or cloud measurements. Lower temporary
allocation in normal publishing is inferred; an end-to-end speedup is not claimed.
The resource regression permits up to 1 MiB to allow instrumentation overhead.

## Exact reproduction

Run from the clients worktree, using the existing root virtual environment:

```sh
CLIENTS_PYTHON=/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python
"$CLIENTS_PYTHON" - <<'PY'
import ast
import hashlib
import json
import platform
import subprocess
import tempfile
import tracemalloc
from pathlib import Path
from publisher.state import file_identity

base = '87389d178a822f92882e04bf4a0109613b844ffb'
source = subprocess.check_output(['git', 'show', f'{base}:publisher/state.py'], text=True)
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'file_identity')
namespace = {'hashlib': hashlib}
exec(compile(ast.Module(body=[node], type_ignores=[]), '<baseline>', 'exec'), namespace)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'clip.mp4'
    with path.open('wb') as stream:
        stream.truncate(8 * 1024 * 1024)
    results = {}
    for label, operation in [('base', namespace['file_identity']), ('worktree', file_identity)]:
        peaks = []
        for _ in range(3):
            tracemalloc.start()
            identity = operation(path)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peaks.append(peak)
        results[label] = {'identity': identity, 'peak_bytes': peaks}
    assert results['base']['identity'] == results['worktree']['identity']
    print(json.dumps({'base': base, 'python': platform.python_version(), 'results': results}, indent=2))
PY
```

## Verification

Before changing production code, the new test file against baseline code returned
exit 1: **5 passed, 1 failed** in 0.10s. Only the allocation test failed:
`file hashing allocated 2102230 bytes at peak`. Correctness already passed.

```sh
"$CLIENTS_PYTHON" -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/publisher/test_file_identity.py
```

After the fix, existing public-contract, cookie/TLS-configuration, owner-scoped
replay, uncertain delivery and state-failure tests plus the six new tests returned
exit 0: **63 passed** in 0.69s. The new tests cover empty input, a small file,
partial final blocks above both buffer sizes, same-size content changes and the
allocation bound. Offline mode forbids actual network access.

```sh
"$CLIENTS_PYTHON" -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/publisher/test_publisher.py tests/publisher/test_file_identity.py
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff check publisher tests/publisher/test_publisher.py tests/publisher/test_file_identity.py
git diff --check
```

Ruff: `All checks passed!`, exit 0. Whitespace check: exit 0. No frontend build
applies to this Python-only change. Live HTTPS and end-to-end/cloud performance
were not rerun. The parent must obtain independent review and required CI.

## Alternatives assessed

- **Publisher connection reuse and multipart streaming:** already present in
  `publisher/client.py:52` and `publisher/client.py:110`; one HTTPX client per
  invocation, file-backed multipart upload. No redundant client creation or
  whole-file upload buffering established.
- **Digest caching, sampling or metadata-only identity:** rejected. Content
  changes with the same size must produce a new identity; owner-scoped uncertain
  replay semantics require preserving full SHA-256.
- **Frontend lazy player loading:** `wc -c frontend/vendor/*.js` measured
  `hls.min.js=619692`, `plyr.min.js=112657`, total `732349` uncompressed bytes.
  Deferred: network compression and browser impact were not measured, and lazy
  loading needs readiness/fallback tests to preserve playback and editor behavior.
- **Cancel abandoned browser polling requests:** `followJob`/`stopPolling` in
  `frontend/app.js:373-430` fence stale responses but do not abort pending reads.
  Plausible follow-up, not a measured result or implemented change in this lane.
  Existing polling intervals, completion/error behavior and UI remain unchanged.

Read-only GitHub access used only `gh issue view 36` and `gh issue view 33` with
`--repo Collaboration95/dc2 --json number,title,body,url`. No GitHub writes,
push, PR, agent creation, dependency installation or infrastructure operation.
