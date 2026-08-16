# ruff: noqa: RUF001 -- Chinese trader-facing explanations intentionally use Chinese punctuation.

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
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

SESSION_REVIEW_SCHEMA = "optimatrix.ai-lab.policy-quality-review.v1"
SESSION_REVIEW_NAMESPACE = "OptimatrixAiLabPolicyQualityReviewV1"
WINDOW_REVIEW_NAMESPACE = "OptimatrixAiLabPolicyQualityWindowV1"
OPPORTUNITY_NAMESPACE = "OptimatrixAiLabHindsightOpportunityV1"
GATE_DISTANCE_NAMESPACE = "OptimatrixAiLabPolicyGateDistanceV2"
CURVE_POINT_NAMESPACE = "OptimatrixAiLabSessionIvRvCurvePointV1"
OPPORTUNITY_DEFINITION_NAMESPACE = "OptimatrixAiLabHindsightOracleDefinitionV1"

HINDSIGHT_ORACLE_VERSION = "HINDSIGHT_SHORT_VOL_POLICY_QUALITY_V1"
HINDSIGHT_RV_METHOD = (
    "MAX_OF_REGISTERED_CUT_LOG_RETURN_VARIANCE_AND_FUTURE_TRAILING_MATCHED_HORIZON_RV_PROXY"
)


class SessionVerdict(StrEnum):
    UNKNOWN = "UNKNOWN"
    NO_OPPORTUNITY_CORRECTLY_AVOIDED = "NO_OPPORTUNITY_CORRECTLY_AVOIDED"
    RULE_WELL_CALIBRATED = "RULE_WELL_CALIBRATED"
    RULE_TOO_CONSERVATIVE = "RULE_TOO_CONSERVATIVE"
    RULE_TOO_AGGRESSIVE = "RULE_TOO_AGGRESSIVE"
    MIXED_RULE_ERROR = "MIXED_RULE_ERROR"


class WindowEvidenceStatus(StrEnum):
    AUDITABLE = "AUDITABLE"
    UNKNOWN = "UNKNOWN"


class WindowClassification(StrEnum):
    UNKNOWN = "UNKNOWN"
    CAPTURED_OPPORTUNITY = "CAPTURED_OPPORTUNITY"
    CORRECT_AVOIDANCE = "CORRECT_AVOIDANCE"
    MISSED_OPPORTUNITY = "MISSED_OPPORTUNITY"
    OVER_RISK_SELECTION = "OVER_RISK_SELECTION"


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
class SessionCurvePoint:
    decision_window_id: str
    starts_at: datetime
    observed_at: datetime
    index_price_usd: Decimal
    implied_variance_proxy: Decimal
    trailing_realized_variance_proxy: Decimal
    ex_ante_vrp_proxy_ratio: Decimal

    def __post_init__(self) -> None:
        values = (
            self.index_price_usd,
            self.implied_variance_proxy,
            self.trailing_realized_variance_proxy,
            self.ex_ante_vrp_proxy_ratio,
        )
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("Session IV/RV curve values must be finite and positive")

    @property
    def identity(self) -> str:
        return content_id(CURVE_POINT_NAMESPACE, self._draft())

    def _draft(self) -> JsonObject:
        return {
            "decision_window_id": self.decision_window_id,
            "starts_at": utc_text(self.starts_at),
            "observed_at": utc_text(self.observed_at),
            "index_price_usd": decimal_text(self.index_price_usd),
            "implied_variance_proxy": decimal_text(self.implied_variance_proxy),
            "trailing_realized_variance_proxy": decimal_text(self.trailing_realized_variance_proxy),
            "ex_ante_vrp_proxy_ratio": decimal_text(self.ex_ante_vrp_proxy_ratio),
        }

    def as_object(self) -> JsonObject:
        return {"curve_point_id": self.identity, **self._draft()}


