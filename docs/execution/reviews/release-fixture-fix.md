# Active release fixture correction

First live V4 operation `9b9ab085006042daa747406479642366` was rejected before
promotion: its baseline artifact/scan/public smoke and candidate build/scan passed,
but the 30-second silent fixture completed before the active Attempt was captured.
Processing's own recorded timestamps were 20:30:22.590456Z to20:30:26.112661Z,
only3.522205 seconds. No candidate was applied; the prior image remained running.
The rejection and exact IDs remain in the run's release journal/history.

The recovery-role SQL diagnostic runs under its intentionally small CPU quota.
Its separate Python/asyncpg process missed that short processing window. Use a
60-second 720p fixture with AAC audio instead, matching the workload class that
already takes roughly24seconds under the two-CPU worker quota. Do not alter
service limits, slow the application, retry until timing happens to pass, or drop
the immediate-before-drain/current-Attempt checks. Ordinary one-second release
smoke remains unchanged. The source hash and declared geometry/duration are saved.
The active fixture still has a bounded30-second host generation command.

The updated regression requires the60-second video, audio input/AAC and absence
of `-an` for active evidence. Actual corrected live acceptance remains pending.
