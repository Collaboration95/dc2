# Prepare the AWS job

This is a preparation pack, not a deployment or spending approval. The original
local delivery is accepted at `b913579`; quota and worker-window experiments
#38/#39 are complete with rejection decisions. Independent review and publication
remain pending at this document revision; no experimental default is adopted.

The proposed demo is one EC2/Compose host plus private S3, preserving the two
business services and their separately owned databases, images and migrations.
The provisional Singapore option is `c6a.2xlarge` (8 vCPU, 16 GiB), with encrypted
persistent disks, private source/output buckets and nginx HTTPS. The plan budgets
100 running hours, with a 120-hour ceiling over about three weeks. Its current
worksheet estimates USD169.47 including domain, tax/FX and contingency allowances;
actual account, currency, region and DNS costs need confirmation before spending.

## Information to prepare

Fill a private copy of [job-inputs.template.json](job-inputs.template.json):

1. The actual project account ID, billing owner and approved local login/profile
   or role. Configure credentials through the normal secure login process; do not
   paste credentials into chat or commit them. Another project's AWS account is
   not authorized for this job.
2. The approved region and budget currency. The recorded ceiling is $200 total
   for about three weeks; the worksheet uses USD and provisional Singapore rates.
3. An existing domain/subdomain, its DNS operator and the operator's ingress CIDR.
4. Required demo windows, start/teardown dates, and a named cost/data-export owner.
5. Whether account policy permits three short-lived, bucket-scoped service key
   pairs. Keep basic login, ownership, private stores and HTTPS; no OIDC,
   credential broker or elaborate security infrastructure is planned.

## What the AWS implementation must prepare

Build and test the accepted source as `linux/amd64`, and retain exact image
digests plus the existing tests/scans. Add a dedicated AWS Compose/configuration
adapter: S3 endpoints and outbound networking, browser CORS and real domain TLS,
encrypted persistent database/queue storage, and cloud-compatible release,
rollback, smoke and evidence commands. Current local scripts assume
localhost/MinIO and cannot be described as cloud-ready unchanged.

Use one/two/three hard-2-CPU workers as explicitly selected. Keep baseline quotas
and explicitly selected fixed worker counts: both experimental candidates were rejected.
Stopping worker replicas on a running host does not save its hourly EC2 charge.
Stop the host between booked windows and verify durable backlog recovery before
relying on that policy. The plan retains single-host failure limits.

The AWS agent must first verify the explicit project account, refresh prices,
fill the usage worksheet, and present the concrete resource list, schedule and
teardown before creating paid resources. No provisioning is authorized by this
preparation task.

## Full context and cost evidence

- [Architecture, deployment gaps, runbook and paste-ready agent brief](architecture-plan.md)
- [Cost assumptions, line items, usage ceilings and required inputs](cost-worksheet.json)
- [Official public pricing rows](pricing-20261014.json)
- [Accepted local handoff and source evidence](../handoff.md)
- [Experimental protocol and outcomes](../experiments-20261014/PROTOCOL.md)

The architecture brief carries the proposal scope, 80/20 and schedule constraints,
measured local results and their limitations, PR37 changes, the no-Alibaba rule,
basic-security agreement and the distinction between local and AWS evidence.
The course report, slides and recording remain separate deliverables.
