# AGENTS.md instructions

For all GitHub access, use the authenticated `gh` CLI exclusively; do not use GitHub connectors, APIs, or browser access.

## Project 2 working agreement

- Work from this repository root. The former `Media_player` submodule has been
  imported here; application code, frontend, tests and deployment files live here.
- Target three elapsed days of agentic implementation, with five days maximum.
  The proposal's 31 person-days is its effort allocation, not this coding schedule.
- Apply the 80/20 principle. Reuse the existing media engine and frontend. Focus on
  the two service boundaries, separate data ownership, web and CLI workflow,
  independent deployment, and measured scaling/recovery evidence.
- The user authorizes implementation choices and work across all inherited tracks.
  Project 1 ownership and PR-only rules in historical notes are not current gates.
- Keep basic login/ownership, private data stores and secrets out of Git. Do not add
  OIDC, a credential broker or elaborate security infrastructure for this demo.
- Preserve the roadmap site's design and illustrations. Only repair source links
  as necessary when code moves. Original course/proposal documents stay intact.
- Read `docs/project2-worklog.txt` for current decisions and implementation status.
- Do not operate the inherited Alibaba deployment. AWS provisioning still needs
  the actual project account and spending limit; local work can proceed.
