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
    _validate_position_source_graph(object_kind, payload)
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
    for rejected_exit in by_kind.get("REJECTED_COUNTERFACTUAL_EXIT", ()):
        payload = _mapping(rejected_exit.get("payload"), "rejected exit payload")
        quote_identity = _identity(
            payload.get("close_quote_evaluation_identity"),
            "close_quote_evaluation_identity",
        )
        quote = by_kind_identity.get(
            ("REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION", quote_identity)
        )
        if quote is None:
            raise PayloadValidationError("rejected exit is missing its owning close quote")
        quote_payload = _mapping(quote.get("payload"), "rejected close quote payload")
        if payload.get("consumed_rule_scoped_quote_fingerprint") != quote_payload.get(
            "consumed_rule_scoped_quote_fingerprint"
        ):
            raise PayloadValidationError(
                "rejected exit quote fingerprint differs from its owning close quote"
            )
    _validate_position_source_chains(
        by_kind=by_kind,
        by_kind_identity=by_kind_identity,
    )
    _validate_position_action_chains(
        by_kind=by_kind,
        by_kind_identity=by_kind_identity,
    )


def _validate_position_source_chains(
    *,
    by_kind: Mapping[str, Sequence[Mapping[str, object]]],
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
) -> None:
    families = (
        ("POSITION_EVALUATION", "shadow_entry_identity", False),
        (
            "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
            "rejected_observation_identity",
            True,
        ),
    )
    for evaluation_kind, owner_field, rejected in families:
        evaluations_by_owner: dict[str, list[Mapping[str, object]]] = {}
        for value in by_kind.get(evaluation_kind, ()):
            evaluation = _mapping(value.get("payload"), "Position evaluation payload")
            if not {
                "entry_index_usdc_per_btc",
                "entry_short_leg_mark_iv_fraction",
                "prior_evaluation_index_usdc_per_btc",
                "current_index_usdc_per_btc",
                "next_evaluation_index_usdc_per_btc",
            }.issubset(evaluation):
                continue
            owner_identity = _identity(evaluation.get(owner_field), owner_field)
            evaluations_by_owner.setdefault(owner_identity, []).append(value)

        for owner_identity, values in evaluations_by_owner.items():
            anchor_identity = owner_identity
            anchor_kind = "SHADOW_ENTRY"
            if rejected:
                observation = by_kind_identity.get(
                    ("REJECTED_COUNTERFACTUAL_OBSERVATION", owner_identity)
                )
                if observation is None:
                    raise PayloadValidationError(
                        "rejected Position evaluation is missing its observation"
                    )
                anchor_identity = _identity(
                    _mapping(
                        observation.get("payload"),
                        "rejected observation payload",
                    ).get("rejected_anchor_identity"),
                    "rejected_anchor_identity",
                )
                anchor_kind = "REJECTED_COUNTERFACTUAL_ANCHOR"
            anchor_value = by_kind_identity.get((anchor_kind, anchor_identity))
            if anchor_value is None:
                raise PayloadValidationError("Position evaluation is missing its entry anchor")
            anchor = _mapping(anchor_value.get("payload"), "Position entry anchor payload")
            if rejected:
                expected_entry = {
                    field: anchor.get(field)
                    for field in (
                        "entry_index_usdc_per_btc",
                        "entry_index_source_identity",
                        "entry_index_fact_boundary",
                        "entry_short_leg_mark_iv_fraction",
                        "entry_short_leg_mark_iv_source_identity",
                        "entry_short_leg_mark_iv_fact_boundary",
                    )
                }
            else:
                index_source = _mapping(
                    anchor.get("entry_index_source_ref"),
                    "entry_index_source_ref",
                )
                ticker_source = _mapping(
                    anchor.get("entry_short_leg_mark_iv_source_ref"),
                    "entry_short_leg_mark_iv_source_ref",
                )
                expected_entry = {
                    "entry_index_usdc_per_btc": anchor.get("entry_index_usdc_per_btc"),
                    "entry_index_source_identity": index_source.get("source_identity"),
                    "entry_index_fact_boundary": index_source.get("receipt_fact_boundary"),
                    "entry_short_leg_mark_iv_fraction": anchor.get(
                        "entry_short_leg_mark_iv_fraction"
                    ),
                    "entry_short_leg_mark_iv_source_identity": ticker_source.get("source_identity"),
                    "entry_short_leg_mark_iv_fact_boundary": ticker_source.get(
                        "receipt_fact_boundary"
                    ),
                }
            expected_prior = (
                expected_entry["entry_index_usdc_per_btc"],
                expected_entry["entry_index_source_identity"],
                expected_entry["entry_index_fact_boundary"],
            )
            for value in sorted(
                values,
                key=lambda item: (
                    _graph_boundary(
                        item.get("fact_boundary"),
                        "Position evaluation boundary",
                    ).causal_seq
                ),
            ):
                evaluation = _mapping(value.get("payload"), "Position evaluation payload")
                if any(
                    evaluation.get(field) != expected for field, expected in expected_entry.items()
                ):
                    raise PayloadValidationError(
                        "Position evaluation entry source graph differs from its entry anchor"
                    )
                actual_prior = (
                    evaluation.get("prior_evaluation_index_usdc_per_btc"),
                    evaluation.get("prior_evaluation_index_source_identity"),
                    evaluation.get("prior_evaluation_index_fact_boundary"),
                )
                if actual_prior != expected_prior:
                    raise PayloadValidationError(
                        "Position evaluation prior index anchor differs from the committed chain"
                    )
                if not rejected:
                    roots: dict[tuple[str, str], FactBoundary] = {}
                    _add_expected_root(
                        roots,
                        role="ANCHOR",
                        identity=anchor_identity,
                        boundary=_graph_boundary(
                            anchor_value.get("fact_boundary"),
                            "SHADOW_ENTRY.fact_boundary",
                        ),
                    )
                    for role, identity_field, boundary_field in (
                        (
                            "POSITION_FACT",
                            "consumed_position_fact_fingerprint",
                            "evaluation_fact_boundary",
                        ),
                        (
                            "POSITION_FACT",
                            "entry_short_leg_mark_iv_source_identity",
                            "entry_short_leg_mark_iv_fact_boundary",
                        ),
                        (
                            "INDEX",
                            "entry_index_source_identity",
                            "entry_index_fact_boundary",
                        ),
                        (
                            "INDEX",
                            "prior_evaluation_index_source_identity",
                            "prior_evaluation_index_fact_boundary",
                        ),
                    ):
                        _add_expected_root(
                            roots,
                            role=role,
                            identity=_identity(evaluation.get(identity_field), identity_field),
                            boundary=_graph_boundary(
                                evaluation.get(boundary_field),
                                boundary_field,
                            ),
                        )
                    if evaluation.get("current_index_availability") == "KNOWN":
                        _add_expected_root(
                            roots,
                            role="INDEX",
                            identity=_identity(
                                evaluation.get("current_index_source_identity"),
                                "current_index_source_identity",
                            ),
                            boundary=_graph_boundary(
                                evaluation.get("current_index_fact_boundary"),
                                "current_index_fact_boundary",
                            ),
                        )
                    _require_exact_provenance(value, roots)
                if evaluation.get("current_index_availability") == "KNOWN":
                    expected_prior = (
                        evaluation.get("next_evaluation_index_usdc_per_btc"),
                        evaluation.get("current_index_source_identity"),
                        evaluation.get("current_index_fact_boundary"),
                    )