@dataclass(frozen=True)
class OpportunityFinding:
    decision_window_id: str
    candidate_id: str
    base_result: str
    base_selected_exact_candidate: bool
    candidate_policy_blockers: tuple[str, ...]
    native_result_btc: Decimal
    settlement_reference_result_usd: Decimal
    entry_implied_variance_proxy: Decimal
    registered_cut_realized_variance: Decimal
    maximum_future_trailing_realized_variance_proxy: Decimal
    hindsight_realized_variance_proxy: Decimal
    implied_minus_hindsight_realized_variance: Decimal
    short_put_strike_usd: Decimal
    short_call_strike_usd: Decimal
    put_short_breached: bool
    call_short_breached: bool
    maximum_contractual_payoff_cap_usd: Decimal
    boundary_net_credit_usd: Decimal
    gate_distances: tuple[GateDistance, ...]

    def __post_init__(self) -> None:
        if self.native_result_btc <= 0:
            raise ValueError("hindsight opportunity requires positive fee-after economics")
        if self.implied_minus_hindsight_realized_variance <= 0:
            raise ValueError("hindsight opportunity requires IV above hindsight RV")
        if self.put_short_breached or self.call_short_breached:
            raise ValueError("hindsight opportunity cannot breach either short strike")
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
            "entry_implied_variance_proxy": decimal_text(self.entry_implied_variance_proxy),
            "registered_cut_realized_variance": decimal_text(self.registered_cut_realized_variance),
            "maximum_future_trailing_realized_variance_proxy": decimal_text(
                self.maximum_future_trailing_realized_variance_proxy
            ),
            "hindsight_realized_variance_proxy": decimal_text(
                self.hindsight_realized_variance_proxy
            ),
            "implied_minus_hindsight_realized_variance": decimal_text(
                self.implied_minus_hindsight_realized_variance
            ),
            "short_put_strike_usd": decimal_text(self.short_put_strike_usd),
            "short_call_strike_usd": decimal_text(self.short_call_strike_usd),
            "put_short_breached": self.put_short_breached,
            "call_short_breached": self.call_short_breached,
            "maximum_contractual_payoff_cap_usd": decimal_text(
                self.maximum_contractual_payoff_cap_usd
            ),
            "boundary_net_credit_usd": decimal_text(self.boundary_net_credit_usd),
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
    classification: WindowClassification
    legal_structure_count: int
    price_evaluable_count: int
    control_candidate_count: int
    hindsight_opportunity_count: int
    control_rejection_counts: tuple[tuple[str, int], ...]
    hindsight_rejection_counts: tuple[tuple[str, int], ...]
    best_control_result_btc: Decimal | None
    best_control_result_usd: Decimal | None
    entry_implied_variance_proxy: Decimal | None
    hindsight_realized_variance_proxy: Decimal | None
    selected_candidate_id: str | None
    selected_native_result_btc: Decimal | None
    selected_settlement_result_usd: Decimal | None
    selected_implied_minus_hindsight_rv: Decimal | None
    selected_short_put_strike_usd: Decimal | None
    selected_short_call_strike_usd: Decimal | None
    selected_path_minimum_index_usd: Decimal | None
    selected_path_maximum_index_usd: Decimal | None
    selected_candidate_hindsight_reasons: tuple[str, ...]
    opportunity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        counts = (
            self.legal_structure_count,
            self.price_evaluable_count,
            self.control_candidate_count,
            self.hindsight_opportunity_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Window review counts must be non-negative")
        if not (
            self.legal_structure_count
            >= self.price_evaluable_count
            >= self.control_candidate_count
            >= self.hindsight_opportunity_count
        ):
            raise ValueError("Window hindsight funnel must be monotonic")
        if self.evidence_status is WindowEvidenceStatus.UNKNOWN:
            if not self.evidence_reasons or self.classification is not WindowClassification.UNKNOWN:
                raise ValueError("unknown Window requires reasons and UNKNOWN classification")
        elif self.evidence_reasons or self.classification is WindowClassification.UNKNOWN:
            raise ValueError("auditable Window requires a known classification")
        if (self.best_control_result_btc is None) != (self.best_control_result_usd is None):
            raise ValueError("best control economics must appear together")
        if (self.entry_implied_variance_proxy is None) != (
            self.hindsight_realized_variance_proxy is None
        ):
            raise ValueError("Window hindsight variance facts must appear together")
        if self.evidence_status is WindowEvidenceStatus.AUDITABLE and (
            self.entry_implied_variance_proxy is None
        ):
            raise ValueError("auditable Window requires hindsight variance facts")
        selected_audit = (
            self.selected_candidate_id,
            self.selected_native_result_btc,
            self.selected_settlement_result_usd,
            self.selected_implied_minus_hindsight_rv,
            self.selected_short_put_strike_usd,
            self.selected_short_call_strike_usd,
            self.selected_path_minimum_index_usd,
            self.selected_path_maximum_index_usd,
        )
        if any(value is not None for value in selected_audit) != all(
            value is not None for value in selected_audit
        ):
            raise ValueError("selected-candidate hindsight audit must appear as one bundle")
        if (
            self.evidence_status is WindowEvidenceStatus.AUDITABLE
            and self.base_result == DecisionResult.CANDIDATE.value
            and self.selected_candidate_id is None
        ):
            raise ValueError("auditable Base Candidate requires selected-candidate hindsight facts")
        if self.base_result != DecisionResult.CANDIDATE.value and self.selected_candidate_id:
            raise ValueError("non-Candidate Window cannot carry a selected-candidate audit")
        if self.classification is WindowClassification.OVER_RISK_SELECTION and not (
            self.selected_candidate_hindsight_reasons
        ):
            raise ValueError("over-risk selection requires exact hindsight reasons")
        if (
            self.classification is not WindowClassification.OVER_RISK_SELECTION
            and self.selected_candidate_hindsight_reasons
        ):
            raise ValueError("only an over-risk selection carries selected-candidate reasons")
        if len(set(self.opportunity_ids)) != len(self.opportunity_ids):
            raise ValueError("Window opportunity identities must be unique")
        if self.hindsight_opportunity_count != len(self.opportunity_ids):
            raise ValueError("Window opportunity count must match its identities")
        if (
            self.classification
            in {
                WindowClassification.CAPTURED_OPPORTUNITY,
                WindowClassification.MISSED_OPPORTUNITY,
            }
            and not self.opportunity_ids
        ):
            raise ValueError("captured or missed classification requires an opportunity")
        if self.classification is WindowClassification.CORRECT_AVOIDANCE and self.opportunity_ids:
            raise ValueError("correct avoidance cannot retain an opportunity")

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
            "classification": self.classification.value,
            "legal_structure_count": self.legal_structure_count,
            "price_evaluable_count": self.price_evaluable_count,
            "control_candidate_count": self.control_candidate_count,
            "hindsight_opportunity_count": self.hindsight_opportunity_count,
            "control_rejection_counts": dict(self.control_rejection_counts),
            "hindsight_rejection_counts": dict(self.hindsight_rejection_counts),
            "best_control_result_btc": _decimal_or_none(self.best_control_result_btc),
            "best_control_result_usd": _decimal_or_none(self.best_control_result_usd),
            "entry_implied_variance_proxy": _decimal_or_none(self.entry_implied_variance_proxy),
            "hindsight_realized_variance_proxy": _decimal_or_none(
                self.hindsight_realized_variance_proxy
            ),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_native_result_btc": _decimal_or_none(self.selected_native_result_btc),
            "selected_settlement_result_usd": _decimal_or_none(self.selected_settlement_result_usd),
            "selected_implied_minus_hindsight_rv": _decimal_or_none(
                self.selected_implied_minus_hindsight_rv
            ),
            "selected_short_put_strike_usd": _decimal_or_none(self.selected_short_put_strike_usd),
            "selected_short_call_strike_usd": _decimal_or_none(self.selected_short_call_strike_usd),
            "selected_path_minimum_index_usd": _decimal_or_none(
                self.selected_path_minimum_index_usd
            ),
            "selected_path_maximum_index_usd": _decimal_or_none(
                self.selected_path_maximum_index_usd
            ),
            "selected_candidate_hindsight_reasons": list(self.selected_candidate_hindsight_reasons),
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
    curve_observation_count: int
    auditable_window_count: int
    unknown_window_count: int
    base_candidate_window_count: int
    captured_opportunity_window_count: int
    correct_avoidance_window_count: int
    missed_opportunity_window_count: int
    over_risk_window_count: int
    legal_structure_count: int
    price_evaluable_count: int
    control_candidate_count: int
    hindsight_opportunity_structure_count: int
    missing_curve_window_ids: tuple[str, ...]
    evidence_reason_counts: tuple[tuple[str, int], ...]
    base_blocker_counts: tuple[tuple[str, int], ...]
    curve: tuple[SessionCurvePoint, ...]
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
            self.curve_observation_count,
            self.auditable_window_count,
            self.unknown_window_count,
            self.base_candidate_window_count,
            self.captured_opportunity_window_count,
            self.correct_avoidance_window_count,
            self.missed_opportunity_window_count,
            self.over_risk_window_count,
            self.legal_structure_count,
            self.price_evaluable_count,
            self.control_candidate_count,
            self.hindsight_opportunity_structure_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("Session review counts must be non-negative")
        if self.expected_window_count != len(self.windows):
            raise ValueError("Session review must retain every expected Window")
        if self.curve_observation_count != len(self.curve):
            raise ValueError("Session curve count must match its points")
        if self.hindsight_opportunity_structure_count != len(self.opportunities):
            raise ValueError("Session opportunity count must match detailed findings")
        classification_counts = Counter(item.classification for item in self.windows)
        expected_classification_counts = {
            WindowClassification.CAPTURED_OPPORTUNITY: self.captured_opportunity_window_count,
            WindowClassification.CORRECT_AVOIDANCE: self.correct_avoidance_window_count,
            WindowClassification.MISSED_OPPORTUNITY: self.missed_opportunity_window_count,
            WindowClassification.OVER_RISK_SELECTION: self.over_risk_window_count,
            WindowClassification.UNKNOWN: self.unknown_window_count,
        }
        if any(
            classification_counts[classification] != count
            for classification, count in expected_classification_counts.items()
        ):
            raise ValueError("Session classification counts do not match its Windows")
        classified = self.expected_window_count - self.unknown_window_count
        if classified != self.auditable_window_count:
            raise ValueError("Session classifications must equal auditable Windows")
        if self.auditable_window_count + self.unknown_window_count != self.expected_window_count:
            raise ValueError("Session evidence statuses must cover the exact denominator")
        complete = self.unknown_window_count == 0
        eligible = (
            complete
            and self.verdict is SessionVerdict.RULE_WELL_CALIBRATED
            and self.captured_opportunity_window_count > 0
        )
        if self.challenger_comparison_eligible != eligible:
            raise ValueError("Challenger eligibility requires complete Base-captured evidence")
        if self.verdict is not SessionVerdict.UNKNOWN and not complete:
            raise ValueError("a Session Policy-quality verdict requires complete evidence")
        expected_verdict, _reason = _session_verdict(
            unknown=self.unknown_window_count,
            captured=self.captured_opportunity_window_count,
            correct_avoidance=self.correct_avoidance_window_count,
            missed=self.missed_opportunity_window_count,
            over_risk=self.over_risk_window_count,
        )
        if self.verdict is not expected_verdict:
            raise ValueError("Session verdict does not match its four-quadrant population")
        if len(set(self.missing_curve_window_ids)) != len(self.missing_curve_window_ids):
            raise ValueError("missing curve Window identities must be unique")
        if len(self.missing_curve_window_ids) != self.expected_window_count - len(self.curve):
            raise ValueError("missing curve identities must close the curve denominator")
        if len({item.identity for item in self.windows}) != len(self.windows):
            raise ValueError("Session Window review identities must be unique")
        if len({item.identity for item in self.curve}) != len(self.curve):
            raise ValueError("Session curve identities must be unique")
        if len({item.identity for item in self.opportunities}) != len(self.opportunities):
            raise ValueError("Session opportunity identities must be unique")

    @property
    def identity(self) -> str:
        return content_id(SESSION_REVIEW_NAMESPACE, self._draft())

    @property
    def fact_ids(self) -> tuple[str, ...]:
        identifiers = [self.identity, self.opportunity_definition_id]
        identifiers.extend(point.identity for point in self.curve)
        identifiers.extend(window.identity for window in self.windows)
        for opportunity in self.opportunities:
            identifiers.append(opportunity.identity)
            identifiers.extend(gate.identity for gate in opportunity.gate_distances)
        return tuple(identifiers)

    @property
    def base_confirmed_opportunity_count(self) -> int:
        return self.captured_opportunity_window_count

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
            "curve_observation_count": self.curve_observation_count,
            "auditable_window_count": self.auditable_window_count,
            "unknown_window_count": self.unknown_window_count,
            "base_candidate_window_count": self.base_candidate_window_count,
            "captured_opportunity_window_count": self.captured_opportunity_window_count,
            "correct_avoidance_window_count": self.correct_avoidance_window_count,
            "missed_opportunity_window_count": self.missed_opportunity_window_count,
            "over_risk_window_count": self.over_risk_window_count,
            "legal_structure_count": self.legal_structure_count,
            "price_evaluable_count": self.price_evaluable_count,
            "control_candidate_count": self.control_candidate_count,
            "hindsight_opportunity_structure_count": (self.hindsight_opportunity_structure_count),
            "missing_curve_window_ids": list(self.missing_curve_window_ids),
            "evidence_reason_counts": dict(self.evidence_reason_counts),
            "base_blocker_counts": dict(self.base_blocker_counts),
            "curve": [item.as_object() for item in self.curve],
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
    curve, missing_curve_window_ids = _session_curve(
        expected_windows=expected_windows,
        records_by_window=records_by_window,
        policy=policy,
    )
    curve_by_window = {point.decision_window_id: index for index, point in enumerate(curve)}
    curve_complete = len(curve) == len(expected_windows) and not missing_curve_window_ids
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
            curve=curve,
            curve_index=curve_by_window.get(window.identity),
            curve_complete=curve_complete,
        )
        window_reviews.append(window_review)
        opportunities.extend(window_opportunities)

    classification_counts = Counter(item.classification for item in window_reviews)
    auditable_count = sum(
        item.evidence_status is WindowEvidenceStatus.AUDITABLE for item in window_reviews
    )
    unknown_count = classification_counts[WindowClassification.UNKNOWN]
    captured = classification_counts[WindowClassification.CAPTURED_OPPORTUNITY]
    correct_avoidance = classification_counts[WindowClassification.CORRECT_AVOIDANCE]
    missed = classification_counts[WindowClassification.MISSED_OPPORTUNITY]
    over_risk = classification_counts[WindowClassification.OVER_RISK_SELECTION]
    verdict, verdict_reason = _session_verdict(
        unknown=unknown_count,
        captured=captured,
        correct_avoidance=correct_avoidance,
        missed=missed,
        over_risk=over_risk,
    )
    base_candidates = tuple(
        record for record in session_records if record.result is DecisionResult.CANDIDATE
    )
    evidence_reason_counts = Counter(
        reason for window in window_reviews for reason in window.evidence_reasons
    )
    base_blocker_counts = Counter(
        blocker for record in session_records for blocker in record.blockers
    )
    sorted_opportunities = tuple(
        sorted(
            opportunities,
            key=lambda item: (
                item.decision_window_id,
                -item.settlement_reference_result_usd,
                item.candidate_id,
            ),
        )
    )
    return SessionReview(
        session_id=session_id,
        policy_id=policy.identity,
        opportunity_definition_id=opportunity_definition_id,
        verdict=verdict,
        verdict_reason=verdict_reason,
        challenger_comparison_eligible=(
            verdict is SessionVerdict.RULE_WELL_CALIBRATED and captured > 0
        ),
        expected_window_count=len(expected_windows),
        recorded_decision_count=len(session_records),
        recorded_outcome_count=len(session_outcomes),
        curve_observation_count=len(curve),
        auditable_window_count=auditable_count,
        unknown_window_count=unknown_count,
        base_candidate_window_count=len(base_candidates),
        captured_opportunity_window_count=captured,
        correct_avoidance_window_count=correct_avoidance,
        missed_opportunity_window_count=missed,
        over_risk_window_count=over_risk,
        legal_structure_count=sum(item.legal_structure_count for item in window_reviews),
        price_evaluable_count=sum(item.price_evaluable_count for item in window_reviews),
        control_candidate_count=sum(item.control_candidate_count for item in window_reviews),
        hindsight_opportunity_structure_count=len(sorted_opportunities),
        missing_curve_window_ids=missing_curve_window_ids,
        evidence_reason_counts=tuple(sorted(evidence_reason_counts.items())),
        base_blocker_counts=tuple(sorted(base_blocker_counts.items())),
        curve=curve,
        windows=tuple(window_reviews),
        opportunities=sorted_opportunities,
        evidence_boundary=(
            "Base DecisionRecord and decision-time component books remain ex-ante facts. The "
            "hindsight oracle uses the complete registered-cut IV/RV curve, a conservative "
            "future-RV proxy, continuous physical-path extrema, standard public Combo cost, and "
            "official settlement only after the Session ends. A one-Session classification is "
            "public Shadow policy-quality evidence, not a fill, realized account PnL, executable "
            "liquidity, global Policy qualification, or Edge."
        ),
    )


