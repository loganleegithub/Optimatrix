"""Durable one-shot Entry and Outcome truth for bounded public Shadow evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from market_tape import PlatformState, canonical_digest, canonical_value
from options_domain import ExecutableVerticalClose, OptionQuote, build_vertical_close
from short_vol_radar import (
    DecisionFrame,
    DecisionInputContract,
    DecisionReceipt,
    InsuranceAssessment,
    RadarAction,
    RadarPolicy,
)

from shadow_engine.contracts import ExitReason, ShadowPolicy, ShadowPosition

OUTCOME_CONTRACT_ID = "PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH"
SHADOW_ENTRY_RECEIPT_TYPE = "SHORT_VOL_SHADOW_ENTRY_RECEIPT"
OUTCOME_RECEIPT_TYPE = "SHORT_VOL_OUTCOME_RECEIPT"
OUTCOME_FACT_SEAL_TYPE = "SHORT_VOL_OUTCOME_FACT_SEAL"
EXECUTION_EVIDENCE_CLASS = "VISIBLE_EXECUTABLE_QUOTE_NOT_FILL"
POST_EXIT_COUNTERFACTUAL = "POST_EXIT_COUNTERFACTUAL"

OUTCOME_CONTRACT_DIGEST = canonical_digest(
    {
        "contract_id": OUTCOME_CONTRACT_ID,
        "admission": ("ADMITTED", "NO_ENTRY", "UNKNOWN"),
        "close_observation": ("EXECUTABLE", "UNEXITABLE", "UNKNOWN"),
        "outcome": ("CLOSED", "UNEXITABLE", "UNKNOWN"),
        "future_rule": "capture_seq > entry_capture_seq",
        "exit_priority": ("PROFIT_TARGET", "FIRST_TOUCH", "HORIZON"),
        "profit_close_fraction": "0.50",
        "actual_path": "ENTRY_THROUGH_EXECUTABLE_EXIT_INCLUSIVE",
        "counterfactual": POST_EXIT_COUNTERFACTUAL,
        "excursion_baseline": "ENTRY_ZERO_AFTER_FUTURE_REFERENCE",
        "horizon": "ARMED_UNTIL_FIRST_EXECUTABLE_CLOSE_OR_DATA_END",
        "observation_freshness": "RECOMPUTED_FROM_FROZEN_INPUT_CONTRACT",
        "quote_age_schema": "NON_BOOLEAN_INTEGER_WITHIN_FROZEN_LIMIT",
        "combo_identity": "NONEMPTY_FOR_OBSERVED_ACTIVE_COMBO",
        "combo_conflict": "UNKNOWN_UNLESS_INDEPENDENT_LEG_CLOSE_IS_EXECUTABLE",
        "leg_quote_conflict": "UNKNOWN_UNLESS_INDEPENDENT_COMBO_CLOSE_IS_EXECUTABLE",
        "pnl": "EXECUTABLE_CLOSE_ONLY",
    }
)


class ShadowAdmission(StrEnum):
    ADMITTED = "ADMITTED"
    NO_ENTRY = "NO_ENTRY"
    UNKNOWN = "UNKNOWN"


class CloseObservationStatus(StrEnum):
    EXECUTABLE = "EXECUTABLE"
    UNEXITABLE = "UNEXITABLE"
    UNKNOWN = "UNKNOWN"


class OutcomeStatus(StrEnum):
    """Durable Outcome Truth status; separate from the legacy synthetic evaluator."""

    CLOSED = "CLOSED"
    UNEXITABLE = "UNEXITABLE"
    UNKNOWN = "UNKNOWN"


class OutcomePathRole(StrEnum):
    ACTUAL = "ACTUAL"
    POST_EXIT_COUNTERFACTUAL = POST_EXIT_COUNTERFACTUAL


@dataclass(frozen=True, slots=True)
class ShadowEntryReceipt:
    receipt_type: str
    fact_provenance: str
    outcome_contract_id: str
    outcome_contract_digest: str
    outcome_runtime_git_commit_sha: str
    outcome_runtime_source_id: str
    outcome_runtime_source_digest: str
    decision_receipt: DecisionReceipt
    decision_receipt_digest: str
    frame: DecisionFrame
    frame_digest: str
    assessment: InsuranceAssessment
    assessment_digest: str
    policy_id: str
    policy_digest: str
    position: ShadowPosition
    entry_platform_state: PlatformState
    entry_platform_control_capture_seqs: tuple[int, ...]
    execution_evidence_class: str

    def __post_init__(self) -> None:
        decision = self.decision_receipt.evaluation.decision
        candidate = self.assessment.candidate
        if self.receipt_type != SHADOW_ENTRY_RECEIPT_TYPE:
            raise ValueError("unsupported Shadow Entry receipt type")
        if self.fact_provenance not in {"synthetic", "production_public"}:
            raise ValueError("Shadow Entry fact provenance is invalid")
        if (
            self.outcome_contract_id != OUTCOME_CONTRACT_ID
            or self.outcome_contract_digest != OUTCOME_CONTRACT_DIGEST
        ):
            raise ValueError("Shadow Entry Outcome contract identity is invalid")
        if not all(
            (
                self.outcome_runtime_git_commit_sha,
                self.outcome_runtime_source_id,
                self.outcome_runtime_source_digest,
            )
        ):
            raise ValueError("Shadow Entry runtime identity is incomplete")
        if (
            self.decision_receipt_digest != self.decision_receipt.digest
            or self.frame_digest != self.frame.digest
            or self.assessment_digest != self.assessment.digest
        ):
            raise ValueError("Shadow Entry bound digest changed")
        if (
            self.decision_receipt.frame_capture_seq != self.frame.as_of_capture_seq
            or self.decision_receipt.frame_digest != self.frame.digest
            or decision.frame_capture_seq != self.frame.as_of_capture_seq
            or decision.frame_digest != self.frame.digest
            or decision.digest != self.position.decision_digest
        ):
            raise ValueError("Shadow Entry Decision and frame identity differ")
        if (
            decision.action is not RadarAction.RESEARCH_CANDIDATE
            or decision.assessment is None
            or decision.assessment != self.assessment
            or decision.selected_candidate_id != candidate.candidate_id
            or decision.horizon_seconds != self.position.horizon_seconds
        ):
            raise ValueError("Shadow Entry selected assessment changed")
        if (
            self.policy_id != self.decision_receipt.policy_id
            or self.policy_digest != self.decision_receipt.policy_digest
            or candidate != self.position.structure
            or candidate.frame_capture_seq != self.frame.as_of_capture_seq
            or candidate.quantity != RadarPolicy().quantity
        ):
            raise ValueError("Shadow Entry Policy or structure changed")
        if (
            self.position.frame_digest != self.frame.digest
            or self.position.entry_capture_seq != self.frame.as_of_capture_seq
            or self.position.entry_elapsed_ms != self.frame.collector_elapsed_ms
            or self.position.entry_reference_price != self.frame.reference_price
        ):
            raise ValueError("Shadow Entry causal boundary changed")
        if (
            self.entry_platform_state.state != "OPEN"
            or self.entry_platform_state.locked is not False
            or self.entry_platform_state.status_capture_seq is None
            or self.entry_platform_state.capture_seq > self.position.entry_capture_seq
            or self.entry_platform_control_capture_seqs
            != self.entry_platform_state.source_capture_seqs
            or not self.entry_platform_control_capture_seqs
            or self.entry_platform_state.status_capture_seq
            not in self.entry_platform_control_capture_seqs
            or not any(
                item < self.entry_platform_state.status_capture_seq
                for item in self.entry_platform_control_capture_seqs
            )
            or not set(self.entry_platform_control_capture_seqs).issubset(
                self.frame.source_capture_seqs
            )
            or any(
                item > self.position.entry_capture_seq
                for item in self.entry_platform_control_capture_seqs
            )
        ):
            raise ValueError("Shadow Entry platform anchors are invalid")
        if self.execution_evidence_class != EXECUTION_EVIDENCE_CLASS:
            raise ValueError("Shadow Entry execution evidence class is invalid")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ShadowAdmissionResult:
    status: ShadowAdmission
    reasons: tuple[str, ...]
    decision_receipt_digest: str
    entry_receipt: ShadowEntryReceipt | None

    def __post_init__(self) -> None:
        if not self.decision_receipt_digest:
            raise ValueError("Shadow admission Decision receipt identity is missing")
        if (self.status is ShadowAdmission.ADMITTED) != (self.entry_receipt is not None):
            raise ValueError("Shadow admission and Entry receipt disagree")
        if self.status is ShadowAdmission.ADMITTED and self.reasons:
            raise ValueError("admitted Shadow entry cannot have failure reasons")
        if self.status is not ShadowAdmission.ADMITTED and not self.reasons:
            raise ValueError("zero Shadow admission requires an explicit reason")


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    frame: DecisionFrame
    platform_state: PlatformState | None
    reconnect_capture_seq: int | None

    def __post_init__(self) -> None:
        if self.platform_state is None:
            if self.frame.platform_state in {"OPEN", "LOCKED"}:
                raise ValueError("Outcome platform fact and Decision frame disagree")
        elif (
            self.platform_state.state != self.frame.platform_state
            or self.platform_state.locked is not self.frame.platform_locked
        ):
            raise ValueError("Outcome platform fact and Decision frame disagree")
        if self.platform_state is not None and (
            self.platform_state.capture_seq > self.frame.as_of_capture_seq
            or any(
                item > self.frame.as_of_capture_seq
                for item in self.platform_state.source_capture_seqs
            )
            or not set(self.platform_state.source_capture_seqs).issubset(
                self.frame.source_capture_seqs
            )
        ):
            raise ValueError("Outcome platform fact exceeds its Decision frame")
        if self.reconnect_capture_seq is not None and (
            self.reconnect_capture_seq <= 0
            or self.reconnect_capture_seq > self.frame.as_of_capture_seq
        ):
            raise ValueError("Outcome reconnect fact exceeds its Decision frame")


@dataclass(frozen=True, slots=True)
class OutcomeClosePoint:
    frame_capture_seq: int
    frame_digest: str
    input_contract_digest: str
    collector_as_of: datetime
    observed_elapsed_ms: int
    market_as_of: datetime | None
    option_freshness_limit_ms: int
    short_quote_age_ms: int | None
    long_quote_age_ms: int | None
    combo_quote_age_ms: int | None
    reference_price: Decimal | None
    close_observation_status: CloseObservationStatus
    close_observation_reasons: tuple[str, ...]
    close_execution_source: str | None
    close_combo_id: str | None
    close_debit: Decimal | None
    close_fee_usdc: Decimal | None
    executable_depth: Decimal | None
    short_delta: Decimal | None
    reference_source_capture_seq: int | None
    quote_source_capture_seqs: tuple[int, ...]
    platform_control_source_capture_seqs: tuple[int, ...]
    reconnect_capture_seq: int | None
    source_capture_seqs: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            self.frame_capture_seq <= 0
            or self.observed_elapsed_ms < 0
            or not self.frame_digest
            or not self.input_contract_digest
            or type(self.option_freshness_limit_ms) is not int
            or self.option_freshness_limit_ms <= 0
        ):
            raise ValueError("Outcome point causal coordinates are invalid")
        if self.reference_price is not None and not _positive_finite(self.reference_price):
            raise ValueError("Outcome point reference price is invalid")
        for lineage in (
            self.quote_source_capture_seqs,
            self.platform_control_source_capture_seqs,
            self.source_capture_seqs,
        ):
            if lineage != tuple(sorted(set(lineage))):
                raise ValueError("Outcome point lineage must be sorted and unique")
            if any(item <= 0 or item > self.frame_capture_seq for item in lineage):
                raise ValueError("Outcome point lineage exceeds its frame")
        close_values = (
            self.close_execution_source,
            self.close_debit,
            self.close_fee_usdc,
            self.executable_depth,
        )
        if self.close_observation_status is CloseObservationStatus.EXECUTABLE:
            if any(item is None for item in close_values) or any(
                not _nonnegative_finite(item)
                for item in (
                    self.close_debit,
                    self.close_fee_usdc,
                    self.executable_depth,
                )
                if item is not None
            ):
                raise ValueError("executable Outcome point lacks close economics")
            if self.close_execution_source not in {
                "ACTIVE_COMBO",
                "CONSERVATIVE_LEG_CROSS",
            } or (self.close_execution_source == "ACTIVE_COMBO" and self.close_combo_id is None):
                raise ValueError("executable Outcome point source is invalid")
            executable_ages = (
                (self.combo_quote_age_ms,)
                if self.close_execution_source == "ACTIVE_COMBO"
                else (self.short_quote_age_ms, self.long_quote_age_ms)
            )
            if any(
                not _valid_quote_age(age, self.option_freshness_limit_ms) for age in executable_ages
            ):
                raise ValueError("executable Outcome point freshness evidence is invalid")
            if self.close_execution_source == "ACTIVE_COMBO" and (
                not isinstance(self.close_combo_id, str) or not self.close_combo_id.strip()
            ):
                raise ValueError("executable Outcome point combo identity is invalid")
        elif any(item is not None for item in close_values) or self.close_combo_id is not None:
            raise ValueError("non-executable Outcome point cannot record close economics")
        if not self.close_observation_reasons:
            raise ValueError("Outcome point requires an observation reason")
        expected_sources = tuple(
            sorted(
                {
                    self.frame_capture_seq,
                    *(
                        (self.reference_source_capture_seq,)
                        if self.reference_source_capture_seq is not None
                        else ()
                    ),
                    *self.quote_source_capture_seqs,
                    *self.platform_control_source_capture_seqs,
                    *((self.reconnect_capture_seq,) if self.reconnect_capture_seq else ()),
                }
            )
        )
        if self.source_capture_seqs != expected_sources:
            raise ValueError("Outcome point aggregate lineage is not exact")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class OutcomeTruthPath:
    role: OutcomePathRole
    entry_receipt_digest: str
    entry_capture_seq: int
    points: tuple[OutcomeClosePoint, ...]

    def __post_init__(self) -> None:
        if not self.entry_receipt_digest or self.entry_capture_seq <= 0:
            raise ValueError("Outcome path Entry identity is invalid")
        if any(item.frame_capture_seq <= self.entry_capture_seq for item in self.points):
            raise ValueError("Outcome path may contain only facts after Entry")
        if any(
            source <= self.entry_capture_seq
            for point in self.points
            for source in point.source_capture_seqs
        ):
            raise ValueError("Outcome path lineage may contain only facts after Entry")
        if any(
            left.frame_capture_seq >= right.frame_capture_seq
            or left.observed_elapsed_ms > right.observed_elapsed_ms
            for left, right in pairwise(self.points)
        ):
            raise ValueError("Outcome path facts are not causally ordered")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ObservedOutcome:
    status: OutcomeStatus
    exit_reason: ExitReason
    actual_path_digest: str
    exit_capture_seq: int | None
    evaluation_capture_seq: int | None
    observed_exposure_seconds: int | None
    observed_executable_close_cost_usdc: Decimal | None
    observed_close_fee_usdc: Decimal | None
    observed_executable_pnl_usdc: Decimal | None
    maximum_up_fraction: Decimal | None
    maximum_down_fraction: Decimal | None
    first_touch_capture_seq: int | None
    time_to_touch_seconds: int | None
    max_loss_region: bool | None
    unknown_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        executable_values = (
            self.exit_capture_seq,
            self.observed_exposure_seconds,
            self.observed_executable_close_cost_usdc,
            self.observed_close_fee_usdc,
            self.observed_executable_pnl_usdc,
        )
        if self.status is OutcomeStatus.CLOSED:
            if any(item is None for item in executable_values) or self.unknown_reasons:
                raise ValueError("CLOSED Outcome lacks executable evidence")
        elif any(item is not None for item in executable_values):
            raise ValueError("non-CLOSED Outcome cannot record executable result")
        if self.status is OutcomeStatus.UNKNOWN and not self.unknown_reasons:
            raise ValueError("UNKNOWN Outcome requires explicit missingness")
        if self.status is OutcomeStatus.UNEXITABLE and self.unknown_reasons:
            raise ValueError("UNEXITABLE Outcome cannot hide missing evidence")

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class OutcomeReceipt:
    receipt_type: str
    fact_provenance: str
    outcome_contract_id: str
    outcome_contract_digest: str
    outcome_runtime_git_commit_sha: str
    outcome_runtime_source_id: str
    outcome_runtime_source_digest: str
    fact_seal_type: str
    fact_seal_digest: str
    full_capture_digest: str
    full_capture_manifest_digest: str
    final_capture_seq: int
    entry_receipt: ShadowEntryReceipt
    entry_receipt_digest: str
    actual_path: OutcomeTruthPath
    counterfactual_path: OutcomeTruthPath | None
    counterfactual_path_digest: str | None
    observed_outcome: ObservedOutcome
    outcome_source_capture_seqs: tuple[int, ...]
    execution_evidence_class: str

    def __post_init__(self) -> None:
        if self.receipt_type != OUTCOME_RECEIPT_TYPE:
            raise ValueError("unsupported Outcome receipt type")
        if self.fact_provenance != self.entry_receipt.fact_provenance:
            raise ValueError("Outcome and Entry provenance differ")
        if (
            self.outcome_contract_id != OUTCOME_CONTRACT_ID
            or self.outcome_contract_digest != OUTCOME_CONTRACT_DIGEST
            or self.fact_seal_type != OUTCOME_FACT_SEAL_TYPE
        ):
            raise ValueError("Outcome receipt contract identity is invalid")
        if not all(
            (
                self.outcome_runtime_git_commit_sha,
                self.outcome_runtime_source_id,
                self.outcome_runtime_source_digest,
                self.fact_seal_digest,
                self.full_capture_digest,
                self.full_capture_manifest_digest,
            )
        ):
            raise ValueError("Outcome receipt source identity is incomplete")
        if (
            self.outcome_runtime_git_commit_sha != self.entry_receipt.outcome_runtime_git_commit_sha
            or self.outcome_runtime_source_id != self.entry_receipt.outcome_runtime_source_id
            or self.outcome_runtime_source_digest
            != self.entry_receipt.outcome_runtime_source_digest
        ):
            raise ValueError("Outcome runtime identity changed after Entry")
        if self.entry_receipt_digest != self.entry_receipt.digest:
            raise ValueError("Outcome Entry receipt digest changed")
        if self.final_capture_seq < self.entry_receipt.position.entry_capture_seq:
            raise ValueError("Outcome final sequence precedes Entry")
        if (
            self.actual_path.role is not OutcomePathRole.ACTUAL
            or self.actual_path.entry_receipt_digest != self.entry_receipt_digest
            or self.actual_path.entry_capture_seq != self.entry_receipt.position.entry_capture_seq
            or self.observed_outcome.actual_path_digest != self.actual_path.digest
        ):
            raise ValueError("Outcome actual path identity is invalid")
        if self.counterfactual_path is not None and (
            self.counterfactual_path.role is not OutcomePathRole.POST_EXIT_COUNTERFACTUAL
            or self.counterfactual_path.entry_receipt_digest != self.entry_receipt_digest
            or self.counterfactual_path.entry_capture_seq
            != self.entry_receipt.position.entry_capture_seq
            or self.observed_outcome.status is not OutcomeStatus.CLOSED
        ):
            raise ValueError("Outcome counterfactual path is invalid")
        if self.counterfactual_path_digest != (
            self.counterfactual_path.digest if self.counterfactual_path is not None else None
        ):
            raise ValueError("Outcome counterfactual path digest changed")
        if any(
            point.close_observation_status is CloseObservationStatus.EXECUTABLE
            and (
                point.executable_depth is None
                or point.executable_depth < self.entry_receipt.position.structure.quantity
            )
            for path in (self.actual_path, self.counterfactual_path)
            if path is not None
            for point in path.points
        ):
            raise ValueError("Outcome executable point lacks frozen-quantity depth")
        exit_capture_seq = self.observed_outcome.exit_capture_seq
        if self.observed_outcome.status is OutcomeStatus.CLOSED:
            if (
                exit_capture_seq is None
                or not self.actual_path.points
                or self.actual_path.points[-1].frame_capture_seq != exit_capture_seq
                or self.actual_path.points[-1].close_observation_status
                is not CloseObservationStatus.EXECUTABLE
                or (
                    self.counterfactual_path is not None
                    and any(
                        point.frame_capture_seq <= exit_capture_seq
                        for point in self.counterfactual_path.points
                    )
                )
            ):
                raise ValueError("Outcome executable exit and path boundary disagree")
        elif self.counterfactual_path is not None:
            raise ValueError("non-CLOSED Outcome cannot have a counterfactual path")
        all_points = self.actual_path.points + (
            self.counterfactual_path.points if self.counterfactual_path is not None else ()
        )
        input_contract = DecisionInputContract()
        if any(
            point.input_contract_digest != self.entry_receipt.frame.input_contract_digest
            or point.input_contract_digest != input_contract.digest
            or point.option_freshness_limit_ms != input_contract.option_freshness_ms
            for point in all_points
        ):
            raise ValueError("Outcome point input-contract binding changed")
        if any(
            left.frame_capture_seq >= right.frame_capture_seq
            or left.observed_elapsed_ms > right.observed_elapsed_ms
            for left, right in pairwise(all_points)
        ):
            raise ValueError("Outcome actual/counterfactual facts are not causally ordered")
        expected_actual, expected_counterfactual, expected_observed = _derive_paths_and_outcome(
            self.entry_receipt,
            self.entry_receipt_digest,
            all_points,
        )
        if (
            self.actual_path != expected_actual
            or self.counterfactual_path != expected_counterfactual
            or self.observed_outcome != expected_observed
        ):
            raise ValueError("Outcome receipt derived semantics changed")
        if self.outcome_source_capture_seqs != tuple(
            sorted(set(self.outcome_source_capture_seqs))
        ) or any(
            item <= self.entry_receipt.position.entry_capture_seq or item > self.final_capture_seq
            for item in self.outcome_source_capture_seqs
        ):
            raise ValueError("Outcome receipt lineage is outside the sealed suffix")
        expected_sources = tuple(
            sorted(
                {
                    source
                    for path in (self.actual_path, self.counterfactual_path)
                    if path is not None
                    for point in path.points
                    for source in point.source_capture_seqs
                }
            )
        )
        if self.outcome_source_capture_seqs != expected_sources:
            raise ValueError("Outcome receipt aggregate lineage is not exact")
        if self.execution_evidence_class != EXECUTION_EVIDENCE_CLASS:
            raise ValueError("Outcome execution evidence class is invalid")

    @property
    def outcome_status(self) -> OutcomeStatus:
        return self.observed_outcome.status

    @property
    def unknown_reasons(self) -> tuple[str, ...]:
        return self.observed_outcome.unknown_reasons

    @property
    def digest(self) -> str:
        return canonical_digest(self)


def _position(decision_receipt: DecisionReceipt, frame: DecisionFrame) -> ShadowPosition:
    decision = decision_receipt.evaluation.decision
    if decision.assessment is None or decision.horizon_seconds is None:
        raise ValueError("Candidate Decision lacks assessment or horizon")
    if frame.reference_price is None:
        raise ValueError("Candidate Decision lacks entry reference")
    return ShadowPosition(
        decision_digest=decision.digest,
        frame_digest=frame.digest,
        entry_capture_seq=frame.as_of_capture_seq,
        entry_at=frame.collector_as_of,
        entry_elapsed_ms=frame.collector_elapsed_ms,
        entry_reference_price=frame.reference_price,
        horizon_seconds=decision.horizon_seconds,
        structure=decision.assessment.candidate,
    )


def admit_shadow(
    decision_receipt: DecisionReceipt,
    *,
    decision_receipt_digest: str,
    frame: DecisionFrame,
    entry_platform_state: PlatformState | None,
    fact_provenance: str,
    outcome_runtime_git_commit_sha: str,
    outcome_runtime_source_id: str,
    outcome_runtime_source_digest: str,
) -> ShadowAdmissionResult:
    """Apply the single fail-closed admission to one exact typed Decision receipt."""

    if decision_receipt.digest != decision_receipt_digest:
        raise ValueError("Decision receipt digest changed before Shadow admission")
    decision = decision_receipt.evaluation.decision
    policy = RadarPolicy()
    if (
        decision_receipt.frame_capture_seq != frame.as_of_capture_seq
        or decision_receipt.frame_digest != frame.digest
        or decision.frame_capture_seq != frame.as_of_capture_seq
        or decision.frame_digest != frame.digest
        or decision_receipt.input_contract_id != frame.input_contract_id
        or decision_receipt.input_contract_digest != frame.input_contract_digest
        or decision_receipt.policy_id != policy.policy_id
        or decision_receipt.policy_digest != policy.digest
    ):
        raise ValueError("Decision receipt, frame, or Policy identity changed")
    if (
        decision_receipt.readiness.frame_complete != frame.complete
        or decision_receipt.readiness.frame_incomplete_reasons != frame.completeness_reasons
    ):
        raise ValueError("Decision readiness and exact frame disagree")
    if not frame.complete:
        reasons = frame.completeness_reasons or ("DECISION_READINESS_INCOMPLETE",)
        return ShadowAdmissionResult(
            status=ShadowAdmission.UNKNOWN,
            reasons=reasons,
            decision_receipt_digest=decision_receipt_digest,
            entry_receipt=None,
        )
    if decision.action is not RadarAction.RESEARCH_CANDIDATE:
        return ShadowAdmissionResult(
            status=ShadowAdmission.NO_ENTRY,
            reasons=(f"DECISION_{decision.action.value}", decision.reason),
            decision_receipt_digest=decision_receipt_digest,
            entry_receipt=None,
        )
    if (
        decision.assessment is None
        or not decision.assessment.all_passed
        or decision.selected_candidate_id != decision.assessment.candidate.candidate_id
        or decision.horizon_seconds is None
        or decision.assessment.candidate.frame_capture_seq != frame.as_of_capture_seq
        or decision.assessment.candidate.quantity != policy.quantity
    ):
        raise ValueError("Candidate Decision assessment or frozen quantity changed")
    if entry_platform_state is None:
        raise ValueError("Candidate Entry lacks exact platform control anchors")
    receipt = ShadowEntryReceipt(
        receipt_type=SHADOW_ENTRY_RECEIPT_TYPE,
        fact_provenance=fact_provenance,
        outcome_contract_id=OUTCOME_CONTRACT_ID,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
        outcome_runtime_git_commit_sha=outcome_runtime_git_commit_sha,
        outcome_runtime_source_id=outcome_runtime_source_id,
        outcome_runtime_source_digest=outcome_runtime_source_digest,
        decision_receipt=decision_receipt,
        decision_receipt_digest=decision_receipt_digest,
        frame=frame,
        frame_digest=frame.digest,
        assessment=decision.assessment,
        assessment_digest=decision.assessment.digest,
        policy_id=policy.policy_id,
        policy_digest=policy.digest,
        position=_position(decision_receipt, frame),
        entry_platform_state=entry_platform_state,
        entry_platform_control_capture_seqs=entry_platform_state.source_capture_seqs,
        execution_evidence_class=EXECUTION_EVIDENCE_CLASS,
    )
    return ShadowAdmissionResult(
        status=ShadowAdmission.ADMITTED,
        reasons=(),
        decision_receipt_digest=decision_receipt_digest,
        entry_receipt=receipt,
    )


def _quotes(frame: DecisionFrame, instrument_name: str) -> tuple[OptionQuote, ...]:
    return tuple(item for item in frame.option_quotes if item.instrument_name == instrument_name)


def _positive_finite(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _nonnegative_finite(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _valid_quote_age(value: object, limit_ms: int) -> bool:
    return type(value) is int and 0 <= value <= limit_ms


def _normalized_quote_age(value: object) -> int | None:
    if type(value) is not int:
        return None
    assert isinstance(value, int)
    return value


def _freeze_contract_terms(observed: OptionQuote, entry: OptionQuote) -> OptionQuote:
    return replace(
        observed,
        expiry=entry.expiry,
        strike=entry.strike,
        option_kind=entry.option_kind,
        contract_size=entry.contract_size,
        min_trade_amount=entry.min_trade_amount,
        amount_step=entry.amount_step,
        taker_commission=entry.taker_commission,
        instrument_source_capture_seq=entry.instrument_source_capture_seq,
    )


def _platform_assessment(
    entry_capture_seq: int,
    observation: OutcomeObservation,
) -> tuple[CloseObservationStatus | None, tuple[str, ...], tuple[int, ...]]:
    platform = observation.platform_state
    if platform is None:
        return CloseObservationStatus.UNKNOWN, ("FUTURE_PLATFORM_STATE_MISSING",), ()
    sources = platform.source_capture_seqs
    future_sources = tuple(item for item in sources if item > entry_capture_seq)
    if platform.capture_seq <= entry_capture_seq:
        return CloseObservationStatus.UNKNOWN, ("FUTURE_PLATFORM_BARRIER_MISSING",), ()
    reconnect = observation.reconnect_capture_seq
    if (
        reconnect is not None
        and reconnect > entry_capture_seq
        and (platform.capture_seq <= reconnect or not any(item > reconnect for item in sources))
    ):
        return (
            CloseObservationStatus.UNKNOWN,
            ("POST_RECONNECT_PLATFORM_BARRIER_MISSING",),
            future_sources,
        )
    if platform.state == "LOCKED" and platform.locked is True:
        return CloseObservationStatus.UNEXITABLE, ("PLATFORM_LOCKED",), future_sources
    if (
        platform.status_capture_seq is None
        or platform.status_capture_seq <= entry_capture_seq
        or platform.status_capture_seq not in sources
        or not any(item < platform.status_capture_seq for item in sources)
        or any(item <= entry_capture_seq for item in sources)
    ):
        return (
            CloseObservationStatus.UNKNOWN,
            ("FUTURE_PLATFORM_BARRIER_MISSING",),
            future_sources,
        )
    if (
        reconnect is not None
        and reconnect > entry_capture_seq
        and (
            platform.capture_seq <= reconnect
            or platform.status_capture_seq <= reconnect
            or any(item <= reconnect for item in sources)
        )
    ):
        return (
            CloseObservationStatus.UNKNOWN,
            ("POST_RECONNECT_PLATFORM_BARRIER_MISSING",),
            future_sources,
        )
    if platform.state != "OPEN" or platform.locked is not False:
        return CloseObservationStatus.UNKNOWN, ("PLATFORM_STATE_UNKNOWN",), future_sources
    return None, (), future_sources


def _point(entry: ShadowEntryReceipt, observation: OutcomeObservation) -> OutcomeClosePoint:
    position = entry.position
    frame = observation.frame
    input_contract = DecisionInputContract()
    if (
        frame.input_contract_id != entry.frame.input_contract_id
        or frame.input_contract_digest != entry.frame.input_contract_digest
        or frame.input_contract_id != input_contract.contract_id
        or frame.input_contract_digest != input_contract.digest
    ):
        raise ValueError("Outcome observation Decision input contract identity changed")
    if frame.as_of_capture_seq <= position.entry_capture_seq:
        raise ValueError("Outcome observation is not strictly after Entry")
    if frame.collector_elapsed_ms < position.entry_elapsed_ms:
        raise ValueError("Outcome observation elapsed time precedes Entry")
    platform_status, platform_reasons, platform_sources = _platform_assessment(
        position.entry_capture_seq,
        observation,
    )
    reference_valid = bool(
        frame.reference_source_capture_seq is not None
        and frame.reference_source_capture_seq > position.entry_capture_seq
        and _positive_finite(frame.reference_price)
        and _positive_finite(frame.index_price)
        and "REFERENCE_STALE" not in frame.completeness_reasons
        and "REFERENCE_NOT_OPEN" not in frame.completeness_reasons
    )
    future_reference_closed = bool(
        "REFERENCE_NOT_OPEN" in frame.completeness_reasons
        and frame.reference_source_capture_seq is not None
        and frame.reference_source_capture_seq > position.entry_capture_seq
    )
    reference_price = frame.reference_price if reference_valid else None
    reference_source = (
        frame.reference_source_capture_seq
        if frame.reference_source_capture_seq is not None
        and frame.reference_source_capture_seq > position.entry_capture_seq
        else None
    )
    short_quotes = _quotes(frame, position.structure.short_leg.instrument_name)
    long_quotes = _quotes(frame, position.structure.long_leg.instrument_name)
    leg_evidence_conflict = len(short_quotes) > 1 or len(long_quotes) > 1
    short_quote = short_quotes[0] if len(short_quotes) == 1 else None
    long_quote = long_quotes[0] if len(long_quotes) == 1 else None
    future_combos = tuple(
        item for item in frame.combo_quotes if item.source_capture_seq > position.entry_capture_seq
    )
    structure_combos = tuple(
        item
        for item in future_combos
        if item.short_instrument == position.structure.short_leg.instrument_name
        and item.long_instrument == position.structure.long_leg.instrument_name
    )
    latest_combo_source_seq = max(
        (item.source_capture_seq for item in structure_combos),
        default=None,
    )
    latest_combos = tuple(
        item for item in structure_combos if item.source_capture_seq == latest_combo_source_seq
    )
    combo_evidence_conflict = len(latest_combos) > 1
    observed_combo = latest_combos[0] if latest_combos else None
    combo_evidence_invalid = bool(
        observed_combo is not None
        and (
            combo_evidence_conflict
            or not isinstance(observed_combo.combo_id, str)
            or not observed_combo.combo_id.strip()
            or observed_combo.fresh is not True
            or observed_combo.valid is not True
            or not _valid_quote_age(
                observed_combo.quote_age_ms,
                input_contract.option_freshness_ms,
            )
            or not _nonnegative_finite(observed_combo.bid_amount)
            or not _nonnegative_finite(observed_combo.ask_amount)
            or (observed_combo.bid is not None and not _nonnegative_finite(observed_combo.bid))
            or (observed_combo.ask is not None and not _nonnegative_finite(observed_combo.ask))
        )
    )
    matching_combo = observed_combo if not combo_evidence_invalid else None
    quote_sources = tuple(
        sorted(
            {
                item.ticker_source_capture_seq
                for item in (*short_quotes, *long_quotes)
                if item.ticker_source_capture_seq > position.entry_capture_seq
            }
            | {*((observed_combo.source_capture_seq,) if observed_combo is not None else ())}
        )
    )

    status = CloseObservationStatus.UNKNOWN
    reasons: tuple[str, ...]
    close: ExecutableVerticalClose | None = None
    if future_reference_closed:
        status = CloseObservationStatus.UNEXITABLE
        reasons = ("REFERENCE_NOT_OPEN",)
    elif platform_status is not None:
        status = platform_status
        reasons = platform_reasons
    elif not reference_valid:
        reasons = ("FUTURE_REFERENCE_UNKNOWN",)
    else:
        if (
            matching_combo is not None
            and not combo_evidence_invalid
            and matching_combo.ask is not None
            and _nonnegative_finite(matching_combo.ask)
            and matching_combo.ask_amount >= position.structure.quantity
        ):
            combo_source_at = frame.market_as_of or frame.collector_as_of
            combo_short = replace(
                position.structure.short_leg,
                quote_age_ms=matching_combo.quote_age_ms,
                fresh=True,
                ticker_source_capture_seq=matching_combo.source_capture_seq,
                source_at=combo_source_at,
            )
            combo_long = replace(
                position.structure.long_leg,
                quote_age_ms=matching_combo.quote_age_ms,
                fresh=True,
                ticker_source_capture_seq=matching_combo.source_capture_seq,
                source_at=combo_source_at,
            )
            close = build_vertical_close(
                index_price=frame.index_price or Decimal("0"),
                short_quote=combo_short,
                long_quote=combo_long,
                quantity=position.structure.quantity,
                combo_quotes=(matching_combo,),
            )
        legs_are_future = bool(
            short_quote is not None
            and long_quote is not None
            and short_quote.ticker_source_capture_seq > position.entry_capture_seq
            and long_quote.ticker_source_capture_seq > position.entry_capture_seq
            and short_quote.fresh is True
            and long_quote.fresh is True
            and _valid_quote_age(
                short_quote.quote_age_ms,
                input_contract.option_freshness_ms,
            )
            and _valid_quote_age(
                long_quote.quote_age_ms,
                input_contract.option_freshness_ms,
            )
        )
        leg_prices_visible = bool(
            legs_are_future
            and short_quote is not None
            and long_quote is not None
            and _nonnegative_finite(short_quote.ask)
            and _nonnegative_finite(long_quote.bid)
        )
        leg_amounts_visible = bool(
            legs_are_future
            and short_quote is not None
            and long_quote is not None
            and _nonnegative_finite(short_quote.ask_amount)
            and _nonnegative_finite(long_quote.bid_amount)
        )
        if close is None and leg_prices_visible and leg_amounts_visible:
            assert short_quote is not None and long_quote is not None
            close = build_vertical_close(
                index_price=frame.index_price or Decimal("0"),
                short_quote=_freeze_contract_terms(short_quote, position.structure.short_leg),
                long_quote=_freeze_contract_terms(long_quote, position.structure.long_leg),
                quantity=position.structure.quantity,
            )
        if close is not None:
            status = CloseObservationStatus.EXECUTABLE
            reasons = ("VISIBLE_EXECUTABLE_CLOSE",)
        else:
            combo_side_unknown = bool(
                observed_combo is not None
                and not combo_evidence_invalid
                and observed_combo.ask is None
            )
            combo_depth_insufficient = bool(
                observed_combo is not None
                and not combo_evidence_invalid
                and observed_combo.ask is not None
                and _nonnegative_finite(observed_combo.ask)
                and observed_combo.ask_amount < position.structure.quantity
            )
            leg_depth_insufficient = bool(
                leg_prices_visible
                and leg_amounts_visible
                and short_quote is not None
                and long_quote is not None
                and min(
                    short_quote.ask_amount or Decimal("0"),
                    long_quote.bid_amount or Decimal("0"),
                )
                < position.structure.quantity
            )
            if combo_evidence_conflict:
                reasons = ("FUTURE_COMBO_EVIDENCE_CONFLICT",)
            elif combo_evidence_invalid:
                reasons = ("FUTURE_COMBO_EVIDENCE_INVALID",)
            elif combo_side_unknown:
                reasons = ("FUTURE_COMBO_CLOSE_SIDE_UNKNOWN",)
            elif leg_evidence_conflict:
                reasons = ("FUTURE_CLOSE_QUOTE_CONFLICT",)
            elif leg_depth_insufficient and (observed_combo is None or combo_depth_insufficient):
                status = CloseObservationStatus.UNEXITABLE
                reasons = ("VISIBLE_CLOSE_DEPTH_INSUFFICIENT",)
            elif short_quote is None or long_quote is None:
                reasons = ("FUTURE_CLOSE_QUOTE_MISSING",)
            elif not legs_are_future:
                reasons = ("FUTURE_CLOSE_QUOTE_STALE_OR_NOT_FUTURE",)
            else:
                reasons = ("EXECUTABLE_CLOSE_EVIDENCE_INCOMPLETE",)
    sources = tuple(
        sorted(
            {
                frame.as_of_capture_seq,
                *((reference_source,) if reference_source is not None else ()),
                *quote_sources,
                *platform_sources,
                *(
                    (observation.reconnect_capture_seq,)
                    if observation.reconnect_capture_seq is not None
                    and observation.reconnect_capture_seq > position.entry_capture_seq
                    else ()
                ),
            }
        )
    )
    future_reconnect_capture_seq = (
        observation.reconnect_capture_seq
        if observation.reconnect_capture_seq is not None
        and observation.reconnect_capture_seq > position.entry_capture_seq
        else None
    )
    return OutcomeClosePoint(
        frame_capture_seq=frame.as_of_capture_seq,
        frame_digest=frame.digest,
        input_contract_digest=frame.input_contract_digest,
        collector_as_of=frame.collector_as_of,
        observed_elapsed_ms=frame.collector_elapsed_ms,
        market_as_of=frame.market_as_of,
        option_freshness_limit_ms=input_contract.option_freshness_ms,
        short_quote_age_ms=(
            _normalized_quote_age(short_quote.quote_age_ms)
            if short_quote is not None
            and short_quote.ticker_source_capture_seq > position.entry_capture_seq
            else None
        ),
        long_quote_age_ms=(
            _normalized_quote_age(long_quote.quote_age_ms)
            if long_quote is not None
            and long_quote.ticker_source_capture_seq > position.entry_capture_seq
            else None
        ),
        combo_quote_age_ms=(
            _normalized_quote_age(observed_combo.quote_age_ms)
            if observed_combo is not None
            else None
        ),
        reference_price=reference_price,
        close_observation_status=status,
        close_observation_reasons=reasons,
        close_execution_source=(close.execution_source if close is not None else None),
        close_combo_id=(close.combo_id if close is not None else None),
        close_debit=(close.debit if close is not None else None),
        close_fee_usdc=(close.fee_usdc if close is not None else None),
        executable_depth=(close.depth if close is not None else None),
        short_delta=(
            short_quote.delta
            if reference_valid
            and short_quote is not None
            and short_quote.ticker_source_capture_seq > position.entry_capture_seq
            and short_quote.fresh is True
            and _valid_quote_age(
                short_quote.quote_age_ms,
                input_contract.option_freshness_ms,
            )
            and (short_quote.delta is None or short_quote.delta.is_finite())
            else None
        ),
        reference_source_capture_seq=reference_source,
        quote_source_capture_seqs=quote_sources,
        platform_control_source_capture_seqs=platform_sources,
        reconnect_capture_seq=future_reconnect_capture_seq,
        source_capture_seqs=sources,
    )


def _touches(entry: ShadowEntryReceipt, point: OutcomeClosePoint) -> bool:
    price = point.reference_price
    if price is None:
        return False
    if entry.position.structure.sold_side.value == "CALL":
        return price >= entry.position.structure.first_touch_level
    return price <= entry.position.structure.first_touch_level


def _derive_paths_and_outcome(
    entry_receipt: ShadowEntryReceipt,
    entry_receipt_digest: str,
    points: tuple[OutcomeClosePoint, ...],
) -> tuple[OutcomeTruthPath, OutcomeTruthPath | None, ObservedOutcome]:
    """Derive every scored field from the immutable Entry and ordered suffix points."""

    position = entry_receipt.position
    target = position.structure.executable_entry_credit * (
        Decimal("1") - ShadowPolicy().profit_close_fraction
    )
    selected: OutcomeClosePoint | None = None
    evaluation: OutcomeClosePoint | None = None
    first_touch: OutcomeClosePoint | None = None
    status = OutcomeStatus.UNKNOWN
    reason = ExitReason.DATA_END
    unknown_reasons: tuple[str, ...] = ("HORIZON_NOT_OBSERVED",)
    for point in points:
        if first_touch is None and _touches(entry_receipt, point):
            first_touch = point
        executable = point.close_observation_status is CloseObservationStatus.EXECUTABLE
        elapsed_seconds = (point.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
        if executable and point.close_debit is not None and point.close_debit <= target:
            selected = point
            status = OutcomeStatus.CLOSED
            reason = ExitReason.PROFIT_TARGET
            unknown_reasons = ()
            break
        if executable and first_touch is not None:
            selected = point
            status = OutcomeStatus.CLOSED
            reason = ExitReason.FIRST_TOUCH
            unknown_reasons = ()
            break
        if elapsed_seconds >= position.horizon_seconds:
            evaluation = point
            if executable:
                selected = point
                status = OutcomeStatus.CLOSED
                reason = ExitReason.HORIZON
                unknown_reasons = ()
                break
            elif point.close_observation_status is CloseObservationStatus.UNEXITABLE:
                status = OutcomeStatus.UNEXITABLE
                reason = ExitReason.UNEXITABLE_AT_HORIZON
                unknown_reasons = ()
            else:
                status = OutcomeStatus.UNKNOWN
                reason = ExitReason.HORIZON
                unknown_reasons = point.close_observation_reasons
    terminal = selected or evaluation
    if selected is not None:
        actual_points = tuple(
            item for item in points if item.frame_capture_seq <= selected.frame_capture_seq
        )
        counterfactual_points = tuple(
            item for item in points if item.frame_capture_seq > selected.frame_capture_seq
        )
    else:
        actual_points = points
        counterfactual_points = ()
    actual_path = OutcomeTruthPath(
        role=OutcomePathRole.ACTUAL,
        entry_receipt_digest=entry_receipt_digest,
        entry_capture_seq=position.entry_capture_seq,
        points=actual_points,
    )
    counterfactual_path = (
        OutcomeTruthPath(
            role=OutcomePathRole.POST_EXIT_COUNTERFACTUAL,
            entry_receipt_digest=entry_receipt_digest,
            entry_capture_seq=position.entry_capture_seq,
            points=counterfactual_points,
        )
        if counterfactual_points
        else None
    )
    prices = tuple(
        item.reference_price for item in actual_points if item.reference_price is not None
    )
    changes = (
        (
            Decimal("0"),
            *(
                (price - position.entry_reference_price) / position.entry_reference_price
                for price in prices
            ),
        )
        if prices
        else ()
    )
    actual_first_touch = next(
        (item for item in actual_points if _touches(entry_receipt, item)),
        None,
    )
    max_loss_region = (
        any(
            (
                price >= position.structure.long_leg.strike
                if position.structure.sold_side.value == "CALL"
                else price <= position.structure.long_leg.strike
            )
            for price in prices
        )
        if prices
        else None
    )
    close_cost: Decimal | None = None
    close_fee: Decimal | None = None
    pnl: Decimal | None = None
    exposure_seconds: int | None = None
    if selected is not None:
        if selected.close_debit is None or selected.close_fee_usdc is None:
            raise RuntimeError("selected executable close lacks economics")
        close_cost = (
            selected.close_debit * position.structure.quantity * position.structure.contract_size
        )
        close_fee = selected.close_fee_usdc
        pnl = (
            position.structure.gross_credit_usdc
            - close_cost
            - position.structure.entry_fee_usdc
            - close_fee
        )
        exposure_seconds = (selected.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
    observed = ObservedOutcome(
        status=status,
        exit_reason=reason,
        actual_path_digest=actual_path.digest,
        exit_capture_seq=(selected.frame_capture_seq if selected is not None else None),
        evaluation_capture_seq=(terminal.frame_capture_seq if terminal is not None else None),
        observed_exposure_seconds=exposure_seconds,
        observed_executable_close_cost_usdc=close_cost,
        observed_close_fee_usdc=close_fee,
        observed_executable_pnl_usdc=pnl,
        maximum_up_fraction=(max(changes) if changes else None),
        maximum_down_fraction=(min(changes) if changes else None),
        first_touch_capture_seq=(
            actual_first_touch.frame_capture_seq if actual_first_touch is not None else None
        ),
        time_to_touch_seconds=(
            (actual_first_touch.observed_elapsed_ms - position.entry_elapsed_ms) // 1_000
            if actual_first_touch is not None
            else None
        ),
        max_loss_region=max_loss_region,
        unknown_reasons=unknown_reasons,
    )
    return actual_path, counterfactual_path, observed


def evaluate_outcome(
    entry_receipt: ShadowEntryReceipt,
    observations: tuple[OutcomeObservation, ...],
    *,
    entry_receipt_digest: str,
    fact_seal_digest: str,
    full_capture_digest: str,
    full_capture_manifest_digest: str,
    final_capture_seq: int,
) -> OutcomeReceipt:
    """Evaluate one sealed future suffix once, without changing its Entry."""

    if entry_receipt.digest != entry_receipt_digest:
        raise ValueError("Shadow Entry receipt digest changed before Outcome evaluation")
    ordered = tuple(sorted(observations, key=lambda item: item.frame.as_of_capture_seq))
    if len({item.frame.as_of_capture_seq for item in ordered}) != len(ordered):
        raise ValueError("Outcome observations have duplicate frame sequences")
    points = tuple(_point(entry_receipt, item) for item in ordered)
    actual_path, counterfactual_path, observed = _derive_paths_and_outcome(
        entry_receipt,
        entry_receipt_digest,
        points,
    )
    source_capture_seqs = tuple(
        sorted({source for point in points for source in point.source_capture_seqs})
    )
    if source_capture_seqs and final_capture_seq < source_capture_seqs[-1]:
        raise ValueError("Outcome final sequence precedes its source facts")
    return OutcomeReceipt(
        receipt_type=OUTCOME_RECEIPT_TYPE,
        fact_provenance=entry_receipt.fact_provenance,
        outcome_contract_id=OUTCOME_CONTRACT_ID,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
        outcome_runtime_git_commit_sha=entry_receipt.outcome_runtime_git_commit_sha,
        outcome_runtime_source_id=entry_receipt.outcome_runtime_source_id,
        outcome_runtime_source_digest=entry_receipt.outcome_runtime_source_digest,
        fact_seal_type=OUTCOME_FACT_SEAL_TYPE,
        fact_seal_digest=fact_seal_digest,
        full_capture_digest=full_capture_digest,
        full_capture_manifest_digest=full_capture_manifest_digest,
        final_capture_seq=final_capture_seq,
        entry_receipt=entry_receipt,
        entry_receipt_digest=entry_receipt_digest,
        actual_path=actual_path,
        counterfactual_path=counterfactual_path,
        counterfactual_path_digest=(
            counterfactual_path.digest if counterfactual_path is not None else None
        ),
        observed_outcome=observed,
        outcome_source_capture_seqs=source_capture_seqs,
        execution_evidence_class=EXECUTION_EVIDENCE_CLASS,
    )


def entry_receipt_payload(receipt: ShadowEntryReceipt) -> dict[str, object]:
    value = canonical_value(receipt)
    if not isinstance(value, dict):
        raise RuntimeError("Shadow Entry receipt encoding is not an object")
    return {**value, "receipt_digest": receipt.digest}


def outcome_receipt_payload(receipt: OutcomeReceipt) -> dict[str, object]:
    value = canonical_value(receipt)
    if not isinstance(value, dict):
        raise RuntimeError("Outcome receipt encoding is not an object")
    return {**value, "receipt_digest": receipt.digest}
