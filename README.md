# Flickpond — dc2 Project 2

Project 2 runs from this repository root. The former `Media_player` submodule
has been imported; no nested checkout is required. The current local stack has
Media Management and Processing as separate services, with separate database
ownership. The existing frontend and media engine are reused. An independent
Publisher CLI uses the public HTTPS API.

```sh
make setup
make doctor
make up RUN_ID=local
make browser-install RUN_ID=local  # first use
make browser RUN_ID=local
make test                         # fast, offline Python and frontend tests
make verify-local RUN_ID=local    # real owned integration, coverage and workflows
make down RUN_ID=local            # preserves configuration and data volumes
```

`make up` prints the run-specific HTTPS URL. Read `.local/runs/local/state.json`
for the URL and CA path; private runtime credentials stay in the ignored
`.local/runs/local/runtime.env`. Create your own account through the browser.
Do not add that environment file or certificate keys to Git.

On this Mac, the project-local Lima runtime and dependencies are installed.
For another host, read [local setup](docs/execution/handoff.md) for prerequisites
and optional `make capacity-install` / `make capacity-start`. Commands do not
change the global Docker context or system certificate trust.

| Current code | Role |
| --- | --- |
| `media/` | Login, owners, Assets, source storage, public API and playback |
| `processing/` | Jobs, Attempts, queue/worker, heartbeats and recovery |
| `media_engine/` | Reused probing, validation and FFmpeg operations |
| `publisher/` | Independent public-API folder publishing CLI |
| `frontend/` | Existing browser UI, with reliable retry/replay behavior |
| `compose/local/`, `scripts/dev/` | Root Make setup, isolated runtime and release |
| `scripts/evidence/` | Local recovery, latency and scaling measurements |
| `app/`, root legacy Compose | Preserved Project 1 regression reference |

Start with the [morning handoff](docs/execution/handoff.md),
[execution plan](docs/execution/plan.md), [contract evidence](docs/execution/contract-evidence.json),
and [working decisions](docs/project2-worklog.txt). `make publisher ARGS='--help'`
shows CLI usage. Slow experiments are separate Make targets listed by `make help`.

The material below records inherited Project 1 architecture and commands.
Its deployment URL, original ownership notes and root legacy Compose instructions
are historical; this work does not operate that deployment. Current Project 2
commands and status are in the links above.

## Inherited Project 1 reference

Flickpond is a practice-module team project: an asynchronous video upload and processing platform. Sprint 1 proved the request path end to end with a copy job standing in for transcoding; **sprint 2 replaced it with real FFmpeg**, added authentication and per-user ownership, a reaper that recovers jobs abandoned by a crashed worker, CI as a required check on `main`, and TLS.

It is deployed at **<https://flickpond.com>**.

```text
browser -> nginx -> FastAPI -> MinIO + PostgreSQL + Redis queue
                                          |
                                          v
                                  one of N workers (FFmpeg)
                                          |
                                          v
                       queued -> processing -> done | failed
                                          |
                                          v
                             browser polls the status API

           reaper: recovers rows a dead worker left in `processing`
```

### Where to read next

| File                                                                                   | What it is                                                                                      |
| -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [`docs/known-traps.md`](docs/known-traps.md)                                           | **Read this before changing anything.** 23 traps already hit here, most of which fail silently. |
| [`docs/contract.md`](docs/contract.md)                                                 | The shared schema and API boundary. Changing it means telling the team.                         |
| [`docs/c-recovery-input-safety.md`](docs/c-recovery-input-safety.md)                   | Sprint 3, track C: retry API, crop/clip validation, tests, and B/E integration instructions.    |
| [`docs/sprint2-report.md`](docs/sprint2-report.md)                                     | **What sprint 2 delivered**: contributions, evidence, BUG-04 to BUG-12.                         |
| [`docs/sprint2-plan.md`](docs/sprint2-plan.md)                                         | Sprint 2: all eight items, what each decided, and why.                                          |
| [`docs/sprint2-backlog.md`](docs/sprint2-backlog.md)                                   | The sprint 1 review's findings, P1-P9. All closed; kept for the reasoning.                      |
| [`docs/s2-03-auth-design.md`](docs/s2-03-auth-design.md)                               | Why authentication is shaped the way it is.                                                     |
| [`docs/scaling-notes.md`](docs/scaling-notes.md)                                       | What serving 50 concurrent users would take.                                                    |
| [`docs/sprint1-report.md`](docs/sprint1-report.md)                                     | What sprint 1 built, by whom, and what broke.                                                   |
| [`docs/sprint1-plan.md`](docs/sprint1-plan.md), [`docs/proposal.md`](docs/proposal.md) | The original plan and module proposal.                                                          |
| [`CLAUDE.md`](CLAUDE.md)                                                               | Working notes: commands, ownership, conventions.                                                |

