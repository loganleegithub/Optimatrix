from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from options_domain import ComboQuote
from radar_runtime.fixture import build_fixture_events, replay_fixture
from shadow_engine import (
    ExitReason,
    OutcomeStatus,
    build_outcome_path,
    mature_outcome,
    open_position,
)
from short_vol_radar import DecisionFrame


def _future_frame(
    frame: DecisionFrame,
    *,
    capture_seq: int,
    seconds: int,
    executable: bool,
    wall_seconds: int | None = None,
) -> DecisionFrame:
    assert frame.market_as_of is not None
    at = frame.collector_as_of + timedelta(
        seconds=seconds if wall_seconds is None else wall_seconds
    )
    market_at = frame.market_as_of + timedelta(seconds=seconds)
    elapsed_ms = frame.collector_elapsed_ms + seconds * 1_000
    quotes = tuple(
        replace(
            item,
            bid=item.bid if executable else None,
            ask=item.ask if executable else None,
            quote_age_ms=0,
            ticker_source_capture_seq=capture_seq,
            source_at=market_at,
        )
        for item in frame.option_quotes
    )
    return replace(
        frame,
        as_of_capture_seq=capture_seq,
        collector_as_of=at,
        collector_elapsed_ms=elapsed_ms,
        market_as_of=market_at,
        market_as_of_capture_seq=capture_seq,
        reference_source_capture_seq=capture_seq,
        option_quotes=quotes,
        source_capture_seqs=tuple(sorted({*frame.source_capture_seqs, capture_seq})),
    )


def test_outcome_path_rejects_entry_or_pre_entry_frame() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    with pytest.raises(ValueError, match="strictly after entry"):
        build_outcome_path(position, (frame,))


def test_unexitable_horizon_is_scored_at_frozen_max_loss() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=position.horizon_seconds,
        executable=False,
    )
    outcome = mature_outcome(
        position,
        build_outcome_path(position, (future,)),
    )

    assert outcome.status is OutcomeStatus.UNEXITABLE
    assert outcome.exit_reason is ExitReason.UNEXITABLE_AT_HORIZON
    assert outcome.objective_usdc == -position.structure.max_loss_usdc
    assert outcome.close_debit_usdc is None


def test_first_touch_uses_future_path_not_entry_detector() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    touched_price = (
        position.structure.first_touch_level - Decimal("1")
        if position.structure.sold_side.value == "PUT"
        else position.structure.first_touch_level + Decimal("1")
    )
    future = replace(
        _future_frame(
            frame,
            capture_seq=frame.as_of_capture_seq + 1,
            seconds=60,
            executable=True,
        ),
        reference_price=touched_price,
        index_price=touched_price,
    )
    outcome = mature_outcome(
        position,
        build_outcome_path(position, (future,)),
    )

    assert outcome.status is OutcomeStatus.CLOSED
    assert outcome.exit_reason is ExitReason.FIRST_TOUCH
    assert outcome.first_touch_capture_seq == future.as_of_capture_seq
    assert outcome.time_to_touch_seconds == 60


def test_wall_rollback_does_not_reject_future_capture_or_change_holding_time() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        wall_seconds=-60,
        executable=True,
    )

    path = build_outcome_path(position, (future,))
    outcome = mature_outcome(position, path)

    assert path.points[0].as_of < position.entry_at
    assert path.points[0].observed_elapsed_ms - position.entry_elapsed_ms == 60_000
    assert outcome.holding_seconds == 60


def test_wall_forward_jump_does_not_mature_before_elapsed_horizon() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=1,
        wall_seconds=24 * 60 * 60,
        executable=False,
    )

    outcome = mature_outcome(position, build_outcome_path(position, (future,)))

    assert future.collector_as_of - position.entry_at == timedelta(days=1)
    assert outcome.status is OutcomeStatus.OPEN
    assert outcome.exit_reason is ExitReason.DATA_END
    assert outcome.holding_seconds == 1


def test_outcome_path_orders_only_by_capture_sequence_when_wall_regresses() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    first = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        wall_seconds=120,
        executable=False,
    )
    second = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 2,
        seconds=120,
        wall_seconds=-120,
        executable=False,
    )

    path = build_outcome_path(position, (second, first))

    assert tuple(item.frame_capture_seq for item in path.points) == (
        first.as_of_capture_seq,
        second.as_of_capture_seq,
    )
    assert path.points[0].as_of > path.points[1].as_of


def test_heartbeat_frame_cannot_reuse_entry_reference_as_future_outcome() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = replace(
        _future_frame(
            frame,
            capture_seq=frame.as_of_capture_seq + 1,
            seconds=60,
            executable=True,
        ),
        reference_source_capture_seq=frame.reference_source_capture_seq,
    )

    point = build_outcome_path(position, (future,)).points[0]

    assert point.reference_price is None
    assert point.close_debit is None
    assert point.executable_depth is None
    assert point.source_capture_seqs == ()

    outcome = mature_outcome(position, build_outcome_path(position, (future,)))
    assert outcome.objective_usdc is None
    assert outcome.maximum_up_fraction is None
    assert outcome.maximum_down_fraction is None
    assert outcome.max_loss_region is None


def test_stale_future_reference_cannot_drive_outcome_or_executable_close() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    stale = replace(
        future,
        complete=False,
        completeness_reasons=("REFERENCE_STALE",),
    )

    point = build_outcome_path(position, (stale,)).points[0]

    assert point.reference_price is None
    assert point.close_debit is None
    assert point.close_fee_usdc is None
    assert point.executable_depth is None


