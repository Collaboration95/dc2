# Appendices

## Glossary

| Term | Meaning |
|:-----|:--------|
| ACU | Aurora capacity unit; each Serverless v2 instance is configured for 0–2 ACU here. |
| ADR / AD-nn | Architecture decision record and identifier. `docs/architecture/decisions.md` retains AD-01–AD-29; Physical Architecture & Design adds the report analyses AD-30 and AD-31. |
| AISS-nn | Architectural issue identifier in Architectural Limitation. |
| Asset | Media-owned accepted video, identified by the public Media `job_id`; distinct from Processing's internal Job UUID. |
| Attempt | One numbered execution of a Job; a retry creates a new Attempt identity. |
| Bounded context | A boundary within which a domain vocabulary, model and rules apply: Media Management or Processing. |
| CD / CI | Continuous delivery / continuous integration. |
| `dc2-live` | The persistent V2-live demonstration environment's AWS stack name. |
| DLQ | Dead-letter queue; configured redrive follows five receives. |
| Inbox / outbox | Owner-local tables that deduplicate received messages / stage outgoing intent in the same transaction as domain changes. |
| Lease | A token and time-limited execution authority for the current Attempt, checked against the database clock. |
| OIDC | OpenID Connect; GitHub Actions uses it to assume an AWS role without a stored cloud key. |
| Projection | Media's local Processing read model, checked against source, identity, attempt and `state_version`. |
| Release (per owner) | Promotion of one service's immutable image through checked alias changes, owner smoke and restore; deployment adoption records the resulting worker definition. |
| SAST / DAST | Static application security testing / dynamic application security testing. |
| SCA | Software composition analysis: dependency vulnerability checks. |
| Seed / producer / consumer | The platform's owned video and Job / the submitting client or owner / the owner using the processed result. |
| V1 / V2-live | Historical per-run, booked-session proof stacks / the persistent environment introduced on 18 October (AD-27). |
| VersionId | The S3 object-version identifier pinned as part of an accepted source descriptor. |

## Use-Case Traceability Matrix

Use Case Model defines the seven goals. Their descriptions, normal/exception flows and
analysis/design diagrams are in Analysis and Design Models; the matrix provides the compact
route from each analysis/design owner to implementation and verification. Test names below are
selected assertions; the named suites contain the remaining cases.

| UC | Analysis/design owner | Section | Key code modules | Key tests |
|:---|:----------------------|:--------|:-----------------|:----------|
| UC-1 | Ibrahim Mammadov | Analysis and Design Models — UC-1 Register, log in and upload an owned video | `media/services/direct_intake.py`, `media/services/storage.py`, `media/messaging.py` | `tests/media/test_direct_intake.py::test_finalize_atomic_adoption_and_replay`; `tests/v1/test_direct_intake_s3.py::test_finalize_pins_the_exact_version_it_verified` |
| UC-2 | Ibrahim Mammadov | Analysis and Design Models — UC-2 Process the video into playable outputs | `processing/messaging.py`, `processing/lifecycle.py`, `processing/worker/tasks.py`, `media_engine/` | `tests/v1/test_messaging_sql.py::test_success_output_namespace_validation_and_atomic_terminal_result`; `tests/processing/test_worker.py::test_hls_failure_retains_primary` |
| UC-3 | Nguyễn Kim Long | Analysis and Design Models — UC-3 Track status and play the result | `media/projections.py`, `media/repositories/assets.py`, `media/api/v1_hls.py` | `tests/media/test_v1_projection.py::test_wrong_owner_source_job_and_output_rejected`; `test_local_status_hls_and_signed_range_capability` in the same suite |
| UC-4 | Ibrahim Mammadov | Analysis and Design Models — UC-4 Retry from the stored source | `media/services/v1_lifecycle.py`, `processing/messaging.py`, `processing/lifecycle.py` | `tests/media/test_v1_projection.py::test_retry_and_cancel_are_commands`; `tests/v1/test_messaging_sql.py::test_retry_idempotency_and_cancel_fence_old_and_current_attempts` |
| UC-5 | Nguyễn Kim Long | Analysis and Design Models — UC-5 Bulk-publish a folder and report results | `publisher/cli.py`, `publisher/client.py`, `publisher/state.py`, `docs/api/media.openapi.json` | `tests/publisher/test_publisher.py::test_cli_mixed_batch_keeps_every_file_outcome`; `test_module_entry_and_import_boundary` in the same suite |
| UC-6 | Guruprasath Gopal | Analysis and Design Models — UC-6 Scale processing capacity independently | `processing/launcher.py`, `processing/launcher_models.py`, `processing/launcher_trigger.py` | `tests/v1/test_launcher_sql.py::test_always_on_concurrent_wakes_never_exceed_the_cap_without_a_session_end`; `test_a_lost_runtask_response_is_resolved_by_token_without_a_second_launch` in the same suite |
| UC-7 | Guruprasath Gopal | Analysis and Design Models — UC-7 Release Processing on its own and demonstrate rollback | `scripts/aws/v1/release.py`, `scripts/aws/v1/deploy.py`, `scripts/aws/journal.py`, `scripts/ci/cd.sh` | `tests/aws/v1/test_v1_release.py::test_failed_candidate_restores_prior_aliases_without_schema_downgrade`; `tests/aws/v1/test_persistent_environment.py::test_owners_are_released_only_when_their_images_build_inputs_changed` |

## Supporting Assets

The UI frames come from retained presentation recordings documented as captured on
23 October 2026. The [asset register](assets/README.md) records each source clip, extraction
timecode and image size. The persona illustration represents the fictional planning personas.

| Asset | Purpose |
|:------|:--------|
| [Upload screen](assets/ui-upload.png) | Owner upload area and supported-file guidance. |
| [Accepted upload](assets/ui-processing.png) | Accepted file waiting for Processing. |
| [Library and playback](assets/ui-library-playback.png) | Completed owner library and inline playback. |
| [Publisher batch](assets/ui-publisher-batch.png) | Public-API batch status for three files. |
| [Foreign access refused](assets/ui-foreign-access-denied.png) | Cross-owner and anonymous access checks. |
| [Bounded capacity](assets/ui-bounded-capacity.png) | Finite Fargate encoder activity and queue counts. |
| [Planning personas](assets/conduct-persona-cast.png) | Maya, Arun, Jules and Sam, from left to right. |
