from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from optimatrix.engine import ShadowEngine
from optimatrix.market import PriceLevel
from optimatrix.product_funnel import FunnelStageName, FunnelStageStatus, project_product_funnel
from optimatrix.radar import Decision
from optimatrix.scenarios import (
    all_joint_adversarial_chain,
    base_chain,
    current_expiry,
    market_context,
)
from optimatrix.structure import select_iron_condor


def test_all_joint_search_finds_the_only_hard_eligible_condor(policy) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    context = market_context(now)
    selection = select_iron_condor(
        quotes=all_joint_adversarial_chain(
            expiry=current_expiry(now),
            observed_at=now,
        ),
        context=context,
        policy=policy,
    )

    assert selection.considered_put_verticals == 4
    assert selection.considered_call_verticals == 1
    assert selection.considered_condors == 4
    assert selection.hard_eligible_condors == 1
    assert selection.selected is not None
    assert selection.selected.long_put.instrument_name == "BTC-X-93000-P"
    assert selection.selected.net_delta == 0


def test_short_buyback_depth_is_a_route_gate_not_a_structure_absence(
    policy,
    tmp_path,
) -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    quotes = list(base_chain(expiry=current_expiry(now), observed_at=now))
    short_put = quotes[1]
    quotes[1] = replace(
        short_put,
        ask=(PriceLevel(short_put.ask[0].price, Decimal("0.05")),),
    )
    engine = ShadowEngine(policy=policy, case_root=tmp_path)
    decision = engine.evaluate(quotes=tuple(quotes), context=market_context(now))
    funnel = project_product_funnel(decision, policy_identity=policy.identity)

    assert decision.decision is Decision.ABSTAIN
    assert decision.structure is None
    assert "NO_JOINT_CANDIDATE_PASSES_HARD_UNDERWRITING" in decision.blockers
    assert "PUT_SHORT_BUYBACK_DEPTH_INSUFFICIENT" in decision.blockers
    structure_stage = funnel.stages[4]
    route_stage = funnel.stages[5]
    assert structure_stage.name is FunnelStageName.TWO_SIDED_STRUCTURE_EVALUABLE
    assert structure_stage.status is FunnelStageStatus.PASSED
    assert route_stage.name is FunnelStageName.ENTRY_ROUTE_EVALUABLE
    assert route_stage.status is FunnelStageStatus.BLOCKED
    assert funnel.primary_blocker == "NO_JOINT_CANDIDATE_PASSES_HARD_UNDERWRITING"
