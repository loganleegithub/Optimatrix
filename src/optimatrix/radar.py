from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from optimatrix.identity import canonical_identity
from optimatrix.market import (
    BreakoutState,
    EventState,
    MarketContext,
    MarketContextKnowledge,
    OptionQuote,
)
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.session import DeribitSession, SessionPhase
from optimatrix.structure import IronCondorCandidate, StructureSelection, select_iron_condor


class Decision(StrEnum):
    UNKNOWN = "UNKNOWN"
    CANDIDATE = "CANDIDATE"
    REVIEW = "REVIEW"
    ABSTAIN = "ABSTAIN"


@dataclass(frozen=True)
class ScoreBreakdown:
    vrp_ratio: Decimal
    theta_capture_proxy: Decimal
    premium_edge: Decimal
    gamma_safety: Decimal
    range_quality: Decimal
    execution_quality: Decimal
    final_score: Decimal


@dataclass(frozen=True)
class RadarDecision:
    decision_identity: str
    decision: Decision
    session_id: str
    session_minute: int
    phase: SessionPhase
    structure: IronCondorCandidate | None
    score: ScoreBreakdown | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.decision is Decision.UNKNOWN and (
            not self.blockers or self.structure is not None or self.score is not None
        ):
            raise ValueError(
                "UNKNOWN decision requires blockers and cannot have structure or score"
            )
        if self.decision is Decision.CANDIDATE and (
            self.blockers or self.structure is None or self.score is None
        ):
            raise ValueError("CANDIDATE requires one structure, one score, and no blockers")


def evaluate_radar_unit(
    *,
    session: DeribitSession,
    context: MarketContext,
    quotes: tuple[OptionQuote, ...],
    policy: BtcShortVolPolicy,
) -> tuple[RadarDecision, StructureSelection | None]:
    """Gate MarketContext truth before any structure enumeration or score computation."""

    if context.knowledge is MarketContextKnowledge.UNKNOWN:
        empty = StructureSelection(
            selected=None,
            considered_put_verticals=0,
            considered_call_verticals=0,
            considered_condors=0,
            blockers=context.evidence_blockers,
        )
        return (
            evaluate_two_sided_short_vol(
                session=session,
                context=context,
                selection=empty,
                policy=policy,
            ),
            None,
        )
    selection = select_iron_condor(quotes=quotes, context=context, policy=policy)
    return (
        evaluate_two_sided_short_vol(
            session=session,
            context=context,
            selection=selection,
            policy=policy,
        ),
        selection,
    )


def evaluate_two_sided_short_vol(
    *,
    session: DeribitSession,
    context: MarketContext,
    selection: StructureSelection,
    policy: BtcShortVolPolicy,
) -> RadarDecision:
    if context.knowledge is MarketContextKnowledge.UNKNOWN:
        return _decision(
            session=session,
            policy=policy,
            result=Decision.UNKNOWN,
            structure=None,
            score=None,
            blockers=("MARKET_CONTEXT_EVIDENCE_NOT_BOUND", *context.evidence_blockers),
        )
    blockers: list[str] = []
    if session.phase is SessionPhase.ROLL_REPRICE:
        blockers.append("ROLL_REPRICE_REVIEW_ONLY")
    if session.phase in {SessionPhase.EXIT_ONLY, SessionPhase.DELIVERY_TWAP}:
        blockers.append("NEW_ENTRY_WINDOW_CLOSED")
    minimum_vrp = (
        policy.radar.late_theta_minimum_vrp_ratio
        if session.phase is SessionPhase.LATE_THETA
        else policy.radar.minimum_vrp_ratio
    )
    vrp_ratio = context.same_session_implied_variance / context.physical_variance_forecast
    if vrp_ratio < minimum_vrp:
        blockers.append("SESSION_VRP_BELOW_THRESHOLD")
    theta = theta_capture_proxy(
        minutes_to_expiry=session.minutes_to_expiry,
        exit_minutes_to_expiry=policy.position.latest_short_risk_exit_minutes_to_expiry,
    )
    if theta < policy.radar.minimum_theta_capture_proxy:
        blockers.append("THETA_CAPTURE_TOO_SMALL")
    if context.rv_acceleration > policy.radar.maximum_rv_acceleration:
        blockers.append("RV_ACCELERATION_TOO_HIGH")
    if context.jump_share > policy.radar.maximum_jump_share:
        blockers.append("JUMP_SHARE_TOO_HIGH")
    if context.directional_persistence > policy.radar.maximum_directional_persistence:
        blockers.append("DIRECTIONAL_PERSISTENCE_TOO_HIGH")
    if context.event_state in {EventState.LIVE_EVENT, EventState.UNSCHEDULED_SHOCK}:
        blockers.append("EVENT_OR_SHOCK_IN_PROGRESS")
    if context.breakout_state is BreakoutState.BREAKING_CONCENTRATED_STRIKE:
        blockers.append("CONCENTRATED_STRIKE_BREAKOUT")
    if selection.selected is None:
        blockers.extend(selection.blockers)
        return _decision(
            session=session,
            policy=policy,
            result=Decision.ABSTAIN,
            structure=None,
            score=None,
            blockers=tuple(blockers),
        )
    structure = selection.selected
    score = _score(session=session, context=context, structure=structure, policy=policy)
    if structure.minimum_body_distance_sigma < policy.radar.minimum_body_distance_sigma:
        blockers.append("BODY_DISTANCE_TOO_SMALL")
    if abs(structure.net_delta) > policy.radar.maximum_abs_net_delta:
        blockers.append("NET_DELTA_TOO_DIRECTIONAL")
    blockers.extend(_underwriting_blockers(structure, policy))

    hard_blockers = tuple(blockers)
    if hard_blockers:
        result = (
            Decision.REVIEW if hard_blockers == ("ROLL_REPRICE_REVIEW_ONLY",) else Decision.ABSTAIN
        )
    elif score.final_score >= policy.radar.activation_score:
        result = Decision.CANDIDATE
    else:
        result = Decision.REVIEW
        blockers.append("COMBINED_SCORE_BELOW_ACTIVATION")
    return _decision(
        session=session,
        policy=policy,
        result=result,
        structure=structure,
        score=score,
        blockers=tuple(blockers),
    )


