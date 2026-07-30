from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation

from short_vol_underwriting.conservation import (
    COHORT_COUNT_KEYS,
    COHORT_RATE_KEYS,
    UNDERWRITING_COUNT_KEYS,
    UNDERWRITING_RATE_KEYS,
    cohort_conservation_status,
    compute_cohort_rates,
    compute_underwriting_rates,
    underwriting_conservation_status,
)
from short_vol_underwriting.constants import (
    ACTUAL_AVAILABILITY_UNKNOWN,
    OUTCOME_OBJECT_KINDS,
    POSITION_CLOSE_REASONS,
)
from short_vol_underwriting.identity import (
    canonical_decimal,
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


class PayloadValidationError(ValueError):
    """A downstream payload violates its frozen semantic schema."""


def validate_payload_semantics(
    *,
    object_kind: str,
    object_identity: str,
    payload: Mapping[str, object],
    code_identity: str,
    runtime_identity: str,
    radar_policy_identity: str,
    underwriting_policy_identity: str,
    position_policy_identity: str,
    underwriting_contract_digest: str,
    outcome_contract_identity: str,
) -> None:
    _reject_floats(payload, "payload")
    for key, value in payload.items():
        if key.endswith("_fact_boundary") and value is not None:
            _boundary(value, key, code_identity, runtime_identity)
    _validate_common_shapes(payload)
    _validate_enums(object_kind, payload)
    _validate_levels_and_arithmetic(object_kind, payload)
    expected = _expected_object_identity(
        object_kind=object_kind,
        payload=payload,
        runtime_identity=runtime_identity,
        radar_policy_identity=radar_policy_identity,
        underwriting_policy_identity=underwriting_policy_identity,
        position_policy_identity=position_policy_identity,
        underwriting_contract_digest=underwriting_contract_digest,
        outcome_contract_identity=outcome_contract_identity,
        code_identity=code_identity,
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


def validate_object_graph(objects: Mapping[str, Mapping[str, object]]) -> None:
    """Validate local one-hop roots and one-to-one lifecycle relationships."""
    by_kind: dict[str, list[Mapping[str, object]]] = {}
    by_identity: dict[str, list[Mapping[str, object]]] = {}
    by_kind_identity: dict[tuple[str, str], Mapping[str, object]] = {}
    for value in objects.values():
        kind = _string(value.get("object_kind"), "object_kind")
        by_kind.setdefault(kind, []).append(value)
        identity = _identity(value.get("object_identity"), "object_identity")
        by_identity.setdefault(identity, []).append(value)
        key = (kind, identity)
        if key in by_kind_identity:
            raise PayloadValidationError(f"duplicate local object: {kind} {identity}")
        by_kind_identity[key] = value
    for value in objects.values():
        kind = _string(value.get("object_kind"), "object_kind")
        if kind in OUTCOME_OBJECT_KINDS[:-1]:
            _validate_exact_outcome_provenance(
                value,
                by_kind_identity=by_kind_identity,
            )
    local_roles = {
        "ANCHOR",
        "POSITION_EVALUATION",
        "POSITION_ACTION",
        "CLOSE_QUOTE_EVALUATION",
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SELECTED_EXIT",
        "TERMINAL_OUTCOME",
    }
    for value in objects.values():
        provenance = value.get("source_provenance")
        if not isinstance(provenance, list):
            raise PayloadValidationError("source_provenance must be an array")
        for member in provenance:
            item = _mapping(member, "source_provenance member")
            role = _string(item.get("source_role"), "source_role")
            identity = _identity(item.get("source_identity"), "source_identity")
            if role in local_roles:
                targets = by_identity.get(identity, ())
                if not targets:
                    raise PayloadValidationError(
                        f"missing local {role} provenance object: {identity}"
                    )
                if not any(
                    target.get("fact_boundary") == item.get("receipt_fact_boundary")
                    for target in targets
                ):
                    raise PayloadValidationError("local provenance boundary mismatch")
    _validate_unique_relation(
        by_kind.get("SHADOW_OUTCOME_OBSERVATION", ()),
        "payload.shadow_entry_identity",
    )
    _validate_unique_relation(
        by_kind.get("REJECTED_COUNTERFACTUAL_OBSERVATION", ()),
        "payload.rejected_anchor_identity",
    )
    _validate_unique_relation(
        by_kind.get("SHADOW_OUTCOME", ()),
        "payload.shadow_observation_identity",
    )
    _validate_unique_relation(
        by_kind.get("REJECTED_COUNTERFACTUAL_OUTCOME", ()),
        "payload.rejected_observation_identity",
    )
    _validate_unique_relation(
        by_kind.get("ALIGNED_POLICY_NO_TRADE_PAIR", ()),
        "payload.trade_observation_identity",
    )


def validate_complete_attempt_relationships(
    objects: Mapping[str, Mapping[str, object]],
) -> None:
    """Require every complete-directory local attempt and its owning anchor."""
    by_kind_identity: dict[tuple[str, str], Mapping[str, object]] = {}
    by_kind: dict[str, list[Mapping[str, object]]] = {}
    for value in objects.values():
        kind = _string(value.get("object_kind"), "object_kind")
        identity = _identity(value.get("object_identity"), "object_identity")
        by_kind_identity[(kind, identity)] = value
        by_kind.setdefault(kind, []).append(value)

    admission_scheduled_by_candidate: dict[str, list[Mapping[str, object]]] = {}
    for scheduled in by_kind.get("ADMISSION_ATTEMPT_SCHEDULED", ()):
        payload = _mapping(scheduled.get("payload"), "scheduled admission attempt payload")
        candidate_identity = _identity(payload.get("candidate_identity"), "candidate_identity")
        admission_scheduled_by_candidate.setdefault(candidate_identity, []).append(scheduled)
        candidate = by_kind_identity.get(("CANDIDATE_ACTIVATION", candidate_identity))
        if candidate is None:
            raise PayloadValidationError(
                "complete admission attempt is missing its Candidate activation"
            )
        if candidate.get("fact_boundary") != scheduled.get("fact_boundary"):
            raise PayloadValidationError(
                "complete admission attempt schedule boundary differs from Candidate activation"
            )
    for candidate in by_kind.get("CANDIDATE_ACTIVATION", ()):
        candidate_identity = _identity(candidate.get("object_identity"), "candidate identity")
        if len(admission_scheduled_by_candidate.get(candidate_identity, ())) != 1:
            raise PayloadValidationError(
                "complete Candidate requires exactly one scheduled admission attempt"
            )

    admission_terminals = _complete_attempt_terminals(
        scheduled=by_kind.get("ADMISSION_ATTEMPT_SCHEDULED", ()),
        terminal=by_kind.get("ADMISSION_ATTEMPT_TERMINAL", ()),
        terminal_scheduled_field="scheduled_admission_attempt_identity",
        label="admission",
    )
    entries_by_terminal: dict[str, list[Mapping[str, object]]] = {}
    for entry in by_kind.get("SHADOW_ENTRY", ()):
        payload = _mapping(entry.get("payload"), "Shadow Entry payload")
        terminal_identity = _identity(
            payload.get("admission_attempt_terminal_identity"),
            "admission_attempt_terminal_identity",
        )
        entries_by_terminal.setdefault(terminal_identity, []).append(entry)
        terminal = admission_terminals.get(terminal_identity)
        if terminal is None:
            raise PayloadValidationError(
                "complete Shadow Entry is missing its admission attempt terminal"
            )
        terminal_payload = _mapping(
            terminal.get("payload"),
            "admission attempt terminal payload",
        )
        if payload.get("candidate_identity") != terminal_payload.get("candidate_identity"):
            raise PayloadValidationError(
                "complete Shadow Entry candidate differs from admission attempt"
            )
    for terminal_identity, terminal in admission_terminals.items():
        terminal_payload = _mapping(
            terminal.get("payload"),
            "admission attempt terminal payload",
        )
        scheduled_identity = _identity(
            terminal_payload.get("scheduled_admission_attempt_identity"),
            "scheduled_admission_attempt_identity",
        )
        scheduled = by_kind_identity[("ADMISSION_ATTEMPT_SCHEDULED", scheduled_identity)]
        scheduled_payload = _mapping(
            scheduled.get("payload"),
            "scheduled admission attempt payload",
        )
        if terminal_payload.get("candidate_identity") != scheduled_payload.get(
            "candidate_identity"
        ):
            raise PayloadValidationError(
                "admission attempt terminal candidate differs from its schedule"
            )
        entry_count = len(entries_by_terminal.get(terminal_identity, ()))
        if terminal_payload.get("terminal_outcome") == "ENTRY_EMITTED":
            if entry_count != 1:
                raise PayloadValidationError(
                    "ENTRY_EMITTED admission attempt requires exactly one Shadow Entry"
                )
        elif entry_count:
            raise PayloadValidationError("non-entry admission attempt cannot own a Shadow Entry")

    for scheduled in by_kind.get("POST_CLOSE_ATTEMPT_SCHEDULED", ()):
        scheduled_identity = _identity(
            scheduled.get("object_identity"),
            "scheduled post-close attempt identity",
        )
        payload = _mapping(scheduled.get("payload"), "scheduled post-close attempt payload")
        action_identity = _identity(
            payload.get("first_latched_close_action_identity"),
            "first_latched_close_action_identity",
        )
        action = by_kind_identity.get(("POSITION_ACTION", action_identity))
        if action is None:
            raise PayloadValidationError(
                "complete post-close attempt is missing its first CLOSE action"
            )
        action_payload = _mapping(action.get("payload"), "Position action payload")
        if action_payload.get("scheduled_post_close_attempt_identity") != scheduled_identity:
            raise PayloadValidationError(
                "first CLOSE action differs from its scheduled post-close attempt"
            )
        if action.get("fact_boundary") != scheduled.get("fact_boundary"):
            raise PayloadValidationError(
                "post-close attempt schedule boundary differs from first CLOSE action"
            )
        evaluation_identity = _identity(
            action_payload.get("position_evaluation_identity"),
            "position_evaluation_identity",
        )
        evaluation = by_kind_identity.get(("POSITION_EVALUATION", evaluation_identity))
        if evaluation is None:
            raise PayloadValidationError(
                "complete post-close attempt is missing its Position evaluation"
            )
        evaluation_payload = _mapping(
            evaluation.get("payload"),
            "Position evaluation payload",
        )
        if payload.get("shadow_entry_identity") != evaluation_payload.get("shadow_entry_identity"):
            raise PayloadValidationError(
                "post-close attempt Shadow Entry differs from its first CLOSE evaluation"
            )
    for action in by_kind.get("POSITION_ACTION", ()):
        payload = _mapping(action.get("payload"), "Position action payload")
        scheduled_identity_value = payload.get("scheduled_post_close_attempt_identity")
        if scheduled_identity_value is None:
            continue
        identity = _identity(
            scheduled_identity_value,
            "scheduled_post_close_attempt_identity",
        )
        if ("POST_CLOSE_ATTEMPT_SCHEDULED", identity) not in by_kind_identity:
            raise PayloadValidationError(
                "complete first CLOSE action is missing its scheduled post-close attempt"
            )
    _complete_attempt_terminals(
        scheduled=by_kind.get("POST_CLOSE_ATTEMPT_SCHEDULED", ()),
        terminal=by_kind.get("POST_CLOSE_ATTEMPT_TERMINAL", ()),
        terminal_scheduled_field="scheduled_post_close_attempt_identity",
        label="post-close",
    )


def _complete_attempt_terminals(
    *,
    scheduled: Sequence[Mapping[str, object]],
    terminal: Sequence[Mapping[str, object]],
    terminal_scheduled_field: str,
    label: str,
) -> dict[str, Mapping[str, object]]:
    scheduled_by_identity = {
        _identity(value.get("object_identity"), f"scheduled {label} attempt identity"): value
        for value in scheduled
    }
    terminal_by_scheduled: dict[str, list[Mapping[str, object]]] = {}
    terminal_by_identity: dict[str, Mapping[str, object]] = {}
    for value in terminal:
        terminal_identity = _identity(
            value.get("object_identity"),
            f"{label} attempt terminal identity",
        )
        terminal_by_identity[terminal_identity] = value
        payload = _mapping(value.get("payload"), f"{label} attempt terminal payload")
        scheduled_identity = _identity(
            payload.get(terminal_scheduled_field),
            terminal_scheduled_field,
        )
        terminal_by_scheduled.setdefault(scheduled_identity, []).append(value)
    for scheduled_identity, value in scheduled_by_identity.items():
        terminals = terminal_by_scheduled.get(scheduled_identity, ())
        if len(terminals) != 1:
            raise PayloadValidationError(
                f"complete scheduled {label} attempt requires exactly one terminal"
            )
        scheduled_boundary = _graph_boundary(
            value.get("fact_boundary"),
            f"scheduled {label} attempt boundary",
        )
        terminal_boundary = _graph_boundary(
            terminals[0].get("fact_boundary"),
            f"{label} attempt terminal boundary",
        )
        if terminal_boundary.causal_seq < scheduled_boundary.causal_seq:
            raise PayloadValidationError(f"{label} attempt terminal precedes its schedule")
    for scheduled_identity in terminal_by_scheduled:
        if scheduled_identity not in scheduled_by_identity:
            raise PayloadValidationError(
                f"complete {label} attempt terminal is missing its schedule"
            )
        if len(terminal_by_scheduled[scheduled_identity]) != 1:
            raise PayloadValidationError(
                f"complete scheduled {label} attempt has multiple terminals"
            )
    return terminal_by_identity


def validate_complete_cohort_summary_provenance(
    summary: Mapping[str, object],
    *,
    manifest_identity: str,
    runtime_start_trigger: Mapping[str, object],
    enrollment_cutoff_trigger: Mapping[str, object],
) -> None:
    """Validate the summary roots that require the bound manifest."""
    if summary.get("object_kind") != "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY":
        raise PayloadValidationError("complete provenance target is not the cohort summary")
    payload = _mapping(summary.get("payload"), "cohort summary payload")
    roots: dict[tuple[str, str], FactBoundary] = {}
    start = _graph_boundary(
        payload.get("runtime_start_fact_boundary"),
        "runtime_start_fact_boundary",
    )
    _add_expected_root(
        roots,
        role="SUPERVISOR_CONTROL",
        identity=_identity(manifest_identity, "manifest_identity"),
        boundary=start,
    )
    _add_expected_root(
        roots,
        role="SUPERVISOR_CONTROL",
        identity=canonical_identity(
            "PreboundSupervisorTriggerIdentity",
            runtime_start_trigger,
        ),
        boundary=start,
    )
    if payload.get("enrollment_end_reason") == "PREBOUND_CUTOFF":
        _add_expected_root(
            roots,
            role="SUPERVISOR_CONTROL",
            identity=canonical_identity(
                "PreboundSupervisorTriggerIdentity",
                enrollment_cutoff_trigger,
            ),
            boundary=_graph_boundary(
                payload.get("enrollment_end_fact_boundary"),
                "enrollment_end_fact_boundary",
            ),
        )
    _add_expected_root(
        roots,
        role="SUPERVISOR_CONTROL",
        identity=_identity(
            payload.get("terminal_source_identity"),
            "terminal_source_identity",
        ),
        boundary=_graph_boundary(
            payload.get("terminal_fact_boundary"),
            "terminal_fact_boundary",
        ),
    )
    _require_exact_provenance(summary, roots)


def _validate_exact_outcome_provenance(
    value: Mapping[str, object],
    *,
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
) -> None:
    kind = _string(value.get("object_kind"), "object_kind")
    payload = _mapping(value.get("payload"), f"{kind} payload")
    roots: dict[tuple[str, str], FactBoundary] = {}

    def local(
        role: str,
        expected_kind: str,
        identity_value: object,
        direct_boundary: object | None = None,
    ) -> None:
        identity = _identity(identity_value, f"{kind} {role} identity")
        target = by_kind_identity.get((expected_kind, identity))
        if target is None:
            raise PayloadValidationError(
                f"{kind} missing exact local {role} kind {expected_kind}: {identity}"
            )
        target_boundary = _graph_boundary(
            target.get("fact_boundary"),
            f"{expected_kind}.fact_boundary",
        )
        if direct_boundary is not None:
            expected_boundary = _graph_boundary(
                direct_boundary,
                f"{kind} direct {role} boundary",
            )
            if target_boundary != expected_boundary:
                raise PayloadValidationError(f"{kind} local {role} direct boundary mismatch")
        _add_expected_root(
            roots,
            role=role,
            identity=identity,
            boundary=target_boundary,
        )

    def direct(role: str, identity_value: object, boundary_value: object) -> None:
        _add_expected_root(
            roots,
            role=role,
            identity=_identity(identity_value, f"{kind} {role} identity"),
            boundary=_graph_boundary(
                boundary_value,
                f"{kind} {role} boundary",
            ),
        )

    def source_ref(role: str, value_to_project: object, field: str) -> None:
        source = _mapping(value_to_project, field)
        direct(
            role,
            source.get("source_identity"),
            source.get("receipt_fact_boundary"),
        )

    def commission_refs(
        value_to_project: object,
        field: str,
        exact_count: int | None = None,
    ) -> None:
        if not isinstance(value_to_project, list):
            raise PayloadValidationError(f"{field} must be an array")
        if exact_count is not None and len(value_to_project) != exact_count:
            raise PayloadValidationError(f"{field} requires exactly {exact_count} provenance roots")
        for index, member in enumerate(value_to_project):
            source_ref(
                "COMMISSION",
                member,
                f"{field}[{index}]",
            )

    if kind == "SHADOW_OUTCOME_OBSERVATION":
        local("ANCHOR", "SHADOW_ENTRY", payload.get("shadow_entry_identity"))
    elif kind == "SHADOW_COUNTERFACTUAL_EXIT":
        local(
            "ANCHOR",
            "SHADOW_OUTCOME_OBSERVATION",
            payload.get("shadow_observation_identity"),
        )
        local(
            "POSITION_ACTION",
            "POSITION_ACTION",
            payload.get("first_latched_close_action_identity"),
            payload.get("first_latched_close_action_fact_boundary"),
        )
        local(
            "CLOSE_OPPORTUNITY_EVALUATION",
            "CLOSE_OPPORTUNITY_EVALUATION",
            payload.get("close_opportunity_evaluation_identity"),
            payload.get("close_opportunity_evaluation_fact_boundary"),
        )
        source_ref(
            "COMBO_QUOTE",
            payload.get("combo_quote_source_ref"),
            "combo_quote_source_ref",
        )
        commission_refs(
            payload.get("commission_source_refs"),
            "commission_source_refs",
            2,
        )
        source_ref("INDEX", payload.get("index_source_ref"), "index_source_ref")
    elif kind == "SHADOW_OUTCOME":
        _derive_outcome_roots(
            payload,
            rejected=False,
            local=local,
            direct=direct,
        )
    elif kind == "REJECTED_COUNTERFACTUAL_ANCHOR":
        local(
            "ANCHOR",
            "UNDERWRITING_ACTION",
            payload.get("underwriting_action_identity"),
            payload.get("anchor_fact_boundary"),
        )
        source_ref(
            "COMBO_QUOTE",
            payload.get("entry_combo_quote_source_ref"),
            "entry_combo_quote_source_ref",
        )
        commission_refs(
            payload.get("entry_commission_source_refs"),
            "entry_commission_source_refs",
            2,
        )
        direct(
            "INDEX",
            payload.get("entry_index_source_identity"),
            payload.get("entry_index_fact_boundary"),
        )
        direct(
            "POSITION_FACT",
            payload.get("entry_short_leg_mark_iv_source_identity"),
            payload.get("entry_short_leg_mark_iv_fact_boundary"),
        )
    elif kind == "REJECTED_COUNTERFACTUAL_OBSERVATION":
        local(
            "ANCHOR",
            "REJECTED_COUNTERFACTUAL_ANCHOR",
            payload.get("rejected_anchor_identity"),
        )
    elif kind == "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION":
        local(
            "ANCHOR",
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
            payload.get("rejected_observation_identity"),
        )
        direct(
            "POSITION_FACT",
            payload.get("consumed_position_fact_fingerprint"),
            payload.get("evaluation_fact_boundary"),
        )
        direct(
            "POSITION_FACT",
            payload.get("entry_short_leg_mark_iv_source_identity"),
            payload.get("entry_short_leg_mark_iv_fact_boundary"),
        )
        for identity_field, boundary_field in (
            ("entry_index_source_identity", "entry_index_fact_boundary"),
            (
                "prior_evaluation_index_source_identity",
                "prior_evaluation_index_fact_boundary",
            ),
        ):
            direct(
                "INDEX",
                payload.get(identity_field),
                payload.get(boundary_field),
            )
        current_availability = payload.get("current_index_availability")
        if current_availability == "KNOWN":
            direct(
                "INDEX",
                payload.get("current_index_source_identity"),
                payload.get("current_index_fact_boundary"),
            )
        elif current_availability == "UNKNOWN":
            if any(
                payload.get(field) is not None
                for field in (
                    "current_index_usdc_per_btc",
                    "current_index_source_identity",
                    "current_index_fact_boundary",
                )
            ):
                raise PayloadValidationError(
                    "UNKNOWN current index cannot project an INDEX provenance root"
                )
        else:
            raise PayloadValidationError("current_index_availability is invalid")
    elif kind == "REJECTED_COUNTERFACTUAL_POSITION_ACTION":
        local(
            "POSITION_EVALUATION",
            "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
            payload.get("rejected_position_evaluation_identity"),
        )
    elif kind == "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION":
        local(
            "ANCHOR",
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
            payload.get("rejected_observation_identity"),
        )
        direct(
            "COMBO_QUOTE",
            payload.get("consumed_rule_scoped_quote_fingerprint"),
            payload.get("evaluation_fact_boundary"),
        )
    elif kind == "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION":
        local(
            "POSITION_ACTION",
            "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
            payload.get("first_latched_close_action_identity"),
        )
        quote_identity = payload.get("close_quote_evaluation_identity")
        if quote_identity is not None:
            local(
                "CLOSE_QUOTE_EVALUATION",
                "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
                quote_identity,
            )
        else:
            direct(
                "ATTEMPT_CONTROL",
                payload.get("attempt_terminal_identity"),
                payload.get("attempt_terminal_fact_boundary"),
            )
        _derive_close_opportunity_direct_roots(
            payload,
            direct=direct,
        )
    elif kind == "REJECTED_COUNTERFACTUAL_EXIT":
        local(
            "ANCHOR",
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
            payload.get("rejected_observation_identity"),
        )
        local(
            "POSITION_ACTION",
            "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
            payload.get("first_latched_close_action_identity"),
            payload.get("first_latched_close_action_fact_boundary"),
        )
        local(
            "CLOSE_QUOTE_EVALUATION",
            "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
            payload.get("close_quote_evaluation_identity"),
            payload.get("close_quote_evaluation_fact_boundary"),
        )
        local(
            "CLOSE_OPPORTUNITY_EVALUATION",
            "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
            payload.get("close_opportunity_evaluation_identity"),
            payload.get("close_opportunity_evaluation_fact_boundary"),
        )
        direct(
            "COMBO_QUOTE",
            payload.get("consumed_rule_scoped_quote_fingerprint"),
            payload.get("close_quote_evaluation_fact_boundary"),
        )
        commission_refs(
            payload.get("commission_source_refs"),
            "commission_source_refs",
            2,
        )
        source_ref("INDEX", payload.get("index_source_ref"), "index_source_ref")
    elif kind == "REJECTED_COUNTERFACTUAL_OUTCOME":
        _derive_outcome_roots(
            payload,
            rejected=True,
            local=local,
            direct=direct,
        )
    elif kind == "ALIGNED_POLICY_NO_TRADE_PAIR":
        rejected = payload.get("pair_family") == "REJECTED"
        local(
            "ANCHOR",
            ("REJECTED_COUNTERFACTUAL_OBSERVATION" if rejected else "SHADOW_OUTCOME_OBSERVATION"),
            payload.get("trade_observation_identity"),
        )
        local(
            "TERMINAL_OUTCOME",
            "REJECTED_COUNTERFACTUAL_OUTCOME" if rejected else "SHADOW_OUTCOME",
            payload.get("trade_outcome_identity"),
            payload.get("terminal_fact_boundary"),
        )
    else:
        raise PayloadValidationError(f"unsupported Outcome provenance kind: {kind}")
    _require_exact_provenance(value, roots)


def _derive_outcome_roots(
    payload: Mapping[str, object],
    *,
    rejected: bool,
    local: Callable[[str, str, object, object | None], None],
    direct: Callable[[str, object, object], None],
) -> None:
    local(
        "ANCHOR",
        ("REJECTED_COUNTERFACTUAL_OBSERVATION" if rejected else "SHADOW_OUTCOME_OBSERVATION"),
        payload.get("rejected_observation_identity" if rejected else "shadow_observation_identity"),
        None,
    )
    state = _string(payload.get("terminal_state"), "terminal_state")
    if state == "MATURE_KNOWN":
        local(
            "SELECTED_EXIT",
            "REJECTED_COUNTERFACTUAL_EXIT" if rejected else "SHADOW_COUNTERFACTUAL_EXIT",
            payload.get("selected_exit_identity"),
            payload.get("terminal_fact_boundary"),
        )
        return
    action_identity = payload.get("first_latched_close_action_identity")
    if action_identity is not None:
        local(
            "POSITION_ACTION",
            "REJECTED_COUNTERFACTUAL_POSITION_ACTION" if rejected else "POSITION_ACTION",
            action_identity,
            payload.get("first_latched_close_action_fact_boundary"),
        )
    scheduled_identity = payload.get("scheduled_post_close_attempt_identity")
    if scheduled_identity is not None:
        if rejected:
            direct(
                "ATTEMPT_CONTROL",
                scheduled_identity,
                payload.get("scheduled_post_close_attempt_fact_boundary"),
            )
        else:
            local(
                "ATTEMPT_CONTROL",
                "POST_CLOSE_ATTEMPT_SCHEDULED",
                scheduled_identity,
                payload.get("scheduled_post_close_attempt_fact_boundary"),
            )
    terminal_identity = payload.get("post_close_attempt_terminal_identity")
    if terminal_identity is not None:
        if rejected:
            direct(
                "ATTEMPT_CONTROL",
                terminal_identity,
                payload.get("post_close_attempt_terminal_fact_boundary"),
            )
        else:
            local(
                "ATTEMPT_CONTROL",
                "POST_CLOSE_ATTEMPT_TERMINAL",
                terminal_identity,
                payload.get("post_close_attempt_terminal_fact_boundary"),
            )
    witnesses = payload.get("natural_terminal_lifecycle_witnesses")
    if not isinstance(witnesses, list):
        raise PayloadValidationError("natural_terminal_lifecycle_witnesses must be an array")
    if state == "MATURE_UNKNOWN":
        for index, member in enumerate(witnesses):
            witness = _mapping(member, f"natural lifecycle witness {index}")
            direct(
                "INSTRUMENT_LIFECYCLE",
                witness.get("source_identity"),
                witness.get("witness_fact_boundary"),
            )
    supervisor_identity = payload.get("terminal_supervisor_source_identity")
    if supervisor_identity is not None:
        direct(
            "SUPERVISOR_CONTROL",
            supervisor_identity,
            payload.get("terminal_fact_boundary"),
        )


def _derive_close_opportunity_direct_roots(
    payload: Mapping[str, object],
    *,
    direct: Callable[[str, object, object], None],
) -> None:
    refs = payload.get("commission_source_refs")
    if not isinstance(refs, list):
        raise PayloadValidationError("commission_source_refs must be an array")
    index_ref = payload.get("index_source_ref")
    reason = _string(payload.get("eligibility_reason"), "eligibility_reason")
    expected_commission_count: set[int]
    index_allowed: bool
    index_required: bool
    if reason in {"KNOWN_ATOMIC_UNAVAILABLE", "QUOTE_OR_ATTEMPT_UNKNOWN"}:
        expected_commission_count = {0}
        index_allowed = False
        index_required = False
    elif reason == "COMMISSION_UNKNOWN":
        expected_commission_count = {0, 1, 2}
        index_allowed = False
        index_required = False
    elif reason == "COMMISSION_ABOVE_POLICY":
        expected_commission_count = {2}
        index_allowed = False
        index_required = False
    elif reason == "INDEX_UNKNOWN":
        expected_commission_count = {2}
        index_allowed = True
        index_required = False
    elif reason == "ELIGIBLE_COMPLETE":
        expected_commission_count = {2}
        index_allowed = True
        index_required = True
    else:
        raise PayloadValidationError("invalid close-opportunity eligibility reason")
    if len(refs) not in expected_commission_count:
        raise PayloadValidationError(
            "close-opportunity commission provenance violates first-match rule"
        )
    if (index_ref is not None and not index_allowed) or (index_ref is None and index_required):
        raise PayloadValidationError("close-opportunity index provenance violates first-match rule")
    for index, member in enumerate(refs):
        source = _mapping(member, f"commission_source_refs[{index}]")
        direct(
            "COMMISSION",
            source.get("source_identity"),
            source.get("receipt_fact_boundary"),
        )
    if index_ref is not None:
        source = _mapping(index_ref, "index_source_ref")
        direct(
            "INDEX",
            source.get("source_identity"),
            source.get("receipt_fact_boundary"),
        )


def _add_expected_root(
    roots: dict[tuple[str, str], FactBoundary],
    *,
    role: str,
    identity: str,
    boundary: FactBoundary,
) -> None:
    key = (role, identity)
    existing = roots.get(key)
    if existing is not None and existing != boundary:
        raise PayloadValidationError("one provenance root has conflicting boundaries")
    roots[key] = boundary


def _require_exact_provenance(
    value: Mapping[str, object],
    expected: Mapping[tuple[str, str], FactBoundary],
) -> None:
    provenance = value.get("source_provenance")
    if not isinstance(provenance, list):
        raise PayloadValidationError("source_provenance must be an array")
    actual: list[tuple[str, str, FactBoundary]] = []
    for index, member in enumerate(provenance):
        item = _mapping(member, f"source_provenance[{index}]")
        _exact_keys(
            item,
            {"source_role", "source_identity", "receipt_fact_boundary"},
            f"source_provenance[{index}]",
        )
        actual.append(
            (
                _string(item.get("source_role"), "source_role"),
                _identity(item.get("source_identity"), "source_identity"),
                _graph_boundary(
                    item.get("receipt_fact_boundary"),
                    "receipt_fact_boundary",
                ),
            )
        )
    expected_ordered = [
        (role, identity, expected[(role, identity)]) for role, identity in sorted(expected)
    ]
    if actual != expected_ordered:
        raise PayloadValidationError(
            f"{value.get('object_kind')} exact one-hop provenance mismatch"
        )


def _graph_boundary(value: object, field: str) -> FactBoundary:
    try:
        return FactBoundary.from_object(value)
    except ValueError as exc:
        raise PayloadValidationError(f"{field}: {exc}") from exc


def _expected_object_identity(
    *,
    object_kind: str,
    payload: Mapping[str, object],
    runtime_identity: str,
    radar_policy_identity: str,
    underwriting_policy_identity: str,
    position_policy_identity: str,
    underwriting_contract_digest: str,
    outcome_contract_identity: str,
    code_identity: str,
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
            _non_negative_integer(payload["request_id"], "request_id"),
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
    if object_kind == "UNDERWRITING_POSITION_SUMMARY":
        raw_counts = _integer_mapping(payload["counts"], "counts")
        counts = {key: raw_counts[key] for key in UNDERWRITING_COUNT_KEYS}
        rates = _ordered_rates(payload["rates"], UNDERWRITING_RATE_KEYS)
        status = underwriting_conservation_status(counts)
        if dict(rates) != compute_underwriting_rates(counts):
            raise PayloadValidationError("Underwriting summary rates mismatch")
        if payload["conservation_status"] != status:
            raise PayloadValidationError("Underwriting summary conservation mismatch")
        return canonical_identity(
            "UNDERWRITING_POSITION_SUMMARY",
            underwriting_contract_digest,
            code_identity,
            runtime_identity,
            radar_policy_identity,
            underwriting_policy_identity,
            position_policy_identity,
            _identity(payload["terminal_source_identity"], "terminal source identity"),
            boundary,
            counts,
            dict(rates),
            status,
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
    if object_kind == "SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY":
        raw_counts = _integer_mapping(payload["counts"], "counts")
        counts = {key: raw_counts[key] for key in COHORT_COUNT_KEYS}
        rates = _ordered_rates(payload["rates"], COHORT_RATE_KEYS)
        evidence_status = _string(payload["evidence_status"], "evidence_status")
        status = cohort_conservation_status(counts, evidence_status=evidence_status)
        if dict(rates) != compute_cohort_rates(
            counts,
            evidence_status=evidence_status,
        ):
            raise PayloadValidationError("cohort summary rates mismatch")
        if payload["conservation_status"] != status:
            raise PayloadValidationError("cohort summary conservation mismatch")
        return canonical_identity(
            "CohortSummaryIdentity",
            outcome_contract_identity,
            runtime_identity,
            _identity(payload["manifest_identity"], "manifest_identity"),
            boundary,
        )
    return None


def _validate_common_shapes(payload: Mapping[str, object]) -> None:
    for key, value in payload.items():
        if _is_decimal_field(key) and value is not None:
            _decimal(value, key)
        if key == "canonical_leg_identities":
            identities = _string_array(value, key)
            if len(identities) != 2 or len(set(identities)) != 2:
                raise PayloadValidationError("canonical_leg_identities requires two distinct legs")
            for identity in identities:
                _identity(identity, key)
        if key in {"commission_source_refs", "entry_commission_source_refs"}:
            _commission_refs(value, key)
        if (
            key
            in {
                "index_source_ref",
                "entry_index_source_ref",
                "entry_combo_quote_source_ref",
                "entry_short_leg_mark_iv_source_ref",
                "combo_quote_source_ref",
            }
            and value is not None
        ):
            _direct_source_ref(value, key)


def _validate_enums(object_kind: str, payload: Mapping[str, object]) -> None:
    enums: dict[str, set[str]] = {
        "availability": {"NOT_EVALUATED", "UNKNOWN", "EVALUABLE"},
        "economic_action": {"CANDIDATE", "WATCH", "ABSTAIN"},
        "serialized_action": {"HOLD", "CLOSE", "UNKNOWN"},
        "close_quote_state": {
            "ATOMIC_COMBO_CLOSE_QUOTE",
            "LEGGED_CLOSE_REFERENCE",
            "UNEXECUTABLE",
            "UNKNOWN",
        },
        "eligibility": {"ELIGIBLE", "INELIGIBLE", "UNKNOWN"},
        "terminal_outcome": {
            "ENTRY_EMITTED",
            "KNOWN_COMPLETE_NO_ENTRY",
            "KNOWN_INVALIDATED_BEFORE_REFRESH",
            "UNKNOWN_CONSUMED",
        },
        "terminal_status": set(POST_CLOSE_TERMINAL_STATUSES),
        "terminal_owner": {"ORDINARY", "STOP", "FAILURE"},
        "terminal_state": set(TERMINAL_STATES),
        "lifecycle_state": {"PENDING"},
        "current_index_availability": {"KNOWN", "UNKNOWN"},
        "economic_availability": {"KNOWN", "UNKNOWN"},
        "gross_cashflow_availability": {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"},
        "derived_economics_availability": {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"},
        "comparison_availability": {"KNOWN", "UNKNOWN"},
        "eligibility_reason": {
            "KNOWN_ATOMIC_UNAVAILABLE",
            "QUOTE_OR_ATTEMPT_UNKNOWN",
            "COMMISSION_UNKNOWN",
            "COMMISSION_ABOVE_POLICY",
            "INDEX_UNKNOWN",
            "ELIGIBLE_COMPLETE",
        },
    }
    for field, allowed in enums.items():
        if field in payload and payload[field] not in allowed:
            raise PayloadValidationError(f"{field} has an invalid enum value")
    for field in (
        "ordered_predicate_truth_vector",
        "ordered_latched_close_reason_vector",
        "secondary_close_reasons",
    ):
        if field not in payload:
            continue
        values = _string_array(payload[field], field)
        if field == "ordered_predicate_truth_vector":
            if len(values) != 9 or any(
                value not in {"TRUE", "FALSE", "UNKNOWN"} for value in values
            ):
                raise PayloadValidationError("Position truth vector requires exact nine values")
        else:
            if len(values) != len(set(values)) or any(
                value not in POSITION_CLOSE_REASONS for value in values
            ):
                raise PayloadValidationError(f"{field} has invalid close reasons")
            if values != tuple(reason for reason in POSITION_CLOSE_REASONS if reason in values):
                raise PayloadValidationError(f"{field} is outside the close-reason total order")
    if object_kind in {"SHADOW_OUTCOME", "REJECTED_COUNTERFACTUAL_OUTCOME"}:
        _validate_outcome_matrix(payload)
    if object_kind == "ALIGNED_POLICY_NO_TRADE_PAIR":
        _validate_aligned_pair(payload)


def _validate_levels_and_arithmetic(
    object_kind: str,
    payload: Mapping[str, object],
) -> None:
    for levels_field in ("consumed_levels", "entry_consumed_levels"):
        if levels_field not in payload:
            continue
        levels = payload[levels_field]
        if not isinstance(levels, list):
            raise PayloadValidationError(f"{levels_field} must be an array")
        if not levels:
            if payload.get("close_quote_state") == "ATOMIC_COMBO_CLOSE_QUOTE":
                raise PayloadValidationError("atomic quote requires non-empty consumed levels")
            continue
        quantity = _decimal(payload.get("full_quantity_btc"), "full_quantity_btc")
        if quantity <= 0:
            raise PayloadValidationError("full_quantity_btc must be positive")
        total = Decimal(0)
        prices: list[Decimal] = []
        for index, member in enumerate(levels):
            level = _mapping(member, f"{levels_field}[{index}]")
            _exact_keys(
                level,
                {"price_usdc_per_btc", "amount_btc"},
                f"{levels_field}[{index}]",
            )
            price = _decimal(level["price_usdc_per_btc"], "price_usdc_per_btc")
            amount = _decimal(level["amount_btc"], "amount_btc")
            if amount <= 0:
                raise PayloadValidationError("consumed level amount must be positive")
            total += amount
            prices.append(price)
        if total != quantity:
            raise PayloadValidationError(f"{levels_field} must consume exact full quantity")
        direction = payload.get("close_direction", payload.get("entry_direction"))
        if direction == "BUY" and prices != sorted(prices):
            raise PayloadValidationError("BUY consumed levels must be best-to-worse ascending")
        if direction == "SELL" and prices != sorted(prices, reverse=True):
            raise PayloadValidationError("SELL consumed levels must be best-to-worse descending")
    if object_kind in {
        "UNDERWRITING_ACTION",
        "SHADOW_ENTRY",
        "REJECTED_COUNTERFACTUAL_ANCHOR",
    }:
        _validate_entry_economics(payload)
    if object_kind in {
        "CLOSE_OPPORTUNITY_EVALUATION",
        "SHADOW_CLOSE_OPPORTUNITY",
        "SHADOW_COUNTERFACTUAL_EXIT",
        "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
        "REJECTED_COUNTERFACTUAL_EXIT",
    }:
        _validate_close_economics(payload)


def _validate_entry_economics(payload: Mapping[str, object]) -> None:
    if payload.get("gross_entry_credit_usdc") is None:
        return
    gross = _decimal(payload["gross_entry_credit_usdc"], "gross_entry_credit_usdc")
    fee = _decimal(payload["entry_fee_reserve_usdc"], "entry_fee_reserve_usdc")
    net = _decimal(payload["net_entry_credit_usdc"], "net_entry_credit_usdc")
    if net != gross - fee:
        raise PayloadValidationError("entry net credit arithmetic mismatch")
    if "actual_all_in_max_loss_usdc" in payload:
        if payload["actual_all_in_max_loss_usdc"] is not None:
            raise PayloadValidationError("actual all-in max loss must remain null")
        if payload.get("actual_all_in_max_loss_availability") != "UNKNOWN":
            raise PayloadValidationError("actual all-in max loss availability must be UNKNOWN")


def _validate_close_economics(payload: Mapping[str, object]) -> None:
    availability = payload.get("derived_economics_availability", "KNOWN")
    economic_fields = (
        "gross_close_cashflow_usdc",
        "close_fee_reserve_usdc",
        "net_close_cashflow_usdc",
        "net_close_debit_usdc",
        "projected_shadow_net_pnl_usdc",
        "projected_net_loss_usdc",
    )
    if "eligibility_reason" in payload:
        _validate_close_opportunity_matrix(payload, economic_fields)
    if availability in {"UNKNOWN", "NOT_APPLICABLE"}:
        if any(payload.get(field) is not None for field in economic_fields[1:]):
            raise PayloadValidationError("unknown close economics require null derived fields")
        return
    if not all(field in payload and payload[field] is not None for field in economic_fields):
        return
    gross = _decimal(payload["gross_close_cashflow_usdc"], "gross_close_cashflow_usdc")
    fee = _decimal(payload["close_fee_reserve_usdc"], "close_fee_reserve_usdc")
    net = _decimal(payload["net_close_cashflow_usdc"], "net_close_cashflow_usdc")
    debit = _decimal(payload["net_close_debit_usdc"], "net_close_debit_usdc")
    projected = _decimal(
        payload["projected_shadow_net_pnl_usdc"],
        "projected_shadow_net_pnl_usdc",
    )
    loss = _decimal(payload["projected_net_loss_usdc"], "projected_net_loss_usdc")
    if net != gross - fee or debit != max(Decimal(0), -net):
        raise PayloadValidationError("close cashflow arithmetic mismatch")
    if loss != max(Decimal(0), -projected):
        raise PayloadValidationError("projected loss arithmetic mismatch")


def _validate_close_opportunity_matrix(
    payload: Mapping[str, object],
    economic_fields: tuple[str, ...],
) -> None:
    reason = _string(payload["eligibility_reason"], "eligibility_reason")
    eligibility = _string(payload["eligibility"], "eligibility")
    gross_availability = _string(
        payload["gross_cashflow_availability"],
        "gross_cashflow_availability",
    )
    derived_availability = _string(
        payload["derived_economics_availability"],
        "derived_economics_availability",
    )
    quote = payload["close_quote_evaluation_identity"]
    attempt = payload["attempt_terminal_identity"]
    attempt_boundary = payload["attempt_terminal_fact_boundary"]
    if (quote is None) == (attempt is None):
        raise PayloadValidationError(
            "close opportunity requires exactly one quote or attempt terminal"
        )
    if quote is not None:
        _identity(quote, "close_quote_evaluation_identity")
        if attempt_boundary is not None:
            raise PayloadValidationError("quote-owned opportunity cannot carry attempt boundary")
    else:
        _identity(attempt, "attempt_terminal_identity")
        if attempt_boundary is None:
            raise PayloadValidationError("attempt-owned opportunity requires its boundary")
    commission_refs = payload["commission_source_refs"]
    if not isinstance(commission_refs, list):
        raise PayloadValidationError("commission_source_refs must be an array")
    index_ref = payload["index_source_ref"]
    commission_values = (
        payload["short_leg_taker_commission_fraction"],
        payload["long_leg_taker_commission_fraction"],
    )
    derived_values = tuple(payload[field] for field in economic_fields[1:])
    expected = {
        "KNOWN_ATOMIC_UNAVAILABLE": (
            "INELIGIBLE",
            "NOT_APPLICABLE",
            "NOT_APPLICABLE",
        ),
        "QUOTE_OR_ATTEMPT_UNKNOWN": ("UNKNOWN", "UNKNOWN", "UNKNOWN"),
        "COMMISSION_UNKNOWN": ("UNKNOWN", "KNOWN", "UNKNOWN"),
        "COMMISSION_ABOVE_POLICY": ("INELIGIBLE", "KNOWN", "UNKNOWN"),
        "INDEX_UNKNOWN": ("UNKNOWN", "KNOWN", "UNKNOWN"),
        "ELIGIBLE_COMPLETE": ("ELIGIBLE", "KNOWN", "KNOWN"),
    }[reason]
    if (eligibility, gross_availability, derived_availability) != expected:
        raise PayloadValidationError("close opportunity first-match state matrix mismatch")
    if gross_availability == "KNOWN":
        _decimal(payload["gross_close_cashflow_usdc"], "gross_close_cashflow_usdc")
    elif payload["gross_close_cashflow_usdc"] is not None:
        raise PayloadValidationError("unavailable gross cashflow must be null")
    if reason in {"KNOWN_ATOMIC_UNAVAILABLE", "QUOTE_OR_ATTEMPT_UNKNOWN"}:
        if (
            commission_refs
            or index_ref is not None
            or any(member is not None for member in commission_values)
        ):
            raise PayloadValidationError("early close rule consumed later commission/index facts")
    elif reason == "COMMISSION_UNKNOWN":
        if (
            len(commission_refs) > 2
            or index_ref is not None
            or any(member is not None for member in commission_values)
        ):
            raise PayloadValidationError("commission-unknown first-match matrix mismatch")
    elif reason == "COMMISSION_ABOVE_POLICY":
        if (
            len(commission_refs) != 2
            or index_ref is not None
            or any(member is None for member in commission_values)
        ):
            raise PayloadValidationError("commission-above-policy first-match matrix mismatch")
    elif reason == "INDEX_UNKNOWN":
        if len(commission_refs) != 2 or any(member is None for member in commission_values):
            raise PayloadValidationError("index-unknown first-match matrix mismatch")
    elif (
        len(commission_refs) != 2
        or index_ref is None
        or any(member is None for member in commission_values)
    ):
        raise PayloadValidationError("eligible close opportunity lacks exact source roots")
    if derived_availability == "KNOWN":
        if any(member is None for member in derived_values):
            raise PayloadValidationError("known derived close economics must be complete")
    elif any(member is not None for member in derived_values):
        raise PayloadValidationError("unavailable derived close economics must be null")


def _validate_outcome_matrix(payload: Mapping[str, object]) -> None:
    state = _string(payload["terminal_state"], "terminal_state")
    selected = payload["selected_exit_identity"]
    entry_fields = (
        "gross_entry_credit_usdc",
        "entry_fee_reserve_usdc",
        "net_entry_credit_usdc",
        "contractual_payoff_max_loss_ex_fees_usdc",
        "entry_fee_reserved_payoff_loss_usdc",
        "underwriting_reserved_loss_usdc",
    )
    entry_values = {field: _decimal(payload[field], field) for field in entry_fields}
    if (
        entry_values["net_entry_credit_usdc"]
        != entry_values["gross_entry_credit_usdc"] - entry_values["entry_fee_reserve_usdc"]
    ):
        raise PayloadValidationError("Outcome Entry audit arithmetic mismatch")
    economics = (
        "gross_close_cashflow_usdc",
        "close_fee_reserve_usdc",
        "net_close_cashflow_usdc",
        "gross_pnl_usdc",
        "total_public_fee_reserve_usdc",
        "net_pnl_after_public_standard_fee_reserve_usdc",
        "net_loss_usdc",
    )
    witnesses = payload["natural_terminal_lifecycle_witnesses"]
    censor_mask = payload["censor_mask"]
    if not isinstance(witnesses, list) or not isinstance(censor_mask, list):
        raise PayloadValidationError("Outcome witness and censor fields must be arrays")
    actual_availability = _mapping(payload["actual_availability"], "actual_availability")
    if dict(actual_availability) != ACTUAL_AVAILABILITY_UNKNOWN:
        raise PayloadValidationError("actual availability matrix mismatch")
    if any(payload[field] is not None for field in ACTUAL_FIELDS):
        raise PayloadValidationError("actual PUBLIC_SHADOW fields must remain null")
    close_tuple_fields = (
        "first_latched_close_action_identity",
        "first_latched_close_action_fact_boundary",
        "scheduled_post_close_attempt_identity",
        "scheduled_post_close_attempt_fact_boundary",
        "post_close_attempt_terminal_identity",
        "post_close_attempt_terminal_status",
        "post_close_attempt_terminal_owner",
        "post_close_attempt_terminal_fact_boundary",
    )
    close_tuple_present = [payload[field] is not None for field in close_tuple_fields]
    if any(close_tuple_present) and not all(close_tuple_present):
        raise PayloadValidationError(
            "Outcome first CLOSE and attempt tuple must be all required or all null"
        )
    has_close_tuple = all(close_tuple_present)
    status: str | None = None
    owner: str | None = None
    action_boundary: FactBoundary | None = None
    attempt_boundary: FactBoundary | None = None
    outcome_boundary = _outcome_boundary(payload["terminal_fact_boundary"])
    if has_close_tuple:
        _identity(
            payload["first_latched_close_action_identity"],
            "first_latched_close_action_identity",
        )
        _identity(
            payload["scheduled_post_close_attempt_identity"],
            "scheduled_post_close_attempt_identity",
        )
        _identity(
            payload["post_close_attempt_terminal_identity"],
            "post_close_attempt_terminal_identity",
        )
        action_boundary = _outcome_boundary(payload["first_latched_close_action_fact_boundary"])
        schedule_boundary = _outcome_boundary(payload["scheduled_post_close_attempt_fact_boundary"])
        attempt_boundary = _outcome_boundary(payload["post_close_attempt_terminal_fact_boundary"])
        if schedule_boundary != action_boundary:
            raise PayloadValidationError(
                "Outcome scheduled attempt boundary must equal first CLOSE"
            )
        if attempt_boundary.causal_seq < action_boundary.causal_seq:
            raise PayloadValidationError("Outcome attempt terminal precedes first CLOSE")
        if attempt_boundary.causal_seq > outcome_boundary.causal_seq:
            raise PayloadValidationError("Outcome attempt terminal follows Outcome")
        status = _string(
            payload["post_close_attempt_terminal_status"],
            "post_close_attempt_terminal_status",
        )
        owner = _string(
            payload["post_close_attempt_terminal_owner"],
            "post_close_attempt_terminal_owner",
        )
        if status not in POST_CLOSE_TERMINAL_STATUSES:
            raise PayloadValidationError("post-close attempt terminal status is invalid")
        if owner not in {"ORDINARY", "STOP", "FAILURE"}:
            raise PayloadValidationError("post-close attempt terminal owner is invalid")
        if owner == "ORDINARY" and status == "CENSORED":
            raise PayloadValidationError("ordinary attempt terminal cannot be CENSORED")
        if owner in {"STOP", "FAILURE"} and status != "CENSORED":
            raise PayloadValidationError("barrier-owned attempt terminal must be CENSORED")
    if state == "MATURE_KNOWN":
        _identity(selected, "selected_exit_identity")
        if (
            not has_close_tuple
            or owner != "ORDINARY"
            or action_boundary is None
            or not outcome_boundary.is_strictly_after(action_boundary)
        ):
            raise PayloadValidationError(
                "MATURE_KNOWN requires the complete ordinary first CLOSE attempt tuple"
            )
        if payload["terminal_supervisor_source_identity"] is not None:
            raise PayloadValidationError("mature Outcome cannot carry a terminal supervisor")
        if witnesses or censor_mask or payload["economic_availability"] != "KNOWN":
            raise PayloadValidationError("MATURE_KNOWN null matrix mismatch")
        if any(payload[field] is None for field in economics):
            raise PayloadValidationError("MATURE_KNOWN requires complete economics")
        gross_entry = _decimal(payload["gross_entry_credit_usdc"], "gross_entry_credit_usdc")
        entry_fee = _decimal(payload["entry_fee_reserve_usdc"], "entry_fee_reserve_usdc")
        gross_close = _decimal(payload["gross_close_cashflow_usdc"], "gross_close_cashflow_usdc")
        close_fee = _decimal(payload["close_fee_reserve_usdc"], "close_fee_reserve_usdc")
        gross_pnl = _decimal(payload["gross_pnl_usdc"], "gross_pnl_usdc")
        total_fee = _decimal(
            payload["total_public_fee_reserve_usdc"],
            "total_public_fee_reserve_usdc",
        )
        net_pnl = _decimal(
            payload["net_pnl_after_public_standard_fee_reserve_usdc"],
            "net_pnl_after_public_standard_fee_reserve_usdc",
        )
        loss = _decimal(payload["net_loss_usdc"], "net_loss_usdc")
        if (
            gross_pnl != gross_entry + gross_close
            or total_fee != entry_fee + close_fee
            or net_pnl != gross_pnl - total_fee
            or loss != max(Decimal(0), -net_pnl)
        ):
            raise PayloadValidationError("Outcome economics arithmetic mismatch")
    else:
        if selected is not None or any(payload[field] is not None for field in economics):
            raise PayloadValidationError("unknown/censored Outcome requires null close economics")
        if payload["economic_availability"] != "UNKNOWN":
            raise PayloadValidationError("unknown/censored Outcome economics must be UNKNOWN")
        expected_mask = {
            "MATURE_UNKNOWN": [],
            "CENSORED_AT_STOP": ["STOP"],
            "CENSORED_AT_FAILURE": ["FAILURE"],
        }[state]
        if censor_mask != expected_mask:
            raise PayloadValidationError("Outcome censor mask mismatch")
        if state == "MATURE_UNKNOWN":
            if (
                not has_close_tuple
                or owner != "ORDINARY"
                or action_boundary is None
                or not outcome_boundary.is_strictly_after(action_boundary)
            ):
                raise PayloadValidationError(
                    "MATURE_UNKNOWN requires the complete ordinary first CLOSE attempt tuple"
                )
            if payload["terminal_supervisor_source_identity"] is not None:
                raise PayloadValidationError("mature Outcome cannot carry a terminal supervisor")
            _validate_lifecycle_witnesses(witnesses)
        else:
            if witnesses:
                raise PayloadValidationError("censored Outcome cannot carry lifecycle witnesses")
            _identity(
                payload["terminal_supervisor_source_identity"],
                "terminal_supervisor_source_identity",
            )
            expected_owner = "STOP" if state == "CENSORED_AT_STOP" else "FAILURE"
            if has_close_tuple and owner != "ORDINARY":
                if owner != expected_owner or status != "CENSORED":
                    raise PayloadValidationError(
                        "censored Outcome barrier-owned attempt does not match its state"
                    )
                if (
                    payload["post_close_attempt_terminal_fact_boundary"]
                    != payload["terminal_fact_boundary"]
                ):
                    raise PayloadValidationError(
                        "barrier-owned attempt must terminate at the Outcome boundary"
                    )


def _outcome_boundary(value: object) -> FactBoundary:
    try:
        return FactBoundary.from_object(value)
    except ValueError as exc:
        raise PayloadValidationError(f"invalid Outcome FactBoundary: {exc}") from exc


def _validate_aligned_pair(payload: Mapping[str, object]) -> None:
    family = payload["pair_family"]
    arms = (payload["policy_arm"], payload["alternative_arm"])
    if family == "ADMITTED":
        if arms != ("SHADOW_TRADE", "NO_TRADE"):
            raise PayloadValidationError("admitted aligned-pair arms mismatch")
    elif family == "REJECTED":
        if arms != ("NO_TRADE", "REJECTED_COUNTERFACTUAL_TRADE"):
            raise PayloadValidationError("rejected aligned-pair arms mismatch")
    else:
        raise PayloadValidationError("aligned pair family is invalid")
    if _decimal(payload["no_trade_cashflow_usdc"], "no_trade_cashflow_usdc") != 0:
        raise PayloadValidationError("NO_TRADE cashflow must be exact zero")
    state = payload["terminal_state"]
    comparison = payload["comparison_availability"]
    trade_pnl = payload["trade_net_pnl_after_public_standard_fee_reserve_usdc"]
    advantage = payload["policy_advantage_usdc"]
    if state == "MATURE_KNOWN":
        pnl = _decimal(trade_pnl, "trade PnL")
        expected = pnl if family == "ADMITTED" else -pnl
        if comparison != "KNOWN" or _decimal(advantage, "policy advantage") != expected:
            raise PayloadValidationError("aligned pair comparison arithmetic mismatch")
    elif comparison != "UNKNOWN" or trade_pnl is not None or advantage is not None:
        raise PayloadValidationError("unknown/censored aligned pair must be incomparable")


def _validate_lifecycle_witnesses(value: object) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise PayloadValidationError("natural terminal requires exactly two lifecycle witnesses")
    roles: list[str] = []
    for index, member in enumerate(value):
        witness = _mapping(member, f"lifecycle witness {index}")
        _exact_keys(
            witness,
            {
                "canonical_leg_role",
                "instrument_identity",
                "lifecycle_state",
                "source_identity",
                "witness_fact_boundary",
            },
            "lifecycle witness",
        )
        role = _string(witness["canonical_leg_role"], "canonical_leg_role")
        roles.append(role)
        if witness["lifecycle_state"] not in {"delivered", "archivized"}:
            raise PayloadValidationError("natural lifecycle state is invalid")
        _identity(witness["instrument_identity"], "instrument_identity")
        _identity(witness["source_identity"], "source_identity")
    if roles != ["SHORT", "LONG"]:
        raise PayloadValidationError("lifecycle witnesses must be ordered SHORT, LONG")


def _commission_refs(value: object, field: str) -> None:
    if not isinstance(value, list):
        raise PayloadValidationError(f"{field} must be an array")
    roles: list[str] = []
    for index, member in enumerate(value):
        item = _mapping(member, f"{field}[{index}]")
        _exact_keys(
            item,
            {"canonical_leg_role", "source_identity", "receipt_fact_boundary"},
            f"{field}[{index}]",
        )
        role = _string(item["canonical_leg_role"], "canonical_leg_role")
        if role not in {"SHORT", "LONG"}:
            raise PayloadValidationError("commission source role is invalid")
        roles.append(role)
        _identity(item["source_identity"], "source_identity")
    if roles != sorted(set(roles), key=("SHORT", "LONG").index):
        raise PayloadValidationError("commission refs must be unique and ordered SHORT, LONG")


def _direct_source_ref(value: object, field: str) -> None:
    item = _mapping(value, field)
    _exact_keys(item, {"source_identity", "receipt_fact_boundary"}, field)
    _identity(item["source_identity"], "source_identity")


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


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or DECIMAL_PATTERN.fullmatch(value) is None:
        raise PayloadValidationError(f"{field} must be one canonical Decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise PayloadValidationError(f"{field} is not a Decimal") from exc
    if not parsed.is_finite() or canonical_decimal(parsed) != value:
        raise PayloadValidationError(f"{field} is not canonical")
    return parsed


def _is_decimal_field(field: str) -> bool:
    return field.endswith(
        (
            "_usdc",
            "_btc",
            "_fraction",
            "_usdc_per_btc",
        )
    )


def _reject_floats(value: object, field: str) -> None:
    if isinstance(value, float):
        raise PayloadValidationError(f"{field} cannot contain binary floating point")
    if isinstance(value, Mapping):
        for key, member in value.items():
            _reject_floats(member, f"{field}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, member in enumerate(value):
            _reject_floats(member, f"{field}[{index}]")


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


def _exact_request_params(value: object) -> dict[str, object]:
    params = _mapping(value, "request_params")
    _exact_keys(params, {"instrument_name", "depth"}, "request_params")
    instrument_name = _string(params["instrument_name"], "request_params.instrument_name")
    depth = _non_negative_integer(params["depth"], "request_params.depth")
    if depth != 10_000:
        raise PayloadValidationError("request_params.depth must be exactly 10000")
    return {"instrument_name": instrument_name, "depth": depth}


def _integer_mapping(value: object, field: str) -> dict[str, int]:
    mapping = _mapping(value, field)
    result: dict[str, int] = {}
    for key, member in mapping.items():
        result[key] = _non_negative_integer(member, f"{field}.{key}")
    return result


def _ordered_rates(
    value: object,
    keys: tuple[str, ...],
) -> dict[str, dict[str, int] | None]:
    mapping = _mapping(value, "rates")
    _exact_keys(mapping, set(keys), "rates")
    result: dict[str, dict[str, int] | None] = {}
    for key in keys:
        member = mapping[key]
        if member is None:
            result[key] = None
            continue
        rate = _mapping(member, f"rates.{key}")
        _exact_keys(rate, {"numerator", "denominator"}, f"rates.{key}")
        numerator = _non_negative_integer(rate["numerator"], f"rates.{key}.numerator")
        denominator = _non_negative_integer(rate["denominator"], f"rates.{key}.denominator")
        if denominator == 0:
            raise PayloadValidationError(f"rates.{key}.denominator must be positive")
        result[key] = {
            "numerator": numerator,
            "denominator": denominator,
        }
    return result


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise PayloadValidationError(f"{field} requires exact keys")


def _nested(value: Mapping[str, object], path: str) -> object:
    current: object = value
    for member in path.split("."):
        current = _mapping(current, path).get(member)
    return current


def _validate_unique_relation(
    values: Sequence[Mapping[str, object]],
    relation_path: str,
) -> None:
    seen: set[object] = set()
    for value in values:
        relation = _nested(value, relation_path)
        if relation in seen:
            raise PayloadValidationError(f"duplicate lifecycle relation: {relation_path}")
        seen.add(relation)
