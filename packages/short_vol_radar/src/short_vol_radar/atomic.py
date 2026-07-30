from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from market_monitor import BookState, ContinuousOrderBook, PriceLevel
from options_domain import (
    AmountState,
    ComboInstrument,
    OptionInstrument,
    OptionType,
    check_target_amount,
)
from options_domain.quotes import walk_target_depth


class PublicAtomicQuoteState(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"
    NO_ACTIVE_COMBO = "NO_ACTIVE_COMBO"
    NO_TARGET_SIZE_CREDIT_QUOTE = "NO_TARGET_SIZE_CREDIT_QUOTE"
    PUBLIC_ATOMIC_QUOTE_AVAILABLE = "PUBLIC_ATOMIC_QUOTE_AVAILABLE"


class ProtectiveLegState(StrEnum):
    KNOWN_PRESENT = "KNOWN_PRESENT"
    KNOWN_ABSENT = "KNOWN_ABSENT"
    UNRESOLVED = "UNRESOLVED"


class ComboOrderDirection(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class AtomicMatch:
    combo_instrument_name: str
    long_instrument_name: str
    signed_order_amount_btc: Decimal
    direction: ComboOrderDirection


@dataclass(frozen=True)
class AtomicQuote:
    match: AtomicMatch
    consumed_levels: tuple[PriceLevel, ...]
    required_side_vwap_usdc_per_btc: Decimal
    gross_entry_credit_usdc: Decimal


@dataclass(frozen=True)
class AtomicResult:
    state: PublicAtomicQuoteState
    quotes: tuple[AtomicQuote, ...] = ()
    unknown_reasons: tuple[str, ...] = ()


def match_vertical_combo(
    *,
    short_leg: OptionInstrument,
    options_by_name: dict[str, OptionInstrument],
    combo: ComboInstrument,
    target_btc: Decimal,
) -> AtomicMatch | None:
    if len(combo.legs) != 2:
        return None
    leg_by_name = {leg.instrument_name: leg.amount for leg in combo.legs}
    if len(leg_by_name) != 2:
        return None
    if set(leg_by_name) - set(options_by_name):
        return None
    if short_leg.instrument_name not in leg_by_name:
        return None
    other_name = next(name for name in leg_by_name if name != short_leg.instrument_name)
    long_leg = options_by_name[other_name]
    if (
        long_leg.expiration_timestamp_ms != short_leg.expiration_timestamp_ms
        or long_leg.option_type is not short_leg.option_type
    ):
        return None
    if short_leg.option_type is OptionType.CALL:
        if not long_leg.strike > short_leg.strike:
            return None
    elif not long_leg.strike < short_leg.strike:
        return None
    desired = {
        short_leg.instrument_name: -target_btc,
        long_leg.instrument_name: target_btc,
    }
    scalars = {desired[name] / amount for name, amount in leg_by_name.items()}
    if len(scalars) != 1:
        return None
    signed_amount = scalars.pop()
    if signed_amount not in {target_btc, -target_btc}:
        return None
    return AtomicMatch(
        combo_instrument_name=combo.instrument_name,
        long_instrument_name=long_leg.instrument_name,
        signed_order_amount_btc=signed_amount,
        direction=ComboOrderDirection.BUY if signed_amount > 0 else ComboOrderDirection.SELL,
    )


def classify_atomic_quotes(
    *,
    anomaly_active: bool,
    combo_catalog_complete: bool,
    option_catalog_complete: bool,
    short_leg: OptionInstrument,
    options_by_name: dict[str, OptionInstrument],
    combos: tuple[ComboInstrument, ...],
    combo_books: dict[str, ContinuousOrderBook],
    target_btc: Decimal,
) -> AtomicResult:
    if not anomaly_active:
        return AtomicResult(PublicAtomicQuoteState.NOT_EVALUATED)
    matches = tuple(
        (combo, match)
        for combo in combos
        if (
            match := match_vertical_combo(
                short_leg=short_leg,
                options_by_name=options_by_name,
                combo=combo,
                target_btc=target_btc,
            )
        )
        is not None
    )
    protective_state = classify_protective_leg(
        short_leg=short_leg,
        options_by_name=options_by_name,
        option_catalog_complete=option_catalog_complete,
    )
    if not matches:
        missing_reasons: list[str] = []
        if not option_catalog_complete:
            missing_reasons.append("OPTION_CATALOG_INCOMPLETE")
        if protective_state is ProtectiveLegState.UNRESOLVED:
            missing_reasons.append("PROTECTIVE_LEG_UNRESOLVED")
        if not combo_catalog_complete:
            missing_reasons.append("COMBO_CATALOG_INCOMPLETE")
        if missing_reasons:
            return AtomicResult(
                PublicAtomicQuoteState.UNKNOWN,
                unknown_reasons=tuple(sorted(set(missing_reasons))),
            )
        return AtomicResult(PublicAtomicQuoteState.NO_ACTIVE_COMBO)
    quotes: list[AtomicQuote] = []
    unknown: list[str] = []
    for combo, match in matches:
        option_amount_unknown = False
        option_amount_ineligible = False
        for option_name in (
            short_leg.instrument_name,
            match.long_instrument_name,
        ):
            option = options_by_name[option_name]
            if option.amount is None:
                unknown.append(f"{option_name}:AMOUNT_METADATA_UNKNOWN")
                option_amount_unknown = True
                continue
            if check_target_amount(target_btc, option.amount).state is AmountState.INELIGIBLE:
                option_amount_ineligible = True
        if option_amount_unknown or option_amount_ineligible:
            continue
        amount_check = (
            check_target_amount(target_btc, combo.amount) if combo.amount is not None else None
        )
        if amount_check is not None and amount_check.state is AmountState.INELIGIBLE:
            continue
        book = combo_books.get(combo.instrument_name)
        if book is None or book.state is not BookState.USABLE:
            unknown.append(f"{combo.instrument_name}:BOOK_UNKNOWN")
            continue
        side = "ask" if match.direction is ComboOrderDirection.BUY else "bid"
        walk = walk_target_depth(book.levels(side), target_btc)
        if walk is None:
            continue
        if amount_check is None:
            unknown.append(f"{combo.instrument_name}:AMOUNT_METADATA_UNKNOWN")
            continue
        gross_credit = -match.signed_order_amount_btc * walk.vwap
        if gross_credit > 0:
            quotes.append(
                AtomicQuote(
                    match=match,
                    consumed_levels=walk.consumed,
                    required_side_vwap_usdc_per_btc=walk.vwap,
                    gross_entry_credit_usdc=gross_credit,
                )
            )
    if quotes:
        return AtomicResult(
            PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE,
            quotes=tuple(quotes),
        )
    if not combo_catalog_complete:
        unknown.append("COMBO_CATALOG_INCOMPLETE")
    if not option_catalog_complete:
        unknown.append("OPTION_CATALOG_INCOMPLETE")
    if unknown:
        return AtomicResult(
            PublicAtomicQuoteState.UNKNOWN,
            unknown_reasons=tuple(sorted(set(unknown))),
        )
    return AtomicResult(PublicAtomicQuoteState.NO_TARGET_SIZE_CREDIT_QUOTE)


def classify_protective_leg(
    *,
    short_leg: OptionInstrument,
    options_by_name: dict[str, OptionInstrument],
    option_catalog_complete: bool,
) -> ProtectiveLegState:
    unresolved_candidate = False
    for candidate in options_by_name.values():
        if (
            candidate.instrument_name == short_leg.instrument_name
            or candidate.expiration_timestamp_ms != short_leg.expiration_timestamp_ms
            or candidate.option_type is not short_leg.option_type
        ):
            continue
        is_protective = (
            short_leg.option_type is OptionType.CALL and candidate.strike > short_leg.strike
        ) or (short_leg.option_type is OptionType.PUT and candidate.strike < short_leg.strike)
        if not is_protective:
            continue
        if candidate.amount is None:
            unresolved_candidate = True
        else:
            return ProtectiveLegState.KNOWN_PRESENT
    if unresolved_candidate or not option_catalog_complete:
        return ProtectiveLegState.UNRESOLVED
    return ProtectiveLegState.KNOWN_ABSENT
