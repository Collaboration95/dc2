# Foundation tooling results

13 October 2026. F1/F2 (#9/#10), branch `work/foundation-tools`, isolated worktree
`.worktrees/foundation-tools`. Plan PR #25 (`6ea8b9b`) and planning re-review PASS
were read before implementation. Parent helpers were imported by fast-forward to
`9a95861`; this report and commit own only tooling, workflows, tests/dev and the
README local setup section. Runtime/product/Compose/deployment/progress files
were not edited by this lane.

Implemented locked root uv setup and optional Playwright 1.63.0, runtime httpx,
future media/media_engine/publisher package inclusion, project-local caches,
exclusive private .env creation, prerequisite doctor, actual Make checks and
clear helper delegation. No global tools were installed or updated. Tests/dev
add 15 tests covering secret preservation, offline tests, unavailable integration,
stale evidence, unexecuted production coverage, branch accounting and safe clean.

## Final local validation

The final source fingerprint (product/tests/dev tooling/locks, including imported
parent helpers) was:

`ffe7888c7e78546dcadeb04498e340651620207b981791a914a1b509c10ee957`.

Source contents were tested after importing the parent helpers. Report/README/
workflow formatting edits do not change that coverage fingerprint. CI must still
run on the exact grouped PR head; no remote CI result is claimed here.

| Command | Elapsed seconds | Result |
| --- | ---: | --- |
| `make setup` first final pass | 1.187 | PASS |
| `make setup` second final pass | 1.020 | PASS |
| `make test` first final pass | 4.961 | 446 Python, 124 frontend passed |
| `make test` second final pass | 4.458 | 446 Python, 124 frontend passed |
| `make test` third final pass | 4.426 | 446 Python, 124 frontend passed |
| `make lint` | 0.136 | PASS, including imported helpers |
| `make doctor` | 0.185 | PASS |
| `make coverage` with real Processing integration enabled | 9.005 | PASS, including 21 real DB tests |
| `make clean` | 0.051 | PASS; .env, TLS files and .venv preserved |

The 446 Python tests retain all 431 inherited fast tests plus 15 tooling tests.
Frontend retains all 124 inherited tests, including vendored player interactions;
live browser/stack files are excluded from fast runs. Timings are whole command
wall times measured with a monotonic clock on this machine, warm local caches.
The local <=30s fast target is met. No equivalent CI timing result is claimed.

Both setup runs preserved the .env SHA-256 and file permissions and left the
tracked-file diff unchanged. Fresh initial setup created .env with mode 0600;
tests also prove preservation of an already configured .env and an .env symlink.
`git check-ignore` confirmed .env/.venv/.cache/.local/artifacts exclusions.
Lock consistency passed `uv lock --check --python 3.12.11` with a local uv cache.

Actual tools: uv 0.8.17, Python 3.12.11 (host bootstrap Python 3.14.7), Node
26.3.1, npm 11.16.0, pytest 9.1.1, Ruff 0.17.0, coverage 7.16.2, httpx 0.28.1,
Playwright 1.63.0, GNU Make 3.81. Current Node works without a global update.

## Coverage and real failure evidence

| Package | Combined statements/branches | Raw branches | Statements covered/total | Branches covered/total |
| --- | ---: | ---: | ---: | ---: |
| app | 86.77% | 78.70% | 1174/1333 | 170/216 |
| processing | 86.69% | 63.64% | 278/309 | 28/44 |

Each combined package gate is >=80%. These are not independent >=80% branch
claims. All production Python files are included, even never imported; migration
scripts retain the existing omission. Frontend statements 99.44%, branches
95.50%, functions 96.82%, lines 99.44%: all four >=90% gates passed.

Processing evidence used a fresh, lane-owned PostgreSQL 16 container with
separate migration/runtime credentials and both database ownership boundaries.
It used one CPU, 256MiB, a dynamically allocated loopback port, and the existing
read-only bootstrap script. Migrations ran under processing_migrator. The final
run enabled RUN_PROCESSING_TESTS=1 and supplied explicit host
PROCESSING_POSTGRES_DSN, PROCESSING_SERVICE_TOKEN and P2_POSTGRES_PORT to
`make coverage`. All 21 intake/concurrency/ownership tests passed. This temporary
container and its own anonymous volume were removed after checks; no other
containers, volumes, Docker settings or the parent's Lima VM were modified.

`make coverage-report COVERAGE_INPUTS='artifacts/coverage/.coverage.fast
artifacts/coverage/.coverage.processing-integration'` also passed. Exact
commands use those two paths on one line. A unit-only run collects evidence but
can fail the Processing combined gate: real DB repository evidence is required.
CI fast jobs collect without applying the DB package gate; the combined job
merges fresh fast and real integration fragments before enforcing per package.
Metadata rejects fragments from different product/test/tooling/lock contents.

Explicitly enabled integration against loopback port 1 failed, rather than
skipping: 6 failed, 15 errors in 1.96s, make exit 2. There was no retry-to-green.
Disabled or incompletely configured integration also fails with a precise
prerequisite message. The integration plugin fails selected skipped tests.

The installed native PostgreSQL utilities were unsuitable for an alternative
test server: PATH's libpq initdb lacked its postgres binary; a separate installed
PostgreSQL 17 binary referenced missing share/timezone paths. No global repair
was attempted; the existing Docker PostgreSQL 16 image supplied real evidence.

## CI and interfaces

`actionlint` 1.7.12 passed both CI and DAST workflows (embedded shell lint
disabled because no local shellcheck was available). Its project-local binary
was downloaded only with authenticated gh and verified against release SHA-256.
YAML parsing, job dependency references, bounded job timeouts and `git diff
--check` also passed. Frontend LCOV normalization passed.

CI always emits `Fast checks` and `Integration checks` with no path filters;
always-running aggregates fail when their dependencies fail or skip. Python and
frontend fast jobs each have a three-minute bound. Test commands have bounded
outer timeouts and Python tests a 30s individual bound. Integration commands
have five-minute bounds; job setup/build waits have separate bounded budgets.
uv/npm, pinned MinIO source, Firefox, and Docker image layers are cached. Real
readiness uses bounded polling; acceptance tests are never retried.

Trivy scans the actual loaded current app and Processing images with exit 1 for
fixable HIGH/CRITICAL findings. The app API/worker share an image. Media and each
distinct future worker digest must extend the scan matrix before promotion; CI
guards make missing new image selection fail visibly. SAST/DAST policies are
retained; DAST now obtains the pinned MinIO source through the runtime lane's
authenticated gh helper before the named-source-context build.

Make dry-runs verified all runtime actions, local-tls, browser install/trust/open
(including `browser` as the open alias),
and capacity install/start/status/stop/env command interfaces. Actual
`make local-tls RUN_ID=tools-check` passed. Actual `make capacity-status` reports
8 CPUs / 8296787968 bytes / cgroup 2 through the common-repository VM; capacity-env
points to that VM, not a worktree-specific replacement. Before helper import,
missing runtime/browser/capacity targets failed explicitly with exit 2.

Doctor's infra tier recognizes FFmpeg, ffprobe, OpenSSL, NSS certutil, Compose,
Docker and imported parent helpers. Its current failure is the absent runtime.py,
which the infrastructure lane must supply. Default Docker still reports its
unchanged 2 CPU/~2GiB limits; the optional project VM reports 8 CPU/~8GiB.

Parent evidence in `foundation-coordinator-results.md` proves real Firefox
trusted HTTPS and unrelated-CA rejection using a temporary NSS cert9.db profile.
The initial Certificates.Install policy was ignored under automation; the parent
recorded the scoped correction. This lane installs libnss3-tools only on the
disposable Linux CI runner and delegates trust checks to that helper. Browser
downloads consistently use .local/playwright, with verification enabled and no
system trust change. Parent browser/capacity measurements are not this lane's
independent repetitions.

## Remaining integration limits

- Runtime.py, the MinIO named-source Dockerfile/Compose changes and runtime tests
  are still supplied by the infrastructure lane. CI uses its fetch_minio helper
  and fails clearly until those files are integrated.
- Local legacy real MinIO/PostgreSQL integration, full HTTPS topology/browser
  trust and remote CI were not rerun by this lane; CI and parent integration must
  provide their evidence. Unit/interaction regressions and real Processing DB
  evidence were run here.
- No Media/media_engine/Publisher production package exists yet. Packaging,
  fast coverage and lint discover them; product lanes must extend real integration
  selection and live-image scans before acceptance.
- Tests retain an expected short JWT signing-key warning from an inherited
  negative test; current Node emits its experimental localStorage warning. npm
  reports inherited dependency deprecations. None caused a failure; no dependency
  warning was suppressed and no global update was made.
- No AWS actions, GitHub writes, push, pull request or merge of this tooling
  implementation was performed. The parent integrates its local commit into the
  grouped foundation PR for #9/#10/#11 and owns final acceptance/issue updates.

Machine-readable logs and coverage reports are ignored under artifacts/tooling
and artifacts/coverage. This report is the tracked evidence summary.
