.DEFAULT_GOAL := help
BOOTSTRAP_PYTHON ?= python3
PYTHON := .venv/bin/python
RUN_ID ?= local
export UV_CACHE_DIR := $(CURDIR)/.cache/uv
export UV_PROJECT_ENVIRONMENT := $(CURDIR)/.venv
export UV_PYTHON_DOWNLOADS := never
export npm_config_cache := $(CURDIR)/.cache/npm
export RUFF_CACHE_DIR := $(CURDIR)/.cache/ruff
export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.local/playwright

.PHONY: help setup setup-browser doctor doctor-infra lint test test-python test-frontend coverage \
        coverage-report integration integration-coverage clean test-app test-processing test-media \
        test-media-engine test-publisher test-cli publisher up down logs smoke-infra images env status local-tls \
        browser browser-install browser-open browser-trust-smoke capacity-install capacity-start capacity-status capacity-stop capacity-env \
        e2e verify-local evidence-status evidence-performance evidence-scaling evidence-recovery evidence-release release rollback

help: ## List project commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_ -]+:.*## / {printf "%-24s %s\n", $$1, $$2}' Makefile

setup: ## Install locked Python/frontend dependencies locally; preserve .env
	$(BOOTSTRAP_PYTHON) -m scripts.dev.setup

setup-browser: setup browser-install ## Setup plus the pinned project browser

doctor: ## Check local tools and installed dependencies without services
	$(PYTHON) -m scripts.dev.doctor

doctor-infra: ## Also diagnose Docker, FFmpeg, TLS and foundation helper availability
	$(PYTHON) -m scripts.dev.doctor --infra

lint: ## Lint all current backend packages, tests, migrations and dev helpers
	$(PYTHON) -m scripts.dev.checks lint

test: ## Fast Python and frontend suites; no real services or live browser
	$(PYTHON) -m scripts.dev.checks test

test-python: ## Fast Python only (network guarded)
	$(PYTHON) -m scripts.dev.checks test-python

test-frontend: ## Frontend regression suite excluding live stack
	$(PYTHON) -m scripts.dev.checks test-frontend

test-app: ## Focus inherited Python regression tests
	$(PYTHON) -m scripts.dev.checks test-python --domain app

test-processing: ## Focus Processing fast tests
	$(PYTHON) -m scripts.dev.checks test-python --domain processing

test-media: ## Focus Media fast tests
	$(PYTHON) -m scripts.dev.checks test-python --domain media

test-media-engine: ## Focus shared engine fast tests
	$(PYTHON) -m scripts.dev.checks test-python --domain media_engine

test-publisher: ## Focus Publisher fast tests
	$(PYTHON) -m scripts.dev.checks test-python --domain publisher

test-cli: test-publisher ## Publisher fast checks (alias)

publisher: ## Run the independent public API CLI: ARGS='--help'
	$(PYTHON) -m publisher $(if $(strip $(ARGS)),$(ARGS),--help)

coverage: ## Collect fast/frontend coverage, enabled real integration, then gate each package
	$(PYTHON) -m scripts.dev.checks coverage

coverage-report: ## Gate explicit current fragments: COVERAGE_INPUTS='path1 path2'
	@test -n "$(COVERAGE_INPUTS)" || { echo 'Set COVERAGE_INPUTS to current data fragments' >&2; exit 2; }
	$(PYTHON) -m scripts.dev.coverage $(foreach file,$(COVERAGE_INPUTS),--data "$(file)")

integration: ## Real isolated integration; requires explicit RUN_* flags/config, unavailable fails
	$(PYTHON) -m scripts.dev.checks integration

integration-coverage: ## Record enabled real integration for combination with fast coverage
	$(PYTHON) -m scripts.dev.checks integration-coverage

clean: ## Remove generated test/lint coverage only; preserve .env/data/venv/browser caches
	$(PYTHON) -m scripts.dev.checks clean

up down logs smoke-infra images env status: ## Delegate isolated runtime ACTION, RUN_ID=local
	$(PYTHON) scripts/dev/runtime.py $@ --run-id "$(RUN_ID)"

