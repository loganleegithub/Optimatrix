from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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


class ComponentLegRole(StrEnum):
    SHORT = "SHORT"
    LONG = "LONG"


def _require_non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _require_positive_integer(value: object, field: str) -> int:
    integer = _require_non_negative_integer(value, field)
    if integer == 0:
        raise ValueError(f"{field} must be positive")
    return integer


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
class RpcComponentLegRefreshWitness:
    """One matched public option-book response for a frozen component leg."""

    source_identity: str
    boundary: FactBoundary
    role: ComponentLegRole
    canonical_option_identity: str
    instrument_name: str
    request_params: Mapping[str, object]
    change_id: int
    source_timestamp_ms: int
    request_id: int
    owner_origin_boundary: FactBoundary
    sent_boundary: FactBoundary
    global_continuity_epoch: int
    response_covers_full_quantity: bool
    payload_matches_request: bool = True
    payload_well_formed: bool = True

    def __post_init__(self) -> None:
        require_identity(self.source_identity, "source_identity")
        require_identity(self.canonical_option_identity, "canonical_option_identity")
        if not self.instrument_name:
            raise ValueError("instrument_name must be non-empty")
        for field_name in (
            "change_id",
            "source_timestamp_ms",
            "request_id",
            "global_continuity_epoch",
        ):
            _require_non_negative_integer(getattr(self, field_name), field_name)
        if dict(self.request_params) != {
            "instrument_name": self.instrument_name,
            "depth": 10000,
        }:
            raise ValueError("component refresh request params must be exact")
        expected_identity = canonical_identity(
            "RpcComponentLegRefreshSourceIdentity",
            self.boundary.runtime_identity,
            self.request_id,
            self.role.value,
            "public/get_order_book",
            self.canonical_option_identity,
            dict(self.request_params),
            self.owner_origin_boundary.as_object(),
            self.sent_boundary.as_object(),
            self.global_continuity_epoch,
            self.change_id,
            self.source_timestamp_ms,
            self.boundary.as_object(),
        )
        if self.source_identity != expected_identity:
            raise ValueError("component RPC source identity mismatch")


