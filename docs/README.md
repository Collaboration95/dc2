This folder and reference/ sub-folder contains original and extracted information regardign to practice project 2. 

reference/Briefing.pdf -> briefing-notes.md 
reference/Project Report Template for Practice Project.docx -> report-template-notes.md 
Project Presentation Guidelines & Schedule.pdf -> presentation-notes.md

Refer to project-2-working-interpretation.md for some ideas on how these requiremnts would apply to project 2. 

It explicitly separates course requirements from proposals and unanswered questions. Project 1's existing code and history are in ../Media_player/.

## Source priority

Use the originals to settle exact wording, team allocations, dates, or changes from lecturers. The presentation schedule provides specific team slots; the briefing only gives tentative presentation dates. The report template is a structure to fill with evidence, not proof that a capability has already been built.

## Current Project 2 planning

**Project proposal:** [project-2-proposal.md](project-2-proposal.md) (Word copy: `project-2-proposal.docx`, diagrams in `images/`). Rebuild the Word copy after editing the Markdown:

```bash
sed -E 's#\]\(images/([a-z-]+)\.svg\)#](images/\1.png){width=6.2in}#' project-2-proposal.md | pandoc -f markdown-implicit_figures --reference-doc=proposal-reference.docx -o project-2-proposal.docx
```

Start with [the Project 2 extension TLDR](project-2-tldr.md) for a quick Cert 1 versus Project 2 comparison and member review checklist.

Review [the Project 2 report draft](project-2-report-draft.md). It follows the original report template and distinguishes inherited functionality, planned work and pending evidence. DOCX conversion requires approval of the Markdown draft.

Read [the implemented baseline and three-day plan](project-2-baseline-and-plan.txt) for the current feature comparison, proposed commitments and agentic time estimates. This plan uses a pinned snapshot of implemented Project 1 code. It does not depend on future Project 1 features.

[The requirements guide](project-2-requirements-and-scope.txt) explains the course requirements. Its original 30-person-day allocation does not represent the current three-day agentic plan.
