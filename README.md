# FlickPond: a reusable cloud media processing platform

Team 17, SWE5001 Architecting Scalable Systems Practice Module (NUS, September to November 2026).
Start here. This page describes the system as built (V1, git tag `project2-v1`). Earlier planning and
Project 1 material is labelled historical and listed at the end.

## What it is

FlickPond lets an application upload a video, have it converted to MP4 and adaptive HLS (360p, 480p,
720p, never above the source height), follow the job, and play the result through an owner-checked
link. Applications use one documented HTTP API and never touch storage, queues or FFmpeg. Two clients
exist: the FlickPond web app (`frontend/`) and an independent Publisher CLI (`publisher/`).

It runs on AWS in one region (ap-southeast-1): CloudFront, API Gateway, Lambda container images, SQS,
Aurora PostgreSQL Serverless v2, S3, and finite Fargate tasks for the encoder. Nothing runs while it is
idle except storage; the stack is operated as booked sessions.

## Architecture

![Physical architecture on AWS](docs/architecture/img/views-physical.svg)

Logical view, domain model and sequence diagrams are in [`docs/architecture/`](docs/architecture/README.md):
[logical and physical views, persistence, upload-to-play sequence](docs/architecture/views.md),
[DDD model](docs/architecture/ddd.md), and the [ADR register, deviations from the proposal and
limitations](docs/architecture/decisions.md).

![Context map of the two bounded contexts](docs/architecture/img/ddd-context-map.svg)

## Two services

| Service | Owns | Code |
|---|---|---|
| **Media Management** | Accounts, ownership, upload intake, playback links, the public job view | [`media/`](media/) |
| **Processing** | Jobs, attempts, leases, retry and cancel, output descriptors, the finite encoder | [`processing/`](processing/), [`media_engine/`](media_engine/) |

Why these are microservices and not one app split into folders (each point has a code or receipt link in
[`decisions.md`](docs/architecture/decisions.md)):

- Each has its own container image, its own Lambda functions and IAM roles, and its own CI lane
  (`.github/workflows/ci.yml`, `.github/CODEOWNERS`).
- Each owns its database and migrations on the shared Aurora cluster. A runtime login for one cannot
  connect to the other's database (live receipt `cross-database`).
- They never call each other. They exchange five message kinds over three SQS queues, with an outbox
  and inbox in each database; Media keeps its own read model of Processing's state.
- Each can be released alone (Lambda image digest and alias): the live release receipt shows the peer
  unchanged at every snapshot. `deploy/v1/check_runtime.py` fails an image build if the other
  service's package or any retired peer-HTTP module is present.
- The published language is [`contracts/`](contracts/README.md) with a versioning policy and
  consumer-driven tests.

