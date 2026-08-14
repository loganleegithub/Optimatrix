from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from optimatrix.decision import (
    DecisionRecord,
    DecisionResult,
    DecisionWindow,
    MarketObservation,
    unassessed_decision_record,
)
from optimatrix.identity import canonical_identity, canonical_value
from optimatrix.market import EventState, OptionQuote
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.risk import (
    AllocationResult,
    ShadowCapacity,
    ShadowRiskAllocation,
    allocate_btc_condor_shadow_risk,
)
from optimatrix.route import ShadowRouteEvidence, component_synthetic_route_evidence
from optimatrix.session import SessionPhase, current_deribit_session
from optimatrix.structure import (
    Btc0DteCondorCandidate,
    Btc0DteCondorSelection,
    select_btc_0dte_condor,
)


@dataclass(frozen=True)
class BtcWindowAssessment:
    record: DecisionRecord
    selection: Btc0DteCondorSelection | None
    allocation: ShadowRiskAllocation | None
    session_phase: SessionPhase
    vrp_proxy_ratio: Decimal | None


def evaluate_btc_short_vol_window(
    *,
    window: DecisionWindow,
    observation: MarketObservation | None,
    capacity: ShadowCapacity | None,
    policy: BtcShortVolPolicy,
    known_at: datetime,
) -> BtcWindowAssessment:
    if known_at.tzinfo is None:
        raise ValueError("Decision known_at must be timezone-aware")
    known_at = known_at.astimezone(UTC)
    if known_at < window.input_deadline:
        raise ValueError("Decision cannot be finalized before the Window input deadline")
    decision_boundary = window.input_deadline
    session = current_deribit_session(window.starts_at, phase_policy=policy.session)
    if window.market_session_id != session.session_id or window.channel_id is not policy.channel_id:
        raise ValueError("DecisionWindow does not match BTC Short Vol Policy scope")
    if observation is None:
        return BtcWindowAssessment(
            record=unassessed_decision_record(
                window=window,
                decision_policy_id=policy.identity,
                known_at=known_at,
                observation=None,
            ),
            selection=None,
            allocation=None,
            session_phase=current_deribit_session(
                window.ends_at - timedelta(microseconds=1),
                phase_policy=policy.session,
            ).phase,
            vrp_proxy_ratio=None,
        )
    if (
        observation.channel_id is not window.channel_id
        or not window.starts_at <= observation.observed_at < window.ends_at
        or observation.known_at > window.input_deadline
    ):
        record = unassessed_decision_record(
            window=window,
            decision_policy_id=policy.identity,
            known_at=known_at,
            observation=observation,
        )
        return BtcWindowAssessment(record, None, None, session.phase, None)
    observed_session = current_deribit_session(
        observation.observed_at,
        phase_policy=policy.session,
    )
    if observed_session.session_id != window.market_session_id:
        raise ValueError("MarketObservation crossed the DecisionWindow Session")
    if observation.data_health_blockers:
        record = _record(
            window=window,
            observation=observation,
            policy=policy,
            result=DecisionResult.UNKNOWN,
            blockers=observation.data_health_blockers,
            known_at=decision_boundary,
        )
        return BtcWindowAssessment(record, None, None, observed_session.phase, None)

    context = observation.context
    vrp_ratio = (
        context.same_session_implied_variance_proxy / context.trailing_realized_variance_proxy
    )
    environment_blockers = btc_environment_blockers(
        phase=observed_session.phase,
        vrp_ratio=vrp_ratio,
        observation=observation,
        policy=policy,
    )
    if environment_blockers:
        result = (
            DecisionResult.REVIEW
            if environment_blockers == ("ROLL_REPRICE_REVIEW_ONLY",)
            else DecisionResult.ABSTAIN
        )
        record = _record(
            window=window,
            observation=observation,
            policy=policy,
            result=result,
            blockers=environment_blockers,
            known_at=decision_boundary,
        )
        return BtcWindowAssessment(record, None, None, observed_session.phase, vrp_ratio)

    selection = select_btc_0dte_condor(observation=observation, policy=policy)
    if selection.selected is None:
        record = _record(
            window=window,
            observation=observation,
            policy=policy,
            result=DecisionResult.ABSTAIN,
            blockers=selection.blockers,
            known_at=decision_boundary,
        )
        return BtcWindowAssessment(record, selection, None, observed_session.phase, vrp_ratio)

    allocation = allocate_btc_condor_shadow_risk(
        candidate=selection.selected,
        market_session_id=window.market_session_id,
        policy=policy,
        capacity=capacity,
        known_at=decision_boundary,
    )
    selected = selection.selected
    route_evidence = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=selected.identity,
        evaluated_at=decision_boundary,
        target_amount=selected.option_amount,
        instrument_names=(
            selected.long_put.instrument_name,
            selected.short_put.instrument_name,
            selected.short_call.instrument_name,
            selected.long_call.instrument_name,
        ),
        observation_id=observation.identity,
        observed_at=observation.observed_at,
        observation_known_at=observation.known_at,
        quotes=(
            selected.long_put,
            selected.short_put,
            selected.short_call,
            selected.long_call,
        ),
        pricing=selected.pricing,
    )
    if allocation.result is AllocationResult.UNKNOWN:
        result = DecisionResult.UNKNOWN
    elif allocation.result is AllocationResult.UNAVAILABLE:
        result = DecisionResult.ABSTAIN
    else:
        result = DecisionResult.CANDIDATE
    blockers = (allocation.reason,) if allocation.reason is not None else ()
    record = _record(
        window=window,
        observation=observation,
        policy=policy,
        result=result,
        blockers=blockers,
        selected_structure_id=selection.selected.identity,
        risk_allocation_id=allocation.identity,
        selected_structure=_structure_record(selection),
        risk_allocation=_allocation_record(allocation),
        route_evidence=route_evidence,
        known_at=decision_boundary,
    )
    return BtcWindowAssessment(record, selection, allocation, observed_session.phase, vrp_ratio)


