"""Endpoint-specific review, never an all-sources permission switch."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urlsplit

from .errors import DataError


@dataclass(frozen=True)
class SourcePolicy:
    provider: str
    enabled: bool
    reference: str
    reason: str
    reviewed: str = "2026-10-07"
    purpose: str = "bounded investment research; no data redistribution grant"


POLICIES = {
    "sec": SourcePolicy(
        "sec",
        True,
        "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data",
        "Explicit declared agent; <=10 requests/s aggregate; no crawling; documented APIs and bounded index requests only",
    ),
    "treasury": SourcePolicy(
        "treasury",
        True,
        "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/interest-rate-xml-files",
        "Official nominal par daily XML feed; bounded year request; not market quotes",
    ),
    "cftc": SourcePolicy(
        "cftc",
        True,
        "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "Official PRE API access guidance; bounded non-excessive query; Legacy Futures Only dataset only",
    ),
    "cboe": SourcePolicy(
        "cboe",
        False,
        "https://www.cboe.com/delayed_quotes/app/",
        "Automated download restriction; a separate reviewed license-specific adapter is required",
    ),
    "yahoo": SourcePolicy(
        "yahoo",
        False,
        "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
        "Automated collection requires permission; no cookie/crumb acquisition or refresh adapter",
    ),
    "finra": SourcePolicy(
        "finra",
        False,
        "https://www.finra.org/terms-of-use",
        "Restrictions (e), (m), (o); AI/software and collection scope not approved",
    ),
    **{
        name: SourcePolicy(
            name, False, "unverified", "Frontend/API access and downstream data rights unverified"
        )
        for name in ("eastmoney", "sina", "tencent", "nasdaq", "hkex")
    },
}

PATHS: dict[str, list[tuple[str, str]]] = {
    "sec": [
        ("data.sec.gov", r"/submissions/CIK\d{10}(?:-submissions-\d{3})?\.json"),
        ("data.sec.gov", r"/api/xbrl/companyfacts/CIK\d{10}\.json"),
        ("www.sec.gov", r"/files/company_tickers\.json"),
        ("www.sec.gov", r"/Archives/edgar/daily-index/\d{4}/QTR[1-4]/master\.\d{8}\.idx"),
    ],
    "treasury": [
        ("home.treasury.gov", r"/resource-center/data-chart-center/interest-rates/pages/xml")
    ],
    "cftc": [("publicreporting.cftc.gov", r"/resource/6dca-aqww\.json")],
}


def authorize(provider: str, url: str, *, online: bool) -> None:
    policy = POLICIES.get(provider)
    if policy is None or not policy.enabled:
        raise DataError("license_denied", "Source has no approved automated adapter")
    if not online:
        raise DataError("offline", "Online access requires explicit opt-in")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise DataError("url_denied", "Invalid URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise DataError("url_denied", "Only approved HTTPS endpoints are allowed")
    if not any(
        parsed.hostname == host and re.fullmatch(path, parsed.path)
        for host, path in PATHS[provider]
    ):
        raise DataError("url_denied", "Host or path is outside reviewed scope")

    query = parse_qs(parsed.query, keep_blank_values=True)
    if provider == "sec":
        allowed = not parsed.query
    elif provider == "treasury":
        allowed = (
            set(query) == {"data", "field_tdr_date_value"}
            and query["data"] == ["daily_treasury_yield_curve"]
            and len(query["field_tdr_date_value"]) == 1
            and bool(re.fullmatch(r"(?:19|20)\d{2}|2100", query["field_tdr_date_value"][0]))
        )
    else:
        allowed = (
            set(query) == {"$limit", "$offset", "$order"}
            and all(len(v) == 1 for v in query.values())
            and query["$limit"][0].isdigit()
            and 1 <= int(query["$limit"][0]) <= 1000
            and query["$offset"][0].isdigit()
            and int(query["$offset"][0]) <= 9000
            and query["$order"] == ["report_date_as_yyyy_mm_dd DESC,cftc_contract_market_code ASC"]
        )
    if not allowed:
        raise DataError("url_denied", "Query is outside reviewed bounded scope")


def source_manifest() -> list[dict[str, str | bool]]:
    return [asdict(policy) for policy in POLICIES.values()]
