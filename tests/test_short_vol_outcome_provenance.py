from __future__ import annotations

from copy import deepcopy

import pytest
from short_vol_underwriting.constants import OUTCOME_OBJECT_KINDS
from short_vol_underwriting.validation import (
    PayloadValidationError,
    validate_object_graph,
)

CODE_IDENTITY = "a" * 40
RUNTIME_IDENTITY = "sha256:" + "b" * 64


def _identity(seed: int) -> str:
    return f"sha256:{seed:064x}"


def _boundary(sequence: int) -> dict[str, object]:
    return {
        "code_identity": CODE_IDENTITY,
        "runtime_identity": RUNTIME_IDENTITY,
        "session_epoch": 1,
        "ingress_seq": sequence,
        "received_monotonic_ms": sequence * 10,
        "causal_seq": sequence,
    }


def _boundary_copy(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return deepcopy(value)


def _source_ref(identity: str, boundary: dict[str, object]) -> dict[str, object]:
    return {
        "source_identity": identity,
        "receipt_fact_boundary": boundary,
    }


def _commission_ref(
    role: str,
    identity: str,
    boundary: dict[str, object],
) -> dict[str, object]:
    return {
        "canonical_leg_role": role,
        **_source_ref(identity, boundary),
    }


def _provenance(
    *roots: tuple[str, str, dict[str, object]],
) -> list[dict[str, object]]:
    unique: dict[tuple[str, str], dict[str, object]] = {
        (role, identity): {
            "source_role": role,
            "source_identity": identity,
            "receipt_fact_boundary": boundary,
        }
        for role, identity, boundary in roots
    }
    return [unique[key] for key in sorted(unique)]


def _object(
    kind: str,
    identity: str,
    boundary: dict[str, object],
    *,
    payload: dict[str, object] | None = None,
    provenance: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "object_kind": kind,
        "object_identity": identity,
        "fact_boundary": boundary,
        "source_provenance": provenance or [],
        "payload": payload or {},
    }


def _exact_graph() -> dict[str, dict[str, object]]:
    b1, b2, b3, b4 = (_boundary(index) for index in range(1, 5))
    rb1, rb2, rb3, rb4 = (_boundary(index) for index in range(11, 15))

    entry = _identity(1)
    observation = _identity(2)
    action = _identity(3)
    opportunity = _identity(4)
    selected_exit = _identity(5)
    outcome = _identity(6)
    admitted_pair = _identity(7)
    scheduled = _identity(8)
    attempt_terminal = _identity(9)
    combo = _identity(10)
    short_commission = _identity(11)
    long_commission = _identity(12)
    index = _identity(13)

    underwriting_action = _identity(20)
    rejected_anchor = _identity(21)
    rejected_observation = _identity(22)
    rejected_evaluation = _identity(23)
    rejected_action = _identity(24)
    rejected_quote = _identity(25)
    rejected_opportunity = _identity(26)
    rejected_exit = _identity(27)
    rejected_outcome = _identity(28)
    rejected_combo = _identity(29)
    rejected_short_commission = _identity(30)
    rejected_long_commission = _identity(31)
    rejected_entry_index = _identity(32)
    rejected_iv = _identity(33)
    position_fingerprint = _identity(34)
    prior_index = _identity(35)
    current_index = _identity(36)
    rejected_quote_fingerprint = _identity(37)

    graph = {
        entry: _object("SHADOW_ENTRY", entry, b1),
        action: _object("POSITION_ACTION", action, b2),
        opportunity: _object("CLOSE_OPPORTUNITY_EVALUATION", opportunity, b3),
        scheduled: _object("POST_CLOSE_ATTEMPT_SCHEDULED", scheduled, b2),
        attempt_terminal: _object("POST_CLOSE_ATTEMPT_TERMINAL", attempt_terminal, b3),
        underwriting_action: _object(
            "UNDERWRITING_ACTION",
            underwriting_action,
            rb1,
        ),
        observation: _object(
            "SHADOW_OUTCOME_OBSERVATION",
            observation,
            b1,
            payload={"shadow_entry_identity": entry},
            provenance=_provenance(("ANCHOR", entry, b1)),
        ),
        selected_exit: _object(
            "SHADOW_COUNTERFACTUAL_EXIT",
            selected_exit,
            b4,
            payload={
                "shadow_observation_identity": observation,
                "first_latched_close_action_identity": action,
                "close_opportunity_evaluation_identity": opportunity,
                "first_latched_close_action_fact_boundary": b2,
                "close_opportunity_evaluation_fact_boundary": b3,
                "combo_quote_source_ref": _source_ref(combo, b3),
                "commission_source_refs": [
                    _commission_ref("SHORT", short_commission, b2),
                    _commission_ref("LONG", long_commission, b2),
                ],
                "index_source_ref": _source_ref(index, b3),
            },
            provenance=_provenance(
                ("ANCHOR", observation, b1),
                ("POSITION_ACTION", action, b2),
                ("CLOSE_OPPORTUNITY_EVALUATION", opportunity, b3),
                ("COMBO_QUOTE", combo, b3),
                ("COMMISSION", short_commission, b2),
                ("COMMISSION", long_commission, b2),
                ("INDEX", index, b3),
            ),
        ),
        outcome: _object(
            "SHADOW_OUTCOME",
            outcome,
            b4,
            payload={
                "shadow_observation_identity": observation,
                "terminal_state": "MATURE_KNOWN",
                "selected_exit_identity": selected_exit,
                "first_latched_close_action_identity": action,
                "first_latched_close_action_fact_boundary": b2,
                "scheduled_post_close_attempt_identity": scheduled,
                "scheduled_post_close_attempt_fact_boundary": b2,
                "post_close_attempt_terminal_identity": attempt_terminal,
                "post_close_attempt_terminal_fact_boundary": b3,
                "natural_terminal_lifecycle_witnesses": [],
                "terminal_supervisor_source_identity": None,
                "terminal_fact_boundary": b4,
            },
            provenance=_provenance(
                ("ANCHOR", observation, b1),
                ("SELECTED_EXIT", selected_exit, b4),
            ),
        ),
        rejected_anchor: _object(
            "REJECTED_COUNTERFACTUAL_ANCHOR",
            rejected_anchor,
            rb1,
            payload={
                "underwriting_action_identity": underwriting_action,
                "anchor_fact_boundary": rb1,
                "entry_combo_quote_source_ref": _source_ref(rejected_combo, rb1),
                "entry_commission_source_refs": [
                    _commission_ref("SHORT", rejected_short_commission, rb1),
                    _commission_ref("LONG", rejected_long_commission, rb1),
                ],
                "entry_index_source_identity": rejected_entry_index,
                "entry_index_fact_boundary": rb1,
                "entry_short_leg_mark_iv_source_identity": rejected_iv,
                "entry_short_leg_mark_iv_fact_boundary": rb1,
            },
            provenance=_provenance(
                ("ANCHOR", underwriting_action, rb1),
                ("COMBO_QUOTE", rejected_combo, rb1),
                ("COMMISSION", rejected_short_commission, rb1),
                ("COMMISSION", rejected_long_commission, rb1),
                ("INDEX", rejected_entry_index, rb1),
                ("POSITION_FACT", rejected_iv, rb1),
            ),
        ),
        rejected_observation: _object(
            "REJECTED_COUNTERFACTUAL_OBSERVATION",
            rejected_observation,
            rb1,
            payload={"rejected_anchor_identity": rejected_anchor},
            provenance=_provenance(("ANCHOR", rejected_anchor, rb1)),
        ),
        rejected_evaluation: _object(
            "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION",
            rejected_evaluation,
            rb2,
            payload={
                "rejected_observation_identity": rejected_observation,
                "consumed_position_fact_fingerprint": position_fingerprint,
                "evaluation_fact_boundary": rb2,
                "entry_short_leg_mark_iv_source_identity": rejected_iv,
                "entry_short_leg_mark_iv_fact_boundary": rb1,
                "entry_index_source_identity": rejected_entry_index,
                "entry_index_fact_boundary": rb1,
                "prior_evaluation_index_source_identity": prior_index,
                "prior_evaluation_index_fact_boundary": rb1,
                "current_index_availability": "KNOWN",
                "current_index_source_identity": current_index,
                "current_index_fact_boundary": rb2,
            },
            provenance=_provenance(
                ("ANCHOR", rejected_observation, rb1),
                ("POSITION_FACT", position_fingerprint, rb2),
                ("POSITION_FACT", rejected_iv, rb1),
                ("INDEX", rejected_entry_index, rb1),
                ("INDEX", prior_index, rb1),
                ("INDEX", current_index, rb2),
            ),
        ),
        rejected_action: _object(
            "REJECTED_COUNTERFACTUAL_POSITION_ACTION",
            rejected_action,
            rb2,
            payload={"rejected_position_evaluation_identity": rejected_evaluation},
            provenance=_provenance(
                ("POSITION_EVALUATION", rejected_evaluation, rb2),
            ),
        ),
        rejected_quote: _object(
            "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION",
            rejected_quote,
            rb3,
            payload={
                "rejected_observation_identity": rejected_observation,
                "consumed_rule_scoped_quote_fingerprint": rejected_quote_fingerprint,
                "evaluation_fact_boundary": rb3,
            },
            provenance=_provenance(
                ("ANCHOR", rejected_observation, rb1),
                ("COMBO_QUOTE", rejected_quote_fingerprint, rb3),
            ),
        ),
        rejected_opportunity: _object(
            "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION",
            rejected_opportunity,
            rb3,
            payload={
                "first_latched_close_action_identity": rejected_action,
                "close_quote_evaluation_identity": rejected_quote,
                "attempt_terminal_identity": None,
                "attempt_terminal_fact_boundary": None,
                "eligibility_reason": "ELIGIBLE_COMPLETE",
                "commission_source_refs": [
                    _commission_ref("SHORT", rejected_short_commission, rb1),
                    _commission_ref("LONG", rejected_long_commission, rb1),
                ],
                "index_source_ref": _source_ref(current_index, rb2),
            },
            provenance=_provenance(
                ("POSITION_ACTION", rejected_action, rb2),
                ("CLOSE_QUOTE_EVALUATION", rejected_quote, rb3),
                ("COMMISSION", rejected_short_commission, rb1),
                ("COMMISSION", rejected_long_commission, rb1),
                ("INDEX", current_index, rb2),
            ),
        ),
        rejected_exit: _object(
            "REJECTED_COUNTERFACTUAL_EXIT",
            rejected_exit,
            rb4,
            payload={
                "rejected_observation_identity": rejected_observation,
                "first_latched_close_action_identity": rejected_action,
                "close_quote_evaluation_identity": rejected_quote,
                "close_opportunity_evaluation_identity": rejected_opportunity,
                "first_latched_close_action_fact_boundary": rb2,
                "close_quote_evaluation_fact_boundary": rb3,
                "close_opportunity_evaluation_fact_boundary": rb3,
                "consumed_rule_scoped_quote_fingerprint": rejected_quote_fingerprint,
                "commission_source_refs": [
                    _commission_ref("SHORT", rejected_short_commission, rb1),
                    _commission_ref("LONG", rejected_long_commission, rb1),
                ],
                "index_source_ref": _source_ref(current_index, rb2),
            },
            provenance=_provenance(
                ("ANCHOR", rejected_observation, rb1),
                ("POSITION_ACTION", rejected_action, rb2),
                ("CLOSE_QUOTE_EVALUATION", rejected_quote, rb3),
                ("CLOSE_OPPORTUNITY_EVALUATION", rejected_opportunity, rb3),
                ("COMBO_QUOTE", rejected_quote_fingerprint, rb3),
                ("COMMISSION", rejected_short_commission, rb1),
                ("COMMISSION", rejected_long_commission, rb1),
                ("INDEX", current_index, rb2),
            ),
        ),
        rejected_outcome: _object(
            "REJECTED_COUNTERFACTUAL_OUTCOME",
            rejected_outcome,
            rb4,
            payload={
                "rejected_observation_identity": rejected_observation,
                "terminal_state": "MATURE_KNOWN",
                "selected_exit_identity": rejected_exit,
                "first_latched_close_action_identity": rejected_action,
                "first_latched_close_action_fact_boundary": rb2,
                "scheduled_post_close_attempt_identity": _identity(38),
                "scheduled_post_close_attempt_fact_boundary": rb2,
                "post_close_attempt_terminal_identity": _identity(39),
                "post_close_attempt_terminal_fact_boundary": rb3,
                "natural_terminal_lifecycle_witnesses": [],
                "terminal_supervisor_source_identity": None,
                "terminal_fact_boundary": rb4,
            },
            provenance=_provenance(
                ("ANCHOR", rejected_observation, rb1),
                ("SELECTED_EXIT", rejected_exit, rb4),
            ),
        ),
        admitted_pair: _object(
            "ALIGNED_POLICY_NO_TRADE_PAIR",
            admitted_pair,
            b4,
            payload={
                "pair_family": "ADMITTED",
                "trade_observation_identity": observation,
                "trade_outcome_identity": outcome,
                "terminal_fact_boundary": b4,
            },
            provenance=_provenance(
                ("ANCHOR", observation, b1),
                ("TERMINAL_OUTCOME", outcome, b4),
            ),
        ),
    }
    return graph


NON_SUMMARY_OUTCOME_KINDS = OUTCOME_OBJECT_KINDS[:-1]


@pytest.mark.parametrize("object_kind", NON_SUMMARY_OUTCOME_KINDS)
def test_exact_outcome_provenance_accepts_only_the_contract_projection(
    object_kind: str,
) -> None:
    graph = _exact_graph()
    subject = next(value for value in graph.values() if value["object_kind"] == object_kind)

    validate_object_graph(graph)

    missing = deepcopy(graph)
    missing_subject = missing[str(subject["object_identity"])]
    provenance = missing_subject["source_provenance"]
    assert isinstance(provenance, list)
    provenance.pop()
    with pytest.raises(PayloadValidationError, match="exact one-hop provenance"):
        validate_object_graph(missing)

    extra = deepcopy(graph)
    extra_subject = extra[str(subject["object_identity"])]
    extra_provenance = extra_subject["source_provenance"]
    assert isinstance(extra_provenance, list)
    extra_provenance.append(
        {
            "source_role": "SUPERVISOR_CONTROL",
            "source_identity": _identity(999),
            "receipt_fact_boundary": _boundary(999),
        }
    )
    extra_provenance.sort(key=lambda item: (item["source_role"], item["source_identity"]))
    with pytest.raises(PayloadValidationError, match="exact one-hop provenance"):
        validate_object_graph(extra)


@pytest.mark.parametrize("object_kind", NON_SUMMARY_OUTCOME_KINDS)
def test_exact_outcome_provenance_rejects_local_root_with_the_wrong_kind(
    object_kind: str,
) -> None:
    graph = _exact_graph()
    subject = next(value for value in graph.values() if value["object_kind"] == object_kind)
    provenance = subject["source_provenance"]
    assert isinstance(provenance, list)
    local_role = next(
        item
        for item in provenance
        if item["source_role"]
        in {
            "ANCHOR",
            "POSITION_EVALUATION",
            "POSITION_ACTION",
            "CLOSE_QUOTE_EVALUATION",
            "CLOSE_OPPORTUNITY_EVALUATION",
            "SELECTED_EXIT",
            "TERMINAL_OUTCOME",
        }
    )
    target = graph[str(local_role["source_identity"])]
    target["object_kind"] = "UNDERWRITING_AVAILABILITY_EVALUATION"

    with pytest.raises(PayloadValidationError, match=r"kind|local"):
        validate_object_graph(graph)


def test_exact_outcome_provenance_rejects_direct_source_boundary_mismatch() -> None:
    graph = _exact_graph()
    rejected_anchor = next(
        value
        for value in graph.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_ANCHOR"
    )
    payload = rejected_anchor["payload"]
    assert isinstance(payload, dict)
    source_ref = payload["entry_combo_quote_source_ref"]
    assert isinstance(source_ref, dict)
    source_ref["receipt_fact_boundary"] = _boundary(404)

    with pytest.raises(PayloadValidationError, match="exact one-hop provenance"):
        validate_object_graph(graph)


@pytest.mark.parametrize(
    ("reason", "commission_count", "has_index"),
    (
        ("KNOWN_ATOMIC_UNAVAILABLE", 0, False),
        ("QUOTE_OR_ATTEMPT_UNKNOWN", 0, False),
        ("COMMISSION_UNKNOWN", 1, False),
        ("COMMISSION_ABOVE_POLICY", 2, False),
        ("INDEX_UNKNOWN", 2, True),
        ("ELIGIBLE_COMPLETE", 2, True),
    ),
)
def test_rejected_close_opportunity_projects_exact_first_match_sources(
    reason: str,
    commission_count: int,
    has_index: bool,
) -> None:
    graph = _exact_graph()
    opportunity = next(
        value
        for value in graph.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
    )
    payload = opportunity["payload"]
    provenance = opportunity["source_provenance"]
    assert isinstance(payload, dict)
    assert isinstance(provenance, list)
    all_commission_refs = payload["commission_source_refs"]
    assert isinstance(all_commission_refs, list)
    payload["eligibility_reason"] = reason
    payload["commission_source_refs"] = all_commission_refs[:commission_count]
    if not has_index:
        payload["index_source_ref"] = None
    projected = [
        item
        for item in provenance
        if item["source_role"] in {"POSITION_ACTION", "CLOSE_QUOTE_EVALUATION"}
    ]
    for item in all_commission_refs[:commission_count]:
        assert isinstance(item, dict)
        projected.append(
            {
                "source_role": "COMMISSION",
                "source_identity": item["source_identity"],
                "receipt_fact_boundary": item["receipt_fact_boundary"],
            }
        )
    index_ref = payload["index_source_ref"]
    if index_ref is not None:
        assert isinstance(index_ref, dict)
        projected.append(
            {
                "source_role": "INDEX",
                "source_identity": index_ref["source_identity"],
                "receipt_fact_boundary": index_ref["receipt_fact_boundary"],
            }
        )
    projected.sort(key=lambda item: (item["source_role"], item["source_identity"]))
    opportunity["source_provenance"] = projected

    validate_object_graph(graph)


def test_rejected_close_opportunity_rejects_source_after_first_match() -> None:
    graph = _exact_graph()
    opportunity = next(
        value
        for value in graph.values()
        if value["object_kind"] == "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION"
    )
    payload = opportunity["payload"]
    assert isinstance(payload, dict)
    payload["eligibility_reason"] = "KNOWN_ATOMIC_UNAVAILABLE"

    with pytest.raises(PayloadValidationError, match="first-match rule"):
        validate_object_graph(graph)


@pytest.mark.parametrize(
    ("object_kind", "state"),
    (
        ("SHADOW_OUTCOME", "MATURE_KNOWN"),
        ("SHADOW_OUTCOME", "MATURE_UNKNOWN"),
        ("SHADOW_OUTCOME", "CENSORED_AT_STOP"),
        ("SHADOW_OUTCOME", "CENSORED_AT_FAILURE"),
        ("REJECTED_COUNTERFACTUAL_OUTCOME", "MATURE_KNOWN"),
        ("REJECTED_COUNTERFACTUAL_OUTCOME", "MATURE_UNKNOWN"),
        ("REJECTED_COUNTERFACTUAL_OUTCOME", "CENSORED_AT_STOP"),
        ("REJECTED_COUNTERFACTUAL_OUTCOME", "CENSORED_AT_FAILURE"),
    ),
)
def test_outcome_four_state_provenance_projection(
    object_kind: str,
    state: str,
) -> None:
    graph = _exact_graph()
    outcome = next(value for value in graph.values() if value["object_kind"] == object_kind)
    payload = outcome["payload"]
    assert isinstance(payload, dict)
    if state == "MATURE_KNOWN":
        validate_object_graph(graph)
        return

    payload["terminal_state"] = state
    payload["selected_exit_identity"] = None
    anchor_identity = str(
        payload[
            (
                "rejected_observation_identity"
                if object_kind.startswith("REJECTED_")
                else "shadow_observation_identity"
            )
        ]
    )
    anchor = graph[anchor_identity]
    roots: list[tuple[str, str, dict[str, object]]] = [
        (
            "ANCHOR",
            anchor_identity,
            _boundary_copy(anchor["fact_boundary"]),
        )
    ]
    if state == "MATURE_UNKNOWN":
        action_identity = str(payload["first_latched_close_action_identity"])
        scheduled_identity = str(payload["scheduled_post_close_attempt_identity"])
        terminal_identity = str(payload["post_close_attempt_terminal_identity"])
        roots.extend(
            (
                (
                    "POSITION_ACTION",
                    action_identity,
                    _boundary_copy(payload["first_latched_close_action_fact_boundary"]),
                ),
                (
                    "ATTEMPT_CONTROL",
                    scheduled_identity,
                    _boundary_copy(payload["scheduled_post_close_attempt_fact_boundary"]),
                ),
                (
                    "ATTEMPT_CONTROL",
                    terminal_identity,
                    _boundary_copy(payload["post_close_attempt_terminal_fact_boundary"]),
                ),
            )
        )
        witnesses = [
            {
                "source_identity": _identity(501),
                "witness_fact_boundary": _boundary(20),
            },
            {
                "source_identity": _identity(502),
                "witness_fact_boundary": _boundary(21),
            },
        ]
        payload["natural_terminal_lifecycle_witnesses"] = witnesses
        roots.extend(
            (
                "INSTRUMENT_LIFECYCLE",
                str(witness["source_identity"]),
                _boundary_copy(witness["witness_fact_boundary"]),
            )
            for witness in witnesses
        )
        payload["terminal_supervisor_source_identity"] = None
    else:
        for field in (
            "first_latched_close_action_identity",
            "first_latched_close_action_fact_boundary",
            "scheduled_post_close_attempt_identity",
            "scheduled_post_close_attempt_fact_boundary",
            "post_close_attempt_terminal_identity",
            "post_close_attempt_terminal_fact_boundary",
        ):
            payload[field] = None
        payload["natural_terminal_lifecycle_witnesses"] = []
        supervisor = _identity(503 if state == "CENSORED_AT_STOP" else 504)
        payload["terminal_supervisor_source_identity"] = supervisor
        roots.append(
            (
                "SUPERVISOR_CONTROL",
                supervisor,
                _boundary_copy(payload["terminal_fact_boundary"]),
            )
        )
    outcome["source_provenance"] = _provenance(*roots)

    validate_object_graph(graph)
