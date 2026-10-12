# Project 2 morning handoff

**13 October 2026, Singapore (UTC+8): product PRs #25–#30 are merged.
V1/V2 workflow and recovery evidence and V4 release evidence PASS.
V3 measurements and V5 final review/merge remain PENDING; PR31 is draft.**
These results belong to the tested sources below. No final Main SHA is certified.
The working target is **three elapsed agentic days, five maximum**, applying 80/20:
reuse the media engine/frontend and prove service boundaries, separate ownership,
web/CLI workflows, independent deployment and measured recovery/scaling.
The proposal's **31 person-days** is its effort allocation, not this coding schedule.

## Morning actions

1. Leave `.worktrees/final-measurements` **frozen at `f46599f`**, `RUN_ID=v3-final`.
   The parent owns its full nine-batch scaling run and the VM exclusively.
   Do not start Docker, builds, browsers, FFmpeg or other live workloads until released.
2. If scaling passes, let the parent run the separate full latency experiment
   (21 minutes of warmup/measurement, plus preparation). Record all original targets,
   raw evidence and misses in the table below. Keep V3/E5 open if unmet.
3. After measurement releases the VM, restore/check root `RUN_ID=local` and fill
   the URL confirmation below. Obtain final independent review, assess source
   applicability, merge accepted PR31 work, then check the exact Main source.
4. Reconcile issues and [Project 14](https://github.com/users/Collaboration95/projects/14)
   using authenticated `gh` only. Finish V5 only after its evidence and checks pass.
   Course report/demo preparation remains separate work.

## Start, use and stop the local demo

Run from the repository root **after the parent releases the VM**. Commands here
were checked against source only; this documentation task ran no live commands.
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
**currently down at this checkpoint**. Parent final confirmation: **PENDING**.
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
| Local acceptance E5 | V1–V5 #20–24 | [#31](https://github.com/Collaboration95/dc2/pull/31) draft; V1/V2/V4 in Review, V3/V5 pending |

Details: [progress](progress.json), [issues](issue-map.md), [plan](plan.md), [interfaces](interfaces.md), [decisions](decisions.md).

## Results and parent final fill-in

PASS below records execution evidence, not issue closure or final Main acceptance.
Retain exact source/image/config/fixture identities, raw paths/hashes and review
scope. New measurements must come from complete runs; pilots cannot replace them.

| Gate / target | Recorded result or final field |
| --- | --- |
| V1: full HTTPS web/CLI and 25 contract dispositions | **PASS at `422609b`**: 1,083 fast Python / 152 frontend / 130 real integration; full Mac E2E **122.740s**. UI login, decoded HLS/MP4, 30-good/1-rejected Publisher batch, stored retry and deletion. [Contract/evidence review](reviews/contract-final.md) |
| Linux full workflow/CI | **All 15 checks PASS**, [run 38303856295](https://github.com/Collaboration95/dc2/actions/runs/38303856295), branch head `422609b`; tested merge `e1062bd8`. No current Linux E2E duration or completed Sonar analysis claimed. |
| V2: failure ≤300s; queue repair ≤120s; restart convergence | **PASS, 190.602s**: kill visibility **69.195s**, queue repair **23.507s**; surviving queue metadata, same-key retry/no duplicate primary, durable pending work through Media restart and restored Processing convergence. |
| V3 scaling: nine batches, 30 identical 60s 720p clips each, 1/2/3 workers | **PENDING — parent fill:** full `f46599f` run path/hash, throughput/queue/processing/CPU/memory/failures and source applicability. |
| V3 targets: 2 workers ≥1.6×; 3 ≥2.1×; falling median queue wait; zero failures | **PENDING — parent fill:** speedups, queue medians and each target verdict, including misses. |
| V3 status: 50 users, 180s, p90 ≤700ms, errors <1% | **PENDING — parent fill:** all three repeats' p90/errors and raw path/hash. |
| V3 login: separate 20 users, p90 <2s | **PENDING — parent fill:** all three repeats' p90/errors/session outcomes and actual hash cost. |
| V4: Processing promotion/smoke ≤600s; active drain; bad startup/rollback | **PASS at `331354d`, 226.828s total**: good **101.197s**, real active drain **34.077s**, bad + restoration **125.621s**. Exact candidate scans: zero fixable HIGH/CRITICAL; actual API exit **42**, automatic exact-good-image rollback/public smoke, Media identities/images and `media_db` revision unchanged. [Release report](reviews/release-validation.md) |
| V5: final review, merge, exact Main CI and metadata | **PENDING — parent fill:** review verdict/link, merged PR, final Main SHA/CI, issue/project dispositions and confirmed local URL. |

Tracked source packs: [Mac V1/V2 index](evidence/local-workflow-422609b/index.json),
[V4 index](evidence/release-331354d/index.json), [capacity](evidence/runtime-capacity.json).
Mac harness `422609b` used runtime build `2cb8da8`; indexed runtime inputs match.
The [older Linux pack](evidence/linux-ci-38300284726/index.json) retains its older head;
current run 38303856295 artifacts still need parent retention.

## Reproduce after exclusive measurements finish

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
