# V3 runner corrections for independent review R1–R5

13 October 2026. Branch `work/evidence`; correction base
`ecd9d5f4d5b43cfa2bd40bb1338353e30df7ab59`. These are runner fixes for
`performance-runner-review.md`, ready for independent recheck. Live V3 acceptance
remains open; this lane ran no containers, pilots or experiments.

This note **supersedes the affected warmup, queue, login and cleanup wording in
performance-runner.md**. That earlier handoff is outside this correction's write
scope and remains unchanged. The independent review is included byte-for-byte
(Git blob `32e5b412c7ad5c0bf34b886ee41fcc48a7cca369`).

R1: Before each warmup, stop nonselected owned containers with a bounded ten-second
stop grace period and start the selected existing container. Docker inspect must
show only that replica running in the evidence namespace and no paused known
replicas, both before submission and after completion. Retain its container
hostname and compare it with the completed Attempt's RQ job `worker_name` and the
corresponding RQ worker hash's hostname. Missing/mismatched execution identity
fails visibly; the selected ID is no longer evidence of assignment by itself.
The queue/assignment diagnostics execute read-only inside Processing using its
own Redis credentials. No product worker changes are needed.

R2: Retain `intermediate_attempt_ids` alongside ready and started IDs in every
queue snapshot. Both clean-queue and exact measured-backlog checks reject any
intermediate membership. They never clean registries or remove work. The
regression executes the runner's actual diagnostic against locked RQ/FakeRedis,
puts an old attempt into the intermediate list with `Queue.lmove`, and proves
both checks reject it while the entry remains intact.

R3: Scaling creates no paused state. Cleanup discovers owned worker containers,
uses IDs tracked inside the bounded start call, inspects ownership/state, and
stops/verifies each container individually. It reconciles a discovered paused
state before stopping. Every known replica gets a cleanup attempt even when one
stop/state check fails; failures are retained in `cleanup.jsonl` and reported
after the loop. Cancellation waits for the bounded in-flight mutation, then
executes this cleanup and closes clients. Workers end stopped, matching scaling's
required starting state. Each Docker call remains bounded at 30 seconds; Compose
discovery remains bounded at 120 seconds. Cleanup can extend the action deadline.

R4: Every upload immediately appends `submissions.jsonl` with phase, sequence,
Asset ID (or null for failure), UTC/acknowledgement monotonic time, actual elapsed
milliseconds, HTTP status and safe error category. Earlier acknowledgements
survive a later upload failure. The first acknowledgement's captured clock also
starts makespan, so artifact-writing time remains included. Private observations
and owner-preparation HTTP samples go to `operations.jsonl` before checked HTTP
errors can escape. Login rows are retained before logout; logout has its own
untimed row with repeat/client/sequence, real status/elapsed/error and the parent
interval's timed/warmup flag. Logout never rewrites the login outcome or latency.
Bodies, credentials, cookies, tokens and URLs are not selected.

R5: Every login repeat's proposal target assessment is strictly p90 <2000 ms.
Login request errors, warmup errors and logout errors are reported explicitly;
none supplies a numeric proposal error threshold. Invalid owner/session/status
protocol observations are separately labelled in `protocol_errors` and
`protocol_eligible`; failed preparation still aborts with retained samples.
Status warmup preparation errors also remain ineligible. `criteria_pass` evaluates
only the proposal's numeric thresholds, while `acceptance_eligible` additionally
requires the full repetition protocol and valid preparation/session protocol.
The CLI exits 1 for an invalid protocol independently of numerical target results.
Ordinary failed login/logout responses alone do not impose a new grading gate.
Status still requires p90 <=700 ms and strictly <1% timed errors; scaling still
requires zero failed jobs and the original speedup/queue-wait targets.

Parent interface notes: pure helper signatures are unchanged. R5 changes
`latency_metrics(..., "login")["errors_pass"]` from a Boolean zero-error gate to
**null**, meaning no specified error target; callers must assess login with
`latency_pass`. Status retains its Boolean `errors_pass`. Internal async helpers
add optional artifact/context keywords; upload still returns the Asset ID string,
Processing reads still return selected records, and latency phases still return
only the timed topic's samples. `Client.checked` preserves its data return and
safe exception behavior and accepts optional `artifacts`/`record` keywords.
Queue snapshot consumers must include the new intermediate field. No parent
Make, Compose, CI, production or private runtime configuration was edited.

The full workload remains nine rotated runs, 30 fresh identical 60-second 720p
Assets per run, and 18 individual replica warmups. Worker caps remain 2 CPU /
1536 MiB; eight persistent nonworkers total 2 CPU. All workers are already stopped
before the measured backlog and restarted for the timed batch, so the warmup
isolation change preserves that existing measured startup protocol.

Validation from this worktree using the root virtual environment:

```text
$ /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/evidence tests/evidence/test_performance.py -q --timeout=5
...............................................................          [100%]
63 passed in 0.67s

$ /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest -p scripts.dev.pytest_plugin --offline-fast --confcutdir=tests/evidence tests/evidence/test_performance.py -q --timeout=5
...............................................................          [100%]
63 passed in 0.75s

$ /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff check scripts/evidence tests/evidence/test_performance.py
All checks passed!

$ /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m scripts.evidence.performance --help
usage: performance.py [-h] --run-id RUN_ID [--repeats REPEATS] [--pilot] ... {performance,scaling}
[exit 0; remaining option descriptions printed normally]

$ git diff --check
[no output; exit 0]
```

All original 48 test cases remain, with the scheduling test upgraded to model
already-issued blocking dequeues independently of container execution state.
Fifteen additional cases cover incorrect warmup assignment, cancellation inside
actual scaling isolation, continued cleanup after a replica fails, partial-upload
identity retention, real RQ intermediate/assignment diagnostics, failed private
HTTP samples, 50/20 mocked concurrent requests, independent logout 503 rows,
proposal-only login assessment, and protocol eligibility/CLI reporting.
Mock intervals and latency values are test data, never performance evidence.

Parent owns independent correction review, the bounded live pilot, final image /
configuration verification, and the full performance/scaling experiments.