Honest limits: one CloudFormation stack, one Aurora cluster (a shared failure and capacity boundary),
a monorepo with one lockfile, and `contracts/` copied into both images. See
[limitations](docs/architecture/decisions.md#6-architectural-limitations).

## Run it locally

Local V1 uses real PostgreSQL 16, FFmpeg and Docker, with Moto standing in for S3 and SQS and an
in-process API Gateway bridge. It does not exercise IAM, Lambda, Fargate or Aurora. Prerequisites:
Docker Compose, FFmpeg/FFprobe and the locked Python environment (`make setup`). Details and what is
emulated: [`local-runtime.md`](docs/execution/aws/v1/local-runtime.md).

```sh
make setup
make test-v1                                                     # offline contract tests, no services
make v1-up V1_RUN_ID=demo1                                       # PostgreSQL + loopback Moto
make verify-v1 V1_RUN_ID=demo1 FLOW=all V1_BROWSER=1             # every flow plus the browser leg
make v1-serve V1_RUN_ID=demo1                                    # loopback Gateway bridge to the real handlers
make v1-down V1_RUN_ID=demo1 DELETE_DATA=1                       # remove only this run's data
make help                                                        # every target
```

Other useful targets: `make lint`, `make test` (fast Python and frontend suites), `make lint-cfn`
(renders and lints the CloudFormation template offline), `make v1-images` (builds and verifies the three
images; local evidence only).

## Deploy to AWS

Deployment is operator-run and costs money. Nothing is applied unless `execute=true`.

- **Pipeline:** the CD workflow [`.github/workflows/cd.yml`](.github/workflows/cd.yml) (preflight,
  deploy, release, teardown) over a GitHub OIDC role
  ([`deploy/aws/v1/github-oidc.yaml`](deploy/aws/v1/github-oidc.yaml)). It refuses a commit without green
  CI. Example: `gh workflow run cd.yml -f operation=preflight -f run_id=<run id>`.
- **Runbook:** [`deploy-runbook.md`](docs/execution/aws/v1/deploy-runbook.md) covers the deploy ladder,
  sessions, the cloud proof steps, release and rollback, teardown, and the section
  "Operator handoff: CD deploy, then session and evidence from a laptop".
- **Template:** `scripts/aws/v1/definitions.py` renders `deploy/aws/v1/template.json`;
  [`deploy/aws/v1/README.md`](deploy/aws/v1/README.md) explains the two phases and the closed-by-default
  session model. Account, quotas and authorization: [`account-receipt-20261017.md`](docs/execution/aws/v1/account-receipt-20261017.md).
- **Status:** two live runs, both torn down. `r1017b` (17 October, operator CLI) proved V1 on AWS.
  `r1018b` (17 to 18 October, deployed through the CD workflow) added backlog scaling, independent
  releases, the Processing-down proof and the unattended launcher. Results include two FAILs reported
  as FAILs: 2-worker scaling at 1.449x against 1.6x, and Processing release at 10.1 to 10.3 min against
  10 min. The CD pipeline is not yet green end to end (pending run `r1019a`). See the evidence index.

## API specifications

- [`docs/api/media.openapi.json`](docs/api/media.openapi.json): accounts, direct-to-S3 upload
  reservations, owned jobs, edit, HLS delivery (`/api/media/*`).
- [`docs/api/processing.openapi.json`](docs/api/processing.openapi.json): owner-scoped job status, retry
  and cancel (`/api/processing/*`).
- Queue messages: [`contracts/`](contracts/README.md) (envelope, source descriptor, trusted actor).

## Evidence

- Live AWS receipts (runs `r1017b` and `r1018b`, redacted): [`docs/execution/aws/v1/evidence/`](docs/execution/aws/v1/evidence/).
  Each receipt lists what it does not prove.
- Local image receipts are in the same folder; local acceptance output is described in
  [`local-runtime.md`](docs/execution/aws/v1/local-runtime.md). Local results are not AWS results.
- Quality scenarios and security controls against the proposal targets, with local and cloud results
  labelled and FAILs stated: [`docs/evidence-index.md`](docs/evidence-index.md).
- Running log: [`docs/project2-worklog.txt`](docs/project2-worklog.txt).

## Publisher CLI

[`publisher/`](publisher/README.md) is an independent client of the public HTTPS API: it imports no
service code and holds no database or storage credentials. It registers or logs in, bulk-publishes a
folder, and polls status and output. Because V1 encoders are started by an operator, a published job
waits in the queue until a batch is started.

```sh
make publisher ARGS='--help'
python -m publisher --base-url https://<cloudfront-domain>/api --json login you@example.com
python -m publisher --base-url https://<cloudfront-domain>/api --json publish ./videos --wait
```

## Repository map

| Path | Contents |
|---|---|
| `media/`, `processing/`, `media_engine/` | The two services and the FFmpeg command builders |
| `contracts/`, `delivery/`, `runtime_support/` | Shared kernel copied into both images: message contracts, outbox/inbox and SQS adapter, Lambda runtime helpers |
| `frontend/`, `publisher/` | Web app (static, no bundler) and the Publisher CLI |
| `scripts/aws/v1/` | Template builder, deploy, session, release and evidence tooling for the AWS stack |
| `scripts/dev/`, `scripts/ci/` | Local V1 runtime and verification; CI policy |
| `deploy/aws/v1/`, `deploy/v1/` | Rendered template, OIDC stack, image recipes and `check_runtime.py` |
| `.github/workflows/` | `ci.yml` (per-service lanes, scans), `cd.yml` (deploy, release, teardown), `v1.yml`, `dast.yml` |
| `tests/` | `v1/` (messaging, gateway, workflow), `aws/v1/` (control plane), `media/`, `processing/`, `contracts/` |
| `docs/architecture/` | DDD model, decisions, views, diagrams |
| `docs/execution/aws/v1/` | V1 runbooks, receipts, evidence, local runtime |
| `docs/api/` | OpenAPI documents |
| `project-documentation/` | Course proposal, briefing, report template notes, proposal images (do not edit) |
| `legacy/` | Retired peer-HTTP and Redis/RQ code, kept out of the V1 images |
| `app/`, `compose/`, `docker-compose*.yml`, `nginx.conf`, `migrations/` | Project 1 baseline and the pre-AWS local stack (CI's legacy lane) |
| `docs/history/` | Superseded root documents (old README, hand-off briefs) |

## Historical material

Planning packets, local-delivery records, Project 1 sprint documents and the old root README are kept
for provenance and carry a "Historical" banner on their first line. Index: [`docs/README.md`](docs/README.md).
The old root README, with the Project 1 architecture and the pre-AWS local stack commands, is
[`docs/history/README-project1-and-pre-aws-local-stack.md`](docs/history/README-project1-and-pre-aws-local-stack.md).