local-tls: ## Generate project-local TLS through the parent helper
	$(PYTHON) scripts/dev/tls.py --run-id "$(RUN_ID)"

browser-trust-smoke: ## Trusted positive/untrusted negative in the actual project browser
	$(PYTHON) scripts/dev/browser.py trust-smoke --run-id "$(RUN_ID)"

browser-install: ## Install the pinned browser under this project
	$(PYTHON) scripts/dev/browser.py install --run-id "$(RUN_ID)"

browser-open: ## Open the scoped project browser
	$(PYTHON) scripts/dev/browser.py open --run-id "$(RUN_ID)"

browser: browser-open ## Open the scoped project browser (alias of browser-open)

capacity-install capacity-start capacity-status capacity-stop capacity-env: ## Delegate isolated capacity ACTION
	$(PYTHON) scripts/dev/capacity.py $(patsubst capacity-%,%,$@)

e2e: ## Full HTTPS browser/CLI workflow
	$(PYTHON) -m scripts.dev.e2e --run-id "$(RUN_ID)"

verify-local: ## Fast checks, isolated real integration/coverage, and full client workflows
	$(PYTHON) -m scripts.dev.verify --run-id "$(RUN_ID)"

evidence-status evidence-performance evidence-scaling evidence-recovery evidence-release: ## Measured local experiments; extra options in EVIDENCE_ARGS
	$(PYTHON) -m scripts.dev.evidence $(patsubst evidence-%,%,$@) --run-id "$(RUN_ID)" $(EVIDENCE_ARGS)

release rollback: ## Promote or roll back Processing locally; RELEASE_ARGS supplies options
	$(PYTHON) -m scripts.dev.release $@ --run-id "$(RUN_ID)" $(RELEASE_ARGS)

# V1 uses no legacy runtime or Redis. Override PYTHON only to use an existing
# read-only dependency environment; imports always resolve from this checkout.
V1_RUN_ID ?= v1-$(shell date +%Y%m%d)-local
FLOW ?= all
.PHONY: v1-up v1-down v1-status verify-v1 test-v1
v1-up: ## Start unique PostgreSQL + loopback Moto; no AWS calls
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.dev.v1_runtime up --run-id "$(V1_RUN_ID)"

v1-down: ## Stop only this V1 namespace; retain SQL volume/logs (DELETE_DATA=1 deletes its SQL)
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.dev.v1_runtime down --run-id "$(V1_RUN_ID)" $(if $(filter 1,$(DELETE_DATA)),--delete-data,)

v1-status: ## Show selected V1 namespace; preserve other runtimes
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.dev.v1_runtime status --run-id "$(V1_RUN_ID)"

verify-v1: ## Real dependency/engine A, integrated clients B, lifecycle/release C; FLOW=a|b|c|all
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.dev.v1_runtime verify --run-id "$(V1_RUN_ID)" --flow "$(FLOW)"

test-v1: ## Offline V1 operational contracts; no services/AWS credentials
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m pytest tests/v1 -m "not integration" -q \
		-p scripts.dev.pytest_plugin --offline-fast

# cfn-lint is a lint-only tool kept out of uv.lock. Locally a missing linter is a clean skip;
# CI passes CFN_LINT_ARGS=--require so a missing linter fails.
CFN_LINT_ARGS ?=
.PHONY: lint-cfn test-aws
lint-cfn: ## Render and lint the V1 CloudFormation template offline (no AWS calls)
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.aws.v1.lint $(CFN_LINT_ARGS)

test-aws: ## Offline AWS control-plane suite (fakes only; network guarded)
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m pytest tests/aws -m "not integration and not e2e" -q \
		-p scripts.dev.pytest_plugin --offline-fast

.PHONY: v1-serve
v1-serve: ## Foreground loopback Gateway bridge to integrated actual handlers; V1_PORT=0 allocates
	PYTHONPATH="$(CURDIR)" $(PYTHON) -m scripts.dev.v1_gateway --run-id "$(V1_RUN_ID)" --port "$(or $(V1_PORT),0)"
