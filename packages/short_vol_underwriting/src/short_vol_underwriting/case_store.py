from __future__ import annotations

import json
import os
import stat
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from short_vol_underwriting.evidence import RuntimeBindings, ShadowStateStore
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary
from short_vol_underwriting.policy import PolicyChain

SHADOW_CASE_SCHEMA_VERSION = 2
OPENED_KIND = "SHADOW_CASE_OPENED"
FIRST_CLOSE_KIND = "SHADOW_CASE_FIRST_CLOSE"
OUTCOME_KIND = "SHADOW_CASE_OUTCOME"


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


class ShadowCaseStore:
    """Persist only admitted Shadow Cases and their bounded future result."""

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
        self._case_by_entry: dict[str, str] = {}
        self._opened_by_case: dict[str, Mapping[str, object]] = {}
        self._case_count = 0

    @property
    def case_count(self) -> int:
        return self._case_count

    @property
    def active_case_count(self) -> int:
        return len(self._opened_by_case)

    def case_id_for_entry(self, entry_identity: str) -> str | None:
        return self._case_by_entry.get(entry_identity)

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        kind = value.get("object_kind")
        if kind == "SHADOW_ENTRY":
            self._open_case(value, state)
        elif kind == "POSITION_ACTION":
            self._record_first_close(value)
        elif kind == "SHADOW_OUTCOME":
            self._record_outcome(value)

    def read_case(self, case_id: str, *, runtime_active: bool = False) -> ShadowCaseRead:
        require_identity(case_id, "case_id")
        case_directory = self._case_directory(case_id)
        opened = _read_json(case_directory / "opened.json")
        _validate_opened(opened, expected_case_id=case_id, bindings=self.bindings)
        first_close_path = case_directory / "first-close.json"
        outcome_path = case_directory / "outcome.json"
        first_close = _read_json(first_close_path) if first_close_path.exists() else None
        outcome = _read_json(outcome_path) if outcome_path.exists() else None
        if first_close is not None:
            _validate_followup(opened, first_close, expected_kind=FIRST_CLOSE_KIND)
        if outcome is not None:
            _validate_followup(opened, outcome, expected_kind=OUTCOME_KIND)
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
        payload = _mapping(value.get("payload"), "SHADOW_ENTRY.payload")
        entry_identity = _identity(value.get("object_identity"), "shadow_entry_identity")
        boundary = _boundary(value.get("fact_boundary"), "opened_fact_boundary")
        case_id = canonical_identity(
            "ShadowCaseIdentity",
            self.bindings.code_identity,
            self.bindings.runtime_identity,
            self.bindings.radar_policy_identity,
            self.bindings.underwriting_policy_identity,
            self.bindings.position_policy_identity,
            entry_identity,
            boundary,
        )
        candidate_identity = _identity(payload.get("candidate_identity"), "candidate_identity")
        candidate = state.get_object("CANDIDATE_ACTIVATION", candidate_identity)
        if candidate is None:
            raise ShadowCaseStoreError("Shadow Entry lacks its Candidate in current owner state")
        candidate_payload = _mapping(candidate.get("payload"), "Candidate.payload")
        action_identity = _identity(
            candidate_payload.get("underwriting_action_identity"),
            "underwriting_action_identity",
        )
        action = state.get_object("UNDERWRITING_ACTION", action_identity)
        if action is None:
            raise ShadowCaseStoreError("Shadow Entry lacks its Underwriting action")
        action_payload = _mapping(action.get("payload"), "UnderwritingAction.payload")
        opened: dict[str, object] = {
            "record_kind": OPENED_KIND,
            "schema_version": SHADOW_CASE_SCHEMA_VERSION,
            "case_id": case_id,
            **self._binding_object(),
            "shadow_case_contract_identity": self.bindings.shadow_case_contract_identity,
            "opened_fact_boundary": boundary,
            "shadow_entry_identity": entry_identity,
            "candidate_identity": candidate_identity,
            "underwriting_action_identity": action_identity,
            "decision_fact_boundary": action_payload.get("evaluation_fact_boundary"),
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
                "entry_component_quote_source_refs": payload.get(
                    "entry_component_quote_source_refs"
                ),
                "entry_component_legs": payload.get("entry_component_legs"),
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
                "action": action_payload.get("economic_action"),
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
        normalized = _normalized_mapping(opened)
        _validate_opened(normalized, expected_case_id=case_id, bindings=self.bindings)
        self._publish(case_id, "opened.json", normalized)
        self._case_by_entry[entry_identity] = case_id
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
        case_id = self._case_by_entry.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("first CLOSE belongs to an unopened Shadow Case")
        record = _normalized_mapping(
            {
                "record_kind": FIRST_CLOSE_KIND,
                "schema_version": SHADOW_CASE_SCHEMA_VERSION,
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
            self._opened_by_case[case_id],
            record,
            expected_kind=FIRST_CLOSE_KIND,
        )
        self._publish(case_id, "first-close.json", record)

    def _record_outcome(self, value: Mapping[str, object]) -> None:
        payload = _mapping(value.get("payload"), "SHADOW_OUTCOME.payload")
        entry_identity = _identity(payload.get("shadow_entry_identity"), "shadow_entry_identity")
        case_id = self._case_by_entry.get(entry_identity)
        if case_id is None:
            raise ShadowCaseStoreError("Outcome belongs to an unopened Shadow Case")
        record = _normalized_mapping(
            {
                "record_kind": OUTCOME_KIND,
                "schema_version": SHADOW_CASE_SCHEMA_VERSION,
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
                "close_component_quote_source_refs": payload.get(
                    "close_component_quote_source_refs"
                ),
                "close_component_legs": payload.get("close_component_legs"),
                "censor_mask": payload.get("censor_mask"),
                "non_claims": payload.get("non_claims"),
            }
        )
        opened = self._opened_by_case[case_id]
        _validate_followup(opened, record, expected_kind=OUTCOME_KIND)
        _validate_outcome_economics(opened, record)
        self._publish(case_id, "outcome.json", record)
        self._case_by_entry.pop(entry_identity, None)
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
) -> None:
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
        "shadow_entry_identity",
        "candidate_identity",
        "underwriting_action_identity",
        "decision_fact_boundary",
        "structure",
        "radar",
        "underwriting",
        "entry_economics",
        "non_claims",
    }
    if set(value) != required:
        raise ShadowCaseStoreError("opened record has an invalid key set")
    if (
        value.get("record_kind") != OPENED_KIND
        or value.get("schema_version") != SHADOW_CASE_SCHEMA_VERSION
    ):
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
        "shadow_entry_identity",
        "candidate_identity",
        "underwriting_action_identity",
    ):
        _identity(value.get(field), field)
    opened_boundary = FactBoundary.from_object(
        _boundary(value.get("opened_fact_boundary"), "opened_fact_boundary")
    )
    if (
        opened_boundary.code_identity != bindings.code_identity
        or opened_boundary.runtime_identity != bindings.runtime_identity
    ):
        raise ShadowCaseStoreError("opened FactBoundary binding mismatch")
    recomputed_case_id = canonical_identity(
        "ShadowCaseIdentity",
        bindings.code_identity,
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        value.get("shadow_entry_identity"),
        opened_boundary,
    )
    if recomputed_case_id != expected_case_id:
        raise ShadowCaseStoreError("opened record Case identity mismatch")
    structure = _mapping(value.get("structure"), "structure")
    _exact_keys(
        structure,
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
            "entry_component_quote_source_refs",
            "entry_component_legs",
        },
        "opened structure",
    )
    if structure.get("execution_model") != "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL":
        raise ShadowCaseStoreError("opened execution_model is invalid")
    leg_identities = _sequence(
        structure.get("canonical_leg_identities"), "canonical_leg_identities"
    )
    if len(leg_identities) != 2:
        raise ShadowCaseStoreError("opened structure must contain exactly two leg identities")
    for index, identity in enumerate(leg_identities):
        _identity(identity, f"canonical_leg_identities[{index}]")
    for field in ("short_leg_instrument_name", "long_leg_instrument_name"):
        _text(structure.get(field), field)
    expiry_ms = structure.get("expiry_ms")
    if isinstance(expiry_ms, bool) or not isinstance(expiry_ms, int) or expiry_ms <= 0:
        raise ShadowCaseStoreError("expiry_ms must be a positive integer")
    if structure.get("option_type") not in {"call", "put"}:
        raise ShadowCaseStoreError("option_type is invalid")
    if structure.get("entry_direction") != "SELL":
        raise ShadowCaseStoreError("entry_direction is invalid")
    _decimal(structure.get("short_strike_usdc_per_btc"), "short_strike_usdc_per_btc")
    _decimal(structure.get("long_strike_usdc_per_btc"), "long_strike_usdc_per_btc")
    quantity = _decimal(structure.get("full_quantity_btc"), "full_quantity_btc")
    if quantity <= 0:
        raise ShadowCaseStoreError("opened quantity must be positive")
    _identity(
        structure.get("entry_component_pair_identity"),
        "entry_component_pair_identity",
    )
    _validate_component_source_refs(
        structure.get("entry_component_quote_source_refs"),
        owner_boundary=opened_boundary,
        field="entry_component_quote_source_refs",
    )
    entry_component_gross, entry_component_fee = _validate_component_legs(
        structure.get("entry_component_legs"),
        quantity=quantity,
        short_name=_text(
            structure.get("short_leg_instrument_name"),
            "short_leg_instrument_name",
        ),
        long_name=_text(
            structure.get("long_leg_instrument_name"),
            "long_leg_instrument_name",
        ),
        expected_actions=("SELL", "BUY"),
        field="entry_component_legs",
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
        {
            "action",
            "minimum_net_entry_credit_usdc",
            "minimum_net_credit_to_payoff_cap_fraction",
            "maximum_underwriting_reserved_loss_usdc",
            "maximum_entry_consumed_level_count",
        },
        "opened underwriting",
    )
    if underwriting.get("action") != "CANDIDATE":
        raise ShadowCaseStoreError("opened Underwriting action is invalid")
    for field in (
        "minimum_net_entry_credit_usdc",
        "minimum_net_credit_to_payoff_cap_fraction",
        "maximum_underwriting_reserved_loss_usdc",
    ):
        _decimal(underwriting.get(field), field)
    maximum_levels = underwriting.get("maximum_entry_consumed_level_count")
    if (
        isinstance(maximum_levels, bool)
        or not isinstance(maximum_levels, int)
        or maximum_levels <= 0
    ):
        raise ShadowCaseStoreError("maximum_entry_consumed_level_count must be positive")

    economics = _mapping(value.get("entry_economics"), "entry_economics")
    _exact_keys(
        economics,
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
        "entry_economics",
    )
    gross_entry = _decimal(economics.get("gross_entry_credit_usdc"), "gross entry credit")
    if gross_entry <= 0:
        raise ShadowCaseStoreError("opened gross entry credit must be positive")
    entry_fee = _decimal(economics.get("entry_fee_reserve_usdc"), "entry fee reserve")
    net_entry = _decimal(economics.get("net_entry_credit_usdc"), "net entry credit")
    if net_entry != gross_entry - entry_fee:
        raise ShadowCaseStoreError("opened entry economics do not conserve")
    if gross_entry != entry_component_gross or entry_fee != entry_component_fee:
        raise ShadowCaseStoreError("opened entry economics do not match component legs")
    width = _decimal(economics.get("width_usdc_per_btc"), "width_usdc_per_btc")
    payoff_cap = _decimal(economics.get("payoff_cap_usdc"), "payoff_cap_usdc")
    contractual = _decimal(
        economics.get("contractual_payoff_max_loss_ex_fees_usdc"),
        "contractual_payoff_max_loss_ex_fees_usdc",
    )
    fee_reserved = _decimal(
        economics.get("entry_fee_reserved_payoff_loss_usdc"),
        "entry_fee_reserved_payoff_loss_usdc",
    )
    if width <= 0 or payoff_cap != width * quantity:
        raise ShadowCaseStoreError("opened vertical width/payoff cap do not conserve")
    if contractual != max(Decimal(0), payoff_cap - gross_entry):
        raise ShadowCaseStoreError("opened contractual maximum loss does not conserve")
    if fee_reserved != max(Decimal(0), payoff_cap - net_entry):
        raise ShadowCaseStoreError("opened fee-reserved maximum loss does not conserve")
    for field in ("future_cost_reserve_usdc", "underwriting_reserved_loss_usdc"):
        _decimal(economics.get(field), field)
    non_claims = _string_sequence(value.get("non_claims"), "non_claims")
    if non_claims != (
        "NOT_AN_ORDER",
        "NOT_A_FILL",
        "NOT_AN_ATOMIC_QUOTE",
        "NO_LIQUIDITY_RESERVATION",
        "ATOMIC_EXECUTABILITY_UNPROVEN",
    ):
        raise ShadowCaseStoreError("opened component non_claims are invalid")

    decision_boundary = FactBoundary.from_object(
        _boundary(value.get("decision_fact_boundary"), "decision_fact_boundary")
    )
    if (
        decision_boundary.code_identity != bindings.code_identity
        or decision_boundary.runtime_identity != bindings.runtime_identity
        or not opened_boundary.is_strictly_after(decision_boundary)
    ):
        raise ShadowCaseStoreError("decision FactBoundary binding/order mismatch")


