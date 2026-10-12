# Project 2 morning handoff

**Checkpoint: 13 October 2026, Singapore (UTC+8).** Planning and product PRs
#25–#30 are merged. **V1–V5 and final local delivery acceptance remain pending.**
This report prepares the handoff; it does not close V5 or certify the proposal.
The parent coordinator will insert exact final measurements and evidence links.

Documentation was prepared offline in `.worktrees/handoff`, starting from
`4a71f6779e499d072f9a9fac864f536f6fb03532`. This branch includes integration and
release corrections beyond the merged product checkpoint. Its HEAD must not be
reported as a tested Main release. Local Git history confirms PR30's merge at
`ea3950c61f4f9eaa5ad8dcbe1f726303f85e0764`; no remote state refresh was performed.

## First actions for the morning

1. Let the parent finish the existing full scaling run. It owns the frozen
   `.worktrees/integration` checkout at `621c03a`, namespace `v3-scale`.
   Do not change that checkout, restart its services, or run competing Docker,
   build, browser or other runtime workloads while measurement is active.
2. Preserve that run's manifest, raw records, failures and target assessment.
   Record its exact source/image/configuration identities before comparing it
   with the final combined source. Later harness fixes do not retroactively
   certify earlier measurements; the parent must assess their applicability.
3. After scaling releases the runtime, integrate/review the corrections and run
   final V1/V2 and V4 checks in separately owned namespaces. Fill the pending
   table below, including failures and any remaining blockers.
4. Reconcile Main, PRs, issues and Project 14 through authenticated `gh` only.
   The checked-in [progress ledger](progress.json) still shows clients in Review
   with no PR30 entry; that is an earlier checkpoint. Parent owns its update.
5. Obtain final independent review and exact-Main checks before marking V5 Done.
   Keep V3/E5 open if full scaling acceptance is unsatisfied. Complete the course
   report/demo pack separately; implementation is not those submissions.

## What is implemented

Two business services run in the local topology. Media Management (`media/`)
owns users, Assets, source intake, request identities, playback signing, edits,
owner deletion and durable submission reconciliation. Processing (`processing/`)
owns Jobs, Attempts, queue delivery, source renewal, FFmpeg execution, leases,
retry/cancel, output publication and recovery. They communicate over HTTP using
separate forward/reverse service tokens and owner/revision checks.

One PostgreSQL server hosts separate `media_db` and `processing_db` databases,
runtime/migration roles and Alembic histories. Redis/RQ belongs to Processing.
Private MinIO source/output buckets implement local S3-compatible storage. Media
has source access and output reads; workers have output PUT/multipart permission,
receive renewable source grants over HTTP, and have no source-store credentials.
Processing cleanup has output List/Delete permission. Compose passes scoped
configuration to each process rather than injecting the entire private env file.

The gateway exposes the new Media public API at `/api`; legacy `app/` remains a
regression reference. `media_engine/` holds pure inherited media helpers, with
[provenance](../../media_engine/README.md). Neither business service imports the
other's ORM/settings. The browser and independent Publisher call Media's public
API. Public `job_id` values identify Assets; internal Job/Attempt IDs are private.

| Persona | Implemented capability | Acceptance boundary |
| --- | --- | --- |
| Maya, course coordinator (UC-1–5) | Publisher registration/login, folder publishing, every file's outcome, bounded status waiting, authorised output links and stored-source retry | Earlier 30-good/1-rejected live batch supports the workflow; final combined V1 remains pending |
| Arun, independent trainer (UC-1–4) | Browser login, upload, status, MP4/HLS playback, stored-source retry, edit/derived copy and owner deletion | Earlier real browser recovery/playback/deletion supports the workflow; tightened final UI login and transport assertions remain pending |
| Jules, integrator (UC-1,3–5) | Documented public HTTPS API and separately installable CLI, cookie/CA configuration, stable replay identities and reproducible Make commands | Client review PASS covers controlled contracts/TLS; final two-service acceptance remains pending |
| Sam, operator (UC-6–7) | Heartbeats, lease fencing, queue repair, worker recovery, bounded cleanup, worker counts and independent Processing release/rollback runners | Runner/code checks exist; final fault timing, fair scaling and live release evidence remain pending |