@dataclass(frozen=True)
class ComponentBookPairWitness:
    pair_identity: str
    boundary: FactBoundary
    short: RpcComponentLegRefreshWitness
    long: RpcComponentLegRefreshWitness

    def __post_init__(self) -> None:
        require_identity(self.pair_identity, "pair_identity")
        if self.short.role is not ComponentLegRole.SHORT:
            raise ValueError("component pair short witness has the wrong role")
        if self.long.role is not ComponentLegRole.LONG:
            raise ValueError("component pair long witness has the wrong role")
        if (
            self.short.owner_origin_boundary != self.long.owner_origin_boundary
            or self.short.boundary.runtime_identity != self.long.boundary.runtime_identity
            or self.boundary
            != max((self.short.boundary, self.long.boundary), key=lambda value: value.causal_seq)
        ):
            raise ValueError("component pair witnesses do not share one causal owner")
        expected = canonical_identity(
            "ComponentBookPairWitnessIdentity",
            self.short.source_identity,
            self.long.source_identity,
            self.boundary.as_object(),
        )
        if self.pair_identity != expected:
            raise ValueError("component pair witness identity mismatch")

    @property
    def source_timestamp_skew_ms(self) -> int:
        return abs(self.short.source_timestamp_ms - self.long.source_timestamp_ms)

    @property
    def receive_skew_ms(self) -> int:
        return abs(
            self.short.boundary.received_monotonic_ms - self.long.boundary.received_monotonic_ms
        )

    def timing_unknown_reasons(
        self,
        *,
        maximum_source_skew_ms: int,
        maximum_receive_skew_ms: int,
    ) -> tuple[str, ...]:
        for value, field_name in (
            (maximum_source_skew_ms, "maximum_source_skew_ms"),
            (maximum_receive_skew_ms, "maximum_receive_skew_ms"),
        ):
            _require_non_negative_integer(value, field_name)
            if value == 0:
                raise ValueError(f"{field_name} must be positive")
        reasons: list[str] = []
        if self.short.boundary.session_epoch != self.long.boundary.session_epoch:
            reasons.append("COMPONENT_PAIR_SESSION_EPOCH_MISMATCH")
        if self.short.global_continuity_epoch != self.long.global_continuity_epoch:
            reasons.append("COMPONENT_PAIR_CONTINUITY_EPOCH_MISMATCH")
        if self.source_timestamp_skew_ms > maximum_source_skew_ms:
            reasons.append("COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED")
        if self.receive_skew_ms > maximum_receive_skew_ms:
            reasons.append("COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED")
        return tuple(reasons)

    def timing_as_object(self) -> dict[str, object]:
        return {
            "session_epochs": [
                self.short.boundary.session_epoch,
                self.long.boundary.session_epoch,
            ],
            "global_continuity_epochs": [
                self.short.global_continuity_epoch,
                self.long.global_continuity_epoch,
            ],
            "source_timestamp_skew_ms": self.source_timestamp_skew_ms,
            "receive_skew_ms": self.receive_skew_ms,
        }

    def attempt_unknown_reasons(
        self,
        *,
        origin_boundary: FactBoundary,
        sent_boundaries: Mapping[int, FactBoundary],
        short_request_id: int,
        long_request_id: int,
        short_option_identity: str,
        long_option_identity: str,
        short_instrument_name: str,
        long_instrument_name: str,
        response_budget_ms: int,
        maximum_source_skew_ms: int,
        maximum_receive_skew_ms: int,
    ) -> tuple[str, ...]:
        """Return the one canonical fail-closed reason vector for a paired attempt."""
        _require_positive_integer(response_budget_ms, "response_budget_ms")
        reasons = list(
            self.timing_unknown_reasons(
                maximum_source_skew_ms=maximum_source_skew_ms,
                maximum_receive_skew_ms=maximum_receive_skew_ms,
            )
        )

        def add_reason(reason: str) -> None:
            if reason not in reasons:
                reasons.append(reason)

        expected = (
            (
                "SHORT",
                self.short,
                short_request_id,
                short_option_identity,
                short_instrument_name,
            ),
            (
                "LONG",
                self.long,
                long_request_id,
                long_option_identity,
                long_instrument_name,
            ),
        )
        for role, member, request_id, option_identity, instrument_name in expected:
            prefix = f"COMPONENT_PAIR_{role}"
            sent = sent_boundaries.get(request_id)
            if sent is None:
                add_reason(f"{prefix}_SENT_BOUNDARY_MISSING")
            if member.request_id != request_id:
                add_reason(f"{prefix}_REQUEST_ID_MISMATCH")
            if member.canonical_option_identity != option_identity:
                add_reason(f"{prefix}_OPTION_IDENTITY_MISMATCH")
            if member.instrument_name != instrument_name:
                add_reason(f"{prefix}_INSTRUMENT_NAME_MISMATCH")
            if member.owner_origin_boundary != origin_boundary:
                add_reason(f"{prefix}_OWNER_ORIGIN_BOUNDARY_MISMATCH")
            if member.sent_boundary != sent:
                add_reason(f"{prefix}_SENT_BOUNDARY_MISMATCH")
            if not member.payload_matches_request:
                add_reason(f"{prefix}_PAYLOAD_REQUEST_MISMATCH")
            if not member.payload_well_formed:
                add_reason(f"{prefix}_PAYLOAD_MALFORMED")
            if not member.response_covers_full_quantity:
                add_reason(f"{prefix}_FULL_QUANTITY_NOT_COVERED")
            if sent is None:
                continue
            same_runtime = (
                member.boundary.code_identity == sent.code_identity
                and member.boundary.runtime_identity == sent.runtime_identity
            )
            if not same_runtime:
                add_reason(f"{prefix}_RESPONSE_RUNTIME_MISMATCH")
            elif not member.boundary.is_strictly_after(sent):
                add_reason(f"{prefix}_RESPONSE_NOT_STRICTLY_AFTER_SENT")
            elif (
                member.boundary.received_monotonic_ms - sent.received_monotonic_ms
                > response_budget_ms
            ):
                add_reason(f"{prefix}_RESPONSE_BUDGET_EXCEEDED")
        return tuple(reasons)


