"""Future-isolated Shadow position construction and executable outcome scoring."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from market_tape import OptionKind
from options_domain import ExecutableVerticalClose, OptionQuote, build_vertical_close
from short_vol_radar import DecisionFrame, RadarAction, RadarDecision

from shadow_engine.contracts import (
    ExitReason,
    MaturedOutcome,
    OutcomePath,
    OutcomePoint,
    OutcomeStatus,
    ShadowPolicy,
    ShadowPosition,
)


def open_position(
    decision: RadarDecision,
    frame: DecisionFrame,
) -> ShadowPosition:
    if decision.action is not RadarAction.RESEARCH_CANDIDATE or decision.assessment is None:
        raise ValueError("only a research candidate can open a Shadow position")
    if (
        decision.frame_capture_seq != frame.as_of_capture_seq
        or decision.frame_digest != frame.digest
    ):
        raise ValueError("decision and entry frame identity differ")
    if decision.horizon_seconds is None or frame.reference_price is None:
        raise ValueError("research candidate lacks horizon or entry reference")
    candidate = decision.assessment.candidate
    if candidate.candidate_id != decision.selected_candidate_id:
        raise ValueError("decision selected candidate and assessment differ")
    return ShadowPosition(
        decision_digest=decision.digest,
        frame_digest=frame.digest,
        entry_capture_seq=frame.as_of_capture_seq,
        entry_at=frame.collector_as_of,
        entry_elapsed_ms=frame.collector_elapsed_ms,
        entry_reference_price=frame.reference_price,
        horizon_seconds=decision.horizon_seconds,
        structure=candidate,
    )


def _quote(
    frame: DecisionFrame,
    instrument_name: str,
) -> OptionQuote | None:
    return next(
        (item for item in frame.option_quotes if item.instrument_name == instrument_name),
        None,
    )


def _freeze_contract_terms(
    observed: OptionQuote,
    entry: OptionQuote,
) -> OptionQuote:
    """Keep future executable prices while freezing the contract opened at entry."""

    return replace(
        observed,
        expiry=entry.expiry,
        strike=entry.strike,
        option_kind=entry.option_kind,
        contract_size=entry.contract_size,
        min_trade_amount=entry.min_trade_amount,
        amount_step=entry.amount_step,
        taker_commission=entry.taker_commission,
        instrument_source_capture_seq=entry.instrument_source_capture_seq,
    )


def build_outcome_path(
    position: ShadowPosition,
    future_frames: tuple[DecisionFrame, ...],
) -> OutcomePath:
    points: list[OutcomePoint] = []
    for frame in sorted(future_frames, key=lambda item: item.as_of_capture_seq):
        if frame.as_of_capture_seq <= position.entry_capture_seq:
            raise ValueError("future frame is not strictly after entry")
        if frame.collector_elapsed_ms < position.entry_elapsed_ms:
            raise ValueError("future frame elapsed time precedes entry")
        reference_is_future = (
            frame.reference_source_capture_seq is not None
            and frame.reference_source_capture_seq > position.entry_capture_seq
            and "REFERENCE_STALE" not in frame.completeness_reasons
            and "REFERENCE_NOT_OPEN" not in frame.completeness_reasons
        )
        reference_price = frame.reference_price if reference_is_future else None
        index_price = frame.index_price if reference_is_future else None
        short_quote = _quote(
            frame,
            position.structure.short_leg.instrument_name,
        )
        long_quote = _quote(
            frame,
            position.structure.long_leg.instrument_name,
        )
        future_combo_quotes = tuple(
            item
            for item in frame.combo_quotes
            if item.source_capture_seq > position.entry_capture_seq
        )
        close: ExecutableVerticalClose | None = None
        platform_is_tradable = (
            frame.platform_state is not None
            and frame.platform_state.lower() == "open"
            and frame.platform_locked is False
            and "REFERENCE_NOT_OPEN" not in frame.completeness_reasons
        )
        if (
            reference_price is not None
            and index_price is not None
            and short_quote is not None
            and long_quote is not None
            and short_quote.ticker_source_capture_seq > position.entry_capture_seq
            and long_quote.ticker_source_capture_seq > position.entry_capture_seq
            and platform_is_tradable
        ):
            close = build_vertical_close(
                index_price=index_price,
                short_quote=_freeze_contract_terms(
                    short_quote,
                    position.structure.short_leg,
                ),
                long_quote=_freeze_contract_terms(
                    long_quote,
                    position.structure.long_leg,
                ),
                quantity=position.structure.quantity,
                combo_quotes=future_combo_quotes,
            )
        quote_source_capture_seqs: tuple[int, ...] = ()
        if close is not None and short_quote is not None and long_quote is not None:
            quote_source_capture_seqs = (
                short_quote.ticker_source_capture_seq,
                long_quote.ticker_source_capture_seq,
            )
            if close.combo_source_capture_seq is not None:
                quote_source_capture_seqs += (close.combo_source_capture_seq,)
        points.append(
            OutcomePoint(
                frame_capture_seq=frame.as_of_capture_seq,
                as_of=frame.collector_as_of,
                observed_elapsed_ms=frame.collector_elapsed_ms,
                reference_price=reference_price,
                close_debit=(close.debit if close is not None else None),
                close_fee_usdc=(close.fee_usdc if close is not None else None),
                executable_depth=(close.depth if close is not None else None),
                short_delta=(short_quote.delta if close is not None and short_quote else None),
                source_capture_seqs=tuple(
                    sorted(
                        {
                            *((frame.reference_source_capture_seq,) if reference_is_future else ()),
                            *quote_source_capture_seqs,
                        }
                    )
                ),
            )
        )
    return OutcomePath(
        position_digest=position.digest,
        entry_capture_seq=position.entry_capture_seq,
        points=tuple(points),
    )


def _touches(side: OptionKind, price: Decimal, level: Decimal) -> bool:
    if side is OptionKind.CALL:
        return price >= level
    return price <= level


def mature_outcome(
    position: ShadowPosition,
    path: OutcomePath,
    *,
    policy: ShadowPolicy | None = None,
) -> MaturedOutcome:
    if path.position_digest != position.digest:
        raise ValueError("OutcomePath does not belong to the position")
    active = policy or ShadowPolicy()
    prices = tuple(item.reference_price for item in path.points if item.reference_price is not None)
    maximum_up = (
        (max(prices) - position.entry_reference_price) / position.entry_reference_price
        if prices
        else None
    )
    maximum_down = (
        (min(prices) - position.entry_reference_price) / position.entry_reference_price
        if prices
        else None
    )
    first_touch = next(
        (
            item
            for item in path.points
            if item.reference_price is not None
            and _touches(
                position.structure.sold_side,
                item.reference_price,
                position.structure.first_touch_level,
            )
        ),
        None,
    )
    max_loss_region = (
        any(
            _touches(
                position.structure.sold_side,
                price,
                position.structure.long_leg.strike,
            )
            for price in prices
        )
        if prices
        else None
    )
    target_close_debit = position.structure.executable_entry_credit * (
        Decimal("1") - active.profit_close_fraction
    )
    selected: OutcomePoint | None = None
    reason = ExitReason.DATA_END
    for point in path.points:
        elapsed_seconds = (point.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
        close_debit = point.close_debit
        close_fee = point.close_fee_usdc
        executable = (
            close_debit is not None
            and close_fee is not None
            and point.executable_depth is not None
            and point.executable_depth >= position.structure.quantity
        )
        if close_debit is not None and executable and close_debit <= target_close_debit:
            selected = point
            reason = ExitReason.PROFIT_TARGET
            break
        if (
            first_touch is not None
            and point.frame_capture_seq >= first_touch.frame_capture_seq
            and executable
        ):
            selected = point
            reason = ExitReason.FIRST_TOUCH
            break
        if elapsed_seconds >= position.horizon_seconds:
            if executable:
                selected = point
                reason = ExitReason.HORIZON
            else:
                reason = ExitReason.UNEXITABLE_AT_HORIZON
            break
    if selected is None and reason is ExitReason.UNEXITABLE_AT_HORIZON:
        objective = -position.structure.max_loss_usdc
        status = OutcomeStatus.UNEXITABLE
        close_notional = None
        total_fee = position.structure.entry_fee_usdc
        exit_sequence = next(
            (
                item.frame_capture_seq
                for item in path.points
                if (item.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
                >= position.horizon_seconds
            ),
            None,
        )
        holding_seconds = position.horizon_seconds
    elif selected is not None:
        close_notional = (
            (selected.close_debit or Decimal("0"))
            * position.structure.quantity
            * position.structure.contract_size
        )
        close_fee = selected.close_fee_usdc or Decimal("0")
        objective = (
            position.structure.gross_credit_usdc
            - close_notional
            - position.structure.entry_fee_usdc
            - close_fee
        )
        status = OutcomeStatus.CLOSED
        total_fee = position.structure.entry_fee_usdc + close_fee
        exit_sequence = selected.frame_capture_seq
        holding_seconds = (selected.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
    else:
        objective = None
        status = OutcomeStatus.OPEN
        close_notional = None
        total_fee = position.structure.entry_fee_usdc
        exit_sequence = None
        holding_seconds = (
            (path.points[-1].observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
            if path.points
            else 0
        )
    return MaturedOutcome(
        position_digest=position.digest,
        outcome_path_digest=path.digest,
        status=status,
        exit_reason=reason,
        exit_capture_seq=exit_sequence,
        holding_seconds=holding_seconds,
        close_debit_usdc=close_notional,
        total_fee_usdc=total_fee,
        objective_usdc=objective,
        maximum_up_fraction=maximum_up,
        maximum_down_fraction=maximum_down,
        first_touch_capture_seq=(
            first_touch.frame_capture_seq if first_touch is not None else None
        ),
        time_to_touch_seconds=(
            (first_touch.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
            if first_touch is not None
            else None
        ),
        max_loss_region=max_loss_region,
    )
