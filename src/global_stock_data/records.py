"""Evidence envelope; no zero imputation or guessed units."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import DataError, require


def instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataError("schema", "Invalid timestamp") from exc
    require(parsed.tzinfo is not None, "Timestamp needs an explicit offset")
    return parsed.astimezone(UTC)


def number(value: Any) -> float | None:
    if value is None or value in ("", "N/A", "NA", "-"):
        return None
    require(not isinstance(value, bool), "Boolean is not a numeric value")
    try:
        result = float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DataError("schema", "Invalid number") from exc
    require(math.isfinite(result), "Non-finite number")
    return result


def evidence_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Record:
    provider: str
    source_url: str
    observed_at: str | None
    reported_at: str | None
    disclosed_at: str | None
    fetched_at: str
    exchange_timezone: str | None
    unit: str | None
    currency: str | None
    scale: str | None
    adjustment: str | None
    actual_data_date: str | None
    fallback_reason: str | None
    evidence_ref: str
    data: dict[str, Any]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        instant(self.fetched_at)
        for value in (self.observed_at, self.reported_at, self.disclosed_at):
            if value is not None:
                instant(value)
        require(
            bool(self.provider and self.source_url and self.evidence_ref),
            "Evidence provenance required",
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def freshness(self, now: str, max_age_seconds: float) -> str:
        require(max_age_seconds >= 0, "Invalid freshness threshold")
        if self.observed_at is None:
            return "unknown"
        age = (instant(now) - instant(self.observed_at)).total_seconds()
        return "future" if age < 0 else "stale" if age > max_age_seconds else "fresh"


def compare(left: Record, right: Record, field: str, tolerance: float = 0) -> str:
    require(tolerance >= 0, "Invalid comparison tolerance")
    require(
        (left.unit, left.currency, left.scale, left.adjustment, left.actual_data_date)
        == (right.unit, right.currency, right.scale, right.adjustment, right.actual_data_date),
        "Incompatible units, basis, or data dates",
        "incomparable",
    )
    require(
        left.unit is not None and left.scale is not None,
        "Unknown units cannot be compared",
        "incomparable",
    )
    require(
        all(
            left.data.get(k) == right.data.get(k)
            for k in ("taxonomy", "tag", "start", "end", "period_kind", "definition")
        ),
        "Fact definitions or periods differ",
        "incomparable",
    )
    a, b = number(left.data.get(field)), number(right.data.get(field))
    if a is None or b is None:
        return "unknown"
    return "conflict" if abs(a - b) > tolerance else "consistent"
