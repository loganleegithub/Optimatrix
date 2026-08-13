from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from optimatrix.lifecycle import TradeCase

WORKBENCH_SCHEMA_VERSION = 2
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
) -> dict[str, object]:
    """Build the complete presentation model for one public Deribit snapshot.

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
    }


def write_workbench(
    snapshot: Mapping[str, object],
    output_dir: str | Path,
    *,
    trade_case: TradeCase | None = None,
) -> WorkbenchExport:
    """Write a self-contained, network-free Workbench directory for one snapshot mapping."""

    document = build_workbench_document(snapshot, trade_case=trade_case)
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
            "message": "This bounded snapshot did not open a TradeCase.",
            "facts": [],
            "exit_intent": [],
            "outcome": [],
            "eligibility": [],
        }
    facts = {
        "truth_layer": case.truth_layer,
        "trade_case_id": case.identity,
        "decision_window_id": case.decision_window_id,
        "entry_status": case.entry_status.value if case.entry_status is not None else None,
        "entry_final": case.entry_final,
        "position_id": case.position_id,
        "position_state": case.position_state.value if case.position_state is not None else None,
        "gap_observed": case.gap_observed,
    }
    intent = (
        {
            "category": case.exit_intent.category,
            "reason": case.exit_intent.reason,
            "observed_at": case.exit_intent.observed_at.isoformat(),
            "scope": case.exit_intent.scope,
        }
        if case.exit_intent is not None
        else None
    )
    outcome = case.outcome
    outcome_values = (
        {
            "terminal_method": outcome.terminal_method.value,
            "terminal_at": outcome.terminal_at.isoformat(),
            "native_result_btc": (
                str(outcome.native_result_btc) if outcome.native_result_btc is not None else None
            ),
            "boundary_reference_result_usd": (
                str(outcome.boundary_reference_result_usd)
                if outcome.boundary_reference_result_usd is not None
                else None
            ),
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
        "message": "Counterfactual whole-product lifecycle; no order, fill, or account Position.",
        "facts": _display_rows(facts, {}),
        "exit_intent": _optional_display_rows(intent, {}),
        "outcome": _optional_display_rows(outcome_values, {}),
        "eligibility": eligibility,
    }


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
