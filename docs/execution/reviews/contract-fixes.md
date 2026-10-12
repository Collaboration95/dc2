# Integration review R3 contract corrections

Branch: `work/contract-tests`. Base: `0b24c9da4007bd44db9671f07924571d98e68e5b`.
Scope: CT-20, CT-21 and CT-23 only. Code implemented; live verification pending.
The original integration review remains historical input. This is not final
V1/V2 acceptance; the overall review verdict remains REVISE. R1, R2 and R4 are
owned by other agents and are **not yet verified** by this lane.

| Case | Exact test function | Layers and assertions | Verification |
| --- | --- | --- | --- |
| CT-20 | `tests/integration/test_processing_worker.py::test_real_worker_source_invalid_edit_has_failed_attempt_and_public_projection` | Real Processing PostgreSQL and FFmpeg fixture/ffprobe. Public/P schemas accept an out-of-source crop and an over-duration clip. Actual `tasks.execute` calls the real source validator, persists a failed current Attempt with error/start/finish, and exposes failed owner read and actual MM public projection without outputs or playback URLs. | Both parameters collected; live PG/FFmpeg pending. |
| CT-21 | `tests/integration/test_media_persistence.py::test_deleted_derived_asset_edit_key_replay_is_410_without_recreation` | Real MM PostgreSQL and actual ASGI edit/delete/replay handlers. Original retained/readable, derived Asset deleted, edit key retained. Two replays return 410; no new Asset, staged row, object, Processing submission/job or cancellation; key/hash and original remain intact. | Collected; live PG pending. |
| CT-23 | `tests/contracts/test_prepared_contracts.py::test_every_prepared_example_matches_its_owning_contract` | Offline JSON Schema: reads all eight prepared payloads and selects the correct public/P/MM operation schema; only the textual note is metadata. | Passed offline. |
| CT-23 negative | `tests/contracts/test_prepared_contracts.py::test_broken_prepared_example_fails_schema_validation` | Independently corrupts each of the eight examples; every variant must raise `ValidationError`. | Eight parameters passed offline. |
| CT-23 unmapped | `tests/contracts/test_prepared_contracts.py::test_unmapped_prepared_example_cannot_be_skipped` | An added payload without a deliberate owning-contract mapping fails. | Passed offline. |

`scripts/dev/contracts.py::check_examples` maps Submit/Retry/Job and owner/conflict
errors to Processing, upload acceptance/public Asset to the public contract, and
source access to MM internal. It reuses the existing request/response validators;
prepared documents and examples are unchanged. Exact functions/current lines are
also mapped in `docs/execution/contract-evidence.json`.

CT-20 uses the existing real worker lane fixtures and file Recorder. Its validator
observer delegates unchanged to the real validator and records the actual
geometry/duration rejection, so an unrelated download/probe failure cannot pass.
Worker execution, probing and lifecycle persistence are not stubbed. Source HTTP
and output storage are controlled; the MM Asset used by the actual public
projection is in memory. This does not claim live MM persistence, public HTTP,
Redis, MinIO or HTTPS. CT-21 reuses the MM lane's controlled Processing HTTP and
in-memory object storage; it does not claim real Processing execution or MinIO.

Offline checks used the root virtual environment from this worktree:

```text
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/contracts/test_prepared_contracts.py
16 passed

env RUN_PROCESSING_TESTS=0 RUN_MEDIA_TESTS=0 RUN_INTEGRATION_TESTS=0 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --collect-only -q tests/contracts/test_prepared_contracts.py tests/integration/test_processing_worker.py tests/integration/test_media_persistence.py
61 tests collected; no fixtures executed

/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m ruff check scripts/dev/contracts.py tests/contracts/test_prepared_contracts.py tests/integration/test_processing_worker.py tests/integration/test_media_persistence.py
All checks passed

/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m ruff format --check scripts/dev/contracts.py tests/contracts/test_prepared_contracts.py tests/integration/test_processing_worker.py tests/integration/test_media_persistence.py
4 files already formatted

git diff --check
Passed
```

Every mapped function in the evidence JSON was checked by AST in this checkout.
Existing test basenames were reused, so no new collection collision was added.
Only the six authorized files are included in this correction commit. The supplied
untracked `integration-review.md` is unchanged and left untracked for the parent.

No containers were started and no live PostgreSQL/FFmpeg integration, browser,
GitHub, AWS/Alibaba operation or child agent was invoked. Parent fair scaling
owns shared Lima. After measurement, the parent must run both CT-20 parameters
and CT-21 using the existing migrated real-service lanes, then retain actual
results against the combined head. Until then their live status is **pending**.
