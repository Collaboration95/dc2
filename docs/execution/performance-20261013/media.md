# Media performance record — 13 October 2026

Issue [#34](https://github.com/Collaboration95/dc2/issues/34), parent
[#33](https://github.com/Collaboration95/dc2/issues/33).
Base: `87389d178a822f92882e04bf4a0109613b844ffb`.
Implementation/test head: `cec36eecc4c740f663fcf0ca463e63401909ce3c`.
Branch: `perf/media-20261013`; worktree:
`/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/perf-media-20261013`.
Code and tests committed at 11:30 Singapore, before the 11:40 freeze.

**Decision.** End the login SELECT's read-only transaction before offloading
bcrypt. Previously the SELECT automatically opened a transaction, retaining a
database connection until request cleanup, including the entire bcrypt execution
and thread-pool wait. The route now wraps only the SELECT in `session.begin()`.
`media/database.py` already supplies `expire_on_commit=False`, so the selected
user's hash and public identity remain readable after transaction completion.
There is still exactly one user SELECT and one password-verification call.

**Measured resource improvement.** A real SQLAlchemy SQLite `QueuePool` with one
slot measured the following at the existing password-verification thread hook:

| Login case | Baseline transaction / connections held | Implementation |
| --- | --- | --- |
| Valid owner | active / 1 | inactive / 0 |
| Wrong password | active / 1 | inactive / 0 |
| Unknown email, dummy hash | active / 1 | inactive / 0 |

`tests/media/test_auth_resources.py` uses the real ORM transaction/pool lifecycle
through a small async-call adapter for a synchronous SQLite Session. Password
verification is stubbed to inspect the resource boundary. It also verifies one
SELECT, the stored/dummy hash choice, valid response identity/current role,
secure-cookie success and 401/no-cookie failure. The existing tests exercise
real bcrypt, including stored cost-12 hashes. SQLite is local and requires no
new dependency. This is **not** an asyncpg/PostgreSQL timing benchmark.

**Inferred impact and limits.** Login no longer occupies a database connection
while waiting for password verification, allowing that connection to serve other
requests. PostgreSQL pool contention should decrease during login bursts; no
HTTP latency, throughput or CPU percentage is claimed. The password cost,
authentication checks, ownership checks, cookie lifetime and API schema are
unchanged. The read transaction now commits before verification; commit errors
continue through the existing dependency-unavailable handler. No asset locks,
recovery behavior, caches, dependencies or infrastructure are changed. Existing
V3 measurements remain attributed to their original source, not this head.

**Alternatives considered.**

- Removing Asset read locks could reduce contention but would change the
  playback-grant/tombstone serialization protected by the existing integration
  test; rejected.
- Skipping the current-user database lookup or caching roles would compromise
  fresh role/owner checks; rejected.
- Output URL signing already has an explicit MinIO region and performs no
  bucket-region discovery I/O. Batching its thread-pool dispatch would require
  broader projection changes; no measured benefit was established in this lane,
  so it was left for later investigation.

**Exact verification.** All commands ran in the worktree above, using the
existing root virtualenv; no installation, VM, Docker or cloud operation ran.

```sh
MEDIA_PERF_PY=/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python
"$MEDIA_PERF_PY" -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/media --no-cov
"$MEDIA_PERF_PY" -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/media/test_auth_resources.py tests/media/test_api_recovery.py tests/media/test_contract_security.py --no-cov
"$MEDIA_PERF_PY" -m ruff check media tests/media
git diff --check
```

Baseline Media suite: **126 passed in 1.14s**. Implementation Media suite:
**129 passed in 1.15s**. Focused auth/security suite: **55 passed in 0.98s**.
These suite durations are test-run diagnostics, not performance comparisons.
Scoped Ruff and whitespace checks passed, exit 0. An initial command used the
unsupported `--offline` spelling and exited 4 without running tests; it was
corrected to the repository's `--offline-fast` option.

The new resource test was also executed against the exact baseline route,
temporarily replacing only that file and restoring it in `finally`:

```python
from pathlib import Path
import subprocess
import sys

path = Path("media/api/auth.py")
proposed = path.read_bytes()
try:
    path.write_bytes(subprocess.check_output([
        "git", "show", "87389d178a822f92882e04bf4a0109613b844ffb:media/api/auth.py"
    ]))
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-q", "-p", "scripts.dev.pytest_plugin",
        "--offline-fast", "tests/media/test_auth_resources.py", "--no-cov", "--tb=short"
    ])
    assert result.returncode == 1
finally:
    path.write_bytes(proposed)
```

Run with the same root virtualenv Python. Baseline result: **3 failed in 0.13s**,
each asserting `(True, 1) != (False, 0)` at password verification, pytest exit 1.
The comparison wrapper exited 0 because this was the expected regression result.
The implementation then passed the complete Media suite above.

**Handoff.** Changed implementation files: `media/api/auth.py` and
`tests/media/test_auth_resources.py`; this record is the only documentation
change. Independent clean-context Sol review, live PostgreSQL integration and
exact combined-head CI remain parent-owned and are not claimed here. The parent
publishes this report as a secret gist and links tracking/PR/review evidence.
No push, PR, GitHub write, extra agent, AWS/Alibaba action or shared live benchmark
was performed. The future $200/three-week cloud budget is unaffected.
