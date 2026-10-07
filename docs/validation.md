# Validation scope and reproduction

Executed on the independent Mac checkout with CPython 3.11.16, fork package 3.0.0. Automated financial inputs are synthetic. Explicit manual government-feed checks are recorded below. No real holdings, account, personal user profile or unlicensed fixture was used.

## Commands and results

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
PYTHONPATH=tests/offline_guard .venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
.venv/bin/python -m build --no-isolation
```

Local optional-MCP environment: 44 tests passed; 94% combined statement/branch coverage (coverage.py report rounded to integer), threshold 80%. Ruff lint/format and strict mypy passed. Both sdist and wheel built successfully with the pinned backend. Tests include twelve product acceptance methods, schema checks, actual SDK-v2 tool calls and a real stdio child, multi-process SQLite aggregate budget, cache freshness/provenance, source denial, typed errors, numerical invariants, optional dependency absence, privacy storage and real save-failure handling.

A separately created /tmp core environment installs requirements-dev.txt with --require-hashes and no MCP extra, builds the editable package with --no-build-isolation --no-deps, then runs the same tests with the socket guard. Core results: 42 tests passed and 2 optional MCP tests skipped, 93% combined coverage. The two real MCP tests are explicitly skipped when the extra is absent; this is intentional optional-capability behavior, not a claim of MCP execution in core. The initial isolated editable install exposed a missing editables backend dependency; it was pinned in the build/dev requirements and revalidated. Build isolation is not used for the final quality gate.

Wheel and sdist inspection found retained LICENSE/NOTICE and no .venv, .uv cache/runtime, database, .env or coverage artifacts. LICENSE has no diff from upstream. Dependency exports are produced from uv.lock with exact versions and SHA256 hashes; CI installation accepts official PyPI binary wheels only.

## End-to-end and explicit manual checks

This socket-blocked CLI workflow reads an allowed synthetic local request/evidence/claims file and emits a dossier. It is also asserted in the CLI unit/contract test; the installed wheel demo was verified without indexes or dependencies.

```sh
PYTHONPATH=tests/offline_guard .venv/bin/gsd research examples/research-synthetic.json --now 2026-01-02T16:00:00Z --format short
```

Result: `Research status: answerable; data: ok.` The fact is `Synthetic revenue is 100 units.` with nearby `demo-1` evidence link (`synthetic://fixture/acme`) and observed time `2026-01-02T15:00:00Z`. The full JSON retains original question, evidence reference `synthetic:acme-v1`, independent freshness, supported claim and unresolved scope. This is a deterministic host workflow, not an LLM quality claim or buy signal.

On 2026-10-07, explicit human-authorized minimal public reads used the reviewed new implementation, not historical upstream snippets:

- Treasury: first request returned typed 404 at a misspelled path. Following the [official XML directory](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rate-xml-files) and its linked feed corrected the fixed route to `/resource-center/data-chart-center/interest-rates/pages/xml`. One verification read returned 192 rows for requested year 2026, newest actual data date 2026-10-06, unit `percent`, type `daily_nominal_par`, status `ok`, coverage `requested_year_only`, fetched 2026-10-07T01:40:41.821069+00:00. The wrong route is rejected by an offline regression test; no fallback, mirror or permission evasion was used.
- CFTC: one request with page_size=3/max_pages=1 to the [official 6dca-aqww API](https://publicreporting.cftc.gov/resource/6dca-aqww.json) returned 3 rows, report/observation date 2026-09-29, unit `contracts`, status `partial`, coverage `bounded_partial`, fetched 2026-10-07T01:39:27.423848+00:00. Actual publication instant remains unknown. This does not validate other report types or complete market coverage.

No raw live response, data value table or cache is committed or uploaded. These two checks establish only the recorded sample behavior; they are separate from synthetic CI. SEC and all restricted collectors were not sampled.

## CI

.github/workflows/quality.yml runs core Python 3.11 and 3.13 plus Python 3.11 with the optional MCP extra. Financial tests and MCP subprocesses use the process-level outbound socket guard. Dependency setup uses official PyPI; offline here means tests do not call providers, not that package bootstrap has no network. Actions are pinned to official SHA refs verified on 2026-10-07; repository permission is contents:read, checkout credentials are not persisted, no secrets/live job/pull_request_target or data upload.

The authoritative final-head result is the current PR Checks tab and its linked workflow runs. This document does not embed a self-referential commit SHA or claim a run before it finishes. The delivery message records the precise branch/head/run and conclusion after inspection.

## Not established by these checks

Availability beyond the two bounded samples above, full upstream schema correctness, real SEC identity acceptance, full historical completeness/point-in-time knowability, provider entitlements, exchange-session completion, data redistribution rights, portfolio suitability, LLM reasoning quality, prediction accuracy, investment returns and an exhaustive dependency vulnerability audit were not tested. Cboe/Yahoo policy page extraction failed and their adapters remain blocked. SEC live smoke was not performed because no real operator SEC_CONTACT was supplied. No restricted source was contacted. Online access remains opt-in and is absent from CI.
