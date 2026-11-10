## Design Problems and Patterns

The analysis and design responsibilities are DP-1, **Bounded cloud capacity and safe per-owner release**, owned by Guruprasath Gopal; DP-2, **Durable asynchronous Processing handoff**, owned by Ibrahim Mammadov; and DP-3, **Trusted owner identity and reusable public contract**, owned by Nguyễn Kim Long. Each problem follows five parts: the problem with class and sequence models, candidate patterns, selection rationale, solution class and sequence models, and implementation decisions with verification evidence.

### DP-1 Bounded cloud capacity and safe per-owner release (Guruprasath Gopal)

#### The problem

Processing needs to absorb queued video work without keeping encoders running while idle or changing Media capacity. Multiple wake sources can observe the same backlog. A naive observe-then-launch decision lets each caller spend the same apparent free slots. A lost launch response makes it worse: retrying as a fresh request can start another billable executor. Figure {@fig:dp1-problem-class} shows the missing shared capacity authority; Figure {@fig:dp1-problem-sequence} illustrates the race. These are deliberately hypothetical failing models, not a claim that this code path is deployed.

![Figure {#fig:dp1-problem-class}. DP-1 problem structure: independent launch decisions without durable reservations.](figures/dp1-problem-class.png){width=15cm}

![Figure {#fig:dp1-problem-sequence}. DP-1 failing scenario: concurrent callers reuse the same free capacity.](figures/dp1-problem-sequence.png){width=15cm}

The forces are bounded spend, asynchronous demand, eventual inventory visibility and recovery after interruption. Release is a related sub-scenario: changing Processing code must preserve Media and retain enough prior state to recover a failed candidate. UC-7 supplies its detailed class and sequence models.

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

These are a comparison of design alternatives against the implemented constraints, rather than a claim that all candidates were benchmarked.

#### Why the chosen pattern

The selected capacity design combines queue buffering and competing consumers with durable reservations and an idempotent launch request. The reservation is the local authority to spend a slot; inventory explains what happened externally. Serializing reservation transactions closes the race between callers. Persisting the token before the external call makes response loss recoverable without granting extra capacity. Finite workers provide return to zero by exiting, while cooldown and idle-breaker rules prevent endless empty replacements.

Per-owner release applies the same principle to a different uncertainty: save intent before mutation, identify the resulting version and check current state before repair. It is a journaled recovery protocol, not an atomic transaction across all cloud resources. Separate owner evidence and peer snapshots support independent deployment (`processing/launcher.py`, `scripts/aws/v1/release.py`).

#### Solution models

Figure {@fig:dp1-solution-class} labels the implemented capacity-gate, reservation and adapter roles. The singleton/reservation association is logical and has no foreign key. Figure {@fig:dp1-solution-sequence} shows serialized admission and token reconciliation under concurrent wakes. The corresponding release solution appears in Figures {@fig:uc7-design-class}, {@fig:uc7-design-normal} and {@fig:uc7-design-recovery}.

![Figure {#fig:dp1-solution-class}. DP-1 solution roles implemented by the launcher and its SQL records.](figures/dp1-solution-class.png){width=15cm}

![Figure {#fig:dp1-solution-sequence}. DP-1 solution: reserve once, retain uncertainty and reconcile the same identity.](figures/dp1-solution-sequence.png){width=15cm}

#### Implementation decisions

`_reserve` calculates `occupied = live workers + unexplained reservations`, then bounds new reservations by both remaining slots and unmet demand. `LauncherConfig.slots` cannot exceed three. The demand subtraction includes unclaimed live workers and pending starts, preventing another executor being launched for work existing capacity can still claim. A shared control lock spans each send, while disable takes an exclusive lock. Always-on configuration removes the session-end gate; deadlines, reservations, the enable flag and idle protection remain (`processing/launcher.py`, `processing/launcher_models.py`).

The launcher-specific SQL tests cover ten queued jobs against cap three, concurrent always-on wakes, lost RunTask replies, identical replay, restarts and disabling during a send (`tests/v1/test_launcher_sql.py`). They use real PostgreSQL with fake cloud ports. Infrastructure tests check bounded permissions and operator controls (`tests/aws/v1/test_unattended_launch.py`).

For release, `Pipeline.changed_owners` compares image build inputs; `cd.sh` preserves unchanged owners, defers migration changes for attestation and invokes restore after failed promotion. Candidates and kept-running images require strict scans. A replaced baseline can carry recorded retained-fixable Trivy findings solely as a restore target; ECR identity, completeness and unaccepted HIGH/CRITICAL checks still apply. `restore` never downgrades schema, and adoption updates the stack's recorded images after promotion. Release protocol, scan and adoption tests reside in `tests/aws/v1/test_v1_release.py`, `test_release_plan.py` and `test_persistent_environment.py`. These tests establish the modeled decisions without asserting a fresh deployment or rollback demonstration.
