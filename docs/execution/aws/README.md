# Current AWS plan: V1 first, optional V2 afterwards

**API Gateway, two domain Lambda applications, SQS instead of Redis/RQ, owned
PostgreSQL databases, private S3 and one Fargate encoding backend.**

- [Authoritative architecture and V1/V2 gate](architecture-plan.md)
- [Dependency-ordered handoff and live issue map](v1/README.md)
- [Backlog](v1/backlog.json) and [GitHub identities](v1/github-map.json)
- [Conditional cost model](v1/cost-model.json); recalculate with
  `python docs/execution/aws/v1/calculate-costs.py`

Plan approximately $200; USD is the worksheet assumption pending the actual
account/billing currency. Target 48 hours for a local integrated build, three
elapsed agentic implementation days as baseline, five maximum. Two calendar weeks
include cloud evidence, review, fixes, writeup and rehearsal.

## Implementation versus target

The reviewed baseline at `8d13194` still contains container APIs, Redis/RQ, HTTP
peer calls and inert EC2/nginx definitions. This publication preserves that work;
it does not implement/deploy V1. Closed preparation issues #47–#62 remain historical
Done work; new migration tickets cover missing V1 behavior. Real account/cloud
acceptance stays open and Blocked. #46 closes only for the merged managed-HTTPS
decision; actual TLS/client proof remains separate.

## Historical material

- [Previous AWS2 architecture, preserved verbatim](architecture-plan-aws2-prep-20261015.md)
- [AWS2 readiness/audit](readiness/README.md)
- [Completed local preparation and limits](prep/README.md)
- `cost-worksheet.json`, `pricing-20261015.json`, `calculate-costs.py` and `review.html`
  describe the previous topology. Their $13.03/$28.27 forecasts are not V1 prices.
- Older `*-20261014.*` files are also historical. Original course documents,
  roadmap illustrations and frozen measurements remain unchanged.

No AWS account inspection, provisioning, deployment or inherited Alibaba action
is authorized by this plan/publication task.
