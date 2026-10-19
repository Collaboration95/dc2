# Service contracts

`contracts/` is the **published language** that Media Management and Processing share. It is
also a **shared kernel** in the Domain-Driven Design sense. The V1 images (`deploy/v1/*.Dockerfile`)
copy three shared directories into both services: `contracts/` (this published language),
`delivery/` (outbox, inbox and the SQS adapter) and `runtime_support/` (Lambda runtime helpers). The
versioning policy below governs `contracts/`; `delivery/` and `runtime_support/` are shared code that
moves with whichever service image is rebuilt. No domain package is shared between the services, they
make no HTTP call to each other, and each owns its own database (both on one Aurora cluster, which
is a shared failure and capacity boundary). Processing also trusts the identity that the Media-owned
API Gateway authorizer attaches to a request. The services communicate through SQS messages
(`submit`, `retry`, `cancel` from Media; `work` and `result` from Processing) and through the
trusted actor that API Gateway's Media authorizer attaches to a request.

| File | Defines |
|---|---|
| `v1.py` | `Envelope` and `Source` (every queue message), `Actor` (the authorizer's context), `SCHEMA_VERSION`, `EMIT_VERSION`, `PRODUCERS` |
| `gateway.py` | The adapter from API Gateway HTTP API events to the services' ASGI apps |

Because the directory is source-copied into each image, a contract change reaches a service only
when that service is rebuilt and released. The rules below exist so that those releases can
happen in either order, one service at a time, without a window in which a message is refused.

## Versioning policy

Let **N** be `SCHEMA_VERSION`, the newest version a copy of `contracts/` can read.

1. **Additive within a version.** A change that stays inside version N may only add things:
   an optional envelope or `Source` field, an optional key in a `payload`, a new `kind` with
   its own producer. It must not rename, remove, retype or re-purpose a field, change the
   meaning of a value, or make validation stricter for data a producer already sends.
2. **Consumers accept N and N-1.** `accepted_versions()` returns `{N, N-1}`. A consumer reads
   both, refuses anything newer (it cannot know what changed) and refuses a non-integer
   version (`True == 1` in Python, but the wire says integer).
3. **Consumers ignore what they do not know.** `Envelope.from_dict`, `Source.from_dict` and
   `Actor.from_context` read the fields they define and drop the rest, so a newer producer's
   extra field is neither an error nor stored. Dropping it also keeps the replay fingerprint
   (the inbox's duplicate check) identical across producer versions. A `payload` is an open
   map: a consumer reads only the keys it names. The single closed payload is the no-job
   cancellation acknowledgement (`status`, `cancellation_confirmed`, `command_message_id`); it
   is checked exactly because it authorizes source deletion, so changing it needs a new version.
4. **Producers emit N only after every consumer accepts N.** `EMIT_VERSION` is what a
   producer stamps on a message or an actor, and it is never ahead of what consumers read.

### Rolling out a breaking change (version N to N+1)

| Release | Change | Safe because |
|---|---|---|
| 1 | Raise `SCHEMA_VERSION` to N+1. Leave `EMIT_VERSION` at N. Ship the new field semantics behind the reading side only. Release Media and Processing in any order. | Everything still on the wire is N, which both copies read. |
| 2 | Once both services run release 1, raise `EMIT_VERSION` to N+1. Release in any order. | Every consumer already reads N+1; messages still in flight at N are read as N-1. |
| later | When no N-1 producer or message can remain (queues drained, DLQ empty), retire N-1 by raising `SCHEMA_VERSION` again. | N-1 is gone from the wire. |

A purely additive change (rule 1) needs none of this: the consumer that does not know the field
ignores it, so producer and consumer can ship independently and the field starts to matter when
a consumer first reads it.

## What enforces it

* **Golden fixtures** (`tests/v1/fixtures/contracts/`, checked by
  `tests/v1/test_contract_fixtures.py`) freeze the shape, the accepted and emitted versions and
  the negative cases. Changing the contract changes a fixture in the same pull request.
* **Tolerance tests** (`tests/v1/test_v1_wire_contracts.py`, `envelopes_additive.json`) prove
  that an unknown field and the previous version are accepted, that a newer version and a
  missing known field are refused, and that no service hardcodes the version it stamps.
* **Consumer-driven contract tests** (`tests/contracts/consumers/`). Each consumer owns a file
  that lists the messages it consumes and the fields it reads. The consumer's tests run its
  real entrypoint against those messages, with an additive field and with the previous
  version. The producer's tests build its real messages and check them against that same file,
  so a producer change that drops something the consumer reads fails in the producer's suite.

| Consumer-owned file | Consumer test | Producer test |
|---|---|---|
| `media_consumes_processing_results.json` | `tests/media/test_media_consumer_contract.py` (`consume_result`, `apply_result`) | `tests/processing/test_processing_consumer_contract.py` (`emit_state`, `OutputStore`) |
| `processing_consumes_media_commands.json` | `tests/processing/test_processing_consumer_contract.py` (`handle_command`) | `tests/media/test_media_consumer_contract.py` (`v1_lifecycle.command`) |

To change what a consumer reads, edit its file in the consumer's pull request. To change what a
producer sends, keep the consumer's file passing, or agree the change with the consumer first.

## What this does not claim

These are offline tests against fixtures and fakes. They do not exercise a live queue, and the
release `compatibility` gate is still an operator attestation that a released pair was run
together; these tests are what that attestation should rest on, not a replacement for it. Only
version 1 exists today, so "N-1" is exercised by raising the version in tests rather than by a
second real version.