These fictional personas describe workflows, not additional roles or sharing.
Publisher provides output access rather than a player/delete command. Upload
acceptance is durable intent, not finished encoding. Status 503 means unavailable;
clients must not turn it into a successful or fabricated processing state.
After uncertain delivery, reuse the same owner's cookie jar and original intent;
stored-source retry sends no video body. See [Publisher usage](../../publisher/README.md).

## New work and inherited work

| Inherited and reused | New Project 2 work |
| --- | --- |
| Existing frontend design/assets, cookie authentication approach, owner checks and editor/player behavior | Independent service boundaries and private data ownership; HTTP composition and durable Asset submission |
| FFmpeg/probe, clip/crop/scale/convert pipeline, MP4/HLS behavior and geometry checks | Attempt-aware execution, renewable source access, heartbeat/deadline supervision, cancellation fencing, queue repair and repeated cleanup |
| Legacy `app/`, migrations and tests; earlier local/Alibaba reports | Independent Publisher, browser stored-source retry and uncertain-action handling |
| Existing quality/image-scan policy | Locked setup, isolated runtime/TLS/browser tooling, package coverage gates, contract/fault/performance/release runners |

The imported media source was commit `885453726d629c524bf511d665311863d9bc70a5`.
The flattening preserved the roadmap's design and illustrations; its 160 source
links were repaired. Original proposal/course documents remain intact. Historical
Alibaba evidence describes the inherited platform and is not new Project 2 cloud
acceptance. No inherited Alibaba deployment is to be operated for this work.

## Delivery map

