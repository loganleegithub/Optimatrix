from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from optimatrix.engine import ShadowEngine
from optimatrix.lifecycle import (
    EntryRoute,
    EntryStatus,
    ExitReason,
    ExitScope,
    PositionState,
    ShadowPosition,
    SideState,
)
from optimatrix.market import (
    BreakoutState,
    EventState,
    MarketContext,
    OptionQuote,
    OptionType,
    PriceLevel,
    TickSchedule,
    TickStep,
)
from optimatrix.persistence import CaseJournal
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.products import BTC
from optimatrix.radar import Decision, RadarDecision


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    facts: dict[str, object]


def run_all_scenarios(
    policy: BtcShortVolPolicy,
    *,
    root: Path | None = None,
) -> tuple[ScenarioResult, ...]:
    target_root = root or Path(tempfile.mkdtemp(prefix="optimatrix-business-scenarios-"))
    target_root.mkdir(parents=True, exist_ok=True)
    return (
        calm_high_vrp_take_profit(policy, target_root / "calm"),
        gamma_explosion_is_rejected(policy, target_root / "gamma"),
        event_phase_changes_decision(policy, target_root / "event"),
        short_only_risk_exit_keeps_long_wing(policy, target_root / "short-only"),
        whipsaw_can_stop_both_sides(policy, target_root / "double-stop"),
        partial_entry_is_persisted(policy, target_root / "partial"),
        process_recovery_keeps_position_duty(policy, target_root / "recovery"),
        expiry_settlement_terminates_residual_risk(policy, target_root / "settlement"),
        roll_reprice_is_review_only(policy, target_root / "roll"),
        low_vrp_is_rejected(policy, target_root / "low-vrp"),
        late_theta_requires_extra_vrp(policy, target_root / "late-theta"),
        wings_only_fallback_is_a_real_position(policy, target_root / "wings-only"),
        source_skew_creates_partial_entry(policy, target_root / "source-skew"),
        public_combo_is_an_optional_diagnostic(policy, target_root / "combo"),
        failed_entry_remains_a_durable_no_entry_case(policy, target_root / "no-entry"),
        friday_expiry_reserves_delivery_fees(policy, target_root / "friday-settlement"),
        failed_exit_survives_process_recovery(policy, target_root / "exit-recovery"),
        live_shock_forces_short_risk_exit(policy, target_root / "live-shock-exit"),
    )


def calm_high_vrp_take_profit(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    quotes = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=quotes, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_context = replace(context, now=now + timedelta(minutes=1))
    entry_result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(quotes, entry_context.now),
        context=entry_context,
        attempted_at=entry_context.now,
    )
    assert position is not None
    later = now + timedelta(hours=4)
    later_context = market_context(later, index=Decimal("100100"))
    decayed = reprice_chain(
        quotes,
        short_bid=Decimal("0.0004"),
        short_ask=Decimal("0.0005"),
        long_bid=Decimal("0.0002"),
        long_ask=Decimal("0.0003"),
        observed_at=later,
    )
    instruction = engine.observe_position(position=position, quotes=decayed, context=later_context)
    outcome = position.outcome
    passed = (
        decision.decision is Decision.CANDIDATE
        and entry_result.status is EntryStatus.FULL_ENTRY
        and instruction is not None
        and instruction.reason is ExitReason.TAKE_PROFIT
        and outcome is not None
        and outcome.total_native_pnl > 0
        and outcome.strategy_outcome_eligible
        and position.state is PositionState.TERMINAL
    )
    return ScenarioResult(
        "calm_high_vrp_take_profit",
        passed,
        {
            "decision": decision.decision.value,
            "score": _score(decision),
            "entry_status": entry_result.status.value,
            "exit_reason": instruction.reason.value if instruction else None,
            "native_pnl": str(outcome.total_native_pnl) if outcome else None,
            "terminal_method": outcome.terminal_method if outcome else None,
        },
    )


