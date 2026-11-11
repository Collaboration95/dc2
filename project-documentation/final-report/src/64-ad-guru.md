### UC-6 Scale processing capacity independently

#### Description

Analysis and design: Guruprasath Gopal. Sam, the operator, enables and observes capacity through operator tools; work publication and the fallback timer start automatic decisions. Preconditions are an enabled launcher, a durable Processing backlog and a configured standard worker definition.

In the normal flow, a successful standard-work send wakes the launcher, and a one-minute schedule recovers a lost wake. The launcher reads queued current Attempts, visible standard-queue messages and worker inventory, reconciles earlier reservations, reserves available slots in one transaction, then starts finite workers. Each worker claims work separately and exits after its bounded execution. The postcondition is capacity between zero and three standard workers; unresolved starts still consume slots and excess work stays queued (`processing/launcher_trigger.py`, `processing/launcher.py`).

Exception flows cover zero visible demand, disabled control, unreadable inventory and uncertain RunTask replies; they prevent new reservations or preserve existing ones. A later observation can identify an uncertain task by its persisted launch identity; otherwise a permitted replay uses the same token and payload. Workers that repeatedly exit without claiming trigger a cooldown and then an idle breaker. Disabling waits for in-flight sends. Short-lane dispatch is a separate decision (AD-30, UC-2).

#### Analysis class diagram

Figure {@fig:uc6-analysis-class} separates the operator boundary, capacity decision and durable capacity records. A slot reservation has its own identity and lifecycle and does not claim a queued Attempt; its association to an executor is an observed outcome that may start unknown.

