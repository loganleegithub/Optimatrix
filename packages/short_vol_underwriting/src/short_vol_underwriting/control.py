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
    REFRESHED_WATCH_OR_ABSTAIN = "REFRESHED_WATCH_OR_ABSTAIN"
    REFRESHED_CANDIDATE = "REFRESHED_CANDIDATE"
    REFRESHED_EVALUABLE_SCORE_BAND_CONTROL = "REFRESHED_EVALUABLE_SCORE_BAND_CONTROL"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class DecisionControlAttemptOutcome(StrEnum):
    CONTROL_OPENED = "CONTROL_OPENED"
    REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION = (
        "REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION"
    )
    KNOWN_NO_CONTROL = "KNOWN_NO_CONTROL"
    UNKNOWN_CONSUMED = "UNKNOWN_CONSUMED"


class DecisionControlKnownNoControlReason(StrEnum):
    RADAR_EPISODE_OR_REVIEW_ENDED = "RADAR_EPISODE_OR_REVIEW_ENDED"
    POSITION_SLOT_CONSUMED = "POSITION_SLOT_CONSUMED"
    NO_PROTECTIVE_COMPONENT = "NO_PROTECTIVE_COMPONENT"
    NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE = "NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE"
    ATOMIC_STRUCTURE_NOT_EVALUATED = "ATOMIC_STRUCTURE_NOT_EVALUATED"
    NO_ACTIVE_COMBO = "NO_ACTIVE_COMBO"
    NO_TARGET_SIZE_CREDIT_QUOTE = "NO_TARGET_SIZE_CREDIT_QUOTE"
    STRUCTURE_OR_LIFECYCLE_INELIGIBLE = "STRUCTURE_OR_LIFECYCLE_INELIGIBLE"
    LATEST_ADMISSION_BOUNDARY_REACHED = "LATEST_ADMISSION_BOUNDARY_REACHED"
    REFRESHED_OPPORTUNITY_CHANGED = "REFRESHED_OPPORTUNITY_CHANGED"
    REQUEST_RETIRED_BEFORE_REFRESH = "REQUEST_RETIRED_BEFORE_REFRESH"
    RUNTIME_TERMINATED_BEFORE_REFRESH = "RUNTIME_TERMINATED_BEFORE_REFRESH"


@dataclass(frozen=True)
class RadarScoreControlDesignation:
    """One future-blind LOW/MID designation for a causal Radar batch."""

    rule_identity: str
    batch_identity: str
    designation_identity: str
    selected_review_identity: str
    selected_band: str
    selected_ordinal: int
    low_eligible_count: int
    mid_eligible_count: int
    present_stratum_count: int
    selected_stratum_eligible_count: int
    inclusion_numerator: int
    inclusion_denominator: int

    def __post_init__(self) -> None:
        for identity_value, field_name in (
            (self.rule_identity, "rule_identity"),
            (self.batch_identity, "batch_identity"),
            (self.designation_identity, "designation_identity"),
            (self.selected_review_identity, "selected_review_identity"),
        ):
            require_identity(identity_value, field_name)
        if self.selected_band not in {"LOW", "MID"}:
            raise ValueError("selected control band must be LOW or MID")
        _require_non_negative_integer(self.selected_ordinal, "selected_ordinal")
        for positive_value, field_name in (
            (self.present_stratum_count, "present_stratum_count"),
            (self.selected_stratum_eligible_count, "selected_stratum_eligible_count"),
            (self.inclusion_numerator, "inclusion_numerator"),
            (self.inclusion_denominator, "inclusion_denominator"),
        ):
            _require_positive_integer(positive_value, field_name)
        for count_value, field_name in (
            (self.low_eligible_count, "low_eligible_count"),
            (self.mid_eligible_count, "mid_eligible_count"),
        ):
            _require_non_negative_integer(count_value, field_name)
        expected_strata = int(self.low_eligible_count > 0) + int(self.mid_eligible_count > 0)
        if self.present_stratum_count != expected_strata:
            raise ValueError("present_stratum_count contradicts eligible counts")
        expected_selected_count = (
            self.low_eligible_count if self.selected_band == "LOW" else self.mid_eligible_count
        )
        if self.selected_stratum_eligible_count != expected_selected_count:
            raise ValueError("selected stratum count contradicts selected band")
        if self.selected_ordinal >= self.selected_stratum_eligible_count:
            raise ValueError("selected_ordinal exceeds its stratum")
        if self.inclusion_numerator != 1 or self.inclusion_denominator != (
            self.present_stratum_count * self.selected_stratum_eligible_count
        ):
            raise ValueError("control inclusion probability is not the declared rational sample")


def radar_score_control_rule_identity(*, bindings: RuntimeBindings) -> str:
    return canonical_identity(
        "RadarScoreBandNoTradeControlRuleIdentity",
        bindings.code_identity,
        bindings.radar_policy_identity,
        bindings.underwriting_policy_identity,
        bindings.position_policy_identity,
        "HIGH_BATCH_PRECEDENCE",
        "EQUAL_PRESENT_LOW_MID_STRATUM_HASH",
        "MINIMUM_HASH_WITHIN_SELECTED_STRATUM",
        "NO_FALLBACK",
        1,
    )


def radar_score_control_batch_identity(
    *,
    bindings: RuntimeBindings,
    activation_causal_seq: int,
) -> str:
    _require_non_negative_integer(activation_causal_seq, "activation_causal_seq")
    return canonical_identity(
        "RadarScoreControlCausalBatchIdentity",
        bindings.runtime_identity,
        bindings.radar_policy_identity,
        activation_causal_seq,
    )