## Architecture

| Component        | Responsibility                                                       | Default local address                                               |
| ---------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| nginx (frontend) | Serves the UI; proxies `/api/` and `/videos/`. The only public port. | `http://localhost:3000` (deploy: `:80`)                             |
| FastAPI          | Upload and job-status HTTP API                                       | `127.0.0.1:8000` (loopback only)                                    |
| PostgreSQL       | Durable job metadata and processing state                            | `127.0.0.1:5432`                                                    |
| Redis + RQ       | Delivery of job IDs to workers                                       | `127.0.0.1:6379`                                                    |
| MinIO            | Original and processed video objects                                 | API `127.0.0.1:9000`, console `127.0.0.1:9001` (both loopback only) |
| Worker           | FFmpeg transcode to 720p MP4, one-way state transitions              | Internal Compose service                                            |
| Reaper           | Fails rows a dead worker abandoned; sweeps orphaned objects          | Internal Compose service                                            |

The queue coordinates work, PostgreSQL records state, and MinIO stores the video bytes. Workers remain stateless, so any worker replica can process any queued job.

### Port policy

**nginx is the only service published beyond loopback.** The API, MinIO's S3 API
and console, PostgreSQL and Redis are pinned to `127.0.0.1` in
`docker-compose.yml` and that is deliberately not configurable.

The API enforces per-user ownership (S2-03), but the datastores behind it do
not: anything that reaches PostgreSQL or MinIO directly reads every user's data.
That is what the loopback binding is for, and why it stays even though the
application now authenticates its own callers.

Reach an internal service from another machine with a tunnel, not a published
port:

```bash
ssh -L 5432:127.0.0.1:5432 user@host    # psql against localhost:5432
ssh -L 9001:127.0.0.1:9001 user@host    # MinIO console on localhost:9001
```

A deployment anyone else can reach sets `FRONTEND_BIND=0.0.0.0` and
`FRONTEND_PORT=80`. The app authenticates its own callers, so no separate gate
is needed — see [`docs/s2-03-auth-design.md`](docs/s2-03-auth-design.md).

