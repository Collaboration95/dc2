# Other Things to Be Highlighted

## What Team 17 Contributed beyond the Inherited Baseline

Project 2 did not add product features to FlickPond. It changed how FlickPond is **built,
deployed and reused**. The contribution, measured against the inherited baseline:

- **A domain-driven split** into two bounded contexts. Each has an aggregate with invariants
  enforced by constraints and code, its own database and roles, and its own image, IAM roles, CI
  lane and release unit (sections 3.1.3 and 3.1.4).
- **An asynchronous, failure-isolated integration**: outbox, SQS and inbox in both directions,
  version-fenced projections and SQL-driven repair. Media keeps working while Processing is
  unavailable (section 4.2).
- **A second client** built only against the published contract, proving reuse (section 4.4).
- **A cloud-native runtime that costs almost nothing idle.** No servers, no NAT, Aurora at 0 ACU,
  and encoders that exist only while there is work (section 3.2).
- **A delivery pipeline that releases one owner at a time from immutable, scanned images**, and
  restores itself on a failed smoke test (section 5).
- **An evidence discipline.** Every claim in this report links to a test, a CI run or a sanitized
  cloud receipt labelled with its environment and source. Misses and not-run items are kept.

## Lessons Learned

1. **Design for the transport you actually have.** The proposal assumed synchronous HTTP between
   the services. Once both ran as Lambdas with no private network, a transactional outbox and
   inbox became necessary, not optional. Adopting them early (AD-11) avoided a dual-write class of
   bugs.
2. **"Scale to zero" moves cost into latency.** Scale-to-zero made the platform cheap to keep
   running, which is why V2-live replaced booked sessions (AD-27). The same choice is the main
   cause of the 37-second queue-wait miss. Both effects are measured and reported.
3. **Idle is a behaviour that needs testing.** Aurora never paused at first, because cleanup
   rescans woke it every few minutes. #273 added activity markers and backoff, and a CloudWatch
   reading of 0 ACU confirmed it.
4. **Pipelines need tests too.** Two CD script bugs (#265, #267) and one workflow-startup error
   (#281) stopped deployments partway. All were fixed with tests and `actionlint`. Formatting once
   changed a released migration's bytes, so Media's release was held (#282); migrations are now
   excluded from formatting and guarded.
5. **At-least-once delivery means duplicates in practice.** A burst produced stale duplicate work
   messages that broke a smoke test (#270). The fix drains them, and the re-test still recorded
   18 sends for 9 jobs. The design tolerates duplicates; it does not pretend to remove them.
6. **Security gates must work in both time directions.** On 21 October a newly published advisory
   affected the *retained rollback* image, and the gate blocked the very release that remediated
   it. AD-28 keeps both scans and handles that case explicitly instead of weakening the gate
   (section 5.3).
7. **A fix can uncover the next defect.** Once the scan gate let the remediation through, the
   deploy smoke met a database that had paused since the last release, and login returned 503.
   The smoke now waits for a waking database for one call only, with every attempt recorded,
   instead of being retried wholesale.
8. **Keep misses visible.** Two-worker scaling (1.449× against 1.6×), Processing release time
   (10.1–10.3 min against 10 min) and queue wait (37 s against 20 s on the standard lane; 0.26 s on the Lambda short lane, with end-to-end latency still above 20 s) are reported as measured. The
   targets were not changed after the fact.

## Responsibilities for Use Cases and Design Problems

Each member led one specialism and reviewed the other two. For the presentation and assessment,
each use case and design problem has a responsible member who explains it and answers questions
on it. The allocation follows the team-agreed specialisms (effort ledger, PR #279).

| Member | Specialism | Use cases | Design problem (section 7.3) |
|:----------------|:--------------------------|:----------------|:----------------------------------------------|
| Guruprasath Gopal | Cloud and delivery: AWS, CI/CD | UC-6, UC-7 | DP-1 Bounded cloud capacity and safe per-owner release |
| Ibrahim Mammadov | Backend services: Processing and Media | UC-1, UC-2, UC-4 | DP-2 Durable asynchronous Processing handoff |
| Nguyễn Kim Long | Domain, contracts and verification | UC-3, UC-5 | DP-3 Trusted owner identity and reusable public contract |

## Evidence and How to Reproduce It

| Evidence | Location |
|:------------------------|:--------------------------------------------------------------|
| Architecture: ADR register, DDD model, views, use-case catalogue | `docs/architecture/decisions.md`, `ddd.md`, `views.md`, `use-case-design.md` |
| Results against targets (table, CSV, figure) | `docs/results/actual-vs-target.md`; regenerate with `python scripts/dev/results_summary.py` |
| Scenario-by-scenario evidence index | `docs/evidence-index.md` |
| Cloud receipts (sanitized) | `docs/execution/aws/v1/evidence/`, `docs/results/engineering-20261020/`, `docs/results/engineering-20261021/` |
| Release identity and freeze | `docs/release/demo-release-manifest.md`, `docs/release/engineering-handoff.md` |
| Runbooks | `docs/execution/aws/v1/deploy-runbook.md`, `dlq-runbook.md` |
| Study guide (public) | <https://collaboration95.github.io/dc2/> |
| Run locally | `make setup-v1`, `make v1-up V1_RUN_ID=demo1`, `make v1-demo V1_RUN_ID=demo1 OPEN=1` |
| Tests | `make lint`, `make format-check`, `make test`; frontend `cd frontend && npm ci && npm test` |
| Live environment (until teardown after 16 Nov 2026) | Frontend <https://d1e1dpefd6hp9x.cloudfront.net>; API `https://nqxf2hclhi.execute-api.ap-southeast-1.amazonaws.com` |
| This report's sources | `project-documentation/final-report/` (Markdown sources, figures, build script) |

## AI Tool Declaration

The team used AI coding and writing assistants (Anthropic Claude models through Claude Code, and
OpenAI GPT models for independent review) during the project:

- generating and refactoring code and tests under the team's direction;
- reviewing pull requests;
- drafting and proof-reading documentation, including this report;
- producing diagrams;
- running and recording verification steps.

Every result in this report comes from a retained test, CI run or cloud receipt, not from an AI
statement. The team is responsible for the content and the quality of the submitted work.
