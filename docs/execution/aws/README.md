# AWS replanning — 15 October 2026

**Separate ECS Fargate services, disposable workers, one small 2-vCPU / 2-GiB
state/proxy host, private S3 through a free gateway endpoint, and a public
CloudFront HTTPS URL.** One public subnet; no domain purchase, NAT, ALB or large host.

**Latest constraints:** at most 14 days, small cloud fixtures, and zero running
application compute during downtime. Stop EC2, set all three ECS services to zero,
and drain/stop workers. Do not retain an Elastic IP; update the origin on wake.
The remaining retained-storage/internal-DNS baseline is about **$1.73 for 14 days**.

- [Next-agent Sol swarm and backlog handoff](../../../handoff-temp.md)
- [Architecture, implementation sequence, and ranked cost chopping block](architecture-plan.md)
- [Interactive review and cost levers](review.html)
- [Editable AWS diagram](../../lean-aws-microservices.drawio)
- [Cost assumptions](cost-worksheet.json) and [official price rows](pricing-20261015.json)
- Recalculate offline: `python docs/execution/aws/calculate-costs.py`
- [Private deployment-input template](job-inputs.template.json)

| 14-day scenario | AWS usage | Including tax/FX reserve and contingency |
|---|---:|---:|
| Expected: 20 online hours, 2 worker-task-hours | $6.03 | **$13.03** |
| Larger: 40 online hours, 8 worker-task-hours | $13.27 | **$28.27** |

Use **$15 expected / $30 envelope** as planning targets, not hard billing caps.
Expected uploads are only **0.25 GB total**, including six ~21-MB long submissions
and short workflow checks. Reuse assets and stored sources. Existing full local
scaling results remain local; no bulk cloud replay is planned.

Public browser access is confirmed. The restricted CloudFront-origin HTTP leg is
explicitly disclosed; viewer TLS is not end-to-end TLS. The database/proxy host
remains a shared failure point. The bounded worker starter and cloud adapters are
still proposed work. Account/currency and paid deployment authorization remain
pending. No provisioning, application changes or live trials occurred.

Historical only: [old shared-host plan](architecture-plan-20261014.md),
[old worksheet](cost-worksheet-20261014.json), [old README](README-20261014.md).
The old large host/storage/domain assumptions and the initial 21-day/300-fixture
replanning assumptions are superseded. Issue 38/39 rejection decisions are unchanged.
