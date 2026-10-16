# V1 dead-letter queue runbook

Scope: the three SQS Standard queues (`processing-commands`, `processing-work`,
`media-results`) and their DLQs (14-day retention). Local steps use the Moto
emulator; the same commands work against a real queue only when an operator runs
them with their own authorized credentials. Nothing here is AWS evidence.

## What lands in a DLQ and what is lost

A message reaches a DLQ after `maxReceiveCount` receives without a delete. SQL,
not the queue, is the source of truth, so a DLQ entry is a *symptom to explain*,
not data to preserve:

| DLQ | Typical cause | Why SQL already covers it |
|---|---|---|
| `processing-commands` | Invalid envelope, owner/source-prefix mismatch, `retry` before `submit` outlived the retry window, conflicting duplicate ID | The inbox row is rolled back with the failed transaction, so a redrive after a fix is processed once. |
| `processing-work` | Identity/source mismatch, a task binding conflict, a message for an unknown attempt. Stale, cancelled, terminal or already-claimed work is **deleted by the encoder** and never reaches the DLQ | Repair re-sends work for a queued attempt with the same message ID on a backoff of 60s doubling to 15 min. |
| `media-results` | A result Media rejects (409/422: source differs from the accepted descriptor, outputs outside the attempt prefix, attempt regression) | The rejected apply rolls back its inbox row. The projection stays at the last good version and **any later version applies**: only a poisoned *final* result can leave a stale status. |

## Inspect (read-only)

Point inspection at a **DLQ only**. A peek is still a receive and raises
`ApproximateReceiveCount`; on a source queue that could push live work into its
DLQ.

```sh
python -m delivery.dlq inspect --queue-url "$DLQ_URL" --limit 10
# Local emulator only:  --endpoint-url http://127.0.0.1:<moto port>
```

Output is identities only (kind, message ID, owner, asset, job, attempt, state
version, status, receive count). `"valid": false` means the body is not a V1
envelope; treat it as a producer defect or injection and do not redrive it.

Equivalent AWS CLI (operator credentials, shows bodies; handle with care):

```sh
aws sqs receive-message --queue-url "$DLQ_URL" --max-number-of-messages 10 \
  --visibility-timeout 0 --attribute-names ApproximateReceiveCount
```

## Decide

1. `media-results`, valid envelope: find the cause from the rejection class in the
   Media result Lambda logs (`MediaError` status 409 or 422), fix the cause (code
   or data), then redrive. If the cause cannot be fixed, publish a fresh result
   instead (below) and leave the old message to expire.
2. `processing-commands` or `processing-work`, valid envelope: confirm the SQL
   state the message refers to is not already terminal. If it is, the message is
   obsolete; purge it by letting retention expire. If not, fix the cause, redrive.
3. Anything with `"valid": false`: never redrive.

## Redrive

```sh
python -m delivery.dlq redrive --dlq-arn "$DLQ_ARN" --per-second 5
python -m delivery.dlq status  --dlq-arn "$DLQ_ARN"
```

This calls `StartMessageMoveTask` without a destination, returning each message
to its original queue. Equivalent: `aws sqs start-message-move-task
--source-arn "$DLQ_ARN" --max-number-of-messages-per-second 5`. Redrive is safe to
repeat: the SQL inbox deduplicates by message ID and content hash, and the
encoder deletes stale work.

## Unfreeze a Media projection without redriving

When the final result for a job was quarantined and cannot be applied, ask
Processing for a fresh snapshot. It bumps the job's state version and stages a new
result from its outbox, which Media applies like any later version:

```python
from processing.recovery_v1 import reemit_result
await reemit_result(factory, job_id)   # then let the next repair tick publish it
```

For a queued job this also stages one new work message under the new version;
the older one becomes stale and is deleted by the next encoder.

## After the incident

Record the DLQ name, count, cause and action in the session journal. A DLQ that
refills after redrive means the cause was not fixed; stop and investigate before
a second redrive.
