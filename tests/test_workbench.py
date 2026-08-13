from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from optimatrix.workbench import build_workbench_document, write_workbench


def _snapshot() -> dict[str, object]:
    legs = (
        ("BTC-13AUG26-93000-P", "93000", "put", "-0.05"),
        ("BTC-13AUG26-95000-P", "95000", "put", "-0.15"),
        ("BTC-13AUG26-105000-C", "105000", "call", "0.15"),
        ("BTC-13AUG26-107000-C", "107000", "call", "0.05"),
    )
    return {
        "observed_at": "2026-08-12T18:00:00+00:00",
        "session_id": "2026-08-13T08:00:00Z",
        "instrument_count": 40,
        "requested_book_count": 12,
        "fetched_book_count": 12,
        "warnings": ["BOUNDED_OPTION_UNIVERSE"],
        "window": {
            "decision_window_id": "sha256:window",
            "channel_id": "INVERSE_BTC_SHORT_VOL",
            "market_session_id": "2026-08-13T08:00:00Z",
            "schedule_policy_id": "sha256:schedule",
            "starts_at": "2026-08-12T18:00:00Z",
            "ends_at": "2026-08-12T18:15:00Z",
            "input_deadline": "2026-08-12T18:16:00Z",
            "observation_id": "sha256:observation",
            "ledger_state": "NOT_RECORDED_BY_BOUNDED_SNAPSHOT",
        },
        "context": {
            "knowledge": "KNOWN",
            "index_price": "100000",
            "forward_price": "100050",
            "trailing_realized_variance_proxy": "0.0018",
            "same_session_implied_variance_proxy": "0.0032",
            "rv_acceleration": "0.12",
            "jump_share": "0.04",
            "directional_persistence": "0.08",
            "event_state": "NONE",
            "concentrated_strike": None,
            "concentration_strength": "0.10",
            "realized_variance_method": "TRAILING_MATCHED_HORIZON_REALIZED_VARIANCE_PROXY",
            "implied_variance_method": "ATM_MARK_VARIANCE_PROXY",
            "event_state_source": "DETERMINISTIC_SCENARIO_INPUT",
            "required_history_start_ms": 1_786_535_700_000,
            "history_coverage_start_ms": 1_786_535_700_000,
            "history_coverage_end_ms": 1_786_543_200_000,
            "history_cadence_ms": 300_000,
            "market_source_min_ms": 1_786_543_200_000,
            "market_source_max_ms": 1_786_543_200_000,
            "market_received_min_ms": 1_786_543_200_050,
            "market_received_max_ms": 1_786_543_200_050,
            "event_state_known_at_ms": 1_786_543_200_000,
        },
        "projection": {
            "state": "STRUCTURE_FOUND",
            "phase": "CORE_CARRY",
            "blockers": [],
            "structure": {
                "long_put": legs[0][0],
                "short_put": legs[1][0],
                "short_call": legs[2][0],
                "long_call": legs[3][0],
                "boundary_net_credit_usd": "38.25",
                "boundary_reference_loss_usd": "161.75",
                "native_net_credit_btc": "0.0003825",
                "combo_standard_fee_btc": "0.00006",
                "maximum_contractual_payoff_cap_usd": "200",
                "net_delta": "0.00",
                "minimum_body_distance_sigma": "2.14",
                "minimum_observed_close_depth_coverage": "0.5",
            },
        },
        "quotes": [
            {
                "instrument_name": name,
                "strike": strike,
                "option_type": option_type,
                "signed_delta": delta,
                "mark_iv": "55",
                "best_bid": "0.0010",
                "best_ask": "0.0011",
                "gamma": "0.0001",
                "source_timestamp_ms": 1_786_543_200_000,
                "received_timestamp_ms": 1_786_543_200_050,
            }
            for name, strike, option_type, delta in legs
        ],
        "methodology": {
            "realized_variance_method": "TRAILING_MATCHED_HORIZON_INDEX_REALIZED_VARIANCE_PROXY",
            "delta_method": "DERIBIT_ORDER_BOOK_GREEKS",
        },
    }


def test_document_projects_one_four_leg_strategy_without_recalculating_values() -> None:
    document = build_workbench_document(_snapshot())

    assert document["boundary"] == {
        "label": "PUBLIC SHADOW - READ ONLY",
        "statements": [
            "Public market facts and counterfactual structure economics only.",
            "No order, fill, account, balance, margin, capital, or actual position is present.",
            "Displayed credit and loss are observation-boundary estimates, not real PnL.",
            "This static export creates no Shadow Case and grants no execution permission.",
        ],
    }
    snapshot_view = cast(Mapping[str, object], document["snapshot"])
    projection_view = cast(Mapping[str, object], document["projection"])
    assert snapshot_view["session_id"] == "2026-08-13T08:00:00Z"
    assert projection_view["state"] == "STRUCTURE_FOUND"
    assert projection_view["blockers"] == []
    structure = cast(Mapping[str, object], document["structure"])
    assert structure["kind"] == "ASYMMETRIC_IRON_CONDOR"
    legs = cast(Sequence[Mapping[str, object]], structure["legs"])
    assert [leg["role"] for leg in legs] == [
        "long_put",
        "short_put",
        "short_call",
        "long_call",
    ]
    assert [leg["instrument_name"] for leg in legs] == [
        "BTC-13AUG26-93000-P",
        "BTC-13AUG26-95000-P",
        "BTC-13AUG26-105000-C",
        "BTC-13AUG26-107000-C",
    ]
    structure_metrics = cast(Sequence[Mapping[str, object]], structure["metrics"])
    assert {row["key"]: row["value"] for row in structure_metrics}[
        "boundary_net_credit_usd"
    ] == "38.25"
    assert {row["key"]: row["value"] for row in structure_metrics}[
        "minimum_observed_close_depth_coverage"
    ] == "0.5"
    context = cast(Sequence[Mapping[str, object]], document["context"])
    assert {row["key"]: row["value"] for row in context}["jump_share"] == "0.04"
    assert {row["key"]: row["value"] for row in context}["knowledge"] == "KNOWN"
    window = cast(Sequence[Mapping[str, object]], document["window"])
    assert {row["key"]: row["value"] for row in window}[
        "ledger_state"
    ] == "NOT_RECORDED_BY_BOUNDED_SNAPSHOT"


