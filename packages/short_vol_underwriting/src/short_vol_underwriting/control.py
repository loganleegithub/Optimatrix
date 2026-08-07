from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from short_vol_underwriting.admission import (
    ComponentBookPairWitness,
    RpcRequestIntent,
)
from short_vol_underwriting.evidence import RuntimeBindings
from short_vol_underwriting.identity import canonical_identity, require_identity
from short_vol_underwriting.model import FactBoundary


class DecisionControlRefreshClassification(StrEnum):
    EVALUABLE = "EVALUABLE"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class DecisionControlAttemptOutcome(StrEnum):
    CONTROL_OPENED = "CONTROL_OPENED"
    KNOWN_NO_CONTROL = "KNOWN_NO_CONTROL"
    UNKNOWN_CONSUMED = "UNKNOWN_CONSUMED"


def selected_decision_rule_identity(
    *,
    bindings: RuntimeBindings,
) -> str:
    return canonical_identity(
        "SelectedUnderwritingDecisionControlRuleIdentity",
        bindings.code_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        "MINIMUM_PRE_OUTCOME_EPISODE_HASH_WITHIN_ACTIVATION_CAUSAL_BATCH",
        "NO_UNKNOWN_FALLBACK",
        1,
    )


def selected_decision_batch_identity(
    *,
    bindings: RuntimeBindings,
    activation_causal_seq: int,
) -> str:
    _require_non_negative_integer(
        activation_causal_seq,
        "activation_causal_seq",
    )
    return canonical_identity(
        "UnderwritingDecisionActivationBatchIdentity",
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        activation_causal_seq,
    )


def selected_decision_designation_key(
    *,
    bindings: RuntimeBindings,
    batch_identity: str,
    episode_identity: str,
) -> str:
    require_identity(batch_identity, "batch_identity")
    if not isinstance(episode_identity, str) or not episode_identity:
        raise ValueError("episode_identity must be non-empty")
    return canonical_identity(
        "SelectedUnderwritingDecisionControlDesignationKey",
        batch_identity,
        episode_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
    )


def designate_selected_decision_episode(
    *,
    bindings: RuntimeBindings,
    batch_identity: str,
    episode_identities: tuple[str, ...],
) -> str:
    if not episode_identities:
        raise ValueError("decision-control batch must contain at least one Episode")
    unique = tuple(sorted(set(episode_identities)))
    if len(unique) != len(episode_identities):
        raise ValueError("decision-control batch Episode identities must be unique")
    return min(
        unique,
        key=lambda episode_identity: selected_decision_designation_key(
            bindings=bindings,
            batch_identity=batch_identity,
            episode_identity=episode_identity,
        ),
    )


