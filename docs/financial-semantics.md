# Financial semantics and test scope

## Records and comparability

Record v1 preserves provider/source_url, observation/report/disclosure/fetch instants, exchange timezone, unit/currency/scale/adjustment, actual data date, fallback reason, evidence reference and raw normalized payload. Unknown metadata is null. Fetched timestamps always include offsets. Date-only source periods remain date-only in data, not fabricated midnight publication timestamps.

`compare` rejects mismatched units, currencies, scaling, adjustment, data dates, taxonomy/tag/start/end/period kind/definition. `comparable_facts` checks complete XBRL context. `growth` supports comparable duration facts with a positive prior denominator and retains formula/inputs/version; same tag/unit/period kind and duration difference <=7 days are required. This is a bounded comparison rule, not a universal fiscal-calendar harmonizer. Unknown or negative denominators need a separately selected method.

Eastmoney requires decimal metadata and explicit scale/currency. Tencent market cap in hundreds of millions of local currency must explicitly use scale=100000000; Yahoo raw amounts cannot be compared until units/currencies match. No scaling is guessed.

## XBRL

All fact observations and original fields are retained, including taxonomy/tag/unit/start/end/form/accn/accession/filed/frame/fy/fp. Missing tags return no observations, never zero. EPS companyfacts units such as `USD/shares` are preserved; SEC frame URL encoding would use `USD-per-shares`. Foreign 20-F/40-F/IFRS normalization is rejected, even though the SEC API itself covers them.

Optional latest-revision selection groups taxonomy/tag/unit/start/end, keeps newest filed date/accession, and rejects conflicting same-day values rather than arbitrary selection. Original revision history is the default. As-of filtering uses filed DATE only. Intraday availability, dimensions, fiscal-quarter derivation from YTD, historical universe and delistings are not modeled. Full backtesting is blocked by `require_backtest_safe`.

Period classification labels `instant`, `quarter` (60–120 days), `ytd` (121–329), `annual` (330–400), `other_duration`; these are explicitly duration heuristics, not a fiscal-calendar assertion. Never subtract or add different periods blindly. Frames latest-filed calendar samples and current ticker files do not establish historical securities membership. Frames are deferred and have no active downloader.

SEC submissions support all returned recent rows and explicitly bounded listed historical files (maximum 10). Remaining files and coverage are reported, without arbitrary recent[:50]. Daily master index is one nightly file, generally updated starting about 22:00 ET; later corrections may require rebuilt full indexes. Requested/actual date and fallback reason differ. Filing dates are not event/holding dates; 13F is a lagged report, never real-time net holdings. FTS is deferred rather than presenting offset=0 as complete search.

## Local price parsing

Yahoo fixture parsing preserves null and precision, UTC and exchange dates, raw OHLC, separate adjclose and actions. Corporate-action coverage is unknown. finished_bar stays null because a timestamp alone does not prove session completion. All OHLC arrays must have identical lengths and ordered unique timestamps. Cookie/crumb/session functionality was removed from the active interface; there is no expiry/refresh promise and no unlicensed fallback.

## Indicators

Positive integer periods only; aligned outputs use null warmup and restart after missing values. SMA/EMA preserve precision; EMA seeds with an n-value SMA then alpha=2/(n+1). RSI defaults to Wilder smoothing seeded with n changes; `simple` is an explicit separate variant. Flat RSI is 50, all gains 100, all losses 0. MACD fast<slow uses those EMA seeds, signal EMA, histogram scale 1 or explicit 2 (both valid conventions), warmup slow+signal-2 indexes. Bollinger uses population variance (ddof=0), explicit multiplier. KDJ uses 50 seed, 1/3 smoothing, flat RSV=50, full n-bar warmup. No predictive value is asserted.

`validate_bars` rejects unordered/duplicate dates, invalid numbers and OHLC range violations. APIs taking bare value arrays cannot infer their dates; callers must validate bars first. Prices are not forcibly positive because some asset classes can have negative observations; this core is not a futures price eligibility model.

## Options and short sales

OSI parsing does not infer multiplier or deliverable. Activity requires known positive OI; missing/zero OI never becomes infinite anomaly. volume/OI is descriptive activity, cannot prove opening trade direction. Gross volume delta is not calculated or called net exposure. `signed_delta_exposure` requires signed quantity, delta [-1,1], actual multiplier, deliverable and delta basis; adjusted multi-asset/cash deliverables require separate review and are not inferred.

0DTE uses source snapshot timestamp and America/New_York date, checks source age and same ET date; it labels delayed chain snapshots, not tick flow. No Cboe/Yahoo live chain is called.

FINRA local CNMS parser labels revision and specified off-exchange facilities. ShortExemptVolume is included in ShortVolume and is not added twice. Duplicate date/symbol/market observations fail. This is short-sale volume, not short interest, not all market volume. Online collection remains disabled.

## Macro

Treasury feed is daily nominal par percent; N/A stays null, numeric strings parse, dates sort across years and spreads convert percentage points to basis points by ×100. No trade quote claim. CFTC 6dca-aqww is Legacy Futures Only, usually Friday publication for Tuesday observation with holiday exceptions. Actual publication timestamps are unknown, not manufactured from that schedule. Pagination is bounded, explicit and not transactionally snapshot-consistent; page exhaustion/partial coverage is reported. Other COT report types are not included.

Primary references: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC index timing](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data), [FINRA scope](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files), [OIC open interest](https://www.optionseducation.org/referencelibrary/faq/general-information), [CFTC reports](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm), [Treasury XML](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rate-xml-files). Synthetic tests establish behavior, not current upstream schema availability.
