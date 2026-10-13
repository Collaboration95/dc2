# V4 independent local release runner handoff

Implemented on `work/release` in `.worktrees/release`. Only
`scripts/dev/release.py`, `tests/dev/test_release.py`, and this report are owned by
this lane. No root/shared files, AWS, Alibaba, GitHub writes, image builds or
running containers were changed by this implementation lane.

**V4 live acceptance remains open.** The full Media/Processing/worker topology
is not integrated in this worktree. Offline tests establish runner behavior; they
are not measured release, recovery or live vulnerability evidence. The parent
runs the actual experiment after integrating product lanes and the wiring below.
Parent reported P1/P2 integration at `0c987ff`; P3 and Media were still arriving.

## Commands and result codes

From the integrated clean repository with its project Python environment:

```sh
.venv/bin/python scripts/dev/release.py release --run-id v4-local
.venv/bin/python scripts/dev/release.py rollback --run-id v4-local
.venv/bin/python scripts/dev/release.py evidence --run-id v4-local
```

New Processing migration revisions require `release --additive-migrations` (or
that flag on `evidence`). This declares reviewed backward compatibility with the
retained image; it does not infer compatibility from arbitrary migration SQL.
Only newly added revision files are permitted. Editing/deleting an existing
revision is rejected. No Media migration or Processing downgrade is executed.

| Exit | Meaning |
| --- | --- |
| 0 | Release promoted / rollback restored / complete good-and-bad experiment passed |
| 1 | Prerequisite/build/test/scan rejection before mutation, or experiment criteria failed |
| 2 | Release failed after mutation and automatic rollback plus real smoke succeeded |
| 3 | Recovery incomplete; durable pending intent retained; run `rollback` |

A failed candidate with successful recovery returns **2**, never successful
release status. Only `evidence` treats the expected bad candidate as a successful
experiment, and only when the bad image actually reached deployment, deployment
failed, the exact good image was restored, smoke passed, and Media remained
unchanged. A rejected scan or failed build is not a rollback experiment.

## Promotion and recovery behavior

- Require a local Unix-socket Docker daemon. Use runtime's automatic common-root
  Lima selection and subprocess environment; never change global Docker context.
- Reject dirty/untracked product, packaging, dev-helper and test paths. Record
  HEAD and SHA-256 of `git ls-files -s -- PRODUCT_PATHS`; recheck after fast tests
  and immediately before deployment.
- Run `make lint test` against that source. Build only Processing with revision,
  source fingerprint and unique build identity labels; resolve the tag to its
  immutable local `sha256:<64 hex>` Docker image ID. Tags never select promotion
  or rollback. Unique build labels make unchanged-source release experiments
  produce a separate image identity.
- Run offline imports of API/worker/recovery and FFmpeg/FFprobe presence in the
  exact image with networking disabled and no production credentials. Fast source
  tests plus those artifact checks are separate recorded gates, not a claim that
  the entire unit suite ran inside the production image.
- Scan that exact ID once for the shared API/worker/recovery image, using pinned
  Trivy 0.75.0. Require matching report `Metadata.ImageID`, OS package results and
  zero fixable HIGH/CRITICAL findings across all results. Scanner/tool/cache errors
  reject promotion. Existing cached DB is mandatory; no registry login, image
  push/pull, scanner DB update or cloud operation is used by this runner.
- Bootstrap the running rollback image only if its labels match current clean
  tested source. It receives its own artifact/scan and real public smoke gates.
  Later releases can use older recorded tested images without relabeling them.
  Retain unique local build tags and journal proofs; never remove/prune images.
- Snapshot Media and Media recovery container IDs/images/revision labels plus
  Media's owned `alembic_version`, through the Media container's runtime DB role.
  Record Processing's separate revision history and original worker replica count.
- Before mutation, fsync recovery intent naming the tested prior immutable image,
  worker count and Media snapshot. Take a nonblocking per-run runner lock.
- Stop workers with 60s grace. Keep the prior recovery service running. Track
  processing attempts before and after stop to cover a final concurrent claim.
  Within five minutes of stop beginning, require succeeded/done, finished failed
  with visible job failure/error, or cancelled/deleted. Merely requeued work is
  not accepted as visible failure. Diagnostic SELECTs use only Processing's owned
  DB through its recovery container, which survives API startup failure; no
  Processing-to-Media DB access.
- Apply only `processing-migrate`, then `processing`, `worker` and
  `processing-recovery`; use no dependency restart/build/pull. Restore the exact
  replica count and verify every running Processing container's image ID.
- Smoke through the real public `/api` HTTPS contract: health, UUID@example.com
  registration/login with Secure cookie, one deterministic 1s MP4 upload, polling
  to done, signed output download, FFprobe video validation, owner deletion.
  Use the run's CA, enforce same-origin HTTPS including redirects, and allow no
  transport/application retry to hide an error. Only queued/processing status is
  polled. URLs, passwords and cookies are never retained in artifacts.
- Promotion requires successful smoke and an unchanged Media snapshot within
  600s including prerequisites, tests, build, scans and drain. Failed deployments
  get a separately recorded, bounded 300s recovery budget. Manual rollback has
  at most 300s drain plus 300s restore; the complete experiment has at most 1500s
  across its two releases and automatic recovery. Process-group timeout cleanup
  is capped at 2s so timed-out Make children cannot hold output pipes open.
- Automatic/restarted rollback first restores the retained recovery image
  independently, then drains candidate workers using that recovery container for
  diagnostics, even if the candidate API/reaper crashed. The recovery
  budget includes that drain. Rollback reapplies the prior tested ID, never
  downgrades the DB, then requires
  restored public smoke and unchanged Media. Any failure leaves recovery intent
  and a distinct `recovery_required` result. A crashed pending run blocks further
  release until `rollback`; rollback can recover even when workers/API stopped.

