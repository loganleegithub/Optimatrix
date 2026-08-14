from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from optimatrix.case_journal import CaseJournal
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.lifecycle import (
    FuturePathSummary,
    ObservationStatus,
    PositionAction,
    PositionState,
    ShadowEntryStatus,
    TerminalMethod,
    WindowOutcome,
    evaluate_shadow_entry,
    evaluate_shadow_exit,
    freeze_latest_exit_on_time_boundary,
    monitor_shadow_position,
    open_trade_case,
    settle_shadow_position,
    window_outcome_eligibility,
)
from optimatrix.market import (
    EventState,
    ExpirySettlementFact,
    MarketContextEvidence,
    PriceLevel,
    SettlementEvidenceKind,
)
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.products import BTC
from optimatrix.risk import ShadowCapacity
from optimatrix.scenarios import (
    all_joint_adversarial_chain,
    base_chain,
    current_expiry,
    market_context,
)
from optimatrix.structure import select_btc_0dte_condor
from optimatrix.workbench import build_case_projection


def _candidate(policy, tmp_path, *, decision_at=None):
    decision_at = decision_at or datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item
        for item in engine.decision_windows(at=decision_at)
        if item.starts_at <= decision_at < item.ends_at
    )
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(decision_at), observed_at=decision_at),
        context=market_context(decision_at),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(tmp_path / "ledger"),
        window=window,
        observation=observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    case = open_trade_case(assessment.record, policy)
    return engine, assessment.record, case


def _observation(
    engine,
    at,
    *,
    event=EventState.NONE,
    quotes=None,
    evidence=None,
    context_overrides=None,
):
    bound_quotes = quotes or base_chain(expiry=current_expiry(at), observed_at=at)
    return engine.capture_observation(
        quotes=bound_quotes,
        context=market_context(
            at,
            event=event,
            evidence=evidence,
            book_names=tuple(quote.instrument_name for quote in bound_quotes),
            **(context_overrides or {}),
        ),
    )


def _entered_case(policy, tmp_path):
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    observation = _observation(engine, entry_at)
    entered, evaluation = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )
    assert evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
    return engine, entered


def test_atomic_entry_creates_one_whole_product_shadow_position(policy, tmp_path) -> None:
    _engine, case = _entered_case(policy, tmp_path)

    assert case.entry_final
    assert case.entry_reunderwriting is not None
    assert case.entry_reunderwriting.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
    assert case.entry_reunderwriting.environment_blockers == ()
    assert case.entry_reunderwriting.structure_blockers == ()
    assert case.entry_reunderwriting.economics_blockers == ()
    assert case.entry_reunderwriting.allocation_blockers == ()
    assert case.entry_reunderwriting.route_blockers == ()
    assert case.entry_reunderwriting.decision_metrics.vrp_proxy_ratio == Decimal("1.5")
    assert case.entry_reunderwriting.entry_metrics.vrp_proxy_ratio == Decimal("1.5")
    assert case.position_id is not None
    assert case.position_state is PositionState.MONITORING
    assert case.entry_native_net_credit is not None
    assert not hasattr(case, "put_side")
    assert not hasattr(case, "residual_wings")


def test_entry_requires_frozen_legs_and_strictly_future_quote_boundaries(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    boundary_cut = record.known_at + timedelta(seconds=1)
    boundary_observation = _observation(engine, boundary_cut)
    unknown, evaluation = evaluate_shadow_entry(
        case,
        observation=boundary_observation,
        policy=policy,
        known_at=boundary_observation.known_at,
    )
    assert evaluation.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
    assert evaluation.reason == "ENTRY_QUOTES_NOT_STRICTLY_FUTURE"
    assert unknown.position_id is None

    later = record.known_at + timedelta(seconds=30)
    altered = tuple(
        replace(quote, strike=quote.strike + Decimal("1"))
        if quote.instrument_name.endswith("95000-P")
        else quote
        for quote in base_chain(expiry=current_expiry(later), observed_at=later)
    )
    altered_observation = _observation(engine, later, quotes=altered)
    unknown, evaluation = evaluate_shadow_entry(
        case,
        observation=altered_observation,
        policy=policy,
        known_at=altered_observation.known_at,
    )
    assert evaluation.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
    assert evaluation.reason == "SELECTED_STRUCTURE_QUOTES_MISSING"
    assert unknown.position_id is None


def test_missing_leg_stays_unknown_and_terminalizes_without_position_at_deadline(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    observed_at = record.known_at + timedelta(seconds=30)
    quotes = base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)[:-1]
    observation = _observation(engine, observed_at, quotes=quotes)

    provisional, first = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )
    assert first.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
    assert not first.final
    assert provisional.position_id is None

    terminal, final = evaluate_shadow_entry(
        provisional,
        observation=observation,
        policy=policy,
        known_at=case.entry_deadline,
    )
    assert final.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
    assert final.final
    assert terminal.position_id is None
    assert terminal.outcome is not None
    assert terminal.outcome.terminal_method is TerminalMethod.NO_POSITION


