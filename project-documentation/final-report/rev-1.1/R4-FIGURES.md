# Figure visual QA — incomplete

**Reviewed: 5 OK, 3 FIX. Not reviewed: 89 of 97 images.** These counts are partial, not report-wide verdicts. Only the burndown and seven assets were visually opened; remaining entries are an inventory, not approvals. Top ten fixes cannot be established until visual inspection is complete.

## Observed fixes

1. `conduct-iteration-burndown.png`: replace five small panels with one continuous timeline of open task and epic counts, with lightly marked iteration boundaries and snapshot cutoff. Mark iteration 1 as no registered issues and iteration 5 as unchanged; retain the unobserved future only as a small shaded extension. Move timestamp and reopen-cycle limitation into caption or prose; use the recovered space for legible axes. Do not invent issue history or an ideal line.
2. `ui-library-playback.png`: crop/enlarge the library and choose a frame with visible playback controls. At 15 cm, 10–16 px labels in 1440 px correspond to approximately 3–5 pt before any further layout scaling.
3. `ui-publisher-batch.png`: the command is clipped at the right edge; wrap or shorten it in a replacement capture. The result rows remain visible.

## Inventory and verdicts

Dimensions are pixels. Width is the source setting; links have no in-document print width. Font estimates are approximate and depend on the final PDF scaling.

