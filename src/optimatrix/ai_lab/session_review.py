# ruff: noqa: RUF001 -- Chinese verdict explanations intentionally use Chinese punctuation.

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from optimatrix.ai_lab.canonical import JsonObject, content_id, decimal_text, utc_text
from optimatrix.channels import ChannelId
from optimatrix.decision import (
    DecisionRecord,
    DecisionResult,
    DecisionWindow,
    schedule_decision_windows,
)
from optimatrix.lifecycle import WindowOutcome
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import settle_btc_0dte_condor
from optimatrix.products import ProductId
from optimatrix.session import SessionPhase, current_deribit_session
from optimatrix.structure import (
    Btc0DteCondorCandidate,
    CandidateDataReadiness,
    enumerate_btc_0dte_condors,
)

SESSION_REVIEW_SCHEMA = "optimatrix.ai-lab.session-review.v1"
SESSION_REVIEW_NAMESPACE = "OptimatrixAiLabSessionReviewV1"
WINDOW_REVIEW_NAMESPACE = "OptimatrixAiLabWindowReviewV1"
OPPORTUNITY_NAMESPACE = "OptimatrixAiLabPostSessionOpportunityV1"
GATE_DISTANCE_NAMESPACE = "OptimatrixAiLabGateDistanceV1"
OPPORTUNITY_DEFINITION_NAMESPACE = "OptimatrixAiLabOpportunityDefinitionV1"


class SessionVerdict(StrEnum):
    UNKNOWN = "UNKNOWN"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    MISSED_OPPORTUNITY = "MISSED_OPPORTUNITY"
    BASE_FOUND_OPPORTUNITY = "BASE_FOUND_OPPORTUNITY"


class WindowEvidenceStatus(StrEnum):
    AUDITABLE = "AUDITABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GateDistance:
    code: str
    quantifiable: bool
    actual: Decimal | None
    threshold: Decimal | None
    signed_margin_to_pass: Decimal | None
    unit: str | None
    explanation: str

    def __post_init__(self) -> None:
        if not self.code or not self.explanation:
            raise ValueError("gate distance requires a code and explanation")
        numeric = (self.actual, self.threshold, self.signed_margin_to_pass)
        if self.quantifiable != all(value is not None for value in numeric):
            raise ValueError("quantifiable gate distance requires all numeric facts")
        if not self.quantifiable and any(value is not None for value in numeric):
            raise ValueError("non-quantifiable gate distance cannot carry invented numbers")
        if any(value is not None and not value.is_finite() for value in numeric):
            raise ValueError("gate distance numbers must be finite")

    @property
    def identity(self) -> str:
        return content_id(GATE_DISTANCE_NAMESPACE, self._draft())

    def _draft(self) -> JsonObject:
        return {
            "code": self.code,
            "quantifiable": self.quantifiable,
            "actual": _decimal_or_none(self.actual),
            "threshold": _decimal_or_none(self.threshold),
            "signed_margin_to_pass": _decimal_or_none(self.signed_margin_to_pass),
            "unit": self.unit,
            "explanation": self.explanation,
        }

    def as_object(self) -> JsonObject:
        return {"gate_fact_id": self.identity, **self._draft()}


@dataclass(frozen=True)
class OpportunityFinding:
    decision_window_id: str
    candidate_id: str
    base_result: str
    base_selected_exact_candidate: bool
    candidate_policy_blockers: tuple[str, ...]
    native_result_btc: Decimal
    settlement_reference_result_usd: Decimal
    short_put_strike_usd: Decimal
    short_call_strike_usd: Decimal
    put_short_breached: bool
    call_short_breached: bool
    maximum_contractual_payoff_cap_usd: Decimal
    boundary_net_credit_usd: Decimal
    credit_to_payoff_cap: Decimal
    entry_combo_fee_fraction: Decimal
    gate_distances: tuple[GateDistance, ...]

    def __post_init__(self) -> None:
        if self.native_result_btc <= 0:
            raise ValueError("post-Session opportunity requires positive fee-after economics")
        if len(set(self.candidate_policy_blockers)) != len(self.candidate_policy_blockers):
            raise ValueError("candidate Policy blockers must be unique")
        if len({item.identity for item in self.gate_distances}) != len(self.gate_distances):
            raise ValueError("opportunity gate facts must be unique")

    @property
    def identity(self) -> str:
        return content_id(OPPORTUNITY_NAMESPACE, self._draft())

    def _draft(self) -> JsonObject:
        return {
            "decision_window_id": self.decision_window_id,
            "candidate_id": self.candidate_id,
            "base_result": self.base_result,
            "base_selected_exact_candidate": self.base_selected_exact_candidate,
            "candidate_policy_blockers": list(self.candidate_policy_blockers),
            "native_result_btc": decimal_text(self.native_result_btc),
            "settlement_reference_result_usd": decimal_text(self.settlement_reference_result_usd),
            "short_put_strike_usd": decimal_text(self.short_put_strike_usd),
            "short_call_strike_usd": decimal_text(self.short_call_strike_usd),
            "put_short_breached": self.put_short_breached,
            "call_short_breached": self.call_short_breached,
            "maximum_contractual_payoff_cap_usd": decimal_text(
                self.maximum_contractual_payoff_cap_usd
            ),
            "boundary_net_credit_usd": decimal_text(self.boundary_net_credit_usd),
            "credit_to_payoff_cap": decimal_text(self.credit_to_payoff_cap),
            "entry_combo_fee_fraction": decimal_text(self.entry_combo_fee_fraction),
            "gate_distances": [item.as_object() for item in self.gate_distances],
        }

    def as_object(self) -> JsonObject:
        return {"opportunity_id": self.identity, **self._draft()}