def test_static_export_is_network_free_and_browser_receives_only_presentation_data(
    tmp_path: Path,
) -> None:
    exported = write_workbench(_snapshot(), tmp_path / "workbench")

    assert exported.index_path.is_file()
    assert exported.stylesheet_path.is_file()
    assert exported.script_path.is_file()
    assert exported.data_path.is_file()
    html = exported.index_path.read_text(encoding="utf-8")
    script = exported.script_path.read_text(encoding="utf-8")
    data_script = exported.data_path.read_text(encoding="utf-8")
    assert "PUBLIC SHADOW - READ ONLY" in html
    assert "No order · No fill · No account" in html
    assert '<script src="workbench-data.js"></script>' in html
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "WebSocket" not in script
    assert "final_score" not in script
    assert "boundary_net_credit_usd" not in script
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    assert data_script.startswith(prefix)
    document = json.loads(data_script.removeprefix(prefix).removesuffix(");\n"))
    assert document["structure"]["legs"][1]["label"] == "Short Put body"
    assert document["warnings"][0]["code"] == "BOUNDED_OPTION_UNIVERSE"


def test_no_structure_and_blockers_remain_truthful() -> None:
    snapshot = _snapshot()
    projection = dict(cast(Mapping[str, object], snapshot["projection"]))
    projection["state"] = "NO_STRUCTURE"
    projection["blockers"] = ["RV_ACCELERATION_TOO_HIGH", "EVENT_OR_SHOCK_IN_PROGRESS"]
    projection["structure"] = None
    snapshot["projection"] = projection

    document = build_workbench_document(snapshot)

    assert document["structure"] == {
        "available": False,
        "kind": "NO_FOUR_LEG_STRUCTURE",
        "message": "No four-leg structure was selected at this observation boundary.",
        "legs": [],
        "metrics": [],
    }
    projection_view = cast(Mapping[str, object], document["projection"])
    blockers = cast(Sequence[Mapping[str, object]], projection_view["blockers"])
    assert [item["code"] for item in blockers] == [
        "RV_ACCELERATION_TOO_HIGH",
        "EVENT_OR_SHOCK_IN_PROGRESS",
    ]


def test_unknown_market_context_is_visible_without_a_structure() -> None:
    snapshot = _snapshot()
    context = dict(cast(Mapping[str, object], snapshot["context"]))
    context["knowledge"] = "UNKNOWN"
    snapshot["context"] = context
    projection = dict(cast(Mapping[str, object], snapshot["projection"]))
    projection["state"] = "UNKNOWN"
    projection["blockers"] = [
        "REALIZED_VARIANCE_METHOD_UNKNOWN",
        "EVENT_STATE_SOURCE_UNKNOWN",
    ]
    projection["structure"] = None
    snapshot["projection"] = projection

    document = build_workbench_document(snapshot)

    projection_view = cast(Mapping[str, object], document["projection"])
    assert projection_view["state"] == "UNKNOWN"
    assert projection_view["tone"] == "warning"
    structure = cast(Mapping[str, object], document["structure"])
    assert structure["available"] is False
    assert structure["kind"] == "NOT_EVALUATED"
    context_rows = cast(Sequence[Mapping[str, object]], document["context"])
    assert {row["key"]: row["value"] for row in context_rows}["knowledge"] == "UNKNOWN"


def test_structure_requires_four_distinct_correctly_typed_legs() -> None:
    duplicate = _snapshot()
    duplicate_projection = dict(cast(Mapping[str, object], duplicate["projection"]))
    duplicate_structure = dict(cast(Mapping[str, object], duplicate_projection["structure"]))
    duplicate_structure["long_call"] = duplicate_structure["short_call"]
    duplicate_projection["structure"] = duplicate_structure
    duplicate["projection"] = duplicate_projection
    with pytest.raises(ValueError, match="duplicate instrument"):
        build_workbench_document(duplicate)

    wrong_type = _snapshot()
    wrong_quotes = [
        dict(quote) for quote in cast(Sequence[Mapping[str, object]], wrong_type["quotes"])
    ]
    wrong_quotes[0]["option_type"] = "call"
    wrong_type["quotes"] = wrong_quotes
    with pytest.raises(ValueError, match="wrong option type"):
        build_workbench_document(wrong_type)
