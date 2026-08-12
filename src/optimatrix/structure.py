from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from optimatrix.market import MarketContext, OptionQuote, OptionType
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import (
    IronCondorExecution,
    VerticalExecution,
    combine_condor,
    price_credit_vertical,
)


@dataclass(frozen=True)
class VerticalCandidate:
    short_quote: OptionQuote
    long_quote: OptionQuote
    execution: VerticalExecution
    credit_to_payoff: Decimal


@dataclass(frozen=True)
class IronCondorCandidate:
    long_put: OptionQuote
    short_put: OptionQuote
    short_call: OptionQuote
    long_call: OptionQuote
    execution: IronCondorExecution
    net_delta: Decimal
    put_body_distance_sigma: Decimal
    call_body_distance_sigma: Decimal
    minimum_body_distance_sigma: Decimal
    average_spread_quality: Decimal
    depth_quality: Decimal

    @property
    def expiry(self) -> datetime:
        return self.short_put.expiry


@dataclass(frozen=True)
class StructureSelection:
    selected: IronCondorCandidate | None
    considered_put_verticals: int
    considered_call_verticals: int
    considered_condors: int
    blockers: tuple[str, ...]


def select_iron_condor(
    *,
    quotes: tuple[OptionQuote, ...],
    context: MarketContext,
    policy: BtcShortVolPolicy,
) -> StructureSelection:
    if not quotes:
        return StructureSelection(
            selected=None,
            considered_put_verticals=0,
            considered_call_verticals=0,
            considered_condors=0,
            blockers=("NO_CURRENT_SESSION_QUOTES",),
        )
    expiries = {quote.expiry for quote in quotes}
    if len(expiries) != 1:
        return StructureSelection(
            selected=None,
            considered_put_verticals=0,
            considered_call_verticals=0,
            considered_condors=0,
            blockers=("MIXED_EXPIRY_INPUT",),
        )
    relevant = tuple(quote for quote in quotes if _short_delta_eligible(quote, policy))
    put_shorts = tuple(
        quote
        for quote in relevant
        if quote.option_type is OptionType.PUT and quote.strike < context.forward_price
    )
    call_shorts = tuple(
        quote
        for quote in relevant
        if quote.option_type is OptionType.CALL and quote.strike > context.forward_price
    )
    put_verticals = _vertical_candidates(
        short_quotes=put_shorts,
        all_quotes=quotes,
        context=context,
        policy=policy,
    )
    call_verticals = _vertical_candidates(
        short_quotes=call_shorts,
        all_quotes=quotes,
        context=context,
        policy=policy,
    )
    blockers: list[str] = []
    if not put_shorts:
        blockers.append("NO_ELIGIBLE_SHORT_PUT")
    if not call_shorts:
        blockers.append("NO_ELIGIBLE_SHORT_CALL")
    if put_shorts and not put_verticals:
        blockers.append("NO_EXECUTABLE_PUT_VERTICAL")
    if call_shorts and not call_verticals:
        blockers.append("NO_EXECUTABLE_CALL_VERTICAL")
    if blockers:
        return StructureSelection(
            selected=None,
            considered_put_verticals=len(put_verticals),
            considered_call_verticals=len(call_verticals),
            considered_condors=0,
            blockers=tuple(blockers),
        )

    top_n = policy.structure.top_verticals_per_side
    ranked_puts = sorted(put_verticals, key=_vertical_rank_key)[:top_n]
    ranked_calls = sorted(call_verticals, key=_vertical_rank_key)[:top_n]
    candidates: list[IronCondorCandidate] = []
    for put in ranked_puts:
        for call in ranked_calls:
            if put.short_quote.expiry != call.short_quote.expiry:
                continue
            legs = (
                put.long_quote,
                put.short_quote,
                call.short_quote,
                call.long_quote,
            )
            if not _four_leg_coherent(legs, policy=policy):
                continue
            execution = combine_condor(put.execution, call.execution)
            net_delta = _condor_net_delta(
                put_short=put.short_quote,
                put_long=put.long_quote,
                call_short=call.short_quote,
                call_long=call.long_quote,
            )
            physical_sigma = context.physical_variance_forecast.sqrt()
            put_distance = _log_distance_sigma(
                strike=put.short_quote.strike,
                forward=context.forward_price,
                physical_sigma=physical_sigma,
            )
            call_distance = _log_distance_sigma(
                strike=call.short_quote.strike,
                forward=context.forward_price,
                physical_sigma=physical_sigma,
            )
            candidates.append(
                IronCondorCandidate(
                    long_put=put.long_quote,
                    short_put=put.short_quote,
                    short_call=call.short_quote,
                    long_call=call.long_quote,
                    execution=execution,
                    net_delta=net_delta,
                    put_body_distance_sigma=put_distance,
                    call_body_distance_sigma=call_distance,
                    minimum_body_distance_sigma=min(put_distance, call_distance),
                    average_spread_quality=sum(
                        (_spread_quality(quote) for quote in legs),
                        Decimal(0),
                    )
                    / Decimal(4),
                    depth_quality=_depth_quality(execution),
                )
            )
    if not candidates:
        return StructureSelection(
            selected=None,
            considered_put_verticals=len(put_verticals),
            considered_call_verticals=len(call_verticals),
            considered_condors=0,
            blockers=("NO_COHERENT_COMBINABLE_TWO_SIDED_STRUCTURE",),
        )
    selected = min(candidates, key=lambda candidate: _condor_rank_key(candidate, policy))
    return StructureSelection(
        selected=selected,
        considered_put_verticals=len(put_verticals),
        considered_call_verticals=len(call_verticals),
        considered_condors=len(candidates),
        blockers=(),
    )


