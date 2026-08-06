from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor import PriceLevel

from options_domain.instruments import InstrumentLifecycleState, OptionInstrument, OptionType
from options_domain.quotes import (
    AmountState,
    DepthWalk,
    check_target_amount,
    stress_depth_walk_down_one_tick,
    stress_depth_walk_up_one_tick,
    walk_target_depth,
)

COMPONENT_BOOK_EXECUTION_MODEL = "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL"
PREMIUM_FEE_CAP_FRACTION = Decimal("0.125")


class ComponentBookQuoteKind(StrEnum):
    ENTRY = "ENTRY"
    CLOSE = "CLOSE"


class ComponentBookAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class ComponentBookLegQuote:
    instrument_name: str
    action: ComponentBookAction
    raw: DepthWalk
    stressed: DepthWalk
    fee_reserve_usdc: Decimal


@dataclass(frozen=True)
class ComponentBookVerticalQuote:
    execution_model: str
    kind: ComponentBookQuoteKind
    full_quantity_btc: Decimal
    short_leg: ComponentBookLegQuote
    long_leg: ComponentBookLegQuote
    gross_cashflow_usdc: Decimal
    total_fee_reserve_usdc: Decimal
    net_cashflow_usdc: Decimal
    width_usdc_per_btc: Decimal
    payoff_cap_usdc: Decimal

    @property
    def consumed_level_count(self) -> int:
        return len(self.short_leg.stressed.consumed) + len(self.long_leg.stressed.consumed)

    @property
    def fingerprint_members(self) -> dict[str, object]:
        """Return the one canonical, scalar-only identity projection for this quote."""
        return {
            "execution_model": self.execution_model,
            "kind": self.kind.value,
            "full_quantity_btc": self.full_quantity_btc,
            "short_leg": _leg_fingerprint_members(self.short_leg),
            "long_leg": _leg_fingerprint_members(self.long_leg),
            "gross_cashflow_usdc": self.gross_cashflow_usdc,
            "total_fee_reserve_usdc": self.total_fee_reserve_usdc,
            "net_cashflow_usdc": self.net_cashflow_usdc,
            "width_usdc_per_btc": self.width_usdc_per_btc,
            "payoff_cap_usdc": self.payoff_cap_usdc,
        }


def standard_option_fee_usdc(
    *,
    index_usdc_per_btc: Decimal,
    option_price_usdc_per_btc: Decimal,
    quantity_btc: Decimal,
    fee_rate_index_fraction: Decimal,
) -> Decimal:
    _require_positive(index_usdc_per_btc, "index_usdc_per_btc")
    _require_positive(option_price_usdc_per_btc, "option_price_usdc_per_btc")
    _require_positive(quantity_btc, "quantity_btc")
    _require_non_negative(fee_rate_index_fraction, "fee_rate_index_fraction")
    index_fee = fee_rate_index_fraction * index_usdc_per_btc * quantity_btc
    premium_cap = PREMIUM_FEE_CAP_FRACTION * option_price_usdc_per_btc * quantity_btc
    return min(index_fee, premium_cap)


