from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from optimatrix.products import ProductSpec


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class EventState(StrEnum):
    NONE = "NONE"
    PRE_EVENT = "PRE_EVENT"
    LIVE_EVENT = "LIVE_EVENT"
    POST_EVENT = "POST_EVENT"
    UNSCHEDULED_SHOCK = "UNSCHEDULED_SHOCK"


class BreakoutState(StrEnum):
    MEAN_REVERTING = "MEAN_REVERTING"
    NEUTRAL = "NEUTRAL"
    APPROACHING_CONCENTRATED_STRIKE = "APPROACHING_CONCENTRATED_STRIKE"
    BREAKING_CONCENTRATED_STRIKE = "BREAKING_CONCENTRATED_STRIKE"


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    quantity: Decimal

    def __post_init__(self) -> None:
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("level price must be finite and positive")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("level quantity must be finite and positive")


@dataclass(frozen=True)
class TickStep:
    above_price: Decimal
    tick_size: Decimal


@dataclass(frozen=True)
class TickSchedule:
    base_tick: Decimal
    steps: tuple[TickStep, ...] = ()

    def __post_init__(self) -> None:
        if not self.base_tick.is_finite() or self.base_tick <= 0:
            raise ValueError("base tick must be finite and positive")
        prior = Decimal("-1")
        prior_tick = self.base_tick
        for step in self.steps:
            if (
                not step.above_price.is_finite()
                or step.above_price < 0
                or not step.tick_size.is_finite()
                or step.tick_size <= prior_tick
                or step.tick_size % self.base_tick != 0
                or step.above_price <= prior
            ):
                raise ValueError("tick steps must increase and use positive base-tick multiples")
            prior = step.above_price
            prior_tick = step.tick_size

    def tick_at(self, price: Decimal) -> Decimal:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        tick = self.base_tick
        for step in self.steps:
            if price < step.above_price:
                break
            tick = step.tick_size
        return tick

    def previous_price(self, price: Decimal) -> Decimal | None:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        regime_index = self._regime_index(price)
        lower_boundary = (
            self.steps[regime_index - 1].above_price if regime_index > 0 else Decimal(0)
        )
        current_tick = (
            self.steps[regime_index - 1].tick_size if regime_index > 0 else self.base_tick
        )
        candidate = price - current_tick
        if candidate >= lower_boundary and candidate > 0:
            return candidate
        if regime_index == 0:
            return None
        previous_tick = (
            self.steps[regime_index - 2].tick_size if regime_index > 1 else self.base_tick
        )
        candidate = lower_boundary - previous_tick
        return candidate if candidate > 0 else None

    def next_price(self, price: Decimal) -> Decimal:
        if not price.is_finite() or price <= 0:
            raise ValueError("price must be finite and positive")
        regime_index = self._regime_index(price)
        current_tick = (
            self.steps[regime_index - 1].tick_size if regime_index > 0 else self.base_tick
        )
        candidate = price + current_tick
        if regime_index < len(self.steps):
            next_boundary = self.steps[regime_index].above_price
            if price < next_boundary <= candidate:
                return next_boundary
        return candidate

    def _regime_index(self, price: Decimal) -> int:
        index = 0
        for step in self.steps:
            if price < step.above_price:
                break
            index += 1
        return index

    def tick_distance(self, lower: Decimal, upper: Decimal) -> Decimal:
        if lower <= 0 or upper < lower:
            raise ValueError("tick distance bounds are invalid")
        if lower == upper:
            return Decimal(0)
        boundaries = tuple(
            step.above_price for step in self.steps if lower < step.above_price < upper
        )
        current = lower
        distance = Decimal(0)
        for boundary in (*boundaries, upper):
            distance += (boundary - current) / self.tick_at(current)
            current = boundary
        return distance


@dataclass(frozen=True)
class OptionQuote:
    instrument_name: str
    product: ProductSpec
    expiry: datetime
    strike: Decimal
    option_type: OptionType
    signed_delta: Decimal
    mark_iv: Decimal
    bid: tuple[PriceLevel, ...]
    ask: tuple[PriceLevel, ...]
    tick_schedule: TickSchedule
    source_timestamp_ms: int
    received_timestamp_ms: int
    continuity_epoch: int
    delivery_fee_exempt: bool
    open_interest: Decimal = Decimal(0)
    gamma: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not self.instrument_name.startswith(self.product.instrument_prefix):
            raise ValueError("instrument_name does not match product")
        if self.expiry.tzinfo is None:
            raise ValueError("expiry must be timezone-aware")
        if not self.strike.is_finite() or self.strike <= 0:
            raise ValueError("strike must be finite and positive")
        if not self.signed_delta.is_finite() or abs(self.signed_delta) > 1:
            raise ValueError("signed_delta must be finite and bounded")
        if not self.mark_iv.is_finite() or self.mark_iv <= 0:
            raise ValueError("mark_iv must be finite and positive")
        if not self.open_interest.is_finite() or self.open_interest < 0:
            raise ValueError("open_interest must be finite and non-negative")
        if not self.gamma.is_finite() or self.gamma < 0:
            raise ValueError("gamma must be finite and non-negative")
        if not isinstance(self.delivery_fee_exempt, bool):
            raise ValueError("delivery_fee_exempt must be boolean")
        if any(
            current.price > previous.price
            for previous, current in zip(self.bid, self.bid[1:], strict=False)
        ):
            raise ValueError("bid levels must be sorted from highest to lowest")
        if any(
            current.price < previous.price
            for previous, current in zip(self.ask, self.ask[1:], strict=False)
        ):
            raise ValueError("ask levels must be sorted from lowest to highest")
        if self.bid and self.ask and self.bid[0].price >= self.ask[0].price:
            raise ValueError("option quote must be uncrossed")
        for value, field_name in (
            (self.source_timestamp_ms, "source_timestamp_ms"),
            (self.received_timestamp_ms, "received_timestamp_ms"),
            (self.continuity_epoch, "continuity_epoch"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True)
class MarketContext:
    now: datetime
    index_price: Decimal
    forward_price: Decimal
    physical_variance_forecast: Decimal
    same_session_implied_variance: Decimal
    rv_acceleration: Decimal
    jump_share: Decimal
    directional_persistence: Decimal
    event_state: EventState
    breakout_state: BreakoutState
    concentrated_strike: Decimal | None
    concentration_strength: Decimal

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise ValueError("market context time must be timezone-aware")
        for value, field_name in (
            (self.index_price, "index_price"),
            (self.forward_price, "forward_price"),
            (self.physical_variance_forecast, "physical_variance_forecast"),
            (self.same_session_implied_variance, "same_session_implied_variance"),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")
        for value, field_name in (
            (self.rv_acceleration, "rv_acceleration"),
            (self.jump_share, "jump_share"),
            (self.directional_persistence, "directional_persistence"),
            (self.concentration_strength, "concentration_strength"),
        ):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError(f"{field_name} must be in [0, 1]")
        if self.concentrated_strike is not None and (
            not self.concentrated_strike.is_finite() or self.concentrated_strike <= 0
        ):
            raise ValueError("concentrated_strike must be positive when present")
