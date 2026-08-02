from __future__ import annotations

import re
from collections.abc import Mapping

from short_vol_underwriting.constants import (
    ACTUAL_AVAILABILITY_UNKNOWN,
)
from short_vol_underwriting.identity import (
    canonical_identity,
    require_identity,
)
from short_vol_underwriting.model import FactBoundary

DECIMAL_PATTERN = re.compile(r"0|-?(?:[1-9][0-9]*(?:\.[0-9]*[1-9])?|0\.[0-9]*[1-9])")
PROVENANCE_ROLES = frozenset(
    {
        "ANCHOR",
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "CLOSE_QUOTE_EVALUATION",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SELECTED_EXIT",
        "TERMINAL_OUTCOME",
        "POSITION_FACT",
        "COMBO_QUOTE",
        "COMMISSION",
        "INDEX",
        "INSTRUMENT_LIFECYCLE",
        "ATTEMPT_CONTROL",
        "SUPERVISOR_CONTROL",
    }
)
ACTUAL_FIELDS = tuple(ACTUAL_AVAILABILITY_UNKNOWN)
TERMINAL_STATES = frozenset(
    {
        "MATURE_KNOWN",
        "MATURE_UNKNOWN",
        "CENSORED_AT_STOP",
        "CENSORED_AT_FAILURE",
    }
)
POST_CLOSE_TERMINAL_STATUSES = frozenset(
    {
        "SUCCESS",
        "ERROR",
        "DEADLINE_LATE",
        "RETIRED",
        "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE",
        "NOT_REQUESTABLE_UNKNOWN",
        "CENSORED",
    }
)
PUBLIC_ORDER_BOOK_METHOD = "public/get_order_book"
POST_CLOSE_NOT_REQUESTABLE_MARKERS = frozenset(
    {
        "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE",
        "NOT_REQUESTABLE_UNKNOWN",
    }
)


class PayloadValidationError(ValueError):
    """A downstream payload violates its frozen semantic schema."""


def validate_payload_identity(
    *,
    object_kind: str,
    object_identity: str,
    payload: Mapping[str, object],
    runtime_identity: str,
    radar_policy_identity: str,
    underwriting_policy_identity: str,
    position_policy_identity: str,
    outcome_contract_identity: str,
) -> None:
    expected = _expected_object_identity(
        object_kind=object_kind,
        payload=payload,
        runtime_identity=runtime_identity,
        radar_policy_identity=radar_policy_identity,
        underwriting_policy_identity=underwriting_policy_identity,
        position_policy_identity=position_policy_identity,
        outcome_contract_identity=outcome_contract_identity,
    )
    if expected is not None and object_identity != expected:
        raise PayloadValidationError(f"{object_kind} object identity mismatch")


def validate_provenance_shape(
    value: object,
    *,
    code_identity: str,
    runtime_identity: str,
) -> tuple[tuple[str, str, FactBoundary], ...]:
    if not isinstance(value, list):
        raise PayloadValidationError("source_provenance must be an array")
    result: list[tuple[str, str, FactBoundary]] = []
    for index, member in enumerate(value):
        item = _mapping(member, f"source_provenance[{index}]")
        _exact_keys(
            item,
            {"source_role", "source_identity", "receipt_fact_boundary"},
            f"source_provenance[{index}]",
        )
        role = _string(item["source_role"], "source_role")
        if role not in PROVENANCE_ROLES:
            raise PayloadValidationError(f"unknown provenance role: {role}")
        identity = _identity(item["source_identity"], "source_identity")
        boundary = _boundary(
            item["receipt_fact_boundary"],
            "receipt_fact_boundary",
            code_identity,
            runtime_identity,
        )
        result.append((role, identity, boundary))
    keys = [(role, identity) for role, identity, _ in result]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise PayloadValidationError("source_provenance must be unique and bytewise sorted")
    return tuple(result)


