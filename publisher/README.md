# Publisher

Independent client of Media's public HTTPS API. It uses the same cookie session
as the browser and imports no application, service, database or storage code.
HTTPX is its only declared runtime dependency. Python 3.12 or newer is required;
the private state lock uses POSIX `flock` (macOS/Linux).

From the repository, run `python -m publisher --help`. Install separately with
`uv tool install ./publisher` to obtain the `publisher` console command. It also
builds as a standalone wheel with `uv build --wheel ./publisher`. Root packaging
can optionally expose `publisher = "publisher.cli:main"`.

Use the HTTPS public origin **including `/api`**, the project-generated CA, and a
private cookie jar dedicated to that local run. All global options precede the
command. Replace the port/CA paths below with the runtime helper's safe state.

```sh
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json register 22222222-2222-4222-8222-222222222222@example.com
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json login 22222222-2222-4222-8222-222222222222@example.com
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json publish ./videos --wait --max-polls 60 --interval 2
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json status ASSET_UUID
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json output ASSET_UUID
python -m publisher --base-url https://localhost:PORT/api --ca-file .local/runs/RUN/tls/ca.crt --cookie-jar .local/publisher/RUN/cookies.txt --json retry ASSET_UUID --wait
```

Passwords are prompted with echo disabled. For automation, `register` and `login`
accept `--password-stdin`, which reads one line without putting a password in argv.
Cookies are persisted, including Secure session cookies, in an atomic mode-0600
Mozilla cookie jar. System trust is used when no CA file is supplied; certificate
and hostname verification are always enabled. Redirects are not followed and
proxy/environment overrides are disabled.

`publish` visits immediate regular files in name order, skips directories and
symlinks, and reports every attempted file, including unsupported files. Each
file has its own UUID intent key. Pending keys are atomically saved beside the
cookie jar, scoped by API base and authenticated owner, and indexed by filename,
byte length and SHA-256. Rerunning after uncertain HTTP delivery uses the same key
and reopens the file stream. Confirmed acceptance or a definitive rejection clears
the pending key. A later publish of an already confirmed file is a new user intent;
this is not a directory synchronization tool. A new retry after confirmed
acceptance is also a new intent; `retry --intent-key UUID` can explicitly replay
an earlier retry. Retry sends no body or source file.

A 401 during an unresolved mutation retains its pending key. Log in again using
the same cookie jar, then rerun the publish/retry command as the same owner with
the original file contents. Another owner's login uses separate intent identities
and cannot consume that pending key. Changed file contents create a new intent.

`--json` prints one document to stdout. Mutation outcomes include `ok`, `job_id`
on acceptance, and `intent_key`. A batch returns `files`, each with a filename
and outcome. Without `--wait`, success means durable acceptance. With `--wait`,
success requires `done`; a failed attempt or exhausted poll budget returns exit 1.
Read-status 503 is treated as unavailable within the same bounded budget rather
than a fabricated processing state. The default is 60 requests, two seconds
between them, with a 20-second timeout per HTTP request; no automatic endless
transport retry exists. Use `status` again when a budget expires.

If local journal cleanup or final cookie saving fails after acceptance, JSON keeps
the confirmed `job_id`, `intent_key` and every batch file outcome, adds a safe
`state_error`, and returns exit 1. Check the confirmed IDs before publishing again.
A failed journal cleanup retains its original key for replay, including after
later files save successfully; cookie-save failure preserves the completed results.

Exit codes: 0 success; 1 failed, partial or incomplete result; 2 invalid arguments.
`output` fetches fresh owner-authorised MP4/HLS links without downloading or
playing media. Those links are requested output capabilities, not permanent
identifiers. Arbitrary server error bodies, passwords and authentication tokens
are excluded from normal output. There is no player or delete command.

V1 uses `--base-url https://<frontend-host>/api/media`. `publish` hashes each file,
reserves an owned S3 POST, sends bytes with a separate cookie-free HTTP client and
finalizes the reservation. Keep the private intent file to replay uncertain
responses. Storage must use normal HTTPS trust or the explicitly supplied CA;
redirects are refused. No file body crosses the domain API.

Edit and delete use the same public owner checks:

```sh
python -m publisher --base-url "$MEDIA_API" edit "$ASSET_ID" \
  --operations '[{"operation":"clip","params":{"start":0,"end":5}}]' --wait
python -m publisher --base-url "$MEDIA_API" delete "$ASSET_ID"
```

The old `PublicClient.legacy_upload` method exists only for frozen pre-Gateway
regression tests. V1 publishing always uses reserve/upload/finalize.

## Integrator contract

The HTTP contract this client speaks is published as generated OpenAPI 3.1 documents:
[`docs/api/media.openapi.json`](../docs/api/media.openapi.json) (base `/api/media`) and
[`docs/api/processing.openapi.json`](../docs/api/processing.openapi.json) (base `/api/processing`).
They are built from the V1 applications under the Gateway's own path prefixes and mark which
routes need the `access_token` session cookie. A fast test fails when they drift, and
`python -m scripts.dev.openapi` regenerates them. The documents under
`project-roadmap/design/05-contracts/` describe the pre-V1 routes and are not the integrator
contract.
