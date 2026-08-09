from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor import PriceLevel

from options_domain.instruments import InstrumentLifecycleState, OptionInstrument, OptionType
from options_domain.product import OptionProductSpec
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
    native_fee_reserve: Decimal
    native_premium_currency: str
    valuation_index_price: Decimal


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
    product_spec_identity: str
    product_name: str
    native_premium_currency: str
    settlement_currency: str
    price_index: str
    valuation_currency: str
    valuation_index_price: Decimal
    native_gross_cashflow: Decimal
    native_total_fee_reserve: Decimal
    native_net_cashflow: Decimal

    @property
    def consumed_level_count(self) -> int:
        return len(self.short_leg.stressed.consumed) + len(self.long_leg.stressed.consumed)

    @property
    def fingerprint_members(self) -> dict[str, object]:
        """Return the one canonical, scalar-only identity projection for this quote."""
        return {
            "execution_model": self.execution_model,
            "kind": self.kind.value,
            "product_spec_identity": self.product_spec_identity,
            "product_name": self.product_name,
            "native_premium_currency": self.native_premium_currency,
            "settlement_currency": self.settlement_currency,
            "price_index": self.price_index,
            "valuation_currency": self.valuation_currency,
            "valuation_index_price": self.valuation_index_price,
            "full_quantity_btc": self.full_quantity_btc,
            "short_leg": _leg_fingerprint_members(self.short_leg),
            "long_leg": _leg_fingerprint_members(self.long_leg),
            "native_gross_cashflow": self.native_gross_cashflow,
            "native_total_fee_reserve": self.native_total_fee_reserve,
            "native_net_cashflow": self.native_net_cashflow,
            "gross_cashflow_usdc": self.gross_cashflow_usdc,
            "total_fee_reserve_usdc": self.total_fee_reserve_usdc,
            "net_cashflow_usdc": self.net_cashflow_usdc,
            "width_usdc_per_btc": self.width_usdc_per_btc,
            "payoff_cap_usdc": self.payoff_cap_usdc,
        }


def component_quote_matches_product_contract(
    quote: ComponentBookVerticalQuote,
    *,
    product: OptionProductSpec,
    fee_rate: Decimal,
) -> bool:
    """Fail closed unless a component quote is arithmetically valid for one product."""
    try:
        if (
            quote.execution_model != COMPONENT_BOOK_EXECUTION_MODEL
            or not product.matches_component_contract(
                product_spec_identity=quote.product_spec_identity,
                product_name=quote.product_name,
                native_premium_currency=quote.native_premium_currency,
                settlement_currency=quote.settlement_currency,
                price_index=quote.price_index,
                valuation_currency=quote.valuation_currency,
            )
            or not _is_positive_decimal(quote.full_quantity_btc)
            or not _is_positive_decimal(quote.valuation_index_price)
            or not _is_non_negative_decimal(fee_rate)
            or not _is_positive_decimal(quote.width_usdc_per_btc)
            or not _is_non_negative_decimal(quote.payoff_cap_usdc)
            or quote.payoff_cap_usdc != quote.width_usdc_per_btc * quote.full_quantity_btc
        ):
            return False

        expected_actions = (
            (ComponentBookAction.SELL, ComponentBookAction.BUY)
            if quote.kind is ComponentBookQuoteKind.ENTRY
            else (ComponentBookAction.BUY, ComponentBookAction.SELL)
            if quote.kind is ComponentBookQuoteKind.CLOSE
            else None
        )
        if expected_actions is None:
            return False

        legs = (quote.short_leg, quote.long_leg)
        for leg, expected_action in zip(legs, expected_actions, strict=True):
            if (
                leg.action is not expected_action
                or not product.matches_instrument_name(leg.instrument_name)
                or leg.native_premium_currency != product.native_premium_currency
                or leg.valuation_index_price != quote.valuation_index_price
                or not _depth_walk_is_valid(leg.raw, quote.full_quantity_btc)
                or not _depth_walk_is_valid(leg.stressed, quote.full_quantity_btc)
                or not _stress_matches_action(leg.raw, leg.stressed, leg.action)
            ):
                return False
            expected_native_fee = product.native_option_fee(
                native_option_price=leg.stressed.vwap,
                index_price=quote.valuation_index_price,
                quantity_btc=quote.full_quantity_btc,
                fee_rate=fee_rate,
            )
            if (
                leg.native_fee_reserve != expected_native_fee
                or leg.fee_reserve_usdc
                != product.valuation(
                    expected_native_fee,
                    index_price=quote.valuation_index_price,
                )
            ):
                return False

        native_gross = _cashflow(quote.short_leg.stressed, quote.short_leg.action) + _cashflow(
            quote.long_leg.stressed, quote.long_leg.action
        )
        native_fee = quote.short_leg.native_fee_reserve + quote.long_leg.native_fee_reserve
        native_net = native_gross - native_fee
        valuation_gross = product.valuation(
            native_gross,
            index_price=quote.valuation_index_price,
        )
        valuation_fee = quote.short_leg.fee_reserve_usdc + quote.long_leg.fee_reserve_usdc
        valuation_net = valuation_gross - valuation_fee
        return (
            quote.short_leg.instrument_name != quote.long_leg.instrument_name
            and quote.native_gross_cashflow == native_gross
            and quote.native_total_fee_reserve == native_fee
            and quote.native_net_cashflow == native_net
            and quote.gross_cashflow_usdc == valuation_gross
            and quote.total_fee_reserve_usdc == valuation_fee
            and quote.net_cashflow_usdc == valuation_net
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        return False


def standard_option_fee_native(
    *,
    product: OptionProductSpec,
    index_price: Decimal,
    native_option_price: Decimal,
    quantity_btc: Decimal,
    fee_rate: Decimal,
) -> Decimal:
    return product.native_option_fee(
        native_option_price=native_option_price,
        index_price=index_price,
        quantity_btc=quantity_btc,
        fee_rate=fee_rate,
    )


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
    """Price one frozen vertical in native units and one causal USD valuation."""
    reasons = _structure_reasons(
        short_instrument=short_instrument,
        long_instrument=long_instrument,
        target_quantity_btc=target_quantity_btc,
    )
    if reasons:
        return None, reasons
    assert short_instrument.price_tick is not None
    assert long_instrument.price_tick is not None
    product = short_instrument.product

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

    short_native_fee = standard_option_fee_native(
        product=product,
        index_price=index_usdc_per_btc,
        native_option_price=short_stressed.vwap,
        quantity_btc=target_quantity_btc,
        fee_rate=fee_rate_index_fraction,
    )
    long_native_fee = standard_option_fee_native(
        product=product,
        index_price=index_usdc_per_btc,
        native_option_price=long_stressed.vwap,
        quantity_btc=target_quantity_btc,
        fee_rate=fee_rate_index_fraction,
    )
    native_gross_cashflow = _cashflow(short_stressed, short_action) + _cashflow(
        long_stressed, long_action
    )
    native_total_fee = short_native_fee + long_native_fee
    native_net_cashflow = native_gross_cashflow - native_total_fee
    if kind is ComponentBookQuoteKind.ENTRY:
        if native_gross_cashflow <= 0:
            return None, ("NON_POSITIVE_STRESSED_GROSS_CREDIT",)
        if native_net_cashflow <= 0:
            return None, ("NON_POSITIVE_STRESSED_NET_CREDIT",)

    short_valuation_fee = product.valuation(short_native_fee, index_price=index_usdc_per_btc)
    long_valuation_fee = product.valuation(long_native_fee, index_price=index_usdc_per_btc)
    gross_valuation = product.valuation(
        native_gross_cashflow,
        index_price=index_usdc_per_btc,
    )
    total_fee_valuation = short_valuation_fee + long_valuation_fee
    net_valuation = gross_valuation - total_fee_valuation
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
                fee_reserve_usdc=short_valuation_fee,
                native_fee_reserve=short_native_fee,
                native_premium_currency=product.native_premium_currency,
                valuation_index_price=index_usdc_per_btc,
            ),
            long_leg=ComponentBookLegQuote(
                instrument_name=long_instrument.instrument_name,
                action=long_action,
                raw=long_raw,
                stressed=long_stressed,
                fee_reserve_usdc=long_valuation_fee,
                native_fee_reserve=long_native_fee,
                native_premium_currency=product.native_premium_currency,
                valuation_index_price=index_usdc_per_btc,
            ),
            gross_cashflow_usdc=gross_valuation,
            total_fee_reserve_usdc=total_fee_valuation,
            net_cashflow_usdc=net_valuation,
            width_usdc_per_btc=width,
            payoff_cap_usdc=payoff_cap,
            product_spec_identity=product.identity,
            product_name=product.name.value,
            native_premium_currency=product.native_premium_currency,
            settlement_currency=product.settlement_currency,
            price_index=product.price_index,
            valuation_currency=product.valuation_currency,
            valuation_index_price=index_usdc_per_btc,
            native_gross_cashflow=native_gross_cashflow,
            native_total_fee_reserve=native_total_fee,
            native_net_cashflow=native_net_cashflow,
        ),
        (),
    )