def gamma_explosion_is_rejected(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)
    context = market_context(
        now,
        implied_variance=Decimal("0.0030"),
        rv_acceleration=Decimal("0.90"),
        jump_share=Decimal("0.80"),
        directional_persistence=Decimal("0.85"),
        breakout=BreakoutState.BREAKING_CONCENTRATED_STRIKE,
    )
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=context,
    )
    passed = decision.decision is Decision.ABSTAIN and {
        "RV_ACCELERATION_TOO_HIGH",
        "JUMP_SHARE_TOO_HIGH",
        "CONCENTRATED_STRIKE_BREAKOUT",
    }.issubset(set(decision.blockers))
    return ScenarioResult(
        "gamma_explosion_is_rejected",
        passed,
        {
            "decision": decision.decision.value,
            "score": _score(decision),
            "blockers": list(decision.blockers),
        },
    )


def event_phase_changes_decision(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 16, 0, tzinfo=UTC)
    quotes = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    pre = engine.evaluate(
        quotes=quotes,
        context=market_context(now, event=EventState.PRE_EVENT),
    )
    post = engine.evaluate(
        quotes=quotes,
        context=market_context(now + timedelta(hours=1), event=EventState.POST_EVENT),
    )
    passed = pre.decision is not Decision.CANDIDATE and post.decision is Decision.CANDIDATE
    return ScenarioResult(
        "event_phase_changes_decision",
        passed,
        {
            "pre_event_decision": pre.decision.value,
            "pre_event_score": _score(pre),
            "post_event_decision": post.decision.value,
            "post_event_score": _score(post),
        },
    )


def short_only_risk_exit_keeps_long_wing(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now, engine, position, quotes = _opened_position(policy, root)
    threatened_context = market_context(
        now + timedelta(hours=2),
        index=Decimal("96000"),
        rv_acceleration=Decimal("0.45"),
    )
    threatened = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.10"),
        observed_at=threatened_context.now,
    )
    threatened = _remove_bid(threatened, instrument_suffix="93000-P")
    instruction = engine.observe_position(
        position=position,
        quotes=threatened,
        context=threatened_context,
    )
    passed = (
        instruction is not None
        and instruction.scope is ExitScope.PUT_SIDE
        and position.put_side.state is SideState.SHORT_FLAT_LONG_WING
        and not position.put_side.short_open
        and position.put_side.long_open
        and position.call_side.short_open
        and position.state is PositionState.EXIT_REQUIRED
    )
    return ScenarioResult(
        "short_only_risk_exit_keeps_long_wing",
        passed,
        {
            "instruction": instruction.reason.value if instruction else None,
            "put_side_state": position.put_side.state.value,
            "call_side_state": position.call_side.state.value,
            "position_state": position.state.value,
            "short_risk_remaining": position.has_short_risk,
            "residual_wings": position.residual_wing_count,
        },
    )


