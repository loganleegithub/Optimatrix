from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from options_domain import (
    OptionProductSpec,
    product_for_identity,
)
from short_vol_radar.bucket import radar_bucket_episode_identity
from short_vol_radar.policy import RadarPolicy
from short_vol_radar.score import (
    RadarSamplingMetadata,
    RadarScorePacket,
    SamplingKind,
    ScoreBand,
    validate_radar_score_packet,
)

from short_vol_underwriting.constants import POSITION_CLOSE_REASONS
from short_vol_underwriting.control import (
    radar_score_control_batch_identity,
    radar_score_control_rule_identity,
    selected_decision_batch_identity,
    selected_decision_rule_identity,
)
from short_vol_underwriting.domain import (
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    EntryEconomics,
    EntryTerms,
    PositionDecision,
    SourceFact,
    UnderwritingThresholdMargins,
)
from short_vol_underwriting.evidence import RuntimeBindings, ShadowStateStore
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import (
    CaseFactBoundary,
    FactBoundary,
    ObservationQuality,
    PositionDecisionRecoverySeed,
)
from short_vol_underwriting.policy import PolicyChain

SHADOW_CASE_SCHEMA_VERSION = 5
OPENED_KIND = "SHADOW_CASE_OPENED"
FIRST_CLOSE_KIND = "SHADOW_CASE_FIRST_CLOSE"
OUTCOME_KIND = "SHADOW_CASE_OUTCOME"
SEGMENT_OPENED_KIND = "SHADOW_CASE_SEGMENT_OPENED"
SEGMENT_CLOSED_KIND = "SHADOW_CASE_SEGMENT_CLOSED"

_V5_STRUCTURE_FIELDS = {
    "short_strike_usdc_per_btc": "short_strike_usd_per_btc",
    "long_strike_usdc_per_btc": "long_strike_usd_per_btc",
}
_V5_UNDERWRITING_FIELDS = {
    "minimum_net_entry_credit_usdc": "minimum_net_entry_credit_usd",
    "maximum_underwriting_reserved_loss_usdc": "maximum_underwriting_reserved_loss_usd",
}
_V5_ENTRY_ECONOMICS_FIELDS = {
    "gross_entry_credit_usdc": "gross_entry_credit_usd",
    "entry_fee_reserve_usdc": "entry_fee_reserve_usd",
    "net_entry_credit_usdc": "net_entry_credit_usd",
    "width_usdc_per_btc": "width_usd_per_btc",
    "payoff_cap_usdc": "contractual_payoff_cap_usd",
    "contractual_payoff_max_loss_ex_fees_usdc": ("entry_boundary_valued_payoff_loss_ex_fees_usd"),
    "entry_fee_reserved_payoff_loss_usdc": (
        "entry_boundary_valued_payoff_loss_including_entry_fee_usd"
    ),
    "future_cost_reserve_usdc": "future_cost_reserve_usd",
    "underwriting_reserved_loss_usdc": "underwriting_reserved_loss_usd",
}
_V5_OUTCOME_ECONOMICS_FIELDS = {
    "gross_close_cashflow_usdc": "gross_close_cashflow_usd",
    "close_fee_reserve_usdc": "close_fee_reserve_usd",
    "net_close_cashflow_usdc": "net_close_cashflow_usd",
    "gross_pnl_usdc": "gross_pnl_usd",
    "total_public_fee_reserve_usdc": "total_public_fee_reserve_usd",
    "net_pnl_after_public_standard_fee_reserve_usdc": (
        "net_pnl_after_public_standard_fee_reserve_usd"
    ),
    "net_loss_usdc": "net_loss_usd",
}
_V5_COMPONENT_LEG_FIELDS = {
    "raw_consumed_levels": "raw_consumed_levels_usd",
    "raw_vwap_usdc_per_btc": "raw_vwap_usd_per_btc",
    "stressed_consumed_levels": "stressed_consumed_levels_usd",
    "stressed_vwap_usdc_per_btc": "stressed_vwap_usd_per_btc",
    "fee_reserve_usdc": "fee_reserve_usd",
}


class ShadowCaseStoreError(ValueError):
    """A minimal durable Shadow Case cannot be written or read truthfully."""


