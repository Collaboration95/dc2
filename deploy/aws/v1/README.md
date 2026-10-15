# DC2 V1 infrastructure

This directory is V1. Historical `deploy/aws/environment.json` and
`scripts/aws/definitions.py` remain unchanged AWS2 preparation.

Render offline from the repository root:

```sh
PYTHONPATH="$PWD" python -m scripts.aws.v1.config \
  --config deploy/aws/v1/config.example.json --output-dir .cache/v1-render
cfn-lint .cache/v1-render/template.json --regions ap-southeast-1
PYTHONPATH="$PWD" python -m pytest tests/aws/v1/test_infrastructure.py -q
```

The example contains dummy account references and creates no resources. Copy it
to an ignored private config, set the explicitly authorized account/environment,
and retain only SSM **ARN references**. Never put credentials or DSN values in
render config, templates, parameters, source control or public evidence. The
renderer rejects secret-bearing fields, shared DB parameters, cross-account
images/references and mutable image tags. It neither imports an SDK nor discovers
credentials. `config.schema.json` documents the public input shape; Python adds
cross-field/account ownership validation.

## Operator deployment sequence

Only the assigned AWS operator applies resources. This helper's checks make zero
AWS calls. Use the dedicated project profile, explicit Singapore region and the
verified account; do not run inherited AWS2 deploy paths.

1. Review current regional engine orderability, service quotas and cost inputs.
   Default PostgreSQL **16.8** comes from the operator's actual Singapore inventory;
   16.6 was unavailable. Verify minimum-zero Serverless v2 support at apply time.
2. Provision foundation with `deploy_applications=false`, `session_open=false`.
   Set all five future SSM parameter ARNs to distinct project paths; their secret
   values are not needed for this phase. The generated template is larger than
   CloudFormation's inline 51,200-byte limit: use the operator's private encrypted
   template-staging bucket, not a public URL. CloudFormation requires IAM capability
   when applications are enabled. Preserve the full original parameters on updates.
3. Read foundation outputs. Upload the existing built frontend to its private
   bucket. Set `source_cors_origin` to the generated `FrontendUrl` (a provisional
   `https://example.invalid` deliberately grants no useful browser origin before
   this update). Keep the root frontend appearance unchanged.
4. Bootstrap the two logical DBs and role grants with the separate private bootstrap
   procedure below; publish four owner-specific DSNs and JWT key as private SSM
   SecureStrings under exactly the configured paths. Use AWS-managed SSM encryption;
   a custom CMK requires a separately scoped KMS policy change. Only the bootstrap
   operator may obtain Aurora's generated master secret. No runtime role can.
5. Build/scan/push distinct Media, Processing and worker images to the emitted
   immutable ECR repositories using C2's release tooling. Include the verified RDS
   CA at `/opt/rds/global-bundle.pem`. Configure all three digest-pinned image URIs
   and `deploy_applications=true`, keeping the session closed. Images are explicit
   parameters; the stack never deploys an arbitrary dummy/placeholder image.
6. Run each owner's migration task in public task subnets with a temporary public
   IPv4 address and the migration SG. Use its own migration DSN only. Check real
   negative cross-database/DDL tests before intake. Migration tasks must complete
   before encoder batches: the observed Fargate quota was only six vCPUs.
7. Open only through Lead C's bounded session controls after readiness and quotas
   pass. Default reserved concurrency is zero; no unbounded fallback is selected.
   The operator observed account Lambda concurrency **10**, which cannot support
   positive reservations with AWS's minimum unreserved pool. Resolve that quota
   prerequisite before opening; infrastructure-only deployment can proceed.

No ECS service, autoscaler or automatic worker starts exist. `WorkerTaskDefinitionArn`
is one finite 2-vCPU/4-GiB task; Lead C's inventory/journal gate enforces cap three,
including unresolved launches. `DC2_WORKER_CAP=3` is documentary process input,
not an ECS-enforced quota. The worker command must receive an absolute
`--deadline-epoch` and unique `--name` from the launcher before RunTask. Late work
remains queued until another explicitly authorized operator batch.

## Interfaces and permissions

Two explicit HTTP API payload-v2 integrations own `/api/media/*` and
`/api/processing/*`. The Media authorizer has TTL zero and supplies canonical
`dc2-gateway-v1` actor context. Only health and Media POST register/login/logout
bypass auth. Lambda resource policies permit only the specific API/authorizer
integration. All functions have separate scoped roles and log groups. Each domain
artifact includes its own API/control/repair functions and initial `live` aliases;
C2 releases promote the full owning function map independently.

