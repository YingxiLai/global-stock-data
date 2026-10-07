"""Offline parsers for authorized user exports or SYNTHETIC fixtures only.

No network adapters for Yahoo, Eastmoney, Tencent, FINRA or Cboe are provided.
"""

import csv
import io
from datetime import UTC, datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from .errors import require
from .indicators import validate_ohlc
from .records import number


def yahoo_bars(raw: dict[str, Any], *, now: str) -> dict[str, Any]:
    result = raw.get("chart", {}).get("result")
    require(isinstance(result, list) and len(result) == 1, "Missing Yahoo chart result")
    item = result[0]
    meta = item.get("meta", {})
    tz = meta.get("exchangeTimezoneName")
    require(
        isinstance(tz, str) and isinstance(meta.get("currency"), str),
        "Exchange timezone and currency required",
    )
    zone = ZoneInfo(tz)
    timestamps = item.get("timestamp", [])
    quote = item.get("indicators", {}).get("quote", [])
    require(len(quote) == 1, "Missing quote series")
    quote = quote[0]
    require(
        all(
            isinstance(quote.get(k), list) and len(quote[k]) == len(timestamps)
            for k in ("open", "high", "low", "close", "volume")
        ),
        "Mismatched bar series",
    )
    require(timestamps == sorted(set(timestamps)), "Bars must be ordered and unique")
    adj = item.get("indicators", {}).get("adjclose", [])
    adjusted = adj[0].get("adjclose") if len(adj) == 1 else None
    if adjusted is not None:
        require(len(adjusted) == len(timestamps), "Mismatched adjusted close series")
    # Intraday/daily session completion cannot be inferred from a timestamp alone.
    output = []
    for i, stamp in enumerate(timestamps):
        dt = datetime.fromtimestamp(stamp, UTC)
        output.append(
            {
                "timestamp_utc": dt.isoformat(),
                "exchange_date": dt.astimezone(zone).date().isoformat(),
                **{key: number(quote[key][i]) for key in quote},
                "adjclose": number(adjusted[i]) if adjusted is not None else None,
                "finished_bar": None,
            }
        )
        validate_ohlc(output[-1])
    return {
        "bars": output,
        "exchange_timezone": tz,
        "currency": meta["currency"],
        "scale": "1",
        "adjustment": "raw_ohlc; separate_provider_adjclose"
        if adjusted is not None
        else "raw; adjustment_unknown",
        "actions": item.get("events", {}),
        "parsed_at": now,
        "actions_completeness": "unknown",
    }


def scaled_quote(
    value: Any,
    *,
    provider: str,
    decimal_places: int | None,
    currency: str | None,
    scale: float | None,
    unit: str | None,
) -> dict[str, Any]:
    require(
        decimal_places is not None and type(decimal_places) is int and 0 <= decimal_places <= 12,
        "Explicit source decimal metadata required",
    )
    factor = number(scale)
    require(
        currency is not None and factor is not None and factor > 0 and unit is not None,
        "Explicit currency, unit and scale required",
    )
    parsed = number(value)
    return {
        "provider": provider,
        "value": None
        if parsed is None
        else number(parsed / 10 ** cast(int, decimal_places) * cast(float, factor)),
        "currency": currency,
        "unit": unit,
        "scale": "1",
        "original_decimal_places": decimal_places,
        "original_scale": scale,
    }


def finra_volume(text: str, *, facility: str, revision: str) -> dict[str, Any]:
    require(
        facility == "CNMS" and bool(revision), "Only explicitly labeled CNMS revision supported"
    )
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    require(
        reader.fieldnames is not None
        and all(
            k in reader.fieldnames
            for k in ("Date", "Symbol", "ShortVolume", "ShortExemptVolume", "TotalVolume", "Market")
        ),
        "Invalid FINRA header",
    )
    rows, seen = [], set()
    for row in reader:
        # FINRA footer count is not an observation.
        if row.get("Symbol") is None:
            require(str(row.get("Date", "")).isdigit(), "Invalid footer")
            continue
        key = (row["Date"], row["Symbol"], row["Market"])
        require(
            key not in seen, "Duplicate facility observation; refusing double count", "conflict"
        )
        seen.add(key)
        short, exempt, total = (
            number(row[k]) for k in ("ShortVolume", "ShortExemptVolume", "TotalVolume")
        )
        require(short is not None and exempt is not None and total is not None, "Missing volume")
        short, exempt, total = cast(float, short), cast(float, exempt), cast(float, total)
        require(0 <= exempt <= short <= total, "FINRA volume invariant failed")
        rows.append(
            {
                **row,
                "short_volume": short,
                "short_exempt_volume": exempt,
                "total_volume": total,
                "short_volume_ratio": short / total if total else None,
            }
        )
    return {
        "facility": facility,
        "revision": revision,
        "scope": "specified_off_exchange_facilities_only",
        "is_short_interest": False,
        "is_whole_market": False,
        "rows": rows,
        "short_exempt_included_in_short_volume": True,
    }
