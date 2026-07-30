from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, localcontext

from options_domain import OptionType

from short_vol_radar.baseline import DECIMAL_CONTEXT


class NumericalUnknown(ValueError):
    """The canonical solver cannot prove one detector truth."""


@dataclass(frozen=True)
class TotalVolatilityInterval:
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True)
class DecimalInterval:
    lower: Decimal
    upper: Decimal

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("interval lower bound exceeds upper bound")


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_price(forward: float, strike: float, total_volatility: float, kind: OptionType) -> float:
    if not all(math.isfinite(value) and value > 0 for value in (forward, strike)):
        raise NumericalUnknown("forward and strike must be finite and positive")
    if not math.isfinite(total_volatility) or total_volatility < 0:
        raise NumericalUnknown("total volatility must be finite and non-negative")
    if total_volatility == 0:
        intrinsic = max(forward - strike, 0.0)
        return intrinsic if kind is OptionType.CALL else max(strike - forward, 0.0)
    d1 = (math.log(forward / strike) + 0.5 * total_volatility**2) / total_volatility
    d2 = d1 - total_volatility
    if kind is OptionType.CALL:
        return forward * normal_cdf(d1) - strike * normal_cdf(d2)
    return strike * normal_cdf(-d2) - forward * normal_cdf(-d1)


def invert_total_volatility(
    *,
    target_price: Decimal,
    forward: Decimal,
    strike: Decimal,
    option_type: OptionType,
) -> TotalVolatilityInterval:
    values = (target_price, forward, strike)
    if any(not value.is_finite() or value <= 0 for value in values):
        raise NumericalUnknown("price, forward, and strike must be finite and positive")
    target = float(target_price)
    forward_float = float(forward)
    strike_float = float(strike)
    upper_domain = forward_float if option_type is OptionType.CALL else strike_float
    if not 0 < target < upper_domain:
        raise NumericalUnknown("target option price is outside the finite formula domain")
    low = 0.0
    high = 1.0
    for _ in range(32):
        if black_price(forward_float, strike_float, high, option_type) >= target:
            break
        high *= 2.0
        if not math.isfinite(high):
            raise NumericalUnknown("total-volatility bracket overflowed")
    else:
        raise NumericalUnknown("target option price was not bracketed")
    for _ in range(64):
        midpoint = (low + high) / 2.0
        if midpoint == low or midpoint == high:
            break
        if black_price(forward_float, strike_float, midpoint, option_type) >= target:
            high = midpoint
        else:
            low = midpoint
    return TotalVolatilityInterval(_decimal_round_trip(low), _decimal_round_trip(high))


def delta_interval(
    *,
    forward: Decimal,
    strike: Decimal,
    total_volatility: TotalVolatilityInterval,
    option_type: OptionType,
) -> DecimalInterval:
    forward_float = float(forward)
    strike_float = float(strike)
    low = max(float(total_volatility.lower), math.nextafter(0.0, 1.0))
    high = float(total_volatility.upper)
    if not 0 < low <= high:
        raise NumericalUnknown("invalid total-volatility interval")
    points = [low, high]
    log_moneyness = math.log(forward_float / strike_float)
    if log_moneyness > 0:
        stationary = math.sqrt(2.0 * log_moneyness)
        if low <= stationary <= high:
            points.append(stationary)
    deltas: list[float] = []
    for total_vol in points:
        d1 = log_moneyness / total_vol + 0.5 * total_vol
        call_delta = normal_cdf(d1)
        deltas.append(call_delta if option_type is OptionType.CALL else call_delta - 1.0)
    return DecimalInterval(
        _decimal_round_trip(min(deltas)),
        _decimal_round_trip(max(deltas)),
    )


def executable_iv_interval(
    *,
    total_volatility: TotalVolatilityInterval,
    time_years: DecimalInterval,
) -> DecimalInterval:
    if time_years.lower <= 0:
        raise NumericalUnknown("time interval must be strictly positive")
    with localcontext(DECIMAL_CONTEXT) as context:
        lower = total_volatility.lower / context.sqrt(time_years.upper)
        upper = total_volatility.upper / context.sqrt(time_years.lower)
    if not lower.is_finite() or not upper.is_finite():
        raise NumericalUnknown("implied-volatility interval is not finite")
    return DecimalInterval(+lower, +upper)


def ratio_interval(numerator: DecimalInterval, denominator: Decimal) -> DecimalInterval:
    if not denominator.is_finite() or denominator <= 0:
        raise NumericalUnknown("ratio denominator must be finite and positive")
    with localcontext(DECIMAL_CONTEXT):
        return DecimalInterval(+(numerator.lower / denominator), +(numerator.upper / denominator))


def _decimal_round_trip(value: float) -> Decimal:
    if not math.isfinite(value):
        raise NumericalUnknown("binary64 model result is not finite")
    return Decimal(str(value))
