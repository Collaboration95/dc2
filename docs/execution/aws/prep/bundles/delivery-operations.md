# Delivery and operations preparation bundle

15 October 2026. Branch `work/aws2-delivery-operations`, isolated worktree
`/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/aws2-delivery-operations`.
Integration baseline `0ffe05261160b3d06ea4197df8b8bc8535cf87af`; planning `8d13508`.
The final response supplies the resulting bundle commit SHA (this report is part
of that commit). No push, PR, issue closure or GitHub access was performed.

Local preparation is implemented and tested for the seven assigned contracts.
Real AWS acceptance, CI artifact builds/scans, authenticated cloud identity,
publication and deployment remain NOT_RUN. These tests establish offline behavior,
not AWS PASS. No AWS CLI/API/account/profile/SSM/metadata request, Alibaba action,
Docker/VM/browser/emulator workload or performance experiment occurred. The shared
locked `.venv` was used without installation or synchronization.

## Issue dispositions

- **54 — owner artifact delivery:** `artifacts.py` validates frozen source,
  Linux/amd64 config ID, executed source tests, exact-image import/encoder tests
  and a retained Trivy OS-package report with zero fixable HIGH/CRITICAL. Registry
  manifest digest is distinct from config ID; raw manifest bytes, registry-reported
  digest and manifest config reference must agree. Index/tag-only, absent/mismatched
  test/scan receipts and wrong-owner artifacts fail. The manual selected-owner
  workflow retains the SAME image archive after gates; no rebuilding before future
  publication. `publication_plan` renders inert Docker/ECR receipt requests;
  `registry_receipt` checks future returned manifests. Actual build/Trivy/ECR
  publication and current/rollback registry retention are future verification.
- **55 — scan scope/disposition:** DAST now prepares an isolated integrated runner
  stack, normal-CA public Media schema/cookie authentication and separate offline
  private token/owner contracts. Source/admin routes receive no service token in
  the scanner. ZAP findings remain report-only; execution errors fail. Auth-bearing
  raw logs/reports stay private and are discarded; only selected alert fields and
  executed/skipped/error scope are uploaded. Extracted services/engine are included
  in Sonar sources; its wrapper records actual analysis outcome, including missing
  configuration and errors. Actual runner ZAP/Java trust-store behavior and Sonar
  execution are NOT_RUN; green/skipped wrappers are never analysis evidence.
- **56 — manual batches:** one designated environment/station, nonblocking OS lock
  and explicit private journal bootstrap/handover. Atomic 0600/fsync intent precedes
  each count-one RunTask; RQ names/client tokens are unique. Both desired-status
  inventories are fully paginated, including STOPPING and mixed digests; acknowledged
  ARNs are described independently of stale lists. Nonterminal tasks and unresolved
  reservations consume the maximum-three cap. Lost/partial responses, restart,
  expiry, corrupt/missing journal, another station and competing local processes
  fail closed. Replay uses the original payload, never changed configuration or
  a new token. Default `--burst`; explicit fixed prewarm remains finite. Late queued
  jobs after an empty burst await another operator batch; no attempt retry added.
- **57 — cloud lifetime/drain:** finite wrapper enforces maximum 3600 seconds,
  launch-supplied absolute epoch plus a monotonic bound, startup included; a small
  reaping reserve fits inside the deadline. Redis/perpetual-queue/operator loss
  cannot extend the child loop. Direct ECS-mode unbounded entry is refused. Local
  default constructor and non-burst behavior remain unchanged; 900-second attempt
  fences remain unchanged. RQ warm shutdown notifies the parent through a private
  inherited pipe; both RQ's cold second handler and duplicate wrapper signals are
  suppressed. External stop permits at most 110 seconds before bounded forcing,
  within Fargate's 120-second final grace. Operator drain captures current/last/
  racing claim IDs, requires fresh acknowledgement, terminal SQL outcomes and task
  STOPPED, and waits at most 300 seconds before explicit failed forcing. Lost ack,
  stale registration, missing task, timeout and repeat close cannot become successful
  drain. Genuine ECS/RQ/SQL/encoder interruption and STOPPED evidence are future.
