from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from short_vol_underwriting.domain import AdmissionTerminalOutcome
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary


class RefreshClassification(StrEnum):
    COMPLETE_CANDIDATE = "COMPLETE_CANDIDATE"
    COMPLETE_NO_ENTRY = "COMPLETE_NO_ENTRY"
    KNOWN_INVALIDATED = "KNOWN_INVALIDATED"
    UNKNOWN = "UNKNOWN"


class AdmissionRefreshKind(StrEnum):
    SUBSCRIPTION = "SUBSCRIPTION"
    RPC = "RPC"


def _require_non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class SubscriptionAdmissionRefreshWitness:
    """Exact official subscription snapshot/change provenance."""

    source_identity: str
    boundary: FactBoundary
    canonical_combo_identity: str
    instrument_name: str
    change_id: int
    source_timestamp_ms: int
    snapshot_kind: str
    session_epoch: int
    subscription_generation: int
    prev_change_id: int | None = None

    @property
    def kind(self) -> AdmissionRefreshKind:
        return AdmissionRefreshKind.SUBSCRIPTION

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")
        require_identity(self.canonical_combo_identity, "canonical_combo_identity")
        if not self.instrument_name:
            raise ValueError("instrument_name must be non-empty")
        _require_non_negative_integer(self.change_id, "change_id")
        _require_non_negative_integer(self.source_timestamp_ms, "source_timestamp_ms")
        _require_non_negative_integer(self.session_epoch, "session_epoch")
        _require_non_negative_integer(
            self.subscription_generation,
            "subscription_generation",
        )
        if self.session_epoch != self.boundary.session_epoch:
            raise ValueError("subscription session_epoch must match its FactBoundary")
        if self.snapshot_kind not in {"snapshot", "change"}:
            raise ValueError("subscription refresh requires snapshot/change kind")
        if self.snapshot_kind == "snapshot" and self.prev_change_id is not None:
            raise ValueError("subscription snapshot prev_change_id must be null")
        if self.snapshot_kind == "change":
            _require_non_negative_integer(self.prev_change_id, "prev_change_id")
        expected_identity = canonical_identity(
            "SubscriptionAdmissionRefreshSourceIdentity",
            self.boundary.runtime_identity,
            self.session_epoch,
            self.subscription_generation,
            self.canonical_combo_identity,
            self.snapshot_kind,
            self.prev_change_id,
            self.change_id,
            self.source_timestamp_ms,
            self.boundary.as_object(),
        )
        if self.source_identity != expected_identity:
            raise ValueError("subscription admission source identity mismatch")


@dataclass(frozen=True)
class RpcAdmissionRefreshWitness:
    """Matched public snapshot response and its accepted market frontier."""

    source_identity: str
    boundary: FactBoundary
    canonical_combo_identity: str
    instrument_name: str
    request_params: Mapping[str, object]
    change_id: int
    source_timestamp_ms: int
    request_id: int
    candidate_origin_boundary: FactBoundary
    sent_boundary: FactBoundary
    market_frontier_change_id: int
    market_frontier_session_epoch: int
    response_matches_frontier: bool
    response_covers_full_quantity: bool
    payload_matches_request: bool = True
    payload_well_formed: bool = True

    @property
    def kind(self) -> AdmissionRefreshKind:
        return AdmissionRefreshKind.RPC

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")
        require_identity(self.canonical_combo_identity, "canonical_combo_identity")
        if not self.instrument_name:
            raise ValueError("instrument_name must be non-empty")
        for field_name in (
            "change_id",
            "source_timestamp_ms",
            "request_id",
            "market_frontier_change_id",
            "market_frontier_session_epoch",
        ):
            _require_non_negative_integer(getattr(self, field_name), field_name)
        if dict(self.request_params) != {
            "instrument_name": self.instrument_name,
            "depth": 10000,
        }:
            raise ValueError("admission refresh request params must be exact")
        expected_identity = canonical_identity(
            "RpcAdmissionRefreshSourceIdentity",
            self.boundary.runtime_identity,
            self.request_id,
            "public/get_order_book",
            self.canonical_combo_identity,
            dict(self.request_params),
            self.candidate_origin_boundary.as_object(),
            self.sent_boundary.as_object(),
            self.change_id,
            self.source_timestamp_ms,
            self.boundary.as_object(),
        )
        if self.source_identity != expected_identity:
            raise ValueError("RPC admission source identity mismatch")


