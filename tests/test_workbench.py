from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from optimatrix.decision import MarketObservation
from optimatrix.engine import Btc0DteShortVolEngine
from optimatrix.lifecycle import (
    PositionState,
    TradeCase,
    evaluate_shadow_entry,
    evaluate_shadow_exit,
    monitor_shadow_position,
    open_trade_case,
)
from optimatrix.observation_ledger import ObservationLedger
from optimatrix.policy import BtcShortVolPolicy
from optimatrix.risk import ShadowCapacity
from optimatrix.scenarios import base_chain, current_expiry, market_context
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
        "known_at": "2026-08-12T18:00:00.250000+00:00",
        "session_id": "2026-08-13T08:00:00Z",
        "instrument_count": 40,
        "requested_book_count": 12,
        "fetched_book_count": 12,
        "warnings": ["BOUNDED_OPTION_UNIVERSE"],
        "candidate_data_readiness": {
            "status": "COMPLETE",
            "unavailable_books": [],
            "primary_rank_unresolved_books": [],
        },
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


def _recovered_case(identity_suffix: str, *, minute: int) -> TradeCase:
    opened_at = datetime(2026, 8, 12, 18, minute, tzinfo=UTC)
    return cast(
        TradeCase,
        SimpleNamespace(
            truth_layer="SHADOW_PROJECTION",
            identity=f"sha256:{identity_suffix * 64}",
            decision_window_id=f"sha256:{str(minute).zfill(2) * 32}",
            opened_at=opened_at,
            entry_deadline=opened_at + timedelta(minutes=2),
            entry_status=None,
            entry_final=False,
            entry_observed_at=None,
            entry_reason=None,
            position_id=None,
            position_state=None,
            last_observed_at=None,
            gap_observed=False,
            exit_intent=None,
            outcome=None,
        ),
    )


