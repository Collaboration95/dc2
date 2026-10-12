# C1/C2 review corrections

Implemented in the isolated `work/clients-fixes` checkout at
`/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/clients-fixes`,
based on `3dd50965be13a53dd8752f95e716faa4f30b37b8`.
Tested implementation commit: `e654ea04ec1d1a627a55b78cb5f6b038f9301f47`.
The subsequent local evidence commit changes documentation only.
Date: 13 October 2026, Singapore.

All three substantive REVISE findings have implementation fixes and sequence/fault
regressions. This is implementation evidence, not an independent reviewer PASS.

## Review snapshot

`clients-review.md` is the exact independent report copied into this checkout at
assignment time. It reviews the base head above, not the corrected implementation.
Its unchanged SHA-256 is
`69175789356ca1d786926dda4474b45878f80a4c299d66b0fed3b6d2f9b71d0b`.
The coordinator can reconcile any later reviewer report changes. No notation or
verdict was added to the copied report itself.

## R1: deferred replies cannot replace a newer card

`frontend/app.js` captures each retry's Asset ID, intent object/key, session
and active-card generation. It checks ownership after the response body resolves,
in error handling, and before releasing controls. A replaced reply cannot alter
another card's ID, clear its pending intent, start/stop its follower, sign it out,
or enable a newer retry's controls. Upload/edit handlers use the same ownership
checks for their surfaces. An automatic transport replay cannot cross a changed
login session. Poll responses check their follower generation before handling 401.
Replacing a card/editor releases abandoned submission controls.

`frontend/app.test.js`, `client review regressions` and `replaced mutation controls`,
exercise actual DOM events with held promises. A failed library A retry is held;
B uploads and starts following; A then returns 202, 401, 503 or a lost reply. B's
filename/status remain displayed, its next scheduled GET still follows B, and the
confirmation `Delete "B.mp4"? This cannot be undone.` produces only
`DELETE /api/jobs/B`. Separate tests retain B's unresolved upload key/content and
keep a newer retry disabled until its own reply. Replaced upload/editor replies
also leave current identity and controls intact.

## R2: preserve uncertainty through basic reauthentication

`publisher/cli.py:mutation` retains the journal key for 401, because rejection of
this HTTP attempt does not establish rejection of an earlier uncertain delivery.
Existing API-origin/owner/operation/content journal identity supplies the scope;
no auth protocol or dependency changes are needed.

`frontend/app.js` retains unresolved File objects, immutable edit JSON and bodyless
retry keys in owner-scoped in-page maps. Sign-out clears the visible session's
references and followers while retaining those records. Same-owner login restores
the pending upload/retry card and its existing Retry action. Reopening the original
editor and submitting the same operations selects its original body/key. Another
owner selects a separate map; their confirmed requests cannot consume the first
owner's pending records. Confirmed acceptance/definitive rejection removes the
matching record so subsequent intentional actions receive fresh UUIDs. Browser
persistence remains within the current page; a page reload does not preserve Files.

`test_cli_uncertain_auth_recovery_is_owner_scoped` covers upload and retry across
separate CLI invocations: lost reply, mutation 401, identity 401, another owner's
login/action, original owner's login/resume, then a confirmed later action. It
asserts journal contents, original file bytes/bodyless retries, original versus
fresh headers and accepted IDs. Browser tests cover all three mutations through
lost reply -> automatic replay 401 -> same-owner login/resume, exact File/JSON/body
and key identity, fresh confirmed later actions, account switching and return to
the original owner. Deferred session-change tests prevent automatic replay with
another login's cookies.

## R3: accepted results survive local state errors

`publisher/cli.py:mutation` constructs the confirmed ID/key result before journal
cleanup. Cleanup OSError retains that result, adds a safe `state_error` and marks
it unsuccessful for exit accounting. Batch output retains all attempted file
outcomes and promotes state failure to the overall result. `main` preserves the
completed result if final cookie saving fails, adds the same safe state error and
returns exit 1. Human batch output also shows the overall state error. Exception
paths/details, credentials and arbitrary server error bodies are not emitted.

`publisher/state.py:Intents.change` rolls back its in-memory snapshot when either
reservation or completion saving fails. A later batch write cannot discard a key
that the failed cleanup left on disk. HTTP submission still follows successful
reservation; failed reservation does not send a request.

Fault tests in `tests/publisher/test_publisher.py` cover:

- First accepted file's completion write fails, then an unsupported file and
  another accepted file write successfully: three outcomes, two distinct accepted
  IDs, all three keys, safe state error, exit 1, and the original key still on disk.
  The next invocation replays that key and preserves batch cardinality; the
  successfully completed file's later action uses a fresh key.
- Final cookie saving fails after both all-accepted and mixed batches: every file
  result, accepted ID and request key survives, with overall state error and exit 1.
- Accepted retry and definitive rejection cleanup fail: confirmed ID or original
  safe rejection and key survive, and disk/in-memory pending state agree.
- Failed reservation rolls back memory; a later save contains only the previously
  persisted and successfully reserved records.

`publisher/README.md` explains same-owner login/resumption and local state-error
outcomes, including checking confirmed IDs before publishing again.

## Verification

The root Python 3.12 venv and root frontend node_modules were reused. The symlink
`frontend/node_modules` is deliberately untracked. Commands used this isolated
checkout as cwd, except Vitest which ran from its frontend directory:

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m ruff check publisher tests/publisher
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher -p scripts.dev.pytest_plugin --offline-fast tests/publisher -m 'not integration and not e2e' -q -o addopts='' --cov=publisher --cov-branch --cov-report=term-missing --cov-report=json:.local/publisher-fixes-coverage.json
PUBLISHER_HTTPS_TEST=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher tests/publisher/test_https.py -q -o addopts=''
node node_modules/vitest/vitest.mjs run --coverage --coverage.include=app.js --coverage.thresholds.statements=90 --coverage.thresholds.branches=90 --coverage.thresholds.functions=90 --coverage.thresholds.lines=90
git diff --check
```

Results:

- Ruff and whitespace checks pass.
- Offline Publisher: **57 passed, 1 TLS test deselected**. All five production
  modules measured; combined coverage **98.43%**, 257/260 statements and 56/58
  raw branches covered. The >=80 combined gate passes.
- Real loopback TLS peer: **1 passed**. Explicit CA trust, persisted Secure cookies
  across client instances, and rejection with unrelated system trust still pass.
- All frontend tests: **152 passed, 3 inherited live tests skipped**. App coverage:
  statements/lines **99.75%**, branches **96.00%**, functions **98.55%**. All four
  >=90 gates pass. This is DOM/fetch evidence, not a newly run deployed workflow.
- No new Python test basename was introduced; tests extend the existing Publisher
  test module, avoiding the repository's basic pytest import-name collision.

Production changes are confined to `publisher/cli.py`, `publisher/state.py` and
`frontend/app.js`; supporting changes are the Publisher README, owned test files,
this evidence note and the exact copied review snapshot. No shared/root files,
sibling worktree, HTML/CSS/assets, services, GitHub, AWS, Alibaba or child agents
were modified or operated. No integrated workflow was rerun for these client-only
corrections; the parent's existing two-service public-workflow result is separate.
