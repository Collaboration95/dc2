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
The second commit will align the performance runner's fixed resource profile
and its resource fixtures. The live pilot will build this worktree's images in
the isolated `login-pilot` namespace on the existing Lima VM, measure two bursts
of 20 valid public HTTPS logins, retain raw timings without credentials, and
stop only that namespace. Other running stacks make this a diagnostic rather
than fair-capacity V3 acceptance; final three-minute/full repeated evidence
belongs to the parent run.
