from __future__ import annotations

import http.client
import inspect
import json
import socket
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import radar_runtime.workbench as workbench_module
from market_monitor import TimeInterval
from options_domain import INVERSE_BTC
from radar_runtime.runtime import (
    CausalCause,
    CausalCommit,
    FactBoundary,
    FailureScope,
    RadarReducer,
)
from radar_runtime.workbench import (
    CSS,
    EMPTY_PANEL_LABEL,
    HTML,
    JS,
    SIMULATION_LABEL,
    DataState,
    LoopbackWorkbenchServer,
    PanelState,
    ServicePhase,
    ServiceStatus,
    SnapshotStore,
    WorkbenchPublisher,
    WorkbenchRequestHandler,
    initial_workbench_document,
    panel_state,
    zero_anomaly_claim,
    zero_candidate_claim,
)
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.detector import DetectorState
from short_vol_underwriting import FactBoundary as DownstreamFactBoundary
from short_vol_underwriting.constants import (
    INVERSE_BTC_POSITION_POLICY_IDENTITY,
    INVERSE_BTC_RADAR_POLICY_IDENTITY,
    INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
)
from short_vol_underwriting.evidence import RuntimeBindings, ShadowStateStore
from short_vol_underwriting.policy import PolicyChain, load_policy_chain

ROOT = Path(__file__).resolve().parents[1]


def _policies() -> PolicyChain:
    return load_policy_chain(
        radar_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-radar.json",
        underwriting_path=(ROOT / "policies/short-vol-inverse-btc-public-shadow-underwriting.json"),
        position_path=ROOT / "policies/short-vol-inverse-btc-public-shadow-position.json",
        radar_identity=INVERSE_BTC_RADAR_POLICY_IDENTITY,
        underwriting_identity=INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        position_identity=INVERSE_BTC_POSITION_POLICY_IDENTITY,
    )


def _bindings() -> RuntimeBindings:
    return RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity="sha256:" + "c" * 64,
        underwriting_policy_identity="sha256:" + "d" * 64,
        position_policy_identity="sha256:" + "e" * 64,
    )


def _request(
    server: LoopbackWorkbenchServer,
    method: str,
    path: str,
) -> tuple[int, dict[str, str], bytes]:
    host, port = server.address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def test_empty_panel_is_not_a_business_zero_and_zero_denominators_are_null() -> None:
    assert panel_state(()) is PanelState.EMPTY_NO_SETTLED_OBJECT
    assert panel_state((object(),)) is PanelState.HAS_SETTLED_OBJECTS

    anomaly = zero_anomaly_claim(
        active_anomaly_count=0,
        monitor_denominator=None,
        monitor_complete=False,
    )
    candidate = zero_candidate_claim(
        candidate_count=0,
        underwriting_evaluable_denominator=0,
    )

    assert anomaly.state.value == "UNKNOWN"
    assert anomaly.value is None
    assert anomaly.denominator is None
    assert candidate.state.value == "UNKNOWN"
    assert candidate.value is None
    assert candidate.denominator == 0
    assert "UNKNOWN" in anomaly.explanation
    assert "UNKNOWN" in candidate.explanation


def test_business_zero_requires_exact_known_positive_denominators() -> None:
    anomaly = zero_anomaly_claim(
        active_anomaly_count=0,
        monitor_denominator=12,
        monitor_complete=True,
    )
    candidate = zero_candidate_claim(
        candidate_count=0,
        underwriting_evaluable_denominator=4,
    )
    positive = zero_anomaly_claim(
        active_anomaly_count=2,
        monitor_denominator=None,
        monitor_complete=False,
    )

    assert anomaly.state.value == "PROVEN_ZERO" and anomaly.value == 0
    assert candidate.state.value == "PROVEN_ZERO" and candidate.value == 0
    assert positive.state.value == "NOT_ZERO" and positive.value == 2


def test_radar_projection_binds_atomic_state_to_active_episode_identity() -> None:
    episode_identity = "sha256:" + "9" * 64
    tracker = SimpleNamespace(
        episode_id=episode_identity,
        detector_state=DetectorState.ANOMALY_ACTIVE,
    )
    reducer = cast(
        RadarReducer,
        SimpleNamespace(
            options={
                "BTC-TEST": SimpleNamespace(
                    expiration_timestamp_ms=10_000,
                    option_type=SimpleNamespace(value="call"),
                    strike=100,
                    product=INVERSE_BTC,
                )
            },
            results={
                "BTC-TEST": SimpleNamespace(
                    detector_state=DetectorState.ANOMALY_ACTIVE,
                    reason="ACTIVE",
                    known_evaluation=True,
                    band_id="band",
                    calculation=None,
                )
            },
            trackers={"BTC-TEST": tracker},
            score_bucket_keys={},
            bucket_leader_by_key={},
            bucket_leader_coverage={},
            bucket_trackers={},
            option_books={
                "BTC-TEST": SimpleNamespace(
                    state=SimpleNamespace(value="UNKNOWN"),
                    reason="CHANGE_ID_GAP",
                )
            },
            atomic_states={episode_identity: PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE},
            episode_started_monotonic_ms=lambda _episode: 100,
            episode_active_duration_ms=lambda _episode, *, observed_monotonic_ms: (
                observed_monotonic_ms - 100
            ),
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 200, 1),
        cause=CausalCause.TIME_BOUNDARY,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )

    (row,) = workbench_module._radar_rows(reducer, commit, None)

    assert row["public_atomic_quote_state"] == "PUBLIC_ATOMIC_QUOTE_AVAILABLE"
    assert row["option_book_state"] == "UNKNOWN"
    assert row["option_book_reason"] == "CHANGE_ID_GAP"


def test_radar_projection_explains_candidate_baseline_sampling_and_selection() -> None:
    baseline = SimpleNamespace(
        annualized_volatility="0.72",
        return_interval_minutes=5,
        selected_lookback_minutes=120,
    )
    calculation = SimpleNamespace(
        clue_eligible=False,
        band=SimpleNamespace(clue_eligible=True),
        delta_clue_eligible=False,
        delta_bucket=SimpleNamespace(value="EXTREME_TAIL_LT_05"),
        delta=SimpleNamespace(lower=Decimal("0.20"), upper=Decimal("0.21")),
        executable_sell_price_usdc=Decimal("123.45"),
        executable_buy_price_usdc=Decimal("124.45"),
        stressed_executable_sell_price_usdc=Decimal("123.44"),
        price_tick_usdc=Decimal("0.01"),
        target_spread_usdc=Decimal("1"),
        target_spread_ticks=Decimal("100"),
        bid_premium_ticks=Decimal("12345"),
        target_bid=SimpleNamespace(consumed=(1,)),
        target_ask=SimpleNamespace(consumed=(1, 2)),
        executable_bid_iv=SimpleNamespace(lower="0.80", upper="0.81"),
        executable_ask_iv=SimpleNamespace(lower="0.82", upper="0.83"),
        stressed_executable_bid_iv=SimpleNamespace(lower="0.79", upper="0.80"),
        baseline=baseline,
        raw_richness=SimpleNamespace(lower="1.22", upper="1.23"),
        richness=SimpleNamespace(lower="1.20", upper="1.21"),
    )
    reducer = cast(
        RadarReducer,
        SimpleNamespace(
            options={
                "BTC-TEST": SimpleNamespace(
                    expiration_timestamp_ms=10_000,
                    option_type=SimpleNamespace(value="call"),
                    strike=100,
                    product=INVERSE_BTC,
                )
            },
            results={
                "BTC-TEST": SimpleNamespace(
                    detector_state=DetectorState.NO_ANOMALY,
                    reason="BELOW_ACTIVATION",
                    known_evaluation=True,
                    band_id="band",
                    calculation=calculation,
                )
            },
            trackers={},
            score_bucket_keys={},
            bucket_leader_by_key={},
            bucket_leader_coverage={},
            bucket_trackers={},
            option_books={},
            atomic_states={},
            episode_started_monotonic_ms=lambda _episode: None,
            episode_active_duration_ms=lambda _episode, *, observed_monotonic_ms: None,
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 200, 1),
        cause=CausalCause.TIME_BOUNDARY,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )

    (row,) = workbench_module._radar_rows(reducer, commit, None)

    assert row["baseline_return_interval_minutes"] == 5
    assert row["baseline_selected_lookback_minutes"] == 120
    assert row["baseline_source"] == "UTC_ALIGNED_5M_INDEX_CHART_AVERAGE_PRICE_RV"
    assert row["clue_eligible_tte"] is True
    assert row["clue_eligible_delta"] is False


