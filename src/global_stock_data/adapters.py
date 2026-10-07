"""Capability registry and consistent result schema; no arbitrary-URL interface."""

from typing import Any

from .errors import DataError, require
from .http import Client
from .macro import cot, treasury
from .policy import POLICIES
from .records import Record
from .sec import Sec, cik, company_facts

CAPABILITIES = {
    "sec_company_facts": "sec",
    "sec_filings": "sec",
    "sec_tickers": "sec",
    "sec_daily_index": "sec",
    "sec_frames": "sec",
    "sec_fulltext_search": "sec",
    "treasury_daily_nominal_par": "treasury",
    "cftc_legacy_futures_only": "cftc",
    "current_quote": None,
}


def capabilities() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": key,
            "provider": provider,
            "enabled": provider is not None,
            "online_default": False,
            "point_in_time_safe": False,
            "policy_reference": POLICIES[provider].reference if provider else None,
            "policy_state": "reviewed_for_scope" if provider else "blocked",
        }
        for key, provider in CAPABILITIES.items()
    ]


def fetch(client: Client, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Explicit bounded capability lookup. Returns errors rather than empty success."""
    provider = CAPABILITIES.get(capability)
    if provider is None:
        return {
            "schema_version": "1.0",
            "capability": capability,
            "data_status": "permission_blocked",
            "records": [],
            "issues": [
                {
                    "code": "unsupported_capability",
                    "retryable": False,
                    "message": "No reviewed source adapter for this capability",
                }
            ],
        }
    try:
        require(isinstance(arguments, dict), "Capability arguments must be an object", "input")
        sec = Sec(client)
        result: dict[str, Any]
        url = ""
        if capability == "sec_company_facts":
            require(
                set(arguments) <= {"cik", "as_of", "latest_revision"},
                "Unknown fact arguments",
                "input",
            )
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik(arguments['cik'])}.json"
            payload = sec.facts(arguments["cik"])
            rows = company_facts(
                payload.json(),
                as_of=arguments.get("as_of"),
                latest_revision=arguments.get("latest_revision", False),
            )
            result = {
                "rows": rows,
                "fetched_at": payload.fetched_at,
                "evidence_ref": payload.evidence_ref,
                "completeness": "companyfacts_standard_taxonomies_only",
            }
        elif capability == "sec_filings":
            require(
                set(arguments) <= {"identifier", "max_history_files"},
                "Unknown filings arguments",
                "input",
            )
            result = sec.filings(**arguments)
            url = f"https://data.sec.gov/submissions/CIK{cik(arguments['identifier'])}.json"
        elif capability == "sec_tickers":
            require(not arguments, "Ticker mapping takes no arguments", "input")
            payload = sec.tickers()
            mapping = payload.json()
            require(isinstance(mapping, dict), "Ticker mapping must be an object")
            result = {
                "rows": list(mapping.values()),
                "fetched_at": payload.fetched_at,
                "evidence_ref": payload.evidence_ref,
                "completeness": "source_accuracy_and_scope_not_guaranteed",
            }
            url = "https://www.sec.gov/files/company_tickers.json"
        elif capability == "sec_daily_index":
            require(
                set(arguments) <= {"requested", "max_fallback_days", "max_data_age_days"},
                "Unknown index arguments",
                "input",
            )
            result = sec.daily_index(**arguments)
            url = result["source_url"]
        elif capability == "sec_frames":
            require(
                set(arguments) == {"taxonomy", "tag", "unit", "period", "kind"},
                "Frame requires explicit taxonomy/tag/unit/period/kind",
                "input",
            )
            result = sec.frames(**arguments)
            url = result["source_url"]
        elif capability == "sec_fulltext_search":
            require(
                {"query", "date_from", "date_to"}
                <= set(arguments)
                <= {"query", "date_from", "date_to", "page_size", "max_pages", "forms"},
                "Search needs explicit query/date range and bounded arguments",
                "input",
            )
            result = sec.fulltext_search(**arguments)
            url = result["source_url"]
        elif capability == "treasury_daily_nominal_par":
            require(set(arguments) == {"year"}, "Treasury requires one year", "input")
            result = treasury(client, arguments["year"])
            url = result["source_url"]
        else:
            require(set(arguments) <= {"page_size", "max_pages"}, "Unknown COT arguments", "input")
            result = cot(client, **arguments)
            url = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
        records = []
        require(
            isinstance(result["rows"], list)
            and all(isinstance(row, dict) for row in result["rows"]),
            "Provider rows must be objects",
        )
        provenance = result.get("row_provenance")
        require(
            provenance is None
            or (isinstance(provenance, list) and len(provenance) == len(result["rows"])),
            "Acquisition metadata must align with provider rows",
        )
        for index, row in enumerate(result["rows"]):
            acquisition = (
                provenance[index]
                if provenance is not None
                else {
                    "source_url": url,
                    "fetched_at": result["fetched_at"],
                    "evidence_ref": result.get("evidence_ref") or result["evidence_refs"][0],
                }
            )
            require(
                isinstance(acquisition, dict)
                and all(
                    isinstance(acquisition.get(key), str) and acquisition[key]
                    for key in ("source_url", "fetched_at", "evidence_ref")
                ),
                "Trusted acquisition metadata required",
            )
            # Only fields defined for this capability supply normalized semantics.
            # Unknown raw fields (including _source on non-FTS rows) stay data only.
            day_field = {
                "sec_company_facts": "end",
                "sec_frames": "end",
                "sec_filings": "filingDate",
                "cftc_legacy_futures_only": "report_date",
                "treasury_daily_nominal_par": "actual_data_date",
            }.get(capability)
            actual_date = (
                row["_source"].get("file_date")
                if capability == "sec_fulltext_search"
                else row.get(day_field)
                if day_field
                else result.get("actual_data_date")
            )
            unit = (
                row.get("unit")
                if capability
                in (
                    "sec_company_facts",
                    "sec_frames",
                    "cftc_legacy_futures_only",
                    "treasury_daily_nominal_par",
                )
                else None
            )
            records.append(
                Record(
                    provider,
                    acquisition["source_url"],
                    None,
                    None,
                    None,
                    acquisition["fetched_at"],
                    None,
                    unit,
                    "USD" if unit in ("USD", "USD/shares") else None,
                    "1" if unit else None,
                    None,
                    actual_date,
                    result.get("fallback_reason"),
                    acquisition["evidence_ref"],
                    row,
                ).as_dict()
            )
        partial = result["completeness"] not in (
            "all_listed_files_retrieved",
            "end_of_query_reached",
            "requested_year_only",
            "companyfacts_standard_taxonomies_only",
        )
        return {
            "schema_version": "1.0",
            "capability": capability,
            "data_status": "partial" if partial else "no_data" if not records else "ok",
            "records": records,
            "coverage": result["completeness"],
            "source_metadata": result,
            "issues": [],
            "point_in_time_safe": False,
        }
    except DataError as exc:
        state = (
            "permission_blocked"
            if exc.code in ("forbidden", "unauthorized", "license_denied", "offline")
            else "stale"
            if exc.code == "stale"
            else "conflict"
            if exc.code == "conflict"
            else "error"
        )
        return {
            "schema_version": "1.0",
            "capability": capability,
            "data_status": state,
            "records": [],
            "issues": [
                {
                    **exc.as_dict()["error"],
                    "retryable": exc.code in ("timeout", "network", "server", "rate_limited"),
                }
            ],
        }
    except (ValueError, KeyError, TypeError):
        return {
            "schema_version": "1.0",
            "capability": capability,
            "data_status": "error",
            "records": [],
            "issues": [
                {"code": "input", "retryable": False, "message": "Invalid capability input"}
            ],
        }
