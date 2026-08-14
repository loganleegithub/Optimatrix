from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from optimatrix.channels import CHANNELS, ChannelId
from optimatrix.lifecycle import TradeCase

WORKBENCH_SCHEMA_VERSION = 4
_ASSET_ROOT = Path(__file__).with_name("workbench_static")
_STATIC_ASSETS = ("index.html", "styles.css", "app.js")

# These are UTC instants whose presentation belongs to the browser. Identities such as
# market_session_id deliberately stay as exact backend text even when they resemble ISO timestamps.
_TIMESTAMP_ROW_KEYS = frozenset(
    {
        "decision_boundary",
        "ends_at",
        "entry_deadline",
        "entry_known_at",
        "observation_known_at",
        "entry_observed_at",
        "event_state_known_at_ms",
        "expires_at",
        "expiry",
        "history_coverage_end_ms",
        "history_coverage_start_ms",
        "input_deadline",
        "known_at",
        "last_observed_at",
        "last_recovery_at",
        "market_received_max_ms",
        "market_received_min_ms",
        "market_source_max_ms",
        "market_source_min_ms",
        "observed_at",
        "opened_at",
        "received_timestamp_ms",
        "required_history_start_ms",
        "source_timestamp_ms",
        "started_at",
        "starts_at",
        "terminal_at",
        "updated_at",
    }
)

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
    "budget_metric": "Stress budget metric",
    "option_amount": "Allocated option amount",
    "maximum_contractual_payoff_usd": "Contractual payoff cap (USD)",
    "entry_premium_native": "Boundary entry premium (BTC)",
    "combo_fee_native": "Boundary Combo fee (BTC)",
    "boundary_index_price_usd": "Boundary index price (USD)",
    "exit_cost_stress_native": "Exit-cost stress (BTC)",
    "exit_cost_stress_usd": "Boundary-valued exit-cost stress (USD)",
    "maximum_delivery_stress_usd": "Maximum delivery stress loss (USD)",
    "stress_reserve_usd": "Conservative stress reserve (USD)",
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
_ENTRY_REUNDERWRITING_LABELS = {
    "entry_reunderwriting_id": "Entry reunderwriting identity",
    "status": "Entry reunderwriting result",
    "final": "Entry reunderwriting final",
    "policy_id": "Frozen Policy identity",
    "selected_structure_id": "Frozen Candidate identity",
    "risk_allocation_id": "Frozen Shadow allocation identity",
    "market_session_id": "Entry Market Session",
    "decision_session_phase": "Decision Session phase",
    "entry_session_phase": "Entry Session phase",
    "observation_known_at": "Entry observation known at",
    "known_at": "Reunderwriting evaluated at",
    "reason": "Owning blocker",
}
_ENTRY_METRIC_LABELS = {
    "vrp_proxy_ratio": "VRP proxy ratio",
    "short_put_abs_delta": "Short Put absolute Delta",
    "short_call_abs_delta": "Short Call absolute Delta",
    "net_delta": "Four-leg net Delta",
    "put_body_distance_sigma": "Put body distance",
    "call_body_distance_sigma": "Call body distance",
    "boundary_net_credit_usd": "Boundary net credit (USD)",
    "credit_to_payoff_cap": "Credit / contractual payoff cap",
    "boundary_reference_loss_usd": "Boundary reference loss (USD)",
    "combo_fee_fraction_of_credit": "Combo fee / gross credit",
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

_CHANNEL_PRESENTATION = (
    (ChannelId.INVERSE_BTC_SHORT_VOL, "BTC", "卖波动率", "铁鹰 / Iron Condor"),
    (ChannelId.INVERSE_BTC_LONG_GAMMA, "BTC", "Long Gamma", "Gamma 结构"),
    (ChannelId.INVERSE_ETH_SHORT_VOL, "ETH", "卖波动率", "铁鹰 / Iron Condor"),
    (ChannelId.INVERSE_ETH_LONG_GAMMA, "ETH", "Long Gamma", "Gamma 结构"),
)

_LEDGER_STAGES = (
    ("DISCOVERY", "发现", "机会判断"),
    ("CONSTRUCTION", "构造", "完整四腿"),
    ("ENTRY", "待入场估价", "严格更晚估价"),
    ("MONITORING", "管理中", "持仓与风控"),
    ("EXIT", "退出意图", "冻结并等待估价"),
    ("SETTLEMENT", "待结算", "官方交割价格"),
    ("OUTCOME", "Outcome", "终局经济结果"),
)

_ELIGIBILITY_LABELS = {
    "decision_evaluable": "机会判断可评估",
    "future_path_known": "未来路径已知",
    "future_path_continuous": "未来路径连续",
    "shadow_entry_evaluable": "模拟入场可估价",
    "terminal_economics_evaluable": "终局经济结果可评估",
    "live_execution_attributable": "真实执行可归因",
    "strategy_population_eligible": "策略样本合格",
    "qualification_eligible": "Policy 晋升样本合格",
}


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
    known_at = _required_text(root.get("known_at"), "snapshot.known_at")
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
    population = _ledger_population_projection(
        ledger_population,
        attempted_window_count=runtime["attempted_window_count"],
    )
    structure = _structure_projection(
        projection.get("structure"),
        quote_index,
        projection_state=state,
    )
    structure_population = _structure_population_projection(
        projection.get("structure"),
        blockers=blockers,
    )
    case_views = _case_collection_projection(
        trade_case=trade_case,
        recovered_cases=recovered_cases,
    )
    channels = _channel_projection(case_views)
    ledger = _product_ledger_projection(
        snapshot=root,
        runtime=runtime,
        population=population,
        projection_state=state,
        projection_phase=phase,
        blockers=blockers,
        structure=structure,
        structure_population=structure_population,
        cases=case_views,
        channels=channels,
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
            "known_at": known_at,
            "instrument_count": _display_value(root.get("instrument_count")),
            "requested_book_count": _display_value(root.get("requested_book_count")),
            "fetched_book_count": _display_value(root.get("fetched_book_count")),
        },
        "runtime": runtime,
        "population": population,
        "warnings": [{"code": warning, "tone": "warning"} for warning in warnings],
        "window": _display_rows(window, _WINDOW_LABELS),
        "projection": {
            "state": state,
            "phase": phase,
            "tone": _projection_tone(state),
            "blockers": [{"code": blocker, "tone": "danger"} for blocker in blockers],
        },
        "structure": structure,
        "structure_population": structure_population,
        "context": _display_rows(context, _CONTEXT_LABELS),
        "methodology": _optional_display_rows(root.get("methodology"), {}),
        "case": build_case_projection(trade_case),
        "cases": case_views,
        "channels": channels,
        "ledger": ledger,
        "review": _review_projection(
            population=population,
            cases=case_views,
            ledger=ledger,
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
            "channel_id": None,
            "entry_status": "UNKNOWN",
            "position_state": "UNKNOWN",
            "message": "This bounded snapshot did not open a TradeCase.",
            "facts": [],
            "selected_structure": _empty_case_structure_projection(),
            "risk_allocation": [],
            "entry_evidence": [],
            "entry_reunderwriting": _empty_entry_reunderwriting_projection(),
            "entry_economics": [],
            "exit_intent": [],
            "outcome": [],
            "eligibility": [],
            "display": None,
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
    entry_reunderwriting = _entry_reunderwriting_projection(case)
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
                "label": _ELIGIBILITY_LABELS[name],
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
        "channel_id": _enum_text(getattr(case, "channel_id", ChannelId.INVERSE_BTC_SHORT_VOL)),
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
        "entry_reunderwriting": entry_reunderwriting,
        "entry_economics": _display_rows(entry_economics, _ENTRY_ECONOMICS_LABELS),
        "exit_intent": _optional_display_rows(intent, _EXIT_INTENT_LABELS),
        "outcome": _optional_display_rows(outcome_values, _OUTCOME_LABELS),
        "eligibility": eligibility,
        "display": _case_display_projection(
            case,
            selected_structure=selected_structure,
            risk_allocation=risk_allocation,
            outcome_values=outcome_values,
        ),
    }


def _case_display_projection(
    case: TradeCase,
    *,
    selected_structure: Mapping[str, object],
    risk_allocation: Mapping[str, object] | None,
    outcome_values: Mapping[str, object] | None,
) -> dict[str, object]:
    stage, stage_label, tone = _case_stage(case)
    frozen_structure = _case_mapping(
        case,
        "selected_structure",
        "TradeCase.selected_structure",
    )
    legs = selected_structure.get("legs")
    leg_values = list(legs) if isinstance(legs, Sequence) else []
    strikes = [str(leg.get("strike", "UNKNOWN")) for leg in leg_values if isinstance(leg, Mapping)]
    structure_line = " / ".join(strikes) if len(strikes) == 4 else "完整四腿已冻结"
    allocation_result = (
        _display_loose(risk_allocation.get("result")) if risk_allocation is not None else "UNKNOWN"
    )
    entry_status = (
        case.entry_status.value if case.entry_status is not None else "等待严格更晚入场估价"
    )
    outcome_method = (
        _display_loose(outcome_values.get("terminal_method"))
        if outcome_values is not None
        else None
    )
    exit_reason = case.exit_intent.reason if case.exit_intent is not None else None
    terminal_at = outcome_values.get("terminal_at") if outcome_values is not None else None
    native_result = outcome_values.get("native_result_btc") if outcome_values is not None else None

    responsibility = {
        "ENTRY": "等待严格更晚的完整四腿入场估价",
        "MONITORING": "持续监控完整组合,首次已知触发将冻结退出意图",
        "EXIT": "退出意图已冻结;等待严格更晚的完整组合估价或到期交割",
        "OUTCOME": "终局经济结果已冻结,可进入复盘",
    }.get(stage, "保持产品责任")
    if case.gap_observed and stage != "OUTCOME":
        responsibility = f"数据存在 Gap;{responsibility}"

    timeline = [
        {
            "key": "DISCOVERY",
            "label": "发现",
            "state": "DONE",
            "at": _optional_isoformat(getattr(case, "decision_boundary", None)),
        },
        {
            "key": "CONSTRUCTION",
            "label": "构造",
            "state": "DONE",
            "at": case.opened_at.isoformat(),
        },
        {
            "key": "ALLOCATION",
            "label": "冻结研究预算",
            "state": "DONE" if allocation_result == "AVAILABLE" else "UNKNOWN",
            "at": (
                _display_loose(risk_allocation.get("known_at"))
                if risk_allocation is not None
                else None
            ),
        },
        {
            "key": "ENTRY",
            "label": "入场估价",
            "state": (
                "DONE"
                if case.entry_status is not None and case.entry_final
                else "CURRENT"
                if stage == "ENTRY"
                else "UNKNOWN"
            ),
            "at": _optional_isoformat(getattr(case, "entry_known_at", None)),
        },
        {
            "key": "MONITORING",
            "label": "持续管理",
            "state": (
                "CURRENT"
                if stage == "MONITORING"
                else "DONE"
                if stage in {"EXIT", "OUTCOME"}
                else "PENDING"
            ),
            "at": _optional_isoformat(case.last_observed_at),
        },
        {
            "key": "EXIT",
            "label": "退出意图",
            "state": (
                "CURRENT"
                if stage == "EXIT"
                else "DONE"
                if stage == "OUTCOME" and case.exit_intent is not None
                else "PENDING"
            ),
            "at": (case.exit_intent.known_at.isoformat() if case.exit_intent is not None else None),
        },
        {
            "key": "OUTCOME",
            "label": "Outcome",
            "state": "DONE" if stage == "OUTCOME" else "PENDING",
            "at": _display_loose(terminal_at) if terminal_at is not None else None,
        },
    ]

    return {
        "short_id": case.identity.split(":", 1)[-1][:12].upper(),
        "stage": stage,
        "stage_label": stage_label,
        "tone": tone,
        "priority": 0 if stage == "EXIT" else 1 if stage == "MONITORING" else 2,
        "structure_line": structure_line,
        "option_amount": (
            _display_loose(frozen_structure.get("option_amount"))
            if frozen_structure is not None
            else "UNKNOWN"
        ),
        "expiry": (
            _display_loose(frozen_structure.get("expiry"))
            if frozen_structure is not None
            else "UNKNOWN"
        ),
        "opened_at": case.opened_at.isoformat(),
        "entry_deadline": case.entry_deadline.isoformat(),
        "entry_status": entry_status,
        "position_state": (
            case.position_state.value if case.position_state is not None else "NO_POSITION"
        ),
        "allocation_result": allocation_result,
        "exit_reason": exit_reason,
        "outcome_method": outcome_method,
        "native_result_btc": _display_loose(native_result) if native_result is not None else None,
        "terminal_at": _display_loose(terminal_at) if terminal_at is not None else None,
        "gap_observed": case.gap_observed,
        "responsibility": responsibility,
        "timeline": timeline,
    }


def _empty_entry_reunderwriting_projection() -> dict[str, object]:
    return {
        "available": False,
        "comparison": None,
        "entry_vrp": None,
        "summary": [],
        "decision_metrics": [],
        "entry_metrics": [],
        "blockers": [],
    }


def _entry_reunderwriting_projection(case: TradeCase) -> dict[str, object]:
    result = getattr(case, "entry_reunderwriting", None)
    if result is None:
        return _empty_entry_reunderwriting_projection()
    summary = {
        "entry_reunderwriting_id": result.identity,
        "status": result.status.value,
        "final": result.final,
        "policy_id": result.policy_id,
        "selected_structure_id": result.selected_structure_id,
        "risk_allocation_id": result.risk_allocation_id,
        "market_session_id": result.market_session_id,
        "decision_session_phase": result.decision_session_phase.value,
        "entry_session_phase": (
            result.entry_session_phase.value if result.entry_session_phase is not None else None
        ),
        "observation_known_at": (
            result.observation_known_at.isoformat()
            if result.observation_known_at is not None
            else None
        ),
        "known_at": result.known_at.isoformat(),
        "reason": result.reason,
    }
    blocker_groups = (
        ("EVIDENCE", result.evidence_blockers),
        ("ENVIRONMENT", result.environment_blockers),
        ("STRUCTURE", result.structure_blockers),
        ("ECONOMICS", result.economics_blockers),
        ("ALLOCATION", result.allocation_blockers),
        ("ROUTE", result.route_blockers),
    )
    return {
        "available": True,
        "comparison": (
            "VRP "
            f"{_display_loose(result.decision_metrics.vrp_proxy_ratio)} → "
            f"{_display_loose(result.entry_metrics.vrp_proxy_ratio)}, 净 Delta "
            f"{_display_loose(result.decision_metrics.net_delta)} → "
            f"{_display_loose(result.entry_metrics.net_delta)}, 边界净权利金 "
            f"{_display_loose(result.decision_metrics.boundary_net_credit_usd)} → "
            f"{_display_loose(result.entry_metrics.boundary_net_credit_usd)} USD"
        ),
        "entry_vrp": _display_loose(result.entry_metrics.vrp_proxy_ratio),
        "summary": _display_rows(summary, _ENTRY_REUNDERWRITING_LABELS),
        "decision_metrics": _display_rows(
            result.decision_metrics.as_object(),
            _ENTRY_METRIC_LABELS,
        ),
        "entry_metrics": _display_rows(
            result.entry_metrics.as_object(),
            _ENTRY_METRIC_LABELS,
        ),
        "blockers": [
            {"dimension": dimension, "code": blocker, "tone": "danger"}
            for dimension, blockers in blocker_groups
            for blocker in blockers
        ],
    }


def _case_stage(case: TradeCase) -> tuple[str, str, str]:
    state = case.position_state.value if case.position_state is not None else None
    if state == "TERMINAL" or case.outcome is not None:
        return "OUTCOME", "Outcome", "positive"
    if state == "EXIT_INTENT_FROZEN" or case.exit_intent is not None:
        return "EXIT", "退出意图", "danger"
    if state == "MONITORING":
        return "MONITORING", "管理中", "positive"
    return "ENTRY", "待入场估价", "warning"


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


def _channel_projection(cases: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    counts = {channel_id.value: 0 for channel_id, *_ in _CHANNEL_PRESENTATION}
    unresolved = {channel_id.value: 0 for channel_id, *_ in _CHANNEL_PRESENTATION}
    for case in cases:
        channel_id = str(case.get("channel_id") or ChannelId.INVERSE_BTC_SHORT_VOL.value)
        if channel_id in counts:
            counts[channel_id] += 1
            display = case.get("display")
            if isinstance(display, Mapping) and display.get("stage") != "OUTCOME":
                unresolved[channel_id] += 1

    output: list[dict[str, object]] = []
    for channel_id, underlying, strategy, product_name in _CHANNEL_PRESENTATION:
        descriptor = CHANNELS[channel_id]
        output.append(
            {
                "channel_id": channel_id.value,
                "underlying": underlying,
                "strategy": strategy,
                "product_name": product_name,
                "implemented": descriptor.implemented,
                "implementation_name": descriptor.implementation_name,
                "status": "PUBLIC_SHADOW" if descriptor.implemented else "UNAUTHORIZED",
                "status_label": (
                    "公开行情模拟" if descriptor.implemented else "尚未授权 · 尚未定义"
                ),
                "case_count": counts[channel_id.value] if descriptor.implemented else None,
                "unresolved_count": (
                    unresolved[channel_id.value] if descriptor.implemented else None
                ),
            }
        )
    return output


def _product_ledger_projection(
    *,
    snapshot: Mapping[str, object],
    runtime: Mapping[str, object],
    population: Mapping[str, object],
    projection_state: str,
    projection_phase: str,
    blockers: Sequence[str],
    structure: Mapping[str, object],
    structure_population: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
    channels: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    stages = [
        {"key": key, "label": label, "description": description}
        for key, label, description in _LEDGER_STAGES
    ]
    active_channel_id = ChannelId.INVERSE_BTC_SHORT_VOL.value
    product_rows: list[dict[str, object]] = []
    for channel in channels:
        channel_id = str(channel["channel_id"])
        items: list[dict[str, object]] = []
        if channel["implemented"]:
            current_window_stage = "DISCOVERY"
            current_window_responsibility = (
                blockers[0]
                if blockers
                else "完整四腿候选已形成;等待业务链后续事实"
                if structure.get("available")
                else "本窗口尚无可展示结构"
            )
            items.append(
                {
                    "id": "CURRENT_WINDOW",
                    "kind": "WINDOW",
                    "stage": current_window_stage,
                    "title": "当前市场窗口",
                    "subtitle": f"{projection_state} · {projection_phase}",
                    "time": _display_loose(snapshot.get("known_at")),
                    "tone": _projection_tone(projection_state),
                    "responsibility": current_window_responsibility,
                    "facts": structure_population,
                    "case_id": None,
                }
            )
            if structure.get("available"):
                items.append(
                    {
                        "id": "CURRENT_STRUCTURE",
                        "kind": "STRUCTURE",
                        "stage": "CONSTRUCTION",
                        "title": "完整四腿候选",
                        "subtitle": _current_structure_line(structure),
                        "time": _display_loose(snapshot.get("known_at")),
                        "tone": "positive",
                        "responsibility": "完整结构已联合选出;不拆分为两侧独立交易",
                        "case_id": None,
                    }
                )
            for case in cases:
                if case.get("channel_id") != channel_id:
                    continue
                display = case.get("display")
                if not isinstance(display, Mapping):
                    continue
                items.append(
                    {
                        "id": display.get("short_id"),
                        "kind": "CASE",
                        "stage": display.get("stage"),
                        "title": f"Case {display.get('short_id')}",
                        "subtitle": display.get("structure_line"),
                        "time": display.get("opened_at"),
                        "tone": display.get("tone"),
                        "responsibility": display.get("responsibility"),
                        "case_id": case.get("trade_case_id"),
                        "entry_deadline": display.get("entry_deadline"),
                        "expiry": display.get("expiry"),
                        "gap_observed": display.get("gap_observed"),
                    }
                )
        product_rows.append({"channel": channel, "items": items})

    attention: list[dict[str, object]] = []
    for case in cases:
        display = case.get("display")
        if not isinstance(display, Mapping) or display.get("stage") == "OUTCOME":
            continue
        attention.append(
            {
                "case_id": case.get("trade_case_id"),
                "short_id": display.get("short_id"),
                "stage": display.get("stage"),
                "stage_label": display.get("stage_label"),
                "tone": display.get("tone"),
                "priority": display.get("priority"),
                "structure_line": display.get("structure_line"),
                "responsibility": display.get("responsibility"),
                "deadline": (
                    display.get("entry_deadline")
                    if display.get("stage") == "ENTRY"
                    else display.get("expiry")
                ),
            }
        )
    attention.sort(key=lambda item: (str(item["priority"]), str(item["deadline"])))

    decisions = _mapping(population.get("decisions"), "population.decisions")
    outcomes = _mapping(population.get("outcomes"), "population.outcomes")
    return {
        "active_channel_id": active_channel_id,
        "stages": stages,
        "rows": product_rows,
        "attention": attention,
        "summary": {
            "recorded_windows": decisions.get("recorded"),
            "attempted_windows": decisions.get("attempted"),
            "session_denominator": decisions.get("denominator"),
            "recorded_window_outcomes": outcomes.get("recorded"),
            "case_count": len(cases),
            "unresolved_count": len(attention),
        },
        "market_strip": {
            "underlying": "BTC",
            "index_price": _display_loose(
                next(
                    (
                        row.get("value")
                        for row in _display_rows(
                            _mapping(snapshot.get("context"), "snapshot.context"),
                            _CONTEXT_LABELS,
                        )
                        if row.get("key") == "index_price"
                    ),
                    "UNKNOWN",
                )
            ),
            "phase": projection_phase,
            "runtime_status": runtime.get("status"),
            "updated_at": runtime.get("updated_at"),
            "next_boundary": next(
                (
                    row.get("value")
                    for row in _display_rows(
                        _mapping(snapshot.get("window"), "snapshot.window"),
                        _WINDOW_LABELS,
                    )
                    if row.get("key") == "input_deadline"
                ),
                "UNKNOWN",
            ),
        },
    }


def _current_structure_line(structure: Mapping[str, object]) -> str:
    legs = structure.get("legs")
    if not isinstance(legs, Sequence) or isinstance(legs, (str, bytes)):
        return "完整四腿候选"
    names = [
        str(leg.get("instrument_name"))
        for leg in legs
        if isinstance(leg, Mapping) and leg.get("instrument_name")
    ]
    return " / ".join(names) if len(names) == 4 else "完整四腿候选"


def _structure_population_projection(
    value: object,
    *,
    blockers: Sequence[str],
) -> dict[str, object]:
    if value is not None:
        structure = _mapping(value, "snapshot.projection.structure")
        counts = structure.get("population_counts")
        if isinstance(counts, Mapping):
            return {
                "legal": _display_value(counts.get("legal")),
                "price_evaluable": _display_value(counts.get("price_evaluable")),
                "policy_eligible": _display_value(counts.get("policy_eligible")),
                "known": True,
            }
    return {
        "legal": "UNKNOWN",
        "price_evaluable": "UNKNOWN",
        "policy_eligible": "0"
        if "NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE" in blockers
        else "UNKNOWN",
        "known": False,
    }


def _review_projection(
    *,
    population: Mapping[str, object],
    cases: Sequence[Mapping[str, object]],
    ledger: Mapping[str, object],
) -> dict[str, object]:
    decisions = _mapping(population.get("decisions"), "population.decisions")
    outcomes = _mapping(population.get("outcomes"), "population.outcomes")
    breakdowns = decisions.get("breakdowns")
    result_counts: dict[str, str] = {}
    if isinstance(breakdowns, Sequence):
        for breakdown in breakdowns:
            if not isinstance(breakdown, Mapping) or breakdown.get("key") != "result_counts":
                continue
            rows = breakdown.get("rows")
            if isinstance(rows, Sequence):
                result_counts = {
                    str(row.get("key")): str(row.get("value"))
                    for row in rows
                    if isinstance(row, Mapping)
                }

    flow = [
        {"key": "UNKNOWN", "label": "未知", "count": result_counts.get("UNKNOWN", "0")},
        {"key": "ABSTAIN", "label": "不做", "count": result_counts.get("ABSTAIN", "0")},
        {"key": "REVIEW", "label": "复核", "count": result_counts.get("REVIEW", "0")},
        {
            "key": "CANDIDATE",
            "label": "候选",
            "count": result_counts.get("CANDIDATE", "0"),
        },
        {"key": "CASE", "label": "形成 Case", "count": str(len(cases))},
        {
            "key": "OUTCOME",
            "label": "Case Outcome",
            "count": str(sum(bool(case.get("outcome")) for case in cases)),
        },
    ]
    traces = []
    for case in cases:
        display = case.get("display")
        if isinstance(display, Mapping):
            traces.append(
                {
                    "case_id": case.get("trade_case_id"),
                    "short_id": display.get("short_id"),
                    "stage": display.get("stage"),
                    "tone": display.get("tone"),
                    "timeline": display.get("timeline"),
                    "outcome_method": display.get("outcome_method"),
                    "native_result_btc": display.get("native_result_btc"),
                }
            )

    case_outcomes = {
        "population": str(sum(bool(case.get("outcome")) for case in cases)),
        "whole_product_exit": str(_case_outcome_method_counts(cases).get("WHOLE_PRODUCT_EXIT", 0)),
        "contract_settlement": str(
            _case_outcome_method_counts(cases).get("CONTRACT_SETTLEMENT", 0)
        ),
        "no_position": str(_case_outcome_method_counts(cases).get("NO_POSITION", 0)),
    }
    outcome_rows_value = outcomes.get("rows", [])
    outcome_rows = (
        outcome_rows_value
        if isinstance(outcome_rows_value, Sequence)
        and not isinstance(outcome_rows_value, (str, bytes))
        else []
    )
    window_outcomes = {
        "recorded": outcomes.get("recorded"),
        "denominator": outcomes.get("denominator"),
        "future_path_known": next(
            (
                row.get("value")
                for row in outcome_rows
                if isinstance(row, Mapping) and row.get("key") == "future_path_known"
            ),
            "UNKNOWN",
        ),
        "future_path_continuous": next(
            (
                row.get("value")
                for row in outcome_rows
                if isinstance(row, Mapping) and row.get("key") == "continuous"
            ),
            "UNKNOWN",
        ),
    }
    return {
        "flow": flow,
        "traces": traces,
        "case_outcomes": case_outcomes,
        "window_outcomes": window_outcomes,
        "eligibility": _aggregate_case_eligibility(cases),
        "challenger": {
            "status": "NOT_YET_MEASURED",
            "status_label": "尚未测量",
            "reason": "D1 离线 AI Challenger 尚未授权;当前没有可比较的冻结 Challenger Policy 与合格前向样本。",
            "arms": [
                {"key": "BASE", "label": "Base", "available": True},
                {"key": "CHALLENGER", "label": "Challenger", "available": False},
                {"key": "UNFILTERED_CONDOR", "label": "无筛选铁鹰", "available": False},
                {"key": "NO_TRADE", "label": "不交易", "available": False},
            ],
            "metrics": [
                "尾部损失",
                "最差单日损失",
                "ES / CVaR",
                "最大回撤",
                "手续费后净收益",
                "错失有效机会",
                "覆盖率与稳定性",
            ],
            "human_gate": "AI 只能提出建议;新 Policy 必须由交易负责人在另一个授权任务中批准。",
        },
        "summary": ledger.get("summary"),
    }


def _case_outcome_method_counts(
    cases: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        rows = case.get("outcome")
        if not isinstance(rows, Sequence):
            continue
        method = next(
            (
                str(row.get("value"))
                for row in rows
                if isinstance(row, Mapping) and row.get("key") == "terminal_method"
            ),
            None,
        )
        if method is not None:
            counts[method] = counts.get(method, 0) + 1
    return counts


def _aggregate_case_eligibility(
    cases: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for key, label in _ELIGIBILITY_LABELS.items():
        eligibility_values = [case.get("eligibility", []) for case in cases]
        values = [
            item
            for raw_values in eligibility_values
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes))
            for item in raw_values
            if isinstance(item, Mapping) and item.get("key") == key
        ]
        output.append(
            {
                "key": key,
                "label": label,
                "yes": sum(item.get("value") == "YES" for item in values),
                "no": sum(item.get("value") == "NO" for item in values),
                "unknown": sum(item.get("value") == "UNKNOWN" for item in values),
                "population": len(values),
            }
        )
    return output


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
        row = {
            "key": key,
            "label": labels.get(key, key.replace("_", " ").title()),
            "value": _display_value(raw),
        }
        if key in _TIMESTAMP_ROW_KEYS:
            row["kind"] = "timestamp"
        rows.append(row)
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


def _enum_text(value: object) -> str | None:
    text = getattr(value, "value", value)
    return text if isinstance(text, str) and text else None


def _display_loose(value: object) -> str:
    if value is None:
        return "UNKNOWN"
    text = getattr(value, "value", value)
    if isinstance(text, str):
        return text or "UNKNOWN"
    if isinstance(text, bool):
        return "YES" if text else "NO"
    if isinstance(text, (int, float)):
        return str(text)
    isoformat = getattr(text, "isoformat", None)
    if callable(isoformat):
        result = isoformat()
        if isinstance(result, str):
            return result
    return str(text)


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
