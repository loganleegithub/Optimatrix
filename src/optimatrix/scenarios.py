from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from optimatrix.case_journal import CaseJournal
from optimatrix.decision import DecisionResult, DecisionWindow
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.lifecycle import (
    FuturePathSummary,
    ObservationStatus,
    PositionState,
    TerminalMethod,
    WindowOutcome,
    window_outcome_eligibility,
)
from optimatrix.market import (
    EventState,
    EventStateSource,
    ExpirySettlementFact,
    ImpliedVarianceMethod,
    MarketContext,
    MarketContextEvidence,
    OptionQuote,
    OptionType,
    PriceLevel,
    RealizedVarianceMethod,
    SettlementEvidenceKind,
    TickSchedule,
    TickStep,
)
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.products import BTC
from optimatrix.radar import BtcWindowAssessment
from optimatrix.risk import AllocationResult, ShadowCapacity
from optimatrix.session import current_deribit_session
from optimatrix.structure import select_btc_0dte_condor

BASE_CHAIN_INSTRUMENTS = (
    "BTC-X-93000-P",
    "BTC-X-95000-P",
    "BTC-X-105000-C",
    "BTC-X-107000-C",
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    facts: dict[str, object]


def run_all_scenarios(policy: BtcShortVolPolicy, *, root: Path) -> tuple[ScenarioResult, ...]:
    return (
        whole_product_candidate(policy, root / "candidate"),
        missing_window_is_unknown(policy, root / "missing"),
        shallow_close_depth_is_diagnostic(policy),
        known_path_risk_abstains(policy, root / "path-risk"),
        atomic_shadow_case_exit(policy, root / "atomic-case"),
        gap_preserves_position_then_settlement(policy, root / "gap-settlement"),
        all_window_outcome_is_independent(policy, root / "window-outcome"),
    )


def whole_product_candidate(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = _window_at(engine, at)
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        context=market_context(at),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(root),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    candidate = assessment.selection.selected if assessment.selection is not None else None
    passed = (
        assessment.record.result is DecisionResult.CANDIDATE
        and candidate is not None
        and assessment.allocation is not None
        and assessment.allocation.result is AllocationResult.AVAILABLE
    )
    return ScenarioResult(
        "whole_product_candidate",
        passed,
        {
            "decision": assessment.record.result.value,
            "candidate_id": candidate.identity if candidate is not None else None,
            "legal_structures": (
                assessment.selection.legal_structure_count
                if assessment.selection is not None
                else 0
            ),
            "combo_fee_native": (
                str(candidate.pricing.combo_standard_fee_native) if candidate is not None else None
            ),
            "allocation": (
                assessment.allocation.result.value if assessment.allocation is not None else None
            ),
        },
    )


def missing_window_is_unknown(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = _window_at(engine, at)
    assessment = engine.assess_window(
        ledger=ObservationLedger(root),
        window=window,
        observation=None,
        capacity=None,
        known_at=window.input_deadline,
    )
    return ScenarioResult(
        "missing_window_is_unknown",
        assessment.record.result is DecisionResult.UNKNOWN
        and assessment.record.blockers == ("NO_OBSERVATION",),
        {
            "decision": assessment.record.result.value,
            "blocker": assessment.record.earliest_blocker,
        },
    )


def shallow_close_depth_is_diagnostic(policy: BtcShortVolPolicy) -> ScenarioResult:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    quotes = tuple(
        replace(quote, ask=(PriceLevel(quote.ask[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P") or quote.instrument_name.endswith("105000-C")
        else quote
        for quote in base_chain(expiry=current_expiry(at), observed_at=at)
    )
    observation = engine.capture_observation(quotes=quotes, context=market_context(at))
    selection = select_btc_0dte_condor(observation=observation, policy=policy)
    candidate = selection.selected
    passed = (
        candidate is not None
        and candidate.pricing.observed_close_native_debit is None
        and min(candidate.close_depth_coverage) == Decimal("0.5")
    )
    return ScenarioResult(
        "shallow_close_depth_is_diagnostic",
        passed,
        {
            "selected": candidate is not None,
            "minimum_close_depth_coverage": (
                str(min(candidate.close_depth_coverage)) if candidate is not None else None
            ),
            "close_price_known": (
                candidate.pricing.observed_close_native_debit is not None
                if candidate is not None
                else None
            ),
        },
    )


def known_path_risk_abstains(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = _window_at(engine, at)
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        context=market_context(at, rv_acceleration=Decimal("0.9")),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(root),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    return ScenarioResult(
        "known_path_risk_abstains",
        assessment.record.result is DecisionResult.ABSTAIN
        and "RV_ACCELERATION_TOO_HIGH" in assessment.record.blockers
        and assessment.selection is None,
        {
            "decision": assessment.record.result.value,
            "blockers": list(assessment.record.blockers),
            "structure_selected": assessment.selection is not None,
        },
    )


def atomic_shadow_case_exit(policy: BtcShortVolPolicy, root: Path) -> ScenarioResult:
    decision_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine, assessment = _candidate_assessment(policy, root, decision_at)
    journal = CaseJournal(root / "journal")
    case = engine.open_case(journal=journal, record=assessment.record)
    entry_at = assessment.record.known_at + timedelta(seconds=30)
    case, entry = engine.evaluate_entry(
        journal=journal,
        case=case,
        observation=engine.capture_observation(
            quotes=base_chain(expiry=current_expiry(entry_at), observed_at=entry_at),
            context=market_context(entry_at),
        ),
        known_at=entry_at,
    )
    trigger_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
    case, monitor = engine.monitor_position(
        journal=journal,
        case=case,
        observation=engine.capture_observation(
            quotes=base_chain(expiry=current_expiry(trigger_at), observed_at=trigger_at),
            context=market_context(trigger_at, event=EventState.LIVE_EVENT),
        ),
    )
    exit_at = trigger_at + timedelta(seconds=2)
    case, exit_evaluation = engine.evaluate_exit(
        journal=journal,
        case=case,
        observation=engine.capture_observation(
            quotes=base_chain(expiry=current_expiry(exit_at), observed_at=exit_at),
            context=market_context(exit_at),
        ),
    )
    recovered = journal.recover(case.identity)
    passed = (
        entry.final
        and case.position_state is PositionState.TERMINAL
        and monitor.exit_intent is not None
        and exit_evaluation.terminal
        and recovered == case
        and case.outcome is not None
        and case.outcome.terminal_method is TerminalMethod.WHOLE_PRODUCT_EXIT
    )
    return ScenarioResult(
        "atomic_shadow_case_exit",
        passed,
        {
            "entry": entry.status.value,
            "exit_reason": monitor.exit_intent.reason if monitor.exit_intent is not None else None,
            "terminal_method": (
                case.outcome.terminal_method.value if case.outcome is not None else None
            ),
            "journal_snapshots": len(journal.read(case.identity)),
        },
    )


def gap_preserves_position_then_settlement(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    decision_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine, assessment = _candidate_assessment(policy, root, decision_at)
    journal = CaseJournal(root / "journal")
    case = engine.open_case(journal=journal, record=assessment.record)
    entry_at = assessment.record.known_at + timedelta(seconds=30)
    case, _ = engine.evaluate_entry(
        journal=journal,
        case=case,
        observation=engine.capture_observation(
            quotes=base_chain(expiry=current_expiry(entry_at), observed_at=entry_at),
            context=market_context(entry_at),
        ),
        known_at=entry_at,
    )
    gap_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
    case, gap = engine.monitor_position(
        journal=journal,
        case=case,
        observation=engine.capture_observation(
            quotes=base_chain(expiry=current_expiry(gap_at), observed_at=gap_at),
            context=market_context(gap_at, evidence=MarketContextEvidence.unknown()),
        ),
    )
    position_id = case.position_id
    expiry = current_expiry(gap_at)
    case = engine.settle_position(
        journal=journal,
        case=case,
        settlement=ExpirySettlementFact(
            product_id=BTC.product_id,
            expiry=expiry,
            delivery_price_usd=Decimal("110000"),
            known_at=expiry,
            evidence_kind=SettlementEvidenceKind.DETERMINISTIC_ACCEPTANCE_FIXTURE,
            source_id="DETERMINISTIC_DELIVERY_FIXTURE",
            method_id="FIXED_DELIVERY_PRICE_V1",
        ),
    )
    passed = (
        gap.observation_status is ObservationStatus.UNKNOWN
        and position_id is not None
        and case.position_id == position_id
        and case.outcome is not None
        and case.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
        and case.outcome.eligibility.future_path_continuous.value is False
        and case.outcome.eligibility.terminal_economics_evaluable.value is True
    )
    return ScenarioResult(
        "gap_preserves_position_then_settlement",
        passed,
        {
            "gap_action": gap.management_action.value
            if gap.management_action is not None
            else None,
            "position_preserved": case.position_id == position_id,
            "terminal_method": (
                case.outcome.terminal_method.value if case.outcome is not None else None
            ),
            "continuous_path_eligible": (
                case.outcome.eligibility.future_path_continuous.value
                if case.outcome is not None
                else None
            ),
        },
    )


def all_window_outcome_is_independent(
    policy: BtcShortVolPolicy,
    root: Path,
) -> ScenarioResult:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    windows = engine.decision_windows(at=at)
    ledger = ObservationLedger(root)
    outcomes: list[WindowOutcome] = []
    for window in windows:
        engine.assess_window(
            ledger=ledger,
            window=window,
            observation=None,
            capacity=None,
            known_at=window.input_deadline,
        )
        horizon = window.ends_at + timedelta(hours=1)
        outcome = WindowOutcome(
            decision_window_id=window.identity,
            horizon_starts_at=window.ends_at,
            horizon_ends_at=horizon,
            known_at=horizon,
            future_path_known=True,
            future_path_continuous=True,
            expiry_settlement=None,
            future_path=FuturePathSummary(
                source_id="DETERMINISTIC_PUBLIC_PATH_FIXTURE",
                method_id="WINDOW_TO_PLUS_ONE_HOUR_SUMMARY_V1",
                starts_at=window.ends_at,
                ends_at=horizon,
                observation_count=2,
                start_index_price_usd=Decimal("100000"),
                end_index_price_usd=Decimal("101000"),
                minimum_index_price_usd=Decimal("99000"),
                maximum_index_price_usd=Decimal("102000"),
                maximum_rv_acceleration=Decimal("0.2"),
            ),
            regime_labels=("DETERMINISTIC_FORWARD_PATH",),
            reason=None,
            eligibility=window_outcome_eligibility(
                decision_evaluable=False,
                future_path_known=True,
                future_path_continuous=True,
            ),
        )
        ledger.append_outcome(outcome)
        outcomes.append(outcome)
    duplicate = ledger.append_outcome(outcomes[0])
    outcome_summary = ledger.summarize_outcomes(expected_windows=windows)
    passed = (
        not duplicate
        and outcome_summary.denominator == outcome_summary.recorded == 96
        and outcome_summary.complete
        and outcome_summary.future_path_known == 96
        and outcome_summary.continuous == 96
    )
    return ScenarioResult(
        "all_window_outcome_is_independent",
        passed,
        {
            "decision_records": len(ledger.read()),
            "window_outcomes": outcome_summary.recorded,
            "future_paths_known": outcome_summary.future_path_known,
            "strategy_population_eligible": outcome_summary.strategy_population_eligible,
            "duplicate_added": duplicate,
        },
    )


def _candidate_assessment(
    policy: BtcShortVolPolicy,
    root: Path,
    at: datetime,
) -> tuple[Btc0DteShortVolEngine, BtcWindowAssessment]:
    engine = Btc0DteShortVolEngine(policy=policy)
    window = _window_at(engine, at)
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        context=market_context(at),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(root / "ledger"),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    return engine, assessment


def current_expiry(now: datetime) -> datetime:
    return current_deribit_session(now).end


def market_context(
    now: datetime,
    *,
    index: Decimal = Decimal("100000"),
    implied_variance: Decimal = Decimal("0.00240"),
    realized_variance: Decimal = Decimal("0.00160"),
    rv_acceleration: Decimal = Decimal("0.10"),
    jump_share: Decimal = Decimal("0.05"),
    directional_persistence: Decimal = Decimal("0.10"),
    event: EventState = EventState.NONE,
    evidence: MarketContextEvidence | None = None,
    book_names: tuple[str, ...] = BASE_CHAIN_INSTRUMENTS,
) -> MarketContext:
    now_ms = int(now.timestamp() * 1000)
    ordered_book_names = tuple(sorted(book_names))
    bound_evidence = evidence or MarketContextEvidence(
        realized_variance_method=(
            RealizedVarianceMethod.DETERMINISTIC_MATCHED_HORIZON_REALIZED_VARIANCE_PROXY
        ),
        implied_variance_method=ImpliedVarianceMethod.DETERMINISTIC_ATM_MARK_VARIANCE_PROXY,
        event_state_source=EventStateSource.DETERMINISTIC_SCENARIO_INPUT,
        required_history_start_ms=now_ms - 120 * 60_000,
        history_coverage_start_ms=now_ms - 120 * 60_000,
        history_coverage_end_ms=now_ms,
        history_cadence_ms=5 * 60_000,
        market_source_min_ms=now_ms,
        market_source_max_ms=now_ms,
        market_received_min_ms=now_ms,
        market_received_max_ms=now_ms,
        event_state_known_at_ms=now_ms,
        maximum_market_age_ms=5_000,
        requested_books=ordered_book_names,
        usable_books=ordered_book_names,
    )
    return MarketContext(
        now=now,
        index_price=index,
        forward_price=index,
        trailing_realized_variance_proxy=realized_variance,
        same_session_implied_variance_proxy=implied_variance,
        rv_acceleration=rv_acceleration,
        jump_share=jump_share,
        directional_persistence=directional_persistence,
        event_state=event,
        concentrated_strike=Decimal("100000"),
        concentration_strength=Decimal("0.70"),
        evidence=bound_evidence,
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
            "93000",
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
            "95000",
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
            "105000",
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
            "107000",
            OptionType.CALL,
            "0.05",
            "0.0008",
            "0.0009",
            tick,
            observed,
            300,
        ),
    )


def all_joint_adversarial_chain(
    *,
    expiry: datetime,
    observed_at: datetime,
) -> tuple[OptionQuote, ...]:
    tick = TickSchedule(Decimal("0.0001"))
    specs = (
        ("BTC-X-93000-P", "93000", OptionType.PUT, "-0.05", "0.0024", "0.0025"),
        ("BTC-X-93500-P", "93500", OptionType.PUT, "-0.20", "0.0026", "0.0027"),
        ("BTC-X-94000-P", "94000", OptionType.PUT, "-0.20", "0.0028", "0.0029"),
        ("BTC-X-94500-P", "94500", OptionType.PUT, "-0.20", "0.0030", "0.0031"),
        ("BTC-X-95000-P", "95000", OptionType.PUT, "-0.25", "0.0050", "0.0051"),
        ("BTC-X-105000-C", "105000", OptionType.CALL, "0.25", "0.0050", "0.0051"),
        ("BTC-X-107000-C", "107000", OptionType.CALL, "0.05", "0.0024", "0.0025"),
    )
    return tuple(
        _quote(name, expiry, strike, option_type, delta, bid, ask, tick, observed_at, index * 100)
        for index, (name, strike, option_type, delta, bid, ask) in enumerate(specs)
    )


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


def _window_at(engine: Btc0DteShortVolEngine, at: datetime) -> DecisionWindow:
    return next(
        window
        for window in engine.decision_windows(at=at)
        if window.starts_at <= at < window.ends_at
    )


def _quote(
    name: str,
    expiry: datetime,
    strike: str,
    option_type: OptionType,
    delta: str,
    bid: str,
    ask: str,
    tick: TickSchedule,
    observed_at: datetime,
    offset_ms: int,
) -> OptionQuote:
    return OptionQuote(
        instrument_name=name,
        product=BTC,
        expiry=expiry,
        strike=Decimal(strike),
        option_type=option_type,
        signed_delta=Decimal(delta),
        mark_iv=Decimal("0.55"),
        bid=(PriceLevel(Decimal(bid), Decimal("1")),),
        ask=(PriceLevel(Decimal(ask), Decimal("1")),),
        tick_schedule=tick,
        source_timestamp_ms=int(observed_at.timestamp() * 1000) - 1_000 + offset_ms,
        received_timestamp_ms=int(observed_at.timestamp() * 1000) - 950 + offset_ms,
        continuity_epoch=1,
        delivery_fee_exempt=True,
        open_interest=Decimal("1000"),
        gamma=Decimal("0.0001"),
    )
