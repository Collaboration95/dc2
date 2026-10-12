# Client grouped validation

C1/C2 (#18/#19) now include the independent public-HTTP Publisher and stored-source
browser retry, with all three independent-review corrections applied.

Coordinator checks on the integrated client source:
- `make test`:827 offline Python tests and152 frontend tests pass.
- `make test-cli`:57 Publisher tests pass; the live TLS case is intentionally
  outside the network-free tier.
- Explicit real HTTPS/cookie test:1 passed, with its flag enabled and selected
  skips treated as failure. A dedicated CI job now requires this check.
- Publisher combined coverage98.43% (raw branches96.55%). Frontend statement/line
  coverage99.75%, branches96.00%, functions98.55%; all required thresholds pass.
- Fast-only package gates also pass for app, Processing, Media and media engine.
  Earlier real backend coverage remains reported separately; current CI will
  recollect all per-service fragments on this source rather than reuse stale data.
- `make publisher` displays the root-level CLI help. Independent wheel install
  and no-backend-import proof are retained in clients-implementation.md.
- Independent Sol xhigh rereview is PASS for R1/R2/R3 in clients-rereview.md:
  deferred replies cannot replace a newer active Asset, unresolved intent keys
  survive same-owner login, and state-write failures retain accepted per-file IDs.

Raw logs: `.cache/execution/clients-{focused,full-fast,tls,coverage-fast,
coverage-gate,frontend-coverage}.log` and `publisher-help.log`.
The integrated worktree also passed the30-good/1-rejected live CLI batch and
stored-source retry. Final V1 browser/CLI and V2 fault gates are separate; their
review-driven assertion/restoration corrections are being completed before
claiming full acceptance. HTML, CSS, icons and roadmap appearance are unchanged.