def _validate_position_action_chains(
    *,
    by_kind: Mapping[str, Sequence[Mapping[str, object]]],
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
) -> None:
    families = (
        (
            "POSITION_EVALUATION",
            "POSITION_ACTION",
            "shadow_entry_identity",
            "position_evaluation_identity",
            False,
        ),
        (
            "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
            "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
            "rejected_observation_identity",
            "rejected_position_evaluation_identity",
            True,
        ),
    )
    for (
        evaluation_kind,
        action_kind,
        owner_field,
        action_evaluation_field,
        rejected,
    ) in families:
        actions_by_owner: dict[str, list[Mapping[str, object]]] = {}
        action_evaluations: set[str] = set()
        for value in by_kind.get(action_kind, ()):
            action = _mapping(value.get("payload"), "Position action payload")
            if not {
                action_evaluation_field,
                "serialized_action",
                "ordered_predicate_truth_vector",
                "ordered_latched_close_reason_vector",
                "first_latched_close_action_identity",
            }.issubset(action):
                continue
            evaluation_identity = _identity(
                action.get(action_evaluation_field),
                action_evaluation_field,
            )
            evaluation = by_kind_identity.get((evaluation_kind, evaluation_identity))
            if evaluation is None:
                continue
            if evaluation_identity in action_evaluations:
                raise PayloadValidationError("duplicate Position actions share one evaluation")
            action_evaluations.add(evaluation_identity)
            evaluation_payload = _mapping(
                evaluation.get("payload"),
                "Position evaluation payload",
            )
            owner_identity = _identity(evaluation_payload.get(owner_field), owner_field)
            actions_by_owner.setdefault(owner_identity, []).append(value)

        for values in actions_by_owner.values():
            action_rows: list[
                tuple[
                    FactBoundary,
                    str,
                    Mapping[str, object],
                    Mapping[str, object],
                    str,
                ]
            ] = []
            for value in values:
                action = _mapping(value.get("payload"), "Position action payload")
                evaluation_identity = _identity(
                    action.get(action_evaluation_field),
                    action_evaluation_field,
                )
                evaluation = by_kind_identity[(evaluation_kind, evaluation_identity)]
                evaluation_payload = _mapping(
                    evaluation.get("payload"),
                    "Position evaluation payload",
                )
                action_boundary = _graph_boundary(
                    value.get("fact_boundary"),
                    "Position action boundary",
                )
                evaluation_boundary = _graph_boundary(
                    evaluation.get("fact_boundary"),
                    "Position evaluation boundary",
                )
                if action_boundary != evaluation_boundary or action.get(
                    "ordered_predicate_truth_vector"
                ) != evaluation_payload.get("ordered_predicate_truth_vector"):
                    raise PayloadValidationError(
                        "Position action boundary/truth vector differs from owning evaluation"
                    )
                action_rows.append(
                    (
                        action_boundary,
                        _identity(value.get("object_identity"), "Position action identity"),
                        action,
                        evaluation_payload,
                        evaluation_identity,
                    )
                )
            causal_seqs = [row[0].causal_seq for row in action_rows]
            if len(causal_seqs) != len(set(causal_seqs)):
                raise PayloadValidationError(
                    "duplicate Position actions share one owner causal boundary"
                )
            action_rows.sort(key=lambda row: row[0].causal_seq)
            latched_reasons: set[str] = set()
            first_close_identity: str | None = None
            for _, action_identity, action, evaluation, _ in action_rows:
                truths = _string_array(
                    evaluation.get("ordered_predicate_truth_vector"),
                    "ordered_predicate_truth_vector",
                )
                latched_reasons.update(
                    reason
                    for reason, truth in zip(POSITION_CLOSE_REASONS, truths, strict=True)
                    if truth == "TRUE"
                )
                ordered_latched = tuple(
                    reason for reason in POSITION_CLOSE_REASONS if reason in latched_reasons
                )
                expected_action = (
                    "CLOSE" if ordered_latched else ("UNKNOWN" if "UNKNOWN" in truths else "HOLD")
                )
                if first_close_identity is None and expected_action == "CLOSE":
                    first_close_identity = action_identity
                if (
                    action.get("serialized_action") != expected_action
                    or action.get("ordered_latched_close_reason_vector") != list(ordered_latched)
                    or action.get("first_latched_close_action_identity") != first_close_identity
                    or (
                        not rejected
                        and (
                            action.get("primary_close_reason")
                            != (ordered_latched[0] if ordered_latched else None)
                            or action.get("secondary_close_reasons") != list(ordered_latched[1:])
                        )
                    )
                ):
                    raise PayloadValidationError("Position action causal latch history mismatch")