| File | Source / label / width | Pixels | Verdict |
|---|---|---:|---|
| `figures/actual-vs-target.png` | src/40-quality.md:6 / results / 15cm | 2000x860 | NOT REVIEWED |
| `figures/arch-artifacts.png` | src/32-physical.md:41 / link or unlabelled / no width (link) | 1478x1036 | NOT REVIEWED |
| `figures/arch-authorizer.png` | src/30-logical.md:85 / arch-authorizer / 15cm | 1224x1181 | NOT REVIEWED |
| `figures/arch-context-map.png` | src/30-logical.md:205 / arch-context-map / 15cm | 1247x487 | NOT REVIEWED |
| `figures/arch-delivery-ledgers.png` | src/30-logical.md:288 / link or unlabelled / no width (link) | 964x390 | NOT REVIEWED |
| `figures/arch-deployment-main.png` | src/32-physical.md:18 / arch-deployment-main / 15cm | 1274x1219 | NOT REVIEWED |
| `figures/arch-dispatch.png` | src/32-physical.md:172 / arch-dispatch / 15cm | 798x902 | NOT REVIEWED |
| `figures/arch-intake-handoff.png` | src/30-logical.md:105 / arch-intake-handoff / 15cm | 1025x1023 | NOT REVIEWED |
| `figures/arch-launcher-control.png` | src/30-logical.md:290 / link or unlabelled / no width (link) | 915x396 | NOT REVIEWED |
| `figures/arch-logical.png` | src/30-logical.md:60 / arch-logical / 15cm | 1412x815 | NOT REVIEWED |
| `figures/arch-media-asset.png` | src/30-logical.md:231 / arch-media-asset / 15cm | 1010x587 | NOT REVIEWED |
| `figures/arch-media-components.png` | src/30-logical.md:144 / arch-media-components / 23cm | 1830x1872 | NOT REVIEWED |
| `figures/arch-media-intake.png` | src/30-logical.md:233 / arch-media-intake / 15cm | 817x498 | NOT REVIEWED |
| `figures/arch-network.png` | src/32-physical.md:94 / link or unlabelled / no width (link) | 1616x836 | NOT REVIEWED |
| `figures/arch-probe-redirect.png` | src/32-physical.md:174 / arch-probe-redirect / 15cm | 885x830 | NOT REVIEWED |
| `figures/arch-processing-authority.png` | src/30-logical.md:272 / link or unlabelled / no width (link) | 1261x814 | NOT REVIEWED |
| `figures/arch-processing-components.png` | src/30-logical.md:146 / arch-processing-components / 23cm | 1427x604 | NOT REVIEWED |
| `figures/arch-processing-job.png` | src/30-logical.md:254 / arch-processing-job / 15cm | 1098x563 | NOT REVIEWED |
| `figures/arch-stores.png` | src/32-physical.md:76 / link or unlabelled / no width (link) | 1420x672 | NOT REVIEWED |
| `figures/arch-triggers.png` | src/32-physical.md:68 / link or unlabelled / no width (link) | 1332x609 | NOT REVIEWED |
| `figures/conduct-issue-reduction.png` | src/20-conduct.md:218 / conduct-issue-reduction / 15cm | 1900x855 | NOT REVIEWED |
| `figures/conduct-iteration-burndown.png` | src/20-conduct.md:202 / conduct-iteration-burndown / 15cm | 2090x2090 | FIX — panel 1 is empty, panel 5 flat, while a whole panel is occupied by explanatory notes; chart is inefficient at 15cm. |
| `figures/conduct-overall-issues.png` | src/20-conduct.md:200 / conduct-overall-issues / 15cm | 1900x1349 | NOT REVIEWED |
| `figures/cover-logo.png` | src/00-front.md:2 / link or unlabelled / 9cm | 1500x555 | NOT REVIEWED |
| `figures/data-delivery-schema.png` | src/34-persistence-detailed.md:25 / data-delivery-schema / 15cm | 637x403 | NOT REVIEWED |
| `figures/data-edit-relay.png` | src/34-persistence-detailed.md:356 / data-edit-relay / 15cm | 1093x1449 | NOT REVIEWED |
| `figures/data-edit-sequence.png` | src/34-persistence-detailed.md:354 / data-edit-sequence / 14cm | 797x1255 | NOT REVIEWED |
| `figures/data-media-main.png` | src/34-persistence-detailed.md:15 / data-media-main / 15cm | 817x1088 | NOT REVIEWED |
| `figures/data-media-support.png` | src/34-persistence-detailed.md:17 / data-media-support / 15cm | 1019x489 | NOT REVIEWED |
| `figures/data-processing-launcher.png` | src/34-persistence-detailed.md:23 / data-processing-launcher / 15cm | 617x585 | NOT REVIEWED |
| `figures/data-processing-main.png` | src/34-persistence-detailed.md:19 / data-processing-main / 15cm | 870x1030 | NOT REVIEWED |
| `figures/data-processing-support.png` | src/34-persistence-detailed.md:21 / data-processing-support / 15cm | 881x481 | NOT REVIEWED |
| `figures/devops-cd.png` | src/50-devops.md:128 / devops-cd / 15cm | 1053x893 | NOT REVIEWED |
| `figures/devops-ci.png` | src/50-devops.md:48 / devops-ci / 15cm | 996x916 | NOT REVIEWED |
| `figures/dp1-problem-class.png` | src/65-dp-guru.md:11 / dp1-problem-class / 15cm | 683x490 | NOT REVIEWED |
| `figures/dp1-problem-sequence.png` | src/65-dp-guru.md:13 / dp1-problem-sequence / 15cm | 695x833 | NOT REVIEWED |
| `figures/dp1-solution-class.png` | src/65-dp-guru.md:43 / dp1-solution-class / 15cm | 836x739 | NOT REVIEWED |
| `figures/dp1-solution-sequence.png` | src/65-dp-guru.md:45 / dp1-solution-sequence / 15cm | 833x1130 | NOT REVIEWED |
| `figures/dp2-problem-class.png` | src/66-dp-ibrahim.md:9 / dp2-problem-class / 15cm | 545x513 | NOT REVIEWED |
| `figures/dp2-problem-sequence.png` | src/66-dp-ibrahim.md:11 / dp2-problem-sequence / 15cm | 714x726 | NOT REVIEWED |
| `figures/dp2-solution-class.png` | src/66-dp-ibrahim.md:29 / dp2-solution-class / 15cm | 935x862 | NOT REVIEWED |
| `figures/dp2-solution-sequence.png` | src/66-dp-ibrahim.md:33 / dp2-solution-sequence / 15cm | 1116x1597 | NOT REVIEWED |
| `figures/dp3-contract-class.png` | src/67-dp-long.md:41 / dp3-contract-class / 15cm | 927x971 | NOT REVIEWED |
| `figures/dp3-problem-class.png` | src/67-dp-long.md:9 / dp3-problem-class / 15cm | 1377x978 | NOT REVIEWED |
| `figures/dp3-problem-sequence.png` | src/67-dp-long.md:11 / dp3-problem-sequence / 15cm | 1366x948 | NOT REVIEWED |
| `figures/dp3-solution-class.png` | src/67-dp-long.md:29 / dp3-solution-class / 15cm | 1344x810 | NOT REVIEWED |
| `figures/dp3-solution-sequence.png` | src/67-dp-long.md:33 / dp3-solution-sequence / 15cm | 1520x2184 | NOT REVIEWED |
| `figures/uc1-analysis-class.png` | src/62-ad-ibrahim.md:19 / uc1-analysis-class / 15cm | 479x648 | NOT REVIEWED |
| `figures/uc1-analysis-identity.png` | src/62-ad-ibrahim.md:25 / uc1-analysis-identity / 15cm | 732x922 | NOT REVIEWED |
| `figures/uc1-analysis-upload.png` | src/62-ad-ibrahim.md:27 / uc1-analysis-upload / 15cm | 783x1219 | NOT REVIEWED |
| `figures/uc1-design-class.png` | src/62-ad-ibrahim.md:33 / uc1-design-class / 15cm | 913x736 | NOT REVIEWED |
| `figures/uc1-design-identity.png` | src/62-ad-ibrahim.md:39 / uc1-design-identity / 15cm | 985x1176 | NOT REVIEWED |
| `figures/uc1-design-upload.png` | src/62-ad-ibrahim.md:41 / uc1-design-upload / 15cm | 994x1483 | NOT REVIEWED |
| `figures/uc2-analysis-class.png` | src/62-ad-ibrahim.md:63 / uc2-analysis-class / 15cm | 673x623 | NOT REVIEWED |
| `figures/uc2-analysis-sequence.png` | src/62-ad-ibrahim.md:69 / uc2-analysis-sequence / 15cm | 1040x1527 | NOT REVIEWED |
| `figures/uc2-design-class.png` | src/62-ad-ibrahim.md:75 / uc2-design-class / 15cm | 675x929 | NOT REVIEWED |
| `figures/uc2-design-exceptions.png` | src/62-ad-ibrahim.md:91 / uc2-design-exceptions / 15cm | 1034x1542 | NOT REVIEWED |
| `figures/uc2-design-execution.png` | src/62-ad-ibrahim.md:85 / uc2-design-execution / 15cm | 1054x1409 | NOT REVIEWED |
| `figures/uc2-design-intake.png` | src/62-ad-ibrahim.md:81 / uc2-design-intake / 15cm | 988x1521 | NOT REVIEWED |
| `figures/uc3-analysis-class.png` | src/63-ad-long.md:15 / uc3-analysis-class / 15cm | 859x1177 | NOT REVIEWED |
| `figures/uc3-analysis-exceptions.png` | src/63-ad-long.md:23 / uc3-analysis-exceptions / 15cm | 1359x1438 | NOT REVIEWED |
| `figures/uc3-analysis-read.png` | src/63-ad-long.md:21 / uc3-analysis-read / 15cm | 1336x1503 | NOT REVIEWED |
| `figures/uc3-design-class.png` | src/63-ad-long.md:29 / uc3-design-class / 15cm | 1348x960 | NOT REVIEWED |
| `figures/uc3-design-read.png` | src/63-ad-long.md:35 / uc3-design-read / 15cm | 1641x2208 | NOT REVIEWED |
| `figures/uc3-design-results.png` | src/63-ad-long.md:39 / uc3-design-results / 15cm | 1550x2175 | NOT REVIEWED |
| `figures/uc4-analysis-class.png` | src/62-ad-ibrahim.md:113 / uc4-analysis-class / 15cm | 594x811 | NOT REVIEWED |
| `figures/uc4-analysis-sequence.png` | src/62-ad-ibrahim.md:119 / uc4-analysis-sequence / 15cm | 884x1198 | NOT REVIEWED |
| `figures/uc4-design-class.png` | src/62-ad-ibrahim.md:125 / uc4-design-class / 15cm | 833x1077 | NOT REVIEWED |
| `figures/uc4-design-fences.png` | src/62-ad-ibrahim.md:135 / uc4-design-fences / 15cm | 800x948 | NOT REVIEWED |
| `figures/uc4-design-retry.png` | src/62-ad-ibrahim.md:131 / uc4-design-retry / 15cm | 646x904 | NOT REVIEWED |
| `figures/uc4-design-successor.png` | src/62-ad-ibrahim.md:133 / uc4-design-successor / 15cm | 778x1160 | NOT REVIEWED |
| `figures/uc5-analysis-class.png` | src/63-ad-long.md:59 / uc5-analysis-class / 15cm | 773x945 | NOT REVIEWED |
| `figures/uc5-analysis-exceptions.png` | src/63-ad-long.md:67 / uc5-analysis-exceptions / 15cm | 1156x1691 | NOT REVIEWED |
| `figures/uc5-analysis-publish.png` | src/63-ad-long.md:65 / uc5-analysis-publish / 15cm | 1417x1822 | NOT REVIEWED |
| `figures/uc5-design-class.png` | src/63-ad-long.md:73 / uc5-design-class / 15cm | 1184x958 | NOT REVIEWED |
| `figures/uc5-design-exceptions.png` | src/63-ad-long.md:83 / uc5-design-exceptions / 15cm | 1339x1638 | NOT REVIEWED |
| `figures/uc5-design-publish.png` | src/63-ad-long.md:79 / uc5-design-publish / 15cm | 1419x2030 | NOT REVIEWED |
| `figures/uc6-analysis-class.png` | src/64-ad-guru.md:15 / uc6-analysis-class / 15cm | 624x855 | NOT REVIEWED |
| `figures/uc6-analysis-normal.png` | src/64-ad-guru.md:21 / uc6-analysis-normal / 15cm | 995x1051 | NOT REVIEWED |
| `figures/uc6-analysis-recovery.png` | src/64-ad-guru.md:23 / uc6-analysis-recovery / 15cm | 954x1160 | NOT REVIEWED |
| `figures/uc6-design-class.png` | src/64-ad-guru.md:29 / uc6-design-class / 15cm | 809x719 | NOT REVIEWED |
| `figures/uc6-design-normal.png` | src/64-ad-guru.md:35 / uc6-design-normal / 15cm | 946x1267 | NOT REVIEWED |
| `figures/uc6-design-recovery.png` | src/64-ad-guru.md:39 / uc6-design-recovery / 15cm | 883x1228 | NOT REVIEWED |
| `figures/uc7-analysis-class.png` | src/64-ad-guru.md:68 / uc7-analysis-class / 15cm | 544x784 | NOT REVIEWED |
| `figures/uc7-analysis-normal.png` | src/64-ad-guru.md:74 / uc7-analysis-normal / 15cm | 869x948 | NOT REVIEWED |
| `figures/uc7-analysis-recovery.png` | src/64-ad-guru.md:76 / uc7-analysis-recovery / 15cm | 826x1195 | NOT REVIEWED |
| `figures/uc7-design-class.png` | src/64-ad-guru.md:82 / uc7-design-class / 15cm | 737x737 | NOT REVIEWED |
| `figures/uc7-design-normal.png` | src/64-ad-guru.md:88 / uc7-design-normal / 15cm | 974x1432 | NOT REVIEWED |
| `figures/uc7-design-recovery.png` | src/64-ad-guru.md:92 / uc7-design-recovery / 15cm | 1121x1741 | NOT REVIEWED |
| `figures/ucm-scope.png` | src/61-use-case-model.md:5 / ucm-scope / 15cm | 1016x1099 | NOT REVIEWED |
| `assets/conduct-persona-cast.png` | src/10-introduction.md:102 / link or unlabelled / no width (link); src/70-appendices.md:58 / link or unlabelled / no width (link) | 2172x724 | OK — four distinct personas visible; names require accompanying text. |
| `assets/ui-bounded-capacity.png` | src/10-introduction.md:192 / link or unlabelled / no width (link); src/70-appendices.md:57 / link or unlabelled / no width (link) | 1120x630 | OK — encoder and queue counts visible at native size; single still does not prove a configured limit. |
| `assets/ui-foreign-access-denied.png` | src/10-introduction.md:191 / link or unlabelled / no width (link); src/70-appendices.md:56 / link or unlabelled / no width (link) | 1440x810 | OK — owner B denial and anonymous 401 visible at native size. |
| `assets/ui-library-playback.png` | src/10-introduction.md:196 / conduct-ui-playback / 15cm; src/70-appendices.md:54 / link or unlabelled / no width (link) | 1440x810 | FIX — small screen labels and video subtitle are roughly 3–5 pt at 15cm, and playback controls are not visible in this still; crop/enlarge and use a frame showing playback. |
| `assets/ui-processing.png` | src/10-introduction.md:189 / link or unlabelled / no width (link); src/70-appendices.md:53 / link or unlabelled / no width (link) | 1440x810 | OK — accepted file and waiting-for-Processing banner visible; filename alone might imply active processing, but report link accurately says awaiting. |
| `assets/ui-publisher-batch.png` | src/10-introduction.md:190 / link or unlabelled / no width (link); src/70-appendices.md:55 / link or unlabelled / no width (link) | 1440x810 | FIX — command is cut off at the right edge. Capture a wrapped or shorter command; the three result rows are readable. |
| `assets/ui-upload.png` | src/10-introduction.md:189 / link or unlabelled / no width (link); src/70-appendices.md:52 / link or unlabelled / no width (link) | 1440x810 | OK — upload area and file guidance visible at native size. |

