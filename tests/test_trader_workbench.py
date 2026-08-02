from __future__ import annotations

import http.client
import inspect
import json
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import radar_runtime.workbench as workbench_module
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
    WorkbenchRequestHandler,
    initial_workbench_document,
    panel_state,
    zero_anomaly_claim,
    zero_candidate_claim,
)
from short_vol_radar.atomic import PublicAtomicQuoteState
from short_vol_radar.detector import DetectorState
from short_vol_underwriting.constants import (
    OUTCOME_CONTRACT_DIGEST,
    POSITION_POLICY_IDENTITY,
    RADAR_POLICY_IDENTITY,
    UNDERWRITING_POLICY_IDENTITY,
    UNDERWRITING_POSITION_CONTRACT_DIGEST,
)
from short_vol_underwriting.evidence import RuntimeBindings
from short_vol_underwriting.policy import PolicyChain, load_policy_chain

ROOT = Path(__file__).resolve().parents[1]


def _policies() -> PolicyChain:
    return load_policy_chain(
        radar_path=ROOT / "policies/short-vol-fixed-public-shadow-radar.json",
        underwriting_path=ROOT / "policies/short-vol-fixed-public-shadow-underwriting.json",
        position_path=ROOT / "policies/short-vol-fixed-public-shadow-position.json",
        radar_identity=RADAR_POLICY_IDENTITY,
        underwriting_identity=UNDERWRITING_POLICY_IDENTITY,
        position_identity=POSITION_POLICY_IDENTITY,
    )


def _bindings() -> RuntimeBindings:
    return RuntimeBindings(
        code_identity="a" * 40,
        runtime_identity="sha256:" + "b" * 64,
        radar_policy_identity="sha256:" + "c" * 64,
        underwriting_policy_identity="sha256:" + "d" * 64,
        position_policy_identity="sha256:" + "e" * 64,
        underwriting_position_contract_digest=UNDERWRITING_POSITION_CONTRACT_DIGEST,
        outcome_contract_digest=OUTCOME_CONTRACT_DIGEST,
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
    assert value["service"]["data_state"] == "UNKNOWN"
    assert value["schema_version"] == 2
    assert "THIS_ARTIFACT_DOES_NOT_GRANT_LIVE_OR_DEPLOYMENT_AUTHORITY" in value["non_claims"]
    assert "NO_LIVE_OR_DEPLOYMENT_AUTHORITY" not in value["non_claims"]


def test_shadow_projection_derives_exact_entry_vwap_only_from_persisted_atomic_levels() -> None:
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
                "payload": {
                    "candidate_identity": candidate_identity,
                    "full_quantity_btc": "0.1",
                    "entry_consumed_levels": [
                        {"price_usdc_per_btc": "100", "amount_btc": "0.04"},
                        {"price_usdc_per_btc": "110", "amount_btc": "0.06"},
                    ],
                    "gross_entry_credit_usdc": "10.6",
                },
            }
        ],
    }

    (row,) = workbench_module._shadow_rows(kinds, _policies())

    assert row["simulated_entry_price_usdc_per_btc"] == "106"
    assert (
        row["simulated_entry_price_availability"]
        == "AVAILABLE_FROM_PERSISTED_ATOMIC_CONSUMED_LEVELS"
    )
    assert row["simulated_entry_price_basis"] == ("PERSISTED_ATOMIC_COMBO_CONSUMED_LEVELS_VWAP")
    assert row["simulation_label"] == SIMULATION_LABEL


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
    assert row["short_strike_usdc_per_btc"] == "100000"
    assert row["target_quantity_btc"] == "0.1"


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
                "payload": {"canonical_leg_identities": []},
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

    assert row["remaining_premium_usdc"] == "25"
    assert row["remaining_premium_availability"] == (
        "AVAILABLE_FROM_PERSISTED_ATOMIC_CLOSE_ECONOMICS"
    )
    assert row["remaining_premium_basis"] == ("MAX_ZERO_NEGATIVE_GROSS_CLOSE_CASHFLOW_USDC")
    assert row["current_atomic_close_debit_usdc"] == "26"
    assert row["projected_shadow_pnl_usdc"] == "8"


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
    assert "<button" not in HTML.lower()
    assert "<form" not in HTML.lower()
    assert "/private" not in combined
    assert "/policy" not in JS.lower()
    assert "set_policy" not in JS.lower()
    assert "submit_order" not in JS.lower()
    assert "escapeHtml" in JS
    assert "&lt;" in JS and "&gt;" in JS and "&amp;" in JS
    assert "safeText(rendered)" in JS
    assert 'class="value ${' not in JS
    assert 'id="connection"' in HTML
    assert 'role="alert"' in HTML
    assert "function renderUnavailable" in JS
    assert "businessPanelIds" in JS
    assert "lastSuccessfulFetchAtMs" in JS
    assert "lastPublicationRuntimeIdentity" in JS
    assert "lastPublicationChangeAtMs" in JS
    assert "documentValue.publication_sequence" in JS
    assert "if (!response.ok) throw" in JS
    assert "renderUnavailable();" in JS
    assert "SUPPORTED_SCHEMA_VERSION = 2" in JS
    assert ".table-scroll" in CSS
    assert "overflow-x:auto" in CSS
    assert 'class="system-details"' in JS


