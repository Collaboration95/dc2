# Concurrent login diagnostic

Scope: basic-demo login performance on `work/login-performance`, base `78cedcc`.
The parent measured two 20-user valid-login bursts at bcrypt cost 12 and Media
0.5 CPU: p90 12.086s and 11.591s, all HTTP 200. These are supplied baseline
diagnostics; V3 acceptance remains open. The original login target is p90 <2s.

New Media password hashes use the documented `BCRYPT_ROUNDS = 10` constant.
Unknown-user verification uses a valid cost-10 dummy hash. Existing hashes retain
their embedded cost and verify normally; no migration or automatic rehash is
added. Existing cost-12 users therefore retain their prior hashing work. Basic
cookie login and ownership checks remain in place.

The fixed nonworker budget remains 2 CPUs: Media 1, Processing API 0.5,
PostgreSQL 0.125, MinIO 0.125, Redis 0.0625, nginx 0.0625, Processing recovery
0.0625 and Media recovery 0.0625. Each worker remains 2 CPUs / 1536 MiB; three
workers plus fixed services require 8 CPUs. Memory limits are unchanged.

Focused checks cover new hash cost, the dummy cost, correct/wrong passwords,
cost-12 compatibility, asynchronous hashing and the unknown-user bcrypt path.
Validation: `../../.venv/bin/python -m pytest tests/media -q` passed all 126
Media tests (including ownership regressions). Scoped Ruff and `git diff --check`
also passed. Tests ran from this worktree using the root's locked environment.
The second commit aligns the performance runner's fixed resource profile and
its resource fixtures. All 64 performance unit tests passed; the fixtures check
the shared Compose/runner 2 CPU budget and reject the previous Media quota.

## Actual local pilot

Tested product/build commit: `90d369aaf189349c7a77f164a95a9b118eed6724`.
The image records a clean source state and fingerprint
`35d6b5310d8df1100f0df267c21804493023fd57155d2034786df41e68448c52`.
Media image ID:
`sha256:1bf8e7c064ab7dbe77a54bf2277a735908e42cafcc76d6b749a1bc3d46bea355`.
The image's security module SHA-256 is
`2a779ee96c4e3b1f3c386a0a5c128470d3c694dd79717b4d45df4e6bf7b6514a`.
The subsequent runner/test/document changes do not change this Media image.

Recorded completion: `2026-10-12T18:34:15.049708+00:00` (13 October Singapore).
Runtime: existing project-local aarch64 Lima VM, 8 CPUs, 8,296,787,968 bytes RAM,
cgroup v2. Compose project: `dc2-login-pilot-a9edf0f7`.
Public route: `https://localhost:57961/api/auth/login`, verified using the
namespace's generated CA. Each burst synchronizes 20 independent HTTPS clients;
each clears its cookies and submits valid credentials for its own newly
registered user. Registration and subsequent `/api/auth/me`/logout checks are
outside the timed login interval. The two bursts are separated by those checks
and a one-second pause. p90 uses nearest rank (18th of 20 sorted samples),
including every request. No warmup login or authentication bypass is used.

Live image inspection confirmed new/default and dummy bcrypt costs are both 10.
A query of this namespace's Media database returned `10|20`: all 20 stored pilot
hashes are cost 10. Live Docker quotas matched the profile above, including the
2 CPU / 1,610,612,736-byte worker. Media cgroup `cpu.max` was `100000 100000`
and `memory.max` was `402653184` (384 MiB).

| Burst | Count | HTTP 200 | Errors | Raw p90 (ms) | p90 <2s |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 20 | 20 | 0 | 985.1738750003278 | yes |
| 2 | 20 | 20 | 0 | 1044.02874999505 | yes |

All 40 login responses matched the expected user and produced cookies; all 40
subsequent `/api/auth/me` checks matched the same user. All 20 final logouts
returned 204. Infrastructure smoke also passed (TLS, database ownership/DDL
denials, Redis, private storage and signed public HTTPS object reads).

Commands, run from this worktree (credentials are generated privately; no values
are included in the commands or retained timing evidence):

```sh
# Reuse the existing pinned MinIO source cache via a worktree-local cache link.
../../.venv/bin/python -m scripts.dev.runtime up --run-id login-pilot
PYTHONPATH=. ../../.venv/bin/python .cache/execution/login-pilot.py
../../.venv/bin/python -m scripts.dev.runtime down --run-id login-pilot
../../.venv/bin/python -m pytest tests/media -q
../../.venv/bin/python -m pytest tests/evidence/test_performance.py -q
```

Retained locally: `.cache/execution/login-pilot.py`,
`.cache/login-pilot-build.log`, `.cache/login-pilot-down.log`, and
`artifacts/login-pilot/raw.json` (all ignored). Raw JSON SHA-256:
`fdaaab00e2074c10263fd0e05e43fa200efeef90b84a423e3cfba925f9758874`.
The JSON retains full-precision request durations, status/error/count results,
image/source identity, live resource records and other running container names,
quotas and start times; it retains no passwords, emails, tokens or secret config.
Full-precision durations are also recorded below so the committed review retains
the measured samples when ignored artifacts are not transferred.

**Diagnostic only; V3 acceptance remains open.** Parent root/integration stacks
and a temporary parent test namespace were also running during the pilot.
Those extra reservations exceed an otherwise fair 8 CPU scaling budget, and
their activity was not controlled. This proves a bounded improvement for new
cost-10 demo users, with no claim for existing cost-12 users or full fair-capacity
status/scaling acceptance. The parent must run the final V3 protocol with the
revised resource profile and verified cost-10 accounts; the original <2s target
is unchanged.

The pilot namespace was stopped with `down` without `-v`, retaining its data.
Post-stop inspection found no running pilot containers. Parent root/integration
containers remained running; shutdown logs contain only the pilot namespace.

## Raw request durations

All entries have HTTP 200 and no error. Values are milliseconds.

| Client | Burst 1 | Burst 2 |
| ---: | ---: | ---: |
| 0 | 105.11887499887962 | 554.0845420036931 |
| 1 | 190.26104200747795 | 450.55379200493917 |
| 2 | 189.36283299990464 | 954.6773329930147 |
| 3 | 594.2883329989854 | 358.50266700435895 |
| 4 | 195.95266599208117 | 448.6320409923792 |
| 5 | 892.7429169998504 | 643.7344580044737 |
| 6 | 793.6658749968046 | 950.2031250012806 |
| 7 | 898.2014170032926 | 541.673500003526 |
| 8 | 884.2520830075955 | 851.2975420017028 |
| 9 | 897.7161669899942 | 540.5452499981038 |
| 10 | 988.0378329980886 | 1048.7151250126772 |
| 11 | 985.1738750003278 | 1055.672999995295 |
| 12 | 886.0822919959901 | 960.5817499978002 |
| 13 | 590.3849160094978 | 950.888457999099 |
| 14 | 981.208166005672 | 954.246666005929 |
| 15 | 791.9329169963021 | 747.5173749990063 |
| 16 | 684.2583749967162 | 950.2397080068476 |
| 17 | 985.5519160046242 | 742.1953749872046 |
| 18 | 786.5884999919217 | 1044.02874999505 |
| 19 | 791.0027920006542 | 752.5354999961564 |