def test_radar_projection_uses_not_evaluated_without_active_detector_truth() -> None:
    episode_identity = "sha256:" + "8" * 64
    reducer = cast(
        RadarReducer,
        SimpleNamespace(
            options={
                "BTC-TEST": SimpleNamespace(
                    expiration_timestamp_ms=10_000,
                    option_type=SimpleNamespace(value="call"),
                    strike=100,
                    product=INVERSE_BTC,
                )
            },
            results={
                "BTC-TEST": SimpleNamespace(
                    detector_state=DetectorState.UNKNOWN,
                    reason="TIME_BAND_BOUNDARY",
                    known_evaluation=False,
                    band_id=None,
                    calculation=None,
                )
            },
            trackers={
                "BTC-TEST": SimpleNamespace(
                    episode_id=episode_identity,
                    detector_state=DetectorState.UNKNOWN,
                )
            },
            score_bucket_keys={},
            bucket_leader_by_key={},
            bucket_leader_coverage={},
            bucket_trackers={},
            option_books={},
            atomic_states={episode_identity: PublicAtomicQuoteState.PUBLIC_ATOMIC_QUOTE_AVAILABLE},
            episode_started_monotonic_ms=lambda _episode: 100,
            episode_active_duration_ms=lambda _episode, *, observed_monotonic_ms: (
                observed_monotonic_ms - 100
            ),
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 200, 1),
        cause=CausalCause.TIME_BOUNDARY,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )

    (row,) = workbench_module._radar_rows(reducer, commit, None)

    assert row["public_atomic_quote_state"] == "NOT_EVALUATED"
    assert workbench_module._active_anomaly_count(reducer) == 0


def test_initial_snapshot_keeps_empty_panels_separate_from_unknown_zero_claims() -> None:
    store = SnapshotStore(initial_workbench_document(_bindings()))
    value = json.loads(store.read().workbench_body)

    assert value["radar"]["panel_state"] == "EMPTY_NO_SETTLED_OBJECT"
    assert value["radar"]["empty_label"] == EMPTY_PANEL_LABEL
    assert value["zero_claims"]["anomaly"]["value"] is None
    assert value["zero_claims"]["candidate"]["value"] is None
    assert value["system"]["coverage_ratio_percent"] is None
    assert value["shadow_entries"]["simulation_label"] == SIMULATION_LABEL
    assert value["funnel"]["primary_blocker"] == {
        "stage": "APPLICABLE_MARKET_SCOPE",
        "reason": "NO_APPLICABLE_MARKET_SCOPE_OBSERVED",
        "blocked_count": 0,
        "upstream_count": 0,
        "observed_count": 0,
    }
    assert value["service"]["data_state"] == "UNKNOWN"
    assert value["schema_version"] == 7
    assert value["channel_id"] == "INVERSE_BTC_SHORT_VOL_V2"
    assert "THIS_ARTIFACT_DOES_NOT_GRANT_LIVE_OR_DEPLOYMENT_AUTHORITY" in value["non_claims"]
    assert "NO_LIVE_OR_DEPLOYMENT_AUTHORITY" not in value["non_claims"]


def test_latency_projection_separates_source_event_age_from_queue_processing_lag() -> None:
    reducer = cast(
        RadarReducer,
        SimpleNamespace(
            accepted_index_receipt=SimpleNamespace(source_timestamp_ms=1_000),
            tickers={},
            accepted_book_receipts={},
            last_wire_received_monotonic_ms=9_900,
            diagnostics=SimpleNamespace(last_queue_processing_lag_ms=12),
            policy=SimpleNamespace(
                runtime_limits=SimpleNamespace(notification_queue_lag_deadline_ms=5_000)
            ),
            queue_lag_currentness_active=False,
        ),
    )
    commit = CausalCommit(
        boundary=FactBoundary(1, 1, 10_000, 1),
        cause=CausalCause.TIME_BOUNDARY,
        failure_domain=FailureScope.CLOCK_INDEX,
        affected_scopes=("GLOBAL",),
    )

    latency = workbench_module._latency_projection(
        reducer,
        commit,
        TimeInterval(7_999, 8_000),
    )

    assert latency == {
        "latest_market_event_timestamp_ms": 1_000,
        "latest_market_event_age_ms": 7_000,
        "last_wire_message_age_ms": 100,
        "last_queue_processing_lag_ms": 12,
        "queue_lag_deadline_ms": 5_000,
        "queue_lag_currentness_active": False,
    }


def test_shadow_projection_derives_vertical_credit_only_from_persisted_component_legs() -> None:
    candidate_identity = "sha256:" + "1" * 64
    entry_identity = "sha256:" + "2" * 64
    kinds: dict[str, list[dict[str, object]]] = {
        "CANDIDATE_ACTIVATION": [
            {
                "object_identity": candidate_identity,
                "payload": {"candidate_activation_fact_boundary": {"causal_seq": 1}},
            }
        ],
        "ADMISSION_ATTEMPT_TERMINAL": [
            {
                "object_identity": "sha256:" + "3" * 64,
                "fact_boundary": {
                    "code_identity": "a" * 40,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "session_epoch": 1,
                    "ingress_seq": 2,
                    "received_monotonic_ms": 3,
                    "causal_seq": 4,
                },
                "payload": {
                    "candidate_identity": candidate_identity,
                    "terminal_outcome": "ENTRY_EMITTED",
                    "matched_response_identity": "sha256:" + "4" * 64,
                },
            }
        ],
        "SHADOW_ENTRY": [
            {
                "object_identity": entry_identity,
                "runtime_identity": "sha256:" + "b" * 64,
                "payload": {
                    "candidate_identity": candidate_identity,
                    "full_quantity_btc": "0.1",
                    "execution_model": "BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL",
                    "entry_component_pair_identity": "sha256:" + "4" * 64,
                    "entry_component_legs": [
                        {
                            "canonical_leg_role": "SHORT",
                            "action": "SELL",
                            "stressed_vwap_usdc_per_btc": "299",
                        },
                        {
                            "canonical_leg_role": "LONG",
                            "action": "BUY",
                            "stressed_vwap_usdc_per_btc": "102",
                        },
                    ],
                    "gross_entry_credit_usdc": "19.7",
                    "origin_runtime_identity": "sha256:" + "b" * 64,
                    "current_segment_identity": "sha256:" + "3" * 64,
                    "current_segment_sequence": 0,
                    "observation_quality": "CONTINUOUS",
                    "gap_count": 0,
                    "qualification_eligible": True,
                    "tracking_state": "ACTIVE",
                    "post_close_attempt_state": "NOT_SCHEDULED",
                },
            }
        ],
    }

    (row,) = workbench_module._shadow_rows(kinds, _policies())

    assert row["simulated_entry_price_valuation_per_btc"] == "197"
    assert (
        row["simulated_entry_price_availability"]
        == "AVAILABLE_FROM_SHADOW_ENTRY_STRESSED_COMPONENT_LEGS"
    )
    assert row["simulated_entry_price_basis"] == (
        "SHORT_STRESSED_SELL_VWAP_MINUS_LONG_STRESSED_BUY_VWAP"
    )
    assert row["matched_refresh_source_identity"] == "sha256:" + "4" * 64
    assert row["simulation_label"] == SIMULATION_LABEL
    assert {
        key: row[key]
        for key in (
            "origin_runtime_identity",
            "current_segment_identity",
            "current_segment_sequence",
            "observation_quality",
            "gap_count",
            "qualification_eligible",
            "tracking_state",
            "post_close_attempt_state",
        )
    } == {
        "origin_runtime_identity": "sha256:" + "b" * 64,
        "current_segment_identity": "sha256:" + "3" * 64,
        "current_segment_sequence": 0,
        "observation_quality": "CONTINUOUS",
        "gap_count": 0,
        "qualification_eligible": True,
        "tracking_state": "ACTIVE",
        "post_close_attempt_state": "NOT_SCHEDULED",
    }