def _score(
    *,
    session: DeribitSession,
    context: MarketContext,
    structure: IronCondorCandidate,
    policy: BtcShortVolPolicy,
) -> ScoreBreakdown:
    vrp_ratio = context.same_session_implied_variance / context.physical_variance_forecast
    minimum_vrp = (
        policy.radar.late_theta_minimum_vrp_ratio
        if session.phase is SessionPhase.LATE_THETA
        else policy.radar.minimum_vrp_ratio
    )
    vrp_normalized = _clamp(
        (vrp_ratio - minimum_vrp) / (policy.radar.vrp_saturation_ratio - minimum_vrp)
    )
    theta = theta_capture_proxy(
        minutes_to_expiry=session.minutes_to_expiry,
        exit_minutes_to_expiry=policy.position.latest_short_risk_exit_minutes_to_expiry,
    )
    theta_normalized = _clamp(
        (theta - policy.radar.minimum_theta_capture_proxy)
        / (Decimal(1) - policy.radar.minimum_theta_capture_proxy)
    )
    premium_edge = _clamp(Decimal("0.7") * vrp_normalized + Decimal("0.3") * theta_normalized)
    gamma_safety = _gamma_safety(context)
    range_quality = _clamp(
        structure.minimum_body_distance_sigma / (policy.radar.minimum_body_distance_sigma * 2)
    )
    fee_fraction = (
        structure.execution.usd_total_fee / structure.execution.usd_gross_credit
        if structure.execution.usd_gross_credit > 0
        else Decimal(1)
    )
    fee_quality = _clamp(Decimal(1) - fee_fraction)
    execution_quality = _clamp(
        Decimal("0.45") * structure.average_spread_quality
        + Decimal("0.30") * structure.depth_quality
        + Decimal("0.25") * fee_quality
    )
    final_score = Decimal(100) * premium_edge * gamma_safety * range_quality * execution_quality
    return ScoreBreakdown(
        vrp_ratio=vrp_ratio,
        theta_capture_proxy=theta,
        premium_edge=premium_edge,
        gamma_safety=gamma_safety,
        range_quality=range_quality,
        execution_quality=execution_quality,
        final_score=final_score,
    )


def theta_capture_proxy(*, minutes_to_expiry: int, exit_minutes_to_expiry: int) -> Decimal:
    if minutes_to_expiry <= exit_minutes_to_expiry:
        return Decimal(0)
    current = Decimal(minutes_to_expiry)
    exit_time = Decimal(exit_minutes_to_expiry)
    return Decimal(1) - (exit_time / current).sqrt()