def whipsaw_can_stop_both_sides(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now, engine, position, quotes = _opened_position(policy, root)
    down_context = market_context(now + timedelta(hours=2), index=Decimal("96000"))
    down_quotes = _update_delta(
        quotes,
        put_delta=Decimal("-0.60"),
        call_delta=Decimal("0.08"),
        observed_at=down_context.now,
    )
    first = engine.observe_position(position=position, quotes=down_quotes, context=down_context)
    up_context = market_context(now + timedelta(hours=5), index=Decimal("104500"))
    up_quotes = _update_delta(
        quotes,
        put_delta=Decimal("-0.05"),
        call_delta=Decimal("0.60"),
        observed_at=up_context.now,
    )
    second = engine.observe_position(position=position, quotes=up_quotes, context=up_context)
    outcome = position.outcome
    passed = (
        first is not None
        and second is not None
        and first.scope is ExitScope.PUT_SIDE
        and second.scope is ExitScope.CALL_SIDE
        and outcome is not None
        and outcome.double_side_stop
    )
    return ScenarioResult(
        "whipsaw_can_stop_both_sides",
        passed,
        {
            "first_scope": first.scope.value if first else None,
            "second_scope": second.scope.value if second else None,
            "double_side_stop": outcome.double_side_stop if outcome else None,
            "native_pnl": str(outcome.total_native_pnl) if outcome else None,
        },
    )


def partial_entry_is_persisted(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now))
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_chain = restamp_quotes(
        _remove_ask(chain, instrument_suffix="107000-C"),
        now + timedelta(minutes=1),
    )
    result, position = engine.attempt_entry(
        case=case,
        quotes=entry_chain,
        context=replace(context, now=now + timedelta(minutes=1)),
        attempted_at=now + timedelta(minutes=1),
    )
    recovered = engine.recover_position(case.case_identity)
    assert recovered is not None
    remediation_at = now + timedelta(minutes=2)
    instruction = engine.observe_position(
        position=recovered,
        quotes=restamp_quotes(chain, remediation_at),
        context=replace(context, now=remediation_at),
    )
    passed = (
        result.status is EntryStatus.PUT_SIDE_ONLY
        and position is not None
        and recovered.entry_status is EntryStatus.PUT_SIDE_ONLY
        and instruction is not None
        and instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE
        and not recovered.put_side.short_open
        and not recovered.call_side.short_open
        and recovered.outcome is not None
        and not recovered.outcome.strategy_outcome_eligible
    )
    return ScenarioResult(
        "partial_entry_is_persisted",
        passed,
        {
            "entry_status": result.status.value,
            "blockers": list(result.blockers),
            "recovered_remediation_reason": (
                instruction.reason.value if instruction is not None else None
            ),
            "short_risk_flat": not recovered.has_short_risk,
            "strategy_outcome_eligible": (
                recovered.outcome.strategy_outcome_eligible
                if recovered.outcome is not None
                else None
            ),
        },
    )


def process_recovery_keeps_position_duty(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now, _engine, position, quotes = _opened_position(policy, root)
    first_engine_identity = position.position_identity
    restarted = ShadowEngine(policy=policy, case_root=root)
    recovered = restarted.recover_position(position.case_identity)
    assert recovered is not None
    context = market_context(now + timedelta(hours=3), index=Decimal("96000"))
    risk_quotes = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.08"),
        observed_at=context.now,
    )
    instruction = restarted.observe_position(
        position=recovered,
        quotes=risk_quotes,
        context=context,
    )
    passed = (
        recovered.position_identity == first_engine_identity
        and instruction is not None
        and recovered.put_side.short_risk_exit_at is not None
    )
    return ScenarioResult(
        "process_recovery_keeps_position_duty",
        passed,
        {
            "same_position_identity": recovered.position_identity == first_engine_identity,
            "instruction": instruction.reason.value if instruction else None,
            "put_short_flat": not recovered.put_side.short_open,
        },
    )