def test_browser_formats_business_states_and_orders_rows_without_recomputing() -> None:
    test_js = JS.replace(
        "refresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchTest = { radarCellValue, underwritingCellValue, "
        "shadowCellValue, positionCellValue, outcomeCellValue, "
        "orderedRadarRows, orderedUnderwritingRows, filterRows };",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
globalThis.document = {{getElementById() {{ return {{}}; }}}};
globalThis.setInterval = () => 1;
eval({json.dumps(test_js)});
const api = globalThis.__workbenchTest;

assert.equal(api.radarCellValue({{
  detector_state: 'UNKNOWN', known_evaluation: false
}}, 'expiration_timestamp_ms', null), 'UNKNOWN');
assert.equal(api.radarCellValue({{
  detector_state: 'UNKNOWN', known_evaluation: false
}}, 'executable_iv_interval', null), 'UNKNOWN');
assert.equal(api.radarCellValue({{
  detector_state: 'NO_ANOMALY', known_evaluation: true
}}, 'executable_iv_interval', null), 'N/A');
assert.equal(api.radarCellValue({{
  detector_state: 'ANOMALY_ACTIVE', known_evaluation: true
}}, 'executable_iv_interval', null), 'UNKNOWN');
assert.equal(api.radarCellValue({{
  detector_state: 'NO_ANOMALY', known_evaluation: true
}}, 'active_episode_identity', null), 'N/A');
assert.equal(api.radarCellValue({{
  detector_state: 'UNKNOWN', known_evaluation: false
}}, 'detector_reason', 'QUEUE_LAG_CURRENTNESS'),
  '处理队列延迟, 行情时效性不可确认');

assert.equal(api.underwritingCellValue({{
  availability: 'NOT_EVALUATED', action: null
}}, 'action', null), 'N/A');
assert.equal(api.underwritingCellValue({{
  availability: 'NOT_EVALUATED', gross_entry_credit_usdc: null
}}, 'gross_entry_credit_usdc', null), 'N/A');
assert.equal(api.underwritingCellValue({{
  availability: 'UNKNOWN', action: null
}}, 'availability', 'UNKNOWN'), 'UNKNOWN');
assert.equal(api.underwritingCellValue({{
  availability: 'UNKNOWN', action: null,
  unknown_reasons: ['COMBO_QUOTE_RECEIPT_UNKNOWN']
}}, 'decision_reason', 'UNDERWRITING_UNKNOWN:COMBO_QUOTE_RECEIPT_UNKNOWN'),
  '组合报价回执不可确认');
assert.equal(api.underwritingCellValue({{
  availability: 'NOT_EVALUATED', action: null,
  unknown_reasons: ['RADAR_EPISODE_NOT_ACTIVE']
}}, 'decision_reason', 'UNDERWRITING_NOT_EVALUATED:RADAR_EPISODE_NOT_ACTIVE'),
  '当前无活跃 Radar 异常, 承保尚未评估');
assert.equal(api.underwritingCellValue({{
  availability: 'NOT_EVALUATED', action: null,
  unknown_reasons: ['NO_ACTIVE_COMBO']
}}, 'decision_reason', 'UNDERWRITING_NOT_EVALUATED:NO_ACTIVE_COMBO'),
  '无活跃组合可供承保评估');
assert.equal(api.underwritingCellValue({{
  availability: 'NOT_EVALUATED', action: null, unknown_reasons: []
}}, 'decision_reason', 'UNDERWRITING_NOT_EVALUATED:NO_ADDITIONAL_REASON_PERSISTED'),
  '已知前置条件未满足, 承保未评估');
assert.equal(api.outcomeCellValue({{
  state: 'MATURED'
}}, 'actual_pnl_usdc', null), 'N/A — public Shadow 无订单、成交或实际持仓');
assert.equal(api.shadowCellValue({{
  shadow_entry_identity: null
}}, 'simulated_entry_price_usdc_per_btc', null), 'N/A');
assert.equal(api.positionCellValue({{}}, 'hard_close_countdown_interval_ms', {{
  lower_ms: 60000, upper_ms: 120000
}}), '1.0 分钟 - 2.0 分钟');

const radar = api.orderedRadarRows([
  {{instrument_name:'N', detector_state:'NO_ANOMALY', expiration_timestamp_ms:2, strike_usdc_per_btc:'2'}},
  {{instrument_name:'U', detector_state:'UNKNOWN', expiration_timestamp_ms:1, strike_usdc_per_btc:'1'}},
  {{instrument_name:'A', detector_state:'ANOMALY_ACTIVE', expiration_timestamp_ms:3, strike_usdc_per_btc:'3'}}
]);
assert.deepEqual(radar.map(row => row.instrument_name), ['A', 'U', 'N']);
assert.deepEqual(api.filterRows(radar, 'detector_state', 'UNKNOWN').map(row => row.instrument_name), ['U']);

const underwriting = api.orderedUnderwritingRows([
  {{radar_scope_or_short_leg_identity:'n', availability:'NOT_EVALUATED'}},
  {{radar_scope_or_short_leg_identity:'u', availability:'UNKNOWN'}},
  {{radar_scope_or_short_leg_identity:'a', availability:'EVALUABLE', action:'ABSTAIN'}},
  {{radar_scope_or_short_leg_identity:'w', availability:'EVALUABLE', action:'WATCH'}},
  {{radar_scope_or_short_leg_identity:'e', availability:'EVALUABLE', action:'CANDIDATE'}}
]);
assert.deepEqual(
  underwriting.map(row => row.radar_scope_or_short_leg_identity),
  ['e', 'w', 'a', 'u', 'n']
);
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_browser_keeps_formatted_exact_facts_in_collapsed_details() -> None:
    for exact_field in (
        "executable IV exact",
        "baseline volatility exact",
        "richness exact",
        "short strike exact",
        "long strike exact",
        "target quantity exact",
        "decision reason enum",
        "evaluation fact boundary",
        "public-quote PnL exact",
        "actual PnL exact",
    ):
        assert exact_field in JS


def test_browser_executes_fail_closed_and_recovery_paths() -> None:
    document = initial_workbench_document(_bindings())
    document["publication_sequence"] = 1
    document["published_fact_boundary"] = {
        "causal_seq": 42,
        "received_monotonic_ms": 1_234,
    }
    restarted_document = json.loads(json.dumps(document))
    restarted_document["runtime_identity"] = "sha256:" + "f" * 64
    malformed_document = json.loads(json.dumps(document))
    malformed_document["runtime_identity"] = "sha256:" + "9" * 64
    malformed_document["publication_sequence"] = 9
    malformed_document["radar"] = None

    test_js = JS.replace(
        "refresh();\nsetInterval(refresh, 2000);",
        "globalThis.__workbenchRefresh = refresh;",
    )
    assert test_js != JS
    harness = f"""
const assert = require('node:assert/strict');
const panelIds = ['zero', 'radar', 'underwriting', 'shadow', 'positions', 'outcomes'];
const elementIds = ['connection', 'runtime', 'system', ...panelIds];
const elements = Object.fromEntries(elementIds.map(id => [id, {{
  hidden: id === 'connection', textContent: '', innerHTML: ''
}}]));
globalThis.document = {{
  body: {{dataset: {{}}}},
  getElementById(id) {{
    assert.ok(elements[id], `unexpected element ${{id}}`);
    return elements[id];
  }}
}};
globalThis.setInterval = () => 1;
let nowMs = 0;
Date.now = () => nowMs;
const fetchQueue = [];
globalThis.fetch = async () => {{
  const item = fetchQueue.shift();
  assert.ok(item, 'unexpected fetch');
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
const systemHas = (label, value) => elements.system.innerHTML.includes(
  `<div class="label">${{label}}</div><div class="value">${{value}}</div>`
);
const assertUnavailable = (successfulFetchAge, publicationAge) => {{
  assert.equal(document.body.dataset.workbenchState, 'UNKNOWN');
  assert.equal(elements.connection.hidden, false);
  assert.equal(elements.runtime.textContent, 'runtime UNKNOWN');
  assert.ok(systemHas('最近成功获取 age ms', successfulFetchAge));
  assert.ok(systemHas('最后 publication sequence', 1));
  assert.ok(systemHas('Publication 未变化 age ms', publicationAge));
  for (const id of panelIds) {{
    assert.match(elements[id].innerHTML, /旧业务数据已隐藏/);
    assert.doesNotMatch(elements[id].innerHTML, /STALE SENTINEL/);
  }}
}};
const markStalePanels = () => {{
  for (const id of panelIds) elements[id].innerHTML = 'STALE SENTINEL';
}};

(async () => {{
  await refreshAt(1000, {{kind: 'ok', value: {json.dumps(document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.equal(elements.connection.hidden, true);
  assert.ok(systemHas('Runtime identity', {json.dumps(document["runtime_identity"])}));
  assert.match(elements.system.innerHTML, /Published fact boundary/);
  assert.match(elements.system.innerHTML, /causal_seq/);
  assert.match(elements.system.innerHTML, /received_monotonic_ms/);
  assert.ok(systemHas('最近成功获取 age', '0 ms'));
  assert.ok(systemHas('Publication 未变化 age', '0 ms'));

  markStalePanels();
  await refreshAt(2000, {{kind: 'fetch-error'}});
  assertUnavailable(1000, 1000);

  await refreshAt(3000, {{kind: 'ok', value: {json.dumps(document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.ok(systemHas('最近成功获取 age', '0 ms'));
  assert.ok(systemHas('Publication 未变化 age', '2.0 秒'));

  markStalePanels();
  await refreshAt(4000, {{kind: 'http-error'}});
  assertUnavailable(1000, 3000);
  markStalePanels();
  await refreshAt(5000, {{kind: 'json-error'}});
  assertUnavailable(2000, 4000);
  markStalePanels();
  await refreshAt(6000, {{kind: 'ok', value: {json.dumps(malformed_document)}}});
  assertUnavailable(3000, 5000);
  assert.ok(!systemHas('最后 publication sequence', 9));

  await refreshAt(7000, {{kind: 'ok', value: {json.dumps(restarted_document)}}});
  assert.equal(document.body.dataset.workbenchState, 'CURRENT_FETCH');
  assert.equal(elements.connection.hidden, true);
  assert.match(elements.runtime.textContent, /…f{{6}}$/);
  assert.ok(systemHas('最近成功获取 age', '0 ms'));
  assert.ok(systemHas('Publication 未变化 age', '0 ms'));
  for (const id of panelIds) {{
    assert.doesNotMatch(elements[id].innerHTML, /旧业务数据已隐藏|STALE SENTINEL/);
  }}
}})().catch(error => {{
  console.error(error.stack || error);
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        check=False,
        capture_output=True,
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
