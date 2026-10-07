# v2.0.3 → v3.0.0 migration

Breaking migration from one embedded-code Skill to a reviewed Python package. No old snippet is automatically executed. All original functions are listed; online-disabled and deferred functions are not silently represented as completed. Original Apache-2.0 source remains in Git at the baseline commit.

| Original function | Replacement/status |
|---|---|
| `get_yahoo_session` | removed active cookie/crumb acquisition; no session/refresh promise |
| `yahoo_quote_summary` | online disabled; license-specific future adapter required |
| `eastmoney_datacenter` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `_limiter_for` | Client policy + shared provider budget; no per-worker global claim |
| `_is_object_missing` | explicit DataError status; 403 never missing |
| `official_get` | http.Client.get |
| `assert_us_ticker` | capability-specific identifiers; CIK validator |
| `us_stock_quote_sina` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `us_stock_quote_tencent` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `hk_stock_quote_tencent` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `hk_stock_quote_sina` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `stock_quote_eastmoney` | local.scaled_quote explicit metadata; online disabled |
| `us_stock_kline_sina` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `stock_kline_yahoo` | local.yahoo_bars; online disabled |
| `_ema` | indicators.ema |
| `calc_ma` | indicators.sma / ema |
| `calc_macd` | indicators.macd |
| `calc_rsi` | indicators.rsi (Wilder or simple explicitly) |
| `calc_kdj` | indicators.kdj |
| `calc_boll` | indicators.bollinger |
| `financial_statements_eastmoney` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `key_indicators_eastmoney` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `key_statistics` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `analyst_estimates` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `institutional_holders` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `financial_statements_yahoo` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `fund_flow_daily` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `parse_osi` | options.parse_osi |
| `options_chain_cboe` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `_et_today` | options.zero_dte requires explicit source snapshot / now |
| `filter_expiry` | options.filter_expiry / zero_dte; explicit expiry or calendar-DTE bounds from ET snapshot |
| `unusual_activity` | options.activity (descriptive screen) |
| `chain_summary` | options.chain_summary (contract volume/OI/P-C/IV, missingness); signed_delta_exposure returns grouped single-equity deltas |
| `cboe_quote` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `options_chain` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `sec_filings` | sec.Sec.filings; historical files explicitly bounded |
| `sec_xbrl_facts` | sec.company_facts + Sec.facts |
| `stock_search` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `stock_news` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |
| `ticker_to_cik` | Sec.tickers + explicit local lookup; no false coverage guarantee |
| `market_stock_list` | online disabled; no universe/replay claim |
| `_recent_weekdays` | explicit calendar-day fallback bound in Sec.daily_index |
| `short_volume_all` | local.finra_volume; online disabled |
| `short_volume_symbol` | local.finra_volume filtered by caller; online disabled |
| `short_volume_ranking` | local normalized CNMS rows; ranking deferred |
| `daily_filings` | sec.Sec.daily_index (nightly bounded master index) |
| `fulltext_search` | Sec.fulltext_search; required dates, max10 pages ×100, exact/lower-bound total and completeness |
| `_frame_period` | sec_queries.frame_period; explicit instant/duration, no 404 fallback |
| `market_frame` | Sec.frames / sec_queries.frame_rows; latest-filed calendar sample, not PIT universe |
| `frame_ranking` | sec_queries.frame_selection(top=...); unknown excluded, heterogeneous periods need explicit acceptance |
| `frame_screen` | sec_queries.frame_selection(min_value/max_value); one unit/context, no PIT claim |
| `treasury_yield_curve` | macro.treasury / treasury_xml |
| `cftc_cot` | macro.cot / cot_rows (LegacyFuturesOnly only) |
| `earnings_calendar` | Online disabled: unreviewed/unsupported provider; future license-specific adapter and contract required |

Inventory: 54 top-level functions, 35 Python blocks, 2221 source lines. `_RateLimiter` class is replaced by `http.SharedBudget`; `DataNotAvailable` is replaced by stable `DataError(code="missing")`. HTTP paths now share one boundary. There are no backward-compatible aliases that bypass it.

## Practical migration

Install the package separately from the native Skill. Use gsd sources/capabilities to understand enabled scope. Move scripts from pasted definitions to package imports or JSON CLI; do not copy upstream HTTP helpers. Use Record for acquisition provenance, EvidenceItem/Claim for research input, and deterministic dossier/render functions for output. See financial-semantics.md for changed formulas, seeds, temporal semantics and failure behavior.

No Yahoo crumb/session refresh exists in the new active API. Rich ownership/13F document extraction, complete analyst/news/fund-flow/front-end financial tables and whole-market quote coverage are explicitly deferred. Historical SEC file listing is bounded, not full EDGAR completeness. Pure indicator and authorized local-export computation do not confer supplier data rights.