def component_pair_witness(
    *,
    short: RpcComponentLegRefreshWitness,
    long: RpcComponentLegRefreshWitness,
) -> ComponentBookPairWitness:
    boundary = max((short.boundary, long.boundary), key=lambda value: value.causal_seq)
    identity = canonical_identity(
        "ComponentBookPairWitnessIdentity",
        short.source_identity,
        long.source_identity,
        boundary.as_object(),
    )
    return ComponentBookPairWitness(identity, boundary, short, long)


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
    terminal_unknown_reasons: tuple[str, ...] = ()

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
            self.terminal_unknown_reasons = ("ADMISSION_SEND_BUDGET_EXCEEDED",)
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


@dataclass
class ComponentAdmissionAttempt:
    candidate_identity: str
    short_option_identity: str
    long_option_identity: str
    short_instrument_name: str
    long_instrument_name: str
    short_request_id: int
    long_request_id: int
    origin_boundary: FactBoundary
    scheduled_identity: str
    _intents_taken: bool = False
    sent_boundaries: dict[int, FactBoundary] = field(default_factory=dict)
    terminal_outcome: AdmissionTerminalOutcome | None = None
    terminal_identity: str | None = None
    terminal_boundary: FactBoundary | None = None
    terminal_source_identity: str | None = None
    terminal_unknown_reasons: tuple[str, ...] = ()
    terminal_pair_timing: dict[str, object] | None = None
    terminal_pair_limits: dict[str, int] | None = None

    @classmethod
    def schedule(
        cls,
        *,
        candidate_identity: str,
        short_option_identity: str,
        long_option_identity: str,
        short_request_id: int,
        long_request_id: int,
        boundary: FactBoundary,
        short_instrument_name: str,
        long_instrument_name: str,
    ) -> ComponentAdmissionAttempt:
        for value, field_name in (
            (candidate_identity, "candidate_identity"),
            (short_option_identity, "short_option_identity"),
            (long_option_identity, "long_option_identity"),
        ):
            require_identity(value, field_name)
        if short_request_id == long_request_id:
            raise ValueError("component admission request ids must be distinct")
        for request_id in (short_request_id, long_request_id):
            _require_non_negative_integer(request_id, "request_id")
        if not short_instrument_name or not long_instrument_name:
            raise ValueError("component admission instrument names must be non-empty")
        params = (
            {"instrument_name": short_instrument_name, "depth": 10000},
            {"instrument_name": long_instrument_name, "depth": 10000},
        )
        scheduled = canonical_identity(
            "ScheduledComponentAdmissionAttemptIdentity",
            candidate_identity,
            [short_request_id, long_request_id],
            "public/get_order_book",
            params,
            boundary.as_object(),
        )
        return cls(
            candidate_identity=candidate_identity,
            short_option_identity=short_option_identity,
            long_option_identity=long_option_identity,
            short_instrument_name=short_instrument_name,
            long_instrument_name=long_instrument_name,
            short_request_id=short_request_id,
            long_request_id=long_request_id,
            origin_boundary=boundary,
            scheduled_identity=scheduled,
        )

    @property
    def request_ids(self) -> tuple[int, int]:
        return self.short_request_id, self.long_request_id

    def take_request_intents(self) -> tuple[RpcRequestIntent, ...]:
        if self._intents_taken or self.terminal_outcome is not None:
            return ()
        self._intents_taken = True
        values = (
            (
                self.short_request_id,
                "COMPONENT_ADMISSION_SHORT_REFRESH",
                self.short_instrument_name,
            ),
            (
                self.long_request_id,
                "COMPONENT_ADMISSION_LONG_REFRESH",
                self.long_instrument_name,
            ),
        )
        return tuple(
            RpcRequestIntent(
                request_id=request_id,
                purpose=purpose,
                method="public/get_order_book",
                params=MappingProxyType({"instrument_name": name, "depth": 10000}),
                scheduled_identity=self.scheduled_identity,
                origin_boundary=self.origin_boundary,
                owner_identity=self.candidate_identity,
            )
            for request_id, purpose, name in values
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        if (
            request_id not in self.request_ids
            or request_id in self.sent_boundaries
            or self.terminal_outcome is not None
        ):
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("component admission SENT must be strictly after Candidate")
        if (
            boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms
            > send_budget_ms
        ):
            self.terminal_unknown_reasons = ("COMPONENT_ADMISSION_SEND_BUDGET_EXCEEDED",)
            return self._terminalize(
                source_identity=canonical_identity(
                    "ComponentAdmissionSendDeadlineLateIdentity",
                    self.scheduled_identity,
                    request_id,
                    boundary.as_object(),
                ),
                boundary=boundary,
                classification=RefreshClassification.UNKNOWN,
            )
        self.sent_boundaries[request_id] = boundary
        return True

    def accept_pair(
        self,
        *,
        witness: ComponentBookPairWitness,
        response_budget_ms: int,
        maximum_source_skew_ms: int,
        maximum_receive_skew_ms: int,
        classification: RefreshClassification,
        classification_unknown_reasons: tuple[str, ...] = (),
    ) -> bool:
        if self.terminal_outcome is not None:
            return False
        for reason in classification_unknown_reasons:
            if not isinstance(reason, str) or not reason:
                raise ValueError("classification_unknown_reasons must contain non-empty strings")
        if len(classification_unknown_reasons) != len(set(classification_unknown_reasons)):
            raise ValueError("classification_unknown_reasons must not contain duplicates")
        invalid_reasons = list(
            witness.attempt_unknown_reasons(
                origin_boundary=self.origin_boundary,
                sent_boundaries=self.sent_boundaries,
                short_request_id=self.short_request_id,
                long_request_id=self.long_request_id,
                short_option_identity=self.short_option_identity,
                long_option_identity=self.long_option_identity,
                short_instrument_name=self.short_instrument_name,
                long_instrument_name=self.long_instrument_name,
                response_budget_ms=response_budget_ms,
                maximum_source_skew_ms=maximum_source_skew_ms,
                maximum_receive_skew_ms=maximum_receive_skew_ms,
            )
        )
        self.terminal_pair_timing = witness.timing_as_object()
        self.terminal_pair_limits = {
            "maximum_source_skew_ms": maximum_source_skew_ms,
            "maximum_receive_skew_ms": maximum_receive_skew_ms,
        }
        if classification is RefreshClassification.UNKNOWN:
            for reason in classification_unknown_reasons:
                if reason not in invalid_reasons:
                    invalid_reasons.append(reason)
            if not classification_unknown_reasons:
                invalid_reasons.append("COMPONENT_ADMISSION_REFRESHED_UNDERWRITING_UNKNOWN")
        if invalid_reasons:
            classification = RefreshClassification.UNKNOWN
            self.terminal_unknown_reasons = tuple(invalid_reasons)
        return self._terminalize(
            source_identity=witness.pair_identity,
            boundary=witness.boundary,
            classification=classification,
        )

    def fail_request(
        self,
        *,
        request_id: int,
        source_identity: str,
        boundary: FactBoundary,
        unknown_reason: str,
    ) -> bool:
        if request_id not in self.request_ids or self.terminal_outcome is not None:
            return False
        lower = self.sent_boundaries.get(request_id, self.origin_boundary)
        if not boundary.is_strictly_after(lower):
            raise ValueError("component admission failure must be causally later")
        if not isinstance(unknown_reason, str) or not unknown_reason:
            raise ValueError("unknown_reason must be a non-empty string")
        self.terminal_unknown_reasons = (unknown_reason,)
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
        outcome = {
            RefreshClassification.COMPLETE_CANDIDATE: AdmissionTerminalOutcome.ENTRY_EMITTED,
            RefreshClassification.COMPLETE_NO_ENTRY: (
                AdmissionTerminalOutcome.KNOWN_COMPLETE_NO_ENTRY
            ),
            RefreshClassification.KNOWN_INVALIDATED: (
                AdmissionTerminalOutcome.KNOWN_INVALIDATED_BEFORE_REFRESH
            ),
            RefreshClassification.UNKNOWN: AdmissionTerminalOutcome.UNKNOWN_CONSUMED,
        }[classification]
        if (
            outcome is AdmissionTerminalOutcome.UNKNOWN_CONSUMED
            and not self.terminal_unknown_reasons
        ):
            self.terminal_unknown_reasons = ("COMPONENT_ADMISSION_UNCLASSIFIED_UNKNOWN",)
        self.terminal_outcome = outcome
        self.terminal_boundary = boundary
        self.terminal_source_identity = source_identity
        self.terminal_identity = canonical_identity(
            "COMPONENT_ADMISSION_ATTEMPT_TERMINAL",
            self.scheduled_identity,
            outcome.value,
            boundary.as_object(),
        )
        return True
