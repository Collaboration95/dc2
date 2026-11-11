# Presentation feedback, 26 Oct 2026

Team 17 (FlickPond) presented on 26 Oct 2026 and the assessors were critical.
This folder tracks the response. The final report is due 16 Nov 2026.

## Feedback, verbatim

Notes the team took during Q&A:

```
Report -> Slide 20 ,
Authorizer , ( tied to api gateway ) ,
More detailed ,
WE dont directly go to sqs when the video is edited ,
report should contain

how do we group them into bounded context , how do we group them into aggregates , etc
Detailed design , need detailed design , at component level
Database design schemas , and data model in the report
Physical architecture , doesnt do loadbalaning ,

In this case you might as one use Nosql like mongo

I didn't see your SAST and DAST in your pipeline
```

Written comment from Boon Kui HENG (26 Oct 2026, 3:12 PM):

> Revisit the architectural diagrams taught in the Architecting Software
> Solutions course and aim to provide more perspectives of the system - e.g.,
> deployment.
> Detailed DDD diagrams with entities are expected. Revisit the Platform
> Engineering course.
> Detailed design diagrams (class & sequence diagrams) at class/object level
> for 1 or 2 critical use cases are expected. Revisit the SAD and SDP courses.
> Data schemas/models for the data stores are expected.

The team's own comment: the diagrams were bad and sometimes wrong. The
private/public subnet architecture diagram did not answer questions such as
"what splits the jobs: how do we decide Lambda or Fargate, and where is that
decision made?" Answers like that belong in the report, and the slides should
make them understandable.

## Ground rules

- **Do not change application code, infrastructure code or CI workflows.**
  Items that need code are tracked, not done.
- Do change the deck (`site/deck.html`, `site/assets/img/`) and write notes
  for the report (`final-report/src/`) in this folder.
- Every claim about the system must cite code at Main commit
  `76282d3` as a GitHub permalink:
  `https://github.com/Collaboration95/dc2/blob/76282d3/<path>#L<n>`.
- External claims need a link to the source.

## Reference

- Deck: `project-documentation/presentation/site/deck.html` (68 slides; the
  first 47 are the main talk, 48 onwards are backup). Diagrams in
  `site/assets/img/*.svg`.
- Report sources: `project-documentation/final-report/src/*.md`, figures in
  `final-report/figures/`.
- Architecture docs: `docs/architecture/` (views, ddd, decisions,
  use-case-design).
- Older deck for a different course (Project 1, older codebase) that the user
  likes for its formal-looking diagrams:
  `/Users/speedpowermac/.t3/userdata/attachments/69126276-ab16-47ff-8dce-05794f4b9464-37522de2-1c8e-4574-9753-f9ab31bd7d52-pdf.pdf`
  (24 pages).
- Course documents: `project-documentation/original-reference/` (briefing,
  report template, presentation guidelines).