- **59 — Processing release:** exact prior/candidate artifact and definition gates,
  pinned owning families, reviewed additive prior-image compatibility, complete
  unchanged Media task/both-container-digest/schema snapshot and zero-worker entry.
  Private pending intent precedes migration/service mutations. Migration requires
  STOPPED, every container exit zero and observed owner revision. Only API/recovery
  and future worker definition change. Running candidate digest/revision/deployment
  checks exceed a waiter; explicit failed task exit codes are retained. Candidate
  public smoke has a 600-second absolute budget; recovery has a persisted 300-second
  budget and does not reset on restart. Optional short smoke workers use the same
  already-held station lock/capped reservation primitive, exact candidate/prior
  worker definition and drain back to zero. Failed candidate stays failed even when
  prior restoration/public smoke passes. Lost migration response retains intent;
  explicit restoration can replay only its original unexpired request. Actual cloud
  good/bad release and compatibility receipts remain future.
- **60 — Media selection:** shared release primitives update only Media owning
  migration and its API/essential reconciler definition. Processing API/recovery
  task/digest/schema plus active worker identities and selected future worker
  revision are captured unchanged. Media smoke cannot launch peer workers. Fake
  success/failure and ownership gates pass; actual Media release proof is future.
- **61 — sessions:** close serializes with launches/releases, pauses intake/launches,
  holds state/Media/recovery through terminal worker outcomes, stops standalone
  orphan writers, invokes an explicit common quiescence/private-export hook, then
  requires all service/deployment/standalone tasks STOPPED and all three counts zero.
  Temporary generator instances and attached/orphan generator volumes are removed;
  state EC2 stops and its auto IP/DNS release/no retained EIP is checked. Failed
  export never stops state. Repeat close verifies stopped inventory without trying
  to re-export offline databases. Wake requires mount, TCP, both schemas, Redis and
  peer readiness, current EC2 DNS, preserved CloudFront configuration/private header,
  matching ETag, deployed propagation and public readiness before explicit intake
  resume. Origin-transport interpretation remains an input gate. No scheduler or
  automatic resume exists. Real continuity/export/zero-compute/billing proof is future.

## Interfaces and integration requirements

- `call(service, operation, payload, *, deadline=None) -> dict` is the frozen
  injectable transport. Control-plane deadlines are absolute monotonic seconds.
  `CLITransport` production execution is unconditionally disabled. Emulator execution
  accepts numeric HTTP loopback only, replaces the entire environment with dummy
  keys, disables config/credential files and metadata, uses no profile/fallback,
  and has finite subprocess timeout. Only fake runners were executed here.
- Plain dicts or attribute-based config objects work without importing other bundles.
  Use shared `CloudConfig` keys from `prep/interfaces.md`; network values are ECS
  `subnets`, `security_groups`, `assign_public_ip` (`ENABLED`/`DISABLED`). Worker
  overrides target container `worker`. Infrastructure must retain the essential
  Media API/reconciler, pinned owner/worker/migration task definitions, stopTimeout
  <=120 and WorkerLifetimeSeconds <=3600. The operator emits exactly
  `python -m processing.worker --cloud-deadline epoch --name unique [--burst]`.
- Every operator/smoke/release launch must use the same `Journal`. Its directory
  must already exist with private permissions. Explicit `initialize(verified_empty=True,
  exclusive_station=True)` represents an operator-confirmed empty exclusive handover;
  it is not distributed consensus. No second station may launch. Use
  `workers.resume_launches` for explicit release handback; release/restore leaves
  launches paused and never restores permanent workers.
- Drain's injected `observe(task_arn,rq_name)` must combine fresh correlated RQ
  current/last/racing claims with authoritative SQL outcomes (`succeeded`, `failed`,
  `cancelled`, `abandoned`), and report `fresh`, `claims_stopped`, `claims`, `outcomes`.
  `warm_shutdown` must positively confirm the single warm request. Redis absence or
  pub/sub publication alone is not an acknowledgement. Actual private SQL/RQ
  observation/acknowledgement adapters must be wired by the coordinator; fake hooks
  here do not establish live drain acceptance. Interrupted/unacknowledged drain
  retains a blocker requiring explicit operator disposition.