def test_recovered_entry_stays_one_shadow_row_and_position_starts_unknown() -> None:
    entry_identity = "sha256:" + "2" * 64
    current_runtime = "sha256:" + "b" * 64
    entry = {
        "object_kind": "SHADOW_ENTRY",
        "object_identity": entry_identity,
        "runtime_identity": current_runtime,
        "payload": {
            "candidate_identity": "sha256:" + "1" * 64,
            "canonical_leg_identities": [],
            "origin_runtime_identity": "sha256:" + "a" * 64,
            "current_segment_identity": None,
            "current_segment_sequence": None,
            "observation_quality": "GAPPED",
            "gap_count": 2,
            "qualification_eligible": False,
            "tracking_state": "RECOVERING",
            "post_close_attempt_state": "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS",
        },
    }
    kinds = {"SHADOW_ENTRY": [entry]}

    shadow_rows = workbench_module._shadow_rows(kinds, _policies())
    position_rows = workbench_module._position_rows(
        kinds,
        _policies(),
        trusted_time=None,
        option_metadata=(),
    )
    projection = workbench_module._build_downstream_projection(
        objects=(entry,),
        policies=_policies(),
        underwriting_metadata=(),
    )

    assert len(shadow_rows) == len(projection.shadow_rows) == 1
    assert shadow_rows[0]["shadow_entry_identity"] == entry_identity
    assert shadow_rows[0]["origin_runtime_identity"] == "sha256:" + "a" * 64
    assert shadow_rows[0]["current_segment_identity"] is None
    assert shadow_rows[0]["current_segment_sequence"] is None
    assert shadow_rows[0]["observation_quality"] == "GAPPED"
    assert shadow_rows[0]["gap_count"] == 2
    assert shadow_rows[0]["qualification_eligible"] is False
    assert shadow_rows[0]["tracking_state"] == "RECOVERING"
    assert shadow_rows[0]["post_close_attempt_state"] == "ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS"
    assert len(position_rows) == 1
    assert position_rows[0]["position_action"] == "UNKNOWN"
    assert position_rows[0]["observation_quality"] == "GAPPED"
    assert position_rows[0]["qualification_eligible"] is False
    assert projection.underwriting_counts == {
        "candidate_count": 0,
        "underwriting_availability_evaluable_count": 0,
    }


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    (
        ("current_segment_sequence", -1, "current_segment_sequence"),
        ("observation_quality", "BROKEN", "observation_quality"),
        ("gap_count", 0, "positive gap_count"),
        ("qualification_eligible", True, "qualification eligible"),
        ("tracking_state", "PAUSED", "tracking_state"),
        ("post_close_attempt_state", "RETRYING", "post_close_attempt_state"),
    ),
)
def test_shadow_entry_recovery_tracking_schema_rejects_invalid_values(
    field: str,
    invalid_value: object,
    message: str,
) -> None:
    payload: dict[str, object] = {
        "origin_runtime_identity": "sha256:" + "a" * 64,
        "current_segment_identity": "sha256:" + "3" * 64,
        "current_segment_sequence": 1,
        "observation_quality": "GAPPED",
        "gap_count": 1,
        "qualification_eligible": False,
        "tracking_state": "ACTIVE",
        "post_close_attempt_state": "NOT_SCHEDULED",
    }
    payload[field] = invalid_value

    with pytest.raises((TypeError, ValueError), match=message):
        workbench_module._entry_tracking_projection(
            {
                "object_identity": "sha256:" + "2" * 64,
                "runtime_identity": "sha256:" + "b" * 64,
                "payload": payload,
            }
        )


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"origin_runtime_identity": "sha256:" + "a" * 64},
    ),
)
def test_shadow_entry_recovery_tracking_schema_rejects_missing_payload(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="recovery tracking payload is incomplete"):
        workbench_module._entry_tracking_projection(
            {
                "object_identity": "sha256:" + "2" * 64,
                "runtime_identity": "sha256:" + "b" * 64,
                "payload": payload,
            }
        )


def test_selected_decision_projection_keeps_original_refresh_and_outcome_together() -> None:
    selection_identity = "sha256:" + "1" * 64
    enrollment_identity = "sha256:" + "2" * 64
    observation = {
        "selected_underwriting_decision_identity": selection_identity,
        "activation_batch_identity": "sha256:" + "3" * 64,
        "selected_economic_action": "ABSTAIN",
        "selected_failed_predicates": ["CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE"],
        "selected_predicate_margin_vector": [{"predicate": "CREDIT", "signed_margin": "-1"}],
        "selection_fact_boundary": {"causal_seq": 1},
        "refreshed_economic_action": "WATCH",
        "refreshed_failed_predicates": ["MINIMUM_NET_ENTRY_CREDIT"],
        "refreshed_predicate_margin_vector": [{"predicate": "CREDIT", "signed_margin": "1"}],
        "refreshed_fact_boundary": {"causal_seq": 5},
    }
    kinds: dict[str, list[dict[str, object]]] = {
        "SELECTED_UNDERWRITING_DECISION": [
            {
                "object_identity": selection_identity,
                "payload": {
                    "active_episode_identity": "episode-1",
                    "economic_action": "ABSTAIN",
                    "failed_predicates": ["CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE"],
                    "predicate_margin_vector": observation["selected_predicate_margin_vector"],
                },
            }
        ],
        "SELECTED_UNDERWRITING_DECISION_CONTROL_OPEN": [
            {
                "object_identity": enrollment_identity,
                "payload": {
                    "enrollment_kind": "SELECTED_UNDERWRITING_DECISION_CONTROL",
                    "selected_underwriting_decision": observation,
                    "entry_component_pair_timing": {"source_timestamp_skew_ms": 1},
                    "non_claims": ["NOT_AN_ADMITTED_TRADE"],
                },
            }
        ],
        "SELECTED_UNDERWRITING_DECISION_CONTROL_OUTCOME": [
            {
                "object_identity": "sha256:" + "4" * 64,
                "payload": {
                    "shadow_entry_identity": enrollment_identity,
                    "terminal_state": "MATURE_KNOWN",
                    "net_pnl_after_public_standard_fee_reserve_usdc": "-3.5",
                },
            }
        ],
    }

    (row,) = workbench_module._decision_control_rows(kinds)

    assert row["selected_economic_action"] == "ABSTAIN"
    assert row["refreshed_economic_action"] == "WATCH"
    assert row["enrollment_kind"] == "SELECTED_UNDERWRITING_DECISION_CONTROL"
    assert row["case_state"] == "MATURE_KNOWN"
    assert row["public_quote_net_pnl_valuation"] == "-3.5"
    assert (
        row["selected_predicate_margin_vector"] == observation["selected_predicate_margin_vector"]
    )
    assert (
        row["refreshed_predicate_margin_vector"] == observation["refreshed_predicate_margin_vector"]
    )


def test_shadow_projection_exposes_exact_pair_timing_no_entry_reason() -> None:
    candidate_identity = "sha256:" + "1" * 64
    boundary = {
        "code_identity": "a" * 40,
        "runtime_identity": "sha256:" + "b" * 64,
        "session_epoch": 1,
        "ingress_seq": 2,
        "received_monotonic_ms": 3,
        "causal_seq": 4,
    }
    kinds: dict[str, list[dict[str, object]]] = {
        "CANDIDATE_ACTIVATION": [
            {
                "object_identity": candidate_identity,
                "fact_boundary": boundary,
                "payload": {"candidate_activation_fact_boundary": boundary},
            }
        ],
        "ADMISSION_ATTEMPT_TERMINAL": [
            {
                "object_identity": "sha256:" + "3" * 64,
                "fact_boundary": boundary,
                "payload": {
                    "candidate_identity": candidate_identity,
                    "terminal_outcome": "UNKNOWN_CONSUMED",
                    "matched_response_identity": None,
                    "terminal_unknown_reasons": [
                        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
                        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
                    ],
                },
            }
        ],
    }

    (row,) = workbench_module._shadow_rows(kinds, _policies())

    assert row["admission_refresh_terminal_outcome"] == "UNKNOWN_CONSUMED"
    assert row["admission_refresh_unknown_reasons"] == [
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    ]
    assert row["no_entry_reason"] == (
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED,COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED"
    )


