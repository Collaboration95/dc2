# Full scaling session expiry and correction

The first full invocation at integration `621c03a` failed at
2026-10-12T20:11:01Z (13 October 04:11 Singapore). Seven complete batches had
210 successful processing outcomes and no missing HLS. During r3-w1 upload
preparation, sequence 8 received HTTP401 after seven acknowledged Assets. The
owner login had been established approximately one hour earlier: its ordinary
session expired. This is a harness failure; the complete run is FAIL, not scaling
acceptance. Its partial submissions and completed batches remain intact under
`.worktrees/integration/artifacts/evidence/v3-scale/scaling-20261013T031058-11d974cf`.
The serial latency launcher correctly refused to start after the failure.

The runner now clears its previous cookie and logs in as the same owner at the
start of each scaling batch, before warmup/submission/timing. It verifies both the
login identity and actual authenticated session/cookie. There is no retry of a
failed upload and no change to application authentication, fixture, quotas,
encoders, target calculations or repeat order. Each observed batch is well within
the existing one-hour session lifetime. Authentication preparation is recorded
separately from measured makespan.

68 offline evidence tests pass, including renewal at all nine batch boundaries,
replacement of an expired cookie, and refusal of missing-cookie/wrong-owner/401
renewal. No password or cookie is recorded in evidence. Ruff passes.

The failed namespace is stopped with its data retained. A fresh, corrected full
nine-batch run is required; earlier completed batches are not spliced into a
successful result. No acceptance claim is made until that run finishes and all
original targets are assessed.
