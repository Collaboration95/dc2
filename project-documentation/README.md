This folder and reference/ sub-folder contains original and extracted information regardign to practice project 2. 

original-reference/01 Briefing.pdf and lecturer guidance -> [briefing-requirements.txt](briefing-requirements.txt)
reference/Project Report Template for Practice Project.docx -> report-template-notes.md 
Project Presentation Guidelines & Schedule.pdf -> presentation-notes.md

Refer to project-2-working-interpretation.md for some ideas on how these requiremnts would apply to project 2. 

It explicitly separates course requirements from proposals and unanswered questions. Project 1's existing code and history are in ../Media_player/.

## Source priority

Use `Team17-Proposal.docx` for this team's specific scope and commitments, and [briefing-requirements.txt](briefing-requirements.txt) for the merged briefing constraints. Prefer the lecturer's interpretation where it differs from the written briefing slides. Use the original presentation schedule for specific team slots and the original report template for report structure. The report template is not proof that a capability has already been built.

## Current Project 2 planning

**Project proposal:** [project-2-proposal.md](project-2-proposal.md) (Word copy: `project-2-proposal.docx`, diagrams in `images/`). Rebuild the Word copy after editing the Markdown:

```bash
sed -E 's#\]\(images/([a-z-]+)\.svg\)#](images/\1.png){width=6.2in}#' project-2-proposal.md | pandoc -f markdown-implicit_figures --reference-doc=proposal-reference.docx -o project-2-proposal.docx
```

Start with [the Project 2 extension TLDR](project-2-tldr.md) for a quick Cert 1 versus Project 2 comparison and member review checklist.

Review [the Project 2 report draft](project-2-report-draft.md). It follows the original report template and distinguishes inherited functionality, planned work and pending evidence. DOCX conversion requires approval of the Markdown draft.

Read [the historical baseline inspection and planning notes](project-2-baseline-and-plan.txt) for the inspected Project 1 capabilities and inherited evidence. Its time estimates and delivery plans are historical; use `Team17-Proposal.docx` for current scope, acceptance targets and effort allocation.

[The requirements guide](project-2-requirements-and-scope.txt) explains the course requirements. Its original 30-person-day allocation does not represent the current three-day agentic plan.
