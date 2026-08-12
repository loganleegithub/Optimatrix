from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.engine import ShadowEngine
from optimatrix.lifecycle import EntryStatus, ExitReason, ExitScope, PositionState, SideState
from optimatrix.radar import Decision
from optimatrix.scenarios import (
    _opened_position,
    _remove_ask,
    _remove_bid,
    _update_delta,
    base_chain,
    current_expiry,
    market_context,
    restamp_quotes,
)


def test_threatened_side_can_flatten_short_without_selling_worthless_wing(
    policy,
    tmp_path,
) -> None:
    now, engine, position, quotes = _opened_position(policy, tmp_path)
    risk_at = now + timedelta(hours=2)
    quotes = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.10"),
        observed_at=risk_at,
    )
    quotes = _remove_bid(quotes, instrument_suffix="93000-P")
    instruction = engine.observe_position(
        position=position,
        quotes=quotes,
        context=market_context(risk_at, index=Decimal("96000")),
    )
    assert instruction is not None and instruction.scope is ExitScope.PUT_SIDE
    assert position.put_side.state is SideState.SHORT_FLAT_LONG_WING
    assert not position.put_side.short_open
    assert position.put_side.long_open
    assert position.call_side.short_open


def test_same_day_whipsaw_can_realize_two_side_stops(policy, tmp_path) -> None:
    now, engine, position, quotes = _opened_position(policy, tmp_path)
    down_at = now + timedelta(hours=2)
    first = engine.observe_position(
        position=position,
        quotes=_update_delta(
            quotes,
            put_delta=Decimal("-0.6"),
            call_delta=Decimal("0.08"),
            observed_at=down_at,
        ),
        context=market_context(down_at, index=Decimal("96000")),
    )
    up_at = now + timedelta(hours=5)
    second = engine.observe_position(
        position=position,
        quotes=_update_delta(
            quotes,
            put_delta=Decimal("-0.05"),
            call_delta=Decimal("0.6"),
            observed_at=up_at,
        ),
        context=market_context(up_at, index=Decimal("104500")),
    )
    assert first is not None and second is not None
    assert position.outcome is not None and position.outcome.double_side_stop
    assert position.state is PositionState.TERMINAL


@pytest.mark.parametrize(
    ("missing_wing", "expected_status", "expected_scope"),
    (
        ("107000-C", EntryStatus.PUT_SIDE_ONLY, ExitScope.PUT_SIDE),
        ("93000-P", EntryStatus.CALL_SIDE_ONLY, ExitScope.CALL_SIDE),
    ),
)
def test_partial_entry_is_immediate_remediation_not_strategy_carry(
    policy,
    tmp_path,
    missing_wing,
    expected_status,
    expected_scope,
) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    decision = engine.evaluate(quotes=chain, context=context)
    assert decision.decision is Decision.CANDIDATE
    case = engine.open_decision_case(decision=decision, opened_at=at)
    entry_at = at + timedelta(minutes=1)
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(
            _remove_ask(chain, instrument_suffix=missing_wing),
            entry_at,
        ),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert result.status is expected_status
    assert position is not None and position.has_short_risk
    assert position.state is PositionState.EXIT_REQUIRED
    assert position.first_instruction is not None
    assert position.first_instruction.scope is expected_scope
    assert position.first_instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE

    exit_at = entry_at + timedelta(minutes=1)
    instruction = engine.observe_position(
        position=position,
        quotes=restamp_quotes(chain, exit_at),
        context=replace(context, now=exit_at),
    )
    assert instruction is not None
    assert instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE
    assert not position.has_short_risk
    assert position.outcome is not None
    assert not position.outcome.strategy_outcome_eligible
    assert position.outcome.outcome_population == "ENTRY_ACQUISITION_OPERATIONAL"


