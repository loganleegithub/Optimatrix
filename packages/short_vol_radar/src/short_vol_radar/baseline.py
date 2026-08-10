from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from itertools import pairwise

MINUTES_PER_YEAR = Decimal(365 * 24 * 60)
DECIMAL_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
PI_OVER_TWO = Decimal("1.5707963267948966192313216916397514420985846996876")


class BaselineUnavailable(ValueError):
    """The causal covered history cannot produce the configured baseline."""


@dataclass(frozen=True)
class WindowDiagnostics:
    lookback_minutes: int
    return_count: int
    variance_rate_per_minute: Decimal
    positive_semivariance_rate_per_minute: Decimal
    negative_semivariance_rate_per_minute: Decimal
    positive_semivariance_share: Decimal
    negative_semivariance_share: Decimal
    bipower_variation_rate_per_minute: Decimal
    jump_variation_rate_per_minute: Decimal
    jump_share: Decimal
    maximum_absolute_return: Decimal
    net_return: Decimal


@dataclass(frozen=True)
class BaselineStatistics:
    return_interval_minutes: int
    window_variances: tuple[tuple[int, Decimal], ...]
    selected_lookback_minutes: int | None
    variance_rate_per_minute: Decimal
    annualized_volatility: Decimal
    window_diagnostics: tuple[WindowDiagnostics, ...] = ()


@dataclass(frozen=True)
class BaselineResult:
    return_interval_minutes: int
    window_variances: tuple[tuple[int, Decimal], ...]
    selected_lookback_minutes: int | None
    variance_rate_per_minute: Decimal
    annualized_volatility: Decimal
    total_variance_low: Decimal
    total_variance_high: Decimal
    window_diagnostics: tuple[WindowDiagnostics, ...] = ()

    def diagnostics_for(self, lookback_minutes: int) -> WindowDiagnostics:
        for member in self.window_diagnostics:
            if member.lookback_minutes == lookback_minutes:
                return member
        raise KeyError(lookback_minutes)


def compute_baseline(
    *,
    sampled_prices: tuple[Decimal, ...],
    lookbacks: tuple[int, ...],
    return_interval_minutes: int,
    annualized_variance_floor: Decimal,
    remaining_life_minutes_low: Decimal,
    remaining_life_minutes_high: Decimal,
) -> BaselineResult:
    statistics = compute_baseline_statistics(
        sampled_prices=sampled_prices,
        lookbacks=lookbacks,
        return_interval_minutes=return_interval_minutes,
        annualized_variance_floor=annualized_variance_floor,
    )
    return project_baseline(
        statistics=statistics,
        remaining_life_minutes_low=remaining_life_minutes_low,
        remaining_life_minutes_high=remaining_life_minutes_high,
    )


