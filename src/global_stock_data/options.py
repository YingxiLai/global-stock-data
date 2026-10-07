"""Descriptive delayed-chain statistics, never inferred opening flow."""

import re
from datetime import date
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from .errors import require
from .records import instant, number


def filter_expiry(
    contracts: list[dict[str, Any]],
    *,
    snapshot_at: str,
    expiry: str | None = None,
    dte_min: int | None = None,
    dte_max: int | None = None,
) -> dict[str, Any]:
    """Calendar-day DTE from the source's ET date; freshness is a separate check."""
    today = instant(snapshot_at).astimezone(ZoneInfo("America/New_York")).date()
    require(
        expiry is None or (dte_min is None and dte_max is None),
        "Choose an expiry or DTE range, not both",
        "input",
    )
    require(
        all(x is None or (type(x) is int and 0 <= x <= 3660) for x in (dte_min, dte_max)),
        "DTE bounds must be nonnegative integers <=3660",
        "input",
    )
    low = 0 if dte_min is None else dte_min
    high = 3660 if dte_max is None else dte_max
    require(low <= high, "Reversed DTE bounds", "input")
    target = today if expiry == "0DTE" else date.fromisoformat(expiry) if expiry else None
    selected = []
    for contract in contracts:
        require(isinstance(contract.get("expiry"), str), "Contract expiry required")
        expiration = date.fromisoformat(contract["expiry"])
        days = (expiration - today).days
        if (target is not None and expiration == target) or (
            target is None and low <= days <= high
        ):
            selected.append({**contract, "dte_calendar_days": days})
    return {
        "contracts": selected,
        "snapshot_at": snapshot_at,
        "snapshot_date_et": today.isoformat(),
        "exchange_timezone": "America/New_York",
        "freshness": "not_checked",
        "dte_basis": "calendar_days_from_source_snapshot; not_trading_days",
    }


def chain_summary(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """Contract-count statistics; no share/notional/delta inference or 100 multiplier."""
    require(len(contracts) <= 100_000, "Local option chain too large", "input")
    groups: dict[str, list[dict[str, Any]]] = {"call": [], "put": []}
    identities = set()
    for contract in contracts:
        side = contract.get("side")
        require(side in ("C", "P"), "Explicit C/P side required")
        require(
            isinstance(contract.get("contract_id"), str) and bool(contract["contract_id"]),
            "Unique contract_id required",
        )
        require(contract["contract_id"] not in identities, "Duplicate contract", "conflict")
        identities.add(contract["contract_id"])
        for key in ("volume", "open_interest"):
            value = number(contract.get(key))
            require(value is None or (value >= 0 and value.is_integer()), "Invalid contract count")
        multiplier = number(contract.get("multiplier"))
        require(multiplier is None or multiplier > 0, "Invalid actual multiplier")
        iv = number(contract.get("iv"))
        require(
            iv is None or (iv >= 0 and contract.get("iv_unit") == "fraction"),
            "IV needs fraction unit",
        )
        groups["call" if side == "C" else "put"].append(contract)

    def count(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        values = [number(row.get(field)) for row in rows]
        missing = sum(value is None for value in values)
        known = sum(int(value) for value in values if value is not None)
        return {
            "value": known if not missing else None,
            "known_sum": known,
            "missing_contracts": missing,
            "unit": "contracts",
        }

    calls, puts = groups["call"], groups["put"]
    cv, pv = count(calls, "volume"), count(puts, "volume")
    co, po = count(calls, "open_interest"), count(puts, "open_interest")

    def ratio(put: dict[str, Any], call: dict[str, Any]) -> float | None:
        return (
            number(float(Decimal(put["value"]) / Decimal(call["value"])))
            if put["value"] is not None and call["value"] is not None and call["value"] > 0
            else None
        )

    iv_rows = [row for row in contracts if number(row.get("volume")) not in (None, 0)]
    iv_complete = all(number(row.get("volume")) is not None for row in contracts) and all(
        number(row.get("iv")) is not None for row in iv_rows
    )
    # Decimal keeps products/sums finite before the final bounded float conversion.
    iv_weight = sum(Decimal(str(row["volume"])) for row in iv_rows)
    weighted_iv = (
        number(
            float(
                sum(Decimal(str(row["volume"])) * Decimal(str(row["iv"])) for row in iv_rows)
                / iv_weight
            )
        )
        if iv_complete and iv_weight > 0
        else None
    )
    unknown_multipliers = sum(number(row.get("multiplier")) is None for row in contracts)
    multipliers = sorted(
        {value for row in contracts if (value := number(row.get("multiplier"))) is not None}
    )
    return {
        "contracts_total": len(contracts),
        "call_volume": cv,
        "put_volume": pv,
        "call_open_interest": co,
        "put_open_interest": po,
        "put_call_volume_ratio": ratio(pv, cv),
        "put_call_open_interest_ratio": ratio(po, co),
        "volume_weighted_iv": weighted_iv,
        "iv_unit": "fraction",
        "iv_coverage": "complete" if iv_complete else "partial",
        "actual_multipliers": multipliers,
        "unknown_multiplier_contracts": unknown_multipliers,
        "ratio_basis": "contract_counts; heterogeneous_deliverables_are_not_equivalent_exposure",
        "exposure": "not_computed; signed_positions_and_deliverable_basis_required",
        "interpretation": "descriptive_contract_counts; neither_opening_flow_nor_net_positions",
    }


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


def signed_delta_exposure(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Group single-equity share deltas; never net unlike deliverables."""
    grouped: dict[str, float] = {}
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
            isinstance(position.get("underlying"), str)
            and bool(position["underlying"])
            and isinstance(position.get("deliverable"), dict)
            and position["deliverable"]
            == {
                "kind": "equity",
                "underlying": position["underlying"],
                "unit": "shares",
            }
            and position.get("delta_basis") == "per_deliverable_unit",
            "Single-equity share deliverable, underlying and delta basis required; mixed/cash unsupported",
        )
        underlying = position["underlying"]
        total = grouped.get(underlying, 0.0) + quantity * delta * multiplier
        number(total)
        grouped[underlying] = total
    return {
        "groups": [
            {"underlying": key, "unit": "shares", "signed_delta": grouped[key]}
            for key in sorted(grouped)
        ],
        "cross_underlying_total": None,
        "method": "signed_quantity*delta*actual_multiplier; grouped_by_equity",
    }


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
        "contracts": filter_expiry(contracts, snapshot_at=snapshot_at, expiry=today)["contracts"],
        "interpretation": "delayed_chain_snapshot; not_tick_flow",
    }