def expiry_settlement_terminates_residual_risk(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now, engine, position, _quotes = _opened_position(policy, root)
    expiry = current_expiry(now)
    outcome = engine.settle(
        position=position,
        delivery_price=Decimal("101000"),
        settled_at=expiry,
    )
    passed = (
        outcome.terminal_method == "CONTRACT_SETTLEMENT"
        and position.state is PositionState.TERMINAL
        and not position.has_short_risk
        and outcome.residual_wing_count == 0
    )
    return ScenarioResult(
        "expiry_settlement_terminates_residual_risk",
        passed,
        {
            "terminal_method": outcome.terminal_method,
            "native_pnl": str(outcome.total_native_pnl),
            "boundary_usd_pnl": str(outcome.boundary_valued_total_usd_pnl),
            "terminal_valued_usd_pnl": str(outcome.terminal_valued_total_usd_pnl),
        },
    )


def roll_reprice_is_review_only(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 8, 20, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(now),
    )
    passed = (
        decision.decision is Decision.REVIEW and "ROLL_REPRICE_REVIEW_ONLY" in decision.blockers
    )
    return ScenarioResult(
        "roll_reprice_is_review_only",
        passed,
        {"decision": decision.decision.value, "blockers": list(decision.blockers)},
    )


def low_vrp_is_rejected(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(
            now,
            implied_variance=Decimal("0.00172"),
            physical_variance=Decimal("0.00160"),
        ),
    )
    passed = (
        decision.decision is Decision.ABSTAIN and "SESSION_VRP_BELOW_THRESHOLD" in decision.blockers
    )
    return ScenarioResult(
        "low_vrp_is_rejected",
        passed,
        {
            "decision": decision.decision.value,
            "vrp_ratio": str(decision.score.vrp_ratio) if decision.score else None,
            "blockers": list(decision.blockers),
        },
    )


def late_theta_requires_extra_vrp(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 13, 5, 30, tzinfo=UTC)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(
            now,
            implied_variance=Decimal("0.00184"),
            physical_variance=Decimal("0.00160"),
        ),
    )
    passed = (
        decision.decision is Decision.ABSTAIN and "SESSION_VRP_BELOW_THRESHOLD" in decision.blockers
    )
    return ScenarioResult(
        "late_theta_requires_extra_vrp",
        passed,
        {
            "phase": decision.phase.value,
            "decision": decision.decision.value,
            "vrp_ratio": str(decision.score.vrp_ratio) if decision.score else None,
        },
    )