def compute_baseline_statistics(
    *,
    sampled_prices: tuple[Decimal, ...],
    lookbacks: tuple[int, ...],
    return_interval_minutes: int,
    annualized_variance_floor: Decimal,
) -> BaselineStatistics:
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
    if not annualized_variance_floor > 0:
        raise BaselineUnavailable("remaining life or variance floor is invalid")
    try:
        with localcontext(DECIMAL_CONTEXT) as context:
            diagnostics: list[WindowDiagnostics] = []
            for lookback in sorted(lookbacks):
                sample_count = lookback // return_interval_minutes + 1
                sampled = sampled_prices[-sample_count:]
                returns = tuple(
                    context.ln(later) - context.ln(earlier) for earlier, later in pairwise(sampled)
                )
                squared = tuple(value * value for value in returns)
                realized_sum = sum(squared, Decimal(0))
                positive_sum = sum(
                    (square for value, square in zip(returns, squared, strict=True) if value > 0),
                    Decimal(0),
                )
                negative_sum = sum(
                    (square for value, square in zip(returns, squared, strict=True) if value < 0),
                    Decimal(0),
                )
                adjacent_absolute_product_sum = sum(
                    (abs(later) * abs(earlier) for earlier, later in pairwise(returns)),
                    Decimal(0),
                )
                return_count = len(returns)
                bipower_sum = (
                    PI_OVER_TWO
                    * Decimal(return_count)
                    / Decimal(return_count - 1)
                    * adjacent_absolute_product_sum
                    if return_count >= 2
                    else Decimal(0)
                )
                jump_sum = max(Decimal(0), realized_sum - bipower_sum)
                denominator = Decimal(lookback)
                variance_rate = realized_sum / denominator
                diagnostics.append(
                    WindowDiagnostics(
                        lookback_minutes=lookback,
                        return_count=len(returns),
                        variance_rate_per_minute=+variance_rate,
                        positive_semivariance_rate_per_minute=+(positive_sum / denominator),
                        negative_semivariance_rate_per_minute=+(negative_sum / denominator),
                        positive_semivariance_share=(
                            +(positive_sum / realized_sum) if realized_sum > 0 else Decimal(0)
                        ),
                        negative_semivariance_share=(
                            +(negative_sum / realized_sum) if realized_sum > 0 else Decimal(0)
                        ),
                        bipower_variation_rate_per_minute=+(bipower_sum / denominator),
                        jump_variation_rate_per_minute=+(jump_sum / denominator),
                        jump_share=(+(jump_sum / realized_sum) if realized_sum > 0 else Decimal(0)),
                        maximum_absolute_return=+max(
                            (abs(value) for value in returns),
                            default=Decimal(0),
                        ),
                        net_return=+sum(returns, Decimal(0)),
                    )
                )
            windows = tuple(
                (member.lookback_minutes, member.variance_rate_per_minute) for member in diagnostics
            )
            floor_per_minute = annualized_variance_floor / MINUTES_PER_YEAR
            maximum_window = max(windows, key=lambda item: (item[1], item[0]))
            mean_window_rate = sum(
                (variance_rate for _lookback, variance_rate in windows),
                Decimal(0),
            ) / Decimal(len(windows))
            reference_rate = (maximum_window[1] + mean_window_rate) / Decimal(2)
            selected_lookback: int | None = maximum_window[0]
            if floor_per_minute >= reference_rate:
                variance_rate = floor_per_minute
                selected_lookback = None
            else:
                variance_rate = reference_rate
            annualized = context.sqrt(variance_rate * MINUTES_PER_YEAR)
            statistics = BaselineStatistics(
                return_interval_minutes=return_interval_minutes,
                window_variances=windows,
                selected_lookback_minutes=selected_lookback,
                variance_rate_per_minute=+variance_rate,
                annualized_volatility=+annualized,
                window_diagnostics=tuple(diagnostics),
            )
    except (InvalidOperation, OverflowError) as exc:
        raise BaselineUnavailable("baseline arithmetic was not finite") from exc
    scalar_values = (
        statistics.variance_rate_per_minute,
        statistics.annualized_volatility,
        *(
            value
            for member in statistics.window_diagnostics
            for value in _diagnostic_decimals(member)
        ),
    )
    if not all(value.is_finite() for value in scalar_values):
        raise BaselineUnavailable("baseline arithmetic was not finite")
    return statistics


def project_baseline(
    *,
    statistics: BaselineStatistics,
    remaining_life_minutes_low: Decimal,
    remaining_life_minutes_high: Decimal,
) -> BaselineResult:
    if not Decimal(0) < remaining_life_minutes_low <= remaining_life_minutes_high:
        raise BaselineUnavailable("remaining life or variance floor is invalid")
    try:
        with localcontext(DECIMAL_CONTEXT):
            result = BaselineResult(
                return_interval_minutes=statistics.return_interval_minutes,
                window_variances=statistics.window_variances,
                selected_lookback_minutes=statistics.selected_lookback_minutes,
                variance_rate_per_minute=statistics.variance_rate_per_minute,
                annualized_volatility=statistics.annualized_volatility,
                total_variance_low=+(
                    statistics.variance_rate_per_minute * remaining_life_minutes_low
                ),
                total_variance_high=+(
                    statistics.variance_rate_per_minute * remaining_life_minutes_high
                ),
                window_diagnostics=statistics.window_diagnostics,
            )
    except (InvalidOperation, OverflowError) as exc:
        raise BaselineUnavailable("baseline arithmetic was not finite") from exc
    scalar_values = (
        result.variance_rate_per_minute,
        result.annualized_volatility,
        result.total_variance_low,
        result.total_variance_high,
        *(value for member in result.window_diagnostics for value in _diagnostic_decimals(member)),
    )
    if not all(value.is_finite() for value in scalar_values):
        raise BaselineUnavailable("baseline arithmetic was not finite")
    return result


def _diagnostic_decimals(member: WindowDiagnostics) -> tuple[Decimal, ...]:
    return (
        member.variance_rate_per_minute,
        member.positive_semivariance_rate_per_minute,
        member.negative_semivariance_rate_per_minute,
        member.positive_semivariance_share,
        member.negative_semivariance_share,
        member.bipower_variation_rate_per_minute,
        member.jump_variation_rate_per_minute,
        member.jump_share,
        member.maximum_absolute_return,
        member.net_return,
    )
