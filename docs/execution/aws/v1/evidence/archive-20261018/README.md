# Evidence archive, 18 October 2026 (#250)

Redacted receipts of the successful `r1019a` CD runs, the persistent-environment (V2-live) smoke and the
exact-source CI run, copied **unmodified** from their Actions artifacts before the 14-day retention
(expiry 1 November) removed them. A run URL stays readable after its artifact expires; these files
do not depend on it.

- Machine-readable index with SHA-256, bytes, run URL, source SHA, artifact name/ID, original expiry and
  limits per file: [`MANIFEST.json`](MANIFEST.json).
- Retrieved 18 October 2026, about 13:05 UTC, with authenticated `gh run download -n <artifact>`.
  Nothing was edited, so a file can be re-checked against the Actions artifact while it exists
  (`gh run download <run id> -n <artifact name>`) and against the hash with
  `shasum -a 256 <file>`.
- Public by construction: the workflows publish only the reduced `cd-out/public` files. A search of the
  archived files found no account IDs, ARNs, cookies, signed URLs or credentials. The private journals
  and environment state stay in the private S3 bucket and are not archived. This is a manual search,
  not a scanner result; the repository's gitleaks CI job runs on the pull request.
- Historical receipts are not touched: `r1017b`/`r1018b` stay one directory up, with their
  FAIL/NOT_RUN outcomes.

## Claim to receipt

| Claim | Kind | Receipt | Source SHA | Limits |
|---|---|---|---|---|
| `r1019a` per-run stack deployed and an upload-to-playback smoke passed | AWS | [`r1019a-deploy-39085599276/`](r1019a-deploy-39085599276/) | `0b491e1712a9e4423e7f53bc2c813191d25669e8` | One smoke clip, `seconds_to_terminal` 108.5; the receipt's own #63 roll-up is INCOMPLETE; #185, #196, #229 and #64 to #68 are NOT_RUN in this file |
| Processing release promoted, six aliases at version 2, post-release checks PASS, upload-to-playback smoke passed | AWS | [`r1019a-release-39087966647/`](r1019a-release-39087966647/) | `358d169d6b0d0fc0f1e5ce809ffc8f1ad02fc592` | The step durations (Release 9m39s, smoke 5m59s) come from the run's job record, not these files. No claim that the upload-smoked release took under 10 minutes |
| `r1019a` teardown, receipt `CLEAN` | AWS | [`r1019a-teardown-39089615147/`](r1019a-teardown-39089615147/) | `0b491e1712a9e4423e7f53bc2c813191d25669e8` | The receipt's journal shows `td-receipt` as `started` beside `td-receipt: done` in the step list; kept verbatim |
| Persistent environment `live` deployed from Main and an upload-to-playback smoke passed | AWS, V2-live | [`live-deploy-39105817431/`](live-deploy-39105817431/) | `d2070db68c6b3545881eb948046b8e57f47e078e` | Basic live evidence; not every #238 acceptance row; #229 security negatives NOT_RUN |
| Exact-source full CI selected every lane | CI policy | [`ci-39107762106/ci-policy.json`](ci-39107762106/ci-policy.json) | `d2070db68c6b3545881eb948046b8e57f47e078e` | Run 39107762106 (scheduled full verification). Policy only, not results |
| V1 images pass local packaging checks | Local image verification | [`ci-39107762106/local-images-d2070db68c6b.json`](ci-39107762106/local-images-d2070db68c6b.json) | same | Packaging, not a vulnerability scan; `aws: NOT_RUN` |
| V1 local flows and the browser leg | Local emulation (Moto, PostgreSQL 16, FFmpeg) | [`ci-39107762106/v1-local-manifest.json`](ci-39107762106/v1-local-manifest.json) | same | Not AWS evidence; the manifest lists what is emulated and not run |
| Original AWS scaling, release, security, isolation proofs | AWS, original | one directory up: `cloud-proof-r1017b*.json`, `cloud-proof-r1018b*.json`, `r1018b-results.md` | not recorded in the receipts | Include the historical FAIL results; see [`docs/evidence-index.md`](../../../../../evidence-index.md) |
| Scanner findings, coverage percentages | CI | **not archived here** | | Coverage data artifacts (7-day retention, expired by 25 October) and Trivy/DAST reports are not copied. The combined-coverage job and "Full verification" concluded success in run 39107762106; Sonar jobs were skipped (advisory); DAST findings are report-only. The coverage percentage for this run is not recorded in this archive (unverified) |

Run 39107762106 jobs concluded success except two skipped Sonar jobs and one skipped image-path job,
per `gh run view 39107762106`. Cancelled run
[39089045496](https://github.com/Collaboration95/dc2/actions/runs/39089045496) was the deliberate CD
bad-candidate test (`bad_candidate=true`, source `784318636b690aac6ca64f0f8817ae7a15b6cae7`); it was
cancelled in the `Release` step and has no result. Cancelled run 39087914927 (source `358d169`, 01:50 UTC,
shortly before the successful Processing release) also has no result; its purpose is unverified.

## Retention policy for future runs

Repository Actions artifact retention is capped at 90 days (`gh api
repos/Collaboration95/dc2/actions/permissions/artifact-and-log-retention` reported maximum 90 on 18
October). The small, final-claim artifacts now keep **60 days**, which covers the 16 November report
deadline and a review period after it:

| Workflow | Artifact | Was | Now |
|---|---|---|---|
| `cd.yml` | `cd-<operation>-<environment>-<run id>` (redacted results) | 14 | 60 |
| `ci.yml` | `python-coverage` (combined coverage gate), `container-scan-*` | 7, 14 | 60 |
| `v1.yml` | `v1-local-*`, `v1-images-*` | 14 | 60 |

Gate behaviour, artifact names and paths are unchanged. Left at their shorter retention on purpose:
per-lane `*-coverage-data` (inputs to the combined gate), failure-only artifacts, Sonar disposition files
and `browser-e2e-evidence` (a test pins its 7 days). A longer horizon does not replace archiving: new
critical receipts that must survive past 60 days should be copied into this folder the same way.
