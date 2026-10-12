# Media grouped validation

M1/M2/M3 (#15/#16/#17) are ready for independent-review reconciliation and remote
checks. Product head tested here: `cd3350f` on `wave/02-media`.

- Full fast Python:770 passed in5.19s; lint passed.
- Isolated real integration:44 inherited,45 Processing and38 Media tests passed;
  no selected skips. The helper applies migrations as foreground one-shot commands
  and runs all owned suites against private PostgreSQL/Redis/MinIO namespaces.
- Combined coverage: Media98.19% (raw branches96.02%), Processing98.32%
  (93.68%), media engine99.42% (98.00%), inherited app93.16% (87.04%).
- `make up RUN_ID=local`: live Media, independent migrations, Processing/worker,
  both recovery processes, TLS gateway, role isolation and storage smoke pass.
- Independent initial review identified uncertain-write cleanup losing authority.
  The additive `media_0002` migration and retained cleanup state correct this;
  independent R1 rereview is PASS in media-rereview.md. Real regression tests
  cover delayed upload/edit PUTs, repeated cleanup and healthy source protection.
- A measured login diagnostic improved from about12s p90 to0.985s/1.044s for
  20 simultaneous valid logins, all200. Cost-10 bcrypt and Media1CPU retain basic
  auth and the total2CPU nonworker budget. Existing hashes still verify. These
  are diagnostic bursts, not the full-duration V3 acceptance experiment.

Raw coordinator logs: `.cache/execution/media-current-{fast,owned,gate}.log`
and `media-runtime.log`. Detailed measured login samples and context are in
login-performance.md. Full browser/CLI and final fault/load/release evidence are
separate V1–V4 work. No cloud or inherited Alibaba resources were operated.