class ShadowCaseReadStatus(StrEnum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    INCOMPLETE_UNCLEAN_EXIT = "INCOMPLETE_UNCLEAN_EXIT"


class ShadowCaseSegmentStatus(StrEnum):
    OPEN = "OPEN"
    CENSORED_AT_STOP = "CENSORED_AT_STOP"
    CENSORED_AT_FAILURE = "CENSORED_AT_FAILURE"
    INCOMPLETE_UNCLEAN_EXIT = "INCOMPLETE_UNCLEAN_EXIT"


@dataclass(frozen=True)
class ShadowCaseSegmentRead:
    sequence: int
    status: ShadowCaseSegmentStatus
    opened: Mapping[str, object]
    closed: Mapping[str, object] | None


@dataclass(frozen=True)
class ShadowCaseRead:
    status: ShadowCaseReadStatus
    opened: Mapping[str, object]
    first_close: Mapping[str, object] | None
    outcome: Mapping[str, object] | None
    segments: tuple[ShadowCaseSegmentRead, ...] = ()


@dataclass(frozen=True)
class RecoverableShadowEntry:
    """Validated process-independent Entry state consumed by a new owner."""

    case_id: str
    shadow_entry_identity: str
    origin_outcome_contract_identity: str
    origin_runtime_identity: str
    product_spec_identity: str
    policy_identities: tuple[str, str, str]
    entry_case_boundary: CaseFactBoundary
    adoption_case_boundary: CaseFactBoundary
    latest_segment_sequence: int
    current_segment_identity: str
    predecessor_segment_state: ShadowCaseSegmentStatus
    observation_quality: ObservationQuality
    gap_count: int
    qualification_eligible: bool
    entry_terms: EntryTerms
    entry_economics: EntryEconomics
    first_close_decision: PositionDecision | None
    first_close_state: str
    attempt_state: str
    entry_payload: Mapping[str, object]

    @property
    def required_option_instrument_names(self) -> tuple[str, str]:
        return (
            self.entry_terms.short_leg_instrument_name,
            self.entry_terms.long_leg_instrument_name,
        )

    @property
    def expiry_ms(self) -> int:
        return self.entry_terms.expiry_ms


@dataclass(frozen=True)
class _ComponentSourceEvidence:
    source_identity: str
    boundary: FactBoundary
    source_timestamp_ms: int | None
    global_continuity_epoch: int | None
    request_id: int | None
    owner_origin_boundary: FactBoundary | None
    sent_boundary: FactBoundary | None


@dataclass(frozen=True)
class _ValidatedComponentEconomics:
    valuation_gross_cashflow: Decimal
    valuation_total_fee: Decimal
    consumed_level_count: int
    native_gross_cashflow: Decimal
    native_total_fee: Decimal
    native_premium_currency: str
    valuation_index_price: Decimal | None


class ShadowCaseStore:
    """Persist admitted trades and explicitly selected no-trade decision Cases."""

    def __init__(
        self,
        directory: Path,
        *,
        bindings: RuntimeBindings,
        policies: PolicyChain,
    ) -> None:
        if directory.is_symlink() or not directory.is_dir():
            raise ShadowCaseStoreError("cases directory must be one existing non-symlink directory")
        self.directory = directory
        self.bindings = bindings
        self.policies = policies
        self.product = product_for_identity(policies.radar.product_spec_identity)
        self.schema_version = _schema_version_for_product(self.product)
        self._case_by_enrollment: dict[str, str] = {}
        self._opened_by_case: dict[str, Mapping[str, object]] = {}
        self._pending_first_close_by_entry: dict[str, Mapping[str, object]] = {}
        self._case_count = 0

    @property
    def case_count(self) -> int:
        return self._case_count

    @property
    def active_case_count(self) -> int:
        return len(self._opened_by_case)

    def case_id_for_entry(self, entry_identity: str) -> str | None:
        return self._case_by_enrollment.get(entry_identity)

    def case_id_for_enrollment(self, enrollment_identity: str) -> str | None:
        return self._case_by_enrollment.get(enrollment_identity)

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        kind = value.get("object_kind")
        if kind in {
            "SHADOW_ENTRY",
            "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN",
        }:
            self._open_case(value, state)
        elif kind == "POSITION_ACTION":
            self._remember_first_close(value)
        elif kind == "POST_CLOSE_ATTEMPT_SCHEDULED":
            self._record_first_close_and_attempt(value)
        elif kind in {
            "SHADOW_OUTCOME",
            "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OUTCOME",
        }:
            self._record_outcome(value)

    def read_case(self, case_id: str, *, runtime_active: bool = False) -> ShadowCaseRead:
        """Read one schema-v5 Case from the stable repository."""

        require_identity(case_id, "case_id")
        case_directory = self._case_directory(case_id)
        _validate_case_directory_members(case_directory, stable=True)
        opened = _read_json(case_directory / "opened.json")
        origin_bindings = _bindings_from_opened(opened)
        _validate_opened(
            opened,
            expected_case_id=case_id,
            bindings=origin_bindings,
            policies=self.policies,
        )
        self._validate_compatible_opened(opened)
        if opened.get("enrollment_kind") in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        }:
            return self._read_control_case(case_id, opened=opened, runtime_active=runtime_active)
        segments = self._read_segments(
            case_id,
            opened,
            runtime_active=runtime_active,
        )
        if opened.get("enrollment_kind") == "ADMITTED_SHADOW_TRADE" and not segments:
            raise ShadowCaseStoreError(
                "stable admitted Shadow Case lacks its origin Observation Segment"
            )
        first_close_path = case_directory / "first-close.json"
        outcome_path = case_directory / "outcome.json"
        first_close = _read_optional_json(first_close_path)
        outcome = _read_optional_json(outcome_path)
        if first_close is not None:
            self._validate_stable_first_close(
                opened=opened,
                segments=segments,
                value=first_close,
            )
        if outcome is not None:
            self._validate_stable_outcome(
                opened=opened,
                segments=segments,
                value=outcome,
            )
            if outcome.get("terminal_state") == "MATURE_KNOWN":
                if first_close is None:
                    raise ShadowCaseStoreError("known Outcome lacks its first CLOSE")
                if outcome.get("first_latched_close_action_identity") != first_close.get(
                    "position_action_identity"
                ):
                    raise ShadowCaseStoreError("known Outcome first CLOSE identity mismatch")
        status = (
            ShadowCaseReadStatus.COMPLETE
            if outcome is not None
            else ShadowCaseReadStatus.OPEN
            if segments
            else ShadowCaseReadStatus.INCOMPLETE_UNCLEAN_EXIT
        )
        return ShadowCaseRead(
            status,
            opened,
            first_close,
            outcome,
            segments,
        )

    def _read_control_case(
        self,
        case_id: str,
        *,
        opened: Mapping[str, object],
        runtime_active: bool = False,
    ) -> ShadowCaseRead:
        """Read one bounded, non-recoverable schema-v5 no-trade Control."""

        require_identity(case_id, "case_id")
        case_directory = self._case_directory(case_id)
        segments_path = case_directory / "segments"
        if segments_path.exists() or segments_path.is_symlink():
            raise ShadowCaseStoreError("no-trade Control cannot carry Observation Segments")
        _validate_case_directory_members(case_directory, stable=False)
        first_close_path = case_directory / "first-close.json"
        outcome_path = case_directory / "outcome.json"
        first_close = _read_optional_json(first_close_path)
        outcome = _read_optional_json(outcome_path)
        if first_close is not None:
            _validate_followup(
                opened,
                first_close,
                expected_kind=FIRST_CLOSE_KIND,
                policies=self.policies,
            )
        if outcome is not None:
            _validate_followup(
                opened,
                outcome,
                expected_kind=OUTCOME_KIND,
                policies=self.policies,
            )
            _validate_outcome_economics(opened, outcome)
            if outcome.get("terminal_state") == "MATURE_KNOWN":
                if first_close is None:
                    raise ShadowCaseStoreError("known Outcome lacks its first CLOSE")
                if outcome.get("first_latched_close_action_identity") != first_close.get(
                    "position_action_identity"
                ):
                    raise ShadowCaseStoreError("known Outcome first CLOSE identity mismatch")
        status = (
            ShadowCaseReadStatus.COMPLETE
            if outcome is not None
            else ShadowCaseReadStatus.OPEN
            if runtime_active
            else ShadowCaseReadStatus.INCOMPLETE_UNCLEAN_EXIT
        )
        return ShadowCaseRead(status, opened, first_close, outcome)

    def scan_active_admitted(self) -> tuple[RecoverableShadowEntry, ...]:
        """Validate the stable repository and return every compatible active Entry."""

        recovered: list[RecoverableShadowEntry] = []
        validated_opened: dict[str, Mapping[str, object]] = {}
        seen_entries: set[str] = set()
        for case_directory in sorted(self.directory.iterdir(), key=lambda path: path.name):
            if is_shadow_case_staging_name(case_directory.name):
                if case_directory.is_symlink() or not case_directory.is_dir():
                    raise ShadowCaseStoreError("invalid Shadow Case staging path")
                continue
            if case_directory.is_symlink() or not case_directory.is_dir():
                raise ShadowCaseStoreError("cases repository contains a non-Case entry")
            case_id = _case_id_from_directory(case_directory)
            opened = _read_json(case_directory / "opened.json")
            if opened.get("enrollment_kind") != "ADMITTED_SHADOW_TRADE":
                self._read_nonrecoverable_case(case_id, opened)
                continue
            case = self.read_case(case_id)
            if case.outcome is not None:
                continue
            entry_identity = _identity(
                case.opened.get("shadow_entry_identity"),
                "shadow_entry_identity",
            )
            if entry_identity in seen_entries:
                raise ShadowCaseStoreError("duplicate active shadow_entry_identity")
            seen_entries.add(entry_identity)
            recovered.append(
                _recoverable_projection(
                    case_id,
                    case,
                    product=self.product,
                    position_fee_rate=self.policies.position.fee_rate_index_fraction,
                )
            )
            validated_opened[case_id] = case.opened

        case_by_enrollment = dict(self._case_by_enrollment)
        opened_by_case = dict(self._opened_by_case)
        for entry in recovered:
            previous = case_by_enrollment.get(entry.shadow_entry_identity)
            if previous is not None and previous != entry.case_id:
                raise ShadowCaseStoreError("duplicate active shadow_entry_identity")
            case_by_enrollment[entry.shadow_entry_identity] = entry.case_id
            opened_by_case[entry.case_id] = validated_opened[entry.case_id]
        self._case_by_enrollment = case_by_enrollment
        self._opened_by_case = opened_by_case
        return tuple(recovered)

    def open_recovery_segment(
        self,
        case_id: str,
        *,
        adoption_fact_boundary: FactBoundary | Mapping[str, object],
    ) -> RecoverableShadowEntry:
        """Open the next GAPPED Segment after a validated external process handoff."""

        case = self.read_case(case_id)
        if (
            case.opened.get("enrollment_kind") != "ADMITTED_SHADOW_TRADE"
            or case.outcome is not None
            or not case.segments
        ):
            raise ShadowCaseStoreError("only an active admitted Entry can open a recovery Segment")
        latest = case.segments[-1]
        if (
            latest.opened.get("code_identity") == self.bindings.code_identity
            and latest.opened.get("runtime_identity") == self.bindings.runtime_identity
        ):
            raise ShadowCaseStoreError("current runtime already owns the latest Segment")
        boundary = _as_fact_boundary(adoption_fact_boundary)
        if (
            boundary.code_identity != self.bindings.code_identity
            or boundary.runtime_identity != self.bindings.runtime_identity
        ):
            raise ShadowCaseStoreError("recovery Segment boundary binding mismatch")
        sequence = latest.sequence + 1
        record = self._segment_opened_record(
            case_id=case_id,
            opened=case.opened,
            sequence=sequence,
            adoption_boundary=boundary,
            predecessor=latest,
            entry_position_baseline=None,
        )
        self._publish_segment(case_id, sequence, "opened.json", record)
        refreshed = self.read_case(case_id, runtime_active=True)
        return _recoverable_projection(
            case_id,
            refreshed,
            product=self.product,
            position_fee_rate=self.policies.position.fee_rate_index_fraction,
        )

    def close_segment(
        self,
        case_id: str,
        *,
        segment_sequence: int,
        closed_fact_boundary: FactBoundary | Mapping[str, object],
        terminal_state: str,
    ) -> ShadowCaseSegmentRead:
        """Close one runtime Segment without terminalizing the admitted Entry."""

        case = self.read_case(case_id, runtime_active=True)
        if case.outcome is not None or not case.segments:
            raise ShadowCaseStoreError("terminal or segmentless Case cannot close a Segment")
        segment = case.segments[-1]
        if segment.sequence != segment_sequence:
            raise ShadowCaseStoreError("only the latest Observation Segment can be closed")
        record = self._segment_closed_record(
            case.opened,
            segment.opened,
            closed_fact_boundary=closed_fact_boundary,
            terminal_state=terminal_state,
        )
        if segment.closed is not None:
            if segment.closed == record:
                return segment
            raise ShadowCaseStoreError("conflicting Observation Segment close")
        self._publish_segment(case_id, segment_sequence, "closed.json", record)
        return self.read_case(case_id).segments[-1]

    def close_active_admitted_segments(
        self,
        *,
        boundary: FactBoundary | Mapping[str, object],
        terminal_state: str,
    ) -> tuple[ShadowCaseSegmentRead, ...]:
        """Close this runtime's admitted Segments without writing aggregate Outcomes."""

        closed: list[ShadowCaseSegmentRead] = []
        for case_id, opened in sorted(self._opened_by_case.items()):
            if opened.get("enrollment_kind") != "ADMITTED_SHADOW_TRADE":
                continue
            case = self.read_case(case_id, runtime_active=True)
            if case.outcome is not None or not case.segments:
                continue
            latest = case.segments[-1]
            if (
                latest.opened.get("code_identity") != self.bindings.code_identity
                or latest.opened.get("runtime_identity") != self.bindings.runtime_identity
            ):
                continue
            closed.append(
                self.close_segment(
                    case_id,
                    segment_sequence=latest.sequence,
                    closed_fact_boundary=boundary,
                    terminal_state=terminal_state,
                )
            )
        return tuple(closed)

    def _open_case(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        object_kind = value.get("object_kind")
        payload = _mapping(value.get("payload"), f"{object_kind}.payload")
        enrollment_identity = _identity(
            value.get("object_identity"),
            "enrollment_identity",
        )
        boundary = _boundary(value.get("fact_boundary"), "opened_fact_boundary")
        if object_kind == "SHADOW_ENTRY":
            enrollment_kind = "ADMITTED_SHADOW_TRADE"
            if payload.get("enrollment_kind") != enrollment_kind:
                raise ShadowCaseStoreError("Shadow Entry enrollment kind is invalid")
            shadow_entry_identity: str | None = enrollment_identity
            candidate_value = _identity(
                payload.get("candidate_identity"),
                "candidate_identity",
            )
            candidate_identity: str | None = candidate_value
            candidate = state.get_object("CANDIDATE_ACTIVATION", candidate_value)
            if candidate is None:
                raise ShadowCaseStoreError(
                    "Shadow Entry lacks its Candidate in current owner state"
                )
            candidate_payload = _mapping(candidate.get("payload"), "Candidate.payload")
            action_value = _identity(
                candidate_payload.get("underwriting_action_identity"),
                "underwriting_action_identity",
            )
            action_identity: str | None = action_value
            action = state.get_object("UNDERWRITING_ACTION", action_value)
            if action is None:
                raise ShadowCaseStoreError("Shadow Entry lacks its Underwriting action")
            selected_decision = payload.get("selected_underwriting_decision")
        elif object_kind in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN",
        }:
            enrollment_kind = (
                "RADAR_SCORE_BAND_NO_TRADE_CONTROL"
                if object_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN"
                else "SELECTED_UNDERWRITING_DECISION_CONTROL"
            )
            if payload.get("enrollment_kind") != enrollment_kind:
                raise ShadowCaseStoreError("decision-control enrollment kind is invalid")
            shadow_entry_identity = None
            candidate_identity = None
            action_identity = None
            selection_identity = _identity(
                payload.get("selected_underwriting_decision_identity"),
                "selected_underwriting_decision_identity",
            )
            if state.get_object("SELECTED_UNDERWRITING_DECISION", selection_identity) is None:
                raise ShadowCaseStoreError(
                    "decision-control open lacks its current selected decision"
                )
            selected_decision = payload.get("selected_underwriting_decision")
        else:
            raise ShadowCaseStoreError("unsupported Shadow Case enrollment kind")
        entry_underwriting_action_identity = _identity(
            payload.get("entry_underwriting_action_identity"),
            "entry_underwriting_action_identity",
        )
        entry_underwriting_economic_fingerprint = _identity(
            payload.get("entry_underwriting_consumed_economic_fact_fingerprint"),
            "entry_underwriting_consumed_economic_fact_fingerprint",
        )
        decision_boundary = payload.get("entry_underwriting_decision_fact_boundary")
        underwriting_action = payload.get("entry_underwriting_economic_action")
        failed_predicates = payload.get("entry_underwriting_failed_predicates")
        predicate_margin_vector = payload.get("entry_underwriting_predicate_margin_vector")
        case_id = _shadow_case_identity(
            bindings=self.bindings,
            enrollment_identity=enrollment_identity,
            opened_boundary=boundary,
            schema_version=self.schema_version,
            product=self.product,
        )
        entry_component_legs = _component_legs_for_schema(
            payload.get("entry_component_legs"),
            schema_version=self.schema_version,
        )
        opened: dict[str, object] = {
            "record_kind": OPENED_KIND,
            "schema_version": self.schema_version,
            "case_id": case_id,
            **self._binding_object(),
            "shadow_case_contract_identity": self.bindings.shadow_case_contract_identity,
            "opened_fact_boundary": boundary,
            "enrollment_kind": enrollment_kind,
            "enrollment_identity": enrollment_identity,
            "shadow_entry_identity": shadow_entry_identity,
            "candidate_identity": candidate_identity,
            "underwriting_action_identity": action_identity,
            "decision_fact_boundary": decision_boundary,
            "selected_underwriting_decision": selected_decision,
            "selection_score_packet": payload.get("selection_score_packet"),
            "entry_refresh_score_packet": payload.get("entry_refresh_score_packet"),
            "structure": {
                "execution_model": payload.get("execution_model"),
                "canonical_leg_identities": payload.get("canonical_leg_identities"),
                "short_leg_instrument_name": payload.get("short_leg_instrument_name"),
                "long_leg_instrument_name": payload.get("long_leg_instrument_name"),
                "expiry_ms": payload.get("expiry_ms"),
                "option_type": payload.get("option_type"),
                "short_strike_usdc_per_btc": payload.get("short_strike_usdc_per_btc"),
                "long_strike_usdc_per_btc": payload.get("long_strike_usdc_per_btc"),
                "entry_direction": payload.get("entry_direction"),
                "full_quantity_btc": payload.get("full_quantity_btc"),
                "entry_component_pair_identity": payload.get("entry_component_pair_identity"),
                "entry_component_pair_timing": payload.get("entry_component_pair_timing"),
                "entry_component_pair_limits": payload.get("entry_component_pair_limits"),
                "entry_component_quote_source_refs": payload.get(
                    "entry_component_quote_source_refs"
                ),
                "entry_component_legs": entry_component_legs,
            },
            "radar": {
                "active_episode_identity": payload.get("active_episode_identity"),
                "radar_research_review_identity": payload.get("radar_research_review_identity"),
                "radar_activation_causal_seq": payload.get("radar_activation_causal_seq"),
                "radar_scope_identity": payload.get("radar_scope_identity"),
                "component_state": payload.get("component_state"),
                "atomic_state_diagnostic": payload.get("atomic_state_diagnostic"),
            },
            "underwriting": {
                "action_identity": entry_underwriting_action_identity,
                "consumed_economic_fact_fingerprint": (entry_underwriting_economic_fingerprint),
                "action": underwriting_action,
                "failed_predicates": failed_predicates,
                "predicate_margin_vector": predicate_margin_vector,
                "protective_leg_selection_rule_identity": payload.get(
                    "entry_underwriting_protective_leg_selection_rule_identity"
                ),
                "candidate_protective_leg_count": payload.get(
                    "entry_underwriting_candidate_protective_leg_count"
                ),
                "minimum_net_entry_credit_usdc": str(
                    self.policies.underwriting.minimum_net_entry_credit_usdc
                ),
                "minimum_net_credit_to_payoff_cap_fraction": str(
                    self.policies.underwriting.minimum_net_credit_to_payoff_cap_fraction
                ),
                "maximum_underwriting_reserved_loss_usdc": str(
                    self.policies.underwriting.maximum_underwriting_reserved_loss_usdc
                ),
                "maximum_entry_consumed_level_count": (
                    self.policies.underwriting.maximum_entry_consumed_level_count
                ),
            },
            "entry_economics": {
                "gross_entry_credit_usdc": payload.get("gross_entry_credit_usdc"),
                "entry_fee_reserve_usdc": payload.get("entry_fee_reserve_usdc"),
                "net_entry_credit_usdc": payload.get("net_entry_credit_usdc"),
                "width_usdc_per_btc": payload.get("width_usdc_per_btc"),
                "payoff_cap_usdc": payload.get("payoff_cap_usdc"),
                "contractual_payoff_max_loss_ex_fees_usdc": payload.get(
                    "contractual_payoff_max_loss_ex_fees_usdc"
                ),
                "entry_fee_reserved_payoff_loss_usdc": payload.get(
                    "entry_fee_reserved_payoff_loss_usdc"
                ),
                "future_cost_reserve_usdc": payload.get("future_cost_reserve_usdc"),
                "underwriting_reserved_loss_usdc": payload.get("underwriting_reserved_loss_usdc"),
            },
            "non_claims": payload.get("non_claims"),
        }
        contractual_payoff_cap = _decimal(
            payload.get("payoff_cap_usdc"),
            "payoff_cap_usdc",
        )
        entry_valuation_index = _decimal(
            payload.get("entry_valuation_index_price"),
            "entry_valuation_index_price",
        )
        native_payoff_cap_at_entry_index = self.product.native_payoff_from_strike_value(
            contractual_payoff_cap,
            settlement_price=entry_valuation_index,
        )
        opened.update(
            {
                "product": _product_record(self.product),
                "native_entry_economics": {
                    "native_gross_entry_credit": payload.get("native_gross_entry_credit"),
                    "native_entry_fee_reserve": payload.get("native_entry_fee_reserve"),
                    "native_net_entry_credit": payload.get("native_net_entry_credit"),
                    "entry_valuation_index_price": payload.get("entry_valuation_index_price"),
                    "boundary_valued_gross_entry_credit_usd": payload.get(
                        "gross_entry_credit_usdc"
                    ),
                    "boundary_valued_entry_fee_reserve_usd": payload.get("entry_fee_reserve_usdc"),
                    "boundary_valued_net_entry_credit_usd": payload.get("net_entry_credit_usdc"),
                    "contractual_payoff_cap_strike_currency": contractual_payoff_cap,
                    "native_contractual_payoff_cap_at_entry_index": (
                        native_payoff_cap_at_entry_index
                    ),
                    "native_contractual_payoff_cap_basis": (
                        "ENTRY_INDEX_COUNTERFACTUAL_NOT_EXPIRY_SETTLEMENT"
                    ),
                    "expiry_delivery_price": None,
                    "native_contractual_payoff_at_expiry": None,
                },
            }
        )
        opened["structure"] = _renamed_fields(
            _mapping(opened.get("structure"), "structure"),
            _V5_STRUCTURE_FIELDS,
        )
        opened["underwriting"] = _renamed_fields(
            _mapping(opened.get("underwriting"), "underwriting"),
            _V5_UNDERWRITING_FIELDS,
        )
        opened["entry_economics"] = _renamed_fields(
            _mapping(opened.get("entry_economics"), "entry_economics"),
            _V5_ENTRY_ECONOMICS_FIELDS,
        )
        normalized = _normalized_mapping(opened)
        _validate_opened(
            normalized,
            expected_case_id=case_id,
            bindings=self.bindings,
            policies=self.policies,
        )
        origin_segment: Mapping[str, object] | None = None
        if enrollment_kind == "ADMITTED_SHADOW_TRADE":
            entry_position_baseline = _entry_position_baseline(
                payload,
                schema_version=self.schema_version,
                opened_boundary=boundary,
            )
            origin_segment = self._segment_opened_record(
                case_id=case_id,
                opened=normalized,
                sequence=0,
                adoption_boundary=FactBoundary.from_object(boundary),
                predecessor=None,
                entry_position_baseline=entry_position_baseline,
            )
        self._publish_new_case(
            case_id,
            opened=normalized,
            origin_segment=origin_segment,
        )
        if origin_segment is not None:
            current_payload = dict(_mapping(value.get("payload"), "SHADOW_ENTRY.payload"))
            current_payload.update(
                {
                    "origin_case_id": case_id,
                    "origin_runtime_identity": self.bindings.runtime_identity,
                    "current_segment_identity": origin_segment.get("segment_identity"),
                    "current_segment_sequence": 0,
                    "observation_quality": "CONTINUOUS",
                    "gap_count": 0,
                    "qualification_eligible": True,
                    "tracking_state": "ACTIVE",
                    "post_close_attempt_state": "NOT_SCHEDULED",
                }
            )
            state.restore_current_record(
                object_kind="SHADOW_ENTRY",
                object_identity=enrollment_identity,
                fact_boundary=FactBoundary.from_object(boundary),
                payload=current_payload,
                replace_existing=True,
            )
        self._case_by_enrollment[enrollment_identity] = case_id
        self._opened_by_case[case_id] = normalized
        self._case_count += 1

    def _remember_first_close(self, value: Mapping[str, object]) -> None:
        payload = _mapping(value.get("payload"), "POSITION_ACTION.payload")
        action_identity = _identity(value.get("object_identity"), "position_action_identity")
        if (
            payload.get("serialized_action") != "CLOSE"
            or payload.get("first_latched_close_action_identity") != action_identity
        ):
            return
        entry_identity = _identity(payload.get("shadow_entry_identity"), "shadow_entry_identity")
        case_id = self._case_by_enrollment.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("first CLOSE belongs to an unopened Shadow Case")
        opened = self._opened_by_case[case_id]
        if opened.get("enrollment_kind") in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        }:
            record = _normalized_mapping(
                {
                    "record_kind": FIRST_CLOSE_KIND,
                    "schema_version": opened.get("schema_version"),
                    "case_id": case_id,
                    **self._binding_object(),
                    "first_close_fact_boundary": value.get("fact_boundary"),
                    "position_action_identity": action_identity,
                    "primary_close_reason": payload.get("primary_close_reason"),
                    "ordered_latched_close_reasons": payload.get(
                        "ordered_latched_close_reason_vector"
                    ),
                    "predicate_truth_vector": payload.get("ordered_predicate_truth_vector"),
                }
            )
            _validate_followup(
                opened,
                record,
                expected_kind=FIRST_CLOSE_KIND,
                policies=self.policies,
            )
            self._publish(case_id, "first-close.json", record)
            return
        previous = self._pending_first_close_by_entry.get(entry_identity)
        if previous is not None and previous != value:
            raise ShadowCaseStoreError("conflicting pending first CLOSE")
        self._pending_first_close_by_entry[entry_identity] = value

    def _record_first_close_and_attempt(self, value: Mapping[str, object]) -> None:
        schedule = _mapping(value.get("payload"), "POST_CLOSE_ATTEMPT_SCHEDULED.payload")
        if schedule.get("scheduled_post_close_attempt_identity") != value.get("object_identity"):
            raise ShadowCaseStoreError("post-CLOSE attempt payload identity mismatch")
        entry_identity = _identity(schedule.get("shadow_entry_identity"), "shadow_entry_identity")
        case_id = self._case_by_enrollment.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("post-CLOSE attempt belongs to an unopened Shadow Case")
        opened = self._opened_by_case[case_id]
        if opened.get("enrollment_kind") in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        }:
            return
        pending = self._pending_first_close_by_entry.get(entry_identity)
        if pending is None:
            raise ShadowCaseStoreError("post-CLOSE attempt lacks its pending first CLOSE")
        action = _mapping(pending.get("payload"), "POSITION_ACTION.payload")
        action_identity = _identity(
            pending.get("object_identity"),
            "position_action_identity",
        )
        if schedule.get("first_latched_close_action_identity") != action_identity:
            raise ShadowCaseStoreError("post-CLOSE attempt first CLOSE identity mismatch")
        case = self.read_case(case_id, runtime_active=True)
        if case.first_close is not None or case.outcome is not None or not case.segments:
            raise ShadowCaseStoreError("Shadow Case cannot schedule another first CLOSE attempt")
        segment = case.segments[-1]
        structure = _mapping(case.opened.get("structure"), "structure")
        record = _normalized_mapping(
            {
                "record_kind": FIRST_CLOSE_KIND,
                "schema_version": case.opened.get("schema_version"),
                "case_id": case_id,
                **self._binding_object(),
                "product_spec_identity": self.product.identity,
                "segment_sequence": segment.sequence,
                "segment_identity": segment.opened.get("segment_identity"),
                "transition": "FIRST_CLOSE_AND_ATTEMPT_SCHEDULED",
                "first_close_fact_boundary": pending.get("fact_boundary"),
                "position_action_identity": action_identity,
                "primary_close_reason": action.get("primary_close_reason"),
                "ordered_latched_close_reasons": action.get("ordered_latched_close_reason_vector"),
                "predicate_truth_vector": action.get("ordered_predicate_truth_vector"),
                "scheduled_post_close_attempt_identity": value.get("object_identity"),
                "request_id_or_marker": schedule.get("request_id_or_marker"),
                "execution_model": schedule.get("execution_model"),
                "request_method": schedule.get("request_method"),
                "request_params": schedule.get("request_params"),
                "canonical_leg_identities": structure.get("canonical_leg_identities"),
                "full_quantity_btc": structure.get("full_quantity_btc"),
                "schedule_fact_boundary": schedule.get("schedule_fact_boundary"),
            }
        )
        self._validate_stable_first_close(
            opened=case.opened,
            segments=case.segments,
            value=record,
        )
        self._publish(case_id, "first-close.json", record)
        self._pending_first_close_by_entry.pop(entry_identity, None)

    def _record_outcome(self, value: Mapping[str, object]) -> None:
        payload = _mapping(value.get("payload"), "SHADOW_OUTCOME.payload")
        entry_identity = _identity(payload.get("shadow_entry_identity"), "shadow_entry_identity")
        case_id = self._case_by_enrollment.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("Outcome belongs to an unopened Shadow Case")
        opened = self._opened_by_case[case_id]
        admitted = opened.get("enrollment_kind") == "ADMITTED_SHADOW_TRADE"
        terminal_state = payload.get("terminal_state")
        if admitted and terminal_state in {"CENSORED_AT_STOP", "CENSORED_AT_FAILURE"}:
            raise ShadowCaseStoreError(
                "stable admitted Entry cannot emit a censored aggregate Outcome"
            )
        schema_version = _record_schema_version(opened)
        outcome_record: dict[str, object] = {
            "record_kind": OUTCOME_KIND,
            "schema_version": schema_version,
            "case_id": case_id,
            **self._binding_object(),
            "outcome_fact_boundary": value.get("fact_boundary"),
            "shadow_outcome_identity": value.get("object_identity"),
            "terminal_state": payload.get("terminal_state"),
            "selected_exit_identity": payload.get("selected_exit_identity"),
            "first_latched_close_action_identity": payload.get(
                "first_latched_close_action_identity"
            ),
            "gross_close_cashflow_usdc": payload.get("gross_close_cashflow_usdc"),
            "close_fee_reserve_usdc": payload.get("close_fee_reserve_usdc"),
            "net_close_cashflow_usdc": payload.get("net_close_cashflow_usdc"),
            "gross_pnl_usdc": payload.get("gross_pnl_usdc"),
            "total_public_fee_reserve_usdc": payload.get("total_public_fee_reserve_usdc"),
            "net_pnl_after_public_standard_fee_reserve_usdc": payload.get(
                "net_pnl_after_public_standard_fee_reserve_usdc"
            ),
            "net_loss_usdc": payload.get("net_loss_usdc"),
            "economic_availability": payload.get("economic_availability"),
            "close_component_pair_identity": payload.get("close_component_pair_identity"),
            "close_component_quote_source_refs": payload.get("close_component_quote_source_refs"),
            "close_component_legs": _component_legs_for_schema(
                payload.get("close_component_legs"),
                schema_version=schema_version,
            ),
            "censor_mask": payload.get("censor_mask"),
            "non_claims": payload.get("non_claims"),
        }
        outcome_record["native_outcome_economics"] = {
            "native_gross_close_cashflow": payload.get("native_gross_close_cashflow"),
            "native_close_fee_reserve": payload.get("native_close_fee_reserve"),
            "native_net_close_cashflow": payload.get("native_net_close_cashflow"),
            "native_gross_pnl": payload.get("native_gross_pnl"),
            "native_total_fee_reserve": payload.get("native_total_fee_reserve"),
            "native_net_pnl": payload.get("native_net_pnl"),
            "close_valuation_index_price": payload.get("close_valuation_index_price"),
            "boundary_valued_net_pnl_usd": payload.get("boundary_valued_net_pnl_usd"),
            "exit_valued_native_net_pnl_usd": payload.get("exit_valued_native_net_pnl_usd"),
        }
        outcome_record = _renamed_fields(
            outcome_record,
            _V5_OUTCOME_ECONOMICS_FIELDS,
        )
        producing_case: ShadowCaseRead | None = None
        if admitted:
            if terminal_state not in {"MATURE_KNOWN", "MATURE_UNKNOWN"}:
                raise ShadowCaseStoreError("admitted Entry Outcome must be mature")
            producing_case = self.read_case(case_id, runtime_active=True)
            if not producing_case.segments:
                raise ShadowCaseStoreError("mature Outcome lacks its producing Segment")
            segment = producing_case.segments[-1]
            outcome_record.update(
                {
                    "product_spec_identity": self.product.identity,
                    "segment_sequence": segment.sequence,
                    "segment_identity": segment.opened.get("segment_identity"),
                    "observation_quality": segment.opened.get("observation_quality"),
                    "gap_count": segment.opened.get("gap_count"),
                    "qualification_eligible": segment.opened.get("qualification_eligible"),
                }
            )
        record = _normalized_mapping(outcome_record)
        if admitted:
            assert producing_case is not None
            self._validate_stable_outcome(
                opened=opened,
                segments=producing_case.segments,
                value=record,
            )
        else:
            _validate_followup(
                opened,
                record,
                expected_kind=OUTCOME_KIND,
                policies=self.policies,
            )
            _validate_outcome_economics(opened, record)
        self._publish(case_id, "outcome.json", record)
        self._case_by_enrollment.pop(entry_identity, None)
        self._opened_by_case.pop(case_id, None)

    def _validate_compatible_opened(self, opened: Mapping[str, object]) -> None:
        expected_policies = {
            "radar_policy_identity": self.bindings.radar_policy_identity,
            "underwriting_policy_identity": self.bindings.underwriting_policy_identity,
            "position_policy_identity": self.bindings.position_policy_identity,
        }
        for field, expected in expected_policies.items():
            if opened.get(field) != expected:
                raise ShadowCaseStoreError(f"active Case Policy mismatch: {field}")
        if _product_from_opened(opened).identity != self.product.identity:
            raise ShadowCaseStoreError("active Case option product mismatch")

    def _read_nonrecoverable_case(
        self,
        case_id: str,
        opened: Mapping[str, object],
    ) -> None:
        if opened.get("enrollment_kind") not in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        }:
            raise ShadowCaseStoreError("Case enrollment kind is not recoverable")
        self.read_case(case_id)

    def _read_segments(
        self,
        case_id: str,
        opened: Mapping[str, object],
        *,
        runtime_active: bool,
    ) -> tuple[ShadowCaseSegmentRead, ...]:
        segments_directory = self._case_directory(case_id) / "segments"
        if not segments_directory.exists():
            return ()
        if segments_directory.is_symlink() or not segments_directory.is_dir():
            raise ShadowCaseStoreError("Observation Segment root is invalid")
        segment_directories: list[Path] = []
        for member in segments_directory.iterdir():
            if _is_staging_segment_name(member.name):
                if member.is_symlink() or not member.is_dir():
                    raise ShadowCaseStoreError("invalid Observation Segment staging path")
                continue
            segment_directories.append(member)
        raw_segments: list[tuple[int, Mapping[str, object], Mapping[str, object] | None]] = []
        predecessor: Mapping[str, object] | None = None
        for expected_sequence, segment_directory in enumerate(
            sorted(segment_directories, key=_segment_directory_sort_key)
        ):
            if segment_directory.name != str(expected_sequence):
                raise ShadowCaseStoreError("Observation Segment sequence is not contiguous")
            if segment_directory.is_symlink() or not segment_directory.is_dir():
                raise ShadowCaseStoreError("Observation Segment path is invalid")
            children = tuple(segment_directory.iterdir())
            if any(
                child.name not in {"opened.json", "closed.json"}
                and not _is_ignorable_writer_residue(
                    child,
                    allowed_records={"opened.json", "closed.json"},
                )
                for child in children
            ):
                raise ShadowCaseStoreError("Observation Segment contains an unauthorized record")
            segment_opened = _read_json(segment_directory / "opened.json")
            _validate_segment_opened(
                opened,
                segment_opened,
                expected_sequence=expected_sequence,
                predecessor=predecessor,
            )
            closed_path = segment_directory / "closed.json"
            closed = _read_optional_json(closed_path)
            if closed is not None:
                _validate_segment_closed(opened, segment_opened, closed)
            raw_segments.append((expected_sequence, segment_opened, closed))
            predecessor = segment_opened

        result: list[ShadowCaseSegmentRead] = []
        for index, (sequence, stored_segment_opened, stored_closed) in enumerate(raw_segments):
            if index:
                previous_closed = raw_segments[index - 1][2]
                expected_predecessor_state = (
                    previous_closed.get("terminal_state")
                    if previous_closed is not None
                    else "INCOMPLETE_UNCLEAN_EXIT"
                )
                if (
                    stored_segment_opened.get("predecessor_segment_state")
                    != expected_predecessor_state
                ):
                    raise ShadowCaseStoreError("Observation Segment predecessor state mismatch")
            if stored_closed is not None:
                status = ShadowCaseSegmentStatus(str(stored_closed.get("terminal_state")))
            elif (
                runtime_active
                and index == len(raw_segments) - 1
                and stored_segment_opened.get("code_identity") == self.bindings.code_identity
                and stored_segment_opened.get("runtime_identity") == self.bindings.runtime_identity
            ):
                status = ShadowCaseSegmentStatus.OPEN
            else:
                status = ShadowCaseSegmentStatus.INCOMPLETE_UNCLEAN_EXIT
            result.append(
                ShadowCaseSegmentRead(
                    sequence=sequence,
                    status=status,
                    opened=stored_segment_opened,
                    closed=stored_closed,
                )
            )
        return tuple(result)

    def _segment_opened_record(
        self,
        *,
        case_id: str,
        opened: Mapping[str, object],
        sequence: int,
        adoption_boundary: FactBoundary,
        predecessor: ShadowCaseSegmentRead | None,
        entry_position_baseline: Mapping[str, object] | None,
    ) -> dict[str, object]:
        predecessor_identity = (
            predecessor.opened.get("segment_identity") if predecessor is not None else None
        )
        predecessor_state = predecessor.status.value if predecessor is not None else None
        observation_quality = "GAPPED" if predecessor is not None else "CONTINUOUS"
        gap_count = (
            _nonnegative_int(predecessor.opened.get("gap_count"), "gap_count") + 1
            if predecessor is not None
            else 0
        )
        segment_identity = _segment_identity(
            case_id=case_id,
            sequence=sequence,
            bindings=self.bindings,
            predecessor_segment_identity=predecessor_identity,
            adoption_boundary=adoption_boundary,
        )
        record = _normalized_mapping(
            {
                "record_kind": SEGMENT_OPENED_KIND,
                "schema_version": opened.get("schema_version"),
                "case_id": case_id,
                "shadow_entry_identity": opened.get("shadow_entry_identity"),
                "segment_sequence": sequence,
                "segment_identity": segment_identity,
                **self._binding_object(),
                "product_spec_identity": self.product.identity,
                "adoption_fact_boundary": adoption_boundary.as_object(),
                "predecessor_segment_identity": predecessor_identity,
                "predecessor_segment_state": predecessor_state,
                "observation_quality": observation_quality,
                "gap_reason": "HANDOFF_GAP" if predecessor is not None else None,
                "gap_count": gap_count,
                "qualification_eligible": predecessor is None,
                "entry_position_baseline": entry_position_baseline,
            }
        )
        _validate_segment_opened(
            opened,
            record,
            expected_sequence=sequence,
            predecessor=predecessor.opened if predecessor is not None else None,
        )
        return record

    def _segment_closed_record(
        self,
        opened: Mapping[str, object],
        segment_opened: Mapping[str, object],
        *,
        closed_fact_boundary: FactBoundary | Mapping[str, object],
        terminal_state: str,
    ) -> dict[str, object]:
        record = _normalized_mapping(
            {
                "record_kind": SEGMENT_CLOSED_KIND,
                "schema_version": opened.get("schema_version"),
                "case_id": opened.get("case_id"),
                "shadow_entry_identity": opened.get("shadow_entry_identity"),
                "segment_sequence": segment_opened.get("segment_sequence"),
                "segment_identity": segment_opened.get("segment_identity"),
                **self._binding_object(),
                "product_spec_identity": self.product.identity,
                "closed_fact_boundary": _as_fact_boundary(closed_fact_boundary).as_object(),
                "terminal_state": terminal_state,
            }
        )
        _validate_segment_closed(opened, segment_opened, record)
        return record

    def _validate_stable_first_close(
        self,
        *,
        opened: Mapping[str, object],
        segments: tuple[ShadowCaseSegmentRead, ...],
        value: Mapping[str, object],
    ) -> None:
        extension_fields = {
            "product_spec_identity",
            "segment_sequence",
            "segment_identity",
            "transition",
            "scheduled_post_close_attempt_identity",
            "request_id_or_marker",
            "execution_model",
            "request_method",
            "request_params",
            "canonical_leg_identities",
            "full_quantity_btc",
            "schedule_fact_boundary",
        }
        legacy = {key: member for key, member in value.items() if key not in extension_fields}
        segment = _record_segment(segments, value)
        _validate_segment_bound_followup(opened, segment.opened, value)
        _validate_followup(
            _opened_projected_to_segment(opened, segment.opened),
            legacy,
            expected_kind=FIRST_CLOSE_KIND,
            policies=self.policies,
        )
        if value.get("transition") != "FIRST_CLOSE_AND_ATTEMPT_SCHEDULED":
            raise ShadowCaseStoreError("first CLOSE transition kind is invalid")
        schedule_boundary = FactBoundary.from_object(
            _boundary(value.get("schedule_fact_boundary"), "schedule_fact_boundary")
        )
        first_close_boundary = FactBoundary.from_object(
            _boundary(value.get("first_close_fact_boundary"), "first_close_fact_boundary")
        )
        if schedule_boundary != first_close_boundary:
            raise ShadowCaseStoreError("first CLOSE and attempt schedule are not atomic")
        if segment.closed is not None:
            closed_boundary = FactBoundary.from_object(
                _boundary(
                    segment.closed.get("closed_fact_boundary"),
                    "closed_fact_boundary",
                )
            )
            if first_close_boundary != closed_boundary and not closed_boundary.is_strictly_after(
                first_close_boundary
            ):
                raise ShadowCaseStoreError("first CLOSE is later than its Segment close")
        scheduled_identity = _identity(
            value.get("scheduled_post_close_attempt_identity"),
            "scheduled_post_close_attempt_identity",
        )
        _validate_attempt_schedule_identity(
            scheduled_identity=scheduled_identity,
            shadow_entry_identity=_identity(
                opened.get("shadow_entry_identity"),
                "shadow_entry_identity",
            ),
            position_action_identity=_identity(
                value.get("position_action_identity"),
                "position_action_identity",
            ),
            request_id_or_marker=value.get("request_id_or_marker"),
            request_method=value.get("request_method"),
            request_params=value.get("request_params"),
            schedule_boundary=schedule_boundary,
        )
        structure = _mapping(opened.get("structure"), "structure")
        if value.get("execution_model") != structure.get("execution_model"):
            raise ShadowCaseStoreError("first CLOSE execution model mismatch")
        if value.get("canonical_leg_identities") != structure.get("canonical_leg_identities"):
            raise ShadowCaseStoreError("first CLOSE canonical leg identities mismatch")
        if _decimal(value.get("full_quantity_btc"), "full_quantity_btc") != _decimal(
            structure.get("full_quantity_btc"),
            "opened full_quantity_btc",
        ):
            raise ShadowCaseStoreError("first CLOSE quantity mismatch")

    def _validate_stable_outcome(
        self,
        *,
        opened: Mapping[str, object],
        segments: tuple[ShadowCaseSegmentRead, ...],
        value: Mapping[str, object],
    ) -> None:
        extension_fields = {
            "product_spec_identity",
            "segment_sequence",
            "segment_identity",
            "observation_quality",
            "gap_count",
            "qualification_eligible",
        }
        legacy = {key: member for key, member in value.items() if key not in extension_fields}
        segment = _record_segment(segments, value)
        if segment.closed is not None:
            raise ShadowCaseStoreError("Outcome belongs to a closed Segment")
        _validate_segment_bound_followup(opened, segment.opened, value)
        _validate_followup(
            _opened_projected_to_segment(opened, segment.opened),
            legacy,
            expected_kind=OUTCOME_KIND,
            policies=self.policies,
        )
        if value.get("terminal_state") not in {"MATURE_KNOWN", "MATURE_UNKNOWN"}:
            raise ShadowCaseStoreError("stable admitted Outcome must be mature")
        _validate_outcome_economics(opened, legacy)
        for field in ("observation_quality", "gap_count", "qualification_eligible"):
            if value.get(field) != segment.opened.get(field):
                raise ShadowCaseStoreError(f"Outcome Segment projection mismatch: {field}")
        if (
            value.get("observation_quality") == "GAPPED"
            and value.get("qualification_eligible") is not False
        ):
            raise ShadowCaseStoreError("gapped Outcome cannot be qualification eligible")

    def _publish_segment(
        self,
        case_id: str,
        sequence: int,
        filename: str,
        value: Mapping[str, object],
    ) -> None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ShadowCaseStoreError("segment sequence must be a non-negative integer")
        case_directory = self._case_directory(case_id)
        if case_directory.is_symlink() or not case_directory.is_dir():
            raise ShadowCaseStoreError("Case directory is invalid")
        segments_directory = case_directory / "segments"
        _ensure_plain_directory(segments_directory)
        segment_directory = segments_directory / str(sequence)
        if filename == "closed.json":
            if segment_directory.is_symlink() or not segment_directory.is_dir():
                raise ShadowCaseStoreError("Observation Segment directory is invalid")
            self._publish_in_directory(segment_directory, filename, value)
            return
        if filename != "opened.json":
            raise ShadowCaseStoreError("Observation Segment filename is invalid")
        if segment_directory.exists() or segment_directory.is_symlink():
            if segment_directory.is_symlink() or not segment_directory.is_dir():
                raise ShadowCaseStoreError("conflicting Observation Segment path")
            if _read_json(segment_directory / "opened.json") == value:
                return
            raise ShadowCaseStoreError("conflicting Observation Segment opened record")

        case = self.read_case(case_id)
        if case.outcome is not None or sequence != len(case.segments):
            raise ShadowCaseStoreError("Observation Segment append sequence is invalid")
        predecessor = case.segments[-1].opened if case.segments else None
        staging = segments_directory / f".segment-{uuid.uuid4().hex}.tmp"
        try:
            staging.mkdir()
            _write_staged_record(staging / "opened.json", value)
            _fsync_directory(staging)
            staged = _read_json(staging / "opened.json")
            if staged != value:
                raise ShadowCaseStoreError("staged Observation Segment opened record changed")
            _validate_segment_opened(
                case.opened,
                staged,
                expected_sequence=sequence,
                predecessor=predecessor,
            )
            try:
                staging.rename(segment_directory)
            except FileExistsError as exc:
                raise ShadowCaseStoreError("conflicting Observation Segment directory") from exc
            _fsync_directory(segments_directory)
        except ShadowCaseStoreError:
            raise
        except OSError as exc:
            raise ShadowCaseStoreError("cannot atomically publish Observation Segment") from exc
        finally:
            _remove_staging_segment(staging)

    def _publish_new_case(
        self,
        case_id: str,
        *,
        opened: Mapping[str, object],
        origin_segment: Mapping[str, object] | None,
    ) -> None:
        final_directory = self._case_directory(case_id)
        if final_directory.exists() or final_directory.is_symlink():
            if final_directory.is_symlink() or not final_directory.is_dir():
                raise ShadowCaseStoreError("conflicting Shadow Case path")
            if _read_json(final_directory / "opened.json") != opened:
                raise ShadowCaseStoreError("conflicting Shadow Case opened record")
            existing_segment = final_directory / "segments" / "0" / "opened.json"
            if origin_segment is None:
                if existing_segment.exists():
                    raise ShadowCaseStoreError("conflicting control Case Segment")
            elif _read_json(existing_segment) != origin_segment:
                raise ShadowCaseStoreError("conflicting Shadow Case origin Segment")
            return

        staging = self.directory / f".case-{uuid.uuid4().hex}.tmp"
        try:
            staging.mkdir()
            _write_staged_record(staging / "opened.json", opened)
            if origin_segment is not None:
                segment_directory = staging / "segments" / "0"
                segment_directory.mkdir(parents=True)
                _write_staged_record(segment_directory / "opened.json", origin_segment)
                _fsync_directory(segment_directory)
                _fsync_directory(segment_directory.parent)
            _fsync_directory(staging)
            staged_opened = _read_json(staging / "opened.json")
            if staged_opened != opened:
                raise ShadowCaseStoreError("staged Shadow Case opened record changed")
            _validate_opened(
                staged_opened,
                expected_case_id=case_id,
                bindings=self.bindings,
                policies=self.policies,
            )
            self._validate_compatible_opened(staged_opened)
            if origin_segment is None:
                if staged_opened.get("enrollment_kind") == "ADMITTED_SHADOW_TRADE":
                    raise ShadowCaseStoreError("staged admitted Case lacks its origin Segment")
            else:
                staged_segment = _read_json(staging / "segments" / "0" / "opened.json")
                if staged_segment != origin_segment:
                    raise ShadowCaseStoreError("staged Shadow Case origin Segment changed")
                _validate_segment_opened(
                    staged_opened,
                    staged_segment,
                    expected_sequence=0,
                    predecessor=None,
                )
            try:
                staging.rename(final_directory)
            except FileExistsError as exc:
                raise ShadowCaseStoreError("conflicting Shadow Case directory") from exc
            _fsync_directory(self.directory)
        except ShadowCaseStoreError:
            raise
        except OSError as exc:
            raise ShadowCaseStoreError("cannot atomically publish new Shadow Case") from exc
        finally:
            _remove_staging_case(staging)

    def _binding_object(self) -> dict[str, str]:
        return {
            "code_identity": self.bindings.code_identity,
            "runtime_identity": self.bindings.runtime_identity,
            "radar_policy_identity": self.bindings.radar_policy_identity,
            "underwriting_policy_identity": self.bindings.underwriting_policy_identity,
            "position_policy_identity": self.bindings.position_policy_identity,
        }

    def _case_directory(self, case_id: str) -> Path:
        return self.directory / case_id.removeprefix("sha256:")

    def _publish(
        self,
        case_id: str,
        filename: str,
        value: Mapping[str, object],
    ) -> None:
        case_directory = self._case_directory(case_id)
        if case_directory.is_symlink():
            raise ShadowCaseStoreError("Case directory cannot be a symlink")
        try:
            case_directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise ShadowCaseStoreError("cannot create Shadow Case directory") from exc
        status = case_directory.stat()
        if not stat.S_ISDIR(status.st_mode):
            raise ShadowCaseStoreError("Shadow Case path is not a directory")
        self._publish_in_directory(case_directory, filename, value)

    def _publish_in_directory(
        self,
        directory: Path,
        filename: str,
        value: Mapping[str, object],
    ) -> None:
        if directory.is_symlink() or not directory.is_dir():
            raise ShadowCaseStoreError("Shadow Case record directory is invalid")
        serialized = _serialize(value)
        path = directory / filename
        temporary = directory / f".case-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        except FileExistsError as exc:
            if path.read_bytes() == serialized:
                return
            raise ShadowCaseStoreError(f"conflicting Shadow Case record: {path}") from exc
        except OSError as exc:
            raise ShadowCaseStoreError(f"Shadow Case publish failed: {path}") from exc
        finally:
            temporary.unlink(missing_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _bindings_from_opened(opened: Mapping[str, object]) -> RuntimeBindings:
    try:
        return RuntimeBindings(
            code_identity=str(opened.get("code_identity")),
            runtime_identity=str(opened.get("runtime_identity")),
            radar_policy_identity=str(opened.get("radar_policy_identity")),
            underwriting_policy_identity=str(opened.get("underwriting_policy_identity")),
            position_policy_identity=str(opened.get("position_policy_identity")),
        )
    except ValueError as exc:
        raise ShadowCaseStoreError("opened record has invalid origin bindings") from exc


def _case_id_from_directory(case_directory: Path) -> str:
    case_id = f"sha256:{case_directory.name}"
    _identity(case_id, "case_id")
    return case_id


def _segment_directory_sort_key(path: Path) -> int:
    if not path.name.isascii() or not path.name.isdecimal():
        raise ShadowCaseStoreError("Observation Segment directory name is invalid")
    if path.name != "0" and path.name.startswith("0"):
        raise ShadowCaseStoreError("Observation Segment directory name is not canonical")
    return int(path.name)


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowCaseStoreError(f"{field} must be a non-negative integer")
    return value


def _as_fact_boundary(value: FactBoundary | Mapping[str, object]) -> FactBoundary:
    if isinstance(value, FactBoundary):
        return value
    try:
        return FactBoundary.from_object(value)
    except ValueError as exc:
        raise ShadowCaseStoreError("FactBoundary is invalid") from exc


def _segment_identity(
    *,
    case_id: str,
    sequence: int,
    bindings: RuntimeBindings,
    predecessor_segment_identity: object,
    adoption_boundary: FactBoundary,
) -> str:
    return canonical_identity(
        "ShadowCaseObservationSegmentIdentity",
        case_id,
        sequence,
        bindings.code_identity,
        bindings.runtime_identity,
        predecessor_segment_identity,
        adoption_boundary.as_object(),
    )


def _ensure_plain_directory(path: Path) -> None:
    if path.is_symlink():
        raise ShadowCaseStoreError(f"Shadow Case directory cannot be a symlink: {path}")
    try:
        path.mkdir(exist_ok=True)
    except OSError as exc:
        raise ShadowCaseStoreError(f"cannot create Shadow Case directory: {path}") from exc
    if path.is_symlink() or not path.is_dir():
        raise ShadowCaseStoreError(f"Shadow Case directory is invalid: {path}")
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _write_staged_record(path: Path, value: Mapping[str, object]) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(_serialize(value))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ShadowCaseStoreError(f"cannot stage Shadow Case record: {path}") from exc


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def is_shadow_case_staging_name(name: str) -> bool:
    """Return whether ``name`` is the store-owned atomic Case staging shape."""

    prefix = ".case-"
    suffix = ".tmp"
    middle = name[len(prefix) : -len(suffix)] if name.startswith(prefix) else ""
    return (
        name.endswith(suffix)
        and len(middle) == 32
        and all(character in "0123456789abcdef" for character in middle)
    )


def _is_staging_segment_name(name: str) -> bool:
    prefix = ".segment-"
    suffix = ".tmp"
    middle = name[len(prefix) : -len(suffix)] if name.startswith(prefix) else ""
    return (
        name.endswith(suffix)
        and len(middle) == 32
        and all(character in "0123456789abcdef" for character in middle)
    )


def _is_ignorable_writer_residue(
    path: Path,
    *,
    allowed_records: set[str],
) -> bool:
    if not is_shadow_case_staging_name(path.name) or path.is_symlink():
        return False
    try:
        status = path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(status.st_mode):
        return False
    if status.st_nlink == 1:
        return True
    if status.st_nlink != 2:
        return False
    for filename in allowed_records:
        published = path.parent / filename
        if published.is_symlink() or not published.is_file():
            continue
        try:
            if path.samefile(published):
                return True
        except OSError:
            continue
    return False


def _remove_staging_case(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    for record in (
        path / "segments" / "0" / "opened.json",
        path / "opened.json",
    ):
        record.unlink(missing_ok=True)
    for directory in (path / "segments" / "0", path / "segments", path):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            # An unexpected member is never deleted by cleanup; startup will ignore only
            # the exact staging name and the operator can inspect it.
            break


def _remove_staging_segment(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    (path / "opened.json").unlink(missing_ok=True)
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        # Unexpected members are preserved for operator inspection.
        pass


def _validate_case_directory_members(case_directory: Path, *, stable: bool) -> None:
    if case_directory.is_symlink() or not case_directory.is_dir():
        raise ShadowCaseStoreError("Shadow Case directory is missing or invalid")
    allowed = {"opened.json", "first-close.json", "outcome.json"}
    if stable:
        allowed.add("segments")
    try:
        members = tuple(case_directory.iterdir())
    except OSError as exc:
        raise ShadowCaseStoreError("cannot enumerate Shadow Case directory") from exc
    if any(
        member.name not in allowed
        and not _is_ignorable_writer_residue(member, allowed_records=allowed)
        for member in members
    ):
        raise ShadowCaseStoreError("Shadow Case contains an unauthorized durable record")


def _entry_position_baseline(
    payload: Mapping[str, object],
    *,
    schema_version: int,
    opened_boundary: Mapping[str, object],
) -> dict[str, object]:
    entry_index = payload.get("entry_index_usdc_per_btc")
    if entry_index is None:
        entry_index = payload.get("entry_valuation_index_price")
    baseline = _normalized_mapping(
        {
            "entry_index_usd_per_btc": entry_index,
            "entry_index_source_ref": payload.get("entry_index_source_ref"),
            "entry_short_leg_mark_iv_fraction": payload.get("entry_short_leg_mark_iv_fraction"),
            "entry_short_leg_mark_iv_source_ref": payload.get("entry_short_leg_mark_iv_source_ref"),
        }
    )
    _validate_entry_position_baseline(
        baseline,
        schema_version=schema_version,
        adoption_boundary=FactBoundary.from_object(opened_boundary),
        require_complete=True,
    )
    return baseline


def _validate_entry_position_baseline(
    value: object,
    *,
    schema_version: int,
    adoption_boundary: FactBoundary,
    require_complete: bool = False,
) -> None:
    baseline = _mapping(value, "entry_position_baseline")
    index_field = "entry_index_usd_per_btc"
    _exact_keys(
        baseline,
        {
            "entry_index_usd_per_btc",
            "entry_index_source_ref",
            "entry_short_leg_mark_iv_fraction",
            "entry_short_leg_mark_iv_source_ref",
        },
        "entry_position_baseline",
    )
    index_value = baseline.get("entry_index_usd_per_btc")
    mark_value = baseline.get("entry_short_leg_mark_iv_fraction")
    if index_value is not None and _decimal(index_value, index_field) <= 0:
        raise ShadowCaseStoreError("entry Position index baseline must be positive")
    if (
        mark_value is not None
        and _decimal(
            mark_value,
            "entry_short_leg_mark_iv_fraction",
        )
        <= 0
    ):
        raise ShadowCaseStoreError("entry short-leg mark IV baseline must be positive")
    for value_field, field in (
        (index_field, "entry_index_source_ref"),
        ("entry_short_leg_mark_iv_fraction", "entry_short_leg_mark_iv_source_ref"),
    ):
        raw_source = baseline.get(field)
        if raw_source is None:
            continue
        if baseline.get(value_field) is None:
            raise ShadowCaseStoreError(f"{field} exists without its baseline value")
        source = _mapping(raw_source, field)
        _exact_keys(source, {"source_identity", "receipt_fact_boundary"}, field)
        _identity(source.get("source_identity"), f"{field}.source_identity")
        source_boundary = FactBoundary.from_object(
            _boundary(source.get("receipt_fact_boundary"), f"{field}.receipt_fact_boundary")
        )
        if (
            source_boundary.code_identity != adoption_boundary.code_identity
            or source_boundary.runtime_identity != adoption_boundary.runtime_identity
            or (
                source_boundary != adoption_boundary
                and not adoption_boundary.is_strictly_after(source_boundary)
            )
        ):
            raise ShadowCaseStoreError(f"{field} is not causally available at Entry")
    if require_complete and any(
        baseline.get(field) is None
        for field in (
            index_field,
            "entry_index_source_ref",
            "entry_short_leg_mark_iv_fraction",
            "entry_short_leg_mark_iv_source_ref",
        )
    ):
        raise ShadowCaseStoreError("new admitted Entry lacks a complete Position baseline")


def _validate_segment_opened(
    opened: Mapping[str, object],
    value: Mapping[str, object],
    *,
    expected_sequence: int,
    predecessor: Mapping[str, object] | None,
) -> None:
    _exact_keys(
        value,
        {
            "record_kind",
            "schema_version",
            "case_id",
            "shadow_entry_identity",
            "segment_sequence",
            "segment_identity",
            "code_identity",
            "runtime_identity",
            "radar_policy_identity",
            "underwriting_policy_identity",
            "position_policy_identity",
            "product_spec_identity",
            "adoption_fact_boundary",
            "predecessor_segment_identity",
            "predecessor_segment_state",
            "observation_quality",
            "gap_reason",
            "gap_count",
            "qualification_eligible",
            "entry_position_baseline",
        },
        "Observation Segment opened",
    )
    schema_version = _record_schema_version(opened)
    if value.get("record_kind") != SEGMENT_OPENED_KIND:
        raise ShadowCaseStoreError("Observation Segment opened kind is invalid")
    if value.get("schema_version") != schema_version:
        raise ShadowCaseStoreError("Observation Segment schema mismatch")
    if value.get("case_id") != opened.get("case_id"):
        raise ShadowCaseStoreError("Observation Segment Case identity mismatch")
    if value.get("shadow_entry_identity") != opened.get("shadow_entry_identity"):
        raise ShadowCaseStoreError("Observation Segment Entry identity mismatch")
    sequence = _nonnegative_int(value.get("segment_sequence"), "segment_sequence")
    if sequence != expected_sequence:
        raise ShadowCaseStoreError("Observation Segment sequence mismatch")
    try:
        require_code_identity(value.get("code_identity"))
    except ValueError as exc:
        raise ShadowCaseStoreError(str(exc)) from exc
    segment_bindings = RuntimeBindings(
        code_identity=str(value.get("code_identity")),
        runtime_identity=_identity(value.get("runtime_identity"), "runtime_identity"),
        radar_policy_identity=_identity(
            value.get("radar_policy_identity"),
            "radar_policy_identity",
        ),
        underwriting_policy_identity=_identity(
            value.get("underwriting_policy_identity"),
            "underwriting_policy_identity",
        ),
        position_policy_identity=_identity(
            value.get("position_policy_identity"),
            "position_policy_identity",
        ),
    )
    for field in (
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        if value.get(field) != opened.get(field):
            raise ShadowCaseStoreError(f"Observation Segment Policy mismatch: {field}")
    product = _product_from_opened(opened)
    if value.get("product_spec_identity") != product.identity:
        raise ShadowCaseStoreError("Observation Segment option product mismatch")
    adoption_boundary = FactBoundary.from_object(
        _boundary(value.get("adoption_fact_boundary"), "adoption_fact_boundary")
    )
    if (
        adoption_boundary.code_identity != segment_bindings.code_identity
        or adoption_boundary.runtime_identity != segment_bindings.runtime_identity
    ):
        raise ShadowCaseStoreError("Observation Segment boundary binding mismatch")
    expected_predecessor = predecessor.get("segment_identity") if predecessor is not None else None
    if value.get("predecessor_segment_identity") != expected_predecessor:
        raise ShadowCaseStoreError("Observation Segment predecessor mismatch")
    expected_identity = _segment_identity(
        case_id=_identity(value.get("case_id"), "case_id"),
        sequence=sequence,
        bindings=segment_bindings,
        predecessor_segment_identity=expected_predecessor,
        adoption_boundary=adoption_boundary,
    )
    if value.get("segment_identity") != expected_identity:
        raise ShadowCaseStoreError("Observation Segment identity mismatch")
    gap_count = _nonnegative_int(value.get("gap_count"), "gap_count")
    if predecessor is None:
        opened_boundary = FactBoundary.from_object(opened.get("opened_fact_boundary"))
        if sequence != 0 or adoption_boundary != opened_boundary:
            raise ShadowCaseStoreError("origin Segment must begin at Entry")
        if any(
            (
                value.get("predecessor_segment_state") is not None,
                value.get("observation_quality") != "CONTINUOUS",
                value.get("gap_reason") is not None,
                gap_count != 0,
                value.get("qualification_eligible") is not True,
            )
        ):
            raise ShadowCaseStoreError("origin Segment continuity projection is invalid")
        _validate_entry_position_baseline(
            value.get("entry_position_baseline"),
            schema_version=schema_version,
            adoption_boundary=adoption_boundary,
        )
    else:
        previous_gap_count = _nonnegative_int(predecessor.get("gap_count"), "gap_count")
        if value.get("predecessor_segment_state") not in {
            "CENSORED_AT_STOP",
            "CENSORED_AT_FAILURE",
            "INCOMPLETE_UNCLEAN_EXIT",
        }:
            raise ShadowCaseStoreError("recovery Segment predecessor state is invalid")
        if any(
            (
                value.get("observation_quality") != "GAPPED",
                value.get("gap_reason") != "HANDOFF_GAP",
                gap_count != previous_gap_count + 1,
                value.get("qualification_eligible") is not False,
                value.get("entry_position_baseline") is not None,
            )
        ):
            raise ShadowCaseStoreError("recovery Segment gap projection is invalid")


def _validate_segment_closed(
    opened: Mapping[str, object],
    segment_opened: Mapping[str, object],
    value: Mapping[str, object],
) -> None:
    _exact_keys(
        value,
        {
            "record_kind",
            "schema_version",
            "case_id",
            "shadow_entry_identity",
            "segment_sequence",
            "segment_identity",
            "code_identity",
            "runtime_identity",
            "radar_policy_identity",
            "underwriting_policy_identity",
            "position_policy_identity",
            "product_spec_identity",
            "closed_fact_boundary",
            "terminal_state",
        },
        "Observation Segment closed",
    )
    if value.get("record_kind") != SEGMENT_CLOSED_KIND:
        raise ShadowCaseStoreError("Observation Segment closed kind is invalid")
    for field in (
        "schema_version",
        "case_id",
        "shadow_entry_identity",
        "segment_sequence",
        "segment_identity",
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
        "product_spec_identity",
    ):
        if value.get(field) != segment_opened.get(field):
            raise ShadowCaseStoreError(f"Observation Segment close binding mismatch: {field}")
    if value.get("case_id") != opened.get("case_id"):
        raise ShadowCaseStoreError("Observation Segment close Case mismatch")
    terminal_state = value.get("terminal_state")
    if terminal_state not in {"CENSORED_AT_STOP", "CENSORED_AT_FAILURE"}:
        raise ShadowCaseStoreError("Observation Segment terminal state is invalid")
    adoption = FactBoundary.from_object(segment_opened.get("adoption_fact_boundary"))
    closed = FactBoundary.from_object(
        _boundary(value.get("closed_fact_boundary"), "closed_fact_boundary")
    )
    if (
        closed.code_identity != adoption.code_identity
        or closed.runtime_identity != adoption.runtime_identity
        or not closed.is_strictly_after(adoption)
    ):
        raise ShadowCaseStoreError("Observation Segment close is not strictly post-adoption")


def _record_segment(
    segments: tuple[ShadowCaseSegmentRead, ...],
    value: Mapping[str, object],
) -> ShadowCaseSegmentRead:
    sequence = _nonnegative_int(value.get("segment_sequence"), "segment_sequence")
    if sequence >= len(segments) or segments[sequence].sequence != sequence:
        raise ShadowCaseStoreError("Case follow-up refers to an unknown Segment")
    segment = segments[sequence]
    if value.get("segment_identity") != segment.opened.get("segment_identity"):
        raise ShadowCaseStoreError("Case follow-up Segment identity mismatch")
    return segment


def _validate_segment_bound_followup(
    opened: Mapping[str, object],
    segment_opened: Mapping[str, object],
    value: Mapping[str, object],
) -> None:
    if value.get("product_spec_identity") != segment_opened.get("product_spec_identity"):
        raise ShadowCaseStoreError("Case follow-up option product mismatch")
    for field in (
        "case_id",
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        expected = segment_opened.get(field) if field != "case_id" else opened.get(field)
        if value.get(field) != expected:
            raise ShadowCaseStoreError(f"Case follow-up Segment binding mismatch: {field}")


def _opened_projected_to_segment(
    opened: Mapping[str, object],
    segment_opened: Mapping[str, object],
) -> dict[str, object]:
    projected = dict(opened)
    for field in (
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        projected[field] = segment_opened.get(field)
    projected["opened_fact_boundary"] = segment_opened.get("adoption_fact_boundary")
    return projected


def _validate_attempt_schedule_identity(
    *,
    scheduled_identity: str,
    shadow_entry_identity: str,
    position_action_identity: str,
    request_id_or_marker: object,
    request_method: object,
    request_params: object,
    schedule_boundary: FactBoundary,
) -> None:
    if request_method != "public/get_order_book":
        raise ShadowCaseStoreError("post-CLOSE attempt request method is invalid")
    if isinstance(request_id_or_marker, list):
        if (
            len(request_id_or_marker) != 2
            or len(set(request_id_or_marker)) != 2
            or any(
                isinstance(member, bool) or not isinstance(member, int) or member < 0
                for member in request_id_or_marker
            )
        ):
            raise ShadowCaseStoreError("component post-CLOSE request ids are invalid")
        params = _sequence(request_params, "request_params")
        if len(params) != 2:
            raise ShadowCaseStoreError("component post-CLOSE request params are invalid")
        canonical_params = tuple(
            _canonical_request_params(member, f"request_params[{index}]")
            for index, member in enumerate(params)
        )
        expected = canonical_identity(
            "ScheduledComponentPostCloseAttemptIdentity",
            shadow_entry_identity,
            position_action_identity,
            request_id_or_marker,
            request_method,
            canonical_params,
            schedule_boundary.as_object(),
        )
    elif isinstance(request_id_or_marker, int) and not isinstance(request_id_or_marker, bool):
        if request_id_or_marker < 0:
            raise ShadowCaseStoreError("post-CLOSE request id is invalid")
        expected = canonical_identity(
            "ScheduledPostCloseQuoteAttemptIdentity",
            shadow_entry_identity,
            position_action_identity,
            request_id_or_marker,
            request_method,
            _canonical_request_params(request_params, "request_params"),
            schedule_boundary.as_object(),
        )
    elif isinstance(request_id_or_marker, str) and request_id_or_marker:
        if request_params is not None:
            raise ShadowCaseStoreError("non-requestable post-CLOSE attempt has request params")
        expected = canonical_identity(
            "ScheduledPostCloseQuoteAttemptIdentity",
            shadow_entry_identity,
            position_action_identity,
            request_id_or_marker,
            request_method,
            None,
            schedule_boundary.as_object(),
        )
    else:
        raise ShadowCaseStoreError("post-CLOSE request id or marker is invalid")
    if scheduled_identity != expected:
        raise ShadowCaseStoreError("post-CLOSE attempt identity mismatch")


def _canonical_request_params(value: object, field: str) -> dict[str, object]:
    params = _mapping(value, field)
    _exact_keys(params, {"instrument_name", "depth"}, field)
    instrument_name = _text(params.get("instrument_name"), f"{field}.instrument_name")
    depth = params.get("depth")
    if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
        raise ShadowCaseStoreError(f"{field}.depth must be a positive integer")
    return {"instrument_name": instrument_name, "depth": depth}


def _recoverable_projection(
    case_id: str,
    case: ShadowCaseRead,
    *,
    product: OptionProductSpec,
    position_fee_rate: Decimal,
) -> RecoverableShadowEntry:
    if not case.segments or case.outcome is not None:
        raise ShadowCaseStoreError("Case is not an active admitted Entry")
    opened = case.opened
    current = case.segments[-1]
    baseline = _mapping(
        case.segments[0].opened.get("entry_position_baseline"),
        "entry_position_baseline",
    )
    entry_identity = _identity(opened.get("shadow_entry_identity"), "shadow_entry_identity")
    effective_first_close = case.first_close
    first_close_decision = (
        _recoverable_first_close(effective_first_close)
        if effective_first_close is not None
        else None
    )
    first_close_state = "LATCHED" if effective_first_close is not None else "NOT_LATCHED"
    attempt_state = (
        "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"
        if effective_first_close is not None
        else "NOT_SCHEDULED"
    )
    predecessor_state_value = current.opened.get("predecessor_segment_state")
    predecessor_state = (
        ShadowCaseSegmentStatus(str(predecessor_state_value))
        if predecessor_state_value is not None
        else current.status
    )
    quality = ObservationQuality(
        _text(current.opened.get("observation_quality"), "observation_quality")
    )
    gap_count = _nonnegative_int(current.opened.get("gap_count"), "gap_count")
    qualification_eligible = current.opened.get("qualification_eligible") is True
    entry_terms, entry_economics = _recoverable_entry_values(
        opened,
        baseline,
        product=product,
        position_fee_rate=position_fee_rate,
    )
    adoption_case_boundary = CaseFactBoundary(
        current.sequence,
        FactBoundary.from_object(
            _boundary(current.opened.get("adoption_fact_boundary"), "adoption_fact_boundary")
        ),
    )
    current_segment_identity = _identity(
        current.opened.get("segment_identity"),
        "segment_identity",
    )
    entry_payload = _recoverable_entry_payload(
        case_id=case_id,
        opened=opened,
        current_segment_identity=current_segment_identity,
        current_segment_sequence=current.sequence,
        observation_quality=quality,
        gap_count=gap_count,
        qualification_eligible=qualification_eligible,
        attempt_state=attempt_state,
        entry_terms=entry_terms,
        entry_economics=entry_economics,
    )
    return RecoverableShadowEntry(
        case_id=case_id,
        shadow_entry_identity=entry_identity,
        origin_outcome_contract_identity=_identity(
            opened.get("shadow_case_contract_identity"),
            "shadow_case_contract_identity",
        ),
        origin_runtime_identity=_identity(
            opened.get("runtime_identity"), "origin runtime_identity"
        ),
        product_spec_identity=product.identity,
        policy_identities=(
            _identity(opened.get("radar_policy_identity"), "radar_policy_identity"),
            _identity(opened.get("underwriting_policy_identity"), "underwriting_policy_identity"),
            _identity(opened.get("position_policy_identity"), "position_policy_identity"),
        ),
        entry_case_boundary=CaseFactBoundary(
            0,
            FactBoundary.from_object(
                _boundary(opened.get("opened_fact_boundary"), "opened_fact_boundary")
            ),
        ),
        adoption_case_boundary=adoption_case_boundary,
        latest_segment_sequence=current.sequence,
        current_segment_identity=current_segment_identity,
        predecessor_segment_state=predecessor_state,
        observation_quality=quality,
        gap_count=gap_count,
        qualification_eligible=qualification_eligible,
        entry_terms=entry_terms,
        entry_economics=entry_economics,
        first_close_decision=first_close_decision,
        first_close_state=first_close_state,
        attempt_state=attempt_state,
        entry_payload=_freeze_mapping(entry_payload),
    )


def _recoverable_source(value: object, field: str) -> SourceFact | None:
    if value is None:
        return None
    source = _mapping(value, field)
    return SourceFact(
        _identity(source.get("source_identity"), f"{field}.source_identity"),
        FactBoundary.from_object(
            _boundary(source.get("receipt_fact_boundary"), f"{field}.receipt_fact_boundary")
        ),
    )


def _recoverable_entry_values(
    opened: Mapping[str, object],
    baseline: Mapping[str, object],
    *,
    product: OptionProductSpec,
    position_fee_rate: Decimal,
) -> tuple[EntryTerms, EntryEconomics]:
    schema_version = _record_schema_version(opened)
    structure = _mapping(opened.get("structure"), "structure")
    economics = _mapping(opened.get("entry_economics"), "entry_economics")

    def economic(product_key: str) -> Decimal:
        return _decimal(economics.get(product_key), product_key)

    leg_identities = _sequence(
        structure.get("canonical_leg_identities"),
        "canonical_leg_identities",
    )
    if len(leg_identities) != 2:
        raise ShadowCaseStoreError("recovered Entry requires exactly two canonical legs")
    entry_legs = _runtime_component_legs(
        structure.get("entry_component_legs"),
        schema_version=schema_version,
    )
    strike_suffix = "usd_per_btc"
    index_key = "entry_index_usd_per_btc"
    entry_index_source = _recoverable_source(
        baseline.get("entry_index_source_ref"),
        "entry_index_source_ref",
    )
    entry_index = (
        _decimal(baseline.get(index_key), index_key)
        if baseline.get(index_key) is not None and entry_index_source is not None
        else None
    )
    entry_mark_source = _recoverable_source(
        baseline.get("entry_short_leg_mark_iv_source_ref"),
        "entry_short_leg_mark_iv_source_ref",
    )
    entry_mark = (
        _decimal(
            baseline.get("entry_short_leg_mark_iv_fraction"),
            "entry_short_leg_mark_iv_fraction",
        )
        if baseline.get("entry_short_leg_mark_iv_fraction") is not None
        and entry_mark_source is not None
        else None
    )
    gross = economic("gross_entry_credit_usd")
    fee = economic("entry_fee_reserve_usd")
    net = economic("net_entry_credit_usd")
    width = economic("width_usd_per_btc")
    native = _mapping(opened.get("native_entry_economics"), "native_entry_economics")
    native_gross = _decimal(
        native.get("native_gross_entry_credit"),
        "native_gross_entry_credit",
    )
    native_fee = _decimal(
        native.get("native_entry_fee_reserve"),
        "native_entry_fee_reserve",
    )
    native_net = _decimal(
        native.get("native_net_entry_credit"),
        "native_net_entry_credit",
    )
    valuation_index = _decimal(
        native.get("entry_valuation_index_price"),
        "entry_valuation_index_price",
    )
    quantity = _decimal(structure.get("full_quantity_btc"), "full_quantity_btc")
    terms = EntryTerms(
        short_leg_identity=_identity(leg_identities[0], "short_leg_identity"),
        long_leg_identity=_identity(leg_identities[1], "long_leg_identity"),
        short_leg_instrument_name=_text(
            structure.get("short_leg_instrument_name"),
            "short_leg_instrument_name",
        ),
        long_leg_instrument_name=_text(
            structure.get("long_leg_instrument_name"),
            "long_leg_instrument_name",
        ),
        canonical_combo_identity=None,
        combo_instrument_name=None,
        option_type=_text(structure.get("option_type"), "option_type"),
        short_strike_usdc_per_btc=_decimal(
            structure.get(f"short_strike_{strike_suffix}"),
            f"short_strike_{strike_suffix}",
        ),
        long_strike_usdc_per_btc=_decimal(
            structure.get(f"long_strike_{strike_suffix}"),
            f"long_strike_{strike_suffix}",
        ),
        expiry_ms=_nonnegative_int(structure.get("expiry_ms"), "expiry_ms"),
        target_quantity_btc=quantity,
        entry_direction=_text(structure.get("entry_direction"), "entry_direction"),
        index_usdc_per_btc=entry_index,
        index_source=entry_index_source,
        short_mark_iv_fraction=entry_mark,
        ticker_source=entry_mark_source,
        short_leg_taker_commission_fraction=position_fee_rate,
        long_leg_taker_commission_fraction=position_fee_rate,
        execution_model=_text(structure.get("execution_model"), "execution_model"),
        product_spec_identity=product.identity if entry_legs else None,
        product_name=product.name.value if entry_legs else None,
        native_premium_currency=product.native_premium_currency if entry_legs else None,
        settlement_currency=product.settlement_currency if entry_legs else None,
        valuation_currency=product.valuation_currency if entry_legs else None,
        price_index=product.price_index if entry_legs else None,
        native_gross_entry_credit=native_gross if entry_legs else None,
        native_entry_fee_reserve=native_fee if entry_legs else None,
        native_net_entry_credit=native_net if entry_legs else None,
        entry_valuation_index_price=valuation_index if entry_legs else None,
        width_usdc_per_btc=width,
        entry_component_legs=entry_legs,
    )
    return terms, EntryEconomics(
        full_quantity_btc=quantity,
        required_side_total_quote_usdc=Decimal(0),
        gross_entry_credit_usdc=gross,
        entry_fee_reserve_usdc=fee,
        net_entry_credit_usdc=net,
        width_usdc_per_btc=width,
        payoff_cap_usdc=economic("contractual_payoff_cap_usd"),
        contractual_payoff_max_loss_ex_fees_usdc=economic(
            "entry_boundary_valued_payoff_loss_ex_fees_usd"
        ),
        entry_fee_reserved_payoff_loss_usdc=economic(
            "entry_boundary_valued_payoff_loss_including_entry_fee_usd"
        ),
        future_cost_reserve_usdc=economic("future_cost_reserve_usd"),
        underwriting_reserved_loss_usdc=economic("underwriting_reserved_loss_usd"),
    )


def _runtime_component_legs(
    value: object,
    *,
    schema_version: int,
) -> tuple[Mapping[str, object], ...]:
    legs = _sequence(value, "entry_component_legs")
    inverse_fields = {
        product_key: legacy for legacy, product_key in _V5_COMPONENT_LEG_FIELDS.items()
    }
    projected: list[Mapping[str, object]] = []
    for raw in legs:
        leg = _mapping(raw, "entry component leg")
        runtime_leg = {inverse_fields.get(key, key): member for key, member in leg.items()}
        for field in ("raw_consumed_levels", "stressed_consumed_levels"):
            runtime_leg[field] = [
                {
                    ("price_usdc_per_btc" if key == "price_usd_per_btc" else key): member
                    for key, member in _mapping(level, f"{field} level").items()
                }
                for level in _sequence(runtime_leg.get(field), field)
            ]
        projected.append(_freeze_mapping(runtime_leg))
    return tuple(projected)


def _recoverable_first_close(value: Mapping[str, object]) -> PositionDecision:
    action_identity = _identity(value.get("position_action_identity"), "position_action_identity")
    reasons = _string_sequence(
        value.get("ordered_latched_close_reasons"),
        "ordered_latched_close_reasons",
    )
    PositionDecisionRecoverySeed(
        first_latched_close_action_identity=action_identity,
        ordered_latched_close_reason_vector=reasons,
    )
    primary = _text(value.get("primary_close_reason"), "primary_close_reason")
    if primary != reasons[0]:
        raise ShadowCaseStoreError("recovered first CLOSE primary reason mismatch")
    truths = _string_sequence(value.get("predicate_truth_vector"), "predicate_truth_vector")
    if len(truths) != len(POSITION_CLOSE_REASONS):
        raise ShadowCaseStoreError("recovered first CLOSE predicate vector is incomplete")
    return PositionDecision(
        position_evaluation_identity=action_identity,
        position_action_identity=action_identity,
        serialized_action="CLOSE",
        ordered_predicate_truth_vector=truths,
        ordered_latched_close_reason_vector=reasons,
        primary_close_reason=primary,
        secondary_close_reasons=reasons[1:],
        first_latched_close_action_identity=action_identity,
        action_case_boundary=CaseFactBoundary(
            _nonnegative_int(value.get("segment_sequence"), "first CLOSE segment_sequence"),
            FactBoundary.from_object(
                _boundary(value.get("first_close_fact_boundary"), "first_close_fact_boundary")
            ),
        ),
    )


def _recoverable_entry_payload(
    *,
    case_id: str,
    opened: Mapping[str, object],
    current_segment_identity: str,
    current_segment_sequence: int,
    observation_quality: ObservationQuality,
    gap_count: int,
    qualification_eligible: bool,
    attempt_state: str,
    entry_terms: EntryTerms,
    entry_economics: EntryEconomics,
) -> Mapping[str, object]:
    structure = _mapping(opened.get("structure"), "structure")
    radar = _mapping(opened.get("radar"), "radar")
    return {
        "shadow_entry_identity": opened.get("shadow_entry_identity"),
        "candidate_identity": opened.get("candidate_identity"),
        "enrollment_kind": "ADMITTED_SHADOW_TRADE",
        "entry_fact_boundary": opened.get("opened_fact_boundary"),
        "selection_score_packet": opened.get("selection_score_packet"),
        "entry_refresh_score_packet": opened.get("entry_refresh_score_packet"),
        "active_episode_identity": radar.get("active_episode_identity"),
        "radar_research_review_identity": radar.get("radar_research_review_identity"),
        "radar_activation_causal_seq": radar.get("radar_activation_causal_seq"),
        "radar_scope_identity": radar.get("radar_scope_identity"),
        "component_state": radar.get("component_state"),
        "atomic_state_diagnostic": radar.get("atomic_state_diagnostic"),
        "execution_model": structure.get("execution_model"),
        "canonical_leg_identities": structure.get("canonical_leg_identities"),
        "short_leg_instrument_name": entry_terms.short_leg_instrument_name,
        "long_leg_instrument_name": entry_terms.long_leg_instrument_name,
        "expiry_ms": entry_terms.expiry_ms,
        "option_type": entry_terms.option_type,
        "short_strike_usdc_per_btc": entry_terms.short_strike_usdc_per_btc,
        "long_strike_usdc_per_btc": entry_terms.long_strike_usdc_per_btc,
        "entry_direction": entry_terms.entry_direction,
        "full_quantity_btc": entry_terms.target_quantity_btc,
        "entry_component_pair_identity": structure.get("entry_component_pair_identity"),
        "entry_component_pair_timing": structure.get("entry_component_pair_timing"),
        "entry_component_pair_limits": structure.get("entry_component_pair_limits"),
        "entry_component_quote_source_refs": structure.get("entry_component_quote_source_refs"),
        "entry_component_legs": list(entry_terms.entry_component_legs),
        "product_spec_identity": entry_terms.product_spec_identity,
        "product_name": entry_terms.product_name,
        "native_premium_currency": entry_terms.native_premium_currency,
        "settlement_currency": entry_terms.settlement_currency,
        "valuation_currency": entry_terms.valuation_currency,
        "price_index": entry_terms.price_index,
        "native_gross_entry_credit": entry_terms.native_gross_entry_credit,
        "native_entry_fee_reserve": entry_terms.native_entry_fee_reserve,
        "native_net_entry_credit": entry_terms.native_net_entry_credit,
        "entry_valuation_index_price": entry_terms.entry_valuation_index_price,
        "gross_entry_credit_usdc": entry_economics.gross_entry_credit_usdc,
        "entry_fee_reserve_usdc": entry_economics.entry_fee_reserve_usdc,
        "net_entry_credit_usdc": entry_economics.net_entry_credit_usdc,
        "width_usdc_per_btc": entry_economics.width_usdc_per_btc,
        "payoff_cap_usdc": entry_economics.payoff_cap_usdc,
        "contractual_payoff_max_loss_ex_fees_usdc": (
            entry_economics.contractual_payoff_max_loss_ex_fees_usdc
        ),
        "entry_fee_reserved_payoff_loss_usdc": (
            entry_economics.entry_fee_reserved_payoff_loss_usdc
        ),
        "future_cost_reserve_usdc": entry_economics.future_cost_reserve_usdc,
        "underwriting_reserved_loss_usdc": entry_economics.underwriting_reserved_loss_usdc,
        "non_claims": opened.get("non_claims"),
        "origin_case_id": case_id,
        "origin_runtime_identity": opened.get("runtime_identity"),
        "current_segment_identity": current_segment_identity,
        "current_segment_sequence": current_segment_sequence,
        "observation_quality": observation_quality.value,
        "gap_count": gap_count,
        "qualification_eligible": qualification_eligible,
        "tracking_state": "ACTIVE",
        "post_close_attempt_state": attempt_state,
    }


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(member: object) -> object:
        if isinstance(member, Mapping):
            return MappingProxyType({key: freeze(item) for key, item in member.items()})
        if isinstance(member, list | tuple):
            return tuple(freeze(item) for item in member)
        return member

    frozen = freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _validate_opened(
    value: Mapping[str, object],
    *,
    expected_case_id: str,
    bindings: RuntimeBindings,
    policies: PolicyChain,
) -> None:
    schema_version = _record_schema_version(value)
    product = product_for_identity(policies.radar.product_spec_identity)
    if schema_version != _schema_version_for_product(product):
        raise ShadowCaseStoreError("opened record schema does not match its option product")
    required = {
        "record_kind",
        "schema_version",
        "case_id",
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
        "shadow_case_contract_identity",
        "opened_fact_boundary",
        "enrollment_kind",
        "enrollment_identity",
        "shadow_entry_identity",
        "candidate_identity",
        "underwriting_action_identity",
        "decision_fact_boundary",
        "selected_underwriting_decision",
        "selection_score_packet",
        "entry_refresh_score_packet",
        "structure",
        "radar",
        "underwriting",
        "entry_economics",
        "non_claims",
    }
    required.update({"product", "native_entry_economics"})
    if set(value) != required:
        raise ShadowCaseStoreError("opened record has an invalid key set")
    if value.get("record_kind") != OPENED_KIND or value.get("schema_version") != schema_version:
        raise ShadowCaseStoreError("opened record kind/schema is invalid")
    if value.get("case_id") != expected_case_id:
        raise ShadowCaseStoreError("opened record Case identity mismatch")
    try:
        require_code_identity(value.get("code_identity"))
    except ValueError as exc:
        raise ShadowCaseStoreError(str(exc)) from exc
    expected_bindings = {
        "code_identity": bindings.code_identity,
        "runtime_identity": bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
    }
    for field, expected in expected_bindings.items():
        if value.get(field) != expected:
            raise ShadowCaseStoreError(f"opened record binding mismatch: {field}")
    if value.get("shadow_case_contract_identity") != bindings.shadow_case_contract_identity:
        raise ShadowCaseStoreError("opened record binding mismatch: shadow_case_contract_identity")
    for field in (
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
        "shadow_case_contract_identity",
    ):
        _identity(value.get(field), field)
    enrollment_kind = value.get("enrollment_kind")
    if enrollment_kind not in {
        "ADMITTED_SHADOW_TRADE",
        "SELECTED_UNDERWRITING_DECISION_CONTROL",
        "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
    }:
        raise ShadowCaseStoreError("opened enrollment_kind is invalid")
    enrollment_identity = _identity(
        value.get("enrollment_identity"),
        "enrollment_identity",
    )
    if enrollment_kind == "ADMITTED_SHADOW_TRADE":
        if value.get("shadow_entry_identity") != enrollment_identity:
            raise ShadowCaseStoreError("trade enrollment identity mismatch")
        _identity(value.get("candidate_identity"), "candidate_identity")
        _identity(value.get("underwriting_action_identity"), "underwriting_action_identity")
    elif any(
        value.get(field) is not None
        for field in (
            "shadow_entry_identity",
            "candidate_identity",
            "underwriting_action_identity",
        )
    ):
        raise ShadowCaseStoreError("decision control masquerades as a Candidate or Shadow Entry")
    opened_boundary = FactBoundary.from_object(
        _boundary(value.get("opened_fact_boundary"), "opened_fact_boundary")
    )
    if (
        opened_boundary.code_identity != bindings.code_identity
        or opened_boundary.runtime_identity != bindings.runtime_identity
    ):
        raise ShadowCaseStoreError("opened FactBoundary binding mismatch")
    recomputed_case_id = _shadow_case_identity(
        bindings=bindings,
        enrollment_identity=enrollment_identity,
        opened_boundary=opened_boundary.as_object(),
        schema_version=schema_version,
        product=product,
    )
    if recomputed_case_id != expected_case_id:
        raise ShadowCaseStoreError("opened record Case identity mismatch")
    structure = _mapping(value.get("structure"), "structure")
    _exact_keys(
        structure,
        _versioned_keys(
            {
                "execution_model",
                "canonical_leg_identities",
                "short_leg_instrument_name",
                "long_leg_instrument_name",
                "expiry_ms",
                "option_type",
                "short_strike_usdc_per_btc",
                "long_strike_usdc_per_btc",
                "entry_direction",
                "full_quantity_btc",
                "entry_component_pair_identity",
                "entry_component_pair_timing",
                "entry_component_pair_limits",
                "entry_component_quote_source_refs",
                "entry_component_legs",
            },
            schema_version=schema_version,
            mapping=_V5_STRUCTURE_FIELDS,
        ),
        "opened structure",
    )
    if structure.get("execution_model") != "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL":
        raise ShadowCaseStoreError("opened execution_model is invalid")
    leg_identities = _sequence(
        structure.get("canonical_leg_identities"), "canonical_leg_identities"
    )
    if len(leg_identities) != 2:
        raise ShadowCaseStoreError("opened structure must contain exactly two leg identities")
    canonical_leg_identities = tuple(
        _identity(identity, f"canonical_leg_identities[{index}]")
        for index, identity in enumerate(leg_identities)
    )
    short_instrument_name = _text(
        structure.get("short_leg_instrument_name"),
        "short_leg_instrument_name",
    )
    long_instrument_name = _text(
        structure.get("long_leg_instrument_name"),
        "long_leg_instrument_name",
    )
    if not product.matches_instrument_name(
        short_instrument_name
    ) or not product.matches_instrument_name(long_instrument_name):
        raise ShadowCaseStoreError("opened component instrument does not match its option product")
    expiry_ms = structure.get("expiry_ms")
    if isinstance(expiry_ms, bool) or not isinstance(expiry_ms, int) or expiry_ms <= 0:
        raise ShadowCaseStoreError("expiry_ms must be a positive integer")
    option_type = structure.get("option_type")
    if option_type not in {"call", "put"}:
        raise ShadowCaseStoreError("option_type is invalid")
    if structure.get("entry_direction") != "SELL":
        raise ShadowCaseStoreError("entry_direction is invalid")
    short_strike = _decimal(
        _versioned_get(
            structure,
            schema_version=schema_version,
            legacy_key="short_strike_usdc_per_btc",
            mapping=_V5_STRUCTURE_FIELDS,
        ),
        "short_strike_usdc_per_btc",
    )
    long_strike = _decimal(
        _versioned_get(
            structure,
            schema_version=schema_version,
            legacy_key="long_strike_usdc_per_btc",
            mapping=_V5_STRUCTURE_FIELDS,
        ),
        "long_strike_usdc_per_btc",
    )
    if (option_type == "call" and long_strike <= short_strike) or (
        option_type == "put" and long_strike >= short_strike
    ):
        raise ShadowCaseStoreError("opened component strikes are not a protective vertical")
    _validate_product_instrument_semantics(
        short_instrument_name,
        product=product,
        expiry_ms=expiry_ms,
        strike=short_strike,
        option_type=option_type,
    )
    _validate_product_instrument_semantics(
        long_instrument_name,
        product=product,
        expiry_ms=expiry_ms,
        strike=long_strike,
        option_type=option_type,
    )
    quantity = _decimal(structure.get("full_quantity_btc"), "full_quantity_btc")
    if quantity <= 0:
        raise ShadowCaseStoreError("opened quantity must be positive")
    entry_component_pair_identity = _identity(
        structure.get("entry_component_pair_identity"),
        "entry_component_pair_identity",
    )
    component_source_boundaries = _validate_component_source_refs(
        structure.get("entry_component_quote_source_refs"),
        owner_boundary=opened_boundary,
        field="entry_component_quote_source_refs",
        require_pair_timing_inputs=True,
        expected_leg_identities=(canonical_leg_identities[0], canonical_leg_identities[1]),
        expected_instrument_names=(short_instrument_name, long_instrument_name),
    )
    _validate_component_pair_timing(
        structure.get("entry_component_pair_timing"),
        structure.get("entry_component_pair_limits"),
        source_boundaries=component_source_boundaries,
        pair_identity=entry_component_pair_identity,
        owner_boundary=opened_boundary,
        policies=policies,
    )
    entry_component = _validate_component_legs(
        structure.get("entry_component_legs"),
        quantity=quantity,
        short_name=short_instrument_name,
        long_name=long_instrument_name,
        expected_actions=("SELL", "BUY"),
        field="entry_component_legs",
        schema_version=schema_version,
        product=product,
        fee_rate_index_fraction=policies.underwriting.fee_rate_index_fraction,
    )
    radar = _mapping(value.get("radar"), "radar")
    _exact_keys(
        radar,
        {
            "active_episode_identity",
            "radar_research_review_identity",
            "radar_activation_causal_seq",
            "radar_scope_identity",
            "component_state",
            "atomic_state_diagnostic",
        },
        "opened radar",
    )
    active_episode_identity = radar.get("active_episode_identity")
    research_review_identity = radar.get("radar_research_review_identity")
    if (active_episode_identity is None) == (research_review_identity is None):
        raise ShadowCaseStoreError("opened Radar enrollment requires exactly one anchor")
    if active_episode_identity is not None:
        _identity(active_episode_identity, "active_episode_identity")
    if research_review_identity is not None:
        _identity(research_review_identity, "radar_research_review_identity")
    activation_causal_seq = radar.get("radar_activation_causal_seq")
    if (
        isinstance(activation_causal_seq, bool)
        or not isinstance(activation_causal_seq, int)
        or activation_causal_seq < 0
        or activation_causal_seq > opened_boundary.causal_seq
    ):
        raise ShadowCaseStoreError("opened Radar activation causal sequence is invalid")
    if enrollment_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL":
        if active_episode_identity is not None:
            raise ShadowCaseStoreError("score-band Control cannot claim a HIGH Episode")
    elif active_episode_identity is None:
        raise ShadowCaseStoreError("canonical enrollment lacks its HIGH Episode")
    _identity(radar.get("radar_scope_identity"), "radar_scope_identity")
    if radar.get("component_state") != "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE":
        raise ShadowCaseStoreError("opened component_state is invalid")
    _text(radar.get("atomic_state_diagnostic"), "atomic_state_diagnostic")
    selection_score_packet, _entry_refresh_score_packet = _validate_case_score_packets(
        selection_value=value.get("selection_score_packet"),
        refresh_value=value.get("entry_refresh_score_packet"),
        opened_boundary=opened_boundary,
        enrollment_kind=enrollment_kind,
        active_episode_identity=active_episode_identity,
        research_review_identity=research_review_identity,
        activation_causal_seq=activation_causal_seq,
        short_instrument_name=short_instrument_name,
        expiry_ms=expiry_ms,
        option_type=option_type,
        bindings=bindings,
        radar_policy=policies.radar,
    )

    underwriting = _mapping(value.get("underwriting"), "underwriting")
    _exact_keys(
        underwriting,
        _versioned_keys(
            {
                "action_identity",
                "consumed_economic_fact_fingerprint",
                "action",
                "failed_predicates",
                "predicate_margin_vector",
                "protective_leg_selection_rule_identity",
                "candidate_protective_leg_count",
                "minimum_net_entry_credit_usdc",
                "minimum_net_credit_to_payoff_cap_fraction",
                "maximum_underwriting_reserved_loss_usdc",
                "maximum_entry_consumed_level_count",
            },
            schema_version=schema_version,
            mapping=_V5_UNDERWRITING_FIELDS,
        ),
        "opened underwriting",
    )
    entry_underwriting_action_identity = _identity(
        underwriting.get("action_identity"),
        "entry underwriting action_identity",
    )
    entry_underwriting_economic_fingerprint = _identity(
        underwriting.get("consumed_economic_fact_fingerprint"),
        "entry underwriting consumed_economic_fact_fingerprint",
    )
    underwriting_action = underwriting.get("action")
    if underwriting_action not in {"CANDIDATE", "WATCH", "ABSTAIN"}:
        raise ShadowCaseStoreError("opened Underwriting action is invalid")
    if enrollment_kind == "ADMITTED_SHADOW_TRADE" and underwriting_action != "CANDIDATE":
        raise ShadowCaseStoreError("admitted trade must remain a Candidate at open")
    failed_predicates = _string_sequence(
        underwriting.get("failed_predicates"),
        "failed_predicates",
    )
    predicate_margins = _validate_predicate_margin_vector(
        underwriting.get("predicate_margin_vector"),
        "predicate_margin_vector",
        valuation_unit=product.valuation_currency,
    )
    _validate_margin_decision(
        action=underwriting_action,
        failed_predicates=failed_predicates,
        margins=predicate_margins,
        field="opened underwriting",
    )
    if (
        underwriting.get("protective_leg_selection_rule_identity")
        != UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY
    ):
        raise ShadowCaseStoreError("opened protective-leg selection rule identity mismatch")
    candidate_protective_leg_count = underwriting.get("candidate_protective_leg_count")
    if (
        isinstance(candidate_protective_leg_count, bool)
        or not isinstance(candidate_protective_leg_count, int)
        or candidate_protective_leg_count < 0
    ):
        raise ShadowCaseStoreError("opened Candidate protective-leg count is invalid")
    expected_thresholds = {
        "minimum_net_entry_credit_usdc": policies.underwriting.minimum_net_entry_credit_usdc,
        "minimum_net_credit_to_payoff_cap_fraction": (
            policies.underwriting.minimum_net_credit_to_payoff_cap_fraction
        ),
        "maximum_underwriting_reserved_loss_usdc": (
            policies.underwriting.maximum_underwriting_reserved_loss_usdc
        ),
    }
    for field, expected_threshold in expected_thresholds.items():
        raw_threshold = _versioned_get(
            underwriting,
            schema_version=schema_version,
            legacy_key=field,
            mapping=_V5_UNDERWRITING_FIELDS,
        )
        if _decimal(raw_threshold, field) != expected_threshold:
            raise ShadowCaseStoreError(f"opened underwriting Policy threshold mismatch: {field}")
    maximum_levels = underwriting.get("maximum_entry_consumed_level_count")
    if (
        isinstance(maximum_levels, bool)
        or not isinstance(maximum_levels, int)
        or maximum_levels <= 0
    ):
        raise ShadowCaseStoreError("maximum_entry_consumed_level_count must be positive")
    if maximum_levels != policies.underwriting.maximum_entry_consumed_level_count:
        raise ShadowCaseStoreError("opened underwriting level limit Policy mismatch")

    economics = _mapping(value.get("entry_economics"), "entry_economics")
    _exact_keys(
        economics,
        _versioned_keys(
            {
                "gross_entry_credit_usdc",
                "entry_fee_reserve_usdc",
                "net_entry_credit_usdc",
                "width_usdc_per_btc",
                "payoff_cap_usdc",
                "contractual_payoff_max_loss_ex_fees_usdc",
                "entry_fee_reserved_payoff_loss_usdc",
                "future_cost_reserve_usdc",
                "underwriting_reserved_loss_usdc",
            },
            schema_version=schema_version,
            mapping=_V5_ENTRY_ECONOMICS_FIELDS,
        ),
        "entry_economics",
    )

    def entry_field(key: str) -> object:
        return _versioned_get(
            economics,
            schema_version=schema_version,
            legacy_key=key,
            mapping=_V5_ENTRY_ECONOMICS_FIELDS,
        )

    gross_entry = _decimal(entry_field("gross_entry_credit_usdc"), "gross entry credit")
    if gross_entry <= 0:
        raise ShadowCaseStoreError("opened gross entry credit must be positive")
    entry_fee = _decimal(entry_field("entry_fee_reserve_usdc"), "entry fee reserve")
    net_entry = _decimal(entry_field("net_entry_credit_usdc"), "net entry credit")
    if net_entry != gross_entry - entry_fee:
        raise ShadowCaseStoreError("opened entry economics do not conserve")
    if (
        gross_entry != entry_component.valuation_gross_cashflow
        or entry_fee != entry_component.valuation_total_fee
    ):
        raise ShadowCaseStoreError("opened entry economics do not match component legs")
    width = _decimal(entry_field("width_usdc_per_btc"), "width_usdc_per_btc")
    payoff_cap = _decimal(entry_field("payoff_cap_usdc"), "payoff_cap_usdc")
    contractual = _decimal(
        entry_field("contractual_payoff_max_loss_ex_fees_usdc"),
        "contractual_payoff_max_loss_ex_fees_usdc",
    )
    fee_reserved = _decimal(
        entry_field("entry_fee_reserved_payoff_loss_usdc"),
        "entry_fee_reserved_payoff_loss_usdc",
    )
    if width <= 0 or payoff_cap != width * quantity:
        raise ShadowCaseStoreError("opened vertical width/payoff cap do not conserve")
    if contractual != max(Decimal(0), payoff_cap - gross_entry):
        raise ShadowCaseStoreError("opened contractual maximum loss does not conserve")
    if fee_reserved != max(Decimal(0), payoff_cap - net_entry):
        raise ShadowCaseStoreError("opened fee-reserved maximum loss does not conserve")
    future_cost_reserve = _decimal(
        entry_field("future_cost_reserve_usdc"),
        "future_cost_reserve_usdc",
    )
    underwriting_reserved_loss = _decimal(
        entry_field("underwriting_reserved_loss_usdc"),
        "underwriting_reserved_loss_usdc",
    )
    if future_cost_reserve != policies.underwriting.future_cost_reserve_usdc:
        raise ShadowCaseStoreError("opened future cost reserve does not match Policy")
    if underwriting_reserved_loss != fee_reserved + future_cost_reserve:
        raise ShadowCaseStoreError("opened Underwriting reserved loss does not conserve")
    expected_margins = UnderwritingThresholdMargins(
        positive_net_credit_usdc=net_entry,
        credit_above_future_cost_reserve_usdc=net_entry - future_cost_reserve,
        reserved_loss_limit_headroom_usdc=(
            policies.underwriting.maximum_underwriting_reserved_loss_usdc
            - underwriting_reserved_loss
        ),
        minimum_net_credit_headroom_usdc=(
            net_entry - policies.underwriting.minimum_net_entry_credit_usdc
        ),
        minimum_credit_ratio_headroom=(
            net_entry / payoff_cap - policies.underwriting.minimum_net_credit_to_payoff_cap_fraction
        ),
        entry_consumed_level_headroom=(
            policies.underwriting.maximum_entry_consumed_level_count
            - entry_component.consumed_level_count
        ),
    )
    if predicate_margins != expected_margins:
        raise ShadowCaseStoreError("opened predicate margins do not match entry economics")
    _validate_product_aware_entry(
        value,
        product=product,
        component=entry_component,
        gross_entry=gross_entry,
        entry_fee=entry_fee,
        net_entry=net_entry,
    )
    non_claims = _string_sequence(value.get("non_claims"), "non_claims")
    component_non_claims = (
        "NOT_AN_ORDER",
        "NOT_A_FILL",
        "NOT_AN_ATOMIC_QUOTE",
        "NO_LIQUIDITY_RESERVATION",
        "ATOMIC_EXECUTABILITY_UNPROVEN",
    )
    expected_non_claims = (
        component_non_claims
        if enrollment_kind == "ADMITTED_SHADOW_TRADE"
        else (
            *component_non_claims,
            "NOT_A_CANDIDATE_ACTIVATION",
            "NOT_A_SHADOW_ENTRY",
            "NOT_AN_ADMITTED_TRADE",
            "NO_CAPITAL_EXPOSURE",
        )
    )
    if non_claims != expected_non_claims:
        raise ShadowCaseStoreError("opened component non_claims are invalid")

    selected_decision = value.get("selected_underwriting_decision")
    selected_decision_identity: str | None = None
    if selected_decision is None:
        if enrollment_kind in {
            "SELECTED_UNDERWRITING_DECISION_CONTROL",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL",
        }:
            raise ShadowCaseStoreError("decision control lacks its selected-decision witness")
    else:
        selected_decision_mapping = _mapping(
            selected_decision,
            "selected_underwriting_decision",
        )
        _validate_selected_decision(
            selected_decision_mapping,
            opened_boundary=opened_boundary,
            enrollment_kind=enrollment_kind,
            active_episode_identity=active_episode_identity,
            research_review_identity=research_review_identity,
            activation_causal_seq=activation_causal_seq,
            sampling_metadata=selection_score_packet.sampling_metadata,
            bindings=bindings,
            product=product,
            protective_leg_selection_rule_identity=_identity(
                underwriting.get("protective_leg_selection_rule_identity"),
                "protective_leg_selection_rule_identity",
            ),
            candidate_protective_leg_count=candidate_protective_leg_count,
        )
        selected_decision_identity = _identity(
            selected_decision_mapping.get("selected_underwriting_decision_identity"),
            "selected_underwriting_decision_identity",
        )
        refreshed_projection = {
            "refreshed_underwriting_action_identity": underwriting.get("action_identity"),
            "refreshed_consumed_economic_fact_fingerprint": underwriting.get(
                "consumed_economic_fact_fingerprint"
            ),
            "refreshed_economic_action": underwriting.get("action"),
            "refreshed_failed_predicates": underwriting.get("failed_predicates"),
            "refreshed_predicate_margin_vector": underwriting.get("predicate_margin_vector"),
        }
        if any(
            selected_decision_mapping.get(field) != expected
            for field, expected in refreshed_projection.items()
        ):
            raise ShadowCaseStoreError(
                "selected decision refreshed Underwriting projection is inconsistent"
            )
    if selection_score_packet.sampling_metadata is None:
        raise ShadowCaseStoreError("Case selection packet lacks sampling metadata")
    if selected_decision_identity is None:
        if enrollment_kind != "ADMITTED_SHADOW_TRADE":
            raise ShadowCaseStoreError("Control Case lacks its selected decision")
        if (
            selection_score_packet.sampling_metadata.kind is not SamplingKind.CANONICAL_HIGH
            or selection_score_packet.sampling_metadata.designation_identity
            != value.get("candidate_identity")
        ):
            raise ShadowCaseStoreError("ordinary Candidate sampling designation mismatch")

    decision_boundary = FactBoundary.from_object(
        _boundary(value.get("decision_fact_boundary"), "decision_fact_boundary")
    )
    if (
        decision_boundary.code_identity != bindings.code_identity
        or decision_boundary.runtime_identity != bindings.runtime_identity
        or decision_boundary != opened_boundary
    ):
        raise ShadowCaseStoreError("decision FactBoundary binding/order mismatch")
    entry_underwriting_owner_identity = (
        selected_decision_identity
        if selected_decision_identity is not None
        else _identity(value.get("candidate_identity"), "candidate_identity")
    )
    expected_entry_underwriting_action_identity = canonical_identity(
        "CaseOpenRefreshedUnderwritingActionIdentity",
        entry_underwriting_owner_identity,
        entry_underwriting_economic_fingerprint,
        underwriting_action,
        underwriting.get("protective_leg_selection_rule_identity"),
        candidate_protective_leg_count,
        decision_boundary.as_object(),
    )
    if entry_underwriting_action_identity != expected_entry_underwriting_action_identity:
        raise ShadowCaseStoreError("entry Underwriting action identity mismatch")


def _validate_followup(
    opened: Mapping[str, object],
    value: Mapping[str, object],
    *,
    expected_kind: str,
    policies: PolicyChain,
) -> None:
    schema_version = _record_schema_version(opened)
    expected_keys = (
        {
            "record_kind",
            "schema_version",
            "case_id",
            "code_identity",
            "runtime_identity",
            "radar_policy_identity",
            "underwriting_policy_identity",
            "position_policy_identity",
            "first_close_fact_boundary",
            "position_action_identity",
            "primary_close_reason",
            "ordered_latched_close_reasons",
            "predicate_truth_vector",
        }
        if expected_kind == FIRST_CLOSE_KIND
        else {
            "record_kind",
            "schema_version",
            "case_id",
            "code_identity",
            "runtime_identity",
            "radar_policy_identity",
            "underwriting_policy_identity",
            "position_policy_identity",
            "outcome_fact_boundary",
            "shadow_outcome_identity",
            "terminal_state",
            "selected_exit_identity",
            "first_latched_close_action_identity",
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "gross_pnl_usdc",
            "total_public_fee_reserve_usdc",
            "net_pnl_after_public_standard_fee_reserve_usdc",
            "net_loss_usdc",
            "economic_availability",
            "close_component_pair_identity",
            "close_component_quote_source_refs",
            "close_component_legs",
            "censor_mask",
            "non_claims",
        }
    )
    if expected_kind == OUTCOME_KIND:
        expected_keys = _versioned_keys(
            expected_keys,
            schema_version=schema_version,
            mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
        )
    if expected_kind == OUTCOME_KIND:
        expected_keys.add("native_outcome_economics")
    _exact_keys(value, expected_keys, "Case follow-up")
    if value.get("record_kind") != expected_kind or value.get("schema_version") != schema_version:
        raise ShadowCaseStoreError("Case follow-up kind/schema is invalid")
    if value.get("case_id") != opened.get("case_id"):
        raise ShadowCaseStoreError("Case follow-up identity mismatch")
    for field in (
        "code_identity",
        "runtime_identity",
        "radar_policy_identity",
        "underwriting_policy_identity",
        "position_policy_identity",
    ):
        if value.get(field) != opened.get(field):
            raise ShadowCaseStoreError(f"Case follow-up {field} mismatch")
    opened_boundary = FactBoundary.from_object(opened.get("opened_fact_boundary"))
    field = (
        "first_close_fact_boundary"
        if expected_kind == FIRST_CLOSE_KIND
        else "outcome_fact_boundary"
    )
    later = FactBoundary.from_object(_boundary(value.get(field), field))
    if (
        later.code_identity != opened_boundary.code_identity
        or later.runtime_identity != opened_boundary.runtime_identity
    ):
        raise ShadowCaseStoreError("Case follow-up FactBoundary binding mismatch")
    if not later.is_strictly_after(opened_boundary):
        raise ShadowCaseStoreError("Case follow-up is not strictly post-open")
    if expected_kind == FIRST_CLOSE_KIND:
        action_identity = _identity(
            value.get("position_action_identity"),
            "position_action_identity",
        )
        primary_reason = _text(value.get("primary_close_reason"), "primary_close_reason")
        reasons = _string_sequence(
            value.get("ordered_latched_close_reasons"),
            "close reasons",
        )
        try:
            PositionDecisionRecoverySeed(
                first_latched_close_action_identity=action_identity,
                ordered_latched_close_reason_vector=reasons,
            )
        except ValueError as exc:
            raise ShadowCaseStoreError("first CLOSE latched reasons are invalid") from exc
        if primary_reason != reasons[0]:
            raise ShadowCaseStoreError("first CLOSE primary reason mismatch")
        predicate_truth = _string_sequence(
            value.get("predicate_truth_vector"),
            "predicate truth vector",
        )
        if len(predicate_truth) != len(POSITION_CLOSE_REASONS):
            raise ShadowCaseStoreError("first CLOSE predicate truth vector is incomplete")
    else:
        _identity(value.get("shadow_outcome_identity"), "shadow_outcome_identity")
        for identity_field in (
            "selected_exit_identity",
            "first_latched_close_action_identity",
        ):
            identity = value.get(identity_field)
            if identity is not None:
                _identity(identity, identity_field)
        _string_sequence(value.get("censor_mask"), "censor_mask")
        _string_sequence(value.get("non_claims"), "non_claims")
        terminal_state = value.get("terminal_state")
        if terminal_state == "MATURE_KNOWN":
            _identity(
                value.get("close_component_pair_identity"),
                "close_component_pair_identity",
            )
            _validate_component_source_refs(
                value.get("close_component_quote_source_refs"),
                owner_boundary=later,
                field="close_component_quote_source_refs",
            )
            structure = _mapping(opened.get("structure"), "structure")
            product = _product_from_opened(opened)
            close_component = _validate_component_legs(
                value.get("close_component_legs"),
                quantity=_decimal(structure.get("full_quantity_btc"), "full_quantity_btc"),
                short_name=_text(
                    structure.get("short_leg_instrument_name"),
                    "short_leg_instrument_name",
                ),
                long_name=_text(
                    structure.get("long_leg_instrument_name"),
                    "long_leg_instrument_name",
                ),
                expected_actions=("BUY", "SELL"),
                field="close_component_legs",
                schema_version=schema_version,
                product=product,
                fee_rate_index_fraction=policies.position.fee_rate_index_fraction,
            )
            if (
                _decimal(
                    _versioned_get(
                        value,
                        schema_version=schema_version,
                        legacy_key="gross_close_cashflow_usdc",
                        mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
                    ),
                    "gross close cashflow",
                )
                != close_component.valuation_gross_cashflow
                or _decimal(
                    _versioned_get(
                        value,
                        schema_version=schema_version,
                        legacy_key="close_fee_reserve_usdc",
                        mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
                    ),
                    "close fee reserve",
                )
                != close_component.valuation_total_fee
            ):
                raise ShadowCaseStoreError("Outcome economics do not match component close legs")
            native = _mapping(
                value.get("native_outcome_economics"),
                "native_outcome_economics",
            )
            if (
                _decimal(
                    native.get("native_gross_close_cashflow"),
                    "native_gross_close_cashflow",
                )
                != close_component.native_gross_cashflow
                or _decimal(
                    native.get("native_close_fee_reserve"),
                    "native_close_fee_reserve",
                )
                != close_component.native_total_fee
                or _decimal(
                    native.get("close_valuation_index_price"),
                    "close_valuation_index_price",
                )
                != close_component.valuation_index_price
            ):
                raise ShadowCaseStoreError(
                    "native Outcome economics do not match component close legs"
                )
        elif (
            value.get("close_component_pair_identity") is not None
            or value.get("close_component_quote_source_refs") != []
            or value.get("close_component_legs") != []
        ):
            raise ShadowCaseStoreError("unknown/censored Outcome carries component close facts")


def _validate_outcome_economics(
    opened: Mapping[str, object],
    outcome: Mapping[str, object],
) -> None:
    state = outcome.get("terminal_state")
    allowed = {
        "MATURE_KNOWN",
        "MATURE_UNKNOWN",
        "CENSORED_AT_STOP",
        "CENSORED_AT_FAILURE",
    }
    if state not in allowed:
        raise ShadowCaseStoreError("Outcome terminal state is invalid")
    schema_version = _record_schema_version(opened)
    economic_fields = tuple(
        _versioned_key(schema_version, field, _V5_OUTCOME_ECONOMICS_FIELDS)
        for field in (
            "gross_close_cashflow_usdc",
            "close_fee_reserve_usdc",
            "net_close_cashflow_usdc",
            "gross_pnl_usdc",
            "total_public_fee_reserve_usdc",
            "net_pnl_after_public_standard_fee_reserve_usdc",
            "net_loss_usdc",
        )
    )
    if state != "MATURE_KNOWN":
        if any(outcome.get(field) is not None for field in economic_fields):
            raise ShadowCaseStoreError("unknown/censored Outcome carries known economics")
        if outcome.get("economic_availability") != "UNKNOWN":
            raise ShadowCaseStoreError("unknown/censored Outcome availability is invalid")
        _validate_product_aware_outcome(opened, outcome)
        return
    if outcome.get("economic_availability") != "KNOWN":
        raise ShadowCaseStoreError("known Outcome availability is invalid")
    entry = _mapping(opened.get("entry_economics"), "entry_economics")
    gross_entry = _decimal(
        _versioned_get(
            entry,
            schema_version=schema_version,
            legacy_key="gross_entry_credit_usdc",
            mapping=_V5_ENTRY_ECONOMICS_FIELDS,
        ),
        "gross entry",
    )
    entry_fee = _decimal(
        _versioned_get(
            entry,
            schema_version=schema_version,
            legacy_key="entry_fee_reserve_usdc",
            mapping=_V5_ENTRY_ECONOMICS_FIELDS,
        ),
        "entry fee",
    )
    gross_close = _decimal(
        _versioned_get(
            outcome,
            schema_version=schema_version,
            legacy_key="gross_close_cashflow_usdc",
            mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
        ),
        "gross close",
    )
    close_fee = _decimal(
        _versioned_get(
            outcome,
            schema_version=schema_version,
            legacy_key="close_fee_reserve_usdc",
            mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
        ),
        "close fee",
    )
    gross_pnl = gross_entry + gross_close
    total_fees = entry_fee + close_fee
    net_pnl = gross_pnl - total_fees
    expected = {
        "gross_pnl_usdc": gross_pnl,
        "total_public_fee_reserve_usdc": total_fees,
        "net_pnl_after_public_standard_fee_reserve_usdc": net_pnl,
        "net_loss_usdc": max(Decimal(0), -net_pnl),
        "net_close_cashflow_usdc": gross_close - close_fee,
    }
    for field, expected_value in expected.items():
        raw_value = _versioned_get(
            outcome,
            schema_version=schema_version,
            legacy_key=field,
            mapping=_V5_OUTCOME_ECONOMICS_FIELDS,
        )
        if _decimal(raw_value, field) != expected_value:
            raise ShadowCaseStoreError(f"Outcome arithmetic mismatch: {field}")
    _validate_product_aware_outcome(opened, outcome)


def _schema_version_for_product(product: OptionProductSpec) -> int:
    return product.case_schema_version


def _record_schema_version(value: Mapping[str, object]) -> int:
    schema_version = value.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SHADOW_CASE_SCHEMA_VERSION
    ):
        raise ShadowCaseStoreError("Shadow Case schema version is invalid")
    return schema_version


def _shadow_case_identity(
    *,
    bindings: RuntimeBindings,
    enrollment_identity: str,
    opened_boundary: Mapping[str, object],
    schema_version: int,
    product: OptionProductSpec,
) -> str:
    members: list[object] = [
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
    ]
    members.extend((f"schema-v{schema_version}", product.identity))
    members.extend((enrollment_identity, opened_boundary))
    return canonical_identity("ShadowCaseIdentity", *members)


def _product_record(product: OptionProductSpec) -> dict[str, object]:
    return {
        "product_spec_identity": product.identity,
        "product_name": product.name.value,
        "market_family": product.market_family,
        "economic_semantics_version": product.economic_semantics_version,
        "case_schema_version": product.case_schema_version,
        "native_premium_currency": product.native_premium_currency,
        "settlement_currency": product.settlement_currency,
        "valuation_currency": product.valuation_currency,
        "price_index": product.price_index,
        "strike_currency": product.strike_currency,
        "valuation_basis": "EACH_CASHFLOW_AT_ITS_CAUSAL_INDEX_BOUNDARY",
        "model_premium_rule": product.model_premium_rule,
        "valuation_rule": product.valuation_rule,
        "fee_rule": product.fee_rule,
        "native_settlement_payoff_rule": product.native_settlement_payoff_rule,
        "native_settlement_liability_profile": product.native_settlement_liability_profile,
        "actual_account_margin_requirement": None,
        "actual_account_margin_availability": product.actual_account_margin_availability,
        "actual_account_margin_reason": product.actual_account_margin_reason,
    }


def _validate_product_instrument_semantics(
    instrument_name: str,
    *,
    product: OptionProductSpec,
    expiry_ms: int,
    strike: Decimal,
    option_type: object,
) -> None:
    if not product.matches_instrument_name(instrument_name):
        raise ShadowCaseStoreError("opened component instrument product mismatch")
    parts = instrument_name.removeprefix(product.instrument_prefix).rsplit("-", 2)
    expected_suffix = "C" if option_type == "call" else "P"
    if len(parts) != 3 or parts[2] != expected_suffix:
        raise ShadowCaseStoreError("opened component instrument option type mismatch")
    try:
        name_expiry = _deribit_expiry_date(parts[0])
        record_expiry = datetime.fromtimestamp(
            expiry_ms // 1_000,
            tz=UTC,
        ).date()
    except (OSError, OverflowError, ValueError) as exc:
        raise ShadowCaseStoreError("opened component instrument expiry is invalid") from exc
    if name_expiry != record_expiry:
        raise ShadowCaseStoreError("opened component instrument expiry date mismatch")
    try:
        name_strike = Decimal(parts[1])
    except InvalidOperation as exc:
        raise ShadowCaseStoreError("opened component instrument strike is invalid") from exc
    if not name_strike.is_finite() or name_strike != strike:
        raise ShadowCaseStoreError("opened component instrument strike mismatch")


def _deribit_expiry_date(value: str) -> date:
    if len(value) not in {6, 7}:
        raise ValueError("Deribit option expiry token has invalid length")
    day_text = value[:-5]
    month_text = value[-5:-2]
    year_text = value[-2:]
    if not day_text.isdigit() or not year_text.isdigit():
        raise ValueError("Deribit option expiry token is invalid")
    months = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    month = months.get(month_text)
    if month is None:
        raise ValueError("Deribit option expiry month is invalid")
    return date(2_000 + int(year_text), month, int(day_text))


def _product_from_opened(opened: Mapping[str, object]) -> OptionProductSpec:
    _record_schema_version(opened)
    product = _mapping(opened.get("product"), "product")
    return product_for_identity(
        _identity(product.get("product_spec_identity"), "product_spec_identity")
    )


def _component_legs_for_schema(value: object, *, schema_version: int) -> object:
    projected: list[dict[str, object]] = []
    for index, raw in enumerate(_sequence(value, "component legs")):
        leg = _mapping(raw, f"component leg[{index}]")
        projected_leg = _renamed_fields(leg, _V5_COMPONENT_LEG_FIELDS)
        for field in ("raw_consumed_levels_usd", "stressed_consumed_levels_usd"):
            projected_leg[field] = [
                _renamed_fields(
                    _mapping(level, f"{field} level"),
                    {"price_usdc_per_btc": "price_usd_per_btc"},
                )
                for level in _sequence(projected_leg.get(field), field)
            ]
        projected.append(projected_leg)
    return projected


def _validate_product_aware_entry(
    value: Mapping[str, object],
    *,
    product: OptionProductSpec,
    component: _ValidatedComponentEconomics,
    gross_entry: Decimal,
    entry_fee: Decimal,
    net_entry: Decimal,
) -> None:
    product_record = _mapping(value.get("product"), "product")
    expected_product = _product_record(product)
    _exact_keys(product_record, set(expected_product), "product")
    if dict(product_record) != expected_product:
        raise ShadowCaseStoreError("opened option product binding mismatch")
    native = _mapping(value.get("native_entry_economics"), "native_entry_economics")
    _exact_keys(
        native,
        {
            "native_gross_entry_credit",
            "native_entry_fee_reserve",
            "native_net_entry_credit",
            "entry_valuation_index_price",
            "boundary_valued_gross_entry_credit_usd",
            "boundary_valued_entry_fee_reserve_usd",
            "boundary_valued_net_entry_credit_usd",
            "contractual_payoff_cap_strike_currency",
            "native_contractual_payoff_cap_at_entry_index",
            "native_contractual_payoff_cap_basis",
            "expiry_delivery_price",
            "native_contractual_payoff_at_expiry",
        },
        "native_entry_economics",
    )
    native_gross = _decimal(
        native.get("native_gross_entry_credit"),
        "native_gross_entry_credit",
    )
    native_fee = _decimal(
        native.get("native_entry_fee_reserve"),
        "native_entry_fee_reserve",
    )
    native_net = _decimal(native.get("native_net_entry_credit"), "native_net_entry_credit")
    valuation_index = _decimal(
        native.get("entry_valuation_index_price"),
        "entry_valuation_index_price",
    )
    if native_gross <= 0 or native_fee < 0 or valuation_index <= 0:
        raise ShadowCaseStoreError("native entry economics are invalid")
    if native_net != native_gross - native_fee:
        raise ShadowCaseStoreError("native entry economics do not conserve")
    if (
        native_gross != component.native_gross_cashflow
        or native_fee != component.native_total_fee
        or component.valuation_index_price != valuation_index
    ):
        raise ShadowCaseStoreError("native entry economics do not match component legs")
    expected_values = {
        "boundary_valued_gross_entry_credit_usd": gross_entry,
        "boundary_valued_entry_fee_reserve_usd": entry_fee,
        "boundary_valued_net_entry_credit_usd": net_entry,
    }
    for field, expected in expected_values.items():
        if _decimal(native.get(field), field) != expected:
            raise ShadowCaseStoreError(f"native entry boundary valuation mismatch: {field}")
    if (
        product.valuation(native_gross, index_price=valuation_index) != gross_entry
        or product.valuation(native_fee, index_price=valuation_index) != entry_fee
        or product.valuation(native_net, index_price=valuation_index) != net_entry
    ):
        raise ShadowCaseStoreError("native entry conversion does not conserve")
    entry_economics = _mapping(value.get("entry_economics"), "entry_economics")
    contractual_payoff_cap = _decimal(
        native.get("contractual_payoff_cap_strike_currency"),
        "contractual_payoff_cap_strike_currency",
    )
    if contractual_payoff_cap != _decimal(
        entry_economics.get("contractual_payoff_cap_usd"),
        "payoff_cap_usdc",
    ):
        raise ShadowCaseStoreError("contractual payoff cap does not match entry economics")
    expected_native_payoff_cap = product.native_payoff_from_strike_value(
        contractual_payoff_cap,
        settlement_price=valuation_index,
    )
    if (
        _decimal(
            native.get("native_contractual_payoff_cap_at_entry_index"),
            "native_contractual_payoff_cap_at_entry_index",
        )
        != expected_native_payoff_cap
    ):
        raise ShadowCaseStoreError("native payoff boundary conversion does not conserve")
    if (
        native.get("native_contractual_payoff_cap_basis")
        != "ENTRY_INDEX_COUNTERFACTUAL_NOT_EXPIRY_SETTLEMENT"
        or native.get("expiry_delivery_price") is not None
        or native.get("native_contractual_payoff_at_expiry") is not None
    ):
        raise ShadowCaseStoreError("native payoff settlement availability is invalid")


def _validate_product_aware_outcome(
    opened: Mapping[str, object],
    outcome: Mapping[str, object],
) -> None:
    native = _mapping(outcome.get("native_outcome_economics"), "native_outcome_economics")
    fields = {
        "native_gross_close_cashflow",
        "native_close_fee_reserve",
        "native_net_close_cashflow",
        "native_gross_pnl",
        "native_total_fee_reserve",
        "native_net_pnl",
        "close_valuation_index_price",
        "boundary_valued_net_pnl_usd",
        "exit_valued_native_net_pnl_usd",
    }
    _exact_keys(native, fields, "native_outcome_economics")
    if outcome.get("terminal_state") != "MATURE_KNOWN":
        if any(native.get(field) is not None for field in fields):
            raise ShadowCaseStoreError("unknown/censored Outcome carries native economics")
        return
    product = _product_from_opened(opened)
    opened_native = _mapping(
        opened.get("native_entry_economics"),
        "native_entry_economics",
    )
    native_entry_gross = _decimal(
        opened_native.get("native_gross_entry_credit"),
        "native_gross_entry_credit",
    )
    native_entry_fee = _decimal(
        opened_native.get("native_entry_fee_reserve"),
        "native_entry_fee_reserve",
    )
    native_close_gross = _decimal(
        native.get("native_gross_close_cashflow"),
        "native_gross_close_cashflow",
    )
    native_close_fee = _decimal(
        native.get("native_close_fee_reserve"),
        "native_close_fee_reserve",
    )
    native_gross_pnl = native_entry_gross + native_close_gross
    native_total_fee = native_entry_fee + native_close_fee
    native_net_pnl = native_gross_pnl - native_total_fee
    expected_native = {
        "native_net_close_cashflow": native_close_gross - native_close_fee,
        "native_gross_pnl": native_gross_pnl,
        "native_total_fee_reserve": native_total_fee,
        "native_net_pnl": native_net_pnl,
    }
    for field, expected in expected_native.items():
        if _decimal(native.get(field), field) != expected:
            raise ShadowCaseStoreError(f"native Outcome arithmetic mismatch: {field}")
    close_index = _decimal(
        native.get("close_valuation_index_price"),
        "close_valuation_index_price",
    )
    if close_index <= 0:
        raise ShadowCaseStoreError("native Outcome close valuation index must be positive")
    boundary_net = _decimal(
        native.get("boundary_valued_net_pnl_usd"),
        "boundary_valued_net_pnl_usd",
    )
    valued_net = _decimal(
        outcome.get("net_pnl_after_public_standard_fee_reserve_usd"),
        "net_pnl_after_public_standard_fee_reserve_usdc",
    )
    if boundary_net != valued_net:
        raise ShadowCaseStoreError("native Outcome boundary valuation mismatch")
    expected_exit_valued = product.valuation(native_net_pnl, index_price=close_index)
    if (
        _decimal(
            native.get("exit_valued_native_net_pnl_usd"),
            "exit_valued_native_net_pnl_usd",
        )
        != expected_exit_valued
    ):
        raise ShadowCaseStoreError("native Outcome exit valuation mismatch")


def _normalized_mapping(value: Mapping[str, object]) -> dict[str, object]:
    normalized = canonical_value(value)
    if not isinstance(normalized, dict):
        raise ShadowCaseStoreError("Shadow Case record must be an object")
    return normalized


def _versioned_key(schema_version: int, legacy_key: str, mapping: Mapping[str, str]) -> str:
    return mapping.get(legacy_key, legacy_key)


def _versioned_get(
    value: Mapping[str, object],
    *,
    schema_version: int,
    legacy_key: str,
    mapping: Mapping[str, str],
) -> object:
    return value.get(_versioned_key(schema_version, legacy_key, mapping))


def _versioned_keys(
    keys: set[str],
    *,
    schema_version: int,
    mapping: Mapping[str, str],
) -> set[str]:
    return {_versioned_key(schema_version, key, mapping) for key in keys}


def _renamed_fields(
    value: Mapping[str, object],
    mapping: Mapping[str, str],
) -> dict[str, object]:
    renamed = {mapping.get(key, key): member for key, member in value.items()}
    if len(renamed) != len(value):
        raise ShadowCaseStoreError("product-aware field names collide")
    return renamed


def _serialize(value: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowCaseStoreError("Shadow Case record is not canonical JSON") from exc


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ShadowCaseStoreError(f"Shadow Case record is missing or invalid: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowCaseStoreError(f"cannot read Shadow Case record: {path}") from exc
    if not isinstance(value, dict):
        raise ShadowCaseStoreError("Shadow Case record must be an object")
    return value


def _read_optional_json(path: Path) -> dict[str, object] | None:
    if path.exists() or path.is_symlink():
        return _read_json(path)
    return None


def _identity(value: object, field: str) -> str:
    try:
        return require_identity(value, field)
    except ValueError as exc:
        raise ShadowCaseStoreError(str(exc)) from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ShadowCaseStoreError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ShadowCaseStoreError(f"{field} must be an array")
    return value


def _boundary(value: object, field: str) -> dict[str, object]:
    try:
        return FactBoundary.from_object(value).as_object()
    except ValueError as exc:
        raise ShadowCaseStoreError(f"{field} is invalid") from exc


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ShadowCaseStoreError(f"{field} must be a Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ShadowCaseStoreError(f"{field} must be a Decimal") from exc
    if not parsed.is_finite():
        raise ShadowCaseStoreError(f"{field} must be finite")
    return parsed


def _levels_amount(levels: Sequence[object], *, price_field: str) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"level[{index}]")
        _exact_keys(level, {"amount_btc", price_field}, f"level[{index}]")
        amount = _decimal(level.get("amount_btc"), f"level[{index}].amount_btc")
        price = _decimal(level.get(price_field), f"level[{index}].{price_field}")
        if amount <= 0 or price <= 0:
            raise ShadowCaseStoreError("consumed level amount and price must be positive")
        total += amount
    return total


def _validate_component_source_refs(
    value: object,
    *,
    owner_boundary: FactBoundary,
    field: str,
    require_pair_timing_inputs: bool = False,
    expected_leg_identities: tuple[str, str] | None = None,
    expected_instrument_names: tuple[str, str] | None = None,
) -> tuple[_ComponentSourceEvidence, _ComponentSourceEvidence]:
    refs = _sequence(value, field)
    if len(refs) != 2:
        raise ShadowCaseStoreError("component entry requires exactly two quote source refs")
    evidence: list[_ComponentSourceEvidence] = []
    for expected_role, raw in zip(("SHORT", "LONG"), refs, strict=True):
        ref = _mapping(raw, f"{expected_role} component quote source ref")
        expected_keys = {
            "canonical_leg_role",
            "source_identity",
            "receipt_fact_boundary",
        }
        if require_pair_timing_inputs:
            expected_keys.update(
                {
                    "source_timestamp_ms",
                    "global_continuity_epoch",
                    "request_id",
                    "owner_origin_boundary",
                    "sent_boundary",
                    "change_id",
                }
            )
        _exact_keys(
            ref,
            expected_keys,
            f"{expected_role} component quote source ref",
        )
        if ref.get("canonical_leg_role") != expected_role:
            raise ShadowCaseStoreError("component quote source role/order is invalid")
        source_identity = _identity(
            ref.get("source_identity"),
            "component quote source identity",
        )
        source_boundary = FactBoundary.from_object(
            _boundary(ref.get("receipt_fact_boundary"), "receipt_fact_boundary")
        )
        if (
            source_boundary.code_identity != owner_boundary.code_identity
            or source_boundary.runtime_identity != owner_boundary.runtime_identity
            or (
                source_boundary != owner_boundary
                and not owner_boundary.is_strictly_after(source_boundary)
            )
        ):
            raise ShadowCaseStoreError("component quote source boundary is not owned by Entry")
        source_timestamp_ms = (
            _non_negative_integer(
                ref.get("source_timestamp_ms"),
                f"{expected_role} component source_timestamp_ms",
            )
            if require_pair_timing_inputs
            else None
        )
        global_continuity_epoch = (
            _non_negative_integer(
                ref.get("global_continuity_epoch"),
                f"{expected_role} component global_continuity_epoch",
            )
            if require_pair_timing_inputs
            else None
        )
        request_id: int | None = None
        origin_boundary: FactBoundary | None = None
        sent_boundary: FactBoundary | None = None
        if require_pair_timing_inputs:
            if expected_leg_identities is None or expected_instrument_names is None:
                raise ShadowCaseStoreError("component source identity expectations are missing")
            request_id = _non_negative_integer(
                ref.get("request_id"),
                f"{expected_role} component request_id",
            )
            change_id = _non_negative_integer(
                ref.get("change_id"),
                f"{expected_role} component change_id",
            )
            origin_boundary = FactBoundary.from_object(
                _boundary(
                    ref.get("owner_origin_boundary"),
                    f"{expected_role} owner_origin_boundary",
                )
            )
            sent_boundary = FactBoundary.from_object(
                _boundary(
                    ref.get("sent_boundary"),
                    f"{expected_role} sent_boundary",
                )
            )
            boundaries = (origin_boundary, sent_boundary, source_boundary)
            if any(
                member.code_identity != owner_boundary.code_identity
                or member.runtime_identity != owner_boundary.runtime_identity
                for member in boundaries
            ):
                raise ShadowCaseStoreError("component source causal boundary binding is invalid")
            if (
                sent_boundary.causal_seq <= origin_boundary.causal_seq
                or source_boundary.causal_seq <= sent_boundary.causal_seq
            ):
                raise ShadowCaseStoreError("component source causal boundaries are invalid")
            expected_source_identity = canonical_identity(
                "RpcComponentLegRefreshSourceIdentity",
                source_boundary.runtime_identity,
                request_id,
                expected_role,
                "public/get_order_book",
                expected_leg_identities[len(evidence)],
                {
                    "instrument_name": expected_instrument_names[len(evidence)],
                    "depth": 10000,
                },
                origin_boundary.as_object(),
                sent_boundary.as_object(),
                global_continuity_epoch,
                change_id,
                source_timestamp_ms,
                source_boundary.as_object(),
            )
            if source_identity != expected_source_identity:
                raise ShadowCaseStoreError("component quote source identity mismatch")
        evidence.append(
            _ComponentSourceEvidence(
                source_identity=source_identity,
                boundary=source_boundary,
                source_timestamp_ms=source_timestamp_ms,
                global_continuity_epoch=global_continuity_epoch,
                request_id=request_id,
                owner_origin_boundary=origin_boundary,
                sent_boundary=sent_boundary,
            )
        )
    if require_pair_timing_inputs:
        request_ids = tuple(member.request_id for member in evidence)
        if request_ids[0] == request_ids[1]:
            raise ShadowCaseStoreError("component pair request identities are not distinct")
        if evidence[0].owner_origin_boundary != evidence[1].owner_origin_boundary:
            raise ShadowCaseStoreError("component pair source owners do not match")
    return evidence[0], evidence[1]


def _validate_component_pair_timing(
    timing_value: object,
    limits_value: object,
    *,
    source_boundaries: tuple[_ComponentSourceEvidence, _ComponentSourceEvidence],
    pair_identity: str,
    owner_boundary: FactBoundary,
    policies: PolicyChain,
) -> None:
    timing = _mapping(timing_value, "entry_component_pair_timing")
    _exact_keys(
        timing,
        {
            "session_epochs",
            "global_continuity_epochs",
            "source_timestamp_skew_ms",
            "receive_skew_ms",
        },
        "entry_component_pair_timing",
    )
    session_epochs = _non_negative_integer_pair(
        timing.get("session_epochs"),
        "entry_component_pair_timing.session_epochs",
    )
    continuity_epochs = _non_negative_integer_pair(
        timing.get("global_continuity_epochs"),
        "entry_component_pair_timing.global_continuity_epochs",
    )
    if session_epochs[0] != session_epochs[1]:
        raise ShadowCaseStoreError("entry component pair session epochs do not match")
    if continuity_epochs[0] != continuity_epochs[1]:
        raise ShadowCaseStoreError("entry component pair continuity epochs do not match")
    if session_epochs != tuple(value.boundary.session_epoch for value in source_boundaries):
        raise ShadowCaseStoreError("entry component pair session evidence is inconsistent")
    if (
        max(source_boundaries, key=lambda value: value.boundary.causal_seq).boundary
        != owner_boundary
    ):
        raise ShadowCaseStoreError("entry component pair does not own the Case-open boundary")
    expected_pair_identity = canonical_identity(
        "ComponentBookPairWitnessIdentity",
        source_boundaries[0].source_identity,
        source_boundaries[1].source_identity,
        owner_boundary.as_object(),
    )
    if pair_identity != expected_pair_identity:
        raise ShadowCaseStoreError("entry component pair identity mismatch")
    source_skew = _non_negative_integer(
        timing.get("source_timestamp_skew_ms"),
        "entry_component_pair_timing.source_timestamp_skew_ms",
    )
    receive_skew = _non_negative_integer(
        timing.get("receive_skew_ms"),
        "entry_component_pair_timing.receive_skew_ms",
    )
    expected_receive_skew = abs(
        source_boundaries[0].boundary.received_monotonic_ms
        - source_boundaries[1].boundary.received_monotonic_ms
    )
    if receive_skew != expected_receive_skew:
        raise ShadowCaseStoreError("entry component pair receive skew is inconsistent")
    source_timestamps = tuple(value.source_timestamp_ms for value in source_boundaries)
    continuity_sources = tuple(value.global_continuity_epoch for value in source_boundaries)
    if any(value is None for value in (*source_timestamps, *continuity_sources)):
        raise ShadowCaseStoreError("entry component pair timing sources are incomplete")
    assert source_timestamps[0] is not None and source_timestamps[1] is not None
    assert continuity_sources[0] is not None and continuity_sources[1] is not None
    if source_skew != abs(source_timestamps[0] - source_timestamps[1]):
        raise ShadowCaseStoreError("entry component pair source skew is inconsistent")
    if continuity_epochs != continuity_sources:
        raise ShadowCaseStoreError("entry component pair continuity evidence is inconsistent")

    limits = _mapping(limits_value, "entry_component_pair_limits")
    _exact_keys(
        limits,
        {"maximum_source_skew_ms", "maximum_receive_skew_ms"},
        "entry_component_pair_limits",
    )
    maximum_source_skew = _positive_integer(
        limits.get("maximum_source_skew_ms"),
        "entry_component_pair_limits.maximum_source_skew_ms",
    )
    maximum_receive_skew = _positive_integer(
        limits.get("maximum_receive_skew_ms"),
        "entry_component_pair_limits.maximum_receive_skew_ms",
    )
    if (
        maximum_source_skew != policies.underwriting.maximum_component_pair_source_skew_ms
        or maximum_receive_skew != policies.underwriting.maximum_component_pair_receive_skew_ms
    ):
        raise ShadowCaseStoreError("entry component pair limits do not match Underwriting Policy")
    if source_skew > maximum_source_skew or receive_skew > maximum_receive_skew:
        raise ShadowCaseStoreError("entry component pair timing exceeds its Policy limits")


def _non_negative_integer_pair(value: object, field: str) -> tuple[int, int]:
    members = _sequence(value, field)
    if len(members) != 2:
        raise ShadowCaseStoreError(f"{field} must contain exactly two members")
    return (
        _non_negative_integer(members[0], f"{field}[0]"),
        _non_negative_integer(members[1], f"{field}[1]"),
    )


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowCaseStoreError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    integer = _non_negative_integer(value, field)
    if integer == 0:
        raise ShadowCaseStoreError(f"{field} must be positive")
    return integer


def _validate_predicate_margin_vector(
    value: object,
    field: str,
    *,
    valuation_unit: str,
) -> UnderwritingThresholdMargins:
    if not valuation_unit:
        raise ShadowCaseStoreError(f"{field} valuation unit must be non-empty")
    members = _sequence(value, field)
    specifications = (
        ("POSITIVE_NET_ENTRY_CREDIT", valuation_unit, True),
        ("CREDIT_ABOVE_FUTURE_COST_RESERVE", valuation_unit, True),
        ("UNDERWRITING_RESERVED_LOSS_WITHIN_LIMIT", valuation_unit, False),
        ("MINIMUM_NET_ENTRY_CREDIT", valuation_unit, False),
        ("MINIMUM_NET_CREDIT_TO_PAYOFF_CAP", "FRACTION", False),
        ("ENTRY_CONSUMED_LEVEL_LIMIT", "LEVEL_COUNT", False),
    )
    if len(members) != len(specifications):
        raise ShadowCaseStoreError(f"{field} must contain all six predicates")
    decimal_margins: list[Decimal] = []
    level_margin: int | None = None
    for index, (raw, specification) in enumerate(zip(members, specifications, strict=True)):
        expected_predicate, expected_unit, strictly_positive = specification
        margin = _mapping(raw, f"{field}[{index}]")
        _exact_keys(
            margin,
            {"predicate", "signed_margin", "unit", "passes"},
            f"{field}[{index}]",
        )
        if margin.get("predicate") != expected_predicate or margin.get("unit") != expected_unit:
            raise ShadowCaseStoreError(f"{field} predicate order/unit is invalid")
        raw_signed_margin = margin.get("signed_margin")
        if expected_unit == "LEVEL_COUNT":
            signed_margin = _non_negative_or_negative_integer(
                raw_signed_margin,
                f"{field}[{index}].signed_margin",
            )
            level_margin = signed_margin
            numeric_margin = Decimal(signed_margin)
        else:
            if not isinstance(raw_signed_margin, str):
                raise ShadowCaseStoreError(
                    f"{field}[{index}].signed_margin must be a decimal string"
                )
            numeric_margin = _decimal(
                raw_signed_margin,
                f"{field}[{index}].signed_margin",
            )
            decimal_margins.append(numeric_margin)
        passes = margin.get("passes")
        if not isinstance(passes, bool):
            raise ShadowCaseStoreError(f"{field}[{index}].passes must be boolean")
        expected_passes = numeric_margin > 0 if strictly_positive else numeric_margin >= 0
        if passes is not expected_passes:
            raise ShadowCaseStoreError(f"{field}[{index}].passes contradicts signed_margin")
    if len(decimal_margins) != 5 or level_margin is None:
        raise ShadowCaseStoreError(f"{field} is incomplete")
    return UnderwritingThresholdMargins(
        positive_net_credit_usdc=decimal_margins[0],
        credit_above_future_cost_reserve_usdc=decimal_margins[1],
        reserved_loss_limit_headroom_usdc=decimal_margins[2],
        minimum_net_credit_headroom_usdc=decimal_margins[3],
        minimum_credit_ratio_headroom=decimal_margins[4],
        entry_consumed_level_headroom=level_margin,
    )


def _non_negative_or_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowCaseStoreError(f"{field} must be an integer")
    return value


def _validate_margin_decision(
    *,
    action: object,
    failed_predicates: tuple[str, ...],
    margins: UnderwritingThresholdMargins,
    field: str,
) -> None:
    if failed_predicates != margins.failed_predicates:
        raise ShadowCaseStoreError(f"{field} failed predicates contradict its margin vector")
    abstain_failures = {
        "NON_POSITIVE_NET_ENTRY_CREDIT",
        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
        "UNDERWRITING_RESERVED_LOSS_LIMIT",
    }
    expected_action = (
        "ABSTAIN"
        if abstain_failures.intersection(failed_predicates)
        else "WATCH"
        if failed_predicates
        else "CANDIDATE"
    )
    if action != expected_action:
        raise ShadowCaseStoreError(f"{field} action contradicts its margin vector")


def _validate_case_score_packets(
    *,
    selection_value: object,
    refresh_value: object,
    opened_boundary: FactBoundary,
    enrollment_kind: str,
    active_episode_identity: object,
    research_review_identity: object,
    activation_causal_seq: int,
    short_instrument_name: str,
    expiry_ms: int,
    option_type: object,
    bindings: RuntimeBindings,
    radar_policy: RadarPolicy,
) -> tuple[RadarScorePacket, RadarScorePacket]:
    try:
        selection = validate_radar_score_packet(selection_value, policy=radar_policy)
        refresh = validate_radar_score_packet(refresh_value, policy=radar_policy)
        selection_boundary = FactBoundary.from_object(selection.fact_boundary)
        refresh_boundary = FactBoundary.from_object(refresh.fact_boundary)
    except (TypeError, ValueError) as exc:
        raise ShadowCaseStoreError(f"opened Radar score packet is invalid: {exc}") from exc
    for packet, boundary, field in (
        (selection, selection_boundary, "selection_score_packet"),
        (refresh, refresh_boundary, "entry_refresh_score_packet"),
    ):
        if (
            packet.policy_identity != bindings.radar_policy_identity
            or boundary.code_identity != bindings.code_identity
            or boundary.runtime_identity != bindings.runtime_identity
            or packet.leader_instrument_name != short_instrument_name
            or packet.bucket_key.expiry_ms != expiry_ms
            or packet.bucket_key.option_type.value != option_type
        ):
            raise ShadowCaseStoreError(f"{field} does not bind to its Case structure")
    if (
        not opened_boundary.is_strictly_after(selection_boundary)
        or refresh_boundary != opened_boundary
        or activation_causal_seq > selection_boundary.causal_seq
    ):
        raise ShadowCaseStoreError("Case score packet boundary/order mismatch")
    metadata = selection.sampling_metadata
    if metadata is None or refresh.sampling_metadata != metadata:
        raise ShadowCaseStoreError("Case score packets must freeze identical sampling metadata")
    if enrollment_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL":
        expected_batch = radar_score_control_batch_identity(
            bindings=bindings,
            activation_causal_seq=activation_causal_seq,
        )
        if (
            active_episode_identity is not None
            or research_review_identity is None
            or selection_boundary.causal_seq != activation_causal_seq
            or metadata.kind is not SamplingKind.DETERMINISTIC_BAND_CONTROL
            or metadata.causal_batch_identity != expected_batch
            or selection.result.band not in {ScoreBand.LOW, ScoreBand.MID}
            or selection.result.band is not metadata.control_band
        ):
            raise ShadowCaseStoreError("score-band Control packet sampling binding mismatch")
        expected_review_identity = radar_bucket_episode_identity(
            runtime_identity=bindings.runtime_identity,
            policy_identity=bindings.radar_policy_identity,
            bucket_key=selection.bucket_key,
            leader_instrument_name=selection.leader_instrument_name,
            score_band=selection.result.band,
            activation_causal_seq=activation_causal_seq,
        )
        if research_review_identity != expected_review_identity:
            raise ShadowCaseStoreError("score-band Control review identity mismatch")
    else:
        expected_batch = selected_decision_batch_identity(
            bindings=bindings,
            activation_causal_seq=activation_causal_seq,
        )
        if (
            active_episode_identity is None
            or research_review_identity is not None
            or metadata.kind is not SamplingKind.CANONICAL_HIGH
            or metadata.causal_batch_identity != expected_batch
            or selection.result.band is not ScoreBand.HIGH
        ):
            raise ShadowCaseStoreError("canonical HIGH packet sampling binding mismatch")
        expected_episode_identity = radar_bucket_episode_identity(
            runtime_identity=bindings.runtime_identity,
            policy_identity=bindings.radar_policy_identity,
            bucket_key=selection.bucket_key,
            leader_instrument_name=selection.leader_instrument_name,
            score_band=ScoreBand.HIGH,
            activation_causal_seq=activation_causal_seq,
        )
        if active_episode_identity != expected_episode_identity:
            raise ShadowCaseStoreError("canonical HIGH Episode identity mismatch")
    return selection, refresh


def _validate_selected_decision(
    value: Mapping[str, object],
    *,
    opened_boundary: FactBoundary,
    enrollment_kind: object,
    active_episode_identity: object,
    research_review_identity: object,
    activation_causal_seq: int,
    sampling_metadata: object,
    bindings: RuntimeBindings,
    product: OptionProductSpec,
    protective_leg_selection_rule_identity: str,
    candidate_protective_leg_count: int,
) -> None:
    _exact_keys(
        value,
        {
            "selected_underwriting_decision_identity",
            "selection_kind",
            "decision_control_rule_identity",
            "activation_batch_identity",
            "active_episode_identity",
            "radar_research_review_identity",
            "selected_underwriting_action_identity",
            "selected_economic_action",
            "selected_consumed_economic_fact_fingerprint",
            "selected_failed_predicates",
            "selected_predicate_margin_vector",
            "selection_fact_boundary",
            "refreshed_underwriting_action_identity",
            "refreshed_economic_action",
            "refreshed_consumed_economic_fact_fingerprint",
            "refreshed_failed_predicates",
            "refreshed_predicate_margin_vector",
            "refreshed_fact_boundary",
        },
        "selected_underwriting_decision",
    )
    for field in (
        "selected_underwriting_decision_identity",
        "decision_control_rule_identity",
        "activation_batch_identity",
        "selected_underwriting_action_identity",
        "selected_consumed_economic_fact_fingerprint",
        "refreshed_underwriting_action_identity",
        "refreshed_consumed_economic_fact_fingerprint",
    ):
        _identity(value.get(field), field)
    selection_kind = value.get("selection_kind")
    if selection_kind == "HIGH_ACTION_BLIND":
        if active_episode_identity is None or research_review_identity is not None:
            raise ShadowCaseStoreError("HIGH selected decision lacks its active Episode")
        expected_rule = selected_decision_rule_identity(bindings=bindings)
        expected_batch = selected_decision_batch_identity(
            bindings=bindings,
            activation_causal_seq=activation_causal_seq,
        )
        expected_anchor = _identity(active_episode_identity, "active_episode_identity")
        expected_sampling_kind = SamplingKind.CANONICAL_HIGH
    elif selection_kind == "RADAR_SCORE_BAND_NO_TRADE_CONTROL":
        if enrollment_kind != "RADAR_SCORE_BAND_NO_TRADE_CONTROL":
            raise ShadowCaseStoreError("score-band selection opened the wrong Case lane")
        if research_review_identity is None or active_episode_identity is not None:
            raise ShadowCaseStoreError("score-band selected decision lacks its review anchor")
        expected_rule = radar_score_control_rule_identity(bindings=bindings)
        expected_batch = radar_score_control_batch_identity(
            bindings=bindings,
            activation_causal_seq=activation_causal_seq,
        )
        expected_anchor = _identity(
            research_review_identity,
            "radar_research_review_identity",
        )
        expected_sampling_kind = SamplingKind.DETERMINISTIC_BAND_CONTROL
    else:
        raise ShadowCaseStoreError("selected decision kind is invalid")
    if value.get("decision_control_rule_identity") != expected_rule:
        raise ShadowCaseStoreError("selected decision rule binding mismatch")
    if value.get("activation_batch_identity") != expected_batch:
        raise ShadowCaseStoreError("selected decision batch binding mismatch")
    if (
        value.get("active_episode_identity") != active_episode_identity
        or value.get("radar_research_review_identity") != research_review_identity
    ):
        raise ShadowCaseStoreError("selected decision Radar anchor projection mismatch")
    if not isinstance(sampling_metadata, RadarSamplingMetadata):
        raise ShadowCaseStoreError("selected decision lacks typed sampling metadata")
    if (
        sampling_metadata.kind is not expected_sampling_kind
        or sampling_metadata.causal_batch_identity != expected_batch
    ):
        raise ShadowCaseStoreError("selected decision sampling metadata binding mismatch")
    for field in ("selected_economic_action", "refreshed_economic_action"):
        if value.get(field) not in {"CANDIDATE", "WATCH", "ABSTAIN"}:
            raise ShadowCaseStoreError(f"{field} is invalid")
    selected_failed_predicates = _string_sequence(
        value.get("selected_failed_predicates"),
        "selected_failed_predicates",
    )
    refreshed_failed_predicates = _string_sequence(
        value.get("refreshed_failed_predicates"),
        "refreshed_failed_predicates",
    )
    selected_margins = _validate_predicate_margin_vector(
        value.get("selected_predicate_margin_vector"),
        "selected_predicate_margin_vector",
        valuation_unit=product.valuation_currency,
    )
    refreshed_margins = _validate_predicate_margin_vector(
        value.get("refreshed_predicate_margin_vector"),
        "refreshed_predicate_margin_vector",
        valuation_unit=product.valuation_currency,
    )
    _validate_margin_decision(
        action=value.get("selected_economic_action"),
        failed_predicates=selected_failed_predicates,
        margins=selected_margins,
        field="selected Underwriting decision",
    )
    _validate_margin_decision(
        action=value.get("refreshed_economic_action"),
        failed_predicates=refreshed_failed_predicates,
        margins=refreshed_margins,
        field="refreshed Underwriting decision",
    )
    selection_boundary = FactBoundary.from_object(
        _boundary(value.get("selection_fact_boundary"), "selection_fact_boundary")
    )
    refreshed_boundary = FactBoundary.from_object(
        _boundary(value.get("refreshed_fact_boundary"), "refreshed_fact_boundary")
    )
    if (
        selection_boundary.code_identity != opened_boundary.code_identity
        or selection_boundary.runtime_identity != opened_boundary.runtime_identity
        or not opened_boundary.is_strictly_after(selection_boundary)
        or refreshed_boundary != opened_boundary
    ):
        raise ShadowCaseStoreError("selected decision boundary/order mismatch")
    expected_selection = canonical_identity(
        "SelectedUnderwritingDecisionIdentity",
        expected_rule,
        expected_batch,
        expected_anchor,
        value.get("selected_underwriting_action_identity"),
        value.get("selected_economic_action"),
        selected_margins.as_vector(product.valuation_currency),
        value.get("selected_consumed_economic_fact_fingerprint"),
        selection_boundary.as_object(),
    )
    if value.get("selected_underwriting_decision_identity") != expected_selection:
        raise ShadowCaseStoreError("selected decision identity mismatch")
    if selection_kind == "HIGH_ACTION_BLIND":
        if sampling_metadata.designation_identity != expected_selection:
            raise ShadowCaseStoreError("HIGH selected decision sampling designation mismatch")
    else:
        if sampling_metadata.control_band is None:
            raise ShadowCaseStoreError("score-band sampling lacks its control band")
        expected_designation = canonical_identity(
            "RadarScoreControlDesignationIdentity",
            expected_rule,
            expected_batch,
            {
                "LOW": sampling_metadata.low_eligible_count,
                "MID": sampling_metadata.mid_eligible_count,
            },
            sampling_metadata.control_band.value,
            expected_anchor,
            sampling_metadata.selected_ordinal,
            {
                "numerator": sampling_metadata.inclusion_numerator,
                "denominator": sampling_metadata.inclusion_denominator,
            },
        )
        if sampling_metadata.designation_identity != expected_designation:
            raise ShadowCaseStoreError("score-band sampling designation identity mismatch")
    expected_refreshed_action = canonical_identity(
        "CaseOpenRefreshedUnderwritingActionIdentity",
        expected_selection,
        value.get("refreshed_consumed_economic_fact_fingerprint"),
        value.get("refreshed_economic_action"),
        protective_leg_selection_rule_identity,
        candidate_protective_leg_count,
        refreshed_boundary.as_object(),
    )
    if value.get("refreshed_underwriting_action_identity") != expected_refreshed_action:
        raise ShadowCaseStoreError("refreshed Underwriting action identity mismatch")
    if (
        enrollment_kind == "ADMITTED_SHADOW_TRADE"
        and value.get("refreshed_economic_action") != "CANDIDATE"
    ):
        raise ShadowCaseStoreError("selected admitted trade did not remain Candidate")


def _validate_component_legs(
    value: object,
    *,
    quantity: Decimal,
    short_name: str,
    long_name: str,
    expected_actions: tuple[str, str],
    field: str,
    schema_version: int,
    product: OptionProductSpec,
    fee_rate_index_fraction: Decimal,
) -> _ValidatedComponentEconomics:
    if schema_version != SHADOW_CASE_SCHEMA_VERSION:
        raise ShadowCaseStoreError("component legs require Shadow Case schema v5")
    legs = _sequence(value, field)
    if len(legs) != 2:
        raise ShadowCaseStoreError("component entry requires exactly two leg quotes")
    expected = (
        ("SHORT", expected_actions[0], short_name),
        ("LONG", expected_actions[1], long_name),
    )
    valuation_gross_cashflow = Decimal(0)
    valuation_total_fee = Decimal(0)
    native_gross_cashflow = Decimal(0)
    native_total_fee = Decimal(0)
    consumed_level_count = 0
    observed_index: Decimal | None = None
    for raw, (role, action, instrument_name) in zip(legs, expected, strict=True):
        leg = _mapping(raw, f"{role} component leg")
        legacy_keys = {
            "canonical_leg_role",
            "instrument_name",
            "action",
            "raw_consumed_levels",
            "raw_vwap_usdc_per_btc",
            "stressed_consumed_levels",
            "stressed_vwap_usdc_per_btc",
            "fee_reserve_usdc",
        }
        product_keys = {
            "native_premium_currency",
            "valuation_index_price",
            "raw_consumed_levels_native",
            "raw_vwap_native",
            "stressed_consumed_levels_native",
            "stressed_vwap_native",
            "native_fee_reserve",
        }
        valuation_keys = _versioned_keys(
            legacy_keys,
            schema_version=schema_version,
            mapping=_V5_COMPONENT_LEG_FIELDS,
        )
        expected_keys = valuation_keys | product_keys
        _exact_keys(leg, expected_keys, f"{role} component leg")
        if (
            leg.get("canonical_leg_role") != role
            or leg.get("action") != action
            or leg.get("instrument_name") != instrument_name
        ):
            raise ShadowCaseStoreError("component leg role/action/instrument is invalid")
        raw_levels = _sequence(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="raw_consumed_levels",
                mapping=_V5_COMPONENT_LEG_FIELDS,
            ),
            "raw_consumed_levels",
        )
        stressed_levels = _sequence(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="stressed_consumed_levels",
                mapping=_V5_COMPONENT_LEG_FIELDS,
            ),
            "stressed_consumed_levels",
        )
        valuation_price_field = "price_usd_per_btc"
        if (
            _levels_amount(
                raw_levels,
                price_field=valuation_price_field,
            )
            != quantity
            or _levels_amount(
                stressed_levels,
                price_field=valuation_price_field,
            )
            != quantity
        ):
            raise ShadowCaseStoreError("component leg levels do not cover full quantity")
        consumed_level_count += len(stressed_levels)
        raw_vwap = _decimal(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="raw_vwap_usdc_per_btc",
                mapping=_V5_COMPONENT_LEG_FIELDS,
            ),
            "raw component VWAP",
        )
        stressed_vwap = _decimal(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="stressed_vwap_usdc_per_btc",
                mapping=_V5_COMPONENT_LEG_FIELDS,
            ),
            "stressed component VWAP",
        )
        valuation_fee = _decimal(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="fee_reserve_usdc",
                mapping=_V5_COMPONENT_LEG_FIELDS,
            ),
            "component fee reserve",
        )
        if raw_vwap <= 0 or stressed_vwap <= 0 or valuation_fee < 0:
            raise ShadowCaseStoreError("component leg economics must be non-negative")
        if raw_vwap * quantity != _levels_value(
            raw_levels,
            price_field=valuation_price_field,
        ) or stressed_vwap * quantity != _levels_value(
            stressed_levels,
            price_field=valuation_price_field,
        ):
            raise ShadowCaseStoreError("component leg VWAP does not match consumed levels")
        if (action == "SELL" and stressed_vwap > raw_vwap) or (
            action == "BUY" and stressed_vwap < raw_vwap
        ):
            raise ShadowCaseStoreError("component stress direction is not conservative")
        valuation_gross_cashflow += (
            stressed_vwap * quantity if action == "SELL" else -stressed_vwap * quantity
        )
        valuation_total_fee += valuation_fee

        native_currency = _text(
            leg.get("native_premium_currency"),
            "native_premium_currency",
        )
        if native_currency != product.native_premium_currency:
            raise ShadowCaseStoreError("component native premium currency mismatch")
        valuation_index = _decimal(
            leg.get("valuation_index_price"),
            "valuation_index_price",
        )
        if valuation_index <= 0:
            raise ShadowCaseStoreError("component valuation index must be positive")
        if observed_index is None:
            observed_index = valuation_index
        elif observed_index != valuation_index:
            raise ShadowCaseStoreError("component legs use different valuation indices")
        raw_native_levels = _sequence(
            leg.get("raw_consumed_levels_native"),
            "raw_consumed_levels_native",
        )
        stressed_native_levels = _sequence(
            leg.get("stressed_consumed_levels_native"),
            "stressed_consumed_levels_native",
        )
        if (
            _native_levels_amount(raw_native_levels) != quantity
            or _native_levels_amount(stressed_native_levels) != quantity
        ):
            raise ShadowCaseStoreError("native component levels do not cover full quantity")
        raw_native_vwap = _decimal(leg.get("raw_vwap_native"), "raw native VWAP")
        stressed_native_vwap = _decimal(
            leg.get("stressed_vwap_native"),
            "stressed native VWAP",
        )
        native_fee = _decimal(leg.get("native_fee_reserve"), "native fee reserve")
        if raw_native_vwap <= 0 or stressed_native_vwap <= 0 or native_fee < 0:
            raise ShadowCaseStoreError("native component economics must be non-negative")
        expected_native_fee = product.native_option_fee(
            native_option_price=stressed_native_vwap,
            index_price=valuation_index,
            quantity_btc=quantity,
            fee_rate=fee_rate_index_fraction,
        )
        if native_fee != expected_native_fee:
            raise ShadowCaseStoreError("component native fee does not match the Policy rule")
        if raw_native_vwap * quantity != _native_levels_value(
            raw_native_levels
        ) or stressed_native_vwap * quantity != _native_levels_value(stressed_native_levels):
            raise ShadowCaseStoreError("native component VWAP does not match consumed levels")
        if (action == "SELL" and stressed_native_vwap > raw_native_vwap) or (
            action == "BUY" and stressed_native_vwap < raw_native_vwap
        ):
            raise ShadowCaseStoreError("native component stress direction is not conservative")
        _validate_native_valuation_levels(
            native_levels=raw_native_levels,
            valuation_levels=raw_levels,
            product=product,
            valuation_index=valuation_index,
            valuation_price_field=valuation_price_field,
            field="raw component levels",
        )
        _validate_native_valuation_levels(
            native_levels=stressed_native_levels,
            valuation_levels=stressed_levels,
            product=product,
            valuation_index=valuation_index,
            valuation_price_field=valuation_price_field,
            field="stressed component levels",
        )
        if product.valuation(raw_native_vwap, index_price=valuation_index) != raw_vwap:
            raise ShadowCaseStoreError("raw component valuation VWAP mismatch")
        if product.valuation(stressed_native_vwap, index_price=valuation_index) != stressed_vwap:
            raise ShadowCaseStoreError("stressed component valuation VWAP mismatch")
        if product.valuation(native_fee, index_price=valuation_index) != valuation_fee:
            raise ShadowCaseStoreError("component fee valuation mismatch")
        native_gross_cashflow += (
            stressed_native_vwap * quantity
            if action == "SELL"
            else -stressed_native_vwap * quantity
        )
        native_total_fee += native_fee
    return _ValidatedComponentEconomics(
        valuation_gross_cashflow=valuation_gross_cashflow,
        valuation_total_fee=valuation_total_fee,
        consumed_level_count=consumed_level_count,
        native_gross_cashflow=native_gross_cashflow,
        native_total_fee=native_total_fee,
        native_premium_currency=product.native_premium_currency,
        valuation_index_price=observed_index,
    )


def _native_levels_amount(levels: Sequence[object]) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"native level[{index}]")
        _exact_keys(level, {"amount_btc", "price_native"}, f"native level[{index}]")
        amount = _decimal(level.get("amount_btc"), f"native level[{index}].amount_btc")
        price = _decimal(level.get("price_native"), f"native level[{index}].price_native")
        if amount <= 0 or price <= 0:
            raise ShadowCaseStoreError("native consumed level amount and price must be positive")
        total += amount
    return total


def _native_levels_value(levels: Sequence[object]) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"native level[{index}]")
        total += _decimal(level.get("amount_btc"), "amount_btc") * _decimal(
            level.get("price_native"), "price_native"
        )
    return total


