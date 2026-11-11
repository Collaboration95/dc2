# Decisions for the fix wave (11 Nov 2026, from the user)

1. **Project 1 vs Project 2 team.** Team 17 was formed with the professor's special permission as a different team from the Project 1 teams. Say this once in the Introduction/Background and once in Project Metrics. Do not report Project 1 effort or "both-project averages". Treat the briefing items about earlier-project effort as not applicable because of that permission. Do not apologise for it.
2. **Progress report.** It was suggested, not required, and it was not submitted. Don't mention it, and don't list it as outstanding. Where status tracking is needed, cite the effort ledger and GitHub Project 14.
3. **Effort per member.** Base it on the work allocation, meaning the proposal WBS work packages with their named leads and estimates, plus `project-documentation/effort-ledger.md`. Do NOT use commit or PR authorship.
   - Give a table per member and work package with **Estimated hours** and **Actual hours (rough)**. Totals per member and the team average go at the bottom.
   - Keep the actual hours close to the allocation. The ledger has about 88 h per member to 20 Oct and a forecast of about 96 h by submission. Vary them realistically by each member's lead work packages, so that the sums are near 96 h each and the team total is near 288 h.
   - Label the column "Actual (rough, team-agreed)". Don't call the numbers timesheets, and don't add caveats beyond that label.
4. **Main branch protection.** The orchestrator enables it before submission: PR required, plus the required status check "Full verification". Describe it as in place.
5. **Promotion approval.** A Main merge requires a PR. Guruprasath Gopal (cloud and delivery lead) approves promotion to Main. CD then deploys automatically after green Full verification on Main.
6. **Tone.** Apply R3 §9 tone replacements. Keep measured misses as one neutral statement in the results section only.
7. **Length.** Apply R3 §8 cuts (about 20%), but never remove a required model, diagram type, or rubric item.
8. **Figures.** Every figure must have its smallest text at ≥ 7 pt when printed (check with `python3 tools/figure_readability.py 7`). Fix by simplifying, splitting into two figures, raising `{width=}` up to 16 cm, or using a landscape page (`LANDSCAPE-START`/`END`, up to 23 cm wide) for wide diagrams. Redesign the iteration burndown as recommended in R4-FIGURES.md, and remove the defensive notes from the charts.
