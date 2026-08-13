from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from optimatrix.lifecycle import TradeCase

WORKBENCH_SCHEMA_VERSION = 3
_ASSET_ROOT = Path(__file__).with_name("workbench_static")
_STATIC_ASSETS = ("index.html", "styles.css", "app.js")

_WINDOW_LABELS = {
    "decision_window_id": "Decision Window identity",
    "channel_id": "Product and strategy",
    "market_session_id": "Market Session",
    "schedule_policy_id": "Window schedule Policy",
    "starts_at": "Scheduled start",
    "ends_at": "Scheduled end",
    "input_deadline": "Input deadline",
    "observation_id": "Market Observation identity",
    "ledger_state": "All-Window ledger state",
}
_CONTEXT_LABELS = {
    "knowledge": "Market-context evidence",
    "index_price": "BTC index price",
    "forward_price": "Forward price",
    "trailing_realized_variance_proxy": "Trailing matched-horizon RV proxy",
    "same_session_implied_variance_proxy": "Same-session ATM mark-variance proxy",
    "rv_acceleration": "Realized-volatility acceleration",
    "jump_share": "Jump share",
    "directional_persistence": "Directional persistence",
    "event_state": "Event state",
    "concentrated_strike": "Concentrated strike",
    "concentration_strength": "Concentration strength",
    "realized_variance_method": "Realized-variance method",
    "implied_variance_method": "Implied-side method",
    "event_state_source": "Event-state source",
    "required_history_start_ms": "Required history start (ms)",
    "history_coverage_start_ms": "History coverage start (ms)",
    "history_coverage_end_ms": "History coverage end (ms)",
    "history_cadence_ms": "History cadence (ms)",
    "market_source_min_ms": "Oldest required market source (ms)",
    "market_source_max_ms": "Latest required market source (ms)",
    "market_received_min_ms": "Oldest required market receipt (ms)",
    "market_received_max_ms": "Latest required market receipt (ms)",
    "event_state_known_at_ms": "Event state known at (ms)",
}
_RUNTIME_LABELS = {
    "status": "Runtime status",
    "session_id": "Target Session",
    "started_at": "Started at",
    "updated_at": "Last update",
    "recovered_case_count": "Recovered Cases",
    "restart_count": "Observed restarts",
    "last_recovery_at": "Last recovery",
    "current_window_id": "Current Decision Window",
    "attempted_window_count": "Attempted Decision Windows",
    "last_error": "Last error",
}
_POPULATION_LABELS = {
    "future_path_known": "Future path known",
    "future_path_unknown": "Future path unknown",
    "continuous": "Continuous future path",
    "discontinuous": "Discontinuous future path",
    "decision_evaluable": "Decision evaluable",
    "strategy_population_eligible": "Strategy population eligible",
}
_CASE_LABELS = {
    "truth_layer": "Truth layer",
    "trade_case_id": "Trade Case identity",
    "decision_window_id": "Decision Window identity",
    "opened_at": "Opened at",
    "entry_deadline": "Entry deadline",
    "entry_status": "Entry status",
    "entry_final": "Entry final",
    "entry_observed_at": "Entry observed at",
    "entry_reason": "Entry reason",
    "position_id": "Shadow Position identity",
    "position_state": "Position state",
    "last_observed_at": "Last lifecycle observation",
    "gap_observed": "DataHealth gap observed",
}
_CASE_STRUCTURE_LABELS = {
    "candidate_id": "Frozen Candidate identity",
    "expiry": "Frozen expiry",
    "option_amount": "Frozen option amount",
}
_CASE_LEG_LABELS = {
    "strike": "Frozen strike",
    "option_type": "Frozen option type",
    "expiry": "Frozen expiry",
    "option_amount": "Frozen amount",
    "candidate_id": "Frozen Candidate identity",
}
_RISK_ALLOCATION_LABELS = {
    "allocation_id": "Shadow Risk Allocation identity",
    "result": "Allocation result",
    "candidate_id": "Frozen Candidate identity",
    "channel_id": "Channel",
    "market_session_id": "Market Session",
    "policy_id": "Risk Policy identity",
    "known_at": "Allocation known at",
    "budget_metric": "Budget metric",
    "option_amount": "Allocated option amount",
    "maximum_contractual_payoff_usd": "Contractual payoff cap (USD)",
    "entry_premium_native": "Boundary entry premium (BTC)",
    "combo_fee_native": "Boundary Combo fee (BTC)",
    "boundary_index_price_usd": "Boundary index price (USD)",
    "exit_cost_stress_native": "Exit-cost stress (BTC)",
    "session_budget_usd": "Session budget (USD)",
    "session_used_before_usd": "Session used before (USD)",
    "session_remaining_after_usd": "Session remaining after (USD)",
    "concurrent_position_limit": "Concurrent Position limit",
    "open_position_count_before": "Open Positions before",
    "expires_at": "Allocation expires at",
    "release_condition": "Release condition",
    "reason": "Allocation reason",
}
_ENTRY_EVIDENCE_LABELS = {
    "decision_record_id": "Decision Record identity",
    "decision_policy_id": "Decision Policy identity",
    "decision_boundary": "Decision known-at boundary",
    "entry_deadline": "Entry deadline",
    "entry_status": "Entry status",
    "entry_final": "Entry final",
    "entry_observation_id": "Entry Market Observation identity",
    "entry_observed_at": "Entry observation observed at",
    "entry_known_at": "Entry observation known at",
    "entry_pricing_basis": "Shadow pricing basis",
    "entry_reason": "Entry reason",
}
_ENTRY_ECONOMICS_LABELS = {
    "fee_model_id": "Fee model identity",
    "native_gross_credit": "Gross entry credit (BTC)",
    "combo_standard_fee_native": "Entry Combo fee (BTC)",
    "native_net_credit": "Net entry credit (BTC)",
    "boundary_index_price_usd": "Entry boundary index (USD)",
    "boundary_net_credit_usd": "Net entry credit at boundary (USD)",
    "entry_native_net_credit": "Frozen Case entry net credit (BTC)",
    "entry_index_price_usd": "Frozen Case entry index (USD)",
    "entry_vrp_proxy_ratio": "Entry VRP proxy ratio",
}
_EXIT_INTENT_LABELS = {
    "exit_intent_id": "Exit Intent identity",
    "category": "Trigger category",
    "reason": "First trigger reason",
    "observation_id": "Trigger Market Observation identity",
    "observed_at": "Trigger observed at",
    "known_at": "Trigger known at",
    "source": "Trigger source",
    "policy_id": "Lifecycle Policy identity",
    "scope": "Exit scope",
}
_OUTCOME_LABELS = {
    "outcome_id": "Outcome identity",
    "terminal_method": "Terminal method",
    "terminal_at": "Terminal known at",
    "entry_status": "Terminal Entry status",
    "entry_observation_id": "Entry Market Observation identity",
    "terminal_evidence_id": "Terminal evidence identity",
    "native_result_btc": "Shadow result (BTC)",
    "boundary_reference_result_usd": "Boundary reference result (USD)",
    "fee_model_id": "Terminal fee model identity",
    "shadow_model_id": "Shadow model identity",
    "terminal_source": "Terminal evidence source",
    "data_gap_observed": "DataHealth gap observed",
    "reason": "Terminal reason",
}
_STRUCTURE_METRIC_LABELS = {
    "boundary_net_credit_usd": "Boundary-valued four-leg net credit",
    "boundary_reference_loss_usd": "Boundary-valued reference loss",
    "native_net_credit_btc": "Native BTC net credit",
    "combo_standard_fee_btc": "Standard Combo fee in BTC",
    "maximum_contractual_payoff_cap_usd": "Maximum contractual payoff cap in USD",
    "net_delta": "Four-leg net Delta",
    "minimum_body_distance_sigma": "Nearest short strike distance",
    "minimum_observed_close_depth_coverage": "Minimum current close-depth coverage",
}
_LEG_DEFINITIONS = (
    ("long_put", "Long Put wing", "LONG", "PUT"),
    ("short_put", "Short Put body", "SHORT", "PUT"),
    ("short_call", "Short Call body", "SHORT", "CALL"),
    ("long_call", "Long Call wing", "LONG", "CALL"),
)
_QUOTE_DETAIL_LABELS = {
    "strike": "Strike",
    "signed_delta": "Delta",
    "mark_iv": "Mark IV",
    "best_bid": "Best public bid",
    "best_ask": "Best public ask",
    "gamma": "Gamma",
    "source_timestamp_ms": "Source timestamp (ms)",
    "received_timestamp_ms": "Received timestamp (ms)",
}
_BOUNDARY_STATEMENTS = (
    "Public market facts and counterfactual structure economics only.",
    "No order, fill, account, balance, margin, capital, or actual position is present.",
    "Displayed credit and loss are observation-boundary estimates, not real PnL.",
    "This static export creates no Shadow Case and grants no execution permission.",
)