def _validate_native_valuation_levels(
    *,
    native_levels: Sequence[object],
    valuation_levels: Sequence[object],
    product: OptionProductSpec,
    valuation_index: Decimal,
    valuation_price_field: str,
    field: str,
) -> None:
    if len(native_levels) != len(valuation_levels):
        raise ShadowCaseStoreError(f"{field} count mismatch")
    for index, (native_raw, valuation_raw) in enumerate(
        zip(native_levels, valuation_levels, strict=True)
    ):
        native = _mapping(native_raw, f"{field} native[{index}]")
        valuation = _mapping(valuation_raw, f"{field} valuation[{index}]")
        native_amount = _decimal(native.get("amount_btc"), "native amount_btc")
        valuation_amount = _decimal(valuation.get("amount_btc"), "valuation amount_btc")
        if native_amount != valuation_amount:
            raise ShadowCaseStoreError(f"{field} amount mismatch")
        native_price = _decimal(native.get("price_native"), "native price")
        valuation_price = _decimal(
            valuation.get(valuation_price_field),
            "valuation price",
        )
        if product.valuation(native_price, index_price=valuation_index) != valuation_price:
            raise ShadowCaseStoreError(f"{field} price conversion mismatch")


def _levels_value(levels: Sequence[object], *, price_field: str) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"level[{index}]")
        total += _decimal(level.get("amount_btc"), "amount_btc") * _decimal(
            level.get(price_field), price_field
        )
    return total


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ShadowCaseStoreError(f"{field} has an invalid key set")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ShadowCaseStoreError(f"{field} must be a non-empty string")
    return value


def _string_sequence(value: object, field: str) -> tuple[str, ...]:
    members = _sequence(value, field)
    return tuple(_text(member, f"{field} member") for member in members)