Handler defaults are `media.lambda_handler.handler` / `.authorizer`,
`processing.lambda_handler.handler`, `processing.handlers.command_handler`,
`media.handlers.result_handler` / `.repair_handler`, and
`processing.handlers.repair_handler` / `.ecs_handler` / `.s3_handler`. Override
handler names explicitly through `handlers` only when updating the artifact contract.

`MEDIA_POSTGRES_DSN_PARAMETER_ARN` / `PROCESSING_POSTGRES_DSN_PARAMETER_ARN`
and `MEDIA_JWT_SECRET_PARAMETER_ARN` are runtime-support loader references.
Storage uses existing `*_MINIO_ENDPOINT`, `*_MINIO_USE_SSL`, `*_MINIO_REGION`,
`*_MINIO_OUTPUT_BUCKET`, `MEDIA_MINIO_SOURCE_BUCKET` names; credential mode is
`lambda` for handlers and `ecs` for tasks. No access keys or peer DSNs are injected.
SQL uses `*_POSTGRES_SSL_CA=/opt/rds/global-bundle.pem`; handlers set
`*_RUNTIME_MODE=lambda`. The corresponding runtime loader must dispose invocation
connections so Aurora can pause; infrastructure alone cannot establish that.

Three Standard queues have seven-day retention, 20-second long polls and matching
14-day DLQs. Commands and results have Lambda batch-partial mappings; work is
consumed directly by finite Fargate tasks, so it has **no Lambda mapping**. Only
Media repair publishes commands; only Processing command/repair/ECS handlers
publish work/results after durable owned outboxes commit. Public APIs and workers
cannot SQS-send. Workers may GET source versions and PUT outputs, never mutate
source objects or read Media DB parameters. Explicit queue denies also constrain
producers/consumers. The repair tick runs each minute during open sessions; ECS
terminal and output-created events are bounded recovery hints. Closed sessions
disable all four rules and both mappings; Lead C controls concurrency and drain.

Private dual-stack Lambda/DB subnets span two AZs. Lambda SDK traffic uses
`AWS_USE_DUALSTACK_ENDPOINT=true` and IPv6 egress-only routing. Private subnets
have no IPv4 default route; the free S3 gateway provides the only IPv4 HTTPS route.
Public worker/migration tasks use transient IPv4 to pull images/retrieve secrets,
plus narrow SG-to-SG private PostgreSQL access. There is no NAT, paid endpoint,
ALB, Redis, nginx, EC2 application host or Batch dependency. S3 gateway IAM allows
only the two data buckets; frontend uses CloudFront OAC. Buckets are private,
TLS-only, encrypted, versioned and retained. Sources support POST CORS only for
the exact generated frontend HTTPS origin; output GET/HEAD CORS supports playback.
CloudFront forwards `/api/*` to HTTPS Gateway, forwards cookies/query/authorization,
excludes the viewer Host header and disables API caching.

## Required live proof (not passed by local tests)

- Verify two-AZ IPv6 Lambda SSM/SQS/ECS DNS/connectivity and S3 gateway traffic,
  native rotating credentials and verified database TLS; no unexpected IPv4 path.
- Bootstrap/migrate both owners and demonstrate cross-DB, runtime-DDL and
  source-write denials, queue injection/consume denials and authorizer spoof denial.
- Demonstrate direct POST constraints, checksum/version adoption, exact-origin CORS,
  cookie roundtrip through CloudFront HTTPS and independent CLI normal TLS trust.
- Verify real partial batches, duplicate/reordered delivery, bounded repair,
  120s lost-work / 300s interrupted recovery and late-output cleanup.
- Prove finite task/watchdog exit and cap-three unresolved-launch accounting.
- Release one owner independently and exercise failed-candidate rollback.
- Close/drain, observe all function reservations at zero, both mappings/four rules
  disabled, no running tasks, then measure actual Aurora zero ACUs after five
  connection-free minutes. Maintenance can wake Aurora; storage/CDN can still bill.
- Retain actual cost/close receipts. Local render/policy/lint checks are not cloud,
  IAM, pause, latency, recovery or throughput evidence. #45/#63–#67 remain open.
