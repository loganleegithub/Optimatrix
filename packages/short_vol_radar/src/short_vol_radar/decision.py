"""Scenario-free finite-risk insurance assessment."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from market_tape import OptionKind, canonical_digest
from options_domain import VerticalQuote, enumerate_verticals

from short_vol_radar.contracts import (
    BreakoutDirection,
    CatalogReadiness,
    DecisionEvaluation,
    DecisionFrame,
    DecisionInputContract,
    DecisionReadiness,
    InsuranceAssessment,
    PredicateResult,
    QuoteReadiness,
    RadarAction,
    RadarDecision,
    RadarPolicy,
    RequiredWindowReadiness,
    ScheduleReadiness,
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
) -> tuple[InsuranceAssessment | None, tuple[str, ...]]:
    if frame.reference_price is None:
        return None, ("REFERENCE_PRICE_UNKNOWN",)
    risk = estimate_path_risk(frame, horizon_seconds, policy=policy)
    adverse_move = risk.adverse_move(candidate.sold_side)
    if adverse_move is None:
        return None, risk.incomplete_reasons or ("ADVERSE_MOVE_UNKNOWN",)
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
            frame.scheduled_block_observed
            and frame.scheduled_block_current
            and frame.scheduled_block is None,
            (str(frame.scheduled_block) if frame.scheduled_block_current else "UNKNOWN"),
        ),
        PredicateResult(
            "POSITIVE_CONSERVATIVE_MARGIN",
            conservative_margin > 0,
            str(conservative_margin),
        ),
    )
    return (
        InsuranceAssessment(
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
        ),
        (),
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


def build_decision_readiness(
    frame: DecisionFrame,
    *,
    input_contract: DecisionInputContract | None = None,
) -> DecisionReadiness:
    active = input_contract or DecisionInputContract()
    catalog_reasons = tuple(
        item for item in frame.completeness_reasons if item.startswith("CATALOG_")
    )
    schedule_reasons = tuple(
        item for item in frame.completeness_reasons if item.startswith("SCHEDULED_BLOCK")
    )
    quote_reason_names = {
        "INSUFFICIENT_FRESH_OPTION_QUOTES",
        "OPTION_UNIVERSE_QUOTES_INCOMPLETE",
        "OPTION_UNIVERSE_QUOTES_STALE",
        "OPTION_DEPTH_UNKNOWN",
    }
    quote_reasons = tuple(item for item in frame.completeness_reasons if item in quote_reason_names)
    fresh_quote_count = sum(item.fresh for item in frame.option_quotes)
    depth_unknown_quote_count = sum(
        (item.bid is not None and item.bid_amount is None)
        or (item.ask is not None and item.ask_amount is None)
        for item in frame.option_quotes
    )
    schedule_state = (
        "UNKNOWN"
        if not frame.scheduled_block_current
        else "BLOCKED"
        if frame.scheduled_block is not None
        else "CLEAR"
    )
    return DecisionReadiness(
        frame_complete=frame.complete,
        frame_incomplete_reasons=frame.completeness_reasons,
        required_windows=tuple(
            RequiredWindowReadiness(
                requested_seconds=item.coverage.requested_seconds,
                price_complete=item.coverage.price_complete,
                trade_complete=item.coverage.trade_complete,
                gap_contaminated=item.coverage.gap_contaminated,
                reconnect_contaminated=item.coverage.reconnect_contaminated,
                incomplete_reasons=item.coverage.incomplete_reasons,
            )
            for item in frame.windows
        ),
        catalog=CatalogReadiness(
            complete=frame.catalog_generation_complete and not catalog_reasons,
            scope=frame.catalog_scope,
            snapshot_capture_seq=frame.catalog_snapshot_capture_seq,
            source_at=frame.catalog_source_at,
            age_ms=frame.catalog_age_ms,
            instrument_count=frame.catalog_instrument_count,
            names_digest=frame.catalog_instrument_names_digest,
            generation_id=frame.catalog_generation_id,
            metadata_set_digest=frame.catalog_metadata_set_digest,
            instrument_source_capture_seqs=frame.catalog_instrument_source_capture_seqs,
            incomplete_reasons=catalog_reasons,
        ),
        schedule=ScheduleReadiness(
            complete=frame.scheduled_block_observed and frame.scheduled_block_current,
            observed=frame.scheduled_block_observed,
            current=frame.scheduled_block_current,
            source_capture_seq=frame.scheduled_block_source_capture_seq,
            source_id=frame.scheduled_block_source_id,
            valid_from=frame.scheduled_block_valid_from,
            valid_until=frame.scheduled_block_valid_until,
            state=schedule_state,
            label=frame.scheduled_block,
            incomplete_reasons=schedule_reasons,
        ),
        quotes=QuoteReadiness(
            complete=not quote_reasons,
            option_quote_count=len(frame.option_quotes),
            fresh_quote_count=fresh_quote_count,
            stale_quote_count=len(frame.option_quotes) - fresh_quote_count,
            depth_unknown_quote_count=depth_unknown_quote_count,
            minimum_fresh_quote_count=active.minimum_fresh_option_quotes,
            incomplete_reasons=quote_reasons,
        ),
    )


def evaluate_radar_evidence(
    frame: DecisionFrame,
    *,
    policy: RadarPolicy | None = None,
) -> DecisionEvaluation:
    active = policy or RadarPolicy()
    candidates: tuple[VerticalQuote, ...] = ()
    assessments: list[InsuranceAssessment] = []
    unavailable_reasons: Counter[str] = Counter()
    if frame.reference_price is None or frame.index_price is None:
        decision = RadarDecision(
            action=RadarAction.ABSTAIN,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=None,
            horizon_seconds=None,
            assessment=None,
            reason="REFERENCE_OR_INDEX_UNKNOWN",
        )
    else:
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
        for candidate in candidates:
            for horizon_seconds in active.horizons_seconds:
                assessment, reasons = _assessment(
                    frame,
                    candidate,
                    horizon_seconds,
                    active,
                )
                if assessment is not None:
                    assessments.append(assessment)
                else:
                    unavailable_reasons.update(reasons)
    if frame.reference_price is not None and frame.index_price is not None and not candidates:
        decision = RadarDecision(
            action=RadarAction.ABSTAIN,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=None,
            horizon_seconds=None,
            assessment=None,
            reason="NO_EXECUTABLE_DEFINED_RISK_STRUCTURE",
        )
    passed = tuple(item for item in assessments if item.all_passed)
    if passed:
        selected = sorted(passed, key=_rank)[0]
        decision = RadarDecision(
            action=RadarAction.RESEARCH_CANDIDATE,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=selected.candidate.candidate_id,
            horizon_seconds=selected.risk.horizon_seconds,
            assessment=selected,
            reason="CONSERVATIVE_INSURANCE_MARGIN_POSITIVE",
        )
    elif assessments:
        selected = sorted(assessments, key=_rank)[0]
        failed = ",".join(item.name for item in selected.predicates if not item.passed)
        decision = RadarDecision(
            action=RadarAction.WATCH,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=selected.candidate.candidate_id,
            horizon_seconds=selected.risk.horizon_seconds,
            assessment=selected,
            reason=f"FAILED_PREDICATES:{failed}",
        )
    elif candidates:
        decision = RadarDecision(
            action=RadarAction.ABSTAIN,
            frame_capture_seq=frame.as_of_capture_seq,
            frame_digest=frame.digest,
            selected_candidate_id=None,
            horizon_seconds=None,
            assessment=None,
            reason="PATH_RISK_UNKNOWN",
        )
    failures = Counter(
        predicate.name
        for assessment in assessments
        for predicate in assessment.predicates
        if not predicate.passed
    )
    return DecisionEvaluation(
        decision=decision,
        option_quote_count=len(frame.option_quotes),
        option_quote_set_digest=canonical_digest(frame.option_quotes),
        executable_structure_count=len(candidates),
        structure_set_digest=canonical_digest(candidates),
        assessment_opportunity_count=len(candidates) * len(active.horizons_seconds),
        assessment_unavailable_count=(
            len(candidates) * len(active.horizons_seconds) - len(assessments)
        ),
        assessment_unavailable_reason_counts=tuple(sorted(unavailable_reasons.items())),
        assessment_count=len(assessments),
        assessment_set_digest=canonical_digest(tuple(assessments)),
        passed_assessment_count=len(passed),
        predicate_failure_counts=tuple(sorted(failures.items())),
    )


def evaluate_radar(
    frame: DecisionFrame,
    *,
    policy: RadarPolicy | None = None,
) -> RadarDecision:
    return evaluate_radar_evidence(frame, policy=policy).decision
