> **Historical (local pre-AWS experiments #38 and #39, both rejected).** Not part of V1. Current plan: [`../aws/architecture-plan.md`](../aws/architecture-plan.md).

# LOCAL experimental follow-ups #38 and #39

Both local experiments are complete and **REJECTED**. Product defaults are
unchanged. The original demo is restored on its exact saved accepted images.
See [STATUS.txt](STATUS.txt) for the final handoff state.
No experimental setting is adopted; no remote publication or AWS operation is
part of this worktree's work.

- [Protocol and thresholds fixed before trials](PROTOCOL.md)
- [#38 decision and every criterion's disposition](EXP38.md)
- [#38 numerical summary](exp38-summary.json)
- [#39 decision and every criterion's disposition](EXP39.md)
- [#39 resource/outcome summary](exp39-summary.json)
- [Indexed compressed raw records](raw/)

The baseline is `b913579be16ca7f1fb9f685e287d905bfbcfbd6a`. Historical acceptance,
the frozen `final-measurements` worktree, earlier failure packs, product defaults,
original academic documents and roadmap design are preserved. These experiments
use separate namespaces and opt-in diagnostics. They do not replace the original
270-job scaling evidence or rewrite accepted targets.

## Reproduce locally

Use the existing project-local 8-CPU/8-GiB/64-GiB Lima instance and selected Docker
helper. Inspect inventory/free disk, then give the run exclusive use of the VM.
Preserve existing volumes and private configuration. Build from clean product
paths; runtime image labels must match the recorded source. Browser decoding uses
the repository's scoped-trust workflow and pinned browser cache.

```sh
# From this worktree, with its Python environment and frontend dependencies ready:
python -m scripts.dev.runtime up --run-id exp38-UNIQUE
python -m scripts.experiments.followups quota --run-id exp38-UNIQUE
python -m scripts.experiments.faults --run-id exp38-UNIQUE --profile baseline
python -m scripts.experiments.faults --run-id exp38-UNIQUE --profile pg-quarter
python -m scripts.dev.runtime down --run-id exp38-UNIQUE

# Start #39 only after the #38 quota decision is resolved:
python -m scripts.dev.runtime up --run-id exp39-UNIQUE
python -m scripts.experiments.followups windows --run-id exp39-UNIQUE
python -m scripts.experiments.faults --run-id exp39-UNIQUE \
  --profile baseline --window-faults --long-drain
python -m scripts.dev.runtime down --run-id exp39-UNIQUE

python -m scripts.experiments.analyze artifacts/RUN/ACTION-TIMESTAMP
python -m scripts.experiments.windows_report artifacts/RUN/windows-TIMESTAMP
python -m scripts.experiments.archive artifacts/RUN docs/execution/DESTINATION
```

Every run ID must be fresh. The harness pins live image IDs, checks the CPU/memory
envelope, rejects competing namespaces, records arrivals/outcomes and stops on
correctness, missing sampling or the preregistered disk/deadline rules. Restore
the original demo after stopping experiments. Do not use global Docker pruning,
remove historical volumes, or publish runtime.env, cookies, signed URLs or DSNs.

## Evidence interpretation

Raw indexes list stored and decompressed SHA-256 hashes and byte lengths.
JSONL/large JSON is deterministically gzip-compressed. Fixtures, images and large
screenshots are not duplicated in Git; exact manifests identify source, images,
fixture generation and configuration. Failed and interrupted runs are retained
and explicitly excluded from complete comparison counts. Exact operator
continuation sources are archived as JSON with source hashes.

SQL timings omit SQL text/parameters. Pool.connect includes pre-ping and creation;
it is not a pure semaphore-wait measurement. Kernel throttle/pressure totals are
cumulative counters; use the recorded sample spans. Memory ceilings are not
reservations and samples do not establish a safe lower limit.

Actual output-prefix enumeration includes every HLS rendition and segment, beyond
the database's primary/master descriptors. API request records and completed
browser response-body transfers have distinct scopes. A decoded playback start
does not measure an entire clip's viewing traffic. Running-host replica residency
is not cloud bill savings. Account/region, retention, availability, full viewing
volume and cloud-specific request/transfer charges still determine an all-in
budget under the unchanged $200 total/about-three-week cap.

[Fresh independent Sol review](../reviews/experiments-20261014-review.md) PASS
at candidate `632cac5`, with no substantive findings. It independently verified
all 248 indexed records and recalculated decision-critical metrics. The coordinator
owns remote publication and exact PR/Main checks. This record does not claim
those checks already passed, and rejection does not become performance acceptance.
