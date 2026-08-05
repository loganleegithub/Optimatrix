from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from itertools import pairwise

MINUTES_PER_YEAR = Decimal(365 * 24 * 60)
DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


class BaselineUnavailable(ValueError):
    """The causal covered close history cannot produce the configured baseline."""


@dataclass(frozen=True)
class BaselineResult:
    return_interval_minutes: int
    window_variances: tuple[tuple[int, Decimal], ...]
    selected_lookback_minutes: int | None
    variance_rate_per_minute: Decimal
    annualized_volatility: Decimal
    total_variance_low: Decimal
    total_variance_high: Decimal


def compute_baseline(
    *,
    sampled_prices: tuple[Decimal, ...],
    lookbacks: tuple[int, ...],
    return_interval_minutes: int,
    annualized_variance_floor: Decimal,
    remaining_life_minutes_low: Decimal,
    remaining_life_minutes_high: Decimal,
) -> BaselineResult:
    if not lookbacks:
        raise ValueError("lookbacks must be non-empty")
    if isinstance(return_interval_minutes, bool) or return_interval_minutes <= 0:
        raise ValueError("return interval must be a positive integer")
    if any(
        isinstance(lookback, bool) or lookback <= 0 or lookback % return_interval_minutes != 0
        for lookback in lookbacks
    ):
        raise ValueError("lookbacks must be positive and divisible by return interval")
    required_sample_count = max(lookbacks) // return_interval_minutes + 1
    if len(sampled_prices) < required_sample_count:
        raise BaselineUnavailable("causal sampled-price history has not completed warm-up")
    if any(price <= 0 or not price.is_finite() for price in sampled_prices):
        raise BaselineUnavailable("sampled-price history contains an invalid price")
    if not (
        Decimal(0) < remaining_life_minutes_low <= remaining_life_minutes_high
        and annualized_variance_floor > 0
    ):
        raise BaselineUnavailable("remaining life or variance floor is invalid")
    try:
        with localcontext(DECIMAL_CONTEXT) as context:
            windows: list[tuple[int, Decimal]] = []
            for lookback in sorted(lookbacks):
                sample_count = lookback // return_interval_minutes + 1
                sampled = sampled_prices[-sample_count:]
                returns = tuple(
                    context.ln(later) - context.ln(earlier) for earlier, later in pairwise(sampled)
                )
                squared = tuple(value * value for value in returns)
                variance_rate = sum(squared, Decimal(0)) / Decimal(lookback)
                windows.append((lookback, +variance_rate))
            floor_per_minute = annualized_variance_floor / MINUTES_PER_YEAR
            selected = max(
                windows,
                key=lambda item: (item[1], item[0]),
            )
            selected_lookback: int | None = selected[0]
            selected_rate = selected[1]
            if floor_per_minute >= selected_rate:
                variance_rate = floor_per_minute
                selected_lookback = None
            else:
                variance_rate = selected_rate
            annualized = context.sqrt(variance_rate * MINUTES_PER_YEAR)
            total_low = variance_rate * remaining_life_minutes_low
            total_high = variance_rate * remaining_life_minutes_high
            result = BaselineResult(
                return_interval_minutes=return_interval_minutes,
                window_variances=tuple(windows),
                selected_lookback_minutes=selected_lookback,
                variance_rate_per_minute=+variance_rate,
                annualized_volatility=+annualized,
                total_variance_low=+total_low,
                total_variance_high=+total_high,
            )
    except (InvalidOperation, OverflowError) as exc:
        raise BaselineUnavailable("baseline arithmetic was not finite") from exc
    if not all(
        value.is_finite()
        for value in (
            result.variance_rate_per_minute,
            result.annualized_volatility,
            result.total_variance_low,
            result.total_variance_high,
        )
    ):
        raise BaselineUnavailable("baseline arithmetic was not finite")
    return result
