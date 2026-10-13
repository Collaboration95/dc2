# Project 2 morning handoff

**13 October 2026, Singapore (UTC+8): local pre-AWS delivery complete, including PostgreSQL readiness correction.**
PR32 merged at [`f10bf04899e6cc80f992c65193a92fbe0b0ce8b2`](https://github.com/Collaboration95/dc2/commit/f10bf04899e6cc80f992c65193a92fbe0b0ce8b2);
[PR CI38330508848](https://github.com/Collaboration95/dc2/actions/runs/38330508848) passed all 15 checks and
[Main CI38331089024](https://github.com/Collaboration95/dc2/actions/runs/38331089024) succeeded with all 14 Actions jobs.
[Independent correction review](reviews/postgres-readiness-review.md) PASS.
All 24 issues, including six epics, are closed; all 24 Project items have
Status and Workflow Done.
[Current completion pack](evidence/main-f10bf04/index.json) retains CI, merge,
metadata and successful postmerge local startup evidence.
These results certify product merge f10bf04. CI for subsequent documentation revisions is recorded in GitHub Actions.
The working target is **three elapsed agentic days, five maximum**, applying 80/20:
reuse the media engine/frontend and prove service boundaries, separate ownership,
web/CLI workflows, independent deployment and measured recovery/scaling.
The proposal's **31 person-days** is its effort allocation, not this coding schedule.

## Completion and demo use

Preserve `.worktrees/final-measurements` frozen at `f46599f`, all raw records
and failed historical runs. Measurements are complete and the VM is released.
Root `RUN_ID=local` is healthy at **https://localhost:54440**, coordinator-confirmed
after successful postmerge startup and infrastructure smoke; [startup log](evidence/main-f10bf04/local-up.log).
Earlier browser-trust smoke remains in its [original pack](evidence/local-demo-20261013/index.json).
CI38329462068 remains a failed startup record; the TCP correction and accepted
PR32/Main runs resolve that failure. Course report/demo preparation remains
separate work; AWS prerequisites are listed below.

## Start, use and stop the local demo

Run from the repository root; measurements have finished and the VM is released.
Commands here were checked against source; current smoke was run by the parent.
This documentation task ran no live commands.
Prerequisites: Python 3.12+, Node/npm, Docker/Compose, FFmpeg/ffprobe, OpenSSL and the pinned browser; `doctor` diagnoses gaps.

```sh
cd /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2
make setup
make doctor
make browser-install RUN_ID=local
make capacity-start                 # Start the existing project VM if stopped.
make up RUN_ID=local
make env RUN_ID=local
make status RUN_ID=local
make smoke-infra RUN_ID=local
make browser-trust-smoke RUN_ID=local
make browser-open RUN_ID=local
# After the demo:
make logs RUN_ID=local
make down RUN_ID=local
```

`up` builds/starts the topology, applies migrations and runs infrastructure smoke.
Root `local` has an existing allocation at **https://localhost:54440**; it is
**healthy, coordinator-confirmed** after `make up` exited 0 and
`make status` showed all services healthy. Postmerge `make up` included passing infrastructure smoke. Earlier
`make browser-trust-smoke` passed at its recorded source; retained logs are linked above.
Read `public_url` and `ca_file` from `.local/runs/local/state.json` after startup;
that state is authoritative. API base is `<public_url>/api`, health `/api/health`.
`down` preserves data and credentials; do not prune volumes or stop a shared VM.

Register a local browser account (no fixed password); Publisher uses the same owner's private jar:

```sh
DC2_PUBLIC_URL=$(.venv/bin/python -c 'import json; print(json.load(open(".local/runs/local/state.json"))["public_url"])')
DC2_CA_FILE=$(.venv/bin/python -c 'import json; print(json.load(open(".local/runs/local/state.json"))["ca_file"])')
pub() { .venv/bin/python -m publisher --base-url "$DC2_PUBLIC_URL/api" --ca-file "$DC2_CA_FILE" --cookie-jar .local/publisher/local/cookies.txt --json "$@"; }
pub login your-email@example.com    # Password is prompted; register is also available.
pub publish ./videos --wait --max-polls 60 --interval 2
pub status ASSET_UUID
pub output ASSET_UUID
pub retry ASSET_UUID --wait
```

Publisher reports every file; exit 1 can mean partial success or a polling limit.
Acceptance means durable intent; `done` means finished encoding. After
uncertain delivery, log in with the same owner's jar and replay the original intent.
Stored-source retry sends no video body. See [Publisher usage](../../publisher/README.md).

## Architecture and people

Browser and independent Publisher → HTTPS gateway `/api` → **Media Management**
(`media/`) → HTTP → **Processing** (`processing/`). Processing renews source grants
through Media over reverse HTTP. Neither service imports the other's ORM/settings.

Media owns users, Assets, source intake, request identities, signing, edits,
deletion and durable submission reconciliation. Processing owns Jobs/Attempts,
Redis/RQ, FFmpeg, leases, retry/cancel, publication and recovery.
One PostgreSQL server hosts private `media_db`/`processing_db`, separate roles and
migration histories. MinIO has private source/output buckets; workers receive
renewable source grants and output-write access without source-store credentials.
Public `job_id` values identify Assets; internal Job/Attempt IDs stay private.

| Persona | Morning workflow |
| --- | --- |
| Maya, course coordinator | Publish a folder, inspect every outcome, wait/status, access output, retry stored source |
| Arun, independent trainer | Browser login/upload, status, HLS/MP4 playback, retry, edit/derived copy, owner deletion |
| Jules, integrator | Public HTTPS API and separately installable Publisher; stable intent replay and reproducible commands |
| Sam, operator | Heartbeat/queue recovery, capped worker scaling, independent Processing promotion/rollback |

Personas add no roles/sharing. Inherited frontend, authentication, player/editor
and FFmpeg helpers are reused. New work adds service boundaries, private ownership,
durable attempts/reconciliation, Publisher and verification/release tooling.
`app/` is a regression reference; shared helpers retain [provenance](../../media_engine/README.md).

## PR and issue map

| Delivery | Issues | PR / checkpoint |
| --- | --- | --- |
| Planning E0 | G1/G2 #7–8 | [#25](https://github.com/Collaboration95/dc2/pull/25) merged `6ea8b9b` |
| Foundation E1 + cache correction | F1–F3 #9–11 | [#26](https://github.com/Collaboration95/dc2/pull/26) `dbc9a4b`, [#27](https://github.com/Collaboration95/dc2/pull/27) `49b693e`, merged |
| Processing E2 | P1–P3 #12–14 | [#28](https://github.com/Collaboration95/dc2/pull/28) merged `4efc41c` |
| Media E3 | M1–M3 #15–17 | [#29](https://github.com/Collaboration95/dc2/pull/29) merged `b4a9f56` |
| Clients E4 | C1/C2 #18–19 | [#30](https://github.com/Collaboration95/dc2/pull/30) merged `ea3950c` |
| Local acceptance E5 | V1–V5 #20–24 | [#31](https://github.com/Collaboration95/dc2/pull/31) merged `66014d0`; [#32](https://github.com/Collaboration95/dc2/pull/32) readiness correction merged `f10bf04`; V1–V5/E5 Done |

Details: [progress](progress.json), [issues](issue-map.md), [plan](plan.md), [interfaces](interfaces.md), [decisions](decisions.md).

## Accepted local results

The measured results below retain their accepted source identities. V5/E5
completion includes the independently reviewed readiness correction and exact
PR32/Main CI passes after the subsequent fresh-start failure.
Their original source identities remain explicit.
Retain exact source/image/config/fixture identities, raw paths/hashes and review
scope. New measurements must come from complete runs; pilots cannot replace them.

| Gate / target | Recorded result or final field |
| --- | --- |
| V1: full HTTPS web/CLI and 25 contract dispositions | **PASS at `422609b`**: 1,083 fast Python / 152 frontend / 130 real integration; full Mac E2E **122.740s**. UI login, decoded HLS/MP4, 30-good/1-rejected Publisher batch, stored retry and deletion. [Contract/evidence review](reviews/contract-final.md) |
| Final PR / Main CI | **PASS:** exact PR `ccd15f8`, [38330508848](https://github.com/Collaboration95/dc2/actions/runs/38330508848), all 15 checks; exact Main `f10bf04`, [38331089024](https://github.com/Collaboration95/dc2/actions/runs/38331089024), all 14 Actions jobs. Sonar analysis skipped. |
| V2: failure ≤300s; queue repair ≤120s; restart convergence | **PASS, 190.602s**: kill visibility **69.195s**, queue repair **23.507s**; surviving queue metadata, same-key retry/no duplicate primary, durable pending work through Media restart and restored Processing convergence. |
| V3 scaling: nine batches, 30 identical 60s 720p clips each, 1/2/3 workers | **PASS at `f46599f`:** 270 successes, zero failures or missing HLS; median throughput 2.337 / 4.749 / 6.743 jobs/min. [Report and raw evidence](reviews/scaling-validation.md). |
| V3 targets: 2 workers ≥1.6×; 3 ≥2.1×; falling median queue wait; zero failures | **All PASS:** speedups 2.032× / 2.885×; pooled median queue wait 375.381 / 175.976 / 120.360 seconds. |
| V3 status: 50 users, 180s, p90 ≤700ms, errors <1% | **PASS:** p90 605.046 / 580.175 / 544.022ms; 8,999 / 8,999 / 9,000 requests; zero errors, all clients/intervals eligible. [Raw/hash review](reviews/performance-validation.md). |
| V3 login: separate 20 users, p90 <2s | **PASS:** p90 1872.986 / 1888.086 / 1898.516ms; 2,468 / 2,387 / 2,374 requests; zero login/warmup/session/logout errors. Bcrypt cost-10 configuration/source; direct image/DB cost inspection absent from pack. [Provenance](reviews/performance-validation.md). |
| V4: Processing promotion/smoke ≤600s; active drain; bad startup/rollback | **PASS at `331354d`, 226.828s total**: good **101.197s**, real active drain **34.077s**, bad + restoration **125.621s**. Exact candidate scans: zero fixable HIGH/CRITICAL; actual API exit **42**, automatic exact-good-image rollback/public smoke, Media identities/images and `media_db` revision unchanged. [Release report](reviews/release-validation.md) |
| V5: final review, merge, exact Main CI and metadata | **Done:** original [delivery review](reviews/delivery-review.md) and corrective [peer review](reviews/postgres-readiness-review.md) PASS; PR32 merged `f10bf04`, exact PR/Main CI passed, issues #24/#6 closed and their Project fields Done. Failed `293b9a8` startup retained. |

Source packs: [final corrected Main](evidence/main-f10bf04/index.json), [readiness correction/failure](evidence/postgres-readiness-fix/index.json), [historical Main 66014d0](evidence/main-66014d0/index.json), [V3 latency index](evidence/performance-f46599f/index.json), [current demo index](evidence/local-demo-20261013/index.json).
Tracked source packs: [Mac V1/V2 index](evidence/local-workflow-422609b/index.json),
[V4 index](evidence/release-331354d/index.json), [capacity](evidence/runtime-capacity.json).
Mac harness `422609b` used runtime build `2cb8da8`; indexed runtime inputs match.
The [older Linux pack](evidence/linux-ci-38300284726/index.json) retains its older head;
Earlier retained CI 38306733800 also passed all 15 checks with 1,085 fast Python tests; its [full Linux proof](evidence/linux-ci-38306733800/index.json) is retained.

## Reproduce in a separate serialized namespace

```sh
set -e                              # Stop on failure; preserve its evidence.
make lint
make test                           # Fast checks; no live service proof.
make verify-local RUN_ID=local      # Full coverage, real integration, TLS and E2E.
make evidence-recovery RUN_ID=local
make down RUN_ID=local
make up RUN_ID=repro-scale          # Fresh scaling namespace; stop its workers first.
.venv/bin/python - <<'PY'
from scripts.dev.runtime import configure, compose
_, state = configure('repro-scale')
compose(state, 'stop', 'worker', timeout=75)
PY
make evidence-scaling RUN_ID=repro-scale
make down RUN_ID=repro-scale
# Proceed to latency only if full scaling passes; never run namespaces concurrently.
make up RUN_ID=repro-perf
make evidence-performance RUN_ID=repro-perf EVIDENCE_ARGS="--login-hash-cost 'bcrypt rounds=10'"
make down RUN_ID=repro-perf
make up RUN_ID=repro-release
make evidence-release RUN_ID=repro-release
# Individual operations, when needed:
make release RUN_ID=repro-release
make rollback RUN_ID=repro-release
make down RUN_ID=repro-release
```

Before reproduction, stop other namespaces' containers and confirm VM availability.
Verify actual built Media/new-account hash cost before using the cost-10 label.
Full scaling uses three rotated repeats with hard 2 CPU / 1536 MiB workers;
fixed nonworkers total 2 CPU. Latency runs separate status/login experiments,
each with three 30s warmups + 180s measurements. Release needs clean source,
pinned Trivy/cache and exact-image gates. Review migration compatibility; pending recovery requires rollback first.

## Limits, private state and detailed history

The first full scaling run at `621c03a` **FAILED** after about one hour: cookie
expiry during batch-8 preparation. Seven complete batches/210 successes are
**diagnostic only**. [Session rereview](reviews/scaling-session-rereview.md) PASS;
`f46599f` runs all nine batches fresh, with no splicing. Earlier V4 active
capture rejection and automatic-rollback failure/manual recovery remain failed
records; reviewed corrections preceded the separate accepted full experiment.

Project-local disk expanded 40→64 GiB (actual filesystem 61G, 34G free at resize);
8 CPU/8 GiB and quotas are unchanged, old data retained. Generator and VM share
one physical Mac. Docker memory samples are not exact process peak RSS.
Final Main SonarCloud analysis was skipped; successful job status does not imply
completed analysis.
[Performance protocol](reviews/performance-runner.md) / [corrections](reviews/performance-runner-rereview.md), [scaling fix](reviews/scaling-session-fix.md),
[release history](reviews/release-validation.md) and [dated worklog](../project2-worklog.txt)
retain detail. Older review statements about pending work apply to their own dates.

Private state: `.local/runs/<id>/runtime.env`, TLS `*.key`, Publisher cookie jars
and sibling intent/lock files, release journals and scoped Lima/Docker state.
Keep values out of Git; use prompted passwords or `--password-stdin`.
Chrome on Mac uses scoped leaf-key trust; Linux Firefox uses a temporary CA profile.
[Browser trust details](reviews/browser-acceptance.md); system trust is unchanged.

All new evidence is local. AWS needs the actual project account, region, spending
limit, domain, scoped credentials and compute; no AWS/Alibaba operation is claimed.
Roadmap visuals and original academic documents remain intact.
Recorded dates: weekly report 16 Oct; Team 17 presentation 26 Oct,
14:35–15:15 Singapore; final report 16 Nov. Verify later course changes separately.
