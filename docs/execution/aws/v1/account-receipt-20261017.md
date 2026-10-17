# V1 account and authorization receipt — 17 October 2026

Status: **account facts observed read-only; cloud authorization recorded.** No AWS resource was
created, changed or deleted to produce this receipt. V1 deployment and the evidence issues
#63-#67 remain NOT_RUN. This receipt supplies the account, currency, quota and scope inputs
that #45 asks for; the coordinator closes #45, not this file.

It contains no credentials, access key ids, secret ARNs, cookies or signed URLs. Account id,
user name, region and policy names are already public in this repository
([`cloud-operator-20261015.md`](cloud-operator-20261015.md)).

## 1. Observed facts

All commands ran from one shell, read-only, with exactly `--profile dc2-project2
--region ap-southeast-1` (the `default` profile was never used and no `AWS_*` variable was
relied on). Times are UTC; the account's budget API reports the same moment as 2026-10-17 in
Singapore time (UTC+8), which is why the date differs from the file name.

| Fact | Observation | Command | Observed (UTC) |
|---|---|---|---|
| Account and region | Account `866865534361`, region `ap-southeast-1` | `aws sts get-caller-identity --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:31Z |
| Operator | IAM user `Guruprasath` (same user the 15 October receipt names) | same STS call | 2026-10-16T19:18:31Z |
| MFA device present | **Yes.** One virtual MFA device, enabled 2026-10-15T12:01:39Z. The 15 October receipt saw an empty list before this enrollment | `aws iam list-mfa-devices --user-name Guruprasath --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:31Z |
| Group | `flickpond-team` | `aws iam list-groups-for-user --user-name Guruprasath --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:32Z |
| User-attached policies | `AdministratorAccess` | `aws iam list-attached-user-policies --user-name Guruprasath --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:33Z |
| Group-attached policies | `FlickPondRequireMFA`, `FlickPondRegionLock`, `AdministratorAccess` | `aws iam list-attached-group-policies --group-name flickpond-team --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:42Z |
| Budget | `flickpond-monthly`: limit **30.0 USD**, monthly, actual spend 0.0 USD, health HEALTHY | `aws budgets describe-budgets --account-id 866865534361 --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:43Z |
| Month-to-date spend | **-0.0000000002 USD** (a rounding residue; effectively 0), `Estimated: true`, period 2026-10-01 to 2026-10-16 inclusive | `aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-10-17 --granularity MONTHLY --metrics UnblendedCost --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:44Z |
| Lambda concurrent executions | Applied quota **10** (L-B99A9384, adjustable, account level) | `aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:45Z |
| Lambda account settings | `ConcurrentExecutions` 10, `UnreservedConcurrentExecutions` 10, 0 functions, 0 bytes of code | `aws lambda get-account-settings --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:46Z |
| Fargate On-Demand vCPU | Applied quota **6** (L-3032A538, adjustable, account level) | `aws service-quotas get-service-quota --service-code fargate --quota-code L-3032A538 --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:46Z |
| Existing stacks | Only two entries, both named `dc2-v1-20261015t1146-bootstrap`: one `ROLLBACK_COMPLETE`, one `DELETE_COMPLETE` | `aws cloudformation list-stacks --query 'StackSummaries[].{N:StackName,S:StackStatus}' --profile dc2-project2 --region ap-southeast-1` | 2026-10-16T19:18:46Z |

Reading the observations:

- **Billing currency: USD.** Cost Explorer returned `Unit: USD` for UnblendedCost and the budget
  limit and actual spend are both `USD`. That is the currency every guard in the pipeline
  compares against (`--budget-usd`, preflight "budget is USD"). Limit of this claim: Cost
  Explorer and Budgets report in the account's billing currency, but the invoice and payment
  method were not inspected, so the card/invoice currency itself is not independently proven.
- **Lambda.** With a limit of 10 and 10 unreserved, AWS refuses any reserved concurrency (it
  keeps 10 unreserved). The deploy design reserves nothing and bounds work with SQS mapping
  `MaximumConcurrency` and the Gateway stage throttle. The quota is still 10 because the
  15 October increase request to 200 was rejected; no request is pending.
- **Fargate.** 6 vCPU fits three 2-vCPU encoders and nothing else at the same time, so
  migration and generator tasks must not overlap them (one run at a time).
