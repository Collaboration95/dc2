VERDICT: REVISE

BRANCH: `plan/local-delivery`
PR: #25 (draft; supplied by coordinator)
ISSUES: G1–V5 / #7–#24
REVIEW: Independent planning review, 13 October 2026. No implementation has begun.

The approach is viable. Keep the six epics, eighteen issues, grouped PRs, foundation-first order, three product lanes and frozen `media/` / `processing/` / optional pure `media_engine/` layout. The fixes below concern executable gates and acceptance; they require no new product features or security infrastructure.

ACCEPTANCE:

- [pass] The backlog has unique keys, valid dependencies and an acyclic DAG. Grouped PRs may build internal dependencies sequentially; requiring external dependencies Done avoids a merge-before-build deadlock. V1 waits for all product lanes; V2 follows V1.
- [pass] UC-1–7 and the persona outcomes are covered. The plan preserves the original scaling/recovery targets, inherited editor/operator behavior, separate database ownership, attempt fencing, source renewal and the 25 prepared contract cases.
- [pass] Worktree ownership and coordination are clear. Root packaging/Compose/CI have one owner; live runs are serialized on constrained resources. `app/` is a tested reference, not a third deployed service. No AWS, Alibaba, OIDC or additional product scope is needed.
- [fail] Resource-limited handoff, browser trust verification, live-image release checks and client acceptance need the specific corrections below.
- [pending] G2 requires a finding-to-fix disposition and re-review PASS. Project metadata population is not a content-planning defect.

FINDINGS — MUST FIX BEFORE PLANNING PASS:

1. **[P1] Make the resource-blocked handoff path executable.** Locations: `plan.md:185–191`, `issues/V3.md:11–14`, `issues/V5.md:12,21`, `issue-map.md` V3→V5, and corresponding backlog entries.

   The plan correctly says full scaling remains open if fair capacity is unavailable. However, V5 depends on V3 Done, while Done requires accepted evidence. The grouped final PR also requests closing keywords for every covered issue. This either blocks the required handoff indefinitely or encourages closing unproven scaling. V3's conditional runner/pilot wording does not identify which acceptance remains outstanding.

   **Exact fix:** Keep V3 and E5 open when full scaling is blocked. Define V5 prerequisites as V2/V4 complete plus an assessed V3 result: full evidence, or a reproducible runner/pilot and a documented capacity blocker. Remove V3→V5 as an unconditional native blocking edge and describe this conditional prerequisite consistently in the plan, backlog, issue contract and map. Permit the final PR to merge accepted scripts/handoff while using closing keywords only for satisfied issues. Handoff must distinguish completed local delivery from outstanding UC-6 acceptance. Assign the bounded project-local quota/capacity investigation to F3 so the feasibility decision occurs before the final evidence wave; no global Docker changes or AWS fallback.

2. **[P1] Carry the existing image scan gate onto the actual live artifacts.** Locations: `issues/F2.md:14`, `issues/V4.md:11–14`, `plan.md:159–165,173–183`; source: proposal §3.3–3.4.

   The inherited CI scans the root Dockerfile's legacy `app/` image. The new layout replaces that runtime, but no issue explicitly requires scanning Media and Processing/worker images or retaining the proposal's zero fixable HIGH/CRITICAL release gate. A green legacy scan could therefore satisfy the vague “required checks” wording while the released artifacts are unchecked.

   **Exact fix:** Add F2 acceptance that the existing Trivy gate covers every distinct live Media/Processing/worker image, with the inherited severity and fixable-finding policy preserved. Add V4 acceptance that the exact candidate artifact being promoted has passing build/test/scan evidence; scan failure blocks promotion. Identical API/worker image digests need only one scan. Address inherited fixable findings in this work; do not add an identity system, credential broker or broader security program.

