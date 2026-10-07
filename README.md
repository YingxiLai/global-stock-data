# Global Stock Data — evidence-first research

Public Apache-2.0 fork of [simonlin1212/global-stock-data](https://github.com/simonlin1212/global-stock-data), rebuilt as a versioned Python package and conversation-first investment **research** assistant. Upstream baseline: `5f27525709ab043b91e53d7a420ce6d46e66a0ce` (Skill 2.0.3). This fork is 3.0.0 and intentionally breaks copy/paste snippet compatibility.

The default path is offline, requires no account, and uses synthetic examples. SEC, Treasury and CFTC have narrowly scoped, opt-in adapters. Cboe, Yahoo, FINRA and unreviewed frontend collectors are disabled. There is no current-price provider, broker, order, transfer, telemetry, background monitor or automatic deployment.

## Run locally

Python 3.11+; runtime core has zero third-party dependencies. Create an isolated environment, then install the pinned tooling from official PyPI:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/gsd demo --format short
.venv/bin/gsd demo --format markdown
.venv/bin/gsd research examples/research-synthetic.json --now 2026-01-02T16:00:00Z
.venv/bin/gsd sources
.venv/bin/gsd capabilities
```

`uv.lock` is the canonical resolved lock; `requirements-*.txt` are hash-checked exports. No upstream Skill scripts are executed by installation. The optional SDK adds only a local protocol facade:

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-mcp-dev.txt
.venv/bin/gsd-mcp
```

`gsd-mcp` speaks stdio. Its two registered tools, `research_dossier` and `what_if`, validate supplied evidence and calculate synthetic scenarios; they do not fetch data or save files. No HTTP transport, external server discovery, shell/path/SQL tool, credential or account tool is exposed. SDK 2.3.0 is pinned and its actual in-process and stdio calls are tested. [Reuse decisions](docs/reuse.md) explain why EdgarTools, TA-Lib, OpenBB and paid providers are candidates rather than installed integrations.

## Research contract

`ResearchRequest → approved capability → Record/Evidence → Claim → ResearchDossier → short answer + optional Markdown → explicit human record → manual review`.

- Facts and calculations have resolvable evidence references. Inferences and scenarios include assumptions. Counterevidence, risks and change conditions stay visible.
- Data status (`ok`, `partial`, `stale`, `no_data`, `conflict`, `permission_blocked`, `error`) differs from readiness (`answerable`, `needs_clarification`, `insufficient_evidence`, `blocked`). Answerable is never a buy signal.
- Original question, answered scope and unresolved parts remain separate. Business research cannot silently complete a current-price or personal decision question.
- Narrow queries need no investor questionnaire. Decision support asks at most two relevant questions, respects declined context, and continues independent research.
- Watchlists, decisions and review conditions are ephemeral by default. Explicit private file storage must be outside the public repository. Adding a watch does not enable notifications.

See [product specification](PRODUCT_SPEC.md), [interaction contract](docs/interaction-contract.md), [schema](schemas/contracts-v1.json), and [A01–A12 acceptance cases](docs/acceptance.md).

## Controlled online access

Operator opt-in and source-specific requirements are mandatory. SEC requires a **real contact explicitly set by the operator** in `SEC_CONTACT`; it is never inferred from login, profile, email or Git identity. Do not publish it. Missing/placeholder configuration fails before any SEC request. This project has not performed live market-data smoke tests.

```sh
# Configure SEC_CONTACT outside the repository using your own real declared contact.
.venv/bin/gsd sec-tickers --online
.venv/bin/gsd sec-filings 0000000001 --online --max-history-files 1
.venv/bin/gsd fetch treasury_daily_nominal_par --online --arguments '{"year":2026}'
.venv/bin/gsd fetch cftc_legacy_futures_only --online --arguments '{"page_size":100,"max_pages":1}'
```

The example CIK is synthetic, not a live availability claim. `GSD_STATE_DIR` selects the private cache/budget directory, defaulting to `~/.cache/global-stock-data`. Every SEC worker on one host must share the same canonical local directory. The SQLite rolling budget permits at most eight requests in any one-second window. All SEC workloads behind the same egress must coordinate through that budget or a single gateway; this is **not cross-machine/IP coordination**, and independent downloaders must not run beside it. Do not put the budget on NFS.

Timeouts, at most three attempts, bounded backoff and Retry-After are enforced. Redirects are rejected. 401/403 stop immediately; a 403 XML AccessDenied is never “missing.” Cache hits preserve original fetch time; stale cache is not returned on failures. Daily-index fallback is off by default, reports actual date/reason, and requires an explicit age bound. Per-evidence freshness uses explicitly selected observation/publication time and thresholds, never retrieval time. The host adapter records unknown publication times honestly.

[Source policies](docs/source-policies.md) distinguish code license from access, retention, AI use and redistribution rights. There is no all-sources permission switch.

## Quality gates

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
PYTHONPATH=tests/offline_guard .venv/bin/python -m coverage run -m unittest discover -s tests -v
.venv/bin/python -m coverage report
.venv/bin/python -m build --no-isolation
```

Tests use our own synthetic fixtures and a process-level outbound socket guard, including the actual MCP stdio subprocess. CI uses hash-pinned dependencies, commit-pinned Actions, read-only repository permissions and no secrets. There is no `pull_request_target`, automatic trading, live smoke, data upload or data redistribution. See [validation scope](docs/validation.md) for precise results and untested boundaries.

## Migration and limitations

[Migration](docs/migration.md) maps **every original function** to a replacement, a local-only parser or an explicit disabled/deferred capability. Original source remains accessible in Git history, never an active instruction to run archived code.

XBRL keeps original fields, taxonomy/tag/unit/start/end/form/accession/filed/frame and all revisions. Domestic forms only; IFRS and foreign 20-F/40-F are unsupported. As-of uses filing dates, not exact availability timestamps. Duration classification is a documented heuristic. Full historical point-in-time backtests are blocked. Frames and SEC full-text search are deferred, not marketed as complete universes or complete search.

Options activity is descriptive; volume/OI does not establish new positions. Signed delta exposure requires actual signed holdings, multiplier, deliverable and delta basis. FINRA local parsing labels specified off-exchange facilities and revisions, not short interest or whole-market volume. Treasury is daily nominal par percent, CFTC `6dca-aqww` is Legacy Futures Only; neither is real-time.

Original LICENSE is retained unchanged. Modified files and new implementation are identified in [NOTICE](NOTICE). No upstream live-validation claim carries over to this fork.
