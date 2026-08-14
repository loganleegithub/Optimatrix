from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self

from optimatrix.channels import ChannelId
from optimatrix.decision import DecisionRecord, DecisionResult, MarketObservation
from optimatrix.identity import canonical_identity, canonical_value, require_identity
from optimatrix.market import EventState, ExpirySettlementFact, OptionQuote
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.pricing import (
    Btc0DteCondorCloseProjection,
    Btc0DteCondorPricing,
    project_btc_0dte_condor_close,
    settle_btc_0dte_condor,
)
from optimatrix.products import BTC, ProductId
from optimatrix.radar import btc_environment_blockers
from optimatrix.risk import SHADOW_STRESS_BUDGET_METRIC, stress_reserve_from_allocation_record
from optimatrix.route import (
    RouteEvidenceStatus,
    ShadowRouteEvidence,
    component_synthetic_route_evidence,
)
from optimatrix.session import SessionPhase, current_deribit_session
from optimatrix.structure import Btc0DteCondorUnderwriting, underwrite_btc_0dte_condor

SHADOW_OUTCOME_EXPLANATION_METHOD_ID = canonical_identity(
    "ShadowOutcomeExplanationMethodV1",
    (
        "CAUSAL_MARKET_OBSERVATION_PREFIX",
        "ENTRY_NET_CREDIT_ZERO_BASELINE",
        "COMPONENT_SYNTHETIC_CLOSE_MFE_MAE",
        "OFFICIAL_SETTLEMENT_HOLD_COUNTERFACTUAL",
        "DECISION_BOUNDED_ALTERNATIVES",
    ),
)
SHADOW_ENTRY_BASELINE_METHOD_ID = canonical_identity(
    "ShadowPathValuationMethodV1", "ENTRY_NET_CREDIT_ZERO_BASELINE"
)
SHADOW_COMPONENT_CLOSE_METHOD_ID = canonical_identity(
    "ShadowPathValuationMethodV1", "COMPONENT_SYNTHETIC_CLOSE"
)
MAX_RETAINED_EXPLANATION_POINTS = 20


class ShadowEntryStatus(StrEnum):
    SHADOW_ATOMIC_EVALUABLE = "SHADOW_ATOMIC_EVALUABLE"
    SHADOW_ATOMIC_NOT_EVALUABLE = "SHADOW_ATOMIC_NOT_EVALUABLE"
    ENTRY_EVIDENCE_UNKNOWN = "ENTRY_EVIDENCE_UNKNOWN"
    ENTRY_THESIS_EXPIRED = "ENTRY_THESIS_EXPIRED"
    ENTRY_STRUCTURE_LIMIT_BREACHED = "ENTRY_STRUCTURE_LIMIT_BREACHED"
    ENTRY_PRICE_DETERIORATED = "ENTRY_PRICE_DETERIORATED"
    RISK_RESERVATION_INVALID = "RISK_RESERVATION_INVALID"


class PositionState(StrEnum):
    MONITORING = "MONITORING"
    EXIT_INTENT_FROZEN = "EXIT_INTENT_FROZEN"
    TERMINAL = "TERMINAL"


class PositionAction(StrEnum):
    HOLD = "HOLD"
    EXIT_WHOLE_PRODUCT = "EXIT_WHOLE_PRODUCT"
    SETTLE_AT_EXPIRY = "SETTLE_AT_EXPIRY"


class ObservationStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class TerminalMethod(StrEnum):
    NO_POSITION = "NO_POSITION"
    WHOLE_PRODUCT_EXIT = "WHOLE_PRODUCT_EXIT"
    CONTRACT_SETTLEMENT = "CONTRACT_SETTLEMENT"


class ShadowPathPhase(StrEnum):
    DECISION = "DECISION"
    ENTRY = "ENTRY"
    MONITOR = "MONITOR"
    EXIT = "EXIT"


class CounterfactualStatus(StrEnum):
    EVALUABLE = "EVALUABLE"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ExitCounterfactualKind(StrEnum):
    NO_ENTRY = "NO_ENTRY"
    HOLD_TO_EXPIRY = "HOLD_TO_EXPIRY"


class ShadowPathStatisticKind(StrEnum):
    MAXIMUM_FAVORABLE_EXCURSION_BTC = "MAXIMUM_FAVORABLE_EXCURSION_BTC"
    MAXIMUM_ADVERSE_EXCURSION_BTC = "MAXIMUM_ADVERSE_EXCURSION_BTC"
    MAXIMUM_FAVORABLE_EXCURSION_BOUNDARY_USD = "MAXIMUM_FAVORABLE_EXCURSION_BOUNDARY_USD"
    MAXIMUM_ADVERSE_EXCURSION_BOUNDARY_USD = "MAXIMUM_ADVERSE_EXCURSION_BOUNDARY_USD"
    MAXIMUM_SHORT_ABS_DELTA = "MAXIMUM_SHORT_ABS_DELTA"
    MINIMUM_PUT_SHORT_DISTANCE_USD = "MINIMUM_PUT_SHORT_DISTANCE_USD"
    MINIMUM_CALL_SHORT_DISTANCE_USD = "MINIMUM_CALL_SHORT_DISTANCE_USD"
    MINIMUM_IMPLIED_VARIANCE_PROXY = "MINIMUM_IMPLIED_VARIANCE_PROXY"
    MAXIMUM_IMPLIED_VARIANCE_PROXY = "MAXIMUM_IMPLIED_VARIANCE_PROXY"
    MINIMUM_TRAILING_RV_PROXY = "MINIMUM_TRAILING_RV_PROXY"
    MAXIMUM_TRAILING_RV_PROXY = "MAXIMUM_TRAILING_RV_PROXY"
    MINIMUM_SHORT_MARK_IV = "MINIMUM_SHORT_MARK_IV"
    MAXIMUM_SHORT_MARK_IV = "MAXIMUM_SHORT_MARK_IV"
    MAXIMUM_RV_ACCELERATION = "MAXIMUM_RV_ACCELERATION"
    MAXIMUM_JUMP_SHARE = "MAXIMUM_JUMP_SHARE"
    MAXIMUM_DIRECTIONAL_PERSISTENCE = "MAXIMUM_DIRECTIONAL_PERSISTENCE"


@dataclass(frozen=True)
class EligibilityFact:
    value: bool | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("eligibility reason must be non-empty")

    def as_object(self) -> dict[str, object]:
        return {"value": self.value, "reason": self.reason}

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "eligibility")
        result = item.get("value")
        if result is not None and not isinstance(result, bool):
            raise ValueError("eligibility.value must be boolean or null")
        return cls(result, _text(item, "reason"))


@dataclass(frozen=True)
class OutcomeEligibility:
    decision_evaluable: EligibilityFact
    future_path_known: EligibilityFact
    future_path_continuous: EligibilityFact
    shadow_entry_evaluable: EligibilityFact
    terminal_economics_evaluable: EligibilityFact
    live_execution_attributable: EligibilityFact
    strategy_population_eligible: EligibilityFact
    qualification_eligible: EligibilityFact

    def as_object(self) -> dict[str, object]:
        return {name: getattr(self, name).as_object() for name in self.__dataclass_fields__}

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "eligibility")
        return cls(
            **{
                name: EligibilityFact.from_object(item.get(name))
                for name in cls.__dataclass_fields__
            }
        )


def window_outcome_eligibility(
    *,
    decision_evaluable: bool,
    future_path_known: bool,
    future_path_continuous: bool | None,
) -> OutcomeEligibility:
    if future_path_known and future_path_continuous is None:
        raise ValueError("known future path requires a continuity fact")
    if not future_path_known and future_path_continuous is not None:
        raise ValueError("unknown future path cannot claim continuity")
    if not future_path_known:
        population = EligibilityFact(None, "FUTURE_PATH_UNKNOWN")
    elif not future_path_continuous:
        population = EligibilityFact(False, "FUTURE_PATH_DISCONTINUOUS")
    else:
        population = EligibilityFact(True, "ALIGNED_WINDOW_PATH_AVAILABLE")
    return OutcomeEligibility(
        decision_evaluable=EligibilityFact(
            decision_evaluable,
            "DECISION_EVALUABLE" if decision_evaluable else "DECISION_UNKNOWN",
        ),
        future_path_known=EligibilityFact(
            future_path_known,
            "FUTURE_PATH_KNOWN" if future_path_known else "FUTURE_PATH_UNKNOWN",
        ),
        future_path_continuous=EligibilityFact(
            future_path_continuous,
            (
                "FUTURE_PATH_CONTINUOUS"
                if future_path_continuous
                else "FUTURE_PATH_DISCONTINUOUS"
                if future_path_continuous is False
                else "FUTURE_PATH_UNKNOWN"
            ),
        ),
        shadow_entry_evaluable=EligibilityFact(None, "CASE_OUTCOME_OWNS_ENTRY"),
        terminal_economics_evaluable=EligibilityFact(None, "CASE_OUTCOME_OWNS_ECONOMICS"),
        live_execution_attributable=EligibilityFact(False, "PUBLIC_WINDOW_HAS_NO_EXECUTION"),
        strategy_population_eligible=population,
        qualification_eligible=EligibilityFact(None, "POLICY_NOT_QUALIFIED"),
    )


@dataclass(frozen=True)
class ExitIntent:
    category: str
    reason: str
    observation_id: str
    observed_at: datetime
    known_at: datetime
    source: str
    policy_id: str
    scope: str = "WHOLE_PRODUCT"

    def __post_init__(self) -> None:
        if not self.category or not self.reason or not self.source:
            raise ValueError("ExitIntent text fields must be non-empty")
        if self.scope != "WHOLE_PRODUCT":
            raise ValueError("B3 ExitIntent scope must be WHOLE_PRODUCT")
        require_identity(self.observation_id, "observation_id")
        require_identity(self.policy_id, "policy_id")
        if _utc(self.observed_at, "observed_at") > _utc(self.known_at, "known_at"):
            raise ValueError("ExitIntent cannot be known before observation")

    @property
    def identity(self) -> str:
        return canonical_identity("ExitIntentV1", self)

    def as_object(self) -> dict[str, object]:
        return _canonical_object(self)

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "exit_intent")
        return cls(
            category=_text(item, "category"),
            reason=_text(item, "reason"),
            observation_id=_text(item, "observation_id"),
            observed_at=_datetime(item, "observed_at"),
            known_at=_datetime(item, "known_at"),
            source=_text(item, "source"),
            policy_id=_text(item, "policy_id"),
            scope=_text(item, "scope"),
        )


