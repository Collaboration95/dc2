# 01 Briefing — extracted requirements

Source: [01 Briefing.pdf](01%20Briefing.pdf), NUS-ISS, *Briefing on Practice Module (SE34FT)*, V2.6. This is a paraphrased working reference; page numbers point to the source.

## Purpose and assessment context (pp. 2–4, 12–13)

- The graduate certificate focuses on architecting scalable, robust, reliable cloud based systems, particularly back end support for large systems and platforms.
- The group project must demonstrate competencies across **Architecting Software Solutions** (business requirements, quality attributes, security, performance and capacity), **Platform Engineering** (robust APIs, domain analysis, reusable assets, platform operations and data), and **Cloud Native Solution Design** (cloud services and infrastructure), plus DevSecOps practices.
- The group project accounts for 50% of the certificate assessment and the written examination for 50%; both must be passed separately with at least 40%. An overall 50% is required for the certificate. A 60% GPA is stated for eligibility to stack toward the MTech, but admission is not guaranteed.
- Assessment weights differ by sponsorship: company sponsored participants have presentation 15%, report 25% including 5% peer assessment, sponsor assessment 10%, exam 50%; others have presentation 20%, report 30% including 5% peer assessment, exam 50%.
- Peer assessment ranks each member's contribution with unique ranks; the source says missed peer ranking yields zero peer assessment marks. Contribution means achievement toward objectives, not simply hours spent.

## What the group project must do (p. 5)

- Architect, design and build a **platform** that can enhance a business ecosystem.
- Demonstrate scalability of the platform architecture.
- Architect and build it as a cloud native application using appropriate cloud architecture services.
- Design and script suitable development and deployment automation.
- Build minimum required security controls.
- Build **at least one application** that demonstrates platform capabilities.

Required deliverables: a working system, code base or repository URL, project report, DevSecOps pipeline scripts, and test scripts. The report must cover design and architecture including key decisions, quality attributes and strategies, and DevOps/development lifecycle. The slide does **not** prescribe a microservices architecture, Kubernetes, or a particular cloud provider.

## Team, effort and dated activities (pp. 6–7, 14)

- Form a **4–5 member group**, sign up to a Canvas team by **4 Oct 2026**, and submit the proposal to the **PM Project Proposals** Canvas assignment. Projects may come from an organisation, a team idea, or another approved source; lecturers review suitability.
- Expected effort is about **10 person days per participant**.
- **22 Sep:** module briefing. **4 Oct:** proposal submission (earlier welcome). **7 Oct:** lecturer proposal review; revise if necessary and begin. **8–20 Oct:** project conduct and lecturer consultation. **23, 24 and 26 Oct:** presentations, marked tentative in this briefing. **26 Oct:** clinic. **2–6 Nov:** tentative open book written exam. **16 Nov:** final report, incorporating presentation feedback.
- Submit team progress reports **fortnightly** to **PM Progress Reports** in Canvas. Each should contain project title, date, work completed since the last report, hours per member, problems needing lecturer help, and the next two weeks' tasks.

## Proposal content (p. 8)

| Section | Content expected |
| --- | --- |
| Title | Project title. |
| Sponsor | Name, title and contact where applicable. |
| Members | Names. |
| Overview | Context and business problem solved by the platform. |
| General architecture | Logical architecture is acceptable before deployment details are chosen; show the context for scope. |
| Scope of work | Platform components such as seed, producers and consumers; included use cases; detailed account of how implementation demonstrates scalability, cloud native design, DevOps and platform engineering. |
| Effort estimates | Rough work breakdown and effort for feasibility. |

## Questions lecturers expect the team to answer (p. 9)

1. What business ecosystem pain point is the platform solving?
2. Which common services, reusable libraries and frameworks support that ecosystem?
3. What does a new use case gain from the platform versus building from scratch: effort, security, scalability, maintainability, defects? How will those benefits be demonstrated?
4. What scale can the architecture support, and what evidence proves it?
5. How will technical and nontechnical benefits be measured?
6. What value does the cloud native design add, and how will that value be shown?
7. What lifecycle activities can be automated, and what effort do they save?
8. Is implementation feasible within the effort guideline?

## Meaning of “platform” in the examples (pp. 10–11)

The iJooz QR code and Travista travel examples both ask teams to identify **seed, producers and consumers**, use cases that grow the ecosystem, scaling of customers and producers, support for future seeds, and useful analytics. They are examples, not required project topics. For Project 2, use them as prompts to define the platform ecosystem and a second use case or participant type that demonstrates reuse.

## Project 2 implication

Extending [`../../Media_player/`](../../Media_player/) is plausible if the extension becomes a demonstrable platform with one or more applications, explicit producer/consumer interactions, cloud native deployment and measured quality attributes. Merely splitting the existing FastAPI app into processes would not by itself satisfy the business ecosystem, reuse, evidence or deliverable requirements. This is an inference from the briefing, not a lecturer approved scope.
