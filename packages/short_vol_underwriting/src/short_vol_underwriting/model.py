from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from short_vol_underwriting.constants import POSITION_CLOSE_REASONS
from short_vol_underwriting.identity import require_code_identity, require_identity


class PredicateTruth(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class OutcomeState(StrEnum):
    PENDING = "PENDING"
    MATURE_KNOWN = "MATURE_KNOWN"
    MATURE_UNKNOWN = "MATURE_UNKNOWN"
    CENSORED_AT_STOP = "CENSORED_AT_STOP"
    CENSORED_AT_FAILURE = "CENSORED_AT_FAILURE"


class ObservationQuality(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    GAPPED = "GAPPED"


class TerminalSource(StrEnum):
    STOP = "STOP"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class FactBoundary:
    code_identity: str
    runtime_identity: str
    session_epoch: int
    ingress_seq: int
    received_monotonic_ms: int
    causal_seq: int

    def __post_init__(self) -> None:
        require_code_identity(self.code_identity)
        require_identity(self.runtime_identity, "runtime_identity")
        for field in (
            "session_epoch",
            "ingress_seq",
            "received_monotonic_ms",
            "causal_seq",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")

    def as_object(self) -> dict[str, object]:
        return {
            "code_identity": self.code_identity,
            "runtime_identity": self.runtime_identity,
            "session_epoch": self.session_epoch,
            "ingress_seq": self.ingress_seq,
            "received_monotonic_ms": self.received_monotonic_ms,
            "causal_seq": self.causal_seq,
        }

    def is_strictly_after(self, other: FactBoundary) -> bool:
        self._require_same_runtime(other)
        return self.causal_seq > other.causal_seq

    def _require_same_runtime(self, other: FactBoundary) -> None:
        if (
            self.code_identity != other.code_identity
            or self.runtime_identity != other.runtime_identity
        ):
            raise ValueError("FactBoundary runtime/code identity mismatch")

    @classmethod
    def from_object(cls, value: object) -> FactBoundary:
        if not isinstance(value, dict):
            raise ValueError("FactBoundary must be an object")
        expected = {
            "code_identity",
            "runtime_identity",
            "session_epoch",
            "ingress_seq",
            "received_monotonic_ms",
            "causal_seq",
        }
        if set(value) != expected:
            raise ValueError("FactBoundary requires exact keys")
        integers: dict[str, int] = {}
        for field in ("session_epoch", "ingress_seq", "received_monotonic_ms", "causal_seq"):
            member = value[field]
            if isinstance(member, bool) or not isinstance(member, int):
                raise ValueError(f"FactBoundary.{field} must be an integer")
            integers[field] = member
        return cls(
            code_identity=str(value["code_identity"]),
            runtime_identity=str(value["runtime_identity"]),
            session_epoch=integers["session_epoch"],
            ingress_seq=integers["ingress_seq"],
            received_monotonic_ms=integers["received_monotonic_ms"],
            causal_seq=integers["causal_seq"],
        )


@dataclass(frozen=True)
class CaseFactBoundary:
    """One Case-local ordering point over a runtime-owned fact boundary."""

    segment_sequence: int
    fact_boundary: FactBoundary

    def __post_init__(self) -> None:
        if (
            isinstance(self.segment_sequence, bool)
            or not isinstance(self.segment_sequence, int)
            or self.segment_sequence < 0
        ):
            raise ValueError("segment_sequence must be a non-negative integer")

    def as_object(self) -> dict[str, object]:
        return {
            "segment_sequence": self.segment_sequence,
            "fact_boundary": self.fact_boundary.as_object(),
        }

    def is_strictly_after(self, other: CaseFactBoundary) -> bool:
        if self.segment_sequence == other.segment_sequence:
            return self.fact_boundary.is_strictly_after(other.fact_boundary)
        return self.segment_sequence > other.segment_sequence


@dataclass(frozen=True)
class PositionDecisionRecoverySeed:
    """Durable first-CLOSE state needed to continue one Position Policy."""

    first_latched_close_action_identity: str | None = None
    ordered_latched_close_reason_vector: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reasons = self.ordered_latched_close_reason_vector
        if not isinstance(reasons, tuple):
            raise ValueError("ordered_latched_close_reason_vector must be a tuple")
        ordered = tuple(reason for reason in POSITION_CLOSE_REASONS if reason in reasons)
        if reasons != ordered or len(set(reasons)) != len(reasons):
            raise ValueError("latched CLOSE reasons must be unique and canonically ordered")
        if self.first_latched_close_action_identity is None:
            if reasons:
                raise ValueError("latched CLOSE reasons require the first CLOSE identity")
        else:
            require_identity(
                self.first_latched_close_action_identity,
                "first_latched_close_action_identity",
            )
            if not reasons:
                raise ValueError("first CLOSE identity requires at least one latched reason")

    def as_object(self) -> dict[str, object]:
        return {
            "first_latched_close_action_identity": self.first_latched_close_action_identity,
            "ordered_latched_close_reason_vector": list(self.ordered_latched_close_reason_vector),
        }
