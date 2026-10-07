# Review remediation and remaining boundaries

Baseline 5f27525709ab043b91e53d7a420ce6d46e66a0ce (2026-09-25, Skill 2.0.3). Fork created from the same upstream HEAD; no upstream drift found. Status means tested offline unless explicitly stated otherwise.

| Review item | Implemented and validated | Disabled/deferred or unverified |
|---|---|---|
| 1 Stable tool boundary | src package/CLI 3.0.0, schema 1.0; short native Skill, docs/examples separated; all 54 original functions mapped; build gate | Backward snippet API intentionally breaking; no global host install |
| 2 Unified HTTP | One policy gate, explicit SEC contact, local process-shared SQLite <=8/rolling-second, timeout/3-attempt/backoff/Retry-After, cache provenance, redacted status logs, HTTPS/path/query allowlist, no redirects | Same-egress safe boundary requires all workloads coordinate; no cross-machine limiter or live SEC contact supplied |
| 3 Licensing | Default deny unreviewed providers, explicit offline/online switch, source-specific policy/purpose references, blocked Cboe/Yahoo/FINRA/frontend collectors | No third-party license obtained; Cboe/Yahoo current policy pages could not be extracted, remain blocked; licensed future adapters need review |
| 4 Normalized evidence | Record/adapter result schema, dates/times/units/currency/scaling/adjustment/null/evidence hash, date/fallback metadata; local Eastmoney/Tencent require metadata; incompatible comparisons fail | Unknown source/publication metadata stays null; no FX/calendar/source-definition harmonization |
| 5 XBRL | Complete original observation fields + taxonomy/tag/unit/start/end/accession/form/filed/frame retained, revision history default, explicit latest/as-of-date selection, quarter/YTD/annual heuristics; missing≠zero; EPS units preserved | IFRS/foreign forms rejected; exact acceptance-time PIT/fiscal-YTD derivation/dimensions/universe/backtests unsupported and blocked; frames deferred |
| 6 Options | Offline OSI/activity/0DTE; missing OI not infinity; activity not opening flow; signed delta needs actual multiplier/deliverable/basis, ET source-snapshot freshness | No online chain, true tick flow, inferred maker/holder positions or adjusted multi-asset risk engine |
| 7 FINRA | Local CNMS-only parser, revision/scope flags, duplicate rejection, short-exempt inclusion invariant | Online blocked; not all-market short interest or a whole-market ranking |
| 8 Filing timeliness/coverage | All recent rows, bounded listed history max10, nightly daily master index, exact actual/fallback date and explicit age limit; event/holding dates unknown, 13F not realtime | FTS pagination and filing-body 13F/Form4/8-K extraction deferred; later index corrections not guaranteed |
| 9 Yahoo | Offline chart parser preserves null, precision, UTC/exchange date, adjclose/actions and unknown finished-bar status; source lengths validated | Online/session/crumb acquisition removed, no false expiry/refresh promise or automatic fallback; actions completeness unknown |
| 10 Error meaning | 401/403 immediate stop, 404 missing, 429 limited, 5xx/server, timeout/network/schema distinct; malformed JSON not empty; no stale failure cache fallback | Real provider errors/schema availability not live tested |
| 11 Financial formulas | Explicit SMA/EMA seeds, Wilder/simple RSI, flat50, null warmup/reset, MACD scale1/2, population BB, KDJ seed50; CFTC LegacyFuturesOnly bounded pagination and publication unknown; Treasury nominal-par percent/NA/sort/bp | No TA-Lib parity claim, exchange calendars, automatic trading interpretation or complete COT coverage |
| 12 Quality | Own synthetic JSON/text/XML, unit/contract/invariant/errors/concurrency/cache, A01–A12, socket guard, lint/strict types/build/coverage>=80; hashed lock + exports, SHA Actions, minimal CI, no secrets | Final head CI reported via PR/check links; no live smoke, provider schema certification, exhaustive vulnerability scan or investment-return evidence |
| Product | Progressive intent/context, original/answered/unresolved separation, data vs readiness, fact/calculation/inference/scenario, short/Markdown render, counterevidence/risks/change conditions, ephemeral watch, explicit private store, append decisions/manual diff, local alert evaluator | No LLM backend, suitability classifier, complete per-constraint interpreter, deployed bot/GUI, scheduler or actual notifications |
| Reuse | Optional official SDK2.3.0 stdio tools actually installed/locked/tested; pure read-only allowlist | EdgarTools/TA-Lib/OpenBB/paid MCP documented candidates, not installed; no accounts/keys or HTTP server |

## Operator decisions after this draft

- Select a licensed quote/news provider and intended use only if current-price research is needed; establish access, AI, retention/display and redistribution rights first.
- Supply a real SEC declared contact outside the repository and run the explicit opt-in smoke only under the documented aggregate-budget boundary.
- Decide whether/where to enable private local persistence; defaults remain ephemeral. Schedule/reminder delivery is not implemented and requires a separate scope.
- Prioritize exact availability/fiscal calendars, full filing-body ownership extraction, bounded SEC FTS, or read-only parser integration; do not market these as already complete.

No merge, deployment, purchase, credential creation, financial account connection, trading or other business repository modification occurred.