@dataclass(frozen=True)
class WorkbenchExport:
    output_dir: Path
    index_path: Path
    data_path: Path
    stylesheet_path: Path
    script_path: Path


def build_workbench_document(
    snapshot: Mapping[str, object],
    *,
    trade_case: TradeCase | None = None,
    runtime_state: Mapping[str, object] | None = None,
    ledger_population: Mapping[str, object] | None = None,
    recovered_cases: Sequence[TradeCase] | None = None,
) -> dict[str, object]:
    """Build the presentation model for one public snapshot and optional runtime facts.

    All joins, ordering, labels, and state tones are resolved here. The browser receives a display
    document and never recomputes strategy, structure, or lifecycle truth.
    """

    root = _mapping(snapshot, "snapshot")
    session_id = _required_text(root.get("session_id"), "snapshot.session_id")
    observed_at = _required_text(root.get("observed_at"), "snapshot.observed_at")
    window = _mapping(root.get("window"), "snapshot.window")
    context = _mapping(root.get("context"), "snapshot.context")
    projection = _mapping(root.get("projection"), "snapshot.projection")
    state = _required_text(projection.get("state"), "snapshot.projection.state")
    phase = _required_text(projection.get("phase"), "snapshot.projection.phase")
    blockers = _text_sequence(projection.get("blockers"), "snapshot.projection.blockers")
    warnings = _text_sequence(root.get("warnings"), "snapshot.warnings")
    quote_index = _quote_index(root.get("quotes"))

    runtime = _runtime_projection(
        runtime_state,
        fallback_session_id=session_id,
        fallback_updated_at=observed_at,
    )

    return {
        "schema_version": WORKBENCH_SCHEMA_VERSION,
        "product": {
            "title": "Optimatrix BTC 0DTE Two-Sided Short Vol",
            "strategy": "Same-session asymmetric Iron Condor",
            "mode": "PUBLIC SHADOW - READ ONLY",
        },
        "boundary": {
            "label": "PUBLIC SHADOW - READ ONLY",
            "statements": list(_BOUNDARY_STATEMENTS),
        },
        "snapshot": {
            "session_id": session_id,
            "observed_at": observed_at,
            "instrument_count": _display_value(root.get("instrument_count")),
            "requested_book_count": _display_value(root.get("requested_book_count")),
            "fetched_book_count": _display_value(root.get("fetched_book_count")),
        },
        "runtime": runtime,
        "population": _ledger_population_projection(
            ledger_population,
            attempted_window_count=runtime["attempted_window_count"],
        ),
        "warnings": [{"code": warning, "tone": "warning"} for warning in warnings],
        "window": _display_rows(window, _WINDOW_LABELS),
        "projection": {
            "state": state,
            "phase": phase,
            "tone": _projection_tone(state),
            "blockers": [{"code": blocker, "tone": "danger"} for blocker in blockers],
        },
        "structure": _structure_projection(
            projection.get("structure"),
            quote_index,
            projection_state=state,
        ),
        "context": _display_rows(context, _CONTEXT_LABELS),
        "methodology": _optional_display_rows(root.get("methodology"), {}),
        "case": build_case_projection(trade_case),
        "cases": _case_collection_projection(
            trade_case=trade_case,
            recovered_cases=recovered_cases,
        ),
    }