def is_protective_vertical(short: OptionInstrument, long: OptionInstrument) -> bool:
    if (
        long.instrument_name == short.instrument_name
        or long.product != short.product
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


def _depth_walk_is_valid(walk: DepthWalk, target_quantity: Decimal) -> bool:
    if (
        walk.target_amount != target_quantity
        or not _is_positive_decimal(walk.target_amount)
        or not walk.consumed
        or not _is_positive_decimal(walk.total_value)
        or not _is_positive_decimal(walk.vwap)
    ):
        return False
    total_amount = Decimal(0)
    total_value = Decimal(0)
    for level in walk.consumed:
        if not _is_positive_decimal(level.price) or not _is_positive_decimal(level.amount):
            return False
        total_amount += level.amount
        total_value += level.price * level.amount
    return (
        total_amount == target_quantity
        and walk.total_value == total_value
        and walk.vwap == total_value / target_quantity
    )


def _stress_matches_action(
    raw: DepthWalk,
    stressed: DepthWalk,
    action: ComponentBookAction,
) -> bool:
    if len(raw.consumed) != len(stressed.consumed):
        return False
    for raw_level, stressed_level in zip(raw.consumed, stressed.consumed, strict=True):
        if raw_level.amount != stressed_level.amount:
            return False
        if action is ComponentBookAction.SELL:
            if stressed_level.price >= raw_level.price:
                return False
        elif action is ComponentBookAction.BUY:
            if stressed_level.price <= raw_level.price:
                return False
        else:
            return False
    return True


def _is_positive_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _is_non_negative_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _leg_fingerprint_members(quote: ComponentBookLegQuote) -> dict[str, object]:
    return {
        "instrument_name": quote.instrument_name,
        "action": quote.action.value,
        "native_premium_currency": quote.native_premium_currency,
        "raw": tuple((level.price, level.amount) for level in quote.raw.consumed),
        "stressed": tuple((level.price, level.amount) for level in quote.stressed.consumed),
        "native_fee_reserve": quote.native_fee_reserve,
        "valuation_index_price": quote.valuation_index_price,
        "fee_reserve_usdc": quote.fee_reserve_usdc,
    }