@dataclass
class DecisionControlAttempt:
    selection_identity: str
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
    terminal_outcome: DecisionControlAttemptOutcome | None = None
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
        selection_identity: str,
        short_option_identity: str,
        long_option_identity: str,
        short_request_id: int,
        long_request_id: int,
        boundary: FactBoundary,
        short_instrument_name: str,
        long_instrument_name: str,
    ) -> DecisionControlAttempt:
        for value, field_name in (
            (selection_identity, "selection_identity"),
            (short_option_identity, "short_option_identity"),
            (long_option_identity, "long_option_identity"),
        ):
            require_identity(value, field_name)
        if short_request_id == long_request_id:
            raise ValueError("decision-control request ids must be distinct")
        for request_id in (short_request_id, long_request_id):
            _require_non_negative_integer(request_id, "request_id")
        if not short_instrument_name or not long_instrument_name:
            raise ValueError("decision-control instrument names must be non-empty")
        params = (
            {"instrument_name": short_instrument_name, "depth": 10000},
            {"instrument_name": long_instrument_name, "depth": 10000},
        )
        scheduled = canonical_identity(
            "ScheduledUnderwritingDecisionControlAttemptIdentity",
            selection_identity,
            [short_request_id, long_request_id],
            "public/get_order_book",
            params,
            boundary.as_object(),
        )
        return cls(
            selection_identity=selection_identity,
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
        members = (
            (
                self.short_request_id,
                "COMPONENT_DECISION_CONTROL_SHORT_REFRESH",
                self.short_instrument_name,
            ),
            (
                self.long_request_id,
                "COMPONENT_DECISION_CONTROL_LONG_REFRESH",
                self.long_instrument_name,
            ),
        )
        return tuple(
            RpcRequestIntent(
                request_id=request_id,
                purpose=purpose,
                method="public/get_order_book",
                params=MappingProxyType({"instrument_name": instrument_name, "depth": 10000}),
                scheduled_identity=self.scheduled_identity,
                origin_boundary=self.origin_boundary,
                owner_identity=self.selection_identity,
            )
            for request_id, purpose, instrument_name in members
        )

    def mark_sent(
        self,
        *,
        request_id: int,
        boundary: FactBoundary,
        send_budget_ms: int,
    ) -> bool:
        _require_positive_integer(send_budget_ms, "send_budget_ms")
        if (
            request_id not in self.request_ids
            or request_id in self.sent_boundaries
            or self.terminal_outcome is not None
        ):
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("decision-control SENT must be strictly after selection")
        if (
            boundary.received_monotonic_ms - self.origin_boundary.received_monotonic_ms
            > send_budget_ms
        ):
            self.terminal_unknown_reasons = ("COMPONENT_DECISION_CONTROL_SEND_BUDGET_EXCEEDED",)
            return self._terminalize(
                source_identity=canonical_identity(
                    "DecisionControlSendDeadlineLateIdentity",
                    self.scheduled_identity,
                    request_id,
                    boundary.as_object(),
                ),
                boundary=boundary,
                classification=DecisionControlRefreshClassification.UNKNOWN,
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
        classification: DecisionControlRefreshClassification,
        classification_unknown_reasons: tuple[str, ...] = (),
    ) -> bool:
        for value, field_name in (
            (response_budget_ms, "response_budget_ms"),
            (maximum_source_skew_ms, "maximum_source_skew_ms"),
            (maximum_receive_skew_ms, "maximum_receive_skew_ms"),
        ):
            _require_positive_integer(value, field_name)
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

        def add_reason(reason: str) -> None:
            if reason not in invalid_reasons:
                invalid_reasons.append(reason)

        if classification is DecisionControlRefreshClassification.UNKNOWN:
            for reason in classification_unknown_reasons:
                add_reason(reason)
            if not classification_unknown_reasons:
                add_reason("COMPONENT_DECISION_CONTROL_REFRESHED_UNDERWRITING_UNKNOWN")
        if invalid_reasons:
            classification = DecisionControlRefreshClassification.UNKNOWN
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
            raise ValueError("decision-control failure must be causally later")
        if not isinstance(unknown_reason, str) or not unknown_reason:
            raise ValueError("unknown_reason must be a non-empty string")
        self.terminal_unknown_reasons = (unknown_reason,)
        return self._terminalize(
            source_identity=source_identity,
            boundary=boundary,
            classification=DecisionControlRefreshClassification.UNKNOWN,
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
            raise ValueError("decision-control invalidation must be causally later")
        return self._terminalize(
            source_identity=source_identity,
            boundary=boundary,
            classification=DecisionControlRefreshClassification.NOT_EVALUATED,
        )

    def _terminalize(
        self,
        *,
        source_identity: str,
        boundary: FactBoundary,
        classification: DecisionControlRefreshClassification,
    ) -> bool:
        require_identity(source_identity, "terminal_source_identity")
        outcome = {
            DecisionControlRefreshClassification.EVALUABLE: (
                DecisionControlAttemptOutcome.CONTROL_OPENED
            ),
            DecisionControlRefreshClassification.NOT_EVALUATED: (
                DecisionControlAttemptOutcome.KNOWN_NO_CONTROL
            ),
            DecisionControlRefreshClassification.UNKNOWN: (
                DecisionControlAttemptOutcome.UNKNOWN_CONSUMED
            ),
        }[classification]
        if (
            classification is DecisionControlRefreshClassification.UNKNOWN
            and not self.terminal_unknown_reasons
        ):
            self.terminal_unknown_reasons = ("COMPONENT_DECISION_CONTROL_UNCLASSIFIED_UNKNOWN",)
        self.terminal_outcome = outcome
        self.terminal_boundary = boundary
        self.terminal_source_identity = source_identity
        self.terminal_identity = canonical_identity(
            "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
            self.scheduled_identity,
            outcome.value,
            boundary.as_object(),
        )
        return True


def _require_non_negative_integer(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_positive_integer(value: int, field: str) -> None:
    _require_non_negative_integer(value, field)
    if value == 0:
        raise ValueError(f"{field} must be positive")
