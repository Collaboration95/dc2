# Advisory security evidence

`security-scans.yml` runs independently of CI's Full verification and CD. Findings are advisory;
installation failures, crashes, timeouts, missing/invalid reports, skipped dependency audits and
CloudFormation parsing errors fail the scanner job. It requests only `contents: read`, has no AWS
credentials or environment, and publishes JSON artifacts rather than uploading generated-template
locations to code scanning. No suppression baseline or dependency fix is applied.

- **Advisory security scans / Python runtime dependency SCA (advisory)**: pip-audit 2.10.1 scans the
  lockfile export of the v1-media, v1-processing and v1-worker extras union, excluding dev and the
  project itself. Markers are evaluated on the scanning runner. This union is not a per-image SBOM.
- **Advisory security scans / Static CloudFormation security (advisory)**: Checkov 3.4.3 scans the
  shared, separate and cloned/split renderings used by the existing offline linter, plus the OIDC
  template. Renderings are temporary; input bytes and per-input reports are retained as artifacts.
  Static findings do not establish deployed infrastructure compliance.

Each successful scan produces `execution.json` with source SHA, lock SHA-256, scanner version,
scanner exit statuses, counts and scope. Exported requirements and scanner stderr are retained.
The helper accepts exit 1 only when a valid report contains findings. Artifacts upload even if an
execution fails; an incomplete run does not receive a successful execution record or clean summary.

CI's **Lint and Python unit tests** publishes fast-suite JUnit counts, including failures and skips,
and retains JUnit on failure. **Combined backend package coverage** publishes existing `gate.json`
rates, package floors and native recovery goal results; it performs no additional measurement.
Missing evidence is labelled NOT_MEASURED. Malformed publication inputs are labelled NOT_EVALUATED.
Thresholds, coverage omits, test selection and measurement commands are unchanged.

DAST's existing **dast** job adds severity record/instance counts, scope and an advisory proposed
HIGH/CRITICAL verdict. ZAP has High/Medium/Low/Informational risks, with no Critical risk code. A scan
without executed disposition and successful runtime/private cleanup cannot receive a clean verdict.
The existing execution, route-coverage and cleanup gates remain authoritative.

## Local baseline, 10 November 2026

Tools installed only in `/private/tmp/dc2-report-scanners`; existing project dependencies reused.
Runtime/template inputs were from source base `a8c8072b667a039923563ac2612dedc7e7a54ce8`, lock SHA-256
`2e56db066041f1b1788380e812057ac37392ef4ebd3adeffd12f298cc1e829be`.

| Scanner / input | Actual local result |
|---|---|
| pip-audit runtime union | 40 applicable packages, 0 vulnerable packages, 0 findings |
| Checkov shared | 71 passed, 26 failed, 0 skipped checks |
| Checkov separate | 83 passed, 31 failed, 0 skipped checks |
| Checkov split | 82 passed, 31 failed, 0 skipped checks |
| Checkov OIDC | 15 passed, 1 failed, 0 skipped checks |

Checkov totals are check/resource occurrences across overlapping renderings, not unique
vulnerabilities. All four inputs parsed successfully. The committed insecure S3 fixture also raised
`CKV_AWS_21` (versioning) among six failures. These are local scanner receipts, not hosted CI,
AWS inspection or remediation evidence. Advisory databases and scanner rules can change results.

Reproduce from the checkout with an isolated pinned tool environment:

```sh
python -m scripts.ci.security_scans pip-audit /private/tmp/sca-reports --tool /path/to/pip-audit
AWS_EC2_METADATA_DISABLED=true python -m scripts.ci.security_scans checkov /private/tmp/iac-reports --tool /path/to/checkov
python -m unittest discover -s tests/ci -v
```
