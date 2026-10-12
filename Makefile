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
        test-media-engine test-publisher up down logs smoke-infra images env status local-tls \
        browser browser-install browser-open browser-trust-smoke capacity-install capacity-start capacity-status capacity-stop capacity-env \
        e2e verify-local evidence-status evidence-scaling evidence-recovery release rollback

help: ## List project commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_ -]+:.*## / {printf "%-24s %s\n", $$1, $$2}' Makefile

setup: ## Install locked Python/frontend dependencies locally; preserve .env
	$(BOOTSTRAP_PYTHON) -m scripts.dev.setup

setup-browser: setup browser-install ## Setup plus parent-managed project-local Firefox

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

test-media: ## Focus Media fast tests once implemented
	$(PYTHON) -m scripts.dev.checks test-python --domain media

test-media-engine: ## Focus shared engine fast tests once implemented
	$(PYTHON) -m scripts.dev.checks test-python --domain media_engine

test-publisher: ## Focus Publisher fast tests once implemented
	$(PYTHON) -m scripts.dev.checks test-python --domain publisher

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
	@test -f scripts/dev/runtime.py || { echo 'scripts/dev/runtime.py is pending foundation runtime integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/runtime.py $@ --run-id "$(RUN_ID)"

local-tls: ## Generate project-local TLS through the parent helper
	@test -f scripts/dev/tls.py || { echo 'scripts/dev/tls.py is pending parent integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/tls.py --run-id "$(RUN_ID)"

browser-trust-smoke: ## Real Firefox trusted positive/untrusted negative through parent helper
	@test -f scripts/dev/browser.py || { echo 'scripts/dev/browser.py is pending parent integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/browser.py trust-smoke --run-id "$(RUN_ID)"

browser-install: ## Install project-local Firefox through the parent helper
	@test -f scripts/dev/browser.py || { echo 'scripts/dev/browser.py is pending parent integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/browser.py install --run-id "$(RUN_ID)"

browser-open: ## Open the project-trusted Firefox profile through the parent helper
	@test -f scripts/dev/browser.py || { echo 'scripts/dev/browser.py is pending parent integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/browser.py open --run-id "$(RUN_ID)"

browser: browser-open ## Open project-trusted Firefox (alias of browser-open)

capacity-install capacity-start capacity-status capacity-stop capacity-env: ## Delegate isolated capacity ACTION
	@test -f scripts/dev/capacity.py || { echo 'scripts/dev/capacity.py is pending parent integration' >&2; exit 2; }
	$(PYTHON) scripts/dev/capacity.py $(patsubst capacity-%,%,$@)

e2e: ## Full HTTPS browser/CLI workflow, supplied by integration wave
	@test -f scripts/dev/e2e.py || { echo 'scripts/dev/e2e.py is pending integration wave' >&2; exit 2; }
	$(PYTHON) scripts/dev/e2e.py --run-id "$(RUN_ID)"

verify-local: doctor lint test coverage smoke-infra browser-trust-smoke e2e ## Full enabled local verification

evidence-status evidence-scaling evidence-recovery: ## Evidence runners supplied by evidence wave
	@test -f scripts/dev/evidence.py || { echo 'scripts/dev/evidence.py is pending evidence wave' >&2; exit 2; }
	$(PYTHON) scripts/dev/evidence.py $(patsubst evidence-%,%,$@) --run-id "$(RUN_ID)"

release rollback: ## Local release/rollback runners supplied by evidence wave
	@test -f scripts/dev/release.py || { echo 'scripts/dev/release.py is pending release wave' >&2; exit 2; }
	$(PYTHON) scripts/dev/release.py $@ --run-id "$(RUN_ID)"