def test_publisher_keeps_retired_admission_terminal_only_for_its_active_episode() -> None:
    bindings = _bindings()
    state = ShadowStateStore(bindings=bindings)
    boundary = DownstreamFactBoundary(
        code_identity=bindings.code_identity,
        runtime_identity=bindings.runtime_identity,
        session_epoch=1,
        ingress_seq=1,
        received_monotonic_ms=2,
        causal_seq=3,
    )
    episode_identity = "sha256:" + "1" * 64
    scope_identity = "sha256:" + "2" * 64
    candidate_identity = "sha256:" + "3" * 64
    state.record(
        object_kind="UNDERWRITING_AVAILABILITY_EVALUATION",
        object_identity="sha256:" + "4" * 64,
        fact_boundary=boundary,
        payload={
            "radar_scope_or_short_leg_identity": scope_identity,
            "active_episode_identity": episode_identity,
            "availability": "EVALUABLE",
        },
    )
    state.record(
        object_kind="CANDIDATE_ACTIVATION",
        object_identity=candidate_identity,
        fact_boundary=boundary,
        payload={
            "candidate_identity": candidate_identity,
            "active_episode_identity": episode_identity,
            "candidate_activation_fact_boundary": boundary.as_object(),
        },
    )
    state.record(
        object_kind="ADMISSION_ATTEMPT_TERMINAL",
        object_identity="sha256:" + "5" * 64,
        fact_boundary=boundary,
        payload={
            "candidate_identity": candidate_identity,
            "active_episode_identity": episode_identity,
            "terminal_outcome": "UNKNOWN_CONSUMED",
            "terminal_unknown_reasons": ["COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED"],
            "component_pair_timing": {"source_timestamp_skew_ms": 7_000},
            "component_pair_limits": {"maximum_source_skew_ms": 6_000},
        },
    )
    state.retire_candidate(candidate_identity)
    assert all(value["object_kind"] != "ADMISSION_ATTEMPT_TERMINAL" for value in state.objects)
    publisher = WorkbenchPublisher(
        store=SnapshotStore(initial_workbench_document(bindings)),
        bindings=bindings,
        policies=_policies(),
        shadow_state=state,
        shadow_metadata=cast(workbench_module.ShadowMetadataSource, SimpleNamespace()),
    )

    publisher._update_admission_terminal_diagnostics(state.take_pending_records())
    diagnostics = tuple(publisher._admission_terminal_diagnostics_by_episode.values())
    projection = workbench_module._build_downstream_projection(
        objects=state.objects,
        diagnostic_records=diagnostics,
        policies=_policies(),
        underwriting_metadata=(),
    )

    (row,) = projection.shadow_rows
    assert row["candidate_identity"] == candidate_identity
    assert row["active_episode_identity"] == episode_identity
    assert row["admission_refresh_terminal_outcome"] == "UNKNOWN_CONSUMED"
    assert row["admission_component_pair_timing"] == {"source_timestamp_skew_ms": 7_000}
    assert row["admission_component_pair_limits"] == {"maximum_source_skew_ms": 6_000}
    state.retire_scope(scope_identity)
    publisher._update_admission_terminal_diagnostics(())
    assert publisher._admission_terminal_diagnostics_by_episode == {}


def test_underwriting_projection_keeps_unknown_availability_without_an_action() -> None:
    availability_identity = "sha256:" + "7" * 64
    scope_identity = "sha256:" + "8" * 64
    kinds: dict[str, list[dict[str, object]]] = {
        "UNDERWRITING_AVAILABILITY_EVALUATION": [
            {
                "object_identity": availability_identity,
                "fact_boundary": {
                    "code_identity": "a" * 40,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 2,
                    "causal_seq": 3,
                },
                "payload": {
                    "radar_scope_or_short_leg_identity": scope_identity,
                    "availability": "UNKNOWN",
                    "unknown_reasons": ["COMBO_QUOTE_RECEIPT_UNKNOWN"],
                    "availability_evaluation_fact_boundary": {"causal_seq": 3},
                },
            }
        ]
    }

    (row,) = workbench_module._underwriting_rows(kinds, _policies())

    assert row["radar_scope_or_short_leg_identity"] == scope_identity
    assert row["availability"] == "UNKNOWN"
    assert row["action"] is None
    assert row["candidate_identity"] is None
    assert row["decision_reason"] == ("UNDERWRITING_UNKNOWN:COMBO_QUOTE_RECEIPT_UNKNOWN")


def test_underwriting_projection_exposes_owner_margin_vector_and_exact_failures() -> None:
    availability_identity = "sha256:" + "7" * 64
    scope_identity = "sha256:" + "8" * 64
    margin_vector = [
        {
            "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
            "signed_margin": "-1",
            "unit": "USDC",
            "passes": False,
        },
        {
            "predicate": "MINIMUM_NET_ENTRY_CREDIT",
            "signed_margin": "-4",
            "unit": "USDC",
            "passes": False,
        },
    ]
    kinds: dict[str, list[dict[str, object]]] = {
        "UNDERWRITING_AVAILABILITY_EVALUATION": [
            {
                "object_identity": availability_identity,
                "fact_boundary": {
                    "code_identity": "a" * 40,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 2,
                    "causal_seq": 3,
                },
                "payload": {
                    "radar_scope_or_short_leg_identity": scope_identity,
                    "availability": "EVALUABLE",
                    "unknown_reasons": [],
                },
            }
        ],
        "UNDERWRITING_ACTION": [
            {
                "object_identity": "sha256:" + "9" * 64,
                "fact_boundary": {
                    "code_identity": "a" * 40,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 2,
                    "causal_seq": 3,
                },
                "payload": {
                    "underwriting_availability_evaluation_identity": availability_identity,
                    "economic_action": "ABSTAIN",
                    "decision_blockers": ["CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE"],
                    "failed_predicates": [
                        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
                        "MINIMUM_NET_ENTRY_CREDIT",
                    ],
                    "predicate_margin_vector": margin_vector,
                    "selected_long_leg_instrument_name": "BTC-SELECTED-LONG",
                    "protective_leg_selection_rule_identity": "sha256:" + "a" * 64,
                    "candidate_protective_leg_count": 0,
                },
            }
        ],
    }

    (row,) = workbench_module._underwriting_rows(kinds, _policies())

    assert row["failed_predicates"] == [
        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE",
        "MINIMUM_NET_ENTRY_CREDIT",
    ]
    assert row["predicate_margin_vector"] == margin_vector
    assert row["long_leg_instrument_name"] == "BTC-SELECTED-LONG"
    assert row["protective_leg_selection_rule_identity"] == "sha256:" + "a" * 64
    assert row["candidate_protective_leg_count"] == 0
    assert row["decision_reason"] == (
        "UNDERWRITING_ACTION:ABSTAIN;FAILED:"
        "CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE,MINIMUM_NET_ENTRY_CREDIT"
    )


def test_underwriting_margin_summary_is_exact_over_the_bounded_current_rows() -> None:
    rows = [
        {
            "predicate_margin_vector": [
                {
                    "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
                    "signed_margin": margin,
                    "unit": "USDC",
                },
                {
                    "predicate": "ENTRY_CONSUMED_LEVEL_LIMIT",
                    "signed_margin": levels,
                    "unit": "LEVEL_COUNT",
                },
            ]
        }
        for margin, levels in (("-1", 8), ("3", 4))
    ]

    assert workbench_module._underwriting_margin_summary(rows) == [
        {
            "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
            "unit": "USDC",
            "count": 2,
            "min": "-1",
            "p50": "1",
            "max": "3",
        },
        {
            "predicate": "ENTRY_CONSUMED_LEVEL_LIMIT",
            "unit": "LEVEL_COUNT",
            "count": 2,
            "min": "4",
            "p50": "6",
            "max": "8",
        },
    ]


