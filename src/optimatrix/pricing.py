from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity
from optimatrix.market import OptionQuote, OptionType, PriceLevel
from optimatrix.products import BTC


class Action(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class DepthWalk:
    levels: tuple[PriceLevel, ...]
    amount: Decimal
    native_total: Decimal
    native_vwap: Decimal


@dataclass(frozen=True)
class BookDepthProjection:
    requested_amount: Decimal
    available_amount: Decimal
    coverage: Decimal
    raw: DepthWalk | None
    stressed: DepthWalk | None

    @property
    def full_amount(self) -> bool:
        return self.coverage == 1 and self.raw is not None and self.stressed is not None


@dataclass(frozen=True)
class OptionLegBookProjection:
    instrument_name: str
    action: Action
    amount: Decimal
    depth: BookDepthProjection
    native_fee: Decimal | None
    native_cashflow: Decimal | None
    boundary_usd_cashflow: Decimal | None
    boundary_usd_fee: Decimal | None

    @property
    def full_amount(self) -> bool:
        return self.depth.full_amount


@dataclass(frozen=True)
class Btc0DteCondorPricing:
    long_put: OptionLegBookProjection
    short_put: OptionLegBookProjection
    short_call: OptionLegBookProjection
    long_call: OptionLegBookProjection
    close_long_put: OptionLegBookProjection
    close_short_put: OptionLegBookProjection
    close_short_call: OptionLegBookProjection
    close_long_call: OptionLegBookProjection
    fee_model_id: str
    native_gross_credit: Decimal
    component_leg_stress_fee_native: Decimal
    combo_standard_fee_native: Decimal
    native_net_credit: Decimal
    boundary_index_price_usd: Decimal
    boundary_gross_credit_usd: Decimal
    boundary_combo_fee_usd: Decimal
    boundary_net_credit_usd: Decimal
    put_contractual_payoff_cap_usd: Decimal
    call_contractual_payoff_cap_usd: Decimal
    maximum_contractual_payoff_cap_usd: Decimal
    boundary_reference_loss_usd: Decimal
    observed_close_native_debit: Decimal | None


@dataclass(frozen=True)
class Btc0DteCondorCloseProjection:
    long_put: OptionLegBookProjection
    short_put: OptionLegBookProjection
    short_call: OptionLegBookProjection
    long_call: OptionLegBookProjection
    fee_model_id: str
    native_gross_cashflow: Decimal
    combo_standard_fee_native: Decimal
    native_net_cashflow: Decimal
    boundary_index_price_usd: Decimal
    boundary_net_cashflow_usd: Decimal


@dataclass(frozen=True)
class Btc0DteCondorSettlement:
    delivery_price_usd: Decimal
    contractual_cashflow_native: Decimal
    delivery_fee_native: Decimal
    native_net_cashflow: Decimal


def walk_depth(levels: tuple[PriceLevel, ...], amount: Decimal) -> DepthWalk | None:
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be finite and positive")
    remaining = amount
    consumed: list[PriceLevel] = []
    total = Decimal(0)
    for level in levels:
        take = min(level.quantity, remaining)
        if take > 0:
            consumed.append(PriceLevel(level.price, take))
            total += level.price * take
            remaining -= take
        if remaining == 0:
            return DepthWalk(tuple(consumed), amount, total, total / amount)
    return None


def project_option_leg_from_book(
    quote: OptionQuote,
    *,
    action: Action,
    amount: Decimal,
    boundary_index_price: Decimal,
) -> OptionLegBookProjection:
    quote.product.check_quantity(amount)
    source = quote.ask if action is Action.BUY else quote.bid
    available = sum((level.quantity for level in source), Decimal(0))
    coverage = min(Decimal(1), available / amount)
    raw = walk_depth(source, amount)
    stressed: DepthWalk | None = None
    if raw is not None:
        stressed_levels: list[PriceLevel] = []
        stressed_total = Decimal(0)
        for level in raw.levels:
            stressed_price = (
                quote.tick_schedule.next_price(level.price)
                if action is Action.BUY
                else quote.tick_schedule.previous_price(level.price)
            )
            if stressed_price is None:
                break
            stressed_levels.append(PriceLevel(stressed_price, level.quantity))
            stressed_total += stressed_price * level.quantity
        else:
            stressed = DepthWalk(
                levels=tuple(stressed_levels),
                amount=amount,
                native_total=stressed_total,
                native_vwap=stressed_total / amount,
            )
    native_fee: Decimal | None = None
    native_cashflow: Decimal | None = None
    boundary_cashflow: Decimal | None = None
    boundary_fee: Decimal | None = None
    if stressed is not None:
        native_fee = quote.product.native_option_fee(
            native_option_price=stressed.native_vwap,
            quantity=amount,
        )
        native_cashflow = stressed.native_total if action is Action.SELL else -stressed.native_total
        boundary_cashflow = quote.product.value_native(
            native_cashflow,
            index_price=boundary_index_price,
        )
        boundary_fee = quote.product.value_native(
            native_fee,
            index_price=boundary_index_price,
        )
    return OptionLegBookProjection(
        instrument_name=quote.instrument_name,
        action=action,
        amount=amount,
        depth=BookDepthProjection(
            requested_amount=amount,
            available_amount=available,
            coverage=coverage,
            raw=raw,
            stressed=stressed,
        ),
        native_fee=native_fee,
        native_cashflow=native_cashflow,
        boundary_usd_cashflow=boundary_cashflow,
        boundary_usd_fee=boundary_fee,
    )


def standard_option_combo_fee_native(
    legs: tuple[OptionLegBookProjection, ...],
) -> Decimal:
    if not legs or any(leg.native_fee is None for leg in legs):
        raise ValueError("Combo fee requires complete leg projections")
    buy = sum(
        (_required(leg.native_fee) for leg in legs if leg.action is Action.BUY),
        Decimal(0),
    )
    sell = sum(
        (_required(leg.native_fee) for leg in legs if leg.action is Action.SELL),
        Decimal(0),
    )
    return max(buy, sell)


def price_btc_0dte_condor(
    *,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    amount: Decimal,
    boundary_index_price: Decimal,
) -> Btc0DteCondorPricing | None:
    _validate_condor_legs(long_put, short_put, short_call, long_call)
    entry = (
        project_option_leg_from_book(
            long_put,
            action=Action.BUY,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            short_put,
            action=Action.SELL,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            short_call,
            action=Action.SELL,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            long_call,
            action=Action.BUY,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
    )
    if any(not leg.full_amount for leg in entry):
        return None
    native_cashflows = tuple(_required(leg.native_cashflow) for leg in entry)
    native_fees = tuple(_required(leg.native_fee) for leg in entry)
    native_gross = sum(native_cashflows, Decimal(0))
    component_fee = sum(native_fees, Decimal(0))
    combo_fee = standard_option_combo_fee_native(entry)
    native_net = native_gross - combo_fee
    if native_gross <= 0 or native_net <= 0:
        return None

    close = _close_leg_projections(
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        amount=amount,
        boundary_index_price=boundary_index_price,
    )
    close_debit: Decimal | None = None
    if all(leg.full_amount for leg in close):
        close_cashflow = sum(
            (_required(leg.native_cashflow) for leg in close),
            Decimal(0),
        )
        close_fee = standard_option_combo_fee_native(close)
        close_debit = max(Decimal(0), -close_cashflow + close_fee)

    product = long_put.product
    boundary_gross = product.value_native(native_gross, index_price=boundary_index_price)
    boundary_fee = product.value_native(combo_fee, index_price=boundary_index_price)
    boundary_net = product.value_native(native_net, index_price=boundary_index_price)
    put_cap = (short_put.strike - long_put.strike) * amount
    call_cap = (long_call.strike - short_call.strike) * amount
    maximum_cap = max(put_cap, call_cap)
    return Btc0DteCondorPricing(
        long_put=entry[0],
        short_put=entry[1],
        short_call=entry[2],
        long_call=entry[3],
        close_long_put=close[0],
        close_short_put=close[1],
        close_short_call=close[2],
        close_long_call=close[3],
        fee_model_id=_combo_fee_model_id(),
        native_gross_credit=native_gross,
        component_leg_stress_fee_native=component_fee,
        combo_standard_fee_native=combo_fee,
        native_net_credit=native_net,
        boundary_index_price_usd=boundary_index_price,
        boundary_gross_credit_usd=boundary_gross,
        boundary_combo_fee_usd=boundary_fee,
        boundary_net_credit_usd=boundary_net,
        put_contractual_payoff_cap_usd=put_cap,
        call_contractual_payoff_cap_usd=call_cap,
        maximum_contractual_payoff_cap_usd=maximum_cap,
        boundary_reference_loss_usd=max(Decimal(0), maximum_cap - boundary_net),
        observed_close_native_debit=close_debit,
    )


def project_btc_0dte_condor_close(
    *,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    amount: Decimal,
    boundary_index_price: Decimal,
) -> Btc0DteCondorCloseProjection | None:
    _validate_condor_legs(long_put, short_put, short_call, long_call)
    close = _close_leg_projections(
        long_put=long_put,
        short_put=short_put,
        short_call=short_call,
        long_call=long_call,
        amount=amount,
        boundary_index_price=boundary_index_price,
    )
    if any(not leg.full_amount for leg in close):
        return None
    gross = sum((_required(leg.native_cashflow) for leg in close), Decimal(0))
    fee = standard_option_combo_fee_native(close)
    net = gross - fee
    return Btc0DteCondorCloseProjection(
        long_put=close[0],
        short_put=close[1],
        short_call=close[2],
        long_call=close[3],
        fee_model_id=_combo_fee_model_id(),
        native_gross_cashflow=gross,
        combo_standard_fee_native=fee,
        native_net_cashflow=net,
        boundary_index_price_usd=boundary_index_price,
        boundary_net_cashflow_usd=long_put.product.value_native(
            net,
            index_price=boundary_index_price,
        ),
    )


def _close_leg_projections(
    *,
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
    amount: Decimal,
    boundary_index_price: Decimal,
) -> tuple[OptionLegBookProjection, ...]:
    return (
        project_option_leg_from_book(
            long_put,
            action=Action.SELL,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            short_put,
            action=Action.BUY,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            short_call,
            action=Action.BUY,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
        project_option_leg_from_book(
            long_call,
            action=Action.SELL,
            amount=amount,
            boundary_index_price=boundary_index_price,
        ),
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


def settle_btc_0dte_condor(
    *,
    long_put_strike: Decimal,
    short_put_strike: Decimal,
    short_call_strike: Decimal,
    long_call_strike: Decimal,
    amount: Decimal,
    delivery_price: Decimal,
    daily_delivery_fee_exempt: bool,
) -> Btc0DteCondorSettlement:
    if not long_put_strike < short_put_strike < short_call_strike < long_call_strike:
        raise ValueError("Condor settlement strikes must be strictly ordered")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("settlement amount must be finite and positive")
    if not delivery_price.is_finite() or delivery_price <= 0:
        raise ValueError("delivery price must be finite and positive")
    payoffs = (
        intrinsic_payoff_usd(
            option_type="PUT",
            strike=long_put_strike,
            delivery_price=delivery_price,
            quantity=amount,
        ),
        intrinsic_payoff_usd(
            option_type="PUT",
            strike=short_put_strike,
            delivery_price=delivery_price,
            quantity=amount,
        ),
        intrinsic_payoff_usd(
            option_type="CALL",
            strike=short_call_strike,
            delivery_price=delivery_price,
            quantity=amount,
        ),
        intrinsic_payoff_usd(
            option_type="CALL",
            strike=long_call_strike,
            delivery_price=delivery_price,
            quantity=amount,
        ),
    )
    native = tuple(payoff / delivery_price for payoff in payoffs)
    contractual = native[0] - native[1] - native[2] + native[3]
    delivery_fee = Decimal(0)
    if not daily_delivery_fee_exempt:
        delivery_fee = sum(
            (
                min(
                    BTC.standard_delivery_fee_rate * amount,
                    Decimal("0.125") * payoff,
                )
                for payoff in native
            ),
            Decimal(0),
        )
    return Btc0DteCondorSettlement(
        delivery_price_usd=delivery_price,
        contractual_cashflow_native=contractual,
        delivery_fee_native=delivery_fee,
        native_net_cashflow=contractual - delivery_fee,
    )


def _combo_fee_model_id() -> str:
    return canonical_identity(
        "DeribitStandardOptionComboFeeV1",
        "MAX_BUY_SELL_DIRECTION_AFTER_LEG_CAPS",
    )


def _validate_condor_legs(
    long_put: OptionQuote,
    short_put: OptionQuote,
    short_call: OptionQuote,
    long_call: OptionQuote,
) -> None:
    legs = (long_put, short_put, short_call, long_call)
    if len({leg.instrument_name for leg in legs}) != 4:
        raise ValueError("Condor legs must be distinct")
    if len({leg.product for leg in legs}) != 1 or len({leg.expiry for leg in legs}) != 1:
        raise ValueError("Condor legs must share product and expiry")
    if (
        long_put.option_type is not OptionType.PUT
        or short_put.option_type is not OptionType.PUT
        or short_call.option_type is not OptionType.CALL
        or long_call.option_type is not OptionType.CALL
    ):
        raise ValueError("Condor leg option types are invalid")
    if not long_put.strike < short_put.strike < short_call.strike < long_call.strike:
        raise ValueError("Condor strikes must be strictly ordered")


def _required(value: Decimal | None) -> Decimal:
    if value is None:
        raise ValueError("complete leg projection is missing a numeric fact")
    return value
