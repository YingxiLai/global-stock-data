"""Daily nominal par Treasury rates and Legacy Futures Only COT."""

from datetime import date
from typing import Any, cast
from urllib.parse import urlencode
from xml.etree import ElementTree

from .errors import require
from .http import Client
from .records import number


def treasury_xml(text: str) -> list[dict[str, Any]]:
    require(
        "<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(), "XML entities forbidden"
    )
    require(len(text) <= 20_000_000, "XML too large")
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 - entities rejected above
    except ElementTree.ParseError as exc:
        from .errors import DataError

        raise DataError("schema", "Invalid Treasury XML") from exc
    rows = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "properties":
            continue
        values = {child.tag.rsplit("}", 1)[-1]: child.text for child in entry}
        stamp = values.get("NEW_DATE")
        require(isinstance(stamp, str), "Treasury date missing")
        day = date.fromisoformat(cast(str, stamp)[:10])
        rates = {
            k.removeprefix("BC_"): number(v)
            for k, v in values.items()
            if k.startswith("BC_") and k != "BC_ID"
        }
        require(bool(rates), "Treasury maturity fields missing")
        rows.append(
            {
                "actual_data_date": day.isoformat(),
                "rates": rates,
                "unit": "percent",
                "rate_type": "daily_nominal_par",
                "is_realtime_quote": False,
            }
        )
    require(
        len({r["actual_data_date"] for r in rows}) == len(rows),
        "Duplicate Treasury dates",
        "conflict",
    )
    return sorted(rows, key=lambda r: r["actual_data_date"], reverse=True)


def spread_basis_points(long_percent: Any, short_percent: Any) -> float | None:
    long, short = number(long_percent), number(short_percent)
    return None if long is None or short is None else (long - short) * 100


def treasury(client: Client, year: int) -> dict[str, Any]:
    require(1990 <= year <= 2100, "Invalid Treasury year", "input")
    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?"
        + urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": year})
    )
    payload = client.get("treasury", url, ttl=3600, max_age=3600)
    return {
        "rows": treasury_xml(payload.body.decode()),
        "fetched_at": payload.fetched_at,
        "source_url": url,
        "evidence_ref": payload.evidence_ref,
        "completeness": "requested_year_only",
    }


def cot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        stamp = row.get("report_date_as_yyyy_mm_dd")
        require(isinstance(stamp, str), "COT report date required")
        day = date.fromisoformat(cast(str, stamp)[:10])
        require(
            bool(row.get("contract_market_name")) and bool(row.get("cftc_contract_market_code")),
            "COT market metadata required",
        )
        output.append(
            {
                **row,
                "report_date": day.isoformat(),
                "report_type": "LegacyFuturesOnly",
                "observed_date": day.isoformat(),
                "publication_timestamp": None,
                "release_schedule": "normally_Friday_for_Tuesday; holidays_exceptions",
                "unit": "contracts",
            }
        )
    return sorted(
        output, key=lambda r: (r["report_date"], r["cftc_contract_market_code"]), reverse=True
    )


def cot(client: Client, *, page_size: int = 100, max_pages: int = 1) -> dict[str, Any]:
    require(
        1 <= page_size <= 1000 and 1 <= max_pages <= 10, "Invalid bounded COT page request", "input"
    )
    rows: list[dict[str, Any]] = []
    refs: list[str] = []
    complete = False
    for page in range(max_pages):
        url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json?" + urlencode(
            {
                "$limit": page_size,
                "$offset": page * page_size,
                "$order": "report_date_as_yyyy_mm_dd DESC,cftc_contract_market_code ASC",
            }
        )
        payload = client.get("cftc", url, ttl=3600, max_age=3600)
        batch = payload.json()
        require(isinstance(batch, list), "COT result is not a list")
        rows.extend(
            {
                **row,
                "_evidence_ref": payload.evidence_ref,
                "_source_url": url,
                "_fetched_at": payload.fetched_at,
            }
            for row in batch
        )
        refs.append(payload.evidence_ref)
        if len(batch) < page_size:
            complete = True
            break
    return {
        "fetched_at": payload.fetched_at,
        "rows": cot_rows(rows),
        "evidence_refs": refs,
        "completeness": "end_of_query_reached" if complete else "bounded_partial",
        "snapshot_consistency": "not_guaranteed_across_pages",
        "dataset": "6dca-aqww",
    }
