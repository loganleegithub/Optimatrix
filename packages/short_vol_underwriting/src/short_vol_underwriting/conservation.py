from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation

COHORT_COUNT_KEYS = (
    "shadow_entry_count",
    "shadow_observation_count",
    "shadow_pending_count",
    "shadow_mature_known_count",
    "shadow_mature_unknown_count",
    "shadow_censored_stop_count",
    "shadow_censored_failure_count",
    "shadow_outcome_count",
    "shadow_selected_exit_count",
    "shadow_terminal_pair_count",
    "rejected_anchor_count",
    "rejected_observation_count",
    "rejected_pending_count",
    "rejected_mature_known_count",
    "rejected_mature_unknown_count",
    "rejected_censored_stop_count",
    "rejected_censored_failure_count",
    "rejected_outcome_count",
    "rejected_selected_exit_count",
    "rejected_terminal_pair_count",
    "rejected_position_evaluation_count",
    "rejected_position_action_count",
    "rejected_close_quote_evaluation_count",
    "rejected_close_opportunity_evaluation_count",
    "logical_admitted_pair_count",
    "logical_rejected_pair_count",
    "logical_aligned_pair_count",
    "non_enrolled_admitted_pair_count",
    "non_enrolled_rejected_pair_count",
    "enrolled_admitted_pair_count",
    "enrolled_admitted_pending_count",
    "enrolled_admitted_mature_known_count",
    "enrolled_admitted_mature_unknown_count",
    "enrolled_admitted_censored_stop_count",
    "enrolled_admitted_censored_failure_count",
    "enrolled_rejected_pair_count",
    "enrolled_rejected_pending_count",
    "enrolled_rejected_mature_known_count",
    "enrolled_rejected_mature_unknown_count",
    "enrolled_rejected_censored_stop_count",
    "enrolled_rejected_censored_failure_count",
    "enrolled_aligned_pair_count",
    "enrolled_terminal_pair_count",
    "enrolled_comparable_pair_count",
    "logical_no_trade_arm_count",
    "durable_terminal_pair_count",
    "durable_no_trade_arm_count",
    "enrolled_admitted_mature_known_win_count",
    "enrolled_admitted_mature_known_loss_count",
    "enrolled_admitted_mature_known_zero_count",
    "enrolled_rejected_mature_known_win_count",
    "enrolled_rejected_mature_known_loss_count",
    "enrolled_rejected_mature_known_zero_count",
)

COHORT_RATE_KEYS = (
    "admitted_terminal_availability_rate",
    "rejected_terminal_availability_rate",
    "admitted_maturity_known_share",
    "rejected_maturity_known_share",
    "admitted_win_rate",
    "admitted_loss_rate",
    "rejected_win_rate",
    "rejected_loss_rate",
    "aligned_economic_comparison_availability_rate",
)

UNDERWRITING_COUNT_KEYS = (
    "underwriting_availability_not_evaluated_count",
    "underwriting_availability_unknown_count",
    "underwriting_availability_evaluable_count",
    "underwriting_action_candidate_count",
    "underwriting_action_watch_count",
    "underwriting_action_abstain_count",
    "candidate_count",
    "admission_entry_emitted_count",
    "admission_known_complete_no_entry_count",
    "admission_known_invalidated_before_refresh_count",
    "admission_unknown_consumed_count",
    "shadow_entry_count",
    "position_hold_count",
    "position_close_count",
    "position_unknown_count",
    "close_quote_atomic_count",
    "close_quote_legged_reference_count",
    "close_quote_unexecutable_count",
    "close_quote_unknown_count",
    "close_opportunity_eligible_count",
    "close_opportunity_ineligible_count",
    "close_opportunity_unknown_count",
    "shadow_close_opportunity_count",
)

UNDERWRITING_RATE_KEYS = (
    "underwriting_known_availability_rate",
    "underwriting_evaluable_rate",
    "underwriting_candidate_action_rate",
    "underwriting_watch_action_rate",
    "underwriting_abstain_action_rate",
    "candidate_activation_rate",
    "admission_evaluable_rate",
    "shadow_entry_rate",
    "position_known_action_rate",
    "close_quote_known_state_rate",
    "close_opportunity_rate_while_closing",
)


