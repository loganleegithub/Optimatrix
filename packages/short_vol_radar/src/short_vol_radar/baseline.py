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
    window_variances: tuple[tuple[int, Decimal], ...]
    variance_rate_per_minute: Decimal
    annualized_volatility: Decimal
    total_variance_low: Decimal
    total_variance_high: Decimal


def compute_baseline(
    *,
    closes: tuple[Decimal, ...],
    lookbacks: tuple[int, ...],
    weights: tuple[Decimal, ...],
    annualized_variance_floor: Decimal,
    remaining_life_minutes_low: Decimal,
    remaining_life_minutes_high: Decimal,
) -> BaselineResult:
    if len(lookbacks) != len(weights) or not lookbacks:
        raise ValueError("lookbacks and weights must be non-empty and aligned")
    if len(closes) < max(lookbacks) + 1:
        raise BaselineUnavailable("causal close history has not completed warm-up")
    if any(close <= 0 or not close.is_finite() for close in closes):
        raise BaselineUnavailable("close history contains an invalid price")
    if not (
        Decimal(0) < remaining_life_minutes_low <= remaining_life_minutes_high
        and annualized_variance_floor > 0
    ):
        raise BaselineUnavailable("remaining life or variance floor is invalid")
    try:
        with localcontext(DECIMAL_CONTEXT) as context:
            returns = tuple(
                context.ln(later) - context.ln(earlier) for earlier, later in pairwise(closes)
            )
            windows: list[tuple[int, Decimal]] = []
            weighted = Decimal(0)
            for lookback, weight in sorted(zip(lookbacks, weights, strict=True)):
                squared = tuple(value * value for value in returns[-lookback:])
                variance = sum(squared, Decimal(0)) / Decimal(lookback)
                windows.append((lookback, +variance))
                weighted += weight * variance
            floor_per_minute = annualized_variance_floor / MINUTES_PER_YEAR
            variance_rate = max(floor_per_minute, weighted)
            annualized = context.sqrt(variance_rate * MINUTES_PER_YEAR)
            total_low = variance_rate * remaining_life_minutes_low
            total_high = variance_rate * remaining_life_minutes_high
            result = BaselineResult(
                window_variances=tuple(windows),
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