AdmissionRefreshWitness = SubscriptionAdmissionRefreshWitness | RpcAdmissionRefreshWitness


@dataclass(frozen=True)
class RpcRequestIntent:
    request_id: int
    purpose: str
    method: str
    params: Mapping[str, object]
    scheduled_identity: str
    origin_boundary: FactBoundary
    owner_identity: str


@dataclass
class AdmissionAttempt:
    candidate_identity: str
    canonical_combo_identity: str
    request_instrument_name: str
    request_id: int
    origin_boundary: FactBoundary
    scheduled_identity: str
    _intent_taken: bool = False
    sent_boundary: FactBoundary | None = None
    terminal_outcome: AdmissionTerminalOutcome | None = None
    terminal_identity: str | None = None
    terminal_boundary: FactBoundary | None = None
    terminal_source_identity: str | None = None

    @classmethod
    def schedule(
        cls,
        *,
        candidate_identity: str,
        canonical_combo_identity: str,
        request_id: int,
        boundary: FactBoundary,
        request_instrument_name: str,
    ) -> AdmissionAttempt:
        require_identity(candidate_identity, "candidate_identity")
        require_identity(canonical_combo_identity, "canonical_combo_identity")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
            raise ValueError("request_id must be a non-negative integer")
        if not request_instrument_name:
            raise ValueError("request instrument name must be non-empty")
        instrument_name = request_instrument_name
        params = {"instrument_name": instrument_name, "depth": 10000}
        scheduled = canonical_identity(
            "ScheduledAdmissionAttemptIdentity",
            candidate_identity,
            request_id,
            "public/get_order_book",
            params,
            boundary.as_object(),
        )
        return cls(
            candidate_identity=candidate_identity,
            canonical_combo_identity=canonical_combo_identity,
            request_instrument_name=instrument_name,
            request_id=request_id,
            origin_boundary=boundary,
            scheduled_identity=scheduled,
        )

    def take_request_intent(self) -> RpcRequestIntent | None:
        if self._intent_taken or self.terminal_outcome is not None:
            return None
        self._intent_taken = True
        return RpcRequestIntent(
            request_id=self.request_id,
            purpose="ADMISSION_REFRESH",
            method="public/get_order_book",
            params=MappingProxyType(
                {
                    "instrument_name": self.request_instrument_name,
                    "depth": 10000,
                }
            ),
            scheduled_identity=self.scheduled_identity,
            origin_boundary=self.origin_boundary,
            owner_identity=self.candidate_identity,
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        if (
            request_id != self.request_id
            or self.terminal_outcome is not None
            or self.sent_boundary is not None
        ):
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("admission SENT must be strictly after Candidate activation")
        if (
            boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms
            > send_budget_ms
        ):
            return self._terminalize(
                source_identity=canonical_identity(
                    "AdmissionSendDeadlineLateIdentity",
                    self.scheduled_identity,
                    boundary.as_object(),
                ),
                boundary=boundary,
                classification=RefreshClassification.UNKNOWN,
            )
        self.sent_boundary = boundary
        return True

    def accept_subscription_refresh(
        self,
        *,
        witness: SubscriptionAdmissionRefreshWitness,
        candidate_quote_witness: SubscriptionAdmissionRefreshWitness,
        classification: RefreshClassification,
    ) -> bool:
        if not self.subscription_qualifies(
            witness=witness,
            candidate_quote_witness=candidate_quote_witness,
        ):
            return False
        boundary = witness.boundary
        return self._terminalize(
            source_identity=witness.source_identity,
            boundary=boundary,
            classification=classification,
        )

    def subscription_qualifies(
        self,
        *,
        witness: SubscriptionAdmissionRefreshWitness,
        candidate_quote_witness: SubscriptionAdmissionRefreshWitness,
    ) -> bool:
        if self.terminal_outcome is not None:
            return False
        return (
            witness.canonical_combo_identity == self.canonical_combo_identity
            and candidate_quote_witness.canonical_combo_identity == self.canonical_combo_identity
            and witness.instrument_name == self.request_instrument_name
            and witness.session_epoch == candidate_quote_witness.session_epoch
            and witness.subscription_generation == candidate_quote_witness.subscription_generation
            and witness.change_id > candidate_quote_witness.change_id
            and (
                witness.snapshot_kind == "snapshot"
                or witness.prev_change_id == candidate_quote_witness.change_id
            )
            and witness.boundary.is_strictly_after(self.origin_boundary)
        )

    def accept_response(
        self,
        *,
        witness: RpcAdmissionRefreshWitness,
        response_budget_ms: int,
        classification: RefreshClassification,
    ) -> bool:
        if (
            witness.request_id != self.request_id
            or self.terminal_outcome is not None
            or self.sent_boundary is None
            or witness.canonical_combo_identity != self.canonical_combo_identity
            or witness.instrument_name != self.request_instrument_name
            or witness.candidate_origin_boundary != self.origin_boundary
        ):
            return False
        if witness.sent_boundary != self.sent_boundary:
            return False
        boundary = witness.boundary
        if not boundary.is_strictly_after(self.sent_boundary):
            raise ValueError("matched admission response must be strictly after SENT")
        if (
            boundary.received_monotonic_ms - self.sent_boundary.received_monotonic_ms
            > response_budget_ms
        ):
            classification = RefreshClassification.UNKNOWN
        if (
            witness.market_frontier_session_epoch != boundary.session_epoch
            or witness.market_frontier_change_id != witness.change_id
            or not witness.response_matches_frontier
            or not witness.response_covers_full_quantity
            or not witness.payload_matches_request
            or not witness.payload_well_formed
        ):
            classification = RefreshClassification.UNKNOWN
        return self._terminalize(
            source_identity=witness.source_identity,
            boundary=boundary,
            classification=classification,
        )

    def fail_request(
        self,
        *,
        request_id: int,
        source_identity: str,
        boundary: FactBoundary,
    ) -> bool:
        if request_id != self.request_id or self.terminal_outcome is not None:
            return False
        lower_bound = self.sent_boundary or self.origin_boundary
        if not boundary.is_strictly_after(lower_bound):
            raise ValueError("admission failure control must be causally later")
        return self._terminalize(
            source_identity=source_identity,
            boundary=boundary,
            classification=RefreshClassification.UNKNOWN,
        )

    def invalidate_before_refresh(
        self,
        *,
        source_identity: str,
        boundary: FactBoundary,
    ) -> bool:
        if self.terminal_outcome is not None:
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("Candidate invalidation must be causally later")
        return self._terminalize(
            source_identity=source_identity,
            boundary=boundary,
            classification=RefreshClassification.KNOWN_INVALIDATED,
        )

    def _terminalize(
        self,
        *,
        source_identity: str,
        boundary: FactBoundary,
        classification: RefreshClassification,
    ) -> bool:
        require_identity(source_identity, "terminal_source_identity")
        outcomes = {
            RefreshClassification.COMPLETE_CANDIDATE: AdmissionTerminalOutcome.ENTRY_EMITTED,
            RefreshClassification.COMPLETE_NO_ENTRY: (
                AdmissionTerminalOutcome.KNOWN_COMPLETE_NO_ENTRY
            ),
            RefreshClassification.KNOWN_INVALIDATED: (
                AdmissionTerminalOutcome.KNOWN_INVALIDATED_BEFORE_REFRESH
            ),
            RefreshClassification.UNKNOWN: AdmissionTerminalOutcome.UNKNOWN_CONSUMED,
        }
        outcome = outcomes[classification]
        self.terminal_outcome = outcome
        self.terminal_boundary = boundary
        self.terminal_source_identity = source_identity
        self.terminal_identity = canonical_identity(
            "ADMISSION_ATTEMPT_TERMINAL",
            self.scheduled_identity,
            outcome.value,
            boundary.as_object(),
        )
        return True