def cohort_conservation_status(
    counts: Mapping[str, int],
    *,
    evidence_status: str,
) -> str:
    normalized = _validate_counts(counts)
    if evidence_status not in {"COMPLETE", "INCOMPLETE"}:
        raise ValueError("evidence_status must be COMPLETE or INCOMPLETE")
    c = normalized
    equations = (
        c["shadow_entry_count"] == c["shadow_observation_count"],
        c["shadow_observation_count"]
        == c["shadow_pending_count"]
        + c["shadow_mature_known_count"]
        + c["shadow_mature_unknown_count"]
        + c["shadow_censored_stop_count"]
        + c["shadow_censored_failure_count"],
        c["shadow_outcome_count"]
        == c["shadow_mature_known_count"]
        + c["shadow_mature_unknown_count"]
        + c["shadow_censored_stop_count"]
        + c["shadow_censored_failure_count"],
        c["shadow_selected_exit_count"] == c["shadow_mature_known_count"],
        c["shadow_terminal_pair_count"] == c["shadow_outcome_count"],
        c["rejected_anchor_count"] == c["rejected_observation_count"],
        c["rejected_observation_count"]
        == c["rejected_pending_count"]
        + c["rejected_mature_known_count"]
        + c["rejected_mature_unknown_count"]
        + c["rejected_censored_stop_count"]
        + c["rejected_censored_failure_count"],
        c["rejected_outcome_count"]
        == c["rejected_mature_known_count"]
        + c["rejected_mature_unknown_count"]
        + c["rejected_censored_stop_count"]
        + c["rejected_censored_failure_count"],
        c["rejected_selected_exit_count"] == c["rejected_mature_known_count"],
        c["rejected_terminal_pair_count"] == c["rejected_outcome_count"],
        c["rejected_position_evaluation_count"] == c["rejected_position_action_count"],
        c["logical_admitted_pair_count"] == c["shadow_observation_count"],
        c["logical_rejected_pair_count"] == c["rejected_observation_count"],
        c["logical_aligned_pair_count"]
        == c["logical_admitted_pair_count"] + c["logical_rejected_pair_count"],
        c["logical_no_trade_arm_count"] == c["logical_aligned_pair_count"],
        c["logical_admitted_pair_count"]
        == c["enrolled_admitted_pair_count"] + c["non_enrolled_admitted_pair_count"],
        c["logical_rejected_pair_count"]
        == c["enrolled_rejected_pair_count"] + c["non_enrolled_rejected_pair_count"],
        c["enrolled_admitted_pair_count"]
        == c["enrolled_admitted_pending_count"]
        + c["enrolled_admitted_mature_known_count"]
        + c["enrolled_admitted_mature_unknown_count"]
        + c["enrolled_admitted_censored_stop_count"]
        + c["enrolled_admitted_censored_failure_count"],
        c["enrolled_rejected_pair_count"]
        == c["enrolled_rejected_pending_count"]
        + c["enrolled_rejected_mature_known_count"]
        + c["enrolled_rejected_mature_unknown_count"]
        + c["enrolled_rejected_censored_stop_count"]
        + c["enrolled_rejected_censored_failure_count"],
        c["enrolled_aligned_pair_count"]
        == c["enrolled_admitted_pair_count"] + c["enrolled_rejected_pair_count"],
        c["enrolled_terminal_pair_count"]
        == c["enrolled_admitted_mature_known_count"]
        + c["enrolled_admitted_mature_unknown_count"]
        + c["enrolled_admitted_censored_stop_count"]
        + c["enrolled_admitted_censored_failure_count"]
        + c["enrolled_rejected_mature_known_count"]
        + c["enrolled_rejected_mature_unknown_count"]
        + c["enrolled_rejected_censored_stop_count"]
        + c["enrolled_rejected_censored_failure_count"],
        c["enrolled_comparable_pair_count"]
        == c["enrolled_admitted_mature_known_count"] + c["enrolled_rejected_mature_known_count"],
        c["enrolled_admitted_mature_known_count"]
        == c["enrolled_admitted_mature_known_win_count"]
        + c["enrolled_admitted_mature_known_loss_count"]
        + c["enrolled_admitted_mature_known_zero_count"],
        c["enrolled_rejected_mature_known_count"]
        == c["enrolled_rejected_mature_known_win_count"]
        + c["enrolled_rejected_mature_known_loss_count"]
        + c["enrolled_rejected_mature_known_zero_count"],
        c["durable_terminal_pair_count"]
        == c["shadow_terminal_pair_count"] + c["rejected_terminal_pair_count"],
        c["durable_no_trade_arm_count"] == c["durable_terminal_pair_count"],
    )
    if not all(equations):
        return "NOT_MET"
    if evidence_status == "INCOMPLETE":
        return "UNKNOWN"
    terminal_has_no_pending = (
        c["shadow_pending_count"]
        == c["rejected_pending_count"]
        == c["enrolled_admitted_pending_count"]
        == c["enrolled_rejected_pending_count"]
        == 0
    )
    return "MET" if terminal_has_no_pending else "NOT_MET"


