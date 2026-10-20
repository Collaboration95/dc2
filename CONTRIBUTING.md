# Contributing

Use Python 3.12 and follow the Ruff settings in `pyproject.toml`: 100-column lines, four-space
indentation, and the configured import and lint rules. Ruff format is the Python formatter.

Before committing Python changes, run `make lint`, `make format-check`, and `make test`. The first two
commands are local and read-only; `make test` uses the offline fast suite. Format only the files you
change. Add short comments to explain important reasons or invariants, and keep type annotations on
changed public interfaces. Avoid broad lint or formatter suppressions.

`make lint` also runs Ruff security rules on the current runtime, Publisher and deployed bootstrap.
Both lint and formatting cover the CI helpers and V1 image-verification scripts.
