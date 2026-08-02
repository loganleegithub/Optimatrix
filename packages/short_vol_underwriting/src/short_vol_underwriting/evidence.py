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


class ShadowStateStore:
    """Current in-memory owner state; never writes pre-Shadow records to disk."""

    def __init__(
        self,
        *,
        bindings: RuntimeBindings,
        observer: ShadowStateObserver | None = None,
    ) -> None:
        self.bindings = bindings
        self.observer = observer
        self._objects: dict[tuple[str, str], dict[str, object]] = {}
        self._object_snapshot: tuple[Mapping[str, object], ...] | None = ()
        self._pending_records: list[Mapping[str, object]] = []
        self._revision = 0

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
        value = build_current_shadow_object(
            object_kind=object_kind,
            object_identity=object_identity,
            fact_boundary=fact_boundary,
            payload=payload,
            bindings=self.bindings,
        )
        key = (object_kind, object_identity)
        previous = self._objects.get(key)
        if previous is not None and previous != value:
            raise ShadowStateError(f"conflicting in-memory object: {object_kind}/{object_identity}")
        if previous == value:
            return
        self._objects[key] = value
        self._pending_records.append(value)
        self._revision += 1
        self._object_snapshot = None
        if self.observer is not None:
            self.observer.on_record(value, self)


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
