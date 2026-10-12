# F3 local runtime implementation and handoff

Implemented on `work/foundation-runtime` in the isolated worktree. Parent branch
`wave/01-foundation` was fast-forwarded to `9a95861` to obtain its actual TLS
helper; those parent files are not duplicated in this implementation commit.
The local runtime changes do not provision AWS or operate the inherited stack.

## CLI and daemon selection

```sh
python scripts/dev/runtime.py ACTION --run-id RUN_ID
```

Actions: `up`, `down`, `logs`, `smoke-infra`, `images`, `env`, `status`.
Use the project Python environment (`.venv/bin/python`) for live commands.
`env` generates configuration and prints safe state, not secret values. IDs are
1–40 lowercase letters/digits/hyphens. Each checkout owns `.local/runs/<id>/`.
Repeated generation preserves existing configuration byte-for-byte and keeps the
secret env file mode 0600. All default host ports are chosen dynamically; no
shared 3443/8010/55432 ports are assumed. Configure a fixed port in the generated
file only when intentionally reserving it for that run.

Selection order: `DC2_DOCKER_HOST`, existing `DOCKER_HOST`, then a healthy socket
at the common Git root `.local/lima/d/sock/docker.sock`, then the caller's Docker
context. Automatic Lima selection pairs common-root `.local/docker`.
`DC2_DOCKER_CONFIG`/`DOCKER_CONFIG` can explicitly select the config directory.
Selection/probe environment is confined to subprocesses; it removes competing
context/TLS variables when overriding the daemon. No global context is changed.
`state.json` has exactly these public fields:

- `public_url`, `postgres_port`, `processing_port`, `ca_file`
- `compose_project`, `env_file`, `docker_host`, `docker_config`

`docker_host` is null when using an unoverridden caller context. Config paths are
safe metadata, not file contents. No credentials or DSNs enter state.

`up` invokes the parent's `tls.py --run-id`, reports Docker CPU/memory allocation,
builds cached images, starts services with bounded health waits, and runs smoke.
`down` removes only that project's containers/networks; volumes and config remain.
`logs` shows the last 100 lines. Presigned bucket requests have nginx access logs
disabled to keep query capabilities out of logs.

## Frozen storage/configuration interface for P and Media lanes

These names are generated in `runtime.env`. Compose supplies credentials explicitly
to each service; never give a worker the entire env file, root keys or MM keys.
Internal endpoints have no scheme; separate `*_USE_SSL` booleans select transport.
All regions are explicitly supplied, avoiding an implicit bucket-location request
that would require extra worker privileges.

| Configuration | Value/meaning |
| --- | --- |
| `MEDIA_MINIO_ENDPOINT` | `minio:9000` |
| `MEDIA_MINIO_USE_SSL` | `false` |
| `MEDIA_MINIO_REGION` | `us-east-1` by default; matches `MINIO_REGION` |
| `MEDIA_MINIO_ACCESS_KEY`, `MEDIA_MINIO_SECRET_KEY` | Separate MM principal; generated secret |
| `MEDIA_MINIO_SOURCE_BUCKET` | Same value as `SOURCE_BUCKET`: `<compose-project>-source` |
| `MEDIA_MINIO_OUTPUT_BUCKET` | Same value as `OUTPUT_BUCKET`: `<compose-project>-output` |
| `MEDIA_MINIO_PUBLIC_ENDPOINT` | `localhost:<DC2_HTTPS_PORT>`; no scheme |
| `MEDIA_MINIO_PUBLIC_USE_SSL` | `true` |
| `MEDIA_PUBLIC_URL` | `https://localhost:<DC2_HTTPS_PORT>` |
| `PROCESSING_MINIO_ENDPOINT` | `minio:9000` |
| `PROCESSING_MINIO_USE_SSL` | `false` |
| `PROCESSING_MINIO_REGION` | Same configured region |
| `PROCESSING_MINIO_ACCESS_KEY`, `PROCESSING_MINIO_SECRET_KEY` | Output-writing worker principal only |
| `PROCESSING_MINIO_OUTPUT_BUCKET` | Same value as `OUTPUT_BUCKET` |
| `CLEANUP_MINIO_ACCESS_KEY`, `CLEANUP_MINIO_SECRET_KEY` | Separate cleanup principal; output list/delete only |
| `PROCESSING_QUEUE_NAME` | `<compose-project>-processing` |
| `PROCESSING_REDIS_URL` | `redis://:<generated-password>@redis:6379/0` |
| `MEDIA_POSTGRES_DSN` | `postgresql+asyncpg://media_runtime:<secret>@postgres:5432/media_db` |
| `MEDIA_MIGRATION_DSN` | Same host/database with `media_migrator` and its own secret |
| `PROCESSING_POSTGRES_DSN` | `postgresql+asyncpg://processing_runtime:<secret>@postgres:5432/processing_db` |
| `PROCESSING_MIGRATION_DSN` | Same host/database with `processing_migrator` and its own secret |
| `MEDIA_JWT_SECRET` | Independent generated cookie signing secret |
| `PROCESSING_SERVICE_TOKEN`, `MEDIA_PROCESSING_SERVICE_TOKEN` | Same forward service token |
| `SOURCE_SERVICE_TOKEN`, `MEDIA_SOURCE_SERVICE_TOKEN`, `PROCESSING_SOURCE_SERVICE_TOKEN` | Same reverse source-access token |