def _short_delta_eligible(quote: OptionQuote, policy: BtcShortVolPolicy) -> bool:
    absolute = abs(quote.signed_delta)
    return policy.structure.short_delta_min <= absolute <= policy.structure.short_delta_max


def _vertical_candidates(
    *,
    short_quotes: tuple[OptionQuote, ...],
    all_quotes: tuple[OptionQuote, ...],
    context: MarketContext,
    policy: BtcShortVolPolicy,
) -> tuple[VerticalCandidate, ...]:
    output: list[VerticalCandidate] = []
    for short in short_quotes:
        for long in all_quotes:
            if (
                long.product != short.product
                or long.expiry != short.expiry
                or long.option_type is not short.option_type
                or long.instrument_name == short.instrument_name
            ):
                continue
            width = abs(long.strike - short.strike)
            if not (
                policy.structure.minimum_wing_width_usd
                <= width
                <= policy.structure.maximum_wing_width_usd
            ):
                continue
            if short.option_type is OptionType.PUT and long.strike >= short.strike:
                continue
            if short.option_type is OptionType.CALL and long.strike <= short.strike:
                continue
            if not _quote_pair_coherent(short, long, policy=policy):
                continue
            execution = price_credit_vertical(
                short_quote=short,
                long_quote=long,
                quantity=policy.structure.target_quantity,
                index_price=context.index_price,
            )
            if execution is None:
                continue
            output.append(
                VerticalCandidate(
                    short_quote=short,
                    long_quote=long,
                    execution=execution,
                    credit_to_payoff=(
                        execution.usd_net_credit / execution.payoff_cap_usd
                        if execution.payoff_cap_usd > 0
                        else Decimal(0)
                    ),
                )
            )
    return tuple(output)


def _quote_pair_coherent(
    first: OptionQuote,
    second: OptionQuote,
    *,
    policy: BtcShortVolPolicy,
) -> bool:
    return (
        first.continuity_epoch == second.continuity_epoch
        and abs(first.source_timestamp_ms - second.source_timestamp_ms)
        <= policy.shadow.maximum_pair_source_skew_ms
        and abs(first.received_timestamp_ms - second.received_timestamp_ms)
        <= policy.shadow.maximum_pair_receive_skew_ms
    )


def _four_leg_coherent(
    legs: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote],
    *,
    policy: BtcShortVolPolicy,
) -> bool:
    return (
        len({quote.continuity_epoch for quote in legs}) == 1
        and max(quote.source_timestamp_ms for quote in legs)
        - min(quote.source_timestamp_ms for quote in legs)
        <= policy.shadow.maximum_pair_source_skew_ms
        and max(quote.received_timestamp_ms for quote in legs)
        - min(quote.received_timestamp_ms for quote in legs)
        <= policy.shadow.maximum_pair_receive_skew_ms
    )


def _vertical_rank_key(candidate: VerticalCandidate) -> tuple[object, ...]:
    return (
        -candidate.credit_to_payoff,
        -candidate.execution.usd_net_credit,
        candidate.execution.consumed_level_count,
        candidate.execution.width_usd_per_unit,
        candidate.long_quote.instrument_name,
    )


def _condor_rank_key(
    candidate: IronCondorCandidate,
    policy: BtcShortVolPolicy,
) -> tuple[object, ...]:
    execution = candidate.execution
    credit_ratio = (
        execution.usd_net_credit / execution.maximum_side_payoff_cap_usd
        if execution.maximum_side_payoff_cap_usd > 0
        else Decimal(0)
    )
    delta_excess = max(Decimal(0), abs(candidate.net_delta) - policy.radar.maximum_abs_net_delta)
    distance_deficit = max(
        Decimal(0),
        policy.radar.minimum_body_distance_sigma - candidate.minimum_body_distance_sigma,
    )
    fee_fraction = execution.usd_total_fee / execution.usd_gross_credit
    return (
        delta_excess,
        distance_deficit,
        -credit_ratio,
        -execution.usd_net_credit,
        fee_fraction,
        -candidate.average_spread_quality,
        -candidate.depth_quality,
        candidate.short_put.instrument_name,
        candidate.short_call.instrument_name,
    )


def _condor_net_delta(
    *,
    put_short: OptionQuote,
    put_long: OptionQuote,
    call_short: OptionQuote,
    call_long: OptionQuote,
) -> Decimal:
    return (
        -put_short.signed_delta
        + put_long.signed_delta
        - call_short.signed_delta
        + call_long.signed_delta
    )


def _log_distance_sigma(*, strike: Decimal, forward: Decimal, physical_sigma: Decimal) -> Decimal:
    if physical_sigma <= 0:
        raise ValueError("physical_sigma must be positive")
    return abs((strike / forward).ln()) / physical_sigma


def _spread_quality(quote: OptionQuote) -> Decimal:
    if not quote.bid or not quote.ask:
        return Decimal(0)
    best_bid = quote.bid[0].price
    best_ask = quote.ask[0].price
    if best_ask <= best_bid:
        return Decimal(0)
    distance = quote.tick_schedule.tick_distance(best_bid, best_ask)
    return _clamp(Decimal(1) - (distance - Decimal(1)) / Decimal(9))


def _depth_quality(execution: IronCondorExecution) -> Decimal:
    levels = (
        execution.put_vertical.short_leg.stressed.levels
        + execution.put_vertical.long_leg.stressed.levels
        + execution.call_vertical.short_leg.stressed.levels
        + execution.call_vertical.long_leg.stressed.levels
    )
    count = len(levels)
    return _clamp(Decimal(1) - Decimal(max(0, count - 4)) / Decimal(12))


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))
