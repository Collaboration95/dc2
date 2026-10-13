VERDICT: PASS
ISSUE: #22 (V3); parent #6 (E5)
PR: local branch review/scaling-session; no GitHub access

Reviewed 13 October 2026, commit
`2cb8da833cb7f20b6f4fb41ff4b318f01530266b`, against its parent `b083a20`.
This verdict covers only the new session-renewal diff and its tests/documentation.
It is runner-fix approval, not full V3 experiment acceptance or merge authorization.
Read the review-work skill, user/repository AGENTS.md, project2-worklog.txt,
scaling-session-fix.md, and the local V3 acceptance contract. The remainder of the
previously reviewed runner was not reopened.

ACCEPTANCE:
- [pass] Renew before every batch, outside warmup and measurement —
  performance.py:894 awaits renewal at each loop boundary before worker launch,
  warmup, and the first measured acknowledgement. The nine-batch scheduling test
  observes renewal before uploads 0/31/63/96/128/161/192/225/256. Authentication
  operations use separate `<batch>-session` phases; makespan still starts at the
  first measured upload acknowledgement.
- [pass] Reuse the existing owner and validate the fresh session —
  performance.py:698-722 clears the old cookie jar, uses the existing credentials,
  and requires successful login and authenticated `/me`, both with the original
  owner ID, plus a nonempty access_token cookie. No owner is registered here.
  Offline tests reject missing-cookie, wrong-owner and refused-login responses.
  Additional probes verify actual Secure cookie delivery to `/me` and rejection
  of wrong login identity, wrong `/me` identity, `/me` 401, and unusable cookie scope.
- [pass] No upload 401 retry — upload and Client retry behavior are unchanged.
  A direct MockTransport probe receives one upload 401, retains its failed
  sequence-8 submission record, and raises EvidenceError with exactly one HTTP
  request and no login/retry.
- [pass] Preserve experiment and product authentication — AST comparison confirms
  that scaling differs solely by the awaited renewal at the loop boundary;
  owner, upload, run_order, scaling_metrics and scaling_targets are unchanged.
  No product authentication, lifetime, fixture, quota or encoder file changed.
- [pass] Preserve truthful evidence — credentials, old/new cookies and response
  bodies are absent from renewal operation records. The existing whole-run failure
  path and per-invocation evidence namespace remain unchanged. As documented in
  scaling-session-fix.md, seven completed batches/210 successes do not convert the
  failed invocation into acceptance and must not be spliced into the rerun.

FINDINGS:
- None in this bounded diff.

CHECKS:
- From this worktree, root `.venv/bin/python -m pytest -p no:cacheprovider
  -p scripts.dev.pytest_plugin --offline-fast --confcutdir=tests/evidence
  tests/evidence/test_performance.py -q --timeout=5`, with bytecode writes disabled
  and PYTEST_ADDOPTS empty — 68 passed in 0.76 seconds; network forbidden.
- Root `.venv/bin/ruff check --no-cache scripts/evidence/performance.py
  tests/evidence/test_performance.py` — passed.
- `git diff --check HEAD^ HEAD` — passed.
- Inline offline AST comparison, six MockTransport renewal scenarios and one
  direct upload-401 probe — passed; socket access explicitly forbidden.

SCOPE:
- No VM, live service, FFmpeg, browser, build or network workload ran. No agents or
  GitHub operations were used. Only this uncommitted review document was written
  in the worktree. The failed live artifact was not reopened or altered.

FOLLOW_UP:
- Parent must rerun all nine batches in its fresh namespace and assess the original
  targets from that complete invocation. The previous invocation remains FAIL;
  V3/E5 live acceptance remains pending until fresh evidence is complete.
