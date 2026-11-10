### UC-6 Scale processing capacity independently

#### Description

Guruprasath Gopal is responsible for this use case's analysis and design. Sam, the operator, enables and observes capacity through operator tools. Work publication and the fallback timer initiate automatic decisions. The preconditions are an enabled launcher, a durable Processing backlog and a configured standard worker definition. Media is independently deployed.

In the normal flow, a successful standard-work send wakes the launcher. A one-minute schedule recovers a lost wake. The launcher reads queued current Attempts, visible standard-queue messages and worker inventory. It reconciles earlier reservations, reserves available slots in one transaction, then starts finite workers. Each worker claims work separately and exits after its bounded execution. The postcondition is capacity between zero and three standard workers, with unresolved starts still consuming slots and excess work remaining queued (`processing/launcher_trigger.py`, `processing/launcher.py`).

Exception flows cover zero visible demand, disabled control, unreadable inventory and uncertain RunTask replies. These conditions prevent new reservations or preserve existing ones. A later observation can identify an uncertain task by its persisted launch identity; otherwise a permitted replay uses the same token and payload. Repeated workers that exit without claiming trigger a cooldown and then an idle breaker. Disabling waits for in-flight sends before returning.

#### Analysis class diagram

Figure {@fig:uc6-analysis-class} separates the operator boundary, capacity decision and durable capacity records. A slot reservation has its own identity and lifecycle; reserving capacity does not claim a queued Attempt. The association to an executor describes an observed outcome, which may initially be unknown.