def write_workbench(
    snapshot: Mapping[str, object],
    output_dir: str | Path,
    *,
    trade_case: TradeCase | None = None,
    runtime_state: Mapping[str, object] | None = None,
    ledger_population: Mapping[str, object] | None = None,
    recovered_cases: Sequence[TradeCase] | None = None,
) -> WorkbenchExport:
    """Write a self-contained, network-JavaScript-free Workbench directory."""

    document = build_workbench_document(
        snapshot,
        trade_case=trade_case,
        runtime_state=runtime_state,
        ledger_population=ledger_population,
        recovered_cases=recovered_cases,
    )
    destination = Path(output_dir).expanduser().resolve()
    if destination == _ASSET_ROOT.resolve():
        raise ValueError("output_dir cannot overwrite the Workbench source assets")
    destination.mkdir(parents=True, exist_ok=True)

    for name in _STATIC_ASSETS:
        source = _ASSET_ROOT / name
        if not source.is_file():
            raise RuntimeError(f"Workbench source asset is missing: {name}")
        _write_text(destination / name, source.read_text(encoding="utf-8"))

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).replace("</", "<\\/")
    data_path = destination / "workbench-data.js"
    _write_text(data_path, f"window.OPTIMATRIX_WORKBENCH = Object.freeze({encoded});\n")
    return WorkbenchExport(
        output_dir=destination,
        index_path=destination / "index.html",
        data_path=data_path,
        stylesheet_path=destination / "styles.css",
        script_path=destination / "app.js",
    )