def compute_cohort_rates(
    counts: Mapping[str, int],
    *,
    evidence_status: str = "COMPLETE",
) -> dict[str, dict[str, int] | None]:
    c = _validate_counts(counts)
    if evidence_status not in {"COMPLETE", "INCOMPLETE"}:
        raise ValueError("evidence_status must be COMPLETE or INCOMPLETE")
    if evidence_status == "INCOMPLETE":
        return {key: None for key in COHORT_RATE_KEYS}
    admitted_available = (
        c["enrolled_admitted_mature_known_count"] + c["enrolled_admitted_mature_unknown_count"]
    )
    admitted_terminal = (
        admitted_available
        + c["enrolled_admitted_censored_stop_count"]
        + c["enrolled_admitted_censored_failure_count"]
    )
    rejected_available = (
        c["enrolled_rejected_mature_known_count"] + c["enrolled_rejected_mature_unknown_count"]
    )
    rejected_terminal = (
        rejected_available
        + c["enrolled_rejected_censored_stop_count"]
        + c["enrolled_rejected_censored_failure_count"]
    )
    rates = {
        "admitted_terminal_availability_rate": _rate(
            admitted_available,
            admitted_terminal,
        ),
        "rejected_terminal_availability_rate": _rate(
            rejected_available,
            rejected_terminal,
        ),
        "admitted_maturity_known_share": _rate(
            c["enrolled_admitted_mature_known_count"],
            admitted_available,
        ),
        "rejected_maturity_known_share": _rate(
            c["enrolled_rejected_mature_known_count"],
            rejected_available,
        ),
        "admitted_win_rate": _rate(
            c["enrolled_admitted_mature_known_win_count"],
            c["enrolled_admitted_mature_known_count"],
        ),
        "admitted_loss_rate": _rate(
            c["enrolled_admitted_mature_known_loss_count"],
            c["enrolled_admitted_mature_known_count"],
        ),
        "rejected_win_rate": _rate(
            c["enrolled_rejected_mature_known_win_count"],
            c["enrolled_rejected_mature_known_count"],
        ),
        "rejected_loss_rate": _rate(
            c["enrolled_rejected_mature_known_loss_count"],
            c["enrolled_rejected_mature_known_count"],
        ),
        "aligned_economic_comparison_availability_rate": _rate(
            c["enrolled_comparable_pair_count"],
            c["enrolled_terminal_pair_count"],
        ),
    }
    if tuple(rates) != COHORT_RATE_KEYS:
        raise RuntimeError("cohort rate registry order drifted")
    return rates


def underwriting_conservation_status(counts: Mapping[str, int]) -> str:
    c = _validate_underwriting_counts(counts)
    equations = (
        c["underwriting_action_candidate_count"]
        + c["underwriting_action_watch_count"]
        + c["underwriting_action_abstain_count"]
        == c["underwriting_availability_evaluable_count"],
        c["candidate_count"] == c["underwriting_action_candidate_count"],
        c["admission_entry_emitted_count"]
        + c["admission_known_complete_no_entry_count"]
        + c["admission_known_invalidated_before_refresh_count"]
        + c["admission_unknown_consumed_count"]
        == c["candidate_count"],
        c["shadow_entry_count"] == c["admission_entry_emitted_count"],
        c["shadow_close_opportunity_count"] == c["close_opportunity_eligible_count"],
    )
    return "MET" if all(equations) else "NOT_MET"