def validate_complete_semantic_graph(
    objects: Mapping[str, Mapping[str, object]],
    *,
    runtime_start: FactBoundary,
    enrollment_end: FactBoundary,
    terminal_boundary: FactBoundary,
) -> None:
    """Cross-bind complete terminal objects after individual object validation."""
    by_kind: dict[str, list[Mapping[str, object]]] = {}
    by_kind_identity: dict[tuple[str, str], Mapping[str, object]] = {}
    for value in objects.values():
        kind = _string(value.get("object_kind"), "object_kind")
        identity = _identity(value.get("object_identity"), "object_identity")
        by_kind.setdefault(kind, []).append(value)
        key = (kind, identity)
        if key in by_kind_identity:
            raise PayloadValidationError(f"duplicate complete-graph object: {kind} {identity}")
        by_kind_identity[key] = value

    def local(kind: str, identity: object, relationship: str) -> Mapping[str, object]:
        target_identity = _identity(identity, relationship)
        target = by_kind_identity.get((kind, target_identity))
        if target is None:
            raise PayloadValidationError(
                f"complete semantic graph is missing {relationship}: {target_identity}"
            )
        return target

    def payload(value: Mapping[str, object], label: str) -> Mapping[str, object]:
        return _mapping(value.get("payload"), label)

    families = (
        {
            "observation_kind": "SHADOW_OUTCOME_OBSERVATION",
            "anchor_kind": "SHADOW_ENTRY",
            "anchor_field": "shadow_entry_identity",
            "outcome_kind": "SHADOW_OUTCOME",
            "outcome_observation_field": "shadow_observation_identity",
            "outcome_anchor_field": "shadow_entry_identity",
            "exit_kind": "SHADOW_COUNTERFACTUAL_EXIT",
            "exit_observation_field": "shadow_observation_identity",
            "opportunity_kind": "CLOSE_OPPORTUNITY_EVALUATION",
            "opportunity_anchor_field": "shadow_entry_identity",
            "quote_kind": "CLOSE_QUOTE_EVALUATION",
            "action_kind": "POSITION_ACTION",
            "evaluation_kind": "POSITION_EVALUATION",
            "pair_family": "ADMITTED",
            "policy_arm": "SHADOW_TRADE",
            "alternative_arm": "NO_TRADE",
        },
        {
            "observation_kind": "REJECTED_COUNTERFACTUAL_OBSERVATION",
            "anchor_kind": "REJECTED_COUNTERFACTUAL_ANCHOR",
            "anchor_field": "rejected_anchor_identity",
            "outcome_kind": "REJECTED_COUNTERFACTUAL_OUTCOME",
            "outcome_observation_field": "rejected_observation_identity",
            "outcome_anchor_field": "rejected_anchor_identity",
            "exit_kind": "REJECTED_COUNTERFACTUAL_EXIT",
            "exit_observation_field": "rejected_observation_identity",
            "opportunity_kind": "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
            "opportunity_anchor_field": "rejected_observation_identity",
            "quote_kind": "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
            "action_kind": "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
            "evaluation_kind": "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
            "pair_family": "REJECTED",
            "policy_arm": "NO_TRADE",
            "alternative_arm": "REJECTED_COUNTERFACTUAL_TRADE",
        },
    )
    entry_audit_fields = (
        "gross_entry_credit_usdc",
        "entry_fee_reserve_usdc",
        "net_entry_credit_usdc",
        "contractual_payoff_max_loss_ex_fees_usdc",
        "entry_fee_reserved_payoff_loss_usdc",
        "underwriting_reserved_loss_usdc",
    )
    quote_fields = (
        "canonical_combo_identity",
        "canonical_leg_identities",
        "close_direction",
        "full_quantity_btc",
        "consumed_levels",
        "gross_close_cashflow_usdc",
    )
    opportunity_fields = (
        "commission_source_refs",
        "index_source_ref",
        "gross_close_cashflow_usdc",
        "close_fee_reserve_usdc",
        "net_close_cashflow_usdc",
        "net_close_debit_usdc",
        "projected_shadow_net_pnl_usdc",
        "projected_net_loss_usdc",
    )

    for family in families:
        observation_kind = family["observation_kind"]
        outcomes_by_observation: dict[str, list[Mapping[str, object]]] = {}
        for value in by_kind.get(family["outcome_kind"], ()):
            value_payload = payload(value, "Outcome payload")
            observation_identity = _identity(
                value_payload[family["outcome_observation_field"]],
                "Outcome observation identity",
            )
            outcomes_by_observation.setdefault(observation_identity, []).append(value)
        opportunities_by_owner: dict[str, list[Mapping[str, object]]] = {}
        for value in by_kind.get(family["opportunity_kind"], ()):
            value_payload = payload(value, "close opportunity payload")
            owner_identity = _identity(
                value_payload[family["opportunity_anchor_field"]],
                "close opportunity owner identity",
            )
            opportunities_by_owner.setdefault(owner_identity, []).append(value)
        _validate_family_reverse_closure(
            family=family,
            by_kind=by_kind,
            by_kind_identity=by_kind_identity,
            outcomes_by_observation=outcomes_by_observation,
        )
        for observation in by_kind.get(observation_kind, ()):
            observation_identity = _identity(
                observation.get("object_identity"),
                "observation identity",
            )
            observation_payload = payload(observation, f"{observation_kind} payload")
            anchor_identity = _identity(
                observation_payload[family["anchor_field"]],
                "observation anchor identity",
            )
            anchor = local(
                family["anchor_kind"],
                anchor_identity,
                "observation anchor",
            )
            anchor_payload = payload(anchor, "observation anchor payload")
            if observation_payload["start_fact_boundary"] != anchor["fact_boundary"]:
                raise PayloadValidationError("observation start differs from anchor boundary")
            anchor_boundary = _graph_boundary(anchor["fact_boundary"], "anchor boundary")
            expected_enrollment = anchor_boundary.is_strictly_after(
                runtime_start
            ) and enrollment_end.is_strictly_after(anchor_boundary)
            if observation_payload["cohort_enrolled"] is not expected_enrollment:
                raise PayloadValidationError(
                    "observation enrollment differs from realized causal boundaries"
                )

            outcomes = outcomes_by_observation.get(observation_identity, ())
            if len(outcomes) != 1:
                raise PayloadValidationError(
                    "complete semantic graph requires exactly one Outcome per observation"
                )
            outcome = outcomes[0]
            outcome_identity = _identity(outcome["object_identity"], "Outcome identity")
            outcome_payload = payload(outcome, "Outcome payload")
            if outcome_payload[family["outcome_anchor_field"]] != anchor_identity:
                raise PayloadValidationError("Outcome anchor differs from observation anchor")
            if outcome_payload["terminal_fact_boundary"] != outcome["fact_boundary"]:
                raise PayloadValidationError("Outcome terminal boundary differs from envelope")
            outcome_boundary = _graph_boundary(outcome["fact_boundary"], "Outcome boundary")
            if terminal_boundary.causal_seq < outcome_boundary.causal_seq:
                raise PayloadValidationError("Outcome occurs after complete-directory terminal")
            _require_equal_fields(
                outcome_payload,
                anchor_payload,
                entry_audit_fields,
                "Outcome entry audit differs from anchor",
            )
            if outcome_payload["terminal_state"] == "MATURE_UNKNOWN":
                witnesses = outcome_payload["natural_terminal_lifecycle_witnesses"]
                if not isinstance(witnesses, list):
                    raise PayloadValidationError(
                        "MATURE_UNKNOWN lifecycle witnesses must be an array"
                    )
                canonical_legs = anchor_payload["canonical_leg_identities"]
                if not isinstance(canonical_legs, list) or len(canonical_legs) != 2:
                    raise PayloadValidationError("anchor canonical legs are incomplete")
                for index, role in enumerate(("SHORT", "LONG")):
                    witness = _mapping(witnesses[index], f"{role} lifecycle witness")
                    if (
                        witness["canonical_leg_role"] != role
                        or witness["instrument_identity"] != canonical_legs[index]
                    ):
                        raise PayloadValidationError(
                            "MATURE_UNKNOWN lifecycle witness differs from anchor leg"
                        )
                    witness_boundary = _graph_boundary(
                        witness["witness_fact_boundary"],
                        f"{role} lifecycle witness boundary",
                    )
                    if (
                        witness_boundary.code_identity != anchor_boundary.code_identity
                        or witness_boundary.runtime_identity != anchor_boundary.runtime_identity
                        or witness_boundary.causal_seq <= anchor_boundary.causal_seq
                    ):
                        raise PayloadValidationError(
                            "MATURE_UNKNOWN lifecycle witness must be strictly after its entry anchor"
                        )
                    if (
                        witness_boundary.code_identity != outcome_boundary.code_identity
                        or witness_boundary.runtime_identity != outcome_boundary.runtime_identity
                        or witness_boundary.causal_seq > outcome_boundary.causal_seq
                    ):
                        raise PayloadValidationError(
                            "MATURE_UNKNOWN lifecycle witness cannot follow its Outcome"
                        )

            pair = local(
                "ALIGNED_POLICY_NO_TRADE_PAIR",
                observation_payload["aligned_pair_identity"],
                "aligned pair",
            )
            pair_payload = payload(pair, "aligned pair payload")
            expected_pair = {
                "pair_family": family["pair_family"],
                "cohort_enrolled": expected_enrollment,
                "pair_anchor_identity": anchor_identity,
                "policy_arm": family["policy_arm"],
                "alternative_arm": family["alternative_arm"],
                "trade_observation_identity": observation_identity,
                "trade_outcome_identity": outcome_identity,
                "terminal_state": outcome_payload["terminal_state"],
                "terminal_fact_boundary": outcome_payload["terminal_fact_boundary"],
                "censor_mask": outcome_payload["censor_mask"],
            }
            for field, expected in expected_pair.items():
                if pair_payload[field] != expected:
                    raise PayloadValidationError(
                        f"aligned pair differs from Outcome/observation at {field}"
                    )

            opportunity_owner = (
                observation_identity if family["pair_family"] == "REJECTED" else anchor_identity
            )
            eligible = [
                value
                for value in opportunities_by_owner.get(opportunity_owner, ())
                if payload(value, "close opportunity payload")["eligibility"] == "ELIGIBLE"
                and _graph_boundary(
                    value["fact_boundary"],
                    "eligible opportunity boundary",
                ).causal_seq
                <= outcome_boundary.causal_seq
            ]
            selected_exit_identity = outcome_payload["selected_exit_identity"]
            if outcome_payload["terminal_state"] == "MATURE_KNOWN":
                if selected_exit_identity is None or not eligible:
                    raise PayloadValidationError(
                        "MATURE_KNOWN requires a selected causal-first eligible exit"
                    )
                earliest_seq = min(
                    _graph_boundary(value["fact_boundary"], "eligible boundary").causal_seq
                    for value in eligible
                )
                first_eligible = [
                    value
                    for value in eligible
                    if _graph_boundary(
                        value["fact_boundary"],
                        "eligible boundary",
                    ).causal_seq
                    == earliest_seq
                ]
                if len(first_eligible) != 1:
                    raise PayloadValidationError(
                        "multiple eligible opportunities share the causal-first boundary"
                    )
                selected_exit = local(
                    family["exit_kind"],
                    selected_exit_identity,
                    "selected exit",
                )
                selected_exit_payload = payload(selected_exit, "selected exit payload")
                if selected_exit_payload[family["exit_observation_field"]] != observation_identity:
                    raise PayloadValidationError("selected exit belongs to another observation")
                selected_opportunity_identity = _identity(
                    selected_exit_payload["close_opportunity_evaluation_identity"],
                    "selected opportunity identity",
                )
                if selected_opportunity_identity != first_eligible[0]["object_identity"]:
                    raise PayloadValidationError(
                        "selected exit is not the causal-first eligible opportunity"
                    )
                if selected_exit["fact_boundary"] != outcome["fact_boundary"]:
                    raise PayloadValidationError(
                        "selected exit boundary differs from MATURE_KNOWN Outcome"
                    )
                if first_eligible[0]["fact_boundary"] != selected_exit["fact_boundary"]:
                    raise PayloadValidationError(
                        "eligible opportunity, selected exit, and Outcome require "
                        "one atomic FactBoundary"
                    )
                _validate_selected_exit_semantics(
                    selected_exit_payload,
                    selected_opportunity_identity=selected_opportunity_identity,
                    family=family,
                    by_kind_identity=by_kind_identity,
                    quote_fields=quote_fields,
                    opportunity_fields=opportunity_fields,
                )
                if (
                    pair_payload["trade_net_pnl_after_public_standard_fee_reserve_usdc"]
                    != outcome_payload["net_pnl_after_public_standard_fee_reserve_usdc"]
                ):
                    raise PayloadValidationError("aligned pair PnL differs from Outcome")
                expected_advantage = (
                    outcome_payload["net_pnl_after_public_standard_fee_reserve_usdc"]
                    if family["pair_family"] == "ADMITTED"
                    else canonical_decimal(
                        -_decimal(
                            outcome_payload["net_pnl_after_public_standard_fee_reserve_usdc"],
                            "Outcome net PnL",
                        )
                    )
                )
                if pair_payload["policy_advantage_usdc"] != expected_advantage:
                    raise PayloadValidationError("aligned pair advantage differs from Outcome")
                exit_payload = selected_exit_payload
                known_outcome_exit_pairs = (
                    ("gross_close_cashflow_usdc", "gross_close_cashflow_usdc"),
                    ("close_fee_reserve_usdc", "close_fee_reserve_usdc"),
                    ("net_close_cashflow_usdc", "net_close_cashflow_usdc"),
                    (
                        "net_pnl_after_public_standard_fee_reserve_usdc",
                        "projected_shadow_net_pnl_usdc",
                    ),
                    ("net_loss_usdc", "projected_net_loss_usdc"),
                )
                for outcome_field, exit_field in known_outcome_exit_pairs:
                    if outcome_payload[outcome_field] != exit_payload[exit_field]:
                        raise PayloadValidationError(
                            f"Outcome economics differ from selected exit at {outcome_field}"
                        )
            else:
                if selected_exit_identity is not None:
                    raise PayloadValidationError(
                        "unknown/censored Outcome cannot reference a selected exit"
                    )
                if eligible:
                    raise PayloadValidationError(
                        "eligible opportunity cannot be rewritten as unknown or censored"
                    )
                if (
                    pair_payload["trade_net_pnl_after_public_standard_fee_reserve_usdc"] is not None
                    or pair_payload["policy_advantage_usdc"] is not None
                ):
                    raise PayloadValidationError(
                        "unknown/censored aligned pair cannot contain economics"
                    )

            _validate_outcome_attempt_links(
                outcome_payload,
                family=family,
                by_kind_identity=by_kind_identity,
            )


