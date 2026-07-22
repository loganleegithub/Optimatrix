"""Visible-price 1:1 defined-risk vertical construction."""

from __future__ import annotations

from decimal import Decimal

from market_tape import OptionKind

from options_domain.contracts import (
    ComboQuote,
    ExecutableVerticalClose,
    OptionQuote,
    VerticalQuote,
)

FEE_CAP_FRACTION = Decimal("0.125")


def _fee(
    price: Decimal,
    quote: OptionQuote,
    index_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    return (
        min(
            quote.taker_commission * index_price,
            FEE_CAP_FRACTION * price,
        )
        * quantity
        * quote.contract_size
    )


def _is_otm(quote: OptionQuote, reference_price: Decimal) -> bool:
    if quote.option_kind is OptionKind.CALL:
        return quote.strike > reference_price
    return quote.strike < reference_price


def _is_pair(short_quote: OptionQuote, long_quote: OptionQuote) -> bool:
    if (
        short_quote.instrument_name == long_quote.instrument_name
        or short_quote.expiry != long_quote.expiry
        or short_quote.option_kind is not long_quote.option_kind
        or short_quote.contract_size != long_quote.contract_size
    ):
        return False
    if short_quote.option_kind is OptionKind.CALL:
        return long_quote.strike > short_quote.strike
    return long_quote.strike < short_quote.strike


def _quantity_valid(quantity: Decimal, quote: OptionQuote) -> bool:
    return (
        quantity >= quote.min_trade_amount
        and quote.amount_step > 0
        and quantity % quote.amount_step == 0
    )


def _matching_combo(
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    combo_quotes: tuple[ComboQuote, ...],
) -> ComboQuote | None:
    return next(
        (
            item
            for item in combo_quotes
            if item.short_instrument == short_quote.instrument_name
            and item.long_instrument == long_quote.instrument_name
            and item.fresh
            and item.valid
        ),
        None,
    )


def build_vertical_close(
    *,
    index_price: Decimal,
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    quantity: Decimal,
    combo_quotes: tuple[ComboQuote, ...] = (),
) -> ExecutableVerticalClose | None:
    """Build only the visible execution needed to close an existing vertical."""

    if (
        index_price <= 0
        or not _is_pair(short_quote, long_quote)
        or not short_quote.fresh
        or not long_quote.fresh
        or not _quantity_valid(quantity, short_quote)
        or not _quantity_valid(quantity, long_quote)
    ):
        return None
    combo = _matching_combo(short_quote, long_quote, combo_quotes)
    if (
        combo is not None
        and combo.ask is not None
        and combo.ask >= 0
        and combo.ask_amount >= quantity
    ):
        return ExecutableVerticalClose(
            combo_id=combo.combo_id,
            execution_source="ACTIVE_COMBO",
            debit=combo.ask,
            fee_usdc=(
                (short_quote.taker_commission + long_quote.taker_commission)
                * index_price
                * quantity
                * short_quote.contract_size
            ),
            depth=combo.ask_amount,
            combo_source_capture_seq=combo.source_capture_seq,
        )
    if (
        short_quote.ask is None
        or short_quote.ask < 0
        or long_quote.bid is None
        or long_quote.bid < 0
        or short_quote.ask_amount is None
        or long_quote.bid_amount is None
        or short_quote.ask_amount < quantity
        or long_quote.bid_amount < quantity
    ):
        return None
    return ExecutableVerticalClose(
        combo_id=(combo.combo_id if combo is not None else None),
        execution_source="CONSERVATIVE_LEG_CROSS",
        debit=max(Decimal("0"), short_quote.ask - long_quote.bid),
        fee_usdc=(
            _fee(short_quote.ask, short_quote, index_price, quantity)
            + _fee(long_quote.bid, long_quote, index_price, quantity)
        ),
        depth=min(short_quote.ask_amount, long_quote.bid_amount),
        combo_source_capture_seq=None,
    )


def build_vertical_quote(
    *,
    frame_capture_seq: int,
    reference_price: Decimal,
    index_price: Decimal,
    short_quote: OptionQuote,
    long_quote: OptionQuote,
    quantity: Decimal,
    combo_quotes: tuple[ComboQuote, ...] = (),
) -> VerticalQuote | None:
    if (
        not _is_pair(short_quote, long_quote)
        or not short_quote.fresh
        or not long_quote.fresh
        or not _quantity_valid(quantity, short_quote)
        or not _quantity_valid(quantity, long_quote)
        or short_quote.bid is None
        or short_quote.ask is None
        or long_quote.bid is None
        or long_quote.ask is None
        or short_quote.bid_amount is None
        or short_quote.ask_amount is None
        or long_quote.bid_amount is None
        or long_quote.ask_amount is None
        or min(
            short_quote.bid_amount,
            short_quote.ask_amount,
            long_quote.bid_amount,
            long_quote.ask_amount,
        )
        < quantity
    ):
        return None
    combo = _matching_combo(short_quote, long_quote, combo_quotes)
    combo_entry = (
        combo is not None
        and combo.bid is not None
        and combo.bid > 0
        and combo.bid_amount >= quantity
    )
    entry_credit = (
        combo.bid if combo_entry and combo is not None else short_quote.bid - long_quote.ask
    )
    close = build_vertical_close(
        index_price=index_price,
        short_quote=short_quote,
        long_quote=long_quote,
        quantity=quantity,
        combo_quotes=combo_quotes,
    )
    if entry_credit is None or entry_credit <= 0 or close is None:
        return None
    if combo_entry:
        entry_fee = (
            (short_quote.taker_commission + long_quote.taker_commission)
            * index_price
            * quantity
            * short_quote.contract_size
        )
        entry_depth = combo.bid_amount if combo is not None else Decimal("0")
    else:
        entry_fee = _fee(
            short_quote.bid,
            short_quote,
            index_price,
            quantity,
        ) + _fee(
            long_quote.ask,
            long_quote,
            index_price,
            quantity,
        )
        entry_depth = min(short_quote.bid_amount, long_quote.ask_amount)
    width = abs(short_quote.strike - long_quote.strike)
    contract_size = short_quote.contract_size
    gross_credit = entry_credit * quantity * contract_size
    immediate_close = close.debit * quantity * contract_size
    friction = max(Decimal("0"), immediate_close - gross_credit) + entry_fee + close.fee_usdc
    net_premium = gross_credit - entry_fee
    max_loss = width * quantity * contract_size - gross_credit + entry_fee
    if net_premium <= 0 or max_loss <= 0:
        return None
    return VerticalQuote(
        candidate_id=(
            f"vertical:{short_quote.option_kind.value.lower()}:"
            f"{short_quote.instrument_name}:{long_quote.instrument_name}"
        ),
        frame_capture_seq=frame_capture_seq,
        sold_side=short_quote.option_kind,
        expiry=short_quote.expiry,
        tte_seconds=min(short_quote.tte_seconds, long_quote.tte_seconds),
        short_leg=short_quote,
        long_leg=long_quote,
        combo_id=combo.combo_id if combo is not None else None,
        execution_source=("ACTIVE_COMBO" if combo_entry else "CONSERVATIVE_LEG_CROSS"),
        close_execution_source=close.execution_source,
        executable_entry_credit=entry_credit,
        executable_close_debit=close.debit,
        entry_fee_usdc=entry_fee,
        close_fee_usdc=close.fee_usdc,
        quantity=quantity,
        contract_size=contract_size,
        width=width,
        executable_depth=min(entry_depth, close.depth),
        gross_credit_usdc=gross_credit,
        immediate_close_usdc=immediate_close,
        net_entry_premium_usdc=net_premium,
        round_trip_friction_usdc=friction,
        credit_to_friction_ratio=(gross_credit / friction if friction > 0 else None),
        max_profit_usdc=net_premium,
        max_loss_usdc=max_loss,
        short_distance_fraction=(abs(short_quote.strike - reference_price) / reference_price),
        first_touch_level=short_quote.strike,
    )


def enumerate_verticals(
    *,
    frame_capture_seq: int,
    reference_price: Decimal,
    index_price: Decimal,
    option_quotes: tuple[OptionQuote, ...],
    quantity: Decimal,
    minimum_tte_seconds: int,
    maximum_tte_seconds: int,
    combo_quotes: tuple[ComboQuote, ...] = (),
) -> tuple[VerticalQuote, ...]:
    eligible = tuple(
        quote
        for quote in option_quotes
        if minimum_tte_seconds <= quote.tte_seconds <= maximum_tte_seconds
        and quote.fresh
        and _is_otm(quote, reference_price)
    )
    candidates: list[VerticalQuote] = []
    for short_quote in eligible:
        for long_quote in eligible:
            candidate = build_vertical_quote(
                frame_capture_seq=frame_capture_seq,
                reference_price=reference_price,
                index_price=index_price,
                short_quote=short_quote,
                long_quote=long_quote,
                quantity=quantity,
                combo_quotes=combo_quotes,
            )
            if candidate is not None:
                candidates.append(candidate)
    return tuple(sorted(candidates, key=lambda item: item.candidate_id))