![Figure {#fig:uc6-analysis-class}. UC-6 conceptual capacity objects and responsibilities.](figures/uc6-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figure {@fig:uc6-analysis-normal} follows demand through reservation to finite execution. Figure {@fig:uc6-analysis-recovery} shows the two principal alternatives: a lost start reply and disabling capacity. These analysis messages express responsibilities without choosing a framework or cloud API.

![Figure {#fig:uc6-analysis-normal}. UC-6 normal flow: reserve before requesting an executor.](figures/uc6-analysis-normal.png){width=15cm}

![Figure {#fig:uc6-analysis-recovery}. UC-6 alternative flows: preserve uncertainty and interlock disable.](figures/uc6-analysis-recovery.png){width=15cm}

#### Design class diagram

Figure {@fig:uc6-design-class} maps those responsibilities to actual modules and records. `LauncherConfig.slots` clamps the configured cap to `HARD_CAP = 3`. `LauncherControl` has a singleton constraint; `LaunchReservation` has a token primary key and unique `started_by`. Their association is application-level, without a foreign key. `EcsPort` and `QueueDepth` isolate network operations from the reservation policy (`processing/launcher_models.py`, `processing/launcher_aws.py`).

![Figure {#fig:uc6-design-class}. UC-6 selected implementation fields, operations and capacity records.](figures/uc6-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc6-design-normal} expands the normal tick. `_reserve` takes the control row `FOR UPDATE`, reconciles observations and commits reservations before `_send` calls RunTask. It computes demand as the smaller of SQL backlog and visible messages. SQL backlog has no lane filter; standard-queue visibility limits standard demand. Live workers plus unexplained reservations consume capacity. Workers not yet bound to an Attempt also offset demand.

![Figure {#fig:uc6-design-normal}. UC-6 implementation: wake, observe, reserve, commit and send.](figures/uc6-design-normal.png){width=15cm}

Figure {@fig:uc6-design-recovery} details response loss and the disable interlock. `_send` holds the control row `FOR SHARE` during RunTask; `set_enabled` needs `FOR UPDATE`. An inventory failure aborts the tick. An unreadable queue produces no new demand. A refused start releases its slot, while an uncertain start retains it for reconciliation, bounded replay or eventual release under the configured horizon/deadline rules.

![Figure {#fig:uc6-design-recovery}. UC-6 implementation alternatives: ambiguous start, reconciliation and disable.](figures/uc6-design-recovery.png){width=15cm}

The launcher controls standard capacity, while `short_lane.work_lane` selects the message lane. Short dispatch requires the feature flag, positive source size at most 64 MiB and no earlier Lambda attempt. Probe admission subsequently checks duration at most 60 seconds and height at most 1080. Short execution has a separate maximum concurrency of two. When both lanes are enabled, their configured combined ceiling is five encoders (`processing/short_lane.py`).

#### Analysis to design

| Analysis responsibility | Design change and reason |
|---|---|
| Capacity controller | `launcher.tick`, `_reserve` and `_send` split observation, serialized decisions and uncertain network effects. |
| Capacity policy and reservation | `LauncherControl`, `LauncherConfig` and `LaunchReservation` add typed control, finite deadlines and stable replay identities. |
| Executor observation | `EcsPort`, `QueueDepth` and `Observation` make inventory and demand explicit; `AttemptTask` supplies claim bindings. |
| Demand notification | `WakeOnWork.send` adds one best-effort wake after a standard send; the schedule supplies recovery. |

The real-PostgreSQL tests in `tests/v1/test_launcher_sql.py` cover concurrent always-on wakes, backlog larger than the cap, lost replies, identical replay, idle exits and disable races. ECS and SQS are fakes in this suite. `tests/aws/v1/test_unattended_launch.py` separately checks configuration, IAM scope and operator control; neither suite alone establishes live cloud execution.

### UC-7 Release Processing on its own and demonstrate rollback

#### Description

Guruprasath Gopal is responsible for this use case's analysis and design. Sam acts through CD and operator tools. Preconditions are an established environment, eligible successful full CI for the exact source, verified immutable image evidence, compatible additive migration evidence and a retained prior version. Owner release also requires the intake/consumer conditions checked by its release hooks.

Normally, CD admits the source, verifies the selected images and identifies changed owners. A Processing-only change preserves Media. Promotion records private pending intent, runs the owning migration, publishes immutable versions, moves Processing aliases with revision checks and performs the owner public smoke. Successful promotion updates the worker selection in release state. Adoption then records the images as the deployment baseline and updates the stack, including the launcher's worker definition (`scripts/aws/v1/release.py`, `deploy.py`, `scripts/ci/cd.sh`).

Failed admission moves no alias. A candidate failure prompts restore, which must itself pass smoke; unresolved recovery retains intent. A provably unchanged candidate may instead be abandoned. Closing the environment defers release, and changed migrations require explicit additive compatibility attestation. Postconditions distinguish promoted, restored, abandoned and restore-failed outcomes. Schema migrations are not automatically reversed.

#### Analysis class diagram

Figure {@fig:uc7-analysis-class} models release coordination, candidate evidence, prior state and recovery intent. The peer service is an independently observed participant. The model requires evidence of its preservation before certifying an owner release.

![Figure {#fig:uc7-analysis-class}. UC-7 conceptual release, evidence and recovery responsibilities.](figures/uc7-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figure {@fig:uc7-analysis-normal} includes admission rejection and successful promotion. Figure {@fig:uc7-analysis-recovery} follows candidate failure through restore or retained recovery intent. These distinguish successful recovery from merely requesting it.

![Figure {#fig:uc7-analysis-normal}. UC-7 admission and normal independent owner release.](figures/uc7-analysis-normal.png){width=15cm}

![Figure {#fig:uc7-analysis-recovery}. UC-7 failed candidate and resumable recovery.](figures/uc7-analysis-recovery.png){width=15cm}

#### Design class diagram

Figure {@fig:uc7-design-class} uses the implemented release functions, station journal and deployment adoption function. `DeployJournal` extends `Journal` with deployment state. `Journal.save` atomically replaces private state; its station lock serializes local operation. This is designated-station coordination, rather than a distributed lock (`scripts/aws/journal.py`). `OperatorTransport.call` is the explicit AWS execution port; the older `CLITransport` is restricted to planning/emulator execution (`scripts/aws/v1/transport.py`, `scripts/aws/transport.py`).

![Figure {#fig:uc7-design-class}. UC-7 actual release, journal, transport and adoption operations.](figures/uc7-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc7-design-normal} shows the principal functions and durable boundaries. Automatic admission is tied to the triggering Main push CI run and attempt. Manual admission also permits an exact-source full CI dispatch; PR and scheduled runs are ineligible. CD checks the images it promotes against source/configuration evidence and registry scans. Source CI success does not by itself establish identical CI image bytes (`scripts/ci/cd_gate.py`, `.github/workflows/cd.yml`).

![Figure {#fig:uc7-design-normal}. UC-7 implementation: exact-source admission, owner promotion and adoption.](figures/uc7-design-normal.png){width=15cm}

Figure {@fig:uc7-design-recovery} covers restore, publication uncertainty and later smoke failure. `_move` checks alias version and revision before changing it. `_version` persists a publication marker and reconciles a lost reply by its unique description; it does not blindly publish again. Restore refuses concurrent alias drift and retains intent if restored smoke fails. The later upload-to-playback smoke fails CD on error but has no independent automatic alias-restore promise.

![Figure {#fig:uc7-design-recovery}. UC-7 recovery: restore checks, uncertain publication and post-release smoke.](figures/uc7-design-recovery.png){width=15cm}

#### Analysis to design

| Analysis responsibility | Design change and reason |
|---|---|
| Candidate evidence | `cd_gate.validate`, `validate_inputs` and the release plan bind source, image, scans and migration definitions before promotion. |
| Release coordinator | `release.promote`, `_version` and `_move` introduce durable preparation and revision-checked alias mutation. |
| Prior state and recovery intent | `snapshot` and `Journal` preserve owner/peer receipts and unresolved operations across interrupted runs. |
| Recovery and adoption | `restore` checks the prior runtime without schema downgrade; `deploy.adopt_release` updates the persistent baseline after success. |

`tests/aws/v1/test_v1_release.py` exercises peer preservation, lost responses, failed candidate restore, concurrent alias changes and retained recovery intent using deterministic AWS protocol fakes. `test_owners_are_released_only_when_their_images_build_inputs_changed` in `tests/aws/v1/test_persistent_environment.py` checks owner selection. `tests/aws/v1/test_release_plan.py` checks image evidence and scans. These support the implementation claims; dated cloud demonstrations remain separate evidence.