def _validate_family_reverse_closure(
    *,
    family: Mapping[str, str],
    by_kind: Mapping[str, Sequence[Mapping[str, object]]],
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
    outcomes_by_observation: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    observation_kind = family["observation_kind"]
    rejected = family["pair_family"] == "REJECTED"
    observations: dict[str, Mapping[str, object]] = {}
    owner_by_observation: dict[str, str] = {}
    anchor_by_owner: dict[str, Mapping[str, object]] = {}
    for value in by_kind.get(observation_kind, ()):
        observation_identity = _identity(value["object_identity"], "observation identity")
        observation = _mapping(value["payload"], "observation payload")
        anchor_identity = _identity(
            observation[family["anchor_field"]],
            "observation anchor identity",
        )
        anchor_value = by_kind_identity.get((family["anchor_kind"], anchor_identity))
        if anchor_value is None:
            raise PayloadValidationError("observation is missing its owning anchor")
        owner_identity = observation_identity if rejected else anchor_identity
        if owner_identity in anchor_by_owner:
            raise PayloadValidationError("multiple observations share one family owner")
        observations[observation_identity] = value
        owner_by_observation[observation_identity] = owner_identity
        anchor_by_owner[owner_identity] = _mapping(
            anchor_value["payload"],
            "observation anchor payload",
        )
    if set(outcomes_by_observation) != set(observations):
        raise PayloadValidationError("Outcome graph has an orphan or missing observation")

    evaluation_owner_field = family["opportunity_anchor_field"]
    evaluations: dict[str, Mapping[str, object]] = {}
    evaluation_payloads: dict[str, Mapping[str, object]] = {}
    evaluation_owners: dict[str, str] = {}
    evaluations_by_owner_boundary: dict[tuple[str, FactBoundary], list[str]] = {}
    for value in by_kind.get(family["evaluation_kind"], ()):
        identity = _identity(value["object_identity"], "Position evaluation identity")
        value_payload = _mapping(value["payload"], "Position evaluation payload")
        owner_identity = _identity(
            value_payload[evaluation_owner_field],
            "Position evaluation owner",
        )
        if owner_identity not in anchor_by_owner:
            raise PayloadValidationError("orphan Position evaluation owner")
        evaluations[identity] = value
        evaluation_payloads[identity] = value_payload
        evaluation_owners[identity] = owner_identity
        boundary = _graph_boundary(value["fact_boundary"], "Position evaluation boundary")
        boundary_evaluations = evaluations_by_owner_boundary.setdefault(
            (owner_identity, boundary),
            [],
        )
        boundary_evaluations.append(identity)
        if len(boundary_evaluations) != 1:
            raise PayloadValidationError("duplicate Position evaluations share one owner boundary")

    action_evaluation_field = (
        "rejected_position_evaluation_identity" if rejected else "position_evaluation_identity"
    )
    actions: dict[str, Mapping[str, object]] = {}
    action_payloads: dict[str, Mapping[str, object]] = {}
    action_owners: dict[str, str] = {}
    actions_by_evaluation: dict[str, list[str]] = {}
    for value in by_kind.get(family["action_kind"], ()):
        identity = _identity(value["object_identity"], "Position action identity")
        value_payload = _mapping(value["payload"], "Position action payload")
        evaluation_identity = _identity(
            value_payload[action_evaluation_field],
            "owning Position evaluation identity",
        )
        evaluation_value = evaluations.get(evaluation_identity)
        evaluation_payload = evaluation_payloads.get(evaluation_identity)
        if evaluation_value is None or evaluation_payload is None:
            raise PayloadValidationError("orphan Position action evaluation")
        if (
            value["fact_boundary"] != evaluation_value["fact_boundary"]
            or value_payload["ordered_predicate_truth_vector"]
            != evaluation_payload["ordered_predicate_truth_vector"]
        ):
            raise PayloadValidationError(
                "Position action boundary/truth vector differs from owning evaluation"
            )
        actions[identity] = value
        action_payloads[identity] = value_payload
        action_owners[identity] = evaluation_owners[evaluation_identity]
        actions_by_evaluation.setdefault(evaluation_identity, []).append(identity)
    for evaluation_identity in evaluations:
        if len(actions_by_evaluation.get(evaluation_identity, ())) != 1:
            raise PayloadValidationError(
                "each Position evaluation requires exactly one owning action"
            )

    quotes: dict[str, Mapping[str, object]] = {}
    quote_payloads: dict[str, Mapping[str, object]] = {}
    quote_owners: dict[str, str] = {}
    quotes_by_owner_boundary: dict[tuple[str, FactBoundary], list[str]] = {}
    for value in by_kind.get(family["quote_kind"], ()):
        identity = _identity(value["object_identity"], "close quote identity")
        value_payload = _mapping(value["payload"], "close quote payload")
        owner_identity = _identity(value_payload[evaluation_owner_field], "close quote owner")
        anchor_payload = anchor_by_owner.get(owner_identity)
        if anchor_payload is None:
            raise PayloadValidationError("orphan close quote owner")
        _require_equal_fields(
            value_payload,
            anchor_payload,
            (
                "canonical_combo_identity",
                "canonical_leg_identities",
                "full_quantity_btc",
            ),
            "close quote differs from owning anchor",
        )
        expected_close_direction = "BUY" if anchor_payload["entry_direction"] == "SELL" else "SELL"
        if value_payload["close_direction"] != expected_close_direction:
            raise PayloadValidationError("close quote direction differs from owning anchor")
        first_action = value_payload["first_latched_close_action_identity"]
        if first_action is not None:
            first_action_identity = _identity(first_action, "first CLOSE action identity")
            first_action_payload = action_payloads.get(first_action_identity)
            if (
                first_action_payload is None
                or action_owners[first_action_identity] != owner_identity
                or first_action_payload["serialized_action"] != "CLOSE"
                or first_action_payload["first_latched_close_action_identity"]
                != first_action_identity
            ):
                raise PayloadValidationError("close quote has an orphan first CLOSE action")
        quotes[identity] = value
        quote_payloads[identity] = value_payload
        quote_owners[identity] = owner_identity
        boundary = _graph_boundary(value["fact_boundary"], "close quote boundary")
        boundary_quotes = quotes_by_owner_boundary.setdefault((owner_identity, boundary), [])
        boundary_quotes.append(identity)
        if len(boundary_quotes) != 1:
            raise PayloadValidationError("duplicate close quotes share one owner boundary")
        if value_payload["close_conditioning"] == "PRE_CLOSE":
            if len(evaluations_by_owner_boundary.get((owner_identity, boundary), ())) != 1:
                raise PayloadValidationError(
                    "pre-CLOSE quote requires exactly one owning Position evaluation"
                )

    opportunities: dict[str, Mapping[str, object]] = {}
    opportunity_payloads: dict[str, Mapping[str, object]] = {}
    opportunity_owners: dict[str, str] = {}
    opportunities_by_quote: dict[str, list[str]] = {}
    opportunities_by_owner_boundary: dict[tuple[str, FactBoundary], list[str]] = {}
    for value in by_kind.get(family["opportunity_kind"], ()):
        identity = _identity(value["object_identity"], "close opportunity identity")
        value_payload = _mapping(value["payload"], "close opportunity payload")
        owner_identity = _identity(
            value_payload[evaluation_owner_field],
            "close opportunity owner",
        )
        if owner_identity not in anchor_by_owner:
            raise PayloadValidationError("orphan close opportunity owner")
        action_identity = _identity(
            value_payload["first_latched_close_action_identity"],
            "close opportunity first CLOSE action",
        )
        if (
            action_identity not in actions
            or action_owners[action_identity] != owner_identity
            or action_payloads[action_identity]["serialized_action"] != "CLOSE"
        ):
            raise PayloadValidationError("close opportunity has an orphan first CLOSE action")
        opportunity_boundary = _graph_boundary(
            value["fact_boundary"],
            "close opportunity boundary",
        )
        action_boundary = _graph_boundary(
            actions[action_identity]["fact_boundary"],
            "first CLOSE action boundary",
        )
        if not opportunity_boundary.is_strictly_after(action_boundary):
            raise PayloadValidationError("close opportunity must be strictly after first CLOSE")
        quote_identity_value = value_payload["close_quote_evaluation_identity"]
        if quote_identity_value is not None:
            quote_identity = _identity(quote_identity_value, "close opportunity quote")
            quote_payload = quote_payloads.get(quote_identity)
            quote_boundary = (
                _graph_boundary(
                    quotes[quote_identity]["fact_boundary"],
                    "close opportunity quote boundary",
                )
                if quote_payload is not None
                else None
            )
            if (
                quote_payload is None
                or quote_owners[quote_identity] != owner_identity
                or quote_payload["first_latched_close_action_identity"] != action_identity
                or quote_payload["close_conditioning"] != action_identity
                or quote_boundary is None
                or not quote_boundary.is_strictly_after(action_boundary)
                or quote_boundary.causal_seq > opportunity_boundary.causal_seq
            ):
                raise PayloadValidationError(
                    "close opportunity differs from its owning quote/action"
                )
            opportunities_by_quote.setdefault(quote_identity, []).append(identity)
        elif value_payload["attempt_terminal_identity"] is None:
            raise PayloadValidationError("close opportunity requires one quote or attempt terminal")
        opportunities[identity] = value
        opportunity_payloads[identity] = value_payload
        opportunity_owners[identity] = owner_identity
        boundary_opportunities = opportunities_by_owner_boundary.setdefault(
            (owner_identity, opportunity_boundary),
            [],
        )
        boundary_opportunities.append(identity)
        if len(boundary_opportunities) != 1:
            raise PayloadValidationError("duplicate close opportunities share one owner boundary")
    for quote_identity, quote_payload in quote_payloads.items():
        conditioning = quote_payload["close_conditioning"]
        if conditioning != "PRE_CLOSE" and not opportunities_by_quote.get(quote_identity):
            raise PayloadValidationError("each post-CLOSE quote requires an owning opportunity")

    exits_by_opportunity: dict[str, list[str]] = {}
    exits_by_observation: dict[str, list[str]] = {}
    for value in by_kind.get(family["exit_kind"], ()):
        identity = _identity(value["object_identity"], "selected exit identity")
        value_payload = _mapping(value["payload"], "selected exit payload")
        observation_identity = _identity(
            value_payload[family["exit_observation_field"]],
            "selected exit observation",
        )
        selected_owner = owner_by_observation.get(observation_identity)
        if selected_owner is None:
            raise PayloadValidationError("orphan selected exit observation")
        opportunity_identity = _identity(
            value_payload["close_opportunity_evaluation_identity"],
            "selected exit opportunity",
        )
        opportunity = opportunities.get(opportunity_identity)
        if (
            opportunity is None
            or opportunity_owners[opportunity_identity] != selected_owner
            or opportunity_payloads[opportunity_identity]["eligibility"] != "ELIGIBLE"
            or opportunity["fact_boundary"] != value["fact_boundary"]
        ):
            raise PayloadValidationError(
                "selected exit differs from its atomic eligible opportunity"
            )
        exits_by_opportunity.setdefault(opportunity_identity, []).append(identity)
        exits_by_observation.setdefault(observation_identity, []).append(identity)
    for opportunity_identity, value_payload in opportunity_payloads.items():
        expected = 1 if value_payload["eligibility"] == "ELIGIBLE" else 0
        if len(exits_by_opportunity.get(opportunity_identity, ())) != expected:
            raise PayloadValidationError("close opportunity and selected exit are not one-to-one")
    for observation_identity, exit_identities in exits_by_observation.items():
        outcomes = outcomes_by_observation.get(observation_identity, ())
        if len(outcomes) != 1:
            raise PayloadValidationError("selected exit lacks one owning Outcome")
        outcome = _mapping(outcomes[0]["payload"], "selected exit Outcome payload")
        if len(exit_identities) != 1 or outcome["selected_exit_identity"] != exit_identities[0]:
            raise PayloadValidationError("selected exit and Outcome are not one-to-one")

    if not rejected:
        shadow_opportunities = {
            _identity(value["object_identity"], "Shadow close opportunity identity"): value
            for value in by_kind.get("SHADOW_CLOSE_OPPORTUNITY", ())
        }
        eligible = {
            identity
            for identity, value_payload in opportunity_payloads.items()
            if value_payload["eligibility"] == "ELIGIBLE"
        }
        if set(shadow_opportunities) != eligible:
            raise PayloadValidationError(
                "eligible evaluation and Shadow close opportunity are not one-to-one"
            )


def _require_equal_fields(
    left: Mapping[str, object],
    right: Mapping[str, object],
    fields: Sequence[str],
    message: str,
) -> None:
    for field in fields:
        if left[field] != right[field]:
            raise PayloadValidationError(f"{message}: {field}")


def _semantic_local_payload(
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
    *,
    kind: str,
    identity: object,
    relationship: str,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    target_identity = _identity(identity, relationship)
    value = by_kind_identity.get((kind, target_identity))
    if value is None:
        raise PayloadValidationError(
            f"complete semantic graph is missing {relationship}: {target_identity}"
        )
    return value, _mapping(value.get("payload"), f"{relationship} payload")


def _validate_selected_exit_semantics(
    selected_exit: Mapping[str, object],
    *,
    selected_opportunity_identity: str,
    family: Mapping[str, str],
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
    quote_fields: Sequence[str],
    opportunity_fields: Sequence[str],
) -> None:
    opportunity_value, opportunity = _semantic_local_payload(
        by_kind_identity,
        kind=family["opportunity_kind"],
        identity=selected_opportunity_identity,
        relationship="selected close opportunity evaluation",
    )
    if opportunity["eligibility"] != "ELIGIBLE":
        raise PayloadValidationError("selected close opportunity is not ELIGIBLE")
    quote_value, quote = _semantic_local_payload(
        by_kind_identity,
        kind=family["quote_kind"],
        identity=opportunity["close_quote_evaluation_identity"],
        relationship="selected close quote evaluation",
    )
    if (
        quote["close_quote_state"] != "ATOMIC_COMBO_CLOSE_QUOTE"
        or quote["first_latched_close_action_identity"]
        != selected_exit["first_latched_close_action_identity"]
        or opportunity["first_latched_close_action_identity"]
        != selected_exit["first_latched_close_action_identity"]
    ):
        raise PayloadValidationError("selected exit action/quote relationship mismatch")
    if (
        selected_exit["close_opportunity_evaluation_fact_boundary"]
        != opportunity_value["fact_boundary"]
    ):
        raise PayloadValidationError("selected exit opportunity boundary mismatch")
    _require_equal_fields(
        selected_exit,
        quote,
        quote_fields,
        "selected exit differs from owning quote",
    )
    _require_equal_fields(
        selected_exit,
        opportunity,
        opportunity_fields,
        "selected exit differs from owning opportunity",
    )

    if family["pair_family"] == "ADMITTED":
        shadow_value, shadow = _semantic_local_payload(
            by_kind_identity,
            kind="SHADOW_CLOSE_OPPORTUNITY",
            identity=selected_exit["shadow_close_opportunity_identity"],
            relationship="Shadow close opportunity",
        )
        if (
            shadow["close_opportunity_evaluation_identity"] != selected_opportunity_identity
            or shadow_value["fact_boundary"] != opportunity_value["fact_boundary"]
        ):
            raise PayloadValidationError("Shadow close opportunity relationship mismatch")
        _require_equal_fields(
            shadow,
            quote,
            quote_fields,
            "Shadow close opportunity differs from quote",
        )
        _require_equal_fields(
            shadow,
            opportunity,
            opportunity_fields,
            "Shadow close opportunity differs from evaluation",
        )
        quote_provenance = quote_value.get("source_provenance")
        if not isinstance(quote_provenance, list):
            raise PayloadValidationError("owning quote provenance must be an array")
        quote_roots = [
            item
            for item in quote_provenance
            if _mapping(item, "quote provenance root")["source_role"] == "COMBO_QUOTE"
        ]
        if len(quote_roots) != 1:
            raise PayloadValidationError("owning quote requires exactly one combo source")
        root = _mapping(quote_roots[0], "combo quote provenance")
        expected_ref = {
            "source_identity": root["source_identity"],
            "receipt_fact_boundary": root["receipt_fact_boundary"],
        }
        if selected_exit["combo_quote_source_ref"] != expected_ref:
            raise PayloadValidationError("selected exit differs from owning quote source")
    else:
        if (
            selected_exit["close_quote_evaluation_identity"] != quote_value["object_identity"]
            or selected_exit["close_quote_evaluation_fact_boundary"] != quote_value["fact_boundary"]
            or selected_exit["consumed_rule_scoped_quote_fingerprint"]
            != quote["consumed_rule_scoped_quote_fingerprint"]
        ):
            raise PayloadValidationError("rejected exit differs from owning quote")


def _validate_outcome_attempt_links(
    outcome: Mapping[str, object],
    *,
    family: Mapping[str, str],
    by_kind_identity: Mapping[tuple[str, str], Mapping[str, object]],
) -> None:
    first_action_identity = outcome["first_latched_close_action_identity"]
    if first_action_identity is None:
        return
    action_value, action = _semantic_local_payload(
        by_kind_identity,
        kind=family["action_kind"],
        identity=first_action_identity,
        relationship="first CLOSE action",
    )
    if (
        action_value["fact_boundary"] != outcome["first_latched_close_action_fact_boundary"]
        or action["first_latched_close_action_identity"] != first_action_identity
    ):
        raise PayloadValidationError("Outcome first CLOSE action cross-bind mismatch")
    outcome_boundary = _graph_boundary(outcome["terminal_fact_boundary"], "Outcome boundary")
    first_boundary = _graph_boundary(
        outcome["first_latched_close_action_fact_boundary"],
        "first CLOSE boundary",
    )
    attempt_boundary = _graph_boundary(
        outcome["post_close_attempt_terminal_fact_boundary"],
        "attempt terminal boundary",
    )
    if family["pair_family"] == "REJECTED":
        if outcome["terminal_state"] == "MATURE_UNKNOWN" and not (
            outcome_boundary.is_strictly_after(first_boundary)
            and attempt_boundary.causal_seq <= outcome_boundary.causal_seq
            and outcome["post_close_attempt_terminal_owner"] == "ORDINARY"
        ):
            raise PayloadValidationError("MATURE_UNKNOWN causal attempt relationship mismatch")
        return
    scheduled_kind = "POST_CLOSE_ATTEMPT_SCHEDULED"
    terminal_kind = "POST_CLOSE_ATTEMPT_TERMINAL"
    scheduled_value, scheduled = _semantic_local_payload(
        by_kind_identity,
        kind=scheduled_kind,
        identity=outcome["scheduled_post_close_attempt_identity"],
        relationship="scheduled post-CLOSE attempt",
    )
    if (
        scheduled_value["fact_boundary"] != outcome["scheduled_post_close_attempt_fact_boundary"]
        or scheduled["first_latched_close_action_identity"] != first_action_identity
    ):
        raise PayloadValidationError("Outcome scheduled attempt cross-bind mismatch")
    terminal_value, terminal = _semantic_local_payload(
        by_kind_identity,
        kind=terminal_kind,
        identity=outcome["post_close_attempt_terminal_identity"],
        relationship="post-CLOSE attempt terminal",
    )
    if (
        terminal_value["fact_boundary"] != outcome["post_close_attempt_terminal_fact_boundary"]
        or terminal["terminal_status"] != outcome["post_close_attempt_terminal_status"]
        or terminal["terminal_owner"] != outcome["post_close_attempt_terminal_owner"]
    ):
        raise PayloadValidationError("Outcome attempt terminal cross-bind mismatch")
    if outcome["terminal_state"] == "MATURE_UNKNOWN" and not (
        outcome_boundary.is_strictly_after(first_boundary)
        and attempt_boundary.causal_seq <= outcome_boundary.causal_seq
        and outcome["post_close_attempt_terminal_owner"] == "ORDINARY"
    ):
        raise PayloadValidationError("MATURE_UNKNOWN causal attempt relationship mismatch")


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


def _validate_position_source_graph(
    object_kind: str,
    payload: Mapping[str, object],
) -> None:
    if object_kind not in {
        "POSITION_EVALUATION",
        "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
    }:
        return
    for field in (
        "entry_index_usdc_per_btc",
        "prior_evaluation_index_usdc_per_btc",
        "next_evaluation_index_usdc_per_btc",
    ):
        if _decimal(payload.get(field), field) <= 0:
            raise PayloadValidationError(f"{field} must be positive")
    entry_iv = _decimal(
        payload.get("entry_short_leg_mark_iv_fraction"),
        "entry_short_leg_mark_iv_fraction",
    )
    if entry_iv < 0:
        raise PayloadValidationError("entry_short_leg_mark_iv_fraction must be nonnegative")
    for field in (
        "entry_index_source_identity",
        "entry_short_leg_mark_iv_source_identity",
        "prior_evaluation_index_source_identity",
    ):
        _identity(payload.get(field), field)
    for field in (
        "entry_index_fact_boundary",
        "entry_short_leg_mark_iv_fact_boundary",
        "prior_evaluation_index_fact_boundary",
    ):
        if payload.get(field) is None:
            raise PayloadValidationError(f"{field} is required")
    current_availability = payload.get("current_index_availability")
    current_members = (
        payload.get("current_index_usdc_per_btc"),
        payload.get("current_index_source_identity"),
        payload.get("current_index_fact_boundary"),
    )
    prior = _decimal(
        payload.get("prior_evaluation_index_usdc_per_btc"),
        "prior_evaluation_index_usdc_per_btc",
    )
    next_index = _decimal(
        payload.get("next_evaluation_index_usdc_per_btc"),
        "next_evaluation_index_usdc_per_btc",
    )
    if current_availability == "KNOWN":
        if any(member is None for member in current_members):
            raise PayloadValidationError("KNOWN current index requires value, source, and boundary")
        current = _decimal(current_members[0], "current_index_usdc_per_btc")
        if current <= 0:
            raise PayloadValidationError("current_index_usdc_per_btc must be positive")
        _identity(current_members[1], "current_index_source_identity")
        if next_index != current:
            raise PayloadValidationError("KNOWN current index must become the next index anchor")
    elif current_availability == "UNKNOWN":
        if any(member is not None for member in current_members):
            raise PayloadValidationError(
                "UNKNOWN current index requires null value, source, and boundary"
            )
        if next_index != prior:
            raise PayloadValidationError("UNKNOWN current index must retain the prior index anchor")
    else:
        raise PayloadValidationError("current_index_availability is invalid")


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
    if object_kind in {
        "POSITION_ACTION",
        "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
    }:
        latched = _string_array(
            payload["ordered_latched_close_reason_vector"],
            "ordered_latched_close_reason_vector",
        )
        if bool(latched) != (payload.get("first_latched_close_action_identity") is not None) or (
            bool(latched) != (payload.get("serialized_action") == "CLOSE")
        ):
            raise PayloadValidationError("Position action differs from its latched close reasons")
        if object_kind == "POSITION_ACTION" and (
            payload.get("primary_close_reason") != (latched[0] if latched else None)
            or payload.get("secondary_close_reasons") != list(latched[1:])
        ):
            raise PayloadValidationError(
                "Position action primary/secondary differ from latched close reasons"
            )
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
        amount_total = Decimal(0)
        quote_total = Decimal(0)
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
            amount_total += amount
            quote_total += price * amount
            prices.append(price)
        if amount_total != quantity:
            raise PayloadValidationError(f"{levels_field} must consume exact full quantity")
        direction = payload.get("close_direction", payload.get("entry_direction"))
        if direction not in {"BUY", "SELL"}:
            raise PayloadValidationError(f"{levels_field} requires BUY or SELL direction")
        if direction == "BUY" and prices != sorted(prices):
            raise PayloadValidationError("BUY consumed levels must be best-to-worse ascending")
        if direction == "SELL" and prices != sorted(prices, reverse=True):
            raise PayloadValidationError("SELL consumed levels must be best-to-worse descending")
        expected_cashflow = -quote_total if direction == "BUY" else quote_total
        if levels_field == "entry_consumed_levels":
            gross_entry = _decimal(
                payload.get("gross_entry_credit_usdc"), "gross_entry_credit_usdc"
            )
            if gross_entry <= 0 or gross_entry != expected_cashflow:
                raise PayloadValidationError(
                    "gross entry credit differs from signed consumed levels"
                )
        elif payload.get("gross_close_cashflow_usdc") is not None:
            gross_close = _decimal(
                payload["gross_close_cashflow_usdc"],
                "gross_close_cashflow_usdc",
            )
            if gross_close != expected_cashflow:
                raise PayloadValidationError(
                    "gross close cashflow differs from signed consumed levels"
                )
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
