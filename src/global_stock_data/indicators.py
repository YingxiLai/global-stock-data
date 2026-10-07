"""Indicator conventions: explicit seed/warmup, gaps reset each segment."""

import math
from collections.abc import Callable
from datetime import date
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

from .errors import DataError, require
from .records import number

P = ParamSpec("P")
T = TypeVar("T")


def finite_result(function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def checked(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            result = function(*args, **kwargs)
        except OverflowError as exc:
            raise DataError("schema", "Indicator arithmetic exceeds finite range") from exc

        def check(value: Any) -> None:
            if isinstance(value, float):
                require(math.isfinite(value), "Indicator output is non-finite")
            elif isinstance(value, dict):
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        check(result)
        return result

    return checked


def validate_ohlc(bar: dict[str, Any]) -> None:
    values = {key: number(bar.get(key)) for key in ("open", "high", "low", "close", "volume")}
    low, high = values["low"], values["high"]
    require(low is None or high is None or low <= high, "Low exceeds high")
    for key in ("open", "close"):
        value = values[key]
        require(
            value is None or ((low is None or value >= low) and (high is None or value <= high)),
            "OHLC invariant failed",
        )
    volume = values["volume"]
    require(volume is None or volume >= 0, "Negative volume")


def period(value: int) -> None:
    require(
        isinstance(value, int) and not isinstance(value, bool) and value > 0,
        "Period must be a positive integer",
        "input",
    )


def validate_bars(bars: list[dict[str, Any]]) -> list[float | None]:
    dates = cast(list[str], [bar.get("date") for bar in bars])
    require(all(isinstance(d, str) for d in dates), "Bar dates required")
    for day in dates:
        date.fromisoformat(day)
    require(dates == sorted(set(dates)), "Bars must be ordered and unique", "input")
    closes = [number(bar.get("close")) for bar in bars]
    for bar in bars:
        validate_ohlc(bar)
    return closes


@finite_result
def sma(values: list[float | None], n: int) -> list[float | None]:
    period(n)
    result: list[float | None] = []
    segment: list[float] = []
    for value in values:
        parsed = number(value)
        if parsed is None:
            segment = []
        else:
            segment.append(parsed)
        result.append(sum(segment[-n:]) / n if len(segment) >= n else None)
    return result


@finite_result
def ema(values: list[float | None], n: int) -> list[float | None]:
    """SMA seed after n nonmissing values; then alpha=2/(n+1)."""
    period(n)
    result: list[float | None] = []
    seed: list[float] = []
    previous: float | None = None
    for value in values:
        parsed = number(value)
        if parsed is None:
            seed, previous = [], None
        elif previous is None:
            seed.append(parsed)
            if len(seed) == n:
                previous = sum(seed) / n
        else:
            previous += 2 / (n + 1) * (parsed - previous)
        result.append(previous)
    return result


@finite_result
def rsi(values: list[float | None], n: int = 14, *, variant: str = "wilder") -> list[float | None]:
    period(n)
    require(variant in ("wilder", "simple"), "RSI variant must be wilder or simple", "input")
    previous: float | None = None
    gains: list[float] = []
    losses: list[float] = []
    avg_gain = avg_loss = 0.0
    result: list[float | None] = []
    for value in values:
        parsed = number(value)
        answer = None
        if parsed is None:
            previous, gains, losses = None, [], []
        elif previous is not None:
            difference = parsed - previous
            gains.append(max(difference, 0))
            losses.append(max(-difference, 0))
            if len(gains) >= n:
                if variant == "simple" or len(gains) == n:
                    avg_gain, avg_loss = sum(gains[-n:]) / n, sum(losses[-n:]) / n
                else:
                    avg_gain = (avg_gain * (n - 1) + gains[-1]) / n
                    avg_loss = (avg_loss * (n - 1) + losses[-1]) / n
                answer = (
                    50.0
                    if avg_gain == avg_loss == 0
                    else 100.0
                    if avg_loss == 0
                    else 100 - 100 / (1 + avg_gain / avg_loss)
                )
        previous = parsed
        result.append(answer)
    return result


@finite_result
def macd(
    values: list[float | None],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    *,
    histogram_scale: float = 1,
) -> dict[str, Any]:
    period(fast)
    period(slow)
    period(signal)
    require(fast < slow and histogram_scale in (1, 2), "Invalid MACD convention", "input")
    a, b = ema(values, fast), ema(values, slow)
    difference = [None if x is None or y is None else x - y for x, y in zip(a, b, strict=True)]
    line = ema(difference, signal)
    hist = [
        None if x is None or y is None else (x - y) * histogram_scale
        for x, y in zip(difference, line, strict=True)
    ]
    return {
        "macd": difference,
        "signal": line,
        "histogram": hist,
        "histogram_scale": histogram_scale,
        "seed": "sma",
        "warmup": slow + signal - 2,
        "gap_policy": "reset",
    }


@finite_result
def bollinger(
    values: list[float | None], n: int = 20, deviations: float = 2
) -> list[dict[str, float | None]]:
    period(n)
    require(math.isfinite(deviations) and deviations >= 0, "Invalid band width", "input")
    means = sma(values, n)
    output: list[dict[str, float | None]] = []
    for i, mean in enumerate(means):
        if mean is None:
            output.append({"middle": None, "upper": None, "lower": None})
        else:
            segment = values[i - n + 1 : i + 1]
            variance = sum((x - mean) ** 2 for x in segment if x is not None) / n
            width = math.sqrt(variance) * deviations
            output.append({"middle": mean, "upper": mean + width, "lower": mean - width})
    return output


@finite_result
def kdj(bars: list[dict[str, Any]], n: int = 9) -> list[dict[str, float | None]]:
    period(n)
    validate_bars(bars)
    output: list[dict[str, float | None]] = []
    segment: list[tuple[float, float, float]] = []
    k = d = 50.0
    for bar in bars:
        close, low, high = (number(bar.get(key)) for key in ("close", "low", "high"))
        if close is None or low is None or high is None:
            segment, k, d = [], 50.0, 50.0
        else:
            segment.append((close, low, high))
        if len(segment) < n:
            output.append({"k": None, "d": None, "j": None})
            continue
        bottom, top = min(x[1] for x in segment[-n:]), max(x[2] for x in segment[-n:])
        rsv = 50 if top == bottom else (segment[-1][0] - bottom) / (top - bottom) * 100
        k, d = 2 / 3 * k + rsv / 3, 2 / 3 * d + (2 / 3 * k + rsv / 3) / 3
        output.append({"k": k, "d": d, "j": 3 * k - 2 * d})
    return output
