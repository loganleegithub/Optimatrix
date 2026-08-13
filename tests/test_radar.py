from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from optimatrix.decision import DecisionRecord, DecisionResult
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.market import MarketContextEvidence
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.risk import AllocationResult, ShadowCapacity
from optimatrix.scenarios import (
    all_joint_adversarial_chain,
    base_chain,
    current_expiry,
    market_context,
)


def _assessment(policy, tmp_path, *, context, quotes, capacity=True):
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item
        for item in engine.decision_windows(at=context.now)
        if item.starts_at <= context.now < item.ends_at
    )
    observation = engine.capture_observation(quotes=quotes, context=context)
    shadow_capacity = (
        ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        )
        if capacity
        else None
    )
    return engine.assess_window(
        ledger=ObservationLedger(tmp_path),
        window=window,
        observation=observation,
        capacity=shadow_capacity,
        known_at=window.input_deadline,
    )


def test_healthy_whole_product_with_capacity_is_candidate(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    assessment = _assessment(
        policy,
        tmp_path,
        context=market_context(at),
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
    )
    assert assessment.record.result is DecisionResult.CANDIDATE
    assert assessment.selection is not None and assessment.selection.selected is not None
    assert assessment.allocation is not None
    assert assessment.allocation.result is AllocationResult.AVAILABLE
    assert assessment.record.selected_structure is not None
    assert (
        assessment.record.selected_structure["candidate_id"]
        == assessment.record.selected_structure_id
    )
    assert assessment.record.risk_allocation is not None
    assert (
        assessment.record.risk_allocation["allocation_id"] == assessment.record.risk_allocation_id
    )
    restored = ObservationLedger(tmp_path).read()
    assert restored == (assessment.record,)


def test_embedded_observation_replays_same_policy_to_same_decision(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    original = _assessment(
        policy,
        tmp_path / "original",
        context=market_context(at),
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
    )
    restored = DecisionRecord.from_object(original.record.as_object())
    assert restored.observation is not None

    engine = Btc0DteShortVolEngine(policy=policy)
    replay = engine.assess_window(
        ledger=ObservationLedger(tmp_path / "replay"),
        window=restored.window,
        observation=restored.observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=restored.window.market_session_id,
            known_at=restored.window.input_deadline,
        ),
        known_at=restored.window.input_deadline,
    )

    assert replay.record.result is original.record.result
    assert replay.record.blockers == original.record.blockers
    assert replay.record.selected_structure == original.record.selected_structure
    assert replay.record.risk_allocation == original.record.risk_allocation
    assert replay.record.identity == original.record.identity


def test_delivery_stress_uses_actual_inverse_condor_payoff(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    assessment = _assessment(
        policy,
        tmp_path,
        context=market_context(at),
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
    )
    assert assessment.allocation is not None
    low, center, high = assessment.allocation.delivery_stress
    assert low.delivery_price_usd == Decimal("50000")
    assert center.delivery_price_usd == Decimal("100000")
    assert high.delivery_price_usd == Decimal("200000")
    assert center.contractual_payoff_usd == 0
    assert low.contractual_payoff_usd == high.contractual_payoff_usd == Decimal("200")
    assert low.contractual_payoff_native != high.contractual_payoff_native


def test_rerun_time_does_not_change_window_record_identity(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item for item in engine.decision_windows(at=at) if item.starts_at <= at < item.ends_at
    )
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        context=market_context(at),
    )
    capacity = ShadowCapacity.empty(
        channel_id=policy.channel_id,
        market_session_id=window.market_session_id,
        known_at=window.input_deadline,
    )
    ledger = ObservationLedger(tmp_path)
    first = engine.assess_window(
        ledger=ledger,
        window=window,
        observation=observation,
        capacity=capacity,
        known_at=window.input_deadline,
    )
    second = engine.assess_window(
        ledger=ledger,
        window=window,
        observation=observation,
        capacity=capacity,
        known_at=window.input_deadline + timedelta(minutes=10),
    )
    assert first.record == second.record
    assert len(ledger.read()) == 1


def test_decision_record_freezes_explainable_bounded_alternatives(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    quotes = all_joint_adversarial_chain(expiry=current_expiry(at), observed_at=at)
    assessment = _assessment(
        policy,
        tmp_path,
        context=market_context(
            at,
            book_names=tuple(quote.instrument_name for quote in quotes),
        ),
        quotes=quotes,
    )
    structure = assessment.record.selected_structure
    assert structure is not None
    assert isinstance(structure["ranking_method_id"], str)
    assert isinstance(structure["rank_evidence"], dict)
    alternatives = structure["retained_alternatives"]
    assert isinstance(alternatives, list)
    assert alternatives
    first = alternatives[0]
    assert isinstance(first, dict)
    assert set(first) == {"candidate_id", "legs", "option_amount", "rank_evidence"}
    assert len(first["legs"]) == 4


def test_unknown_data_skips_structure_and_is_not_abstain(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    context = market_context(at, evidence=MarketContextEvidence.unknown())
    assessment = _assessment(
        policy,
        tmp_path,
        context=context,
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
    )
    assert assessment.record.result is DecisionResult.UNKNOWN
    assert assessment.selection is None
    assert assessment.allocation is None


def test_known_path_risk_abstains_before_structure(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    assessment = _assessment(
        policy,
        tmp_path,
        context=market_context(at, rv_acceleration=Decimal("0.9")),
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
    )
    assert assessment.record.result is DecisionResult.ABSTAIN
    assert "RV_ACCELERATION_TOO_HIGH" in assessment.record.blockers
    assert assessment.selection is None


def test_missing_shadow_capacity_is_unknown_not_candidate(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    assessment = _assessment(
        policy,
        tmp_path,
        context=market_context(at),
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        capacity=False,
    )
    assert assessment.record.result is DecisionResult.UNKNOWN
    assert assessment.record.blockers == ("SHADOW_CAPACITY_UNKNOWN",)
    assert assessment.selection is not None
    assert assessment.allocation is not None


def test_exhausted_shadow_capacity_is_known_abstain(policy, tmp_path) -> None:
    at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item for item in engine.decision_windows(at=at) if item.starts_at <= at < item.ends_at
    )
    observation = engine.capture_observation(
        quotes=base_chain(expiry=current_expiry(at), observed_at=at),
        context=market_context(at),
    )
    capacity = ShadowCapacity(
        channel_id=policy.channel_id,
        market_session_id=window.market_session_id,
        contractual_payoff_used_usd=policy.risk.maximum_session_contractual_payoff_usd,
        open_position_count=0,
        known_at=window.input_deadline,
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(tmp_path),
        window=window,
        observation=observation,
        capacity=capacity,
        known_at=window.input_deadline,
    )
    assert assessment.record.result is DecisionResult.ABSTAIN
    assert assessment.record.blockers == ("SESSION_SHADOW_BUDGET_EXCEEDED",)
    assert assessment.allocation is not None
    assert assessment.allocation.session_remaining_after_usd == 0
