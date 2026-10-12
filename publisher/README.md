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

`--json` prints one document to stdout. Mutation outcomes include `ok`, `job_id`
on acceptance, and `intent_key`. A batch returns `files`, each with a filename
and outcome. Without `--wait`, success means durable acceptance. With `--wait`,
success requires `done`; a failed attempt or exhausted poll budget returns exit 1.
Read-status 503 is treated as unavailable within the same bounded budget rather
than a fabricated processing state. The default is 60 requests, two seconds
between them, with a 20-second timeout per HTTP request; no automatic endless
transport retry exists. Use `status` again when a budget expires.

Exit codes: 0 success; 1 failed, partial or incomplete result; 2 invalid arguments.
`output` fetches fresh owner-authorised MP4/HLS links without downloading or
playing media. Those links are requested output capabilities, not permanent
identifiers. Arbitrary server error bodies, passwords and authentication tokens
are excluded from normal output. There is no player or delete command.