def _terminal_case(policy: BtcShortVolPolicy, tmp_path: Path) -> TradeCase:
    decision_at = datetime(2026, 8, 12, 18, 7, tzinfo=UTC)
    engine = Btc0DteShortVolEngine(policy=policy)
    window = next(
        item
        for item in engine.decision_windows(at=decision_at)
        if item.starts_at <= decision_at < item.ends_at
    )
    decision_quotes = base_chain(
        expiry=current_expiry(decision_at),
        observed_at=decision_at,
    )
    decision_observation = engine.capture_observation(
        quotes=decision_quotes,
        context=market_context(
            decision_at,
            book_names=tuple(quote.instrument_name for quote in decision_quotes),
        ),
    )
    assessment = engine.assess_window(
        ledger=ObservationLedger(tmp_path / "case-evidence-ledger"),
        window=window,
        observation=decision_observation,
        capacity=ShadowCapacity.empty(
            channel_id=policy.channel_id,
            market_session_id=window.market_session_id,
            known_at=window.input_deadline,
        ),
        known_at=window.input_deadline,
    )
    opened = open_trade_case(assessment.record, policy)

    def observation(
        at: datetime,
        *,
        index: Decimal | None = None,
    ) -> MarketObservation:
        quotes = base_chain(expiry=current_expiry(at), observed_at=at)
        return engine.capture_observation(
            quotes=quotes,
            context=market_context(
                at,
                index=index if index is not None else Decimal("100000"),
                book_names=tuple(quote.instrument_name for quote in quotes),
            ),
        )

    entry_at = assessment.record.known_at + timedelta(seconds=30)
    entered, _entry = evaluate_shadow_entry(
        opened,
        observation=observation(entry_at),
        policy=policy,
        known_at=entry_at,
    )
    trigger_at = entry_at + timedelta(seconds=policy.lifecycle.monitoring_cadence_seconds)
    armed, _monitor = monitor_shadow_position(
        entered,
        observation=observation(trigger_at, index=Decimal("104100")),
        policy=policy,
    )
    terminal, _exit = evaluate_shadow_exit(
        armed,
        observation=observation(
            trigger_at + timedelta(seconds=2),
            index=Decimal("104100"),
        ),
        policy=policy,
    )
    assert terminal.position_state is PositionState.TERMINAL
    return terminal


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
    assert snapshot_view["observed_at"] == "2026-08-12T18:00:00+00:00"
    assert snapshot_view["known_at"] == "2026-08-12T18:00:00.250000+00:00"
    channels = cast(Sequence[Mapping[str, object]], document["channels"])
    assert [channel["channel_id"] for channel in channels] == [
        "INVERSE_BTC_SHORT_VOL",
        "INVERSE_BTC_LONG_GAMMA",
        "INVERSE_ETH_SHORT_VOL",
        "INVERSE_ETH_LONG_GAMMA",
    ]
    assert [channel["implemented"] for channel in channels] == [True, False, False, False]
    assert [channel["status_label"] for channel in channels[1:]] == [
        "尚未授权 · 尚未定义",
        "尚未授权 · 尚未定义",
        "尚未授权 · 尚未定义",
    ]
    ledger = cast(Mapping[str, object], document["ledger"])
    stages = cast(Sequence[Mapping[str, object]], ledger["stages"])
    assert [stage["key"] for stage in stages] == [
        "DISCOVERY",
        "CONSTRUCTION",
        "ENTRY",
        "MONITORING",
        "EXIT",
        "SETTLEMENT",
        "OUTCOME",
    ]
    review = cast(Mapping[str, object], document["review"])
    challenger = cast(Mapping[str, object], review["challenger"])
    assert challenger["status"] == "NOT_YET_MEASURED"
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
    context_by_key = {row["key"]: row for row in context}
    assert context_by_key["candidate_data_readiness"]["value"] == "COMPLETE"
    assert context_by_key["unavailable_books"]["value"] == "NONE"
    assert context_by_key["history_coverage_end_ms"]["kind"] == "timestamp"
    assert "kind" not in context_by_key["history_cadence_ms"]
    window = cast(Sequence[Mapping[str, object]], document["window"])
    assert {row["key"]: row["value"] for row in window}[
        "ledger_state"
    ] == "NOT_RECORDED_BY_BOUNDED_SNAPSHOT"
    window_by_key = {row["key"]: row for row in window}
    assert window_by_key["starts_at"]["kind"] == "timestamp"
    assert window_by_key["input_deadline"]["kind"] == "timestamp"
    assert "kind" not in window_by_key["market_session_id"]
    assert "kind" not in window_by_key["decision_window_id"]
    assert document["runtime"] == {
        "available": False,
        "status": "SNAPSHOT_ONLY",
        "tone": "neutral",
        "session_id": "2026-08-13T08:00:00Z",
        "updated_at": "2026-08-12T18:00:00+00:00",
        "attempted_window_count": "UNKNOWN",
        "last_error": "NONE",
        "facts": [],
    }
    assert document["cases"] == []


