from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor.types import PriceLevel

from options_domain.instruments import AmountMetadata, PriceTickMetadata


class AmountState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


@dataclass(frozen=True)
class AmountCheck:
    state: AmountState
    reason: str | None


@dataclass(frozen=True)
class DepthWalk:
    consumed: tuple[PriceLevel, ...]
    target_amount: Decimal
    total_value: Decimal
    vwap: Decimal


def check_target_amount(target: Decimal, metadata: AmountMetadata) -> AmountCheck:
    if not target.is_finite() or target <= 0:
        raise ValueError("target amount must be finite and positive")
    if target < metadata.min_trade_amount:
        return AmountCheck(AmountState.INELIGIBLE, "BELOW_MIN_TRADE_AMOUNT")
    if metadata.qty_tick_size is not None and target % metadata.qty_tick_size != 0:
        return AmountCheck(AmountState.INELIGIBLE, "OFF_PUBLISHED_QUANTITY_GRID")
    return AmountCheck(AmountState.ELIGIBLE, None)


def walk_target_depth(levels: tuple[PriceLevel, ...], target: Decimal) -> DepthWalk | None:
    if not target.is_finite() or target <= 0:
        raise ValueError("target amount must be finite and positive")
    remaining = target
    consumed: list[PriceLevel] = []
    total_value = Decimal(0)
    for level in levels:
        if not level.price.is_finite() or not level.amount.is_finite() or level.amount <= 0:
            raise ValueError("book levels must contain finite price and positive amount")
        take = min(level.amount, remaining)
        if take > 0:
            consumed.append(PriceLevel(level.price, take))
            total_value += level.price * take
            remaining -= take
        if remaining == 0:
            return DepthWalk(
                consumed=tuple(consumed),
                target_amount=target,
                total_value=total_value,
                vwap=total_value / target,
            )
    return None


def stress_depth_walk_down_one_tick(
    walk: DepthWalk,
    price_ticks: PriceTickMetadata,
) -> DepthWalk | None:
    consumed: list[PriceLevel] = []
    total_value = Decimal(0)
    for level in walk.consumed:
        stressed_price = price_ticks.previous_legal_price(level.price)
        if stressed_price is None:
            return None
        consumed.append(PriceLevel(stressed_price, level.amount))
        total_value += stressed_price * level.amount
    return DepthWalk(
        consumed=tuple(consumed),
        target_amount=walk.target_amount,
        total_value=total_value,
        vwap=total_value / walk.target_amount,
    )


def stress_depth_walk_up_one_tick(
    walk: DepthWalk,
    price_ticks: PriceTickMetadata,
) -> DepthWalk:
    consumed: list[PriceLevel] = []
    total_value = Decimal(0)
    for level in walk.consumed:
        stressed_price = price_ticks.next_legal_price(level.price)
        consumed.append(PriceLevel(stressed_price, level.amount))
        total_value += stressed_price * level.amount
    return DepthWalk(
        consumed=tuple(consumed),
        target_amount=walk.target_amount,
        total_value=total_value,
        vwap=total_value / walk.target_amount,
    )
