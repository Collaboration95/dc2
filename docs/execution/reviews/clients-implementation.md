# Clients lane implementation and verification

C1/C2 (#18/#19), implemented only in the assigned clients worktree on
`work/clients`. Production implementation commit:
`d739fc5ce6267ba5b0b21c059e377f9f6b821f25`. This subsequent evidence commit
adjusts synthetic authentication fixture addresses and documentation only; it
changes no production Python or JavaScript. The final local commit hash is
reported to the coordinator in the agent handoff. No branch/PR/issue was published
or changed. No AWS, Alibaba or other lane code was operated or modified.

## Delivered behavior

- `python -m publisher`: register/login, folder publishing with each file's
  outcome, status, fresh authorised output links, and bodyless stored-source retry.
  Standalone `publisher/pyproject.toml` builds an independently installable wheel
  with console entry `publisher = "publisher.cli:main"`; HTTPX is its only declared
  dependency. There are no player/delete commands or service/database imports.
- Private atomically replaced mode-0600 persisted Secure cookie jar and pending
  intent journal. Journal scope includes HTTPS API base and authenticated owner;
  upload identity includes filename/length/SHA-256. Pending UUIDs are saved before
  HTTP submission and reused after uncertain delivery, including process restart.
  Confirmed responses release the key; later deliberate submissions use new keys.
  POSIX flock serialises processes sharing a session. No database persistence is
  owned by this lane, so no owned PostgreSQL migrations/persistence test exists.
- JSON stdout is one machine-readable document. Batch failures do not stop later
  files; nonzero exit indicates partial failure or an exhausted wait budget.
  Accepted Asset IDs survive subsequent status-query failures. Requests have
  explicit timeouts; optional polling has a bounded request count and interval.
  Status 503 is unavailable, never a synthetic queued/done result. Arbitrary error
  bodies/passwords/session tokens are excluded from output. Output links are
  intentionally requested authorised capabilities, not permanent identifiers.
- Browser upload/edit/retry POSTs carry UUID Idempotency-Key headers. At most two
  automatic transport attempts use identical request content/key; unresolved
  upload/edit/retry keys survive subsequent manual replay within the page session.
  Successful acceptance separates a later user action into a new intent.
- Failed browser jobs retry their stored source through POST /jobs/AssetId/retry,
  with no body, no remembered-file requirement and no /upload request. Failed
  library cards reuse existing button classes to expose the same action. Slow or
  queued jobs cannot retry. Pending intake has explanatory text; status 503 keeps
  the displayed confirmed state and schedules another status check. Missing assets
  stop polling with an error. Existing editor/player/delete behavior is retained.
- CSS, HTML, vendor assets, illustrations, roadmap and original course/proposal
  documents are unchanged. No live runtime credentials entered committed files or
  artifacts. Synthetic fixture emails use fixed UUID@example.com addresses; no
  email is sent. The node_modules symlink is deliberately untracked/uncommitted.

## Recorded checks

Python 3.12.11 from the coordinator's root venv was used by absolute path; Node
and the existing root frontend node_modules were reused. Commands ran from this
worktree (frontend commands from its frontend directory).

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff check publisher tests/publisher
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher -p scripts.dev.pytest_plugin --offline-fast tests/publisher -m 'not integration and not e2e' -q --cov=publisher --cov-branch --cov-report=term-missing --cov-report=json:.local/publisher-coverage.json
PUBLISHER_HTTPS_TEST=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher tests/publisher/test_https.py -q
node node_modules/vitest/vitest.mjs run --coverage --coverage.include=app.js --coverage.thresholds.statements=90 --coverage.thresholds.branches=90 --coverage.thresholds.functions=90 --coverage.thresholds.lines=90
uv build --wheel --out-dir .local/wheels ./publisher
uv venv --python /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python .local/publisher-venv
uv pip install --offline --python .local/publisher-venv/bin/python .local/wheels/dc2_publisher-0.1.0-py3-none-any.whl
.local/publisher-venv/bin/python -I -m publisher --help
.local/publisher-venv/bin/publisher --help
git diff --check
```

- Ruff and whitespace checks pass. Offline Publisher: 49 passed, 1 optional TLS
  test deselected, 0.60 s with coverage on the final valid-email fixture tree.
  Earlier complete runs also passed; no retry-to-green test wrapper was used.
- Publisher combined statement/branch coverage: **97.97%**. All five production
  Python files are measured, including __main__.py. Statements 238/242 (98.35%);
  raw branches 52/54 (**96.30%**). Coverage artifacts stay ignored under .local.
- Optional real loopback HTTPS peer: 1 passed in 0.58 s. An explicit generated
  certificate is trusted, Secure session cookie persists across client instances,
  and the same peer is rejected with system trust. It uses temporary test fixtures,
  no disabled certificate verification or system trust changes, and no production
  service. Server request logs are suppressed. This is controlled-peer TLS evidence.
- Frontend: **135 passed**, 3 inherited live tests skipped, 2.04 s total. Statements
  **99.73%**, branches **96.13%**, functions **98.46%**, lines **99.73%**; all four
  required >=90 thresholds pass. DOM/fetch interaction assertions verify requests
  and file/body absence. These are not real-browser/live-service workflow claims.
- Wheel build, fresh isolated installation, isolated-mode module launch and console
  entry launch pass. Installed dependency metadata is only httpx>=0.28,<1, with its
  normal transitive dependencies. AST import inspection rejects app/media/processing,
  SQLAlchemy and asyncpg imports. Actual live credentials are neither needed nor
  used. This verifies small-package independence rather than root-venv coincidence.

## Contract evidence and scope

`test_public_schema_conformance_and_explicit_ca` validates actual controlled-peer
credentials and accepted/status response shapes with the frozen public OpenAPI
schemas and UUID/email format checking. Tests cover public bodyless retry, UUID
headers, immutable upload replay, definitive 409/410 rejection, partial 415 batch,
503 status/outage behavior and output link compatibility. Separate tests exercise
empty/malformed JSON, lost replies, expired authentication, owner-scoped journal
identity, polling limits and private on-disk persistence.

Relevant prepared cases: CT-01 upload replay, CT-06 retry replay, CT-13 pending
intake presentation, CT-14 status outage, CT-18 client compatibility, CT-20 partial
admission failures, CT-21 deleted-result rejection and CT-23 public schema shapes.
This lane verifies the client side against controlled public peers; it does not
claim database/backend case completion or mark all prepared cases implemented.

The Maya 30-file live batch, Arun real browser, actual FFmpeg MP4/HLS playback,
backend-owned PostgreSQL persistence and full cookie/ownership interaction across
both services belong to V1. No full integration is proven here. No containers were
started or deleted. Coordinator's nonworker aggregate 2 CPU and each of three
workers' 2 CPU/1536 MiB quotas remain inputs to later integrated/scaling runs.

## Coordinator shared-file requests

No root Make/pyproject/lock/Compose/Docker/CI/tests-dev file was edited.

1. Optionally expose `[project.scripts] publisher = "publisher.cli:main"` in the
   root pyproject. Independent installation already provides it. Root package
   discovery already includes publisher; HTTPX is already a runtime dependency.
2. Add `test-cli` as an alias of existing `test-publisher` to match C1's documented
   verification name. Foundation's dynamic package scanner/domain selection already
   lists publisher; check integrated fast/lint/coverage CI selections pick it up.
3. Keep the coordinator's new jsonschema dev dependency for formal schema tests.
   The optional controlled loopback HTTPS test is integration-marked and opt-in
   via PUBLISHER_HTTPS_TEST=1; it needs openssl and no infrastructure credentials.
4. Do not weaken frontend coverage or change its existing design. V1 should use
   the runtime's public_url + /api, explicit ca_file and a private cookie jar per
   run. Use UUID@example.com synthetic accounts, not example.test addresses.

## Proposal effort evidence

First captured implementation timestamp: 2026-10-12T17:27:00+00:00.
Evidence preparation timestamp: 2026-10-12T17:41:16.979403+00:00.
Measured lane implementation/testing interval: **857 seconds**
(**14.28 minutes**, 0.238 hours). Initial instruction/contract
reading started before this captured interval; final evidence/commit preparation
continues afterward. This is an actual measured interval, not a complete timed
human-effort allocation. C1 and C2 were interleaved, so no unsupported CLI-only
person-day number is asserted against the proposal's 2-person-day CLI allocation.

Publisher production Python physical LOC: **371** including blank/comment
lines; **242 executable statements** by coverage. Publisher test physical LOC:
**567**. At the production implementation commit, frontend/app.js changed
114 added / 13 removed lines; frontend/app.test.js changed 172 added / 11 removed.
Package metadata, README and this evidence note are separate from production LOC.
These are measured code-size facts, not proof of the proposal's effort estimates.
