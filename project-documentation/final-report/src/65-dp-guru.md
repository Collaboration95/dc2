## Design Problems and Patterns

DP-1 to DP-3 follow the ownership allocation in the Project Plan. Each problem has five parts: the problem with class and sequence models, candidate patterns, the rationale for the chosen pattern, solution class and sequence models, and implementation decisions with verification evidence.

### DP-1 Bounded cloud capacity and safe per-owner release (Guruprasath Gopal)

#### The problem

Processing must absorb queued video work without idle encoders and without changing Media capacity. Several wake sources can see the same backlog, so a naive observe-then-launch decision lets each caller spend the same apparent free slots. A lost launch response is worse: retrying as a fresh request can start another billable executor. Figure {@fig:dp1-problem-class} shows the missing shared capacity authority; Figure {@fig:dp1-problem-sequence} illustrates the race. The problem models illustrate the unprotected observe-then-launch alternative.

![Figure {#fig:dp1-problem-class}. DP-1 problem structure: independent launch decisions without durable reservations.](figures/dp1-problem-class.png){width=15cm}

![Figure {#fig:dp1-problem-sequence}. DP-1 failing scenario: concurrent callers reuse the same free capacity.](figures/dp1-problem-sequence.png){width=15cm}

The forces are bounded spend, asynchronous demand, eventual inventory visibility and recovery after interruption. Release is a related sub-scenario: a Processing change must preserve Media and keep enough prior state to recover a failed candidate (UC-7 holds its models).

#### Candidate patterns

| Capacity candidate | Benefit | Cost or limitation for FlickPond |
|---|---|---|
| ECS service autoscaling on queue depth | Managed desired-count adjustment for a continuing consumer service. | Requires a service and scale-in policy in place of the current one-Attempt finite task lifecycle; queue depth alone does not explain uncertain starts. |
| Fixed always-on worker pool | Predictable warm consumers and simple capacity accounting. | Pays for idle workers and weakens the zero-idle-encoder goal. |
| Reservation-based launcher with a global cap | Records slot ownership before launch; supports finite tasks and stable replay. | Requires SQL locking, inventory reconciliation and explicit uncertainty handling. **Selected.** |

| Release candidate | Benefit | Cost or limitation |
|---|---|---|
| All-at-once stack update | One deployment operation. | Couples code changes to a wider update and lacks the owner-specific smoke/recovery protocol. |
| Blue/green | Keeps separate candidate and prior environments for cutover. | Duplicates capacity and requires additional traffic and database coordination. |
| Per-owner journaled release | Exact-source admission, owner smoke, retained prior receipts and checked restore. | Requires resumable intent and additive schema compatibility. **Selected.** |

The comparison evaluates each alternative against finite-task operation, bounded spend and recoverability.

#### Why the chosen pattern

The selected capacity design combines queue buffering and competing consumers with durable reservations and an idempotent launch request. The reservation is the local authority to spend a slot; inventory explains what happened externally. Serializing reservation transactions closes the race between callers, and persisting the token before the external call makes response loss recoverable without extra capacity. Finite workers return to zero by exiting; cooldown and idle-breaker rules stop endless empty replacements.

Per-owner release applies the same principle to a different uncertainty: save intent before mutation, identify the resulting version and check current state before repair. It is a journaled recovery protocol, not an atomic transaction across cloud resources; separate owner evidence and peer snapshots support independent deployment (`processing/launcher.py`, `scripts/aws/v1/release.py`).

#### Solution models

Figure {@fig:dp1-solution-class} labels the implemented capacity-gate, reservation and adapter roles. The singleton/reservation association is logical and has no foreign key. Figure {@fig:dp1-solution-sequence} labels the same roles at run time: `LauncherControl` is the serialization root, `LaunchReservation` the durable reservation and `EcsPort` the adapter. The figure shows serialized admission, then reconciliation by token, with every replay passing through the checked `_send`. The corresponding release solution appears in Figures {@fig:uc7-design-class}, {@fig:uc7-design-normal} and {@fig:uc7-design-recovery}.

![Figure {#fig:dp1-solution-class}. DP-1 solution roles implemented by the launcher and its SQL records.](figures/dp1-solution-class.png){width=14cm}

![Figure {#fig:dp1-solution-sequence}. DP-1 solution: reserve once, retain uncertainty and reconcile the same identity.](figures/dp1-solution-sequence.png){width=13cm}

#### Implementation decisions

`_reserve` calculates `occupied = live workers + unexplained reservations`, then bounds new reservations by remaining slots and unmet demand; `LauncherConfig.slots` cannot exceed three. Unclaimed live workers and pending starts offset demand, so no executor starts for work that existing capacity can still claim. A shared control lock spans each send, while disable takes an exclusive lock. Always-on configuration removes the session-end gate; deadlines, reservations, the enable flag and idle protection remain (`processing/launcher.py`, `processing/launcher_models.py`).

The launcher-specific SQL tests cover ten queued jobs against cap three, concurrent always-on wakes, lost RunTask replies, identical replay, restarts and disabling during a send (`tests/v1/test_launcher_sql.py`). The suite uses real PostgreSQL with fake cloud ports. Infrastructure tests check bounded permissions and operator controls (`tests/aws/v1/test_unattended_launch.py`).

For release, `Pipeline.changed_owners` compares image build inputs and `cd.sh` preserves unchanged owners, and the same principle applies: intent is saved before mutation, and restore never downgrades schema. Candidates and kept-running images require strict scans; the detailed protocol is in UC-7 and §5.3. Release protocol, scan and adoption tests reside in `tests/aws/v1/test_v1_release.py`, `test_release_plan.py` and `test_persistent_environment.py`. The tests verify release selection, image policy and recovery behavior; the recorded cloud demonstrations are listed in §5.3.
