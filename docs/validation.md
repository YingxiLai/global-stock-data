# Validation scope and reproduction

Executed on the independent Mac checkout with CPython 3.11.16, fork package 3.0.0. All financial inputs are synthetic. No live market-data endpoint, real holdings, account, personal user profile or unlicensed fixture was used.

## Commands and results

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
PYTHONPATH=tests/offline_guard .venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
python -m build --no-isolation
```

Local optional-MCP environment: 42 tests passed; 94% combined statement/branch coverage (coverage.py report rounded to integer), threshold 80%. Ruff lint/format and strict mypy passed. Both sdist and wheel built successfully with the pinned backend. Tests include twelve product acceptance methods, schema checks, actual SDK-v2 tool calls and a real stdio child, multi-process SQLite aggregate budget, cache freshness/provenance, source denial, typed errors, numerical invariants, optional dependency absence, privacy storage and real save-failure handling.

A separately created /tmp core environment installs requirements-dev.txt with --require-hashes and no MCP extra, builds the editable package with --no-build-isolation --no-deps, then runs the same tests with the socket guard. The two real MCP tests are explicitly skipped when the extra is absent; this is intentional optional-capability behavior, not a claim of MCP execution in core. The initial isolated editable install exposed a missing editables backend dependency; it was pinned in the build/dev requirements and revalidated. Build isolation is not used for the final quality gate.

Wheel and sdist inspection found retained LICENSE/NOTICE and no .venv, .uv cache/runtime, database, .env or coverage artifacts. LICENSE has no diff from upstream. Dependency exports are produced from uv.lock with exact versions and SHA256 hashes; CI installation accepts official PyPI binary wheels only.

## CI

.github/workflows/quality.yml runs core Python 3.11 and 3.13 plus Python 3.11 with the optional MCP extra. Financial tests and MCP subprocesses use the process-level outbound socket guard. Dependency setup uses official PyPI; offline here means tests do not call providers, not that package bootstrap has no network. Actions are pinned to official SHA refs verified on 2026-10-07; repository permission is contents:read, checkout credentials are not persisted, no secrets/live job/pull_request_target or data upload.

The authoritative final-head result is the current PR Checks tab and its linked workflow runs. This document does not embed a self-referential commit SHA or claim a run before it finishes. The delivery message records the precise branch/head/run and conclusion after inspection.

## Not established by these checks

Live endpoint availability, current upstream schema correctness, real SEC identity acceptance, full historical completeness/point-in-time knowability, provider entitlements, exchange-session completion, data redistribution rights, portfolio suitability, LLM reasoning quality, prediction accuracy, investment returns and an exhaustive dependency vulnerability audit were not tested. Cboe/Yahoo policy page extraction failed and their adapters remain blocked. No online smoke was performed; the CLI has explicit opt-in commands for a separately configured operator to run later.
