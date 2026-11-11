# Other Things to Be Highlighted

This section responds to the presentation feedback and collects the supporting models, design
decisions and team contributions:

- 6.1 Presentation Feedback and Response
- 6.2 Use Case Model
- 6.3 Analysis-to-Design Transition Strategies
- 6.4 Analysis and Design Models
- 6.5 Design Problems and Patterns
- 6.6 Member Contributions and Lessons Learned

## Presentation Feedback and Response

The table answers each written comment and recorded spoken remark from the presentation on
26 October 2026 (`project-documentation/presentation/feedback-20261026/FEEDBACK.md`). The
record does not name the spoken assessors. The last row is the team's own follow-up question
about where the Lambda-or-Fargate decision is made.

| Remark (assessor) | Response and evidence | Where in this report |
|:-----------------|:----------------------|:---------------------|
| Provide more architectural perspectives, including deployment (Boon Kui HENG, written). | The logical view gives responsibilities and interfaces (Figure {@fig:arch-logical}). The deployment view maps image artifacts to Lambda aliases, finite Fargate tasks, owned stores and network placement (Figure {@fig:arch-deployment-main}). | Logical Architecture & Design; Physical Architecture & Design |
| Provide detailed DDD diagrams with entities (Boon Kui HENG, written). | The domain models show Asset and Job roots, Attempt entities, immutable source values and independent identity and intake lifecycles (Figures {@fig:arch-context-map} and {@fig:arch-processing-job}). | Platform Design |
| Provide class and sequence diagrams at class/object level for critical use cases (Boon Kui HENG, written). | Every scoped use case has analysis and design class and sequence models. The upload and processing designs name the actual records, functions, transactions and exception paths (Figures {@fig:uc1-design-upload} and {@fig:uc2-design-execution}). | Analysis and Design Models: UC-1, UC-2 |
| Provide data schemas/models for the data stores (Boon Kui HENG, written). | Typed relational models and physical dictionaries give keys, nullability, defaults, checks and indexes. JSONB values, SQS envelopes and S3 object namespaces have their own schemas (Figures {@fig:data-media-main} and {@fig:data-processing-main}). | Persistence Design |
| Expand the detail behind slide 20; make the report more detailed (spoken assessor remark). | The report follows an upload from identity resolution through reservation, direct S3 upload, verification and SQL adoption to later publication (Figures {@fig:arch-intake-handoff} and {@fig:uc1-design-upload}). | Logical Architecture & Design; Analysis-to-Design Transition Strategies; Analysis and Design Models: UC-1 |
| Show the authorizer tied to API Gateway (spoken assessor remark). | Gateway invokes the Media-owned Lambda authorizer before the protected API. The adapter supplies trusted Actor context and Media revalidates the current user (Figures {@fig:arch-authorizer} and {@fig:dp3-solution-sequence}). | Logical Architecture & Design; DP-3 |
| Editing does not go directly to SQS (spoken assessor remark). | An edit commits its new Asset, verified source pin and submit outbox row in one Media transaction. MediaRepair publishes after that commit and Processing accepts through its own inbox transaction (Figures {@fig:arch-intake-handoff} and {@fig:dp2-solution-sequence}). | Logical Architecture & Design; Detailed Design; DP-2 |
| Explain grouping into bounded contexts and aggregates (spoken assessor remark). | Capabilities are grouped by vocabulary, invariants and local consistency. Account, intake and playback stay in Media; execution, leases and recovery belong to Processing (Figures {@fig:arch-context-map} and {@fig:arch-media-asset}). | Platform Design |
| Provide component-level detailed design (spoken assessor remark). | The component views show the real Media and Processing modules and adapters. The use-case and pattern sequences expand their collaborations, and unit tests cover the complex policy and orchestration modules (Figures {@fig:arch-media-components} and {@fig:arch-processing-components}). | Tiers and Layers; Detailed Design; Unit tests for complex classes and modules |
| Include database schemas and the data model (spoken assessor remark). | Each database has its own migration history, runtime and migrator roles, and model. Plain identifiers cross contexts; SQL constraints, version pins and lease fences protect local authority (Figures {@fig:data-media-support} and {@fig:data-processing-support}). | Persistence Design; Platform Design |
| The physical architecture lacks load balancing (spoken assessor remark). | AD-30 explains HTTP distribution through Gateway and Lambda, queue buffering with competing consumers, and SQL-reserved finite capacity. An ALB with an ECS HTTP service is the alternative it compares (Figure {@fig:arch-deployment-main}). | Physical Architecture & Design: Key Architectural Decisions; Performance |
| Consider NoSQL such as MongoDB (spoken assessor remark). | AD-31 compares PostgreSQL/JSONB with MongoDB and DynamoDB against owned reads, transactional inbox/outbox changes, uniqueness, leases and due-work queries. PostgreSQL keeps these rules; JSONB holds variable descriptors and S3 holds video bytes. | Physical Architecture & Design: Key Architectural Decisions, Technology and Services; Persistence Design |
| SAST and DAST were not visible in the pipeline (spoken assessor remark). | The scanner inventory lists the SAST (Ruff S rules, CodeQL), supply-chain (Trivy, pip-audit, Checkov) and DAST (authenticated local-stack OWASP ZAP) stages with scope, trigger and disposition (Figure {@fig:devops-ci}). | Security; Continuous Integration |
| Where is the Lambda-or-Fargate decision made? (team follow-up to the presentation Q&A). | The Processing transaction chooses the lane by size, feature flag and history, and the short executor re-checks duration and height after download. A refused short encode becomes a new standard-lane Attempt, and the launcher decides standard capacity separately (Figures {@fig:arch-dispatch} and {@fig:arch-probe-redirect}). | Physical Architecture & Design; Analysis and Design Models: UC-2, UC-6 |
