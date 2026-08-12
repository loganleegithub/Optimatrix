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
        "public_combo_id": None,
        "warnings": ["PUBLIC_COMBO_DIAGNOSTIC_UNAVAILABLE"],
        "funnel": {
            "unit_identity": "sha256:funnel",
            "session_id": "2026-08-13T08:00:00Z",
            "decision_window_identity": "2026-08-13T08:00:00Z:600",
            "policy_identity": "sha256:policy",
            "current_node": "ENTRY_ATTEMPT_SELECTED",
            "primary_blocker": None,
            "stages": [
                {
                    "name": name,
                    "status": "PASSED",
                    "denominator": 1,
                    "numerator": 1,
                    "blockers": [],
                }
                for name in (
                    "APPLICABLE_SESSION_DECISION",
                    "MARKET_CONTEXT_KNOWN",
                    "VRP_THETA_QUALIFIED",
                    "GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE",
                    "TWO_SIDED_STRUCTURE_EVALUABLE",
                    "ENTRY_ROUTE_EVALUABLE",
                    "ENTRY_ATTEMPT_SELECTED",
                )
            ]
            + [
                {
                    "name": "DECISION_CASE_OPENED",
                    "status": "NOT_REACHED",
                    "denominator": 1,
                    "numerator": 0,
                    "blockers": [],
                },
                {
                    "name": "ENTRY_RESULT_KNOWN",
                    "status": "NOT_REACHED",
                    "denominator": 0,
                    "numerator": 0,
                    "blockers": [],
                },
                {
                    "name": "DECISION_CASE_OUTCOME_KNOWN",
                    "status": "NOT_REACHED",
                    "denominator": 0,
                    "numerator": 0,
                    "blockers": [],
                },
            ],
        },
        "context": {
            "index_price": "100000",
            "forward_price": "100050",
            "physical_variance_forecast": "0.0018",
            "same_session_implied_variance": "0.0032",
            "rv_acceleration": "0.12",
            "jump_share": "0.04",
            "directional_persistence": "0.08",
            "event_state": "NONE",
            "breakout_state": "CALM",
            "concentrated_strike": None,
            "concentration_strength": "0.10",
        },
        "decision": {
            "decision_identity": "sha256:decision",
            "state": "CANDIDATE",
            "phase": "CORE_CARRY",
            "blockers": [],
            "score": {
                "vrp_ratio": "1.77",
                "theta_capture_proxy": "0.61",
                "premium_edge": "0.72",
                "gamma_safety": "0.81",
                "range_quality": "0.76",
                "execution_quality": "0.84",
                "final_score": "0.78",
            },
            "structure": {
                "long_put": legs[0][0],
                "short_put": legs[1][0],
                "short_call": legs[2][0],
                "long_call": legs[3][0],
                "combined_net_credit_usd": "38.25",
                "entry_boundary_max_loss_usd": "161.75",
                "net_delta": "0.00",
                "minimum_body_distance_sigma": "2.14",
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
            "physical_variance_method": "TRAILING_MATCHED_HORIZON_INDEX_REALIZED_VARIANCE_PROXY",
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
    decision_view = cast(Mapping[str, object], document["decision"])
    assert snapshot_view["session_id"] == "2026-08-13T08:00:00Z"
    assert decision_view["state"] == "CANDIDATE"
    assert decision_view["blockers"] == []
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
        "combined_net_credit_usd"
    ] == "38.25"
    score = cast(Sequence[Mapping[str, object]], document["score"])
    context = cast(Sequence[Mapping[str, object]], document["context"])
    assert {row["key"]: row["value"] for row in score}["final_score"] == "0.78"
    assert {row["key"]: row["value"] for row in context}["jump_share"] == "0.04"
    funnel = cast(Sequence[Mapping[str, object]], document["funnel"])
    assert {row["key"]: row["value"] for row in funnel}[
        "TWO_SIDED_STRUCTURE_EVALUABLE"
    ] == "PASSED · 1/1"


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
    assert "combined_net_credit_usd" not in script
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    assert data_script.startswith(prefix)
    document = json.loads(data_script.removeprefix(prefix).removesuffix(");\n"))
    assert document["structure"]["legs"][1]["label"] == "Short Put body"
    assert document["warnings"][0]["code"] == "PUBLIC_COMBO_DIAGNOSTIC_UNAVAILABLE"


def test_no_structure_and_blockers_remain_truthful() -> None:
    snapshot = _snapshot()
    decision = dict(cast(Mapping[str, object], snapshot["decision"]))
    decision["state"] = "ABSTAIN"
    decision["blockers"] = ["GAMMA_SAFETY_BELOW_MINIMUM", "EVENT_STATE_BLOCKED"]
    decision["score"] = None
    decision["structure"] = None
    snapshot["decision"] = decision

    document = build_workbench_document(snapshot)

    assert document["structure"] == {
        "available": False,
        "kind": "NO_FOUR_LEG_STRUCTURE",
        "message": "No four-leg structure was selected at this observation boundary.",
        "legs": [],
        "metrics": [],
    }
    assert document["score"] == []
    decision_view = cast(Mapping[str, object], document["decision"])
    blockers = cast(Sequence[Mapping[str, object]], decision_view["blockers"])
    assert [item["code"] for item in blockers] == [
        "GAMMA_SAFETY_BELOW_MINIMUM",
        "EVENT_STATE_BLOCKED",
    ]


def test_structure_requires_four_distinct_correctly_typed_legs() -> None:
    duplicate = _snapshot()
    duplicate_decision = dict(cast(Mapping[str, object], duplicate["decision"]))
    duplicate_structure = dict(cast(Mapping[str, object], duplicate_decision["structure"]))
    duplicate_structure["long_call"] = duplicate_structure["short_call"]
    duplicate_decision["structure"] = duplicate_structure
    duplicate["decision"] = duplicate_decision
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