def build_case_projection(case: TradeCase | None) -> dict[str, object]:
    if case is None:
        return {
            "available": False,
            "trade_case_id": None,
            "entry_status": "UNKNOWN",
            "position_state": "UNKNOWN",
            "message": "This bounded snapshot did not open a TradeCase.",
            "facts": [],
            "selected_structure": _empty_case_structure_projection(),
            "risk_allocation": [],
            "entry_evidence": [],
            "entry_economics": [],
            "exit_intent": [],
            "outcome": [],
            "eligibility": [],
        }
    facts = {
        "truth_layer": case.truth_layer,
        "trade_case_id": case.identity,
        "decision_window_id": case.decision_window_id,
        "opened_at": case.opened_at.isoformat(),
        "entry_deadline": case.entry_deadline.isoformat(),
        "entry_status": case.entry_status.value if case.entry_status is not None else None,
        "entry_final": case.entry_final,
        "entry_observed_at": (
            case.entry_observed_at.isoformat() if case.entry_observed_at is not None else None
        ),
        "entry_reason": case.entry_reason,
        "position_id": case.position_id,
        "position_state": case.position_state.value if case.position_state is not None else None,
        "last_observed_at": (
            case.last_observed_at.isoformat() if case.last_observed_at is not None else None
        ),
        "gap_observed": case.gap_observed,
    }
    selected_structure = _case_structure_projection(case)
    risk_allocation = _case_mapping(case, "risk_allocation", "TradeCase.risk_allocation")
    entry_pricing = _case_mapping(case, "entry_pricing", "TradeCase.entry_pricing")
    entry_evidence = {
        "decision_record_id": getattr(case, "decision_record_id", None),
        "decision_policy_id": getattr(case, "decision_policy_id", None),
        "decision_boundary": _optional_isoformat(getattr(case, "decision_boundary", None)),
        "entry_deadline": case.entry_deadline.isoformat(),
        "entry_status": case.entry_status.value if case.entry_status is not None else None,
        "entry_final": case.entry_final,
        "entry_observation_id": getattr(case, "entry_observation_id", None),
        "entry_observed_at": _optional_isoformat(case.entry_observed_at),
        "entry_known_at": _optional_isoformat(getattr(case, "entry_known_at", None)),
        "entry_pricing_basis": getattr(case, "entry_pricing_basis", None),
        "entry_reason": case.entry_reason,
    }
    entry_economics = dict(entry_pricing or {})
    entry_economics.update(
        {
            "entry_native_net_credit": _optional_string(
                getattr(case, "entry_native_net_credit", None)
            ),
            "entry_index_price_usd": _optional_string(getattr(case, "entry_index_price_usd", None)),
            "entry_vrp_proxy_ratio": _optional_string(getattr(case, "entry_vrp_proxy_ratio", None)),
        }
    )
    intent = (
        {
            "exit_intent_id": case.exit_intent.identity,
            "category": case.exit_intent.category,
            "reason": case.exit_intent.reason,
            "observation_id": case.exit_intent.observation_id,
            "observed_at": case.exit_intent.observed_at.isoformat(),
            "known_at": case.exit_intent.known_at.isoformat(),
            "source": case.exit_intent.source,
            "policy_id": case.exit_intent.policy_id,
            "scope": case.exit_intent.scope,
        }
        if case.exit_intent is not None
        else None
    )
    outcome = case.outcome
    outcome_values = (
        {
            "outcome_id": outcome.identity,
            "terminal_method": outcome.terminal_method.value,
            "terminal_at": outcome.terminal_at.isoformat(),
            "entry_status": outcome.entry_status.value,
            "entry_observation_id": outcome.entry_observation_id,
            "terminal_evidence_id": outcome.terminal_evidence_id,
            "native_result_btc": (
                str(outcome.native_result_btc) if outcome.native_result_btc is not None else None
            ),
            "boundary_reference_result_usd": (
                str(outcome.boundary_reference_result_usd)
                if outcome.boundary_reference_result_usd is not None
                else None
            ),
            "fee_model_id": outcome.fee_model_id,
            "shadow_model_id": outcome.shadow_model_id,
            "terminal_source": outcome.terminal_source,
            "data_gap_observed": outcome.data_gap_observed,
            "reason": outcome.reason,
        }
        if outcome is not None
        else None
    )
    eligibility = (
        [
            {
                "key": name,
                "label": name.replace("_", " ").title(),
                "value": ("UNKNOWN" if fact.value is None else "YES" if fact.value else "NO"),
                "reason": fact.reason,
            }
            for name, fact in (
                ("decision_evaluable", outcome.eligibility.decision_evaluable),
                ("future_path_known", outcome.eligibility.future_path_known),
                ("future_path_continuous", outcome.eligibility.future_path_continuous),
                ("shadow_entry_evaluable", outcome.eligibility.shadow_entry_evaluable),
                (
                    "terminal_economics_evaluable",
                    outcome.eligibility.terminal_economics_evaluable,
                ),
                (
                    "live_execution_attributable",
                    outcome.eligibility.live_execution_attributable,
                ),
                (
                    "strategy_population_eligible",
                    outcome.eligibility.strategy_population_eligible,
                ),
                ("qualification_eligible", outcome.eligibility.qualification_eligible),
            )
        ]
        if outcome is not None
        else []
    )
    return {
        "available": True,
        "trade_case_id": case.identity,
        "entry_status": case.entry_status.value if case.entry_status is not None else "UNKNOWN",
        "position_state": (
            case.position_state.value if case.position_state is not None else "UNKNOWN"
        ),
        "message": "Counterfactual whole-product lifecycle; no order, fill, or account Position.",
        "facts": _display_rows(facts, _CASE_LABELS),
        "selected_structure": selected_structure,
        "risk_allocation": _optional_display_rows(
            risk_allocation,
            _RISK_ALLOCATION_LABELS,
        ),
        "entry_evidence": _display_rows(entry_evidence, _ENTRY_EVIDENCE_LABELS),
        "entry_economics": _display_rows(entry_economics, _ENTRY_ECONOMICS_LABELS),
        "exit_intent": _optional_display_rows(intent, _EXIT_INTENT_LABELS),
        "outcome": _optional_display_rows(outcome_values, _OUTCOME_LABELS),
        "eligibility": eligibility,
    }