3. **[P1] Prove the browser trust mechanism in foundation, before depending on it for integration.** Locations: `plan.md:120–126`, `issues/F3.md:12,20`, `issues/V1.md:13`; current frontend tooling is Vitest/jsdom.

   “Explicit trust settings for browser context” names no browser, trust mechanism or verification command. Supplying a CA to an HTTP client does not establish that the selected real browser accepts it. With both system trust changes and disabled verification excluded, leaving this discovery until V1 risks blocking every Secure-cookie and playback acceptance check.

   **Exact fix:** Record the selected real browser and project/profile-scoped CA trust mechanism in `decisions.md`; assign its pinned tooling and launcher to the coordinator. Add F3 acceptance for real-browser HTTPS navigation to an infrastructure endpoint using that trust mechanism with certificate verification enabled, plus the exact repeatable command. Cover the hostnames/SANs used by the public API and media URLs. Keep actual login/upload/playback/retry in V1. Do not use an insecure browser flag, a certificate-error bypass or jsdom as that evidence.

4. **[P2] Align V1 with the promised CLI surface and lane gates.** Locations: `issues/V1.md:11`, `issues/C1.md:11,19`, `plan.md:48–50`; source: proposal UC-3/UC-5 and persona acceptance.

   V1 currently requires the entire registration/upload/process/status/MP4/HLS/retry/delete sequence “through web and CLI.” C1 promises authorised playback access, not a CLI player or delete command. C1 also calls for a live mixed-success batch despite depending only on foundation. This makes scope and merge acceptance less precise than the plan's explicit parallel-client strategy.

   **Exact fix:** State separately that the browser proves playable MP4/HLS and owner deletion, while the CLI proves registration/login, mixed-success folder publishing, per-file outcomes, status, authorised output access and stored-source retry. Place the live CLI batch evidence in V1. Let C1's merge gate use controlled public-contract responses and import/credential checks; V1 validates the integrated result after both backend lanes. Do not add CLI playback or deletion features to resolve the wording.

5. **[P2] Define what the coverage gate actually measures.** Locations: `plan.md:113–118`, `issues/F2.md:13,19`; current `pyproject.toml` coverage settings and CI commands.

   `branch = true` with `fail_under = 80` enforces coverage.py's combined statement/branch percentage, not an independent 80% branch rate. The current root source selection is `app`; Processing has a separate CI measurement. Without a defined denominator and per-service gate, the proposed wording permits legacy coverage to mask new live-service gaps or an inaccurate branch-coverage claim.

   **Exact fix:** F2 must name the metric and enforce it separately for each live backend package, including unexecuted production files. Either retain an explicitly named combined statement/branch ≥80% gate and report branch rates separately, or implement the stated ≥80% branch-rate check from covered/total branches. Preserve the inherited regression gate and frontend's four ≥90% thresholds. Require product PRs to extend lint/coverage/CI package selection when `media/`, shared helpers and CLI arrive; passing legacy-only reports cannot satisfy their acceptance.

OPTIONAL — DOES NOT BLOCK PASS:

- **[P3] Promote the existing lease-supervisor requirements into P2/P3's checklists.** `plan.md:217–227` already requires supervision across download/encode/upload, process-group termination, fencing of stale failure as well as success, cancellation escaping HLS fallback, whole-attempt time budgeting and late-upload cleanup. Mirror these in issue verification with focused race/cancellation tests. This improves issue-by-issue review without adding scope; these global plan requirements already remain binding.

CHECKS:

- Parsed `backlog.json`: six epics, eighteen unique issue keys, all dependency references valid, no cycle.
- Authenticated `gh issue list` fresh read: all 24 epic/issue bodies matched local contracts; all were open. Coordinator subsequently supplied fresh verification of all Project 14 items and native relationships and publication of draft PR #25. No finding about unfinished metadata.
- Read the accepted `Team17-Proposal.docx`, personas/UC acceptance, all issue contracts, the three OpenAPI contracts' operations, all 25 CT cases, worklog and relevant existing CI/packaging/intake/frontend files. This was a planning review, not an implementation test run; no runtime or numeric target pass is claimed.

SCOPE: Only this review file was written. No code, other planning files or GitHub state were changed; no further agents or infrastructure operations were used. The review-work skill supplied the independent-review method (`/Users/speedpowermac/.codex/skills/review-work/SKILL.md`).

FOLLOW_UP: Parent applies the five must-fix changes consistently to the planning package and published issue contracts, records dispositions, then requests re-review. No additional feature epics are required.
