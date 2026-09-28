# Project 2 — working interpretation from the course documents

**Status:** planning reference, **not an approved proposal**. Project 1 is [`../../Media_player/`](../../Media_player/) (Flickpond). The user recalls the lecture suggesting that the current project could be extended into a microservices architecture. The three supplied documents do not explicitly mandate either that extension or microservices; the documented assignment is to deliver a cloud native **platform** with demonstrated scalability, automation, security, at least one working application, and supporting evidence. See [briefing-notes.md](briefing-notes.md), [report-template-notes.md](report-template-notes.md), and [presentation-notes.md](presentation-notes.md).

## Starting point: what Project 1 can contribute

Project 1's [README](../../Media_player/README.md) describes Flickpond as a video upload/processing system with a browser frontend and nginx, FastAPI, PostgreSQL, Redis/RQ, MinIO, FFmpeg workers, a reaper, authentication, and per user jobs. Its [proposal](../../Media_player/docs/proposal.md) describes a **modular monolith plus an asynchronous worker** and broader ambitions such as discovery and moderation. Its [contract](../../Media_player/docs/contract.md) documents the implemented/shared job states and API boundaries. Treat proposal features as intent until checked in code and a running build; do not claim they are delivered because they appear in a proposal.

This is a useful base for Project 2: upload/processing is already an end to end seed workflow, the worker can scale separately from HTTP handling, and code/tests/CI exist to build on. It is **not automatically a platform** in the course's sense. The Project 2 story still needs a business ecosystem, named participants, reusable capabilities, a demonstrator application, and evidence of their benefit.

## Suggested framing to discuss with the team/lecturer

**Candidate concept:** a reusable media processing platform that allows multiple producer applications or content teams to submit media work and multiple consumer applications to receive and play processed outputs. Flickpond can be the first application using the platform. A second thin client/integration or independently configurable workflow would provide stronger evidence of reuse than the existing UI alone. This is a proposal, not a course requirement or a claim about existing code.

Define these explicitly in the proposal:

| Platform question | Candidate Project 2 answer to validate |
| --- | --- |
| Business need | Small teams repeatedly build upload, media processing, storage, access and delivery plumbing. |
| Seed | A video asset and processing job, with stable identity and metadata. |
| Producers | The Flickpond UI and a second application/integration submitting assets or jobs. |
| Consumers | Playback clients, content portals, or other apps reading processing status and authorised outputs. |
| Reusable capabilities | Identity/tenant access, upload and storage, job orchestration, transformation, catalogue/metadata, playback delivery, observability. Choose a feasible subset. |
| New use case benefit | Show a new client using documented APIs without duplicating core processing; record effort and quality evidence. |

The proposed ecosystem terms must be refined with actual stakeholders and lecturer feedback. Avoid inventing tenants, billing or marketplace features unless they are needed for the chosen use case.

## Architecture decision to make, not assume

The course asks for logical and physical architecture, decisions, trade-offs, and measured quality attributes. A possible Project 2 path is to extract **one or two bounded services with an independently useful interface** from the current FastAPI code while keeping other modules together. Candidate boundaries are an asset/upload API, a processing/job service, and a delivery/catalogue API; an asynchronous worker already exists as a separate runtime but shares the application's repository/data contracts. Any extraction should define data ownership, API/event contracts, authentication between components, failure/retry/idempotency behavior, and deployability. A diagram with more boxes alone is not evidence of a service boundary.

Record an ADR comparing this path with retaining the modular monolith plus worker. Consider operational cost, cross service latency and failure modes, data consistency, team effort, maintainability, independent scaling, and the actual need for multiple consuming applications. Choose the smallest architecture that can make the platform and scalability claims credible in roughly 10 person days per member.

## Minimum evidence map

| Course expectation | Concrete evidence to plan |
| --- | --- |
| Working platform and at least one app | Running Flickpond workflow through the proposed platform boundary; show a second integration if reuse is claimed. |
| Scalability | Define load target and test setup, measure throughput/latency/queue depth with increased API or worker replicas; report the observed limit. |
| Cloud native design | Deploy diagram and running environment; explain selected managed/self hosted services and how they improve scaling/reliability. |
| Security | Auth/authz across exposed and internal APIs, storage access, secrets, transport, dependency/container checks, and verification results. |
| DevSecOps | Source strategy, scripted build/test/security checks, automated deployment and a recorded pipeline run. |
| Quality attributes | Scenarios and measured results for performance, availability/recovery, security, and extensibility/maintainability. |
| Design quality | Logical and physical views, ADRs, data ownership and persistence model, representative request/job lifecycle. |
| Project conduct | Proposal, WBS/effort, fortnightly progress, actual milestones/effort per person, open issues. |

## Decisions and information still needed

1. **Approval and team:** confirm with the lecturer that reusing Project 1 and the proposed platform framing are acceptable, and identify team number/members and presentation slot.
2. **Scope:** choose the business problem, producer/consumer roles, one core use case, and what is actually implemented versus only designed.
3. **Architecture:** decide whether service extraction adds a measurable benefit; document precise boundaries and ownership if chosen.
4. **Target and environment:** choose cloud provider/services, deployment budget, scale target, and performance test conditions.
5. **Evidence:** agree in advance which live demo and measurements will substantiate claims, and who records effort and results.

The source schedule is in [briefing-notes.md](briefing-notes.md) and [presentation-notes.md](presentation-notes.md). The final report should use the original DOCX template and explicitly separate delivered work from architecture or roadmap items.