def _validate_followup(
    opened: Mapping[str, object],
    value: Mapping[str, object],
    *,
    expected_kind: str,
) -> None:
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
    _exact_keys(value, expected_keys, "Case follow-up")
    if (
        value.get("record_kind") != expected_kind
        or value.get("schema_version") != SHADOW_CASE_SCHEMA_VERSION
    ):
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
            close_component_gross, close_component_fee = _validate_component_legs(
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
            )
            if (
                _decimal(value.get("gross_close_cashflow_usdc"), "gross close cashflow")
                != close_component_gross
                or _decimal(value.get("close_fee_reserve_usdc"), "close fee reserve")
                != close_component_fee
            ):
                raise ShadowCaseStoreError("Outcome economics do not match component close legs")
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
    economic_fields = (
        "gross_close_cashflow_usdc",
        "close_fee_reserve_usdc",
        "net_close_cashflow_usdc",
        "gross_pnl_usdc",
        "total_public_fee_reserve_usdc",
        "net_pnl_after_public_standard_fee_reserve_usdc",
        "net_loss_usdc",
    )
    if state != "MATURE_KNOWN":
        if any(outcome.get(field) is not None for field in economic_fields):
            raise ShadowCaseStoreError("unknown/censored Outcome carries known economics")
        if outcome.get("economic_availability") != "UNKNOWN":
            raise ShadowCaseStoreError("unknown/censored Outcome availability is invalid")
        return
    if outcome.get("economic_availability") != "KNOWN":
        raise ShadowCaseStoreError("known Outcome availability is invalid")
    entry = _mapping(opened.get("entry_economics"), "entry_economics")
    gross_entry = _decimal(entry.get("gross_entry_credit_usdc"), "gross entry")
    entry_fee = _decimal(entry.get("entry_fee_reserve_usdc"), "entry fee")
    gross_close = _decimal(outcome.get("gross_close_cashflow_usdc"), "gross close")
    close_fee = _decimal(outcome.get("close_fee_reserve_usdc"), "close fee")
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
        if _decimal(outcome.get(field), field) != expected_value:
            raise ShadowCaseStoreError(f"Outcome arithmetic mismatch: {field}")


