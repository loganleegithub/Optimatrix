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

from options_domain import (
    LINEAR_BTC_USDC,
    OptionProductSpec,
    product_for_identity,
)

from short_vol_underwriting.control import (
    selected_decision_batch_identity,
    selected_decision_rule_identity,
)
from short_vol_underwriting.domain import (
    UNDERWRITING_COMPONENT_SELECTION_RULE_IDENTITY,
    UnderwritingThresholdMargins,
)
from short_vol_underwriting.evidence import RuntimeBindings, ShadowStateStore
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary
from short_vol_underwriting.policy import PolicyChain

SHADOW_CASE_SCHEMA_VERSION = 3
PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION = 4
OPENED_KIND = "SHADOW_CASE_OPENED"
FIRST_CLOSE_KIND = "SHADOW_CASE_FIRST_CLOSE"
OUTCOME_KIND = "SHADOW_CASE_OUTCOME"

_V4_STRUCTURE_FIELDS = {
    "short_strike_usdc_per_btc": "short_strike_usd_per_btc",
    "long_strike_usdc_per_btc": "long_strike_usd_per_btc",
}
_V4_UNDERWRITING_FIELDS = {
    "minimum_net_entry_credit_usdc": "minimum_net_entry_credit_usd",
    "maximum_underwriting_reserved_loss_usdc": "maximum_underwriting_reserved_loss_usd",
}
_V4_ENTRY_ECONOMICS_FIELDS = {
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
_V4_OUTCOME_ECONOMICS_FIELDS = {
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
_V4_COMPONENT_LEG_FIELDS = {
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


@dataclass(frozen=True)
class ShadowCaseRead:
    status: ShadowCaseReadStatus
    opened: Mapping[str, object]
    first_close: Mapping[str, object] | None
    outcome: Mapping[str, object] | None


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
        if kind in {"SHADOW_ENTRY", "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN"}:
            self._open_case(value, state)
        elif kind == "POSITION_ACTION":
            self._record_first_close(value)
        elif kind in {"SHADOW_OUTCOME", "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME"}:
            self._record_outcome(value)

    def read_case(self, case_id: str, *, runtime_active: bool = False) -> ShadowCaseRead:
        require_identity(case_id, "case_id")
        case_directory = self._case_directory(case_id)
        opened = _read_json(case_directory / "opened.json")
        _validate_opened(
            opened,
            expected_case_id=case_id,
            bindings=self.bindings,
            policies=self.policies,
        )
        first_close_path = case_directory / "first-close.json"
        outcome_path = case_directory / "outcome.json"
        first_close = _read_json(first_close_path) if first_close_path.exists() else None
        outcome = _read_json(outcome_path) if outcome_path.exists() else None
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
        elif object_kind == "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN":
            enrollment_kind = "SELECTED_UNDERWRITING_DECISION_CONTROL"
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
                "radar_scope_identity": payload.get("radar_scope_identity"),
                "component_state": payload.get("component_state"),
                "atomic_state_diagnostic": payload.get("atomic_state_diagnostic"),
                "band_id": payload.get("radar_band_id"),
                "richness_interval": payload.get("radar_richness_interval"),
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
        if self.schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
                        "boundary_valued_entry_fee_reserve_usd": payload.get(
                            "entry_fee_reserve_usdc"
                        ),
                        "boundary_valued_net_entry_credit_usd": payload.get(
                            "net_entry_credit_usdc"
                        ),
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
                _V4_STRUCTURE_FIELDS,
            )
            opened["underwriting"] = _renamed_fields(
                _mapping(opened.get("underwriting"), "underwriting"),
                _V4_UNDERWRITING_FIELDS,
            )
            opened["entry_economics"] = _renamed_fields(
                _mapping(opened.get("entry_economics"), "entry_economics"),
                _V4_ENTRY_ECONOMICS_FIELDS,
            )
        normalized = _normalized_mapping(opened)
        _validate_opened(
            normalized,
            expected_case_id=case_id,
            bindings=self.bindings,
            policies=self.policies,
        )
        self._publish(case_id, "opened.json", normalized)
        self._case_by_enrollment[enrollment_identity] = case_id
        self._opened_by_case[case_id] = normalized
        self._case_count += 1

    def _record_first_close(self, value: Mapping[str, object]) -> None:
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
        record = _normalized_mapping(
            {
                "record_kind": FIRST_CLOSE_KIND,
                "schema_version": opened.get("schema_version"),
                "case_id": case_id,
                **self._binding_object(),
                "first_close_fact_boundary": value.get("fact_boundary"),
                "position_action_identity": action_identity,
                "primary_close_reason": payload.get("primary_close_reason"),
                "ordered_latched_close_reasons": payload.get("ordered_latched_close_reason_vector"),
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

    def _record_outcome(self, value: Mapping[str, object]) -> None:
        payload = _mapping(value.get("payload"), "SHADOW_OUTCOME.payload")
        entry_identity = _identity(payload.get("shadow_entry_identity"), "shadow_entry_identity")
        case_id = self._case_by_enrollment.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("Outcome belongs to an unopened Shadow Case")
        opened = self._opened_by_case[case_id]
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
        if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
                _V4_OUTCOME_ECONOMICS_FIELDS,
            )
        record = _normalized_mapping(outcome_record)
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
        serialized = _serialize(value)
        path = case_directory / filename
        temporary = case_directory / f".case-{uuid.uuid4().hex}.tmp"
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
        directory_fd = os.open(case_directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


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
        "structure",
        "radar",
        "underwriting",
        "entry_economics",
        "non_claims",
    }
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
            mapping=_V4_STRUCTURE_FIELDS,
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
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION and (
        not product.matches_instrument_name(short_instrument_name)
        or not product.matches_instrument_name(long_instrument_name)
    ):
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
            mapping=_V4_STRUCTURE_FIELDS,
        ),
        "short_strike_usdc_per_btc",
    )
    long_strike = _decimal(
        _versioned_get(
            structure,
            schema_version=schema_version,
            legacy_key="long_strike_usdc_per_btc",
            mapping=_V4_STRUCTURE_FIELDS,
        ),
        "long_strike_usdc_per_btc",
    )
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION and (
        (option_type == "call" and long_strike <= short_strike)
        or (option_type == "put" and long_strike >= short_strike)
    ):
        raise ShadowCaseStoreError("opened component strikes are not a protective vertical")
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
            "radar_scope_identity",
            "component_state",
            "atomic_state_diagnostic",
            "band_id",
            "richness_interval",
        },
        "opened radar",
    )
    _text(radar.get("active_episode_identity"), "active_episode_identity")
    _identity(radar.get("radar_scope_identity"), "radar_scope_identity")
    if radar.get("component_state") != "COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE":
        raise ShadowCaseStoreError("opened component_state is invalid")
    _text(radar.get("atomic_state_diagnostic"), "atomic_state_diagnostic")
    _text(radar.get("band_id"), "band_id")
    richness = _mapping(radar.get("richness_interval"), "richness_interval")
    _exact_keys(richness, {"lower", "upper"}, "richness_interval")
    if _decimal(richness.get("lower"), "richness lower") > _decimal(
        richness.get("upper"), "richness upper"
    ):
        raise ShadowCaseStoreError("richness interval is inverted")

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
            mapping=_V4_UNDERWRITING_FIELDS,
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
            mapping=_V4_UNDERWRITING_FIELDS,
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
            mapping=_V4_ENTRY_ECONOMICS_FIELDS,
        ),
        "entry_economics",
    )

    def entry_field(key: str) -> object:
        return _versioned_get(
            economics,
            schema_version=schema_version,
            legacy_key=key,
            mapping=_V4_ENTRY_ECONOMICS_FIELDS,
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
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
        if enrollment_kind == "SELECTED_UNDERWRITING_DECISION_CONTROL":
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
            active_episode_identity=_text(
                radar.get("active_episode_identity"),
                "active_episode_identity",
            ),
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
            mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
        )
    if expected_kind == OUTCOME_KIND and schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
        _identity(value.get("position_action_identity"), "position_action_identity")
        _text(value.get("primary_close_reason"), "primary_close_reason")
        _string_sequence(value.get("ordered_latched_close_reasons"), "close reasons")
        _string_sequence(value.get("predicate_truth_vector"), "predicate truth vector")
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
                        mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
                    ),
                    "gross close cashflow",
                )
                != close_component.valuation_gross_cashflow
                or _decimal(
                    _versioned_get(
                        value,
                        schema_version=schema_version,
                        legacy_key="close_fee_reserve_usdc",
                        mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
                    ),
                    "close fee reserve",
                )
                != close_component.valuation_total_fee
            ):
                raise ShadowCaseStoreError("Outcome economics do not match component close legs")
            if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
        _versioned_key(schema_version, field, _V4_OUTCOME_ECONOMICS_FIELDS)
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
        if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
            mapping=_V4_ENTRY_ECONOMICS_FIELDS,
        ),
        "gross entry",
    )
    entry_fee = _decimal(
        _versioned_get(
            entry,
            schema_version=schema_version,
            legacy_key="entry_fee_reserve_usdc",
            mapping=_V4_ENTRY_ECONOMICS_FIELDS,
        ),
        "entry fee",
    )
    gross_close = _decimal(
        _versioned_get(
            outcome,
            schema_version=schema_version,
            legacy_key="gross_close_cashflow_usdc",
            mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
        ),
        "gross close",
    )
    close_fee = _decimal(
        _versioned_get(
            outcome,
            schema_version=schema_version,
            legacy_key="close_fee_reserve_usdc",
            mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
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
            mapping=_V4_OUTCOME_ECONOMICS_FIELDS,
        )
        if _decimal(raw_value, field) != expected_value:
            raise ShadowCaseStoreError(f"Outcome arithmetic mismatch: {field}")
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
        _validate_product_aware_outcome(opened, outcome)


def _schema_version_for_product(product: OptionProductSpec) -> int:
    return product.case_schema_version


def _record_schema_version(value: Mapping[str, object]) -> int:
    schema_version = value.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version
        not in {SHADOW_CASE_SCHEMA_VERSION, PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION}
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
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
        members.extend(("schema-v4", product.identity))
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
    if _record_schema_version(opened) == SHADOW_CASE_SCHEMA_VERSION:
        return LINEAR_BTC_USDC
    product = _mapping(opened.get("product"), "product")
    return product_for_identity(
        _identity(product.get("product_spec_identity"), "product_spec_identity")
    )


def _component_legs_for_schema(value: object, *, schema_version: int) -> object:
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
        projected_v4: list[dict[str, object]] = []
        for index, raw in enumerate(_sequence(value, "component legs")):
            leg = _mapping(raw, f"component leg[{index}]")
            projected_leg = _renamed_fields(leg, _V4_COMPONENT_LEG_FIELDS)
            for field in ("raw_consumed_levels_usd", "stressed_consumed_levels_usd"):
                projected_leg[field] = [
                    _renamed_fields(
                        _mapping(level, f"{field} level"),
                        {"price_usdc_per_btc": "price_usd_per_btc"},
                    )
                    for level in _sequence(projected_leg.get(field), field)
                ]
            projected_v4.append(projected_leg)
        return projected_v4
    legs = _sequence(value, "component legs")
    legacy_keys = (
        "canonical_leg_role",
        "instrument_name",
        "action",
        "raw_consumed_levels",
        "raw_vwap_usdc_per_btc",
        "stressed_consumed_levels",
        "stressed_vwap_usdc_per_btc",
        "fee_reserve_usdc",
    )
    projected: list[dict[str, object]] = []
    for index, raw in enumerate(legs):
        leg = _mapping(raw, f"component leg[{index}]")
        projected.append({key: leg.get(key) for key in legacy_keys})
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
    if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
        return mapping.get(legacy_key, legacy_key)
    return legacy_key


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
    valuation_unit: str = "USDC",
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


def _validate_selected_decision(
    value: Mapping[str, object],
    *,
    opened_boundary: FactBoundary,
    enrollment_kind: object,
    active_episode_identity: str,
    bindings: RuntimeBindings,
    product: OptionProductSpec,
    protective_leg_selection_rule_identity: str,
    candidate_protective_leg_count: int,
) -> None:
    _exact_keys(
        value,
        {
            "selected_underwriting_decision_identity",
            "decision_control_rule_identity",
            "activation_batch_identity",
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
    expected_rule = selected_decision_rule_identity(bindings=bindings)
    if value.get("decision_control_rule_identity") != expected_rule:
        raise ShadowCaseStoreError("selected decision rule binding mismatch")
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
    _episode_prefix, separator, activation_seq_text = active_episode_identity.rpartition(":")
    if (
        not separator
        or not activation_seq_text.isdigit()
        or str(int(activation_seq_text)) != activation_seq_text
    ):
        raise ShadowCaseStoreError("selected decision Episode identity is invalid")
    expected_batch = selected_decision_batch_identity(
        bindings=bindings,
        activation_causal_seq=int(activation_seq_text),
    )
    if value.get("activation_batch_identity") != expected_batch:
        raise ShadowCaseStoreError("selected decision batch binding mismatch")
    expected_selection = canonical_identity(
        "SelectedUnderwritingDecisionIdentity",
        expected_rule,
        expected_batch,
        active_episode_identity,
        value.get("selected_underwriting_action_identity"),
        value.get("selected_economic_action"),
        selected_margins.as_vector(product.valuation_currency),
        value.get("selected_consumed_economic_fact_fingerprint"),
        selection_boundary.as_object(),
    )
    if value.get("selected_underwriting_decision_identity") != expected_selection:
        raise ShadowCaseStoreError("selected decision identity mismatch")
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
            mapping=_V4_COMPONENT_LEG_FIELDS,
        )
        expected_keys = (
            valuation_keys | product_keys
            if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION
            else valuation_keys
        )
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
                mapping=_V4_COMPONENT_LEG_FIELDS,
            ),
            "raw_consumed_levels",
        )
        stressed_levels = _sequence(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="stressed_consumed_levels",
                mapping=_V4_COMPONENT_LEG_FIELDS,
            ),
            "stressed_consumed_levels",
        )
        valuation_price_field = (
            "price_usd_per_btc"
            if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION
            else "price_usdc_per_btc"
        )
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
                mapping=_V4_COMPONENT_LEG_FIELDS,
            ),
            "raw component VWAP",
        )
        stressed_vwap = _decimal(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="stressed_vwap_usdc_per_btc",
                mapping=_V4_COMPONENT_LEG_FIELDS,
            ),
            "stressed component VWAP",
        )
        valuation_fee = _decimal(
            _versioned_get(
                leg,
                schema_version=schema_version,
                legacy_key="fee_reserve_usdc",
                mapping=_V4_COMPONENT_LEG_FIELDS,
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

        if schema_version == PRODUCT_AWARE_SHADOW_CASE_SCHEMA_VERSION:
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
            if (
                product.valuation(stressed_native_vwap, index_price=valuation_index)
                != stressed_vwap
            ):
                raise ShadowCaseStoreError("stressed component valuation VWAP mismatch")
            if product.valuation(native_fee, index_price=valuation_index) != valuation_fee:
                raise ShadowCaseStoreError("component fee valuation mismatch")
            native_gross_cashflow += (
                stressed_native_vwap * quantity
                if action == "SELL"
                else -stressed_native_vwap * quantity
            )
            native_total_fee += native_fee
        else:
            native_gross_cashflow = valuation_gross_cashflow
            native_total_fee = valuation_total_fee

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