def test_static_export_is_network_free_and_browser_receives_only_presentation_data(
    tmp_path: Path,
) -> None:
    exported = write_workbench(_snapshot(), tmp_path / "workbench")

    assert exported.index_path.is_file()
    assert exported.stylesheet_path.is_file()
    assert exported.script_path.is_file()
    assert exported.data_path.is_file()
    assert exported.review_data_path.is_file()
    html = exported.index_path.read_text(encoding="utf-8")
    stylesheet = exported.stylesheet_path.read_text(encoding="utf-8")
    script = exported.script_path.read_text(encoding="utf-8")
    data_script = exported.data_path.read_text(encoding="utf-8")
    review_data_script = exported.review_data_path.read_text(encoding="utf-8")
    assert "PUBLIC SHADOW - READ ONLY" in html
    assert "公开行情模拟" in html
    assert "账户持仓" in html
    assert '<script src="workbench-data.js"></script>' in html
    assert '<script src="workbench-reviews.js"></script>' in html
    assert '<meta http-equiv="refresh"' not in html
    assert "产品账" in html
    assert "复盘与进化" in html
    assert "现在处理" in html
    assert "完整四腿与收益边界" in html
    assert "Case Outcome" in html
    assert "Window Outcome" in html
    assert "每日 Session 复盘" in html
    assert "复盘不改写事实" in html
    assert "不自动晋升" in html
    assert ".ledger-grid" in stylesheet
    assert ".product-main-grid" in stylesheet
    assert ".daily-review-report" in stylesheet
    assert "@media (max-width: 1360px)" in stylesheet
    assert "gradient(" not in stylesheet
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "WebSocket" not in script
    assert "final_score" not in script
    assert "boundary_net_credit_usd" not in script
    assert "new Intl.DateTimeFormat" in script
    assert "row.kind === 'timestamp'" in script
    assert "formatTimestamp(completed.generated_at)" in script
    assert "pointByWindow" in script
    assert "断点 = UNKNOWN" in html
    assert "workbench.runtime.session_id" in script
    assert "workbench.ledger" in script
    assert "workbench.review" in script
    assert "workbench.review.completed" in script
    assert "OPTIMATRIX_COMPLETED_SESSION_REVIEWS" in script
    assert "OPTIMATRIX_COMPLETED_SESSION_REVIEWS" in review_data_script
    assert '"reviews":[]' in data_script
    assert "NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE" in script
    assert "NO_LEGAL_FOUR_LEG_STRUCTURE" in script
    assert "translateComposite(item.subtitle)" in script
    assert "RESTART_INTERRUPTED_CAUSAL_CUT" in script
    assert "RECOVERY_GAP: '恢复中断形成数据缺口'" in script
    assert "MARKET_SOURCE_BOUNDARY_STALE" in script
    assert "item.facts.policy_eligible" in script
    assert "documentSignature(window.OPTIMATRIX_WORKBENCH)" in script
    assert "window.setInterval(refreshDocumentWhenCurrent, 10000)" in script
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    app_targets = set(re.findall(r"\bbyId\('([^']+)'", script))
    assert app_targets <= html_ids
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    assert data_script.startswith(prefix)
    document = json.loads(data_script.removeprefix(prefix).removesuffix(");\n"))
    assert document["structure"]["legs"][1]["label"] == "Short Put body"
    assert document["warnings"][0]["code"] == "BOUNDED_OPTION_UNIVERSE"
    assert document["structure_population"] == {
        "legal": "UNKNOWN",
        "price_evaluable": "UNKNOWN",
        "policy_eligible": "UNKNOWN",
        "known": False,
    }
    assert document["snapshot"]["known_at"] == "2026-08-12T18:00:00.250000+00:00"


def test_snapshot_known_at_is_required_instead_of_falling_back_to_observed_at() -> None:
    snapshot = _snapshot()
    del snapshot["known_at"]

    with pytest.raises(ValueError, match=r"snapshot\.known_at"):
        build_workbench_document(snapshot)


def test_legacy_single_trade_case_is_also_the_only_case_in_the_runtime_collection() -> None:
    trade_case = _recovered_case("c", minute=37)

    document = build_workbench_document(_snapshot(), trade_case=trade_case)

    legacy_case = cast(Mapping[str, object], document["case"])
    case_views = cast(Sequence[Mapping[str, object]], document["cases"])
    assert legacy_case["trade_case_id"] == trade_case.identity
    assert [item["trade_case_id"] for item in case_views] == [trade_case.identity]


