# Active release fixture bounded rereview

VERDICT: PASS
ISSUE: Scoped fixture correction; acceptance supplied by the user and `release-fixture-fix.md`.
PR: `review/release-fixture`, commit `5d6c0cdba9789b555f3216b02e53a3c0852eb2fa`
BASE: `422609b434102fd132b41c5bd9ab113d03984ed0` (latest commit's parent)

This PASS covers offline argument validity, scope and regression preservation.
It does not certify actual fixture generation, worker duration or live V4 acceptance.

ACCEPTANCE:

- [pass] Use the representative active workload — `scripts/dev/release.py:1187`
  selects 60-second 1280x720/30 fps `testsrc2` only for `prepare_drain=True`.
  A second lavfi input supplies a 60-second 997 Hz/48 kHz sine wave.
  Each `-f lavfi` precedes its own `-i`; output options follow both inputs.
  Automatic stream selection has one video and one audio stream available.
  `-c:v libx264`, `-c:a aac`, `-b:a 128k`, `-shortest` and `yuv420p` are
  correctly scoped to the single MP4 output. Equal source durations are compatible
  with `-shortest`; no `-an` suppresses the active audio.
- [pass] Preserve ordinary smoke — evaluating the command-list AST for
  `prepare_drain=False` produced exactly the parent commit's argv and 10-second
  cap: one-second blue 160x90/10 fps video, `-an`, and no active-only preset.
- [pass] Keep bounded generation and evidence identity — active generation retains
  `ultrafast`, one encoding thread and the 30-second command cap. The journal
  retains the uploaded-byte SHA-256 and 1280x720 geometry, with declared duration
  updated to 60 seconds (`scripts/dev/release.py:1245`).
- [pass] Preserve acceptance guards — drain, release, evidence, terminal-outcome,
  injected-failure and command/deadline functions are AST-identical to the parent.
  The exact unfinished current Attempt must still be processing immediately before
  drain; nonempty before/after evidence and matching public terminal outcome remain
  required. The 600-second promotion limit, visible failure requirement, injected
  startup exit-42 proof and tested-image restoration remain intact. No quota,
  service configuration, sleep or retry-until-pass changes occur in this diff.
- [pass] Retain focused regression assertions — `tests/dev/test_release.py:1189`
  now requires declared/video duration 60, the sine input, AAC and absence of
  `-an`, while retaining the 30-second cap, original deadline, owned IDs and
  no-playback/no-delete checks during preparation. Existing finished-upload,
  current-Attempt, public-failure, no-artificial-wait and deadline tests are unchanged.

FINDINGS:

- None within the requested scope.

CHECKS:

- Read user guidance, worktree `AGENTS.md`, review-work skill,
  `docs/project2-worklog.txt` and `release-fixture-fix.md`.
- Inspected the complete latest-commit diff and necessary unchanged release/test
  context. Both Python files parse successfully.
- Read-only Python AST evaluation/comparison — PASS for active argv/input/output
  ordering, caps, exact ordinary-command preservation and unchanged guard functions.
  This evaluated argument expressions only; it did not import or run the release runner.
- `git diff --check HEAD^ HEAD` — PASS.
- Pytest and live fixture/runtime checks were not executed in this bounded review.

SCOPE:

- Executable changes are confined to the requested fixture and regression test.
  The commit also adds its correction note and an unrelated prior HLS review record;
  the latter introduces no executable change and was not independently rereviewed.
- Only this review document was written, uncommitted. No VM, Docker, FFmpeg,
  browser, network, AGENTS edits or GitHub mutations were performed.

FOLLOW_UP:

- Parent owns the corrected V4 run and must establish actual generation time,
  active capture, drain/public outcome, promotion within 600 seconds and injected
  failure/restoration evidence on corrected source. The previous rejected operation
  `9b9ab085006042daa747406479642366` remains a rejection; this review does not
  relabel its reported 3.522205-second worker run or claim corrected live success.
