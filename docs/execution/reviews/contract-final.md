VERDICT: PASS
SCOPE: Final CT evidence reconciliation and local V1/V2 execution evidence only
SOURCE: 422609b434102fd132b41c5bd9ab113d03984ed0
WORKTREE: work/contract-final

The reconciled map preserves all 25 case descriptions, inputs and expectations,
all 81 node references (62 distinct functions), the original findings, failed
reports and historical correction/checklist states. Schema version 2 makes the
current PASS fields explicit and places the original review metadata in
`historical_review`. The unchanged root `findings`, `run_only_checklist`,
`r3_correction` and `parent_reports` are listed as historical field paths.
Each case retains its historical evaluation; each test retains its earlier
execution/line and gains current source hash, AST line, layers and proof selector.
Historical REVISE and FAIL results remain historical REVISE and FAIL.

Current evidence:

- Full Mac verify: 1,083 fast Python, 152 frontend and 130 enabled real integration
  cases (44 legacy + 47 Processing + 39 Media); all five backend coverage gates
  and frontend gates pass. Quiet complete-module results are aggregate selected
  suite proof, not named verbose node/parameter output. `--require-integration`
  fails on skips; the actual owned environment enables PG/Redis/storage flags.
- Full E2E: PASS, 122.740s. Publisher registers/logs in, records 30 accepted plus
  one rejected file, polls status and retrieves output. Its intentionally damaged
  source remains failed after stored-source retry on Attempt 2 with the local
  input removed. Successful valid-source retry is proved separately by browser/V2.
- Browser: actual registration, logout and UI login (201/204/200), one upload,
  visible worker failure, zero-byte stored retry, selected native HLS and explicit
  MP4 decoded playback, owner deletion. Native HLS records three playlists/two
  segments, time 0 to 0.219818s and frames 4 to 9; MP4 records time 0 to 0.221848s
  and frames 0 to 9. Selected transport assertions distinguish decoding from
  merely receiving bytes. Child and supervisor worker restoration both pass.
- Complete V2: PASS, 190.602s. Worker failure visible in 69.195s <=300s; same-key
  retry creates one new Attempt and exactly one published primary. Real queue
  list loss preserves the RQ hash, repairs in 23.507s <=120s using the same
  Attempt, and completes. Actual Processing outage accepts durable pending work,
  Media restart/same-key replay preserves its Asset, and restored services
  converge. Previously submitted status returns 503 during the outage. All scoped
  restoration outcomes pass; no live daemon-failure restoration guarantee follows.
- R3 variants: both accepted source-invalid CT-20 crop/clip parameters are in the
  passing Processing module; CT-21 retained derived edit-key deletion/replay is
  in the passing Media module; CT-23 validates all eight prepared examples plus
  their negative variants in the passing fast suite. CT-20 has actual PG and
  FFmpeg source probing but controlled HTTP/output peers and an in-memory MM
  Asset projection. CT-21 has actual Media PG/handlers with controlled Processing
  and objects. These layers are not promoted to fully live service experiments.
- Original R1-R4 corrections retain integration-rereview PASS. The later, distinct
  final-code-review Media-readiness R1 is resolved by final-code-rereview PASS and
  the subsequent successful actual V2 run. Native-HLS observer rereview is PASS.
  Release active-work and scaling session-renewal rereviews are bounded code
  approvals; neither proves live V3/V4 acceptance.

Provenance:

The parent selected-original pack is
`/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/docs/execution/evidence/local-workflow-422609b/`.
All six indexed file hashes match. The map records the index, each selected
report and raw `.cache/execution/final-verify-2.log` / `final-recovery.log` with
SHA-256 and exact selectors. These parent-local inputs are read-only, several
uncommitted and absent from this worktree; this two-file commit does not package
or imply their tracked availability. Parent retention/import remains necessary
for a portable handoff.

Runtime build is `2cb8da833cb7f20b6f4fb41ff4b318f01530266b`; tested harness is
`422609b434102fd132b41c5bd9ab113d03984ed0`. The selected index records identical
Media, Processing, shared engine, Publisher, frontend, deployment, Compose and
lock inputs. Independent offline `git diff --exit-code` on exactly those paths
confirmed equality. This is source equivalence, not a claim that images were
built or relabelled at 422609b, and not an exact-image V4 scan certificate.

Tracked older Linux [run 38300284726](https://github.com/Collaboration95/dc2/actions/runs/38300284726)
remains evidence for branch head `c0a7315c44ce89c03c8adb7b51ab39a1aca569d9`, tested
synthetic merge `a9c14b925213fc5b3ff61d141be0bc74363144fc`; all five indexed hashes
match. It is not relabelled as current-head evidence.

Read-only authenticated `gh` queries now confirm [run 38303856295](https://github.com/Collaboration95/dc2/actions/runs/38303856295)
completed successfully for branch head 422609b, with 14 successful jobs. The Linux
browser job log identifies tested synthetic merge
`e1062bd8e5826848fa67c4aa95b6e40ecf92f4ac`, trusted/untrusted TLS PASS and E2E PASS
at `artifacts/ci-trust/e2e-20261012T202558-a5a46afe/result.json`. Full scope, both
CT-18 cases and HLS/MP4 decoded-event gates completed. New hosted raw artifacts
were not downloaded/packaged; no exact current Linux E2E duration is invented.
The successful SonarCloud job skipped its analysis step, so no completed Sonar
analysis is claimed. A wrong job-ID lookup returned 404 and was corrected using
the returned job identity; no test rerun or GitHub mutation occurred.

Validation and boundaries:

All 25 IDs/descriptions/inputs/expectations exactly match the unchanged prepared
contract-cases.json by ID; its SHA-256 is recorded and map order is preserved.
Offline AST checks resolve all 81 exact Python function references and refresh
current lines. Parameterized base nodes are preserved. All 15 historical report
paths exist and SHA-256 values match, including the failed combined CLI/browser
invocation and failed Firefox workflow. Static JSON/source-selection checks
confirm every mapped pytest module belongs to its stated successful suite and
every scenario selector exists in the selected original result. The map's
`acceptance.V1/V2` PASS means bounded local execution evidence, not Issue closure.

No VM, live service, build, browser or network test ran; no AWS/Alibaba action,
child agent or competing workload was invoked. GitHub access used only read-only
`gh` metadata/log queries. Only the two authorized documents are edited.

Main merge and exact Main checks are not claimed. V3's first full session-expiry
run remains FAIL; the corrected full run was not started at the supplied task
checkpoint. Parent V4 was running and is not assessed here. V5/parent metadata
and final evidence packaging remain pending. This review does not claim all
pre-AWS work complete or AWS readiness.