def _expected_object_identity(
    *,
    object_kind: str,
    payload: Mapping[str, object],
    runtime_identity: str,
    radar_policy_identity: str,
    underwriting_policy_identity: str,
    position_policy_identity: str,
    outcome_contract_identity: str,
) -> str | None:
    try:
        boundary = FactBoundary.from_object(_boundary_object(payload)).as_object()
    except ValueError as exc:
        raise PayloadValidationError(f"invalid primary FactBoundary: {exc}") from exc
    if object_kind == "UNDERWRITING_AVAILABILITY_EVALUATION":
        return canonical_identity(
            "UnderwritingAvailabilityEvaluationIdentity",
            runtime_identity,
            radar_policy_identity,
            underwriting_policy_identity,
            position_policy_identity,
            _identity(payload["radar_scope_or_short_leg_identity"], "radar scope identity"),
            _identity(
                payload["consumed_availability_fact_fingerprint"],
                "availability fingerprint",
            ),
            payload["availability"],
            boundary,
        )
    if object_kind == "UNDERWRITING_ACTION":
        evaluation = canonical_identity(
            "UnderwritingEvaluationIdentity",
            _identity(
                payload["underwriting_opportunity_key_identity"],
                "underwriting opportunity identity",
            ),
            underwriting_policy_identity,
            position_policy_identity,
            _identity(payload["consumed_economic_fact_fingerprint"], "economic fingerprint"),
            boundary,
        )
        return canonical_identity(
            "UnderwritingActionIdentity",
            evaluation,
            payload["economic_action"],
        )
    if object_kind == "CANDIDATE_ACTIVATION":
        return canonical_identity(
            "CandidateIdentity",
            _identity(payload["underwriting_action_identity"], "underwriting action identity"),
            boundary,
        )
    if object_kind == "CANDIDATE_INVALIDATION":
        reasons = _string_array(
            payload["ordered_applicable_reason_vector"],
            "ordered_applicable_reason_vector",
        )
        return canonical_identity(
            "CANDIDATE_INVALIDATION",
            _identity(payload["candidate_identity"], "candidate_identity"),
            payload["primary_reason"],
            list(reasons),
            boundary,
        )
    if object_kind == "ADMISSION_ATTEMPT_SCHEDULED":
        request_params = _exact_request_params(payload["request_params"])
        return canonical_identity(
            "ScheduledAdmissionAttemptIdentity",
            _identity(payload["candidate_identity"], "candidate_identity"),
            _positive_integer(payload["request_id"], "request_id"),
            payload["request_method"],
            request_params,
            boundary,
        )
    if object_kind == "ADMISSION_ATTEMPT_TERMINAL":
        return canonical_identity(
            "ADMISSION_ATTEMPT_TERMINAL",
            _identity(
                payload["scheduled_admission_attempt_identity"],
                "scheduled admission attempt identity",
            ),
            payload["terminal_outcome"],
            boundary,
        )
    if object_kind == "SHADOW_ENTRY":
        return canonical_identity(
            "ShadowEntryIdentity",
            _identity(payload["candidate_identity"], "candidate_identity"),
            boundary,
        )
    if object_kind in {
        "POSITION_EVALUATION",
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
    }:
        anchor_field = (
            "shadow_entry_identity"
            if object_kind == "POSITION_EVALUATION"
            else "rejected_observation_identity"
        )
        label = (
            "PositionEvaluationIdentity"
            if object_kind == "POSITION_EVALUATION"
            else "RejectedCounterfactualPositionEvaluationIdentity"
        )
        return canonical_identity(
            label,
            _identity(payload[anchor_field], anchor_field),
            position_policy_identity,
            _identity(payload["consumed_position_fact_fingerprint"], "position fingerprint"),
            boundary,
        )
    if object_kind in {
        "POSITION_ACTION",
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
    }:
        evaluation_field = (
            "position_evaluation_identity"
            if object_kind == "POSITION_ACTION"
            else "rejected_position_evaluation_identity"
        )
        label = (
            "PositionActionIdentity"
            if object_kind == "POSITION_ACTION"
            else "RejectedCounterfactualPositionActionIdentity"
        )
        return canonical_identity(
            label,
            _identity(payload[evaluation_field], evaluation_field),
            payload["serialized_action"],
            payload["ordered_predicate_truth_vector"],
            payload["ordered_latched_close_reason_vector"],
        )
    if object_kind in {
        "CLOSE_QUOTE_EVALUATION",
        "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
    }:
        anchor_field = (
            "shadow_entry_identity"
            if object_kind == "CLOSE_QUOTE_EVALUATION"
            else "rejected_observation_identity"
        )
        label = (
            "CloseQuoteEvaluationIdentity"
            if object_kind == "CLOSE_QUOTE_EVALUATION"
            else "RejectedCounterfactualCloseQuoteEvaluationIdentity"
        )
        structure = canonical_identity(
            "OfficialComboAndCanonicalLegIdentity",
            payload["canonical_combo_identity"],
            payload["canonical_leg_identities"],
        )
        return canonical_identity(
            label,
            _identity(payload[anchor_field], anchor_field),
            position_policy_identity,
            structure,
            payload["close_direction"],
            payload["full_quantity_btc"],
            _identity(
                payload["consumed_rule_scoped_quote_fingerprint"],
                "quote fingerprint",
            ),
            payload["close_quote_state"],
            payload["close_conditioning"],
            boundary,
        )
    if object_kind == "POST_CLOSE_ATTEMPT_SCHEDULED":
        post_close_request_params = (
            None
            if payload["request_params"] is None
            else _exact_request_params(payload["request_params"])
        )
        return canonical_identity(
            "ScheduledPostCloseQuoteAttemptIdentity",
            _identity(payload["shadow_entry_identity"], "shadow_entry_identity"),
            _identity(
                payload["first_latched_close_action_identity"],
                "first_latched_close_action_identity",
            ),
            payload["request_id_or_marker"],
            payload["request_method"],
            post_close_request_params,
            boundary,
        )
    if object_kind == "POST_CLOSE_ATTEMPT_TERMINAL":
        return canonical_identity(
            "PostCloseAttemptTerminalIdentity",
            _identity(
                payload["scheduled_post_close_attempt_identity"],
                "scheduled post-close attempt identity",
            ),
            payload["terminal_status"],
            payload["terminal_owner"],
            boundary,
        )
    if object_kind in {
        "CLOSE_OPPORTUNITY_EVALUATION",
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
    }:
        rejected = object_kind.startswith("REJECTED_")
        anchor_field = "rejected_observation_identity" if rejected else "shadow_entry_identity"
        label = (
            "RejectedCounterfactualCloseOpportunityEvaluationIdentity"
            if rejected
            else "CloseOpportunityEvaluationIdentity"
        )
        quote_or_attempt = (
            payload["close_quote_evaluation_identity"]
            if payload["close_quote_evaluation_identity"] is not None
            else payload["attempt_terminal_identity"]
        )
        return canonical_identity(
            label,
            _identity(payload[anchor_field], anchor_field),
            _identity(
                payload["first_latched_close_action_identity"],
                "first_latched_close_action_identity",
            ),
            _identity(quote_or_attempt, "quote or attempt terminal identity"),
            _identity(
                payload["opportunity_economics_business_fingerprint"],
                "opportunity fingerprint",
            ),
            payload["eligibility"],
            boundary,
        )
    if object_kind == "SHADOW_CLOSE_OPPORTUNITY":
        return _identity(
            payload["close_opportunity_evaluation_identity"],
            "close_opportunity_evaluation_identity",
        )
    if object_kind == "SHADOW_OUTCOME_OBSERVATION":
        return canonical_identity(
            "ShadowObservationIdentity",
            outcome_contract_identity,
            _identity(payload["shadow_entry_identity"], "shadow_entry_identity"),
        )
    if object_kind == "SHADOW_COUNTERFACTUAL_EXIT":
        return canonical_identity(
            "ShadowCounterfactualExitIdentity",
            _identity(payload["shadow_observation_identity"], "shadow_observation_identity"),
            _identity(
                payload["first_latched_close_action_identity"],
                "first_latched_close_action_identity",
            ),
            _identity(
                payload["close_opportunity_evaluation_identity"],
                "close_opportunity_evaluation_identity",
            ),
        )
    if object_kind in {"SHADOW_OUTCOME", "REJECTED_COUNTERFACTUAL_OUTCOME"}:
        rejected = object_kind.startswith("REJECTED_")
        observation_field = (
            "rejected_observation_identity" if rejected else "shadow_observation_identity"
        )
        label = "RejectedCounterfactualOutcomeIdentity" if rejected else "ShadowOutcomeIdentity"
        return canonical_identity(
            label,
            _identity(payload[observation_field], observation_field),
            payload["terminal_state"],
            boundary,
        )
    if object_kind == "REJECTED_COUNTERFACTUAL_ANCHOR":
        return canonical_identity(
            "RejectedCounterfactualAnchorIdentity",
            outcome_contract_identity,
            _identity(
                payload["underwriting_position_slot_key"],
                "underwriting_position_slot_key",
            ),
            _identity(payload["underwriting_action_identity"], "underwriting_action_identity"),
        )
    if object_kind == "REJECTED_COUNTERFACTUAL_OBSERVATION":
        return canonical_identity(
            "RejectedCounterfactualObservationIdentity",
            _identity(payload["rejected_anchor_identity"], "rejected_anchor_identity"),
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
        )
    if object_kind == "REJECTED_COUNTERFACTUAL_EXIT":
        return canonical_identity(
            "RejectedCounterfactualExitIdentity",
            _identity(payload["rejected_observation_identity"], "rejected_observation_identity"),
            _identity(
                payload["first_latched_close_action_identity"],
                "first_latched_close_action_identity",
            ),
            _identity(
                payload["close_opportunity_evaluation_identity"],
                "close_opportunity_evaluation_identity",
            ),
        )
    if object_kind == "ALIGNED_POLICY_NO_TRADE_PAIR":
        return canonical_identity(
            "AlignedPolicyNoTradePairIdentity",
            outcome_contract_identity,
            _identity(payload["pair_anchor_identity"], "pair_anchor_identity"),
            payload["policy_arm"],
            payload["alternative_arm"],
        )
    return None