The bad experiment builds **another image**, derived from the good immutable ID.
It appends a synthetic exit-42 condition to Processing's API module for uvicorn
startup, preserving ordinary Python imports and future imports. Its unique ID,
source revision, deliberate injection label, build derivation, artifact checks
and scan are recorded independently. This is a declared synthetic startup fault,
not a claim that ordinary reviewed source contains that fault.

## Durable private artifacts

Under `.local/runs/<run-id>/`:

- `releases/journal.json`: authoritative image proofs, current/previous IDs,
  pending recovery intent and timestamped operation history.
- `releases/<operation-id>.json`: individual operation evidence.
- `releases/<operation-id>.override.json`: temporary candidate/restore selection.
- `releases/experiment-<good-operation-id>.json`: evaluated good/bad experiment.
- `release.override.json`: atomically persisted tested image selection after
  promotion or successful rollback; includes only Processing service image IDs.

Writes fsync the file and directory and use mode 0600; run directories are private.
Journal data includes safe command arguments, output hashes, exact source/image
IDs, migration revisions, bounded drain records, resource limits and timestamps.
**No raw runtime command output, env values, DB DSNs, passwords, cookies or signed
URLs are written to artifacts.** Unexpected exceptions retain their type and failed
phase; subprocess errors retain command exit/deadline status. No retry-to-green.
Failed smoke may leave its synthetic account/asset behind; a successful smoke
owner-deletes the asset. These accounts do not send email or alter real owners.

## Required parent-owned wiring

1. Add `make evidence-release` delegating to `release.py evidence --run-id`, and
   keep existing `release`/`rollback` Make delegation. If forwarding release flags,
   provide a parent-owned argument variable.
2. `runtime.compose` must load `<run dir>/release.override.json` after the base
   Compose file on ordinary runtime calls, before any explicitly supplied `-f`
   candidate override. The runner already includes these files explicitly for
   its own commands; loading the persisted file twice is harmless. Normal `up`
   must refuse unfinished `journal.pending` rather than silently disrupting
   recovery. Serialize normal up/down/images against this same per-run lock.
3. Runtime image **builds must exclude the persisted override**. Keep
   `DC2_PROCESSING_IMAGE` as a mutable build tag in `runtime.env`; never build/tag
   an immutable `sha256:` reference. Normal startup should use the persisted ID
   with `--no-build --pull never`. An unpromoted rebuilt configured tag must not
   replace the selected released image.
4. Initial bootstrap Processing images need these labels, calculated from clean
   source at build time (do not relabel an unknown old image as tested source):

   ```text
   org.opencontainers.image.revision = git rev-parse HEAD
   dc2.release.source-fingerprint = sha256(git ls-files -s -- PRODUCT_PATHS output)
   ```

   Import `PRODUCT_PATHS` from `scripts.dev.release` so parent and runner hash the
   same ordered arguments. Hash stdout encoded as UTF-8 exactly, including its
   trailing newline. Parent can extend its build helper/Compose build labels;
   this lane does not modify those shared files.
5. Complete service names `media`, `media-recovery`, `processing`,
   `processing-migrate`, `worker`, `processing-recovery`, with the same Processing
   image for API/worker/recovery/migrator. Candidate overrides change images only;
   parent retains narrowly scoped environments, networks and commands. Give
   workers 60s stop grace, 2 CPU and 1536 MiB each. Parent's planned total is
   2 CPU for all non-worker services plus 3 × 2 CPU workers on 8 CPU Lima. The
   runner records actual daemon capacity and container CPU/memory limits; it does
   not adjust quotas or substitute thread counts for quota evidence.
6. Preserve Media and Processing migration histories as separate owned databases.
   Keep recovery running during worker drain, with leases/recovery intervals
   small enough for the original five-minute bound. No extra deployment framework.
7. Trivy binary/cache are found at the **common Git root**:
   `.local/trivy/trivy`, `.cache/trivy`. Parent installed 0.75.0 using authenticated
   `gh`, archive SHA-256
   `4a77108cccf8e55c8d6823e1e759939a622277e66cd0daa3c1fc621ed69e4568`.
   Version was independently checked with `--version --format json` in this lane.
   The runner sets `--docker-host` from runtime selection, `--image-src docker`,
   `--scanners vuln`, `--skip-db-update --skip-java-db-update --offline-scan`.
   Parent owns refreshing the common cache and all distinct Media image scans;
   this independent Processing release never rebuilds/restarts Media.

## Offline verification and live follow-up

Run from this worktree (which reuses the common-root project Python/ruff binaries):

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
  -m pytest --confcutdir=tests/dev -p scripts.dev.pytest_plugin --offline-fast \
  tests/dev/test_release.py -q
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
  check scripts/dev/release.py tests/dev/test_release.py
git diff --check
```

Observed on 13 October 2026: **51 offline tests passed in 0.49s** with the
network guard enabled; focused Ruff and whitespace checks passed. No live build,
image vulnerability scan, release timing or container experiment was run here.

Tests cover gate rejection before mutation, exact scan/image provenance, private
atomic journals, lock contention, successful promotion, health/workflow failure,
restored smoke, failed rollback/restart recovery, expired promotion budget,
Media-change rejection, migration policy, final worker-claim race, visible drain
failure bound, Processing-only Compose commands, Trivy daemon/cache selection,
process-group timeout cleanup, public HTTP/TLS/redaction and synthetic bad startup.
Full V4 PASS still requires parent-produced live good/bad evidence and measured
600s target with unchanged Media, exact images/scans, revisions and actual drain.
