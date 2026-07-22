"""Scenario-free finite-risk insurance assessment."""

from __future__ import annotations

from decimal import Decimal

from market_tape import OptionKind
from options_domain import VerticalQuote, enumerate_verticals

from short_vol_radar.contracts import (
    BreakoutDirection,
    DecisionFrame,
    InsuranceAssessment,
    PredicateResult,
    RadarAction,
    RadarDecision,
    RadarPolicy,
)
from short_vol_radar.risk import estimate_path_risk


def _stress_intrinsic_payout(
    candidate: VerticalQuote,
    reference_price: Decimal,
    adverse_move: Decimal,
) -> Decimal:
    stress_price = (
        reference_price * (Decimal("1") + adverse_move)
        if candidate.sold_side is OptionKind.CALL
        else reference_price * (Decimal("1") - adverse_move)
    )
    intrinsic = (
        max(Decimal("0"), stress_price - candidate.short_leg.strike)
        if candidate.sold_side is OptionKind.CALL
        else max(Decimal("0"), candidate.short_leg.strike - stress_price)
    )
    return min(candidate.width, intrinsic) * candidate.quantity * candidate.contract_size


def _residual_time_value_floor(
    candidate: VerticalQuote,
    horizon_seconds: int,
) -> Decimal:
    remaining_seconds = max(candidate.tte_seconds - horizon_seconds, 0)
    residual_fraction = (
        (Decimal(remaining_seconds) / Decimal(candidate.tte_seconds)).sqrt()
        if candidate.tte_seconds > 0
        else Decimal("0")
    )
    return candidate.immediate_close_usdc * residual_fraction


def _assessment(
    frame: DecisionFrame,
    candidate: VerticalQuote,
    horizon_seconds: int,
    policy: RadarPolicy,
) -> InsuranceAssessment | None:
    if frame.reference_price is None:
        return None
    risk = estimate_path_risk(frame, horizon_seconds, policy=policy)
    adverse_move = risk.adverse_move(candidate.sold_side)
    if adverse_move is None:
        return None
    safety_multiple = (
        candidate.short_distance_fraction / adverse_move
        if adverse_move > 0
        else Decimal("Infinity")
    )
    intrinsic_reserve = _stress_intrinsic_payout(
        candidate,
        frame.reference_price,
        adverse_move,
    )
    time_value_floor = _residual_time_value_floor(candidate, horizon_seconds)
    claim_reserve = max(intrinsic_reserve, time_value_floor)
    liquidity_reserve = candidate.max_loss_usdc * policy.liquidity_reserve_fraction
    method_reserve = candidate.max_loss_usdc * policy.method_uncertainty_reserve_fraction
    conservative_margin = (
        candidate.gross_credit_usdc
        - candidate.entry_fee_usdc
        - candidate.close_fee_usdc
        - claim_reserve
        - liquidity_reserve
        - method_reserve
    )
    same_side_breakout = (
        candidate.sold_side is OptionKind.CALL and risk.breakout is BreakoutDirection.UP
    ) or (candidate.sold_side is OptionKind.PUT and risk.breakout is BreakoutDirection.DOWN)
    flow_score = risk.directional_flow_score or Decimal("0")
    same_side_flow_veto = (
        flow_score >= policy.directional_flow_veto
        if candidate.sold_side is OptionKind.CALL
        else flow_score <= -policy.directional_flow_veto
    )
    premium_to_max_loss = candidate.net_entry_premium_usdc / candidate.max_loss_usdc
    predicates = (
        PredicateResult(
            "FRAME_COMPLETE",
            frame.complete,
            str(frame.completeness_reasons),
        ),
        PredicateResult(
            "RISK_COMPLETE",
            risk.complete,
            str(risk.incomplete_reasons),
        ),
        PredicateResult(
            "TTE_BUFFER",
            candidate.tte_seconds >= horizon_seconds + policy.settlement_buffer_seconds,
            f"tte={candidate.tte_seconds} horizon={horizon_seconds}",
        ),
        PredicateResult(
            "DEPTH",
            candidate.executable_depth >= policy.quantity,
            f"depth={candidate.executable_depth}",
        ),
        PredicateResult(
            "CREDIT_TO_FRICTION",
            candidate.credit_to_friction_ratio is None
            or candidate.credit_to_friction_ratio >= policy.minimum_credit_to_friction,
            str(candidate.credit_to_friction_ratio),
        ),
        PredicateResult(
            "SAFETY_MULTIPLE",
            safety_multiple >= policy.minimum_safety_multiple,
            str(safety_multiple),
        ),
        PredicateResult(
            "PREMIUM_TO_MAX_LOSS",
            premium_to_max_loss >= policy.minimum_net_premium_to_max_loss,
            str(premium_to_max_loss),
        ),
        PredicateResult(
            "NO_SAME_SIDE_BREAKOUT",
            not same_side_breakout,
            risk.breakout.value,
        ),
        PredicateResult(
            "NO_SAME_SIDE_FLOW_VETO",
            not same_side_flow_veto,
            str(flow_score),
        ),
        PredicateResult(
            "NO_PLATFORM_LOCK",
            frame.platform_locked is False,
            str(frame.platform_state),
        ),
        PredicateResult(
            "NO_SCHEDULED_BLOCK",
            frame.scheduled_block is None,
            str(frame.scheduled_block),
        ),
        PredicateResult(
            "POSITIVE_CONSERVATIVE_MARGIN",
            conservative_margin > 0,
            str(conservative_margin),
        ),
    )
    return InsuranceAssessment(
        candidate=candidate,
        risk=risk,
        adverse_move_fraction=adverse_move,
        safety_multiple=safety_multiple,
        stress_intrinsic_payout_usdc=intrinsic_reserve,
        residual_time_value_floor_usdc=time_value_floor,
        claim_reserve_usdc=claim_reserve,
        liquidity_reserve_usdc=liquidity_reserve,
        method_uncertainty_reserve_usdc=method_reserve,
        conservative_margin_usdc=conservative_margin,
        predicates=predicates,
    )