def test_case_card_projects_frozen_structure_budget_and_causal_evidence_from_case(
    policy: BtcShortVolPolicy,
    tmp_path: Path,
) -> None:
    trade_case = _terminal_case(policy, tmp_path)
    snapshot = _snapshot()
    current_projection = dict(cast(Mapping[str, object], snapshot["projection"]))
    current_structure = dict(cast(Mapping[str, object], current_projection["structure"]))
    current_structure.update(
        {
            "long_put": "CURRENT-CUT-LONG-PUT",
            "short_put": "CURRENT-CUT-SHORT-PUT",
            "short_call": "CURRENT-CUT-SHORT-CALL",
            "long_call": "CURRENT-CUT-LONG-CALL",
        }
    )
    current_projection["structure"] = current_structure
    snapshot["projection"] = current_projection

    document = build_workbench_document(snapshot, recovered_cases=(trade_case,))

    case_view = cast(Sequence[Mapping[str, object]], document["cases"])[0]
    frozen = cast(Mapping[str, object], case_view["selected_structure"])
    frozen_legs = cast(Sequence[Mapping[str, object]], frozen["legs"])
    case_structure = trade_case.selected_structure
    case_legs = cast(Mapping[str, Mapping[str, object]], case_structure["legs"])
    assert [leg["role"] for leg in frozen_legs] == [
        "long_put",
        "short_put",
        "short_call",
        "long_call",
    ]
    assert [leg["instrument_name"] for leg in frozen_legs] == [
        case_legs[role]["instrument_name"]
        for role in ("long_put", "short_put", "short_call", "long_call")
    ]
    assert "CURRENT-CUT-LONG-PUT" not in json.dumps(frozen)
    assert all(leg["candidate_id"] == trade_case.selected_structure_id for leg in frozen_legs)
    assert all(leg["expiry"] == case_structure["expiry"] for leg in frozen_legs)
    assert all(leg["option_amount"] == case_structure["option_amount"] for leg in frozen_legs)
    assert [leg["strike"] for leg in frozen_legs] == [
        case_legs[role]["strike"] for role in ("long_put", "short_put", "short_call", "long_call")
    ]

    allocation = trade_case.risk_allocation
    allocation_rows = cast(Sequence[Mapping[str, str]], case_view["risk_allocation"])
    allocation_values = {row["key"]: row["value"] for row in allocation_rows}
    allocation_by_key = {row["key"]: row for row in allocation_rows}
    assert allocation_values["allocation_id"] == trade_case.risk_allocation_id
    assert allocation_values["budget_metric"] == allocation["budget_metric"]
    assert (
        allocation_values["maximum_contractual_payoff_usd"]
        == allocation["maximum_contractual_payoff_usd"]
    )
    assert allocation_values["exit_cost_stress_usd"] == allocation["exit_cost_stress_usd"]
    assert (
        allocation_values["maximum_delivery_stress_usd"]
        == allocation["maximum_delivery_stress_usd"]
    )
    assert allocation_values["stress_reserve_usd"] == allocation["stress_reserve_usd"]
    assert allocation_values["session_used_before_usd"] == allocation["session_used_before_usd"]
    assert (
        allocation_values["session_remaining_after_usd"]
        == allocation["session_remaining_after_usd"]
    )
    assert allocation_values["concurrent_position_limit"] == str(
        allocation["concurrent_position_limit"]
    )
    assert allocation_values["expires_at"] == allocation["expires_at"]
    assert allocation_by_key["expires_at"]["kind"] == "timestamp"
    assert "kind" not in allocation_by_key["market_session_id"]
    assert allocation_values["release_condition"] == allocation["release_condition"]

    entry_rows = cast(Sequence[Mapping[str, str]], case_view["entry_evidence"])
    entry_values = {row["key"]: row["value"] for row in entry_rows}
    entry_by_key = {row["key"]: row for row in entry_rows}
    assert trade_case.entry_observation_id is not None
    assert trade_case.entry_observed_at is not None
    assert trade_case.entry_known_at is not None
    assert entry_values["decision_boundary"] == trade_case.decision_boundary.isoformat()
    assert entry_values["entry_observation_id"] == trade_case.entry_observation_id
    assert entry_values["entry_observed_at"] == trade_case.entry_observed_at.isoformat()
    assert entry_values["entry_known_at"] == trade_case.entry_known_at.isoformat()
    assert entry_by_key["decision_boundary"]["kind"] == "timestamp"
    assert entry_by_key["entry_observed_at"]["kind"] == "timestamp"
    assert "kind" not in entry_by_key["entry_observation_id"]
    assert entry_values["decision_route_evidence_id"] == trade_case.decision_route_evidence_id
    assert trade_case.entry_reunderwriting is not None
    assert (
        entry_values["entry_route_evidence_id"]
        == trade_case.entry_reunderwriting.route_evidence.identity
    )
    decision_route = cast(Mapping[str, object], case_view["decision_route_evidence"])
    entry_route = cast(Mapping[str, object], case_view["entry_route_evidence"])
    assert decision_route["available"] is True
    assert entry_route["available"] is True
    decision_route_values = {
        row["key"]: row["value"]
        for row in cast(Sequence[Mapping[str, str]], decision_route["summary"])
    }
    entry_route_values = {
        row["key"]: row["value"]
        for row in cast(Sequence[Mapping[str, str]], entry_route["summary"])
    }
    assert decision_route_values["kind"] == "COMPONENT_SYNTHETIC_ESTIMATE"
    assert decision_route_values["status"] == "EVALUABLE"
    assert entry_route_values["kind"] == "COMPONENT_SYNTHETIC_ESTIMATE"
    assert entry_route_values["status"] == "EVALUABLE"
    economics_rows = cast(Sequence[Mapping[str, str]], case_view["entry_economics"])
    economics_values = {row["key"]: row["value"] for row in economics_rows}
    entry_pricing = trade_case.entry_pricing
    assert entry_pricing is not None
    assert economics_values["native_net_credit"] == entry_pricing["native_net_credit"]
    assert economics_values["entry_native_net_credit"] == str(trade_case.entry_native_net_credit)
    reunderwriting = cast(Mapping[str, object], case_view["entry_reunderwriting"])
    assert reunderwriting["available"] is True
    summary_rows = cast(Sequence[Mapping[str, str]], reunderwriting["summary"])
    summary_values = {row["key"]: row["value"] for row in summary_rows}
    assert summary_values["entry_reunderwriting_id"] == trade_case.entry_reunderwriting.identity
    assert summary_values["status"] == "SHADOW_ATOMIC_EVALUABLE"
    decision_metric_rows = cast(
        Sequence[Mapping[str, str]],
        reunderwriting["decision_metrics"],
    )
    entry_metric_rows = cast(
        Sequence[Mapping[str, str]],
        reunderwriting["entry_metrics"],
    )
    decision_metrics = {row["key"]: row["value"] for row in decision_metric_rows}
    entry_metrics = {row["key"]: row["value"] for row in entry_metric_rows}
    assert decision_metrics["vrp_proxy_ratio"] == "1.5"
    assert entry_metrics["vrp_proxy_ratio"] == "1.5"
    assert reunderwriting["blockers"] == []
    assert "VRP 1.5 → 1.5" in str(reunderwriting["comparison"])

    assert trade_case.exit_intent is not None
    exit_rows = cast(Sequence[Mapping[str, str]], case_view["exit_intent"])
    exit_values = {row["key"]: row["value"] for row in exit_rows}
    exit_by_key = {row["key"]: row for row in exit_rows}
    assert exit_values["exit_intent_id"] == trade_case.exit_intent.identity
    assert exit_values["observation_id"] == trade_case.exit_intent.observation_id
    assert exit_values["known_at"] == trade_case.exit_intent.known_at.isoformat()
    assert exit_values["source"] == trade_case.exit_intent.source
    assert exit_values["policy_id"] == trade_case.exit_intent.policy_id
    assert exit_values["scope"] == "WHOLE_PRODUCT"
    assert exit_by_key["observed_at"]["kind"] == "timestamp"
    assert exit_by_key["known_at"]["kind"] == "timestamp"

    assert trade_case.outcome is not None
    assert trade_case.outcome.terminal_evidence_id is not None
    outcome_rows = cast(Sequence[Mapping[str, str]], case_view["outcome"])
    outcome_values = {row["key"]: row["value"] for row in outcome_rows}
    outcome_by_key = {row["key"]: row for row in outcome_rows}
    assert outcome_values["terminal_evidence_id"] == trade_case.outcome.terminal_evidence_id
    assert outcome_values["terminal_source"] == trade_case.outcome.terminal_source
    assert outcome_values["terminal_at"] == trade_case.outcome.terminal_at.isoformat()
    assert outcome_by_key["terminal_at"]["kind"] == "timestamp"
    assert "kind" not in outcome_by_key["terminal_evidence_id"]
    assert outcome_values["native_result_btc"] == str(trade_case.outcome.native_result_btc)
    assert outcome_values["boundary_reference_result_usd"] == str(
        trade_case.outcome.boundary_reference_result_usd
    )
    explanation = cast(Mapping[str, object], case_view["outcome_explanation"])
    assert explanation["available"] is True
    assert explanation["complete"] is False
    explanation_rows = cast(Sequence[Mapping[str, str]], explanation["summary"])
    explanation_values = {row["key"]: row["value"] for row in explanation_rows}
    assert explanation_values["path_id"] == trade_case.explanation_path.identity
    assert explanation_values["entry_reunderwriting_id"] == (
        trade_case.entry_reunderwriting.identity
    )
    assert explanation_values["primary_exit_reason"] == trade_case.exit_intent.reason
    assert len(cast(Sequence[object], explanation["path"])) == 4
    assert explanation["gaps"] == []
    assert len(cast(Sequence[object], explanation["counterfactuals"])) == 2
    assert len(cast(Sequence[object], explanation["alternative_outcomes"])) == len(
        trade_case.explanation_path.alternative_entry_bases
    )

    exported = write_workbench(
        snapshot,
        tmp_path / "case-evidence-workbench",
        recovered_cases=(trade_case,),
    )
    app_script = exported.script_path.read_text(encoding="utf-8")
    data_script = exported.data_path.read_text(encoding="utf-8")
    assert "四腿" in app_script
    assert "入场结果" in app_script
    assert "Decision → Entry → Outcome" in exported.index_path.read_text(encoding="utf-8")
    assert "等待官方交割补全" in app_script
    assert trade_case.selected_structure_id in data_script
    assert trade_case.entry_observation_id in data_script
    assert trade_case.outcome.terminal_evidence_id in data_script
    assert "innerHTML" not in app_script
    assert "insertAdjacentHTML" not in app_script