- Release hooks: `schema_revision(owner) -> str`, bounded `readiness(owner,deadline)`
  and `public_smoke(owner,deadline) -> {status}`. For a workflow needing short worker
  capacity, supply `smoke_workflow(owner,deadline,operations)` and drain hooks;
  `operations['launch_workers'](count=1)` is bound to the existing station lock and
  selected immutable worker definition. Do not reacquire the journal in this hook.
  Media smoke uses existing peer capacity/assets; it cannot mutate Processing.
- Lifecycle hooks are explicit bounded intake pause/resume, mount/TCP/schema/Redis/
  peer/public probes, writer quiescence and `export_hook(proof,deadline) -> {status}`.
  Infrastructure/state owns private DB/roles export implementation. Only selected
  export confirmation is journaled, never raw manifests/data. Generator discovery
  requires environment/Role=generator tags. Missing/unknown resources fail closed.
- CloudFront private origin-header values are copied directly between injected
  transport calls, never journaled or rendered. The safe CLI planner intentionally
  rejects private-header payloads. A separately approved private real transport
  must preserve that configuration without exposing it in argv/logs/evidence;
  this cycle provides no such real execution path.
- Workflow YAML definitions are prepared, not executed. Publication/apply remains
  DISABLED; the workflow runs selected-owner preparation only. Coordinator owns
  root test-tier/dependency/Makefile integration, CI execution, review, GitHub and
  eventual approved identity/approval gates. No common-check requirements weakened.

## Verification actually executed

Every repository command used the absolute assigned worktree as working directory.
Python imports used `PYTHONPATH` equal to that worktree; `scripts.aws.__file__` was
checked once and resolved to its worktree `scripts/aws/__init__.py`.

```text
PYTHONPATH=<assigned-absolute-worktree> .venv/bin/python -m pytest \
  -p scripts.dev.pytest_plugin --offline-fast tests/aws tests/processing/test_worker.py -q
128 passed in 0.52s (105 new bundle checks + 23 existing focused worker checks)

PYTHONPATH=<assigned-absolute-worktree> .venv/bin/ruff check \
  scripts/aws/{transport,journal,workers,release,lifecycle,artifacts}.py \
  processing/worker/{cloud,__main__}.py tests/aws
PASS (scoped formatting applied as well)

Offline PyYAML BaseLoader + bash -n + ast.parse of embedded Python:
3 workflow YAML files, 58 shell blocks, 8 embedded Python blocks parsed; PASS

git diff --check
PASS
```

No full historical suite, real subprocess AWS invocation, emulator activation,
container build, scan, long upload or cloud performance check was run.

Retained failed-test notes: the first run was **82 passed / 1 failed**, revealing
that tuple snapshots became lists on journal reload and broke restart restoration.
Snapshots now persist consistently and explicit restart restoration passes. A later
**82 passed / 1 failed** run caught the new early origin gate returning before
launch pause; wake now persists the pause before rejecting unresolved origin
interpretation, and performs no cloud mutation. Initial scoped Ruff findings were
formatting/unused-import issues and were corrected; final lint passes. Subsequent
expanded worker/claim/deadline/ownership checks passed; no failed run is AWS evidence.

## Limits that remain material

The one-station journal assumes an exclusively governed dedicated cluster. It
cannot coordinate independent stations or prevent out-of-band account writers.
An unacknowledged task or expired token is never cleared by stale absence. Cloud
control-plane uncertainty and pre-container provisioning cannot be converted to a
universal billing bound by a container watchdog; operator deadlines/inventory must
still account for that state.

The essential container command must be the finite wrapper. Existing FFmpeg
supervision creates separate encoder process groups; fake process-group tests do
not prove real kernel/Fargate descendant cleanup on essential container exit. That,
RQ warm acknowledgement/racing claims, role permissions, CloudFront propagation,
actual bad-candidate exit/restore, state exports/restore and complete compute/IP
closure require the authorized short genuine-cloud checks. Six long capacity
uploads remain reserved for future fixed prewarmed 1/2/3 capacity, never a fabricated
speedup or AWS PASS. The 14-day window remains anchored to 15 October.