- **Stacks.** `dc2-v1-20261015t1146-bootstrap` in `ROLLBACK_COMPLETE` is the 15 October failure
  receipt (an empty stack, no resources, its Retain bucket never existed). It was **left
  untouched**; the pipeline picks a new `<env>-bootstrap` name and never reuses or deletes it.
  The `DELETE_COMPLETE` entry of the same name is an earlier, already-deleted incarnation; this
  receipt did not create it. No other stack exists, so the account holds no V1 resource.
- The `AdministratorAccess` policy is attached to both the user and the group. The scope in
  section 4 is therefore a self-imposed limit of the pipeline (tags, journal, region), not one
  IAM enforces beyond `FlickPondRegionLock` and `FlickPondRequireMFA`.

## 2. MFA finding (observed 2026-10-17)

The policy text below was observed by the coordinator on 2026-10-17 and is not re-fetched
here; this receipt re-verified only that the policy is attached to the group and that an MFA
device now exists (section 1).

- `FlickPondRequireMFA` denies on a `Bool` condition `aws:MultiFactorAuthPresent` equal to
  `false`.
- Direct CLI calls with the long-term access key pass: `aws ec2 create-security-group
  --dry-run` returned `DryRunOperation`. A key without a session carries no
  `MultiFactorAuthPresent` key at all, and `Bool ... false` does not match an absent key.
- CloudFormation-mediated creates are denied, because calls CloudFormation makes on the caller's
  behalf carry `MultiFactorAuthPresent=false`. This is the 2026-10-15 failure: `s3:CreateBucket`
  received an explicit identity-policy deny and the bootstrap stack rolled back.
- So the deploy needs an MFA-backed session: `make aws-mfa-session CODE=<6 digits>` writes
  profile `dc2-project2-mfa` (36 hour token). Preflight refuses a long-term key and tells the
  operator to run it.
- The policy is deliberately **not** bypassed or edited, and no service role is used to dodge
  it. Having a device is necessary, not sufficient: **for `Guruprasath`, execution still requires
  the user to mint the MFA session**; an agent cannot. The dedicated principal in section 2a is
  the user-authorized alternative.

### 2a. Dedicated agent principal (authorized 2026-10-17)

On 2026-10-17 the user authorized the dedicated IAM user `flickpond-agent` for the cloud proof,
through local profile `dc2-agent` (long-term keys held only in the user's local AWS
configuration; no key id or secret appears in this repository). The user verified that it has
`AdministratorAccess` and `FlickPondRegionLock` attached directly, belongs to group
`flickpond-agents` (`PowerUserAccess`), is not subject to `FlickPondRequireMFA` and has no MFA
device. The MFA-session path above remains the route for `Guruprasath`.

The deploy pipeline distinguishes the two principals with `iam simulate-principal-policy`
(`s3:CreateBucket`, `cloudformation:CreateStack`; `aws:MultiFactorAuthPresent=false`,
`aws:ViaAWSService=false`, `aws:RequestedRegion=ap-southeast-1`): for `Guruprasath` both actions
are `explicitDeny`, for `flickpond-agent` both are `allowed`. A long-term key is accepted only
when every decision is `allowed`; a denied or failed simulation keeps the refusal. The policy
itself is not edited or bypassed, and the `default` profile stays refused.

## 3. Envelope and limits (USD)

| Quantity | Value | Meaning |
|---|---|---|
| Planning envelope | approximately $200 | The user's own figure. A planning ceiling for the whole project, not a bill, a cap or permission to spend |
| Live guard | **$30 `flickpond-monthly`** | The only live limit. Pipeline cost guard: month-to-date UnblendedCost + forecast + `planned_cost(3 h)` ($1.97) must not exceed `--budget-usd` (default 30). Run in preflight and before each change-set execute. Budgets is an alert, Cost Explorer lags and is estimated: alert-grade, not a hard cap |
| Today's headroom | $30 limit, about $0 spent | The guard passes with a wide margin |
| Planned proof run | **roughly $2-$6** | Derived below |

Derivation of the proof-run cost, from the runbook's per-step estimates and Singapore rates
(Aurora $0.20/ACU-hour; Fargate $0.05056/vCPU-hour + $0.00553/GiB-hour + $0.005/hour IPv4;
three 2 vCPU/4 GiB encoders $0.38472/hour combined; database about $0.10/hour typical at 0.5 ACU,
$0.40/hour at the 2 ACU ceiling). Assumptions: one run id; steps run once; the database is awake
for the whole of each step and for the 30 minute pause wait; each capacity encoder runs for the
whole step in the high case (about a quarter of it in the low case); time ranges are the
runbook's estimates, not measurements.

