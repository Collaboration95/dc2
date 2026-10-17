# V1 execution handoff; V2 only after accepted V1

Source of intent: [the accepted architecture](../architecture-plan.md).

## Current status (updated 2026-10-18)

**Local V1 is implemented and verified on `dev/v1-integration`.** The seed import and
the three lanes landed through PRs #97-#106: both domain Lambda API applications behind
the Gateway contract, SQS delivery with durable SQL repair, direct-to-S3 intake, the finite
SQS Fargate encoder, bounded repair and late-output cleanup, the session and release
operators, reproducible images, the browser acceptance leg and the journaled deploy and
teardown pipeline. The Redis/RQ path is gone from V1.

**Cloud acceptance has run once; a second session is in progress.** Run `r1017b`
(ap-southeast-1, 17 October) produced redacted receipts that record PASS for #63 to #67:
[`evidence/cloud-proof-r1017b.json`](evidence/cloud-proof-r1017b.json) and the Media release leg
[`evidence/cloud-proof-r1017bmedia.json`](evidence/cloud-proof-r1017bmedia.json) (there, only #65 ran, and
`bad-candidate-restore` is NOT_RUN). Their own `not_proven` lists apply: Cost Explorer is an estimate,
latency came from an in-region generator, and fakes or CI are not AWS evidence. The stack is torn down
(one Aurora snapshot is retained). #45 and #63-#67 are closed and the `project2-v1` tag exists. Run
`r1018a` (#186: CD-workflow deploy, backlog scaling, independent release, demo recording, teardown) is
**in progress**; its receipts will be added under [`evidence/`](evidence/). Everything in "Run it"
below is local: real PostgreSQL 16, FFmpeg and Docker, but Moto for S3/SQS, an in-process API Gateway
bridge and an in-memory release transport.

The actual account, billing currency (USD), quotas, MFA state and the scoped cloud
authorization are recorded in [`account-receipt-20261017.md`](account-receipt-20261017.md);
it does not itself authorize or evidence any cloud run (it predates `r1017b`).

### Run it

```sh
make v1-up V1_RUN_ID=<unique-id>                                  # PostgreSQL + loopback Moto
make verify-v1 V1_RUN_ID=<unique-id> FLOW=all V1_BROWSER=1        # every flow plus the browser leg
make v1-down V1_RUN_ID=<unique-id> DELETE_DATA=1                  # remove only this namespace
```

`make test-v1` runs the offline contract tests with no services. A passing
`FLOW=all V1_BROWSER=1` records `complete_v1_acceptance: PASS` in the run's evidence
manifest; without the browser flag it stays `NOT_RUN`. `cloud_acceptance` is always
`NOT_RUN`.

### Where to read next

- [`local-runtime.md`](local-runtime.md): runtime commands, honest gates, CI tiers and what is emulated.
- [`contracts/README.md`](contracts/README.md): the executable gateway, identity and message contracts.
- [`deploy-runbook.md`](deploy-runbook.md): the first real deploy and teardown, written and verified offline only.
  Its "CD workflow" section covers `.github/workflows/cd.yml`, which runs the same commands from GitHub Actions over an OIDC role.
- [`../../../api/`](../../../api/): the generated OpenAPI documents of the Media and Processing public APIs.
- [`dlq-runbook.md`](dlq-runbook.md): inspect and redrive the three DLQs. Local redrive uses a
  manual fallback because Moto lacks the move-task API; native redrive evidence is separate.

### What remains

1. Done (17-18 October): cloud proof #45 and #63-#67 (run `r1017b`), epics closed, `project2-v1` tagged.
2. In progress: run `r1018a` (#186) and the evidence index (#189).
3. V2 experiments (#80, #93, #94, #68) start only after the tag. #93 and #94 were closed on 18 October (parked, listed as future work); #68 stays opt-in and off by default. Exception, by owner decision:
   the opt-in unattended launcher (#68) is developed in parallel and stays off by default; see
   [`../v2/unattended-launch.md`](../v2/unattended-launch.md) (cloud evidence NOT_RUN).
   The opt-in Lambda short-encode benchmark (#93) is likewise developed ahead of the tag, off by
   default; see [`../v2/lambda-short-encodes.md`](../v2/lambda-short-encodes.md) (cloud evidence
   NOT_RUN, merge decision pending).
   The opt-in database layout and pause/capacity experiment (#94, one Aurora cluster per domain)
   follows the same rule; see [`../v2/database-topology.md`](../v2/database-topology.md) (cloud
   evidence NOT_RUN, V1's single cluster stays the default).

---

## Historical planning checkpoint (2026-10-15)

Superseded by the status above. Everything from here down is the original plan as
published on 2026-10-15, kept unchanged for provenance: it described reviewed AWS2
preparation at `8d13194` with all V1 migrations pending. Its "next issue", "future
deliverable" and "needs implementation" statements are no longer current.

Source of intent: [the accepted architecture](../architecture-plan.md). Current code
is reviewed AWS2 preparation at `8d13194`; all Lambda/SQS/Aurora V1 migrations below
are pending. This publication preserves the baseline and updates the plan, not the
application runtime or AWS resources.

### Start here

**Then-next issue: #81 — aws3-v1-contracts (since implemented locally).**
Freeze route/identity/message contracts first. It is the only dependency-free
Ready V1 handoff. Account #45 can remain Blocked while local work progresses.

1. Merge the contract fixtures, then publish their stable interfaces to each lane.
2. Run the following three four-issue bundles in dependency order; the coordinator
   owns shared settings/contracts and merges compatible lane work.
3. Complete one coherent local workflow, then only later perform authorized cloud
   acceptance. Required cloud issues stay open Blocked until genuine receipts.
4. Preserve an immutable `project2-v1` tag after all required checks/acceptance pass;
   that version remains suitable for submission.

[Editable accepted V1 diagram](architecture.tldr). The [live tldraw board](https://www.tldraw.com/f/KnQQunnp-JvYCDGKVcCFN) has the same target on page 08; earlier pages are consultation history.

### Implementation bundles

#### Domain APIs and clients

- #[81](https://github.com/Collaboration95/dc2/issues/81) — Freeze gateway routes, trusted identity and message contracts. Depends on none.
- #[82](https://github.com/Collaboration95/dc2/issues/82) — Package Media Lambda with native credentials and owned SQL. Depends on #81.
- #[83](https://github.com/Collaboration95/dc2/issues/83) — Package Processing Lambda API and owned job lifecycle. Depends on #81.
- #[86](https://github.com/Collaboration95/dc2/issues/86) — Move browser and Publisher uploads directly to authorized S3. Depends on #81, #82.

#### Messaging and finite execution

- #[84](https://github.com/Collaboration95/dc2/issues/84) — Replace Redis/RQ delivery with SQS and durable SQL repair. Depends on #81.
- #[85](https://github.com/Collaboration95/dc2/issues/85) — Replace peer calls with commands, results and owned projections. Depends on #82, #83, #84.
- #[87](https://github.com/Collaboration95/dc2/issues/87) — Run finite SQS Fargate encoders and remove source callbacks. Depends on #84, #83.
- #[88](https://github.com/Collaboration95/dc2/issues/88) — Implement bounded Lambda repair and late-output cleanup. Depends on #85, #87.

#### Runtime, delivery and verification

- #[89](https://github.com/Collaboration95/dc2/issues/89) — Define managed Gateway/Lambda/SQS/Aurora infrastructure offline. Depends on #81.
- #[90](https://github.com/Collaboration95/dc2/issues/90) — Adapt independent releases, migrations and rollback to Lambda/Fargate. Depends on #82, #83, #87, #89.
- #[91](https://github.com/Collaboration95/dc2/issues/91) — Adapt session open/close, cost model and evidence protocols. Depends on #87, #88, #89, #90.
- #[92](https://github.com/Collaboration95/dc2/issues/92) — Verify the complete Redis-free workflow locally. Depends on #86, #85, #88, #90, #91.

These are future four-issue implementation assignments, not newly launched
agents. This publication uses one independent practical audit for the full packet.

### Existing epics and evidence

- #[41](https://github.com/Collaboration95/dc2/issues/41) — Visible domain APIs, ownership and S3 intake.
- #[42](https://github.com/Collaboration95/dc2/issues/42) — Managed runtime, session controls and budget.
- #[43](https://github.com/Collaboration95/dc2/issues/43) — Redis-free delivery, finite workers and independent releases.
- #[44](https://github.com/Collaboration95/dc2/issues/44) — Authentic acceptance and immutable submission baseline.

Real account/cloud acceptance: #45 and #63–#67 stay open Blocked. #46 is a
document/owner decision: the merged managed-HTTPS architecture replaces the old
public EC2 HTTP leg; close the decision after Main merge. Actual public TLS and
client traces remain #63/#66. Epics can have Ready offline children while their
full outcome is Blocked on live evidence.

Completed #47–#62 remain closed Done as AWS2 preparation. The frozen original
contracts live in [readiness/backlog.json](../readiness/backlog.json); legacy
[preparation](../prep/README.md) and [architecture](../architecture-plan-aws2-prep-20261015.md)
do not define the new V1 target. Original historical issues and measurements stay intact.

### V2 gate

- #[80](https://github.com/Collaboration95/dc2/issues/80) — optional experiments after accepted/tagged V1.
- #[93](https://github.com/Collaboration95/dc2/issues/93) — Benchmark bounded short encodes on Lambda.
- #[94](https://github.com/Collaboration95/dc2/issues/94) — Measure separate database clusters and pause behavior.
- #[68](https://github.com/Collaboration95/dc2/issues/68) — Optional unattended worker starts and further cost cuts.

All V2 work is Backlog with V1 acceptance as its prerequisite; none blocks V1.
#68 is intentionally reopened from its earlier not-planned closure into this
deferred lane. Choose one experiment, measure against the tag and retain/revert
the working V1 baseline. No additional business service or mixed executor pool
is assumed.

### Verification and cost

- Validate the packet offline: `python scripts/planning/validate_v1_plan.py`.
- Fresh remote captures can be checked with `--remote <issues.json> --project <items.json>`.
- Recalculate: `python docs/execution/aws/v1/calculate-costs.py`.
- [Backlog](backlog.json), [identity map](github-map.json), [cost inputs](cost-inputs.json),
  [forecast](cost-model.json), [public price provenance](price-sources.json).
- Existing `make lint`, `make test`, owner integration selections and `make verify-local`
  remain real baseline commands. New V1 runtime/verification entrypoints are deliverables
  of the implementation issues; they are not silently assumed to exist today.
- Keep emulator/fake, actual local service/encoding, hosted CI and genuine cloud
  evidence separately identified. Cloud runs (#63-#67) fill in
  [`job-inputs.template.json`](job-inputs.template.json) (V1 topology); the older
  `../job-inputs.template.json` is the legacy topology and must not be reused.

The approximately $200 ceiling uses USD as a worksheet assumption pending actual
billing currency. Native Lambda authorization, DB pooling/pause, VPC IPv6 routes,
SQS repair and direct intake still need implementation and authentic verification.
Time target: 48-hour local build; three elapsed agentic days baseline/five maximum.
Keep the inherited October window and 26 October rehearsal/presentation anchor.

### Publication and current status

GitHub Project [#14](https://github.com/users/Collaboration95/projects/14) is reused.
Workflow is authoritative; built-in Status is coarse Todo/In Progress/Done.
Use the `v1`/`v2` labels with existing fields; no redundant Project or recurring
iteration machinery is added. The identity map captures publication-time state,
including #46 Review → Done after Main merge. Read GitHub for later live status.

After verifying the Main merge, the publisher ticks only #46's final merge
acceptance checkbox, closes it as completed, and sets Workflow/Status to Done.
The map records the expected final body hash without claiming this happened.
Recheck fresh issue and Project captures with `--decision-merged`; omit that flag
before merge. All other implementation/evidence remains open at this boundary.

The user authorizes commit, authenticated gh publication and Main merge after audit
and checks. This does not authorize AWS/Alibaba operations, deployment or spending.
Do not mark new implementation/evidence complete merely because this plan merges.
