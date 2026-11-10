# R5 — External references for the 26 October 2026 assessor feedback

Verified on **26 October 2026**. Scope: NUS-ISS Graduate Certificate in Architecting Scalable Systems, SWE5001 practice project, and the feedback recorded in `../FEEDBACK.md`.

This is external research and suggested report content, not an implementation audit. The “good answer” guidance below is the researcher's synthesis of the sources and assessor feedback, not an invented marking rubric. Any statement about what FlickPond actually implements still needs evidence from Main commit `76282d3`, with the GitHub permalinks required by `FEEDBACK.md`. Proposed repairs must be labelled proposed. No application, infrastructure or workflow change is implied by this document.

**Verification method.** Every linked reference below was successfully opened and its relevant content inspected. Most were opened with the web tool. The four UML-Diagrams pages and the OMG normative PDF were successfully retrieved over HTTPS with `curl`/HTTP retrieval after web-tool failures; the PDF text was inspected in memory. All GitHub content was read exclusively through authenticated `gh api` calls to the repositories' README content endpoints; the links below use the returned `html_url`, including the Baseline Action's `master` branch. No failed URL is included. Public NUS-ISS pages establish advertised coverage, not the full classroom syllabus or assessment criteria. ISO's public catalogue establishes the standard's scope; its paid normative text was not inspected.

## Feedback map

| ID | Assessor feedback / question | What the report should make assessable |
| --- | --- | --- |
| F1 | More architectural perspectives, especially deployment; revisit Architecting Software Solutions | Separate concerns into named views, with consistent elements and explicit mappings between software and infrastructure. |
| F2 | How bounded contexts and aggregates are grouped; detailed DDD diagrams with entities; revisit Platform Engineering | Explain domain boundaries, context relationships, aggregate roots, entities, value objects and consistency rules. |
| F3 | Component-level detailed design; class/object-level class and sequence diagrams for one or two critical use cases; revisit SAD and SDP | Show internal responsibilities and actual collaborating objects, including methods, guards and failure paths. |
| F4 | Database schemas and data models | Show owned schemas, keys, constraints, relationships, access paths and transaction/event boundaries. |
| F5 | “Might as well use NoSQL like Mongo” | Compare relational, document and key-value models against the workload and consistency requirements. |
| F6 | Physical architecture does not explain load balancing | Distinguish HTTP request handling, admission control, queue load leveling, consumer concurrency and worker scaling. |
| F7 | Authorizer is tied to API Gateway; more detail | Identify the API and authorizer type, route attachment, validation and backend invocation boundary. |
| F8 | Editing does not go directly to SQS; who chooses Lambda or Fargate, and where? | Trace the complete command-to-job flow and identify the routing policy and the component that executes it. |
| F9 | SAST and DAST missing from the pipeline explanation | Locate distinct static and running-application checks, their coverage, gates and execution evidence. |

## Course anchors — what the public NUS-ISS pages actually say