| Step | Time | Low | High |
|---|---|---|---|
| 1 Deploy, steps 1-12 (runbook: "about $0.40-$2.00 including the retained month") | 50-80 min | 0.40 | 2.00 |
| 2 Gateway and capacity: encoders (low 30 min, high 125 min of three tasks) | | 0.20 | 0.80 |
| 2 Gateway and capacity: database awake (140 min) | | 0.23 | 0.93 |
| 3-4 Close and ACU pause wait (database awake, 35 min) | | 0.06 | 0.23 |
| 5 Latency: cold wake and generator (20 min, task cents) | | 0.04 | 0.14 |
| 6 Release (40 min database awake) | | 0.07 | 0.27 |
| 7 Teardown (database until deleted, about 15 min; final snapshot storage under $0.10) | | 0.03 | 0.10 |
| **Single clean pass** | | **about $1.0** | **about $4.5** |
| One extra full redeploy after a failed step (step 1 repeated) | | | + up to $2.0 |
| **Worst case with one redeploy** | | | **about $6.5** |

The planning figure is therefore $2-$6: a clean pass lands near the bottom to middle of that
range and one failed deploy pushes it to the top. Standing cost after the run is about
$0.76/month (RDS-managed secret, ECR, logs) plus the retained final snapshot's storage until
it is deleted. Even the high case is about a fifth of the $30 budget, and a never-pausing
database for the whole month (about $43.87 at 0.5 ACU in `cost-model.json`) is the one
scenario that would breach it: the pause evidence step exists to catch that.

## 4. Approved scope

On 2026-10-17 the user instructed the coordinator to complete the whole V1 plan, including the
cloud proof (#45, #63-#67), and to close the epics and the tag. That instruction authorizes
exactly this scope, and nothing wider:

- **One run id.** One namespace `dc2-v1-<run id>` at a time (the 6 vCPU and 10 execution quotas
  do not allow overlap). A failed run is torn down and a new id is chosen.
- **Resources:** only those the pipeline creates, tagged `deploy-project=dc2-v1` and
  `owner-run=<run id>`, in `ap-southeast-1`. No NAT gateway, paid endpoints, ALB, EC2 or Redis.
- **Session windows:** opened only for evidence steps (`session open` / `window`) and closed
  after each; the deploy itself ends closed. Throttle 0/0 and disabled mappings and rules are
  the closed state.
- **Teardown after evidence.** The final database snapshot `<env>-final` is **retained by
  default**; it may be deleted afterwards, optionally, once the receipts are archived.
  `--skip-final-snapshot` is the operator's choice, not the default.
- **Spend cap:** the $30 `flickpond-monthly` budget, enforced by the pipeline cost guard. The
  roughly $200 envelope is not a spending permission.
- **Out of scope:** any other AWS account, any Alibaba resource, the legacy bootstrap stack
  (untouched), account-wide billing or security changes (including the IAM policies above), and
  quota-increase requests.

Execution requires either an MFA session minted by the user (`Guruprasath`) or the authorized
`dc2-agent` profile (section 2a). Until a real run produces real
receipts, #63-#67 stay open and Blocked; a simulated or local run is not an AWS PASS.

## 5. Ownership

The rules live in [`deploy-runbook.md`](deploy-runbook.md) (see "Teardown", "Resuming" and
"Cloud proof in order"); in short:

- **Resource ownership:** every created resource carries `deploy-project=dc2-v1` and
  `owner-run=<run id>`. Teardown deletes something only if its id is in this run's journal
  **and** its live tags match; anything else is listed under `skipped_not_owned` and left alone.
  Pre-existing resources, including the `ROLLBACK_COMPLETE` stack, are never candidates.
- **Session ownership:** one operator owns live mutations; one process per run (a lock refuses a
  second). The session journal records open, window and close, and a failed or partial close
  keeps every wake source disabled until `close` is rerun.
- **State outside the repo:** the private `--state-dir` (mode 0700, files 0600) holds the
  journal, stack outputs, smoke credentials, transient database passwords and evidence
  receipts. It is the only record of what the run owns, is never committed, and only the
  redacted `evidence summary` output may enter Git.
- **Identity:** every command names `--profile`, `--region ap-southeast-1` and `--account
  866865534361`; the `default` profile and ambient `AWS_*` variables are refused.
