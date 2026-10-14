# Integration correction record

Round1 independently reviewed assembled073a37a and returned REVISE for local
preparation (see coordinator retained review-r1.md). Actual AWS absence was not a
review defect. Coordinator corrections are additive to the three bundle commits.

| Finding | Correction and verification |
|---|---|
| F1 | Uniquely named AWS test modules. Normal make test:1411Python passed,2deselected;152frontend passed. No import-mode workaround. |
| F2 | Common observed quiescence proof, service/task writer stop before export, explicit monotonic-to-epoch conversion and proof-expiry ceiling. Detailed lifecycle tests pass. |
| F3 | Shared Environment/Role tags for state/generator and propagation to generator volumes. Renderer/action/tag regression passes; cfn-lint passes. |
| F4 | Exact state origin and X-DC2-Origin-Gate; private matched activation transform and observed digest gate before wake compute. Disabled/unmatched edge fails closed. |
| F5 | Own task-family version reads/launches, environment/Role-scoped generator terminate/delete. Required action/resource/tag regression passes. |
| F6 | Concrete loopback SQL/RQ observer, correlated finite-worker claim history and positive warm acknowledgment; namespace-specific intake guard, owner readiness/prior-image SQL compatibility, shared journal/ledger/public workflow, bounded private pg_dump/roles/files. Opt-in actual-service composition harness uses synthetic AWS inventory and synthetic artifact gate inputs, labeled explicitly; actual service checks are being finalized. |
| F7 | Explicit local-fixture HTTPS object origin/CA with approved bucket path and separate cookie jar. Physical loopback HTTPS positive/negative trust, unchanged signed query, range and auth-isolation regression passes; marked integration for the offline-fast guard. |
| F8 | Protocols import the Singapore-anchored shared calendar; early/late boundary tests pass. |
| F9 | Raw timestamps/window/warmup/booked deadline, elapsed consistency, full-client coverage and gap checks; actual bounded5s warmup then180s status and separate20-login window. Instantaneous/truncated/missing/reversed/nonfinite/out-of-window replay is ineligible. |
| F10 | Inspectable selected package/vulnerability and test-case reports retained; retained-byte digest/source/configID binding and secret/log removal checked. Exact Processing artifact gate executes1s encode/probe. Actual new amd64 build/Trivy/registry receipts remain separate gates. |

No AWS/profile/metadata/account/Alibaba action. No genuine IAM, Fargate, CloudFront,
cloud latency, cloud restore, zero-resource or bill PASS. Local controls and actual
local service observations remain distinct. Failures in coordinator local composition
logs are retained; no failed run is counted as a passing run.

The combined state will be published as one PR against work/aws2-prep-20261015,
preserving all three delegated source histories plus coordinator corrections.
Fresh independent round2 review and final composition/artifact receipts remain
required before merge or issue reconciliation. The umbrella PR70 remains against Main.

Round2 checked4b4eb9a and resolved F1–F5/F7–F10. Three remaining F6 seams:
R2-F1 concrete drain now freshly inventories stopped tasks/unresolved reservations
and returns the capacity consumer's typed receipt; a direct offline1/2/3capacity
composition plus missing-describe negative passes without video uploads.
R2-F2 readiness now uses the existing owning PostgreSQL role/DML/DDL/cross-database
probe, authenticated Redis ping and actual private peer/token/owner-header HTTP
probes from the selected API task network. Negative dependency checks fail closed.
R2-F3 one absolute deadline now enters API/object reads, multipart payload reads,
public poll terminal validation and all concrete smoke/capacity HTTP edges.
Slow terminal response and mid-upload expiry regressions reject late success.

Coordinator also corrected bounded local RQ timestamp skew and ZAP's writable
working directory, copied its pinned API policy to the private Java directory,
and retained normal Java roots before adding the namespace CA. A health-only
physical ZAP wrapper now executes and emits a report (exit2 means findings).
Authenticated runner scan is a separate CI receipt, not inferred from this probe.

One full coordinator local runR9 completed finite warm drain, both owners' actual
promotion/bad restoration and short encode/range/decode/delete, close/private export
and wake. It preceded the round2 adapter corrections; it is historical integration
proof, not final exact-source validation. The final corrected run and fresh round3
review remain required. Genuine AWS and restore evidence remain NOT_RUN.
