VERDICT: PASS
ISSUE: #21 (V2), parent #6; R1 from final-code-review.md only
PR: #31 (parent); local branch review/readiness
HEAD: 6865c9651b1b5d5be1af34a54c5156647ba5795e
BASE: 7a22429bdfeee65a0aa0c43e462f72d6cc7aaa30 (HEAD^)

Independent bounded rereview, 13 October 2026, Singapore. R1, Media restart
readiness, is resolved. Reviewed the latest commit's complete two-file readiness
diff and surrounding processing_outage/ServiceGuard control flow. Read supplied
and repository AGENTS.md, review-work SKILL.md, worklog, final-code-review.md,
local V2 acceptance, CT-13/CT-14 mapping and relevant execution decisions.

ACCEPTANCE:

- [pass] Transient failures are tolerated only during health readiness —
  recovery.py:134–139 catches httpx.TransportError around client.get("health")
  alone. ConnectError, ReadTimeout and RemoteProtocolError followed by 200 each
  succeed in controlled execution. HTTP 503 followed by 200 also succeeds;
  a nontransport exception propagates immediately.
- [pass] Absolute 30-second readiness deadline and remaining request budget —
  recovery.py:129–144 creates one monotonic deadline, supplies
  timeout=min(1.0, remaining), checks expiry before each request and after each
  reply, and caps each sleep at min(0.5, remaining). Independent simulated-clock
  probes include time consumed by requests: persistent transport failures and
  persistent 503 exhaust exactly 30 seconds, with a fractional final request
  budget. A 200 at or after expiry raises TimeoutError rather than passing.
- [pass] Timeout still attempts scoped restoration — the committed unavailable
  regression and independent probes execute the actual processing_outage and
  ServiceGuard with controlled Docker/HTTP boundaries. Processing, media-recovery
  and Media all receive restoration attempts and PASS outcomes; the original
  TimeoutError is retained. CT-13/CT-14 are not reported as passing on failure.
- [pass] Acceptance assertions are not retried — recovery.py:145–149 leaves
  pending-state verification, idempotent replay and convergence outside the
  readiness catch/loop. Separate assertion and HTTPX transport failures at each
  stage propagate on their first execution; health polling is not reentered.
  Convergence runs after the restoration context has already completed.
- [pass] Required regressions accompany the fix — test_scenario_restore.py:228–288
  covers ConnectError then 200 and persistent unavailability, positive bounded
  request timeouts, exact simulated expiry, absent acceptance success on timeout,
  and restoration with the original failure recorded.

FINDINGS:

- None requiring revision within R1.

CHECKS:

- Root .venv Python, run from this worktree with sanitized fast_env,
  PYTHONDONTWRITEBYTECODE=1, dummy DC2_DOCKER_HOST/DOCKER_HOST, empty PYTEST_ADDOPTS:

  ```sh
  /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
    -m pytest --confcutdir=tests/dev -p no:cacheprovider \
    -p scripts.dev.pytest_plugin --offline-fast --no-cov \
    tests/dev/test_scenario_restore.py -q
  ```

  Result: **14 passed in 1.35s**, including both new parametrized readiness cases.
- **15 independent offline reviewer probes passed**, executed from stdin using
  root .venv Python, actual processing_outage and ServiceGuard, ControlledStack,
  simulated monotonic time and HTTP responses/errors. Network connections/name
  resolution and external child commands were explicitly forbidden. Covered the
  readiness, deadline, restoration and acceptance failure paths described above.
- Root .venv Ruff: `check --no-cache scripts/evidence/recovery.py
  tests/dev/test_scenario_restore.py` — PASS.
- `git diff --check HEAD^ HEAD -- scripts/evidence/recovery.py
  tests/dev/test_scenario_restore.py` — PASS. Reviewed HEAD remained unchanged.

SCOPE:

Only this uncommitted rereview document is authored. R1 alone is rereviewed;
all other PASS assessments in final-code-review.md are retained. The V4 active-work
addition retains its separate PASS in release-active-rereview.md. Those verdicts
are not broadened by these checks. No application/test edits, subagents, GitHub
access or mutations, VM/Docker/live/network/build/FFmpeg/browser workloads were
performed. The ongoing full benchmark was not touched.

FOLLOW_UP:

- Parent still runs actual V2 later and retains its measured states, identities,
  timings and restoration evidence. This offline R1 PASS does not claim live
  CT-13/CT-14 execution, complete V2 acceptance, or authorize merge/release.