def test_underwriting_projection_joins_only_settled_display_metadata() -> None:
    availability_identity = "sha256:" + "7" * 64
    scope_identity = "sha256:" + "8" * 64
    kinds: dict[str, list[dict[str, object]]] = {
        "UNDERWRITING_AVAILABILITY_EVALUATION": [
            {
                "object_identity": availability_identity,
                "fact_boundary": {
                    "code_identity": "a" * 40,
                    "runtime_identity": "sha256:" + "b" * 64,
                    "session_epoch": 1,
                    "ingress_seq": 1,
                    "received_monotonic_ms": 2,
                    "causal_seq": 3,
                },
                "payload": {
                    "radar_scope_or_short_leg_identity": scope_identity,
                    "availability": "NOT_EVALUATED",
                    "unknown_reasons": ["RADAR_EPISODE_NOT_ACTIVE"],
                    "availability_evaluation_fact_boundary": {"causal_seq": 3},
                },
            }
        ]
    }
    display_metadata = (
        {
            "radar_scope_identity": scope_identity,
            "short_leg_instrument_name": "BTC-8AUG26-100000-C",
            "long_leg_instrument_name": "BTC-8AUG26-105000-C",
            "combo_instrument_name": "BTC-CS-8AUG26-100000_105000",
            "expiry_timestamp_ms": 1_786_150_800_000,
            "option_type": "call",
            "short_strike_usdc_per_btc": "100000",
            "long_strike_usdc_per_btc": "105000",
            "target_quantity_btc": "0.1",
        },
    )

    (row,) = workbench_module._underwriting_rows(
        kinds,
        _policies(),
        display_metadata=display_metadata,
    )

    assert row["short_leg_instrument_name"] == "BTC-8AUG26-100000-C"
    assert row["long_leg_instrument_name"] == "BTC-8AUG26-105000-C"
    assert row["combo_instrument_name"] == "BTC-CS-8AUG26-100000_105000"
    assert row["expiry_timestamp_ms"] == 1_786_150_800_000
    assert row["short_strike_price"] == "100000"
    assert row["target_quantity_btc"] == "0.1"


def test_underwriting_projection_does_not_attach_old_shadow_entry_by_scope() -> None:
    scope_identity = "sha256:" + "1" * 64
    old_availability_identity = "sha256:" + "2" * 64
    current_availability_identity = "sha256:" + "3" * 64
    action_identity = "sha256:" + "4" * 64
    candidate_identity = "sha256:" + "5" * 64

    def boundary(sequence: int) -> dict[str, object]:
        return {
            "code_identity": "a" * 40,
            "runtime_identity": "sha256:" + "b" * 64,
            "session_epoch": 1,
            "ingress_seq": sequence,
            "received_monotonic_ms": sequence,
            "causal_seq": sequence,
        }

    kinds: dict[str, list[dict[str, object]]] = {
        "UNDERWRITING_AVAILABILITY_EVALUATION": [
            {
                "object_identity": old_availability_identity,
                "fact_boundary": boundary(1),
                "payload": {
                    "radar_scope_or_short_leg_identity": scope_identity,
                    "availability": "EVALUABLE",
                    "availability_evaluation_fact_boundary": {"causal_seq": 1},
                },
            },
            {
                "object_identity": current_availability_identity,
                "fact_boundary": boundary(5),
                "payload": {
                    "radar_scope_or_short_leg_identity": scope_identity,
                    "availability": "NOT_EVALUATED",
                    "availability_evaluation_fact_boundary": {"causal_seq": 5},
                },
            },
        ],
        "UNDERWRITING_ACTION": [
            {
                "object_identity": action_identity,
                "fact_boundary": boundary(2),
                "payload": {
                    "underwriting_availability_evaluation_identity": old_availability_identity,
                    "economic_action": "CANDIDATE",
                },
            }
        ],
        "CANDIDATE_ACTIVATION": [
            {
                "object_identity": candidate_identity,
                "fact_boundary": boundary(3),
                "payload": {"underwriting_action_identity": action_identity},
            }
        ],
        "SHADOW_ENTRY": [
            {
                "object_identity": "sha256:" + "6" * 64,
                "fact_boundary": boundary(4),
                "payload": {
                    "candidate_identity": candidate_identity,
                    "radar_scope_identity": scope_identity,
                    "full_quantity_btc": "0.1",
                    "entry_component_legs": [],
                },
            }
        ],
    }

    (row,) = workbench_module._underwriting_rows(kinds, _policies())

    assert row["underwriting_availability_evaluation_identity"] == current_availability_identity
    assert row["availability"] == "NOT_EVALUATED"
    assert row["underwriting_action_identity"] is None
    assert row["candidate_identity"] is None
    assert row["candidate_lifecycle"] is None

    coherent_kinds = {
        **kinds,
        "UNDERWRITING_AVAILABILITY_EVALUATION": [kinds["UNDERWRITING_AVAILABILITY_EVALUATION"][0]],
    }
    (admitted_row,) = workbench_module._underwriting_rows(coherent_kinds, _policies())
    assert admitted_row["underwriting_action_identity"] == action_identity
    assert admitted_row["candidate_identity"] == candidate_identity
    assert admitted_row["candidate_lifecycle"] == "ADMITTED"


def test_position_projection_separates_gross_remaining_premium_from_net_close_debit() -> None:
    entry_identity = "sha256:" + "5" * 64
    boundary = {
        "code_identity": "a" * 40,
        "runtime_identity": "sha256:" + "b" * 64,
        "session_epoch": 1,
        "ingress_seq": 2,
        "received_monotonic_ms": 3,
        "causal_seq": 4,
    }
    kinds: dict[str, list[dict[str, object]]] = {
        "SHADOW_ENTRY": [
            {
                "object_identity": entry_identity,
                "runtime_identity": "sha256:" + "b" * 64,
                "payload": {
                    "canonical_leg_identities": [],
                    "origin_runtime_identity": "sha256:" + "b" * 64,
                    "current_segment_identity": "sha256:" + "7" * 64,
                    "current_segment_sequence": 0,
                    "observation_quality": "CONTINUOUS",
                    "gap_count": 0,
                    "qualification_eligible": True,
                    "tracking_state": "ACTIVE",
                    "post_close_attempt_state": "NOT_SCHEDULED",
                },
            }
        ],
        "CLOSE_OPPORTUNITY_EVALUATION": [
            {
                "object_identity": "sha256:" + "6" * 64,
                "fact_boundary": boundary,
                "payload": {
                    "shadow_entry_identity": entry_identity,
                    "gross_close_cashflow_usdc": "-25",
                    "net_close_debit_usdc": "26",
                    "projected_shadow_net_pnl_usdc": "8",
                    "eligibility": "ELIGIBLE",
                    "eligibility_reason": "ALL_RULES_MET",
                    "component_pair_timing": {
                        "source_timestamp_skew_ms": 7_000,
                        "receive_skew_ms": 5_000,
                    },
                    "component_pair_limits": {
                        "maximum_source_skew_ms": 6_000,
                        "maximum_receive_skew_ms": 4_000,
                    },
                    "component_pair_unknown_reasons": [
                        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
                        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
                    ],
                },
            }
        ],
    }

    (row,) = workbench_module._position_rows(
        kinds,
        _policies(),
        trusted_time=None,
        option_metadata=(),
    )

    assert row["remaining_premium_valuation"] == "25"
    assert row["remaining_premium_availability"] == (
        "AVAILABLE_FROM_PERSISTED_COMPONENT_CLOSE_ECONOMICS"
    )
    assert row["remaining_premium_basis"] == ("MAX_ZERO_NEGATIVE_GROSS_CLOSE_CASHFLOW_VALUATION")
    assert row["current_close_debit_valuation"] == "26"
    assert row["projected_shadow_pnl_valuation"] == "8"
    assert row["observation_quality"] == "CONTINUOUS"
    assert row["qualification_eligible"] is True
    assert row["component_pair_timing"] == {
        "source_timestamp_skew_ms": 7_000,
        "receive_skew_ms": 5_000,
    }
    assert row["component_pair_limits"] == {
        "maximum_source_skew_ms": 6_000,
        "maximum_receive_skew_ms": 4_000,
    }
    assert row["component_pair_business_state"] == "UNKNOWN"
    assert row["component_pair_unknown_reasons"] == [
        "COMPONENT_PAIR_SOURCE_TIMESTAMP_SKEW_EXCEEDED",
        "COMPONENT_PAIR_RECEIVE_SKEW_EXCEEDED",
    ]


