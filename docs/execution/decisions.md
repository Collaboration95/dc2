# Execution decisions

- 2026-10-12: User authorizes autonomous local/GitHub implementation, reviews,
  grouped PRs, merges and issue/project upkeep through pre-AWS completion.
- Use GPT-6.1 Sol high implementers and xhigh planning review; isolated worktrees.
- Three elapsed agentic days is the target, five is the maximum. Retain80/20 scope.
- Six epics and eighteen issues cover planning, foundation, three implementation
  lanes and integrated evidence. No new product features are added.
- Preserve basic boundary/owner controls. No OIDC or security infrastructure work.
- Docker allocation2CPU/2GiB is an evidence constraint, not permission to claim
  a fair3×2vCPU scaling result. Evaluate project-scoped alternatives before deferring.
- All GitHub changes use authenticated gh. No GitHub connector or browser access.
- Backend lane interface freeze: `media/` is the new live Media Management
  package; `processing/` remains Processing; `media_engine/` contains only pure
  shared media helpers where useful. Legacy `app/` stays a regression reference,
  not a third live service. The final default stack exposes only the new Media API.
- Sidecar inspections retained the prepared attempt fencing, renewal, queue-loss
  and cancellation requirements, and identified image-tag/queue/bucket isolation
  and the obsolete jsdom live test as explicit acceptance work.
