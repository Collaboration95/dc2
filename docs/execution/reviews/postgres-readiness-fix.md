# PostgreSQL TCP startup readiness correction

**Implementation/probe and [independent peer review](postgres-readiness-review.md) PASS;
corrective PR and exact PR/Main CI pending.**
Base `293b9a868029f239fc3cf4539e67f489e8a09472`, branch
`fix/postgres-startup-readiness`. No change to migration/application behavior.

[CI38329462068](https://github.com/Collaboration95/dc2/actions/runs/38329462068)
failed in `Local HTTPS and browser trust` during fresh `make up`, before E2E.
PostgreSQL was marked healthy at 00:55:55.790 UTC while its temporary Unix-socket
server was running init scripts. Media and Processing migrations received TCP
connection refusals. The final IPv4 listener started only at 00:55:59.565.
The full original log SHA-256 and compact exact excerpts are retained in the
[evidence index](../evidence/postgres-readiness-fix/index.json). This failure
remains failed; earlier accepted results retain their original sources.

Add `-h 127.0.0.1` to three active PostgreSQL readiness commands:

- `compose/local/docker-compose.yml`: integrated local/CI stack; both migrations
  depend on PostgreSQL health.
- `docker-compose.processing.yml`: same bootstrap and health gate, actively used
  by the CI Processing ownership job.
- `.github/workflows/ci.yml`: legacy integration PostgreSQL service uses the same
  socket-only readiness command before TCP clients.

Host selection forces the healthcheck to wait for the final TCP server after
initialization. Existing intervals, retries, dependencies, images and quotas are
unchanged. The inherited root `docker-compose.yml` reference was inspected but
is outside these active runtime/CI paths and is unchanged; no inherited deployment
was operated. No sleep or migration retry was added to product startup.

The bounded live probe used only the project Docker socket, cached PostgreSQL 16
image `sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d`,
0.125 CPU / 512 MiB, fresh tmpfs database storage and a random loopback port.
The real `deploy/postgres/bootstrap.sh` ran first; a final init script then held
the temporary server behind an explicit release file (120-second fail bound).
This avoids relying on a lucky timing window. Both health commands and actual
owner Alembic migrations were observed before and after release.

| Observation | Held initialization | Final server |
| --- | --- | --- |
| Socket `pg_isready -U postgres -d postgres` | exit 0, accepting | exit 0 |
| TCP `pg_isready -h 127.0.0.1 -U postgres -d postgres` | exit 2, no response | exit 0, accepting |
| Docker TCP health | starting | healthy |
| Media owner migration | exit 1, connection lost | exit 0, `0002_uncertain_writes` |
| Processing owner migration | exit 1, connection lost | exit 0, `processing_0002` |

The successful fresh probe ran 01:00:14–01:00:25 UTC. Lima port forwarding reports
`ConnectionError: unexpected connection_lost() call` during init, whereas Linux
CI reports connection refused; both are retained accurately. An initial diagnostic
aborted because it required the specific refusal spelling, after reproducing the
same health distinction. Its records remain separate. Only that probe assertion
was corrected before the fresh complete run; no product gate was weakened.

Each probe container was explicitly removed and its temporary init file cleaned;
no named volume was created. All 15 preexisting container IDs, image IDs, statuses
and start times were unchanged after both attempts; before/after hashes match.
Local and frozen namespaces were not modified. The retained diagnostic source is
`probe-script.txt`; it is evidence, not a CI test or an instruction to overwrite
this pack. No credentials are retained.

Existing related offline tests: **66 passed in 0.54s** using the required
`scripts.dev.pytest_plugin --offline-fast` (exact command in `checks.json`).
The initial invocation omitted that plugin and had one network-guard failure;
the corrected invocation passed without changing tests. Scoped Ruff, YAML parsing
and whitespace checks passed. No new string-matching regression test was added;
the real held-init negative/positive probe verifies the behavior. No full E2E or
benchmark rerun. [Peer review](postgres-readiness-review.md) PASS. Parent owns corrective PR32
and exact PR/Main CI.
V5/E5 are reopened locally pending those gates and metadata reconciliation.