def test_snapshot_store_serializes_before_publication_and_does_not_retain_mutable_input() -> None:
    bindings = _bindings()
    document = initial_workbench_document(bindings)
    rows: list[dict[str, object]] = [{"instrument_name": "BTC-TEST"}]
    document["radar"] = {
        "panel_state": "HAS_SETTLED_OBJECTS",
        "empty_label": None,
        "rows": rows,
    }
    store = SnapshotStore(initial_workbench_document(bindings))

    published = store.publish(document)
    rows[0]["instrument_name"] = "MUTATED-AFTER-PUBLISH"
    value = json.loads(published.workbench_body)

    assert value["radar"]["rows"][0]["instrument_name"] == "BTC-TEST"


def test_snapshot_store_preencoded_members_preserve_exact_snapshot_bytes() -> None:
    bindings = _bindings()
    document = initial_workbench_document(bindings)
    document["underwriting"] = {
        "panel_state": "HAS_SETTLED_OBJECTS",
        "empty_label": None,
        "rows": [
            {
                "radar_scope_or_short_leg_identity": "sha256:" + "1" * 64,
                "availability": "NOT_EVALUATED",
                "decision_reason": "UNDERWRITING_NOT_EVALUATED:RADAR_EPISODE_NOT_ACTIVE",
            }
        ],
    }
    expected_store = SnapshotStore(initial_workbench_document(bindings))
    actual_store = SnapshotStore(initial_workbench_document(bindings))

    expected = expected_store.publish(document)
    actual = actual_store.publish_preencoded_members(
        document,
        preencoded_members={
            "underwriting": workbench_module._json_value_bytes(document["underwriting"])
        },
    )

    assert actual.sequence == expected.sequence
    assert actual.workbench_body == expected.workbench_body
    assert actual.health_body == expected.health_body
    assert actual.ready_body == expected.ready_body


def test_http_is_loopback_get_head_only_with_security_headers() -> None:
    store = SnapshotStore(initial_workbench_document(_bindings()))
    server = LoopbackWorkbenchServer(host="127.0.0.1", port=0, store=store)
    server.start()
    try:
        status, headers, body = _request(server, "GET", "/api/workbench/current")
        assert status == 200
        assert json.loads(body)["runtime_identity"] == _bindings().runtime_identity
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "connect-src 'self'" in headers["Content-Security-Policy"]

        status, headers, body = _request(server, "HEAD", "/api/workbench/current")
        assert status == 200
        assert body == b""
        assert int(headers["Content-Length"]) > 0

        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"):
            status, headers, body = _request(server, method, "/api/workbench/current")
            assert status == 405
            assert headers["Allow"] == "GET, HEAD"
            assert body == b""
        status, headers, body = _request(server, "BREW", "/api/workbench/current")
        assert status == 405
        assert headers["Allow"] == "GET, HEAD"
        assert body == b""

        status, _, _ = _request(server, "GET", "/private/account")
        assert status == 404
        status, _, _ = _request(server, "GET", "/healthz")
        assert status == 200
        status, _, _ = _request(server, "GET", "/readyz")
        assert status == 503
    finally:
        server.close()


def test_http_rejects_non_loopback_or_hostname_bindings() -> None:
    store = SnapshotStore(initial_workbench_document(_bindings()))
    with pytest.raises(ValueError, match="loopback"):
        LoopbackWorkbenchServer(host="0.0.0.0", port=0, store=store)
    with pytest.raises(ValueError, match="explicit loopback"):
        LoopbackWorkbenchServer(host="localhost", port=0, store=store)


def test_http_supports_explicit_ipv6_loopback_when_available() -> None:
    probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    store = SnapshotStore(initial_workbench_document(_bindings()))
    try:
        probe.bind(("::1", 0))
    except OSError as exc:
        pytest.skip(f"IPv6 loopback unavailable: {exc}")
    finally:
        probe.close()
    server = LoopbackWorkbenchServer(host="::1", port=0, store=store)
    assert server._server.address_family == socket.AF_INET6
    server.start()
    try:
        status, _, body = _request(server, "GET", "/api/workbench/current")
        assert status == 200
        assert json.loads(body)["runtime_identity"] == _bindings().runtime_identity
    finally:
        server.close()


def test_health_and_readiness_are_independent_published_facts() -> None:
    bindings = _bindings()
    document = initial_workbench_document(bindings)
    store = SnapshotStore(document)
    assert store.read().health is True
    assert store.read().ready is False

    document["service"] = {
        "phase": ServicePhase.RUNNING.value,
        "data_state": DataState.CURRENT.value,
        "health": True,
        "ready": True,
        "stale": False,
        "reason": "CURRENT",
        "recorded_monotonic_ms": 10,
    }
    store.publish(document)

    assert store.read().health is True
    assert store.read().ready is True


def test_get_handler_reads_only_immutable_store_bytes() -> None:
    source = inspect.getsource(WorkbenchRequestHandler)
    for forbidden in (
        "RadarReducer",
        "FixedContractShadowOwner",
        "classify_",
        "freeze",
        "policy",
        "owner.",
        "reducer.",
    ):
        assert forbidden not in source
    assert "self._store.read()" in source


def test_browser_assets_are_display_only_and_have_no_execution_surface() -> None:
    combined = f"{HTML}\n{JS}"
    assert SIMULATION_LABEL in HTML
    assert "/api/workbench/current" in JS
    assert "WebSocket" not in combined
    assert "deribit.com" not in combined.lower()
    assert "<form" not in HTML.lower()
    assert "/private" not in combined
    assert "/policy" not in JS.lower()
    assert "set_policy" not in JS.lower()
    assert "submit_order" not in JS.lower()
    assert "escapeHtml" in JS
    assert "&lt;" in JS and "&gt;" in JS and "&amp;" in JS
    assert "JSON.stringify(row, null, 2)" in JS
    assert 'id="connection"' in HTML
    assert 'id="runtime-status"' in HTML
    assert 'id="runtime-state-label"' in HTML
    assert 'id="runtime-blocker"' in HTML
    assert 'id="channel-list"' in HTML
    assert 'id="queue-body"' in HTML
    assert 'id="detail-panel"' in HTML
    assert 'role="alert"' in HTML
    assert "function renderUnavailable" in JS
    assert "lastSuccessfulFetchAtMs" in JS
    assert "lastPublicationRuntimeIdentity" in JS
    assert "lastPublicationChangeAtMs" in JS
    assert "documentValue.publication_sequence" in JS
    assert "if (!response.ok) throw" in JS
    assert "renderUnavailable();" in JS
    assert "SUPPORTED_SCHEMA_VERSION = 7" in JS
    assert "runtimeStatusState" in JS
    assert ".queue-table" in CSS
    assert "overflow: auto" in CSS
    assert "服务器未提供 V2 score packet" in JS
    assert "浏览器不补算" in JS