def evaluate_component_book_vertical(
    *,
    kind: ComponentBookQuoteKind,
    short_instrument: OptionInstrument,
    long_instrument: OptionInstrument,
    short_side_levels: tuple[PriceLevel, ...],
    long_side_levels: tuple[PriceLevel, ...],
    index_usdc_per_btc: Decimal,
    target_quantity_btc: Decimal,
    fee_rate_index_fraction: Decimal,
) -> tuple[ComponentBookVerticalQuote | None, tuple[str, ...]]:
    """Price one frozen protective vertical from two public component books."""
    reasons = _structure_reasons(
        short_instrument=short_instrument,
        long_instrument=long_instrument,
        target_quantity_btc=target_quantity_btc,
    )
    if reasons:
        return None, reasons
    assert short_instrument.price_tick is not None
    assert long_instrument.price_tick is not None

    short_raw = walk_target_depth(short_side_levels, target_quantity_btc)
    long_raw = walk_target_depth(long_side_levels, target_quantity_btc)
    if short_raw is None or long_raw is None:
        missing = []
        if short_raw is None:
            missing.append("SHORT_TARGET_DEPTH_INSUFFICIENT")
        if long_raw is None:
            missing.append("LONG_TARGET_DEPTH_INSUFFICIENT")
        return None, tuple(missing)

    if kind is ComponentBookQuoteKind.ENTRY:
        short_action = ComponentBookAction.SELL
        long_action = ComponentBookAction.BUY
    else:
        short_action = ComponentBookAction.BUY
        long_action = ComponentBookAction.SELL
    short_stressed = _stress(short_raw, short_instrument, short_action)
    long_stressed = _stress(long_raw, long_instrument, long_action)
    if short_stressed is None or long_stressed is None:
        missing = []
        if short_stressed is None:
            missing.append("SHORT_STRESSED_PRICE_NON_POSITIVE")
        if long_stressed is None:
            missing.append("LONG_STRESSED_PRICE_NON_POSITIVE")
        return None, tuple(missing)

    short_fee = standard_option_fee_usdc(
        index_usdc_per_btc=index_usdc_per_btc,
        option_price_usdc_per_btc=short_stressed.vwap,
        quantity_btc=target_quantity_btc,
        fee_rate_index_fraction=fee_rate_index_fraction,
    )
    long_fee = standard_option_fee_usdc(
        index_usdc_per_btc=index_usdc_per_btc,
        option_price_usdc_per_btc=long_stressed.vwap,
        quantity_btc=target_quantity_btc,
        fee_rate_index_fraction=fee_rate_index_fraction,
    )
    gross_cashflow = _cashflow(short_stressed, short_action) + _cashflow(long_stressed, long_action)
    total_fee = short_fee + long_fee
    net_cashflow = gross_cashflow - total_fee
    if kind is ComponentBookQuoteKind.ENTRY:
        if gross_cashflow <= 0:
            return None, ("NON_POSITIVE_STRESSED_GROSS_CREDIT",)
        if net_cashflow <= 0:
            return None, ("NON_POSITIVE_STRESSED_NET_CREDIT",)
    width = abs(long_instrument.strike - short_instrument.strike)
    payoff_cap = width * target_quantity_btc
    return (
        ComponentBookVerticalQuote(
            execution_model=COMPONENT_BOOK_EXECUTION_MODEL,
            kind=kind,
            full_quantity_btc=target_quantity_btc,
            short_leg=ComponentBookLegQuote(
                instrument_name=short_instrument.instrument_name,
                action=short_action,
                raw=short_raw,
                stressed=short_stressed,
                fee_reserve_usdc=short_fee,
            ),
            long_leg=ComponentBookLegQuote(
                instrument_name=long_instrument.instrument_name,
                action=long_action,
                raw=long_raw,
                stressed=long_stressed,
                fee_reserve_usdc=long_fee,
            ),
            gross_cashflow_usdc=gross_cashflow,
            total_fee_reserve_usdc=total_fee,
            net_cashflow_usdc=net_cashflow,
            width_usdc_per_btc=width,
            payoff_cap_usdc=payoff_cap,
        ),
        (),
    )


def is_protective_vertical(short: OptionInstrument, long: OptionInstrument) -> bool:
    if (
        long.instrument_name == short.instrument_name
        or long.expiration_timestamp_ms != short.expiration_timestamp_ms
        or long.option_type is not short.option_type
    ):
        return False
    if short.option_type is OptionType.CALL:
        return long.strike > short.strike
    return long.strike < short.strike


def _structure_reasons(
    *,
    short_instrument: OptionInstrument,
    long_instrument: OptionInstrument,
    target_quantity_btc: Decimal,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not is_protective_vertical(short_instrument, long_instrument):
        reasons.append("NOT_A_PROTECTIVE_VERTICAL")
    for label, instrument in (("SHORT", short_instrument), ("LONG", long_instrument)):
        if (
            instrument.lifecycle_state is not InstrumentLifecycleState.OPEN
            or not instrument.is_active
        ):
            reasons.append(f"{label}_LEG_NOT_OPEN_ACTIVE")
        if instrument.amount is None:
            reasons.append(f"{label}_AMOUNT_METADATA_UNKNOWN")
        elif (
            check_target_amount(target_quantity_btc, instrument.amount).state
            is AmountState.INELIGIBLE
        ):
            reasons.append(f"{label}_TARGET_AMOUNT_INELIGIBLE")
        if instrument.price_tick is None:
            reasons.append(f"{label}_PRICE_TICK_METADATA_UNKNOWN")
    return tuple(reasons)


def _stress(
    raw: DepthWalk,
    instrument: OptionInstrument,
    action: ComponentBookAction,
) -> DepthWalk | None:
    assert instrument.price_tick is not None
    if action is ComponentBookAction.SELL:
        return stress_depth_walk_down_one_tick(raw, instrument.price_tick)
    return stress_depth_walk_up_one_tick(raw, instrument.price_tick)


def _cashflow(walk: DepthWalk, action: ComponentBookAction) -> Decimal:
    return walk.total_value if action is ComponentBookAction.SELL else -walk.total_value


def _leg_fingerprint_members(quote: ComponentBookLegQuote) -> dict[str, object]:
    return {
        "instrument_name": quote.instrument_name,
        "action": quote.action.value,
        "raw": tuple((level.price, level.amount) for level in quote.raw.consumed),
        "stressed": tuple((level.price, level.amount) for level in quote.stressed.consumed),
        "fee_reserve_usdc": quote.fee_reserve_usdc,
    }


def _require_positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be finite and positive")


def _require_non_negative(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < 0:
        raise ValueError(f"{field} must be finite and non-negative")
