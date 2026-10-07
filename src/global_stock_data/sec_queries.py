"""Bounded SEC calendar frames and full-text search, never a PIT universe."""

import re
from datetime import date
from typing import Any, cast
from urllib.parse import urlencode

from .errors import DataError, require
from .http import Client
from .records import number


def _day(value: Any, code: str = "schema") -> date:
    require(isinstance(value, str), "Date string required", code)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(code, "Invalid date") from exc


def frame_period(year: int, *, quarter: int | None = None, kind: str) -> str:
    require(type(year) is int and 2009 <= year <= 2100, "Invalid frame year", "input")
    require(kind in ("instant", "duration"), "Explicit instant/duration kind required", "input")
    require(
        quarter is None or (type(quarter) is int and 1 <= quarter <= 4),
        "Invalid frame quarter",
        "input",
    )
    require(kind != "instant" or quarter is not None, "Instant frames need a quarter", "input")
    return f"CY{year}" + (f"Q{quarter}" if quarter else "") + ("I" if kind == "instant" else "")


def frame_arguments(taxonomy: str, tag: str, unit: str, period: str, kind: str) -> str:
    require(taxonomy == "us-gaap", "Only us-gaap frames supported", "unsupported")
    require(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,119}", tag)), "Invalid tag", "input")
    require(unit in ("USD", "USD-per-shares", "shares", "pure"), "Unsupported unit", "input")
    require(kind in ("instant", "duration"), "Explicit frame kind required", "input")
    pattern = (
        r"CY(?:20\d{2}|2100)Q[1-4]I" if kind == "instant" else r"CY(?:20\d{2}|2100)(?:Q[1-4])?"
    )
    require(bool(re.fullmatch(pattern, period)), "Period suffix disagrees with kind", "input")
    require(int(period[2:6]) >= 2009, "Frames predate XBRL coverage", "input")
    require(
        not tag.startswith("EarningsPerShare") or unit == "USD-per-shares",
        "EPS frames require explicit USD-per-shares; USD is not equivalent",
        "input",
    )
    return f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json"


def frame_rows(
    raw: dict[str, Any], *, taxonomy: str, tag: str, unit: str, period: str, kind: str
) -> list[dict[str, Any]]:
    frame_arguments(taxonomy, tag, unit, period, kind)
    normalized_unit = unit.replace("-per-", "/")
    require(
        raw.get("taxonomy") == taxonomy
        and raw.get("tag") == tag
        and raw.get("ccp") == period
        and raw.get("uom") in (unit, normalized_unit),
        "Frame response context disagrees with request",
    )
    rows = raw.get("data")
    require(isinstance(rows, list), "Frame data must be a list")
    rows = cast(list[dict[str, Any]], rows)
    require(type(raw.get("pts")) is int and raw["pts"] == len(rows), "Frame count mismatch")
    output, seen = [], set()
    for row in rows:
        require(isinstance(row, dict), "Invalid frame row")
        require(
            all(key in row for key in ("cik", "accn", "end", "val")),
            "Incomplete frame observation",
        )
        require(
            type(row["cik"]) is int and 0 < row["cik"] < 10**10 and bool(row["accn"]),
            "Invalid frame entity/accession",
        )
        require(row["cik"] not in seen, "Repeated entity in a frame", "conflict")
        seen.add(row["cik"])
        end = _day(row["end"])
        number(row["val"])
        start = row.get("start")
        require(
            (kind == "instant" and start is None)
            or (kind == "duration" and isinstance(start, str) and _day(start) <= end),
            "Frame observation contradicts instant/duration kind",
        )
        if row.get("filed") is not None:
            _day(row["filed"])
        output.append(
            {
                **row,
                "taxonomy": taxonomy,
                "tag": tag,
                "unit": normalized_unit,
                "unit_url": unit,
                "raw_uom": raw["uom"],
                "start": start,
                "accession": row["accn"],
                "frame": period,
                "period_kind": kind,
                "sample_basis": "latest_filed_calendar_approximation",
                "point_in_time_safe": False,
            }
        )
    return output


def frames(
    client: Client, *, taxonomy: str, tag: str, unit: str, period: str, kind: str
) -> dict[str, Any]:
    url = frame_arguments(taxonomy, tag, unit, period, kind)
    payload = client.get("sec", url)
    raw = payload.json()
    require(isinstance(raw, dict), "Frame response must be an object")
    rows = frame_rows(raw, taxonomy=taxonomy, tag=tag, unit=unit, period=period, kind=kind)
    return {
        "rows": rows,
        "source_url": url,
        "fetched_at": payload.fetched_at,
        "evidence_ref": payload.evidence_ref,
        "frame_metadata": {key: value for key, value in raw.items() if key != "data"},
        "completeness": "latest_filed_calendar_sample; not_historical_universe",
        "point_in_time_safe": False,
    }