def test_browser_formats_business_states_and_orders_rows_without_recomputing() -> None:
    test_js = JS.replace(
        "syncThemeControl();\nupdateResponsiveDetailState();\nrefresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchTest = { structureState, radarState, orderedStructureRows, "
        "orderedRadarRows, predicateMarginForFailure, formatMargin, formatDurationInterval, "
        "reasonText, channelSnapshotState };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
globalThis.document = {{getElementById() {{ return {{}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__workbenchTest;

assert.equal(api.formatDurationInterval({{
  lower_ms: 60000, upper_ms: 120000
}}), '1.0 分钟 \u2013 2.0 分钟');
assert.equal(api.reasonText('QUEUE_LAG_CURRENTNESS'), '处理队列延迟\uff0c行情时效性不可确认');
assert.equal(api.reasonText('NO_ACTIVE_COMBO'), '无现成官方组合\uff1b不阻塞双腿 Shadow 模拟');

const radar = api.orderedRadarRows([
  {{instrument_name:'N', score_result:{{band:'LOW'}}, attention_rank:3}},
  {{instrument_name:'U', attention_rank:2}},
  {{instrument_name:'A', score_result:{{band:'HIGH'}}, attention_rank:1,
    clue_eligible_tte:true, clue_eligible_delta:true,
    is_bucket_leader:true, bucket_episode_leader_instrument_name:'A',
    bucket_episode_state:'ACTIVE', bucket_episode_score_band:'HIGH',
    bucket_episode_identity:'sha256:active'}}
]);
assert.deepEqual(radar.map(row => row.instrument_name), ['A', 'U', 'N']);
assert.equal(api.radarState(radar[0]).key, 'HIGH');
assert.equal(api.radarState(radar[0]).label, 'HIGH · 已确认线索');

const underwriting = api.orderedStructureRows([
  {{short_leg_instrument_name:'n', availability:'NOT_EVALUATED'}},
  {{short_leg_instrument_name:'u', availability:'UNKNOWN'}},
  {{short_leg_instrument_name:'a', availability:'EVALUABLE', action:'ABSTAIN'}},
  {{short_leg_instrument_name:'w', availability:'EVALUABLE', action:'WATCH'}},
  {{short_leg_instrument_name:'e', availability:'EVALUABLE', action:'CANDIDATE'}},
  {{short_leg_instrument_name:'s', candidate_lifecycle:'ADMITTED'}}
]);
assert.deepEqual(
  underwriting.map(row => row.short_leg_instrument_name),
  ['s', 'e', 'w', 'a', 'u', 'n']
);

const margin = api.predicateMarginForFailure({{
  predicate_margin_vector: [{{
    predicate:'CREDIT_ABOVE_FUTURE_COST_RESERVE', signed_margin:'-2.5',
    unit:'USD_EQUIVALENT', passes:false
  }}]
}}, 'CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE');
assert.equal(api.formatMargin(margin), '-2.5 USD 等值');

const snapshot = {{
  channel_id:'INVERSE_BTC_SHORT_VOL_V2',
  product: {{name:'inverse-btc', product_spec_identity:{json.dumps(INVERSE_BTC.identity)}}},
  policy_identities: {{
    radar:{json.dumps(INVERSE_BTC_RADAR_POLICY_IDENTITY)},
    underwriting:{json.dumps(INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY)},
    position:{json.dumps(INVERSE_BTC_POSITION_POLICY_IDENTITY)}
  }},
  service: {{ready:true, reason:'NONE'}},
  system: {{
    latest_market_event_age_ms:7000, last_wire_message_age_ms:100,
    last_queue_processing_lag_ms:12, queue_lag_deadline_ms:5000,
    queue_lag_currentness_active:false
  }}
}};
assert.equal(api.channelSnapshotState(snapshot).code, 'CONNECTED');
assert.match(api.channelSnapshotState(snapshot).note, /处理 12 ms/);
assert.match(api.channelSnapshotState(snapshot).note, /行情事件 7.0 秒/);
assert.equal(api.channelSnapshotState({{...snapshot, product:{{...snapshot.product, name:'linear-btc-usdc'}}}}).code,
  'IDENTITY_MISMATCH');
"""
    completed = subprocess.run(
        ["node"],
        check=False,
        capture_output=True,
        input=harness,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_keeps_formatted_exact_facts_in_collapsed_details() -> None:
    for exact_field in (
        "native_net_entry_credit",
        "net_entry_credit_valuation",
        "future_cost_reserve_valuation",
        "underwriting_reserved_loss_valuation",
        "entry_boundary_valued_payoff_loss_ex_fees_valuation",
        "predicate_margin_vector",
        "primary_blocker",
        "upgrade_condition",
        "invalidation_condition",
    ):
        assert exact_field in JS
    assert "data-evidence-details" in JS
    assert 'class="evidence-raw"' in JS


def test_browser_executes_fail_closed_and_recovery_paths() -> None:
    document = initial_workbench_document(_bindings(), product=INVERSE_BTC)
    document["policy_identities"] = {
        "radar": INVERSE_BTC_RADAR_POLICY_IDENTITY,
        "underwriting": INVERSE_BTC_UNDERWRITING_POLICY_IDENTITY,
        "position": INVERSE_BTC_POSITION_POLICY_IDENTITY,
    }
    document["publication_sequence"] = 1
    document["published_fact_boundary"] = {
        "causal_seq": 42,
        "received_monotonic_ms": 1_234,
    }
    document["service"] = {
        "phase": "RUNNING",
        "data_state": "CURRENT",
        "health": True,
        "ready": True,
        "stale": False,
        "reason": "NONE",
        "recorded_monotonic_ms": 1_234,
    }
    system = document["system"]
    assert isinstance(system, dict)
    system["latest_market_event_timestamp_ms"] = 1_700_000_000_000
    system["latest_market_event_age_ms"] = 18
    system["last_wire_message_age_ms"] = 8
    system["last_queue_processing_lag_ms"] = 2
    system["queue_lag_deadline_ms"] = 5_000
    system["queue_lag_currentness_active"] = False
    underwriting = document["underwriting"]
    assert isinstance(underwriting, dict)
    underwriting["rows"] = [
        {
            "underwriting_availability_evaluation_identity": "structure-current",
            "underwriting_action_identity": "action-current",
            "radar_scope_or_short_leg_identity": "scope-current",
            "short_leg_instrument_name": "BTC-TEST-65000-P",
            "long_leg_instrument_name": "BTC-TEST-62000-P",
            "short_strike_price": "65000",
            "long_strike_price": "62000",
            "option_type": "put",
            "expiry_timestamp_ms": 1_800_000_000_000,
            "availability": "EVALUABLE",
            "action": "WATCH",
            "candidate_lifecycle": None,
            "candidate_still_valid": False,
            "candidate_identity": None,
            "target_quantity_btc": "0.1",
            "native_net_entry_credit": "0.001",
            "net_entry_credit_valuation": "64.8",
            "entry_valuation_index_price": "64800",
            "future_cost_reserve_valuation": "80",
            "underwriting_reserved_loss_valuation": "120",
            "entry_boundary_valued_payoff_loss_ex_fees_valuation": "300",
            "failed_predicates": ["CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE"],
            "predicate_margin_vector": [
                {
                    "predicate": "CREDIT_ABOVE_FUTURE_COST_RESERVE",
                    "signed_margin": "-15.2",
                    "unit": "USD_EQUIVALENT",
                    "passes": False,
                }
            ],
        }
    ]
    radar = document["radar"]
    assert isinstance(radar, dict)
    radar["rows"] = [
        {
            "instrument_name": "BTC-TEST-65000-P",
            "attention_rank": 1,
            "detector_state": "ANOMALY_ACTIVE",
            "detector_reason": "NONE",
            "primary_blocker": "NONE_AT_RADAR_HARD_SCREEN",
            "positive_witness": "TARGET_SIZE_TWO_SIDED_ONE_TICK_FORMULA_KNOWN",
            "upgrade_condition": "OFFICIAL_ATOMIC_QUOTE_THEN_UNDERWRITING",
            "invalidation_condition": "SOURCE_LOSS_OR_KNOWN_FORMULA_INELIGIBILITY",
            "expiration_timestamp_ms": 1_800_000_000_000,
            "strike_price": "65000",
            "option_type": "put",
            "tte_interval_ms": {"lower_ms": 3_600_000, "upper_ms": 3_600_000},
            "delta_interval": {"lower": "-0.2", "upper": "-0.2"},
            "executable_iv_interval": {"lower": "0.5", "upper": "0.5"},
            "one_tick_stressed_iv_interval": {"lower": "0.49", "upper": "0.49"},
            "baseline_annualized_volatility": "0.37",
            "richness_ratio_interval": {"lower": "1.3", "upper": "1.3"},
            "target_spread_ticks": "3",
        }
    ]
    restarted_document = json.loads(json.dumps(document))
    restarted_document["runtime_identity"] = "sha256:" + "f" * 64
    restarted_newer_document = json.loads(json.dumps(restarted_document))
    restarted_newer_document["publication_sequence"] = 2
    restarted_underwriting = restarted_newer_document["underwriting"]
    assert isinstance(restarted_underwriting, dict)
    restarted_rows = restarted_underwriting["rows"]
    assert isinstance(restarted_rows, list)
    restarted_rows[0]["short_leg_instrument_name"] = "BTC-NEWER-65000-P"
    retired_document = json.loads(json.dumps(document))
    retired_document["publication_sequence"] = 2
    malformed_document = json.loads(json.dumps(document))
    malformed_document["runtime_identity"] = "sha256:" + "9" * 64
    malformed_document["publication_sequence"] = 9
    malformed_document["radar"] = None

    test_js = JS.replace(
        "syncThemeControl();\nupdateResponsiveDetailState();\nrefresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchRefresh = refresh;",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
const elementIds = [
  'connection', 'as-of', 'runtime', 'channel-list', 'queue-context', 'queue-filters',
  'queue-status', 'queue-head', 'queue-body', 'detail-title', 'detail-content',
  'detail-panel', 'detail-scrim', 'shadow-jump', 'evidence-toggle', 'footer-summary',
  'runtime-status', 'runtime-state-label', 'runtime-state-detail', 'service-phase',
  'data-currentness', 'data-delay', 'wire-age', 'queue-lag', 'runtime-blocker'
];
const elements = Object.fromEntries(elementIds.map(id => [id, {{
  hidden: id === 'connection', textContent: '', innerHTML: '', scrollTop: 0,
  dataset: {{}}, attributes: {{}},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  removeAttribute(name) {{ delete this.attributes[name]; }},
  querySelector() {{ return null; }}
}}]));
const queueTable = {{scrollTop: 0}};
globalThis.document = {{
  body: {{dataset: {{}}, classList: {{toggle() {{}}}}}},
  getElementById(id) {{
    assert.ok(elements[id], `unexpected element ${{id}}`);
    return elements[id];
  }},
  querySelector(selector) {{ return selector === '.queue-table' ? queueTable : null; }},
  querySelectorAll() {{ return []; }}
}};
globalThis.setInterval = () => 1;
let nowMs = 0;
Date.now = () => nowMs;
const fetchQueue = [];
globalThis.fetch = async () => {{
  const item = fetchQueue.shift();
  assert.ok(item, 'unexpected fetch');
  if (item.gate) await item.gate;
  if (item.kind === 'fetch-error') throw new Error('offline');
  if (item.kind === 'http-error') return {{ok: false, status: 503}};
  if (item.kind === 'json-error') return {{
    ok: true, status: 200, json: async () => {{ throw new Error('bad json'); }}
  }};
  return {{ok: true, status: 200, json: async () => structuredClone(item.value)}};
}};
eval({json.dumps(test_js)});
const refreshAt = async (timestamp, item) => {{
  nowMs = timestamp;
  fetchQueue.push(item);
  await globalThis.__workbenchRefresh();
}};
const assertUnavailable = () => {{
  assert.equal(document.body.dataset.workbenchState, 'UNKNOWN');
  assert.equal(elements.connection.hidden, false);
  assert.equal(elements['runtime-status'].dataset.state, 'unknown');
  assert.equal(elements['runtime-state-label'].textContent, 'Runtime 状态未知');
  assert.equal(elements.runtime.textContent, 'runtime —');
  assert.match(elements['queue-body'].innerHTML, /旧业务数据已隐藏/);
  assert.doesNotMatch(elements['queue-body'].innerHTML, /BTC-TEST-65000-P|STALE SENTINEL/);
  assert.doesNotMatch(elements['detail-content'].innerHTML, /64\\.8|STALE SENTINEL/);
}};
const markStalePanels = () => {{
  elements['queue-body'].innerHTML = 'STALE SENTINEL';
  elements['detail-content'].innerHTML = 'STALE SENTINEL';
}};

(async () => {{
  await refreshAt(1000, {{kind: 'ok', value: {json.dumps(document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.equal(elements.connection.hidden, true);
  assert.equal(elements['runtime-status'].dataset.state, 'healthy');
  assert.equal(elements['runtime-state-label'].textContent, 'Runtime 正常运行');
  assert.match(elements['runtime-blocker'].textContent, /系统阻塞/);
  assert.match(elements['channel-list'].innerHTML, /INVERSE_BTC_SHORT_VOL_V2/);
  assert.match(elements['channel-list'].innerHTML, /INVERSE_ETH_LONG_GAMMA/);
  assert.match(elements['queue-body'].innerHTML, /BTC-TEST-65000-P/);
  assert.match(elements['queue-body'].innerHTML, /继续观察/);
  assert.match(elements['detail-content'].innerHTML, /64\\.8/);
  assert.match(elements['detail-content'].innerHTML, /不是到期 BTC 负债/);

  elements['queue-body'].innerHTML = 'UNCHANGED PUBLICATION SENTINEL';
  await refreshAt(1500, {{kind: 'ok', value: {json.dumps(document)}}});
  assert.equal(elements['queue-body'].innerHTML, 'UNCHANGED PUBLICATION SENTINEL');

  markStalePanels();
  await refreshAt(2000, {{kind: 'fetch-error'}});
  assertUnavailable();

  await refreshAt(3000, {{kind: 'ok', value: {json.dumps(document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.match(elements['queue-body'].innerHTML, /BTC-TEST-65000-P/);

  markStalePanels();
  await refreshAt(4000, {{kind: 'http-error'}});
  assertUnavailable();
  markStalePanels();
  await refreshAt(5000, {{kind: 'json-error'}});
  assertUnavailable();
  markStalePanels();
  await refreshAt(6000, {{kind: 'ok', value: {json.dumps(malformed_document)}}});
  assertUnavailable();

  await refreshAt(7000, {{kind: 'ok', value: {json.dumps(restarted_document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.equal(elements.connection.hidden, true);
  assert.match(elements.runtime.textContent, /…f{{6}}$/);
  assert.match(elements['queue-body'].innerHTML, /BTC-TEST-65000-P/);
  assert.doesNotMatch(elements['queue-body'].innerHTML, /旧业务数据已隐藏|STALE SENTINEL/);

  await refreshAt(7100, {{kind: 'ok', value: {json.dumps(retired_document)}}});
  assertUnavailable();
  await refreshAt(7200, {{kind: 'ok', value: {json.dumps(restarted_document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');

  let releaseOldResponse;
  const oldResponseGate = new Promise(resolve => {{ releaseOldResponse = resolve; }});
  fetchQueue.push({{kind: 'ok', value: {json.dumps(restarted_newer_document)}, gate: oldResponseGate}});
  nowMs = 7300;
  const oldRefresh = globalThis.__workbenchRefresh();
  await Promise.resolve();
  // Interval ticks are serialized while a slow request is pending; they cannot starve its response.
  nowMs = 7400;
  await globalThis.__workbenchRefresh();
  await globalThis.__workbenchRefresh();
  assert.equal(fetchQueue.length, 0);
  releaseOldResponse();
  await oldRefresh;
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.match(elements['queue-body'].innerHTML, /BTC-NEWER-65000-P/);
  assert.doesNotMatch(elements['queue-body'].innerHTML, /旧业务数据已隐藏/);

  await refreshAt(7500, {{kind: 'ok', value: {json.dumps(restarted_document)}}});
  assertUnavailable();
  await refreshAt(7600, {{kind: 'ok', value: {json.dumps(restarted_newer_document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.match(elements['queue-body'].innerHTML, /BTC-NEWER-65000-P/);
}})().catch(error => {{
  console.error(error.stack || error);
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node"],
        check=False,
        capture_output=True,
        input=harness,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_service_status_rejects_false_ready_or_stale_semantics() -> None:
    with pytest.raises(ValueError, match="ready"):
        ServiceStatus(
            ServicePhase.RUNNING,
            DataState.UNKNOWN,
            True,
            True,
            False,
            "BAD",
            1,
        )
    with pytest.raises(ValueError, match="stale"):
        ServiceStatus(
            ServicePhase.RUNNING,
            DataState.STALE,
            True,
            False,
            False,
            "BAD",
            1,
        )