def radar_score_control_designation_key(
    *,
    bindings: RuntimeBindings,
    batch_identity: str,
    review_identity: str,
    band: str,
) -> str:
    require_identity(batch_identity, "batch_identity")
    require_identity(review_identity, "review_identity")
    if band not in {"LOW", "MID"}:
        raise ValueError("score-band control eligibility is LOW or MID only")
    return canonical_identity(
        "RadarScoreControlDesignationKey",
        radar_score_control_rule_identity(bindings=bindings),
        batch_identity,
        band,
        review_identity,
    )


def designate_radar_score_control_review(
    *,
    bindings: RuntimeBindings,
    batch_identity: str,
    eligible_reviews: tuple[tuple[str, str], ...],
) -> RadarScoreControlDesignation:
    """Select one LOW/MID review without consulting Underwriting or later facts."""

    require_identity(batch_identity, "batch_identity")
    if not eligible_reviews:
        raise ValueError("score-band control batch must contain an eligible review")
    review_identities = tuple(review_identity for review_identity, _band in eligible_reviews)
    if len(set(review_identities)) != len(review_identities):
        raise ValueError("score-band control review identities must be unique")
    strata: dict[str, list[str]] = {"LOW": [], "MID": []}
    for review_identity, band in eligible_reviews:
        require_identity(review_identity, "review_identity")
        if band not in strata:
            raise ValueError("score-band control eligibility is LOW or MID only")
        strata[band].append(review_identity)
    present_bands = tuple(band for band in ("LOW", "MID") if strata[band])
    selected_band = min(
        present_bands,
        key=lambda band: canonical_identity(
            "RadarScoreControlStratumDesignationKey",
            radar_score_control_rule_identity(bindings=bindings),
            batch_identity,
            band,
        ),
    )
    ordered_stratum = tuple(
        sorted(
            strata[selected_band],
            key=lambda review_identity: radar_score_control_designation_key(
                bindings=bindings,
                batch_identity=batch_identity,
                review_identity=review_identity,
                band=selected_band,
            ),
        )
    )
    selected_review = ordered_stratum[0]
    selected_ordinal = 0
    low_count = len(strata["LOW"])
    mid_count = len(strata["MID"])
    stratum_count = len(present_bands)
    selected_count = len(ordered_stratum)
    denominator = stratum_count * selected_count
    rule_identity = radar_score_control_rule_identity(bindings=bindings)
    designation_identity = canonical_identity(
        "RadarScoreControlDesignationIdentity",
        rule_identity,
        batch_identity,
        {"LOW": low_count, "MID": mid_count},
        selected_band,
        selected_review,
        selected_ordinal,
        {"numerator": 1, "denominator": denominator},
    )
    return RadarScoreControlDesignation(
        rule_identity=rule_identity,
        batch_identity=batch_identity,
        designation_identity=designation_identity,
        selected_review_identity=selected_review,
        selected_band=selected_band,
        selected_ordinal=selected_ordinal,
        low_eligible_count=low_count,
        mid_eligible_count=mid_count,
        present_stratum_count=stratum_count,
        selected_stratum_eligible_count=selected_count,
        inclusion_numerator=1,
        inclusion_denominator=denominator,
    )


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
    terminal_known_no_control_reason: DecisionControlKnownNoControlReason | None = None
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
        known_no_control_reason: DecisionControlKnownNoControlReason | None = None,
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
        if (classification is DecisionControlRefreshClassification.NOT_EVALUATED) != (
            known_no_control_reason is not None
        ):
            raise ValueError("NOT_EVALUATED requires exactly one known-no-control reason")
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
            known_no_control_reason=(
                known_no_control_reason
                if classification is DecisionControlRefreshClassification.NOT_EVALUATED
                else None
            ),
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
        known_no_control_reason: DecisionControlKnownNoControlReason,
    ) -> bool:
        if self.terminal_outcome is not None:
            return False
        if not boundary.is_strictly_after(self.origin_boundary):
            raise ValueError("decision-control invalidation must be causally later")
        return self._terminalize(
            source_identity=source_identity,
            boundary=boundary,
            classification=DecisionControlRefreshClassification.NOT_EVALUATED,
            known_no_control_reason=known_no_control_reason,
        )

    def _terminalize(
        self,
        *,
        source_identity: str,
        boundary: FactBoundary,
        classification: DecisionControlRefreshClassification,
        known_no_control_reason: DecisionControlKnownNoControlReason | None = None,
    ) -> bool:
        require_identity(source_identity, "terminal_source_identity")
        outcome = {
            DecisionControlRefreshClassification.REFRESHED_WATCH_OR_ABSTAIN: (
                DecisionControlAttemptOutcome.CONTROL_OPENED
            ),
            DecisionControlRefreshClassification.REFRESHED_EVALUABLE_SCORE_BAND_CONTROL: (
                DecisionControlAttemptOutcome.CONTROL_OPENED
            ),
            DecisionControlRefreshClassification.REFRESHED_CANDIDATE: (
                DecisionControlAttemptOutcome.REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION
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
        if (outcome is DecisionControlAttemptOutcome.KNOWN_NO_CONTROL) != (
            known_no_control_reason is not None
        ):
            raise ValueError("KNOWN_NO_CONTROL requires exactly one fixed reason")
        self.terminal_outcome = outcome
        self.terminal_known_no_control_reason = known_no_control_reason
        self.terminal_boundary = boundary
        self.terminal_source_identity = source_identity
        if known_no_control_reason is None:
            self.terminal_identity = canonical_identity(
                "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
                self.scheduled_identity,
                outcome.value,
                boundary.as_object(),
            )
        else:
            self.terminal_identity = canonical_identity(
                "UNDERWRITING_DECISION_CONTROL_ATTEMPT_TERMINAL",
                self.scheduled_identity,
                outcome.value,
                known_no_control_reason.value,
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