def _session_curve(
    *,
    expected_windows: tuple[DecisionWindow, ...],
    records_by_window: dict[str, DecisionRecord],
    policy: BtcShortVolPolicy,
) -> tuple[tuple[SessionCurvePoint, ...], tuple[str, ...]]:
    points: list[SessionCurvePoint] = []
    missing: list[str] = []
    for window in expected_windows:
        record = records_by_window.get(window.identity)
        if _curve_evidence_reasons(window=window, record=record, policy=policy):
            missing.append(window.identity)
            continue
        assert record is not None and record.observation is not None
        context = record.observation.context
        points.append(
            SessionCurvePoint(
                decision_window_id=window.identity,
                starts_at=window.starts_at,
                observed_at=record.observation.observed_at,
                index_price_usd=context.index_price,
                implied_variance_proxy=context.same_session_implied_variance_proxy,
                trailing_realized_variance_proxy=context.trailing_realized_variance_proxy,
                ex_ante_vrp_proxy_ratio=(
                    context.same_session_implied_variance_proxy
                    / context.trailing_realized_variance_proxy
                ),
            )
        )
    return tuple(points), tuple(missing)


def _curve_evidence_reasons(
    *,
    window: DecisionWindow,
    record: DecisionRecord | None,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    if record is None:
        return ("DECISION_RECORD_MISSING",)
    reasons: list[str] = []
    if record.decision_policy_id != policy.identity:
        reasons.append("BASE_POLICY_ID_MISMATCH")
    observation = record.observation
    if observation is None:
        reasons.append("DECISION_TIME_OBSERVATION_MISSING")
    else:
        if observation.data_health_blockers:
            reasons.extend(f"DATA_HEALTH:{item}" for item in observation.data_health_blockers)
        if not window.starts_at <= observation.observed_at < window.ends_at:
            reasons.append("OBSERVATION_OUTSIDE_WINDOW")
        if observation.known_at > window.input_deadline:
            reasons.append("OBSERVATION_KNOWN_AFTER_WINDOW_DEADLINE")
    return tuple(dict.fromkeys(reasons))


def _review_window(
    *,
    window: DecisionWindow,
    session_expiry: datetime,
    record: DecisionRecord | None,
    outcome: WindowOutcome | None,
    policy: BtcShortVolPolicy,
    curve: tuple[SessionCurvePoint, ...],
    curve_index: int | None,
    curve_complete: bool,
) -> tuple[WindowReview, tuple[OpportunityFinding, ...]]:
    evidence_reasons = list(
        _window_evidence_reasons(
            window=window,
            session_expiry=session_expiry,
            record=record,
            outcome=outcome,
            policy=policy,
        )
    )
    if not curve_complete:
        evidence_reasons.append("SESSION_IV_RV_CURVE_INCOMPLETE")
    if curve_index is None:
        evidence_reasons.append("WINDOW_IV_RV_CURVE_POINT_MISSING")
    base_result = record.result.value if record is not None else "MISSING"
    base_blockers = record.blockers if record is not None else ()
    if evidence_reasons:
        return _unknown_window(
            window=window,
            base_result=base_result,
            base_blockers=base_blockers,
            reasons=tuple(dict.fromkeys(evidence_reasons)),
        )
    assert record is not None and record.observation is not None
    assert outcome is not None and outcome.future_path is not None
    assert outcome.expiry_settlement is not None
    assert curve_index is not None
    entry_curve = curve[curve_index]
    registered_variance, max_future_trailing_rv, hindsight_rv = _future_variance(
        curve=curve,
        curve_index=curve_index,
        delivery_price=outcome.expiry_settlement.delivery_price_usd,
    )
    enumeration = enumerate_btc_0dte_condors(observation=record.observation, policy=policy)
    if enumeration.data_readiness is CandidateDataReadiness.PRIMARY_RANK_UNRESOLVED:
        reasons = tuple(
            f"PRIMARY_RANK_UNRESOLVED:{name}"
            for name in enumeration.primary_rank_unresolved_book_names
        )
        return _unknown_window(
            window=window,
            base_result=base_result,
            base_blockers=base_blockers,
            reasons=reasons,
            legal_structure_count=enumeration.legal_structure_count,
            price_evaluable_count=len(enumeration.candidates),
        )

    rejection_counts: Counter[str] = Counter()
    hindsight_rejection_counts: Counter[str] = Counter()
    control_results: list[tuple[Btc0DteCondorCandidate, Decimal, Decimal, tuple[str, ...]]] = []
    findings: list[OpportunityFinding] = []
    selected_reconstructed = record.result is not DecisionResult.CANDIDATE
    selected_hindsight_reasons: tuple[str, ...] = ()
    selected_audit: tuple[Btc0DteCondorCandidate, Decimal, Decimal] | None = None
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
        put_breached = outcome.future_path.minimum_index_price_usd <= candidate.short_put.strike
        call_breached = outcome.future_path.maximum_index_price_usd >= candidate.short_call.strike
        hindsight_reasons = _candidate_hindsight_reasons(
            native_result=native_result,
            entry_implied_variance=entry_curve.implied_variance_proxy,
            hindsight_realized_variance=hindsight_rv,
            put_short_breached=put_breached,
            call_short_breached=call_breached,
        )
        hindsight_rejection_counts.update(hindsight_reasons)
        control_results.append((candidate, native_result, usd_result, hindsight_reasons))
        is_selected = (
            record.result is DecisionResult.CANDIDATE
            and record.selected_structure_id == candidate.identity
        )
        if is_selected:
            selected_reconstructed = True
            selected_hindsight_reasons = hindsight_reasons
            selected_audit = (candidate, native_result, usd_result)
        if hindsight_reasons:
            continue
        findings.append(
            OpportunityFinding(
                decision_window_id=window.identity,
                candidate_id=candidate.identity,
                base_result=base_result,
                base_selected_exact_candidate=is_selected,
                candidate_policy_blockers=candidate.policy_blockers,
                native_result_btc=native_result,
                settlement_reference_result_usd=usd_result,
                entry_implied_variance_proxy=entry_curve.implied_variance_proxy,
                registered_cut_realized_variance=registered_variance,
                maximum_future_trailing_realized_variance_proxy=max_future_trailing_rv,
                hindsight_realized_variance_proxy=hindsight_rv,
                implied_minus_hindsight_realized_variance=(
                    entry_curve.implied_variance_proxy - hindsight_rv
                ),
                short_put_strike_usd=candidate.short_put.strike,
                short_call_strike_usd=candidate.short_call.strike,
                put_short_breached=False,
                call_short_breached=False,
                maximum_contractual_payoff_cap_usd=(
                    candidate.pricing.maximum_contractual_payoff_cap_usd
                ),
                boundary_net_credit_usd=candidate.pricing.boundary_net_credit_usd,
                gate_distances=_gate_distances(record=record, candidate=candidate, policy=policy),
            )
        )
    if not selected_reconstructed:
        return _unknown_window(
            window=window,
            base_result=base_result,
            base_blockers=base_blockers,
            reasons=("BASE_SELECTED_STRUCTURE_NOT_RECONSTRUCTABLE",),
            legal_structure_count=enumeration.legal_structure_count,
            price_evaluable_count=len(enumeration.candidates),
            control_candidate_count=len(control_results),
        )
    best = max(control_results, key=lambda item: (item[1], item[0].identity), default=None)
    if record.result is DecisionResult.CANDIDATE:
        selected_is_opportunity = not selected_hindsight_reasons
        classification = (
            WindowClassification.CAPTURED_OPPORTUNITY
            if selected_is_opportunity
            else WindowClassification.OVER_RISK_SELECTION
        )
    else:
        classification = (
            WindowClassification.MISSED_OPPORTUNITY
            if findings
            else WindowClassification.CORRECT_AVOIDANCE
        )
    selected_candidate = selected_audit[0] if selected_audit is not None else None
    return (
        WindowReview(
            decision_window_id=window.identity,
            starts_at=window.starts_at,
            base_result=base_result,
            base_blockers=base_blockers,
            evidence_status=WindowEvidenceStatus.AUDITABLE,
            evidence_reasons=(),
            classification=classification,
            legal_structure_count=enumeration.legal_structure_count,
            price_evaluable_count=len(enumeration.candidates),
            control_candidate_count=len(control_results),
            hindsight_opportunity_count=len(findings),
            control_rejection_counts=tuple(sorted(rejection_counts.items())),
            hindsight_rejection_counts=tuple(sorted(hindsight_rejection_counts.items())),
            best_control_result_btc=best[1] if best is not None else None,
            best_control_result_usd=best[2] if best is not None else None,
            entry_implied_variance_proxy=entry_curve.implied_variance_proxy,
            hindsight_realized_variance_proxy=hindsight_rv,
            selected_candidate_id=(
                selected_candidate.identity if selected_candidate is not None else None
            ),
            selected_native_result_btc=(selected_audit[1] if selected_audit is not None else None),
            selected_settlement_result_usd=(
                selected_audit[2] if selected_audit is not None else None
            ),
            selected_implied_minus_hindsight_rv=(
                entry_curve.implied_variance_proxy - hindsight_rv
                if selected_audit is not None
                else None
            ),
            selected_short_put_strike_usd=(
                selected_candidate.short_put.strike if selected_candidate is not None else None
            ),
            selected_short_call_strike_usd=(
                selected_candidate.short_call.strike if selected_candidate is not None else None
            ),
            selected_path_minimum_index_usd=(
                outcome.future_path.minimum_index_price_usd
                if selected_candidate is not None
                else None
            ),
            selected_path_maximum_index_usd=(
                outcome.future_path.maximum_index_price_usd
                if selected_candidate is not None
                else None
            ),
            selected_candidate_hindsight_reasons=(
                selected_hindsight_reasons
                if classification is WindowClassification.OVER_RISK_SELECTION
                else ()
            ),
            opportunity_ids=tuple(item.identity for item in findings),
        ),
        tuple(findings),
    )


def _unknown_window(
    *,
    window: DecisionWindow,
    base_result: str,
    base_blockers: tuple[str, ...],
    reasons: tuple[str, ...],
    legal_structure_count: int = 0,
    price_evaluable_count: int = 0,
    control_candidate_count: int = 0,
) -> tuple[WindowReview, tuple[OpportunityFinding, ...]]:
    return (
        WindowReview(
            decision_window_id=window.identity,
            starts_at=window.starts_at,
            base_result=base_result,
            base_blockers=base_blockers,
            evidence_status=WindowEvidenceStatus.UNKNOWN,
            evidence_reasons=reasons,
            classification=WindowClassification.UNKNOWN,
            legal_structure_count=legal_structure_count,
            price_evaluable_count=price_evaluable_count,
            control_candidate_count=control_candidate_count,
            hindsight_opportunity_count=0,
            control_rejection_counts=(),
            hindsight_rejection_counts=(),
            best_control_result_btc=None,
            best_control_result_usd=None,
            entry_implied_variance_proxy=None,
            hindsight_realized_variance_proxy=None,
            selected_candidate_id=None,
            selected_native_result_btc=None,
            selected_settlement_result_usd=None,
            selected_implied_minus_hindsight_rv=None,
            selected_short_put_strike_usd=None,
            selected_short_call_strike_usd=None,
            selected_path_minimum_index_usd=None,
            selected_path_maximum_index_usd=None,
            selected_candidate_hindsight_reasons=(),
            opportunity_ids=(),
        ),
        (),
    )


def _window_evidence_reasons(
    *,
    window: DecisionWindow,
    session_expiry: datetime,
    record: DecisionRecord | None,
    outcome: WindowOutcome | None,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    reasons = list(_curve_evidence_reasons(window=window, record=record, policy=policy))
    if record is not None and record.result is DecisionResult.UNKNOWN:
        reasons.append("BASE_DECISION_UNKNOWN")
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


def _future_variance(
    *,
    curve: tuple[SessionCurvePoint, ...],
    curve_index: int,
    delivery_price: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    tail = curve[curve_index:]
    prices = (*(point.index_price_usd for point in tail), delivery_price)
    registered = sum(
        (((right / left).ln()) ** 2 for left, right in pairwise(prices)),
        Decimal(0),
    )
    maximum_trailing = max(point.trailing_realized_variance_proxy for point in tail)
    return registered, maximum_trailing, max(registered, maximum_trailing)


def _candidate_hindsight_reasons(
    *,
    native_result: Decimal,
    entry_implied_variance: Decimal,
    hindsight_realized_variance: Decimal,
    put_short_breached: bool,
    call_short_breached: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if native_result <= 0:
        reasons.append("TERMINAL_FEE_AFTER_ECONOMICS_NOT_POSITIVE")
    if entry_implied_variance <= hindsight_realized_variance:
        reasons.append("ENTRY_IV_DID_NOT_EXCEED_HINDSIGHT_RV")
    if put_short_breached:
        reasons.append("PUT_SHORT_STRIKE_BREACHED")
    if call_short_breached:
        reasons.append("CALL_SHORT_STRIKE_BREACHED")
    return tuple(reasons)


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


_RECORD_LEVEL_POLICY_GATES = {
    "ROLL_REPRICE_REVIEW_ONLY",
    "NEW_ENTRY_WINDOW_CLOSED",
    "SESSION_VRP_PROXY_BELOW_THRESHOLD",
    "RV_ACCELERATION_TOO_HIGH",
    "JUMP_SHARE_TOO_HIGH",
    "DIRECTIONAL_PERSISTENCE_TOO_HIGH",
    "EVENT_OR_SHOCK_IN_PROGRESS",
    "SESSION_SHADOW_STRESS_BUDGET_EXCEEDED",
    "SHADOW_CONCURRENT_POSITION_LIMIT_REACHED",
}


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
    codes = tuple(
        dict.fromkeys(
            (
                *(code for code in record.blockers if code in _RECORD_LEVEL_POLICY_GATES),
                *candidate.policy_blockers,
            )
        )
    )
    distances: list[GateDistance] = []
    for code in codes:
        gate: GateDistance
        if code == "SESSION_VRP_PROXY_BELOW_THRESHOLD":
            gate = _minimum_gate(code, vrp, minimum_vrp, "ratio")
        elif code == "RV_ACCELERATION_TOO_HIGH":
            gate = _maximum_gate(
                code,
                context.rv_acceleration,
                policy.environment.maximum_rv_acceleration,
                "fraction",
            )
        elif code == "JUMP_SHARE_TOO_HIGH":
            gate = _maximum_gate(
                code,
                context.jump_share,
                policy.environment.maximum_jump_share,
                "fraction",
            )
        elif code == "DIRECTIONAL_PERSISTENCE_TOO_HIGH":
            gate = _maximum_gate(
                code,
                context.directional_persistence,
                policy.environment.maximum_directional_persistence,
                "fraction",
            )
        elif code == "BODY_DISTANCE_TOO_SMALL":
            gate = _minimum_gate(
                code,
                candidate.minimum_body_distance_sigma,
                policy.structure.minimum_body_distance_sigma,
                "sigma",
            )
        elif code == "NET_DELTA_TOO_DIRECTIONAL":
            gate = _maximum_gate(
                code,
                abs(candidate.net_delta),
                policy.structure.maximum_abs_net_delta,
                "absolute_delta",
            )
        elif code == "BOUNDARY_NET_CREDIT_TOO_SMALL":
            gate = _minimum_gate(
                code,
                pricing.boundary_net_credit_usd,
                policy.underwriting.minimum_boundary_net_credit_usd,
                "USD",
            )
        elif code == "CREDIT_TO_PAYOFF_CAP_TOO_SMALL":
            gate = _minimum_gate(
                code,
                credit_ratio,
                policy.underwriting.minimum_credit_to_payoff_cap,
                "ratio",
            )
        elif code == "BOUNDARY_REFERENCE_LOSS_TOO_HIGH":
            gate = _maximum_gate(
                code,
                pricing.boundary_reference_loss_usd,
                policy.underwriting.maximum_boundary_reference_loss_usd,
                "USD",
            )
        elif code == "COMBO_FEE_BURDEN_TOO_HIGH":
            gate = _maximum_gate(
                code,
                fee_fraction,
                policy.underwriting.maximum_combo_fee_fraction_of_credit,
                "ratio",
            )
        else:
            gate = GateDistance(
                code=code,
                quantifiable=False,
                actual=None,
                threshold=None,
                signed_margin_to_pass=None,
                unit=None,
                explanation="该门槛是类别或组合层判断，不能诚实压缩成单一数值距离。",
            )
        if gate.signed_margin_to_pass is None or gate.signed_margin_to_pass < 0:
            distances.append(gate)
    return tuple(distances)


def _minimum_gate(code: str, actual: Decimal, threshold: Decimal, unit: str) -> GateDistance:
    return GateDistance(
        code=code,
        quantifiable=True,
        actual=actual,
        threshold=threshold,
        signed_margin_to_pass=actual - threshold,
        unit=unit,
        explanation="signed_margin_to_pass = actual - minimum；负数表示距通过还差多少。",
    )


def _maximum_gate(code: str, actual: Decimal, threshold: Decimal, unit: str) -> GateDistance:
    return GateDistance(
        code=code,
        quantifiable=True,
        actual=actual,
        threshold=threshold,
        signed_margin_to_pass=threshold - actual,
        unit=unit,
        explanation="signed_margin_to_pass = maximum - actual；负数表示超限多少。",
    )


def _session_verdict(
    *,
    unknown: int,
    captured: int,
    correct_avoidance: int,
    missed: int,
    over_risk: int,
) -> tuple[SessionVerdict, str]:
    if unknown:
        return (
            SessionVerdict.UNKNOWN,
            "Session 的 IV/RV 曲线、真实路径、结算或完整 Window 分母存在缺口，不能证明规则既不漏机会又不过度冒险。",
        )
    if missed and over_risk:
        return (
            SessionVerdict.MIXED_RULE_ERROR,
            "完整事后证据同时发现漏掉的低风险机会和 Base 选中的过度风险结构。",
        )
    if missed:
        return (
            SessionVerdict.RULE_TOO_CONSERVATIVE,
            "完整事后证据发现至少一个低风险短波机会，但 Base 没有选中。",
        )
    if over_risk:
        return (
            SessionVerdict.RULE_TOO_AGGRESSIVE,
            "完整事后证据发现至少一个 Base Candidate 的 IV/RV、路径或结算风险不合格。",
        )
    if captured:
        return (
            SessionVerdict.RULE_WELL_CALIBRATED,
            "本 Session 的完整事后证据显示 Base 抓住了低风险机会，且没有漏掉机会或选择过度风险结构。",
        )
    if correct_avoidance:
        return (
            SessionVerdict.NO_OPPORTUNITY_CORRECTLY_AVOIDED,
            "完整事后证据没有发现符合固定 Oracle 的机会，Base 也没有承担事后不合格风险。",
        )
    raise ValueError("complete Session requires at least one classified Window")


def _opportunity_definition_id(policy: BtcShortVolPolicy) -> str:
    return content_id(
        OPPORTUNITY_DEFINITION_NAMESPACE,
        {
            "version": HINDSIGHT_ORACLE_VERSION,
            "policy_id": policy.identity,
            "complete_session_curve_required": True,
            "decision_time_preserved": [
                "CAUSAL_COMPONENT_BOOKS",
                "FOUR_LEG_POLICY_GEOMETRY",
                "FULL_POLICY_AMOUNT_PRICING",
                "STANDARD_COMBO_COST",
                "BOUNDARY_REFERENCE_LOSS_CONTROL",
                "USD_CONTRACTUAL_PAYOFF_CAP_WITHIN_SESSION_LIMIT",
            ],
            "hindsight_realized_variance_method": HINDSIGHT_RV_METHOD,
            "opportunity_requires_all": [
                "ENTRY_IMPLIED_VARIANCE_PROXY_GT_HINDSIGHT_REALIZED_VARIANCE_PROXY",
                "NO_CONTINUOUS_PATH_SHORT_STRIKE_BREACH",
                "FEE_AFTER_OFFICIAL_SETTLEMENT_NATIVE_RESULT_GT_ZERO",
            ],
            "classification": [
                "CAPTURED_OPPORTUNITY",
                "CORRECT_AVOIDANCE",
                "MISSED_OPPORTUNITY",
                "OVER_RISK_SELECTION",
            ],
            "terminal_profit_alone": "INSUFFICIENT",
            "single_session_scope": "SESSION_LOCAL_POLICY_QUALITY_ONLY",
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