def _empty_case_structure_projection() -> dict[str, object]:
    return {"available": False, "summary": [], "legs": []}


def _case_structure_projection(case: TradeCase) -> dict[str, object]:
    structure = _case_mapping(case, "selected_structure", "TradeCase.selected_structure")
    if structure is None:
        return _empty_case_structure_projection()
    candidate_id = structure.get("candidate_id")
    expiry = structure.get("expiry")
    option_amount = structure.get("option_amount")
    legs_value = _mapping(structure.get("legs"), "TradeCase.selected_structure.legs")
    legs: list[dict[str, object]] = []
    for position, (role, label, action, _option_type) in enumerate(_LEG_DEFINITIONS, start=1):
        leg = _mapping(legs_value.get(role), f"TradeCase.selected_structure.legs.{role}")
        values = {
            "strike": leg.get("strike"),
            "option_type": leg.get("option_type"),
            "expiry": expiry,
            "option_amount": option_amount,
            "candidate_id": candidate_id,
        }
        legs.append(
            {
                "position": position,
                "role": role,
                "label": label,
                "action": action,
                "option_type": _display_value(leg.get("option_type")),
                "instrument_name": _display_value(leg.get("instrument_name")),
                "strike": _display_value(leg.get("strike")),
                "expiry": _display_value(expiry),
                "option_amount": _display_value(option_amount),
                "candidate_id": _display_value(candidate_id),
                "details": _display_rows(values, _CASE_LEG_LABELS),
            }
        )
    return {
        "available": True,
        "summary": _display_rows(
            {
                "candidate_id": candidate_id,
                "expiry": expiry,
                "option_amount": option_amount,
            },
            _CASE_STRUCTURE_LABELS,
        ),
        "legs": legs,
    }