def test_frozen_case_text_cannot_close_the_data_script_or_become_html(tmp_path: Path) -> None:
    malicious_name = "</script><img src=x onerror=alert(1)>"
    legacy_value = cast(SimpleNamespace, _recovered_case("d", minute=52))
    legacy_value.selected_structure = {
        "candidate_id": f"sha256:{'e' * 64}",
        "expiry": "2026-08-13T08:00:00+00:00",
        "option_amount": "1",
        "legs": {
            role: {
                "instrument_name": malicious_name if role == "long_put" else f"SAFE-{role}",
                "strike": str(90_000 + position * 1_000),
                "option_type": option_type,
            }
            for position, (role, _label, _action, option_type) in enumerate(
                (
                    ("long_put", "Long Put wing", "LONG", "PUT"),
                    ("short_put", "Short Put body", "SHORT", "PUT"),
                    ("short_call", "Short Call body", "SHORT", "CALL"),
                    ("long_call", "Long Call wing", "LONG", "CALL"),
                ),
                start=1,
            )
        },
    }
    exported = write_workbench(
        _snapshot(),
        tmp_path / "escaped-case-evidence",
        recovered_cases=(cast(TradeCase, legacy_value),),
    )

    app_script = exported.script_path.read_text(encoding="utf-8")
    data_script = exported.data_path.read_text(encoding="utf-8")
    assert malicious_name not in data_script
    assert "<\\/script><img src=x onerror=alert(1)>" in data_script
    assert "innerHTML" not in app_script
    assert "insertAdjacentHTML" not in app_script