| ID | Title and verified URL | Publisher | Relevant teaching / notation evidence | Supports |
| --- | --- | --- | --- | --- |
| C1 | [Graduate Certificate in Architecting Scalable Systems](https://www.iss.nus.edu.sg/stackable-certificate-programmes/graduate-certificate/smart-systems-platforms/graduate-certificate-in-architecting-scalable-systems) | NUS-ISS | The programme brings together Platform Engineering, Architecting Software Solutions and Cloud Native Solution Design, providing the programme context for the assessor's architecture and platform references. | F1, F2, F6, F8 |
| C2 | [Architecting Software Solutions](https://www.iss.nus.edu.sg/executive-education/course/detail/architecting-software--solutions) | NUS-ISS | The advertised outcomes explicitly include describing architecture through views and viewpoints, quality-attribute tradeoffs, threat modelling and capacity planning, while UML and object-oriented design are prerequisites. | F1, F6, F7 |
| C3 | [Platform Engineering](https://www.iss.nus.edu.sg/executive-education/course/detail/platform--engineering/software-systems) | NUS-ISS | The syllabus includes domain analysis for reusable assets, API design, microservices/API Gateway, event-driven models and platform data management, but does not publicly name a particular DDD diagram notation. | F2, F4, F7, F8 |
| C4 | [Software Analysis & Design](https://www.iss.nus.edu.sg/executive-education/course/detail/object--oriented-analysis-design/software-systems) | NUS-ISS | The course explicitly covers UML diagramming, use cases/user stories, identifying objects and responsibilities, distributed-system/persistence design and mapping OO design to implementation. | F3, F4 |
| C5 | [Software Design Patterns](https://www.iss.nus.edu.sg/executive-education/course/detail/software-design-patterns/software-systems) | NUS-ISS | The course teaches appropriate application and implementation of Gang of Four patterns and explicitly requires familiarity with OO modelling using class and sequence diagrams. | F3 |

**Interpretation for the report.** The public pages support views/viewpoints for F1 and UML/OO design for F3. C3 supports the platform/domain/data connection, while the explicit expectation for detailed DDD diagrams comes from the assessor's feedback. Do not claim that the public course descriptions mandate Kruchten, C4, arc42, Crow's Foot notation, or any specific DDD canvas. SAD and SDP are presented under Designing Modern Software Systems; the assessor is drawing on those earlier design skills, not asserting that all four courses belong to this GradCert.

## F1 — Architectural perspectives and deployment

### View frameworks and quality perspectives

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| V1 | [Architectural Blueprints: The “4+1” View Model of Software Architecture](https://arxiv.org/pdf/2006.04975) | Philippe Kruchten; author's arXiv copy of the IEEE Software paper | The model separates logical, process, development and physical views and uses scenarios to connect and validate them for different stakeholder concerns. | F1; F3 and F8 scenario selection |
| V2 | [ISO/IEC/IEEE 42010:2022 — Software, systems and enterprise — Architecture description](https://www.iso.org/standard/74393.html) | ISO / IEC / IEEE | The public scope defines requirements for architecture descriptions, viewpoints and model kinds without prescribing a single diagram set or architecture method. | F1 |
| V3 | [Viewpoints](https://www.viewpoints-and-perspectives.info/home/viewpoints/) | Nick Rozanski and Eóin Woods, Software Systems Architecture companion site | A viewpoint supplies conventions for a view addressing particular concerns, and separate functional, information, concurrency, development, deployment and operational viewpoints avoid an overloaded single diagram. | F1; F4 and F6 |
| V4 | [Perspectives](https://www.viewpoints-and-perspectives.info/home/perspectives/) | Nick Rozanski and Eóin Woods, Software Systems Architecture companion site | Quality concerns such as security cut across several views, so perspectives guide consistent treatment of those concerns throughout the architecture description. | F1; F6, F7 and F9 |

### Concrete diagram sets and deployment notation

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| V5 | [The C4 model for visualising software architecture](https://c4model.com/) | Simon Brown / C4 model | C4 supplies context, container, component and code abstractions plus supporting dynamic and deployment diagrams to explain a system at different levels. | F1, F3 |
| V6 | [Deployment diagram](https://c4model.com/diagrams/deployment) | Simon Brown / C4 model | Deployment diagrams map instances of systems or containers onto nested deployment nodes in a named environment and can include infrastructure nodes such as load balancers. | F1, F6 |
| V7 | [arc42 section 7 — Deployment view](https://docs.arc42.org/section-7/) | arc42, Gernot Starke and contributors | The deployment view describes technical infrastructure, communication topology and the mapping of software building blocks to that infrastructure, with justification and relevant quality characteristics. | F1, F6, F8 |
| V8 | [UML Deployment Diagrams](https://www.uml-diagrams.org/deployment-diagrams.html) | Kirill Fakhroutdinov / UML-Diagrams.org; explanatory guide | UML deployment notation distinguishes nodes, devices, execution environments, artifacts, deployment relationships and communication paths, including artifacts that manifest components. | F1, F6 |

**What a good answer looks like.** Provide a small, connected set of views: context/container overview; internal building blocks; deployment; and selected runtime scenarios. Give each a title, scope, environment, legend, stakeholder question and source evidence. Explain the relationship between views rather than combining AWS icons, classes, database entities and message timing on one canvas. Use the same names across diagrams.

The deployment view should identify the actual hosting and managed-service boundaries, relevant network/security boundaries, deployed software units, stores, queues and communication paths. Explain which service scales each workload, where concurrency is constrained, and where routing decisions happen. Use an AWS/C4 deployment drawing with a clear legend or a UML deployment drawing with correct node/artifact semantics. Neither C4 nor a “4+1” label alone satisfies the request for object-level detailed design.

## F2 — Bounded contexts, aggregates, entities and value objects

### Strategic design: domain boundaries and context relationships

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| D1 | [Domain-Driven Design Reference: Definitions and Pattern Summaries](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf) | Eric Evans / Domain Language | Evans defines bounded contexts, context maps, entities, value objects and aggregates, connecting model boundaries and integration relationships to domain consistency. | F2; F3 and F4 |
| D2 | [Bounded Context](https://martinfowler.com/bliki/BoundedContext.html) | Martin Fowler | A large domain model is divided into explicitly related bounded contexts whose terminology and models can differ across their boundaries. | F2 |
| D3 | [Use domain analysis to model microservices](https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis) | Microsoft Learn / Azure Architecture Center | The guidance proceeds from business-domain analysis to bounded contexts, then tactical entities/aggregates/services and finally candidate microservice boundaries. | F2 |
| D4 | [Context Mapping](https://github.com/ddd-crew/context-mapping/blob/main/README.md) | DDD Crew | The context-mapping guide describes upstream/downstream relationships and patterns such as Open Host Service, Published Language and Anti-Corruption Layer, with a practical visual cheat sheet. | F2 |

**What a good answer looks like.** Show a context map with the business capability and vocabulary of each context, who owns each model and data, and the APIs/events that connect them. Label upstream/downstream roles and any context-mapping pattern only where evidence supports it. Explain why a boundary follows domain meaning, business rules or change ownership. A service name, shared noun or database table by itself does not establish a bounded context. Distinguish the domain boundary from its present deployment mapping.

### Aggregate boundaries and collaboration

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| D5 | [Effective Aggregate Design, Part I: Modeling a Single Aggregate](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_1.pdf) | Vaughn Vernon / DDD Community | Aggregate boundaries should protect business invariants and transactional consistency rather than collect every object reachable through a relationship. | F2, F4 |
| D6 | [Effective Aggregate Design, Part II: Making Aggregates Work Together](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_2.pdf) | Vaughn Vernon / DDD Community | Separate aggregates can reference one another by identity and collaborate through eventual consistency without becoming one large consistency boundary. | F2, F4, F8 |
| D7 | [Effective Aggregate Design, Part III: Gaining Insight Through Discovery](https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_3.pdf) | Vaughn Vernon / DDD Community | Iterating on aggregate size, business rules and concurrency exposes mistaken object clustering and improves the domain model. | F2 |
| D8 | [DDD Aggregate](https://martinfowler.com/bliki/DDD_Aggregate.html) | Martin Fowler | An aggregate groups domain objects as a unit, with its root serving as the reference point and transaction boundaries normally aligned to aggregates. | F2, F4 |

### Entity/value-object detail and a reviewable design canvas

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| D9 | [Design a microservice domain model](https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/microservice-domain-model) | Microsoft Learn / .NET Architecture | The guidance distinguishes identity-bearing entities, identity-free value objects and aggregate roots, while keeping domain behaviour and invariants inside the model. | F2, F3 |
| D10 | [The Aggregate Design Canvas](https://github.com/ddd-crew/aggregate-design-canvas/blob/main/README.md) | DDD Crew | The canvas makes aggregate state transitions, enforced invariants, corrective policies, commands, events, throughput and size explicit for design review. | F2; F4 and F8 |

**What a good answer looks like.** Within each selected context, draw an aggregate boundary around a named root and its internal entities/value objects. Include identities, key attributes, meaningful behaviour, multiplicities and external references by ID. Add a short table for each aggregate: invariant, command, state transition, emitted event and transaction boundary. Explain what must be immediately consistent and what can become consistent later. Use a composition diamond only for the appropriate UML lifecycle/ownership meaning; it does not establish a DDD aggregate by itself. An ERD and a DDD domain model answer different questions and both may be needed.

These are modelling criteria, not a recommendation to introduce new domain classes into the application during this documentation pass. If the current implementation is procedural or uses persistence records directly, distinguish its actual structure from the proposed richer domain model.

## F3 — Component design, then class/object-level design for critical use cases

### Component responsibilities and internal structure

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| S1 | [OMG Unified Modeling Language, Version 2.5.1 — normative specification](https://www.omg.org/spec/UML/2.5.1/PDF) | Object Management Group | The normative specification defines the semantics and notation for classes/components, interactions and deployments, including the distinctions between structural elements and their runtime instances. | F1, F2, F3 |
| S2 | [UML Component Diagrams](https://www.uml-diagrams.org/component-diagrams.html) | Kirill Fakhroutdinov / UML-Diagrams.org; explanatory guide | Component notation represents responsibilities through components, provided/required interfaces, ports, connectors and dependencies. | F3 |
| S3 | [Component diagram](https://c4model.com/diagrams/component) | Simon Brown / C4 model | A C4 component diagram decomposes one container into internal components and explains their responsibilities and implementation details. | F3 |
| S4 | [arc42 section 5 — Building block view](https://docs.arc42.org/section-5/) | arc42, Gernot Starke and contributors | The building-block view documents hierarchical static decomposition, responsibilities, interfaces and dependencies, allowing important internals to be expanded as white boxes. | F3 |

### Classes, objects and interaction sequences

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| S5 | [UML Class and Object Diagrams Overview](https://www.uml-diagrams.org/class-diagrams-overview.html) | Kirill Fakhroutdinov / UML-Diagrams.org; explanatory guide | Class diagrams describe types, features, constraints and relationships, whereas object diagrams describe instance specifications, values and links at a particular moment. | F2, F3 |
| S6 | [UML Sequence Diagrams](https://www.uml-diagrams.org/sequence-diagrams.html) | Kirill Fakhroutdinov / UML-Diagrams.org; explanatory guide | Sequence diagrams show message exchanges among individual participants using lifelines, messages, execution specifications and interaction fragments. | F3, F7, F8 |
| S7 | [arc42 section 6 — Runtime view](https://docs.arc42.org/section-6/) | arc42, Gernot Starke and contributors | Runtime scenarios explain how building-block instances collaborate, including important use cases and error scenarios, with sequence diagrams among the supported notations. | F3, F8 |

**What a good answer looks like.** Select one or two critical use cases from the actual implementation; editing/submitting a media-processing job is a strong candidate because it addresses F8. For each, pair a focused class diagram with a sequence diagram using the same names. Show relevant methods/signatures, interfaces, state, associations and dependencies in the class view. Show typed object lifelines such as `handler:ActualHandlerType`, method calls, responses, transaction boundaries and guarded alternatives in the sequence view. Replace illustrative names with source-backed names.

Trace validation/authorization, application coordination, domain behaviour, persistence, event publication and asynchronous processing at the appropriate level. Include at least the material rejection, rollback, retry or duplicate path for the chosen scenario. A sequence containing only “Frontend → API → Service → Database” remains an architectural interaction view; it does not by itself answer the assessor's class/object-level request. For a GoF pattern, identify the actual participant roles and the design problem it solves instead of attaching pattern labels to arbitrary boxes. C4 components complement the UML detail; they do not replace it.

## F4 — Data schemas, data ownership and reliable event publication

### ER notation and service-owned schemas

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| M1 | [What is an entity relationship diagram?](https://www.ibm.com/think/topics/entity-relationship-diagram) | IBM | The guide distinguishes conceptual, logical and physical ER models and explains entities, attributes, relationship cardinality and Chen/Crow's Foot notation. | F4 |
| M2 | [Data Modeler Concepts and Usage](https://docs.oracle.com/en/database/oracle/sql-developer-data-modeler/24.3/dmdug/data-modeler-concepts-usage.html) | Oracle, SQL Developer Data Modeler documentation | Oracle distinguishes logical and relational models and documents Barker/Crow's Foot and Bachman notation and foreign-key relationship rendering. | F4 |
| M3 | [Pattern: Database per service](https://microservices.io/patterns/data/database-per-service.html) | Chris Richardson / Microservices.io | Persistent data belongs privately to a service and is accessed through its API, with private tables or schemas possible without a separate database server for every service. | F2, F4, F5 |

**What a good answer looks like.** Show a logical data model and the implemented physical schemas, grouped by service ownership. Include table/collection purpose, primary and foreign keys where applicable, cardinality and optionality, field types/nullability, unique/check constraints, indexes and important access patterns. Mark an ID referencing another service's data separately from a locally enforced foreign key. Explain identifiers that connect records across boundaries without suggesting shared ownership or cross-service ORM navigation.

If a store is document- or key-value-based, provide its schema and access patterns: document/item shape, required fields, embedded versus referenced data, partition/sort keys, secondary indexes and validation rules. NoSQL still needs an explicit data model. DDD entities, ER entities, persisted documents and AWS resources should not be treated as interchangeable diagram elements.

### Transactional outbox and the transition to a queue

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| M4 | [Pattern: Transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html) | Chris Richardson / Microservices.io | Store an outgoing message atomically with the business update and let a separate relay publish it, accounting for duplicate publication and ordering. | F4, F8 |
| M5 | [Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) | AWS Prescriptive Guidance | AWS explains the dual-write failure, an RDS outbox-table implementation and a DynamoDB Streams CDC implementation, with idempotency and ordering considerations. | F4, F5, F8 |

**What a good answer looks like.** If source evidence shows an outbox, include its event identifier, aggregate/correlation identifier, event type/version, payload and actual publication-state fields, plus the business-update/outbox transaction and relay flow. Trace where the queue publication occurs and how failed publication and duplicate delivery are handled. The external pattern is a way to explain or propose reliable publication; it is not evidence that this codebase implements an outbox. Do not add an outbox box to the “as implemented” diagram merely because the pattern fits.

## F5 — A fair relational versus NoSQL answer for media/job metadata

### Workload selection and DynamoDB single-table design

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| N1 | [Selecting a database for a SaaS application](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-managed-postgresql/db-selection.html) | AWS Prescriptive Guidance | A comparison of Aurora/RDS PostgreSQL and DynamoDB evaluates data model, planned access patterns, latency and transaction integrity rather than declaring one category universally superior. | F5 |
| N2 | [Data Modeling foundations in DynamoDB](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/data-modeling-foundations.html) | AWS DynamoDB Developer Guide | The guide explains single- and multiple-table designs, their tradeoffs and when data locality and querying related entity types make single-table design useful. | F4, F5 |
| N3 | [Single-table vs. multi-table design in Amazon DynamoDB](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/) | AWS Database Blog | The article explains how access patterns and DynamoDB's storage/query mechanics determine table design, including operational and cost reasons to choose different layouts. | F4, F5 |

### MongoDB transaction capabilities and costs

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| N4 | [Transactions](https://www.mongodb.com/docs/manual/core/transactions/) | MongoDB Manual | MongoDB supports single-document atomicity and multi-document ACID transactions, while warning that distributed transactions cost more than single-document writes and do not replace sound schema design. | F5 |
| N5 | [Production Considerations](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/) | MongoDB Manual | Transaction support depends on deployment configuration, and transaction lifetime, cache pressure, conflicts and retry behaviour require operational consideration. | F5 |

### DynamoDB CDC/outbox alternative

Use **M5** for AWS's DynamoDB Streams implementation of the outbox/CDC pattern, together with this operational reference:

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| N6 | [Using AWS Lambda with Amazon DynamoDB](https://docs.aws.amazon.com/lambda/latest/dg/with-ddb.html) | AWS Lambda Developer Guide | Lambda polls and batches DynamoDB stream records with at-least-once event processing, so stream consumers need idempotency and explicit batch-failure handling. | F5, F8 |

**What a good answer looks like.** Start with an access-pattern and invariant table for the metadata workload: lookups by media/job ID, owner listings, state transitions, retries, event publication, and any actual joins/reporting queries. Treat these as candidate questions until confirmed against the code and requirements. Separate metadata modelling from the storage of large media objects. Then make the following comparison with measured or explicitly estimated costs:

| Candidate | A defensible reason to choose it | Tradeoff the report should address |
| --- | --- | --- |
| Relational, including Aurora/PostgreSQL | Relational constraints, multi-row transactions, evolving SQL queries and joins within a service's owned schema. | Query/index design, connection and capacity management, cost and service ownership boundaries. |
| MongoDB | A media/job aggregate can fit a useful document boundary and flexible embedded metadata matches the access patterns. | Document growth and indexing, schema validation, cross-document transaction cost and deployment requirements. |
| DynamoDB | Stable key-based access patterns and conditional state updates fit an access-pattern-first model with managed scaling. | Partition/sort key and GSI design, denormalization, hot keys, query evolution and any required transaction/CDC design. |

A single-table design is a modelling option, not a prerequisite for microservices or an instruction to combine independently owned contexts into one shared table. The justified unit of comparison is the workload and ownership boundary. Do not argue that NoSQL has no transactions, that SQL cannot scale, or that “serverless” alone determines the database. MongoDB's transaction support makes the assessor's suggestion credible; it does not by itself prove a migration is warranted.

If proposing DynamoDB Streams, show a proposed alternative flow: committed item change → stream → Lambda event-source mapping/relay → downstream queue/event consumer. Explain retry/idempotency and per-item ordering rather than claiming exactly-once end-to-end delivery. M5 and N6 support this alternative; they do not prove it is deployed.

## F6 — Load balancing, load leveling and worker scaling

### HTTP admission and Lambda request execution

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| L1 | [Throttle requests to your HTTP APIs for better throughput in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html) | AWS API Gateway Developer Guide | HTTP API throttling uses best-effort account/route rate and burst controls and can return HTTP 429 when demand exceeds capacity targets. | F6 |
| L2 | [Event Function scaling behavior](https://docs.aws.amazon.com/lambda/latest/dg/scaling-behavior.html) | AWS Lambda Developer Guide | Lambda grows execution environments according to a defined per-function concurrency scaling rate, so managed request execution is scalable but subject to capacity limits. | F6 |

### Queue buffering and competing consumers

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| L3 | [Queue-Based Load Leveling pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/queue-based-load-leveling) | Microsoft Learn / Azure Architecture Center | A queue buffers variable arrival rates so workers can process demand without forcing the downstream service to absorb every burst immediately. | F6, F8 |
| L4 | [Competing Consumers pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/competing-consumers) | Microsoft Learn / Azure Architecture Center | Multiple consumer instances process work from the same messaging channel to distribute workload and improve throughput and availability. | F6 |
| L5 | [Amazon SQS short and long polling](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html) | AWS SQS Developer Guide | Consumers retrieve messages with `ReceiveMessage`, and long polling reduces empty responses while waiting for available work. | F6, F8 |
| L6 | [Configuring scaling behavior for SQS event source mappings](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-scaling.html) | AWS Lambda Developer Guide | Lambda's SQS event-source mapping polls and invokes workers with configurable scaling/concurrency controls, including limits that interact with function reserved concurrency. | F6, F8 |

### ECS Fargate with and without an ALB

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| L7 | [Use load balancing to distribute Amazon ECS service traffic](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html) | AWS ECS Developer Guide | ECS service load balancing is optional, and an Application Load Balancer routes HTTP/HTTPS traffic to service tasks when that traffic path is required. | F6 |
| L8 | [Create a target tracking scaling policy for Application Auto Scaling using metric math](https://docs.aws.amazon.com/autoscaling/application/userguide/application-auto-scaling-target-tracking-metric-math.html) | AWS Application Auto Scaling User Guide | The SQS backlog-per-task example divides visible queued messages by running ECS tasks to supply a worker-capacity scaling signal. | F6 |

**What a good answer looks like.** Explain four separate mechanisms and then identify the actual configured values and evidence:

1. **HTTP entry:** API Gateway routing/authorization and throttling, followed by Lambda invocation or the configured integration; explain Lambda concurrency and downstream limits.
2. **Buffering:** SQS absorbs bursts; arrival rate, processing time, backlog age and allowed delay determine whether worker capacity is sufficient.
3. **Work distribution:** an SQS event-source mapping invokes Lambda workers, or ECS workers poll with `ReceiveMessage`; describe concurrency, acknowledgement/deletion, visibility timeout, retries, duplicate handling and dead-letter behaviour where implemented.
4. **Capacity control:** document whether ECS uses a persistent worker service, individual on-demand tasks or another orchestration mechanism, and show the actual scaler/launcher and limits.

An ALB distributes incoming network requests among registered targets. A queue buffers and distributes jobs through consumer retrieval. These can coexist, but they solve different problems. A Fargate HTTP service can sit behind an ALB; a worker that only polls SQS can run without an ALB on that job path. Neither adding an ALB icon nor saying “SQS load balances” explains the full mechanism.

The report should state which mechanism is implemented and which is proposed. A backlog-per-task scaler is an example to evaluate, not evidence that automatic scaling exists. An ECS service's desired task count, a per-job task launcher and an SQS-to-Lambda event-source mapping are different deployment/runtime arrangements and need different arrows. Use M5/N6 for the duplicate-processing rationale where relevant.

## F7 — API Gateway authorizers and how to draw them

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| A1 | [Control access to HTTP APIs with JWT authorizers in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html) | AWS API Gateway Developer Guide | API Gateway validates JWT signatures and configured claims such as issuer/audience and route scopes, then passes verified claims to the integration. | F7 |
| A2 | [Control access to HTTP APIs with AWS Lambda authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-lambda-authorizer.html) | AWS API Gateway Developer Guide | A Lambda authorizer is a separate function invoked by API Gateway whose response supplies an authorization decision, with payload-format, identity-source and caching configuration. | F7 |

**What a good answer looks like.** First establish whether the implementation uses an HTTP API or another API type and inspect its actual authorizer configuration. These two references are specifically for HTTP APIs; do not silently apply their configuration to a REST API. Distinguish the two possible drawings:

| If the actual configuration is… | Draw and explain… |
| --- | --- |
| HTTP API managed JWT authorizer | Client sends bearer token to API Gateway; a JWT-authorizer annotation/subcomponent is attached to the protected route; Gateway validates the token before invoking the backend integration and passes claims onward; show the identity provider/JWKS relationship separately if useful. |
| HTTP API Lambda authorizer | Client calls API Gateway; Gateway invokes a separate authorizer Lambda and receives its decision/context; an allowed request reaches the backend integration; label authorizer caching/identity sources where configured. |

The managed JWT authorizer is not an application Lambda just because Lambda serves the protected route. Conversely, a custom Lambda authorizer should be visible as its own function. Show denied requests ending at the gateway, and show any backend ownership/domain permission checks as a further responsibility. For payload version 2.0, Lambda authorizers can return a Boolean simple response when enabled or an IAM policy; version 1.0 requires the policy format. Match the diagram and explanation to the configuration rather than mixing the two mechanisms.

## F8 — Edited-video flow and the Lambda/Fargate decision

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| E1 | [Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) | AWS Lambda Developer Guide | The quotas document lists a standard 900-second function timeout, memory up to 10,240 MB and `/tmp` storage configurable from 512 to 10,240 MB, with invocation/model-specific exceptions documented separately. | F8 |
| E2 | [AWS Fargate or AWS Lambda?](https://docs.aws.amazon.com/decision-guides/latest/decision-guides/fargate-or-lambda.html) | AWS Decision Guides | The decision guide compares short event-driven functions with container workloads needing different resource/runtime control and longer execution, and permits hybrid designs. | F8 |
| E3 | [Processing user-generated content using AWS Lambda and FFmpeg](https://aws.amazon.com/blogs/media/processing-user-generated-content-using-aws-lambda-and-ffmpeg/) | AWS for Media & Entertainment Blog, Abbas Nemr | This worked example processes bounded user-generated media with FFmpeg in Lambda, demonstrating that media processing is possible when its memory/runtime and data-access approach fit. | F8 |

**Limit and age qualifications.** The commonly stated Lambda envelope is **15 minutes per standard invocation, up to 10,240 MB memory, and up to 10,240 MB `/tmp`**; the latter two are commonly described as 10 GB. These are maxima/configurable limits, not evidence of the deployed configuration. The live E1 page also documents up to 5,400 seconds/90 minutes for certain asynchronous/event-source invocations on **Lambda Managed Instances**, with stated exclusions. Therefore, “all Lambda processing always stops at 15 minutes” is too broad. Establish the actual compute model and invocation type before applying a limit. E3 dates from 2020 and describes the then-current 512 MB temporary-storage constraint; use E1 for current `/tmp` limits and E3 only for its media-processing technique.

**What a good answer looks like.** Present the actual edited-video sequence and identify the component that decides the processing destination. Use this as a tracing checklist, not an assertion of an implemented topology:

1. User submits an edit/processing command to a named API operation.
2. Authorization, request/domain validation and the relevant metadata/state update occur in identified handlers/objects.
3. Show the precise transaction/event boundary and actual publication mechanism; if an outbox exists, show the writer and relay separately (M4–M5).
4. Identify the dispatcher/policy owner, its input metadata and the decision point relative to persistence, publication and consumption.
5. Label each branch with its actual predicate and action: invoke a function, publish to a queue, launch an ECS task, or let a worker consume a queue, as evidenced by the code.
6. Show accepted/rejected/completed/failed outcomes and how their state changes become visible.

For each compute branch, give the predicted/observed processing time, memory and scratch-space requirements, codec/tool/runtime constraints, concurrency limits and cost/startup tradeoffs. Media duration alone is not encoding duration; file bytes alone are not memory or CPU demand. Defend any threshold with measurements of representative inputs and a margin for tail latency. If the present code uses a simpler heuristic, describe that actual heuristic and record its limitations rather than inventing a sophisticated scheduler.

AWS does not automatically choose between arbitrary Lambda and Fargate implementations for a business job. The report must locate the application's routing rule or its orchestration configuration. E1–E3 explain selection criteria; S6–S7 explain the sequence notation; M4–M5 explain reliable publication where applicable; L5–L8 explain queue consumption and worker capacity. If the source contains no decision rule, mark the question unresolved and track a proposed design separately.

## F9 — Visible SAST and DAST in CI/CD

### Pipeline security practices and standards

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| P1 | [OWASP DevSecOps Guideline](https://owasp.org/www-project-devsecops-guideline/) | OWASP Foundation | The guideline includes SAST and DAST as distinct pipeline activities alongside dependency, secret, infrastructure and other security controls. | F9 |
| P2 | [NIST SP 800-218 — Secure Software Development Framework, Version 1.1](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-218.pdf) | US National Institute of Standards and Technology | Practices PW.7 and PW.8 address human-readable-code review/analysis and executable-code security testing respectively, supporting explicit complementary verification activities and recorded findings. | F9 |
| P3 | [Tests for CI/CD pipelines](https://docs.aws.amazon.com/prescriptive-guidance/latest/strategy-cicd-litmus/tests-for-cicd-pipelines.html) | AWS Prescriptive Guidance | AWS distinguishes source-code SAST from DAST against a provisioned test environment and identifies security checks as part of a pipeline's broader test strategy. | F9 |

### SAST tools

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| P4 | [CodeQL Action](https://github.com/github/codeql-action/blob/main/README.md) | GitHub | CodeQL performs semantic analysis of repository source code to find security vulnerabilities and uploads results for review in GitHub code scanning. | F9 |
| P5 | [Add Semgrep to CI](https://docs.semgrep.dev/deployment/add-semgrep-to-ci) | Semgrep | The documentation explains integrating Semgrep scans into CI jobs triggered by development events, with findings available for triage and remediation. | F9 |

### DAST techniques and their GitHub Actions

| ID | Title and verified URL | Publisher | Relevant point | Supports |
| --- | --- | --- | --- | --- |
| P6 | [ZAP — Baseline Scan](https://www.zaproxy.org/docs/docker/baseline-scan/) | ZAP project | The baseline scan spiders a target and performs passive scanning, with report/rule configuration, rather than carrying out the full active API attack scan. | F9 |
| P7 | [ZAP — API Scan](https://www.zaproxy.org/docs/docker/api-scan/) | ZAP project | The API scan imports OpenAPI, SOAP or GraphQL definitions and normally runs active as well as passive API-focused checks, with a safe-mode option to skip active scanning. | F9 |
| P8 | [Action Baseline](https://github.com/zaproxy/action-baseline/blob/master/README.md) | ZAP project / zaproxy | The Baseline GitHub Action supplies target, rule, failure-policy and report-artifact inputs to execute the baseline scanner in a workflow. | F9 |
| P9 | [Action API Scan](https://github.com/zaproxy/action-api-scan/blob/main/README.md) | ZAP project / zaproxy | The API Scan GitHub Action runs DAST from an API definition and exposes workflow inputs for scan format, rules, failure behaviour and artifacts. | F9 |

**What a good answer looks like.** Draw a pipeline with separate source/build scanning and deployed-test-environment scanning, then substantiate each implemented stage. The evidence should identify:

| Stage | What to show in the report |
| --- | --- |
| SAST | Tool/version, configured rules and supported source languages, scan scope/exclusions, event trigger, findings format, severity/failure policy and the exact workflow step. |
| DAST | The deployed target/version, reachability/readiness check, API definition or discovery method, authentication and tested roles/routes, baseline versus active mode, exclusions, failure policy and report artifact. |
| Gate and evidence | Which stage blocks progression, how findings are triaged, any accepted exceptions, and a completed run/report tied to the same source revision and deployed artifact. |

Present the tools that are actually configured; P4 and P5 are alternatives/examples, not a requirement to install both. SCA, secrets scanning, linting and unit tests do not by themselves establish SAST or DAST coverage. A workflow file proves configuration, not that the job ran successfully, reached protected endpoints or scanned the intended artifact. Distinguish implemented, passing, skipped, failing and proposed stages.

Describe a ZAP baseline as passive DAST and document its reach; it does not prove comprehensive active API testing. An API scan needs the correct definition and authentication/context if protected operations are in scope. Active scans belong against an authorized test target, with their side effects accounted for. Tool output needs interpretation and retention, not just a scanner icon or a green pipeline screenshot. This research did not run scans or change workflows.

## Suggested report handoff order

1. Build the view map and vocabulary, then deployment and capacity explanation (F1, F6).
2. Establish domain boundaries, aggregate rules and owned data models (F2, F4).
3. Document the authorizer and one or two critical object-level scenarios, including the edited-video routing decision (F3, F7, F8).
4. Add the workload-based database decision with a fair MongoDB/DynamoDB alternative (F5).
5. Tie the pipeline drawing to actual SAST/DAST configuration and completed-run evidence (F9).

Use these references to justify concepts and design choices. Use Main `76282d3` source evidence to establish the actual system. Keep discrepancies and missing mechanisms visible rather than using external patterns to fill them in.
