from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from optimatrix.market import OptionQuote, PriceLevel
from optimatrix.products import ProductSpec


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class DepthWalk:
    levels: tuple[PriceLevel, ...]
    quantity: Decimal
    native_total: Decimal
    native_vwap: Decimal


@dataclass(frozen=True)
class LegExecution:
    instrument_name: str
    action: Action
    quantity: Decimal
    raw: DepthWalk
    stressed: DepthWalk
    native_fee: Decimal
    native_cashflow: Decimal
    usd_cashflow: Decimal
    usd_fee: Decimal


@dataclass(frozen=True)
class VerticalExecution:
    short_leg: LegExecution
    long_leg: LegExecution
    native_gross_credit: Decimal
    native_total_fee: Decimal
    native_net_credit: Decimal
    usd_gross_credit: Decimal
    usd_total_fee: Decimal
    usd_net_credit: Decimal
    width_usd_per_unit: Decimal
    payoff_cap_usd: Decimal

    @property
    def consumed_level_count(self) -> int:
        return len(self.short_leg.stressed.levels) + len(self.long_leg.stressed.levels)


@dataclass(frozen=True)
class SettlementLegCashflow:
    contractual_cashflow_native: Decimal
    delivery_fee_native: Decimal
    net_cashflow_native: Decimal


@dataclass(frozen=True)
class IronCondorExecution:
    put_vertical: VerticalExecution
    call_vertical: VerticalExecution
    native_gross_credit: Decimal
    native_total_fee: Decimal
    native_net_credit: Decimal
    usd_gross_credit: Decimal
    usd_total_fee: Decimal
    usd_net_credit: Decimal
    put_payoff_cap_usd: Decimal
    call_payoff_cap_usd: Decimal
    maximum_side_payoff_cap_usd: Decimal
    entry_boundary_max_loss_usd: Decimal


def walk_depth(levels: tuple[PriceLevel, ...], quantity: Decimal) -> DepthWalk | None:
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("quantity must be finite and positive")
    remaining = quantity
    consumed: list[PriceLevel] = []
    total = Decimal(0)
    for level in levels:
        take = min(level.quantity, remaining)
        if take > 0:
            consumed.append(PriceLevel(level.price, take))
            total += level.price * take
            remaining -= take
        if remaining == 0:
            return DepthWalk(tuple(consumed), quantity, total, total / quantity)
    return None


def execute_leg(
    quote: OptionQuote,
    *,
    action: Action,
    quantity: Decimal,
    index_price: Decimal,
) -> LegExecution | None:
    quote.product.check_quantity(quantity)
    source = quote.ask if action is Action.BUY else quote.bid
    raw = walk_depth(source, quantity)
    if raw is None:
        return None
    stressed_levels: list[PriceLevel] = []
    stressed_total = Decimal(0)
    for level in raw.levels:
        stressed_price = (
            quote.tick_schedule.next_price(level.price)
            if action is Action.BUY
            else quote.tick_schedule.previous_price(level.price)
        )
        if stressed_price is None or stressed_price <= 0:
            return None
        stressed_levels.append(PriceLevel(stressed_price, level.quantity))
        stressed_total += stressed_price * level.quantity
    stressed = DepthWalk(
        levels=tuple(stressed_levels),
        quantity=quantity,
        native_total=stressed_total,
        native_vwap=stressed_total / quantity,
    )
    native_fee = quote.product.native_option_fee(
        native_option_price=stressed.native_vwap,
        quantity=quantity,
    )
    native_cashflow = stressed.native_total if action is Action.SELL else -stressed.native_total
    return LegExecution(
        instrument_name=quote.instrument_name,
        action=action,
        quantity=quantity,
        raw=raw,
        stressed=stressed,
        native_fee=native_fee,
        native_cashflow=native_cashflow,
        usd_cashflow=quote.product.value_native(native_cashflow, index_price=index_price),
        usd_fee=quote.product.value_native(native_fee, index_price=index_price),
    )


