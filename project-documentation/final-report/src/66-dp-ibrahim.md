### DP-2 Durable asynchronous Processing handoff (Ibrahim Mammadov)

#### The problem

Ibrahim Mammadov is responsible for DP-2's analysis and design. An accepted video must survive temporary unavailability of Processing or the queue without losing its processing request. Media and Processing own separate databases; SQL commit and queue publication cannot share one local atomic transaction. The design must also tolerate duplicate delivery, reordered commands and lost replies without accepting stale execution or displaying older results.

Figure {@fig:dp2-problem-class} models the direct dual-write candidate. Figure {@fig:dp2-problem-sequence} exposes its failure window: the Asset commits, then the process crashes before publishing. Sending first merely moves the window: Processing could receive work for acceptance that later rolls back. These are explanatory candidate models. The proposal's synchronous peer `SubmitJob`/Redis-RQ arrangement is the recorded earlier alternative; the current code uses SQL ledgers and SQS (`docs/architecture/decisions.md`, AD-11).

![Figure {#fig:dp2-problem-class}. DP-2 candidate structure with an unprotected SQL/broker dual write.](figures/dp2-problem-class.png){width=15cm}

![Figure {#fig:dp2-problem-sequence}. DP-2 lost publication and ambiguous-send failure windows.](figures/dp2-problem-sequence.png){width=15cm}

#### Candidate patterns

| Candidate | Benefit | Main consequence |
|---|---|---|
| Transactional outbox + idempotent inbox | Owned state and message intent commit locally; consumers deduplicate in their mutation transaction. | Requires a relay, repair, retained ledgers and explicit ordering fences; transport remains at least once. |
| Direct dual write: publish after commit | Small API path and immediate publication when dependencies are healthy. | Crash or broker outage after commit loses intent; uncertain sends require durable reconciliation and deduplication. |
| Synchronous peer HTTP with request identity | Immediate peer response and familiar request handling. | Couples acceptance to peer availability; a timeout still leaves an ambiguous outcome and requires durable retry/reconciliation. |

#### Why the chosen pattern

The outbox/inbox pair preserves local transaction boundaries and reuses the existing SQS transport. Media accepts independently of Processing availability, and Processing atomically prepares its own work/results before command acknowledgement. An inbox alone cannot recover an unsent command; an outbox alone cannot prevent repeated consumer mutations. Together they address both failure boundaries, while guard, version and lease checks handle domain ordering. The tradeoff is eventual status propagation and explicit repair rather than a synchronous cross-service result.

#### Solution models

Figure {@fig:dp2-solution-class} labels the implemented pattern roles. `delivery.sql` supplies shared algorithms, while each owner retains its own inbox/outbox rows. The ledgers are technical consistency records rather than children reached through cross-database foreign keys. `Envelope`, `Source` and `Actor` in `contracts/v1.py` carry versioned identities and values across the boundary; the common schema does not itself grant producer authority.

![Figure {#fig:dp2-solution-class}. DP-2 owner-local outboxes, idempotent inboxes and relay adapter.](figures/dp2-solution-class.png){width=15cm}

Figure {@fig:dp2-solution-sequence} follows one accepted command through a lost-send reply. The relay reserves a due row under `SKIP LOCKED`, commits its claim, and sends outside SQL locks. A second transaction records success or retry only if the claim token still matches. Lost replies can cause another send of the same identity. Processing's inbox, guarded Job/Attempt and follow-on outboxes commit together; the result path repeats the pattern for Media's projection.

![Figure {#fig:dp2-solution-sequence}. DP-2 committed intent, fenced relay and duplicate-safe consumption.](figures/dp2-solution-sequence.png){width=15cm}

#### Implementation decisions

`delivery.sql.stage` never commits implicitly. Direct finalize calls `media.messaging.enqueue_submit` inside adoption; edit uses `stage_submit` in its separate source-adoption transaction. `MediaRepair` calls `publish_commands` later. The invariant is commit-before-send, including when repair runs before the HTTP response reaches the client (`media/handlers.py`, `media/services/direct_intake.py`, `media/services/v1_lifecycle.py`).

`delivery.sql.accept` keys deduplication by message UUID and canonical body hash. Identical replay returns false; changed content raises `MessageConflict`. `handle_command` commits inbox and owned changes before returning. `delivery.sqs.consume_batch` records callback exceptions as partial failures; the Lambda mapping deletes successful records. `handlers.invoke` attempts best-effort publication after consumption, while repair retains responsibility for unavailable sends. Encoders stage result intent in SQL; publication belongs to the Processing relay.

`processing.recovery_v1.repair_work` reconstructs or rearms transport intent for queued current attempts. Execution expiry uses `recover_expired`/`interrupt`, producing an abandoned Attempt, failed Job, cleanup and result intent. User retry creates a new Attempt. These mechanisms complement inbox deduplication; they do not provide exactly-once transport.

The SQL assertions in `tests/v1/test_messaging_sql.py::test_lost_send_response_replays_after_commit_outside_locks` acquire the rows with `NOWAIT` during a simulated send and verify stable replay identities. `test_submit_duplicate_conflict_and_rollback` checks atomic acceptance and conflict rollback; `test_success_output_namespace_validation_and_atomic_terminal_result` checks terminal intent. `tests/media/test_v1_result_delivery.py::test_projection_commits_before_successful_batch_ack` checks projection/ACK ordering. These tests establish the stated local consistency mechanisms; cloud recovery latency is a separate measurement.
