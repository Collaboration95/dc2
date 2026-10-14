# Lean AWS implementation handoff — 15 October 2026

Readiness analysis and real GitHub backlog; application/cloud implementation remains future. Source inspected: `af0b21e3c10d6ad62a77549756787eac738e83b5` on Main. No AWS/Alibaba operation, cloud account access, product change or live workload was performed.

[Project 14](https://github.com/users/Collaboration95/projects/14) is reused; historical 30 closed issues and Done items stay intact. Four epics and 24 new children have stable AWS keys, native parent/blocking links and existing Project fields. The seven Ready issues are local adapters/definitions; actual cloud work remains gated.

The default remains separate Media/Processing images and owned DBs, three Fargate services, at most three disposable 2-vCPU / 4-GiB workers, t3a.small only PostgreSQL/Redis/nginx, one public subnet/AZ/free S3 gateway, private regional S3 and generated CloudFront HTTPS. No NAT/ALB/paid domain/interface endpoints or mandatory starter. Shared state/gateway/AZ failures are explicit.

## Epics and execution order

### [#41](https://github.com/Collaboration95/dc2/issues/41) Native credentials and owned S3 storage

- [#47](https://github.com/Collaboration95/dc2/issues/47) Wire refreshing ECS credentials into Media storage — **Ready**; dependencies: none.
- [#48](https://github.com/Collaboration95/dc2/issues/48) Wire ECS writer and cleanup credentials into Processing — **Ready**; dependencies: none.
- [#49](https://github.com/Collaboration95/dc2/issues/49) Bound signed URL lifetime to the credentials actually used — **Backlog**; dependencies: [#47](https://github.com/Collaboration95/dc2/issues/47).

### [#42](https://github.com/Collaboration95/dc2/issues/42) Minimal infrastructure and zero-compute downtime

- [#45](https://github.com/Collaboration95/dc2/issues/45) Record project-account, budget, window and deletion authorization — **Blocked**; dependencies: none.
- [#46](https://github.com/Collaboration95/dc2/issues/46) Resolve the proposal interpretation of CloudFront origin HTTP — **Blocked**; dependencies: none.
- [#50](https://github.com/Collaboration95/dc2/issues/50) Define one-subnet state, storage and IAM infrastructure offline — **Ready**; dependencies: none.
- [#51](https://github.com/Collaboration95/dc2/issues/51) Bootstrap only PostgreSQL, Redis and nginx on retained EBS — **Backlog**; dependencies: [#50](https://github.com/Collaboration95/dc2/issues/50).
- [#52](https://github.com/Collaboration95/dc2/issues/52) Define three services, owner migrations and disposable worker tasks — **Backlog**; dependencies: [#50](https://github.com/Collaboration95/dc2/issues/50), [#47](https://github.com/Collaboration95/dc2/issues/47), [#48](https://github.com/Collaboration95/dc2/issues/48).
- [#53](https://github.com/Collaboration95/dc2/issues/53) Configure CloudFront and nginx for private authenticated API traffic — **Backlog**; dependencies: [#50](https://github.com/Collaboration95/dc2/issues/50), [#46](https://github.com/Collaboration95/dc2/issues/46).
- [#61](https://github.com/Collaboration95/dc2/issues/61) Open and close sessions with complete task and IP accounting — **Backlog**; dependencies: [#51](https://github.com/Collaboration95/dc2/issues/51), [#52](https://github.com/Collaboration95/dc2/issues/52), [#53](https://github.com/Collaboration95/dc2/issues/53), [#57](https://github.com/Collaboration95/dc2/issues/57), [#58](https://github.com/Collaboration95/dc2/issues/58).
- [#62](https://github.com/Collaboration95/dc2/issues/62) Export both owned databases at one quiescent boundary — **Backlog**; dependencies: [#61](https://github.com/Collaboration95/dc2/issues/61).

### [#43](https://github.com/Collaboration95/dc2/issues/43) Independent releases and bounded worker execution

- [#54](https://github.com/Collaboration95/dc2/issues/54) Bind amd64 owner artifacts to tests, scans and ECR digest receipts — **Ready**; dependencies: none.
- [#55](https://github.com/Collaboration95/dc2/issues/55) Cover extracted services in delivery scans and report execution honestly — **Ready**; dependencies: none.
- [#56](https://github.com/Collaboration95/dc2/issues/56) Start at most three worker tasks with one serialized operator — **Ready**; dependencies: none.
- [#57](https://github.com/Collaboration95/dc2/issues/57) Bound cloud worker lifetime and warm-drain before StopTask — **Backlog**; dependencies: [#56](https://github.com/Collaboration95/dc2/issues/56).
- [#59](https://github.com/Collaboration95/dc2/issues/59) Promote and roll back Processing alone on ECS — **Backlog**; dependencies: [#52](https://github.com/Collaboration95/dc2/issues/52), [#54](https://github.com/Collaboration95/dc2/issues/54), [#57](https://github.com/Collaboration95/dc2/issues/57), [#58](https://github.com/Collaboration95/dc2/issues/58).
- [#60](https://github.com/Collaboration95/dc2/issues/60) Release Media API and reconciler without changing Processing — **Backlog**; dependencies: [#59](https://github.com/Collaboration95/dc2/issues/59).
- [#68](https://github.com/Collaboration95/dc2/issues/68) Optional unattended starts and further cost cuts — **Optional**; dependencies: [#57](https://github.com/Collaboration95/dc2/issues/57).

### [#44](https://github.com/Collaboration95/dc2/issues/44) Small authentic cloud evidence and closeout

- [#58](https://github.com/Collaboration95/dc2/issues/58) Add a small cloud client and safe evidence context — **Ready**; dependencies: none.
- [#63](https://github.com/Collaboration95/dc2/issues/63) Bootstrap the approved environment and prove public workflow boundaries — **Blocked**; dependencies: [#45](https://github.com/Collaboration95/dc2/issues/45), [#46](https://github.com/Collaboration95/dc2/issues/46), [#49](https://github.com/Collaboration95/dc2/issues/49), [#48](https://github.com/Collaboration95/dc2/issues/48), [#51](https://github.com/Collaboration95/dc2/issues/51), [#52](https://github.com/Collaboration95/dc2/issues/52), [#53](https://github.com/Collaboration95/dc2/issues/53), [#54](https://github.com/Collaboration95/dc2/issues/54), [#57](https://github.com/Collaboration95/dc2/issues/57), [#58](https://github.com/Collaboration95/dc2/issues/58), [#61](https://github.com/Collaboration95/dc2/issues/61).
- [#64](https://github.com/Collaboration95/dc2/issues/64) Show 1/2/3 task capacity and bounded recovery using six long uploads — **Blocked**; dependencies: [#63](https://github.com/Collaboration95/dc2/issues/63).
- [#65](https://github.com/Collaboration95/dc2/issues/65) Capture both owner releases and real failed-candidate rollback on AWS — **Blocked**; dependencies: [#63](https://github.com/Collaboration95/dc2/issues/63), [#64](https://github.com/Collaboration95/dc2/issues/64), [#59](https://github.com/Collaboration95/dc2/issues/59), [#60](https://github.com/Collaboration95/dc2/issues/60), [#55](https://github.com/Collaboration95/dc2/issues/55).
- [#66](https://github.com/Collaboration95/dc2/issues/66) Measure one bounded status/login cycle on a separate generator — **Blocked**; dependencies: [#63](https://github.com/Collaboration95/dc2/issues/63).
- [#67](https://github.com/Collaboration95/dc2/issues/67) Reconcile costs, prove zero compute, and hand off bounded teardown — **Blocked**; dependencies: [#64](https://github.com/Collaboration95/dc2/issues/64), [#65](https://github.com/Collaboration95/dc2/issues/65), [#62](https://github.com/Collaboration95/dc2/issues/62), [#66](https://github.com/Collaboration95/dc2/issues/66).

## Next concrete change

Start [#47](https://github.com/Collaboration95/dc2/issues/47): use the existing MinIO credential provider in both Media storage clients and its reconciler, preserve static local MinIO, and verify token A→B refresh/missing-provider/ordinary-request/presign behavior with dummy credentials and guarded HTTP. No AWS account is needed for this implementation and offline verification. The dependent presign-expiry issue then binds lifetime to the same credential snapshot.

Parallel Ready work includes Processing credentials, core definitions, image delivery, extracted-service scan disposition, serialized manual worker batches and cloud smoke/evidence context. Dependency-bearing changes wait for their owning contracts; optional automation is excluded.

## Deployment blockers and critical path

External prerequisites are [#45](https://github.com/Collaboration95/dc2/issues/45) (actual project account/access, currency/spending/window/quota and export/deletion owner) and [#46](https://github.com/Collaboration95/dc2/issues/46) (proposal interpretation of the restricted HTTP origin). Viewer HTTPS is not end-to-end TLS. Resolve those inputs without delaying offline work.

Credentials/definitions/artifact/cloud-context/manual-start work → state/task/edge + finite lifetime/drain → owning release/lifecycle + quiescent export → authorized public workflow → six-job capacity/recovery and one serial status/login cycle → both-owner release proof → cost/closeout. Live evidence tickets stay Blocked, even with dependency-ready local code.

Maximum 14 elapsed days stays anchored to 15 October 2026, no later than the corresponding 29 October checkpoint; presentation 26 October is the nearer rehearsal milestone. No fresh two-week schedule is created by later execution. Expected 20 core / 2 cumulative worker-task hours, larger 40 / 8, include pull/startup/propagation/drain/retry/overlap.

Offline arithmetic reproduces $6.03 usage/$13.03 with reserves and $13.27/$28.27 larger. $15/$30 USD targets are forecasts, not caps or spending approval. Retained ≈$1.73 across 14 days is already in totals. Original captured price inputs remain assumptions until actual account/currency/billing reconciliation.

Six ~21-MB long uploads occur only in fixed prewarmed 1/2/3-worker batches; short workflow checks share ≈0.25 GB total uploads. Reuse assets and stored sources for retry/release/ownership. The small sample proves placement/concurrent claims, never full throughput speedup. One bounded 50-status / 180-s and 20-login cycle uses the separately priced short-lived generator. Original local targets/raw provenance and38/39rejections stay unchanged.

Close means every service/deployment/standalone worker/migration/generator/restore/candidate task is STOPPED, all three desired counts 0, EC2 stopped, public IP released, no EIP and generator volume deleted. Wake uses current public DNS→CloudFront update/deployed readiness. Stopping retains storage charges; destructive teardown needs the named export/deletion authorization.

## Evidence and independent audit

[Gap synthesis and dispositions](gap-analysis.md), [backlog contracts](backlog.json), [actual issue/Project map](github-map.json), [fresh remote-state evidence](remote-state.json), [task ledger](task-ledger.json), [source provenance](provenance.json), and lane reports [A](lanes/a-storage.md), [B](lanes/b-placement.md), [C](lanes/c-lifecycle.md), [D](lanes/d-delivery.md).

The fresh independent standard-tier/high Sol [audit](audit-sol.md) returned **PASS for readiness and backlog**, with deployment still blocked by #45/#46. It independently inspected code, verified the captured hashes/cost arithmetic, and reconciled all 28 remote issues and relationships. No substantive correction round was needed. The minor supplemental optional-starter label was corrected without geometry or roadmap changes. This PASS certifies the plan, not AWS implementation or expenditure.

The user subsequently authorized a persistent preparation-only implementation goal, an integration branch and grouped subagents. No AWS deployment/operation is authorized; local emulation will be labeled separately from authentic cloud evidence. The implementation cycle is tracked independently from this frozen planning snapshot.