def _normalized_mapping(value: Mapping[str, object]) -> dict[str, object]:
    normalized = canonical_value(value)
    if not isinstance(normalized, dict):
        raise ShadowCaseStoreError("Shadow Case record must be an object")
    return normalized


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


def _levels_amount(levels: Sequence[object]) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"level[{index}]")
        _exact_keys(level, {"amount_btc", "price_usdc_per_btc"}, f"level[{index}]")
        amount = _decimal(level.get("amount_btc"), f"level[{index}].amount_btc")
        price = _decimal(level.get("price_usdc_per_btc"), f"level[{index}].price_usdc_per_btc")
        if amount <= 0 or price <= 0:
            raise ShadowCaseStoreError("consumed level amount and price must be positive")
        total += amount
    return total


def _validate_component_source_refs(
    value: object,
    *,
    owner_boundary: FactBoundary,
    field: str,
) -> None:
    refs = _sequence(value, field)
    if len(refs) != 2:
        raise ShadowCaseStoreError("component entry requires exactly two quote source refs")
    for expected_role, raw in zip(("SHORT", "LONG"), refs, strict=True):
        ref = _mapping(raw, f"{expected_role} component quote source ref")
        _exact_keys(
            ref,
            {"canonical_leg_role", "source_identity", "receipt_fact_boundary"},
            f"{expected_role} component quote source ref",
        )
        if ref.get("canonical_leg_role") != expected_role:
            raise ShadowCaseStoreError("component quote source role/order is invalid")
        _identity(ref.get("source_identity"), "component quote source identity")
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