@dataclass(frozen=True)
class EntryUnderwritingMetrics:
    vrp_proxy_ratio: Decimal | None
    short_put_abs_delta: Decimal | None
    short_call_abs_delta: Decimal | None
    net_delta: Decimal | None
    put_body_distance_sigma: Decimal | None
    call_body_distance_sigma: Decimal | None
    boundary_net_credit_usd: Decimal | None
    credit_to_payoff_cap: Decimal | None
    boundary_reference_loss_usd: Decimal | None
    combo_fee_fraction_of_credit: Decimal | None

    def as_object(self) -> dict[str, object]:
        return _canonical_object(self)

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "entry_underwriting_metrics")
        return cls(**{name: _optional_decimal(item, name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ShadowEntryReunderwriting:
    status: ShadowEntryStatus
    final: bool
    observation_id: str | None
    observed_at: datetime | None
    observation_known_at: datetime | None
    known_at: datetime
    reason: str | None
    policy_id: str
    selected_structure_id: str
    risk_allocation_id: str
    route_evidence: ShadowRouteEvidence
    market_session_id: str | None
    decision_session_phase: SessionPhase
    entry_session_phase: SessionPhase | None
    decision_metrics: EntryUnderwritingMetrics
    entry_metrics: EntryUnderwritingMetrics
    evidence_blockers: tuple[str, ...]
    environment_blockers: tuple[str, ...]
    structure_blockers: tuple[str, ...]
    economics_blockers: tuple[str, ...]
    allocation_blockers: tuple[str, ...]
    native_net_credit: Decimal | None
    combo_fee_native: Decimal | None
    boundary_index_price_usd: Decimal | None

    def __post_init__(self) -> None:
        require_identity(self.policy_id, "policy_id")
        require_identity(self.selected_structure_id, "selected_structure_id")
        require_identity(self.risk_allocation_id, "risk_allocation_id")
        evaluated_at = _utc(self.known_at, "known_at")
        if self.observation_id is None:
            if self.observed_at is not None or self.observation_known_at is not None:
                raise ValueError("Entry observation boundaries require an observation identity")
        else:
            require_identity(self.observation_id, "observation_id")
            if self.observed_at is None or self.observation_known_at is None:
                raise ValueError("Entry observation identity requires both source boundaries")
            if _utc(self.observed_at, "observed_at") > _utc(
                self.observation_known_at,
                "observation_known_at",
            ):
                raise ValueError("Entry observation cannot be known before it is observed")
            if (
                self.status is not ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
                and _utc(self.observation_known_at, "observation_known_at") > evaluated_at
            ):
                raise ValueError("Entry reunderwriting cannot use future knowledge")
        blocker_groups = (
            self.evidence_blockers,
            self.environment_blockers,
            self.structure_blockers,
            self.economics_blockers,
            self.allocation_blockers,
        )
        if any(len(set(group)) != len(group) for group in blocker_groups):
            raise ValueError("Entry reunderwriting blockers must be unique within each dimension")
        status_blockers = {
            ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN: self.evidence_blockers,
            ShadowEntryStatus.ENTRY_THESIS_EXPIRED: self.environment_blockers,
            ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED: self.structure_blockers,
            ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE: (),
            ShadowEntryStatus.ENTRY_PRICE_DETERIORATED: self.economics_blockers,
            ShadowEntryStatus.RISK_RESERVATION_INVALID: self.allocation_blockers,
            ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE: (),
        }[self.status]
        blockers = tuple(blocker for group in blocker_groups for blocker in group)
        expected_reason = (
            self.route_evidence.reason
            if self.status is ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE
            else (status_blockers[0] if status_blockers else None)
        )
        if self.reason != expected_reason:
            raise ValueError("Entry reason must identify the status-owning blocker")
        if (
            self.route_evidence.policy_id != self.policy_id
            or self.route_evidence.selected_structure_id != self.selected_structure_id
            or self.route_evidence.evaluated_at != self.known_at
        ):
            raise ValueError("Entry route evidence does not bind its reunderwriting")
        if self.route_evidence.observation_id is not None and (
            self.route_evidence.observation_id != self.observation_id
            or self.route_evidence.observed_at != self.observed_at
            or self.route_evidence.observation_known_at != self.observation_known_at
        ):
            raise ValueError("Entry route source does not match its reunderwriting observation")
        if self.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN:
            if (
                not self.evidence_blockers
                or self.route_evidence.status is not RouteEvidenceStatus.UNKNOWN
                or self.route_evidence.reason != self.evidence_blockers[0]
            ):
                raise ValueError("unknown Entry requires matching unknown route evidence")
        elif self.route_evidence.status is RouteEvidenceStatus.UNKNOWN:
            raise ValueError("unknown route evidence requires unknown Entry evidence")
        if self.status is ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE and (
            self.route_evidence.status is not RouteEvidenceStatus.NOT_EVALUABLE
        ):
            raise ValueError("not-evaluable Entry requires not-evaluable route evidence")
        if (
            self.status
            in {
                ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE,
                ShadowEntryStatus.ENTRY_PRICE_DETERIORATED,
                ShadowEntryStatus.RISK_RESERVATION_INVALID,
            }
            and self.route_evidence.status is not RouteEvidenceStatus.EVALUABLE
        ):
            raise ValueError(
                "economic or allocation Entry result requires evaluable route evidence"
            )
        if self.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
            if not self.final or blockers:
                raise ValueError("evaluable Entry requires one final blocker-free reunderwriting")
            if self.route_evidence.status is not RouteEvidenceStatus.EVALUABLE:
                raise ValueError("evaluable Entry requires evaluable route evidence")
            if any(value is None for value in self.entry_metrics.__dict__.values()):
                raise ValueError("evaluable Entry requires complete current Policy metrics")
            if (
                self.native_net_credit is None
                or self.combo_fee_native is None
                or self.boundary_index_price_usd is None
            ):
                raise ValueError("evaluable Entry requires complete Shadow economics")
            if (
                self.native_net_credit != self.route_evidence.native_net_credit
                or self.combo_fee_native != self.route_evidence.standard_combo_fee_projection_native
                or self.boundary_index_price_usd != self.route_evidence.boundary_index_price_usd
            ):
                raise ValueError("Entry economics do not match route evidence")
        elif self.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN:
            if not self.evidence_blockers:
                raise ValueError("unknown Entry evidence requires an evidence blocker")
        elif not self.final:
            raise ValueError("known Entry rejection must be final")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowEntryReunderwritingV2", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["decision_metrics"] = self.decision_metrics.as_object()
        value["entry_metrics"] = self.entry_metrics.as_object()
        value["route_evidence"] = self.route_evidence.as_object()
        value["entry_reunderwriting_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "entry_reunderwriting")
        result = cls(
            status=ShadowEntryStatus(_text(item, "status")),
            final=_boolean(item, "final"),
            observation_id=_optional_text(item, "observation_id"),
            observed_at=_optional_datetime(item, "observed_at"),
            observation_known_at=_optional_datetime(item, "observation_known_at"),
            known_at=_datetime(item, "known_at"),
            reason=_optional_text(item, "reason"),
            policy_id=_text(item, "policy_id"),
            selected_structure_id=_text(item, "selected_structure_id"),
            risk_allocation_id=_text(item, "risk_allocation_id"),
            route_evidence=ShadowRouteEvidence.from_object(item.get("route_evidence")),
            market_session_id=_optional_text(item, "market_session_id"),
            decision_session_phase=SessionPhase(_text(item, "decision_session_phase")),
            entry_session_phase=(
                SessionPhase(value)
                if (value := _optional_text(item, "entry_session_phase")) is not None
                else None
            ),
            decision_metrics=EntryUnderwritingMetrics.from_object(item.get("decision_metrics")),
            entry_metrics=EntryUnderwritingMetrics.from_object(item.get("entry_metrics")),
            evidence_blockers=_text_tuple(item, "evidence_blockers"),
            environment_blockers=_text_tuple(item, "environment_blockers"),
            structure_blockers=_text_tuple(item, "structure_blockers"),
            economics_blockers=_text_tuple(item, "economics_blockers"),
            allocation_blockers=_text_tuple(item, "allocation_blockers"),
            native_net_credit=_optional_decimal(item, "native_net_credit"),
            combo_fee_native=_optional_decimal(item, "combo_fee_native"),
            boundary_index_price_usd=_optional_decimal(item, "boundary_index_price_usd"),
        )
        if _text(item, "entry_reunderwriting_id") != result.identity:
            raise ValueError("Entry reunderwriting identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowPathPoint:
    phase: ShadowPathPhase
    observation_status: ObservationStatus
    observation_id: str
    observed_at: datetime
    known_at: datetime
    reunderwriting_id: str | None
    index_price_usd: Decimal | None
    native_result_btc: Decimal | None
    boundary_reference_result_usd: Decimal | None
    combo_fee_native: Decimal | None
    short_put_abs_delta: Decimal | None
    short_call_abs_delta: Decimal | None
    net_delta: Decimal | None
    put_short_distance_usd: Decimal | None
    call_short_distance_usd: Decimal | None
    long_put_mark_iv: Decimal | None
    short_put_mark_iv: Decimal | None
    short_call_mark_iv: Decimal | None
    long_call_mark_iv: Decimal | None
    same_session_implied_variance_proxy: Decimal | None
    trailing_realized_variance_proxy: Decimal | None
    rv_acceleration: Decimal | None
    jump_share: Decimal | None
    directional_persistence: Decimal | None
    event_state: EventState | None
    valuation_method_id: str | None
    valuation_reason: str | None
    reason: str | None

    def __post_init__(self) -> None:
        require_identity(self.observation_id, "observation_id")
        observed_at = _utc(self.observed_at, "observed_at")
        if observed_at > _utc(self.known_at, "known_at"):
            raise ValueError("explanation point cannot be known before its observation")
        if self.reunderwriting_id is not None:
            require_identity(self.reunderwriting_id, "reunderwriting_id")
            if self.phase is not ShadowPathPhase.ENTRY:
                raise ValueError("only an Entry point may bind reunderwriting")
        market_values = (
            self.index_price_usd,
            self.short_put_abs_delta,
            self.short_call_abs_delta,
            self.net_delta,
            self.put_short_distance_usd,
            self.call_short_distance_usd,
            self.long_put_mark_iv,
            self.short_put_mark_iv,
            self.short_call_mark_iv,
            self.long_call_mark_iv,
            self.same_session_implied_variance_proxy,
            self.trailing_realized_variance_proxy,
            self.rv_acceleration,
            self.jump_share,
            self.directional_persistence,
            self.event_state,
        )
        if self.observation_status is ObservationStatus.UNKNOWN:
            if not self.reason or any(value is not None for value in market_values):
                raise ValueError("unknown explanation point cannot claim known market metrics")
            if any(
                value is not None
                for value in (
                    self.native_result_btc,
                    self.boundary_reference_result_usd,
                    self.combo_fee_native,
                    self.valuation_method_id,
                    self.valuation_reason,
                )
            ):
                raise ValueError("unknown explanation point cannot claim a valuation")
            return
        if self.reason is not None or any(value is None for value in market_values):
            raise ValueError("known explanation point requires complete market metrics")
        assert self.index_price_usd is not None
        if not self.index_price_usd.is_finite() or self.index_price_usd <= 0:
            raise ValueError("explanation index price must be finite and positive")
        bounded_deltas = (
            self.short_put_abs_delta,
            self.short_call_abs_delta,
            self.net_delta,
        )
        if any(
            value is None or not value.is_finite() or abs(value) > 1 for value in bounded_deltas
        ):
            raise ValueError("explanation Deltas must be finite and bounded")
        positive_values = (
            self.long_put_mark_iv,
            self.short_put_mark_iv,
            self.short_call_mark_iv,
            self.long_call_mark_iv,
            self.same_session_implied_variance_proxy,
            self.trailing_realized_variance_proxy,
        )
        if any(value is None or not value.is_finite() or value <= 0 for value in positive_values):
            raise ValueError("explanation IV/RV values must be finite and positive")
        fractions = (self.rv_acceleration, self.jump_share, self.directional_persistence)
        if any(
            value is None or not value.is_finite() or not Decimal(0) <= value <= Decimal(1)
            for value in fractions
        ):
            raise ValueError("explanation path fractions must be in [0, 1]")
        distances = (self.put_short_distance_usd, self.call_short_distance_usd)
        if any(value is None or not value.is_finite() for value in distances):
            raise ValueError("short-strike distances must be finite")
        valuation = (
            self.native_result_btc,
            self.boundary_reference_result_usd,
            self.valuation_method_id,
        )
        if any(value is None for value in valuation) != all(value is None for value in valuation):
            raise ValueError("whole-product valuation fields must appear together")
        if self.native_result_btc is None:
            if not self.valuation_reason or self.combo_fee_native is not None:
                raise ValueError("missing whole-product valuation requires one exact reason")
        else:
            assert self.boundary_reference_result_usd is not None
            if (
                not self.native_result_btc.is_finite()
                or not self.boundary_reference_result_usd.is_finite()
                or self.valuation_reason is not None
            ):
                raise ValueError("known whole-product valuation must be finite and blocker-free")
            if self.combo_fee_native is not None and (
                not self.combo_fee_native.is_finite() or self.combo_fee_native < 0
            ):
                raise ValueError("Combo fee projection must be finite and non-negative")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowPathPointV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["path_point_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_path_point")
        result = cls(
            phase=ShadowPathPhase(_text(item, "phase")),
            observation_status=ObservationStatus(_text(item, "observation_status")),
            observation_id=_text(item, "observation_id"),
            observed_at=_datetime(item, "observed_at"),
            known_at=_datetime(item, "known_at"),
            reunderwriting_id=_optional_text(item, "reunderwriting_id"),
            index_price_usd=_optional_decimal(item, "index_price_usd"),
            native_result_btc=_optional_decimal(item, "native_result_btc"),
            boundary_reference_result_usd=_optional_decimal(item, "boundary_reference_result_usd"),
            combo_fee_native=_optional_decimal(item, "combo_fee_native"),
            short_put_abs_delta=_optional_decimal(item, "short_put_abs_delta"),
            short_call_abs_delta=_optional_decimal(item, "short_call_abs_delta"),
            net_delta=_optional_decimal(item, "net_delta"),
            put_short_distance_usd=_optional_decimal(item, "put_short_distance_usd"),
            call_short_distance_usd=_optional_decimal(item, "call_short_distance_usd"),
            long_put_mark_iv=_optional_decimal(item, "long_put_mark_iv"),
            short_put_mark_iv=_optional_decimal(item, "short_put_mark_iv"),
            short_call_mark_iv=_optional_decimal(item, "short_call_mark_iv"),
            long_call_mark_iv=_optional_decimal(item, "long_call_mark_iv"),
            same_session_implied_variance_proxy=_optional_decimal(
                item, "same_session_implied_variance_proxy"
            ),
            trailing_realized_variance_proxy=_optional_decimal(
                item, "trailing_realized_variance_proxy"
            ),
            rv_acceleration=_optional_decimal(item, "rv_acceleration"),
            jump_share=_optional_decimal(item, "jump_share"),
            directional_persistence=_optional_decimal(item, "directional_persistence"),
            event_state=(
                EventState(event_state)
                if (event_state := _optional_text(item, "event_state")) is not None
                else None
            ),
            valuation_method_id=_optional_text(item, "valuation_method_id"),
            valuation_reason=_optional_text(item, "valuation_reason"),
            reason=_optional_text(item, "reason"),
        )
        if _text(item, "path_point_id") != result.identity:
            raise ValueError("Shadow path point identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowPathStatistic:
    kind: ShadowPathStatisticKind
    value: Decimal
    observation_id: str
    observed_at: datetime
    known_at: datetime

    def __post_init__(self) -> None:
        require_identity(self.observation_id, "observation_id")
        observed_at = _utc(self.observed_at, "observed_at")
        if observed_at > _utc(self.known_at, "known_at"):
            raise ValueError("path statistic cannot be known before its observation")
        if not self.value.is_finite():
            raise ValueError("path statistic value must be finite")
        if (
            self.kind
            in {
                ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BTC,
                ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BTC,
                ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BOUNDARY_USD,
                ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BOUNDARY_USD,
                ShadowPathStatisticKind.MAXIMUM_SHORT_ABS_DELTA,
                ShadowPathStatisticKind.MINIMUM_IMPLIED_VARIANCE_PROXY,
                ShadowPathStatisticKind.MAXIMUM_IMPLIED_VARIANCE_PROXY,
                ShadowPathStatisticKind.MINIMUM_TRAILING_RV_PROXY,
                ShadowPathStatisticKind.MAXIMUM_TRAILING_RV_PROXY,
                ShadowPathStatisticKind.MINIMUM_SHORT_MARK_IV,
                ShadowPathStatisticKind.MAXIMUM_SHORT_MARK_IV,
                ShadowPathStatisticKind.MAXIMUM_RV_ACCELERATION,
                ShadowPathStatisticKind.MAXIMUM_JUMP_SHARE,
                ShadowPathStatisticKind.MAXIMUM_DIRECTIONAL_PERSISTENCE,
            }
            and self.value < 0
        ):
            raise ValueError("non-negative path statistic cannot be negative")
        if (
            self.kind
            in {
                ShadowPathStatisticKind.MAXIMUM_SHORT_ABS_DELTA,
                ShadowPathStatisticKind.MAXIMUM_RV_ACCELERATION,
                ShadowPathStatisticKind.MAXIMUM_JUMP_SHARE,
                ShadowPathStatisticKind.MAXIMUM_DIRECTIONAL_PERSISTENCE,
            }
            and self.value > 1
        ):
            raise ValueError("bounded path statistic must be in [0, 1]")
        if (
            self.kind
            in {
                ShadowPathStatisticKind.MINIMUM_IMPLIED_VARIANCE_PROXY,
                ShadowPathStatisticKind.MAXIMUM_IMPLIED_VARIANCE_PROXY,
                ShadowPathStatisticKind.MINIMUM_TRAILING_RV_PROXY,
                ShadowPathStatisticKind.MAXIMUM_TRAILING_RV_PROXY,
                ShadowPathStatisticKind.MINIMUM_SHORT_MARK_IV,
                ShadowPathStatisticKind.MAXIMUM_SHORT_MARK_IV,
            }
            and self.value <= 0
        ):
            raise ValueError("IV/RV path statistic must be positive")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowPathStatisticV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["path_statistic_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_path_statistic")
        result = cls(
            kind=ShadowPathStatisticKind(_text(item, "kind")),
            value=_decimal(item, "value"),
            observation_id=_text(item, "observation_id"),
            observed_at=_datetime(item, "observed_at"),
            known_at=_datetime(item, "known_at"),
        )
        if _text(item, "path_statistic_id") != result.identity:
            raise ValueError("Shadow path statistic identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowPathGap:
    known_at: datetime
    reason: str
    source: str
    observation_id: str | None = None
    observed_at: datetime | None = None
    reunderwriting_id: str | None = None

    def __post_init__(self) -> None:
        known_at = _utc(self.known_at, "known_at")
        if not self.reason or not self.source:
            raise ValueError("explanation Gap requires a reason and source")
        if (self.observation_id is None) != (self.observed_at is None):
            raise ValueError("Gap observation identity and source boundary must appear together")
        if self.observation_id is not None:
            require_identity(self.observation_id, "observation_id")
            assert self.observed_at is not None
            if _utc(self.observed_at, "observed_at") > known_at:
                raise ValueError("Gap cannot be known before its observation")
        if self.reunderwriting_id is not None:
            require_identity(self.reunderwriting_id, "reunderwriting_id")
            if self.source != "ENTRY_EVALUATION":
                raise ValueError("only an Entry-evaluation Gap may bind reunderwriting")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowPathGapV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["path_gap_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_path_gap")
        result = cls(
            known_at=_datetime(item, "known_at"),
            reason=_text(item, "reason"),
            source=_text(item, "source"),
            observation_id=_optional_text(item, "observation_id"),
            observed_at=_optional_datetime(item, "observed_at"),
            reunderwriting_id=_optional_text(item, "reunderwriting_id"),
        )
        if _text(item, "path_gap_id") != result.identity:
            raise ValueError("Shadow path Gap identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowAlternativeEntryBasis:
    candidate_id: str
    status: CounterfactualStatus
    route_evidence: ShadowRouteEvidence | None
    blockers: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        require_identity(self.candidate_id, "candidate_id")
        if len(set(self.blockers)) != len(self.blockers):
            raise ValueError("alternative Entry blockers must be unique")
        route = self.route_evidence
        if route is not None and route.selected_structure_id != self.candidate_id:
            raise ValueError("alternative Entry route does not bind its Candidate")
        if self.status is CounterfactualStatus.EVALUABLE:
            if (
                route is None
                or route.status is not RouteEvidenceStatus.EVALUABLE
                or self.blockers
                or self.reason is not None
            ):
                raise ValueError("evaluable alternative Entry requires complete route economics")
        elif self.status is CounterfactualStatus.UNKNOWN:
            if (
                route is None
                or route.status is not RouteEvidenceStatus.UNKNOWN
                or not self.reason
                or self.reason != route.reason
            ):
                raise ValueError("unknown alternative Entry requires matching route evidence")
        elif self.status is CounterfactualStatus.NOT_EVALUABLE:
            expected = self.blockers[0] if self.blockers else route.reason if route else None
            if route is None or not expected or self.reason != expected:
                raise ValueError("not-evaluable alternative Entry requires an exact blocker")
        elif route is not None or self.blockers or not self.reason:
            raise ValueError("not-applicable alternative Entry cannot claim route evidence")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowAlternativeEntryBasisV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["route_evidence"] = (
            self.route_evidence.as_object() if self.route_evidence is not None else None
        )
        value["alternative_entry_basis_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "alternative_entry_basis")
        result = cls(
            candidate_id=_text(item, "candidate_id"),
            status=CounterfactualStatus(_text(item, "status")),
            route_evidence=(
                ShadowRouteEvidence.from_object(item.get("route_evidence"))
                if item.get("route_evidence") is not None
                else None
            ),
            blockers=_text_tuple(item, "blockers"),
            reason=_optional_text(item, "reason"),
        )
        if _text(item, "alternative_entry_basis_id") != result.identity:
            raise ValueError("alternative Entry basis identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowExplanationPath:
    decision_record_id: str
    policy_id: str
    selected_structure_id: str
    observation_count: int
    last_observation_id: str
    last_observed_at: datetime
    points: tuple[ShadowPathPoint, ...]
    statistics: tuple[ShadowPathStatistic, ...]
    gaps: tuple[ShadowPathGap, ...]
    alternative_entry_bases: tuple[ShadowAlternativeEntryBasis, ...]

    def __post_init__(self) -> None:
        for value, field in (
            (self.decision_record_id, "decision_record_id"),
            (self.policy_id, "policy_id"),
            (self.selected_structure_id, "selected_structure_id"),
        ):
            require_identity(value, field)
        if not self.points or self.points[0].phase is not ShadowPathPhase.DECISION:
            raise ValueError("explanation path must begin at the Decision")
        if self.observation_count < len(self.points) or self.observation_count < 1:
            raise ValueError("explanation observation count cannot omit retained points")
        require_identity(self.last_observation_id, "last_observation_id")
        last_observed_at = _utc(self.last_observed_at, "last_observed_at")
        if len(self.points) > MAX_RETAINED_EXPLANATION_POINTS:
            raise ValueError("explanation path exceeds its retained-point bound")
        if any(
            current.observed_at <= previous.observed_at
            for previous, current in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError("explanation market points must be strictly chronological")
        if len({point.identity for point in self.points}) != len(self.points):
            raise ValueError("explanation path points must be unique")
        phase_order = {
            ShadowPathPhase.DECISION: 0,
            ShadowPathPhase.ENTRY: 1,
            ShadowPathPhase.MONITOR: 2,
            ShadowPathPhase.EXIT: 3,
        }
        if any(
            phase_order[current.phase] < phase_order[previous.phase]
            for previous, current in zip(self.points, self.points[1:], strict=False)
        ):
            raise ValueError("explanation path phases cannot move backwards")
        if self.points[-1].observed_at > last_observed_at:
            raise ValueError("explanation path cursor cannot precede a retained point")
        if self.points[-1].observed_at == last_observed_at and (
            self.points[-1].observation_id != self.last_observation_id
        ):
            raise ValueError("explanation path cursor must bind its latest retained point")
        if len({statistic.kind for statistic in self.statistics}) != len(self.statistics):
            raise ValueError("explanation statistics must bind distinct extrema")
        if tuple(statistic.kind for statistic in self.statistics) != tuple(
            sorted((statistic.kind for statistic in self.statistics), key=lambda item: item.value)
        ):
            raise ValueError("explanation statistics must preserve canonical kind order")
        if any(statistic.observed_at > last_observed_at for statistic in self.statistics):
            raise ValueError("explanation statistic cannot follow the observation cursor")
        if any(
            current.known_at < previous.known_at
            for previous, current in zip(self.gaps, self.gaps[1:], strict=False)
        ):
            raise ValueError("explanation Gaps must preserve known-at order")
        if len({gap.identity for gap in self.gaps}) != len(self.gaps):
            raise ValueError("explanation Gaps must be unique")
        if len({basis.candidate_id for basis in self.alternative_entry_bases}) != len(
            self.alternative_entry_bases
        ):
            raise ValueError("alternative Entry bases must bind distinct Candidates")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowExplanationPathV2", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["points"] = tuple(point.as_object() for point in self.points)
        value["statistics"] = tuple(statistic.as_object() for statistic in self.statistics)
        value["gaps"] = tuple(gap.as_object() for gap in self.gaps)
        value["alternative_entry_bases"] = tuple(
            basis.as_object() for basis in self.alternative_entry_bases
        )
        value["explanation_path_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_explanation_path")
        result = cls(
            decision_record_id=_text(item, "decision_record_id"),
            policy_id=_text(item, "policy_id"),
            selected_structure_id=_text(item, "selected_structure_id"),
            observation_count=_integer(item, "observation_count"),
            last_observation_id=_text(item, "last_observation_id"),
            last_observed_at=_datetime(item, "last_observed_at"),
            points=tuple(
                ShadowPathPoint.from_object(member) for member in _object_sequence(item, "points")
            ),
            statistics=tuple(
                ShadowPathStatistic.from_object(member)
                for member in _object_sequence(item, "statistics")
            ),
            gaps=tuple(
                ShadowPathGap.from_object(member) for member in _object_sequence(item, "gaps")
            ),
            alternative_entry_bases=tuple(
                ShadowAlternativeEntryBasis.from_object(member)
                for member in _object_sequence(item, "alternative_entry_bases")
            ),
        )
        if _text(item, "explanation_path_id") != result.identity:
            raise ValueError("Shadow explanation path identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowAlternativeOutcome:
    candidate_id: str
    entry_basis_id: str
    status: CounterfactualStatus
    terminal_method: TerminalMethod
    terminal_evidence_id: str | None
    known_at: datetime
    native_result_btc: Decimal | None
    boundary_reference_result_usd: Decimal | None
    entry_combo_fee_native: Decimal | None
    terminal_combo_fee_native: Decimal | None
    reason: str | None

    def __post_init__(self) -> None:
        require_identity(self.candidate_id, "candidate_id")
        require_identity(self.entry_basis_id, "entry_basis_id")
        _utc(self.known_at, "known_at")
        if self.terminal_evidence_id is not None:
            require_identity(self.terminal_evidence_id, "terminal_evidence_id")
        economics = (
            self.native_result_btc,
            self.boundary_reference_result_usd,
            self.entry_combo_fee_native,
        )
        if self.status is CounterfactualStatus.EVALUABLE:
            if (
                self.terminal_evidence_id is None
                or any(value is None for value in economics)
                or self.reason is not None
            ):
                raise ValueError("evaluable alternative Outcome requires complete economics")
            assert self.native_result_btc is not None
            assert self.boundary_reference_result_usd is not None
            assert self.entry_combo_fee_native is not None
            if any(
                not value.is_finite()
                for value in (
                    self.native_result_btc,
                    self.boundary_reference_result_usd,
                    self.entry_combo_fee_native,
                )
            ):
                raise ValueError("alternative Outcome economics must be finite")
            if self.entry_combo_fee_native < 0:
                raise ValueError("alternative Entry Combo fee must be non-negative")
            if self.terminal_combo_fee_native is not None and (
                not self.terminal_combo_fee_native.is_finite() or self.terminal_combo_fee_native < 0
            ):
                raise ValueError("alternative terminal Combo fee must be non-negative")
        elif any(value is not None for value in (*economics, self.terminal_combo_fee_native)) or (
            not self.reason
        ):
            raise ValueError("unevaluable alternative Outcome cannot claim economics")
        elif self.terminal_evidence_id is not None:
            raise ValueError("unevaluable alternative Outcome cannot claim terminal evidence")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowAlternativeOutcomeV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["alternative_outcome_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_alternative_outcome")
        result = cls(
            candidate_id=_text(item, "candidate_id"),
            entry_basis_id=_text(item, "entry_basis_id"),
            status=CounterfactualStatus(_text(item, "status")),
            terminal_method=TerminalMethod(_text(item, "terminal_method")),
            terminal_evidence_id=_optional_text(item, "terminal_evidence_id"),
            known_at=_datetime(item, "known_at"),
            native_result_btc=_optional_decimal(item, "native_result_btc"),
            boundary_reference_result_usd=_optional_decimal(item, "boundary_reference_result_usd"),
            entry_combo_fee_native=_optional_decimal(item, "entry_combo_fee_native"),
            terminal_combo_fee_native=_optional_decimal(item, "terminal_combo_fee_native"),
            reason=_optional_text(item, "reason"),
        )
        if _text(item, "alternative_outcome_id") != result.identity:
            raise ValueError("alternative Outcome identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowExitCounterfactual:
    kind: ExitCounterfactualKind
    status: CounterfactualStatus
    known_at: datetime
    terminal_evidence_id: str | None
    native_result_btc: Decimal | None
    boundary_reference_result_usd: Decimal | None
    fee_model_id: str | None
    reason: str | None

    def __post_init__(self) -> None:
        _utc(self.known_at, "known_at")
        if self.terminal_evidence_id is not None:
            require_identity(self.terminal_evidence_id, "terminal_evidence_id")
        economics = (self.native_result_btc, self.boundary_reference_result_usd)
        if self.status is CounterfactualStatus.EVALUABLE:
            if any(value is None for value in economics) or self.reason is not None:
                raise ValueError("evaluable exit counterfactual requires complete economics")
            assert self.native_result_btc is not None
            assert self.boundary_reference_result_usd is not None
            if not self.native_result_btc.is_finite() or not (
                self.boundary_reference_result_usd.is_finite()
            ):
                raise ValueError("exit counterfactual economics must be finite")
        elif any(value is not None for value in (*economics, self.fee_model_id)) or not self.reason:
            raise ValueError("unevaluable exit counterfactual cannot claim economics")
        elif self.terminal_evidence_id is not None:
            raise ValueError("unevaluable exit counterfactual cannot claim terminal evidence")
        if self.kind is ExitCounterfactualKind.NO_ENTRY:
            if (
                self.status is not CounterfactualStatus.EVALUABLE
                or self.terminal_evidence_id is not None
                or self.fee_model_id is not None
                or self.native_result_btc != 0
                or self.boundary_reference_result_usd != 0
            ):
                raise ValueError("no-entry counterfactual must be an exact zero baseline")
        elif self.status is CounterfactualStatus.EVALUABLE and (
            self.terminal_evidence_id is None or not self.fee_model_id
        ):
            raise ValueError("evaluable hold counterfactual requires settlement evidence and fee")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowExitCounterfactualV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["exit_counterfactual_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_exit_counterfactual")
        result = cls(
            kind=ExitCounterfactualKind(_text(item, "kind")),
            status=CounterfactualStatus(_text(item, "status")),
            known_at=_datetime(item, "known_at"),
            terminal_evidence_id=_optional_text(item, "terminal_evidence_id"),
            native_result_btc=_optional_decimal(item, "native_result_btc"),
            boundary_reference_result_usd=_optional_decimal(item, "boundary_reference_result_usd"),
            fee_model_id=_optional_text(item, "fee_model_id"),
            reason=_optional_text(item, "reason"),
        )
        if _text(item, "exit_counterfactual_id") != result.identity:
            raise ValueError("exit counterfactual identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowOutcomeExplanation:
    method_id: str
    path_id: str
    entry_reunderwriting_id: str
    decision_metrics: EntryUnderwritingMetrics
    entry_metrics: EntryUnderwritingMetrics
    maximum_favorable_excursion_btc: Decimal | None
    maximum_adverse_excursion_btc: Decimal | None
    maximum_favorable_excursion_boundary_usd: Decimal | None
    maximum_adverse_excursion_boundary_usd: Decimal | None
    maximum_short_abs_delta: Decimal | None
    minimum_put_short_distance_usd: Decimal | None
    minimum_call_short_distance_usd: Decimal | None
    put_short_breached: bool | None
    call_short_breached: bool | None
    gap_ids: tuple[str, ...]
    alternative_outcomes: tuple[ShadowAlternativeOutcome, ...]
    entry_combo_fee_native: Decimal | None
    terminal_combo_fee_native: Decimal | None
    total_combo_fee_native: Decimal | None
    primary_exit_category: str
    primary_exit_reason: str
    no_entry: ShadowExitCounterfactual
    hold_to_expiry: ShadowExitCounterfactual
    complete: bool

    def __post_init__(self) -> None:
        require_identity(self.method_id, "method_id")
        require_identity(self.path_id, "path_id")
        require_identity(self.entry_reunderwriting_id, "entry_reunderwriting_id")
        for gap_id in self.gap_ids:
            require_identity(gap_id, "gap_id")
        if len(set(self.gap_ids)) != len(self.gap_ids):
            raise ValueError("Outcome explanation Gap identities must be unique")
        if len({item.candidate_id for item in self.alternative_outcomes}) != len(
            self.alternative_outcomes
        ):
            raise ValueError("Outcome alternatives must bind distinct Candidates")
        excursions = (
            self.maximum_favorable_excursion_btc,
            self.maximum_adverse_excursion_btc,
            self.maximum_favorable_excursion_boundary_usd,
            self.maximum_adverse_excursion_boundary_usd,
        )
        if any(value is not None and (not value.is_finite() or value < 0) for value in excursions):
            raise ValueError("MFE/MAE values must be finite non-negative magnitudes")
        if self.maximum_short_abs_delta is not None and (
            not self.maximum_short_abs_delta.is_finite()
            or not Decimal(0) <= self.maximum_short_abs_delta <= Decimal(1)
        ):
            raise ValueError("maximum short Delta must be in [0, 1]")
        distances = (
            self.minimum_put_short_distance_usd,
            self.minimum_call_short_distance_usd,
        )
        if any(value is not None and not value.is_finite() for value in distances):
            raise ValueError("minimum short-strike distances must be finite")
        if (self.minimum_put_short_distance_usd is None) != (self.put_short_breached is None) or (
            self.minimum_call_short_distance_usd is None
        ) != (self.call_short_breached is None):
            raise ValueError("short-strike breach flags require matching distances")
        fees = (
            self.entry_combo_fee_native,
            self.terminal_combo_fee_native,
            self.total_combo_fee_native,
        )
        if any(value is not None and (not value.is_finite() or value < 0) for value in fees):
            raise ValueError("Outcome Combo fees must be finite and non-negative")
        if self.total_combo_fee_native is not None:
            if self.entry_combo_fee_native is None:
                raise ValueError("total Combo fee requires an Entry fee")
            expected = self.entry_combo_fee_native + (self.terminal_combo_fee_native or Decimal(0))
            if self.total_combo_fee_native != expected:
                raise ValueError("Outcome total Combo fee is incoherent")
        if not self.primary_exit_category or not self.primary_exit_reason:
            raise ValueError("Outcome explanation requires a primary terminal reason")
        if self.no_entry.kind is not ExitCounterfactualKind.NO_ENTRY:
            raise ValueError("Outcome explanation no-entry counterfactual kind is invalid")
        if self.hold_to_expiry.kind is not ExitCounterfactualKind.HOLD_TO_EXPIRY:
            raise ValueError("Outcome explanation hold counterfactual kind is invalid")
        if self.complete == (self.hold_to_expiry.status is CounterfactualStatus.UNKNOWN):
            raise ValueError("Outcome explanation completeness must match hold counterfactual")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowOutcomeExplanationV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["decision_metrics"] = self.decision_metrics.as_object()
        value["entry_metrics"] = self.entry_metrics.as_object()
        value["alternative_outcomes"] = tuple(
            item.as_object() for item in self.alternative_outcomes
        )
        value["no_entry"] = self.no_entry.as_object()
        value["hold_to_expiry"] = self.hold_to_expiry.as_object()
        value["outcome_explanation_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_outcome_explanation")
        result = cls(
            method_id=_text(item, "method_id"),
            path_id=_text(item, "path_id"),
            entry_reunderwriting_id=_text(item, "entry_reunderwriting_id"),
            decision_metrics=EntryUnderwritingMetrics.from_object(item.get("decision_metrics")),
            entry_metrics=EntryUnderwritingMetrics.from_object(item.get("entry_metrics")),
            maximum_favorable_excursion_btc=_optional_decimal(
                item, "maximum_favorable_excursion_btc"
            ),
            maximum_adverse_excursion_btc=_optional_decimal(item, "maximum_adverse_excursion_btc"),
            maximum_favorable_excursion_boundary_usd=_optional_decimal(
                item, "maximum_favorable_excursion_boundary_usd"
            ),
            maximum_adverse_excursion_boundary_usd=_optional_decimal(
                item, "maximum_adverse_excursion_boundary_usd"
            ),
            maximum_short_abs_delta=_optional_decimal(item, "maximum_short_abs_delta"),
            minimum_put_short_distance_usd=_optional_decimal(
                item, "minimum_put_short_distance_usd"
            ),
            minimum_call_short_distance_usd=_optional_decimal(
                item, "minimum_call_short_distance_usd"
            ),
            put_short_breached=_optional_boolean(item, "put_short_breached"),
            call_short_breached=_optional_boolean(item, "call_short_breached"),
            gap_ids=_text_tuple(item, "gap_ids"),
            alternative_outcomes=tuple(
                ShadowAlternativeOutcome.from_object(member)
                for member in _object_sequence(item, "alternative_outcomes")
            ),
            entry_combo_fee_native=_optional_decimal(item, "entry_combo_fee_native"),
            terminal_combo_fee_native=_optional_decimal(item, "terminal_combo_fee_native"),
            total_combo_fee_native=_optional_decimal(item, "total_combo_fee_native"),
            primary_exit_category=_text(item, "primary_exit_category"),
            primary_exit_reason=_text(item, "primary_exit_reason"),
            no_entry=ShadowExitCounterfactual.from_object(item.get("no_entry")),
            hold_to_expiry=ShadowExitCounterfactual.from_object(item.get("hold_to_expiry")),
            complete=_boolean(item, "complete"),
        )
        if _text(item, "outcome_explanation_id") != result.identity:
            raise ValueError("Outcome explanation identity mismatch")
        return result


@dataclass(frozen=True)
class ShadowMonitorEvaluation:
    observation_status: ObservationStatus
    observation_id: str
    observed_at: datetime
    management_action: PositionAction | None
    known_triggers: tuple[str, ...]
    current_native_result: Decimal | None
    exit_intent: ExitIntent | None
    reason: str | None


@dataclass(frozen=True)
class ShadowExitEvaluation:
    observation_status: ObservationStatus
    observation_id: str
    observed_at: datetime
    native_close_cashflow: Decimal | None
    native_result: Decimal | None
    terminal: bool
    reason: str | None


@dataclass(frozen=True)
class ShadowPosition:
    position_id: str
    trade_case_id: str
    truth_layer: str
    channel_id: ChannelId
    selected_structure_id: str
    option_amount: Decimal
    entry_observation_id: str
    entry_observed_at: datetime
    entry_native_net_credit: Decimal
    state: PositionState
    exit_intent: ExitIntent | None


@dataclass(frozen=True)
class FuturePathSummary:
    source_id: str
    method_id: str
    starts_at: datetime
    ends_at: datetime
    observation_count: int
    start_index_price_usd: Decimal
    end_index_price_usd: Decimal
    minimum_index_price_usd: Decimal
    maximum_index_price_usd: Decimal
    maximum_rv_acceleration: Decimal

    def __post_init__(self) -> None:
        if not self.source_id or not self.method_id:
            raise ValueError("future path source and method must be non-empty")
        if _utc(self.starts_at, "starts_at") > _utc(self.ends_at, "ends_at"):
            raise ValueError("future path boundaries are invalid")
        if self.observation_count <= 0:
            raise ValueError("future path requires a positive observation count")
        prices = (
            self.start_index_price_usd,
            self.end_index_price_usd,
            self.minimum_index_price_usd,
            self.maximum_index_price_usd,
        )
        if any(not price.is_finite() or price <= 0 for price in prices):
            raise ValueError("future path prices must be finite and positive")
        if not self.minimum_index_price_usd <= min(
            self.start_index_price_usd,
            self.end_index_price_usd,
        ) or not self.maximum_index_price_usd >= max(
            self.start_index_price_usd,
            self.end_index_price_usd,
        ):
            raise ValueError("future path extrema do not contain endpoints")
        if not self.maximum_rv_acceleration.is_finite() or not (
            Decimal(0) <= self.maximum_rv_acceleration <= Decimal(1)
        ):
            raise ValueError("future path RV acceleration must be in [0, 1]")

    def as_object(self) -> dict[str, object]:
        return _canonical_object(self)

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "future_path")
        return cls(
            source_id=_text(item, "source_id"),
            method_id=_text(item, "method_id"),
            starts_at=_datetime(item, "starts_at"),
            ends_at=_datetime(item, "ends_at"),
            observation_count=_integer(item, "observation_count"),
            start_index_price_usd=_decimal(item, "start_index_price_usd"),
            end_index_price_usd=_decimal(item, "end_index_price_usd"),
            minimum_index_price_usd=_decimal(item, "minimum_index_price_usd"),
            maximum_index_price_usd=_decimal(item, "maximum_index_price_usd"),
            maximum_rv_acceleration=_decimal(item, "maximum_rv_acceleration"),
        )


@dataclass(frozen=True)
class ShadowCaseOutcome:
    terminal_method: TerminalMethod
    terminal_at: datetime
    entry_status: ShadowEntryStatus
    entry_observation_id: str | None
    terminal_evidence_id: str | None
    native_result_btc: Decimal | None
    boundary_reference_result_usd: Decimal | None
    fee_model_id: str | None
    shadow_model_id: str | None
    terminal_source: str
    data_gap_observed: bool
    reason: str | None
    eligibility: OutcomeEligibility
    explanation: ShadowOutcomeExplanation

    def __post_init__(self) -> None:
        _utc(self.terminal_at, "terminal_at")
        if not self.terminal_source:
            raise ValueError("terminal_source must be non-empty")
        if self.terminal_evidence_id is not None:
            require_identity(self.terminal_evidence_id, "terminal_evidence_id")
        if self.data_gap_observed != bool(self.explanation.gap_ids):
            raise ValueError("Outcome Gap summary does not match its explanation")
        if self.entry_status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
            if self.explanation.entry_combo_fee_native is None:
                raise ValueError("entered Shadow Outcome requires its Entry Combo fee")
        elif self.explanation.entry_combo_fee_native is not None:
            raise ValueError("no-Position Outcome cannot claim an Entry Combo fee")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowCaseOutcomeV2", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["eligibility"] = self.eligibility.as_object()
        value["explanation"] = self.explanation.as_object()
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "shadow_case_outcome")
        return cls(
            terminal_method=TerminalMethod(_text(item, "terminal_method")),
            terminal_at=_datetime(item, "terminal_at"),
            entry_status=ShadowEntryStatus(_text(item, "entry_status")),
            entry_observation_id=_optional_text(item, "entry_observation_id"),
            terminal_evidence_id=_optional_text(item, "terminal_evidence_id"),
            native_result_btc=_optional_decimal(item, "native_result_btc"),
            boundary_reference_result_usd=_optional_decimal(item, "boundary_reference_result_usd"),
            fee_model_id=_optional_text(item, "fee_model_id"),
            shadow_model_id=_optional_text(item, "shadow_model_id"),
            terminal_source=_text(item, "terminal_source"),
            data_gap_observed=_boolean(item, "data_gap_observed"),
            reason=_optional_text(item, "reason"),
            eligibility=OutcomeEligibility.from_object(item.get("eligibility")),
            explanation=ShadowOutcomeExplanation.from_object(item.get("explanation")),
        )


@dataclass(frozen=True)
class WindowOutcome:
    decision_window_id: str
    horizon_starts_at: datetime
    horizon_ends_at: datetime
    known_at: datetime
    future_path_known: bool
    future_path_continuous: bool | None
    expiry_settlement: ExpirySettlementFact | None
    future_path: FuturePathSummary | None
    regime_labels: tuple[str, ...]
    reason: str | None
    eligibility: OutcomeEligibility

    def __post_init__(self) -> None:
        require_identity(self.decision_window_id, "decision_window_id")
        if _utc(self.horizon_starts_at, "horizon_starts_at") >= _utc(
            self.horizon_ends_at, "horizon_ends_at"
        ):
            raise ValueError("WindowOutcome horizon must have positive duration")
        if _utc(self.horizon_ends_at, "horizon_ends_at") > _utc(self.known_at, "known_at"):
            raise ValueError("WindowOutcome cannot be known before its horizon")
        if self.future_path_known and self.future_path_continuous is None:
            raise ValueError("known future path requires a continuity fact")
        if not self.future_path_known and self.future_path_continuous is not None:
            raise ValueError("unknown future path cannot claim continuity")
        if self.future_path_known != (self.future_path is not None):
            raise ValueError("known future path requires one path summary")
        if self.future_path is not None and (
            self.future_path.starts_at != self.horizon_starts_at
            or self.future_path.ends_at != self.horizon_ends_at
        ):
            raise ValueError("future path must cover the declared WindowOutcome horizon")
        if not self.future_path_known and not self.reason:
            raise ValueError("unknown future path requires a reason")
        if len(set(self.regime_labels)) != len(self.regime_labels):
            raise ValueError("WindowOutcome regime labels must be unique")
        if self.expiry_settlement is not None and self.expiry_settlement.known_at > self.known_at:
            raise ValueError("WindowOutcome cannot know settlement before its source fact")
        if self.eligibility.future_path_known.value is not self.future_path_known:
            raise ValueError("WindowOutcome future-path eligibility mismatch")
        if self.eligibility.future_path_continuous.value is not self.future_path_continuous:
            raise ValueError("WindowOutcome continuity eligibility mismatch")
        if self.eligibility.live_execution_attributable.value is not False:
            raise ValueError("Public WindowOutcome cannot attribute live execution")
        if self.eligibility.strategy_population_eligible.value is True and not (
            self.future_path_known and self.future_path_continuous
        ):
            raise ValueError("strategy population eligibility requires a continuous future path")
        if self.eligibility.qualification_eligible.value is True and (
            self.eligibility.strategy_population_eligible.value is not True
        ):
            raise ValueError("qualification eligibility requires strategy population eligibility")

    @property
    def identity(self) -> str:
        return canonical_identity("WindowOutcomeV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["future_path"] = (
            self.future_path.as_object() if self.future_path is not None else None
        )
        value["expiry_settlement"] = (
            self.expiry_settlement.as_object() if self.expiry_settlement is not None else None
        )
        value["eligibility"] = self.eligibility.as_object()
        value["window_outcome_id"] = self.identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "window_outcome")
        outcome = cls(
            decision_window_id=_text(item, "decision_window_id"),
            horizon_starts_at=_datetime(item, "horizon_starts_at"),
            horizon_ends_at=_datetime(item, "horizon_ends_at"),
            known_at=_datetime(item, "known_at"),
            future_path_known=_boolean(item, "future_path_known"),
            future_path_continuous=_optional_boolean(item, "future_path_continuous"),
            expiry_settlement=(
                ExpirySettlementFact.from_object(item.get("expiry_settlement"))
                if item.get("expiry_settlement") is not None
                else None
            ),
            future_path=(
                FuturePathSummary.from_object(item.get("future_path"))
                if item.get("future_path") is not None
                else None
            ),
            regime_labels=_text_tuple(item, "regime_labels"),
            reason=_optional_text(item, "reason"),
            eligibility=OutcomeEligibility.from_object(item.get("eligibility")),
        )
        if _text(item, "window_outcome_id") != outcome.identity:
            raise ValueError("WindowOutcome identity mismatch")
        return outcome


@dataclass(frozen=True)
class TradeCase:
    channel_id: ChannelId
    truth_layer: str
    decision_record_id: str
    decision_window_id: str
    decision_policy_id: str
    decision_boundary: datetime
    decision_session_phase: SessionPhase
    decision_vrp_proxy_ratio: Decimal
    selected_structure_id: str
    selected_structure_json: str
    risk_allocation_id: str
    risk_allocation_json: str
    opened_at: datetime
    entry_deadline: datetime
    decision_route_evidence_id: str
    decision_route_evidence_json: str
    explanation_path: ShadowExplanationPath
    entry_status: ShadowEntryStatus | None = None
    entry_final: bool = False
    entry_observation_id: str | None = None
    entry_observed_at: datetime | None = None
    entry_known_at: datetime | None = None
    entry_reason: str | None = None
    entry_reunderwriting_json: str | None = None
    entry_pricing_json: str | None = None
    position_id: str | None = None
    position_state: PositionState | None = None
    entry_native_net_credit: Decimal | None = None
    entry_index_price_usd: Decimal | None = None
    entry_vrp_proxy_ratio: Decimal | None = None
    last_observation_id: str | None = None
    last_observed_at: datetime | None = None
    exit_intent: ExitIntent | None = None
    outcome: ShadowCaseOutcome | None = None

    def __post_init__(self) -> None:
        if self.truth_layer != "SHADOW_PROJECTION":
            raise ValueError("B3 TradeCase truth layer must be SHADOW_PROJECTION")
        for value, field in (
            (self.decision_record_id, "decision_record_id"),
            (self.decision_window_id, "decision_window_id"),
            (self.decision_policy_id, "decision_policy_id"),
            (self.selected_structure_id, "selected_structure_id"),
            (self.risk_allocation_id, "risk_allocation_id"),
            (self.decision_route_evidence_id, "decision_route_evidence_id"),
        ):
            require_identity(value, field)
        boundary = _utc(self.decision_boundary, "decision_boundary")
        if _utc(self.opened_at, "opened_at") < boundary:
            raise ValueError("TradeCase cannot open before its Decision")
        if _utc(self.entry_deadline, "entry_deadline") <= boundary:
            raise ValueError("TradeCase Entry deadline must be after its Decision")
        if not self.decision_vrp_proxy_ratio.is_finite() or self.decision_vrp_proxy_ratio <= 0:
            raise ValueError("TradeCase Decision VRP proxy must be finite and positive")
        structure = self.selected_structure
        if structure.get("candidate_id") != self.selected_structure_id:
            raise ValueError("TradeCase structure identity mismatch")
        allocation = self.risk_allocation
        if allocation.get("allocation_id") != self.risk_allocation_id:
            raise ValueError("TradeCase allocation identity mismatch")
        if allocation.get("candidate_id") != self.selected_structure_id:
            raise ValueError("TradeCase allocation does not bind its structure")
        decision_route = self.decision_route_evidence
        if (
            decision_route.identity != self.decision_route_evidence_id
            or decision_route.status is not RouteEvidenceStatus.EVALUABLE
            or decision_route.policy_id != self.decision_policy_id
            or decision_route.selected_structure_id != self.selected_structure_id
            or decision_route.target_amount != _structure_amount(self)
            or decision_route.evaluated_at != self.decision_boundary
        ):
            raise ValueError("TradeCase Decision route evidence is incoherent")
        if tuple(leg.instrument_name for leg in decision_route.legs) != _structure_instrument_names(
            self
        ):
            raise ValueError("TradeCase Decision route legs do not match its structure")
        selected_pricing = _mapping(
            self.selected_structure.get("pricing"),
            "selected_structure.pricing",
        )
        if _route_economics(decision_route) != _recorded_pricing_economics(selected_pricing):
            raise ValueError("TradeCase Decision route economics do not match its structure")
        path = self.explanation_path
        if (
            path.decision_record_id != self.decision_record_id
            or path.policy_id != self.decision_policy_id
            or path.selected_structure_id != self.selected_structure_id
            or path.points[0].observation_id != decision_route.observation_id
        ):
            raise ValueError("TradeCase explanation path does not bind its frozen Decision")
        if self.last_observation_id is not None and (
            path.last_observation_id != self.last_observation_id
            or path.last_observed_at != self.last_observed_at
        ):
            raise ValueError("TradeCase latest observation does not match its explanation cursor")
        if self.entry_final and self.entry_status is None:
            raise ValueError("final Entry requires a status")
        if (self.entry_status is None) != (self.entry_reunderwriting_json is None):
            raise ValueError("Entry status and reunderwriting evidence must appear together")
        if not self.entry_final and (self.position_id is not None or self.outcome is not None):
            raise ValueError("provisional Entry cannot create Position or Outcome")
        if self.entry_status is not None and self.entry_known_at is None:
            raise ValueError("Entry evaluation requires a known-at boundary")
        reunderwriting = self.entry_reunderwriting
        if reunderwriting is not None and (
            reunderwriting.status is not self.entry_status
            or reunderwriting.final is not self.entry_final
            or reunderwriting.observation_id != self.entry_observation_id
            or reunderwriting.observed_at != self.entry_observed_at
            or reunderwriting.known_at != self.entry_known_at
            or reunderwriting.reason != self.entry_reason
            or reunderwriting.policy_id != self.decision_policy_id
            or reunderwriting.selected_structure_id != self.selected_structure_id
            or reunderwriting.risk_allocation_id != self.risk_allocation_id
            or reunderwriting.decision_session_phase is not self.decision_session_phase
            or reunderwriting.decision_metrics.vrp_proxy_ratio != self.decision_vrp_proxy_ratio
        ):
            raise ValueError("TradeCase Entry fields do not match reunderwriting evidence")
        if reunderwriting is not None:
            entry_evidence = [
                (point.known_at, point.reunderwriting_id)
                for point in path.points
                if point.phase is ShadowPathPhase.ENTRY and point.reunderwriting_id is not None
            ] + [
                (gap.known_at, gap.reunderwriting_id)
                for gap in path.gaps
                if gap.reunderwriting_id is not None
            ]
            if (
                not entry_evidence
                or max(entry_evidence, key=lambda item: item[0])[1] != reunderwriting.identity
            ):
                raise ValueError("TradeCase explanation path lacks its latest Entry evaluation")
            entry_pricing = self.entry_pricing
            route_is_evaluable = (
                reunderwriting.route_evidence.status is RouteEvidenceStatus.EVALUABLE
            )
            if route_is_evaluable != (entry_pricing is not None):
                raise ValueError("TradeCase Entry pricing does not match route evaluability")
            if entry_pricing is not None and (
                _route_economics(reunderwriting.route_evidence)
                != _recorded_pricing_economics(entry_pricing)
            ):
                raise ValueError("TradeCase Entry route economics do not match its pricing")
        elif any(point.phase is ShadowPathPhase.ENTRY for point in path.points) or any(
            gap.reunderwriting_id is not None for gap in path.gaps
        ):
            raise ValueError("TradeCase cannot retain Entry path facts before Entry evaluation")
        alternatives = _structure_alternatives(self)
        basis_ids = tuple(basis.candidate_id for basis in path.alternative_entry_bases)
        expected_alternative_ids = tuple(_text(item, "candidate_id") for item in alternatives)
        if self.entry_final:
            if basis_ids != expected_alternative_ids:
                raise ValueError("final Entry must classify every frozen bounded alternative")
        elif basis_ids:
            raise ValueError("provisional Entry cannot freeze alternative Entry bases")
        if self.position_id is not None and (
            self.entry_status is not ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
            or not self.entry_final
            or self.entry_pricing_json is None
            or self.position_state is None
        ):
            raise ValueError("Shadow Position requires final atomic Entry economics")
        if self.position_state is not None and self.position_id is None:
            raise ValueError("Position state requires one Shadow Position")
        if self.entry_final and (
            self.entry_status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
        ) != (self.position_id is not None):
            raise ValueError("final Entry status does not match Position existence")
        if self.position_state is PositionState.EXIT_INTENT_FROZEN and self.exit_intent is None:
            raise ValueError("EXIT_INTENT_FROZEN requires one ExitIntent")
        if self.exit_intent is not None and self.position_id is None:
            raise ValueError("ExitIntent requires one Shadow Position")
        if self.position_state is PositionState.TERMINAL and self.outcome is None:
            raise ValueError("TERMINAL Position requires one Outcome")
        if self.outcome is not None:
            outcome = self.outcome
            has_position = self.position_id is not None
            if has_position != (outcome.terminal_method is not TerminalMethod.NO_POSITION):
                raise ValueError("Outcome terminal method does not match Position existence")
            if has_position != (self.position_state is PositionState.TERMINAL):
                raise ValueError("Position Outcome requires terminal Position state")
            explanation = outcome.explanation
            if explanation.path_id != path.identity:
                raise ValueError("Outcome explanation does not bind the accepted Case path")
            if (
                reunderwriting is None
                or explanation.entry_reunderwriting_id != reunderwriting.identity
            ):
                raise ValueError("Outcome explanation does not bind final Entry truth")
            if (
                explanation.decision_metrics != reunderwriting.decision_metrics
                or explanation.entry_metrics != reunderwriting.entry_metrics
            ):
                raise ValueError("Outcome explanation metrics do not match final Entry truth")
            expected_entry_fee = (
                reunderwriting.combo_fee_native
                if reunderwriting.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
                else None
            )
            if explanation.entry_combo_fee_native != expected_entry_fee:
                raise ValueError("Outcome explanation Entry fee does not match final Entry truth")
            if explanation.gap_ids != tuple(gap.identity for gap in path.gaps):
                raise ValueError("Outcome explanation does not bind every accepted Gap")
            if tuple(
                item.candidate_id for item in explanation.alternative_outcomes
            ) != basis_ids or any(
                item.entry_basis_id != basis.identity
                or item.terminal_method is not outcome.terminal_method
                for item, basis in zip(
                    explanation.alternative_outcomes,
                    path.alternative_entry_bases,
                    strict=True,
                )
            ):
                raise ValueError("Outcome alternatives do not bind the frozen Entry bases")
            if any(
                item.status is CounterfactualStatus.EVALUABLE
                and item.terminal_evidence_id != outcome.terminal_evidence_id
                for item in explanation.alternative_outcomes
            ):
                raise ValueError("evaluable Outcome alternatives require the actual terminal cut")
            expected_primary_category = (
                self.exit_intent.category if self.exit_intent is not None else "TIME"
            )
            expected_primary_reason = (
                self.exit_intent.reason if self.exit_intent is not None else "EXPIRY_SETTLEMENT"
            )
            if outcome.terminal_method is TerminalMethod.NO_POSITION:
                expected_primary_category = "ENTRY"
                expected_primary_reason = reunderwriting.reason or reunderwriting.status.value
                if explanation.hold_to_expiry.status is not CounterfactualStatus.NOT_APPLICABLE:
                    raise ValueError("no-Position Outcome cannot claim hold-to-expiry economics")
            elif outcome.terminal_method is TerminalMethod.CONTRACT_SETTLEMENT:
                hold = explanation.hold_to_expiry
                if (
                    hold.status is not CounterfactualStatus.EVALUABLE
                    or hold.terminal_evidence_id != outcome.terminal_evidence_id
                    or hold.native_result_btc != outcome.native_result_btc
                    or hold.boundary_reference_result_usd != outcome.boundary_reference_result_usd
                ):
                    raise ValueError("settlement Outcome must bind its exact hold counterfactual")
            else:
                if self.exit_intent is None:
                    raise ValueError("whole-product exit Outcome requires its frozen ExitIntent")
                hold = explanation.hold_to_expiry
                if hold.status is CounterfactualStatus.UNKNOWN:
                    if hold.reason != "OFFICIAL_EXPIRY_SETTLEMENT_PENDING":
                        raise ValueError("pending hold counterfactual requires its exact reason")
                elif hold.status is CounterfactualStatus.EVALUABLE:
                    if hold.known_at < _structure_expiry(self):
                        raise ValueError("hold counterfactual cannot precede the frozen expiry")
                else:
                    raise ValueError("whole-product exit hold counterfactual has invalid status")
            if (
                explanation.primary_exit_category != expected_primary_category
                or explanation.primary_exit_reason != expected_primary_reason
            ):
                raise ValueError("Outcome explanation primary reason is incoherent")

    @property
    def identity(self) -> str:
        structure = self.selected_structure
        return canonical_identity(
            "TradeCaseV2",
            self.channel_id,
            self.truth_layer,
            self.decision_window_id,
            self.decision_policy_id,
            self.selected_structure_id,
            structure.get("option_amount"),
            self.decision_boundary,
            self.decision_route_evidence_id,
        )

    @property
    def snapshot_identity(self) -> str:
        return canonical_identity("TradeCaseSnapshotV3", self.as_object(include_snapshot=False))

    @property
    def gap_observed(self) -> bool:
        return bool(self.explanation_path.gaps)

    @property
    def selected_structure(self) -> dict[str, object]:
        return _json_mapping(self.selected_structure_json, "selected_structure")

    @property
    def risk_allocation(self) -> dict[str, object]:
        return _json_mapping(self.risk_allocation_json, "risk_allocation")

    @property
    def decision_route_evidence(self) -> ShadowRouteEvidence:
        return ShadowRouteEvidence.from_object(
            _json_mapping(self.decision_route_evidence_json, "decision_route_evidence")
        )

    @property
    def entry_pricing(self) -> dict[str, object] | None:
        return (
            _json_mapping(self.entry_pricing_json, "entry_pricing")
            if self.entry_pricing_json is not None
            else None
        )

    @property
    def entry_reunderwriting(self) -> ShadowEntryReunderwriting | None:
        return (
            ShadowEntryReunderwriting.from_object(
                _json_mapping(self.entry_reunderwriting_json, "entry_reunderwriting")
            )
            if self.entry_reunderwriting_json is not None
            else None
        )

    @property
    def position(self) -> ShadowPosition | None:
        if self.position_id is None:
            return None
        return ShadowPosition(
            position_id=self.position_id,
            trade_case_id=self.identity,
            truth_layer=self.truth_layer,
            channel_id=self.channel_id,
            selected_structure_id=self.selected_structure_id,
            option_amount=_structure_amount(self),
            entry_observation_id=_required(self.entry_observation_id, "entry_observation_id"),
            entry_observed_at=_required_datetime(self.entry_observed_at, "entry_observed_at"),
            entry_native_net_credit=_required_decimal(
                self.entry_native_net_credit, "entry_native_net_credit"
            ),
            state=_required_state(self.position_state),
            exit_intent=self.exit_intent,
        )

    def as_object(self, *, include_snapshot: bool = True) -> dict[str, object]:
        value = _canonical_object(self)
        value["explanation_path"] = self.explanation_path.as_object()
        value["outcome"] = self.outcome.as_object() if self.outcome is not None else None
        value["trade_case_id"] = self.identity
        if include_snapshot:
            value["snapshot_id"] = self.snapshot_identity
        return value

    @classmethod
    def from_object(cls, value: object) -> Self:
        item = _mapping(value, "trade_case")
        case = cls(
            channel_id=ChannelId(_text(item, "channel_id")),
            truth_layer=_text(item, "truth_layer"),
            decision_record_id=_text(item, "decision_record_id"),
            decision_window_id=_text(item, "decision_window_id"),
            decision_policy_id=_text(item, "decision_policy_id"),
            decision_boundary=_datetime(item, "decision_boundary"),
            decision_session_phase=SessionPhase(_text(item, "decision_session_phase")),
            decision_vrp_proxy_ratio=_decimal(item, "decision_vrp_proxy_ratio"),
            selected_structure_id=_text(item, "selected_structure_id"),
            selected_structure_json=_text(item, "selected_structure_json"),
            risk_allocation_id=_text(item, "risk_allocation_id"),
            risk_allocation_json=_text(item, "risk_allocation_json"),
            opened_at=_datetime(item, "opened_at"),
            entry_deadline=_datetime(item, "entry_deadline"),
            decision_route_evidence_id=_text(item, "decision_route_evidence_id"),
            decision_route_evidence_json=_text(item, "decision_route_evidence_json"),
            explanation_path=ShadowExplanationPath.from_object(item.get("explanation_path")),
            entry_status=_optional_enum(item, "entry_status", ShadowEntryStatus),
            entry_final=_boolean(item, "entry_final"),
            entry_observation_id=_optional_text(item, "entry_observation_id"),
            entry_observed_at=_optional_datetime(item, "entry_observed_at"),
            entry_known_at=_optional_datetime(item, "entry_known_at"),
            entry_reason=_optional_text(item, "entry_reason"),
            entry_reunderwriting_json=_optional_text(item, "entry_reunderwriting_json"),
            entry_pricing_json=_optional_text(item, "entry_pricing_json"),
            position_id=_optional_text(item, "position_id"),
            position_state=_optional_enum(item, "position_state", PositionState),
            entry_native_net_credit=_optional_decimal(item, "entry_native_net_credit"),
            entry_index_price_usd=_optional_decimal(item, "entry_index_price_usd"),
            entry_vrp_proxy_ratio=_optional_decimal(item, "entry_vrp_proxy_ratio"),
            last_observation_id=_optional_text(item, "last_observation_id"),
            last_observed_at=_optional_datetime(item, "last_observed_at"),
            exit_intent=(
                ExitIntent.from_object(item.get("exit_intent"))
                if item.get("exit_intent") is not None
                else None
            ),
            outcome=(
                ShadowCaseOutcome.from_object(item.get("outcome"))
                if item.get("outcome") is not None
                else None
            ),
        )
        if _text(item, "trade_case_id") != case.identity:
            raise ValueError("TradeCase identity mismatch")
        if _text(item, "snapshot_id") != case.snapshot_identity:
            raise ValueError("TradeCase snapshot identity mismatch")
        return case


def open_trade_case(record: DecisionRecord, policy: BtcShortVolPolicy) -> TradeCase:
    if record.result is not DecisionResult.CANDIDATE:
        raise ValueError("only a CANDIDATE DecisionRecord can open a TradeCase")
    if record.decision_policy_id != policy.identity:
        raise ValueError("DecisionRecord Policy does not match")
    if record.window.channel_id is not policy.channel_id:
        raise ValueError("DecisionRecord Channel does not match")
    if record.selected_structure_json is None or record.risk_allocation_json is None:
        raise ValueError("Candidate DecisionRecord lacks frozen structure or allocation")
    allocation = record.risk_allocation
    if allocation is None or allocation.get("result") != "AVAILABLE":
        raise ValueError("TradeCase requires AVAILABLE ShadowRiskAllocation")
    if record.observation is None:
        raise ValueError("Candidate DecisionRecord lacks its causal MarketObservation")
    route_evidence = record.route_evidence
    if route_evidence is None or route_evidence.status is not RouteEvidenceStatus.EVALUABLE:
        raise ValueError("Candidate DecisionRecord lacks evaluable route evidence")
    decision_session = current_deribit_session(
        record.observation.observed_at,
        phase_policy=policy.session,
    )
    decision_vrp = (
        record.observation.context.same_session_implied_variance_proxy
        / record.observation.context.trailing_realized_variance_proxy
    )
    selected_structure = _json_mapping(record.selected_structure_json, "selected_structure")
    decision_point = _market_path_point(
        structure=selected_structure,
        expiry=_parse_iso(_text(selected_structure, "expiry"), "expiry"),
        observation=record.observation,
        phase=ShadowPathPhase.DECISION,
        valuation_reason="NO_POSITION_AT_DECISION",
    )
    return TradeCase(
        channel_id=record.window.channel_id,
        truth_layer="SHADOW_PROJECTION",
        decision_record_id=record.identity,
        decision_window_id=record.window.identity,
        decision_policy_id=record.decision_policy_id,
        decision_boundary=record.known_at,
        decision_session_phase=decision_session.phase,
        decision_vrp_proxy_ratio=decision_vrp,
        selected_structure_id=_required(record.selected_structure_id, "selected_structure_id"),
        selected_structure_json=record.selected_structure_json,
        risk_allocation_id=_required(record.risk_allocation_id, "risk_allocation_id"),
        risk_allocation_json=record.risk_allocation_json,
        opened_at=record.known_at,
        entry_deadline=record.known_at
        + timedelta(seconds=policy.lifecycle.entry_evaluation_window_seconds),
        decision_route_evidence_id=route_evidence.identity,
        decision_route_evidence_json=_json_text(route_evidence.as_object()),
        explanation_path=ShadowExplanationPath(
            decision_record_id=record.identity,
            policy_id=policy.identity,
            selected_structure_id=_required(record.selected_structure_id, "selected_structure_id"),
            observation_count=1,
            last_observation_id=decision_point.observation_id,
            last_observed_at=decision_point.observed_at,
            points=(decision_point,),
            statistics=_updated_path_statistics((), decision_point),
            gaps=(),
            alternative_entry_bases=(),
        ),
    )


def evaluate_shadow_entry(
    case: TradeCase,
    *,
    observation: MarketObservation | None,
    policy: BtcShortVolPolicy,
    known_at: datetime,
) -> tuple[TradeCase, ShadowEntryReunderwriting]:
    _require_case_policy(case, policy)
    boundary = _utc(known_at, "known_at")
    if case.entry_final:
        raise ValueError("TradeCase Entry result is already final")
    evidence_blockers = list(_entry_evidence_blockers(case, observation, boundary, policy))
    legs: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None = None
    if not evidence_blockers:
        assert observation is not None
        legs = _selected_quotes(case, observation)
        if legs is None:
            evidence_blockers.append("SELECTED_STRUCTURE_QUOTES_MISSING")
        elif not _quotes_strictly_after(legs, case.decision_boundary):
            evidence_blockers.append("ENTRY_QUOTES_NOT_STRICTLY_FUTURE")
    if evidence_blockers:
        route_observation = (
            observation
            if observation is not None
            and observation.channel_id is case.channel_id
            and observation.known_at <= boundary
            else None
        )
        route_evidence = component_synthetic_route_evidence(
            policy_id=policy.identity,
            selected_structure_id=case.selected_structure_id,
            evaluated_at=boundary,
            target_amount=_structure_amount(case),
            instrument_names=_structure_instrument_names(case),
            observation_id=(route_observation.identity if route_observation is not None else None),
            observed_at=(route_observation.observed_at if route_observation is not None else None),
            observation_known_at=(
                route_observation.known_at if route_observation is not None else None
            ),
            quotes=None,
            pricing=None,
            unknown_reason=evidence_blockers[0],
        )
        result = _entry_reunderwriting_result(
            case=case,
            policy=policy,
            status=ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN,
            final=boundary >= case.entry_deadline,
            observation=observation,
            known_at=boundary,
            session_phase=None,
            market_session_id=None,
            vrp_proxy_ratio=None,
            legs=None,
            underwriting=None,
            route_evidence=route_evidence,
            evidence_blockers=tuple(evidence_blockers),
        )
        return _apply_entry_evaluation(
            case,
            result,
            pricing=None,
            observation=observation,
            policy=policy,
        ), result

    assert observation is not None and legs is not None
    session = current_deribit_session(observation.observed_at, phase_policy=policy.session)
    vrp_ratio = (
        observation.context.same_session_implied_variance_proxy
        / observation.context.trailing_realized_variance_proxy
    )
    environment_blockers = btc_environment_blockers(
        phase=session.phase,
        vrp_ratio=vrp_ratio,
        observation=observation,
        policy=policy,
    )
    underwriting = underwrite_btc_0dte_condor(
        observation=observation,
        long_put=legs[0],
        short_put=legs[1],
        short_call=legs[2],
        long_call=legs[3],
        amount=_structure_amount(case),
        policy=policy,
    )
    structure_blockers = underwriting.legal_blockers + underwriting.structure_limit_blockers
    route_evidence = component_synthetic_route_evidence(
        policy_id=policy.identity,
        selected_structure_id=case.selected_structure_id,
        evaluated_at=boundary,
        target_amount=_structure_amount(case),
        instrument_names=_structure_instrument_names(case),
        observation_id=observation.identity,
        observed_at=observation.observed_at,
        observation_known_at=observation.known_at,
        quotes=legs,
        pricing=underwriting.pricing,
    )
    allocation_blockers = _entry_allocation_blockers(
        case,
        entry_boundary=boundary,
        market_session_id=session.session_id,
    )
    if environment_blockers:
        status = ShadowEntryStatus.ENTRY_THESIS_EXPIRED
    elif structure_blockers:
        status = ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED
    elif route_evidence.status is RouteEvidenceStatus.NOT_EVALUABLE:
        status = ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE
    elif underwriting.economics_blockers:
        status = ShadowEntryStatus.ENTRY_PRICE_DETERIORATED
    elif allocation_blockers:
        status = ShadowEntryStatus.RISK_RESERVATION_INVALID
    else:
        status = ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
    result = _entry_reunderwriting_result(
        case=case,
        policy=policy,
        status=status,
        final=True,
        observation=observation,
        known_at=boundary,
        session_phase=session.phase,
        market_session_id=session.session_id,
        vrp_proxy_ratio=vrp_ratio,
        legs=legs,
        underwriting=underwriting,
        route_evidence=route_evidence,
        environment_blockers=environment_blockers,
        structure_blockers=structure_blockers,
        economics_blockers=underwriting.economics_blockers,
        allocation_blockers=allocation_blockers,
    )
    return _apply_entry_evaluation(
        case,
        result,
        pricing=underwriting.pricing,
        observation=observation,
        policy=policy,
    ), result


def monitor_shadow_position(
    case: TradeCase,
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> tuple[TradeCase, ShadowMonitorEvaluation]:
    _require_open_position(case, policy)
    _require_next_observation(case, observation, policy)
    if observation.observed_at >= _structure_expiry(case):
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.MONITOR,
            valuation_reason="EXPIRY_REQUIRES_OFFICIAL_SETTLEMENT",
        )
        updated = _advance_observation(_append_path_point(case, point), observation)
        if point.observation_status is ObservationStatus.UNKNOWN:
            updated = record_shadow_gap(
                updated,
                known_at=observation.known_at,
                reason=point.reason or "EXPIRY_MARKET_OBSERVATION_UNKNOWN",
                source="EXPIRY_OBSERVATION",
                observation=observation,
            )
        return updated, ShadowMonitorEvaluation(
            point.observation_status,
            observation.identity,
            observation.observed_at,
            PositionAction.SETTLE_AT_EXPIRY,
            ("EXPIRY_REACHED",),
            None,
            case.exit_intent,
            point.reason,
        )
    latest_exit_due = (
        _structure_expiry(case) - observation.observed_at
    ).total_seconds() <= policy.lifecycle.latest_exit_minutes_to_expiry * 60
    if observation.data_health_blockers:
        intent = _latest_exit_intent(case, observation, policy) if latest_exit_due else None
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.MONITOR,
            valuation_reason="WHOLE_PRODUCT_CLOSE_NOT_EVALUABLE",
        )
        advanced = record_shadow_gap(
            _advance_observation(_append_path_point(case, point), observation),
            known_at=observation.known_at,
            reason=observation.data_health_blockers[0],
            source="MONITORING_OBSERVATION",
            observation=observation,
        )
        updated = replace(
            advanced,
            exit_intent=intent,
            position_state=(
                PositionState.EXIT_INTENT_FROZEN if intent is not None else PositionState.MONITORING
            ),
        )
        evaluation = ShadowMonitorEvaluation(
            ObservationStatus.UNKNOWN,
            observation.identity,
            observation.observed_at,
            PositionAction.EXIT_WHOLE_PRODUCT if intent is not None else None,
            ("LATEST_EXIT",) if intent is not None else (),
            None,
            intent,
            observation.data_health_blockers[0],
        )
        return updated, evaluation

    legs = _selected_quotes(case, observation)
    if legs is None:
        intent = _latest_exit_intent(case, observation, policy) if latest_exit_due else None
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.MONITOR,
            valuation_reason="WHOLE_PRODUCT_CLOSE_NOT_EVALUABLE",
        )
        advanced = record_shadow_gap(
            _advance_observation(_append_path_point(case, point), observation),
            known_at=observation.known_at,
            reason="SELECTED_STRUCTURE_QUOTES_MISSING",
            source="MONITORING_OBSERVATION",
            observation=observation,
        )
        updated = replace(
            advanced,
            exit_intent=intent,
            position_state=(
                PositionState.EXIT_INTENT_FROZEN if intent is not None else PositionState.MONITORING
            ),
        )
        return updated, ShadowMonitorEvaluation(
            ObservationStatus.UNKNOWN,
            observation.identity,
            observation.observed_at,
            PositionAction.EXIT_WHOLE_PRODUCT if intent is not None else None,
            ("LATEST_EXIT",) if intent is not None else (),
            None,
            intent,
            "SELECTED_STRUCTURE_QUOTES_MISSING",
        )
    close = _close_projection(case, observation, legs) if legs is not None else None
    triggers = _position_triggers(case, observation, close, policy) if legs is not None else ()
    if not triggers and close is None:
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.MONITOR,
            valuation_reason="POSITION_CLOSE_CONTEXT_UNKNOWN",
        )
        updated = _advance_observation(_append_path_point(case, point), observation)
        return updated, ShadowMonitorEvaluation(
            ObservationStatus.UNKNOWN,
            observation.identity,
            observation.observed_at,
            None,
            (),
            None,
            case.exit_intent,
            "POSITION_CLOSE_CONTEXT_UNKNOWN",
        )
    native_result = (
        _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        + close.native_net_cashflow
        if close is not None
        else None
    )
    intent = case.exit_intent
    if intent is None and triggers:
        primary = next(reason for reason in policy.lifecycle.trigger_priority if reason in triggers)
        intent = ExitIntent(
            category=_trigger_category(primary),
            reason=primary,
            observation_id=observation.identity,
            observed_at=observation.observed_at,
            known_at=observation.known_at,
            source="PUBLIC_MARKET_OBSERVATION",
            policy_id=policy.identity,
        )
    action = PositionAction.EXIT_WHOLE_PRODUCT if intent is not None else PositionAction.HOLD
    point = _market_path_point(
        structure=case.selected_structure,
        expiry=_structure_expiry(case),
        observation=observation,
        phase=ShadowPathPhase.MONITOR,
        native_result_btc=native_result,
        boundary_reference_result_usd=(
            native_result * observation.context.index_price if native_result is not None else None
        ),
        combo_fee_native=close.combo_standard_fee_native if close is not None else None,
        valuation_method_id=SHADOW_COMPONENT_CLOSE_METHOD_ID if close is not None else None,
        valuation_reason=None if close is not None else "WHOLE_PRODUCT_CLOSE_NOT_EVALUABLE",
    )
    updated = replace(
        _advance_observation(_append_path_point(case, point), observation),
        exit_intent=intent,
        position_state=(
            PositionState.EXIT_INTENT_FROZEN if intent is not None else PositionState.MONITORING
        ),
    )
    return updated, ShadowMonitorEvaluation(
        ObservationStatus.KNOWN,
        observation.identity,
        observation.observed_at,
        action,
        triggers,
        native_result,
        intent,
        None,
    )


def freeze_latest_exit_on_time_boundary(
    case: TradeCase,
    *,
    known_at: datetime,
    policy: BtcShortVolPolicy,
) -> TradeCase:
    """Freeze deterministic exit responsibility when no market cut is available."""

    _require_open_position(case, policy)
    if case.exit_intent is not None:
        return case
    boundary = _utc(known_at, "known_at")
    expiry = _structure_expiry(case)
    latest_exit_at = expiry - timedelta(minutes=policy.lifecycle.latest_exit_minutes_to_expiry)
    if boundary < latest_exit_at:
        raise ValueError("LATEST_EXIT time boundary has not been reached")
    evidence_id = canonical_identity(
        "DeribitTimeBoundaryV1",
        case.identity,
        policy.identity,
        latest_exit_at,
    )
    return replace(
        case,
        exit_intent=ExitIntent(
            category=_trigger_category("LATEST_EXIT"),
            reason="LATEST_EXIT",
            observation_id=evidence_id,
            observed_at=latest_exit_at,
            known_at=boundary,
            source="DERIBIT_TIME_BOUNDARY_WITHOUT_MARKET_CUT",
            policy_id=policy.identity,
        ),
        position_state=PositionState.EXIT_INTENT_FROZEN,
    )


def _latest_exit_intent(
    case: TradeCase,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> ExitIntent:
    if case.exit_intent is not None:
        return case.exit_intent
    return ExitIntent(
        category=_trigger_category("LATEST_EXIT"),
        reason="LATEST_EXIT",
        observation_id=observation.identity,
        observed_at=observation.observed_at,
        known_at=observation.known_at,
        source="DERIBIT_TIME_BOUNDARY",
        policy_id=policy.identity,
    )


def evaluate_shadow_exit(
    case: TradeCase,
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> tuple[TradeCase, ShadowExitEvaluation]:
    _require_open_position(case, policy)
    if case.exit_intent is None:
        raise ValueError("Shadow exit requires a frozen ExitIntent")
    if observation.observed_at <= case.exit_intent.observed_at:
        raise ValueError("Shadow exit evidence must be strictly later than its trigger")
    if observation.known_at <= case.exit_intent.known_at:
        raise ValueError("Shadow exit known-at must be strictly later than its trigger")
    if observation.observed_at >= _structure_expiry(case):
        raise ValueError("at or after expiry, only settlement can terminalize a Position")
    _require_next_observation(case, observation, policy)
    selected_legs = (
        None if observation.data_health_blockers else _selected_quotes(case, observation)
    )
    quotes_not_future = selected_legs is not None and not _quotes_strictly_after(
        selected_legs, case.exit_intent.known_at
    )
    legs = None if quotes_not_future else selected_legs
    close = _close_projection(case, observation, legs) if legs is not None else None
    if close is None:
        reason = (
            observation.data_health_blockers[0]
            if observation.data_health_blockers
            else "SELECTED_STRUCTURE_QUOTES_MISSING"
            if selected_legs is None
            else "EXIT_QUOTES_NOT_STRICTLY_FUTURE"
            if quotes_not_future
            else "WHOLE_PRODUCT_EXIT_NOT_PRICE_EVALUABLE"
        )
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.EXIT,
            valuation_reason=reason,
            unknown_reason=(
                reason if observation.data_health_blockers or selected_legs is None else None
            ),
        )
        updated = _advance_observation(_append_path_point(case, point), observation)
        if observation.data_health_blockers or selected_legs is None or quotes_not_future:
            updated = record_shadow_gap(
                updated,
                known_at=observation.known_at,
                reason=reason,
                source="EXIT_OBSERVATION",
                observation=observation,
            )
        evaluation = ShadowExitEvaluation(
            ObservationStatus.UNKNOWN,
            observation.identity,
            observation.observed_at,
            None,
            None,
            False,
            reason,
        )
        return updated, evaluation
    native_result = (
        _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        + close.native_net_cashflow
    )
    point = _market_path_point(
        structure=case.selected_structure,
        expiry=_structure_expiry(case),
        observation=observation,
        phase=ShadowPathPhase.EXIT,
        native_result_btc=native_result,
        boundary_reference_result_usd=native_result * observation.context.index_price,
        combo_fee_native=close.combo_standard_fee_native,
        valuation_method_id=SHADOW_COMPONENT_CLOSE_METHOD_ID,
    )
    terminal_case = _advance_observation(
        _append_path_point(case, point, terminal=True), observation
    )
    outcome = _position_outcome(
        terminal_case,
        method=TerminalMethod.WHOLE_PRODUCT_EXIT,
        terminal_at=observation.known_at,
        terminal_evidence_id=observation.identity,
        native_result=native_result,
        boundary_result=native_result * observation.context.index_price,
        fee_model_id=close.fee_model_id,
        source="STRICTLY_LATER_PUBLIC_FOUR_LEG_ESTIMATE",
        terminal_combo_fee_native=close.combo_standard_fee_native,
        alternative_outcomes=_alternative_outcomes_for_exit(case, observation=observation),
        hold_to_expiry=_pending_hold_counterfactual(observation.known_at),
    )
    updated = replace(
        terminal_case,
        position_state=PositionState.TERMINAL,
        outcome=outcome,
    )
    return updated, ShadowExitEvaluation(
        ObservationStatus.KNOWN,
        observation.identity,
        observation.observed_at,
        close.native_net_cashflow,
        native_result,
        True,
        None,
    )


def settle_shadow_position(
    case: TradeCase,
    *,
    settlement: ExpirySettlementFact,
    policy: BtcShortVolPolicy,
) -> TradeCase:
    _require_open_position(case, policy)
    if settlement.product_id is not ProductId.INVERSE_BTC:
        raise ValueError("BTC Shadow Position requires a BTC settlement fact")
    boundary = _utc(settlement.known_at, "settlement.known_at")
    structure = case.selected_structure
    expiry = _parse_iso(_text(structure, "expiry"), "expiry")
    if settlement.expiry != expiry:
        raise ValueError("settlement expiry does not match the frozen structure")
    legs = _structure_legs(case)
    economics = settle_btc_0dte_condor(
        long_put_strike=legs[0][1],
        short_put_strike=legs[1][1],
        short_call_strike=legs[2][1],
        long_call_strike=legs[3][1],
        amount=_structure_amount(case),
        delivery_price=settlement.delivery_price_usd,
        daily_delivery_fee_exempt=all(leg[3] for leg in legs),
    )
    native_result = (
        _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        + economics.native_net_cashflow
    )
    settlement_fee_model = (
        "DERIBIT_DAILY_OPTION_DELIVERY_FEE_EXEMPT"
        if economics.delivery_fee_native == 0
        else "DERIBIT_STANDARD_DELIVERY_FEE"
    )
    boundary_result = native_result * settlement.delivery_price_usd
    outcome = _position_outcome(
        case,
        method=TerminalMethod.CONTRACT_SETTLEMENT,
        terminal_at=boundary,
        terminal_evidence_id=settlement.identity,
        native_result=native_result,
        boundary_result=boundary_result,
        fee_model_id=settlement_fee_model,
        source=(f"{settlement.evidence_kind.value}:{settlement.source_id}:{settlement.method_id}"),
        terminal_combo_fee_native=None,
        alternative_outcomes=_alternative_outcomes_for_settlement(case, settlement=settlement),
        hold_to_expiry=ShadowExitCounterfactual(
            kind=ExitCounterfactualKind.HOLD_TO_EXPIRY,
            status=CounterfactualStatus.EVALUABLE,
            known_at=settlement.known_at,
            terminal_evidence_id=settlement.identity,
            native_result_btc=native_result,
            boundary_reference_result_usd=boundary_result,
            fee_model_id=settlement_fee_model,
            reason=None,
        ),
    )
    return replace(case, position_state=PositionState.TERMINAL, outcome=outcome)


def enrich_shadow_exit_outcome_at_settlement(
    case: TradeCase,
    *,
    settlement: ExpirySettlementFact,
    policy: BtcShortVolPolicy,
) -> TradeCase:
    """Complete only the hold-to-expiry explanation of an already terminal Shadow exit."""

    _require_case_policy(case, policy)
    outcome = case.outcome
    if (
        case.position_state is not PositionState.TERMINAL
        or outcome is None
        or outcome.terminal_method is not TerminalMethod.WHOLE_PRODUCT_EXIT
    ):
        raise ValueError("settlement enrichment requires a terminal whole-product Shadow exit")
    if settlement.product_id is not ProductId.INVERSE_BTC:
        raise ValueError("BTC hold counterfactual requires a BTC settlement fact")
    if settlement.expiry != _structure_expiry(case):
        raise ValueError("hold counterfactual settlement does not match the frozen structure")
    current = outcome.explanation.hold_to_expiry
    if current.status is CounterfactualStatus.EVALUABLE:
        if current.terminal_evidence_id != settlement.identity:
            raise ValueError("Outcome already binds a different expiry settlement")
        return case
    if current.status is not CounterfactualStatus.UNKNOWN:
        raise ValueError("Outcome hold counterfactual is not pending")
    legs = _structure_legs(case)
    economics = settle_btc_0dte_condor(
        long_put_strike=legs[0][1],
        short_put_strike=legs[1][1],
        short_call_strike=legs[2][1],
        long_call_strike=legs[3][1],
        amount=_structure_amount(case),
        delivery_price=settlement.delivery_price_usd,
        daily_delivery_fee_exempt=all(leg[3] for leg in legs),
    )
    native_result = (
        _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        + economics.native_net_cashflow
    )
    fee_model_id = (
        "DERIBIT_DAILY_OPTION_DELIVERY_FEE_EXEMPT"
        if economics.delivery_fee_native == 0
        else "DERIBIT_STANDARD_DELIVERY_FEE"
    )
    hold = ShadowExitCounterfactual(
        kind=ExitCounterfactualKind.HOLD_TO_EXPIRY,
        status=CounterfactualStatus.EVALUABLE,
        known_at=settlement.known_at,
        terminal_evidence_id=settlement.identity,
        native_result_btc=native_result,
        boundary_reference_result_usd=native_result * settlement.delivery_price_usd,
        fee_model_id=fee_model_id,
        reason=None,
    )
    explanation = replace(outcome.explanation, hold_to_expiry=hold, complete=True)
    return replace(case, outcome=replace(outcome, explanation=explanation))


def _apply_entry_evaluation(
    case: TradeCase,
    evaluation: ShadowEntryReunderwriting,
    *,
    pricing: Btc0DteCondorPricing | None,
    observation: MarketObservation | None = None,
    policy: BtcShortVolPolicy,
) -> TradeCase:
    outcome: ShadowCaseOutcome | None = None
    position_id: str | None = None
    position_state: PositionState | None = None
    entry_pricing_json: str | None = None
    entry_credit: Decimal | None = None
    entry_index: Decimal | None = None
    entry_vrp: Decimal | None = None
    if pricing is not None and observation is not None:
        entry_pricing_json = _json_text(
            {
                "fee_model_id": pricing.fee_model_id,
                "native_gross_credit": pricing.native_gross_credit,
                "combo_standard_fee_native": pricing.combo_standard_fee_native,
                "native_net_credit": pricing.native_net_credit,
                "boundary_index_price_usd": pricing.boundary_index_price_usd,
                "boundary_net_credit_usd": pricing.boundary_net_credit_usd,
                "maximum_contractual_payoff_cap_usd": (pricing.maximum_contractual_payoff_cap_usd),
                "boundary_reference_loss_usd": pricing.boundary_reference_loss_usd,
            }
        )
        if evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
            position_id = canonical_identity(
                "ShadowPositionV1",
                case.identity,
                case.truth_layer,
                case.selected_structure_id,
                evaluation.identity,
                observation.identity,
                observation.observed_at,
            )
            position_state = PositionState.MONITORING
            entry_credit = pricing.native_net_credit
            entry_index = pricing.boundary_index_price_usd
            entry_vrp = evaluation.entry_metrics.vrp_proxy_ratio
    explanation_path = case.explanation_path
    if observation is not None and observation.identity != explanation_path.last_observation_id:
        evaluable = evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
        point = _market_path_point(
            structure=case.selected_structure,
            expiry=_structure_expiry(case),
            observation=observation,
            phase=ShadowPathPhase.ENTRY,
            reunderwriting_id=evaluation.identity,
            native_result_btc=Decimal(0) if evaluable else None,
            boundary_reference_result_usd=Decimal(0) if evaluable else None,
            combo_fee_native=(pricing.combo_standard_fee_native if evaluable and pricing else None),
            valuation_method_id=SHADOW_ENTRY_BASELINE_METHOD_ID if evaluable else None,
            valuation_reason=None if evaluable else evaluation.reason or "NO_SHADOW_POSITION",
            unknown_reason=(
                evaluation.reason
                if evaluation.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
                else None
            ),
        )
        explanation_path = _path_with_point(explanation_path, point)
    if evaluation.status is ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN:
        gap = ShadowPathGap(
            known_at=evaluation.known_at,
            reason=evaluation.reason or "ENTRY_EVIDENCE_UNKNOWN",
            source="ENTRY_EVALUATION",
            observation_id=observation.identity if observation is not None else None,
            observed_at=observation.observed_at if observation is not None else None,
            reunderwriting_id=evaluation.identity,
        )
        if gap.identity not in {item.identity for item in explanation_path.gaps}:
            explanation_path = replace(
                explanation_path,
                gaps=(*explanation_path.gaps, gap),
            )
    explanation_path = replace(
        explanation_path,
        alternative_entry_bases=_alternative_entry_bases(
            case,
            evaluation=evaluation,
            observation=observation,
            policy=policy,
        ),
    )
    if evaluation.final and evaluation.status is not ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
        outcome = _no_position_outcome(
            case,
            evaluation=evaluation,
            explanation_path=explanation_path,
        )
    return replace(
        case,
        explanation_path=explanation_path,
        entry_status=evaluation.status,
        entry_final=evaluation.final,
        entry_observation_id=evaluation.observation_id,
        entry_observed_at=evaluation.observed_at,
        entry_known_at=evaluation.known_at,
        entry_reason=evaluation.reason,
        entry_reunderwriting_json=_json_text(evaluation.as_object()),
        entry_pricing_json=entry_pricing_json,
        position_id=position_id,
        position_state=position_state,
        entry_native_net_credit=entry_credit,
        entry_index_price_usd=entry_index,
        entry_vrp_proxy_ratio=entry_vrp,
        last_observation_id=evaluation.observation_id or case.last_observation_id,
        last_observed_at=evaluation.observed_at or case.last_observed_at,
        outcome=outcome,
    )


def _entry_reunderwriting_result(
    *,
    case: TradeCase,
    policy: BtcShortVolPolicy,
    status: ShadowEntryStatus,
    final: bool,
    observation: MarketObservation | None,
    known_at: datetime,
    session_phase: SessionPhase | None,
    market_session_id: str | None,
    vrp_proxy_ratio: Decimal | None,
    legs: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None,
    underwriting: Btc0DteCondorUnderwriting | None,
    route_evidence: ShadowRouteEvidence,
    evidence_blockers: tuple[str, ...] = (),
    environment_blockers: tuple[str, ...] = (),
    structure_blockers: tuple[str, ...] = (),
    economics_blockers: tuple[str, ...] = (),
    allocation_blockers: tuple[str, ...] = (),
) -> ShadowEntryReunderwriting:
    status_blockers = {
        ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN: evidence_blockers,
        ShadowEntryStatus.ENTRY_THESIS_EXPIRED: environment_blockers,
        ShadowEntryStatus.ENTRY_STRUCTURE_LIMIT_BREACHED: structure_blockers,
        ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE: (),
        ShadowEntryStatus.ENTRY_PRICE_DETERIORATED: economics_blockers,
        ShadowEntryStatus.RISK_RESERVATION_INVALID: allocation_blockers,
        ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE: (),
    }[status]
    pricing = underwriting.pricing if underwriting is not None else None
    return ShadowEntryReunderwriting(
        status=status,
        final=final,
        observation_id=observation.identity if observation is not None else None,
        observed_at=observation.observed_at if observation is not None else None,
        observation_known_at=observation.known_at if observation is not None else None,
        known_at=known_at,
        reason=(
            route_evidence.reason
            if status is ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE
            else (status_blockers[0] if status_blockers else None)
        ),
        policy_id=policy.identity,
        selected_structure_id=case.selected_structure_id,
        risk_allocation_id=case.risk_allocation_id,
        route_evidence=route_evidence,
        market_session_id=market_session_id,
        decision_session_phase=case.decision_session_phase,
        entry_session_phase=session_phase,
        decision_metrics=_decision_entry_metrics(case),
        entry_metrics=_current_entry_metrics(
            vrp_proxy_ratio=vrp_proxy_ratio,
            legs=legs,
            underwriting=underwriting,
        ),
        evidence_blockers=evidence_blockers,
        environment_blockers=environment_blockers,
        structure_blockers=structure_blockers,
        economics_blockers=economics_blockers,
        allocation_blockers=allocation_blockers,
        native_net_credit=pricing.native_net_credit if pricing is not None else None,
        combo_fee_native=pricing.combo_standard_fee_native if pricing is not None else None,
        boundary_index_price_usd=(
            pricing.boundary_index_price_usd if pricing is not None else None
        ),
    )


def _decision_entry_metrics(case: TradeCase) -> EntryUnderwritingMetrics:
    structure = case.selected_structure
    legs = _mapping(structure.get("legs"), "selected_structure.legs")
    short_put = _mapping(legs.get("short_put"), "legs.short_put")
    short_call = _mapping(legs.get("short_call"), "legs.short_call")
    pricing = _mapping(structure.get("pricing"), "selected_structure.pricing")
    boundary_credit = _decimal(pricing, "boundary_net_credit_usd")
    payoff_cap = _decimal(pricing, "maximum_contractual_payoff_cap_usd")
    combo_fee = _decimal(pricing, "combo_standard_fee_native")
    gross_credit = _decimal(pricing, "native_gross_credit")
    return EntryUnderwritingMetrics(
        vrp_proxy_ratio=case.decision_vrp_proxy_ratio,
        short_put_abs_delta=abs(_decimal(short_put, "signed_delta")),
        short_call_abs_delta=abs(_decimal(short_call, "signed_delta")),
        net_delta=_decimal(structure, "net_delta"),
        put_body_distance_sigma=_decimal(structure, "put_body_distance_sigma"),
        call_body_distance_sigma=_decimal(structure, "call_body_distance_sigma"),
        boundary_net_credit_usd=boundary_credit,
        credit_to_payoff_cap=boundary_credit / payoff_cap,
        boundary_reference_loss_usd=_decimal(pricing, "boundary_reference_loss_usd"),
        combo_fee_fraction_of_credit=combo_fee / gross_credit,
    )


def _current_entry_metrics(
    *,
    vrp_proxy_ratio: Decimal | None,
    legs: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None,
    underwriting: Btc0DteCondorUnderwriting | None,
) -> EntryUnderwritingMetrics:
    pricing = underwriting.pricing if underwriting is not None else None
    return EntryUnderwritingMetrics(
        vrp_proxy_ratio=vrp_proxy_ratio,
        short_put_abs_delta=abs(legs[1].signed_delta) if legs is not None else None,
        short_call_abs_delta=abs(legs[2].signed_delta) if legs is not None else None,
        net_delta=underwriting.net_delta if underwriting is not None else None,
        put_body_distance_sigma=(
            underwriting.put_body_distance_sigma if underwriting is not None else None
        ),
        call_body_distance_sigma=(
            underwriting.call_body_distance_sigma if underwriting is not None else None
        ),
        boundary_net_credit_usd=(pricing.boundary_net_credit_usd if pricing is not None else None),
        credit_to_payoff_cap=(
            pricing.boundary_net_credit_usd / pricing.maximum_contractual_payoff_cap_usd
            if pricing is not None
            else None
        ),
        boundary_reference_loss_usd=(
            pricing.boundary_reference_loss_usd if pricing is not None else None
        ),
        combo_fee_fraction_of_credit=(
            pricing.combo_standard_fee_native / pricing.native_gross_credit
            if pricing is not None
            else None
        ),
    )


def _entry_evidence_blockers(
    case: TradeCase,
    observation: MarketObservation | None,
    known_at: datetime,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    if observation is None:
        return ("NO_ENTRY_OBSERVATION",)
    blockers: list[str] = []
    if observation.channel_id is not case.channel_id:
        blockers.append("ENTRY_OBSERVATION_CHANNEL_MISMATCH")
    if observation.data_health_policy_id != policy.observation.identity:
        blockers.append("ENTRY_OBSERVATION_DATA_HEALTH_POLICY_MISMATCH")
    if observation.known_at > known_at:
        blockers.append("ENTRY_OBSERVATION_NOT_KNOWN_AT_EVALUATION")
    if observation.observed_at <= case.decision_boundary:
        blockers.append("ENTRY_OBSERVATION_NOT_STRICTLY_FUTURE")
    if observation.observed_at > case.entry_deadline:
        blockers.append("ENTRY_WINDOW_EXPIRED")
    if observation.known_at > case.entry_deadline:
        blockers.append("ENTRY_OBSERVATION_KNOWN_AFTER_DEADLINE")
    blockers.extend(observation.data_health_blockers)
    return tuple(dict.fromkeys(blockers))


def _entry_allocation_blockers(
    case: TradeCase,
    *,
    entry_boundary: datetime,
    market_session_id: str,
) -> tuple[str, ...]:
    allocation = case.risk_allocation
    blockers: list[str] = []
    if allocation.get("result") != "AVAILABLE":
        blockers.append("ALLOCATION_NOT_AVAILABLE")
    if allocation.get("channel_id") != case.channel_id.value:
        blockers.append("ALLOCATION_CHANNEL_MISMATCH")
    if allocation.get("policy_id") != case.decision_policy_id:
        blockers.append("ALLOCATION_POLICY_MISMATCH")
    if allocation.get("candidate_id") != case.selected_structure_id:
        blockers.append("ALLOCATION_CANDIDATE_MISMATCH")
    if allocation.get("market_session_id") != market_session_id:
        blockers.append("ALLOCATION_SESSION_MISMATCH")
    try:
        if Decimal(str(allocation.get("option_amount"))) != _structure_amount(case):
            blockers.append("ALLOCATION_AMOUNT_MISMATCH")
    except (ArithmeticError, ValueError):
        blockers.append("ALLOCATION_AMOUNT_INVALID")
    try:
        allocation_known_at = _parse_iso(str(allocation.get("known_at")), "allocation.known_at")
    except ValueError:
        blockers.append("ALLOCATION_KNOWN_AT_INVALID")
    else:
        if allocation_known_at > case.decision_boundary:
            blockers.append("ALLOCATION_NOT_KNOWN_AT_DECISION")
    try:
        expires_at = _parse_iso(str(allocation.get("expires_at")), "allocation.expires_at")
    except ValueError:
        blockers.append("ALLOCATION_EXPIRY_INVALID")
    else:
        if expires_at != _structure_expiry(case):
            blockers.append("ALLOCATION_EXPIRY_STRUCTURE_MISMATCH")
        if entry_boundary >= expires_at:
            blockers.append("ALLOCATION_EXPIRED_AT_ENTRY")
        if case.entry_deadline >= expires_at:
            blockers.append("ALLOCATION_DOES_NOT_COVER_ENTRY_DEADLINE")
    try:
        stress_reserve_from_allocation_record(
            allocation,
            allocation_id=case.risk_allocation_id,
        )
    except ValueError:
        blockers.append("ALLOCATION_STRESS_RESERVE_INVALID")
    if allocation.get("budget_metric") != SHADOW_STRESS_BUDGET_METRIC:
        blockers.append("ALLOCATION_BUDGET_METRIC_MISMATCH")
    return tuple(dict.fromkeys(blockers))


def _alternative_entry_bases(
    case: TradeCase,
    *,
    evaluation: ShadowEntryReunderwriting,
    observation: MarketObservation | None,
    policy: BtcShortVolPolicy,
) -> tuple[ShadowAlternativeEntryBasis, ...]:
    alternatives = _structure_alternatives(case)
    if not evaluation.final:
        return ()
    if evaluation.status is not ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
        return tuple(
            ShadowAlternativeEntryBasis(
                candidate_id=_text(alternative, "candidate_id"),
                status=CounterfactualStatus.NOT_APPLICABLE,
                route_evidence=None,
                blockers=(),
                reason="PRIMARY_SHADOW_ENTRY_NOT_OPENED",
            )
            for alternative in alternatives
        )
    if observation is None:
        raise ValueError("evaluable primary Entry requires an observation")
    expiry = _structure_expiry(case)
    bases: list[ShadowAlternativeEntryBasis] = []
    for alternative in alternatives:
        candidate_id = _text(alternative, "candidate_id")
        amount = _decimal(alternative, "option_amount")
        instruments = tuple(leg[0] for leg in _structure_legs_from_mapping(alternative))
        quotes = _quotes_for_structure(
            alternative,
            expiry=expiry,
            observation=observation,
        )
        if quotes is None:
            route = component_synthetic_route_evidence(
                policy_id=policy.identity,
                selected_structure_id=candidate_id,
                evaluated_at=evaluation.known_at,
                target_amount=amount,
                instrument_names=instruments,  # type: ignore[arg-type]
                observation_id=observation.identity,
                observed_at=observation.observed_at,
                observation_known_at=observation.known_at,
                quotes=None,
                pricing=None,
                unknown_reason="ALTERNATIVE_ENTRY_QUOTES_MISSING",
            )
            bases.append(
                ShadowAlternativeEntryBasis(
                    candidate_id=candidate_id,
                    status=CounterfactualStatus.UNKNOWN,
                    route_evidence=route,
                    blockers=(),
                    reason=route.reason,
                )
            )
            continue
        underwriting = underwrite_btc_0dte_condor(
            observation=observation,
            long_put=quotes[0],
            short_put=quotes[1],
            short_call=quotes[2],
            long_call=quotes[3],
            amount=amount,
            policy=policy,
        )
        route = component_synthetic_route_evidence(
            policy_id=policy.identity,
            selected_structure_id=candidate_id,
            evaluated_at=evaluation.known_at,
            target_amount=amount,
            instrument_names=instruments,  # type: ignore[arg-type]
            observation_id=observation.identity,
            observed_at=observation.observed_at,
            observation_known_at=observation.known_at,
            quotes=quotes,
            pricing=underwriting.pricing,
        )
        blockers = tuple(
            dict.fromkeys(
                underwriting.legal_blockers
                + underwriting.structure_limit_blockers
                + underwriting.economics_blockers
            )
        )
        if route.status is RouteEvidenceStatus.NOT_EVALUABLE:
            bases.append(
                ShadowAlternativeEntryBasis(
                    candidate_id=candidate_id,
                    status=CounterfactualStatus.NOT_EVALUABLE,
                    route_evidence=route,
                    blockers=(),
                    reason=route.reason,
                )
            )
        elif blockers:
            bases.append(
                ShadowAlternativeEntryBasis(
                    candidate_id=candidate_id,
                    status=CounterfactualStatus.NOT_EVALUABLE,
                    route_evidence=route,
                    blockers=blockers,
                    reason=blockers[0],
                )
            )
        else:
            bases.append(
                ShadowAlternativeEntryBasis(
                    candidate_id=candidate_id,
                    status=CounterfactualStatus.EVALUABLE,
                    route_evidence=route,
                    blockers=(),
                    reason=None,
                )
            )
    return tuple(bases)


def _alternative_outcomes_for_exit(
    case: TradeCase,
    *,
    observation: MarketObservation,
) -> tuple[ShadowAlternativeOutcome, ...]:
    alternatives = {_text(item, "candidate_id"): item for item in _structure_alternatives(case)}
    output: list[ShadowAlternativeOutcome] = []
    for basis in case.explanation_path.alternative_entry_bases:
        if basis.status is not CounterfactualStatus.EVALUABLE:
            output.append(
                ShadowAlternativeOutcome(
                    candidate_id=basis.candidate_id,
                    entry_basis_id=basis.identity,
                    status=basis.status,
                    terminal_method=TerminalMethod.WHOLE_PRODUCT_EXIT,
                    terminal_evidence_id=None,
                    known_at=observation.known_at,
                    native_result_btc=None,
                    boundary_reference_result_usd=None,
                    entry_combo_fee_native=None,
                    terminal_combo_fee_native=None,
                    reason=basis.reason,
                )
            )
            continue
        route = basis.route_evidence
        assert route is not None
        alternative = alternatives[basis.candidate_id]
        quotes = _quotes_for_structure(
            alternative,
            expiry=_structure_expiry(case),
            observation=observation,
        )
        if (
            quotes is not None
            and route.observation_known_at is not None
            and not (_quotes_strictly_after(quotes, route.observation_known_at))
        ):
            quotes = None
        close = (
            project_btc_0dte_condor_close(
                long_put=quotes[0],
                short_put=quotes[1],
                short_call=quotes[2],
                long_call=quotes[3],
                amount=_decimal(alternative, "option_amount"),
                boundary_index_price=observation.context.index_price,
            )
            if quotes is not None
            else None
        )
        if close is None:
            output.append(
                ShadowAlternativeOutcome(
                    candidate_id=basis.candidate_id,
                    entry_basis_id=basis.identity,
                    status=CounterfactualStatus.UNKNOWN,
                    terminal_method=TerminalMethod.WHOLE_PRODUCT_EXIT,
                    terminal_evidence_id=None,
                    known_at=observation.known_at,
                    native_result_btc=None,
                    boundary_reference_result_usd=None,
                    entry_combo_fee_native=None,
                    terminal_combo_fee_native=None,
                    reason="ALTERNATIVE_EXIT_NOT_PRICE_EVALUABLE",
                )
            )
            continue
        assert route.native_net_credit is not None
        assert route.standard_combo_fee_projection_native is not None
        native_result = route.native_net_credit + close.native_net_cashflow
        output.append(
            ShadowAlternativeOutcome(
                candidate_id=basis.candidate_id,
                entry_basis_id=basis.identity,
                status=CounterfactualStatus.EVALUABLE,
                terminal_method=TerminalMethod.WHOLE_PRODUCT_EXIT,
                terminal_evidence_id=observation.identity,
                known_at=observation.known_at,
                native_result_btc=native_result,
                boundary_reference_result_usd=(native_result * observation.context.index_price),
                entry_combo_fee_native=route.standard_combo_fee_projection_native,
                terminal_combo_fee_native=close.combo_standard_fee_native,
                reason=None,
            )
        )
    return tuple(output)


def _alternative_outcomes_for_settlement(
    case: TradeCase,
    *,
    settlement: ExpirySettlementFact,
) -> tuple[ShadowAlternativeOutcome, ...]:
    alternatives = {_text(item, "candidate_id"): item for item in _structure_alternatives(case)}
    output: list[ShadowAlternativeOutcome] = []
    for basis in case.explanation_path.alternative_entry_bases:
        if basis.status is not CounterfactualStatus.EVALUABLE:
            output.append(
                ShadowAlternativeOutcome(
                    candidate_id=basis.candidate_id,
                    entry_basis_id=basis.identity,
                    status=basis.status,
                    terminal_method=TerminalMethod.CONTRACT_SETTLEMENT,
                    terminal_evidence_id=None,
                    known_at=settlement.known_at,
                    native_result_btc=None,
                    boundary_reference_result_usd=None,
                    entry_combo_fee_native=None,
                    terminal_combo_fee_native=None,
                    reason=basis.reason,
                )
            )
            continue
        route = basis.route_evidence
        assert route is not None
        alternative = alternatives[basis.candidate_id]
        legs = _structure_legs_from_mapping(alternative)
        economics = settle_btc_0dte_condor(
            long_put_strike=legs[0][1],
            short_put_strike=legs[1][1],
            short_call_strike=legs[2][1],
            long_call_strike=legs[3][1],
            amount=_decimal(alternative, "option_amount"),
            delivery_price=settlement.delivery_price_usd,
            daily_delivery_fee_exempt=all(leg[3] for leg in legs),
        )
        assert route.native_net_credit is not None
        assert route.standard_combo_fee_projection_native is not None
        native_result = route.native_net_credit + economics.native_net_cashflow
        output.append(
            ShadowAlternativeOutcome(
                candidate_id=basis.candidate_id,
                entry_basis_id=basis.identity,
                status=CounterfactualStatus.EVALUABLE,
                terminal_method=TerminalMethod.CONTRACT_SETTLEMENT,
                terminal_evidence_id=settlement.identity,
                known_at=settlement.known_at,
                native_result_btc=native_result,
                boundary_reference_result_usd=(native_result * settlement.delivery_price_usd),
                entry_combo_fee_native=route.standard_combo_fee_projection_native,
                terminal_combo_fee_native=None,
                reason=None,
            )
        )
    return tuple(output)


def _position_triggers(
    case: TradeCase,
    observation: MarketObservation,
    close: Btc0DteCondorCloseProjection | None,
    policy: BtcShortVolPolicy,
) -> tuple[str, ...]:
    triggers: set[str] = set()
    seconds_to_expiry = (_structure_expiry(case) - observation.observed_at).total_seconds()
    if seconds_to_expiry <= policy.lifecycle.latest_exit_minutes_to_expiry * 60:
        triggers.add("LATEST_EXIT")
    if observation.context.event_state in {EventState.LIVE_EVENT, EventState.UNSCHEDULED_SHOCK}:
        triggers.add("EVENT_OR_SHOCK")
    legs = _selected_quotes(case, observation)
    if legs is not None and max(abs(legs[1].signed_delta), abs(legs[2].signed_delta)) > (
        policy.lifecycle.maximum_short_abs_delta
    ):
        triggers.add("SHORT_DELTA")
    entry_index = _required_decimal(case.entry_index_price_usd, "entry_index_price_usd")
    if abs(observation.context.index_price / entry_index - Decimal(1)) > (
        policy.lifecycle.maximum_adverse_move_fraction
    ):
        triggers.add("ADVERSE_MOVE")
    if observation.context.rv_acceleration > policy.lifecycle.maximum_rv_acceleration:
        triggers.add("RV_ACCELERATION")
    vrp = (
        observation.context.same_session_implied_variance_proxy
        / observation.context.trailing_realized_variance_proxy
    )
    if vrp < policy.environment.minimum_vrp_ratio:
        triggers.add("VRP_PROXY_DISSIPATED")
    if close is not None:
        credit = _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        result = credit + close.native_net_cashflow
        if result >= credit * policy.lifecycle.take_profit_fraction_of_credit:
            triggers.add("TAKE_PROFIT")
        if -result >= credit * policy.lifecycle.maximum_loss_multiple_of_credit:
            triggers.add("MAXIMUM_LOSS")
    return tuple(reason for reason in policy.lifecycle.trigger_priority if reason in triggers)


def _close_projection(
    case: TradeCase,
    observation: MarketObservation,
    legs: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None,
) -> Btc0DteCondorCloseProjection | None:
    if legs is None:
        return None
    return project_btc_0dte_condor_close(
        long_put=legs[0],
        short_put=legs[1],
        short_call=legs[2],
        long_call=legs[3],
        amount=_structure_amount(case),
        boundary_index_price=observation.context.index_price,
    )


def _selected_quotes(
    case: TradeCase,
    observation: MarketObservation,
) -> tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None:
    return _quotes_for_structure(
        case.selected_structure,
        expiry=_structure_expiry(case),
        observation=observation,
    )


def _quotes_for_structure(
    structure: dict[str, object],
    *,
    expiry: datetime,
    observation: MarketObservation,
) -> tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote] | None:
    by_name = {quote.instrument_name: quote for quote in observation.quotes}
    frozen_legs = _structure_legs_from_mapping(structure)
    names = tuple(leg[0] for leg in frozen_legs)
    if any(name not in by_name for name in names):
        return None
    quotes = tuple(by_name[name] for name in names)
    if any(
        quote.product != BTC
        or quote.strike != frozen[1]
        or quote.option_type.value != frozen[2]
        or quote.delivery_fee_exempt != frozen[3]
        or quote.expiry != expiry
        for quote, frozen in zip(quotes, frozen_legs, strict=True)
    ):
        return None
    return quotes  # type: ignore[return-value]


def _market_path_point(
    *,
    structure: dict[str, object],
    expiry: datetime,
    observation: MarketObservation,
    phase: ShadowPathPhase,
    reunderwriting_id: str | None = None,
    native_result_btc: Decimal | None = None,
    boundary_reference_result_usd: Decimal | None = None,
    combo_fee_native: Decimal | None = None,
    valuation_method_id: str | None = None,
    valuation_reason: str | None = None,
    unknown_reason: str | None = None,
) -> ShadowPathPoint:
    reason = unknown_reason or (
        observation.data_health_blockers[0] if observation.data_health_blockers else None
    )
    legs = None
    if reason is None:
        legs = _quotes_for_structure(structure, expiry=expiry, observation=observation)
        if legs is None:
            reason = "SELECTED_STRUCTURE_QUOTES_MISSING"
    if reason is not None:
        return ShadowPathPoint(
            phase=phase,
            observation_status=ObservationStatus.UNKNOWN,
            observation_id=observation.identity,
            observed_at=observation.observed_at,
            known_at=observation.known_at,
            reunderwriting_id=reunderwriting_id,
            index_price_usd=None,
            native_result_btc=None,
            boundary_reference_result_usd=None,
            combo_fee_native=None,
            short_put_abs_delta=None,
            short_call_abs_delta=None,
            net_delta=None,
            put_short_distance_usd=None,
            call_short_distance_usd=None,
            long_put_mark_iv=None,
            short_put_mark_iv=None,
            short_call_mark_iv=None,
            long_call_mark_iv=None,
            same_session_implied_variance_proxy=None,
            trailing_realized_variance_proxy=None,
            rv_acceleration=None,
            jump_share=None,
            directional_persistence=None,
            event_state=None,
            valuation_method_id=None,
            valuation_reason=None,
            reason=reason,
        )
    assert legs is not None
    context = observation.context
    return ShadowPathPoint(
        phase=phase,
        observation_status=ObservationStatus.KNOWN,
        observation_id=observation.identity,
        observed_at=observation.observed_at,
        known_at=observation.known_at,
        reunderwriting_id=reunderwriting_id,
        index_price_usd=context.index_price,
        native_result_btc=native_result_btc,
        boundary_reference_result_usd=boundary_reference_result_usd,
        combo_fee_native=combo_fee_native,
        short_put_abs_delta=abs(legs[1].signed_delta),
        short_call_abs_delta=abs(legs[2].signed_delta),
        net_delta=(
            legs[0].signed_delta
            - legs[1].signed_delta
            - legs[2].signed_delta
            + legs[3].signed_delta
        ),
        put_short_distance_usd=context.index_price - legs[1].strike,
        call_short_distance_usd=legs[2].strike - context.index_price,
        long_put_mark_iv=legs[0].mark_iv,
        short_put_mark_iv=legs[1].mark_iv,
        short_call_mark_iv=legs[2].mark_iv,
        long_call_mark_iv=legs[3].mark_iv,
        same_session_implied_variance_proxy=context.same_session_implied_variance_proxy,
        trailing_realized_variance_proxy=context.trailing_realized_variance_proxy,
        rv_acceleration=context.rv_acceleration,
        jump_share=context.jump_share,
        directional_persistence=context.directional_persistence,
        event_state=context.event_state,
        valuation_method_id=valuation_method_id,
        valuation_reason=valuation_reason,
        reason=None,
    )


def _append_path_point(
    case: TradeCase,
    point: ShadowPathPoint,
    *,
    terminal: bool = False,
) -> TradeCase:
    return replace(
        case,
        explanation_path=_path_with_point(
            case.explanation_path,
            point,
            terminal=terminal,
        ),
        last_observation_id=point.observation_id,
        last_observed_at=point.observed_at,
    )


def _path_with_point(
    path: ShadowExplanationPath,
    point: ShadowPathPoint,
    *,
    terminal: bool = False,
) -> ShadowExplanationPath:
    if point.observation_id == path.last_observation_id:
        if point.observed_at != path.last_observed_at:
            raise ValueError("repeated explanation observation has a different boundary")
        return path
    if point.observed_at <= path.last_observed_at:
        raise ValueError("explanation observations must be strictly chronological")
    retain = len(path.points) < MAX_RETAINED_EXPLANATION_POINTS - 1
    if terminal:
        if point.phase is not ShadowPathPhase.EXIT:
            raise ValueError("only a terminal exit may consume the reserved path point")
        if len(path.points) >= MAX_RETAINED_EXPLANATION_POINTS:
            raise ValueError("explanation path did not reserve its terminal point")
        retain = True
    return replace(
        path,
        observation_count=path.observation_count + 1,
        last_observation_id=point.observation_id,
        last_observed_at=point.observed_at,
        points=(*path.points, point) if retain else path.points,
        statistics=_updated_path_statistics(path.statistics, point),
    )


def _updated_path_statistics(
    statistics: tuple[ShadowPathStatistic, ...],
    point: ShadowPathPoint,
) -> tuple[ShadowPathStatistic, ...]:
    current = {statistic.kind: statistic for statistic in statistics}
    for kind, value in _path_statistic_values(point):
        previous = current.get(kind)
        replace_extreme = previous is None or (
            value < previous.value
            if kind
            in {
                ShadowPathStatisticKind.MINIMUM_PUT_SHORT_DISTANCE_USD,
                ShadowPathStatisticKind.MINIMUM_CALL_SHORT_DISTANCE_USD,
                ShadowPathStatisticKind.MINIMUM_IMPLIED_VARIANCE_PROXY,
                ShadowPathStatisticKind.MINIMUM_TRAILING_RV_PROXY,
                ShadowPathStatisticKind.MINIMUM_SHORT_MARK_IV,
            }
            else value > previous.value
        )
        if replace_extreme:
            current[kind] = ShadowPathStatistic(
                kind=kind,
                value=value,
                observation_id=point.observation_id,
                observed_at=point.observed_at,
                known_at=point.known_at,
            )
    return tuple(current[kind] for kind in sorted(current, key=lambda item: item.value))


def _path_statistic_values(
    point: ShadowPathPoint,
) -> tuple[tuple[ShadowPathStatisticKind, Decimal], ...]:
    if point.observation_status is ObservationStatus.UNKNOWN:
        return ()
    values: list[tuple[ShadowPathStatisticKind, Decimal]] = []
    if point.native_result_btc is not None:
        values.extend(
            (
                (
                    ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BTC,
                    max(Decimal(0), point.native_result_btc),
                ),
                (
                    ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BTC,
                    max(Decimal(0), -point.native_result_btc),
                ),
            )
        )
    if point.boundary_reference_result_usd is not None:
        values.extend(
            (
                (
                    ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BOUNDARY_USD,
                    max(Decimal(0), point.boundary_reference_result_usd),
                ),
                (
                    ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BOUNDARY_USD,
                    max(Decimal(0), -point.boundary_reference_result_usd),
                ),
            )
        )
    assert point.short_put_abs_delta is not None
    assert point.short_call_abs_delta is not None
    assert point.put_short_distance_usd is not None
    assert point.call_short_distance_usd is not None
    assert point.same_session_implied_variance_proxy is not None
    assert point.trailing_realized_variance_proxy is not None
    assert point.short_put_mark_iv is not None
    assert point.short_call_mark_iv is not None
    assert point.rv_acceleration is not None
    assert point.jump_share is not None
    assert point.directional_persistence is not None
    if point.phase is not ShadowPathPhase.DECISION:
        values.extend(
            (
                (
                    ShadowPathStatisticKind.MAXIMUM_SHORT_ABS_DELTA,
                    max(point.short_put_abs_delta, point.short_call_abs_delta),
                ),
                (
                    ShadowPathStatisticKind.MINIMUM_PUT_SHORT_DISTANCE_USD,
                    point.put_short_distance_usd,
                ),
                (
                    ShadowPathStatisticKind.MINIMUM_CALL_SHORT_DISTANCE_USD,
                    point.call_short_distance_usd,
                ),
            )
        )
    values.extend(
        (
            (
                ShadowPathStatisticKind.MINIMUM_IMPLIED_VARIANCE_PROXY,
                point.same_session_implied_variance_proxy,
            ),
            (
                ShadowPathStatisticKind.MAXIMUM_IMPLIED_VARIANCE_PROXY,
                point.same_session_implied_variance_proxy,
            ),
            (
                ShadowPathStatisticKind.MINIMUM_TRAILING_RV_PROXY,
                point.trailing_realized_variance_proxy,
            ),
            (
                ShadowPathStatisticKind.MAXIMUM_TRAILING_RV_PROXY,
                point.trailing_realized_variance_proxy,
            ),
            (
                ShadowPathStatisticKind.MINIMUM_SHORT_MARK_IV,
                min(point.short_put_mark_iv, point.short_call_mark_iv),
            ),
            (
                ShadowPathStatisticKind.MAXIMUM_SHORT_MARK_IV,
                max(point.short_put_mark_iv, point.short_call_mark_iv),
            ),
            (
                ShadowPathStatisticKind.MAXIMUM_RV_ACCELERATION,
                point.rv_acceleration,
            ),
            (ShadowPathStatisticKind.MAXIMUM_JUMP_SHARE, point.jump_share),
            (
                ShadowPathStatisticKind.MAXIMUM_DIRECTIONAL_PERSISTENCE,
                point.directional_persistence,
            ),
        )
    )
    return tuple(values)


def record_shadow_gap(
    case: TradeCase,
    *,
    known_at: datetime,
    reason: str,
    source: str,
    observation: MarketObservation | None = None,
    reunderwriting_id: str | None = None,
) -> TradeCase:
    gap = ShadowPathGap(
        known_at=known_at,
        reason=reason,
        source=source,
        observation_id=observation.identity if observation is not None else None,
        observed_at=observation.observed_at if observation is not None else None,
        reunderwriting_id=reunderwriting_id,
    )
    if gap.identity in {item.identity for item in case.explanation_path.gaps}:
        return case
    return replace(
        case,
        explanation_path=replace(
            case.explanation_path,
            gaps=(*case.explanation_path.gaps, gap),
        ),
    )


def _structure_legs(
    case: TradeCase,
) -> tuple[
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
]:
    return _structure_legs_from_mapping(case.selected_structure)


def _structure_legs_from_mapping(
    structure: dict[str, object],
) -> tuple[
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
]:
    legs = _mapping(structure.get("legs"), "selected_structure.legs")
    output: list[tuple[str, Decimal, str, bool]] = []
    for role in ("long_put", "short_put", "short_call", "long_call"):
        leg = _mapping(legs.get(role), f"legs.{role}")
        output.append(
            (
                _text(leg, "instrument_name"),
                _decimal(leg, "strike"),
                _text(leg, "option_type"),
                _boolean(leg, "delivery_fee_exempt"),
            )
        )
    return tuple(output)  # type: ignore[return-value]


def _structure_alternatives(case: TradeCase) -> tuple[dict[str, object], ...]:
    return tuple(
        _mapping(member, "retained_alternative")
        for member in _object_sequence(case.selected_structure, "retained_alternatives")
    )


def _structure_instrument_names(case: TradeCase) -> tuple[str, str, str, str]:
    return tuple(leg[0] for leg in _structure_legs(case))  # type: ignore[return-value]


def _route_economics(evidence: ShadowRouteEvidence) -> tuple[object, ...]:
    return (
        evidence.fee_model_id,
        evidence.native_gross_credit,
        evidence.standard_combo_fee_projection_native,
        evidence.native_net_credit,
        evidence.boundary_index_price_usd,
        evidence.boundary_net_credit_usd,
    )


def _recorded_pricing_economics(pricing: dict[str, object]) -> tuple[object, ...]:
    return (
        _text(pricing, "fee_model_id"),
        _decimal(pricing, "native_gross_credit"),
        _decimal(pricing, "combo_standard_fee_native"),
        _decimal(pricing, "native_net_credit"),
        _decimal(pricing, "boundary_index_price_usd"),
        _decimal(pricing, "boundary_net_credit_usd"),
    )


def _structure_amount(case: TradeCase) -> Decimal:
    return _decimal(case.selected_structure, "option_amount")


def _structure_expiry(case: TradeCase) -> datetime:
    return _parse_iso(_text(case.selected_structure, "expiry"), "expiry")


def _quotes_strictly_after(
    quotes: tuple[OptionQuote, OptionQuote, OptionQuote, OptionQuote],
    boundary: datetime,
) -> bool:
    boundary_ms = int(_utc(boundary, "boundary").timestamp() * 1000)
    return all(
        quote.source_timestamp_ms > boundary_ms and quote.received_timestamp_ms > boundary_ms
        for quote in quotes
    )


def _advance_observation(
    case: TradeCase,
    observation: MarketObservation,
) -> TradeCase:
    return replace(
        case,
        last_observation_id=observation.identity,
        last_observed_at=observation.observed_at,
    )


def _require_next_observation(
    case: TradeCase,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> None:
    if observation.channel_id is not case.channel_id:
        raise ValueError("Position observation Channel mismatch")
    if observation.data_health_policy_id != policy.observation.identity:
        raise ValueError("Position observation DataHealth Policy mismatch")
    last = case.last_observed_at or case.entry_observed_at
    if last is None or observation.observed_at <= last:
        raise ValueError("Position observation must be strictly later")


def _require_case_policy(case: TradeCase, policy: BtcShortVolPolicy) -> None:
    if case.channel_id is not policy.channel_id or case.decision_policy_id != policy.identity:
        raise ValueError("TradeCase does not match Policy")


def _require_open_position(case: TradeCase, policy: BtcShortVolPolicy) -> None:
    _require_case_policy(case, policy)
    if case.position_id is None or case.position_state is None:
        raise ValueError("TradeCase has no Shadow Position")
    if case.position_state is PositionState.TERMINAL:
        raise ValueError("Shadow Position is already terminal")


def _pending_hold_counterfactual(known_at: datetime) -> ShadowExitCounterfactual:
    return ShadowExitCounterfactual(
        kind=ExitCounterfactualKind.HOLD_TO_EXPIRY,
        status=CounterfactualStatus.UNKNOWN,
        known_at=known_at,
        terminal_evidence_id=None,
        native_result_btc=None,
        boundary_reference_result_usd=None,
        fee_model_id=None,
        reason="OFFICIAL_EXPIRY_SETTLEMENT_PENDING",
    )


def _outcome_explanation(
    case: TradeCase,
    *,
    explanation_path: ShadowExplanationPath,
    evaluation: ShadowEntryReunderwriting,
    terminal_method: TerminalMethod,
    terminal_at: datetime,
    terminal_native_result: Decimal | None,
    terminal_boundary_result: Decimal | None,
    terminal_combo_fee_native: Decimal | None,
    alternative_outcomes: tuple[ShadowAlternativeOutcome, ...],
    primary_exit_category: str,
    primary_exit_reason: str,
    hold_to_expiry: ShadowExitCounterfactual,
) -> ShadowOutcomeExplanation:
    statistic_values = {
        statistic.kind: statistic.value for statistic in explanation_path.statistics
    }
    maximum_favorable_excursion_btc = statistic_values.get(
        ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BTC
    )
    maximum_adverse_excursion_btc = statistic_values.get(
        ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BTC
    )
    maximum_favorable_excursion_boundary_usd = statistic_values.get(
        ShadowPathStatisticKind.MAXIMUM_FAVORABLE_EXCURSION_BOUNDARY_USD
    )
    maximum_adverse_excursion_boundary_usd = statistic_values.get(
        ShadowPathStatisticKind.MAXIMUM_ADVERSE_EXCURSION_BOUNDARY_USD
    )
    if terminal_method is TerminalMethod.CONTRACT_SETTLEMENT:
        assert terminal_native_result is not None and terminal_boundary_result is not None
        maximum_favorable_excursion_btc = max(
            maximum_favorable_excursion_btc or Decimal(0),
            terminal_native_result,
            Decimal(0),
        )
        maximum_adverse_excursion_btc = max(
            maximum_adverse_excursion_btc or Decimal(0),
            -terminal_native_result,
            Decimal(0),
        )
        maximum_favorable_excursion_boundary_usd = max(
            maximum_favorable_excursion_boundary_usd or Decimal(0),
            terminal_boundary_result,
            Decimal(0),
        )
        maximum_adverse_excursion_boundary_usd = max(
            maximum_adverse_excursion_boundary_usd or Decimal(0),
            -terminal_boundary_result,
            Decimal(0),
        )
    maximum_short_abs_delta = statistic_values.get(ShadowPathStatisticKind.MAXIMUM_SHORT_ABS_DELTA)
    minimum_put_short_distance_usd = statistic_values.get(
        ShadowPathStatisticKind.MINIMUM_PUT_SHORT_DISTANCE_USD
    )
    minimum_call_short_distance_usd = statistic_values.get(
        ShadowPathStatisticKind.MINIMUM_CALL_SHORT_DISTANCE_USD
    )
    entry_fee = (
        evaluation.combo_fee_native
        if evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE
        else None
    )
    return ShadowOutcomeExplanation(
        method_id=SHADOW_OUTCOME_EXPLANATION_METHOD_ID,
        path_id=explanation_path.identity,
        entry_reunderwriting_id=evaluation.identity,
        decision_metrics=evaluation.decision_metrics,
        entry_metrics=evaluation.entry_metrics,
        maximum_favorable_excursion_btc=maximum_favorable_excursion_btc,
        maximum_adverse_excursion_btc=maximum_adverse_excursion_btc,
        maximum_favorable_excursion_boundary_usd=(maximum_favorable_excursion_boundary_usd),
        maximum_adverse_excursion_boundary_usd=(maximum_adverse_excursion_boundary_usd),
        maximum_short_abs_delta=maximum_short_abs_delta,
        minimum_put_short_distance_usd=minimum_put_short_distance_usd,
        minimum_call_short_distance_usd=minimum_call_short_distance_usd,
        put_short_breached=(
            minimum_put_short_distance_usd <= 0
            if minimum_put_short_distance_usd is not None
            else None
        ),
        call_short_breached=(
            minimum_call_short_distance_usd <= 0
            if minimum_call_short_distance_usd is not None
            else None
        ),
        gap_ids=tuple(gap.identity for gap in explanation_path.gaps),
        alternative_outcomes=alternative_outcomes,
        entry_combo_fee_native=entry_fee,
        terminal_combo_fee_native=terminal_combo_fee_native,
        total_combo_fee_native=(
            entry_fee + (terminal_combo_fee_native or Decimal(0)) if entry_fee is not None else None
        ),
        primary_exit_category=primary_exit_category,
        primary_exit_reason=primary_exit_reason,
        no_entry=ShadowExitCounterfactual(
            kind=ExitCounterfactualKind.NO_ENTRY,
            status=CounterfactualStatus.EVALUABLE,
            known_at=terminal_at,
            terminal_evidence_id=None,
            native_result_btc=Decimal(0),
            boundary_reference_result_usd=Decimal(0),
            fee_model_id=None,
            reason=None,
        ),
        hold_to_expiry=hold_to_expiry,
        complete=hold_to_expiry.status is not CounterfactualStatus.UNKNOWN,
    )


def _position_outcome(
    case: TradeCase,
    *,
    method: TerminalMethod,
    terminal_at: datetime,
    terminal_evidence_id: str | None,
    native_result: Decimal,
    boundary_result: Decimal,
    fee_model_id: str,
    source: str,
    terminal_combo_fee_native: Decimal | None,
    alternative_outcomes: tuple[ShadowAlternativeOutcome, ...],
    hold_to_expiry: ShadowExitCounterfactual,
) -> ShadowCaseOutcome:
    continuity = False if case.gap_observed else None
    eligibility = OutcomeEligibility(
        decision_evaluable=EligibilityFact(True, "CANDIDATE_DECISION_EVALUABLE"),
        future_path_known=EligibilityFact(None, "WINDOW_OUTCOME_OWNS_FUTURE_PATH"),
        future_path_continuous=EligibilityFact(
            continuity,
            "DATA_GAP_OBSERVED" if case.gap_observed else "WINDOW_OUTCOME_OWNS_CONTINUITY",
        ),
        shadow_entry_evaluable=EligibilityFact(True, "ATOMIC_SHADOW_ENTRY_EVALUABLE"),
        terminal_economics_evaluable=EligibilityFact(True, "TERMINAL_ECONOMICS_KNOWN"),
        live_execution_attributable=EligibilityFact(False, "PUBLIC_SHADOW_HAS_NO_LIVE_EXECUTION"),
        strategy_population_eligible=EligibilityFact(
            False if case.gap_observed else None,
            "DATA_GAP_OBSERVED" if case.gap_observed else "WINDOW_OUTCOME_REQUIRED",
        ),
        qualification_eligible=EligibilityFact(
            False if case.gap_observed else None,
            "DATA_GAP_OBSERVED" if case.gap_observed else "POLICY_NOT_QUALIFIED",
        ),
    )
    evaluation = case.entry_reunderwriting
    if evaluation is None or (
        case.exit_intent is None and method is TerminalMethod.WHOLE_PRODUCT_EXIT
    ):
        raise ValueError("Position Outcome requires final Entry and terminal reason truth")
    primary_category = case.exit_intent.category if case.exit_intent is not None else "TIME"
    primary_reason = (
        case.exit_intent.reason if case.exit_intent is not None else "EXPIRY_SETTLEMENT"
    )
    explanation = _outcome_explanation(
        case,
        explanation_path=case.explanation_path,
        evaluation=evaluation,
        terminal_method=method,
        terminal_at=terminal_at,
        terminal_native_result=native_result,
        terminal_boundary_result=boundary_result,
        terminal_combo_fee_native=terminal_combo_fee_native,
        alternative_outcomes=alternative_outcomes,
        primary_exit_category=primary_category,
        primary_exit_reason=primary_reason,
        hold_to_expiry=hold_to_expiry,
    )
    return ShadowCaseOutcome(
        terminal_method=method,
        terminal_at=terminal_at,
        entry_status=ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE,
        entry_observation_id=case.entry_observation_id,
        terminal_evidence_id=terminal_evidence_id,
        native_result_btc=native_result,
        boundary_reference_result_usd=boundary_result,
        fee_model_id=fee_model_id,
        shadow_model_id=case.decision_route_evidence.model_id,
        terminal_source=source,
        data_gap_observed=case.gap_observed,
        reason=None,
        eligibility=eligibility,
        explanation=explanation,
    )


def _no_position_outcome(
    case: TradeCase,
    *,
    evaluation: ShadowEntryReunderwriting,
    explanation_path: ShadowExplanationPath,
) -> ShadowCaseOutcome:
    known = evaluation.status is not ShadowEntryStatus.ENTRY_EVIDENCE_UNKNOWN
    eligibility = OutcomeEligibility(
        decision_evaluable=EligibilityFact(True, "CANDIDATE_DECISION_EVALUABLE"),
        future_path_known=EligibilityFact(None, "WINDOW_OUTCOME_OWNS_FUTURE_PATH"),
        future_path_continuous=EligibilityFact(None, "WINDOW_OUTCOME_OWNS_CONTINUITY"),
        shadow_entry_evaluable=EligibilityFact(
            False if known else None,
            evaluation.reason or "SHADOW_ENTRY_UNKNOWN",
        ),
        terminal_economics_evaluable=EligibilityFact(False, "NO_SHADOW_POSITION"),
        live_execution_attributable=EligibilityFact(False, "PUBLIC_SHADOW_HAS_NO_LIVE_EXECUTION"),
        strategy_population_eligible=EligibilityFact(None, "WINDOW_OUTCOME_REQUIRED"),
        qualification_eligible=EligibilityFact(None, "POLICY_NOT_QUALIFIED"),
    )
    alternative_outcomes = tuple(
        ShadowAlternativeOutcome(
            candidate_id=basis.candidate_id,
            entry_basis_id=basis.identity,
            status=CounterfactualStatus.NOT_APPLICABLE,
            terminal_method=TerminalMethod.NO_POSITION,
            terminal_evidence_id=None,
            known_at=evaluation.known_at,
            native_result_btc=None,
            boundary_reference_result_usd=None,
            entry_combo_fee_native=None,
            terminal_combo_fee_native=None,
            reason=basis.reason or "NO_SHADOW_POSITION",
        )
        for basis in explanation_path.alternative_entry_bases
    )
    explanation = _outcome_explanation(
        case,
        explanation_path=explanation_path,
        evaluation=evaluation,
        terminal_method=TerminalMethod.NO_POSITION,
        terminal_at=evaluation.known_at,
        terminal_native_result=None,
        terminal_boundary_result=None,
        terminal_combo_fee_native=None,
        alternative_outcomes=alternative_outcomes,
        primary_exit_category="ENTRY",
        primary_exit_reason=evaluation.reason or evaluation.status.value,
        hold_to_expiry=ShadowExitCounterfactual(
            kind=ExitCounterfactualKind.HOLD_TO_EXPIRY,
            status=CounterfactualStatus.NOT_APPLICABLE,
            known_at=evaluation.known_at,
            terminal_evidence_id=None,
            native_result_btc=None,
            boundary_reference_result_usd=None,
            fee_model_id=None,
            reason="NO_SHADOW_POSITION",
        ),
    )
    return ShadowCaseOutcome(
        terminal_method=TerminalMethod.NO_POSITION,
        terminal_at=evaluation.known_at,
        entry_status=evaluation.status,
        entry_observation_id=evaluation.observation_id,
        terminal_evidence_id=None,
        native_result_btc=None,
        boundary_reference_result_usd=None,
        fee_model_id=None,
        shadow_model_id=evaluation.route_evidence.model_id,
        terminal_source="ENTRY_EVALUATION",
        data_gap_observed=bool(explanation_path.gaps),
        reason=evaluation.reason,
        eligibility=eligibility,
        explanation=explanation,
    )


def _trigger_category(reason: str) -> str:
    if reason in {"LATEST_EXIT"}:
        return "TIME"
    if reason in {"VRP_PROXY_DISSIPATED"}:
        return "THESIS"
    return "POSITION"


def _canonical_object(value: object) -> dict[str, object]:
    normalized = canonical_value(value)
    if not isinstance(normalized, dict):
        raise TypeError("canonical object must be a mapping")
    return normalized


def _json_text(value: object) -> str:
    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_mapping(value: str, field: str) -> dict[str, object]:
    try:
        return _mapping(json.loads(value), field)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is invalid canonical JSON") from exc


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _object_sequence(value: dict[str, object], field: str) -> tuple[object, ...]:
    member = value.get(field)
    if not isinstance(member, list):
        raise ValueError(f"{field} must be an array")
    return tuple(member)


def _text(value: dict[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text")
    return member


def _optional_text(value: dict[str, object], field: str) -> str | None:
    member = value.get(field)
    if member is None:
        return None
    if not isinstance(member, str) or not member:
        raise ValueError(f"{field} must be non-empty text or null")
    return member


def _boolean(value: dict[str, object], field: str) -> bool:
    member = value.get(field)
    if not isinstance(member, bool):
        raise ValueError(f"{field} must be boolean")
    return member


def _optional_boolean(value: dict[str, object], field: str) -> bool | None:
    member = value.get(field)
    if member is not None and not isinstance(member, bool):
        raise ValueError(f"{field} must be boolean or null")
    return member


def _integer(value: dict[str, object], field: str) -> int:
    member = value.get(field)
    if isinstance(member, bool) or not isinstance(member, int):
        raise ValueError(f"{field} must be an integer")
    return member


def _decimal(value: dict[str, object], field: str) -> Decimal:
    member = value.get(field)
    if not isinstance(member, str):
        raise ValueError(f"{field} must be canonical decimal text")
    parsed = Decimal(member)
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _optional_decimal(value: dict[str, object], field: str) -> Decimal | None:
    return None if value.get(field) is None else _decimal(value, field)


def _datetime(value: dict[str, object], field: str) -> datetime:
    return _parse_iso(_text(value, field), field)


def _optional_datetime(value: dict[str, object], field: str) -> datetime | None:
    return None if value.get(field) is None else _datetime(value, field)


def _parse_iso(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    return _utc(parsed, field)


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _text_tuple(value: dict[str, object], field: str) -> tuple[str, ...]:
    member = value.get(field)
    if not isinstance(member, list) or not all(isinstance(item, str) for item in member):
        raise ValueError(f"{field} must be an array of text")
    return tuple(member)


def _optional_enum[T: StrEnum](
    value: dict[str, object],
    field: str,
    kind: type[T],
) -> T | None:
    member = value.get(field)
    return None if member is None else kind(_text(value, field))


def _required(value: str | None, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _required_decimal(value: Decimal | None, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _required_datetime(value: datetime | None, field: str) -> datetime:
    if value is None:
        raise ValueError(f"{field} is required")
    return value


def _required_state(value: PositionState | None) -> PositionState:
    if value is None:
        raise ValueError("position_state is required")
    return value
