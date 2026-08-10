from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from short_vol_underwriting.constants import ALL_DOWNSTREAM_OBJECT_KINDS
from short_vol_underwriting.identity import (
    canonical_identity,
    canonical_value,
    require_code_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary


class ShadowStateError(ValueError):
    """One in-memory Shadow owner record is invalid."""


@dataclass(frozen=True)
class RuntimeBindings:
    code_identity: str
    runtime_identity: str
    radar_policy_identity: str
    underwriting_policy_identity: str
    position_policy_identity: str

    def __post_init__(self) -> None:
        try:
            require_code_identity(self.code_identity)
            for field in (
                "runtime_identity",
                "radar_policy_identity",
                "underwriting_policy_identity",
                "position_policy_identity",
            ):
                require_identity(getattr(self, field), field)
        except ValueError as exc:
            raise ShadowStateError(str(exc)) from exc

    @property
    def shadow_case_contract_identity(self) -> str:
        """Semantic code/Policy binding; Markdown bytes never enter runtime identity."""
        return canonical_identity(
            "ShadowCaseContractIdentity",
            "SHORT_VOL_SHADOW_CASE",
            self.code_identity,
            self.radar_policy_identity,
            self.underwriting_policy_identity,
            self.position_policy_identity,
        )

    @property
    def outcome_contract_identity(self) -> str:
        """Internal Outcome reducer binding retained without a document-byte digest."""
        return self.shadow_case_contract_identity


class ShadowStateObserver(Protocol):
    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None: ...


type _ObjectKey = tuple[str, str]


class ShadowStateStore:
    """Bounded current owner projection; completed history belongs only to Shadow Case files."""

    def __init__(
        self,
        *,
        bindings: RuntimeBindings,
        observer: ShadowStateObserver | None = None,
    ) -> None:
        self.bindings = bindings
        self.observer = observer
        self._objects: dict[_ObjectKey, dict[str, object]] = {}
        self._object_snapshot: tuple[Mapping[str, object], ...] | None = ()
        self._pending_records: list[Mapping[str, object]] = []
        self._revision = 0

        self._scope_keys: dict[str, dict[str, _ObjectKey]] = {}
        self._candidate_keys: dict[str, dict[str, _ObjectKey]] = {}
        self._control_keys: dict[str, dict[str, _ObjectKey]] = {}
        self._entry_keys: dict[str, dict[str, _ObjectKey]] = {}
        self._scope_by_availability: dict[str, str] = {}
        self._candidate_by_admission_attempt: dict[str, str] = {}
        self._entry_by_observation: dict[str, str] = {}
        self._entry_by_post_close_attempt: dict[str, str] = {}
        self._latest_terminal_entry: str | None = None
        self._latest_terminal_control_batch: str | None = None

    @property
    def objects(self) -> tuple[Mapping[str, object], ...]:
        if self._object_snapshot is None:
            self._object_snapshot = tuple(self._objects[key] for key in sorted(self._objects))
        return self._object_snapshot

    def get_object(self, object_kind: str, object_identity: str) -> Mapping[str, object] | None:
        return self._objects.get((object_kind, object_identity))

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def retained_object_count(self) -> int:
        return len(self._objects)

    @property
    def active_scope_count(self) -> int:
        return len(self._scope_keys)

    @property
    def active_candidate_count(self) -> int:
        return len(self._candidate_keys)

    @property
    def retained_case_count(self) -> int:
        return len(self._entry_keys)

    @property
    def retained_state_counts(self) -> Mapping[str, int]:
        return {
            "objects": len(self._objects),
            "pending_records": len(self._pending_records),
            "active_scopes": len(self._scope_keys),
            "active_candidates": len(self._candidate_keys),
            "active_or_latest_terminal_control_batches": len(self._control_keys),
            "active_or_latest_terminal_cases": len(self._entry_keys),
            "availability_bindings": len(self._scope_by_availability),
            "admission_attempt_bindings": len(self._candidate_by_admission_attempt),
            "observation_bindings": len(self._entry_by_observation),
            "post_close_attempt_bindings": len(self._entry_by_post_close_attempt),
            "latest_terminal_cases": int(self._latest_terminal_entry is not None),
            "latest_terminal_control_batches": int(self._latest_terminal_control_batch is not None),
        }

    def take_pending_records(self) -> tuple[Mapping[str, object], ...]:
        records = tuple(self._pending_records)
        self._pending_records.clear()
        return records

    def record(
        self,
        *,
        object_kind: str,
        object_identity: str,
        fact_boundary: FactBoundary,
        payload: Mapping[str, object],
    ) -> None:
        self._store_current_record(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
            publish=True,
        )

    def restore_current_record(
        self,
        *,
        object_kind: str,
        object_identity: str,
        fact_boundary: FactBoundary,
        payload: Mapping[str, object],
        replace_existing: bool = False,
    ) -> None:
        """Rehydrate current state without pending records or observer notification."""
        self._store_current_record(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
            publish=False,
            replace_existing=replace_existing,
        )

    def _store_current_record(
        self,
        *,
        object_kind: str,
        object_identity: str,
        fact_boundary: FactBoundary,
        payload: Mapping[str, object],
        publish: bool,
        replace_existing: bool = False,
    ) -> None:
        value = build_current_shadow_object(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
            bindings=self.bindings,
        )
        key = (object_kind, object_identity)
        previous = self._objects.get(key)
        if previous is not None and previous != value and not replace_existing:
            raise ShadowStateError(f"conflicting in-memory object: {object_kind}/{object_identity}")
        if previous is None and replace_existing:
            raise ShadowStateError(
                f"cannot replace absent in-memory object: {object_kind}/{object_identity}"
            )
        if previous == value:
            return

        owner_kind, owner_identity = self._current_owner(object_kind, object_identity, value)
        if owner_kind is not None and owner_identity is not None:
            owner_index = self._owner_index(owner_kind)
            current_by_kind = owner_index.setdefault(owner_identity, {})
            old_key = current_by_kind.get(object_kind)
            if old_key is not None and old_key != key:
                self._objects.pop(old_key, None)
            current_by_kind[object_kind] = key

        self._objects[key] = value
        self._revision += 1
        self._object_snapshot = None
        if publish:
            self._pending_records.append(value)
            if self.observer is not None:
                self.observer.on_record(value, self)

    def retire_scope(self, scope_identity: str) -> None:
        self._retire_owner("scope", scope_identity)

    def retire_candidate(self, candidate_identity: str) -> None:
        self._retire_owner("candidate", candidate_identity)
        for attempt, candidate in tuple(self._candidate_by_admission_attempt.items()):
            if candidate == candidate_identity:
                self._candidate_by_admission_attempt.pop(attempt, None)

    def retire_control_batch(self, batch_identity: str) -> None:
        self._retire_owner("control", batch_identity)

    def retain_latest_terminal_control_batch(self, batch_identity: str) -> None:
        previous = self._latest_terminal_control_batch
        if previous is not None and previous != batch_identity:
            self._retire_owner("control", previous)
        self._latest_terminal_control_batch = batch_identity

    def retain_latest_terminal_case(self, entry_identity: str) -> None:
        previous = self._latest_terminal_entry
        if previous is not None and previous != entry_identity:
            self._retire_owner("entry", previous)
        self._latest_terminal_entry = entry_identity

    def _current_owner(
        self,
        kind: str,
        identity: str,
        value: Mapping[str, object],
    ) -> tuple[str | None, str | None]:
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ShadowStateError("current Shadow payload must be an object")

        if kind == "UNDERWRITING_AVAILABILITY_EVALUATION":
            scope = _required_text(payload, "radar_scope_or_short_leg_identity")
            prior = self._scope_keys.get(scope, {}).get(kind)
            if prior is not None and prior[1] != identity:
                self._scope_by_availability.pop(prior[1], None)
            self._scope_by_availability[identity] = scope
            return "scope", scope
        if kind == "UNDERWRITING_ACTION":
            availability = _required_text(
                payload,
                "underwriting_availability_evaluation_identity",
            )
            owner_scope = self._scope_by_availability.get(availability)
            if owner_scope is None:
                raise ShadowStateError("Underwriting action lacks its current availability scope")
            return "scope", owner_scope

        if kind == "CANDIDATE_ACTIVATION":
            return "candidate", identity
        if kind == "ADMISSION_ATTEMPT_SCHEDULED":
            candidate = _required_text(payload, "candidate_identity")
            self._candidate_by_admission_attempt[identity] = candidate
            return "candidate", candidate
        if kind == "ADMISSION_ATTEMPT_TERMINAL":
            selection = payload.get("selected_underwriting_decision_identity")
            batch = payload.get("activation_batch_identity")
            if isinstance(selection, str) and selection and isinstance(batch, str) and batch:
                return "control", batch
            return "candidate", _required_text(payload, "candidate_identity")
        if kind == "CANDIDATE_INVALIDATION":
            return "candidate", _required_text(payload, "candidate_identity")

        if kind == "UNDERWRITING_DECISION_BATCH_DESIGNATION":
            return "control", _required_text(payload, "activation_batch_identity")
        if kind in {
            "SELECTED_UNDERWRITING_DECISION",
            "UNDERWRITING_DECISION_CONTROL_ATTEMPT_SCHEDULED",
            "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
        }:
            return "control", _required_text(payload, "activation_batch_identity")

        if kind in {
            "SHADOW_ENTRY",
            "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OPEN",
        }:
            return "entry", identity
        if kind == "SHADOW_OUTCOME_OBSERVATION":
            entry = _required_text(payload, "shadow_entry_identity")
            self._entry_by_observation[identity] = entry
            return "entry", entry
        if kind in {"POSITION_EVALUATION", "POSITION_ACTION", "CLOSE_QUOTE_EVALUATION"}:
            return "entry", _required_text(payload, "shadow_entry_identity")
        if kind == "POST_CLOSE_ATTEMPT_SCHEDULED":
            entry = _required_text(payload, "shadow_entry_identity")
            self._entry_by_post_close_attempt[identity] = entry
            return "entry", entry
        if kind == "POST_CLOSE_ATTEMPT_TERMINAL":
            scheduled = _required_text(payload, "scheduled_post_close_attempt_identity")
            owner_entry = self._entry_by_post_close_attempt.get(scheduled)
            if owner_entry is None:
                raise ShadowStateError("post-CLOSE terminal lacks its current Case")
            return "entry", owner_entry
        if kind in {
            "CLOSE_OPPORTUNITY_EVALUATION",
            "SHADOW_CLOSE_OPPORTUNITY",
            "SHADOW_OUTCOME",
            "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME",
            "RADAR_SCORE_BAND_NO_TRADE_CONTROL_OUTCOME",
        }:
            return "entry", _required_text(payload, "shadow_entry_identity")
        if kind == "SHADOW_COUNTERFACTUAL_EXIT":
            observation = _required_text(payload, "shadow_observation_identity")
            owner_entry = self._entry_by_observation.get(observation)
            if owner_entry is None:
                raise ShadowStateError("selected exit lacks its current Case observation")
            return "entry", owner_entry
        return None, None

    def _owner_index(self, owner_kind: str) -> dict[str, dict[str, _ObjectKey]]:
        if owner_kind == "scope":
            return self._scope_keys
        if owner_kind == "candidate":
            return self._candidate_keys
        if owner_kind == "control":
            return self._control_keys
        if owner_kind == "entry":
            return self._entry_keys
        raise RuntimeError("unknown current-state owner kind")

    def _retire_owner(self, owner_kind: str, owner_identity: str) -> None:
        owner_index = self._owner_index(owner_kind)
        keys = owner_index.pop(owner_identity, None)
        if not keys:
            return
        for key in keys.values():
            self._objects.pop(key, None)
        if owner_kind == "scope":
            for availability, scope in tuple(self._scope_by_availability.items()):
                if scope == owner_identity:
                    self._scope_by_availability.pop(availability, None)
        elif owner_kind == "entry":
            for observation, entry in tuple(self._entry_by_observation.items()):
                if entry == owner_identity:
                    self._entry_by_observation.pop(observation, None)
            for attempt, entry in tuple(self._entry_by_post_close_attempt.items()):
                if entry == owner_identity:
                    self._entry_by_post_close_attempt.pop(attempt, None)
            if self._latest_terminal_entry == owner_identity:
                self._latest_terminal_entry = None
        elif owner_kind == "control":
            if self._latest_terminal_control_batch == owner_identity:
                self._latest_terminal_control_batch = None
        self._revision += 1
        self._object_snapshot = None


def _required_text(value: Mapping[str, object], field: str) -> str:
    member = value.get(field)
    if not isinstance(member, str) or not member:
        raise ShadowStateError(f"{field} must be a non-empty string")
    return member


def build_current_shadow_object(
    *,
    object_kind: str,
    object_identity: str,
    fact_boundary: FactBoundary,
    payload: Mapping[str, object],
    bindings: RuntimeBindings,
) -> dict[str, object]:
    if object_kind not in ALL_DOWNSTREAM_OBJECT_KINDS:
        raise ShadowStateError("unknown current Shadow object kind")
    try:
        require_identity(object_identity, "object_identity")
    except ValueError as exc:
        raise ShadowStateError(str(exc)) from exc
    if (
        fact_boundary.code_identity != bindings.code_identity
        or fact_boundary.runtime_identity != bindings.runtime_identity
    ):
        raise ShadowStateError("FactBoundary does not belong to this current state")
    normalized_payload = canonical_value(payload)
    if not isinstance(normalized_payload, dict):
        raise ShadowStateError("payload must be an object")
    return {
        "object_kind": object_kind,
        "object_identity": object_identity,
        "code_identity": bindings.code_identity,
        "runtime_identity": bindings.runtime_identity,
        "radar_policy_identity": bindings.radar_policy_identity,
        "underwriting_policy_identity": bindings.underwriting_policy_identity,
        "position_policy_identity": bindings.position_policy_identity,
        "fact_boundary": fact_boundary.as_object(),
        "payload": normalized_payload,
    }
