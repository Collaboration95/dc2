# Foundation coordinator results

13October2026. Scope F3 only; no AWS actions.

- Project-local Lima2.2.1 asset and Ubuntu26.04 image match the pinned SHA256s in
  local-capacity-options.md. codesign strict verification passed. VM startup needs
  no hostsudo, systemsettings, globalDockercontext or interactive approval.
- VM reports8CPUs,8296787968bytes memory andcgroupv2. `docker run --rm --cpus=2
  alpine:3.24 cat /sys/fs/cgroup/cpu.max` reports `200000 100000`.
- TLSgeneration creates project-local CA/serverkeys and localhost/127.0.0.1/::1
  SANs. Re-running preserves existing keys; OpenSSL verifies the server chain.
- Playwright1.63.0/Firefox155.0 installed under .local/playwright. Initial
  Certificates.Install trust attempts failed with SEC_ERROR_UNKNOWN_ISSUER.
  Existing NSScertutil now seeds the explicit CA into a temporary browser profile.
  `python scripts/dev/browser.py trust-smoke --run-id dc2` passes trusted HTTPS
  and rejects an unrelated CA, with ignore_https_errors=false. Evidence is in
  artifacts/dc2/browser-trust.json and browser-trust.png. No system trust changes.
- These are infrastructure results. Full media workflow/scaling are not claimed.

## Integrated root verification

After integrating tools commit5d5e275 and runtime commitb3c0a04:

- make setup, doctor-infra and lint passed from the root.
- Three combined fast runs each passed458Python and124frontend tests; Python
  command wall time was about2.7seconds and frontend1.3–1.8seconds.
- make up RUN_ID=local passed fresh root-scoped boot and full infrastructure smoke:
  HTTPS, frontend assets, Processing/DB, Redis, separate database roles, storage
  denials and actual signed source/output GETs. PublicURLhttps://localhost:54440.
- Real Firefox also navigated that running nginx /health endpoint, in addition to
  the trusted-positive/unrelated-CA-negative controls. Verification stayed enabled.
- make coverage with the selected run's explicit runtime credentials passed21real
  database tests and per-package gates: app86.77%, Processing86.69%. Frontend's
  four>=90%gates passed. No disabled integration was counted as accepted evidence.
- Fixed server certificate AKI/SKI extensions; systemPython3.14.7 strict HTTPS
  verification and realFirefox checks now pass. Initial failed attempt preserved
  in the lane report, rather than weakening TLS validation.
- Container Pythonbase is digest-pinned. Current app/Processing Dockerfiles now
  install hash-checked runtime dependencies exported from uv.lock; dev/browser
  dependencies are excluded from these live images. Processing build/smoke passed.
- Remote CI and independent grouped foundation review remain pending.
