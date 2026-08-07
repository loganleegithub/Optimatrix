from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

from conftest import encode_policy, policy_document
from market_monitor.deribit import PLATFORM_CHANNELS
from options_domain import OptionType
from radar_runtime.deribit_public import (
    InboundEnvelope,
    SendControlEvent,
    SendControlKind,
)
from radar_runtime.runtime import PendingRpc, RadarReducer, RpcPurpose
from short_vol_radar.black import black_price
from short_vol_radar.detector import DetectorState
from short_vol_radar.evidence import RadarEventSink
from short_vol_radar.policy import load_policy_bytes

_next_application_seq = 1


def next_application_seq() -> int:
    global _next_application_seq
    value = _next_application_seq
    _next_application_seq += 1
    return value


def envelope(
    message: dict[str, object],
    *,
    seq: int,
    received_ms: int,
) -> InboundEnvelope:
    return InboundEnvelope(
        {"jsonrpc": "2.0", **message},
        session_epoch=1,
        ingress_seq=next_application_seq(),
        received_monotonic_ms=received_ms,
    )


def response(
    reducer: RadarReducer,
    command: PendingRpc,
    result: object,
    *,
    seq: int,
    received_ms: int,
) -> InboundEnvelope:
    reducer.reduce(
        InboundEnvelope(
            {},
            session_epoch=command.session_epoch,
            ingress_seq=next_application_seq(),
            received_monotonic_ms=command.origin_boundary.received_monotonic_ms,
            control_event=SendControlEvent(
                kind=SendControlKind.SEND_COMPLETED,
                request_id=command.request_id,
                boundary_monotonic_ms=command.origin_boundary.received_monotonic_ms,
            ),
        ),
        processed_monotonic_ms=command.origin_boundary.received_monotonic_ms,
    )
    return envelope(
        {"id": command.request_id, "result": result},
        seq=seq,
        received_ms=received_ms,
    )


def only(commands: tuple[PendingRpc, ...], purpose: RpcPurpose) -> PendingRpc:
    selected = tuple(command for command in commands if command.purpose is purpose)
    assert len(selected) == 1
    return selected[0]


def exact_channels(command: PendingRpc) -> list[str]:
    value = command.params.get("channels")
    assert isinstance(value, list)
    assert all(isinstance(channel, str) for channel in value)
    return value


def option_payload(name: str, expiry_ms: int, strike: str) -> dict[str, object]:
    return {
        "instrument_name": name,
        "kind": "option",
        "base_currency": "BTC",
        "quote_currency": "USDC",
        "settlement_currency": "USDC",
        "counter_currency": "USDC",
        "price_index": "btc_usdc",
        "instrument_type": "linear",
        "is_active": True,
        "state": "open",
        "option_type": "call",
        "expiration_timestamp": expiry_ms,
        "strike": strike,
        "contract_size": 1,
        "min_trade_amount": 0.1,
        "qty_tick_size": 0.1,
        "tick_size": 0.00000001,
        "tick_size_steps": [],
    }