Note that `ufw` will not save you here: Docker publishes ports through its own
iptables chain and bypasses ufw entirely, so a host that believes it is
firewalled is not ([T-06](docs/known-traps.md#t-06)).

## Repository layout

```text
dc2/  (inherited Project 1 paths shown below)
|-- app/
|   |-- api/jobs.py               # GET /jobs and GET /jobs/{id}
|   |-- api/uploads.py            # POST /upload
|   |-- models/job.py             # SQLAlchemy Job model and state names
|   |-- repositories/jobs.py      # Shared DB functions for API and worker
|   |-- schemas/job.py            # Public response schemas
|   |-- services/output_urls.py   # Browser-accessible MinIO signed URLs
|   |-- services/media_type.py    # Container sniffing: what an upload actually is
|   |-- services/storage.py       # Upload-path object storage
|   |-- services/minio_client.py  # The only place a MinIO client is constructed
|   |-- services/security.py      # Password hashing and JWT issue/verify
|   |-- api/auth.py               # register / login / logout / me
|   |-- worker/                   # RQ worker, state machine, FFmpeg step, reaper
|   |-- queue.py                  # Shared enqueue/consume seam
|   |-- config.py                 # Environment configuration
|   |-- database.py               # Async SQLAlchemy engine and sessions
|   `-- main.py                   # FastAPI application and /health
|-- frontend/                     # Static UI: upload, poll, play
|-- migrations/
|   `-- versions/                 # Alembic database revisions
|-- tests/
|   |-- integration/              # Tests using the real Compose PostgreSQL
|   `-- test_*.py                 # API and service unit tests
|-- docs/
|   |-- contract.md               # Shared schema and API boundary
|   |-- sprint1-report.md         # Sprint 1 record: contributions, bugs, evidence
|   |-- scaling-notes.md          # Capacity analysis
|   |-- sprint2-backlog.md        # The sprint 1 review's findings, P1-P9
|   |-- sprint2-plan.md           # Sprint 2: what was built, in what order
|   |-- sprint2-report.md         # Sprint 2 record: contributions, bugs, evidence
|   |-- s2-03-auth-design.md      # Why auth is shaped the way it is
|   |-- known-traps.md            # Traps already hit here -- read before coding
|   |-- a-worker.md               # Worker and state machine notes
|   |-- proposal.md               # Full module proposal
|   `-- sprint1-plan.md           # Sprint 1 plan
|-- Dockerfile                    # Python 3.12 API image
|-- docker-compose.yml            # Frontend, API, worker, reaper, Redis, PostgreSQL, MinIO
|-- deploy/                       # nginx config, TLS, certbot renewal
|-- alembic.ini                   # Migration configuration
|-- pyproject.toml                # Runtime and development dependencies
`-- .env.example                  # Safe local configuration template
```

## Project 2 local setup

Work from this repository root, including inside an isolated Git worktree. Supply
`make`, `uv` (CI pins 0.8.17), an installed Python **3.12.11** matching
`.python-version`, and Node **20+** with npm on PATH. A current supported Node is
accepted locally; doctor records actual versions. CI uses Node 22. Setup reads
installed Python interpreters and never installs or updates global tools.

```bash
make setup                 # uv sync --locked; npm ci; create .env only if absent
make setup                 # repeat safely; preserve configured .env and permissions
make doctor
make lint
make test                  # fast Python and frontend tests
make help
```

Python runtime dependencies include `httpx`; `dev` and optional `browser` extras
are pinned through `uv.lock`. Setup installs both extras into `.venv`, without
downloading a browser. `make browser-install RUN_ID=local` delegates project-local
installation to the browser helper (Chrome for Testing on macOS; Firefox on Linux). `make setup-browser` runs
setup and that helper. `make browser RUN_ID=local` (or `browser-open`) opens its trusted profile.
`make doctor-infra` additionally
checks Docker/Compose, FFmpeg/ffprobe, OpenSSL, NSS `certutil`, and the runtime,
TLS, browser and capacity helpers. On Linux `certutil` comes from `libnss3-tools`; developer commands
do not install system packages.

Caches stay in `.cache/uv`, `.cache/npm`, `.cache/ruff`, and
`.local/playwright` for the parent browser helper. Environments, secrets and evidence live in ignored
`.venv`, `.local`, `.env`, and `artifacts`. `make clean` removes generated test,
lint and coverage output only. It preserves configured secrets, virtual
environments, browser installations, runtime state and service data.

The fast Python tier excludes `tests/integration`, `tests/e2e` and their markers,
blocks real socket connections/DNS, and ignores ambient service configuration and
the legacy `.env` settings file. Frontend fast checks exclude live stack tests;
the real vendored player interaction tests still run. Python tests have a 30s
individual timeout, with 120s/90s outer Python/frontend bounds. New tests needing
real services belong in the integration tier. No test is retried to obtain green.

Real integration requires explicit configuration for **isolated test resources**:

```bash
# Legacy migrated database + MinIO + FFmpeg:
RUN_POSTGRES_TESTS=1 POSTGRES_DSN="$TEST_POSTGRES_DSN" make integration
# Processing migrated database and runtime role, including ownership checks:
RUN_PROCESSING_TESTS=1 PROCESSING_POSTGRES_DSN="$TEST_PROCESSING_DSN" \
  PROCESSING_SERVICE_TOKEN="$TEST_PROCESSING_TOKEN" \
  P2_POSTGRES_PORT="$TEST_POSTGRES_PORT" make integration
```

Supply legacy MinIO settings explicitly when using non-default isolated ports.
Processing ownership tests use `MEDIA_RUNTIME_PASSWORD`,
`MEDIA_MIGRATION_PASSWORD`, `PROCESSING_RUNTIME_PASSWORD` and
`PROCESSING_MIGRATION_PASSWORD` (existing demo defaults otherwise). Host DSNs must
use the host-accessible port, rather than the internal Compose hostname. An
enabled tier fails for missing prerequisites, unavailable services or skipped
tests; it cannot silently claim success. Each selected integration suite has a
300s command bound.

```bash
# Current fast/frontend evidence plus whichever real integration flags are enabled:
make coverage
# Collect real integration separately, then combine explicit current fragments:
RUN_PROCESSING_TESTS=1 PROCESSING_POSTGRES_DSN="$TEST_PROCESSING_DSN" \
  PROCESSING_SERVICE_TOKEN="$TEST_PROCESSING_TOKEN" \
  P2_POSTGRES_PORT="$TEST_POSTGRES_PORT" make integration-coverage
make coverage-report COVERAGE_INPUTS='artifacts/coverage/.coverage.fast artifacts/coverage/.coverage.processing-integration'
```

Coverage gates **combined statements and branches >=80% per package**, and
reports raw branch percentages separately. It includes every production Python
file, even never imported, excluding migration scripts. The gate discovers
`app`, `processing`, `media`, `media_engine` and `publisher` as they arrive;
packaging and lint selection already include those names. Every evidence fragment
must match the current product/tests/tooling/lock fingerprint. Processing database
repository coverage needs real integration: a unit-only `make coverage` can fail
and reports that limitation explicitly. Frontend coverage retains statements,
branches, functions and lines **all >=90%**. Output is under
`artifacts/coverage`; command durations are in `artifacts/tooling/timings.jsonl`.

Runtime targets delegate to their owning helpers:

```bash
make env RUN_ID=local
make local-tls RUN_ID=local
make up RUN_ID=local
make smoke-infra RUN_ID=local
make browser-trust-smoke RUN_ID=local
make status RUN_ID=local
make logs RUN_ID=local
make down RUN_ID=local      # preserve service data
make capacity-status       # read-only: never starts the VM; shows size, lease and owner
```

`images`, `capacity-install/start/stop/env/reap/renew` are also available. The VM defaults to
2 CPU / 2 GiB with a 2 hour lease; `CAPACITY_ARGS=--benchmark` selects the 8 / 8 scaling profile. Runtime state is
`.local/runs/<RUN_ID>/state.json` with `public_url`, `postgres_port`,
`processing_port`, `ca_file`, `compose_project`, `env_file`; secrets stay in its
private environment file. On Linux, Firefox trust uses a temporary NSS profile seeded with
the project CA by the parent helper; system trust and certificate verification
remain intact. Its smoke must prove trusted HTTPS success and untrusted HTTPS
rejection. Full workflow/evidence/release targets fail clearly until their waves
supply the corresponding helpers.

CI always reports **Fast checks** and **Integration checks**, including when a
dependency fails or is skipped. Fast coverage is collected before combining real
legacy and Processing database evidence. Separate bounded jobs perform HTTPS
browser trust, SAST, and Trivy scans of the actual current app and Processing
images. The inherited zero fixable HIGH/CRITICAL policy remains enforced. Backend
lanes must extend integration selection and the image scan matrix for Media and
each distinct worker image before promotion (a shared API/worker digest needs
one scan); new Media/worker image files currently trigger a clear CI guard.

The following WSL/deployment instructions are inherited Project 1 documentation.
Current Project 2 setup and ownership instructions above take precedence.

## Prerequisites

- Windows 11 with WSL 2 and an Ubuntu distribution
- Docker Desktop with WSL integration enabled for Ubuntu
- Git configured inside WSL

Run all commands below inside Ubuntu WSL, not PowerShell:

```bash
cd /mnt/e/workspace/Media_player
```

## Quick start

Create the local environment file. `.env` is ignored by Git.

```bash
cp .env.example .env
```

Build and start all six services:

```bash
docker compose up --build -d
docker compose ps
```

Wait until every service reports `healthy`, then check the API:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/jobs
```

Expected responses from an empty installation:

```json
{"status":"ok"}
[]
```

Then open the app:

```text
http://localhost:3000
```

Choose a video file and click Upload. The status line moves through
`Queued...` -> `Processing...` -> `Processing complete.` and the player appears
with the processed result.

Use `localhost:3000` (or `127.0.0.1:3000`) exactly. The API's CORS allowlist
only accepts those two origins, and opening `frontend/index.html` directly from
disk will not work - the browser sends a `null` origin and every request is
blocked.

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.

View logs or stop the stack without deleting data:

```bash
docker compose logs -f api
docker compose down
```

`docker compose down -v` also deletes the local PostgreSQL, Redis, and MinIO volumes. Use it only when a completely clean local state is intended.

## Database migrations

The API container applies pending migrations before Uvicorn starts. Migrations can also be inspected or applied manually:

```bash
docker compose run --rm api alembic current
docker compose run --rm api alembic upgrade head
```

Inspect the current table directly:

```bash
docker compose exec postgres \
  psql -U flickpond -d flickpond -c '\d+ jobs'
```

The `jobs` table uses UUID identifiers and exactly four lowercase states:

```text
queued -> processing -> done
                     -> failed
```

Database constraints reject unknown states, a `done` row without `output_key`, and a `failed` row without a readable error. Indexes exist on `status` and `created_at`.

## Upload API

```http
POST /upload
```

Multipart form with a single `file` field. Stores the object, inserts the job
row, enqueues the job id, and returns immediately - it never waits for
processing:

```json
{"job_id": "9b4595b8-9bd3-4a71-b99d-488c7c7f381c"}
```

Returns `202`. Rejections:

| Status | Body                                                         | When                                                                                                                                                                    |
| ------ | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `413`  | `{"error": "file too large"}`                                | Above the 100MB limit. Checked against `Content-Length` before the body is read, and again against the bytes that arrived.                                              |
| `415`  | `{"error": "unsupported media type"}`                        | The declared `Content-Type` is not an accepted video type.                                                                                                              |
| `415`  | `{"error": "file content is not a recognized video format"}` | The bytes are not a recognised video container. The declared type is attacker-supplied — a browser fills it in from the file extension — so the content is checked too. |

The stored object is served back under the *sniffed* type, not the client's claim.

## Status API

Get one job:

```http
GET /jobs/{uuid}
```

Get a page of jobs, newest first:

```http
GET /jobs?limit=50&offset=0
```

`limit` defaults to 50 and is capped at 200; `offset` defaults to 0. Ordering is `created_at` descending with `id` breaking ties, so paging never repeats or drops a row. Out-of-range values return `422`.

Queued response:

```json
{
  "id": "9b4595b8-9bd3-4a71-b99d-488c7c7f381c",
  "filename": "demo.mp4",
  "status": "queued"
}
```

Completed response:

```json
{
  "id": "9b4595b8-9bd3-4a71-b99d-488c7c7f381c",
  "filename": "demo.mp4",
  "status": "done",
  "output_url": "http://127.0.0.1:9000/videos/...signed-query..."
}
```

Internal `source_key` and `output_key` values never appear in HTTP responses. A completed job receives a time-limited `output_url`; the frontend must use this URL for playback.

An unknown UUID returns:

```json
{"error":"not found"}
```

## Shared repository interface

`app.repositories.jobs` exposes asynchronous functions for the upload API and worker:

```python
create_job(session, filename=..., source_key=..., job_id=None)
get_job(session, job_id)
list_jobs(session, *, limit=50, offset=0)
mark_processing(session, job_id)
mark_done(session, job_id, output_key=...)
mark_failed(session, job_id, error=...)
```

Integration rules:

- B calls `create_job` after storing the source object, then enqueues the returned job ID.
- A is the sole caller of `mark_processing`, `mark_done`, and `mark_failed`.
- C's GET endpoints only read state and create output URLs.
- E reads `output_url`, never `output_key`, and stops polling on `done` or `failed`.

The transition functions use conditional SQL updates. Repeating or skipping a transition raises `InvalidJobTransitionError` instead of silently overwriting the row.

## MinIO addresses

Two endpoint variables are intentional:

- `MINIO_ENDPOINT=minio:9000` is the internal Compose address used by API and worker code.
- `MINIO_PUBLIC_ENDPOINT=127.0.0.1:9000` is embedded in signed URLs returned to the browser. The deployment sets it to `flickpond.com`.

Do not generate browser URLs with `minio:9000`; that hostname only resolves inside the Compose network. Set `MINIO_PUBLIC_ENDPOINT` to the public storage hostname when deploying remotely.

The **host is part of a SigV4 signature**, so the two endpoints cannot be swapped after a URL is signed, and `MINIO_PUBLIC_USE_SSL` must match the page's scheme or the browser blocks the result as mixed content.

## Tests and code quality

Start the dependency services, then run the full Python 3.12 test suite:

```bash
docker compose up -d postgres redis minio
docker compose run --rm \
  -e RUN_POSTGRES_TESTS=1 \
  -v "$PWD:/workspace" -w /workspace api \
  sh -c "python -m pip install -e '.[dev]' && \
         ruff check . && ruff format --check . && \
         pytest --cov=app"
```

Without `RUN_POSTGRES_TESTS=1`, tests that require a real PostgreSQL service are skipped. The configured coverage gate is 80%.

The frontend has its own suite (Node 20+ required):

```bash
cd frontend
npm install
npm test                                    # unit tests, mocked fetch
RUN_LIVE_TESTS=1 npx vitest run app.live.test.js   # against the running stack
```

CI sends Python and frontend coverage to SonarCloud for static security
analysis. Create the SonarCloud project with Automatic Analysis disabled, then
configure the repository with the `SONAR_TOKEN` secret and the
`SONAR_PROJECT_KEY` and `SONAR_ORGANIZATION` variables. The Quality Gate should
require an A security rating on new code. The scan currently reports its gate
result without blocking the PR while the initial baseline is reviewed; forked
PRs without access to the secret skip the scan with a warning.

The separate DAST workflow runs an authenticated OWASP ZAP API scan against an
isolated Compose stack on relevant pull requests, every Monday at 03:00 UTC,
and on manual dispatch. It never targets the deployed site. High, medium, low,
and informational findings are summarized without blocking the PR while the
baseline is reviewed; a ZAP infrastructure failure still fails the workflow.
HTML, JSON, Markdown, XML, and application logs are retained as workflow
artifacts for 30 days. No repository secret is required because every DAST
credential exists only for the lifetime of the disposable runner. The DAST
stack builds its pinned MinIO release from source because MinIO's community
container registries no longer allow anonymous pulls; this override does not
change the image used by normal deployments.

## Environment variables

| Variable                    | Meaning                                  | Local default              |
| --------------------------- | ---------------------------------------- | -------------------------- |
| `POSTGRES_DSN`              | Async API and worker database connection | Compose PostgreSQL service |
| `REDIS_HOST` / `REDIS_PORT` | Queue connection                         | `redis` / `6379`           |
| `REDIS_QUEUE`               | Shared RQ queue                          | `video_jobs`               |
| `MINIO_ENDPOINT`            | Internal object-store address            | `minio:9000`               |
| `MINIO_PUBLIC_ENDPOINT`     | Browser-accessible signed-URL address    | `127.0.0.1:9000`           |
| `MINIO_BUCKET`              | Source and output object bucket          | `videos`                   |
| `MINIO_REGION`              | Signing region                           | `us-east-1`                |
| `MINIO_USE_SSL`             | Whether MinIO uses TLS                   | `false`                    |

See [`.env.example`](.env.example) for the complete list. Never commit `.env` or real credentials.

## Git workflow

Each role has an integration branch. Create a short-lived personal branch from the role branch, open a pull request back to that role branch, and merge the completed role branch into `main` only after integration testing.

Example for track C:

```bash
git switch C-status-endpoints-db
git pull --ff-only
git switch -c <name>/c-status-db

# After committing and testing:
git push -u origin <name>/c-status-db
```

Before committing, confirm that `git config user.email` belongs to the contributor's GitHub account so the work appears in the contribution history.

## What is and is not built

Built, through sprint 2:

```text
register/login -> upload -> queued -> processing (FFmpeg 720p) -> done | failed
                                   -> status API -> playback URL
                     reaper recovers rows abandoned by a dead worker
```

Sprint 3 track C adds the owner-scoped `POST /jobs/{id}/retry` endpoint and
source-aware crop/clip validation. See the [C handoff](docs/c-recovery-input-safety.md)
for usage, transaction behaviour, and the B/E integration still required before
claiming the complete editing feature works in the browser.

Still out of scope here: format selection, quotas, resumable or multipart
upload, cloud orchestration, and instant session revocation (the JWT is
stateless and stays valid until it expires — see
[`docs/s2-03-auth-design.md`](docs/s2-03-auth-design.md) §1).

Upload is also **not atomic**: the object lands in MinIO before the job row is
committed, so a crash between the two leaves an orphaned object. The reaper
sweeps those; the reasoning is in
[`docs/sprint2-backlog.md`](docs/sprint2-backlog.md).
# Project 2 working repository

The former `Media_player` submodule now lives directly in this repository.
Run application, test and Docker commands from this root; no submodule checkout
is needed. See [current decisions and work log](docs/project2-worklog.txt).
For the first independent Processing service, see
[local setup and current scope](docs/processing-intake.txt).
The original application documentation follows below.


On macOS the pinned Chrome for Testing launcher validates the generated server
certificate against the project CA, then pins that certificate's public key for
that browser process. Linux uses Firefox with a temporary NSS CA profile. Neither
changes system trust; `make browser-trust-smoke` checks the trusted endpoint and
rejects an unrelated certificate. The macOS choice avoids a reproduced decoded-
frame copy failure in the bundled Firefox builds during H.264 playback.