![Figure {#fig:uc6-analysis-class}. UC-6 conceptual capacity objects and responsibilities.](figures/uc6-analysis-class.png){width=10.5cm}

#### Analysis sequence diagrams

Figure {@fig:uc6-analysis-normal} follows demand through reservation to finite execution; Figure {@fig:uc6-analysis-recovery} shows the two alternatives, a lost start reply and disabling capacity.

![Figure {#fig:uc6-analysis-normal}. UC-6 normal flow: reserve before requesting an executor.](figures/uc6-analysis-normal.png){width=15cm}

![Figure {#fig:uc6-analysis-recovery}. UC-6 alternative flows: preserve uncertainty and interlock disable.](figures/uc6-analysis-recovery.png){width=14.5cm}

#### Design class diagram

Figure {@fig:uc6-design-class} maps those responsibilities to actual modules and records. `LauncherConfig.slots` clamps the configured cap to `HARD_CAP = 3`. `LauncherControl` is a singleton; `LaunchReservation` has a token primary key and unique `started_by`, linked to the control row by application logic rather than a foreign key. `EcsPort` and `QueueDepth` isolate network operations from the reservation policy (`processing/launcher_models.py`, `processing/launcher_aws.py`).

![Figure {#fig:uc6-design-class}. UC-6 selected implementation fields, operations and capacity records.](figures/uc6-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc6-design-normal} expands the normal tick. `tick` calls the module function `observe`, which lists and describes tasks through `EcsPort`. `_reserve` takes the control row `FOR UPDATE`, reconciles observations and commits reservations before `_send` calls RunTask. Demand is the smaller of SQL backlog (no lane filter) and visible standard-queue messages. Live workers plus unexplained reservations consume capacity, and workers not yet bound to an Attempt offset demand.

![Figure {#fig:uc6-design-normal}. UC-6 implementation: wake, observe, reserve, commit and send.](figures/uc6-design-normal.png){width=15cm}

Figure {@fig:uc6-design-recovery} details response loss and replay. An inventory failure aborts the tick, and an unreadable queue produces no new demand. A refused start releases its slot; an uncertain start keeps it for reconciliation, bounded replay or release at its deadline. Every replay goes back through `_send`, which repeats the shared control lock, the reservation lock and the state, enabled and session checks before `run_task` with the stored payload and the same `clientToken`.

![Figure {#fig:uc6-design-recovery}. UC-6 implementation: ambiguous start, reconciliation and checked replay.](figures/uc6-design-recovery.png){width=12cm}

Figure {@fig:uc6-design-disable} shows the disable interlock. `_send` holds the control row `FOR SHARE` during RunTask and `set_enabled` needs `FOR UPDATE`, so disabling returns only when no send is in flight. A later `_send` sees the flag off and releases its slot without calling ECS (`processing/launcher.py`).

![Figure {#fig:uc6-design-disable}. UC-6 implementation: disable waits for in-flight sends.](figures/uc6-design-disable.png){width=15cm}

#### Analysis to design

| Analysis responsibility | Design change and reason |
|---|---|
| Capacity controller | `launcher.tick`, `_reserve` and `_send` split observation, serialized decisions and uncertain network effects. |
| Capacity policy and reservation | `LauncherControl`, `LauncherConfig` and `LaunchReservation` add typed control, finite deadlines and stable replay identities. |
| Executor observation | `EcsPort`, `QueueDepth` and `Observation` make inventory and demand explicit; `AttemptTask` supplies claim bindings. |
| Demand notification | `WakeOnWork.send` adds one best-effort wake after a standard send; the schedule supplies recovery. |

`tests/v1/test_launcher_sql.py` covers concurrent always-on wakes, backlog larger than the cap, lost replies, identical replay, idle exits and disable races. The SQL suite uses PostgreSQL with fake ECS and SQS ports; dated cloud execution results are in §4. `tests/aws/v1/test_unattended_launch.py` checks configuration, IAM scope and operator control.

### UC-7 Release Processing on its own and demonstrate rollback

#### Description

Analysis and design: Guruprasath Gopal. Sam acts through CD and operator tools. Preconditions are an established environment, successful full CI for the exact source, verified immutable image evidence, additive migration evidence and a retained prior version; the release hooks also check the owner's intake and consumer conditions.

Normally, CD admits the source, verifies the selected images and identifies changed owners; a Processing-only change preserves Media. Promotion records private pending intent, runs the owning migration, publishes immutable versions, moves Processing aliases with revision checks and runs the owner public smoke. Adoption then records the images as the deployment baseline and updates the stack, including the launcher's worker definition (`scripts/aws/v1/release.py`, `deploy.py`, `scripts/ci/cd.sh`).

Failed admission moves no alias. A candidate failure prompts restore, which must itself pass smoke; unresolved recovery retains intent, and a provably unchanged candidate may be abandoned. Closing the environment defers release, and changed migrations need explicit additive compatibility attestation. Postconditions distinguish promoted, restored, abandoned and restore-failed outcomes; schema migrations are never reversed automatically.

#### Analysis class diagram

Figure {@fig:uc7-analysis-class} models release coordination, candidate evidence, prior state and recovery intent. The peer service is observed independently, and its preservation must be evidenced before an owner release is certified.

![Figure {#fig:uc7-analysis-class}. UC-7 conceptual release, evidence and recovery responsibilities.](figures/uc7-analysis-class.png){width=10cm}

#### Analysis sequence diagrams

Figure {@fig:uc7-analysis-normal} covers admission rejection and promotion; Figure {@fig:uc7-analysis-recovery} follows candidate failure through restore or retained recovery intent, distinguishing successful recovery from merely requesting it.

![Figure {#fig:uc7-analysis-normal}. UC-7 admission and normal independent owner release.](figures/uc7-analysis-normal.png){width=15cm}

![Figure {#fig:uc7-analysis-recovery}. UC-7 failed candidate and resumable recovery.](figures/uc7-analysis-recovery.png){width=12cm}

#### Design class diagram

Figure {@fig:uc7-design-class} uses the implemented release functions, station journal and adoption function. `DeployJournal` extends `Journal`; `Journal.save` atomically replaces private state and its station lock serializes local operation, which is designated-station coordination rather than a distributed lock (`scripts/aws/journal.py`). `OperatorTransport.call` is the AWS execution port; the older `CLITransport` is restricted to planning and emulator execution (`scripts/aws/v1/transport.py`, `scripts/aws/transport.py`).

![Figure {#fig:uc7-design-class}. UC-7 actual release, journal, transport and adoption operations.](figures/uc7-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc7-design-normal} shows the principal functions and durable boundaries. The helpers `_version` and `_move` are self-calls of the `release` module; only the AWS operations they issue reach `OperatorTransport`. The Journal records `publication_started` before `publish-version`, then the version receipt and the alias receipt. Automatic admission is tied to the triggering Main push CI run and attempt; manual admission also permits an exact-source full CI dispatch, and PR and scheduled runs are ineligible. CD checks the images it promotes against source and configuration evidence and registry scans (`scripts/ci/cd_gate.py`, `.github/workflows/cd.yml`).

![Figure {#fig:uc7-design-normal}. UC-7 implementation: exact-source admission, owner promotion and adoption.](figures/uc7-design-normal.png){width=15cm}

Figure {@fig:uc7-design-recovery} covers restore: `_move` checks alias version and revision, restore refuses concurrent drift and checks the prior function receipt, and intent is retained if restored smoke fails. Figure {@fig:uc7-design-uncertain} covers publication uncertainty: `_version` looks for a version carrying the unique release description and never publishes blindly. The later upload-to-playback smoke fails CD on error but has no automatic alias restore.

![Figure {#fig:uc7-design-recovery}. UC-7 implementation: restore checks and recovery outcomes.](figures/uc7-design-recovery.png){width=15cm}

![Figure {#fig:uc7-design-uncertain}. UC-7 implementation: lost publication reply and post-release smoke.](figures/uc7-design-uncertain.png){width=15cm}

#### Analysis to design

| Analysis responsibility | Design change and reason |
|---|---|
| Candidate evidence | `cd_gate.validate`, `validate_inputs` and the release plan bind source, image, scans and migration definitions before promotion. |
| Release coordinator | `release.promote`, `_version` and `_move` introduce durable preparation and revision-checked alias mutation. |
| Prior state and recovery intent | `snapshot` and `Journal` preserve owner/peer receipts and unresolved operations across interrupted runs. |
| Recovery and adoption | `restore` checks the prior runtime without schema downgrade; `deploy.adopt_release` updates the persistent baseline after success. |

`tests/aws/v1/test_v1_release.py` exercises peer preservation, lost responses, failed-candidate restore, concurrent alias changes and retained recovery intent with deterministic AWS protocol fakes. `test_owners_are_released_only_when_their_images_build_inputs_changed` (`test_persistent_environment.py`) checks owner selection and `test_release_plan.py` checks image evidence and scans. Dated cloud demonstrations are listed in §5.3.