For public signing, instantiate a distinct MM signer using the public endpoint,
HTTPS and explicit region. nginx proxies `/<actual-source-bucket>/...` and
`/<actual-output-bucket>/...` without rewriting paths/queries and sends
`Host: localhost:<HTTPS-port>` unchanged. There is no `/objects` prefix.
Public signed URLs work for host/browser clients. A container must use an
internally signed `minio:9000` URL for source downloading: public `localhost`
means that container itself. MM can renew/sign that internal capability over its
private source-access API. Workers use their output credential only for writes;
verify successful PUT acknowledgement/etag/local digest instead of granting
HEAD/Get. Cleanup uses the same internal endpoint/region/output bucket but its
separate keys. Supply the project CA explicitly to clients using public HTTPS.

Policies enforced by MinIO bootstrap:

- MM: source Get/Put/Delete and source List; output Get; bucket location.
- Worker: output Put and minimal AbortMultipartUpload/ListMultipartUploadParts;
  no Get, Delete, bucket List or source access.
- Cleanup: output ListBucket/DeleteObject; no output Get or source access.

Bucket policies are removed on bootstrap so anonymous access stays disabled.
Only the server and transient storage bootstrap receive MinIO root credentials.
The bootstrap uses the installed official MinIO Python SDK admin API; no `mc`
binary/compiler is required. Signed GET and anonymous-denial smoke tests verify
both actual bucket routes. Temporary smoke objects are removed after each run.

Parent packaging needs **HTTPX as a production dependency** for the upcoming
service HTTP clients; the current intake does not use it. This work does not
modify pyproject/lock files. Product lanes must implement their settings using
the exact prefixes above; do not add speculative aliases to runtime.

## Topology and build details

`compose/local/docker-compose.yml` starts PostgreSQL, Processing migration/API,
Redis, source-built MinIO, one-shot storage bootstrap and nginx. PostgreSQL owns
separate media/processing databases and four limited runtime/migration roles.
The existing Processing migration runs before API startup. Media migration/code
will join during the Media lane; F3 does not invent a Media schema.

Media/Processing data, interservice and object networks are internal. nginx joins
an edge bridge. Docker suppresses published ports on internal-only services, so
PG and the P API additionally join `host-access` for their explicitly loopback
host diagnostic ports. Redis, MinIO and future workers do not join that bridge.
Future Media joins media-data/interservice/object-data/edge; workers join
processing-data/interservice/object-data, with no public listener. The planned
actual worker service still needs its hard 2 CPU cap when it lands.

nginx serves existing frontend files and `/health` over TLS; `/api` returns 503
and `/internal/` returns 404. Its container liveness probe uses a private
127.0.0.1 HTTP listener; smoke verifies real public TLS with the explicit CA.
`smoke-infra` checks TLS/frontend, MinIO health, Processing/DB health, Redis,
both databases' runtime writes/DDL denial/cross-database role denial, storage
principal denials and signed HTTPS source/output reads. It polls only TCP
readiness for at most 20 seconds to accommodate VM port forwarding; failed
application/TLS checks are not retried to green.