def test_runtime_population_and_every_recovered_case_are_rendered_as_supplied(
    tmp_path: Path,
) -> None:
    runtime_state = {
        "status": "RUNNING",
        "session_id": "2026-08-13T08:00:00Z",
        "started_at": "2026-08-13T08:00:01Z",
        "updated_at": "2026-08-13T12:30:03Z",
        "recovered_case_count": 2,
        "restart_count": 1,
        "last_recovery_at": "2026-08-13T11:45:00Z",
        "current_window_id": "sha256:current-window",
        "attempted_window_count": 20,
        "last_error": None,
    }
    ledger_population = {
        "decisions": {
            "denominator": 96,
            "recorded": 19,
            "missing": 77,
            "complete": False,
            "result_counts": {"ABSTAIN": 12, "CANDIDATE": 2, "UNKNOWN": 5},
            "earliest_blocker_counts": {"MARKET_CONTEXT_UNKNOWN": 5},
        },
        "outcomes": {
            "denominator": 96,
            "recorded": 3,
            "missing": 93,
            "complete": False,
            "future_path_known": 2,
            "future_path_unknown": 1,
            "continuous": 2,
            "discontinuous": 0,
            "decision_evaluable": 3,
            "strategy_population_eligible": 2,
        },
    }
    cases = (
        _recovered_case("a", minute=7),
        _recovered_case("b", minute=22),
    )

    document = build_workbench_document(
        _snapshot(),
        runtime_state=runtime_state,
        ledger_population=ledger_population,
        recovered_cases=cases,
    )

    runtime = cast(Mapping[str, object], document["runtime"])
    assert runtime["status"] == "RUNNING"
    assert runtime["tone"] == "positive"
    assert runtime["updated_at"] == "2026-08-13T12:30:03Z"
    runtime_rows = cast(Sequence[Mapping[str, str]], runtime["facts"])
    assert {row["key"]: row["value"] for row in runtime_rows}["last_error"] == "NONE"
    runtime_by_key = {row["key"]: row for row in runtime_rows}
    assert runtime_by_key["started_at"]["kind"] == "timestamp"
    assert runtime_by_key["updated_at"]["kind"] == "timestamp"
    assert "kind" not in runtime_by_key["session_id"]
    assert "kind" not in runtime_by_key["current_window_id"]
    population = cast(Mapping[str, object], document["population"])
    decisions = cast(Mapping[str, object], population["decisions"])
    outcomes = cast(Mapping[str, object], population["outcomes"])
    assert population["calendar_reference"] == "96"
    assert (decisions["recorded"], decisions["denominator"]) == ("19", "96")
    assert (outcomes["recorded"], outcomes["denominator"]) == ("3", "96")
    assert (decisions["recorded"], decisions["attempted"]) == ("19", "20")
    assert (outcomes["recorded"], outcomes["attempted"]) == ("3", "20")
    assert decisions["scheduled_missing"] == "77"
    assert decisions["scheduled_complete"] == "NO"
    decision_rows = cast(Sequence[Mapping[str, str]], decisions["rows"])
    assert not {"denominator", "recorded", "missing", "complete"} & {
        row["key"] for row in decision_rows
    }
    decision_breakdowns = cast(Sequence[Mapping[str, object]], decisions["breakdowns"])
    result_counts = cast(Sequence[Mapping[str, str]], decision_breakdowns[0]["rows"])
    assert {row["key"]: row["value"] for row in result_counts} == {
        "ABSTAIN": "12",
        "CANDIDATE": "2",
        "UNKNOWN": "5",
    }
    case_views = cast(Sequence[Mapping[str, object]], document["cases"])
    assert [item["trade_case_id"] for item in case_views] == [
        f"sha256:{'a' * 64}",
        f"sha256:{'b' * 64}",
    ]
    legacy_case = cast(Mapping[str, object], document["case"])
    assert legacy_case["available"] is False

    exported = write_workbench(
        _snapshot(),
        tmp_path / "runtime-workbench",
        runtime_state=runtime_state,
        ledger_population=ledger_population,
        recovered_cases=cases,
    )
    prefix = "window.OPTIMATRIX_WORKBENCH = Object.freeze("
    data_script = exported.data_path.read_text(encoding="utf-8")
    exported_document = json.loads(data_script.removeprefix(prefix).removesuffix(");\n"))
    assert exported_document["runtime"]["status"] == "RUNNING"
    assert len(exported_document["cases"]) == 2


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


def test_no_policy_eligible_window_is_explained_without_inventing_population_counts() -> None:
    snapshot = _snapshot()
    projection = dict(cast(Mapping[str, object], snapshot["projection"]))
    projection["state"] = "NO_STRUCTURE"
    projection["blockers"] = ["NO_POLICY_ELIGIBLE_FOUR_LEG_STRUCTURE"]
    projection["structure"] = None
    snapshot["projection"] = projection

    document = build_workbench_document(snapshot)

    assert document["structure_population"] == {
        "legal": "UNKNOWN",
        "price_evaluable": "UNKNOWN",
        "policy_eligible": "0",
        "known": False,
    }
    ledger = cast(Mapping[str, object], document["ledger"])
    rows = cast(Sequence[Mapping[str, object]], ledger["rows"])
    items = cast(Sequence[Mapping[str, object]], rows[0]["items"])
    assert items[0]["stage"] == "DISCOVERY"
    assert items[0]["facts"] == document["structure_population"]


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