def btc_environment_blockers(
    *,
    phase: SessionPhase,
    vrp_ratio: Decimal,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    context = observation.context
    blockers: list[str] = []
    if phase is SessionPhase.ROLL_REPRICE:
        blockers.append("ROLL_REPRICE_REVIEW_ONLY")
    if phase in {SessionPhase.EXIT_ONLY, SessionPhase.DELIVERY_TWAP}:
        blockers.append("NEW_ENTRY_WINDOW_CLOSED")
    minimum_vrp = (
        policy.environment.late_theta_minimum_vrp_ratio
        if phase is SessionPhase.LATE_THETA
        else policy.environment.minimum_vrp_ratio
    )
    if vrp_ratio < minimum_vrp:
        blockers.append("SESSION_VRP_PROXY_BELOW_THRESHOLD")
    if context.rv_acceleration > policy.environment.maximum_rv_acceleration:
        blockers.append("RV_ACCELERATION_TOO_HIGH")
    if context.jump_share > policy.environment.maximum_jump_share:
        blockers.append("JUMP_SHARE_TOO_HIGH")
    if context.directional_persistence > policy.environment.maximum_directional_persistence:
        blockers.append("DIRECTIONAL_PERSISTENCE_TOO_HIGH")
    if context.event_state in {EventState.LIVE_EVENT, EventState.UNSCHEDULED_SHOCK}:
        blockers.append("EVENT_OR_SHOCK_IN_PROGRESS")
    return tuple(blockers)


def _record(
    *,
    window: DecisionWindow,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
    result: DecisionResult,
    blockers: tuple[str, ...],
    selected_structure_id: str | None = None,
    risk_allocation_id: str | None = None,
    selected_structure: dict[str, object] | None = None,
    risk_allocation: dict[str, object] | None = None,
    route_evidence: ShadowRouteEvidence | None = None,
    known_at: datetime,
) -> DecisionRecord:
    return DecisionRecord(
        window=window,
        decision_policy_id=policy.identity,
        known_at=known_at,
        observation_id=observation.identity,
        observation=observation,
        result=result,
        blockers=blockers,
        selected_structure_id=selected_structure_id,
        risk_allocation_id=risk_allocation_id,
        selected_structure_json=_payload_json(selected_structure),
        risk_allocation_json=_payload_json(risk_allocation),
        route_evidence_id=(route_evidence.identity if route_evidence is not None else None),
        route_evidence_json=(
            _payload_json(route_evidence.as_object()) if route_evidence is not None else None
        ),
    )


def _structure_record(selection: Btc0DteCondorSelection) -> dict[str, object]:
    candidate = selection.selected
    if candidate is None:
        raise ValueError("selected structure record requires one Candidate")
    value = canonical_value(
        {
            "candidate_id": candidate.identity,
            "observation_id": candidate.observation_id,
            "legs": {
                "long_put": _leg_record(candidate.long_put),
                "short_put": _leg_record(candidate.short_put),
                "short_call": _leg_record(candidate.short_call),
                "long_call": _leg_record(candidate.long_call),
            },
            "option_amount": candidate.option_amount,
            "expiry": candidate.expiry,
            "pricing": {
                "fee_model_id": candidate.pricing.fee_model_id,
                "native_gross_credit": candidate.pricing.native_gross_credit,
                "combo_standard_fee_native": candidate.pricing.combo_standard_fee_native,
                "native_net_credit": candidate.pricing.native_net_credit,
                "boundary_index_price_usd": candidate.pricing.boundary_index_price_usd,
                "boundary_net_credit_usd": candidate.pricing.boundary_net_credit_usd,
                "maximum_contractual_payoff_cap_usd": (
                    candidate.pricing.maximum_contractual_payoff_cap_usd
                ),
                "boundary_reference_loss_usd": (candidate.pricing.boundary_reference_loss_usd),
                "observed_close_native_debit": (candidate.pricing.observed_close_native_debit),
                "observed_close_depth_coverage": candidate.close_depth_coverage,
            },
            "net_delta": candidate.net_delta,
            "put_body_distance_sigma": candidate.put_body_distance_sigma,
            "call_body_distance_sigma": candidate.call_body_distance_sigma,
            "ranking_method_id": canonical_identity(
                "Btc0DteCondorRankV1",
                (
                    "MAX_CREDIT_TO_PAYOFF_CAP",
                    "MAX_NATIVE_NET_CREDIT",
                    "MIN_COMBO_FEE_BURDEN",
                    "MAX_MINIMUM_OBSERVED_CLOSE_DEPTH_COVERAGE",
                    "STABLE_INSTRUMENT_NAMES",
                ),
            ),
            "rank_evidence": _rank_evidence(candidate),
            "retained_alternatives": tuple(
                _alternative_record(item) for item in selection.retained_alternatives
            ),
            "population_counts": {
                "legal": selection.legal_structure_count,
                "price_evaluable": selection.price_evaluable_count,
                "policy_eligible": selection.policy_eligible_count,
            },
        }
    )
    if not isinstance(value, dict):
        raise TypeError("canonical structure record must be an object")
    return value


def _leg_record(quote: OptionQuote) -> dict[str, object]:
    return {
        "instrument_name": quote.instrument_name,
        "strike": quote.strike,
        "option_type": quote.option_type,
        "signed_delta": quote.signed_delta,
        "delivery_fee_exempt": quote.delivery_fee_exempt,
    }


def _rank_evidence(candidate: Btc0DteCondorCandidate) -> dict[str, object]:
    pricing = candidate.pricing
    return {
        "credit_to_payoff_cap": (
            pricing.boundary_net_credit_usd / pricing.maximum_contractual_payoff_cap_usd
        ),
        "native_net_credit": pricing.native_net_credit,
        "combo_fee_fraction_of_credit": (
            pricing.combo_standard_fee_native / pricing.native_gross_credit
        ),
        "minimum_observed_close_depth_coverage": min(candidate.close_depth_coverage),
        "net_delta": candidate.net_delta,
        "minimum_body_distance_sigma": candidate.minimum_body_distance_sigma,
    }


def _alternative_record(candidate: Btc0DteCondorCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.identity,
        "legs": {
            "long_put": _leg_record(candidate.long_put),
            "short_put": _leg_record(candidate.short_put),
            "short_call": _leg_record(candidate.short_call),
            "long_call": _leg_record(candidate.long_call),
        },
        "option_amount": candidate.option_amount,
        "rank_evidence": _rank_evidence(candidate),
    }


def _allocation_record(allocation: ShadowRiskAllocation) -> dict[str, object]:
    value = canonical_value(allocation)
    if not isinstance(value, dict):
        raise TypeError("canonical allocation record must be an object")
    value["allocation_id"] = allocation.identity
    return value


def _payload_json(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