## PNGs in figures/ with no src reference

Candidates only: check other consumers and provenance before any deletion.

- `figures/architecture-before-after.png`
- `figures/aws-topology.png`
- `figures/ddd-01-context-map.png`
- `figures/ddd-context-map.png`
- `figures/deployment-pipeline.png`
- `figures/domain-model.png`
- `figures/platform-context.png`
- `figures/report-burnup.png`
- `figures/report-cicd.png`
- `figures/report-context-map.png`
- `figures/report-dp1-capacity-release.png`
- `figures/report-dp2-handoff.png`
- `figures/report-dp3-identity.png`
- `figures/report-logical.png`
- `figures/report-schedule.png`
- `figures/report-seq-encode.png`
- `figures/report-seq-intake.png`
- `figures/report-seq-play.png`
- `figures/report-use-cases.png`
- `figures/use-case-design-01-shared-analysis-class-model.png`
- `figures/use-case-design-02-common-implemented-design-class-model.png`
- `figures/use-case-design-03-analysis-sequence-uc-1-uc-3-core-workflow.png`
- `figures/use-case-design-04-analysis-sequence-uc-4-and-uc-5-retry-integration.png`
- `figures/use-case-design-05-analysis-sequence-uc-6-and-uc-7-operations.png`
- `figures/use-case-design-06-implemented-sequence-uc-1-uc-3-upload-process-and-play.png`
- `figures/use-case-design-07-implemented-sequence-uc-4-and-uc-5-publisher-stored-source-retry.png`
- `figures/use-case-design-08-implemented-sequence-uc-6-capacity-and-uc-7-release.png`
- `figures/views-er-media.png`
- `figures/views-er-processing.png`
- `figures/views-job-states.png`
- `figures/views-logical.png`
- `figures/views-physical.png`
- `figures/views-sequence.png`