def price_credit_vertical(
    *,
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    quantity: Decimal,
    index_price: Decimal,
) -> VerticalExecution | None:
    if short_quote.product != long_quote.product:
        raise ValueError("vertical legs must use one product")
    if (
        short_quote.expiry != long_quote.expiry
        or short_quote.option_type is not long_quote.option_type
    ):
        raise ValueError("vertical legs must share expiry and option type")
    if short_quote.option_type.value == "CALL" and long_quote.strike <= short_quote.strike:
        raise ValueError("call long wing must be above the short strike")
    if short_quote.option_type.value == "PUT" and long_quote.strike >= short_quote.strike:
        raise ValueError("put long wing must be below the short strike")
    short = execute_leg(short_quote, action=Action.SELL, quantity=quantity, index_price=index_price)
    long = execute_leg(long_quote, action=Action.BUY, quantity=quantity, index_price=index_price)
    if short is None or long is None:
        return None
    product = short_quote.product
    native_gross = short.native_cashflow + long.native_cashflow
    native_fee = short.native_fee + long.native_fee
    native_net = native_gross - native_fee
    if native_gross <= 0 or native_net <= 0:
        return None
    usd_gross = product.value_native(native_gross, index_price=index_price)
    usd_fee = product.value_native(native_fee, index_price=index_price)
    width = abs(long_quote.strike - short_quote.strike)
    payoff_cap = width * quantity
    return VerticalExecution(
        short_leg=short,
        long_leg=long,
        native_gross_credit=native_gross,
        native_total_fee=native_fee,
        native_net_credit=native_net,
        usd_gross_credit=usd_gross,
        usd_total_fee=usd_fee,
        usd_net_credit=usd_gross - usd_fee,
        width_usd_per_unit=width,
        payoff_cap_usd=payoff_cap,
    )


def combine_condor(
    put_vertical: VerticalExecution,
    call_vertical: VerticalExecution,
) -> IronCondorExecution:
    if put_vertical.short_leg.quantity != call_vertical.short_leg.quantity:
        raise ValueError("condor side quantities must match")
    native_gross = put_vertical.native_gross_credit + call_vertical.native_gross_credit
    native_fee = put_vertical.native_total_fee + call_vertical.native_total_fee
    native_net = put_vertical.native_net_credit + call_vertical.native_net_credit
    usd_gross = put_vertical.usd_gross_credit + call_vertical.usd_gross_credit
    usd_fee = put_vertical.usd_total_fee + call_vertical.usd_total_fee
    usd_net = put_vertical.usd_net_credit + call_vertical.usd_net_credit
    maximum_payoff = max(put_vertical.payoff_cap_usd, call_vertical.payoff_cap_usd)
    return IronCondorExecution(
        put_vertical=put_vertical,
        call_vertical=call_vertical,
        native_gross_credit=native_gross,
        native_total_fee=native_fee,
        native_net_credit=native_net,
        usd_gross_credit=usd_gross,
        usd_total_fee=usd_fee,
        usd_net_credit=usd_net,
        put_payoff_cap_usd=put_vertical.payoff_cap_usd,
        call_payoff_cap_usd=call_vertical.payoff_cap_usd,
        maximum_side_payoff_cap_usd=maximum_payoff,
        entry_boundary_max_loss_usd=max(Decimal(0), maximum_payoff - usd_net),
    )


def intrinsic_payoff_usd(
    *,
    option_type: str,
    strike: Decimal,
    delivery_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if option_type == "CALL":
        return max(Decimal(0), delivery_price - strike) * quantity
    if option_type == "PUT":
        return max(Decimal(0), strike - delivery_price) * quantity
    raise ValueError("option_type must be CALL or PUT")


def settle_option_leg(
    *,
    product: ProductSpec,
    option_type: str,
    strike: Decimal,
    delivery_price: Decimal,
    quantity: Decimal,
    action: Action,
    delivery_fee_exempt: bool,
) -> SettlementLegCashflow:
    """Settle one Inverse option leg and reserve the public delivery fee.

    The fee is charged only on positive contractual payoff and is capped at
    12.5% of that payoff. A short leg therefore keeps its negative payoff sign
    while the fee remains an additional negative cashflow.
    """

    product.check_quantity(quantity)
    payoff_usd = intrinsic_payoff_usd(
        option_type=option_type,
        strike=strike,
        delivery_price=delivery_price,
        quantity=quantity,
    )
    native_payoff = product.native_payoff(payoff_usd, delivery_price=delivery_price)
    contractual = native_payoff if action is Action.BUY else -native_payoff
    fee = (
        Decimal(0)
        if delivery_fee_exempt or native_payoff == 0
        else min(
            product.standard_delivery_fee_rate * quantity,
            Decimal("0.125") * native_payoff,
        )
    )
    return SettlementLegCashflow(
        contractual_cashflow_native=contractual,
        delivery_fee_native=fee,
        net_cashflow_native=contractual - fee,
    )


def price_close_vertical(
    *,
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    quantity: Decimal,
    index_price: Decimal,
) -> tuple[LegExecution, LegExecution] | None:
    """Return the close legs: buy the short and sell the protective long."""
    short = execute_leg(short_quote, action=Action.BUY, quantity=quantity, index_price=index_price)
    long = execute_leg(long_quote, action=Action.SELL, quantity=quantity, index_price=index_price)
    if short is None or long is None:
        return None
    return short, long
