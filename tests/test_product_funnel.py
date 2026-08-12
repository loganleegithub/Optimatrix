from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from optimatrix.engine import ShadowEngine
from optimatrix.market import MarketContextEvidence
from optimatrix.product_funnel import FunnelStageName, FunnelStageStatus, project_product_funnel
from optimatrix.radar import Decision
from optimatrix.scenarios import base_chain, current_expiry, market_context


def test_candidate_reaches_the_entry_attempt_node(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(now),
    )
    funnel = project_product_funnel(decision, policy_identity=policy.identity)
    assert funnel.current_node is FunnelStageName.ENTRY_ATTEMPT_SELECTED
    assert funnel.primary_blocker is None
    assert all(stage.status is FunnelStageStatus.PASSED for stage in funnel.stages[:7])
    assert funnel.stages[7].status is FunnelStageStatus.NOT_REACHED
    assert funnel.stages[7].denominator == 1
    assert all(stage.status is FunnelStageStatus.NOT_REACHED for stage in funnel.stages[7:])


def test_gamma_rejection_stops_at_the_earliest_risk_stage(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(
            now,
            implied_variance=Decimal("0.0032"),
            rv_acceleration=Decimal("0.9"),
            jump_share=Decimal("0.9"),
        ),
    )
    funnel = project_product_funnel(decision, policy_identity=policy.identity)
    assert funnel.current_node is FunnelStageName.GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE
    assert funnel.primary_blocker == "RV_ACCELERATION_TOO_HIGH"
    failed = funnel.stages[3]
    assert failed.denominator == 1 and failed.numerator == 0
    assert all(stage.status is FunnelStageStatus.NOT_REACHED for stage in funnel.stages[4:])


def test_no_structure_is_counted_once_not_as_independent_strikes(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=(),
        context=market_context(now),
    )
    funnel = project_product_funnel(decision, policy_identity=policy.identity)
    assert funnel.current_node is FunnelStageName.TWO_SIDED_STRUCTURE_EVALUABLE
    assert funnel.primary_blocker == "NO_CURRENT_SESSION_QUOTES"
    assert funnel.stages[4].denominator == 1
    assert funnel.stages[4].numerator == 0


def test_unknown_context_consumes_the_unit_without_becoming_a_negative_decision(
    policy,
    tmp_path,
) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(
            now,
            evidence=MarketContextEvidence.unknown(),
        ),
    )
    funnel = project_product_funnel(decision, policy_identity=policy.identity)

    assert decision.decision is Decision.UNKNOWN
    assert funnel.current_node is FunnelStageName.MARKET_CONTEXT_KNOWN
    assert funnel.primary_blocker == "MARKET_CONTEXT_EVIDENCE_NOT_BOUND"
    assert funnel.stages[1].status is FunnelStageStatus.UNKNOWN
    assert funnel.stages[1].denominator == 1
    assert funnel.stages[1].numerator == 0
    assert all(stage.status is FunnelStageStatus.NOT_REACHED for stage in funnel.stages[2:])


def test_lifecycle_truth_can_complete_the_same_canonical_funnel(policy, tmp_path) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    decision = ShadowEngine(policy=policy, case_root=tmp_path).evaluate(
        quotes=base_chain(expiry=current_expiry(now), observed_at=now),
        context=market_context(now),
    )
    funnel = project_product_funnel(
        decision,
        policy_identity=policy.identity,
        decision_case_opened=True,
        entry_result_known=True,
        decision_case_outcome_known=True,
    )
    assert funnel.current_node is FunnelStageName.DECISION_CASE_OUTCOME_KNOWN
    assert funnel.primary_blocker is None
    assert all(stage.status is FunnelStageStatus.PASSED for stage in funnel.stages)