def compute_underwriting_rates(
    counts: Mapping[str, int],
) -> dict[str, dict[str, int] | None]:
    c = _validate_underwriting_counts(counts)
    availability_total = (
        c["underwriting_availability_not_evaluated_count"]
        + c["underwriting_availability_unknown_count"]
        + c["underwriting_availability_evaluable_count"]
    )
    admission_evaluable = (
        c["admission_entry_emitted_count"] + c["admission_known_complete_no_entry_count"]
    )
    position_total = (
        c["position_hold_count"] + c["position_close_count"] + c["position_unknown_count"]
    )
    quote_total = (
        c["close_quote_atomic_count"]
        + c["close_quote_legged_reference_count"]
        + c["close_quote_unexecutable_count"]
        + c["close_quote_unknown_count"]
    )
    known_opportunity_total = (
        c["close_opportunity_eligible_count"] + c["close_opportunity_ineligible_count"]
    )
    rates = {
        "underwriting_known_availability_rate": _rate(
            c["underwriting_availability_not_evaluated_count"]
            + c["underwriting_availability_evaluable_count"],
            availability_total,
        ),
        "underwriting_evaluable_rate": _rate(
            c["underwriting_availability_evaluable_count"],
            availability_total,
        ),
        "underwriting_candidate_action_rate": _rate(
            c["underwriting_action_candidate_count"],
            c["underwriting_availability_evaluable_count"],
        ),
        "underwriting_watch_action_rate": _rate(
            c["underwriting_action_watch_count"],
            c["underwriting_availability_evaluable_count"],
        ),
        "underwriting_abstain_action_rate": _rate(
            c["underwriting_action_abstain_count"],
            c["underwriting_availability_evaluable_count"],
        ),
        "candidate_activation_rate": _rate(
            c["candidate_count"],
            c["underwriting_availability_evaluable_count"],
        ),
        "admission_evaluable_rate": _rate(
            admission_evaluable,
            c["candidate_count"],
        ),
        "shadow_entry_rate": _rate(
            c["shadow_entry_count"],
            admission_evaluable,
        ),
        "position_known_action_rate": _rate(
            c["position_hold_count"] + c["position_close_count"],
            position_total,
        ),
        "close_quote_known_state_rate": _rate(
            c["close_quote_atomic_count"]
            + c["close_quote_legged_reference_count"]
            + c["close_quote_unexecutable_count"],
            quote_total,
        ),
        "close_opportunity_rate_while_closing": _rate(
            c["close_opportunity_eligible_count"],
            known_opportunity_total,
        ),
    }
    if tuple(rates) != UNDERWRITING_RATE_KEYS:
        raise RuntimeError("Underwriting rate registry order drifted")
    return rates