def _case_mapping(
    case: TradeCase,
    attribute: str,
    field: str,
) -> Mapping[str, object] | None:
    value = getattr(case, attribute, None)
    if value is None:
        return None
    return _mapping(value, field)


def _optional_isoformat(value: object) -> str | None:
    method = getattr(value, "isoformat", None)
    if value is None:
        return None
    if not callable(method):
        raise TypeError("Case timestamp must provide isoformat()")
    result = method()
    if not isinstance(result, str):
        raise TypeError("Case timestamp isoformat() must return text")
    return result


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _runtime_projection(
    value: Mapping[str, object] | None,
    *,
    fallback_session_id: str,
    fallback_updated_at: str,
) -> dict[str, object]:
    if value is None:
        return {
            "available": False,
            "status": "SNAPSHOT_ONLY",
            "tone": "neutral",
            "session_id": fallback_session_id,
            "updated_at": fallback_updated_at,
            "attempted_window_count": "UNKNOWN",
            "last_error": "NONE",
            "facts": [],
        }
    runtime = _mapping(value, "runtime_state")
    status = _required_text(runtime.get("status"), "runtime_state.status")
    session_id = _required_text(runtime.get("session_id"), "runtime_state.session_id")
    display_runtime = dict(runtime)
    if "last_error" in display_runtime and display_runtime["last_error"] is None:
        display_runtime["last_error"] = "NONE"
    return {
        "available": True,
        "status": status,
        "tone": _runtime_tone(status),
        "session_id": session_id,
        "updated_at": _display_value(runtime.get("updated_at")),
        "attempted_window_count": _display_count(
            runtime.get("attempted_window_count"),
            "runtime_state.attempted_window_count",
        ),
        "last_error": _display_value(display_runtime.get("last_error")),
        "facts": _display_rows(display_runtime, _RUNTIME_LABELS),
    }