@dataclass(frozen=True)
class WindowReview:
    decision_window_id: str
    starts_at: datetime
    base_result: str
    base_blockers: tuple[str, ...]
    evidence_status: WindowEvidenceStatus
    evidence_reasons: tuple[str, ...]
    legal_structure_count: int
    price_evaluable_count: int
    control_candidate_count: int
    successful_opportunity_count: int
    control_rejection_counts: tuple[tuple[str, int], ...]
    best_control_result_btc: Decimal | None
    best_control_result_usd: Decimal | None
    opportunity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        counts = (
            self.legal_structure_count,
            self.price_evaluable_count,
            self.control_candidate_count,
            self.successful_opportunity_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Window review counts must be non-negative")
        if not (
            self.legal_structure_count
            >= self.price_evaluable_count
            >= self.control_candidate_count
            >= self.successful_opportunity_count
        ):
            raise ValueError("Window opportunity funnel must be monotonic")
        if self.evidence_status is WindowEvidenceStatus.UNKNOWN and not self.evidence_reasons:
            raise ValueError("unknown Window review requires exact evidence reasons")
        if self.evidence_status is WindowEvidenceStatus.AUDITABLE and self.evidence_reasons:
            raise ValueError("auditable Window review cannot retain evidence reasons")
        if (self.best_control_result_btc is None) != (self.best_control_result_usd is None):
            raise ValueError("best control economics must appear together")
        if len(set(self.opportunity_ids)) != len(self.opportunity_ids):
            raise ValueError("Window opportunity identities must be unique")

    @property
    def identity(self) -> str:
        return content_id(WINDOW_REVIEW_NAMESPACE, self._draft())

    def _draft(self) -> JsonObject:
        return {
            "decision_window_id": self.decision_window_id,
            "starts_at": utc_text(self.starts_at),
            "base_result": self.base_result,
            "base_blockers": list(self.base_blockers),
            "evidence_status": self.evidence_status.value,
            "evidence_reasons": list(self.evidence_reasons),
            "legal_structure_count": self.legal_structure_count,
            "price_evaluable_count": self.price_evaluable_count,
            "control_candidate_count": self.control_candidate_count,
            "successful_opportunity_count": self.successful_opportunity_count,
            "control_rejection_counts": dict(self.control_rejection_counts),
            "best_control_result_btc": _decimal_or_none(self.best_control_result_btc),
            "best_control_result_usd": _decimal_or_none(self.best_control_result_usd),
            "opportunity_ids": list(self.opportunity_ids),
        }

    def as_object(self) -> JsonObject:
        return {"window_review_id": self.identity, **self._draft()}


@dataclass(frozen=True)
class SessionReview:
    session_id: str
    policy_id: str
    opportunity_definition_id: str
    verdict: SessionVerdict
    verdict_reason: str
    challenger_comparison_eligible: bool
    expected_window_count: int
    recorded_decision_count: int
    recorded_outcome_count: int
    auditable_window_count: int
    base_candidate_window_count: int
    base_confirmed_opportunity_count: int
    legal_structure_count: int
    price_evaluable_count: int
    control_candidate_count: int
    successful_opportunity_count: int
    evidence_reason_counts: tuple[tuple[str, int], ...]
    base_blocker_counts: tuple[tuple[str, int], ...]
    windows: tuple[WindowReview, ...]
    opportunities: tuple[OpportunityFinding, ...]
    evidence_boundary: str

    def __post_init__(self) -> None:
        if not self.verdict_reason or not self.evidence_boundary:
            raise ValueError("Session review requires explicit verdict and evidence boundaries")
        counts = (
            self.expected_window_count,
            self.recorded_decision_count,
            self.recorded_outcome_count,
            self.auditable_window_count,
            self.base_candidate_window_count,
            self.base_confirmed_opportunity_count,
            self.legal_structure_count,
            self.price_evaluable_count,
            self.control_candidate_count,
            self.successful_opportunity_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Session review counts must be non-negative")
        if self.expected_window_count != len(self.windows):
            raise ValueError("Session review must retain every expected Window")
        if self.successful_opportunity_count != len(self.opportunities):
            raise ValueError("Session opportunity count must match detailed findings")
        if self.challenger_comparison_eligible != (
            self.verdict is SessionVerdict.BASE_FOUND_OPPORTUNITY
            and self.auditable_window_count == self.expected_window_count
        ):
            raise ValueError("Challenger eligibility requires a complete Base-found Session")
        if self.verdict is SessionVerdict.NO_OPPORTUNITY and (
            self.auditable_window_count != self.expected_window_count
            or self.successful_opportunity_count != 0
        ):
            raise ValueError("NO_OPPORTUNITY requires complete zero-opportunity evidence")
        if len({item.identity for item in self.windows}) != len(self.windows):
            raise ValueError("Session Window review identities must be unique")
        if len({item.identity for item in self.opportunities}) != len(self.opportunities):
            raise ValueError("Session opportunity identities must be unique")

    @property
    def identity(self) -> str:
        return content_id(SESSION_REVIEW_NAMESPACE, self._draft())

    @property
    def fact_ids(self) -> tuple[str, ...]:
        identifiers = [self.identity, self.opportunity_definition_id]
        identifiers.extend(window.identity for window in self.windows)
        for opportunity in self.opportunities:
            identifiers.append(opportunity.identity)
            identifiers.extend(gate.identity for gate in opportunity.gate_distances)
        return tuple(identifiers)

    def _draft(self) -> JsonObject:
        return {
            "schema_version": SESSION_REVIEW_SCHEMA,
            "session_id": self.session_id,
            "policy_id": self.policy_id,
            "opportunity_definition_id": self.opportunity_definition_id,
            "verdict": self.verdict.value,
            "verdict_reason": self.verdict_reason,
            "challenger_comparison_eligible": self.challenger_comparison_eligible,
            "expected_window_count": self.expected_window_count,
            "recorded_decision_count": self.recorded_decision_count,
            "recorded_outcome_count": self.recorded_outcome_count,
            "auditable_window_count": self.auditable_window_count,
            "base_candidate_window_count": self.base_candidate_window_count,
            "base_confirmed_opportunity_count": self.base_confirmed_opportunity_count,
            "legal_structure_count": self.legal_structure_count,
            "price_evaluable_count": self.price_evaluable_count,
            "control_candidate_count": self.control_candidate_count,
            "successful_opportunity_count": self.successful_opportunity_count,
            "evidence_reason_counts": dict(self.evidence_reason_counts),
            "base_blocker_counts": dict(self.base_blocker_counts),
            "windows": [item.as_object() for item in self.windows],
            "opportunities": [item.as_object() for item in self.opportunities],
            "evidence_boundary": self.evidence_boundary,
        }

    def as_object(self) -> JsonObject:
        return {"review_id": self.identity, **self._draft()}


def review_ledger_session(
    *,
    ledger_root: Path,
    session_id: str,
    policy: BtcShortVolPolicy,
) -> SessionReview:
    ledger = ObservationLedger(ledger_root)
    return review_session(
        session_id=session_id,
        policy=policy,
        records=ledger.read(),
        outcomes=ledger.read_outcomes(),
    )


def review_session(
    *,
    session_id: str,
    policy: BtcShortVolPolicy,
    records: tuple[DecisionRecord, ...],
    outcomes: tuple[WindowOutcome, ...],
) -> SessionReview:
    session_expiry = _session_expiry(session_id)
    session = current_deribit_session(
        session_expiry - timedelta(microseconds=1),
        phase_policy=policy.session,
    )
    if session.session_id != session_id:
        raise ValueError("session_id is not one canonical Deribit Session expiry")
    expected_windows = schedule_decision_windows(
        session=session,
        channel_id=ChannelId.INVERSE_BTC_SHORT_VOL,
        policy=policy.window,
    )
    expected_ids = {window.identity for window in expected_windows}
    session_records = tuple(record for record in records if record.window.identity in expected_ids)
    session_outcomes = tuple(
        outcome for outcome in outcomes if outcome.decision_window_id in expected_ids
    )
    records_by_window = _unique_records(session_records)
    outcomes_by_window = _unique_outcomes(session_outcomes)
    opportunity_definition_id = _opportunity_definition_id(policy)
    window_reviews: list[WindowReview] = []
    opportunities: list[OpportunityFinding] = []
    for window in expected_windows:
        window_review, window_opportunities = _review_window(
            window=window,
            session_expiry=session_expiry,
            record=records_by_window.get(window.identity),
            outcome=outcomes_by_window.get(window.identity),
            policy=policy,
        )
        window_reviews.append(window_review)
        opportunities.extend(window_opportunities)

    auditable_count = sum(
        item.evidence_status is WindowEvidenceStatus.AUDITABLE for item in window_reviews
    )
    base_candidates = tuple(
        record for record in session_records if record.result is DecisionResult.CANDIDATE
    )
    base_confirmed = sum(item.base_selected_exact_candidate for item in opportunities)
    verdict, verdict_reason = _session_verdict(
        expected=len(expected_windows),
        auditable=auditable_count,
        successful=len(opportunities),
        base_candidates=len(base_candidates),
        base_confirmed=base_confirmed,
    )
    evidence_reason_counts = Counter(
        reason for window in window_reviews for reason in window.evidence_reasons
    )
    base_blocker_counts = Counter(
        blocker for record in session_records for blocker in record.blockers
    )
    return SessionReview(
        session_id=session_id,
        policy_id=policy.identity,
        opportunity_definition_id=opportunity_definition_id,
        verdict=verdict,
        verdict_reason=verdict_reason,
        challenger_comparison_eligible=(
            verdict is SessionVerdict.BASE_FOUND_OPPORTUNITY
            and auditable_count == len(expected_windows)
        ),
        expected_window_count=len(expected_windows),
        recorded_decision_count=len(session_records),
        recorded_outcome_count=len(session_outcomes),
        auditable_window_count=auditable_count,
        base_candidate_window_count=len(base_candidates),
        base_confirmed_opportunity_count=base_confirmed,
        legal_structure_count=sum(item.legal_structure_count for item in window_reviews),
        price_evaluable_count=sum(item.price_evaluable_count for item in window_reviews),
        control_candidate_count=sum(item.control_candidate_count for item in window_reviews),
        successful_opportunity_count=len(opportunities),
        evidence_reason_counts=tuple(sorted(evidence_reason_counts.items())),
        base_blocker_counts=tuple(sorted(base_blocker_counts.items())),
        windows=tuple(window_reviews),
        opportunities=tuple(
            sorted(
                opportunities,
                key=lambda item: (
                    item.decision_window_id,
                    -item.native_result_btc,
                    item.candidate_id,
                ),
            )
        ),
        evidence_boundary=(
            "Decision-time MarketObservation establishes only ex-ante public Shadow structure and "
            "component-book pricing. Matching continuous WindowOutcome extrema and official "
            "delivery establish only post-Session counterfactual settlement economics; no order, "
            "fill, executable Combo liquidity, account Position, realized PnL, Policy "
            "qualification, or Edge is claimed."
        ),
    )


def _review_window(
    *,
    window: DecisionWindow,
    session_expiry: datetime,
    record: DecisionRecord | None,
    outcome: WindowOutcome | None,
    policy: BtcShortVolPolicy,
) -> tuple[WindowReview, tuple[OpportunityFinding, ...]]:
    evidence_reasons = _window_evidence_reasons(
        window=window,
        session_expiry=session_expiry,
        record=record,
        outcome=outcome,
        policy=policy,
    )
    base_result = record.result.value if record is not None else "MISSING"
    base_blockers = record.blockers if record is not None else ()
    if evidence_reasons:
        return (
            WindowReview(
                decision_window_id=window.identity,
                starts_at=window.starts_at,
                base_result=base_result,
                base_blockers=base_blockers,
                evidence_status=WindowEvidenceStatus.UNKNOWN,
                evidence_reasons=evidence_reasons,
                legal_structure_count=0,
                price_evaluable_count=0,
                control_candidate_count=0,
                successful_opportunity_count=0,
                control_rejection_counts=(),
                best_control_result_btc=None,
                best_control_result_usd=None,
                opportunity_ids=(),
            ),
            (),
        )
    assert record is not None and record.observation is not None
    assert outcome is not None and outcome.future_path is not None
    assert outcome.expiry_settlement is not None
    enumeration = enumerate_btc_0dte_condors(observation=record.observation, policy=policy)
    if enumeration.data_readiness is CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED:
        reasons = tuple(
            f"PRIMARY_RANK_UNRESOLVED:{name}"
            for name in enumeration.primary_rank_unresolved_book_names
        )
        return (
            WindowReview(
                decision_window_id=window.identity,
                starts_at=window.starts_at,
                base_result=base_result,
                base_blockers=base_blockers,
                evidence_status=WindowEvidenceStatus.UNKNOWN,
                evidence_reasons=reasons,
                legal_structure_count=enumeration.legal_structure_count,
                price_evaluable_count=len(enumeration.candidates),
                control_candidate_count=0,
                successful_opportunity_count=0,
                control_rejection_counts=(),
                best_control_result_btc=None,
                best_control_result_usd=None,
                opportunity_ids=(),
            ),
            (),
        )

    rejection_counts: Counter[str] = Counter()
    control_results: list[tuple[Btc0DteCondorCandidate, Decimal, Decimal]] = []
    findings: list[OpportunityFinding] = []
    for candidate in enumeration.candidates:
        control_blockers = _control_blockers(
            candidate=candidate,
            decision_known_at=record.known_at,
            session_expiry=session_expiry,
            policy=policy,
        )
        if control_blockers:
            rejection_counts.update(control_blockers)
            continue
        settlement = settle_btc_0dte_condor(
            long_put_strike=candidate.long_put.strike,
            short_put_strike=candidate.short_put.strike,
            short_call_strike=candidate.short_call.strike,
            long_call_strike=candidate.long_call.strike,
            amount=candidate.option_amount,
            delivery_price=outcome.expiry_settlement.delivery_price_usd,
            daily_delivery_fee_exempt=all(
                leg.delivery_fee_exempt
                for leg in (
                    candidate.long_put,
                    candidate.short_put,
                    candidate.short_call,
                    candidate.long_call,
                )
            ),
        )
        native_result = candidate.pricing.native_net_credit + settlement.native_net_cashflow
        usd_result = native_result * settlement.delivery_price_usd
        control_results.append((candidate, native_result, usd_result))
        if native_result <= 0:
            continue
        findings.append(
            OpportunityFinding(
                decision_window_id=window.identity,
                candidate_id=candidate.identity,
                base_result=base_result,
                base_selected_exact_candidate=(
                    record.result is DecisionResult.CANDIDATE
                    and record.selected_structure_id == candidate.identity
                ),
                candidate_policy_blockers=candidate.policy_blockers,
                native_result_btc=native_result,
                settlement_reference_result_usd=usd_result,
                short_put_strike_usd=candidate.short_put.strike,
                short_call_strike_usd=candidate.short_call.strike,
                put_short_breached=(
                    outcome.future_path.minimum_index_price_usd <= candidate.short_put.strike
                ),
                call_short_breached=(
                    outcome.future_path.maximum_index_price_usd >= candidate.short_call.strike
                ),
                maximum_contractual_payoff_cap_usd=(
                    candidate.pricing.maximum_contractual_payoff_cap_usd
                ),
                boundary_net_credit_usd=candidate.pricing.boundary_net_credit_usd,
                credit_to_payoff_cap=(
                    candidate.pricing.boundary_net_credit_usd
                    / candidate.pricing.maximum_contractual_payoff_cap_usd
                ),
                entry_combo_fee_fraction=(
                    candidate.pricing.combo_standard_fee_native
                    / candidate.pricing.native_gross_credit
                ),
                gate_distances=_gate_distances(
                    record=record,
                    candidate=candidate,
                    policy=policy,
                ),
            )
        )
    best = max(control_results, key=lambda item: (item[1], item[0].identity), default=None)
    return (
        WindowReview(
            decision_window_id=window.identity,
            starts_at=window.starts_at,
            base_result=base_result,
            base_blockers=base_blockers,
            evidence_status=WindowEvidenceStatus.AUDITABLE,
            evidence_reasons=(),
            legal_structure_count=enumeration.legal_structure_count,
            price_evaluable_count=len(enumeration.candidates),
            control_candidate_count=len(control_results),
            successful_opportunity_count=len(findings),
            control_rejection_counts=tuple(sorted(rejection_counts.items())),
            best_control_result_btc=best[1] if best is not None else None,
            best_control_result_usd=best[2] if best is not None else None,
            opportunity_ids=tuple(item.identity for item in findings),
        ),
        tuple(findings),
    )


def _window_evidence_reasons(
    *,
    window: DecisionWindow,
    session_expiry: datetime,
    record: DecisionRecord | None,
    outcome: WindowOutcome | None,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if record is None:
        reasons.append("DECISION_RECORD_MISSING")
    else:
        if record.decision_policy_id != policy.identity:
            reasons.append("BASE_POLICY_ID_MISMATCH")
        if record.result is DecisionResult.UNKNOWN:
            reasons.append("BASE_DECISION_UNKNOWN")
        if record.observation is None:
            reasons.append("DECISION_TIME_OBSERVATION_MISSING")
        else:
            if record.observation.data_health_blockers:
                reasons.extend(
                    f"DATA_HEALTH:{blocker}" for blocker in record.observation.data_health_blockers
                )
            if record.observation.known_at > window.input_deadline:
                reasons.append("OBSERVATION_KNOWN_AFTER_WINDOW_DEADLINE")
    if outcome is None:
        reasons.append("WINDOW_OUTCOME_MISSING")
    else:
        if not outcome.future_path_known:
            reasons.append("FUTURE_PATH_UNKNOWN")
        elif outcome.future_path_continuous is not True:
            reasons.append("FUTURE_PATH_DISCONTINUOUS")
        if outcome.future_path is None:
            reasons.append("FUTURE_PATH_SUMMARY_MISSING")
        elif outcome.horizon_ends_at < session_expiry:
            reasons.append("FUTURE_PATH_DOES_NOT_REACH_SESSION_EXPIRY")
        settlement = outcome.expiry_settlement
        if settlement is None:
            reasons.append("OFFICIAL_SETTLEMENT_MISSING")
        elif (
            settlement.expiry != session_expiry
            or settlement.product_id is not ProductId.INVERSE_BTC
        ):
            reasons.append("OFFICIAL_SETTLEMENT_SCOPE_MISMATCH")
    return tuple(dict.fromkeys(reasons))


def _control_blockers(
    *,
    candidate: Btc0DteCondorCandidate,
    decision_known_at: datetime,
    session_expiry: datetime,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    blockers: list[str] = []
    pricing = candidate.pricing
    if decision_known_at >= session_expiry:
        blockers.append("DECISION_NOT_KNOWN_BEFORE_EXPIRY")
    if pricing.maximum_contractual_payoff_cap_usd > policy.risk.maximum_session_stress_reserve_usd:
        blockers.append("USD_CONTRACTUAL_PAYOFF_CAP_EXCEEDS_SESSION_LIMIT")
    if (
        pricing.boundary_reference_loss_usd
        > policy.underwriting.maximum_boundary_reference_loss_usd
    ):
        blockers.append("BOUNDARY_REFERENCE_LOSS_EXCEEDS_CONTROL_LIMIT")
    if (
        pricing.combo_standard_fee_native / pricing.native_gross_credit
        > policy.underwriting.maximum_combo_fee_fraction_of_credit
    ):
        blockers.append("COMBO_FEE_BURDEN_EXCEEDS_CONTROL_LIMIT")
    return tuple(blockers)


def _gate_distances(
    *,
    record: DecisionRecord,
    candidate: Btc0DteCondorCandidate,
    policy: BtcShortVolPolicy,
) -> tuple[GateDistance, ...]:
    observation = record.observation
    if observation is None:
        return ()
    context = observation.context
    session = current_deribit_session(observation.observed_at, phase_policy=policy.session)
    vrp = context.same_session_implied_variance_proxy / context.trailing_realized_variance_proxy
    minimum_vrp = (
        policy.environment.late_theta_minimum_vrp_ratio
        if session.phase is SessionPhase.LATE_THETA
        else policy.environment.minimum_vrp_ratio
    )
    pricing = candidate.pricing
    credit_ratio = pricing.boundary_net_credit_usd / pricing.maximum_contractual_payoff_cap_usd
    fee_fraction = pricing.combo_standard_fee_native / pricing.native_gross_credit
    candidate_codes = set(candidate.policy_blockers)
    record_codes = set(record.blockers)
    codes = tuple(
        dict.fromkeys(
            (
                *record.blockers,
                *candidate.policy_blockers,
            )
        )
    )
    distances: list[GateDistance] = []
    for code in codes:
        if (
            code
            in {
                "NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE",
                "NO_LEGAL_FOUR_LEG_STRUCTURE",
                "NO_PRICE_EVALUABLE_FOUR_LEG_STRUCTURE",
            }
            and candidate_codes
        ):
            continue
        if code == "SESSION_VRP_PROXY_BELOW_THRESHOLD":
            distances.append(_minimum_gate(code, vrp, minimum_vrp, "ratio"))
        elif code == "RV_ACCELERATION_TOO_HIGH":
            distances.append(
                _maximum_gate(
                    code,
                    context.rv_acceleration,
                    policy.environment.maximum_rv_acceleration,
                    "fraction",
                )
            )
        elif code == "JUMP_SHARE_TOO_HIGH":
            distances.append(
                _maximum_gate(
                    code,
                    context.jump_share,
                    policy.environment.maximum_jump_share,
                    "fraction",
                )
            )
        elif code == "DIRECTIONAL_PERSISTENCE_TOO_HIGH":
            distances.append(
                _maximum_gate(
                    code,
                    context.directional_persistence,
                    policy.environment.maximum_directional_persistence,
                    "fraction",
                )
            )
        elif code == "BODY_DISTANCE_TOO_SMALL":
            distances.append(
                _minimum_gate(
                    code,
                    candidate.minimum_body_distance_sigma,
                    policy.structure.minimum_body_distance_sigma,
                    "sigma",
                )
            )
        elif code == "NET_DELTA_TOO_DIRECTIONAL":
            distances.append(
                _maximum_gate(
                    code,
                    abs(candidate.net_delta),
                    policy.structure.maximum_abs_net_delta,
                    "absolute_delta",
                )
            )
        elif code == "BOUNDARY_NET_CREDIT_TOO_SMALL":
            distances.append(
                _minimum_gate(
                    code,
                    pricing.boundary_net_credit_usd,
                    policy.underwriting.minimum_boundary_net_credit_usd,
                    "USD",
                )
            )
        elif code == "CREDIT_TO_PAYOFF_CAP_TOO_SMALL":
            distances.append(
                _minimum_gate(
                    code,
                    credit_ratio,
                    policy.underwriting.minimum_credit_to_payoff_cap,
                    "ratio",
                )
            )
        elif code == "BOUNDARY_REFERENCE_LOSS_TOO_HIGH":
            distances.append(
                _maximum_gate(
                    code,
                    pricing.boundary_reference_loss_usd,
                    policy.underwriting.maximum_boundary_reference_loss_usd,
                    "USD",
                )
            )
        elif code == "COMBO_FEE_BURDEN_TOO_HIGH":
            distances.append(
                _maximum_gate(
                    code,
                    fee_fraction,
                    policy.underwriting.maximum_combo_fee_fraction_of_credit,
                    "ratio",
                )
            )
        elif code == "ROLL_REPRICE_REVIEW_ONLY":
            elapsed = Decimal(int((observation.observed_at - session.start).total_seconds())) / 60
            distances.append(
                _minimum_gate(
                    code,
                    elapsed,
                    Decimal(policy.session.roll_reprice_minutes),
                    "minutes_from_session_start",
                )
            )
        elif code == "NEW_ENTRY_WINDOW_CLOSED":
            remaining = Decimal(int((session.end - observation.observed_at).total_seconds())) / 60
            distances.append(
                _minimum_gate(
                    code,
                    remaining,
                    Decimal(policy.session.exit_only_minutes_to_expiry),
                    "minutes_to_expiry",
                )
            )
        else:
            distances.append(
                GateDistance(
                    code=code,
                    quantifiable=False,
                    actual=None,
                    threshold=None,
                    signed_margin_to_pass=None,
                    unit=None,
                    explanation=(
                        "该门槛是类别、证据或组合层判断；当前事实不能诚实压缩成单一数值距离。"
                    ),
                )
            )
    if not distances and record.result is not DecisionResult.CANDIDATE and record_codes:
        raise ValueError("missed opportunity lost its Base blocker attribution")
    return tuple(distances)


def _minimum_gate(code: str, actual: Decimal, threshold: Decimal, unit: str) -> GateDistance:
    margin = actual - threshold
    return GateDistance(
        code=code,
        quantifiable=True,
        actual=actual,
        threshold=threshold,
        signed_margin_to_pass=margin,
        unit=unit,
        explanation="signed_margin_to_pass = actual - minimum; 负数表示距通过还差多少。",
    )


def _maximum_gate(code: str, actual: Decimal, threshold: Decimal, unit: str) -> GateDistance:
    margin = threshold - actual
    return GateDistance(
        code=code,
        quantifiable=True,
        actual=actual,
        threshold=threshold,
        signed_margin_to_pass=margin,
        unit=unit,
        explanation="signed_margin_to_pass = maximum - actual; 负数表示超限多少。",
    )


def _session_verdict(
    *,
    expected: int,
    auditable: int,
    successful: int,
    base_candidates: int,
    base_confirmed: int,
) -> tuple[SessionVerdict, str]:
    if successful > 0 and base_confirmed > 0:
        return (
            SessionVerdict.BASE_FOUND_OPPORTUNITY,
            "至少一个 Base Candidate 与事后成功的同一四腿结构完全匹配。",
        )
    if successful > 0:
        return (
            SessionVerdict.MISSED_OPPORTUNITY,
            "至少一个 UNFILTERED_CONDOR 事后成功，但 Base 没有选中同一四腿结构。",
        )
    if auditable != expected:
        return (
            SessionVerdict.UNKNOWN,
            "存在不可审计 Window；零个已见机会不能外推为整个 Session 没有机会。",
        )
    if base_candidates > 0:
        return (
            SessionVerdict.NO_OPPORTUNITY,
            "完整 Window 分母均可审计；Base 虽产生过 Candidate，但固定控制组没有一个形成正的费用后结算结果。",
        )
    return (
        SessionVerdict.NO_OPPORTUNITY,
        "完整 Window 分母均可审计，且固定 UNFILTERED_CONDOR 控制组没有正的费用后结算结果。",
    )


def _opportunity_definition_id(policy: BtcShortVolPolicy) -> str:
    return content_id(
        OPPORTUNITY_DEFINITION_NAMESPACE,
        {
            "version": "UNFILTERED_CONDOR_POST_SESSION_SETTLEMENT_V1",
            "policy_id": policy.identity,
            "decision_time_only": True,
            "preserved": [
                "FOUR_LEG_POLICY_GEOMETRY",
                "CAUSAL_DATA_HEALTH",
                "FULL_POLICY_AMOUNT_COMPONENT_PRICING",
                "POSITIVE_NET_CREDIT_AFTER_STANDARD_COMBO_FEE",
                "BOUNDARY_REFERENCE_LOSS_CONTROL",
                "USD_CONTRACTUAL_PAYOFF_CAP_WITHIN_SESSION_LIMIT",
                "COMBO_FEE_BURDEN_CONTROL",
            ],
            "removed_strategy_filters": [
                "SESSION_PHASE",
                "ENVIRONMENT",
                "BODY_DISTANCE",
                "NET_DELTA",
                "MINIMUM_CREDIT_USD",
                "MINIMUM_CREDIT_TO_PAYOFF_CAP",
            ],
            "post_session_success": (
                "ENTRY_NATIVE_NET_CREDIT_PLUS_OFFICIAL_SETTLEMENT_NATIVE_CASHFLOW_GT_ZERO"
            ),
            "short_strike_breach": "CONTINUOUS_WINDOW_PATH_EXTREMA_DIAGNOSTIC_ONLY",
        },
    )


def _session_expiry(session_id: str) -> datetime:
    if not session_id.endswith("Z"):
        raise ValueError("session_id must be canonical UTC ending in Z")
    try:
        value = datetime.fromisoformat(session_id.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError("session_id is not a UTC timestamp") from exc
    normalized = value.astimezone(UTC)
    if utc_text(normalized) != session_id:
        raise ValueError("session_id must use canonical UTC formatting")
    return normalized


def _unique_records(records: tuple[DecisionRecord, ...]) -> dict[str, DecisionRecord]:
    output: dict[str, DecisionRecord] = {}
    for record in records:
        if record.window.identity in output:
            raise ValueError("Session review received duplicate DecisionRecords")
        output[record.window.identity] = record
    return output


def _unique_outcomes(outcomes: tuple[WindowOutcome, ...]) -> dict[str, WindowOutcome]:
    output: dict[str, WindowOutcome] = {}
    for outcome in outcomes:
        if outcome.decision_window_id in output:
            raise ValueError("Session review received duplicate WindowOutcomes")
        output[outcome.decision_window_id] = outcome
    return output


def _decimal_or_none(value: Decimal | None) -> str | None:
    return decimal_text(value) if value is not None else None
