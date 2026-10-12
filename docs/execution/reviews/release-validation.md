# Actual local independent release and rollback

Complete good/bad experiment PASS at source `331354d`, finished13October2026
Singapore. The full experiment took226.828s. Good promotion plus public smoke
completed in101.197s (target<=600s), including a real current Attempt captured
processing immediately before drain. Drain took34.077s and the job finished
successfully; its matching public outcome was checked and the test Asset deleted.

Both exact candidate images passed artifact imports/FFmpeg presence, source-bound
fast tests and Trivy0.75.0 scans with zero fixable HIGH/CRITICAL findings before
promotion. The injected bad API actually started and exited42 with its recorded
marker; its container/image/timestamps were captured before replacement. Automatic
rollback restored the exact tested good image, original worker count and public
workflow, kept Media API/recovery identities/images and media_db revision unchanged,
and cleared the pending intent. Processing migrations were independent; no downgrade
or Media migration was performed. The failed candidate remains a failed release;
the evaluated expected-failure experiment passes.

Rollback steps: recovery start0.732s, worker drain33.931s, apply15.078s,
public smoke2.036s and Media comparison0.534s. These step values are recorded
individually; they are not substituted for the complete operation duration.
Bad promotion plus automatic restoration took125.621s. Exact images, revisions,
active/terminal Attempt identities, scan hashes, command-output hashes and bounded
step timestamps are retained in the selected source pack:
[`../evidence/release-331354d/index.json`](../evidence/release-331354d/index.json).
The private original journal remains `.local/runs/final-local/releases/journal.json`.

Earlier live results remain separate: one preparation was rejected because a
silent30-second clip completed before capture; a later good promotion succeeded
but automatic rollback hit the15-second cold diagnostic bound. Manual recovery
then restored the good image. The corrected fixture and45-second diagnostic
allowance passed independent reviews; both original experiments remain failed.
No result was spliced or relabeled. Overall600/300-second bounds were unchanged.
All observations are local; no AWS or inherited Alibaba operation occurred.
