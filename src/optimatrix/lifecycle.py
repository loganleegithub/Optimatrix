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
    price_btc_0dte_condor,
    project_btc_0dte_condor_close,
    settle_btc_0dte_condor,
)
from optimatrix.products import BTC, ProductId

SHADOW_PRICING_BASIS = "SYNTHETIC_FOUR_LEG_COMPONENT_BOOK_ESTIMATE_V1"


class ShadowEntryStatus(StrEnum):
    SHADOW_ATOMIC_EVALUABLE = "SHADOW_ATOMIC_EVALUABLE"
    SHADOW_ATOMIC_NOT_EVALUABLE = "SHADOW_ATOMIC_NOT_EVALUABLE"
    UNKNOWN = "UNKNOWN"


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
class ShadowEntryEvaluation:
    status: ShadowEntryStatus
    final: bool
    observation_id: str | None
    observed_at: datetime | None
    known_at: datetime
    reason: str | None
    pricing_basis: str
    native_net_credit: Decimal | None
    combo_fee_native: Decimal | None
    boundary_index_price_usd: Decimal | None


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

    def __post_init__(self) -> None:
        _utc(self.terminal_at, "terminal_at")
        if not self.terminal_source:
            raise ValueError("terminal_source must be non-empty")
        if self.terminal_evidence_id is not None:
            require_identity(self.terminal_evidence_id, "terminal_evidence_id")

    @property
    def identity(self) -> str:
        return canonical_identity("ShadowCaseOutcomeV1", self)

    def as_object(self) -> dict[str, object]:
        value = _canonical_object(self)
        value["eligibility"] = self.eligibility.as_object()
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
    selected_structure_id: str
    selected_structure_json: str
    risk_allocation_id: str
    risk_allocation_json: str
    opened_at: datetime
    entry_deadline: datetime
    entry_pricing_basis: str
    entry_status: ShadowEntryStatus | None = None
    entry_final: bool = False
    entry_observation_id: str | None = None
    entry_observed_at: datetime | None = None
    entry_known_at: datetime | None = None
    entry_reason: str | None = None
    entry_pricing_json: str | None = None
    position_id: str | None = None
    position_state: PositionState | None = None
    entry_native_net_credit: Decimal | None = None
    entry_index_price_usd: Decimal | None = None
    entry_vrp_proxy_ratio: Decimal | None = None
    last_observation_id: str | None = None
    last_observed_at: datetime | None = None
    gap_observed: bool = False
    exit_intent: ExitIntent | None = None
    outcome: ShadowCaseOutcome | None = None

    def __post_init__(self) -> None:
        if self.truth_layer != "SHADOW_PROJECTION":
            raise ValueError("B3 TradeCase truth layer must be SHADOW_PROJECTION")
        if self.entry_pricing_basis != SHADOW_PRICING_BASIS:
            raise ValueError("B3 TradeCase has an unsupported Shadow pricing basis")
        for value, field in (
            (self.decision_record_id, "decision_record_id"),
            (self.decision_window_id, "decision_window_id"),
            (self.decision_policy_id, "decision_policy_id"),
            (self.selected_structure_id, "selected_structure_id"),
            (self.risk_allocation_id, "risk_allocation_id"),
        ):
            require_identity(value, field)
        boundary = _utc(self.decision_boundary, "decision_boundary")
        if _utc(self.opened_at, "opened_at") < boundary:
            raise ValueError("TradeCase cannot open before its Decision")
        if _utc(self.entry_deadline, "entry_deadline") <= boundary:
            raise ValueError("TradeCase Entry deadline must be after its Decision")
        structure = self.selected_structure
        if structure.get("candidate_id") != self.selected_structure_id:
            raise ValueError("TradeCase structure identity mismatch")
        allocation = self.risk_allocation
        if allocation.get("allocation_id") != self.risk_allocation_id:
            raise ValueError("TradeCase allocation identity mismatch")
        if allocation.get("candidate_id") != self.selected_structure_id:
            raise ValueError("TradeCase allocation does not bind its structure")
        if self.entry_final and self.entry_status is None:
            raise ValueError("final Entry requires a status")
        if not self.entry_final and (self.position_id is not None or self.outcome is not None):
            raise ValueError("provisional Entry cannot create Position or Outcome")
        if self.entry_status is not None and self.entry_known_at is None:
            raise ValueError("Entry evaluation requires a known-at boundary")
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
            has_position = self.position_id is not None
            if has_position != (self.outcome.terminal_method is not TerminalMethod.NO_POSITION):
                raise ValueError("Outcome terminal method does not match Position existence")
            if has_position != (self.position_state is PositionState.TERMINAL):
                raise ValueError("Position Outcome requires terminal Position state")

    @property
    def identity(self) -> str:
        structure = self.selected_structure
        return canonical_identity(
            "TradeCaseV1",
            self.channel_id,
            self.truth_layer,
            self.decision_window_id,
            self.decision_policy_id,
            self.selected_structure_id,
            structure.get("option_amount"),
            self.decision_boundary,
        )

    @property
    def snapshot_identity(self) -> str:
        return canonical_identity("TradeCaseSnapshotV1", self.as_object(include_snapshot=False))

    @property
    def selected_structure(self) -> dict[str, object]:
        return _json_mapping(self.selected_structure_json, "selected_structure")

    @property
    def risk_allocation(self) -> dict[str, object]:
        return _json_mapping(self.risk_allocation_json, "risk_allocation")

    @property
    def entry_pricing(self) -> dict[str, object] | None:
        return (
            _json_mapping(self.entry_pricing_json, "entry_pricing")
            if self.entry_pricing_json is not None
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
            selected_structure_id=_text(item, "selected_structure_id"),
            selected_structure_json=_text(item, "selected_structure_json"),
            risk_allocation_id=_text(item, "risk_allocation_id"),
            risk_allocation_json=_text(item, "risk_allocation_json"),
            opened_at=_datetime(item, "opened_at"),
            entry_deadline=_datetime(item, "entry_deadline"),
            entry_pricing_basis=_text(item, "entry_pricing_basis"),
            entry_status=_optional_enum(item, "entry_status", ShadowEntryStatus),
            entry_final=_boolean(item, "entry_final"),
            entry_observation_id=_optional_text(item, "entry_observation_id"),
            entry_observed_at=_optional_datetime(item, "entry_observed_at"),
            entry_known_at=_optional_datetime(item, "entry_known_at"),
            entry_reason=_optional_text(item, "entry_reason"),
            entry_pricing_json=_optional_text(item, "entry_pricing_json"),
            position_id=_optional_text(item, "position_id"),
            position_state=_optional_enum(item, "position_state", PositionState),
            entry_native_net_credit=_optional_decimal(item, "entry_native_net_credit"),
            entry_index_price_usd=_optional_decimal(item, "entry_index_price_usd"),
            entry_vrp_proxy_ratio=_optional_decimal(item, "entry_vrp_proxy_ratio"),
            last_observation_id=_optional_text(item, "last_observation_id"),
            last_observed_at=_optional_datetime(item, "last_observed_at"),
            gap_observed=_boolean(item, "gap_observed"),
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
    return TradeCase(
        channel_id=record.window.channel_id,
        truth_layer="SHADOW_PROJECTION",
        decision_record_id=record.identity,
        decision_window_id=record.window.identity,
        decision_policy_id=record.decision_policy_id,
        decision_boundary=record.known_at,
        selected_structure_id=_required(record.selected_structure_id, "selected_structure_id"),
        selected_structure_json=record.selected_structure_json,
        risk_allocation_id=_required(record.risk_allocation_id, "risk_allocation_id"),
        risk_allocation_json=record.risk_allocation_json,
        opened_at=record.known_at,
        entry_deadline=record.known_at
        + timedelta(seconds=policy.lifecycle.entry_evaluation_window_seconds),
        entry_pricing_basis=SHADOW_PRICING_BASIS,
    )


def evaluate_shadow_entry(
    case: TradeCase,
    *,
    observation: MarketObservation | None,
    policy: BtcShortVolPolicy,
    known_at: datetime,
) -> tuple[TradeCase, ShadowEntryEvaluation]:
    _require_case_policy(case, policy)
    boundary = _utc(known_at, "known_at")
    if case.entry_final:
        raise ValueError("TradeCase Entry result is already final")
    reason = _entry_unknown_reason(case, observation, boundary, policy)
    if reason is not None:
        final = boundary >= case.entry_deadline
        evaluation = ShadowEntryEvaluation(
            ShadowEntryStatus.UNKNOWN,
            final,
            observation.identity if observation is not None else None,
            observation.observed_at if observation is not None else None,
            boundary,
            reason,
            case.entry_pricing_basis,
            None,
            None,
            None,
        )
        updated = _apply_entry_evaluation(case, evaluation, pricing=None)
        return updated, evaluation

    assert observation is not None
    legs = _selected_quotes(case, observation)
    if legs is None:
        evaluation = ShadowEntryEvaluation(
            ShadowEntryStatus.UNKNOWN,
            boundary >= case.entry_deadline,
            observation.identity,
            observation.observed_at,
            boundary,
            "SELECTED_STRUCTURE_QUOTES_MISSING",
            case.entry_pricing_basis,
            None,
            None,
            None,
        )
        return _apply_entry_evaluation(case, evaluation, pricing=None), evaluation
    if not _quotes_strictly_after(legs, case.decision_boundary):
        evaluation = ShadowEntryEvaluation(
            ShadowEntryStatus.UNKNOWN,
            boundary >= case.entry_deadline,
            observation.identity,
            observation.observed_at,
            boundary,
            "ENTRY_QUOTES_NOT_STRICTLY_FUTURE",
            case.entry_pricing_basis,
            None,
            None,
            None,
        )
        return _apply_entry_evaluation(case, evaluation, pricing=None), evaluation
    pricing = price_btc_0dte_condor(
        long_put=legs[0],
        short_put=legs[1],
        short_call=legs[2],
        long_call=legs[3],
        amount=_structure_amount(case),
        boundary_index_price=observation.context.index_price,
    )
    if pricing is None:
        evaluation = ShadowEntryEvaluation(
            ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE,
            True,
            observation.identity,
            observation.observed_at,
            observation.known_at,
            "WHOLE_PRODUCT_NOT_PRICE_EVALUABLE_AT_OBSERVED_DEPTH",
            case.entry_pricing_basis,
            None,
            None,
            observation.context.index_price,
        )
        return _apply_entry_evaluation(case, evaluation, pricing=None), evaluation

    evaluation = ShadowEntryEvaluation(
        ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE,
        True,
        observation.identity,
        observation.observed_at,
        observation.known_at,
        None,
        case.entry_pricing_basis,
        pricing.native_net_credit,
        pricing.combo_standard_fee_native,
        pricing.boundary_index_price_usd,
    )
    return _apply_entry_evaluation(
        case, evaluation, pricing=pricing, observation=observation
    ), evaluation


def monitor_shadow_position(
    case: TradeCase,
    *,
    observation: MarketObservation,
    policy: BtcShortVolPolicy,
) -> tuple[TradeCase, ShadowMonitorEvaluation]:
    _require_open_position(case, policy)
    _require_next_observation(case, observation, policy)
    if observation.observed_at >= _structure_expiry(case):
        updated = _advance_observation(case, observation, gap=False)
        return updated, ShadowMonitorEvaluation(
            ObservationStatus.KNOWN,
            observation.identity,
            observation.observed_at,
            PositionAction.SETTLE_AT_EXPIRY,
            ("EXPIRY_REACHED",),
            None,
            case.exit_intent,
            None,
        )
    latest_exit_due = (
        _structure_expiry(case) - observation.observed_at
    ).total_seconds() <= policy.lifecycle.latest_exit_minutes_to_expiry * 60
    if observation.data_health_blockers:
        intent = _latest_exit_intent(case, observation, policy) if latest_exit_due else None
        updated = replace(
            _advance_observation(case, observation, gap=True),
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
        updated = replace(
            _advance_observation(case, observation, gap=True),
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
        updated = _advance_observation(case, observation, gap=False)
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
    updated = replace(
        _advance_observation(case, observation, gap=False),
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
    legs = None if observation.data_health_blockers else _selected_quotes(case, observation)
    if legs is not None and not _quotes_strictly_after(legs, case.exit_intent.known_at):
        legs = None
    close = _close_projection(case, observation, legs) if legs is not None else None
    if close is None:
        updated = _advance_observation(
            case,
            observation,
            gap=bool(observation.data_health_blockers or legs is None),
        )
        evaluation = ShadowExitEvaluation(
            ObservationStatus.UNKNOWN,
            observation.identity,
            observation.observed_at,
            None,
            None,
            False,
            (
                observation.data_health_blockers[0]
                if observation.data_health_blockers
                else "WHOLE_PRODUCT_EXIT_NOT_PRICE_EVALUABLE"
            ),
        )
        return updated, evaluation
    native_result = (
        _required_decimal(case.entry_native_net_credit, "entry_native_net_credit")
        + close.native_net_cashflow
    )
    outcome = _position_outcome(
        case,
        method=TerminalMethod.WHOLE_PRODUCT_EXIT,
        terminal_at=observation.known_at,
        terminal_evidence_id=observation.identity,
        native_result=native_result,
        boundary_result=native_result * observation.context.index_price,
        fee_model_id=close.fee_model_id,
        source="STRICTLY_LATER_PUBLIC_FOUR_LEG_ESTIMATE",
    )
    updated = replace(
        _advance_observation(case, observation, gap=False),
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
    outcome = _position_outcome(
        case,
        method=TerminalMethod.CONTRACT_SETTLEMENT,
        terminal_at=boundary,
        terminal_evidence_id=settlement.identity,
        native_result=native_result,
        boundary_result=native_result * settlement.delivery_price_usd,
        fee_model_id="DERIBIT_DAILY_OPTION_DELIVERY_FEE_EXEMPT"
        if economics.delivery_fee_native == 0
        else "DERIBIT_STANDARD_DELIVERY_FEE",
        source=(f"{settlement.evidence_kind.value}:{settlement.source_id}:{settlement.method_id}"),
    )
    return replace(case, position_state=PositionState.TERMINAL, outcome=outcome)


def _apply_entry_evaluation(
    case: TradeCase,
    evaluation: ShadowEntryEvaluation,
    *,
    pricing: Btc0DteCondorPricing | None,
    observation: MarketObservation | None = None,
) -> TradeCase:
    outcome: ShadowCaseOutcome | None = None
    position_id: str | None = None
    position_state: PositionState | None = None
    entry_pricing_json: str | None = None
    entry_credit: Decimal | None = None
    entry_index: Decimal | None = None
    entry_vrp: Decimal | None = None
    if evaluation.final and evaluation.status is not ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE:
        outcome = _no_position_outcome(evaluation)
    if pricing is not None and observation is not None:
        entry_pricing_json = _json_text(
            {
                "fee_model_id": pricing.fee_model_id,
                "native_gross_credit": pricing.native_gross_credit,
                "combo_standard_fee_native": pricing.combo_standard_fee_native,
                "native_net_credit": pricing.native_net_credit,
                "boundary_index_price_usd": pricing.boundary_index_price_usd,
                "boundary_net_credit_usd": pricing.boundary_net_credit_usd,
            }
        )
        position_id = canonical_identity(
            "ShadowPositionV1",
            case.identity,
            case.truth_layer,
            case.selected_structure_id,
            observation.identity,
            observation.observed_at,
        )
        position_state = PositionState.MONITORING
        entry_credit = pricing.native_net_credit
        entry_index = pricing.boundary_index_price_usd
        entry_vrp = (
            observation.context.same_session_implied_variance_proxy
            / observation.context.trailing_realized_variance_proxy
        )
    return replace(
        case,
        entry_status=evaluation.status,
        entry_final=evaluation.final,
        entry_observation_id=evaluation.observation_id,
        entry_observed_at=evaluation.observed_at,
        entry_known_at=evaluation.known_at,
        entry_reason=evaluation.reason,
        entry_pricing_json=entry_pricing_json,
        position_id=position_id,
        position_state=position_state,
        entry_native_net_credit=entry_credit,
        entry_index_price_usd=entry_index,
        entry_vrp_proxy_ratio=entry_vrp,
        last_observation_id=evaluation.observation_id or case.last_observation_id,
        last_observed_at=evaluation.observed_at or case.last_observed_at,
        gap_observed=case.gap_observed or (evaluation.status is ShadowEntryStatus.UNKNOWN),
        outcome=outcome,
    )


def _entry_unknown_reason(
    case: TradeCase,
    observation: MarketObservation | None,
    known_at: datetime,
    policy: BtcShortVolPolicy,
) -> str | None:
    if observation is None:
        return "NO_ENTRY_OBSERVATION"
    if observation.channel_id is not case.channel_id:
        return "ENTRY_OBSERVATION_CHANNEL_MISMATCH"
    if observation.data_health_policy_id != policy.observation.identity:
        return "ENTRY_OBSERVATION_DATA_HEALTH_POLICY_MISMATCH"
    if observation.known_at > known_at:
        return "ENTRY_OBSERVATION_NOT_KNOWN_AT_EVALUATION"
    if observation.observed_at <= case.decision_boundary:
        return "ENTRY_OBSERVATION_NOT_STRICTLY_FUTURE"
    if observation.observed_at > case.entry_deadline:
        return "ENTRY_WINDOW_EXPIRED"
    if observation.known_at > case.entry_deadline:
        return "ENTRY_OBSERVATION_KNOWN_AFTER_DEADLINE"
    if observation.data_health_blockers:
        return observation.data_health_blockers[0]
    return None


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
    by_name = {quote.instrument_name: quote for quote in observation.quotes}
    frozen_legs = _structure_legs(case)
    names = tuple(leg[0] for leg in frozen_legs)
    if any(name not in by_name for name in names):
        return None
    quotes = tuple(by_name[name] for name in names)
    expiry = _parse_iso(_text(case.selected_structure, "expiry"), "expiry")
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


def _structure_legs(
    case: TradeCase,
) -> tuple[
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
    tuple[str, Decimal, str, bool],
]:
    structure = case.selected_structure
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
    *,
    gap: bool,
) -> TradeCase:
    return replace(
        case,
        last_observation_id=observation.identity,
        last_observed_at=observation.observed_at,
        gap_observed=case.gap_observed or gap,
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
    return ShadowCaseOutcome(
        terminal_method=method,
        terminal_at=terminal_at,
        entry_status=ShadowEntryStatus.SHADOW_ATOMIC_EVALUABLE,
        entry_observation_id=case.entry_observation_id,
        terminal_evidence_id=terminal_evidence_id,
        native_result_btc=native_result,
        boundary_reference_result_usd=boundary_result,
        fee_model_id=fee_model_id,
        shadow_model_id=case.entry_pricing_basis,
        terminal_source=source,
        data_gap_observed=case.gap_observed,
        reason=None,
        eligibility=eligibility,
    )


def _no_position_outcome(evaluation: ShadowEntryEvaluation) -> ShadowCaseOutcome:
    known = evaluation.status is ShadowEntryStatus.SHADOW_ATOMIC_NOT_EVALUABLE
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
    return ShadowCaseOutcome(
        terminal_method=TerminalMethod.NO_POSITION,
        terminal_at=evaluation.known_at,
        entry_status=evaluation.status,
        entry_observation_id=evaluation.observation_id,
        terminal_evidence_id=None,
        native_result_btc=None,
        boundary_reference_result_usd=None,
        fee_model_id=None,
        shadow_model_id=evaluation.pricing_basis,
        terminal_source="ENTRY_EVALUATION",
        data_gap_observed=evaluation.status is ShadowEntryStatus.UNKNOWN,
        reason=evaluation.reason,
        eligibility=eligibility,
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
