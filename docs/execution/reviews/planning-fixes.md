# Planning review dispositions

All five must-fix findings from planning-review.md are addressed in plan.md,
backlog.json and the affected issue contracts; GitHub sync follows these files.

| Finding | Fix | Verification |
| --- | --- | --- |
| R1 resource/handoff deadlock | V5 depends on V2/V4 plus assessed V3; blocked V3/E5 stay open; close only accepted issues; F3 investigates capacity | DAG validation and native blocked-by22 removal from24 |
| R2 live-artifact scans | F2 covers all distinct live image digests; V4 gates exact promotion artifact | F2/V4 acceptance clauses |
| R3 browser trust uncertainty | Scoped Playwright Firefox install/profile and Certificates.Install CA policy; positive/negative real-browser proof inF3 | make browser-trust-smoke acceptance |
| R4 CLI scope/gate mismatch | Browser plays/deletes; CLI reports output access; live mixed batch moves toV1 | C1/V1 verification clauses |
| R5 ambiguous coverage | Separate combined coverage>=80% perlivepackage, branch-rate report, includeunexecutedfiles; legacy/frontendgates retained | F2 and globalteststrategy |
| Optional P3 lease detail | Added supervisor/cancellation/whole-attempt/late-upload clauses directly toP2/P3 | Per-issue acceptance |

No product feature or new security infrastructure was added. Re-review PASS recorded in planning-rereview.md.