def test_full_entry_requires_four_leg_attempt_coherence(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    case = engine.open_decision_case(
        decision=engine.evaluate(quotes=chain, context=context),
        opened_at=at,
    )
    entry_at = at + timedelta(minutes=1)
    entry_quotes = list(restamp_quotes(chain, entry_at))
    for index in (0, 1):
        entry_quotes[index] = replace(
            entry_quotes[index],
            source_timestamp_ms=entry_quotes[index].source_timestamp_ms - 6500,
            received_timestamp_ms=entry_quotes[index].received_timestamp_ms - 4500,
        )
    result, position = engine.attempt_entry(
        case=case,
        quotes=tuple(entry_quotes),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert result.status is EntryStatus.TWO_SIDES_INCOHERENT
    assert result.blockers == ("FOUR_LEG_ENTRY_NOT_COHERENT",)
    assert position is not None and position.has_short_risk
    assert position.state is PositionState.EXIT_REQUIRED
    assert position.first_instruction is not None
    assert position.first_instruction.scope is ExitScope.BOTH_SIDES
    assert position.first_instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE


def test_coherent_full_entry_stays_normal_strategy_carry(policy, tmp_path) -> None:
    _now, _engine, position, _quotes = _opened_position(policy, tmp_path)
    assert position.entry_status is EntryStatus.FULL_ENTRY
    assert position.state is PositionState.MONITORING
    assert position.first_instruction is None


def test_full_entry_outcome_remains_strategy_eligible_after_side_specific_exits(
    policy,
    tmp_path,
) -> None:
    now, engine, position, quotes = _opened_position(policy, tmp_path)
    down_at = now + timedelta(hours=2)
    engine.observe_position(
        position=position,
        quotes=_update_delta(
            quotes,
            put_delta=Decimal("-0.60"),
            call_delta=Decimal("0.08"),
            observed_at=down_at,
        ),
        context=market_context(down_at, index=Decimal("96000")),
    )
    up_at = now + timedelta(hours=5)
    engine.observe_position(
        position=position,
        quotes=_update_delta(
            quotes,
            put_delta=Decimal("-0.05"),
            call_delta=Decimal("0.60"),
            observed_at=up_at,
        ),
        context=market_context(up_at, index=Decimal("104500")),
    )
    assert position.outcome is not None
    assert position.outcome.strategy_outcome_eligible
    assert position.outcome.outcome_population == "IRON_CONDOR_STRATEGY"
    assert position.outcome.strategy_ineligibility_reason is None


def test_decision_and_entry_are_single_terminal_transitions(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=at)
    with pytest.raises(ValueError, match="already exists"):
        engine.open_decision_case(decision=decision, opened_at=at)

    entry_at = at + timedelta(minutes=1)
    entry_quotes = restamp_quotes(chain, entry_at)
    result, position = engine.attempt_entry(
        case=case,
        quotes=entry_quotes,
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert result.status is EntryStatus.FULL_ENTRY
    assert position is not None
    with pytest.raises(ValueError, match="terminal entry result"):
        engine.attempt_entry(
            case=case,
            quotes=entry_quotes,
            context=replace(context, now=entry_at),
            attempted_at=entry_at,
        )


def test_settlement_is_idempotent_and_not_journaled_twice(policy, tmp_path) -> None:
    now, engine, position, _quotes = _opened_position(policy, tmp_path)
    settled_at = current_expiry(now)
    first = engine.settle(
        position=position,
        delivery_price=Decimal("101000"),
        settled_at=settled_at,
    )
    journal_path = next(tmp_path.glob("*.jsonl"))
    before = journal_path.read_text(encoding="utf-8")
    second = engine.settle(
        position=position,
        delivery_price=Decimal("99000"),
        settled_at=settled_at + timedelta(minutes=1),
    )
    after = journal_path.read_text(encoding="utf-8")
    assert second is first
    assert after == before


def test_pending_exit_respects_in_process_retry_cadence(policy, tmp_path) -> None:
    now, engine, position, quotes = _opened_position(policy, tmp_path)
    first_at = now + timedelta(hours=2)
    unavailable = _remove_ask(
        _update_delta(
            quotes,
            put_delta=Decimal("-0.58"),
            call_delta=Decimal("0.10"),
            observed_at=first_at,
        ),
        instrument_suffix="95000-P",
    )
    first = engine.observe_position(
        position=position,
        quotes=unavailable,
        context=market_context(first_at, index=Decimal("96000")),
    )
    assert first is not None
    assert position.put_side.short_open

    too_soon = first_at + timedelta(seconds=10)
    available_soon = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.10"),
        observed_at=too_soon,
    )
    engine.observe_position(
        position=position,
        quotes=available_soon,
        context=market_context(too_soon, index=Decimal("96000")),
    )
    assert position.put_side.short_open

    after_retry = first_at + timedelta(seconds=31)
    available_later = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.10"),
        observed_at=after_retry,
    )
    engine.observe_position(
        position=position,
        quotes=available_later,
        context=market_context(after_retry, index=Decimal("96000")),
    )
    assert not position.put_side.short_open


def test_live_shock_after_entry_requires_both_side_risk_exit(policy, tmp_path) -> None:
    from optimatrix.market import EventState

    now, engine, position, quotes = _opened_position(policy, tmp_path)
    shock_at = now + timedelta(hours=2)
    instruction = engine.observe_position(
        position=position,
        quotes=restamp_quotes(quotes, shock_at),
        context=market_context(shock_at, event=EventState.UNSCHEDULED_SHOCK),
    )
    assert instruction is not None
    assert instruction.scope is ExitScope.BOTH_SIDES
    assert instruction.reason.value == "EVENT_OR_SHOCK"
    assert not position.has_short_risk


def test_entry_deadline_and_future_quote_boundaries_are_enforced(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=at)

    late = at + timedelta(milliseconds=policy.shadow.entry_acquisition_window_ms + 1)
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(chain, late),
        context=replace(context, now=late),
        attempted_at=late,
    )
    assert result.status is EntryStatus.NO_ENTRY
    assert result.blockers == ("ENTRY_ACQUISITION_DEADLINE_EXCEEDED",)
    assert position is None


def test_pending_decision_case_survives_process_restart(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(at)
    chain = base_chain(expiry=current_expiry(at), observed_at=at)
    first = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = first.evaluate(quotes=chain, context=context)
    case = first.open_decision_case(decision=decision, opened_at=at)

    restarted = ShadowEngine(policy=policy, case_root=tmp_path)
    recovered = restarted.recover_decision_case(case.case_identity)
    assert recovered == case
    entry_at = at + timedelta(minutes=1)
    result, position = restarted.attempt_entry(
        case=recovered,
        quotes=restamp_quotes(chain, entry_at),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert result.status is EntryStatus.FULL_ENTRY
    assert position is not None