def frame_selection(
    rows: list[dict[str, Any]],
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    top: int | None = None,
    ascending: bool = False,
    allow_calendar_approximation: bool = False,
) -> dict[str, Any]:
    """Screen/rank one frame; heterogeneous actual periods need explicit acceptance."""
    require(
        all(
            isinstance(row, dict)
            and all(
                key in row
                for key in (
                    "taxonomy",
                    "tag",
                    "unit",
                    "frame",
                    "period_kind",
                    "start",
                    "end",
                    "val",
                    "cik",
                )
            )
            for row in rows
        ),
        "Complete frame context required",
        "incomparable",
    )
    require(
        all(row["unit"] in ("USD", "USD/shares", "shares", "pure") for row in rows),
        "Unknown frame units cannot be compared",
        "incomparable",
    )
    low, high = number(min_value), number(max_value)
    require(low is None or high is None or low <= high, "Invalid screen bounds", "input")
    require(top is None or (type(top) is int and 1 <= top <= 1000), "Invalid rank bound", "input")
    contexts = {(r["taxonomy"], r["tag"], r["unit"], r["frame"], r["period_kind"]) for r in rows}
    require(len(contexts) <= 1, "Mixed frame context", "incomparable")
    periods = {(r["start"], r["end"]) for r in rows}
    require(
        len(periods) <= 1 or allow_calendar_approximation,
        "Different actual periods require explicit calendar approximation acceptance",
        "incomparable",
    )
    selected = []
    unknown = 0
    for row in rows:
        value = number(row["val"])
        if value is None:
            unknown += 1
        elif (low is None or value >= low) and (high is None or value <= high):
            selected.append(row)
    selected.sort(key=lambda row: (float(row["val"]), row["cik"]), reverse=not ascending)
    return {
        "rows": selected if top is None else selected[:top],
        "excluded_unknown_values": unknown,
        "comparison_basis": "calendar_approximation" if len(periods) > 1 else "same_actual_period",
        "point_in_time_safe": False,
    }


def search_arguments(
    query: str, date_from: str, date_to: str, page_size: int, max_pages: int, forms: str | None
) -> dict[str, str | int]:
    require(
        isinstance(query, str)
        and 0 < len(query.strip()) <= 500
        and not any(ord(c) < 32 for c in query),
        "Bounded nonempty search query required",
        "input",
    )
    start, end = _day(date_from, "input"), _day(date_to, "input")
    require(
        date(2001, 1, 1) <= start <= end and (end - start).days <= 3660,
        "Search needs ordered dates spanning at most 3660 days, from 2001",
        "input",
    )
    require(
        type(page_size) is int
        and 1 <= page_size <= 100
        and type(max_pages) is int
        and 1 <= max_pages <= 10,
        "Search bounded to ten pages of at most 100 hits",
        "input",
    )
    args: dict[str, str | int] = {
        "q": query,
        "dateRange": "custom",
        "startdt": date_from,
        "enddt": date_to,
        "size": page_size,
    }
    if forms is not None:
        require(
            bool(re.fullmatch(r"[A-Za-z0-9/-]{1,20}(?:,[A-Za-z0-9/-]{1,20}){0,9}", forms)),
            "Invalid bounded forms filter",
            "input",
        )
        args["forms"] = forms
    return args


def fulltext_search(
    client: Client,
    *,
    query: str,
    date_from: str,
    date_to: str,
    page_size: int = 100,
    max_pages: int = 1,
    forms: str | None = None,
) -> dict[str, Any]:
    args = search_arguments(query, date_from, date_to, page_size, max_pages, forms)
    rows: dict[str, dict[str, Any]] = {}
    refs, totals = [], []
    complete = False
    duplicates = 0
    pages = 0
    for page in range(max_pages):
        url = "https://efts.sec.gov/LATEST/search-index?" + urlencode(
            {**args, "from": page * page_size}
        )
        payload = client.get("sec", url)
        raw = payload.json()
        require(isinstance(raw, dict) and isinstance(raw.get("hits"), dict), "Missing search hits")
        hits = raw["hits"].get("hits")
        total = raw["hits"].get("total")
        require(
            isinstance(hits, list)
            and len(hits) <= page_size
            and isinstance(total, dict)
            and type(total.get("value")) is int
            and total["value"] >= 0
            and total.get("relation") in ("eq", "gte"),
            "Invalid bounded search page/total",
        )
        totals.append(total)
        refs.append(payload.evidence_ref)
        pages += 1
        for hit in hits:
            require(
                isinstance(hit, dict)
                and isinstance(hit.get("_id"), str)
                and isinstance(hit.get("_source"), dict),
                "Invalid search hit",
            )
            identifier, source = hit["_id"], hit["_source"]
            filed = source.get("file_date")
            require(
                isinstance(filed, str)
                and _day(date_from, "input") <= _day(filed) <= _day(date_to, "input"),
                "Search hit outside requested filing date range",
            )
            if identifier in rows:
                require(
                    {
                        k: v
                        for k, v in rows[identifier].items()
                        if not k.startswith("_evidence") and k not in ("_source_url", "_fetched_at")
                    }
                    == hit,
                    "Search hit changed between pages",
                    "conflict",
                )
                duplicates += 1
            else:
                rows[identifier] = {
                    **hit,
                    "_evidence_ref": payload.evidence_ref,
                    "_source_url": url,
                    "_fetched_at": payload.fetched_at,
                }
        # Exact totals and no duplicates are required; an empty/short page alone
        # does not establish completeness against a lower-bound total.
        if total["relation"] == "eq" and len(rows) == total["value"] and duplicates == 0:
            complete = True
            break
        if len(hits) < page_size:
            break
    stable_totals = all(total == totals[0] for total in totals)
    complete = complete and stable_totals
    return {
        "rows": list(rows.values()),
        "fetched_at": payload.fetched_at,
        "evidence_refs": refs,
        "source_url": url,
        "query": query,
        "date_from": date_from,
        "date_to": date_to,
        "pages_retrieved": pages,
        "page_size": page_size,
        "max_pages": max_pages,
        "reported_totals": totals,
        "duplicate_hits": duplicates,
        "completeness": "end_of_query_reached" if complete else "bounded_partial",
        "snapshot_consistency": "not_guaranteed_across_pages",
        "earliest_mention_established": False,
        "point_in_time_safe": False,
    }