def test_complete_but_shallow_entry_is_not_evaluable_and_never_partial(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    observed_at = record.known_at + timedelta(seconds=30)
    quotes = tuple(
        replace(quote, bid=(PriceLevel(quote.bid[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P")
        else quote
        for quote in base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)
    )
    observation = _observation(engine, observed_at, quotes=quotes)

    terminal, evaluation = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )
    assert evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE
    assert terminal.position_id is None
    assert terminal.outcome is not None
    assert terminal.outcome.eligibility.shadow_entry_evaluable.value is False


def test_entry_reunderwriting_rejects_later_vrp_failure(policy, tmp_path) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    observation = _observation(
        engine,
        entry_at,
        context_overrides={
            "implied_variance": Decimal("0.00100"),
            "realized_variance": Decimal("0.00160"),
        },
    )

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.ENTRY_THESIS_EXPIRED
    assert result.environment_blockers == ("SESSION_VRP_PROXY_BELOW_THRESHOLD",)
    assert result.decision_metrics.vrp_proxy_ratio == Decimal("1.5")
    assert result.entry_metrics.vrp_proxy_ratio == Decimal("0.625")
    assert rejected.position_id is None
    assert rejected.outcome is not None


def test_entry_reunderwriting_rejects_phase_that_closed_after_decision(
    policy,
    tmp_path,
) -> None:
    decision_at = datetime(2026, 8, 13, 6, 28, tzinfo=UTC)
    engine, record, case = _candidate(policy, tmp_path, decision_at=decision_at)
    entry_at = record.known_at + timedelta(seconds=30)
    observation = _observation(engine, entry_at)

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.ENTRY_THESIS_EXPIRED
    assert result.decision_session_phase.value == "LATE_THETA"
    assert result.entry_session_phase is not None
    assert result.entry_session_phase.value == "EXIT_ONLY"
    assert result.environment_blockers == ("NEW_ENTRY_WINDOW_CLOSED",)
    assert rejected.position_id is None


@pytest.mark.parametrize(
    ("instrument_suffix", "signed_delta", "expected_blocker"),
    (
        ("95000-P", Decimal("-0.30"), "SHORT_PUT_DELTA_OUTSIDE_POLICY"),
        ("93000-P", Decimal("-0.30"), "NET_DELTA_TOO_DIRECTIONAL"),
    ),
)
def test_entry_reunderwriting_rejects_current_delta_limits(
    policy,
    tmp_path,
    instrument_suffix,
    signed_delta,
    expected_blocker,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    quotes = tuple(
        replace(quote, signed_delta=signed_delta)
        if quote.instrument_name.endswith(instrument_suffix)
        else quote
        for quote in base_chain(expiry=current_expiry(entry_at), observed_at=entry_at)
    )
    observation = _observation(engine, entry_at, quotes=quotes)

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED
    assert expected_blocker in result.structure_blockers
    assert rejected.position_id is None


def test_entry_reunderwriting_rejects_current_body_distance(policy, tmp_path) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    observation = _observation(
        engine,
        entry_at,
        context_overrides={
            "implied_variance": Decimal("0.015"),
            "realized_variance": Decimal("0.01"),
        },
    )

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED
    assert result.structure_blockers == ("BODY_DISTANCE_TOO_SMALL",)
    assert result.entry_metrics.put_body_distance_sigma is not None
    assert result.entry_metrics.put_body_distance_sigma < (
        policy.structure.minimum_body_distance_sigma
    )
    assert rejected.position_id is None


def test_entry_reunderwriting_rejects_credit_payoff_and_fee_deterioration(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    quotes = tuple(
        replace(quote, bid=(PriceLevel(Decimal("0.0016"), Decimal("1")),))
        if quote.instrument_name.endswith(("95000-P", "105000-C"))
        else quote
        for quote in base_chain(expiry=current_expiry(entry_at), observed_at=entry_at)
    )
    observation = _observation(engine, entry_at, quotes=quotes)

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.ENTRY_PRICE_DETERIORATED
    assert result.economics_blockers == (
        "BOUNDARY_NET_CREDIT_TOO_SMALL",
        "CREDIT_TO_PAYOFF_CAP_TOO_SMALL",
        "COMBO_FEE_BURDEN_TOO_HIGH",
    )
    assert result.entry_metrics.boundary_net_credit_usd == Decimal("6.25000000")
    assert rejected.position_id is None


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    (
        ("market_session_id", "FOREIGN_SESSION", "ALLOCATION_SESSION_MISMATCH"),
        ("expires_at", "2026-08-12T18:16:30+00:00", "ALLOCATION_EXPIRED_AT_ENTRY"),
    ),
)
def test_entry_reunderwriting_rejects_allocation_mismatch_or_expiry(
    policy,
    tmp_path,
    field,
    value,
    expected_blocker,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    allocation = dict(case.risk_allocation)
    allocation[field] = value
    altered_case = replace(
        case,
        risk_allocation_json=json.dumps(
            allocation,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    entry_at = record.known_at + timedelta(seconds=30)
    observation = _observation(engine, entry_at)

    rejected, result = evaluate_shadow_entry(
        altered_case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.status is ShadowEntryStatus.RISK_RESERVATION_INVALID
    assert expected_blocker in result.allocation_blockers
    assert "ALLOCATION_IDENTITY_MISMATCH" in result.allocation_blockers
    assert rejected.position_id is None


def test_entry_never_reselects_a_better_structure(policy, tmp_path) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    entry_at = record.known_at + timedelta(seconds=30)
    quotes = tuple(
        replace(quote, signed_delta=Decimal("-0.30"))
        if quote.instrument_name.endswith("95000-P")
        else quote
        for quote in all_joint_adversarial_chain(
            expiry=current_expiry(entry_at),
            observed_at=entry_at,
        )
    )
    observation = _observation(engine, entry_at, quotes=quotes)
    replacement = select_btc_0dte_condor(observation=observation, policy=policy)
    assert replacement.selected is not None
    assert replacement.selected.identity != case.selected_structure_id

    rejected, result = evaluate_shadow_entry(
        case,
        observation=observation,
        policy=policy,
        known_at=observation.known_at,
    )

    assert result.selected_structure_id == case.selected_structure_id
    assert result.status is ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED
    assert result.structure_blockers == ("SHORT_PUT_DELTA_OUTSIDE_POLICY",)
    assert rejected.position_id is None


def test_data_gap_preserves_position_and_cannot_create_exit_intent(policy, tmp_path) -> None:
    engine, case = _entered_case(policy, tmp_path)
    gap_at = case.entry_observed_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
    unknown_evidence = MarketContextEvidence.unknown()
    gap = _observation(engine, gap_at, evidence=unknown_evidence)

    updated, evaluation = monitor_shadow_position(
        case,
        observation=gap,
        policy=policy,
    )
    assert evaluation.observation_status is ObservationStatus.UNKNOWN
    assert evaluation.management_action is None
    assert updated.position_id == case.position_id
    assert updated.exit_intent is None
    assert updated.gap_observed


def test_latest_exit_freezes_responsibility_even_when_market_data_is_unknown(
    policy,
    tmp_path,
) -> None:
    engine, case = _entered_case(policy, tmp_path)
    expiry = current_expiry(case.entry_observed_at)
    latest_exit_at = expiry - timedelta(minutes=policy.lifecycle.latest_exit_minutes_to_expiry)
    gap = _observation(engine, latest_exit_at, evidence=MarketContextEvidence.unknown())

    updated, evaluation = monitor_shadow_position(case, observation=gap, policy=policy)

    assert evaluation.observation_status is ObservationStatus.UNKNOWN
    assert evaluation.management_action is PositionAction.EXIT_WHOLE_PRODUCT
    assert evaluation.known_triggers == ("LATEST_EXIT",)
    assert evaluation.reason is not None
    assert updated.gap_observed
    assert updated.position_state is PositionState.EXIT_INTENT_FROZEN
    assert updated.exit_intent is not None
    assert updated.exit_intent.reason == "LATEST_EXIT"
    assert updated.exit_intent.source == "DERIBIT_TIME_BOUNDARY"


def test_latest_exit_freezes_responsibility_when_one_frozen_leg_is_missing(
    policy,
    tmp_path,
) -> None:
    engine, case = _entered_case(policy, tmp_path)
    expiry = current_expiry(case.entry_observed_at)
    latest_exit_at = expiry - timedelta(minutes=policy.lifecycle.latest_exit_minutes_to_expiry)
    quotes = tuple(
        quote
        for quote in base_chain(expiry=expiry, observed_at=latest_exit_at)
        if not quote.instrument_name.endswith("95000-P")
    )
    incomplete = _observation(engine, latest_exit_at, quotes=quotes)
    assert not incomplete.data_health_blockers

    updated, evaluation = monitor_shadow_position(
        case,
        observation=incomplete,
        policy=policy,
    )

    assert evaluation.observation_status is ObservationStatus.UNKNOWN
    assert evaluation.management_action is PositionAction.EXIT_WHOLE_PRODUCT
    assert evaluation.known_triggers == ("LATEST_EXIT",)
    assert evaluation.reason == "SELECTED_STRUCTURE_QUOTES_MISSING"
    assert updated.position_state is PositionState.EXIT_INTENT_FROZEN
    assert updated.exit_intent is not None
    assert updated.exit_intent.reason == "LATEST_EXIT"


def test_latest_exit_can_freeze_from_deribit_time_when_no_market_cut_exists(
    policy,
    tmp_path,
) -> None:
    _engine, case = _entered_case(policy, tmp_path)
    expiry = current_expiry(case.entry_observed_at)
    latest_exit_at = expiry - timedelta(minutes=policy.lifecycle.latest_exit_minutes_to_expiry)
    gapped = replace(case, gap_observed=True)

    updated = freeze_latest_exit_on_time_boundary(
        gapped,
        known_at=latest_exit_at,
        policy=policy,
    )

    assert updated.position_state is PositionState.EXIT_INTENT_FROZEN
    assert updated.exit_intent is not None
    assert updated.exit_intent.reason == "LATEST_EXIT"
    assert updated.exit_intent.observed_at == latest_exit_at
    assert updated.exit_intent.known_at == latest_exit_at
    assert updated.exit_intent.source == "DERIBIT_TIME_BOUNDARY_WITHOUT_MARKET_CUT"


def test_latest_exit_responsibility_can_be_recovered_after_expiry(
    policy,
    tmp_path,
) -> None:
    _engine, case = _entered_case(policy, tmp_path)
    expiry = current_expiry(case.entry_observed_at)

    updated = freeze_latest_exit_on_time_boundary(
        replace(case, gap_observed=True),
        known_at=expiry + timedelta(minutes=5),
        policy=policy,
    )

    assert updated.exit_intent is not None
    assert updated.exit_intent.reason == "LATEST_EXIT"
    assert updated.exit_intent.observed_at == expiry - timedelta(
        minutes=policy.lifecycle.latest_exit_minutes_to_expiry
    )
    assert updated.exit_intent.known_at == expiry + timedelta(minutes=5)


def test_first_trigger_is_immutable_and_exit_requires_strictly_later_cut(
    policy,
    tmp_path,
) -> None:
    engine, case = _entered_case(policy, tmp_path)
    trigger_at = case.entry_observed_at + timedelta(
        seconds=policy.lifecycle.monitoring_cadence_seconds
    )
    trigger = _observation(engine, trigger_at, event=EventState.LIVE_EVENT)
    armed, monitor = monitor_shadow_position(case, observation=trigger, policy=policy)
    assert monitor.management_action is PositionAction.EXIT_WHOLE_PRODUCT
    assert armed.exit_intent is not None
    assert armed.exit_intent.reason == "EVENT_OR_SHOCK"

    with pytest.raises(ValueError, match="strictly later"):
        evaluate_shadow_exit(armed, observation=trigger, policy=policy)

    exit_at = trigger_at + timedelta(seconds=2)
    later = _observation(engine, exit_at)
    terminal, exit_evaluation = evaluate_shadow_exit(
        armed,
        observation=later,
        policy=policy,
    )
    assert exit_evaluation.terminal
    assert terminal.position_state is PositionState.TERMINAL
    assert terminal.exit_intent == armed.exit_intent
    assert terminal.outcome is not None
    assert terminal.outcome.terminal_method is TerminalMethod.WHOLE_PRODUCT_EXIT
    assert terminal.outcome.native_result_btc is not None
    assert terminal.outcome.shadow_model_id == "SYNTHETIC_FOUR_LEG_COMPONENT_BOOK_ESTIMATE_V1"
    assert terminal.outcome.eligibility.future_path_known.value is None
    assert terminal.outcome.eligibility.future_path_continuous.value is None
    assert terminal.outcome.eligibility.strategy_population_eligible.value is None
    projection = build_case_projection(terminal)
    assert projection["available"] is True
    eligibility = projection["eligibility"]
    assert isinstance(eligibility, list)
    assert len(eligibility) == 8
    assert "realized" not in json.dumps(projection).lower()


def test_close_depth_unknown_is_not_a_data_gap(policy, tmp_path) -> None:
    engine, case = _entered_case(policy, tmp_path)
    trigger_at = case.entry_observed_at + timedelta(
        seconds=policy.lifecycle.monitoring_cadence_seconds
    )
    armed, _ = monitor_shadow_position(
        case,
        observation=_observation(engine, trigger_at, event=EventState.LIVE_EVENT),
        policy=policy,
    )
    exit_at = trigger_at + timedelta(seconds=2)
    shallow = tuple(
        replace(quote, ask=(PriceLevel(quote.ask[0].price, Decimal("0.05")),))
        if quote.instrument_name.endswith("95000-P")
        else quote
        for quote in base_chain(expiry=current_expiry(exit_at), observed_at=exit_at)
    )
    unresolved, evaluation = evaluate_shadow_exit(
        armed,
        observation=_observation(engine, exit_at, quotes=shallow),
        policy=policy,
    )
    assert evaluation.observation_status is ObservationStatus.UNKNOWN
    assert not evaluation.terminal
    assert not unresolved.gap_observed
    assert unresolved.position_id == armed.position_id
    assert unresolved.exit_intent == armed.exit_intent


def test_unknown_exit_preserves_intent_then_official_settlement_can_terminalize(
    policy,
    tmp_path,
) -> None:
    engine, case = _entered_case(policy, tmp_path)
    trigger_at = case.entry_observed_at + timedelta(
        seconds=policy.lifecycle.monitoring_cadence_seconds
    )
    armed, _ = monitor_shadow_position(
        case,
        observation=_observation(engine, trigger_at, event=EventState.LIVE_EVENT),
        policy=policy,
    )
    gap_at = trigger_at + timedelta(seconds=1)
    gap = _observation(engine, gap_at, evidence=MarketContextEvidence.unknown())
    unresolved, evaluation = evaluate_shadow_exit(armed, observation=gap, policy=policy)
    assert not evaluation.terminal
    assert unresolved.position_id == armed.position_id
    assert unresolved.exit_intent == armed.exit_intent

    expiry = current_expiry(gap_at)
    terminal = settle_shadow_position(
        unresolved,
        settlement=ExpirySettlementFact(
            product_id=BTC.product_id,
            expiry=expiry,
            delivery_price_usd=Decimal("110000"),
            known_at=expiry,
            evidence_kind=SettlementEvidenceKind.DETERMINISTIC_ACCEPTANCE_FIXTURE,
            source_id="DETERMINISTIC_DELIVERY_FIXTURE",
            method_id="FIXED_DELIVERY_PRICE_V1",
        ),
        policy=policy,
    )
    assert terminal.position_state is PositionState.TERMINAL
    assert terminal.outcome is not None
    assert terminal.outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT
    assert terminal.outcome.eligibility.future_path_continuous.value is False
    assert terminal.outcome.eligibility.terminal_economics_evaluable.value is True


def test_expiry_uses_frozen_structure_and_requires_matching_settlement_fact(
    policy,
    tmp_path,
) -> None:
    engine, case = _entered_case(policy, tmp_path)
    expiry = current_expiry(case.entry_observed_at)
    at_expiry = _observation(engine, expiry)
    preserved, evaluation = monitor_shadow_position(
        case,
        observation=at_expiry,
        policy=policy,
    )
    assert evaluation.management_action is PositionAction.SETTLE_AT_EXPIRY
    assert preserved.position_id == case.position_id
    assert preserved.outcome is None

    wrong_expiry = expiry + timedelta(days=1)
    with pytest.raises(ValueError, match="expiry does not match"):
        settle_shadow_position(
            case,
            settlement=ExpirySettlementFact(
                product_id=BTC.product_id,
                expiry=wrong_expiry,
                delivery_price_usd=Decimal("110000"),
                known_at=wrong_expiry,
                evidence_kind=SettlementEvidenceKind.DETERMINISTIC_ACCEPTANCE_FIXTURE,
                source_id="DETERMINISTIC_DELIVERY_FIXTURE",
                method_id="FIXED_DELIVERY_PRICE_V1",
            ),
            policy=policy,
        )


def test_case_journal_is_idempotent_recovers_prefix_and_rejects_tampering(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    assert journal.append(case)
    assert not journal.append(case)
    entry_at = record.known_at + timedelta(seconds=30)
    entered, entry_result = engine.evaluate_entry(
        journal=journal,
        case=case,
        observation=_observation(engine, entry_at),
        known_at=entry_at,
    )
    assert journal.recover(case.identity) == entered
    assert journal.recover(case.identity).entry_reunderwriting == entry_result
    assert len(journal.read(case.identity)) == 2

    changed_result = replace(
        entry_result,
        known_at=entry_result.known_at + timedelta(microseconds=1),
    )
    changed_case = replace(
        entered,
        entry_known_at=changed_result.known_at,
        entry_reunderwriting_json=json.dumps(
            changed_result.as_object(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    with pytest.raises(ValueError, match="final Entry truth"):
        journal.append(changed_case)

    path = journal.path_for(case.identity)
    with path.open("ab") as handle:
        handle.write(b'{"sequence":2')
    assert journal.recover(case.identity) == entered
    monitor_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
    monitored, _ = engine.monitor_position(
        journal=journal,
        case=entered,
        observation=_observation(engine, monitor_at),
    )
    assert journal.recover(case.identity) == monitored
    assert len(journal.read(case.identity)) == 3

    records = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(records[-1])
    tampered["previous_snapshot_id"] = "sha256:" + "0" * 64
    records[-1] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="chain is broken"):
        journal.recover(case.identity)


def test_case_journal_finalizes_same_observation_and_recovers_truncated_tail(
    policy,
    tmp_path,
) -> None:
    engine, record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    journal.append(case)
    observed_at = record.known_at + timedelta(seconds=30)
    quotes = base_chain(expiry=current_expiry(observed_at), observed_at=observed_at)[:-1]
    observation = _observation(engine, observed_at, quotes=quotes)
    provisional, _ = engine.evaluate_entry(
        journal=journal,
        case=case,
        observation=observation,
        known_at=observation.known_at,
    )
    terminal, _ = engine.evaluate_entry(
        journal=journal,
        case=provisional,
        observation=observation,
        known_at=case.entry_deadline,
    )
    assert terminal.outcome is not None
    assert len(journal.read(case.identity)) == 3

    path = journal.path_for(case.identity)
    with path.open("ab") as handle:
        handle.write(b'{"sequence":3')
    assert journal.recover(case.identity) == terminal
    assert path.read_bytes().endswith(b"\n")
    assert len(journal.read(case.identity)) == 3


def test_case_journal_rejects_mutation_of_frozen_case_facts(policy, tmp_path) -> None:
    _engine, _record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    journal.append(case)
    with pytest.raises(ValueError, match="frozen TradeCase facts"):
        journal.append(replace(case, entry_deadline=case.entry_deadline + timedelta(seconds=1)))


def test_case_journal_recover_all_enumerates_every_case_and_repairs_each_tail(
    policy,
    tmp_path,
) -> None:
    _engine, _record, first = _candidate(policy, tmp_path)
    _engine, _record, second = _candidate(
        policy,
        tmp_path,
        decision_at=datetime(2026, 8, 12, 18, 22, tzinfo=UTC),
    )
    journal = CaseJournal(tmp_path / "case-journal")
    journal.append(first)
    journal.append(second)
    for case in (first, second):
        with journal.path_for(case.identity).open("ab") as handle:
            handle.write(b'{"sequence":1')

    assert journal.recover_all() == tuple(sorted((first, second), key=lambda case: case.identity))
    assert all(
        journal.path_for(case.identity).read_bytes().endswith(b"\n") for case in (first, second)
    )


def test_case_journal_recovery_discards_complete_json_without_commit_newline(
    policy,
    tmp_path,
) -> None:
    _engine, _record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    journal.append(case)
    path = journal.path_for(case.identity)
    path.write_bytes(path.read_bytes().removesuffix(b"\n"))

    with pytest.raises(ValueError, match="unterminated write"):
        journal.read(case.identity)

    before = path.read_bytes()
    with pytest.raises(ValueError, match="no accepted snapshot"):
        journal.recover_all()
    assert path.read_bytes() == before

    assert journal.recover_all(recoverable_empty_case_ids=frozenset({case.identity})) == ()
    assert not path.exists()


def test_case_journal_recovery_rejects_unowned_empty_case_file(policy, tmp_path) -> None:
    journal = CaseJournal(tmp_path / "case-journal")
    foreign = journal.path_for(f"sha256:{'0' * 64}")
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"")

    with pytest.raises(ValueError, match="no accepted snapshot"):
        journal.recover_all()

    assert foreign.read_bytes() == b""


def test_case_journal_recover_all_rejects_foreign_case_directory_entries(
    policy,
    tmp_path,
) -> None:
    _engine, _record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    journal.append(case)
    case_path = journal.path_for(case.identity)
    with case_path.open("ab") as handle:
        handle.write(b'{"sequence":1')
    before = case_path.read_bytes()
    foreign = case_path.parent / "zz-foreign"
    foreign.write_text("foreign", encoding="utf-8")

    with pytest.raises(ValueError, match="foreign entry: zz-foreign"):
        journal.recover_all()
    assert case_path.read_bytes() == before


def test_case_journal_recover_all_rejects_filename_identity_mismatch(
    policy,
    tmp_path,
) -> None:
    _engine, _record, case = _candidate(policy, tmp_path)
    journal = CaseJournal(tmp_path / "case-journal")
    original = journal.path_for(case.identity)
    journal.append(case)
    mismatched = original.with_name(f"{'0' * 64}.jsonl")
    original.rename(mismatched)

    with pytest.raises(ValueError, match="contains a different TradeCase"):
        journal.recover_all()


def test_window_outcome_is_distinct_append_once_population(policy, tmp_path) -> None:
    _engine, record, _case = _candidate(policy, tmp_path)
    ledger = ObservationLedger(tmp_path / "outcomes")
    ledger.append(record)
    horizon = record.window.ends_at + timedelta(hours=1)
    outcome = WindowOutcome(
        decision_window_id=record.window.identity,
        horizon_starts_at=record.window.ends_at,
        horizon_ends_at=horizon,
        known_at=horizon,
        future_path_known=True,
        future_path_continuous=True,
        expiry_settlement=None,
        future_path=FuturePathSummary(
            source_id="DETERMINISTIC_PUBLIC_PATH_FIXTURE",
            method_id="WINDOW_TO_PLUS_ONE_HOUR_SUMMARY_V1",
            starts_at=record.window.ends_at,
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
            decision_evaluable=True,
            future_path_known=True,
            future_path_continuous=True,
        ),
    )
    assert ledger.append_outcome(outcome)
    assert not ledger.append_outcome(outcome)
    assert ledger.read_outcomes() == (outcome,)
    assert ledger.read() == (record,)
    summary = ledger.summarize_outcomes(expected_windows=(record.window,))
    assert summary.denominator == summary.recorded == 1
    assert summary.future_path_known == summary.continuous == 1
    assert summary.strategy_population_eligible == 1

    orphan = ObservationLedger(tmp_path / "orphan")
    with pytest.raises(ValueError, match="matching DecisionRecord"):
        orphan.append_outcome(outcome)
