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
- Current target: `docs/execution/aws/architecture-plan.md` and `v1/README.md`.
  Deliver a complete V1 first: API Gateway, two domain Lambda API applications,
  SQS instead of Redis/RQ, owned PostgreSQL/S3, one finite Fargate encoder backend.
  The current AWS2 code is a reviewed baseline; V1 migration is not yet implemented.
  V2 experiments follow accepted/tagged V1 and never block its completion.
- Target 48 continuous agent hours for local integration, three elapsed days as
  baseline and five maximum. Two calendar weeks include cloud proof and rehearsal.
  Group at least four implementation issues per agent; avoid redundant reviewers.
- Do not operate the inherited Alibaba deployment. The user supplied an approximate
  $200 planning envelope; actual account/billing currency and scoped live permission
  remain prerequisites. This plan-publication task authorizes commit/push/Main
  merge after audit/checks, not AWS account operations or deployment. Local work
  can proceed. Required real-AWS evidence stays open Blocked until obtained.
- Local VM resources: the project Lima VM defaults to 2 vCPU / 2 GiB (`make capacity-start`).
  The 8 / 8 profile is for scaling measurements only and needs `CAPACITY_ARGS=--benchmark`;
  never choose it for routine work, smoke checks or documentation. Every start takes an
  expiring lease (2 h by default; `--keep-alive` for a demo, 24 h at most). Stop the VM you
  started when the work ends (`make capacity-stop`), do not stop another task's unexpired
  lease, and never let `status` or a background task start it. `make capacity-reap` stops a
  VM whose lease lapsed. V1 verification (`make verify-v1`) needs no VM.
