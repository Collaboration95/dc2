# FlickPond Project 2 Extension TLDR

Team 17 | 4 October 2026 | For review by Cert 1 project members

**The proposal:** Reuse FlickPond's upload, processing, status, and playback workflow. Separate media management from processing, demonstrate another client, and measure the resulting platform.

**Status:** Baseline capabilities come from code inspection. Project 2 extensions remain planned. New implementation and test results remain unconfirmed.

## What changes from Cert 1

| Area | Cert 1 baseline | Proposed Project 2 extension |
| --- | --- | --- |
| User workflow | Login, upload, asynchronous processing, status, and authorised playback exist. | Keep the core workflow working across the new service boundary. |
| Service structure | One application API, separate workers, and a recovery task share job models and persistence. Workers already support replicas. | Extract Processing behind an authenticated contract. Give it independent deployment and ownership of job records. |
| Data ownership | Accounts and jobs share a database. Jobs reference the users table. | Media Management owns accounts and source assets. Processing owns jobs, state changes, and outputs. Separate credentials enforce ownership. |
| Platform reuse | FlickPond is the existing application. | Add one small client that authenticates, uploads, checks status, and accesses a result through published APIs. |
| Security and delivery | Owner checks, TLS, containers, tests, CI, and scans exist. Deployment remains operator-driven. | Adapt controls across the boundary. Resolve setup and scan issues. Script versioned cloud deployment and an upload-to-playback check. |
| Recovery and evidence | Durable states, duplicate worker-claim protection, retry, and a recovery task exist. Historical load tests mainly read a completed video. | Check failures after extraction. Compare one worker with two workers. Record queue wait, throughput, failures, latency, and playback. |

Both services can share one PostgreSQL server if permissions isolate their records and migrations.

## Picture the extension

```text
Inherited: FlickPond -> One API -> Queue -> Workers
                       API and workers share job records

Planned:   FlickPond + small client -> Media Management -> Processing
                                      Media records       Jobs + queue + workers
```

Domain-driven design (DDD) will use media concepts and business rules to check the boundary before coding. Internal calls need authentication and trusted owner identity.

## What counts as the new contribution

The contribution is the service boundary, independent client, adapted controls, and fresh evidence. FFmpeg, editing, worker replicas, cloud hosting, and CI remain inherited capabilities.

The scope covers architecture and quality attributes, platform engineering, cloud design, and DevSecOps.

## Scope limits and open evidence

Use fresh demonstration data. Search, moderation workflows, product analytics, sharing, external videos, and editor UI work remain outside scope. AWS migration, direct uploads, Kubernetes, and autoscaling are not commitments.

**Pending decisions:** Final contracts, cloud environment and budget, internal authentication, recovery bounds, and numeric acceptance targets.

**Pending evidence:** Both client workflows, independent deployment, data isolation, worker capacity, recovery, security, and scripted cloud delivery.

Two workers do not guarantee twice the throughput. Worker recovery does not establish host resilience. The inherited recovery task does not resume an interrupted encode.

## What a Cert 1 member should check

1. Check whether the baseline description matches the implemented system.
2. Check whether source assets belong with Media Management and processing jobs belong with Processing.
3. Identify hidden dependencies in authentication, job repositories, storage, retry, and cleanup.
4. Check whether the proposed changes and experiments justify the scope without extra product features.

Shared persistence and identity logic create the main extraction risk. Prof Heng accepted reuse and the focused direction. He requires DDD and techniques from all three courses. Detailed mechanisms remain proposed.

For details, read the [report draft](project-2-report-draft.md) and [baseline and plan](project-2-baseline-and-plan.txt).
