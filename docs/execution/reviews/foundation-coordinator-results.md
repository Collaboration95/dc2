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