def test_close_requires_future_tickers_and_freezes_entry_instrument_metadata() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    current_point = build_outcome_path(position, (future,)).points[0]
    instrument_sources = {
        position.structure.short_leg.instrument_source_capture_seq,
        position.structure.long_leg.instrument_source_capture_seq,
    }

    assert current_point.close_debit is not None
    assert instrument_sources.isdisjoint(current_point.source_capture_seqs)
    assert all(item <= position.entry_capture_seq for item in instrument_sources)
    assert all(item > position.entry_capture_seq for item in current_point.source_capture_seqs)

    changed_catalog_quotes = tuple(
        replace(
            item,
            strike=item.strike + Decimal("123"),
            contract_size=item.contract_size * Decimal("7"),
            min_trade_amount=Decimal("0.001"),
            amount_step=Decimal("0.001"),
            taker_commission=Decimal("0.01"),
            instrument_source_capture_seq=future.as_of_capture_seq,
        )
        if item.instrument_name
        in {
            position.structure.short_leg.instrument_name,
            position.structure.long_leg.instrument_name,
        }
        else item
        for item in future.option_quotes
    )
    changed_catalog_point = build_outcome_path(
        position,
        (replace(future, option_quotes=changed_catalog_quotes),),
    ).points[0]

    assert changed_catalog_point.close_debit == current_point.close_debit
    assert changed_catalog_point.close_fee_usdc == current_point.close_fee_usdc
    assert changed_catalog_point.executable_depth == current_point.executable_depth
    assert all(
        item > position.entry_capture_seq for item in changed_catalog_point.source_capture_seqs
    )

    stale_short_quotes = tuple(
        replace(item, ticker_source_capture_seq=position.entry_capture_seq)
        if item.instrument_name == position.structure.short_leg.instrument_name
        else item
        for item in future.option_quotes
    )
    stale_short = replace(future, option_quotes=stale_short_quotes)
    stale_point = build_outcome_path(position, (stale_short,)).points[0]

    assert stale_point.reference_price is not None
    assert stale_point.close_debit is None
    assert stale_point.source_capture_seqs == (future.reference_source_capture_seq,)


def test_close_uses_only_future_exit_sides_not_irrelevant_entry_sides() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    baseline = build_outcome_path(position, (future,)).points[0]
    exit_only_quotes = tuple(
        replace(item, bid=None)
        if item.instrument_name == position.structure.short_leg.instrument_name
        else replace(item, ask=None)
        if item.instrument_name == position.structure.long_leg.instrument_name
        else item
        for item in future.option_quotes
    )
    exit_only = build_outcome_path(
        position,
        (replace(future, option_quotes=exit_only_quotes),),
    ).points[0]

    assert baseline.close_debit is not None
    assert exit_only.close_debit == baseline.close_debit
    assert exit_only.close_fee_usdc == baseline.close_fee_usdc
    assert exit_only.executable_depth == baseline.executable_depth


@pytest.mark.parametrize("missing_leg", ("short_ask", "long_bid"))
def test_close_fails_closed_when_a_future_exit_side_is_missing(missing_leg: str) -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    quotes = tuple(
        replace(item, ask=None)
        if missing_leg == "short_ask"
        and item.instrument_name == position.structure.short_leg.instrument_name
        else replace(item, bid=None)
        if missing_leg == "long_bid"
        and item.instrument_name == position.structure.long_leg.instrument_name
        else item
        for item in future.option_quotes
    )

    point = build_outcome_path(
        position,
        (replace(future, option_quotes=quotes),),
    ).points[0]

    assert point.close_debit is None
    assert point.close_fee_usdc is None


@pytest.mark.parametrize(
    "platform_state,platform_locked,reasons",
    (
        ("LOCKED", True, ("PLATFORM_LOCKED",)),
        ("OPEN", False, ("REFERENCE_NOT_OPEN",)),
        (None, None, ("PLATFORM_STATE_UNKNOWN",)),
    ),
)
def test_close_requires_open_platform_and_reference(
    platform_state: str | None,
    platform_locked: bool | None,
    reasons: tuple[str, ...],
) -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    untradable = replace(
        future,
        platform_state=platform_state,
        platform_locked=platform_locked,
        complete=False,
        completeness_reasons=reasons,
    )

    point = build_outcome_path(position, (untradable,)).points[0]

    assert point.reference_price is (
        None if "REFERENCE_NOT_OPEN" in reasons else future.reference_price
    )
    assert point.close_debit is None
    assert point.close_fee_usdc is None
    assert point.source_capture_seqs == (
        () if "REFERENCE_NOT_OPEN" in reasons else (future.reference_source_capture_seq,)
    )


def test_close_does_not_reuse_entry_combo_quote() -> None:
    frame, decision = replay_fixture(build_fixture_events())
    position = open_position(decision, frame)
    future = _future_frame(
        frame,
        capture_seq=frame.as_of_capture_seq + 1,
        seconds=60,
        executable=True,
    )
    stale_combo = ComboQuote(
        combo_id="stale-entry-combo",
        short_instrument=position.structure.short_leg.instrument_name,
        long_instrument=position.structure.long_leg.instrument_name,
        bid=position.structure.executable_entry_credit,
        ask=Decimal("0.01"),
        bid_amount=position.structure.quantity,
        ask_amount=position.structure.quantity,
        quote_age_ms=0,
        fresh=True,
        valid=True,
        source_capture_seq=position.entry_capture_seq,
    )

    stale_point = build_outcome_path(
        position,
        (replace(future, combo_quotes=(stale_combo,)),),
    ).points[0]
    fresh_combo = replace(stale_combo, source_capture_seq=future.as_of_capture_seq)
    fresh_point = build_outcome_path(
        position,
        (replace(future, combo_quotes=(fresh_combo,)),),
    ).points[0]

    assert stale_point.close_debit != stale_combo.ask
    assert fresh_point.close_debit == fresh_combo.ask
    assert fresh_combo.source_capture_seq in fresh_point.source_capture_seqs