def wings_only_fallback_is_a_real_position(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_at = now + timedelta(minutes=1)
    no_short_bids = tuple(
        replace(quote, bid=()) if quote.instrument_name.endswith(("95000-P", "105000-C")) else quote
        for quote in restamp_quotes(chain, entry_at)
    )
    result, position = engine.attempt_entry(
        case=case,
        quotes=no_short_bids,
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
        allow_wings_only_fallback=True,
    )
    assert position is not None
    wing_sale_at = now + timedelta(hours=2)
    wing_quotes = reprice_chain(
        chain,
        short_bid=Decimal("0.0010"),
        short_ask=Decimal("0.0011"),
        long_bid=Decimal("0.0010"),
        long_ask=Decimal("0.0011"),
        observed_at=wing_sale_at,
    )
    outcome = engine.dispose_wings(
        position=position,
        quotes=wing_quotes,
        context=market_context(wing_sale_at),
    )
    passed = (
        result.status is EntryStatus.WINGS_ONLY
        and position.short_risk_flat_at == entry_at
        and outcome is not None
        and outcome.terminal_method == "MARKET_EXIT"
        and not outcome.strategy_outcome_eligible
    )
    return ScenarioResult(
        "wings_only_fallback_is_a_real_position",
        passed,
        {
            "entry_status": result.status.value,
            "short_risk_flat_at_entry": position.short_risk_flat_at == entry_at,
            "terminal": outcome is not None,
        },
    )


def source_skew_creates_partial_entry(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_at = now + timedelta(minutes=1)
    entry_chain = list(restamp_quotes(chain, entry_at))
    entry_chain[3] = replace(
        entry_chain[3],
        source_timestamp_ms=entry_chain[2].source_timestamp_ms + 7000,
        received_timestamp_ms=entry_chain[2].received_timestamp_ms + 5000,
    )
    result, position = engine.attempt_entry(
        case=case,
        quotes=tuple(entry_chain),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    passed = (
        result.status is EntryStatus.PUT_SIDE_ONLY
        and position is not None
        and "CALL_ENTRY_PAIR_NOT_STRICTLY_FUTURE_OR_COHERENT" in result.blockers
        and position.state is PositionState.EXIT_REQUIRED
        and position.first_instruction is not None
        and position.first_instruction.reason is ExitReason.ENTRY_ACQUISITION_INCOMPLETE
    )
    return ScenarioResult(
        "source_skew_creates_partial_entry",
        passed,
        {"entry_status": result.status.value, "blockers": list(result.blockers)},
    )


def public_combo_is_an_optional_diagnostic(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_at = now + timedelta(minutes=1)
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(chain, entry_at),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
        public_combo_observed=True,
    )
    passed = (
        result.status is EntryStatus.FULL_ENTRY
        and result.route is EntryRoute.TWO_VERTICALS
        and result.public_combo_observed
        and position is not None
    )
    return ScenarioResult(
        "public_combo_is_an_optional_diagnostic",
        passed,
        {
            "route": result.route.value,
            "public_combo_observed": result.public_combo_observed,
            "entry_status": result.status.value,
        },
    )


def failed_entry_remains_a_durable_no_entry_case(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_at = now + timedelta(minutes=1)
    unavailable = tuple(replace(quote, bid=(), ask=()) for quote in restamp_quotes(chain, entry_at))
    result, position = engine.attempt_entry(
        case=case,
        quotes=unavailable,
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    events = CaseJournal(root, case.case_identity).read()
    kinds = tuple(str(event["kind"]) for event in events)
    passed = (
        result.status is EntryStatus.NO_ENTRY
        and position is None
        and kinds == ("DECISION_OPENED", "ENTRY_TERMINAL")
    )
    return ScenarioResult(
        "failed_entry_remains_a_durable_no_entry_case",
        passed,
        {
            "entry_status": result.status.value,
            "event_kinds": list(kinds),
            "blockers": list(result.blockers),
        },
    )


def friday_expiry_reserves_delivery_fees(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    context = market_context(now)
    chain = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=chain, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_at = now + timedelta(minutes=1)
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(chain, entry_at),
        context=replace(context, now=entry_at),
        attempted_at=entry_at,
    )
    assert position is not None
    outcome = engine.settle(
        position=position,
        delivery_price=Decimal("110000"),
        settled_at=current_expiry(now),
    )
    passed = (
        result.status is EntryStatus.FULL_ENTRY
        and outcome.terminal_method == "CONTRACT_SETTLEMENT"
        and outcome.total_delivery_fee_native > 0
        and outcome.residual_wings_settled == 2
        and outcome.residual_wing_count == 0
    )
    return ScenarioResult(
        "friday_expiry_reserves_delivery_fees",
        passed,
        {
            "delivery_fee_native": str(outcome.total_delivery_fee_native),
            "residual_wings_settled": outcome.residual_wings_settled,
            "boundary_valued_pnl_usd": str(outcome.boundary_valued_total_usd_pnl),
            "terminal_valued_pnl_usd": str(outcome.terminal_valued_total_usd_pnl),
        },
    )


def failed_exit_survives_process_recovery(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now, engine, position, quotes = _opened_position(policy, root)
    risk_at = now + timedelta(hours=2)
    blocked_quotes = _update_delta(
        quotes,
        put_delta=Decimal("-0.58"),
        call_delta=Decimal("0.10"),
        observed_at=risk_at,
    )
    blocked_quotes = _remove_ask(blocked_quotes, instrument_suffix="95000-P")
    first = engine.observe_position(
        position=position,
        quotes=blocked_quotes,
        context=market_context(risk_at, index=Decimal("96000")),
    )
    restarted = ShadowEngine(policy=policy, case_root=root)
    recovered = restarted.recover_position(position.case_identity)
    assert recovered is not None
    exit_at = risk_at + timedelta(minutes=1)
    second = restarted.observe_position(
        position=recovered,
        quotes=restamp_quotes(quotes, exit_at),
        context=market_context(exit_at, index=Decimal("96000")),
    )
    passed = (
        first is not None
        and recovered.put_side.exit_requested_reason is ExitReason.PUT_SIDE_DELTA
        and second is not None
        and not recovered.put_side.short_open
        and len(recovered.instructions) == 1
    )
    return ScenarioResult(
        "failed_exit_survives_process_recovery",
        passed,
        {
            "first_reason": first.reason.value if first else None,
            "recovered_pending_reason": (
                recovered.put_side.exit_requested_reason.value
                if recovered.put_side.exit_requested_reason is not None
                else None
            ),
            "short_flat_after_recovery": not recovered.put_side.short_open,
            "durable_instruction_count": len(recovered.instructions),
        },
    )


def current_expiry(now: datetime) -> datetime:
    settlement = now.astimezone(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    return settlement if now < settlement else settlement + timedelta(days=1)


def market_context(
    now: datetime,
    *,
    index: Decimal = Decimal("100000"),
    implied_variance: Decimal = Decimal("0.00240"),
    physical_variance: Decimal = Decimal("0.00160"),
    rv_acceleration: Decimal = Decimal("0.10"),
    jump_share: Decimal = Decimal("0.05"),
    directional_persistence: Decimal = Decimal("0.10"),
    event: EventState = EventState.NONE,
    breakout: BreakoutState = BreakoutState.MEAN_REVERTING,
) -> MarketContext:
    return MarketContext(
        now=now,
        index_price=index,
        forward_price=index,
        physical_variance_forecast=physical_variance,
        same_session_implied_variance=implied_variance,
        rv_acceleration=rv_acceleration,
        jump_share=jump_share,
        directional_persistence=directional_persistence,
        event_state=event,
        breakout_state=breakout,
        concentrated_strike=Decimal("100000"),
        concentration_strength=Decimal("0.70"),
    )


def base_chain(*, expiry: datetime, observed_at: datetime | None = None) -> tuple[OptionQuote, ...]:
    tick = TickSchedule(
        Decimal("0.0001"),
        (TickStep(Decimal("0.005"), Decimal("0.0005")),),
    )
    observed = observed_at or (expiry - timedelta(hours=14))
    return (
        _quote(
            "BTC-X-93000-P",
            expiry,
            Decimal("93000"),
            OptionType.PUT,
            "-0.05",
            "0.0008",
            "0.0009",
            tick,
            observed,
            0,
        ),
        _quote(
            "BTC-X-95000-P",
            expiry,
            Decimal("95000"),
            OptionType.PUT,
            "-0.15",
            "0.0028",
            "0.0029",
            tick,
            observed,
            100,
        ),
        _quote(
            "BTC-X-105000-C",
            expiry,
            Decimal("105000"),
            OptionType.CALL,
            "0.15",
            "0.0028",
            "0.0029",
            tick,
            observed,
            200,
        ),
        _quote(
            "BTC-X-107000-C",
            expiry,
            Decimal("107000"),
            OptionType.CALL,
            "0.05",
            "0.0008",
            "0.0009",
            tick,
            observed,
            300,
        ),
    )


def reprice_chain(
    quotes: tuple[OptionQuote, ...],
    *,
    short_bid: Decimal,
    short_ask: Decimal,
    long_bid: Decimal,
    long_ask: Decimal,
    observed_at: datetime | None = None,
) -> tuple[OptionQuote, ...]:
    output: list[OptionQuote] = []
    for quote in quotes:
        is_short = quote.instrument_name.endswith("95000-P") or (
            quote.instrument_name.endswith("105000-C")
        )
        bid = short_bid if is_short else long_bid
        ask = short_ask if is_short else long_ask
        output.append(
            replace(
                quote,
                bid=(PriceLevel(bid, Decimal("1")),),
                ask=(PriceLevel(ask, Decimal("1")),),
            )
        )
    result = tuple(output)
    return restamp_quotes(result, observed_at) if observed_at is not None else result


def _quote(
    name: str,
    expiry: datetime,
    strike: Decimal,
    option_type: OptionType,
    delta: str,
    bid: str,
    ask: str,
    tick: TickSchedule,
    observed_at: datetime,
    offset_ms: int,
    delivery_fee_exempt: bool | None = None,
) -> OptionQuote:
    return OptionQuote(
        instrument_name=name,
        product=BTC,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        signed_delta=Decimal(delta),
        mark_iv=Decimal("0.55"),
        bid=(PriceLevel(Decimal(bid), Decimal("1")),),
        ask=(PriceLevel(Decimal(ask), Decimal("1")),),
        tick_schedule=tick,
        source_timestamp_ms=int(observed_at.timestamp() * 1000) - 1_000 + offset_ms,
        received_timestamp_ms=int(observed_at.timestamp() * 1000) - 950 + offset_ms,
        continuity_epoch=1,
        delivery_fee_exempt=(
            expiry.weekday() != 4 if delivery_fee_exempt is None else delivery_fee_exempt
        ),
        open_interest=Decimal("1000"),
        gamma=Decimal("0.0001"),
    )


def live_shock_forces_short_risk_exit(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    now, engine, position, quotes = _opened_position(policy, root)
    shock_at = now + timedelta(hours=2)
    instruction = engine.observe_position(
        position=position,
        quotes=restamp_quotes(quotes, shock_at),
        context=market_context(shock_at, event=EventState.UNSCHEDULED_SHOCK),
    )
    passed = (
        instruction is not None
        and instruction.reason is ExitReason.EVENT_OR_SHOCK
        and instruction.scope is ExitScope.BOTH_SIDES
        and not position.has_short_risk
    )
    return ScenarioResult(
        "live_shock_forces_short_risk_exit",
        passed,
        {
            "instruction": instruction.reason.value if instruction else None,
            "scope": instruction.scope.value if instruction else None,
            "short_risk_remaining": position.has_short_risk,
        },
    )


def _opened_position(
    policy: BtcShortVolPolicy,
    root: Path,
) -> tuple[datetime, ShadowEngine, ShadowPosition, tuple[OptionQuote, ...]]:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    quotes = base_chain(expiry=current_expiry(now), observed_at=now)
    engine = ShadowEngine(policy=policy, case_root=root)
    decision = engine.evaluate(quotes=quotes, context=context)
    case = engine.open_decision_case(decision=decision, opened_at=now)
    entry_context = replace(context, now=now + timedelta(minutes=1))
    result, position = engine.attempt_entry(
        case=case,
        quotes=restamp_quotes(quotes, entry_context.now),
        context=entry_context,
        attempted_at=entry_context.now,
    )
    if position is None or result.status is not EntryStatus.FULL_ENTRY:
        raise AssertionError("scenario fixture did not establish the full position")
    return now, engine, position, quotes


def _update_delta(
    quotes: tuple[OptionQuote, ...],
    *,
    put_delta: Decimal,
    call_delta: Decimal,
    observed_at: datetime | None = None,
) -> tuple[OptionQuote, ...]:
    output: list[OptionQuote] = []
    for quote in quotes:
        if quote.instrument_name.endswith("95000-P"):
            output.append(replace(quote, signed_delta=put_delta))
        elif quote.instrument_name.endswith("105000-C"):
            output.append(replace(quote, signed_delta=call_delta))
        else:
            output.append(quote)
    result = tuple(output)
    return restamp_quotes(result, observed_at) if observed_at is not None else result


def restamp_quotes(
    quotes: tuple[OptionQuote, ...],
    observed_at: datetime,
) -> tuple[OptionQuote, ...]:
    base = int(observed_at.timestamp() * 1000) - 1_000
    return tuple(
        replace(
            quote,
            source_timestamp_ms=base + index * 100,
            received_timestamp_ms=base + index * 100 + 50,
            continuity_epoch=1,
        )
        for index, quote in enumerate(quotes)
    )


def _remove_bid(
    quotes: tuple[OptionQuote, ...],
    *,
    instrument_suffix: str,
) -> tuple[OptionQuote, ...]:
    return tuple(
        replace(quote, bid=()) if quote.instrument_name.endswith(instrument_suffix) else quote
        for quote in quotes
    )


def _remove_ask(
    quotes: tuple[OptionQuote, ...],
    *,
    instrument_suffix: str,
) -> tuple[OptionQuote, ...]:
    return tuple(
        replace(quote, ask=()) if quote.instrument_name.endswith(instrument_suffix) else quote
        for quote in quotes
    )


def _score(decision: RadarDecision) -> str | None:
    return str(decision.score.final_score) if decision.score is not None else None