def _ledger_population_projection(
    value: Mapping[str, object] | None,
    *,
    attempted_window_count: object,
) -> dict[str, object]:
    if value is None:
        return {
            "available": False,
            "calendar_reference": "UNKNOWN",
            "decisions": _population_section(
                None,
                label="DecisionRecords",
                attempted_window_count=attempted_window_count,
            ),
            "outcomes": _population_section(
                None,
                label="WindowOutcomes",
                attempted_window_count=attempted_window_count,
            ),
        }
    population = _mapping(value, "ledger_population")
    decisions = _population_section(
        population.get("decisions"),
        label="DecisionRecords",
        attempted_window_count=attempted_window_count,
        field="ledger_population.decisions",
    )
    return {
        "available": True,
        "calendar_reference": decisions["denominator"],
        "decisions": decisions,
        "outcomes": _population_section(
            population.get("outcomes"),
            label="WindowOutcomes",
            attempted_window_count=attempted_window_count,
            field="ledger_population.outcomes",
        ),
    }


def _population_section(
    value: object,
    *,
    label: str,
    attempted_window_count: object,
    field: str = "ledger population",
) -> dict[str, object]:
    if value is None:
        return {
            "label": label,
            "recorded": "UNKNOWN",
            "attempted": attempted_window_count,
            "denominator": "UNKNOWN",
            "scheduled_missing": "UNKNOWN",
            "scheduled_complete": "UNKNOWN",
            "rows": [],
            "breakdowns": [],
        }
    summary = _mapping(value, field)
    breakdowns: list[dict[str, object]] = []
    for key, nested in summary.items():
        if not isinstance(nested, Mapping):
            continue
        nested_summary = _mapping(nested, f"{field}.{key}")
        breakdowns.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "rows": _display_rows(nested_summary, {}),
            }
        )
    return {
        "label": label,
        "recorded": _display_value(summary.get("recorded")),
        "attempted": attempted_window_count,
        "denominator": _display_value(summary.get("denominator")),
        "scheduled_missing": _display_value(summary.get("missing")),
        "scheduled_complete": _display_value(summary.get("complete")),
        "rows": _display_rows(
            {
                key: nested
                for key, nested in summary.items()
                if key not in {"denominator", "recorded", "missing", "complete"}
            },
            _POPULATION_LABELS,
        ),
        "breakdowns": breakdowns,
    }


def _case_collection_projection(
    *,
    trade_case: TradeCase | None,
    recovered_cases: Sequence[TradeCase] | None,
) -> list[dict[str, object]]:
    if recovered_cases is not None and isinstance(recovered_cases, (str, bytes)):
        raise TypeError("recovered_cases must be an array of TradeCase values")
    values = ([trade_case] if trade_case is not None else []) + list(recovered_cases or ())
    selected: list[TradeCase] = []
    by_identity: dict[str, TradeCase] = {}
    for case in values:
        prior = by_identity.get(case.identity)
        if prior is None:
            by_identity[case.identity] = case
            selected.append(case)
        elif prior != case:
            raise ValueError("recovered_cases contains different snapshots for one TradeCase")
    return [build_case_projection(case) for case in selected]


