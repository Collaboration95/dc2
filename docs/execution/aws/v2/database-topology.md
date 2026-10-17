# V2 experiment: one Aurora cluster per domain, and Aurora's pause behaviour (#94)

Status: **implemented locally, cloud evidence NOT_RUN, merge decision PENDING.** Nothing here has
touched AWS. The tests prove the template, the pipeline and the harness against fakes and the
simulation. They do not prove that CloudFormation accepts the separate layout, how fast a
second cluster resumes, whether load on one domain really leaves the other cluster paused, or
what any of it costs. Those are what the measurement plan below is for.

V1 is the default and the baseline. A stack deployed without the options below is one Aurora
cluster holding `media_db` and `processing_db`, pausing after 300 s with a 2 ACU ceiling, and its
CloudFormation template is **byte-for-byte the one V1 shipped** (a test compares the bytes with
`deploy/aws/v1/template.json`). Leaving the options out is the whole revert.

Experiment owner decision (see #80): the epic's "after the `project2-v1` tag" gate is overridden
for this work, as it was for #68 and #93. It is off by default and not on the V1 critical path.
**Keep the V1 default unless the measured evidence warrants a change** (rule below). Data API,
DSQL and DynamoDB are not part of this issue; each needs its own compatibility spike.

## The question

V1 shares one cluster, so any work for either domain wakes the cluster both use, and both domains
share its connections and its ACU ceiling. Does giving each domain its own cluster buy anything
that is worth a second cluster's fixed cost, without changing the application database model?
Two knobs are separable from that and are exposed on their own: how long an idle cluster waits
before it pauses, and the ACU ceiling.

## Design

1. **The layout is chosen when the template is rendered, not by a CloudFormation parameter.**
   `DatabaseOptions(topology, auto_pause_seconds, max_capacity)` in
   `scripts/aws/v1/definitions.py` defaults to V1's values, and `template(options)` renders them.
   A CloudFormation parameter would add a parameter and conditions to every V1 template, and one
   template cannot swap one resource set for another without a condition on every output, rule
   and reference. Rendering keeps V1's bytes unchanged and makes each layout a plain, lintable
   document. The cost: the layout of a live stack cannot be flipped (see "Switching").
2. **`separate` adds a second cluster, instance and security group; nothing else.** Resource names
   stay V1's for `shared`. For `separate` they are `MediaDatabaseCluster`/`Instance`/
   `SecurityGroup` and the `Processing` set, with the same encryption, TLS group, deletion
   protection, backup and `Retain` policies as V1's cluster. The outputs name each domain's
   endpoint and master credential (`MediaDatabaseEndpoint`, `MediaBootstrapSecretArn`, and the
   Processing pair) and add `DatabaseTopology: separate`, so nothing can read the wrong cluster
   through a name that fits both. The **application database model does not change**: each
   service still reads its own DSN parameter for its own `<domain>_db`; only the host in that
   DSN differs.
3. **The pipeline is keyed per domain.** `deploy --database-topology separate`:
   `db-bootstrap` reads both clusters' master credentials and sends the bootstrap task a
   `databases: {media: {...}, processing: {...}}` input (V1's single-connection input is still
   accepted and still used for `shared`); the bootstrap reconciles each cluster for its own
   domain only, so a cluster never learns of the peer's roles. The four DSN parameters each name
   their own domain's cluster, and the owner migration tasks, which only read their own
   parameters, need no change. `td-database` requests every deletion before waiting on any and
   takes one final snapshot per cluster (`<env>-media-final`, `<env>-processing-final`).
4. **The network follows the layout.** Each cluster has its own security group, and the encoder
   (Fargate worker) network can reach only Processing's cluster. Lambda and the migration task
   are shared by both domains today, so both clusters admit them. This is a real but narrow
   gain: a Media Lambda can still reach Processing's cluster at the network layer, and is kept out
   by its credentials exactly as in V1.
5. **The cost model and the guard price the second cluster.** `planned_cost(hours, options)`
   charges every cluster at its ceiling for the window and adds `$0.51` a month of retained cost
   (managed master credential `$0.40` + storage `$0.11`) per extra cluster.

### Pause and capacity

| Option | Deploy flag | Config key | Default | Allowed (Aurora) |
|---|---|---|---|---|
| Topology | `--database-topology` | `database_topology` | `shared` | `shared`, `separate` |
| Seconds until auto-pause | `--database-auto-pause-seconds` | `database_auto_pause_seconds` | `300` | 300 to 86,400 |
| ACU ceiling (each cluster) | `--database-max-capacity` | `database_max_capacity` | `2` | 1 to 256, steps of 0.5 |

`300` is both V1's value and the least Aurora accepts, so the pause knob can only lengthen the
wait. A longer wait trades ACU-hours (a resume avoided, a longer tail billed) for resume
latency; a lower ceiling also lowers the connection limit Aurora derives from it, which matters
because three encoders and the repair handlers share these connections (the Lambda lane's
arithmetic is in `lambda-short-encodes.md`). Pause and capacity are in-place cluster settings, so
a resume may change them (the journal records the new values); the topology may not be changed.
Both are also render inputs to `python -m scripts.aws.v1.definitions --output F
[--database-topology ...]` and to `scripts.aws.v1.config`, whose schema documents the keys.

## How to deploy each arm

The arms are different stacks, so each is its own deploy under its own run id and state
directory. Everything else about the deploy ladder is the V1 runbook (`v1/deploy-runbook.md`).

```sh
# Baseline: V1's single cluster. No flag is needed; this is what an unflagged deploy is.
python -m scripts.aws.v1.deploy deploy <scope> --run-id r1018s --state-dir D1 --images images.json \
    --seed-email ops@example.com --assume-empty-counts --forecast-usd 0 [--execute]

# Experiment: one cluster per domain, same defaults for pause and ceiling.
python -m scripts.aws.v1.deploy deploy <scope> --run-id r1018x --state-dir D2 --images images.json \
    --seed-email ops@example.com --assume-empty-counts --forecast-usd 0 \
    --database-topology separate [--execute]

# A pause or capacity change alone (a third stack, if the evidence points that way):
#   ... --database-auto-pause-seconds 900 --database-max-capacity 1
```

Both pass `rehearse` and `--dry-run` offline for either layout. The planned cost in preflight
and in the cost guard includes the second cluster, so a budget that fits V1 can be refused for
`separate`. A resume must repeat `--database-topology`; a mismatch is refused, and a journal
written before the option existed is V1's layout.

### Switching and reverting

* **There is no in-place switch.** Changing a live stack from `shared` to `separate` would add an
  empty cluster without moving Processing's data, and the reverse would ask CloudFormation to
  remove a database. The deploy refuses a mismatched resume. To change layout, deploy a new run
  id and tear the old one down (the teardown receipt takes a final snapshot per cluster).
* **Revert** is deploying V1 without the flag under a new run id. Nothing in V1 depends on this.

## Cost implications

| Item | `shared` | `separate` | Delta |
|---|---|---|---|
| Guard worst case, 3 h window, 2 ACU ceiling | `$1.97` | `$3.68` | **+`$1.71`** (second cluster at its ceiling for 3 h, `$1.20`, plus `$0.51` retained) |
| Retained while idle (paused at 0 ACU) | master credential `$0.40` + storage `$0.11` | twice that | **+`$0.51` a month** |
| Each awake ACU-hour | `$0.20` | `$0.20` per cluster | proportional to how long each cluster is awake |
| V1 14-day forecast (`cost-inputs.json`, 20 awake h at 0.5 ACU per cluster) | `$5.27` | `$7.97` | +`$2.70`, an upper bound that wakes both clusters equally long |

The figures come from the captured rates in `docs/execution/aws/v1/cost-inputs.json` and the
deploy cost guard. They are a model, not a bill. The case for `separate` is that a domain's work
wakes only its own cluster; because sessions normally use both domains the saving may be small,
and the measurement below is what shows it. A paused cluster costs only its fixed share.

## Measurement plan (not yet run)

Needs two deployed stacks (above), the V1 cloud proof's account access and `session window` on
each, **not** `session open`: an open session enables the repair schedules, which touch the
database every minute and would keep Aurora from ever pausing. About 45 to 70 minutes per arm,
most of it waiting for Aurora to pause (five minutes plus CloudWatch's lag, at least twice).

```text
# 1. Baseline stack (D1). Window, measure, close.
python -m scripts.aws.v1.session window --config D1/operator-config.json <scope>
python -m scripts.aws.v1.evidence db-topology --arm shared --state-dir D1 --run-id dbtopo1 <scope>
python -m scripts.aws.v1.session close  --config D1/operator-config.json <scope>

# 2. Experiment stack (D2). Carry the first arm's receipt across, then measure and compare.
cp D1/evidence/evidence-94-dbtopo1.json D2/evidence/
python -m scripts.aws.v1.session window --config D2/operator-config.json <scope>
python -m scripts.aws.v1.evidence db-topology --arm separate --state-dir D2 --run-id dbtopo1 <scope>
python -m scripts.aws.v1.evidence db-topology --arm compare  --state-dir D2 --run-id dbtopo1 <scope>
```

`--dry-run` runs the same code against the simulated account (its receipts are marked SIMULATED
and can never be summarized) and `evidence rehearse` includes it. The harness refuses an arm
that does not match the stack it finds (read from the stack outputs), and a session that is not
a window.

### What each arm records, per cluster

| Measurement | How |
|---|---|
| **Cold-resume latency** | Wait until CloudWatch `ServerlessDatabaseCapacity` shows 0 (the newest datapoint is 0), then time the first ready probe to the first successful one (retrying every 2 s, 300 s limit), through the owner's own Lambda (`dc2_operation: ready`, a fresh connection and `SELECT 1`). For `shared` the one cluster is probed through the Processing API; for `separate` each cluster through its own domain's API. A cluster that never shows 0 inside the wait is recorded as **not measured**, never as fast. |
| **Warm query latency** | After a settle and three warm-ups, `--samples` (30) sequential ready probes per domain; p50, p95 and max of the successes, failures counted. The probe includes the Lambda invoke and the network path from the operator's station; that overhead is the same in both arms, so the comparison is paired. |
| **Isolation** | With every cluster paused, hold sustained Media probes (`--load-concurrency` 4 for `--load-seconds` 60), then read CloudWatch for **Processing's** cluster: did it leave 0 ACU, and what was its peak. Then Processing's p50/p95 without and with that Media load; the ratio is the slowdown. `shared` is expected to show both effects; the question is whether `separate` shows neither. One direction (Media load, Processing observed) is measured. |
| **ACU-hours and cost** | CloudWatch average ACU per minute for each cluster over the arm's whole window (including `--tail-minutes`, 10, so the billed pause tail is inside it), times the captured ACU rate, plus each cluster's fixed share prorated from `$0.51` a month. Cost Explorer lags a day and cannot split one Aurora line between two clusters, so this is a model on measured ACU. |
| **Migration and restore behaviour** | Notes only, recorded in the receipt and marked not measured: a migration wakes only its own domain's cluster under `separate`; a `shared` cluster restores both databases to one point in time, `separate` clusters independently. Neither a migration timing nor a restore drill is part of this harness. |

The receipt (`evidence-94-<run>.json`, mode 0600) keeps the cluster identifiers private and
screens the public view for identifiers, URLs and secrets. `compare` reads both arms and
changes no AWS state.

### Decision rule (fixed before any measurement)

`compare` computes each line. The change is warranted only if **every** line holds in a live run
(not a simulated one), and even then it only records `merge_decision: pending`.

| Line | Holds when |
|---|---|
| `both_arms_fully_measured` | no cold resume, wake test or slowdown test was recorded as not measured |
| `coupling_observed_when_shared` | the shared cluster woke under the peer's load, or the peer's p95 slowed by more than 1.25x |
| `separate_does_not_wake_the_peer` | with two clusters, Media load left Processing's cluster at 0 ACU |
| `separate_peer_slowdown_within_limit` | Processing's p95 under Media load is at most 1.25x its p95 without |
| `separate_cold_resume_not_slower` | each separate cluster resumed within 15 s of the shared cluster |
| `separate_warm_p95_not_slower` | each domain's warm p95 is at most 1.2x the shared arm's |
| `separate_extra_cost_within_limit` | one more cluster's `$0.51` a month plus the measured extra ACU compute of one such window stays at or under `$2.00` (1% of the `$200` planning envelope; scale the window to real usage) |

Otherwise the V1 default stays, and the redeploy-without-the-flag revert above is all that is
needed. If only the pause or ceiling change is promising, take that alone as a third stack and
read its `configured` block beside the baseline's; it needs no new code.

## Limits and risks

* Aurora's resume time depends on whether it is actually at 0 ACU, and the first real deploy saw
  roughly 15 to 60 s. The harness does not pick a number; it measures per cluster, and
  `WAKE_DEADLINE_SECONDS` in the bootstrap (150 s) already covers a resume for each connection.
* The Lambda security group and the migration security group are shared by both domains, so the
  network gain is limited to keeping the encoder out of Media's cluster.
* A second cluster doubles the managed master credentials that must be kept out of Git and logs;
  the bootstrap input still travels only as a temporary SecureString, never in a public file.
* The isolation test loads Media and observes Processing. The reverse is the same code path and
  is not run, to avoid a second full pause cycle.
* The probe is `SELECT 1` on a fresh connection, not a representative query mix; the warm numbers
  describe connection and round-trip cost, not query planning or data size.
* Cloud evidence is NOT_RUN; every number in a receipt from `--dry-run` or `rehearse` is
  simulated.
