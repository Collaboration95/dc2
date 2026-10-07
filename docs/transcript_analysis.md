# Project briefing: extracted facts and connections

## How to use these notes

- [transcript_sections.md](transcript_sections.md) is the organized source transcript. Its section text retains the source wording and punctuation in the same order; headings are editorial.
- This document has two passes: **Pass 1** lists information stated in the briefing, and **Pass 2** connects those statements into a usable project plan.
- References such as **S02** point to sections in the verbatim transcript. The original timestamps were removed before this analysis, so section references are the available source locations.
- “The speaker says” marks a source statement. “Reading” or “connection” marks a synthesis across statements, not a new requirement.

## Pass 1: information extracted from the briefing

### A. Project requirements and deliverables — S02

- The project must be a **distributed application** and must demonstrate **scalability** and **cloud-native design**.
- A platform is preferred, but it is **not mandatory**. If a platform is built, it may contain multiple applications.
- Cloud-native design means using cloud capabilities, including **managed services**; merely deploying an application to the cloud is not enough.
- Students must continue demonstrating **DevOps** in this project. The speaker expects evidence of a proper DevOps pipeline and says DevOps is assessed in both the earlier and current graduate certificates.
- Security controls are not a focus of this project. If login is needed, a simple user ID and password is sufficient; encryption and similar controls are described as unnecessary for this project. The speaker advises against spending limited project time on security.
- At least one **web or mobile frontend application** must be available to demonstrate the system. A backend with no frontend is not an acceptable demonstration.
- The team must demonstrate the system **working as one integrated system**, rather than presenting separate, isolated microservices.
- Code must be submitted; a **Git archive** is described as ideal. A project report is also required. A report template is available and emphasizes architecture and design, with cues or tips in the template. The speaker invites students to clarify anything unclear.

### B. Proposal, timeline, and project presentation — S03, S05, S11

- Students are urged to brainstorm and prepare the proposal promptly. The speaker hopes proposals will be submitted by **4 October** and says proposals are usually not rejected; the reviewer may suggest strengthening or increasing the challenge of parts of the proposal.
- There are about **two weeks after proposal review** to conduct the project. Starting before that period is allowed.
- The presentation schedule is in Canvas, runs by team number, and starts at **5:30**; the speaker explicitly says that start time is not tentative. Students should agree with teammates before joining a Canvas team.
- Presentation comments should be addressed in the final report and will still be considered there.
- Presentations are online via Zoom. The schedule lists **23rd, 24th, and 26th**; the 24th is identified as a Saturday. Teams on the 23rd and 26th use one Zoom link; teams on the 24th use a different link. The speaker warns that using the wrong link may place a team in a meeting without the lecturers.
- The second Zoom link is associated with part-time teams, though some full-time teams are placed in those slots. Detailed presentation guidance and rough timing are available. Teams present consecutively and should not exceed their time because this affects the next team.
- The briefing was recorded, and the speaker says they will share the video later because many students were absent.

### C. Team formation and reuse of the earlier project — S04, S10

- **16 teams of up to five members** have been created. A team of six may be considered case by case.
- Continuing from the earlier graduate certificate is **optional**, but reuse is encouraged because it can reduce the work required to build from scratch.
- One suggested path is to refactor an earlier monolithic application into microservices. If the earlier project already uses microservices, the team can continue it while improving architecture and design, especially **domain-driven design (DDD)**.
- The speaker says the earlier and current projects are likely to have **different codebases**. The first project may remain monolithic, while the current project can use microservices and more cloud-native services. These points are presented with qualifiers such as “might” and “most likely.”
- The speaker defers questions about sharing code between **5001 and 5006** until the proposal discussion. The transcript does not capture a final answer to that question.

### D. Proposal contents and effort — S05

- There is **no proposal template**. Students should submit a document through the Canvas assignment. If reusing the 5006 project, they may reuse the proposal but must address this project’s concerns.
- Sponsorship is not expected and is not recommended for the practice project, though teams may have a sponsor if they choose.
- The proposal should include:
  1. **Overview:** the business problem; describe additional functionality if applicable.
  2. **General architecture:** a logical or physical overview informed by prior architecture work. It is an initial cut, not the final architecture.
  3. **Scope of work:** functionality/use cases and plans for scalability and cloud-native design. These are plans and do not lock the team into implementing every proposal detail exactly.
  4. **Effort estimate:** estimate tasks and effort to judge whether the proposed scope is too large or too small.
- Expected effort is **10 person-days per member on average**. The speaker gives a five-person team example of **50 person-days**.

### E. Illustrative project examples — S06

- **iJuice:** a sponsored orange-juice vending-machine project. The team built a payment platform with QR-code payment and cash. The platform was designed for extensibility so other payment methods could be added.
- **Travel platform:** a fictitious, unsponsored example that brings hotel, tour, and air-ticket providers together in a one-stop portal. It should make it easy to add providers or partners, including competing providers in the same category.

### F. Project marks, sponsor marks, and peer assessment — S07–S08

