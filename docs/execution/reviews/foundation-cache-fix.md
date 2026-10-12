# Foundation cache correction

The foundation initially received PASS and its functional checks passed. A late
review update added R1 while PR26 was merging: the browser job rebuilt MinIO
instead of persisting build layers. The coordinator reopened F2 (#10) and E1 (#2)
and held the product wave for a corrective PR. The earlier coordinator assessment
that the measured duration fit the budget was not a new user instruction.

The correction adds a dedicated BuildKit cache for browser storage builds, reads
the existing integration cache as a fallback, loads the pinned image, and lets
runtime startup reuse that verified image. The opt-in path requires its source
revision label to equal the pinned MinIO commit; an absent/mismatched image fails.
Default local image builds are unchanged.

Local validation:14runtime tests pass (including accepted/rejected cache identity),
full fast suite passes460Python+124frontend tests, lint and actionlint pass.
A normal local image build followed by DC2_USE_PREBUILT_MINIO=1 startup skips
source compilation and passes all infrastructure/storage/database/TLS smoke.
Persistent GitHub cache-hit evidence and independent re-review are pending.