MinIO source pin: `20960b6a2ddb9594ee418035b3c7c7fe92ae6a12`, release
`RELEASE.2024-06-13T22-53-53Z`. `gh api repos/minio/minio/tarball/<commit>`
fetches once into ignored `.cache/minio/<commit>`; extraction rejects unsafe
archive paths. Docker has no git fetch and receives the cached named build
context. Both Go/Alpine build bases are digest-pinned. BuildKit caches modules
and compiled Go packages; `GOMAXPROCS=2`, `go build -p 1`. `GOPROXY` is restricted
to the official Go proxy with no direct GitHub fallback. The release/commit
identity is set in ldflags because archive sources have no `.git` history.
Each run has unique image tags while BuildKit layers are reusable. The inherited
DAST MinIO override now uses this same cached source context.

## Observed validation, 13 October 2026

Scoped daemon: project Lima, 8 CPUs / 7.73 GiB reported by runtime. Parent provided
and separately verified cgroup v2/2 CPU hard-quota evidence. F3 builds started only
after parent confirmation; no simultaneous parent Docker build occurred.

Commands (from the isolated worktree; Python is root project's 3.12.11 venv):

```sh
.venv/bin/python -m pytest --confcutdir=tests/dev tests/dev/test_runtime.py -q
.venv/bin/ruff check scripts/dev/runtime.py deploy/minio/bootstrap.py tests/dev/test_runtime.py
.venv/bin/python scripts/dev/runtime.py images --run-id f3-live-a
.venv/bin/python scripts/dev/runtime.py up --run-id f3-live-a
.venv/bin/python scripts/dev/runtime.py up --run-id f3-live-b
.venv/bin/python scripts/dev/runtime.py smoke-infra --run-id f3-live-a
.venv/bin/python scripts/dev/runtime.py smoke-infra --run-id f3-live-b
.venv/bin/python scripts/dev/runtime.py down --run-id f3-live-a
.venv/bin/python scripts/dev/runtime.py up --run-id f3-live-a
```

The worktree uses the absolute main-root `.venv/bin/python` and `ruff` paths;
commands above express the equivalent integrated-root invocation. Initial images
used explicit scoped daemon/config overrides. Subsequent CLI up/smoke commands
passed with automatic healthy common-root Lima selection and no override.

- 12 focused tests passed in 0.07 seconds; lint and diff whitespace checks passed.
- Fresh MinIO source cache and fresh VM image cache built successfully. The second
  run reused cached build layers and had independently created volumes/buckets.
- Both live CLI `up` runs and complete infrastructure smoke passed simultaneously.
- Live stack A: HTTPS 62851, PG 62852, Processing 62853.
- Live stack B: HTTPS 49393, PG 49394, Processing 49395.
- Both roles' opposite database connections and runtime DDL were denied; own
  runtime data writes and migration DDL succeeded. No proof tables remain.
- Worker source Get/Put and output Get/Delete/List denied; cleanup source/output
  Get denied; MM output Put denied. Positive worker output Put and cleanup List/
  Delete succeeded. MM signed source/output HTTPS GET succeeded; anonymous GET
  returned 403 on both.
- A real authenticated Processing intake POST returned 201. After CLI down/up,
  the same Job/Attempt IDs, private source bytes, Redis marker and byte-identical
  secret config remained. Stack B passed smoke while A was down.
- Parent Firefox trusted positive and untrusted negative proof is in the parent's
  coordinator evidence; this agent did not repeat that browser installation.

An initial host smoke with system Python 3.14 failed strict certificate validation
because the parent server certificate lacked Authority Key Identifier. Verification
was not weakened. All recorded successful host smoke commands use project Python
3.12. Parent TLS should add AKI if supporting system Python 3.14. Browser trust is
independently handled by the parent. A manual nginx restart followed immediately
by smoke before its health wait completed produced a transient TLS EOF; waiting
for Compose health, as production `up` already does, then passed complete smoke.

## Remaining scope

Both owned test stacks were stopped with CLI `down` at handoff; their volumes,
run configuration and BuildKit/source caches remain. No inherited stack was stopped.

No public login/video workflow is claimed; Media and workers are not integrated.
No image vulnerability gate or release/scaling experiment was run here. MinIO was
built on the 8 GiB VM; the constrained-build flags were not separately measured
on the inherited 2 GiB daemon. Parent owns Make/CI/locking, Firefox, capacity and
TLS helpers; full integrated-root acceptance and interface wiring remain there.