- For a sponsored project, the speaker describes a **50-mark maximum** with **10 marks allocated to the sponsor**; sponsor satisfaction therefore represents **20% of the project weighting**. Unsponsored projects have no sponsor weighting.
- For the unsponsored assessment breakdown, the speaker states **20 marks for the presentation**, then describes the report as **25%** and peer assessment as **5%**. The speaker says the peer-assessment portion is grouped with the report component. The wording shifts between “marks” and “%,” so the notes retain that distinction rather than assume the scoring scale.
- Peer assessment is **mandatory** and evaluates teammates’ **perceived contribution**, not simply hours worked. More hours do not guarantee a higher perceived contribution if the work is ineffective.
- A peer-grading system sends an email to each student’s NUS email address and sends reminders. Not reading the email is not accepted as an excuse.
- Students must rank their other teammates uniquely, with someone ranked best and someone worst; they must not rank themselves. A student who does not submit a ranking receives **zero peer-assessment marks**.

### G. Progress reporting and effort tracking — S09

- Progress reports are welcome and could be weekly, but the speaker says they may be less important for full-time teams because the project period is short.
- A report can summarize work completed in a sprint and the plan for the next sprint.
- Teams are expected to track effort for the two projects **separately**. At the presentation, they should report average effort for this project and for both projects.

## Pass 2: how the information connects

### 1. Treat the proposal as a scope and feasibility check

The proposal asks for architecture, use cases, scalability/cloud-native plans, and task-based effort estimates (S05). Those sections connect directly to the mandatory distributed-system, scalability, and cloud-native requirements (S02). The estimate is meant to reveal an oversized or undersized scope before the short implementation period begins. The stated planning envelope is about 10 person-days per member, while the delivery window is about two weeks after review (S03, S05). Teams should therefore size the proposal around both constraints.

### 2. Make the architecture, demo, and evidence tell one story

The architecture should describe a distributed system that demonstrates scalability and meaningful cloud-native use (S02, S05). The implementation must then run as one integrated system, include a web or mobile frontend, and provide DevOps pipeline evidence (S02). The report should explain the architecture and design, and the code submission should let the work be inspected (S02). These are connected parts of one demonstration: proposed design → working system → pipeline and code evidence → architecture-focused report.

### 3. Reuse can save effort, but the current project still needs its own design

Reuse is encouraged to avoid starting from scratch (S04), while the proposal and effort estimate must address the current project’s scope (S05). The suggested evolution is to improve domain boundaries and DDD, then refactor or extend toward microservices and cloud-native design (S04, S10). The speaker’s expectation that the earlier and current codebases differ means teams should plan a distinct current-project result; the exact rules for sharing code between 5001 and 5006 remain unanswered in this transcript.

### 4. Proposal flexibility does not remove the core requirements

The speaker says proposal plans do not require the team to implement every detail exactly as written (S05). Separately, scalability and cloud-native design are stated as mandatory project requirements (S02). Read together, teams have room to adjust implementation details while still demonstrating those required outcomes.

### 5. Assessment links live performance, reporting, and team contribution

The project component includes a presentation, report, and peer assessment (S07–S08). Presentation feedback is expected to flow into the final report (S03), so the report is both an architecture/design record and a place to address reviewer comments. Peer marks measure how teammates perceive contribution, while effort logs separately measure time spent on each project (S08–S09); these measures should not be conflated.

### 6. Scheduling details affect both planning and delivery

The project has a short post-review window, fixed team-number presentation slots, consecutive presentations, and different Zoom links for different days (S03, S11). Teams need to confirm their assigned slot and link, prepare to the provided time guidance, and avoid overrunning.

### 7. Prioritize work according to the stated assessment emphasis

The speaker explicitly emphasizes scalability, cloud-native design, DevOps evidence, an integrated frontend-backed demo, architecture/design reporting, and presentation quality (S02, S05, S07). Security controls are explicitly deprioritized for this project (S02). In a constrained schedule, the transcript’s guidance points toward spending effort on the required architecture and working demonstration before adding security features that are not assessed here.

## Unclear wording and limits in the source

- The source contains likely speech-recognition artifacts. Examples include “code clearance” and “10% month, sorry, 10% days.” The intended wording is not silently substituted in the verbatim transcript.
- “10% days” is interpreted as **person-days** in the extracted notes because the speaker immediately gives a five-member/50-day example. This is a contextual reading, not a verbatim correction.
- The transcript says “effort expanded”; this may mean “effort expended,” but the correction is uncertain.
- The speaker refers to a presentation “this week,” a proposal deadline of 4 October, and presentation dates 23/24/26. The briefing date/year is not established in the transcript, so relative dates should not be converted into calendar dates here.
- The answer about code sharing between 5001 and 5006 is not present.
- Speaker 1/Speaker 2 labels and timestamps were removed from the source at the user’s earlier request. The brief opening “Yes” is retained, but the sectioned transcript cannot establish whether it belongs to the same speaker.
