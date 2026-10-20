# Contributing

Use Python 3.12 and follow the Ruff settings in `pyproject.toml`: 100-column lines, four-space
indentation, and the configured import and lint rules. Ruff format is the Python formatter;
short expressions stay compact even when the input has a trailing comma.

Before committing Python changes, run `make lint`, `make format-check`, and `make test`. The first two
commands are local and read-only; `make test` uses the offline fast suite. Format only the files you
change. Add short comments to explain important reasons or invariants, and keep type annotations on
changed public interfaces. Avoid broad lint or formatter suppressions.

Keep released migration files unchanged. Routine formatting excludes migration versions because
deployment compares their bytes with the running release. Format a new migration explicitly before
its first release; use a new migration for later schema changes. Migration lint remains enabled.

`make lint` also runs Ruff security rules on the current runtime, Publisher and deployed bootstrap.
Both lint and formatting cover the CI helpers and V1 image-verification scripts.

For frontend test-tool changes, use a Node version supported by `frontend/package.json`, run
`npm ci`, `npm run test:coverage`, and `npm audit --audit-level=high` from `frontend/`.
CI uses Node 22 and blocks known high or critical findings in this locked development toolchain.

Before publishing workflow edits, run `actionlint -shellcheck= -pyflakes= .github/workflows/*.yml`
(validated with actionlint 1.7.12). This checks GitHub expression contexts and workflow structure;
Python source lint and tests run separately. An invalid workflow can fail before CI creates jobs.