def _boundary_object(payload: Mapping[str, object]) -> Mapping[str, object]:
    candidates = (
        "availability_evaluation_fact_boundary",
        "evaluation_fact_boundary",
        "candidate_activation_fact_boundary",
        "terminal_fact_boundary",
        "schedule_fact_boundary",
        "entry_fact_boundary",
        "action_fact_boundary",
        "opportunity_fact_boundary",
        "start_fact_boundary",
        "selection_fact_boundary",
        "anchor_fact_boundary",
    )
    for field in candidates:
        value = payload.get(field)
        if isinstance(value, Mapping):
            return value
    raise PayloadValidationError("payload lacks its primary FactBoundary")


def _boundary(
    value: object,
    field: str,
    code_identity: str,
    runtime_identity: str,
) -> FactBoundary:
    try:
        boundary = FactBoundary.from_object(value)
    except ValueError as exc:
        raise PayloadValidationError(f"{field}: {exc}") from exc
    if boundary.code_identity != code_identity or boundary.runtime_identity != runtime_identity:
        raise PayloadValidationError(f"{field} has mixed code/runtime identity")
    return boundary


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PayloadValidationError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PayloadValidationError(f"{field} must be a non-empty string")
    return value


def _identity(value: object, field: str) -> str:
    try:
        return require_identity(value, field)
    except ValueError as exc:
        raise PayloadValidationError(str(exc)) from exc


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(member, str) for member in value):
        raise PayloadValidationError(f"{field} must be a string array")
    return tuple(value)


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PayloadValidationError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PayloadValidationError(f"{field} must be a positive integer")
    return value


def _exact_request_params(value: object) -> dict[str, object]:
    params = _mapping(value, "request_params")
    _exact_keys(params, {"instrument_name", "depth"}, "request_params")
    instrument_name = _string(params["instrument_name"], "request_params.instrument_name")
    depth = _non_negative_integer(params["depth"], "request_params.depth")
    if depth != 10_000:
        raise PayloadValidationError("request_params.depth must be exactly 10000")
    return {"instrument_name": instrument_name, "depth": depth}


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise PayloadValidationError(f"{field} requires exact keys")
