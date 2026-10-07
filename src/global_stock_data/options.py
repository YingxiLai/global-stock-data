"""Descriptive delayed-chain statistics, never inferred opening flow."""

import re
from datetime import date
from typing import Any, cast
from zoneinfo import ZoneInfo

from .errors import require
from .records import instant, number


def parse_osi(symbol: str) -> dict[str, Any]:
    match = re.fullmatch(r"([A-Z0-9. ]{1,6})(\d{6})([CP])(\d{8})", symbol)
    require(match is not None, "Invalid OSI contract symbol", "input")
    if match is None:
        raise ValueError("Unreachable invalid symbol")
    root, expiry, side, strike = match.groups()
    parsed = date.fromisoformat("20" + expiry[:2] + "-" + expiry[2:4] + "-" + expiry[4:])
    return {
        "root": root.strip(),
        "expiry": parsed.isoformat(),
        "side": side,
        "strike": int(strike) / 1000,
        "multiplier": None,
        "deliverable": None,
    }


def activity(
    contracts: list[dict[str, Any]], *, min_volume: float = 500, min_ratio: float = 1
) -> list[dict[str, Any]]:
    require(min_volume >= 0 and min_ratio >= 0, "Invalid activity threshold", "input")
    result = []
    for contract in contracts:
        volume, oi = number(contract.get("volume")), number(contract.get("open_interest"))
        require(volume is None or volume >= 0, "Negative volume")
        require(oi is None or oi >= 0, "Negative open interest")
        if (
            volume is not None
            and oi is not None
            and oi > 0
            and volume >= min_volume
            and volume / oi > min_ratio
        ):
            result.append(
                {
                    **contract,
                    "volume_oi_ratio": volume / oi,
                    "interpretation": "activity_screen; opening_direction_unknown",
                }
            )
    return result


def signed_delta_exposure(positions: list[dict[str, Any]]) -> float:
    total = 0.0
    for position in positions:
        quantity, delta, multiplier = (
            number(position.get(k)) for k in ("signed_quantity", "delta", "multiplier")
        )
        require(
            quantity is not None and delta is not None and multiplier is not None,
            "Signed quantity, delta and actual multiplier required",
        )
        quantity, delta, multiplier = (
            cast(float, quantity),
            cast(float, delta),
            cast(float, multiplier),
        )
        require(-1 <= delta <= 1 and multiplier > 0, "Invalid delta or multiplier")
        require(
            bool(position.get("deliverable"))
            and position.get("delta_basis") == "per_deliverable_unit",
            "Explicit deliverable and delta basis required; adjusted contracts need review",
        )
        total += quantity * delta * multiplier
    return total


def zero_dte(
    contracts: list[dict[str, Any]], *, snapshot_at: str, now: str, max_age_seconds: float = 900
) -> dict[str, Any]:
    require(max_age_seconds >= 0, "Invalid freshness bound")
    snapshot, current = instant(snapshot_at), instant(now)
    age = (current - snapshot).total_seconds()
    require(0 <= age <= max_age_seconds, "Option snapshot is stale or future", "stale")
    et = ZoneInfo("America/New_York")
    require(
        snapshot.astimezone(et).date() == current.astimezone(et).date(),
        "Snapshot belongs to another ET date",
        "stale",
    )
    today = snapshot.astimezone(et).date().isoformat()
    return {
        "snapshot_at": snapshot_at,
        "exchange_timezone": "America/New_York",
        "expiry": today,
        "contracts": [c for c in contracts if c.get("expiry") == today],
        "interpretation": "delayed_chain_snapshot; not_tick_flow",
    }