def _validate_component_legs(
    value: object,
    *,
    quantity: Decimal,
    short_name: str,
    long_name: str,
    expected_actions: tuple[str, str],
    field: str,
) -> tuple[Decimal, Decimal]:
    legs = _sequence(value, field)
    if len(legs) != 2:
        raise ShadowCaseStoreError("component entry requires exactly two leg quotes")
    expected = (
        ("SHORT", expected_actions[0], short_name),
        ("LONG", expected_actions[1], long_name),
    )
    gross_cashflow = Decimal(0)
    total_fee = Decimal(0)
    for raw, (role, action, instrument_name) in zip(legs, expected, strict=True):
        leg = _mapping(raw, f"{role} component leg")
        _exact_keys(
            leg,
            {
                "canonical_leg_role",
                "instrument_name",
                "action",
                "raw_consumed_levels",
                "raw_vwap_usdc_per_btc",
                "stressed_consumed_levels",
                "stressed_vwap_usdc_per_btc",
                "fee_reserve_usdc",
            },
            f"{role} component leg",
        )
        if (
            leg.get("canonical_leg_role") != role
            or leg.get("action") != action
            or leg.get("instrument_name") != instrument_name
        ):
            raise ShadowCaseStoreError("component leg role/action/instrument is invalid")
        raw_levels = _sequence(leg.get("raw_consumed_levels"), "raw_consumed_levels")
        stressed_levels = _sequence(
            leg.get("stressed_consumed_levels"),
            "stressed_consumed_levels",
        )
        if _levels_amount(raw_levels) != quantity or _levels_amount(stressed_levels) != quantity:
            raise ShadowCaseStoreError("component leg levels do not cover full quantity")
        raw_vwap = _decimal(leg.get("raw_vwap_usdc_per_btc"), "raw component VWAP")
        stressed_vwap = _decimal(
            leg.get("stressed_vwap_usdc_per_btc"),
            "stressed component VWAP",
        )
        fee = _decimal(leg.get("fee_reserve_usdc"), "component fee reserve")
        if raw_vwap <= 0 or stressed_vwap <= 0 or fee < 0:
            raise ShadowCaseStoreError("component leg economics must be non-negative")
        if raw_vwap * quantity != _levels_value(
            raw_levels
        ) or stressed_vwap * quantity != _levels_value(stressed_levels):
            raise ShadowCaseStoreError("component leg VWAP does not match consumed levels")
        if (action == "SELL" and stressed_vwap > raw_vwap) or (
            action == "BUY" and stressed_vwap < raw_vwap
        ):
            raise ShadowCaseStoreError("component stress direction is not conservative")
        gross_cashflow += (
            stressed_vwap * quantity if action == "SELL" else -stressed_vwap * quantity
        )
        total_fee += fee
    return gross_cashflow, total_fee


def _levels_value(levels: Sequence[object]) -> Decimal:
    total = Decimal(0)
    for index, raw in enumerate(levels):
        level = _mapping(raw, f"level[{index}]")
        total += _decimal(level.get("amount_btc"), "amount_btc") * _decimal(
            level.get("price_usdc_per_btc"), "price_usdc_per_btc"
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