def _structure_projection(
    value: object,
    quote_index: Mapping[str, Mapping[str, object]],
    *,
    projection_state: str,
) -> dict[str, object]:
    if value is None:
        if projection_state.upper() == "UNKNOWN":
            return {
                "available": False,
                "kind": "NOT_EVALUATED",
                "message": (
                    "Four-leg structure was not evaluated because required "
                    "MarketContext evidence is UNKNOWN."
                ),
                "legs": [],
                "metrics": [],
            }
        return {
            "available": False,
            "kind": "NO_FOUR_LEG_STRUCTURE",
            "message": "No four-leg structure was selected at this observation boundary.",
            "legs": [],
            "metrics": [],
        }
    structure = _mapping(value, "snapshot.projection.structure")
    legs: list[dict[str, object]] = []
    seen: set[str] = set()
    for position, (field, label, action, option_type) in enumerate(_LEG_DEFINITIONS, start=1):
        instrument_name = _required_text(structure.get(field), f"structure.{field}")
        if instrument_name in seen:
            raise ValueError("four-leg structure contains a duplicate instrument")
        seen.add(instrument_name)
        quote = quote_index.get(instrument_name, {})
        observed_type = quote.get("option_type")
        if isinstance(observed_type, str) and observed_type.upper() != option_type:
            raise ValueError(f"{field} quote has the wrong option type")
        legs.append(
            {
                "position": position,
                "role": field,
                "label": label,
                "action": action,
                "option_type": option_type,
                "instrument_name": instrument_name,
                "quote_available": bool(quote),
                "details": _display_rows(quote, _QUOTE_DETAIL_LABELS),
            }
        )
    return {
        "available": True,
        "kind": "ASYMMETRIC_IRON_CONDOR",
        "message": "One same-session, equal-amount, USD-payoff-capped four-leg candidate.",
        "legs": legs,
        "metrics": _display_rows(structure, _STRUCTURE_METRIC_LABELS, exclude_leg_fields=True),
    }


def _quote_index(value: object) -> dict[str, Mapping[str, object]]:
    if value is None:
        return {}
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("snapshot.quotes must be an array")
    output: dict[str, Mapping[str, object]] = {}
    for index, raw_quote in enumerate(value):
        quote = _mapping(raw_quote, f"snapshot.quotes[{index}]")
        name = _required_text(
            quote.get("instrument_name"), f"snapshot.quotes[{index}].instrument_name"
        )
        if name in output:
            raise ValueError(f"snapshot contains duplicate quote: {name}")
        output[name] = quote
    return output


def _optional_display_rows(
    value: object,
    labels: Mapping[str, str],
) -> list[dict[str, str]]:
    if value is None:
        return []
    return _display_rows(_mapping(value, "optional display object"), labels)


def _display_rows(
    values: Mapping[str, object],
    labels: Mapping[str, str],
    *,
    exclude_leg_fields: bool = False,
) -> list[dict[str, str]]:
    leg_fields = {definition[0] for definition in _LEG_DEFINITIONS}
    ordered = [key for key in labels if key in values]
    ordered.extend(sorted(str(key) for key in values if str(key) not in labels))
    rows: list[dict[str, str]] = []
    for key in ordered:
        if exclude_leg_fields and key in leg_fields:
            continue
        raw = values[key]
        if isinstance(raw, Mapping) or (
            isinstance(raw, Sequence) and not isinstance(raw, (str, bytes))
        ):
            continue
        rows.append(
            {
                "key": key,
                "label": labels.get(key, key.replace("_", " ").title()),
                "value": _display_value(raw),
            }
        )
    return rows


def _projection_tone(state: str) -> str:
    return {
        "STRUCTURE_FOUND": "positive",
        "UNKNOWN": "warning",
        "NO_STRUCTURE": "neutral",
    }.get(state.upper(), "unknown")


def _runtime_tone(status: str) -> str:
    return {
        "RUNNING": "positive",
        "COMPLETE": "positive",
        "STARTING": "warning",
        "RECOVERING": "warning",
        "STOPPED": "neutral",
        "ERROR": "danger",
        "FAILED": "danger",
    }.get(status.upper(), "neutral")


def _display_value(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, str):
        return value if value else "UNKNOWN"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("snapshot contains a non-finite number")
        return str(value)
    raise TypeError(f"snapshot display value has unsupported type: {type(value).__name__}")


def _display_count(value: object, field: str) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return str(value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field} must be an object with string keys")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _text_sequence(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be an array of strings")
    output: list[str] = []
    for index, member in enumerate(value):
        output.append(_required_text(member, f"{field}[{index}]"))
    return tuple(output)


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.optimatrix-tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)