def run_nonempty_scenario(
    tmp_path: Path,
) -> tuple[object, ...]:
    global _next_application_seq
    _next_application_seq = 1
    tmp_path.mkdir(parents=True, exist_ok=True)
    document = policy_document(
        activation_count=1,
        clear_count=2,
        separation_ms=0,
    )
    limits = document["runtime_limits"]
    assert isinstance(limits, dict)
    limits["clock_refresh_interval_ms"] = 300_000
    limits["clock_stale_deadline_ms"] = 600_000
    exact, digest = encode_policy(document)
    policy = load_policy_bytes(exact, digest)
    sink = RadarEventSink(
        code_identity="a" * 40,
        runtime_identity="runtime",
        policy_identity=digest,
    )
    reducer = RadarReducer(
        policy=policy,
        code_identity="a" * 40,
        event_sink=sink,
        runtime_identity="runtime",
    )
    short_name = "BTC_USDC-TEST-10001-C"
    long_name = "BTC_USDC-TEST-110-C"
    expiry_ms = 4_620_000
    summary = {
        "id": "COMBO",
        "state": "active",
        "legs": [
            {"instrument_name": short_name, "amount": -1},
            {"instrument_name": long_name, "amount": 1},
        ],
    }

    heartbeat = only(
        reducer.begin_session(session_epoch=1, monotonic_ms=1_000),
        RpcPurpose.SET_HEARTBEAT,
    )
    subscribe = only(
        reducer.reduce(
            response(reducer, heartbeat, "ok", seq=1, received_ms=1_001),
            processed_monotonic_ms=1_001,
        ),
        RpcPurpose.SUBSCRIBE_CHANNELS,
    )
    commands = reducer.reduce(
        response(
            reducer,
            subscribe,
            exact_channels(subscribe),
            seq=2,
            received_ms=1_002,
        ),
        processed_monotonic_ms=1_002,
    )
    status = only(commands, RpcPurpose.PLATFORM_STATUS)
    bootstrap_commands = reducer.reduce(
        response(
            reducer,
            status,
            {"locked": False, "locked_indices": [], "locked_currencies": []},
            seq=3,
            received_ms=1_003,
        ),
        processed_monotonic_ms=1_003,
    )
    clock = only(bootstrap_commands, RpcPurpose.CLOCK_BOOTSTRAP)
    index_history = only(bootstrap_commands, RpcPurpose.INDEX_HISTORY)
    option_catalog = only(bootstrap_commands, RpcPurpose.OPTION_CATALOG)
    combo_catalog = only(bootstrap_commands, RpcPurpose.COMBO_CATALOG)
    index_subscribe = only(
        reducer.reduce(
            response(reducer, clock, 600_000, seq=4, received_ms=1_004),
            processed_monotonic_ms=1_004,
        ),
        RpcPurpose.SUBSCRIBE_CHANNELS,
    )
    reducer.reduce(
        response(
            reducer,
            index_history,
            [[0, 100], [300_000, 100]],
            seq=5,
            received_ms=1_004,
        ),
        processed_monotonic_ms=1_004,
    )
    reducer.reduce(
        response(
            reducer,
            index_subscribe,
            exact_channels(index_subscribe),
            seq=5,
            received_ms=1_005,
        ),
        processed_monotonic_ms=1_005,
    )
    membership_commands = reducer.reduce(
        response(
            reducer,
            option_catalog,
            [
                option_payload(short_name, expiry_ms, "100.01"),
                option_payload(long_name, expiry_ms, "110"),
            ],
            seq=6,
            received_ms=1_006,
        ),
        processed_monotonic_ms=1_006,
    )
    option_subscribe = only(membership_commands, RpcPurpose.SUBSCRIBE_CHANNELS)
    combo_metadata = only(
        reducer.reduce(
            response(reducer, combo_catalog, [summary], seq=7, received_ms=1_007),
            processed_monotonic_ms=1_007,
        ),
        RpcPurpose.COMBO_METADATA,
    )
    reducer.reduce(
        response(
            reducer,
            combo_metadata,
            {
                "instrument_name": "COMBO",
                "kind": "option_combo",
                "base_currency": "BTC",
                "quote_currency": "USDC",
                "settlement_currency": "USDC",
                "counter_currency": "USDC",
                "instrument_type": "linear",
                "is_active": True,
                "state": "open",
                "contract_size": 1,
                "min_trade_amount": 0.1,
                "qty_tick_size": 0.1,
            },
            seq=8,
            received_ms=1_008,
        ),
        processed_monotonic_ms=1_008,
    )
    reducer.reduce(
        response(
            reducer,
            option_subscribe,
            exact_channels(option_subscribe),
            seq=9,
            received_ms=1_009,
        ),
        processed_monotonic_ms=1_009,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": PLATFORM_CHANNELS[0],
                    "data": {"maintenance": False},
                },
            },
            seq=10,
            received_ms=1_010,
        ),
        processed_monotonic_ms=1_010,
    )
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": PLATFORM_CHANNELS[1],
                    "data": {"allow_unauthenticated_public_requests": True},
                },
            },
            seq=11,
            received_ms=1_011,
        ),
        processed_monotonic_ms=1_011,
    )

    seq = 11
    for source_ms in range(660_000, 1_020_001, 60_000):
        seq += 1
        received_ms = source_ms - 598_500
        reducer.reduce(
            envelope(
                {
                    "method": "subscription",
                    "params": {
                        "channel": "deribit_price_index.btc_usdc",
                        "data": {
                            "timestamp": source_ms,
                            "price": 100,
                            "index_name": "btc_usdc",
                        },
                    },
                },
                seq=seq,
                received_ms=received_ms,
            ),
            processed_monotonic_ms=received_ms,
        )
    assert reducer.platform.usable, (
        reducer.platform.status_usable,
        reducer.platform.lock_snapshot,
        reducer.platform.maintenance_guard,
        reducer.platform.public_method_guard,
        reducer.platform.post_status_probe,
        reducer.platform.fresh_index_coverage,
        reducer.channel_state("deribit_price_index.btc_usdc"),
    )

    final_ms = 422_000
    seq += 1
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": f"book.{long_name}.agg2",
                    "data": {
                        "type": "snapshot",
                        "timestamp": 1_020_100,
                        "instrument_name": long_name,
                        "change_id": 1,
                        "bids": [],
                        "asks": [],
                    },
                },
            },
            seq=seq,
            received_ms=final_ms,
        ),
        processed_monotonic_ms=final_ms,
    )
    seq += 1
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": f"ticker.{short_name}.agg2",
                    "data": {
                        "instrument_name": short_name,
                        "timestamp": 1_020_101,
                        "underlying_price": 100,
                        "underlying_index": "index_price",
                    },
                },
            },
            seq=seq,
            received_ms=final_ms + 1,
        ),
        processed_monotonic_ms=final_ms + 1,
    )
    total_volatility = 0.5 * math.sqrt(60 / (365 * 24 * 60))
    first_price = Decimal(str(black_price(100, 100.01, total_volatility, OptionType.CALL)))
    seq += 1
    reducer.reduce(
        envelope(
            {
                "method": "subscription",
                "params": {
                    "channel": f"book.{short_name}.agg2",
                    "data": {
                        "type": "snapshot",
                        "timestamp": 1_020_102,
                        "instrument_name": short_name,
                        "change_id": 1,
                        "bids": [["new", first_price, "0.1"]],
                        "asks": [["new", first_price + Decimal("0.00000002"), "0.1"]],
                    },
                },
            },
            seq=seq,
            received_ms=final_ms + 2,
        ),
        processed_monotonic_ms=final_ms + 2,
    )
    result = reducer.results[short_name]
    assert result.known_evaluation
    assert result.full_formula_evaluation
    assert result.detector_state is DetectorState.ANOMALY_ACTIVE
    scope = next(iter(reducer._scope_counts.values()))
    assert scope.complete_aggregate_with_full_formula_evaluation_count == 1
    assert reducer.combo_catalog.complete
    assert tuple(reducer.combos) == ("COMBO",)
    terminal_summary = reducer.clean_stop(final_ms + 100)
    assert terminal_summary["object_kind"] == "RADAR_RUN_SUMMARY"
    assert sink.summary == terminal_summary
    return (
        tuple(
            sorted(
                (
                    name,
                    value.detector_state.value,
                    value.reason,
                    value.known_evaluation,
                    value.full_formula_evaluation,
                    value.band_id,
                )
                for name, value in reducer.results.items()
            )
        ),
        tuple(
            sorted(
                (
                    name,
                    tracker.detector_state.value,
                    tracker.episode_id,
                )
                for name, tracker in reducer.trackers.items()
            )
        ),
        reducer._coverage._current_state.value,
        tuple(
            sorted(
                (
                    request.request_id,
                    request.purpose.value,
                    request.method,
                    request.scope,
                    request.generation,
                )
                for request in reducer.pending_rpcs.values()
            )
        ),
        tuple(sorted((value["episode_identity"], value["causal_seq"]) for value in sink.anomalies)),
        tuple(
            sorted(
                (value["episode_identity"], value["combo_instrument_name"])
                for value in sink.atomics
            )
        ),
        sink.summary,
        tuple(tmp_path.iterdir()),
    )


def test_nonempty_bootstrap_reaches_real_formula_and_complete_joint_aggregate(
    tmp_path: Path,
) -> None:
    run_nonempty_scenario(tmp_path)


def test_deterministic_interleaving_repeats_exact_business_and_durable_edges(
    tmp_path: Path,
) -> None:
    first = run_nonempty_scenario(tmp_path / "first")
    second = run_nonempty_scenario(tmp_path / "second")

    assert second == first