def _gamma_safety(context: MarketContext) -> Decimal:
    path = _clamp(
        Decimal(1)
        - Decimal("0.35") * context.rv_acceleration
        - Decimal("0.35") * context.jump_share
        - Decimal("0.30") * context.directional_persistence
    )
    event_factor = {
        EventState.NONE: Decimal(1),
        EventState.POST_EVENT: Decimal(1),
        EventState.PRE_EVENT: Decimal("0.45"),
        EventState.LIVE_EVENT: Decimal(0),
        EventState.UNSCHEDULED_SHOCK: Decimal(0),
    }[context.event_state]
    breakout_factor = {
        BreakoutState.MEAN_REVERTING: Decimal(1),
        BreakoutState.NEUTRAL: Decimal("0.85"),
        BreakoutState.APPROACHING_CONCENTRATED_STRIKE: Decimal("0.50"),
        BreakoutState.BREAKING_CONCENTRATED_STRIKE: Decimal("0.05"),
    }[context.breakout_state]
    concentration_factor = Decimal(1)
    if context.concentrated_strike is not None:
        if context.breakout_state is BreakoutState.MEAN_REVERTING:
            concentration_factor = _clamp(
                Decimal(1) + Decimal("0.10") * context.concentration_strength
            )
        elif context.breakout_state in {
            BreakoutState.APPROACHING_CONCENTRATED_STRIKE,
            BreakoutState.BREAKING_CONCENTRATED_STRIKE,
        }:
            concentration_factor = _clamp(
                Decimal(1) - Decimal("0.50") * context.concentration_strength
            )
    return _clamp(path * event_factor * breakout_factor * concentration_factor)


def _underwriting_blockers(
    structure: IronCondorCandidate,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    execution = structure.execution
    blockers: list[str] = []
    if execution.usd_net_credit < policy.underwriting.minimum_combined_net_credit_usd:
        blockers.append("COMBINED_NET_CREDIT_TOO_SMALL")
    credit_ratio = execution.usd_net_credit / execution.maximum_side_payoff_cap_usd
    if credit_ratio < policy.underwriting.minimum_credit_to_max_side_payoff:
        blockers.append("CREDIT_TO_MAX_SIDE_PAYOFF_TOO_SMALL")
    if execution.entry_boundary_max_loss_usd > policy.underwriting.maximum_entry_boundary_loss_usd:
        blockers.append("ENTRY_BOUNDARY_MAX_LOSS_TOO_HIGH")
    fee_fraction = execution.usd_total_fee / execution.usd_gross_credit
    if fee_fraction > policy.underwriting.maximum_total_fee_fraction_of_credit:
        blockers.append("FOUR_LEG_FEE_BURDEN_TOO_HIGH")
    return tuple(blockers)


def radar_decision_identity(
    *,
    policy_identity: str,
    session_id: str,
    session_minute: int,
    result: Decision,
    structure: IronCondorCandidate | None,
    score: ScoreBreakdown | None,
    blockers: tuple[str, ...],
) -> str:
    return canonical_identity(
        "TwoSidedShortVolDecisionV1",
        policy_identity,
        session_id,
        session_minute,
        result,
        structure,
        score,
        blockers,
    )


def require_radar_decision_identity(
    decision: RadarDecision,
    *,
    policy_identity: str,
) -> None:
    expected = radar_decision_identity(
        policy_identity=policy_identity,
        session_id=decision.session_id,
        session_minute=decision.session_minute,
        result=decision.decision,
        structure=decision.structure,
        score=decision.score,
        blockers=decision.blockers,
    )
    if decision.decision_identity != expected:
        raise ValueError("Radar Decision identity mismatch")


def _decision(
    *,
    session: DeribitSession,
    policy: BtcShortVolPolicy,
    result: Decision,
    structure: IronCondorCandidate | None,
    score: ScoreBreakdown | None,
    blockers: tuple[str, ...],
) -> RadarDecision:
    identity = radar_decision_identity(
        policy_identity=policy.identity,
        session_id=session.session_id,
        session_minute=session.minute,
        result=result,
        structure=structure,
        score=score,
        blockers=blockers,
    )
    return RadarDecision(
        decision_identity=identity,
        decision=result,
        session_id=session.session_id,
        session_minute=session.minute,
        phase=session.phase,
        structure=structure,
        score=score,
        blockers=blockers,
    )


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))
