# Security negatives on `dc2-live` (#229): results (2026-10-19 UTC)

`evidence security` run against the persistent environment `dc2-live` (always on, launcher-started
encoders) from a laptop, through the public CloudFront and API Gateway origins only. Redacted
receipt: [`cloud-proof-s229live.json`](cloud-proof-s229live.json). It merges three attempts of one
state directory because the two URL-expiry steps wait 15 minutes each and ran in parallel:

| Attempt | Steps | Note |
|---|---|---|
| `s229main` | all but expiry | `setup-job` **FAIL**: the harness tried to start its own encoder, which `Session.batch` refuses while the launcher owns worker starts. Tooling gap, fixed in this PR (`isolation.finish_job` now only observes encoders when the launcher owns them). The other steps of this attempt also passed. |
| `s229b` | all but `upload-url-expiry`; `cross-owner` and `oversize-100mib` rerun with `--fresh` | `cross-owner` first reran FAIL because my new Processing retry probe sent an invalid body (HTTP 422, validation, not the owner check); body fixed, rerun PASS. |
| `s229upl` | `upload-url-expiry` | needs no finished job, so it ran concurrently with the playback expiry |

## Results

| Check | Result | Evidence |
|---|---|---|
| Cross-owner (user B against user A's finished job) | **PASS** | B gets 404 on Media read, retry, edit, delete, HLS master, HLS segment, Processing read, Processing retry and Processing cancel. A's reads are 200 (control). B's job list and Processing-by-asset list do not contain A's job; A's job is `done` and unchanged afterwards. |
| Unauthenticated | **PASS** | 401 on all 16 route and origin combinations (CloudFront and execute-api: jobs, job, retry, playback, Processing job, reserve, finalize, `auth/me`). Forged `alg:none` token and a token with a changed signature: 403 (the Lambda authorizer rejects a cookie that is present). |
| Tampered upload grant | **PASS** | Signature changed 403, policy changed 403, key changed 403, content type changed 403, signature removed 400. Untouched grant 204 (control). |
| Tampered signed GET (HLS segment and MP4) | **PASS** | Signature changed 403, key changed 403, lifetime extended 403, unsigned 403, signature removed 400. Untouched URLs 206 (control). |
| Expired URLs | **PASS** | Media fixes both lifetimes at 15 minutes (900 s), so both were waited out (about 910 s). Signed GET: 206 before, 403 after. Upload grant: 204 before, 403 after. |
| Oversize | **PASS** | Reservation of limit plus one byte (104,857,601): 422, no grant. A PUT of 2 x the reserved size is rejected by S3 itself (400). The real 100 MiB plus one byte upload is rejected by S3 (400). Neither is adopted. |
| S3 direct access | **PASS** | Unsigned list, versions, GET and PUT on the source and output buckets are all 403. |
| External port scan | **PASS** | TCP connect over 12 ports on the 4 IPv4 addresses of the CloudFront hostname: only 80 and 443 open, the rest filtered; plain HTTP answers 301 to HTTPS. nmap is not installed; Python sockets were used. IPv6 not scanned. |
| API Gateway execute-api URL without CloudFront | **PASS (by design)** | Reachable on 443 only; `/health` 200, every protected route 401 without a session, so the authorizer is the control, and B still gets 404 on A's job through it. |
| Aurora not public | **PASS** | `describe-db-instances`: the single instance of `dc2-live-databasecluster` has `PubliclyAccessible=false`. |
| Security groups | **PASS** | No rule in any security group of the account's VPCs allows 0.0.0.0/0 or ::/0 ingress. The database group admits TCP 5432 only from the Lambda, Migration and Worker groups; those three have no ingress; the two `default` groups only self-reference. |

## Observations (not failures)

- The oversize finalize step answers HTTP 503 (not 202/4xx) when S3 refused the bytes, because
  the object is missing: Media reports "source storage unavailable" and does not adopt anything.
  A clearer 4xx would be nicer for clients but nothing is exposed.
- `all_401` in the unauthenticated step is `false` by design: forged cookies get the authorizer's
  403, absent sessions get 401 (`absent_session_all_401` is `true`).
- The throwaway users and their probe uploads stay on `dc2-live` (accounts are derived from the
  smoke secret and the run id; nothing was written down). The encoder for the one job ran 43.7 s
  billed.
