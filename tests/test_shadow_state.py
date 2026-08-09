from __future__ import annotations

from collections.abc import Mapping

import pytest
from short_vol_underwriting.evidence import (
    RuntimeBindings,
    ShadowStateError,
    ShadowStateStore,
)
from short_vol_underwriting.identity import canonical_identity
from short_vol_underwriting.model import FactBoundary

CODE_IDENTITY = "a" * 40
RUNTIME_IDENTITY = "sha256:" + "b" * 64
RADAR_POLICY_IDENTITY = "sha256:" + "c" * 64
UNDERWRITING_POLICY_IDENTITY = "sha256:" + "d" * 64
POSITION_POLICY_IDENTITY = "sha256:" + "e" * 64


class _RecordingObserver:
    def __init__(self) -> None:
        self.records: list[Mapping[str, object]] = []

    def on_record(
        self,
        value: Mapping[str, object],
        state: ShadowStateStore,
    ) -> None:
        del state
        self.records.append(value)


def _bindings() -> RuntimeBindings:
    return RuntimeBindings(
        code_identity=CODE_IDENTITY,
        runtime_identity=RUNTIME_IDENTITY,
        radar_policy_identity=RADAR_POLICY_IDENTITY,
        underwriting_policy_identity=UNDERWRITING_POLICY_IDENTITY,
        position_policy_identity=POSITION_POLICY_IDENTITY,
    )


def _boundary(causal_seq: int) -> FactBoundary:
    return FactBoundary(
        code_identity=CODE_IDENTITY,
        runtime_identity=RUNTIME_IDENTITY,
        session_epoch=1,
        ingress_seq=causal_seq,
        received_monotonic_ms=100 + causal_seq,
        causal_seq=causal_seq,
    )


def test_restore_current_record_is_visible_without_replaying_record_effects() -> None:
    observer = _RecordingObserver()
    state = ShadowStateStore(bindings=_bindings(), observer=observer)
    entry_identity = canonical_identity("ShadowEntry", "restored")

    state.restore_current_record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=_boundary(1),
        payload={"shadow_entry_identity": entry_identity},
    )

    restored = state.get_object("SHADOW_ENTRY", entry_identity)
    assert restored is not None
    assert restored["runtime_identity"] == RUNTIME_IDENTITY
    assert restored["fact_boundary"] == _boundary(1).as_object()
    assert state.objects == (restored,)
    assert state.retained_case_count == 1
    assert state.revision == 1
    assert state.take_pending_records() == ()
    assert observer.records == []

    first_evaluation = canonical_identity("PositionEvaluation", entry_identity, 2)
    state.record(
        object_kind="POSITION_EVALUATION",
        object_identity=first_evaluation,
        fact_boundary=_boundary(2),
        payload={"shadow_entry_identity": entry_identity, "position_state": "UNKNOWN"},
    )
    assert state.get_object("POSITION_EVALUATION", first_evaluation) is not None
    assert [record["object_identity"] for record in state.take_pending_records()] == [
        first_evaluation
    ]
    assert [record["object_identity"] for record in observer.records] == [first_evaluation]

    second_evaluation = canonical_identity("PositionEvaluation", entry_identity, 3)
    state.record(
        object_kind="POSITION_EVALUATION",
        object_identity=second_evaluation,
        fact_boundary=_boundary(3),
        payload={"shadow_entry_identity": entry_identity, "position_state": "HOLD"},
    )
    assert state.get_object("SHADOW_ENTRY", entry_identity) is restored
    assert state.get_object("POSITION_EVALUATION", first_evaluation) is None
    assert state.get_object("POSITION_EVALUATION", second_evaluation) is not None
    assert state.retained_case_count == 1


def test_restore_current_record_rejects_a_conflicting_identity_without_side_effects() -> None:
    observer = _RecordingObserver()
    state = ShadowStateStore(bindings=_bindings(), observer=observer)
    entry_identity = canonical_identity("ShadowEntry", "conflict")
    original_payload = {"shadow_entry_identity": entry_identity, "position_state": "UNKNOWN"}
    state.restore_current_record(
        object_kind="SHADOW_ENTRY",
        object_identity=entry_identity,
        fact_boundary=_boundary(1),
        payload=original_payload,
    )
    snapshot = state.objects

    with pytest.raises(ShadowStateError, match="conflicting in-memory object"):
        state.restore_current_record(
            object_kind="SHADOW_ENTRY",
            object_identity=entry_identity,
            fact_boundary=_boundary(2),
            payload={"shadow_entry_identity": entry_identity, "position_state": "HOLD"},
        )

    assert state.objects is snapshot
    assert state.get_object("SHADOW_ENTRY", entry_identity) == snapshot[0]
    assert state.revision == 1
    assert state.take_pending_records() == ()
    assert observer.records == []
