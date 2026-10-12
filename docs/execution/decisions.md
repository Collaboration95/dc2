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

- Planning review R1: V5 may deliver an honest handoff after an assessed V3 blocker;
  full-scaling issue V3 and epic E5 stay open if fair capacity is unavailable.
- R2: retain the existing image scan policy on actual distinct live images and
  promoted digests; no new security infrastructure or features.
- R3: choose pinned Playwright Firefox, installed under the project, and scoped
  Certificates.Install CA policy. F3 must prove trusted navigation and an untrusted
  negative before this choice is accepted for end-to-end tests. The coordinator
  owns tooling/launcher and will revise within scope if this mechanism fails.
- R4: CLI returns authorised output access; the browser proves playback/deletion.
  Live batch acceptance is V1; C1 can merge against controlled public contracts.
- R5: coverage80% means combined statement/branch coverage, separately gated for
  live packages with unexecuted production files included. Branch rates are also
  reported. Legacy app and frontend gates stay intact.

- 2026-10-13 F3 runtime correction: Playwright Firefox155.0 did not apply the
  Certificates.Install policy during automation, including an explicit alternate
  policy path. Replace it with existing NSS certutil importing the local CA into
  each temporary project profile. The trusted HTTPS positive and unrelated-CA
  negative both pass with ignore_https_errors=false. No system trust modification.
- F3 capacity evidence: pinned Lima2.2.1 VZ VM boots8vCPU/8GiB under .local/lima;
  DockerDesktop remains unchanged. A container capped at2CPUs reports cgroup
  cpu.max=200000 100000. This proves resource/quota feasibility, not throughput.