def _validate_counts(counts: Mapping[str, int]) -> dict[str, int]:
    if tuple(counts) != COHORT_COUNT_KEYS and set(counts) != set(COHORT_COUNT_KEYS):
        missing = sorted(set(COHORT_COUNT_KEYS) - set(counts))
        unknown = sorted(set(counts) - set(COHORT_COUNT_KEYS))
        raise ValueError(f"CohortCounts requires exact keys; missing={missing}, unknown={unknown}")
    normalized: dict[str, int] = {}
    for key in COHORT_COUNT_KEYS:
        value = counts[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        normalized[key] = value
    return normalized


def _validate_underwriting_counts(counts: Mapping[str, int]) -> dict[str, int]:
    if set(counts) != set(UNDERWRITING_COUNT_KEYS):
        missing = sorted(set(UNDERWRITING_COUNT_KEYS) - set(counts))
        unknown = sorted(set(counts) - set(UNDERWRITING_COUNT_KEYS))
        raise ValueError(
            f"Underwriting counts require exact keys; missing={missing}, unknown={unknown}"
        )
    normalized: dict[str, int] = {}
    for key in UNDERWRITING_COUNT_KEYS:
        value = counts[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        normalized[key] = value
    return normalized


def _rate(numerator: int, denominator: int) -> dict[str, int] | None:
    if denominator == 0:
        return None
    return {"numerator": numerator, "denominator": denominator}


def derive_underwriting_counts(
    objects: Iterable[Mapping[str, object]],
) -> dict[str, int]:
    """Derive exact distinct-business-identity counts from validated durable objects."""
    counts = {key: 0 for key in UNDERWRITING_COUNT_KEYS}
    seen: set[tuple[str, str]] = set()
    for value in objects:
        kind = value.get("object_kind")
        identity = value.get("object_identity")
        payload = value.get("payload")
        if not isinstance(kind, str) or not isinstance(identity, str):
            raise ValueError("validated object lacks kind or identity")
        if not isinstance(payload, Mapping):
            raise ValueError("validated object lacks payload")
        if (kind, identity) in seen:
            continue
        seen.add((kind, identity))
        if kind == "UNDERWRITING_AVAILABILITY_EVALUATION":
            counts[f"underwriting_availability_{str(payload['availability']).lower()}_count"] += 1
        elif kind == "UNDERWRITING_ACTION":
            counts[f"underwriting_action_{str(payload['economic_action']).lower()}_count"] += 1
        elif kind == "CANDIDATE_ACTIVATION":
            counts["candidate_count"] += 1
        elif kind == "ADMISSION_ATTEMPT_TERMINAL":
            counts[f"admission_{str(payload['terminal_outcome']).lower()}_count"] += 1
        elif kind == "SHADOW_ENTRY":
            counts["shadow_entry_count"] += 1
        elif kind == "POSITION_ACTION":
            counts[f"position_{str(payload['serialized_action']).lower()}_count"] += 1
        elif kind == "CLOSE_QUOTE_EVALUATION":
            suffix = {
                "ATOMIC_COMBO_CLOSE_QUOTE": "atomic",
                "LEGGED_CLOSE_REFERENCE": "legged_reference",
                "UNEXECUTABLE": "unexecutable",
                "UNKNOWN": "unknown",
            }[str(payload["close_quote_state"])]
            counts[f"close_quote_{suffix}_count"] += 1
        elif kind == "CLOSE_OPPORTUNITY_EVALUATION":
            counts[f"close_opportunity_{str(payload['eligibility']).lower()}_count"] += 1
        elif kind == "SHADOW_CLOSE_OPPORTUNITY":
            counts["shadow_close_opportunity_count"] += 1
    return counts


def derive_cohort_counts(
    objects: Iterable[Mapping[str, object]],
) -> dict[str, int]:
    """Derive CohortCounts from validated observation, Outcome, exit, and pair identities."""
    counts = {key: 0 for key in COHORT_COUNT_KEYS}
    unique: dict[tuple[str, str], Mapping[str, object]] = {}
    for value in objects:
        kind = value.get("object_kind")
        identity = value.get("object_identity")
        if not isinstance(kind, str) or not isinstance(identity, str):
            raise ValueError("validated object lacks kind or identity")
        unique.setdefault((kind, identity), value)

    admitted_observations: dict[str, bool] = {}
    rejected_observations: dict[str, bool] = {}
    for (kind, _identity), value in unique.items():
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("validated object lacks payload")
        if kind == "SHADOW_ENTRY":
            counts["shadow_entry_count"] += 1
        elif kind == "SHADOW_OUTCOME_OBSERVATION":
            observation = str(payload["shadow_observation_identity"])
            admitted_observations[observation] = bool(payload["cohort_enrolled"])
            counts["shadow_observation_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_ANCHOR":
            counts["rejected_anchor_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_OBSERVATION":
            observation = str(payload["rejected_observation_identity"])
            rejected_observations[observation] = bool(payload["cohort_enrolled"])
            counts["rejected_observation_count"] += 1
        elif kind == "SHADOW_COUNTERFACTUAL_EXIT":
            counts["shadow_selected_exit_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_EXIT":
            counts["rejected_selected_exit_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_POSITION_EVALUATION":
            counts["rejected_position_evaluation_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_POSITION_ACTION":
            counts["rejected_position_action_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION":
            counts["rejected_close_quote_evaluation_count"] += 1
        elif kind == "REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION":
            counts["rejected_close_opportunity_evaluation_count"] += 1

    admitted_terminal: set[str] = set()
    rejected_terminal: set[str] = set()
    for (kind, _identity), value in unique.items():
        payload = value["payload"]
        assert isinstance(payload, Mapping)
        if kind == "SHADOW_OUTCOME":
            observation = str(payload["shadow_observation_identity"])
            admitted_terminal.add(observation)
            counts["shadow_outcome_count"] += 1
            _count_terminal_state(
                counts,
                prefix="shadow",
                state=str(payload["terminal_state"]),
            )
            if admitted_observations.get(observation) is True:
                _count_terminal_state(
                    counts,
                    prefix="enrolled_admitted",
                    state=str(payload["terminal_state"]),
                )
        elif kind == "REJECTED_COUNTERFACTUAL_OUTCOME":
            observation = str(payload["rejected_observation_identity"])
            rejected_terminal.add(observation)
            counts["rejected_outcome_count"] += 1
            _count_terminal_state(
                counts,
                prefix="rejected",
                state=str(payload["terminal_state"]),
            )
            if rejected_observations.get(observation) is True:
                _count_terminal_state(
                    counts,
                    prefix="enrolled_rejected",
                    state=str(payload["terminal_state"]),
                )

    counts["shadow_pending_count"] = len(set(admitted_observations) - admitted_terminal)
    counts["rejected_pending_count"] = len(set(rejected_observations) - rejected_terminal)
    counts["logical_admitted_pair_count"] = len(admitted_observations)
    counts["logical_rejected_pair_count"] = len(rejected_observations)
    counts["logical_aligned_pair_count"] = len(admitted_observations) + len(rejected_observations)
    counts["logical_no_trade_arm_count"] = counts["logical_aligned_pair_count"]
    counts["enrolled_admitted_pair_count"] = sum(admitted_observations.values())
    counts["non_enrolled_admitted_pair_count"] = (
        len(admitted_observations) - counts["enrolled_admitted_pair_count"]
    )
    counts["enrolled_rejected_pair_count"] = sum(rejected_observations.values())
    counts["non_enrolled_rejected_pair_count"] = (
        len(rejected_observations) - counts["enrolled_rejected_pair_count"]
    )
    counts["enrolled_admitted_pending_count"] = sum(
        enrolled and identity not in admitted_terminal
        for identity, enrolled in admitted_observations.items()
    )
    counts["enrolled_rejected_pending_count"] = sum(
        enrolled and identity not in rejected_terminal
        for identity, enrolled in rejected_observations.items()
    )

    for (kind, _identity), value in unique.items():
        if kind != "ALIGNED_POLICY_NO_TRADE_PAIR":
            continue
        payload = value["payload"]
        assert isinstance(payload, Mapping)
        family = str(payload["pair_family"])
        enrolled = bool(payload["cohort_enrolled"])
        if family == "ADMITTED":
            counts["shadow_terminal_pair_count"] += 1
        else:
            counts["rejected_terminal_pair_count"] += 1
        counts["durable_terminal_pair_count"] += 1
        counts["durable_no_trade_arm_count"] += 1
        if enrolled:
            counts["enrolled_aligned_pair_count"] += 1
            counts["enrolled_terminal_pair_count"] += 1
            if payload["comparison_availability"] == "KNOWN":
                counts["enrolled_comparable_pair_count"] += 1
                pnl = _decimal(payload["trade_net_pnl_after_public_standard_fee_reserve_usdc"])
                suffix = "win" if pnl > 0 else "loss" if pnl < 0 else "zero"
                prefix = (
                    "enrolled_admitted_mature_known"
                    if family == "ADMITTED"
                    else "enrolled_rejected_mature_known"
                )
                counts[f"{prefix}_{suffix}_count"] += 1
    return counts


def _count_terminal_state(
    counts: dict[str, int],
    *,
    prefix: str,
    state: str,
) -> None:
    suffix = {
        "MATURE_KNOWN": "mature_known",
        "MATURE_UNKNOWN": "mature_unknown",
        "CENSORED_AT_STOP": "censored_stop",
        "CENSORED_AT_FAILURE": "censored_failure",
    }.get(state)
    if suffix is None:
        raise ValueError(f"invalid terminal state: {state}")
    counts[f"{prefix}_{suffix}_count"] += 1


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("known pair PnL must be an exact Decimal") from exc
    if not result.is_finite():
        raise ValueError("known pair PnL must be finite")
    return result