Project: [dc2 — Pre-AWS local delivery, #14](https://github.com/users/Collaboration95/projects/14).
The waves below are execution milestones, not claims of completed course dates.
Detailed dependencies are in [issue-map.md](issue-map.md),
[plan.md](plan.md) and the [local issue contracts](issues/).

| Wave / epic | Child issues | PR / merge | Checkpoint |
| --- | --- | --- | --- |
| 0 / E0 [#1](https://github.com/Collaboration95/dc2/issues/1): plan | G1 [#7](https://github.com/Collaboration95/dc2/issues/7), G2 [#8](https://github.com/Collaboration95/dc2/issues/8) | [#25](https://github.com/Collaboration95/dc2/pull/25), `6ea8b9b` | Merged; planning rereview PASS |
| 1 / E1 [#2](https://github.com/Collaboration95/dc2/issues/2): foundation | F1 [#9](https://github.com/Collaboration95/dc2/issues/9), F2 [#10](https://github.com/Collaboration95/dc2/issues/10), F3 [#11](https://github.com/Collaboration95/dc2/issues/11) | [#26](https://github.com/Collaboration95/dc2/pull/26), `dbc9a4b`; cache correction [#27](https://github.com/Collaboration95/dc2/pull/27), `49b693e` | Merged; late cache finding resolved with warm CI evidence, no waiver |
| 2A / E2 [#3](https://github.com/Collaboration95/dc2/issues/3): Processing | P1 [#12](https://github.com/Collaboration95/dc2/issues/12), P2 [#13](https://github.com/Collaboration95/dc2/issues/13), P3 [#14](https://github.com/Collaboration95/dc2/issues/14) | [#28](https://github.com/Collaboration95/dc2/pull/28), `4efc41c` | Merged; bounded recovery-lock rereview PASS |
| 2B / E3 [#4](https://github.com/Collaboration95/dc2/issues/4): Media | M1 [#15](https://github.com/Collaboration95/dc2/issues/15), M2 [#16](https://github.com/Collaboration95/dc2/issues/16), M3 [#17](https://github.com/Collaboration95/dc2/issues/17) | [#29](https://github.com/Collaboration95/dc2/pull/29), `b4a9f56` | Merged; uncertain-write cleanup rereview PASS |
| 2C / E4 [#5](https://github.com/Collaboration95/dc2/issues/5): clients | C1 [#18](https://github.com/Collaboration95/dc2/issues/18), C2 [#19](https://github.com/Collaboration95/dc2/issues/19) | [#30](https://github.com/Collaboration95/dc2/pull/30), `ea3950c` | Merged; client R1–R3 rereview PASS |
| 3 / E5 [#6](https://github.com/Collaboration95/dc2/issues/6): integration/faults | V1 [#20](https://github.com/Collaboration95/dc2/issues/20), V2 [#21](https://github.com/Collaboration95/dc2/issues/21) | Final integration PR: **PENDING** | Final combined-head acceptance **PENDING** |
| 4 / E5: measurements/release/handoff | V3 [#22](https://github.com/Collaboration95/dc2/issues/22), V4 [#23](https://github.com/Collaboration95/dc2/issues/23), V5 [#24](https://github.com/Collaboration95/dc2/issues/24) | Final evidence/handoff PR(s): **PENDING** | Full scaling running at frozen checkpoint; release/final review **PENDING** |

V1 depends on P3/M3/C1/C2; V2/V3/V4 depend on V1. V5 has native dependencies
V2/V4 and an assessed V3 prerequisite. A documented capacity blocker can support
an honest limited handoff; it does not complete V3 or E5. Available 8-CPU capacity
alone does not establish scaling results.

## Commands for the parent after the frozen run finishes

Run from the selected final repository root, not inside the frozen measurement
checkout. These commands were read from Make/helpers; **none was executed during
this documentation task**. Use a dedicated namespace and serialize runtime work.
Python 3.12+, locked dependencies, Node/npm, Docker/Compose, FFmpeg/ffprobe,
OpenSSL and the pinned project browser are prerequisites; `doctor` diagnoses them.

```sh
cd /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2
make help
make setup
make doctor
make doctor-infra
make browser-install RUN_ID=handoff-local
# If the project-local Lima VM is stopped, start the existing VM first:
make capacity-start
make up RUN_ID=handoff-local
make env RUN_ID=handoff-local
make status RUN_ID=handoff-local
make smoke-infra RUN_ID=handoff-local
make browser-trust-smoke RUN_ID=handoff-local
make browser-open RUN_ID=handoff-local
```

`make up` builds/starts the isolated topology, applies migrations and runs
infrastructure smoke. `make env`/`status` print safe state. Read `public_url` and
`ca_file` from `.local/runs/handoff-local/state.json`: browser origin is
`https://localhost:<allocated-port>`, API base is that origin plus `/api`, and
public health is `/api/health`. No fixed 8000/9000 origin should be copied from
inherited documentation for this topology. Container peers use
`http://processing:8000`, `http://media:8000` and `minio:9000`; those are internal
origins, not browser/CLI URLs. Register a local demo account; no fixed demo
password is supplied here.

```sh
make lint
make test
make test-processing
make test-media
make test-cli
make verify-local RUN_ID=handoff-local
make e2e RUN_ID=handoff-local
make evidence-recovery RUN_ID=handoff-local
```

`verify-local` runs fast/frontend coverage, isolated real integration for all
services, per-package coverage gates, infrastructure/TLS smoke and supervised
browser/CLI E2E. Standalone `e2e` is available to retain a separate workflow run;
it is already included in full verification. Fast `make test` does not exercise
live services. `make integration`/`integration-coverage` require explicit enabled
`RUN_*` flags and isolated configuration; disabled tiers do not count as proof.
Combined Python statement/branch coverage must be >=80% per package, with raw
branches reported separately; all four frontend gates remain >=90%.

For performance use a separate healthy namespace with 1–3 running capped workers.
For scaling use a separate healthy namespace with workers stopped before launch.
Do not run these namespaces concurrently on the measurement VM.

```sh
make up RUN_ID=handoff-perf
# This cost label is valid only after confirming the built Media/new-account cost.
make evidence-performance RUN_ID=handoff-perf EVIDENCE_ARGS="--login-hash-cost 'bcrypt rounds=10'"
# evidence-status is an alias for the same status + separate login experiment.
make down RUN_ID=handoff-perf

make up RUN_ID=handoff-scale
.venv/bin/python - <<'PY'
from scripts.dev.runtime import configure, compose
_, state = configure('handoff-scale')
compose(state, 'stop', 'worker', timeout=75)
PY
make evidence-scaling RUN_ID=handoff-scale
make down RUN_ID=handoff-scale
```

Full defaults preserve three rotated repeats (nine scaling runs): each has 30
fresh Assets from identical 60s 720p bytes, with workers capped at 2 CPU / 1536 MiB.
The fixed nonworkers total 2 CPU; three workers require 8 CPU before other
reservations. Status/login use separate 50/20-owner tests, 30s warmup and 180s
measurement intervals, three repeats. `EVIDENCE_ARGS='--pilot ...'` is diagnostic
only. Reduced/pilot/dirty-source runs must not be counted as full acceptance.
The host generator and VM share the physical Mac; this differs from a separate
load-generator host and must remain visible in the report.

For local release, use clean combined source and an isolated healthy runtime.
The common-root pinned Trivy binary/cache must already be available; exact-image
artifact and zero-fixable-HIGH/CRITICAL scan gates must pass before promotion.

```sh
make up RUN_ID=handoff-release
make evidence-release RUN_ID=handoff-release
# Individual operations, when needed:
make release RUN_ID=handoff-release
make rollback RUN_ID=handoff-release
make down RUN_ID=handoff-release

make logs RUN_ID=handoff-local
make down RUN_ID=handoff-local
```

Release changes Processing API/worker/recovery/migrations only. Existing Media
container/image identities and `media_db` revision must remain unchanged. New
Processing revisions need explicit reviewed additive compatibility via
`RELEASE_ARGS='--additive-migrations'` (or `EVIDENCE_ARGS` for evidence-release).
A pending recovery journal blocks normal startup/build/release until rollback.
A failed deployment with successful rollback remains a failed release (exit 2);
only the evaluated good/bad experiment may pass as evidence. `down` preserves
volumes and credentials. Do not prune/delete evidence or stop the shared VM while
another namespace still uses it.

## Browser trust and private locations

The pinned Playwright 1.63.0 tooling uses Chrome for Testing 153.0.8010.12 on
macOS and Firefox 155.0 with temporary NSS CA profiles on Linux. On this Mac,
Firefox received/buffered MP4/HLS but failed to copy decoded AppleVT frames;
the final launcher changed browser instead of changing media output.

The macOS launcher validates certificate/hostname/expiry against the generated
project CA, then pins the leaf certificate's SHA-256 SPKI for that browser
process. Linux imports the CA into a disposable NSS profile. This is scoped
browser trust; no system trust changes, certificate-error bypass or
`ignore_https_errors` are used. Trusted-positive and unrelated-certificate
negative controls are required. CLI uses `--ca-file` with certificate/hostname
verification enabled. See [browser diagnostic/design evidence](reviews/browser-acceptance.md).

Paths below are relative to the checkout owning the run unless stated otherwise.
Only locations are listed; do not publish their contents.

| Location | Purpose |
| --- | --- |
| `.local/runs/<run-id>/runtime.env` (0600) | Generated DB/Redis/storage passwords, runtime/migration DSNs, JWT secret and separate service tokens |
| `.local/runs/<run-id>/state.json` | Safe origin/ports/CA/config-file references; not a credential dump |
| `.local/runs/<run-id>/tls/ca.key`, `server.key` (0600) | Private TLS keys; `ca.crt` is the CLI trust file |
| Chosen Publisher jar, e.g. `.local/publisher/<run-id>/cookies.txt` (0600) | Private cookie session; sibling `cookies.intents.json` and `cookies.lock` retain replay/locking state |
| `.local/runs/<run-id>/publisher-e2e/cookies.txt` | E2E's private Publisher cookie jar and sibling state |
| `.env`, if configured | Ignored inherited/local configuration preserved by setup; not the new per-run source of truth |
| Common root `.local/lima/`, `.local/docker/` | Scoped VM keys/state and Docker configuration; no global context change |
| `.local/runs/<run-id>/releases/`, `release.override.json` | Private release journal, exact-image proofs, pending recovery and persisted image choice |

Automated accounts are generated locally; performance account credentials remain
in process memory. Enter interactive Publisher passwords at the prompt, or use
`--password-stdin` for automation. No credential values belong in argv, Git,
screenshots or the report. Normal CLI output links are expiring capabilities,
not permanent shareable identifiers. `.local/`, `.cache/`, `artifacts/`, `.env`
and worktrees are ignored; retained evidence must be transferred deliberately.

## Recorded checkpoints and pending final measurements

These are attributed historical observations, not fresh verification of this
handoff's source. See the [dated worklog](../project2-worklog.txt) for earlier counts.

| Supporting observation | Source and qualification |
| --- | --- |
| Processing: 644 fast Python + 45 real owned checks at reviewed PR28 head | [Processing rereview](reviews/processing-rereview.md); product lane, not full V1/V2 |
| Media: 770 fast Python + 127 real checks (44 legacy / 45 Processing / 38 Media); combined Media coverage 98.19% | [Media validation](reviews/media-validation.md); final combined-head gates must be recollected |
| Clients: 827 Python / 152 frontend; separate real TLS test; Publisher combined coverage 98.43% | [Client validation](reviews/clients-validation.md), [client rereview](reviews/clients-rereview.md); product acceptance, not final V1 |
| Earlier browser flow: 78.802s total, worker failure visible in 66.521s, retry/playback/deletion | [Browser report](reviews/browser-acceptance.md); predates explicit UI login and separate decoded HLS/MP4 assertions |
| Login diagnostic: two 20-user bursts, p90 985.174ms / 1044.029ms, all 40 HTTP 200 | [Login pilot](reviews/login-performance.md), tested product `90d369a`; cost 10 / Media 1 CPU. Not full-duration V3 |
| Performance runner bounded R1–R5 rereview PASS, 63 offline tests | [Runner rereview](reviews/performance-runner-rereview.md); no live throughput claim |
| Integration corrections: 33 offline harness regressions; CT-23 offline examples checked, CT-20/21 live pending | [Integration fixes](reviews/integration-fixes.md), [contract fixes](reviews/contract-fixes.md) |
| Release corrections: 81 release / 140 dev offline tests; actual scratch bad-image build | [Release fixes](reviews/release-fixes.md); build compatibility only, not release/rollback acceptance |

**Parent fill-in table — every final result below is PENDING at this checkpoint.**
Retain exact UTC timestamps, Git SHA, clean/dirty state, image IDs/digests,
configuration, fixture SHA-256, quotas, command, raw artifact path/hash and review
verdict. Report missed targets as misses; never replace them with a pilot.

| Gate / original target | Final measurement and acceptance |
| --- | --- |
| V1: full HTTPS browser/CLI workflow; all 25 CT cases with evidence-backed dispositions | **PENDING:** combined SHA, full verify/E2E results, UI login, decoded HLS + MP4, retry/deletion, CLI batch, CT-20/21 real runs and CT-23 mapping |
| V2: worker failure <=300s; lost queue entry repair <=120s with surviving metadata; P outage survives restart; retry/no duplicate output | **PENDING:** fault timings, Asset/Job/Attempt identities, replica restoration and raw result |
| V3 status: 50 users / 180s, p90 <=700ms, errors <1% | **PENDING:** full-repeat p90/error samples and assessment |
| V3 login: 20 concurrent users, p90 <2s, measured separately | **PENDING:** full-repeat p90, actual hashing cost, errors/session protocol observations |
| V3 scaling: 30 identical 60s 720p clips, 1/2/3 workers at hard 2 vCPU | **PENDING:** nine-run throughput/queue/processing/CPU/memory/failure table; fixture/resources and frozen `621c03a` applicability assessment |
| V3 scaling targets: 2 workers >=1.6x, 3 >=2.1x, falling median queue wait, zero failed jobs | **PENDING:** computed target results, including misses/limitations |
| V4: independent Processing promotion + smoke <=600s; unchanged Media; bad candidate rollback | **PENDING:** distinct good/bad exact images/scans, actual exit-42 startup proof, nonempty drain <=300s, promotion/restore times and smoke |
| V5: final independent review, accepted merges, exact Main checks and metadata reconciliation | **PENDING:** review verdict, final Main SHA/CI, PR numbers, issue/project dispositions and durable report/demo pack |

## Evidence source pack and limitations

Start with [execution plan](plan.md), [interfaces](interfaces.md),
[decisions](decisions.md), [contract case map](contract-evidence.json) and the
review links above. The original review failures remain historical records;
bounded rereview PASS supersedes only its stated correction scope. Some older
plans still describe superseded Firefox policy/CPU defaults; current browser
report, login resource profile and code define this checkpoint.

Raw workflow/fault runs live at `artifacts/<run-id>/<scenario>-<UTC>-<id>/result.json`
with sibling screenshots and latest pointers. Supervisor outcomes are
`artifacts/<run-id>/e2e-supervisor-<id>.json`. Full performance/scaling retains
`artifacts/evidence/<run-id>/<action>-<UTC>-<id>/` manifests, raw JSONL,
per-run CSV/JSON, `runs.json`, `targets.json` and scaling `targets.csv`.
Coverage/gates are under `artifacts/coverage/`; coordinator logs under
`.cache/execution/`. Release proofs live in the private locations above.
Paths are discovery patterns, not assertions that final files already exist.
The parent must fill exact final paths/hashes and preserve a sanitised source pack
for teammates; ignored local artifacts are not delivered by a Git commit.

Continuous recovery is required. Stable Asset guards and uncertain-write cleanup
ledgers are deliberately retained for the demo lifetime; that has a small ongoing
row/cleanup cost. Existing higher-cost bcrypt hashes still verify at their stored
cost. Publisher uses POSIX flock (macOS/Linux), immediate regular files and bounded
polling; it is not directory synchronisation. No new sharing, search, multipart
upload, autoscaling or editor features are in scope. The recorded 857s client
implementation/testing interval interleaves C1/C2 and excludes some preparation;
it is not complete member effort or proof of the proposed two-person-day CLI
allocation. Final Linux playback acceptance, measured effort and report/presentation work
remain pending.

## Local versus AWS and academic milestones

All new observations here are local. No AWS provisioning or cloud acceptance is
claimed. Future deployment remains one EC2/Compose demo host plus private S3,
with separate data ownership, scoped credentials and manual release promotion.
Before AWS work, supply the actual project account, region, spending limit,
domain, scoped credentials and adequate compute. Another project's AWS account
or configuration is not an approved substitute. Do not operate inherited Alibaba.

The accepted proposal allocates 31 person-days; the implementation target is three
elapsed agentic days, maximum five. Those are different measures. A fourth/fifth
day addresses a concrete required gap, not extra product scope.

The [preserved roadmap](../../project-roadmap/roadmap-data.json) records these
planning/course dates; they were not revalidated with Canvas during this offline
handoff:

| Recorded milestone | Relationship to this delivery |
| --- | --- |
| 14 Oct: proposal integrated boundary/web workflow and CLI started | Product PRs are merged early; final integrated V1 proof still pending |
| 16 Oct: first and only weekly progress report (user D-06) | Use dated evidence and explicit pending results; report itself remains to finish |
| 20 Oct: proposed AWS/experiment completion | Local evidence and AWS deployment are separate; AWS prerequisites unresolved |
| 25 Oct: suggested rehearsal/pack ready | Preserve time for fixes, evidence and rehearsal |
| 26 Oct, 14:35–15:15 Singapore: recorded Team 17 slot | 40-minute allocation includes questions; verify later course changes in Canvas |
| 13 Nov: suggested all-member report review; 16 Nov: recorded final report deadline | Exact submission cutoff/format not established by these local files |

Keep [original academic materials](../../project-documentation/) and roadmap
visuals intact. Use actual contribution provenance, measured results, limitations,
DDD justification, member effort and AI-tool declaration in the final report.