def _rank(item: InsuranceAssessment) -> tuple[object, ...]:
    return (
        -item.conservative_margin_usdc,
        -item.safety_multiple,
        -(item.candidate.net_entry_premium_usdc - item.candidate.round_trip_friction_usdc),
        item.candidate.max_loss_usdc,
        -item.candidate.executable_depth,
        item.risk.horizon_seconds,
        item.candidate.candidate_id,
    )


def evaluate_radar(
    frame: DecisionFrame,
    *,
    policy: RadarPolicy | None = None,
) -> RadarDecision:
    active = policy or RadarPolicy()
    if frame.reference_price is None or frame.index_price is None:
        return RadarDecision(
            action=RadarAction.ABSTAIN,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=None,
            horizon_seconds=None,
            assessment=None,
            reason="REFERENCE_OR_INDEX_UNKNOWN",
        )
    candidates = enumerate_verticals(
        frame_capture_seq=frame.as_of_capture_seq,
        reference_price=frame.reference_price,
        index_price=frame.index_price,
        option_quotes=frame.option_quotes,
        combo_quotes=frame.combo_quotes,
        quantity=active.quantity,
        minimum_tte_seconds=active.minimum_tte_seconds,
        maximum_tte_seconds=active.maximum_tte_seconds,
    )
    if not candidates:
        return RadarDecision(
            action=RadarAction.ABSTAIN,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=None,
            horizon_seconds=None,
            assessment=None,
            reason="NO_EXECUTABLE_DEFINED_RISK_STRUCTURE",
        )
    assessments: list[InsuranceAssessment] = []
    for candidate in candidates:
        for horizon_seconds in active.horizons_seconds:
            assessment = _assessment(
                frame,
                candidate,
                horizon_seconds,
                active,
            )
            if assessment is not None:
                assessments.append(assessment)
    passed = tuple(item for item in assessments if item.all_passed)
    if passed:
        selected = sorted(passed, key=_rank)[0]
        return RadarDecision(
            action=RadarAction.RESEARCH_CANDIDATE,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=selected.candidate.candidate_id,
            horizon_seconds=selected.risk.horizon_seconds,
            assessment=selected,
            reason="CONSERVATIVE_INSURANCE_MARGIN_POSITIVE",
        )
    if assessments:
        selected = sorted(assessments, key=_rank)[0]
        failed = ",".join(item.name for item in selected.predicates if not item.passed)
        return RadarDecision(
            action=RadarAction.WATCH,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=selected.candidate.candidate_id,
            horizon_seconds=selected.risk.horizon_seconds,
            assessment=selected,
            reason=f"FAILED_PREDICATES:{failed}",
        )
    return RadarDecision(
        action=RadarAction.ABSTAIN,
        frame_capture_seq=frame.as_of_capture_seq,
        frame_digest=frame.digest,
        selected_candidate_id=None,
        horizon_seconds=None,
        assessment=None,
        reason="PATH_RISK_UNKNOWN",
    )
