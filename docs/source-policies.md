# Provider-specific access policy

Reviewed 2026-10-07. Code Apache-2.0 is separate from third-party data rights. This is an engineering access gate for a recorded method/purpose, not blanket legal clearance. Only explicit, minimal manual Treasury/CFTC government-feed checks were performed; see docs/validation.md. SEC and restricted sources were not probed.

| Provider | Active method/scope | Requirements | Retention/export/AI boundary |
|---|---|---|---|
| SEC | fixed companyfacts, submissions/listed history, company_tickers, explicit us-gaap frames, bounded EFTS search and one daily master index | Explicit online opt-in and real operator SEC_CONTACT; shared local <=8/s budget; no crawls, redirects or permission retries | Local response cache/evidence hash for bounded research; SEC public-access guidance does not eliminate filer third-party content rights or grant unrestricted redistribution |
| Treasury | official nominal-par daily XML, explicit single year | Online opt-in, small bounded request; nominal par, not trade feed | Local research cache; no blanket export or third-party content grant; source date/percent retained |
| CFTC | PRE dataset 6dca-aqww only, <=10 pages ×1000 rows | Online opt-in, no token acquisition or excessive use; stable sort and explicit bounded pagination | Local research cache; no all-report/real-time claim, no automated bulk bootstrap |
| Cboe | no active online method | Delayed-quotes automatic downloading restriction; future license-specific adapter review required | Local synthetic parsing only; no general personal-use exception assumed |
| Yahoo | no active online method or cookie/crumb/session | Automation permission not established for this use | Local synthetic/authorized export parser only; no automatic refresh/fallback |
| FINRA | no active online method | Terms Restrictions (e), (m), (o) cover collection and software/AI uses; separate applicable permission needed | Local synthetic/authorized CNMS parser only, source/revision/scope preserved; not all-market or short interest |
| Eastmoney, Sina, Tencent, Nasdaq, HKEX | no active online method | Access/AI/retention/display/redistribution unverified or restricted | Local explicit metadata transformations only; no network probing |

There is no environment variable that permits all disabled sources. A new source requires a reviewed method and purpose, endpoint allowlist, provider-specific budget, rights/entitlement record, parser contracts and offline failure tests. If a separate license authorizes a disabled provider, add and review a license-specific adapter; do not toggle the policy map at runtime or evade a denial through a mirror/account.

SEC 10 requests/second applies collectively. Local SQLite sliding-window budget is conservative and coordinates processes sharing one canonical directory. It does not coordinate multiple machines or other programs on the same IP. Safe execution boundary: all SEC traffic behind one egress shares the gateway/budget; do not run beside unrelated downloaders. No claim of globally compliant 8/s per worker.

Raw cache is private, not encrypted, and not committed. TTL is cache usability, distinct from a redistribution license. Usability is capped at one day; a subsequent permitted request purges entries older than one day. An idle cache is not automatically deleted, so operators must remove it to meet a strict wall-clock retention policy. No daemon or background deletion is started. No source data is exported to public Git or uploaded as a CI artifact. Online access defaults off; CLI demo and MCP pure tools make zero network calls.

Policy evidence:

- [SEC access requirements and index timing](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data): free public downloads, declared agent and aggregate rate policy, nightly indexes. [SEC API scope](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) documents standard facts and latest-filed calendar frames.
- [Treasury XML documentation](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rate-xml-files) documents daily feeds. Review only this government nominal-par feed; do not infer permission for third-party Treasury pages or transaction data.
- [CFTC COT official guidance](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) documents PRE/API use, report types, weekly publication and bounded/nonexcessive API access. A three-row explicit manual sample was checked; it does not establish full availability or coverage.
- [FINRA terms](https://www.finra.org/terms-of-use) (last-modified 2023-11-09) were retrieved during review, including software/AI restrictions. [FINRA daily file scope](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files) describes facility coverage.
- [Cboe delayed-quotes app](https://www.cboe.com/delayed_quotes/app/) and [Yahoo terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) are the review-baseline policy references. Current page extraction was unsuccessful (Cboe too large; Yahoo 999), so they remain blocked and current wording was not independently reverified. No endpoint workaround was attempted.
- [AWS GetObject permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html) distinguish 403 access denial from 404 absence. XML AccessDenied does not prove an object is missing.

SEC extension scope: Frames are the documented XBRL calendar API, not historical membership. EFTS is the official full-text search UI endpoint at efts.sec.gov/LATEST/search-index, treated as a schema-dependent search adapter rather than a documented stable data.sec.gov API. Only fixed GET keys, custom date ranges and bounded offsets/sizes/forms are accepted. Both use the same real-contact UA, sec budget/cache/error boundary; permission denials stop. No SEC extension endpoint was sampled live. Reference: https://www.sec.gov/edgar/search/.
